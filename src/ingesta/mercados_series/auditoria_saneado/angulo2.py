"""Auditoría del Tema 1 · ángulo 2: actualización, frescura y vintages (SOLO LECTURA).

Uso: PYTHONPATH=<worktree>/src python angulo2.py [s1 s2 ...]   (sin argumentos: todas las secciones)
Secciones: s1 frescura de series · s2 filas posteriores al corte · s3 frescura de precios · s4 vintages (fuga y
unico) · s5 WEO · s6 OAS de ICE · s7 ediciones académicas · s8 mecanismo de refresco (código) · s9 tablas y logs.
Nunca imprime valores: solo recuentos, fechas, porcentajes e ids. Lee columnas mínimas con pyarrow.
Escribe las cifras en angulo2_cifras.json (junto a este script), fusionando con lo que ya hubiera.
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import gc
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

WT = _REPO
SRC = WT / "src" / "ingesta" / "mercados_series"
TABLAS = WT / "results" / "ingesta" / "mercados_series" / "tablas"
C = Path("D:/tfm_corpus/mercados_series")
BASE = C / "series" / "base_series.parquet"
CURADA = C / "series" / "base_curada.parquet"
CORTE = pd.Timestamp("2026-11-13")
HOY = pd.Timestamp("2026-11-21")
AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "angulo2_cifras.json"
FUGA = "posible fuga de revisiones"
NOMINAL = {"diaria": 1, "semanal": 7, "mensual": 30, "trimestral": 91, "anual": 365}

CIFRAS: dict = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}


def guardar(clave: str, valor) -> None:
    CIFRAS[clave] = valor
    SALIDA.write_text(json.dumps(CIFRAS, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def leer(ruta: Path, cols: list[str]) -> pd.DataFrame:
    dic = [c for c in cols if c in ("serie", "fuente", "vintage", "nota", "metodo_publicacion", "mercado", "ticker")]
    return pq.read_table(ruta, columns=cols, read_dictionary=dic).to_pandas()


def catalogo() -> dict:
    from ingesta.mercados_series import catalogo as cm
    return cm.cargar_catalogo()


def lista() -> dict:
    import yaml
    return yaml.safe_load((SRC / "config" / "lista_curada.yaml").read_text(encoding="utf-8"))


def p(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------------------------------------ s1
def perfil_series(ruta: Path) -> pd.DataFrame:
    """Por serie: última referencia, última publicación, última publicación de un periodo NUEVO, cadencia y
    retraso típicos (medianas de los últimos 12 periodos nuevos). Solo fechas."""
    df = leer(ruta, ["serie", "fuente", "fecha_referencia", "fecha_publicacion"])
    fuente = df.groupby("serie", observed=True)["fuente"].first().astype(str)
    ult_pub = df.groupby("serie", observed=True)["fecha_publicacion"].max()
    prim = (df.groupby(["serie", "fecha_referencia"], observed=True)["fecha_publicacion"].min()
            .reset_index().dropna(subset=["fecha_publicacion"]))
    del df
    gc.collect()
    filas = []
    for sid, g in prim.groupby("serie", observed=True, sort=False):
        g = g.sort_values("fecha_referencia")
        pubs = np.sort(g["fecha_publicacion"].drop_duplicates().to_numpy())
        ult = g.tail(12)
        cad = float(np.median(np.diff(pubs[-13:]).astype("timedelta64[D]").astype(int))) if len(pubs) > 2 else np.nan
        lag = float(np.median((ult["fecha_publicacion"] - ult["fecha_referencia"]).dt.days))
        filas.append({"serie": str(sid), "ult_ref": g["fecha_referencia"].max(), "ult_pub_nueva": pubs[-1],
                      "n_pubs": len(pubs), "cadencia_dias": cad, "retraso_dias": lag})
    out = pd.DataFrame(filas).set_index("serie")
    out["fuente"] = fuente
    out["ult_pub"] = ult_pub
    return out


def clasificar(edad: float, cad: float, estado: str) -> str:
    if estado == "retirada":   # «capada» = historia recortada por la fuente, no parada
        return "parado/discontinuado"
    if np.isnan(cad):
        cad = 365.0
    u1, u2, u3 = max(1.5 * cad, 7), max(3 * cad, 14), max(4 * cad, 365)
    if edad <= u1:
        return "al dia"
    if edad <= u2:
        return "retraso normal"
    if edad <= u3:
        return "desfasado"
    return "parado/discontinuado"


EXTRACTOR = {  # fuente de la base -> orden que la refresca gratis (o None)
    "fred_alfred": "descargar-fred-vivo / descargar-alfred --refrescar", "ken_french": "construir-base (académicos)",
    "shiller": "construir-base (académicos)", "goyal_welch": "construir-base (académicos)",
    "ofr_fsi": "construir-base (académicos)", "bce": "descargar-bce", "eurostat": "descargar-eurostat",
    "bis": "descargar-bis", "imf_weo": "descargar-imf", "worldbank": "descargar-worldbank", "oecd": "descargar-oecd",
    "philly_rtdsm": "descargar-philly", "boc": "descargar-bancos", "boj": "descargar-bancos", "rba": "descargar-bancos",
    "bundesbank": "descargar-bancos (anti-bots)", "ust_curva": "descargar-curvas", "bce_curvas": "descargar-curvas",
    "boe_curvas": "descargar-curvas", "mof_jgb": "descargar-curvas", "boc_curva": "descargar-curvas",
    "yfinance": "descargar-precios + construir-base (fase1 extendida)", "calculo_propio": "construir-base (derivada)",
}


def s1():
    p("\n== s1 · frescura de las series curadas (base_curada) frente al corte y frente a hoy")
    cat = catalogo()
    lc = lista()["series"]
    cur = perfil_series(CURADA)
    gc.collect()
    tra = perfil_series(BASE)
    gc.collect()
    cur["frecuencia"] = [cat.get(s, {}).get("frecuencia") for s in cur.index]
    cur["estado"] = [cat.get(s, {}).get("estado") for s in cur.index]
    cur["decision"] = [lc.get(s, {}).get("decision") for s in cur.index]
    nom = cur["frecuencia"].map(NOMINAL).astype(float)
    cur["cad"] = np.fmax(cur["cadencia_dias"], nom.fillna(1))
    cur["edad_corte"] = (CORTE - pd.to_datetime(cur["ult_pub_nueva"])).dt.days
    cur["clase"] = [clasificar(e, c, str(s)) for e, c, s in zip(cur["edad_corte"], cur["cad"], cur["estado"])]
    # base de trabajo (lo que ya se tiene, sin red)
    cur["ult_pub_nueva_trabajo"] = tra.reindex(cur.index)["ult_pub_nueva"]
    cur["ult_ref_trabajo"] = tra.reindex(cur.index)["ult_ref"]
    cur["edad_hoy_trabajo"] = (HOY - pd.to_datetime(cur["ult_pub_nueva_trabajo"])).dt.days
    cur["clase_hoy"] = [clasificar(e, c, str(s)) for e, c, s in zip(cur["edad_hoy_trabajo"], cur["cad"], cur["estado"])]
    cur["mas_nuevo_en_trabajo"] = cur["ult_ref_trabajo"] > cur["ult_ref"]
    p(f"series en la curada: {len(cur)}; fuentes: {cur['fuente'].nunique()}")
    t = pd.crosstab(cur["fuente"], cur["clase"], margins=True)
    p(t.to_string())
    guardar("s1_series_curada", int(len(cur)))
    guardar("s1_clase_total", {k: int(v) for k, v in cur["clase"].value_counts().items()})
    guardar("s1_clase_por_fuente", {f: {k: int(v) for k, v in r.items() if v} for f, r in
                                    pd.crosstab(cur["fuente"], cur["clase"]).iterrows()})
    p("\nfrente a HOY con la base de trabajo:")
    guardar("s1_clase_hoy_trabajo", {k: int(v) for k, v in cur["clase_hoy"].value_counts().items()})
    p(cur["clase_hoy"].value_counts().to_string())
    # desfasadas y paradas: detalle
    malas = cur[cur["clase"].isin(["desfasado", "parado/discontinuado"])].copy()
    # último día de descarga del crudo de cada fuente (s9) y de los precios de Yahoo (yf: sale del almacén)
    crudo = {k: str(v)[:8] for k, v in CIFRAS.get("s9_ultima_descarga_crudo", {}).items()}
    crudo["fred_alfred"] = crudo.get("fred", "")
    crudo["yfinance"] = "20261120"   # 3b-1/3b-2: refresco de precios del 19 y 20-nov (logs yahoo_3b*.jsonl)

    def gratis(m, f, e):
        if m:
            return "ya en la base de trabajo: re-curar con corte nuevo"
        if e == "retirada" or f not in EXTRACTOR:
            return "no: retirada o sin extractor"
        if crudo.get(f, "") >= "20261119":
            return f"no: refrescada el {crudo[f]} y sin periodos nuevos (la fuente no publica o cambió)"
        return f"sí: {EXTRACTOR[f]}"
    malas["gratis"] = [gratis(m, f, e) for m, f, e in
                       zip(malas["mas_nuevo_en_trabajo"], malas["fuente"], malas["estado"])]
    cols = ["fuente", "frecuencia", "estado", "ult_ref", "ult_pub_nueva", "cad", "retraso_dias", "edad_corte",
            "clase", "ult_ref_trabajo", "gratis"]
    with pd.option_context("display.width", 250, "display.max_rows", 400, "display.max_colwidth", 60):
        p("\ndesfasadas o paradas en la curada:")
        p(malas.sort_values(["clase", "fuente", "edad_corte"])[cols].to_string())
    guardar("s1_malas", {s: {"fuente": r["fuente"], "frecuencia": r["frecuencia"], "estado": r["estado"],
                             "ult_ref": str(pd.Timestamp(r["ult_ref"]).date()),
                             "ult_pub_nueva": str(pd.Timestamp(r["ult_pub_nueva"]).date()),
                             "cadencia": r["cad"], "retraso_mediano": r["retraso_dias"], "edad_corte": int(r["edad_corte"]),
                             "clase": r["clase"], "ult_ref_trabajo": str(pd.Timestamp(r["ult_ref_trabajo"]).date())
                             if pd.notna(r["ult_ref_trabajo"]) else None, "gratis": r["gratis"]}
                         for s, r in malas.iterrows()})
    guardar("s1_malas_por_fuente_gratis", {f"{f} | {g}": int(n) for (f, g), n in
                                           malas.groupby(["fuente", "gratis"]).size().items()})
    # retraso normal: resumen por fuente
    rn = cur[cur["clase"] == "retraso normal"]
    guardar("s1_retraso_normal_por_fuente", {k: int(v) for k, v in rn["fuente"].value_counts().items()})
    # series que la base de trabajo ya tiene más nuevas que la curada (ganan con re-curar)
    mas = cur[cur["mas_nuevo_en_trabajo"]]
    guardar("s1_mas_nuevo_en_trabajo", {"series": int(len(mas)),
                                        "por_fuente": {k: int(v) for k, v in mas["fuente"].value_counts().items()}})
    p(f"\nseries con periodos más nuevos en la base de trabajo que en la curada: {len(mas)}")
    p(mas["fuente"].value_counts().to_string())
    cur.reset_index().to_csv(AQUI / "angulo2_frescura_series.csv", index=False)


# ------------------------------------------------------------------------------------------------ s2
def s2():
    p("\n== s2 · filas de la base de trabajo posteriores al corte")
    df = leer(BASE, ["serie", "fuente", "fecha_publicacion", "fecha_referencia"])
    post = df[df["fecha_publicacion"] > CORTE]
    p(f"filas base de trabajo: {len(df)}; con fecha_publicacion > corte: {len(post)} "
      f"({100 * len(post) / len(df):.3f} %); series: {post['serie'].nunique()}")
    por = post.groupby("fuente", observed=True).agg(filas=("serie", "size"), series=("serie", "nunique"),
                                                     max_pub=("fecha_publicacion", "max"))
    por = por[por["filas"] > 0].sort_values("filas", ascending=False)
    p(por.to_string())
    nuevas_ref = post[post["fecha_referencia"] > CORTE]
    guardar("s2_post_corte", {"filas_base": int(len(df)), "filas_post": int(len(post)),
                              "pct": round(100 * len(post) / len(df), 3), "series": int(post["serie"].nunique()),
                              "filas_ref_post_corte": int(len(nuevas_ref)),
                              "max_fecha_publicacion": str(df["fecha_publicacion"].max().date()),
                              "por_fuente": {f: {"filas": int(r["filas"]), "series": int(r["series"]),
                                                 "max_pub": str(r["max_pub"].date())} for f, r in por.iterrows()}})
    fut = post[post["fecha_publicacion"] > HOY]
    hasta_hoy = post[post["fecha_publicacion"] <= HOY]
    guardar("s2_post_corte_split", {
        "pub_hasta_hoy": {"filas": int(len(hasta_hoy)), "series": int(hasta_hoy["serie"].nunique()),
                          "por_fuente": {k: int(v) for k, v in hasta_hoy["fuente"].value_counts().items() if v}},
        "pub_futura": {"filas": int(len(fut)), "series": int(fut["serie"].nunique()),
                       "por_fuente": {k: int(v) for k, v in fut["fuente"].value_counts().items() if v},
                       "max": str(fut["fecha_publicacion"].max().date()) if len(fut) else None}})
    p(f"posteriores al corte y publicadas hasta hoy: {len(hasta_hoy)} filas ({hasta_hoy['serie'].nunique()} series); "
      f"con fecha_publicacion futura (> hoy, regla conservadora o proyección): {len(fut)} filas")
    p("futuras por fuente:", {k: int(v) for k, v in fut["fuente"].value_counts().items() if v})
    cur_ids = set(pq.read_table(CURADA, columns=["serie"]).column("serie").unique().to_pylist())
    pc = post[post["serie"].astype(str).isin(cur_ids)]
    guardar("s2_post_corte_series_curadas", {"filas": int(len(pc)), "series": int(pc["serie"].nunique())})
    p(f"de ellas en series curadas: {len(pc)} filas, {pc['serie'].nunique()} series")
    # prueba: ¿la curada lleva algo posterior al corte?
    cu = leer(CURADA, ["fecha_publicacion"])
    guardar("s2_curada_post_corte", int((cu["fecha_publicacion"] > CORTE).sum()))
    guardar("s2_curada_max_pub", str(cu["fecha_publicacion"].max().date()))
    p(f"curada con fecha_publicacion > corte: {(cu['fecha_publicacion'] > CORTE).sum()}; "
      f"máx {cu['fecha_publicacion'].max().date()}")


# ------------------------------------------------------------------------------------------------ s3
def s3():
    p("\n== s3 · frescura de los precios (curados y crudos)")
    from ingesta.mercados_series import curada_precios as cp
    lc = lista().get("precios", {})
    queda = {t for t, e in lc.items() if isinstance(e, dict) and e.get("decision") == "queda"}
    filas = []
    for prov in ("yahoo", "coinbase"):
        for f in sorted((C / "precios_curados" / prov).glob("*.parquet")):
            t = pq.read_table(f, columns=["ticker", "sesion", "mercado", "fecha_publicacion"]).to_pandas()
            if not len(t):
                filas.append({"prov": prov, "fichero": f.name, "vacio": True})
                continue
            raw = C / "precios" / prov / f.name
            r = (pq.read_table(raw, columns=["sesion", "fecha_publicacion"]).to_pandas() if raw.exists() else None)
            ult = t["sesion"].max()
            retraso = max(0, (t["fecha_publicacion"].max().normalize() - ult.normalize()).days)
            merc = str(t["mercado"].iloc[-1])
            esp = cp.ultima_sesion_esperada(merc, CORTE, retraso)
            cal = cp._calendario(merc)
            u = np.datetime64(ult.date(), "D")
            if esp is None:
                faltan = 0
            else:
                e = np.datetime64(esp.date(), "D")
                faltan = (int(((cal > u) & (cal <= e)).sum()) if cal is not None
                          else int(np.busday_count(u + 1, e + 1)))
            filas.append({"prov": prov, "ticker": str(t["ticker"].iloc[0]), "mercado": merc, "ult_sesion": ult,
                          "ult_pub": t["fecha_publicacion"].max(), "esperada": esp, "faltan": max(faltan, 0),
                          "raw_ult_sesion": r["sesion"].max() if r is not None and len(r) else pd.NaT,
                          "raw_post_corte": int((r["fecha_publicacion"] > CORTE).sum()) if r is not None else 0,
                          "en_lista_queda": str(t["ticker"].iloc[0]) in queda})
    df = pd.DataFrame(filas)
    df["clase"] = pd.cut(df["faltan"], [-1, 0, 2, 40, 10 ** 6],
                         labels=["al dia", "retraso normal", "desfasado", "parado/discontinuado"]).astype(str)
    df["raw_mas_nuevo"] = df["raw_ult_sesion"] > df["ult_sesion"]
    p(f"ficheros curados: {len(df)}; tickers queda en la lista: {len(queda)}; curados que no están en 'queda': "
      f"{int((~df['en_lista_queda']).sum())}; 'queda' sin fichero curado: {len(queda - set(df['ticker']))}")
    p(pd.crosstab(df["prov"], df["clase"], margins=True).to_string())
    guardar("s3_precios", {"ficheros": int(len(df)), "queda_lista": len(queda),
                           "queda_sin_fichero": sorted(queda - set(df["ticker"]))[:50],
                           "n_queda_sin_fichero": len(queda - set(df["ticker"])),
                           "clase": {k: int(v) for k, v in df["clase"].value_counts().items()},
                           "por_mercado_desfasado": {k: int(v) for k, v in
                                                     df[df["clase"].isin(["desfasado", "parado/discontinuado"])]
                                                     ["mercado"].value_counts().items()},
                           "raw_post_corte_sesiones": int(df["raw_post_corte"].sum()),
                           "raw_post_corte_tickers": int((df["raw_post_corte"] > 0).sum()),
                           "max_raw_sesion": str(pd.to_datetime(df["raw_ult_sesion"]).max().date()),
                           "raw_mas_nuevo_que_curado_entre_malos": int(df[df["clase"].isin(
                               ["desfasado", "parado/discontinuado"])]["raw_mas_nuevo"].sum())})
    malos = df[df["clase"].isin(["desfasado", "parado/discontinuado"])].sort_values("faltan", ascending=False)
    with pd.option_context("display.width", 250, "display.max_rows", 200):
        p(malos[["prov", "ticker", "mercado", "ult_sesion", "esperada", "faltan", "raw_ult_sesion", "clase"]]
          .to_string(index=False))
    guardar("s3_malos", {r["ticker"]: {"mercado": r["mercado"], "ult_sesion": str(r["ult_sesion"].date()),
                                       "faltan": int(r["faltan"]), "clase": r["clase"]} for _, r in malos.iterrows()})
    # retraso normal: por mercado
    rn = df[df["clase"] == "retraso normal"]
    guardar("s3_retraso_normal_por_mercado", {k: int(v) for k, v in rn["mercado"].value_counts().items()})
    p("retraso normal por mercado:", rn["mercado"].value_counts().to_dict())
    # cuántas sesiones de crudo hay ya tras el corte
    p(f"sesiones en crudo con fecha_publicacion > corte: {df['raw_post_corte'].sum()} en "
      f"{(df['raw_post_corte'] > 0).sum()} tickers; última sesión cruda: {pd.to_datetime(df['raw_ult_sesion']).max()}")
    # avisos no_llega_corte de la tabla oficial (contraste)
    av = pd.read_csv(TABLAS / "precios_curados_avisos.csv", usecols=["ticker", "tipo"]) if (
        TABLAS / "precios_curados_avisos.csv").exists() else None
    if av is not None:
        n = int((av["tipo"] == "no_llega_corte").sum())
        guardar("s3_avisos_no_llega_corte_tabla", n)
        p(f"avisos no_llega_corte en precios_curados_avisos.csv: {n}")
    df.to_csv(AQUI / "angulo2_frescura_precios.csv", index=False)


# ------------------------------------------------------------------------------------------------ s4
TIPOS_NOTA = [
    ("alfred_anterior", "anterior a ALFRED"),
    ("ultimo_vintage (NOTA_REVISABLE)", "valores del último vintage: posible fuga"),
    ("ultima_edicion (NOTA_REVISABLE_EDICION)", "valores de la última edición del fichero"),
    ("primera_edicion (NOTA_PRIMERA_EDICION)", "valor de la primera edición archivada"),
    ("bce_previa (NOTA_PREVIA)", "anterior al historial de versiones del BCE"),
]


def s4():
    p("\n== s4 · vintages: «posible fuga de revisiones» y vintage «unico»")
    cat = catalogo()
    for nombre, ruta in (("curada", CURADA), ("trabajo", BASE)):
        df = leer(ruta, ["serie", "fuente", "vintage", "nota"])
        n = len(df)
        notas = pd.Series(df["nota"].cat.categories)
        es_fuga_cat = notas.str.contains(FUGA, regex=False).to_numpy()
        codes = df["nota"].cat.codes.to_numpy()
        fuga = np.where(codes >= 0, es_fuga_cat[np.clip(codes, 0, None)], False)
        tipo_cat = np.full(len(notas), "otra", dtype=object)
        for etiqueta, patron in reversed(TIPOS_NOTA):
            tipo_cat[notas.str.contains(patron, regex=False).to_numpy()] = etiqueta
        tipo = np.where(fuga, tipo_cat[np.clip(codes, 0, None)], "sin fuga")
        p(f"\n[{nombre}] filas {n}; con «{FUGA}»: {fuga.sum()} ({100 * fuga.sum() / n:.2f} %)")
        f = df.loc[fuga]
        por_f = f.groupby("fuente", observed=True).size().sort_values(ascending=False)
        tot_f = df.groupby("fuente", observed=True).size()
        p((pd.DataFrame({"filas_fuga": por_f, "pct_de_la_fuente": (100 * por_f / tot_f.reindex(por_f.index)).round(1),
                         "series": f.groupby("fuente", observed=True)["serie"].nunique()})).to_string())
        por_tipo = pd.Series(tipo[fuga]).value_counts()
        p("por tipo de nota:\n" + por_tipo.to_string())
        top = f.groupby("serie", observed=True).size().sort_values(ascending=False)
        tipo_fuente = pd.crosstab(f["fuente"].astype(str).to_numpy(), tipo[fuga])
        guardar(f"s4_fuga_{nombre}", {
            "filas": int(n), "filas_fuga": int(fuga.sum()), "pct": round(100 * fuga.sum() / n, 2),
            "series": int(f["serie"].nunique()),
            "por_fuente": {k: {"filas": int(v), "pct_fuente": round(100 * v / tot_f[k], 1),
                               "series": int(f[f["fuente"] == k]["serie"].nunique())} for k, v in por_f.items()},
            "por_tipo": {k: int(v) for k, v in por_tipo.items()},
            "tipo_por_fuente": {fu: {k: int(v) for k, v in r.items() if v} for fu, r in tipo_fuente.iterrows()},
            "top_series": {str(k): int(v) for k, v in top.head(15).items()}})
        # vintage unico
        un = (df["vintage"] == "unico").to_numpy()
        rev = df["serie"].astype(str).map(lambda s: bool(cat.get(s, {}).get("revisable"))).to_numpy()
        p(f"[{nombre}] vintage unico: {un.sum()} ({100 * un.sum() / n:.2f} %); unico y revisable: {(un & rev).sum()} "
          f"({100 * (un & rev).sum() / n:.2f} %); unico y con nota de fuga: {(un & fuga).sum()}")
        u = df.loc[un]
        por_u = u.groupby("fuente", observed=True).size().sort_values(ascending=False)
        por_ur = df.loc[un & rev].groupby("fuente", observed=True).size()
        tab = pd.DataFrame({"filas_unico": por_u, "pct_fuente": (100 * por_u / tot_f.reindex(por_u.index)).round(1),
                            "series": u.groupby("fuente", observed=True)["serie"].nunique(),
                            "unico_revisable": por_ur.reindex(por_u.index).fillna(0).astype(int)})
        p(tab.to_string())
        # formato de vintage por fuente (fecha, edición, unico)
        v = df["vintage"].astype(str)
        fmt = np.where(v == "unico", "unico", np.where(v.str.len() == 7, "edicion AAAA-MM", "fecha AAAA-MM-DD"))
        fmt_fu = pd.crosstab(df["fuente"].astype(str).to_numpy(), fmt)
        guardar(f"s4_unico_{nombre}", {
            "filas_unico": int(un.sum()), "pct": round(100 * un.sum() / n, 2),
            "unico_revisable": int((un & rev).sum()), "pct_unico_revisable": round(100 * (un & rev).sum() / n, 2),
            "unico_con_fuga": int((un & fuga).sum()),
            "por_fuente": {k: {"filas": int(r["filas_unico"]), "pct_fuente": float(r["pct_fuente"]),
                               "series": int(r["series"]), "revisable": int(r["unico_revisable"])}
                           for k, r in tab.iterrows()},
            "formato_vintage_por_fuente": {fu: {k: int(x) for k, x in r.items() if x} for fu, r in fmt_fu.iterrows()}})
        del df, f, u
        gc.collect()


# ------------------------------------------------------------------------------------------------ s5
def s5():
    p("\n== s5 · WEO (FMI)")
    ed_esperadas = [f"{a}-{m}" for a in range(2008, 2027) for m in ("04", "10")]
    w = pq.read_table(C / "bloque4" / "imf_weo.parquet")
    p("columnas bloque4/imf_weo.parquet:", w.schema.names)
    cols = [c for c in w.schema.names if c in ("serie", "vintage", "fecha_publicacion", "fecha_referencia", "fuente",
                                               "edicion", "horizonte")]
    wd = w.select(cols).to_pandas()
    del w
    r = wd.groupby("vintage").agg(filas=("serie", "size"), series=("serie", "nunique"),
                                  pub_min=("fecha_publicacion", "min"), pub_max=("fecha_publicacion", "max"))
    p(r.to_string())
    guardar("s5_bloque4_weo", {"filas": int(len(wd)), "series": int(wd["serie"].nunique()),
                               "por_vintage": {k: {"filas": int(x["filas"]), "series": int(x["series"]),
                                                   "pub_min": str(x["pub_min"].date())} for k, x in r.iterrows()}})
    pr = pq.read_table(C / "series" / "proyecciones.parquet",
                       columns=["serie", "fuente", "edicion", "vintage", "fecha_publicacion"]).to_pandas()
    rp = pr.groupby(["fuente", "edicion"]).agg(filas=("serie", "size"), series=("serie", "nunique"),
                                               pub_min=("fecha_publicacion", "min"))
    p(rp.to_string())
    guardar("s5_proyecciones", {"filas": int(len(pr)), "series": int(pr["serie"].nunique()),
                                "por_fuente_edicion": {f"{a}|{b}": {"filas": int(x["filas"]), "series": int(x["series"])}
                                                       for (a, b), x in rp.iterrows()}})
    for nombre, ruta in (("curada", CURADA), ("trabajo", BASE)):
        t = pq.read_table(ruta, columns=["serie", "fuente", "vintage", "fecha_publicacion"],
                          filters=[("fuente", "=", "imf_weo")]).to_pandas()
        rv = t.groupby("vintage").agg(filas=("serie", "size"), series=("serie", "nunique"),
                                      pub_min=("fecha_publicacion", "min"), pub_max=("fecha_publicacion", "max"))
        p(f"[{nombre}] imf_weo: {len(t)} filas, {t['serie'].nunique()} series\n{rv.to_string()}")
        guardar(f"s5_weo_{nombre}", {"filas": int(len(t)), "series": int(t["serie"].nunique()),
                                     "por_vintage": {k: {"filas": int(x["filas"]), "series": int(x["series"]),
                                                         "pub_min": str(x["pub_min"].date()),
                                                         "pub_max": str(x["pub_max"].date())} for k, x in rv.iterrows()},
                                     "primera_pub": str(t["fecha_publicacion"].min().date()) if len(t) else None})
    vistas = set(wd["vintage"].astype(str).str[:7]) | set(pr.loc[pr["fuente"] == "imf_weo", "edicion"].astype(str).str[:7])
    faltan = [e for e in ed_esperadas if e not in vistas]
    guardar("s5_ediciones", {"esperadas_2008_2026": len(ed_esperadas), "vistas": sorted(vistas & set(ed_esperadas)),
                             "faltan": faltan, "n_faltan": len(faltan)})
    p(f"ediciones vistas (bloque4+proyecciones): {sorted(vistas)}; faltan {len(faltan)}: {faltan}")
    crudo = sorted(x.name for x in (C / "crudo" / "imf_weo").iterdir())
    guardar("s5_crudo", {"ficheros": len(crudo), "dbnomics_solo_meta": sum("dbnomics" in x for x in crudo),
                         "sdmx_json": [x for x in crudo if x.endswith(".json") and "sdmx" in x]})
    p("crudo imf_weo:", len(crudo), "ficheros;", sum("dbnomics" in x for x in crudo), "son .meta.json de DBnomics")


# ------------------------------------------------------------------------------------------------ s6
def s6():
    p("\n== s6 · OAS de ICE (archivo)")
    car = C / "archivo" / "ice_oas"
    reg = pd.read_csv(car / "registro.csv")
    p(reg.to_string())
    caps = sorted(x.name for x in car.glob("captura_*.parquet"))
    acu = pq.read_table(car / "acumulado.parquet").to_pandas()
    cols = [c for c in acu.columns if c != "valor"]
    acu = acu[cols]
    cob = acu.groupby("serie").agg(filas=("fecha_referencia", "size"), ref_min=("fecha_referencia", "min"),
                                   ref_max=("fecha_referencia", "max"), vintages=("vintage", "nunique"))
    p(f"capturas: {caps}")
    p(cob.to_string())
    ids = list(cob.index)
    b = pq.read_table(BASE, columns=["serie", "fecha_referencia", "fecha_publicacion"],
                      filters=[("serie", "in", ids)]).to_pandas()
    cb = b.groupby("serie").agg(filas=("fecha_referencia", "size"), ref_min=("fecha_referencia", "min"),
                                ref_max=("fecha_referencia", "max"))
    k = pq.read_table(CURADA, columns=["serie", "fecha_referencia"], filters=[("serie", "in", ids)]).to_pandas()
    ck = k.groupby("serie").agg(filas=("fecha_referencia", "size"), ref_min=("fecha_referencia", "min"))
    p("en la base de trabajo:\n" + cb.to_string())
    p("en la curada:\n" + ck.to_string())
    # meses de historia que la ventana de 3 años pierde por cada mes sin captura
    ult_cap = pd.Timestamp(caps[-1][8:18])
    guardar("s6_oas", {
        "capturas": [c[8:18] for c in caps], "n_capturas": len(caps),
        "ejecuciones_registro": int(len(reg)), "primera_captura": caps[0][8:18], "ultima_captura": caps[-1][8:18],
        "acumulado_filas": int(len(acu)), "series": int(acu["serie"].nunique()),
        "acumulado_ref_min": str(cob["ref_min"].min().date()), "acumulado_ref_max": str(cob["ref_max"].max().date()),
        "origen": {k2: int(v) for k2, v in acu["origen"].value_counts().items()} if "origen" in acu else None,
        "base_trabajo_ref_min": str(cb["ref_min"].min().date()) if len(cb) else None,
        "base_trabajo_filas": int(cb["filas"].sum()) if len(cb) else 0,
        "curada_series": int(len(ck)), "curada_filas": int(ck["filas"].sum()) if len(ck) else 0,
        "curada_ref_min": str(ck["ref_min"].min().date()) if len(ck) else None,
        "dias_desde_ultima_captura_a_hoy": int((HOY - ult_cap).days),
        "proxima_captura_antes_de": str((ult_cap + pd.DateOffset(months=1)).date())})


# ------------------------------------------------------------------------------------------------ s7
def s7():
    p("\n== s7 · ediciones académicas archivadas y vintages en la base")
    out = {}
    for fu in ("ken_french", "shiller", "goyal_welch", "ofr_fsi", "jst_macrohistory"):
        d = C / "crudo" / fu
        eds = sorted(x.name for x in (d / "ediciones").iterdir()) if (d / "ediciones").exists() else []
        descargas = sorted({x.name[:8] for x in d.iterdir() if x.is_file() and re.match(r"\d{8}_", x.name)})
        out[fu] = {"ediciones_archivadas": eds, "dias_descarga": descargas}
        p(fu, "ediciones:", eds, "descargas:", descargas)
    t = pq.read_table(CURADA, columns=["fuente", "vintage"],
                      filters=[("fuente", "in", ["ken_french", "shiller", "goyal_welch", "ofr_fsi"])]).to_pandas()
    vv = t.groupby(["fuente", "vintage"]).size()
    p(vv.to_string())
    out["vintages_curada"] = {f"{a}|{b}": int(v) for (a, b), v in vv.items()}
    ed = pd.read_csv(TABLAS / "academicos_ediciones.csv")
    out["tabla_ediciones"] = {f: sorted(set(g["etiqueta"].astype(str))) for f, g in ed.groupby("fuente")}
    out["shiller_mismo_tamano_oct_nov"] = (C / "crudo/shiller/20261012_ie_data.xls").stat().st_size == (
        C / "crudo/shiller/20261119_ie_data.xls").stat().st_size
    out["gw_mismo_tamano_oct_nov"] = (C / "crudo/goyal_welch/20261012_gw_predictores.xlsx").stat().st_size == (
        C / "crudo/goyal_welch/20261119_gw_predictores.xlsx").stat().st_size
    guardar("s7_academicos", out)


# ------------------------------------------------------------------------------------------------ s8
def buscar(fichero: str, patron: str) -> list[str]:
    lineas = (SRC / fichero).read_text(encoding="utf-8").splitlines()
    return [f"{fichero}:{i + 1}: {l.strip()[:140]}" for i, l in enumerate(lineas) if re.search(patron, l)]


def s8():
    p("\n== s8 · mecanismo de refresco (evidencia en el código)")
    ev = {
        "corte_fijo": buscar("curada.py", r"^CORTE_G2 =") + buscar("curada_precios.py", r"^CORTE_G2 ="),
        "curar_sin_opcion_corte": buscar("curada.py", r"add_argument") + buscar("curada_precios.py", r"add_argument"),
        "corte_en_cli": buscar("__main__.py", r"--corte"),
        "yahoo_period_max": buscar("proveedores/yahoo.py", r"period=.max."),
        "yahoo_reanuda_solo_hoy": buscar("proveedores/yahoo.py", r"startswith\(hoy\)"),
        "alfred_salta_archivo": buscar("fuentes/alfred.py", r"previo = None if refrescar"),
        "fred_incremental": buscar("fuentes/fred.py", r"SOLAPE_DIAS|incremental"),
        "solo_anadir": buscar("base.py", r"^CARGADORES_SOLO_ANADIR"),
        "observado_ahora": buscar("base.py", r"t_obs = pd.Timestamp.now"),
        "construir_baja_sin_sin_red": buscar("base.py", r"if not sin_red:|descargar=not sin_red"),
        "oas_no_integrado": buscar("archivo_oas.py", r"NO se integra"),
        "tools_atraso_solo_diarias": buscar("tools.py", r"^MAX_DIAS_PASO_ATRASO|^MULTIPLO_RITMO|^MAX_DIAS_HABILES"),
        "orden_regeneracion": buscar("__main__.py", r"Orden de regeneración"),
        "fuentes_cli": buscar("__main__.py", r'^    "[a-z]+": \("ingesta'),
        "refrescar_cli": buscar("__main__.py", r"refrescar|refresco"),
        "programada": buscar("archivo_oas.py", r"tarea programada"),
    }
    for k, v in ev.items():
        p(f"- {k}:")
        for l in v:
            p("   ", l)
    guardar("s8_evidencia", ev)


# ------------------------------------------------------------------------------------------------ s9
def s9():
    p("\n== s9 · tablas y logs")
    e = pd.read_csv(TABLAS / "descargas_3b_estado.csv", usecols=["id", "tipo", "fuente", "estado_3b"])
    p(e["estado_3b"].value_counts().to_string())
    guardar("s9_estado_3b", {k: int(v) for k, v in e["estado_3b"].value_counts().items()})
    guardar("s9_estado_3b_por_tipo", {f"{a}|{b}": int(v) for (a, b), v in e.groupby(["tipo", "estado_3b"]).size().items()})
    lg = pd.read_csv(C / "logs" / "descargas.csv")
    guardar("s9_log_descargas", lg[["fecha", "orden", "descargadas", "archivo", "errores"]].astype(str)
            .to_dict("records"))
    p(lg.to_string())
    man = json.loads((C / "series" / "curada_manifiesto.json").read_text(encoding="utf-8"))
    guardar("s9_manifiesto_claves", {k: (v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>")
                                     for k, v in man.items()})
    p({k: (v if not isinstance(v, (dict, list)) else type(v).__name__) for k, v in man.items()})
    # registro de cambios: capas
    rc = pq.read_table(C / "series" / "registro_cambios.parquet", columns=["capa", "en_base_curada"]).to_pandas()
    guardar("s9_registro_capas", {str(k): int(v) for k, v in rc["capa"].value_counts().items()})
    # revisiones de precios de Yahoo (cuántas, cuándo)
    rv = C / "logs" / "revisiones_precios_yahoo.csv"
    if rv.exists():
        r = pd.read_csv(rv)
        colf = [c for c in r.columns if "deteccion" in c or "detect" in c or c == "fecha"]
        guardar("s9_revisiones_yahoo", {"filas": int(len(r)), "tickers": int(r["ticker"].nunique()),
                                        "columnas": r["columna"].value_counts().to_dict() if "columna" in r else None,
                                        "fechas": r[colf[0]].astype(str).str[:10].value_counts().to_dict() if colf else None})
        p("revisiones_precios_yahoo:", len(r), "filas,", r["ticker"].nunique(), "tickers")
    # ultimas fichas: fecha de cada crudo por fuente (último día de descarga)
    ult = {}
    for d in sorted((C / "crudo").iterdir()):
        ficheros = [x for x in d.rglob("*") if x.is_file()]
        fechas = [m.group(1) for x in ficheros for m in [re.match(r"(\d{8})_", x.name)] if m]
        if fechas:
            ult[d.name] = max(fechas)
        elif ficheros:
            ult[d.name] = pd.Timestamp(max(x.stat().st_mtime for x in ficheros), unit="s").strftime("%Y%m%d") + " (mtime)"
        else:
            ult[d.name] = "vacío"
    p(ult)
    guardar("s9_ultima_descarga_crudo", ult)


# ----------------------------------------------------------------------------------------------- s10
def s10():
    p("\n== s10 · riesgo de vuelco de la lista curada en un refresco y lo que gana un re-curado sin red")
    pr = pd.read_csv(TABLAS / "redundancia_pares.csv", usecols=["serie_a", "serie_b", "pearson", "spearman",
                                                                  "misma_fuente", "anios_solape"])
    cerca = pr[(pr["pearson"].between(0.94, 0.96)) & (pr["anios_solape"] >= 5)]
    lc = lista()["series"]
    impl = cerca[cerca["serie_a"].map(lambda s: lc.get(s, {}).get("decision") in ("queda", "alias")) |
                 cerca["serie_b"].map(lambda s: lc.get(s, {}).get("decision") in ("queda", "alias"))]
    p(f"pares con Pearson en [0,94; 0,96] y solape >= 5 años: {len(cerca)}; con alguna serie queda/alias: {len(impl)}")
    guardar("s10_pares_cerca_umbral", {"pares": int(len(cerca)), "con_queda_o_alias": int(len(impl)),
                                       "misma_fuente": int(cerca["misma_fuente"].sum())})
    # filas posteriores al corte ya publicadas hasta hoy en series curadas (gratis con un corte nuevo)
    ids = set(pq.read_table(CURADA, columns=["serie"]).column("serie").unique().to_pylist())
    b = pq.read_table(BASE, columns=["serie", "fuente", "fecha_publicacion"],
                      filters=[("fecha_publicacion", ">", CORTE.to_datetime64())]).to_pandas()
    b = b[b["serie"].isin(ids)]
    h = b[b["fecha_publicacion"] <= HOY]
    p(f"en series curadas: {len(b)} filas tras el corte; publicadas hasta hoy: {len(h)} ({h['serie'].nunique()} series)")
    guardar("s10_recurado_gratis", {"filas_post_corte_curadas": int(len(b)), "hasta_hoy": int(len(h)),
                                    "series_hasta_hoy": int(h["serie"].nunique()),
                                    "por_fuente_hasta_hoy": {k: int(v) for k, v in h["fuente"].value_counts().items() if v}})
    # precios: sesiones crudas tras el corte (de s3)
    s3 = CIFRAS.get("s3_precios", {})
    p(f"precios: {s3.get('raw_post_corte_sesiones')} sesiones crudas tras el corte en {s3.get('raw_post_corte_tickers')} tickers")


if __name__ == "__main__":
    pedidas = sys.argv[1:] or ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"]
    for s in pedidas:
        globals()[s]()
    p(f"\ncifras -> {SALIDA}")
