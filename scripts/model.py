"""Build DWSIM compounds and flowsheet objects for a characterized crude."""
import math
import os

import dw
from DWSIM.Thermodynamics.BaseClasses import ConstantProperties
from DWSIM.Thermodynamics.PetroleumCharacterization.Methods import PropertyMethods
from DWSIM.Thermodynamics.Utilities.PetroleumCharacterization.Methods import GL

R = 8314.46  # J/(kmol K)
PM = PropertyMethods()
REAL = ["Water", "Ethane", "Propane", "Isobutane", "N-butane", "Isopentane", "N-pentane"]


def rackett_z(mw, sg, tc, pc, t=288.15):
    """Rackett parameter that reproduces the pseudo's 15 C density (SG * 999.0 kg/m3)."""
    v = mw / (sg * 999.0)  # m3/kmol
    tr = min(t / tc, 0.999)
    expo = 1.0 + (1.0 - tr) ** (2.0 / 7.0)
    return (v / (R * tc / pc)) ** (1.0 / expo)


def rackett_v(z, tc, pc, t):
    tr = min(t / tc, 0.999)
    return R * tc / pc * z ** (1.0 + (1.0 - tr) ** (2.0 / 7.0))


def pseudo_compound(p, cid):
    """ConstantProperties for one pseudo-component, using the same correlations
    DWSIM's characterization wizard uses (Winn MW, Riazi-Daubert Tc/Pc,
    Lee-Kesler acentric factor, Abbott viscosities -> Walther constants)."""
    tb = p["tb"] + 273.15
    sg = p["sg"]
    mw = PM.MW_Winn(tb, sg)
    tc = PM.Tc_RiaziDaubert(tb, sg)
    pc = PM.Pc_RiaziDaubert(tb, sg)
    w = float(PM.AcentricFactor_LeeKesler(tc, pc, tb))
    z = rackett_z(mw, sg, tc, pc)
    tbr = tb / tc
    hvap_nbp = 1.093 * R * tc * tbr * (math.log(pc / 1e5) - 1.013) / (0.930 - tbr) / 1000.0  # kJ/kmol, Riedel
    v25 = rackett_v(z, tc, pc, 298.15) * 1000.0  # cm3/mol
    h298 = hvap_nbp * ((1 - 298.15 / tc) / (1 - tbr)) ** 0.38  # Watson, kJ/kmol
    delta = math.sqrt(max(h298 - 8.314 * 298.15, 1.0) * 1000.0 / 4.184 / v25)  # (cal/cm3)^0.5
    v37, v98 = PM.Visc37_Abbott(tb, sg), PM.Visc98_Abbott(tb, sg)

    c = ConstantProperties()
    c.Name = p["name"]
    c.ID = cid
    c.OriginalDB = "DWSIM"
    c.CurrentDB = "DWSIM"
    c.IsPF = 1
    c.IsHYPO = 0
    c.NBP = tb
    c.Normal_Boiling_Point = tb
    c.Molar_Weight = mw
    c.PF_MM = mw
    c.PF_SG = sg
    c.PF_Watson_K = (1.8 * tb) ** (1 / 3) / sg
    c.Critical_Temperature = tc
    c.Critical_Pressure = pc
    c.Acentric_Factor = w
    c.Z_Rackett = z
    c.Critical_Compressibility = z
    c.Critical_Volume = z * R * tc / pc
    c.HVap_A = hvap_nbp / mw
    c.Chao_Seader_Acentricity = w
    c.Chao_Seader_Liquid_Molar_Volume = v25
    c.Chao_Seader_Solubility_Parameter = delta
    c.PF_Tv1, c.PF_Tv2 = 310.95, 372.05
    c.PF_v1, c.PF_v2 = v37, v98
    c.PF_vA = PM.ViscWaltherASTM_A(310.95, v37, 372.05, v98)
    c.PF_vB = PM.ViscWaltherASTM_B(310.95, v37, 372.05, v98)
    hf = GL().calculate_Hf_Sf(sg, mw, tb)
    try:
        c.IG_Enthalpy_of_Formation_25C = float(hf[0])
        c.IG_Entropy_of_Formation_25C = float(hf[1])
    except Exception:
        pass
    return c


REAL_D15 = {"Water": 0.9991, "Ethane": 0.356, "Propane": 0.507, "Isobutane": 0.563,
            "N-butane": 0.584, "Isopentane": 0.625, "N-pentane": 0.631}
CAL_T, CAL_P = 288.71, 50e5  # 60 F; 50 bar keeps every light end liquid


