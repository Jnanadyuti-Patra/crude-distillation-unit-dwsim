"""Atmospheric crude distillation unit (CDU) in DWSIM.

Flowsheet
  CRUDE -> E-101 (preheat train, heater) -> V-101 preflash drum
  V-101 liquid -> F-101 furnace -> T-101 flash zone
  V-101 vapour -> T-101 (a few stages above the flash zone)
  STEAM -> T-101 bottom stage
  T-101: refluxed absorber (no reboiler), partial condenser,
         side draws KERO / LGO / HGO, bottoms RCO, two pumparound coolers.
"""
import uuid

import System
import model
from DWSIM.Interfaces.Enums.GraphicObjects import ObjectType
from DWSIM.UnitOperations.UnitOperations.Auxiliary.SepOps import StreamInformation, ColumnSpec

SI = StreamInformation
KG_H = 1 / 3600.0

BASE = {
    "crude_kg_s": 750_000 * KG_H,     # 750 t/h ~ 6 MMTPA at 8,000 h/yr
    "crude_T": 30.0 + 273.15,
    "crude_P": 12e5,
    "preheat_T": 230.0 + 273.15,      # end of preheat train
    "preflash_P": 3.5e5,
    "cot": 365.0 + 273.15,            # furnace coil outlet temperature
    "furnace_P": 2.4e5,
    "top_P": 1.5e5,                    # top tray
    "column_dP": 0.9e5,
    "stages": 25,                      # condenser = 0, trays 1..24
    "steam_kg_s": 7_000 * KG_H,
    "steam_T": 400.0 + 273.15,
    "steam_P": 4.5e5,
    # stage indices (0 = condenser)
    "kero_stage": 7, "lgo_stage": 13, "hgo_stage": 18,
    "preflash_vap_stage": 18, "feed_stage": 21,
    "pa1_stage": 4, "pa2_stage": 11,
    "pa1_MW": 0.0, "pa2_MW": 0.0,
    # TBP cut points (C) that set the draw rates
    "cuts": {"NAPHTHA": 150.0, "KERO": 250.0, "LGO": 350.0, "HGO": 370.0},
    "solver": "Napthali-Sandholm",
    "coltype": "refluxed",       # "refluxed" (steam stripped) or "distillation" (reboiled)
    "condenser": "partial",      # "partial" (offgas + naphtha) or "total"
    "estimates": True,           # user T / flow estimates + Direct scheme
    "scheme": "Direct",
    "draws": ("KERO", "LGO", "HGO"),  # side draws to include
    "reflux_ratio": None,             # if set (with no draws / distillation), C spec = reflux ratio
}


PRODUCTS = ["OFFGAS", "NAPHTHA", "KERO", "LGO", "HGO", "RCO"]
LPG = {"Ethane", "Propane", "Isobutane", "N-butane"}


def product_of(name, nbp_c, cuts):
    if name in LPG:
        return "OFFGAS"
    if name in ("Isopentane", "N-pentane") or nbp_c < cuts["NAPHTHA"]:
        return "NAPHTHA"
    for prod in ("KERO", "LGO", "HGO"):
        if nbp_c < cuts[prod]:
            return prod
    return "RCO"


def tbp_product_rates(ch, fs, crude_kg_s, cuts):
    """Ideal TBP-cut product rates {product: (kg/s, mol/s)} for the given crude rate."""
    fr = model.crude_mass_fractions(ch)
    nbp = {p["name"]: p["tb"] for p in ch["pseudos"]}
    out = {p: [0.0, 0.0] for p in PRODUCTS}
    for n, w in fr.items():
        if w <= 0:
            continue
        prod = product_of(n, nbp.get(n, -100.0), cuts)
        kg = w * crude_kg_s
        out[prod][0] += kg
        out[prod][1] += kg / fs.SelectedCompounds[n].Molar_Weight * 1000.0
    return {k: tuple(v) for k, v in out.items()}


def _add_stream(fs, tag, x, y):
    return fs.AddObject(ObjectType.MaterialStream, x, y, tag).GetAsObject()


