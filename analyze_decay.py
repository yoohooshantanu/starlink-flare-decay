"""
Phase 5 - Statistical Analysis.

Four core questions:
  Q1 - Does decay rate increase during flare windows?  (paired t-test + Wilcoxon)
  Q2 - Does effect scale with flare class?             (Kruskal-Wallis across groups)
  Q3 - Is the CME effect larger than the direct flare? (paired comparison of windows)
  Q4 - How long does recovery take?                    (days-to-recovery distribution)
  Control group validation.

Output → data/analysis_results.json
"""
import json
from collections import defaultdict

import numpy as np
from scipy import stats as sp_stats
from datetime import datetime, timedelta
import pandas as pd
import statsmodels.api as sm

import config


# ── Helpers ──────────────────────────────────────────────────────────────────

def cohens_d(group1, group2):
    """Compute Cohen's d effect size."""
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return None
    var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0
    return float((np.mean(group1) - np.mean(group2)) / pooled_std)


def safe_test(func, *args, min_n=5, **kwargs):
    """Run a scipy test safely, returning dict with statistic and p-value."""
    try:
        for a in args:
            if hasattr(a, "__len__") and len(a) < min_n:
                return {"statistic": None, "p_value": None, "note": f"n < {min_n}"}
        result = func(*args, **kwargs)
        return {
            "statistic": round(float(result.statistic), 6),
            "p_value":   round(float(result.pvalue), 8),
        }
    except Exception as e:
        return {"statistic": None, "p_value": None, "error": str(e)}


def classify_flare_group(intensity, letter):
    """Classify a flare into M1-M5, M5-M9, X1-X5, X5+ groups."""
    if letter == "X":
        # intensity is on M-scale (X1=10, X5=50)
        if intensity >= 50:
            return "X5+"
        else:
            return "X1-X5"
    elif letter == "M":
        if intensity >= 5:
            return "M5-M9"
        else:
            return "M1-M5"
    return None


