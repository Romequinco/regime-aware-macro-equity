"""Auditoría ángulo 3 · capas de fecha conservadoras: dónde el retraso añadido es grande frente al retraso original
(posible pérdida de información por prudencia). SOLO LECTURA de registro_cambios.parquet; solo días y recuentos.
Uso: python angulo3_capas.py  → a3_cifras_capas.json"""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
reg = pq.read_table("D:/tfm_corpus/mercados_series/series/registro_cambios.parquet",
                    columns=["serie", "fecha_referencia", "fecha_publicacion_antes", "fecha_publicacion_despues",
                             "retraso_dias", "seccion", "grupo", "regla", "reconstruida", "h15", "derivada",
                             "en_base_curada", "con_tope"]).to_pandas()
r = reg[reg["en_base_curada"] & (reg["retraso_dias"] > 0)].copy()
for c in ("seccion", "grupo", "regla"):
    r[c] = r[c].astype(str)
r["lag_antes"] = (r["fecha_publicacion_antes"] - r["fecha_referencia"]).dt.days
r["lag_despues"] = (r["fecha_publicacion_despues"] - r["fecha_referencia"]).dt.days
C = {"filas_retrasadas": int(len(r))}
# solo prudencia: sin reconstruidas (fecha de creación real de la fuente), en la ventana 2007+
w = r[(r["fecha_referencia"] >= "2007-01-01") & ~r["reconstruida"]]
C["ventana2007_sin_reconstruidas_filas"] = int(len(w))
g = w.groupby(["seccion", "grupo", "regla"]).agg(filas=("serie", "size"), series=("serie", "nunique"),
                                                  retraso_med=("retraso_dias", "median"),
                                                  retraso_p90=("retraso_dias", lambda s: s.quantile(.9)),
                                                  lag_antes_med=("lag_antes", "median"),
                                                  lag_despues_med=("lag_despues", "median"))
g["x_lag"] = (g["lag_despues_med"] / g["lag_antes_med"].where(g["lag_antes_med"] > 0)).round(1)
g = g.sort_values("retraso_med", ascending=False)
pd.set_option("display.width", 250)
print("ventana 2007+, sin reconstruidas, por regla (días):\n", g.round(1).head(40).to_string())
sosp = g[(g["retraso_med"] >= 14) & ((g["x_lag"] >= 2) | g["x_lag"].isna())]
print("\nreglas con retraso mediano >= 14 días y que al menos doblan el retraso original:\n", sosp.round(1).to_string())
C["reglas_retraso_grande_2007"] = {f"{a}/{b}/{c}": {k: (float(v) if pd.notna(v) else None) for k, v in row.items()}
                                   for (a, b, c), row in sosp.iterrows()}
C["filas_reglas_retraso_grande_2007"] = int(sosp["filas"].sum())
# días de información perdidos en la ventana: suma de retraso de esas reglas
C["dias_fila_perdidos_reglas_grandes_2007"] = float(w[w.set_index(["seccion", "grupo", "regla"]).index.isin(sosp.index)]
                                                    ["retraso_dias"].sum())
# mercado diario: todo el grupo
md = w[w["grupo"] == "mercado_diario"]
C["mercado_diario_2007"] = {"filas": int(len(md)), "mediana": float(md["retraso_dias"].median()),
                            "p90": float(md["retraso_dias"].quantile(.9)),
                            "pct_1_dia": round(100 * (md["retraso_dias"] == 1).mean(), 1)}
print("\nmercado diario 2007+:", C["mercado_diario_2007"])
# por regla del mercado diario
gm = md.groupby("regla").agg(filas=("serie", "size"), series=("serie", "nunique"), med=("retraso_dias", "median"),
                             p90=("retraso_dias", lambda s: s.quantile(.9)), lag_antes=("lag_antes", "median"),
                             lag_despues=("lag_despues", "median"))
print(gm.to_string())
C["mercado_diario_por_regla_2007"] = gm.reset_index().to_dict("records")
rba = sorted(r.loc[r["regla"] == "rba_diario", "serie"].unique().tolist())
C["rba_series"] = rba
print("series rba_diario:", rba)
# tope del primer vintage
C["con_tope"] = int(reg["con_tope"].sum())
# reconstruidas en la ventana: historia que existe pero no era pública (fuentes creadas después)
rec = r[(r["fecha_referencia"] >= "2007-01-01") & r["reconstruida"]]
gr = rec.groupby("regla").agg(filas=("serie", "size"), series=("serie", "nunique"), med=("retraso_dias", "median"))
print("\nreconstruidas en 2007+ (fuente creada después del dato: no es prudencia, es la realidad):\n", gr.to_string())
C["reconstruidas_2007"] = {k: {"filas": int(v["filas"]), "series": int(v["series"]), "mediana": float(v["med"])}
                           for k, v in gr.iterrows()}
json.dump(C, open(OUT / "a3_cifras_capas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("ok: a3_cifras_capas.json")
