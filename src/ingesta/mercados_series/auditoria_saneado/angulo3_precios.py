"""Auditoría ángulo 3 · parte PRECIOS. SOLO LECTURA.

Lee D:/tfm_corpus/mercados_series/precios_curados/<proveedor>/*.parquet (columnas mínimas) y calcula en memoria
rentabilidades para contar saltos; nunca imprime precios ni valores: solo recuentos, fechas, ids y porcentajes.
Guarda las cifras en a3_cifras_precios.json. Uso: python angulo3_precios.py
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path("D:/tfm_corpus/mercados_series")
REPO = _REPO
TAB = REPO / "results/ingesta/mercados_series/tablas"
CFG = REPO / "src/ingesta/mercados_series/config"
OUT = Path(__file__).resolve().parent
CORTE = pd.Timestamp("2026-11-13")
C: dict = {}

lista = yaml.safe_load(open(CFG / "lista_curada.yaml", encoding="utf-8"))
precios_lista = lista["precios"]
queda = {k: v for k, v in precios_lista.items() if v.get("decision") == "queda"}
C["lista_precios"] = len(precios_lista)
C["lista_precios_queda"] = len(queda)
aviso = {k: str(v.get("aviso", "")) for k, v in precios_lista.items()}
reut_lista = sorted(k for k, a in aviso.items() if "ticker reutilizado" in a)
reut_lista_queda = sorted(k for k in reut_lista if precios_lista[k].get("decision") == "queda")
sosp_lista = sorted(k for k, a in aviso.items() if "serie sospechosa" in a)
sosp_lista_queda = sorted(k for k in sosp_lista if precios_lista[k].get("decision") == "queda")
sosp_motivo_fuera = sorted(k for k, v in precios_lista.items() if v.get("decision") != "queda"
                           and "sospechosa" in str(v.get("motivo", "")))
C["lista_reutilizados"] = len(reut_lista)
C["lista_reutilizados_queda"] = len(reut_lista_queda)
C["lista_sospechosas"] = len(sosp_lista)
C["lista_sospechosas_queda"] = len(sosp_lista_queda)
C["lista_sospechosas_fuera_por_motivo"] = sosp_motivo_fuera
print(f"lista curada: {C['lista_precios']} precios ({C['lista_precios_queda']} queda); con aviso 'ticker reutilizado': "
      f"{len(reut_lista)} ({len(reut_lista_queda)} queda); con aviso 'serie sospechosa': {len(sosp_lista)} "
      f"({len(sosp_lista_queda)} queda); fuera con 'sospechosa' en el motivo: {sosp_motivo_fuera}")

# ---------------------------------------------------------------- sospechosas: conciliar 35/36/37
eda = pd.read_csv(TAB / "eda_precios.csv", dtype={"ticker": str})
sosp_eda = set(eda.loc[eda["serie_sospechosa"] == True, "ticker"])  # noqa: E712
est = pd.read_csv(TAB / "descargas_3b_estado.csv", dtype={"id": str})
sosp_est = set(est.loc[est["tipo"] == "serie_sospechosa", "id"])
pav = pd.read_csv(TAB / "precios_curados_avisos.csv", dtype={"ticker": str})
sosp_av = set(pav.loc[pav["tipo"] == "serie_sospechosa", "ticker"])
sosp_av_lista = set(pav.loc[(pav["tipo"] == "aviso_lista") & pav["nota"].astype(str).str.contains("serie sospechosa"),
                            "ticker"])
C["sospechosas"] = {"eda_precios_serie_sospechosa": len(sosp_eda), "estado_3b_tipo_serie_sospechosa": len(sosp_est),
                    "lista_curada_aviso": len(sosp_lista), "lista_curada_aviso_queda": len(sosp_lista_queda),
                    "avisos_tipo_serie_sospechosa": len(sosp_av), "avisos_aviso_lista_con_sospechosa": len(sosp_av_lista)}
C["sospechosas_diferencias"] = {
    "estado_menos_eda": sorted(sosp_est - sosp_eda), "eda_menos_estado": sorted(sosp_eda - sosp_est),
    "estado_menos_avisos": sorted(sosp_est - sosp_av), "eda_menos_avisos": sorted(sosp_eda - sosp_av),
    "lista_menos_estado": sorted(set(sosp_lista) - sosp_est), "estado_menos_lista": sorted(sosp_est - set(sosp_lista)),
    "avisos_lista_menos_avisos_tipo": sorted(sosp_av_lista - sosp_av)}
print("sospechosas:", C["sospechosas"])
print("   diferencias:", C["sospechosas_diferencias"])
reut_av = set(pav.loc[(pav["tipo"] == "aviso_lista") & pav["nota"].astype(str).str.contains("ticker reutilizado"),
                      "ticker"])
C["avisos_reutilizado"] = len(reut_av)
C["reutilizado_lista_queda_sin_aviso_en_avisos"] = sorted(set(reut_lista_queda) - reut_av)
print("avisos 'ticker reutilizado' en precios_curados_avisos:", len(reut_av), "; de la lista (queda) sin él:",
      len(C["reutilizado_lista_queda_sin_aviso_en_avisos"]))
recort = set(pav.loc[(pav["tipo"] == "aviso_lista") & pav["nota"].astype(str).str.contains("historia recortada"), "ticker"])
corrbaja = set(pav.loc[(pav["tipo"] == "aviso_lista") & pav["nota"].astype(str).str.contains("correlación semanal baja"),
                       "ticker"])
nollega = set(pav.loc[pav["tipo"] == "no_llega_corte", "ticker"])
lim_rec = est.loc[est["id"] == "precios:universo:historia_recortada", "detalle"].astype(str)
n_rec_est = len(re.findall(r"[A-Z0-9]+\.(?:L|DE)", lim_rec.iloc[0])) if len(lim_rec) else None
C["ucits_historia_recortada_avisos"] = len(recort)
C["ucits_historia_recortada_estado_3b"] = n_rec_est
C["ucits_historia_recortada_solo_avisos"] = sorted(recort - set(re.findall(r"[A-Z0-9]+\.(?:L|DE|SW|AS|PA|MI)",
                                                                           lim_rec.iloc[0] if len(lim_rec) else "")))
C["ucits_corr_baja"] = len(corrbaja)
C["no_llega_corte"] = len(nollega)
print(f"UCITS historia recortada: {len(recort)} en avisos, {n_rec_est} en el estado del 3b; solo en avisos: "
      f"{C['ucits_historia_recortada_solo_avisos']}; UCITS correlación < 0,90: {len(corrbaja)}; no llegan al corte: "
      f"{len(nollega)}")

# ---------------------------------------------------------------- recorrido de los precios curados
fx_ini = {}
cur_ser = pq.read_table(RAIZ / "series/base_curada.parquet", columns=["serie", "fecha_referencia"],
                        filters=[("serie", "in", [f"ecb:EXR.D.{x}.EUR" for x in
                                                  "USD CNY HKD KRW INR TWD JPY GBP CHF SEK NOK DKK CAD AUD BRL MXN ZAR "
                                                  "SGD PLN TRY IDR THB MYR NZD ILS HUF CZK PHP RON ISK".split()])]).to_pandas()
for s, g in cur_ser.groupby("serie"):
    fx_ini[s.split(".")[2]] = (g["fecha_referencia"].min(), g["fecha_referencia"].max())
del cur_ser
SUB = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}

filas = []
saltos = []
huecos = []
fx_rows = []
for prov in ("yahoo", "coinbase"):
    for f in sorted((RAIZ / "precios_curados" / prov).glob("*.parquet")):
        t = pq.read_table(f, columns=["ticker", "sesion", "close", "split", "dividendo", "divisa"]).to_pandas()
        if t.empty:
            filas.append({"ticker": f.stem, "prov": prov, "sesiones": 0})
            continue
        tk = str(t["ticker"].iloc[0])
        t = t.sort_values("sesion")
        c = t["close"].to_numpy(float)
        sp = t["split"].fillna(0).to_numpy(float)
        dv = t["dividendo"].fillna(0).to_numpy(float)
        ev = ((sp != 0) & (sp != 1)) | (dv != 0)
        ev_sig = np.r_[ev[1:], False]
        prev = np.r_[np.nan, c[:-1]]
        with np.errstate(divide="ignore", invalid="ignore"):
            r = c / prev - 1
        grande = (np.abs(r) > 0.5) & ~ev & ~ev_sig & np.isfinite(r)
        ses = t["sesion"].to_numpy()
        for i in np.flatnonzero(grande):
            saltos.append({"ticker": tk, "sesion": pd.Timestamp(ses[i]).date().isoformat(),
                           "signo": "sube" if r[i] > 0 else "baja",
                           "x10_o_mas": bool(abs(np.log10(max(1 + r[i], 1e-12))) >= 1)})
        no_pos = int(((c <= 0) & np.isfinite(c)).sum())
        contra = int(((sp > 0) & (sp < 1)).sum())
        frac = int(((sp > 1) & (np.abs(sp - np.round(sp)) > 1e-9)).sum())
        gaps = np.diff(ses).astype("timedelta64[D]").astype(int) if len(ses) > 1 else np.array([0])
        big = np.flatnonzero(gaps > 365)
        for i in big:
            huecos.append({"ticker": tk, "desde": pd.Timestamp(ses[i]).date().isoformat(),
                           "hasta": pd.Timestamp(ses[i + 1]).date().isoformat(), "dias": int(gaps[i])})
        div = str(t["divisa"].iloc[-1])
        d_iso = SUB.get(div, div)
        if d_iso not in ("USD",):
            # EUR se convierte con USD/EUR; USX no está en divisas.SUBUNIDADES (sin FX)
            ini, fin = fx_ini.get("USD" if d_iso == "EUR" else d_iso, (None, None))
            s = pd.to_datetime(t["sesion"])
            fuera = ((s < ini) | (s > fin)) if ini is not None else pd.Series(True, index=s.index)
            fx_rows.append({"ticker": tk, "divisa": div, "sesiones": len(s), "sin_fx": int(fuera.sum()),
                            "sin_fx_desde_2007": int((fuera & (s >= "2007-01-01")).sum()),
                            "fx_existe": ini is not None})
        filas.append({"ticker": tk, "prov": prov, "sesiones": len(t), "desde": str(pd.Timestamp(ses[0]).date()),
                      "hasta": str(pd.Timestamp(ses[-1]).date()), "saltos50": int(grande.sum()), "no_pos": no_pos,
                      "contrasplits": contra, "split_frac": frac, "huecos_365": int(len(big)),
                      "max_hueco": int(gaps.max()), "divisa": div, "tras_corte": int((ses > np.datetime64(CORTE)).sum())})
pr = pd.DataFrame(filas)
sal = pd.DataFrame(saltos)
hu = pd.DataFrame(huecos)
fxd = pd.DataFrame(fx_rows)
C["precios_ficheros"] = len(pr)
C["precios_sesiones"] = int(pr["sesiones"].sum())
C["precios_sesiones_tras_corte"] = int(pr["tras_corte"].sum())
C["saltos50_total"] = int(len(sal))
C["saltos50_tickers"] = int(sal["ticker"].nunique()) if len(sal) else 0
C["saltos50_x10"] = int(sal["x10_o_mas"].sum()) if len(sal) else 0
C["saltos50_top"] = sal.groupby("ticker").size().sort_values(ascending=False).head(15).to_dict() if len(sal) else {}
C["saltos50_desde2007"] = int((sal["sesion"] >= "2007-01-01").sum()) if len(sal) else 0
C["cierres_no_positivos_tickers"] = pr.loc[pr["no_pos"] > 0, "ticker"].tolist()
C["contrasplits_eventos"] = int(pr["contrasplits"].sum())
C["contrasplits_tickers"] = int((pr["contrasplits"] > 0).sum())
C["split_fraccionario_eventos"] = int(pr["split_frac"].sum())
C["split_fraccionario_tickers"] = int((pr["split_frac"] > 0).sum())
C["huecos_365_tickers"] = int(pr.loc[pr["huecos_365"] > 0, "ticker"].nunique())
C["huecos_365_lista"] = hu.to_dict("records")
print(f"precios curados: {C['precios_ficheros']} ficheros, {C['precios_sesiones']} sesiones, tras corte "
      f"{C['precios_sesiones_tras_corte']}")
print(f"saltos |r| > 50 % sin split ni dividendo (ni en la sesión siguiente): {C['saltos50_total']} en "
      f"{C['saltos50_tickers']} tickers; de ellos ×10 o ÷10: {C['saltos50_x10']}; desde 2007: {C['saltos50_desde2007']}")
print("   top:", C["saltos50_top"])
print("cierres <= 0:", C["cierres_no_positivos_tickers"])
print(f"contrasplits: {C['contrasplits_eventos']} en {C['contrasplits_tickers']} tickers; splits fraccionarios: "
      f"{C['split_fraccionario_eventos']} en {C['split_fraccionario_tickers']} tickers")
print(f"ficheros con hueco > 365 días entre sesiones: {C['huecos_365_tickers']}:", C["huecos_365_lista"][:30])
# casos conocidos de la sonda
CONOC = ["AAPL", "ASML.AS", "CL=F", "NVDA", "SHEL.L", "^VIX", "XLF", "EWJ", "USO", "ETHA", "SAN.MC"]
C["casos_sonda"] = {k: (sal["ticker"] == k).sum().item() if len(sal) else 0 for k in CONOC}
print("saltos > 50 % en los casos de la sonda:", C["casos_sonda"])
# saltos ×10 o más sin aviso en la lista (probables errores de escala del proveedor, no movimientos reales)
sin_av = ~sal["ticker"].isin(set(reut_lista) | set(sosp_lista))
C["saltos_x10_sin_aviso"] = int((sal["x10_o_mas"] & sin_av).sum())
C["saltos_x10_sin_aviso_tickers"] = sorted(sal.loc[sal["x10_o_mas"] & sin_av, "ticker"].unique().tolist())
C["saltos50_sin_aviso_desde2007"] = int((sin_av & (sal["sesion"] >= "2007-01-01")).sum())
print(f"saltos ×10 sin aviso: {C['saltos_x10_sin_aviso']} en {len(C['saltos_x10_sin_aviso_tickers'])} tickers:",
      C["saltos_x10_sin_aviso_tickers"], "; saltos > 50 % sin aviso desde 2007:", C["saltos50_sin_aviso_desde2007"])
# saltos en reutilizados y sospechosos
C["saltos50_en_reutilizados"] = int(sal["ticker"].isin(reut_lista).sum()) if len(sal) else 0
C["saltos50_en_sospechosas"] = int(sal["ticker"].isin(sosp_lista).sum()) if len(sal) else 0
C["saltos50_tickers_sin_aviso"] = sorted(set(sal["ticker"]) - set(reut_lista) - set(sosp_lista)) if len(sal) else []
C["saltos50_tickers_sin_aviso_n"] = len(C["saltos50_tickers_sin_aviso"])
C["saltos50_sin_aviso_eventos"] = int((~sal["ticker"].isin(set(reut_lista) | set(sosp_lista))).sum()) if len(sal) else 0
print(f"saltos en reutilizados: {C['saltos50_en_reutilizados']}, en sospechosas: {C['saltos50_en_sospechosas']}; "
      f"tickers con salto y sin aviso: {C['saltos50_tickers_sin_aviso_n']} ({C['saltos50_sin_aviso_eventos']} saltos)")
print("   ", C["saltos50_tickers_sin_aviso"][:60])
# reutilizados: ¿mezcla de dos empresas en el mismo fichero? (hueco > 365 d o salto > 50 %)
rr = pr[pr["ticker"].isin(reut_lista)]
C["reutilizados_con_fichero_curado"] = int(len(rr))
C["reutilizados_con_hueco_365"] = rr.loc[rr["huecos_365"] > 0, "ticker"].tolist()
C["reutilizados_con_salto50"] = rr.loc[rr["saltos50"] > 0, "ticker"].tolist()
print(f"reutilizados con fichero curado: {len(rr)}; con hueco > 1 año: {C['reutilizados_con_hueco_365']}; con salto > 50 %: "
      f"{len(C['reutilizados_con_salto50'])}")
# FX
fxs = fxd.groupby("divisa").agg(tickers=("ticker", "size"), sesiones=("sesiones", "sum"), sin_fx=("sin_fx", "sum"),
                                sin_fx_desde_2007=("sin_fx_desde_2007", "sum"), fx_existe=("fx_existe", "all"))
fxs["pct_sin_fx"] = (100 * fxs["sin_fx"] / fxs["sesiones"]).round(1)
print("FX de los precios no USD (sesiones fuera del rango del fixing del BCE en la curada):\n", fxs.to_string())
C["fx_por_divisa"] = {k: {"tickers": int(v["tickers"]), "sesiones": int(v["sesiones"]), "sin_fx": int(v["sin_fx"]),
                          "sin_fx_desde_2007": int(v["sin_fx_desde_2007"]),
                          "pct_sin_fx": float(v["pct_sin_fx"]), "fx_existe": bool(v["fx_existe"])} for k, v in fxs.iterrows()}
C["fx_rangos"] = {k: [str(a.date()), str(b.date())] for k, (a, b) in fx_ini.items()}
C["fx_sin_total"] = int(fxd["sin_fx"].sum())
C["fx_sin_desde_2007"] = int(fxd["sin_fx_desde_2007"].sum())
C["fx_sin_desde_2007_tickers"] = fxd.loc[fxd["sin_fx_desde_2007"] > 0, "ticker"].tolist()
print("sesiones no USD sin fixing (o con fixing caducado) desde 2007:", C["fx_sin_desde_2007"], C["fx_sin_desde_2007_tickers"])
C["fx_sesiones_no_usd"] = int(fxd["sesiones"].sum())
print("rangos FX:", C["fx_rangos"])

# ---------------------------------------------------------------- supervivencia S&P 500
sys.path.insert(0, str(REPO / "src"))
from ingesta.mercados_series import seleccion  # noqa: E402  (función pura, sin escritura)
tramos = pq.read_table(RAIZ / "constituyentes/sp500.parquet").to_pandas()
inv = pd.read_csv(TAB / "inventario_precios.csv", dtype={"ticker": str})
clases = dict(zip(inv["ticker"], inv["clase"]))
cob = seleccion.cobertura_tramos_sp500(tramos, inv, clases)
res = seleccion.resumen_cobertura_sp500(cob).set_index("metrica")["valor"]
C["sp500_recalculado"] = {k: (float(v) if v is not None else None) for k, v in res.items()}
print("S&P 500 recalculado con seleccion.cobertura_tramos_sp500:", C["sp500_recalculado"])
reut_hoy = set(cob.loc[cob["reutilizado"], "ticker_yahoo"])
C["reutilizados_lista_no_recalculados"] = sorted(set(reut_lista) - reut_hoy)
C["reutilizados_recalculados_no_lista"] = sorted(reut_hoy - set(reut_lista))
print("reutilizados en la lista y no al recalcular:", C["reutilizados_lista_no_recalculados"],
      "; al recalcular y no en la lista:", C["reutilizados_recalculados_no_lista"])
# alternativa: con los precios curados y sesiones reales (no rango desde-hasta)
curados = {r.ticker: r for r in pr.itertuples()}
cob["ticker_yahoo"] = cob["ticker_yahoo"].astype(str)
desde_2007 = cob.copy()
desde_2007["alta"] = desde_2007["alta"].clip(lower=pd.Timestamp("2007-01-01"))
desde_2007["d"] = (desde_2007["fin"] - desde_2007["alta"]).dt.days.clip(lower=0)
ini = pd.concat([pd.to_datetime(desde_2007["desde"]), desde_2007["alta"]], axis=1).max(axis=1)
fin = pd.concat([pd.to_datetime(desde_2007["hasta"]) + pd.Timedelta(days=1), desde_2007["fin"]], axis=1).min(axis=1)
desde_2007["cub"] = (fin - ini).dt.days.where(desde_2007["tiene_fichero"], 0).fillna(0).clip(lower=0)
ok7 = ~desde_2007["reutilizado"]
C["sp500_pct_dias_desde_2007"] = round(100 * desde_2007.loc[ok7, "cub"].sum() / desde_2007["d"].sum(), 2)
C["sp500_pct_dias_desde_2016"] = None
d16 = cob.copy()
d16["alta"] = d16["alta"].clip(lower=pd.Timestamp("2016-01-01"))
d16["d"] = (d16["fin"] - d16["alta"]).dt.days.clip(lower=0)
ini = pd.concat([pd.to_datetime(d16["desde"]), d16["alta"]], axis=1).max(axis=1)
fin = pd.concat([pd.to_datetime(d16["hasta"]) + pd.Timedelta(days=1), d16["fin"]], axis=1).min(axis=1)
d16["cub"] = (fin - ini).dt.days.where(d16["tiene_fichero"], 0).fillna(0).clip(lower=0)
C["sp500_pct_dias_desde_2016"] = round(100 * d16.loc[~d16["reutilizado"], "cub"].sum() / d16["d"].sum(), 2)
print(f"cobertura días-tramo S&P 500 desde 2007: {C['sp500_pct_dias_desde_2007']} %; desde 2016: {C['sp500_pct_dias_desde_2016']} %")
# miembros vivos el día del corte y miembros por fecha
for f_ in ("2008-09-15", "2016-01-04", "2026-11-13"):
    d = pd.Timestamp(f_)
    viv = cob[(cob["alta"] <= d) & (cob["fin"] > d)]
    con = viv[viv["solapa"] & ~viv["reutilizado"] & (pd.to_datetime(viv["desde"]) <= d) & (pd.to_datetime(viv["hasta"]) >= d)]
    C[f"sp500_miembros_{f_}"] = [int(len(viv)), int(len(con))]
    print(f"S&P 500 el {f_}: {len(viv)} miembros en los tramos, {len(con)} con precio ese día")
sup = pd.read_csv(TAB / "supervivencia_cobertura.csv", dtype={"ticker": str})
C["supervivencia_grupos"] = sup.groupby("grupo").agg(n=("ticker", "size"),
                                                     con_precio=("sesiones_con_precio", lambda s: int((s > 0).sum())),
                                                     frac_ponderada=("fraccion", "mean")).round(3).to_dict("index")
print("supervivencia_cobertura.csv por grupo:", C["supervivencia_grupos"])
# salidos del índice
sal_idx = cob[cob["fin"] <= CORTE]
C["sp500_tramos_cerrados"] = int(len(sal_idx))
C["sp500_tramos_cerrados_sin_precio"] = int((~sal_idx["solapa"] | sal_idx["reutilizado"]).sum())
print(f"tramos cerrados (salidos): {C['sp500_tramos_cerrados']}, sin precio del miembro: {C['sp500_tramos_cerrados_sin_precio']}")

json.dump(C, open(OUT / "a3_cifras_precios.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("ok: a3_cifras_precios.json")