def compute_recovery_days(aligned_records, decay_data_by_sat):
    """
    For each flare event per satellite, estimate how many days
    until the decay rate returns to within 1-sigma of the pre-flare baseline.
    Returns list of {flare_class, flare_group, recovery_days, ...}.
    """
    recovery_results = []

    for a in aligned_records:
        if a["group"] not in ("shell1", "shell2"):
            continue
        if a["pre_rate"]["mean"] is None or a["pre_rate"]["std"] is None:
            continue
        if a["pre_rate"]["n"] < 2:
            continue

        pre_mean = a["pre_rate"]["mean"]
        pre_std  = a["pre_rate"]["std"]
        if pre_std < 0.01:
            pre_std = abs(pre_mean) * 0.1 if abs(pre_mean) > 0.01 else 1.0

        # Threshold: within 1-sigma of pre-flare baseline
        threshold_low  = pre_mean - pre_std
        threshold_high = pre_mean + pre_std

        # Parse flare peak time
        peak_str = a.get("flare_peak", "")
        peak = None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                peak = datetime.strptime(peak_str.rstrip("Z"), fmt)
                break
            except (ValueError, TypeError):
                continue
        if not peak:
            continue

        norad_id = a["norad_id"]
        sat_dates = decay_data_by_sat.get(norad_id, {})

        # Scan days +3 to +30 after flare looking for recovery
        recovery_day = None
        for day_offset in range(3, 31):
            target_date = (peak + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            if target_date in sat_dates:
                day_rates = [r["decay_rate_m_day"] for r in sat_dates[target_date]
                             if not r.get("is_maneuver", False)]
                if day_rates:
                    day_mean = np.mean(day_rates)
                    if threshold_low <= day_mean <= threshold_high:
                        recovery_day = day_offset
                        break

        letter = a.get("class_letter", "M")
        intensity = a.get("numeric_intensity", 1.0)
        flare_group = classify_flare_group(intensity, letter)

        recovery_results.append({
            "norad_id": norad_id,
            "flare_id": a.get("flare_id"),
            "class_letter": letter,
            "flare_group": flare_group,
            "recovery_days": recovery_day,  # None = didn't recover within 30 days
            "recovered": recovery_day is not None,
        })

    return recovery_results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 5 - Statistical Analysis")
    print("=" * 60)

    with open(config.ALIGNED_FILE) as f:
        aligned = json.load(f)
    with open(config.DECAY_FILE) as f:
        decay_data = json.load(f)
    
    # Load space weather indices
    sw_file = config.DATA_DIR / "space_weather.json"
    sw_data = {}
    if sw_file.exists():
        with open(sw_file) as f:
            sw_data = json.load(f)
        print(f"  Loaded {len(sw_data)} space weather records")

    print(f"  Loaded {len(aligned)} aligned records")

    # Index decay data by satellite for recovery computation
    decay_by_sat = defaultdict(lambda: defaultdict(list))
    for d in decay_data:
        decay_by_sat[d["norad_id"]][d["date"]].append(d)

    starlink = [a for a in aligned if a["group"] in ("shell1", "shell2")]
    control  = [a for a in aligned if a["group"] == "control"]

    print(f"  Starlink records: {len(starlink)}")
    print(f"  Control records : {len(control)}")

    results = {"meta": {"total_records": len(aligned),
                        "starlink_records": len(starlink),
                        "control_records": len(control)}}

    # ======================================================================
    # Q1 - Does decay rate increase during flare windows?
    # Paired t-test + Wilcoxon signed-rank test
    # ======================================================================
    print("\n  -- Q1: Pre-flare vs. Flare-window --")

    paired_pre, paired_flare = [], []
    for a in starlink:
        if a["pre_rate"]["mean"] is not None and a["flare_rate"]["mean"] is not None:
            paired_pre.append(abs(a["pre_rate"]["mean"]))
            paired_flare.append(abs(a["flare_rate"]["mean"]))

    ttest = safe_test(sp_stats.ttest_rel, paired_flare, paired_pre, alternative="greater")
    wilcoxon = safe_test(sp_stats.wilcoxon, paired_flare, paired_pre, alternative="greater")
    d1 = cohens_d(paired_flare, paired_pre)

    results["q1_flare_vs_pre"] = {
        "description": "Does decay rate increase during flare windows?",
        "n_pairs": len(paired_pre),
        "pre_rate_mean": round(float(np.mean(paired_pre)), 4) if paired_pre else None,
        "flare_rate_mean": round(float(np.mean(paired_flare)), 4) if paired_flare else None,
        "acceleration_ratio": round(float(np.mean(paired_flare)) / float(np.mean(paired_pre)), 3) if paired_pre and np.mean(paired_pre) > 0 else None,
        "paired_ttest": ttest,
        "wilcoxon": wilcoxon,
        "cohens_d": round(d1, 4) if d1 is not None else None,
    }
    print(f"    n={len(paired_pre)}, t-test p={ttest.get('p_value')}, "
          f"wilcoxon p={wilcoxon.get('p_value')}, d={d1}")

    # ======================================================================
    # Q2 - Does effect scale with flare class?
    # Kruskal-Wallis across M1-M5 / M5-M9 / X1-X5 / X5+
    # ======================================================================
    print("\n  -- Q2: Effect scales with flare class? (Kruskal-Wallis) --")

    group_ratios = defaultdict(list)
    for a in starlink:
        if a["decay_ratio_flare"] is None or a["decay_ratio_flare"] <= 0:
            continue
        letter = a.get("class_letter", "?")
        intensity = a.get("numeric_intensity", 0)
        fg = classify_flare_group(intensity, letter)
        if fg:
            group_ratios[fg].append(a["decay_ratio_flare"])

    ordered_groups = ["M1-M5", "M5-M9", "X1-X5", "X5+"]
    kw_arrays = [np.array(group_ratios[g]) for g in ordered_groups if g in group_ratios]
    kw_labels = [g for g in ordered_groups if g in group_ratios]

    kruskal = safe_test(sp_stats.kruskal, *kw_arrays) if len(kw_arrays) >= 2 else {"statistic": None, "p_value": None}

    q2_groups = {}
    for g in ordered_groups:
        if g in group_ratios:
            data = group_ratios[g]
            q2_groups[g] = {
                "n": len(data),
                "mean_ratio": round(float(np.mean(data)), 4),
                "median_ratio": round(float(np.median(data)), 4),
                "std": round(float(np.std(data)), 4),
            }
            print(f"    {g}: n={len(data)}, median_ratio={np.median(data):.3f}")

    results["q2_flare_class_scaling"] = {
        "description": "Kruskal-Wallis: decay ratio across M1-M5 / M5-M9 / X1-X5 / X5+",
        "kruskal_wallis": kruskal,
        "groups": q2_groups,
    }
    print(f"    Kruskal-Wallis: H={kruskal.get('statistic')}, p={kruskal.get('p_value')}")

    # Post-hoc pairwise Mann-Whitney
    pairwise = {}
    for i, g1 in enumerate(kw_labels):
        for g2 in kw_labels[i+1:]:
            key = f"{g1}_vs_{g2}"
            pw = safe_test(sp_stats.mannwhitneyu, group_ratios[g1], group_ratios[g2])
            pairwise[key] = pw
    results["q2_flare_class_scaling"]["pairwise_mannwhitney"] = pairwise

    # -- Point 2.6: Lag Analysis (Peak Decay Delay) --
    print("\n  -- Q2.6: Lag Analysis (Peak Decay Delay) --")
    lag_days = []
    for a in starlink:
        peak_str = a.get("flare_peak")
        if not peak_str: continue
        try:
            peak_dt = datetime.strptime(peak_str.rstrip("Z")[:10], "%Y-%m-%d")
        except ValueError: continue
            
        norad_id = a["norad_id"]
        sat_dates = decay_by_sat.get(norad_id, {})
        max_rate, max_day_offset = -1, -1
        for day_offset in range(6):
            target_date = (peak_dt + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            if target_date in sat_dates:
                rates = [r["decay_rate_m_day"] for r in sat_dates[target_date] if not r.get("is_maneuver", False)]
                if rates:
                    mean_rate = abs(np.mean(rates))
                    if mean_rate > max_rate:
                        max_rate, max_day_offset = mean_rate, day_offset
        if max_day_offset != -1:
            lag_days.append(max_day_offset)
            
    if lag_days:
        mean_lag = np.mean(lag_days)
        median_lag = np.median(lag_days)
        mode_res = sp_stats.mode(lag_days, keepdims=False)
        mode_lag = float(mode_res.mode) if hasattr(mode_res, 'mode') else float(mode_res[0])
        
        results["lag_analysis"] = {
            "description": "Days between flare peak and maximum observed decay rate",
            "n_events": len(lag_days),
            "mean_lag_days": round(float(mean_lag), 2),
            "median_lag_days": round(float(median_lag), 2),
            "mode_lag_days": round(float(mode_lag), 2)
        }
        print(f"    Mean lag={mean_lag:.2f} days, Median={median_lag:.0f} days, Mode={mode_lag:.0f} days")

    # -- Point 2: Multivariate Regression --
    print("\n  -- Point 2: Multivariate Regression --")
    mv_records = []
    for a in starlink:
        peak_str = a.get("flare_peak", "")[:10]
        if peak_str in sw_data and a["flare_rate"]["mean"] is not None:
            sw = sw_data[peak_str]
            mv_records.append({
                "decay_rate": abs(a["flare_rate"]["mean"]),
                "log_intensity": np.log10(a.get("numeric_intensity", 1.0) + 0.1),
                "kp_sum": sw["kp_sum"],
                "f107": sw["f107"],
                "altitude": a["flare_rate"].get("altitude_km", 550.0),
                "is_shell2": 1 if a["group"] == "shell2" else 0
            })
    if len(mv_records) > 20:
        df = pd.DataFrame(mv_records)
        X = sm.add_constant(df[["log_intensity", "kp_sum", "f107", "altitude", "is_shell2"]])
        model = sm.OLS(df["decay_rate"], X).fit()
        results["multivariate_regression"] = {
            "description": "OLS: DecayRate ~ log(Int) + Kp + F10.7 + Alt + Group",
            "n": len(df),
            "r_squared": round(float(model.rsquared), 4),
            "adj_r_squared": round(float(model.rsquared_adj), 4),
            "params": {k: round(float(v), 4) for k, v in model.params.items()},
            "pvalues": {k: round(float(v), 8) for k, v in model.pvalues.items()},
            "summary_text": str(model.summary())
        }
        print(f"    Multivariate R^2: {model.rsquared:.4f}")

    # ======================================================================
    # Q3 - Is the CME effect larger than the direct flare effect?
    # Compare flare_window vs cme_window decay rates (paired)
    # ======================================================================
    print("\n  -- Q3: CME window vs. Flare window (paired) --")

    paired_flare_w, paired_cme_w = [], []
    for a in starlink:
        if (a["flare_rate"]["mean"] is not None and
                a["cme_rate"]["mean"] is not None and
                a.get("has_cme", False)):
            paired_flare_w.append(abs(a["flare_rate"]["mean"]))
            paired_cme_w.append(abs(a["cme_rate"]["mean"]))

    cme_ttest = safe_test(sp_stats.ttest_rel, paired_cme_w, paired_flare_w, alternative="greater")
    cme_wilcoxon = safe_test(sp_stats.wilcoxon, paired_cme_w, paired_flare_w, alternative="greater")
    d3 = cohens_d(paired_cme_w, paired_flare_w)

    cme_ratio = None
    if paired_flare_w and np.mean(paired_flare_w) > 0:
        cme_ratio = round(float(np.mean(paired_cme_w)) / float(np.mean(paired_flare_w)), 3)

    results["q3_cme_vs_flare"] = {
        "description": "Is CME-window decay larger than flare-window decay? (CME-linked events only)",
        "n_pairs": len(paired_flare_w),
        "flare_window_mean": round(float(np.mean(paired_flare_w)), 4) if paired_flare_w else None,
        "cme_window_mean": round(float(np.mean(paired_cme_w)), 4) if paired_cme_w else None,
        "cme_to_flare_ratio": cme_ratio,
        "paired_ttest": cme_ttest,
        "wilcoxon": cme_wilcoxon,
        "cohens_d": round(d3, 4) if d3 is not None else None,
    }
    print(f"    n={len(paired_flare_w)}, CME/flare ratio={cme_ratio}, "
          f"p={cme_wilcoxon.get('p_value')}, d={d3}")

    # ======================================================================
    # Q4 - How long does recovery take?
    # Days-to-recovery distribution by flare class
    # ======================================================================
    print("\n  -- Q4: Recovery time (days-to-recovery) --")

    recovery_results = compute_recovery_days(aligned, decay_by_sat)

    recovery_by_group = defaultdict(list)
    for r in recovery_results:
        if r["recovered"] and r["flare_group"]:
            recovery_by_group[r["flare_group"]].append(r["recovery_days"])

    q4_data = {}
    for g in ordered_groups:
        data = recovery_by_group.get(g, [])
        if data:
            q4_data[g] = {
                "n_recovered": len(data),
                "n_total": sum(1 for r in recovery_results if r["flare_group"] == g),
                "median_days": round(float(np.median(data)), 1),
                "mean_days": round(float(np.mean(data)), 1),
                "pct_25": round(float(np.percentile(data, 25)), 1),
                "pct_75": round(float(np.percentile(data, 75)), 1),
            }
            pct_recovered = 100.0 * len(data) / q4_data[g]["n_total"] if q4_data[g]["n_total"] > 0 else 0
            print(f"    {g}: median={np.median(data):.0f} days, "
                  f"recovered={len(data)}/{q4_data[g]['n_total']} ({pct_recovered:.0f}%)")

    results["q4_recovery_time"] = {
        "description": "Days until decay rate returns within 1-sigma of pre-flare baseline",
        "groups": q4_data,
    }

    # Save full recovery data for visualization
    with open(config.DATA_DIR / "recovery_days.json", "w") as f:
        json.dump(recovery_results, f, indent=2)

    # ======================================================================
    # Control group validation
    # ======================================================================
    print("\n  -- Control Group Validation --")

    ctrl_pre, ctrl_flare = [], []
    for a in control:
        if a["pre_rate"]["mean"] is not None and a["flare_rate"]["mean"] is not None:
            ctrl_pre.append(abs(a["pre_rate"]["mean"]))
            ctrl_flare.append(abs(a["flare_rate"]["mean"]))

    ctrl_ttest = safe_test(sp_stats.ttest_rel, ctrl_flare, ctrl_pre, alternative="greater")
    ctrl_wilcoxon = safe_test(sp_stats.wilcoxon, ctrl_flare, ctrl_pre, alternative="greater")
    d_ctrl = cohens_d(ctrl_flare, ctrl_pre)

    results["control_validation"] = {
        "description": "Same Q1 test on non-Starlink debris - confirms atmospheric drag signal",
        "n_pairs": len(ctrl_pre),
        "ctrl_pre_mean": round(float(np.mean(ctrl_pre)), 4) if ctrl_pre else None,
        "ctrl_flare_mean": round(float(np.mean(ctrl_flare)), 4) if ctrl_flare else None,
        "paired_ttest": ctrl_ttest,
        "wilcoxon": ctrl_wilcoxon,
        "cohens_d": round(d_ctrl, 4) if d_ctrl is not None else None,
    }
    print(f"    n={len(ctrl_pre)}, p={ctrl_wilcoxon.get('p_value')}, d={d_ctrl}")

    # ======================================================================
    # Summary by flare class (for report table)
    # ======================================================================
    class_summary = defaultdict(list)
    for a in starlink:
        if a["decay_ratio_flare"] is not None and a.get("class_letter") in ("M", "X"):
            class_summary[a["class_letter"]].append(a["decay_ratio_flare"])

    results["class_summary"] = {}
    for cl in sorted(class_summary.keys()):
        data = class_summary[cl]
        results["class_summary"][cl] = {
            "n": len(data),
            "mean_decay_ratio": round(float(np.mean(data)), 4),
            "median_decay_ratio": round(float(np.median(data)), 4),
            "std": round(float(np.std(data)), 4),
        }

    # -- Point 9: Sensitivity Analysis (Threshold Robustness) --
    print("\n  -- Point 9: Sensitivity Analysis (Threshold Robustness) --")
    thresholds = [100, 250, 500, 1000, 2000]
    sensitivity_results = {}
    for t in thresholds:
        filtered_starlink = []
        for d in decay_data:
            if d["group"] in ("shell1", "shell2") and d["decay_rate_m_day"] < t:
                filtered_starlink.append(abs(d["decay_rate_m_day"]))
        if filtered_starlink:
            sensitivity_results[str(t)] = {
                "n_points": len(filtered_starlink),
                "mean_decay": round(float(np.mean(filtered_starlink)), 2),
                "median_decay": round(float(np.median(filtered_starlink)), 2)
            }
            print(f"    Threshold {t:4} m/day: n={len(filtered_starlink):6}, mean={np.mean(filtered_starlink):.2f}")
    results["sensitivity_analysis"] = sensitivity_results

    # Save
    with open(config.ANALYSIS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved to {config.ANALYSIS_FILE}")


if __name__ == "__main__":
    main()
