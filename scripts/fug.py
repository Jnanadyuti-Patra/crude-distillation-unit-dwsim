"""Crude unit in DWSIM: rigorous front end + shortcut (FUG) fractionation train.

CRUDE -> E-101 preheat -> V-101 preflash -> F-101 furnace -> M-101 (+ preflash vapour)
      -> C-1 (RCO split at 370 C) -> C-2 (HGO at 350 C) -> C-3 (LGO at 250 C)
      -> C-4 (KERO at 150 C; total condenser: unstabilised naphtha incl. LPG)
Each shortcut column: Fenske Nmin, Underwood Rmin, Gilliland N at R = 1.3 Rmin.
"""
import model
from DWSIM.Interfaces.Enums.GraphicObjects import ObjectType

KG_H = 1 / 3600.0
BASE = {
    "crude_kg_s": 750_000 * KG_H,   # 750 t/h ~ 6 MMTPA
    "crude_T": 30.0, "crude_P": 12e5,
    "preheat_T": 230.0, "preflash_P": 3.5e5,
    "cot": 365.0, "furnace_P": 2.4e5,
    "top_P": 1.5e5, "bottom_P": 2.4e5,
    "cuts": [("RCO", 370.0), ("HGO", 350.0), ("LGO", 250.0), ("KERO", 150.0)],
    "key_frac": 0.01,               # LK mole fraction in bottoms / HK in distillate
    "r_factor": 1.3,
    "r_floor": 0.25,
    "furnace_eff": 0.88,
}


def _stream(fs, tag, x, y):
    return fs.AddObject(ObjectType.MaterialStream, x, y, tag).GetAsObject()


def _energy(fs, tag, x, y):
    return fs.AddObject(ObjectType.EnergyStream, x, y, tag).GetAsObject()


def _conn(fs, a, b, ia=0, ib=0):
    fs.ConnectObjects(a.GraphicObject, b.GraphicObject, ia, ib)


def _heater(fs, tag, inlet, outlet, T_c, dP, x, y):
    h = fs.AddObject(ObjectType.Heater, x, y, tag).GetAsObject()
    q = _energy(fs, "Q-" + tag, x, y + 60)
    _conn(fs, inlet, h, 0, 0)
    _conn(fs, h, outlet, 0, 0)
    _conn(fs, q, h, 0, 1)
    h.CalcMode = h.CalcMode.OutletTemperature
    h.OutletTemperature = T_c + 273.15
    h.DeltaP = dP
    return h


def keys_for(ch, cut_c):
    """Adjacent pseudos straddling a TBP cut point: (light key, heavy key)."""
    ps = sorted(ch["pseudos"], key=lambda p: p["tb"])
    lk = max((p for p in ps if p["tb"] < cut_c), key=lambda p: p["tb"])
    hk = min((p for p in ps if p["tb"] >= cut_c), key=lambda p: p["tb"])
    return lk["name"], hk["name"]


def build(ch, prm=BASE):
    mgr, fs = model.new_flowsheet(ch)
    crude = _stream(fs, "CRUDE", 0, 200)
    model.set_mass_composition(crude, model.crude_mass_fractions(ch))
    crude.SetTemperature(prm["crude_T"] + 273.15); crude.SetPressure(prm["crude_P"]); crude.SetMassFlow(prm["crude_kg_s"])

    s1 = _stream(fs, "PREHEATED", 150, 200)
    e101 = _heater(fs, "E-101", crude, s1, prm["preheat_T"], prm["crude_P"] - prm["preflash_P"], 80, 200)

    v101 = fs.AddObject(ObjectType.Vessel, 220, 200, "V-101").GetAsObject()
    pf_v = _stream(fs, "PF-VAP", 300, 140); pf_l = _stream(fs, "PF-LIQ", 300, 260)
    _conn(fs, s1, v101, 0, 0); _conn(fs, v101, pf_v, 0, 0); _conn(fs, v101, pf_l, 1, 0)

    fo = _stream(fs, "FURNACE-OUT", 450, 260)
    f101 = _heater(fs, "F-101", pf_l, fo, prm["cot"], prm["preflash_P"] - prm["furnace_P"], 380, 260)

    mix = fs.AddObject(ObjectType.Mixer, 520, 200, "M-101").GetAsObject()
    feed = _stream(fs, "FLASH-ZONE", 580, 200)
    _conn(fs, pf_v, mix, 0, 0); _conn(fs, fo, mix, 0, 1); _conn(fs, mix, feed, 0, 0)

    cols, products, inlet = [], {}, feed
    for i, (bottom_prod, cut) in enumerate(prm["cuts"]):
        lk, hk = keys_for(ch, cut)
        c = fs.AddObject(ObjectType.ShortcutColumn, 650 + 150 * i, 200, f"C-{i + 1}").GetAsObject()
        last = i == len(prm["cuts"]) - 1
        dist = _stream(fs, "NAPHTHA" if last else f"OVHD-{i + 1}", 720 + 150 * i, 120)
        bott = _stream(fs, bottom_prod, 720 + 150 * i, 300)
        qr = _energy(fs, f"QR-{i + 1}", 640 + 150 * i, 340)
        _conn(fs, inlet, c, 0, 0)
        _conn(fs, qr, c, 0, 1)
        _conn(fs, c, dist, 0, 0)
        _conn(fs, c, bott, 1, 0)
        c.condtype = c.condtype.TotalCond
        c.m_lightkey, c.m_heavykey = lk, hk
        c.m_lightkeymolarfrac = prm["key_frac"]
        c.m_heavykeymolarfrac = prm["key_frac"]
        c.m_condenserpressure = prm["top_P"]
        c.m_boilerpressure = prm["bottom_P"]
        c.m_refluxratio = 2.0
        cols.append(c)
        products[bottom_prod] = bott
        inlet = dist
    return mgr, fs, cols


def solve(mgr, fs, cols, prm=BASE):
    """Solve at R = 2, then reset each column to R = r_factor * Rmin and re-solve."""
    errs = mgr.CalculateFlowsheet4(fs)
    if errs is not None and errs.Count:
        return [str(e).splitlines()[0] for e in errs]
    for c in cols:
        # Underwood Rmin <= 0 means an easy split (minimum reflux effectively
        # zero); floor R so Gilliland stays meaningful.
        c.m_refluxratio = max(prm["r_factor"] * c.m_Rmin, prm["r_floor"])
    errs = mgr.CalculateFlowsheet4(fs)
    return [str(e).splitlines()[0] for e in errs] if errs is not None and errs.Count else []
