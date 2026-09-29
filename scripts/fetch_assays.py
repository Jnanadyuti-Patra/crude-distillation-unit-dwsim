"""Download the two public ExxonMobil crude assays into ../data/.

The assays are ExxonMobil's (courtesy EMTEC) and are not redistributed in this
repository; see their terms on the assay download page:
https://corporate.exxonmobil.com/what-we-do/energy-supply/crude-trading/assays-available-for-download
"""
import os
import urllib.request

BASE = "https://corporate.exxonmobil.com/-/media/global/files/crude-oils/xls/"
FILES = ["upper_zakum.xlsx", "wti_light.xlsx"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in FILES:
        dest = os.path.join(OUT, name)
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
            f.write(r.read())
        print(f"{name}: {os.path.getsize(dest):,} bytes")
