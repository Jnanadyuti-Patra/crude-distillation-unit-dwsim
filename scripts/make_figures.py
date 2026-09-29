"""Figures for the crude-unit report, from ../results/results.json."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
FIG = os.path.join(HERE, "..", "figures")
os.makedirs(FIG, exist_ok=True)

BLUE, ORANGE = "#2a78d6", "#eb6834"      # categorical slots 1, 2
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
PRODUCTS = ["NAPHTHA", "KERO", "LGO", "HGO", "RCO"]
LABELS = ["Naphtha\n(+LPG)", "Kerosene", "Diesel\n(LGO)", "Gas oil\n(HGO)", "Reduced\ncrude"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})


def load():
    with open(os.path.join(RES, "results.json"), encoding="utf-8") as f:
        return json.load(f)


def fig_yields(r):
    uz, wt = r["base"]["upper_zakum"], r["base"]["wti_light"]
    x = range(len(PRODUCTS))
    w = 0.38
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=200)
    for off, run, col, name in ((-w / 2 - 0.01, uz, BLUE, "Upper Zakum (33.4° API, 2.1% S)"),
                                (w / 2 + 0.01, wt, ORANGE, "WTI Light (47.4° API, 0.07% S)")):
        vals = [run["yields_wt"][p] for p in PRODUCTS]
        bars = ax.bar([i + off for i in x], vals, width=w, color=col, label=name)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.8, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(list(x), LABELS)
    ax.set_ylabel("Yield, wt% of crude")
    ax.set_title("Product yields, same unit and cut points", loc="left", fontsize=11, color=INK)
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "yields_crude_switch.png"))
    plt.close(fig)


def fig_cot(r):
    cot = [s["cot_C"] for s in r["cot"]]
    vap = [s["flash_zone_vap_wt"] for s in r["cot"]]
    fired = [s["furnace_fired_MW"] for s in r["cot"]]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 3.2), dpi=200)
    a1.plot(cot, vap, color=BLUE, lw=2, marker="o", ms=5)
    needed = 100 - r["base"]["upper_zakum"]["yields_wt"]["RCO"]
    a1.axhline(needed, color=INK2, lw=1, ls="--")
    a1.text(cot[0], needed + 0.4, "distillate lifted above RCO", fontsize=8, color=INK2)
    a1.set_title("Flash-zone vaporization, wt%", loc="left", fontsize=10)
    a1.set_xlabel("Furnace outlet temperature, °C")
    a2.plot(cot, fired, color=BLUE, lw=2, marker="o", ms=5)
    a2.set_title("Furnace fired duty, MW", loc="left", fontsize=10)
    a2.set_xlabel("Furnace outlet temperature, °C")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "cot_sensitivity.png"))
    plt.close(fig)


def fig_preheat(r):
    pre = [s["preheat_C"] for s in r["preheat"]]
    fuel = [s["fuel_t_h"] for s in r["preheat"]]
    fig, ax = plt.subplots(figsize=(4.6, 3.2), dpi=200)
    ax.plot(pre, fuel, color=BLUE, lw=2, marker="o", ms=5)
    for p, f in zip(pre, fuel):
        ax.text(p + 1.2, f + 0.18, f"{f:.1f}", ha="left", fontsize=8, color=INK2)
    ax.set_title("Furnace fuel vs preheat-train outlet", loc="left", fontsize=10)
    ax.set_xlabel("Crude temperature leaving preheat train, °C")
    ax.set_ylabel("Fuel oil, t/h")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "preheat_fuel.png"))
    plt.close(fig)


if __name__ == "__main__":
    r = load()
    fig_yields(r)
    fig_cot(r)
    fig_preheat(r)
    print("figures written to", os.path.abspath(FIG))