def _free_out(go):
    for i in range(go.OutputConnectors.Count):
        if not go.OutputConnectors[i].IsAttached:
            return i
    raise RuntimeError("no free output connector")


def _free_in(go):
    for i in range(go.InputConnectors.Count):
        if not go.InputConnectors[i].IsAttached:
            return i
    raise RuntimeError("no free input connector")


def add_sidedraw(fs, col, stream, stage_idx, mol_s):
    si = SI()
    si.ID = str(uuid.uuid4())
    si.StreamID = stream.Name
    si.AssociatedStage = col.Stages[stage_idx].ID
    si.StreamBehavior = SI.Behavior.Sidedraw
    si.StreamType = SI.Type.Material
    si.StreamPhase = SI.Phase.L
    si.FlowRate.Value = mol_s
    col.MaterialStreams[si.ID] = si
    fs.ConnectObjects(col.GraphicObject, stream.GraphicObject, _free_out(col.GraphicObject), 0)
    return si


def add_stage_cooler(fs, col, estream, stage_idx, watts):
    """Pumparound represented as heat removed from one stage."""
    si = SI()
    si.ID = str(uuid.uuid4())
    si.StreamID = estream.Name
    si.AssociatedStage = col.Stages[stage_idx].ID
    si.StreamBehavior = SI.Behavior.InterExchanger
    si.StreamType = SI.Type.Energy
    si.StreamPhase = getattr(SI.Phase, "None")
    col.EnergyStreams[si.ID] = si
    estream.EnergyFlow = -watts / 1000.0  # kW; negative = heat removed
    fs.ConnectObjects(col.GraphicObject, estream.GraphicObject, _free_out(col.GraphicObject), 0)
    return si


def build_column_only(ch, prm=BASE, tag_prefix=""):
    """Stage 1 of the build: furnace-outlet feed + steam straight into the column."""
    mgr, fs = model.new_flowsheet(ch)
    rates = tbp_product_rates(ch, fs, prm["crude_kg_s"], prm["cuts"])

    feed = _add_stream(fs, "FEED", 100, 300)
    model.set_mass_composition(feed, model.crude_mass_fractions(ch))
    feed.SetTemperature(prm["cot"]); feed.SetPressure(prm["furnace_P"]); feed.SetMassFlow(prm["crude_kg_s"])
    use_steam = prm["steam_kg_s"] > 0
    if use_steam:
        steam = _add_stream(fs, "STEAM", 100, 450)
        model.set_mass_composition(steam, {"Water": 1.0})
        steam.SetTemperature(prm["steam_T"]); steam.SetPressure(prm["steam_P"]); steam.SetMassFlow(prm["steam_kg_s"])

    col = fs.AddObject(ObjectType.DistillationColumn, 400, 100, "T-101").GetAsObject()
    col.SetNumberOfStages(prm["stages"])
    if prm["coltype"] == "refluxed":
        col.RefluxedAbsorber = True
        col.ColumnType = col.ColumnType.RefluxedAbsorber
    partial = prm["condenser"] == "partial"
    col.CondenserType = col.CondenserType.Partial_Condenser if partial else col.CondenserType.Total_Condenser
    col.SetTopPressure(prm["top_P"])
    col.ColumnPressureDrop = prm["column_dP"]
    col.SolvingMethodName = prm["solver"]
    col.MaxIterations = 200

    col.ConnectFeed(feed, prm["feed_stage"])
    if use_steam:
        col.ConnectFeed(steam, prm["stages"] - 1)
    if partial:
        ovhd = _add_stream(fs, "OFFGAS", 650, 20); col.ConnectVaporProduct(ovhd)
    dist = _add_stream(fs, "NAPHTHA", 650, 80); col.ConnectDistillate(dist)
    rco = _add_stream(fs, "RCO", 650, 500); col.ConnectBottoms(rco)
    qc = fs.AddObject(ObjectType.EnergyStream, 650, 0, "Q-COND").GetAsObject(); col.ConnectCondenserDuty(qc)
    if prm["coltype"] == "distillation":
        qr = fs.AddObject(ObjectType.EnergyStream, 650, 560, "Q-REB").GetAsObject(); col.ConnectReboilerDuty(qr)

    for i, (prod, key) in enumerate((("KERO", "kero_stage"), ("LGO", "lgo_stage"), ("HGO", "hgo_stage"))):
        if prod not in prm["draws"]:
            continue
        s = _add_stream(fs, prod, 650, 150 + 80 * i)
        add_sidedraw(fs, col, s, prm[key], rates[prod][1])
    for i, key in enumerate(("pa1", "pa2")):
        if prm[key + "_MW"] > 0:
            e = fs.AddObject(ObjectType.EnergyStream, 550, 120 + 200 * i, "Q-" + key.upper()).GetAsObject()
            add_stage_cooler(fs, col, e, prm[key + "_stage"], prm[key + "_MW"] * 1e6)

    # Top specs. Partial condenser: offgas vapour at the LPG rate. Liquid
    # distillate = naphtha (+ LPG if total condenser) + all stripping steam,
    # which condenses in the reflux drum and is decanted downstream.
    steam_mol = prm["steam_kg_s"] / 18.015 * 1000.0
    dist_mol = rates["NAPHTHA"][1] + steam_mol
    dist_mol += sum(rates[p][1] for p in ("KERO", "LGO", "HGO") if p not in prm["draws"])
    if partial:
        col.VaporFlowRate = rates["OFFGAS"][1]
        col.VaporFlowRateUnit = "mol/s"
    else:
        dist_mol += rates["OFFGAS"][1]
    spec = col.Specs["C"]
    spec.SType = ColumnSpec.SpecType.Product_Molar_Flow_Rate
    spec.SpecValue = dist_mol
    spec.SpecUnit = "mol/s"
    if prm["coltype"] == "distillation":
        rs = col.Specs["R"]
        rs.SType = ColumnSpec.SpecType.Product_Molar_Flow_Rate
        rs.SpecValue = rates["RCO"][1]
        rs.SpecUnit = "mol/s"
    col.SolverScheme = getattr(col.SolverScheme, prm["scheme"])
    if prm["estimates"]:
        set_temperature_estimates(col, prm)
        set_flow_estimates(col, prm, rates)
    return mgr, fs, col, rates


