"""DWSIM bootstrap shared by the model scripts.

DWSIM's install folder defaults to %LOCALAPPDATA%\\DWSIM (the per-user installer's
location); set the DWSIM_PATH environment variable to override.
"""
import os
import sys

D = os.environ.get("DWSIM_PATH", os.path.join(os.environ.get("LOCALAPPDATA", ""), "DWSIM"))
if not os.path.isfile(os.path.join(D, "DWSIM.Automation.dll")):
    raise FileNotFoundError(f"DWSIM not found in {D!r}; install DWSIM 9.x or set DWSIM_PATH")
sys.path.append(D)
_cwd = os.getcwd()
os.chdir(D)
import pythonnet
pythonnet.load("netfx")
import clr
for dll in ("DWSIM.Automation", "DWSIM.Interfaces", "DWSIM.Thermodynamics", "DWSIM.UnitOperations",
            "DWSIM.GlobalSettings", "DWSIM.SharedClasses", "DWSIM.FlowsheetBase"):
    clr.AddReference(os.path.join(D, dll + ".dll"))
from DWSIM.Automation import Automation3
from DWSIM.GlobalSettings import Settings

# Solve serially: keeps runs deterministic and column-solver tracebacks readable.
Settings.EnableParallelProcessing = False
os.chdir(_cwd)
