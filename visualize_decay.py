"""
Phase 6 — Generate Publication-Quality Charts.

Plot 1 — Bar chart of M/X flare events, colored by class, annotated
Plot 2 — Box plots: pre-flare vs flare vs CME window decay rates
Plot 3 — Scatter: flare intensity vs mean decay rate increase
Plot 4 — Case deep dives: day-by-day individual satellite traces
Plot 5 — Histogram of days-to-recovery by flare class

Output → plots/01–05_*.png
"""
import json
from datetime import datetime, timedelta
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from scipy import stats as sp_stats

import config

# ── Theme ────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
FG      = "#c9d1d9"
GRID    = "#21262d"
ACCENT1 = "#58a6ff"
ACCENT2 = "#f78166"
ACCENT3 = "#7ee787"
ACCENT4 = "#d2a8ff"
ACCENT5 = "#ff7b72"

def apply_theme():
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": BG,
        "axes.edgecolor": GRID, "axes.labelcolor": FG,
        "axes.grid": True, "grid.color": GRID, "grid.alpha": 0.3,
        "text.color": FG, "xtick.color": FG, "ytick.color": FG,
        "legend.facecolor": "#161b22", "legend.edgecolor": GRID,
        "legend.labelcolor": FG, "font.family": "sans-serif",
        "font.size": 11, "figure.dpi": 150, "savefig.dpi": 200,
        "savefig.facecolor": BG, "savefig.bbox": "tight",
    })


def parse_dt(s):
    if not s: return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try: return datetime.strptime(s.rstrip("Z"), fmt)
        except ValueError: continue
    return None


