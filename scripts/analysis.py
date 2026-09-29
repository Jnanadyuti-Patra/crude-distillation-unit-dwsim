"""Product properties from a solved CDU flowsheet.

TBP of a product: components sorted by NBP, each occupying its liquid-volume
share (volume-additive at 15 C); a component's NBP sits at the midpoint of its
share. D86 from TBP by Riazi-Daubert (API TDB 1987): TBP = a * D86^b, in K.
"""
from characterize import LIGHT_D15, LIGHT_NBP_C

# vol% : (a, b)
RD_D86 = {0: (0.9177, 1.0019), 10: (0.5564, 1.0900), 30: (0.7617, 1.0425),
          50: (0.9013, 1.0176), 70: (0.8821, 1.0226), 90: (0.9552, 1.0110), 95: (0.8177, 1.0355)}


def component_table(ch):
    """{name: (nbp C, SG, sulfur wt%)} for hydrocarbons (water excluded)."""
    tab = {n: (LIGHT_NBP_C[n], LIGHT_D15[n], 0.0) for n in LIGHT_D15}
    for p in ch["pseudos"]:
        tab[p["name"]] = (p["tb"], p["sg"], p["s_wt"])
    return tab


def stream_hc_masses(stream, tab):
    """Hydrocarbon mass flow (kg/s) per component in a DWSIM stream."""
    m = stream.GetMassFlow()
    out = {}
    for n in tab:
        c = stream.Phases[0].Compounds[n]
        out[n] = c.MassFraction * m
    return out


def tbp_curve(masses, tab):
    """[(cum vol %, T C)] points."""
    items = sorted(((tab[n][0], w / tab[n][1]) for n, w in masses.items() if w > 0), key=lambda t: t[0])
    vtot = sum(v for _, v in items)
    pts, cum = [], 0.0
    for t, v in items:
        pts.append((100.0 * (cum + 0.5 * v) / vtot, t))
        cum += v
    return pts


def t_at(pts, pct):
    if not pts:
        return float("nan")
    if pct <= pts[0][0]:
        return pts[0][1]
    for (x0, t0), (x1, t1) in zip(pts, pts[1:]):
        if x0 <= pct <= x1:
            return t0 + (t1 - t0) * (pct - x0) / (x1 - x0)
    return pts[-1][1]


def d86_from_tbp(tbp_c, pct):
    a, b = RD_D86[pct]
    return ((tbp_c + 273.15) / a) ** (1.0 / b) - 273.15


def product_properties(stream, tab):
    masses = stream_hc_masses(stream, tab)
    m = sum(masses.values())
    if m <= 0:
        return None
    vol = sum(w / tab[n][1] for n, w in masses.items())
    sg = m / vol
    pts = tbp_curve(masses, tab)
    tbp = {p: t_at(pts, p) for p in (5, 10, 30, 50, 70, 90, 95)}
    return {
        "kg_s": m,
        "sg": sg,
        "api": 141.5 / sg - 131.5,
        "sulfur_wt": sum(w * tab[n][2] for n, w in masses.items()) / m,
        "tbp": tbp,
        "d86": {p: d86_from_tbp(tbp[p], p) for p in (10, 30, 50, 70, 90, 95)},
    }


def gaps(props, order=("NAPHTHA", "KERO", "LGO", "HGO", "RCO")):
    """TBP (5-95) gap between adjacent products: T5(heavy) - T95(light), C."""
    out = {}
    for lt, hv in zip(order, order[1:]):
        if props.get(lt) and props.get(hv):
            out[f"{lt}/{hv}"] = props[hv]["tbp"][5] - props[lt]["tbp"][95]
    return out