def set_temperature_estimates(col, prm):
    """Linear profile: condenser 60 C, top tray 115 C, flash zone ~COT-15 C,
    stripping section cooling ~5 C per stage."""
    n = prm["stages"]
    f = prm["feed_stage"]
    t_flash = prm["cot"] - 15.0
    est = []
    for i in range(n):
        if i == 0:
            est.append(60.0 + 273.15)
        elif i <= f:
            est.append(115.0 + 273.15 + (t_flash - 388.15) * (i - 1) / (f - 1))
        else:
            est.append(t_flash - 5.0 * (i - f))
    col.UseTemperatureEstimates = True
    col.SetInitialTemperatureEstimates(System.Array[float](est))


def set_flow_estimates(col, prm, rates):
    """Rough internal flows: reflux ~1.5x naphtha above the kero draw, vapour
    carries everything lighter than the stage plus steam."""
    n, f = prm["stages"], prm["feed_stage"]
    steam = prm["steam_kg_s"] / 18.015 * 1000.0
    draws = {prm["kero_stage"]: "KERO", prm["lgo_stage"]: "LGO", prm["hgo_stage"]: "HGO"}
    top = rates["OFFGAS"][1] + rates["NAPHTHA"][1] + steam
    L, V = [], []
    below = top
    for i in range(n):
        if i in draws:
            below += rates[draws[i]][1]
        if i == 0:
            V.append(rates["OFFGAS"][1]); L.append(1.5 * rates["NAPHTHA"][1])
        elif i <= f:
            V.append(below + 1.5 * rates["NAPHTHA"][1]); L.append(1.5 * rates["NAPHTHA"][1])
        else:
            V.append(steam * (n - i) / (n - f)); L.append(rates["RCO"][1] * 1.05)
    col.UseVaporFlowEstimates = True
    col.UseLiquidFlowEstimates = True
    col.SetInitialVaporMolarFlowEstimates(System.Array[float](V))
    col.SetInitialLiquidMolarFlowEstimates(System.Array[float](L))
