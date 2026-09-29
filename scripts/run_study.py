"""Base case + sensitivity studies for the crude unit. Writes ../results/*.json and .dwxmz."""
import json
import os
import time

import dw
import fug
import analysis
from characterize import characterize

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
os.makedirs(OUT, exist_ok=True)
PRODUCTS = ["NAPHTHA", "KERO", "LGO", "HGO", "RCO"]
FUEL_LHV = 40.0e3  # kJ/kg fuel oil


def obj(fs, tag):
    return fs.GetFlowsheetSimulationObject(tag).GetAsObject()


def snapshot(ch, fs, cols, prm):
    tab = analysis.component_table(ch)
    crude = prm["crude_kg_s"]
    props = {p: analysis.product_properties(obj(fs, p), tab) for p in PRODUCTS}
    q_pre = obj(fs, "E-101").DeltaQ / 1000.0   # MW
    q_fur = obj(fs, "F-101").DeltaQ / 1000.0
    fuel = q_fur * 1000.0 / prm["furnace_eff"] / FUEL_LHV  # kg/s
    fz = obj(fs, "FLASH-ZONE")
    return {
        "crude": ch["assay"]["name"],
        "cot_C": prm["cot"], "preheat_C": prm["preheat_T"],
        "yields_wt": {p: 100 * props[p]["kg_s"] / crude for p in PRODUCTS},
        "products": props,
        "gaps_C": analysis.gaps(props),
        "preflash_vap_wt": 100 * obj(fs, "PF-VAP").GetMassFlow() / crude,
        "flash_zone_T_C": fz.GetTemperature() - 273.15,
        "flash_zone_vap_wt": 100 * (fz.Phases[2].Properties.massfraction or 0.0),
        "preheat_MW": q_pre, "furnace_absorbed_MW": q_fur,
        "furnace_fired_MW": q_fur / prm["furnace_eff"],
        "fuel_t_h": fuel * 3.6, "fuel_pct_crude": 100 * fuel / crude,
        "furnace_kJ_per_kg": q_fur * 1000.0 / crude,
        "columns": [{"tag": c.GraphicObject.Tag, "LK": c.m_lightkey, "HK": c.m_heavykey,
                     "Rmin": c.m_Rmin, "R": c.m_refluxratio, "Nmin": c.m_Nmin, "N": c.m_N,
                     "feed_stage": c.ofs} for c in cols],
    }


def set_and_solve(mgr, fs, cols, prm):
    obj(fs, "E-101").OutletTemperature = prm["preheat_T"] + 273.15
    obj(fs, "F-101").OutletTemperature = prm["cot"] + 273.15
    errs = fug.solve(mgr, fs, cols, prm)
    if errs:
        raise RuntimeError(errs)


def main():
    t0 = time.time()
    results = {"base": {}, "cot": [], "preheat": []}
    for crude, prefix in (("upper_zakum", "UZ_"), ("wti_light", "WT_")):
        ch = characterize(f"../data/{crude}.xlsx", prefix)
        prm = dict(fug.BASE)
        mgr, fs, cols = fug.build(ch, prm)
        set_and_solve(mgr, fs, cols, prm)
        results["base"][crude] = snapshot(ch, fs, cols, prm)
        mgr.SaveFlowsheet(fs, os.path.abspath(os.path.join(OUT, f"CDU_{crude}.dwxmz")), True)
        print(f"{crude} base done {time.time() - t0:.0f}s", flush=True)
        if crude != "upper_zakum":
            continue
        for cot in (345.0, 355.0, 365.0, 375.0, 385.0):
            p = dict(prm, cot=cot)
            set_and_solve(mgr, fs, cols, p)
            results["cot"].append(snapshot(ch, fs, cols, p))
            print(f"  COT {cot} done {time.time() - t0:.0f}s", flush=True)
        for pre in (200.0, 215.0, 230.0, 245.0, 260.0):
            p = dict(prm, preheat_T=pre)
            set_and_solve(mgr, fs, cols, p)
            results["preheat"].append(snapshot(ch, fs, cols, p))
            print(f"  preheat {pre} done {time.time() - t0:.0f}s", flush=True)
        set_and_solve(mgr, fs, cols, prm)
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"ALL DONE {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
