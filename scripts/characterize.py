"""Split a crude assay into real light ends + TBP pseudo-components.

Method
  * C2-nC5 are real components at the assay's light-end wt%.
  * The rest of the TBP (wt%) curve is cut into pseudo-components on boundaries
    aligned with the assay cut table, so every pseudo sits inside one assay cut.
  * NBP of a pseudo = temperature at the mass midpoint of its slice.
    The >700 C lump gets its NBP from the 550 C+ volume-average boiling point.
  * SG from the assay cut's Watson K, then scaled inside each assay cut so the
    cut's 15 C density is reproduced exactly (volume-additive blending).
  * Sulfur wt% is carried per assay cut.
"""
import bisect
import math

from assay import read_assay

# 15 C liquid densities (g/cc) of the real light ends, used only when matching
# the C5-65 cut density (the cut contains iC5 and nC5).
LIGHT_D15 = {"Ethane": 0.356, "Propane": 0.507, "Isobutane": 0.563, "N-butane": 0.584,
             "Isopentane": 0.625, "N-pentane": 0.631}
LIGHT_NBP_C = {"Ethane": -88.6, "Propane": -42.1, "Isobutane": -11.7, "N-butane": -0.5,
               "Isopentane": 27.8, "N-pentane": 36.1}

BOUNDS = [65, 82, 100, 125, 150, 175, 200, 225, 250, 275, 300, 325, 350, 370,
          397, 423, 450, 475, 500, 525, 550, 600, 650, 700]
LAST_T = 700.0


def watson_k(tb_c, sg):
    return (1.8 * (tb_c + 273.15)) ** (1 / 3) / sg


def sg_from_k(tb_c, k):
    return (1.8 * (tb_c + 273.15)) ** (1 / 3) / k


class Curve:
    """Monotone linear interpolation of cumulative wt% vs T (and inverse)."""

    def __init__(self, tbp):
        pts = sorted(tbp)
        self.T = [p[0] for p in pts]
        self.W = [p[1] for p in pts]

    def w(self, t):
        i = bisect.bisect_left(self.T, t)
        if i <= 0:
            return self.W[0]
        if i >= len(self.T):
            return self.W[-1]
        t0, t1, w0, w1 = self.T[i - 1], self.T[i], self.W[i - 1], self.W[i]
        return w0 + (w1 - w0) * (t - t0) / (t1 - t0)

    def t(self, w):
        i = bisect.bisect_left(self.W, w)
        if i <= 0:
            return self.T[0]
        if i >= len(self.W):
            return self.T[-1]
        t0, t1, w0, w1 = self.T[i - 1], self.T[i], self.W[i - 1], self.W[i]
        return t0 + (t1 - t0) * (w - w0) / (w1 - w0)


def _cut_of(tb, cuts):
    """Assay cut (finest available) containing boiling point tb."""
    fine = [c for c in cuts if c["start"] not in ("IBP",) and c["end"] != "C4"
            and not (c["start"] == 370 and c["end"] == "FBP")]
    for c in fine:
        lo = 36.0 if c["start"] == "C5" else float(c["start"])
        hi = 1e9 if c["end"] == "FBP" else float(c["end"])
        if lo - 1e-9 <= tb < hi:
            return c
    return fine[-1]


def characterize(path, prefix):
    a = read_assay(path)
    curve = Curve(a["tbp"])
    light = dict(a["light_ends_wt"])
    le_total = sum(light.values())

    t0 = curve.t(le_total)  # light ends exhausted here
    edges = [t0] + [b for b in BOUNDS if b > t0 + 5]
    pseudos = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        wlo, whi = curve.w(lo), curve.w(hi)
        pseudos.append({"lo": lo, "hi": hi, "wt": whi - wlo, "tb": curve.t(0.5 * (wlo + whi))})
    lump_wt = 100.0 - curve.w(LAST_T)
    pseudos.append({"lo": LAST_T, "hi": None, "wt": lump_wt, "tb": None})

    # >700 C lump NBP from the 550+ cut average boiling point (mass weighting).
    resid = [p for p in pseudos if p["lo"] >= 550]
    c550 = _cut_of(600, a["cuts"])
    known = [p for p in resid if p["tb"] is not None]
    target = c550["vabp"] * sum(p["wt"] for p in resid)
    tb_lump = (target - sum(p["wt"] * p["tb"] for p in known)) / lump_wt
    pseudos[-1]["tb"] = max(tb_lump, LAST_T + 30.0)

    # Initial SG from each pseudo's assay-cut Watson K, then per-cut density match.
    for p in pseudos:
        c = _cut_of(p["tb"], a["cuts"])
        p["cut"] = c
        k = watson_k(c["vabp"], c["d15"])
        p["sg"] = sg_from_k(p["tb"], k)
        p["s_wt"] = c["sulfur"] or 0.0

    for c in {id(p["cut"]): p["cut"] for p in pseudos}.values():
        members = [p for p in pseudos if p["cut"] is c]
        mass = sum(p["wt"] for p in members)
        real_vol = 0.0
        if c["start"] == "C5":  # this cut also holds iC5 + nC5 (real components)
            for n in ("Isopentane", "N-pentane"):
                mass += light[n]
                real_vol += light[n] / LIGHT_D15[n]
        target_pseudo_vol = mass / c["d15"] - real_vol
        f = sum(p["wt"] / p["sg"] for p in members) / target_pseudo_vol
        for p in members:
            p["sg"] *= f

    for i, p in enumerate(pseudos):
        p["name"] = f"{prefix}{int(round(p['tb']))}C"
        p["kw"] = watson_k(p["tb"], p["sg"])
    return {"assay": a, "light": light, "pseudos": pseudos, "t0": t0}


def check(ch):
    a, light, ps = ch["assay"], ch["light"], ch["pseudos"]
    mass = sum(light.values()) + sum(p["wt"] for p in ps)
    vol = sum(light[n] / LIGHT_D15[n] for n in light) + sum(p["wt"] / p["sg"] for p in ps)
    d15 = mass / vol
    api = 141.5 / (d15 / 0.99910) - 131.5
    sulfur = sum(p["wt"] * p["s_wt"] for p in ps) / mass
    w = a["whole"]
    print(f"{a['name']}: mass {mass:.2f} wt%, light ends {sum(light.values()):.2f} wt%, pseudos {len(ps)} "
          f"(light ends end at {ch['t0']:.1f} C)")
    print(f"  whole crude d15 {d15:.4f} vs assay {w['Density @ 15°C (g/cc)']:.4f} | API {api:.2f} vs {w['API Gravity']:.2f}"
          f" | S {sulfur:.3f} vs {w['Total Sulfur (% wt)']:.3f} wt%")
    print(f"  {'pseudo':>10} {'range C':>11} {'wt%':>6} {'NBP C':>6} {'SG':>7} {'Kw':>6} {'S%':>5}")
    for p in ps:
        hi = "" if p["hi"] is None else f"{p['hi']:.0f}"
        rng = f"{p['lo']:.0f}-{hi}"
        print(f"  {p['name']:>10} {rng:>11} {p['wt']:6.2f} {p['tb']:6.0f} {p['sg']:7.4f} {p['kw']:6.2f} {p['s_wt']:5.2f}")


if __name__ == "__main__":
    import sys
    check(characterize(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "UZ_"))