# ── Plot 1: Flare Timeline Bar Chart ────────────────────────────────────────
def plot_flare_timeline(flares):
    fig, ax = plt.subplots(figsize=(16, 5))
    # Monthly bin counts by class
    m_months, x_months = Counter(), Counter()
    for f in flares:
        dt = parse_dt(f.get("peakTime"))
        if not dt: continue
        key = dt.strftime("%Y-%m")
        if f.get("classLetter") == "X":
            x_months[key] += 1
        else:
            m_months[key] += 1
    all_keys = sorted(set(list(m_months.keys()) + list(x_months.keys())))
    dates = [datetime.strptime(k, "%Y-%m") for k in all_keys]
    m_vals = [m_months.get(k, 0) for k in all_keys]
    x_vals = [x_months.get(k, 0) for k in all_keys]

    ax.bar(dates, m_vals, width=25, color=ACCENT1, alpha=0.7, label="M-class")
    ax.bar(dates, x_vals, width=25, bottom=m_vals, color=ACCENT5, alpha=0.85, label="X-class")

    # Annotate key events
    for edate, elabel, color in [
        ("2022-02-01", "Feb 2022\nStarlink Loss", ACCENT3),
        ("2024-05-01", "May 2024\nGannon G5", ACCENT4),
    ]:
        edt = datetime.strptime(edate, "%Y-%m-%d")
        ax.axvline(edt, color=color, alpha=0.8, linestyle="--", linewidth=1.5)
        ax.annotate(elabel, xy=(edt, ax.get_ylim()[1] * 0.85 if ax.get_ylim()[1] > 0 else 50),
                    fontsize=9, color=color, ha="right", fontweight="bold")

    ax.set_ylabel("Flare Count (monthly)")
    ax.set_title("M & X-Class Solar Flare Activity (2022-2025)",
                 fontsize=14, fontweight="bold", pad=12)
    ax.legend(loc="upper left", framealpha=0.7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    plt.xticks(rotation=45, ha="right")
    plt.savefig(config.PLOT_FILES["flare_timeline"])
    plt.close()
    print("  done 01_flare_timeline.png")


# ── Plot 2: Box Plots ───────────────────────────────────────────────────────
def plot_decay_distribution(aligned):
    fig, ax = plt.subplots(figsize=(10, 7))
    starlink = [a for a in aligned if a["group"] in ("shell1", "shell2")]
    rows = []
    for a in starlink:
        if a["pre_rate"]["mean"] is not None:
            rows.append({"Window": "Pre-flare", "rate": abs(a["pre_rate"]["mean"])})
        if a["flare_rate"]["mean"] is not None:
            rows.append({"Window": "Flare (0-3d)", "rate": abs(a["flare_rate"]["mean"])})
        if a["cme_rate"]["mean"] is not None:
            rows.append({"Window": "CME (1-5d)", "rate": abs(a["cme_rate"]["mean"])})
    if not rows:
        print("  skip 02 — no data"); return
    df = pd.DataFrame(rows)
    # Clip outliers for readability
    p95 = df["rate"].quantile(0.95)
    df["rate"] = df["rate"].clip(upper=p95)

    palette = {"Pre-flare": ACCENT1, "Flare (0-3d)": ACCENT2, "CME (1-5d)": ACCENT5}
    order = ["Pre-flare", "Flare (0-3d)", "CME (1-5d)"]
    sns.boxplot(data=df, x="Window", y="rate", order=order, palette=palette,
                ax=ax, linewidth=0.8, fliersize=1, boxprops=dict(alpha=0.7),
                medianprops=dict(color=ACCENT3, linewidth=2))
    ax.set_ylabel("|Decay Rate| (m/day)")
    ax.set_xlabel("")
    ax.set_title("Decay Rate Distribution by Event Window",
                 fontsize=14, fontweight="bold", pad=12)
    # Add median annotations
    for i, w in enumerate(order):
        subset = df[df["Window"] == w]["rate"]
        med = subset.median()
        ax.annotate(f"med={med:.1f}", xy=(i, med), xytext=(i + 0.25, med),
                    fontsize=9, color=FG, fontweight="bold")
    plt.savefig(config.PLOT_FILES["decay_distribution"])
    plt.close()
    print("  done 02_decay_distribution.png")


# ── Plot 3: Scatter — Intensity vs Decay Increase ───────────────────────────
def plot_decay_vs_flare_class(aligned):
    fig, ax = plt.subplots(figsize=(12, 7))
    starlink = [a for a in aligned if a["group"] in ("shell1", "shell2")]
    # Compute per-flare MEAN decay increase across all sats
    flare_agg = defaultdict(lambda: {"intensities": [], "increases": [], "ed": False})
    for a in starlink:
        if a["pre_rate"]["mean"] is None or a["flare_rate"]["mean"] is None:
            continue
        increase = abs(a["flare_rate"]["mean"]) - abs(a["pre_rate"]["mean"])
        fid = a.get("flare_id", "")
        flare_agg[fid]["intensities"].append(a.get("numeric_intensity", 1))
        flare_agg[fid]["increases"].append(increase)
        flare_agg[fid]["ed"] = a.get("earth_directed", False)

    ed_x, ed_y, ned_x, ned_y = [], [], [], []
    for fid, d in flare_agg.items():
        intensity = np.mean(d["intensities"])
        increase = np.mean(d["increases"])
        if intensity <= 0: continue
        if d["ed"]:
            ed_x.append(intensity); ed_y.append(increase)
        else:
            ned_x.append(intensity); ned_y.append(increase)

    if ned_x:
        ax.scatter(ned_x, ned_y, s=25, c=ACCENT1, alpha=0.5, label="Non-directed", zorder=3)
    if ed_x:
        ax.scatter(ed_x, ed_y, s=35, c=ACCENT5, alpha=0.6, marker="D",
                   label="Earth-directed", zorder=4)
    # Regression
    all_x = np.array(ed_x + ned_x)
    all_y = np.array(ed_y + ned_y)
    if len(all_x) > 10:
        slope, intercept, r, p, se = sp_stats.linregress(np.log10(all_x + 0.1), all_y)
        x_fit = np.linspace(all_x.min(), all_x.max(), 100)
        y_fit = slope * np.log10(x_fit + 0.1) + intercept
        ax.plot(x_fit, y_fit, color=ACCENT3, linewidth=2.5, linestyle="--",
                label=f"Log-linear fit (r={r:.3f}, p={p:.3g})", alpha=0.9, zorder=5)

    ax.set_xscale("log")
    ax.axhline(y=0, color=FG, alpha=0.2, linestyle=":")
    ax.set_xlabel("Flare Intensity (M-scale; X1 = 10)")
    ax.set_ylabel("Mean Decay Rate Increase (m/day)")
    ax.set_title("Decay Acceleration vs. Flare Intensity (per-event average)",
                 fontsize=14, fontweight="bold", pad=12)
    ax.legend(framealpha=0.7)
    plt.savefig(config.PLOT_FILES["decay_vs_flare_class"])
    plt.close()
    print("  done 03_decay_vs_flare_class.png")


# ── Plot 4: Case Deep Dives — Individual Satellite Traces ───────────────────
def plot_case_events(decay_data):
    fig, axes = plt.subplots(2, 1, figsize=(16, 11))
    events = [
        {"title": "February 2022 — Starlink Group 4-7 Loss Event",
         "center": datetime(2022, 2, 3), "window": 14, "ax": axes[0]},
        {"title": "May 2024 — Gannon G5 Geomagnetic Storm",
         "center": datetime(2024, 5, 10), "window": 14, "ax": axes[1]},
    ]
    # Pick a sample of ~8 individual satellites for traces
    sat_ids_by_group = defaultdict(set)
    for d in decay_data:
        sat_ids_by_group[d["group"]].add(d["norad_id"])

    sample_sats = {}
    for grp in ["shell1", "shell2", "control"]:
        ids = sorted(sat_ids_by_group.get(grp, set()))
        sample_sats[grp] = ids[:3]  # 3 per group for readability

    grp_colors = {"shell1": ACCENT1, "shell2": ACCENT4, "control": ACCENT3}
    grp_labels = {"shell1": "Shell 1", "shell2": "Shell 2", "control": "Control"}

    for event in events:
        ax = event["ax"]
        center = event["center"]
        start = center - timedelta(days=event["window"])
        end = center + timedelta(days=event["window"])

        # Index data for this window
        sat_traces = defaultdict(lambda: defaultdict(list))
        for d in decay_data:
            try: dt = datetime.strptime(d["date"], "%Y-%m-%d")
            except ValueError: continue
            if start <= dt <= end and not d.get("is_maneuver"):
                sat_traces[d["norad_id"]][d["date"]].append(d["decay_rate_m_day"])

        # Plot individual satellite traces
        plotted_labels = set()
        for grp in ["shell1", "shell2", "control"]:
            for sid in sample_sats[grp]:
                if sid not in sat_traces: continue
                dates_sorted = sorted(sat_traces[sid].keys())
                means = [np.mean(sat_traces[sid][d]) for d in dates_sorted]
                pdates = [datetime.strptime(d, "%Y-%m-%d") for d in dates_sorted]
                label = grp_labels[grp] if grp not in plotted_labels else None
                ax.plot(pdates, means, color=grp_colors[grp], linewidth=0.9,
                        alpha=0.5, label=label)
                plotted_labels.add(grp)

        # Also plot group mean as thick line
        group_daily = defaultdict(lambda: defaultdict(list))
        for d in decay_data:
            try: dt = datetime.strptime(d["date"], "%Y-%m-%d")
            except ValueError: continue
            if start <= dt <= end and not d.get("is_maneuver") and d["group"] in ("shell1", "shell2"):
                group_daily["starlink"][d["date"]].append(d["decay_rate_m_day"])
            if start <= dt <= end and not d.get("is_maneuver") and d["group"] == "control":
                group_daily["control"][d["date"]].append(d["decay_rate_m_day"])

        for gname, color, lbl in [("starlink", ACCENT2, "Starlink mean"), ("control", ACCENT3, "Control mean")]:
            if gname in group_daily:
                ds = sorted(group_daily[gname].keys())
                ms = [np.mean(group_daily[gname][d]) for d in ds]
                pds = [datetime.strptime(d, "%Y-%m-%d") for d in ds]
                ax.plot(pds, ms, color=color, linewidth=2.5, alpha=0.9, label=lbl, zorder=5)

        # Mark events
        ax.axvline(center, color=ACCENT5, linestyle="--", alpha=0.8, linewidth=2)
        ax.annotate("Flare/Storm", xy=(center, ax.get_ylim()[1] if ax.get_ylim()[1] != 1 else 0),
                    fontsize=10, color=ACCENT5, ha="left", va="top", fontweight="bold")

        # CME arrival window (+1 to +3 days)
        cme_start = center + timedelta(days=1)
        cme_end = center + timedelta(days=3)
        ax.axvspan(cme_start, cme_end, alpha=0.08, color=ACCENT5, label="CME window")

        ax.set_title(event["title"], fontsize=12, fontweight="bold")
        ax.set_ylabel("Decay Rate (m/day)")
        ax.legend(loc="lower left", fontsize=8, framealpha=0.7, ncol=3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    axes[-1].set_xlabel("Date")
    fig.suptitle("Case Study Deep Dives — Individual Satellite Traces",
                 fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()
    plt.savefig(config.PLOT_FILES["case_events"])
    plt.close()
    print("  done 04_case_events.png")


# ── Plot 5: Recovery Time Histogram ─────────────────────────────────────────
def plot_recovery_time():
    recovery_file = config.DATA_DIR / "recovery_days.json"
    if not recovery_file.exists():
        print("  skip 05 — no recovery data"); return

    with open(recovery_file) as f:
        recovery = json.load(f)

    fig, ax = plt.subplots(figsize=(12, 6))
    ordered = ["M1-M5", "M5-M9", "X1-X5", "X5+"]
    colors = {"M1-M5": ACCENT1, "M5-M9": ACCENT4, "X1-X5": ACCENT2, "X5+": ACCENT5}

    for grp in ordered:
        data = [r["recovery_days"] for r in recovery
                if r["recovered"] and r.get("flare_group") == grp]
        if not data: continue
        ax.hist(data, bins=range(3, 31), alpha=0.5, color=colors[grp],
                label=f"{grp} (n={len(data)}, med={np.median(data):.0f}d)",
                edgecolor=colors[grp], linewidth=0.5)

    ax.set_xlabel("Days to Recovery (within 1-sigma of baseline)")
    ax.set_ylabel("Count")
    ax.set_title("Post-Flare Recovery Time Distribution by Flare Class",
                 fontsize=14, fontweight="bold", pad=12)
    ax.legend(framealpha=0.7, fontsize=10)
    ax.set_xlim(3, 30)
    plt.savefig(config.PLOT_FILES["recovery_time"])
    plt.close()
    print("  done 05_recovery_time.png")


# ── Entry Point ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Phase 6 — Generating Charts")
    print("=" * 60)
    apply_theme()
    with open(config.FLARE_FILE) as f: flares = json.load(f)
    with open(config.DECAY_FILE) as f: decay_data = json.load(f)
    with open(config.ALIGNED_FILE) as f: aligned = json.load(f)
    print(f"  Data: {len(flares)} flares, {len(decay_data)} decay pts, {len(aligned)} aligned\n")
    config.PLOT_DIR.mkdir(parents=True, exist_ok=True)

    plot_flare_timeline(flares)
    plot_decay_distribution(aligned)
    plot_decay_vs_flare_class(aligned)
    plot_case_events(decay_data)
    plot_recovery_time()

    print(f"\n  All charts saved to {config.PLOT_DIR}/")

if __name__ == "__main__":
    main()
