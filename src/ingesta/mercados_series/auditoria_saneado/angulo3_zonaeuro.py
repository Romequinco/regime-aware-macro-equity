"""Auditoría ángulo 3 · composición de la zona euro en la base curada (solo ids, sin valores).
Clasifica las series de la base curada que son de la zona euro por su código de área. Uso: python angulo3_zonaeuro.py"""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json, re, sys
from pathlib import Path
import pyarrow.parquet as pq, pyarrow.compute as pc
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
t = pq.read_table("D:/tfm_corpus/mercados_series/series/base_curada.parquet", columns=["serie"])
ids = sorted(map(str, pc.unique(t["serie"]).to_pylist()))
REGLAS = [  # (patrón, tipo, explicación)
    (r"\.U2\.|\.U2$", "cambiante", "BCE U2: zona euro de composición cambiante (la oficial de cada fecha)"),
    (r"\.EA$|\.EA\.", "cambiante", "Eurostat EA: zona euro de composición cambiante (EA11-1999 … EA20-2023)"),
    (r"EA20|EA21|EA19", "fija_actual", "composición fija (todos los países actuales hacia atrás)"),
    (r"\.XM\.|\.XM$", "fija_actual", "BIS XM: zona euro con la composición actual"),
    (r"EMU", "fija_actual", "Banco Mundial EMU: agregado con los miembros actuales"),
    (r"G4E", "fija_actual", "OCDE G4E (4 grandes de la zona euro)"),
    (r"EU27", "fija_actual", "UE27 de 2020 (composición fija)"),
]
filas = []
for s in ids:
    for pat, tipo, expl in REGLAS:
        if re.search(pat, s):
            filas.append({"serie": s, "tipo": tipo, "regla": expl}); break
NO_IMPORTA = {"bis:WS_CBPOL.M.XM", "bis:WS_EER.M.R.B.XM"}  # tipo oficial y TCE del euro: la composición no cambia el dato
for f in filas:
    f["importa"] = f["serie"] not in NO_IMPORTA and "EU27" not in f["serie"] and "G4E" not in f["serie"]
C = {"series_zona_euro": len(filas),
     "fija_donde_importa": [f["serie"] for f in filas if f["tipo"] == "fija_actual" and f["importa"]],
     "cambiante": [f["serie"] for f in filas if f["tipo"] == "cambiante"],
     "fija_actual": [f["serie"] for f in filas if f["tipo"] == "fija_actual"]}
print("series de zona euro/UE en la curada:", len(filas), "| cambiante:", len(C["cambiante"]), "| fija:", len(C["fija_actual"]),
      "| fija donde la composición importa:", len(C["fija_donde_importa"]), C["fija_donde_importa"])
for f in filas: print("  ", f["tipo"], f["serie"])
json.dump(C, open(OUT / "a3_cifras_zonaeuro.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