def _bare_flowsheet(ch, package):
    here = os.getcwd()
    os.chdir(dw.D)
    mgr = dw.Automation3()
    fs = mgr.CreateFlowsheet()
    os.chdir(here)
    for n in REAL:
        fs.AddCompound(n)
    for i, p in enumerate(ch["pseudos"]):
        c = pseudo_compound(p, -9000 - i)
        fs.AvailableCompounds[c.Name] = c
        fs.AddCompound(c.Name)
    fs.CreateAndAddPropertyPackage(package)
    set_flash_algorithm(fs, FLASH)
    return mgr, fs


# DWSIM 8.8.3's default nested-loops PV flash indexes result(11) without
# checking that the inner flash succeeded, so column bubble-point failures
# surface as IndexOutOfRange. Inside-out is the robust choice for crude.
FLASH = "InsideOut"
EQUILIBRIUM = "Default"  # "VLLE" routes PV flashes through NestedLoops3PV3


def set_flash_algorithm(fs, approach):
    import System
    from DWSIM.Interfaces.Enums import FlashSetting
    pp = list(fs.PropertyPackages.Values)[0].__implementation__
    prop = pp.GetType().GetProperty("FlashCalculationApproach")
    prop.SetValue(pp, System.Enum.Parse(prop.PropertyType, approach))
    pp.FlashSettings[FlashSetting.ForceEquilibriumCalculationType] = EQUILIBRIUM


def _set_liquid_density_eos(fs):
    """EOS liquid density with Peneloux translation. DWSIM's Rackett mixing rule
    underpredicts wide-boiling crude density by ~10%, so it is not used."""
    import System
    pp = list(fs.PropertyPackages.Values)[0]
    t = pp.GetType()
    for nm in ("LiquidDensityCalculationMode_Subcritical", "LiquidDensityCalculationMode_Supercritical"):
        prop = t.GetProperty(nm)
        prop.SetValue(pp, System.Enum.Parse(prop.PropertyType, "EOS"))
    t.GetProperty("LiquidDensity_UsePenelouxVolumeTranslation").SetValue(pp, True)


def volume_translations(ch, package):
    """Per-compound Peneloux coefficient so PR reproduces each 15 C density.
    DWSIM applies V = V_PR - coef * b with b = 0.07780 R Tc / Pc."""
    from DWSIM.Interfaces.Enums.GraphicObjects import ObjectType
    mgr, fs = _bare_flowsheet(ch, package)
    _set_liquid_density_eos(fs)
    target = dict(REAL_D15)
    target.update({p["name"]: p["sg"] for p in ch["pseudos"]})
    streams = {}
    for i, n in enumerate(target):
        s = fs.AddObject(ObjectType.MaterialStream, 0, 40 * i, "CAL_" + n).GetAsObject()
        set_mass_composition(s, {n: 1.0})
        s.SetTemperature(CAL_T)
        s.SetPressure(CAL_P)
        s.SetMassFlow(1.0)
        streams[n] = s
    mgr.CalculateFlowsheet4(fs)
    coefs = {}
    for n, s in streams.items():
        c = fs.SelectedCompounds[n]
        v0 = c.Molar_Weight / s.Phases[0].Properties.density
        vt = c.Molar_Weight / (target[n] * 999.0)
        b = 0.07780 * R * c.Critical_Temperature / c.Critical_Pressure
        coefs[n] = (v0 - vt) / b
    return coefs


def new_flowsheet(ch, package="Peng-Robinson (PR)"):
    """Flowsheet with water, light ends and the crude's pseudos, with PR liquid
    densities volume-translated to the assay's 15 C densities."""
    coefs = volume_translations(ch, package)
    mgr, fs = _bare_flowsheet(ch, package)
    _set_liquid_density_eos(fs)
    for n, k in coefs.items():
        fs.SelectedCompounds[n].PR_Volume_Translation_Coefficient = k
    return mgr, fs


def crude_mass_fractions(ch):
    """{compound: mass fraction} for the whole crude (water-free)."""
    x = {n: ch["light"].get(n, 0.0) for n in REAL}
    for p in ch["pseudos"]:
        x[p["name"]] = p["wt"]
    tot = sum(x.values())
    return {k: v / tot for k, v in x.items()}


def set_mass_composition(stream, fracs):
    names = list(stream.Phases[0].Compounds.Keys)
    for n in names:
        stream.Phases[0].Compounds[n].MassFraction = fracs.get(n, 0.0)
    comp = [fracs.get(n, 0.0) for n in names]
    stream.SetOverallMassComposition(__import__("System").Array[float](comp))
