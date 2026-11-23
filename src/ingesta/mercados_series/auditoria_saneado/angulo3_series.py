"""Auditoría ángulo 3 (sanidad, consistencia, limitaciones) · parte SERIES. SOLO LECTURA.

Lee D:/tfm_corpus/mercados_series/series/*.parquet con columnas mínimas; nunca imprime valores,
solo recuentos, fechas, ids y porcentajes. Guarda las cifras en a3_cifras_series.json (carpeta del script).
Uso:  python angulo3_series.py
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path("D:/tfm_corpus/mercados_series")
SER = RAIZ / "series"
REPO = _REPO
TAB = REPO / "results/ingesta/mercados_series/tablas"
OUT = Path(__file__).resolve().parent
CORTE = pd.Timestamp("2026-11-13")
C: dict = {}


def leer(f, cols):
    return pq.read_table(f, columns=cols, read_dictionary=[c for c in cols if c in ("serie", "vintage", "unidad",
                                                                                     "divisa", "fuente", "capa",
                                                                                     "grupo", "regla", "seccion")]).to_pandas()


# ---------------------------------------------------------------- 0. recuentos básicos
cur = leer(SER / "base_curada.parquet", ["serie", "fecha_referencia", "fecha_publicacion", "vintage", "valor",
                                          "unidad", "divisa", "fuente", "metodo_publicacion"])
C["curada_filas"] = len(cur)
C["curada_series"] = int(cur["serie"].nunique())
C["curada_max_pub"] = str(cur["fecha_publicacion"].max().date())
C["curada_filas_pub_tras_corte"] = int((cur["fecha_publicacion"] > CORTE).sum())
C["curada_filas_pub_antes_ref"] = int((cur["fecha_publicacion"] < cur["fecha_referencia"]).sum())
C["curada_fuentes"] = int(cur["fuente"].nunique())
print("0) base curada:", C["curada_filas"], "filas,", C["curada_series"], "series,", C["curada_fuentes"], "fuentes;",
      "max fecha_publicacion", C["curada_max_pub"], "; filas tras corte", C["curada_filas_pub_tras_corte"],
      "; pub<ref", C["curada_filas_pub_antes_ref"])
base_meta = pq.ParquetFile(SER / "base_series.parquet").metadata
C["base_filas"] = base_meta.num_rows
bs = leer(SER / "base_series.parquet", ["serie"])
C["base_series"] = int(bs["serie"].nunique())
del bs
print("0) base de trabajo:", C["base_filas"], "filas,", C["base_series"], "series")

# ---------------------------------------------------------------- 1. unidades y divisas por serie
g = cur.groupby("serie", observed=True)
n_uni = g["unidad"].nunique(dropna=False)
n_div = g["divisa"].nunique(dropna=False)
C["series_varias_unidades"] = sorted(n_uni[n_uni > 1].index.tolist())
C["series_varias_divisas"] = sorted(n_div[n_div > 1].index.tolist())
uni_null = g["unidad"].apply(lambda s: s.isna().any())
C["series_unidad_nula"] = sorted(uni_null[uni_null].index.tolist())
print("1) series con >1 unidad:", len(C["series_varias_unidades"]), C["series_varias_unidades"][:10])
print("1) series con >1 divisa:", len(C["series_varias_divisas"]), C["series_varias_divisas"][:10])
print("1) series con alguna unidad nula:", len(C["series_unidad_nula"]))

# 1b. cambios de escala entre vintages consecutivos (ratio de medianas de |valor| en fechas comunes)
ESC = {"fred:BCNSDODNS", "fred:BOGMBASE", "fred:CMDEBT", "fred:REVOLSL", "fred:TNWBSHNO", "fred:TOTALSL"}
mv = cur[cur["metodo_publicacion"].astype(str) == "vintage_exacto"]
filas_esc = []
for s, d in mv.groupby("serie", observed=True):
    if d["vintage"].nunique() < 2:
        continue
    piv = d.pivot_table(index="fecha_referencia", columns="vintage", values="valor", aggfunc="first", observed=True)
    piv = piv.reindex(sorted(piv.columns), axis=1)
    cols = list(piv.columns)
    for a, b in zip(cols[:-1], cols[1:]):
        ab = piv[[a, b]].dropna()
        ab = ab[(ab[a] != 0) & (ab[b] != 0)]
        if len(ab) < 3:
            continue
        r = np.log10((ab[b].abs() / ab[a].abs()).median())
        if abs(r) >= 0.9:
            filas_esc.append({"serie": s, "vintage_antes": a, "vintage_despues": b, "log10": round(float(r), 2),
                              "comunes": len(ab)})
esc = pd.DataFrame(filas_esc)
C["escala_vintage_restantes"] = esc.to_dict("records") if len(esc) else []
C["escala_vintage_restantes_series"] = sorted(esc["serie"].unique().tolist()) if len(esc) else []
C["escala_vintage_6_corregidas_sin_salto"] = sorted(ESC - set(C["escala_vintage_restantes_series"]))
print("1b) saltos de escala (|log10| >= 0.9) entre vintages consecutivos en la curada:",
      len(esc), "pares en", len(C["escala_vintage_restantes_series"]), "series:", C["escala_vintage_restantes_series"])
print("1b) de las 6 escaladas por vintage, sin salto restante:", len(C["escala_vintage_6_corregidas_sin_salto"]))
del mv

# 1c. saltos ×100/×1000 dentro de una misma serie (último valor por fecha_referencia): ratio de medianas
# de |valor| entre años consecutivos, y entre observaciones consecutivas con ratio ≈ 10^k (k=2,3)
ult = cur.sort_values(["serie", "fecha_referencia", "fecha_publicacion"]).drop_duplicates(
    ["serie", "fecha_referencia"], keep="last")
ult["anio"] = ult["fecha_referencia"].dt.year
med = ult.assign(a=ult["valor"].abs()).groupby(["serie", "anio"], observed=True)["a"].median().reset_index()
med = med[med["a"] > 0]
med["prev"] = med.groupby("serie", observed=True)["a"].shift()
med["l"] = np.log10(med["a"] / med["prev"])
uni = ult.groupby("serie", observed=True)["unidad"].first().astype(str)
med["unidad"] = med["serie"].map(uni)
sosp = med[(med["l"].abs() >= 1.7)].copy()
# descarta tipos y tasas cerca de cero (el ratio no tiene sentido si |mediana| < 0,5 en % o índices de variación)
sosp["cerca_cero"] = (sosp[["a", "prev"]].min(axis=1) < 0.5)
C["salto_anual_x50_total"] = int(len(sosp))
C["salto_anual_x50_series"] = int(sosp["serie"].nunique())
lejos = sosp[~sosp["cerca_cero"]]
C["salto_anual_x50_lejos_de_cero"] = lejos[["serie", "anio", "l", "unidad"]].assign(
    l=lambda d: d["l"].round(2)).to_dict("records")
print("1c) años con mediana |valor| ×50 o más frente al año anterior:", C["salto_anual_x50_total"], "en",
      C["salto_anual_x50_series"], "series; lejos de cero:", len(lejos))
for r in C["salto_anual_x50_lejos_de_cero"]:
    print("    ", r)
# saltos puntuales consecutivos ≈ ×100 / ×1000 (±5 %)
ult["prev"] = ult.groupby("serie", observed=True)["valor"].shift()
ok = ult["prev"].notna() & (ult["prev"] != 0) & (ult["valor"] != 0)
lr = np.log10((ult.loc[ok, "valor"] / ult.loc[ok, "prev"]).abs())
k = lr.round()
cerca = (k.abs().isin([2, 3])) & ((lr - k).abs() < 0.02)
pts = ult.loc[ok].loc[cerca]
mag = ult.loc[ok].loc[cerca, ["valor", "prev"]].abs().min(axis=1)
pts = pts.assign(min_abs=mag.values)
pts_lejos = pts[pts["min_abs"] >= 0.5]
C["salto_puntual_x100_x1000"] = int(cerca.sum())
C["salto_puntual_x100_x1000_lejos_cero"] = int(len(pts_lejos))
C["salto_puntual_series_lejos_cero"] = pts_lejos.groupby("serie", observed=True).size().sort_values(
    ascending=False).head(15).to_dict()
print("1c) observaciones consecutivas con ratio ≈ ×100 o ×1000 (±5 %):", C["salto_puntual_x100_x1000"],
      "; con |valor| >= 0,5 en ambos lados:", C["salto_puntual_x100_x1000_lejos_cero"], C["salto_puntual_series_lejos_cero"])

# 1d. unidades % con todos los valores en [-1,1] (¿tanto por uno sin escalar?) y tanto por uno con mediana > 1
uu = ult.groupby("serie", observed=True).agg(unidad=("unidad", "first"), mx=("valor", lambda s: s.abs().max()),
                                              md=("valor", lambda s: s.abs().median()))
uu["unidad"] = uu["unidad"].astype(str)
pct_pequena = uu[uu["unidad"].str.contains("%") & (uu["mx"] <= 1)]
tpu_grande = uu[uu["unidad"].str.contains("tanto por uno") & (uu["md"] > 1)]
C["pct_todo_en_menos1_1"] = sorted(pct_pequena.index.tolist())
C["tanto_por_uno_con_mediana_mayor_1"] = sorted(tpu_grande.index.tolist())
C["tanto_por_uno_restantes"] = sorted(uu[uu["unidad"].str.contains("tanto por uno")].index.tolist())
print("1d) series en % con todo |valor| <= 1:", C["pct_todo_en_menos1_1"])
print("1d) series en tanto por uno con mediana > 1:", C["tanto_por_uno_con_mediana_mayor_1"])
print("1d) series que siguen en tanto por uno:", C["tanto_por_uno_restantes"])

# ---------------------------------------------------------------- 1e. registro de cambios: escalas y homogeneización
reg = leer(SER / "registro_cambios.parquet", ["serie", "retraso_dias", "capa", "seccion", "grupo", "regla",
                                               "escala", "homogeneizacion", "factor_escala", "unidad_antes",
                                               "unidad_despues", "en_base_curada", "fecha_referencia",
                                               "reconstruida", "h15", "derivada", "con_tope"])
C["registro_filas"] = len(reg)
e = reg[reg["escala"]]
C["registro_escala_vintage_series"] = int(e["serie"].nunique())
C["registro_escala_vintage_filas"] = int(len(e))
h = reg[reg["homogeneizacion"]]
C["registro_homog_series"] = int(h["serie"].nunique())
C["registro_homog_filas"] = int(len(h))
x100 = h[h["factor_escala"] == 100]
C["registro_x100_filas"] = int(len(x100))
C["registro_x100_series"] = int(x100["serie"].nunique())
C["registro_x100_filas_en_curada"] = int(x100["en_base_curada"].sum())
print("1e) registro: escala por vintage:", C["registro_escala_vintage_series"], "series,", C["registro_escala_vintage_filas"],
      "filas; homogeneización:", C["registro_homog_series"], "series,", C["registro_homog_filas"], "filas; ×100:",
      C["registro_x100_series"], "series,", C["registro_x100_filas"], "filas (en curada:", C["registro_x100_filas_en_curada"], ")")
# las ×100 escaladas: ¿la base curada tiene filas de esas series con la unidad antigua?
for s in sorted(x100["serie"].unique()):
    ua = set(x100.loc[x100["serie"] == s, "unidad_antes"].astype(str))
    ucur = set(cur.loc[cur["serie"] == s, "unidad"].astype(str))
    if ua & ucur:
        print("   ¡OJO! unidad antigua sigue en curada:", s, ua & ucur)
C["x100_con_unidad_antigua_en_curada"] = [s for s in sorted(x100["serie"].unique())
                                         if set(x100.loc[x100["serie"] == s, "unidad_antes"].astype(str))
                                         & set(cur.loc[cur["serie"] == s, "unidad"].astype(str))]
# filas ×100 en curada vs filas totales de esas series en curada
nx = cur[cur["serie"].isin(x100["serie"].unique())].groupby("serie", observed=True).size()
C["x100_filas_series_en_curada"] = int(nx.sum())
print("1e) filas en curada de las series ×100:", C["x100_filas_series_en_curada"], "frente a registradas ×100 en curada",
      C["registro_x100_filas_en_curada"])

# ---------------------------------------------------------------- 3. alias con historia anterior
al = pq.read_table(SER / "alias.parquet", columns=["alias", "canonico"]).to_pandas()
C["alias_n"] = len(al)
need = set(al["alias"]) | set(al["canonico"])
pt = pq.read_table(SER / "base_series.parquet", columns=["serie", "fecha_referencia", "fecha_publicacion"],
                   filters=[("serie", "in", list(need))]).to_pandas()
ini = pt.groupby("serie").agg(ref0=("fecha_referencia", "min"), pub0=("fecha_publicacion", "min"))
del pt
cini = cur.groupby("serie", observed=True).agg(cref0=("fecha_referencia", "min"), cpub0=("fecha_publicacion", "min"))
al = al.join(ini, on="alias").join(cini, on="canonico")
al = al.join(ini.rename(columns={"ref0": "can_ref0_base", "pub0": "can_pub0_base"}), on="canonico")
Y2K = pd.Timestamp("2000-01-01")
for base_col, can_col, tag in (("pub0", "can_pub0_base", "pub_base"), ("pub0", "cpub0", "pub_curada"),
                               ("ref0", "cref0", "ref_curada")):
    mas = al[al[base_col] < al[can_col]]
    C[f"alias_antes_canonico_{tag}"] = int(len(mas))
    C[f"alias_antes_canonico_y_pre2000_{tag}"] = int((mas[base_col] < Y2K).sum())
    C[f"alias_pre2000_canonico_desde_2000_{tag}"] = int(((mas[base_col] < Y2K) & (mas[can_col] >= Y2K)).sum())
    print(f"3) [{tag}] alias que empiezan antes que su canónico: {len(mas)}; con inicio < 2000: "
          f"{C[f'alias_antes_canonico_y_pre2000_{tag}']}; y canónico desde 2000 (toda la historia previa perdida): "
          f"{C[f'alias_pre2000_canonico_desde_2000_{tag}']}")
mas = al[(al["pub0"] < al["cpub0"]) & (al["pub0"] < Y2K)].copy()
mas["anios_previos"] = ((mas["cpub0"].clip(upper=Y2K) - mas["pub0"]).dt.days / 365.25).round(1)
mas = mas.sort_values("anios_previos", ascending=False)
C["alias_pre2000_lista"] = [{"alias": r.alias, "canonico": r.canonico, "pub_alias": str(r.pub0.date()),
                             "pub_canonico_curada": str(r.cpub0.date()), "anios_previos_antes_2000": r.anios_previos}
                            for r in mas.itertuples()]
for r in C["alias_pre2000_lista"]:
    print("    ", r)
# definición del notebook 04 (inicio de publicación en la base de trabajo, alias frente a canónico)
nb = al[al["pub0"] < al["can_pub0_base"]].copy()
nb["anios_previos"] = ((nb["can_pub0_base"] - nb["pub0"]).dt.days / 365.25).round(1)
C["alias_def_nb04_lista"] = [{"alias": r.alias, "canonico": r.canonico, "pub_alias": str(r.pub0.date()),
                              "pub_canonico_base": str(r.can_pub0_base.date()), "anios_previos": r.anios_previos,
                              "pre2000": bool(r.pub0 < Y2K), "canonico_desde_2000": bool(r.can_pub0_base >= Y2K)}
                             for r in nb.sort_values("anios_previos", ascending=False).itertuples()]
print("3) definición del 04 (pub en base, alias < canónico):", len(nb), "; con inicio < 2000:",
      int((nb["pub0"] < Y2K).sum()), "; canónico desde 2000:", int((nb["can_pub0_base"] >= Y2K).sum()))
for r in C["alias_def_nb04_lista"]:
    print("    ", r)
ref = al[al["ref0"] < al["cref0"]]
C["alias_ref_lista"] = [{"alias": r.alias, "canonico": r.canonico, "ref_alias": str(r.ref0.date()),
                         "ref_canonico_curada": str(r.cref0.date())} for r in ref.itertuples()]
print("3) por fecha de referencia (periodos que el canónico curado no tiene):", C["alias_ref_lista"])
# canónicos que no están en la curada
C["alias_canonico_fuera_curada"] = sorted(set(al["canonico"]) - set(cini.index))

# ---------------------------------------------------------------- 5. cobertura desde 2000
c0 = cur.groupby("serie", observed=True)["fecha_publicacion"].min()
C["curada_series_pub_desde_2000"] = int((c0 <= pd.Timestamp("2001-01-02")).sum())
C["curada_pct_series_pub_desde_2000"] = round(100 * C["curada_series_pub_desde_2000"] / len(c0), 1)
r0 = cur.groupby("serie", observed=True)["fecha_referencia"].min()
C["curada_series_ref_desde_2000"] = int((r0 <= pd.Timestamp("2000-12-31")).sum())
C["curada_pct_series_ref_desde_2000"] = round(100 * C["curada_series_ref_desde_2000"] / len(r0), 1)
print("5) series curadas con primera publicación <= 2001-01-02:", C["curada_series_pub_desde_2000"], "de", len(c0),
      f"({C['curada_pct_series_pub_desde_2000']} %); por fecha de referencia <= 2000: {C['curada_series_ref_desde_2000']}"
      f" ({C['curada_pct_series_ref_desde_2000']} %)")
fu = cur.groupby("serie", observed=True)["fuente"].first().astype(str)
pf = pd.DataFrame({"f": fu, "ok": c0 <= pd.Timestamp("2001-01-02")}).groupby("f")["ok"].agg(["sum", "count"])
C["desde_2000_por_fuente"] = {k: f"{int(v['sum'])}/{int(v['count'])}" for k, v in pf.iterrows()}
print("5) desde 2000 por fuente:", C["desde_2000_por_fuente"])

# ---------------------------------------------------------------- 5b. divisas y FX disponible
divs = cur["divisa"].dropna().astype(str).value_counts()
C["curada_divisas"] = divs.to_dict()
fx = {s.split(".")[2] for s in cur["serie"].unique() if str(s).startswith("ecb:EXR.D.")}
C["fx_bce_en_curada"] = sorted(fx)
cny = cur[cur["divisa"].astype(str) == "CNY"]["serie"].unique().tolist()
C["series_cny"] = sorted(map(str, cny))
print("5b) divisas en la base curada:", C["curada_divisas"])
print("5b) FX del BCE en la curada:", C["fx_bce_en_curada"])
print("5b) series en CNY:", C["series_cny"], "; ¿hay ecb:EXR.D.CNY.EUR en la curada?", "CNY" in fx)
fxbase = pq.read_table(SER / "base_series.parquet", columns=["serie"], filters=[("serie", "==", "ecb:EXR.D.CNY.EUR")]).num_rows
C["fx_cny_filas_base_trabajo"] = int(fxbase)
print("5b) filas de ecb:EXR.D.CNY.EUR en la base de trabajo:", fxbase)

# ---------------------------------------------------------------- 6. capas de fecha: distribución del retraso
ret = reg[reg["en_base_curada"] & (reg["retraso_dias"] > 0)].copy()
C["retrasadas_en_curada"] = int(len(ret))
C["adelantadas_registro"] = int((reg["retraso_dias"] < 0).sum())
C["retrasadas_total_registro"] = int((reg["retraso_dias"] > 0).sum())
print("6) filas retrasadas en curada:", C["retrasadas_en_curada"], "; en todo el registro:", C["retrasadas_total_registro"],
      "; adelantadas:", C["adelantadas_registro"])
ret["seccion"] = ret["seccion"].astype(str)
ret["grupo"] = ret["grupo"].astype(str)
ret["regla"] = ret["regla"].astype(str)
ret["capa"] = ret["capa"].astype(str)


def resumen(df, por):
    q = df.groupby(por)["retraso_dias"].describe(percentiles=[.5, .9])
    q["series"] = df.groupby(por)["serie"].nunique()
    q["dias_retraso_total"] = df.groupby(por)["retraso_dias"].sum()
    return q[["count", "series", "50%", "90%", "max", "dias_retraso_total"]].sort_values("count", ascending=False)


qc = resumen(ret, "capa")
qg = resumen(ret, ["seccion", "grupo"])
qr = resumen(ret, ["seccion", "grupo", "regla"])
ret["fuente"] = ret["serie"].astype(str).str.split(":").str[0]
qf = resumen(ret, "fuente")
pd.set_option("display.width", 220)
print("6) por capa:\n", qc.round(1).to_string())
print("6) por sección/grupo:\n", qg.round(1).to_string())
print("6) por prefijo de id:\n", qf.round(1).to_string())
print("6) reglas con mediana > 30 días:\n", qr[qr["50%"] > 30].round(1).to_string())
C["retraso_por_capa"] = {k: {"filas": int(v["count"]), "series": int(v["series"]), "mediana": float(v["50%"]),
                             "p90": float(v["90%"]), "max": float(v["max"])} for k, v in qc.iterrows()}
C["retraso_por_grupo"] = {f"{a}/{b}": {"filas": int(v["count"]), "series": int(v["series"]), "mediana": float(v["50%"]),
                                       "p90": float(v["90%"]), "max": float(v["max"])} for (a, b), v in qg.iterrows()}
C["retraso_por_fuente"] = {k: {"filas": int(v["count"]), "series": int(v["series"]), "mediana": float(v["50%"]),
                               "p90": float(v["90%"]), "max": float(v["max"])} for k, v in qf.iterrows()}
C["reglas_mediana_mayor_30"] = {f"{a}/{b}/{c}": {"filas": int(v["count"]), "series": int(v["series"]),
                                                 "mediana": float(v["50%"]), "p90": float(v["90%"]),
                                                 "max": float(v["max"])} for (a, b, c), v in qr[qr["50%"] > 30].iterrows()}
C["retraso_mas_30d"] = int((ret["retraso_dias"] > 30).sum())
C["retraso_mas_365d"] = int((ret["retraso_dias"] > 365).sum())
C["retraso_mas_30d_pre2000_pct"] = round(100 * (ret.loc[ret["retraso_dias"] > 30, "fecha_referencia"].dt.year < 2000).mean(), 1)
C["retraso_mas_30d_desde2007"] = int(((ret["retraso_dias"] > 30) & (ret["fecha_referencia"] >= "2007-01-01")).sum())
C["retraso_mas_365d_desde2007"] = int(((ret["retraso_dias"] > 365) & (ret["fecha_referencia"] >= "2007-01-01")).sum())
C["con_tope"] = int(reg["con_tope"].sum())
print("6) retrasos > 30 d:", C["retraso_mas_30d"], f"({C['retraso_mas_30d_pre2000_pct']} % antes de 2000); > 365 d:",
      C["retraso_mas_365d"], "; > 30 d con ref >= 2007:", C["retraso_mas_30d_desde2007"], "; > 365 d con ref >= 2007:",
      C["retraso_mas_365d_desde2007"])
big = ret[ret["retraso_dias"] > 365]
bb = big.groupby(["capa", "regla"]).agg(filas=("serie", "size"), series=("serie", "nunique"),
                                        mediana=("retraso_dias", "median"),
                                        desde2007=("fecha_referencia", lambda s: int((s >= "2007-01-01").sum())))
print("6) retrasos > 365 d por capa/regla:\n", bb.sort_values("filas", ascending=False).head(20).to_string())
C["retraso_mas_365d_por_capa_regla"] = {f"{a}/{b}": {k: (float(v) if k == "mediana" else int(v)) for k, v in r.items()}
                                       for (a, b), r in bb.sort_values("filas", ascending=False).head(20).iterrows()}
# días-retraso acumulados desde 2007 por grupo (pérdida de información en la ventana del estudio)
w = ret[ret["fecha_referencia"] >= "2007-01-01"]
qw = resumen(w, ["seccion", "grupo"])
C["retraso_por_grupo_desde2007"] = {f"{a}/{b}": {"filas": int(v["count"]), "mediana": float(v["50%"]),
                                                 "p90": float(v["90%"])} for (a, b), v in qw.iterrows()}
print("6) desde 2007 por sección/grupo:\n", qw.round(1).to_string())

json.dump(C, open(OUT / "a3_cifras_series.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("ok: a3_cifras_series.json")
