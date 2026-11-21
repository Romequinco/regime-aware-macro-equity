"""Auditoría · ángulo 1 (huecos y nulos) · PRECIOS. SOLO LECTURA.

Lee precios/<proveedor>/*.parquet y precios_curados/<proveedor>/*.parquet fichero a fichero con pyarrow, solo las
columnas sesion, fecha_publicacion, mercado, ticker y open/close/volume para is_null(). Nunca imprime un precio.
Escribe angulo1_precios.json.

Uso: PYTHONPATH=<worktree>/src python angulo1_precios.py
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
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

WT = _REPO
sys.path.insert(0, str(WT / "src"))
from ingesta.mercados_series import eda, almacen, curada_precios  # noqa: E402  (solo funciones puras / lectura)

TAB = WT / "results/ingesta/mercados_series/tablas"
RAIZ = Path("D:/tfm_corpus/mercados_series")
CORTE = pd.Timestamp("2026-11-13")
OUT = Path(__file__).with_name("angulo1_precios.json")
R: dict = {}
_CAL: dict = {}


def cal(mercado):
    nombre = eda.CALENDARIO_MERCADO.get(mercado or "")
    if nombre not in _CAL:
        try:
            _CAL[nombre] = eda.sesiones_calendario(nombre) if nombre else None
        except Exception:
            _CAL[nombre] = None
    return nombre, _CAL[nombre]


def leer(f: Path, cols):
    t = pq.read_table(f, columns=cols)
    out = {}
    for c in cols:
        if c in ("open", "close", "volume"):
            out[c + "_nulo"] = pc.is_null(t[c], nan_is_null=True).to_numpy(zero_copy_only=False)
            if c == "volume":
                v = pc.fill_null(t[c], 0).to_numpy(zero_copy_only=False)
                out["vol_pos"] = np.nan_to_num(v.astype(float)) > 0
        else:
            out[c] = t[c].to_pandas()
    return pd.DataFrame(out)


def racha_max(pos: np.ndarray) -> int:
    """Mayor número de posiciones consecutivas (índices del calendario) en ``pos`` (ordenado)."""
    if not len(pos):
        return 0
    corte = np.flatnonzero(np.diff(pos) != 1)
    lens = np.diff(np.r_[-1, corte, len(pos) - 1])
    return int(lens.max())


def main():
    meta = pd.read_csv(TAB / "eda_precios.csv", usecols=["ticker", "proveedor", "clase", "mercado"])
    res = pd.read_csv(TAB / "precios_curados_resumen.csv")
    av = pd.read_csv(TAB / "precios_curados_avisos.csv")
    lista = yaml.safe_load((WT / "src/ingesta/mercados_series/config/lista_curada.yaml").read_text(encoding="utf-8"))["precios"]

    # ------------------------------------------------ ficheros: crudo frente a curado
    crudos, curados = {}, {}
    for pv in ("yahoo", "coinbase"):
        for f in (RAIZ / "precios" / pv).glob("*.parquet"):
            crudos[(pv, f.stem)] = f
        for f in (RAIZ / "precios_curados" / pv).glob("*.parquet"):
            curados[(pv, f.stem)] = f
    R["ficheros_crudos"] = len(crudos); R["ficheros_curados"] = len(curados)
    solo_crudo = sorted(set(crudos) - set(curados))
    filas = []
    for pv, st in solo_crudo:
        tk = almacen.ticker_de_fichero(st)
        e = lista.get(tk, {})
        t = pq.read_table(crudos[(pv, st)], columns=["sesion", "fecha_publicacion"])
        ses = t["sesion"].to_pandas()
        filas.append({"ticker": tk, "proveedor": pv, "decision": e.get("decision"), "regla": e.get("regla"),
                      "motivo": e.get("motivo"), "alias_de": e.get("alias_de"), "sesiones": len(ses),
                      "desde": str(pd.Timestamp(ses.min()).date()) if len(ses) else None,
                      "hasta": str(pd.Timestamp(ses.max()).date()) if len(ses) else None})
    R["solo_en_crudo"] = filas
    print("== Ficheros: crudos", len(crudos), "curados", len(curados), "solo en crudo", len(solo_crudo))
    print(pd.DataFrame(filas).to_string())
    print("en curado y no en crudo:", sorted(set(curados) - set(crudos)))

    # ------------------------------------------------ recorrido de los curados
    filas_t, anios = [], []
    for (pv, st), f in sorted(curados.items()):
        tk = almacen.ticker_de_fichero(st)
        c = leer(f, ["sesion", "mercado", "open", "close", "volume", "fecha_publicacion"])
        c["sesion"] = pd.to_datetime(c["sesion"])
        r = leer(crudos[(pv, st)], ["sesion", "open", "fecha_publicacion"]) if (pv, st) in crudos else None
        mercado = c["mercado"].dropna().iloc[-1] if c["mercado"].notna().any() else None
        fila = {"ticker": tk, "proveedor": pv, "mercado": mercado, "sesiones": len(c),
                "cierre_nulo": int(c["close_nulo"].sum()), "open_nulo": int(c["open_nulo"].sum()),
                "post_corte": int((pd.to_datetime(c["fecha_publicacion"]) > CORTE).sum())}
        if r is not None:
            r["sesion"] = pd.to_datetime(r["sesion"])
            rh = r[pd.to_datetime(r["fecha_publicacion"]) <= CORTE]
            fila["sesiones_crudo_hasta_corte"] = len(rh)
            fila["open_nulo_crudo"] = int(rh["open_nulo"].sum())
            m = c.merge(rh[["sesion", "open_nulo"]].rename(columns={"open_nulo": "o_crudo"}), on="sesion", how="left")
            anul = m["open_nulo"] & ~m["o_crudo"].fillna(True).astype(bool)
            fila["open_anulada"] = int(anul.sum())
            fila["open_anulada_con_vol"] = int((anul & m["vol_pos"]).sum())
            if anul.any():
                y = m.loc[anul, "sesion"].dt.year.value_counts()
                anios += [(tk, pv, mercado, int(k), int(v)) for k, v in y.items()]
        # huecos de calendario
        nombre, sc = cal(mercado)
        s = np.unique(c["sesion"].values.astype("datetime64[D]"))
        if sc is None:
            dias = np.arange(s[0], s[-1] + np.timedelta64(1, "D"), dtype="datetime64[D]")
            sc_ = dias[np.is_busday(dias)]; nombre = nombre or "L-V"
        else:
            sc_ = sc
        if len(s):
            lo, hi = max(s[0], sc_[0]), s[-1]
            calr = sc_[(sc_ >= lo) & (sc_ <= hi)]
            falt = ~np.isin(calr, s)
            pos = np.flatnonzero(falt)
            fila.update(calendario=nombre, esperadas=int(len(calr)), faltan=int(falt.sum()), racha_max=racha_max(pos))
            # año y fecha de inicio de la racha mayor
            if len(pos):
                corte_ = np.flatnonzero(np.diff(pos) != 1)
                ini = np.r_[0, corte_ + 1]; fin = np.r_[corte_, len(pos) - 1]
                k = int(np.argmax(fin - ini)); fila["racha_desde"] = str(calr[pos[ini[k]]]); fila["racha_hasta"] = str(calr[pos[fin[k]]])
                fila["rachas_gt5"] = int(((fin - ini + 1) > 5).sum())
                fila["faltan_desde2000"] = int((calr[pos] >= np.datetime64("2000-01-01")).sum())
            else:
                fila["rachas_gt5"] = 0; fila["faltan_desde2000"] = 0
            fila["ultima"] = str(s[-1])
            esp = curada_precios.ultima_sesion_esperada(mercado, CORTE, 1 if pv == "coinbase" else 0)
            fila["ultima_esperada"] = str(esp.date()) if esp is not None else None
        filas_t.append(fila)
    T = pd.DataFrame(filas_t).merge(meta, on=["ticker", "proveedor"], how="left", suffixes=("", "_eda"))
    T.to_csv(Path(__file__).with_name("angulo1_precios_tickers.csv"), index=False)  # solo recuentos y fechas

    # ------------------------------------------------ cifras
    R["sesiones_curadas"] = int(T["sesiones"].sum())
    R["cierres_nulos"] = int(T["cierre_nulo"].sum())
    R["aperturas_nulas_curado"] = int(T["open_nulo"].sum())
    R["aperturas_nulas_ya_en_crudo"] = int(T["open_nulo_crudo"].sum())
    R["aperturas_anuladas_medidas"] = int(T["open_anulada"].sum())
    R["aperturas_anuladas_con_volumen"] = int(T["open_anulada_con_vol"].sum())
    R["aperturas_anuladas_tabla_resumen"] = int(res["aperturas_anuladas"].sum())
    R["pct_aperturas_anuladas"] = round(100 * R["aperturas_anuladas_medidas"] / R["sesiones_curadas"], 2)
    R["tickers_con_anuladas"] = int((T["open_anulada"] > 0).sum())
    R["velas_quitadas_tabla"] = int(res["velas_quitadas"].sum())
    R["velas_quitadas_medidas"] = int((T["sesiones_crudo_hasta_corte"] - T["sesiones"]).sum())
    R["sesiones_post_corte_en_curado"] = int(T["post_corte"].sum())
    print("\n== Cifras"); [print(k, R[k]) for k in list(R) if not isinstance(R[k], list)]
    g = T.groupby("mercado").agg(tickers=("ticker", "size"), sesiones=("sesiones", "sum"), anuladas=("open_anulada", "sum"),
                                 tickers_anul=("open_anulada", lambda x: int((x > 0).sum()))).reset_index()
    g["pct"] = (100 * g["anuladas"] / g["sesiones"]).round(1)
    g = g.sort_values("anuladas", ascending=False)
    print(g.to_string()); R["anuladas_por_mercado"] = g.to_dict("records")
    A = pd.DataFrame(anios, columns=["ticker", "proveedor", "mercado", "anio", "n"])
    pa = A.groupby("anio")["n"].sum()
    R["anuladas_por_anio"] = {int(k): int(v) for k, v in pa.items()}
    R["anuladas_antes_2000"] = int(pa[pa.index < 2000].sum()); R["anuladas_2000_2010"] = int(pa[(pa.index >= 2000) & (pa.index <= 2010)].sum())
    R["anuladas_desde_2011"] = int(pa[pa.index >= 2011].sum()); R["anuladas_desde_2016"] = int(pa[pa.index >= 2016].sum())
    print("anuladas por año (resumen):", {k: R[k] for k in ("anuladas_antes_2000", "anuladas_2000_2010", "anuladas_desde_2011", "anuladas_desde_2016")})
    top = T.sort_values("open_anulada", ascending=False)[["ticker", "mercado", "clase", "sesiones", "open_anulada", "open_anulada_con_vol"]].head(15)
    print(top.to_string()); R["anuladas_top_tickers"] = top.to_dict("records")
    rec = A[A["anio"] >= 2016].groupby(["mercado"])["n"].sum().sort_values(ascending=False)
    R["anuladas_desde2016_por_mercado"] = {k: int(v) for k, v in rec.items()}
    rect = A[A["anio"] >= 2016].groupby("ticker")["n"].sum().sort_values(ascending=False).head(15)
    R["anuladas_desde2016_top_tickers"] = {k: int(v) for k, v in rect.items()}
    print("anuladas desde 2016 por mercado:", R["anuladas_desde2016_por_mercado"])
    print("anuladas desde 2016 top:", R["anuladas_desde2016_top_tickers"])
    # sin apertura
    T["pct_open_nulo"] = 100 * T["open_nulo"] / T["sesiones"]
    sa = T[T["pct_open_nulo"] > 99][["ticker", "mercado", "sesiones", "open_nulo", "open_nulo_crudo", "pct_open_nulo"]]
    print("sin apertura (>99 %):"); print(sa.to_string()); R["sin_apertura"] = sa.round(2).to_dict("records")
    alto = T[(T["pct_open_nulo"] > 20) & (T["pct_open_nulo"] <= 99)].sort_values("pct_open_nulo", ascending=False)
    R["open_nulo_mas_20pct_n"] = int(len(alto))
    R["open_nulo_mas_20pct"] = alto[["ticker", "mercado", "clase", "sesiones", "open_nulo", "pct_open_nulo"]].round(1).head(25).to_dict("records")
    print("tickers con >20 % de aperturas nulas:", len(alto)); print(alto[["ticker", "mercado", "clase", "pct_open_nulo"]].head(25).to_string())

    # ------------------------------------------------ huecos de calendario
    R["tickers_con_faltantes"] = int((T["faltan"] > 0).sum())
    R["sesiones_faltantes_total"] = int(T["faltan"].sum())
    R["sesiones_faltantes_desde2000"] = int(T["faltan_desde2000"].sum())
    R["tickers_racha_gt5"] = int((T["racha_max"] > 5).sum())
    R["tickers_racha_gt20"] = int((T["racha_max"] > 20).sum())
    R["tickers_racha_gt5_desde2000"] = int(((T["racha_max"] > 5) & (pd.to_datetime(T["racha_desde"], errors="coerce") >= "2000-01-01")).sum())
    gm = T[T["racha_max"] > 5].groupby(["mercado"]).agg(tickers=("ticker", "size"), racha_mediana=("racha_max", "median")).reset_index().sort_values("tickers", ascending=False)
    R["racha_gt5_por_mercado"] = gm.to_dict("records")
    gc = T[T["racha_max"] > 5].groupby(["clase"]).size().sort_values(ascending=False)
    R["racha_gt5_por_clase"] = {k: int(v) for k, v in gc.items()}
    tr = T.sort_values("racha_max", ascending=False)[["ticker", "mercado", "clase", "calendario", "racha_max", "racha_desde", "racha_hasta", "faltan", "esperadas"]].head(25)
    R["racha_top"] = tr.astype(str).to_dict("records")
    print("\n== Huecos de calendario"); [print(k, R[k]) for k in ("tickers_con_faltantes", "sesiones_faltantes_total", "sesiones_faltantes_desde2000", "tickers_racha_gt5", "tickers_racha_gt20", "tickers_racha_gt5_desde2000")]
    print(gm.to_string()); print(R["racha_gt5_por_clase"]); print(tr.to_string())
    # comparar con eda_precios (paso 3, crudo)
    ep = pd.read_csv(TAB / "eda_precios.csv", usecols=["ticker", "proveedor", "sesiones_faltantes"])
    R["eda_sesiones_faltantes_total"] = int(ep["sesiones_faltantes"].sum())

    # ------------------------------------------------ no llegan al corte
    T["no_llega"] = pd.to_datetime(T["ultima"]) < pd.to_datetime(T["ultima_esperada"])
    nl = T[T["no_llega"]][["ticker", "proveedor", "mercado", "clase", "ultima", "ultima_esperada"]]
    tabla_nl = av[av["tipo"] == "no_llega_corte"][["ticker", "proveedor", "n", "primera", "ultima", "nota"]]
    nl = nl.merge(tabla_nl[["ticker", "n", "nota"]], on="ticker", how="outer")
    nl = nl.merge(pd.DataFrame([{"ticker": k, "aviso_lista": v.get("aviso"), "motivo_lista": v.get("motivo")} for k, v in lista.items()]), on="ticker", how="left")
    R["no_llega_medido"] = int(T["no_llega"].sum()); R["no_llega_tabla"] = int(len(tabla_nl))
    R["no_llega_lista"] = nl.astype(str).to_dict("records")
    print("\n== No llegan al corte: medido", R["no_llega_medido"], "tabla", R["no_llega_tabla"])
    print(nl.drop(columns=["motivo_lista"]).to_string())
    # tickers cuya última sesión es > 10 días hábiles antes del corte (regla de tools)
    T["habiles_atraso"] = [int(np.busday_count(np.datetime64(u, "D") + 1, np.datetime64(CORTE.date(), "D") + 1)) for u in T["ultima"]]
    at = T[T["habiles_atraso"] > 10]
    R["atraso_tools_precios"] = int(len(at))
    R["atraso_tools_precios_lista"] = at[["ticker", "mercado", "ultima", "habiles_atraso"]].astype(str).to_dict("records")
    print("aviso datos atrasados de tools (>10 hábiles):", len(at)); print(at[["ticker", "mercado", "ultima", "habiles_atraso"]].to_string())
    R["avisos_tipos"] = av["tipo"].value_counts().astype(int).to_dict()
    R["aviso_relleno_quitadas_tabla"] = int(av.loc[(av["tipo"] == "sesion_fuera_calendario_relleno") & (av["accion"] == "quitada"), "n"].sum())
    R["aviso_apertura_n_tabla"] = int(av.loc[av["tipo"].isin(["apertura_igual_cierre", "apertura_igual_cierre_con_volumen"]), "n"].sum())
    R["aviso_apertura_con_vol_tabla"] = int(av.loc[av["tipo"] == "apertura_igual_cierre_con_volumen", "n"].sum())
    print({k: R[k] for k in ("aviso_relleno_quitadas_tabla", "aviso_apertura_n_tabla", "aviso_apertura_con_vol_tabla")})
    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("escrito", OUT)


if __name__ == "__main__":
    main()
