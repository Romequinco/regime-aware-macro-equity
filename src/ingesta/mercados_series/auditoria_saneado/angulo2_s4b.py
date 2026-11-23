"""Complemento de s4: filas anteriores a ALFRED (valor del primer vintage, ya revisado) que NO llevan el texto
«posible fuga de revisiones» en la nota de la base, y detalle de las series con fuga. Sin valores."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

C = Path("D:/tfm_corpus/mercados_series/series")
AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
print("top series con fuga (curada):", d["s4_fuga_curada"]["top_series"])
print("tipo por fuente (curada):", json.dumps(d["s4_fuga_curada"]["tipo_por_fuente"], ensure_ascii=False))
out = {}
for nombre in ("base_curada", "base_series"):
    t = pq.read_table(C / f"{nombre}.parquet", columns=["serie", "fuente", "vintage", "nota", "fecha_referencia"],
                      filters=[("fuente", "=", "fred_alfred")], read_dictionary=["serie", "nota", "vintage"]).to_pandas()
    cats = pd.Series(t["nota"].cat.categories)
    es = cats.str.contains("anterior a ALFRED", regex=False).to_numpy()
    fuga = cats.str.contains("posible fuga de revisiones", regex=False).to_numpy()
    codes = t["nota"].cat.codes.to_numpy()
    m = np.where(codes >= 0, es[np.clip(codes, 0, None)], False)
    f = np.where(codes >= 0, fuga[np.clip(codes, 0, None)], False)
    total = pq.ParquetFile(C / f"{nombre}.parquet").metadata.num_rows
    sub = t[m]
    desde2000 = sub[sub["fecha_referencia"] >= "2000-01-01"]
    out[nombre] = {"filas_anterior_alfred": int(m.sum()), "pct_base": round(100 * m.sum() / total, 2),
                   "series": int(sub["serie"].nunique()), "con_texto_fuga": int((m & f).sum()),
                   "filas_desde_2000": int(len(desde2000)), "series_desde_2000": int(desde2000["serie"].nunique()),
                   "fuga_mas_anterior_pct": round(100 * (m.sum() + d[f"s4_fuga_{'curada' if nombre == 'base_curada' else 'trabajo'}"]["filas_fuga"]) / total, 2)}
    vint = t[(t["vintage"].astype(str) != "unico")]
    out[nombre]["fred_alfred_filas_con_vintage_fecha"] = int(len(vint))
    out[nombre]["fred_alfred_series_con_vintage_fecha"] = int(vint["serie"].nunique())
    print(nombre, out[nombre])
    top = sub.groupby("serie", observed=True).size().sort_values(ascending=False).head(10)
    print(" top anteriores a ALFRED:", {str(k): int(v) for k, v in top.items()})
    out[nombre]["top"] = {str(k): int(v) for k, v in top.items()}
d["s4b_anterior_alfred"] = out
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
