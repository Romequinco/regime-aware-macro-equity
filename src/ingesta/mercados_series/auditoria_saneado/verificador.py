"""Verificador adversarial (solo lectura) de la auditoría del Tema 1.

Recalcula, con consultas propias (DuckDB/pyarrow/pandas), la cifra clave de cada hallazgo de
angulo1.json, angulo2.json y angulo3.json. No escribe en D: ni en el worktree: solo deja
verificador_cifras.json en la carpeta de la auditoría. Nunca imprime valores ni precios.

Uso:  python verificador.py [seccion ...]    (secciones: series precios codigo tablas; por defecto todas)
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

AQUI = Path(__file__).resolve().parent
CORPUS = Path("D:/tfm_corpus/mercados_series")
WT = _REPO
SRC = WT / "src/ingesta/mercados_series"
TAB = WT / "results/ingesta/mercados_series/tablas"
CUR = (CORPUS / "series/base_curada.parquet").as_posix()
BASE = (CORPUS / "series/base_series.parquet").as_posix()
CORTE = "2026-11-13"
SALIDA = AQUI / "verificador_cifras.json"

con = duckdb.connect()
con.execute("SET threads TO 4")
R: dict[str, dict] = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}


def q(sql: str):
    return con.execute(sql).fetchall()


def q1(sql: str):
    return con.execute(sql).fetchone()[0]


def df(sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def guarda():
    SALIDA.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def linea(fichero: str, patron: str) -> list[int]:
    """Números de línea (1-based) de ``fichero`` (relativo a SRC) que casan con ``patron``."""
    txt = (SRC / fichero).read_text(encoding="utf-8").splitlines()
    return [i + 1 for i, l in enumerate(txt) if re.search(patron, l)]


# ----------------------------------------------------------------------------------------------
# SERIES
# ----------------------------------------------------------------------------------------------
def series():
    cat = pd.read_csv(TAB / "cobertura_series.csv", usecols=["id", "fuente", "frecuencia", "estado"])
    con.register("cat", cat)
    con.execute(f"CREATE OR REPLACE TEMP VIEW cur AS SELECT serie, fecha_referencia fr, fecha_publicacion fp, "
                f"vintage v, valor IS NULL nulo, fuente, nota, unidad, divisa FROM '{CUR}'")

    # ---------------- N01 ------------------------------------------------------------------
    r = {}
    r["filas_curada"] = q1("SELECT count(*) FROM cur")
    r["series_curada"] = q1("SELECT count(DISTINCT serie) FROM cur")
    r["nulos"] = q1("SELECT count(*) FROM cur WHERE nulo")
    r["series_con_nulo"] = q1("SELECT count(DISTINCT serie) FROM cur WHERE nulo")
    r["nulos_sin_nota"] = q1("SELECT count(*) FROM cur WHERE nulo AND (nota IS NULL OR trim(nota)='')")
    r["nulos_por_fuente"] = dict(q("SELECT fuente, count(*) FROM cur WHERE nulo GROUP BY 1 ORDER BY 2 DESC"))
    # causa propia: para cada fila nula, ¿hay otra fila (otro vintage) de la misma referencia con valor,
    # publicada después (luego publicado) o solo antes (retirado)? si no hay ninguna, nunca publicado.
    causas = df("""
        WITH n AS (SELECT serie, fr, fp, v, fuente FROM cur WHERE nulo),
        val AS (SELECT serie, fr, min(fp) fpmin, max(fp) fpmax FROM cur WHERE NOT nulo GROUP BY 1,2)
        SELECT n.fuente, n.serie, n.fr,
           CASE WHEN val.serie IS NULL THEN 'nunca'
                WHEN val.fpmax > n.fp THEN 'luego_publicado'
                ELSE 'retirado' END causa
        FROM n LEFT JOIN val USING (serie, fr)""")
    causas["fr"] = pd.to_datetime(causas["fr"])
    r["causa_simple"] = causas["causa"].value_counts().to_dict()
    nunca = causas[causas.causa == "nunca"]
    r["nunca_por_fuente"] = nunca["fuente"].value_counts().to_dict()
    r["nunca_fred_2025_10"] = int(((nunca.fuente == "fred_alfred") & (nunca.fr == "2025-10-01")).sum())
    r["nunca_fred_pre2006"] = int(((nunca.fuente == "fred_alfred") & (nunca.fr < "2006-01-01")).sum())
    r["nunca_fred_otros"] = int(((nunca.fuente == "fred_alfred") & (nunca.fr >= "2006-01-01")
                                 & (nunca.fr != "2025-10-01")).sum())
    fa = causas[causas.fuente == "fred_alfred"].merge(cat[["id", "frecuencia"]], left_on="serie", right_on="id",
                                                       how="left")
    r["fred_nulos_por_frecuencia"] = fa["frecuencia"].value_counts(dropna=False).to_dict()
    # festivos: filas nulas de series diarias en día laborable que el calendario de su bolsa da cerrado
    import exchange_calendars as xc
    diarias = causas.merge(cat[["id", "frecuencia"]], left_on="serie", right_on="id", how="left")
    diarias = diarias[diarias.frecuencia == "diaria"]
    cal_de = {"boe_curvas": "XLON", "mof_jgb": "XTKS", "boc_curva": "XTSE", "fred_alfred": "XNYS",
              "boc": "XTSE"}
    fest = []
    for fuente, g in diarias.groupby("fuente"):
        if fuente not in cal_de:
            continue
        ini = max(g.fr.min() - pd.Timedelta(days=15), pd.Timestamp("1960-01-04"))
        try:
            cal = xc.get_calendar(cal_de[fuente], start=ini, end="2026-12-31")
        except ValueError:   # calendario con límite inferior (XTKS desde 1997)
            cal = xc.get_calendar(cal_de[fuente], start="1997-01-02", end="2026-12-31")
        ses = set(cal.sessions_in_range(cal.first_session, cal.last_session))
        for _, row in g.iterrows():
            if row.fr.weekday() < 5 and row.fr >= cal.first_session and pd.Timestamp(row.fr) not in ses:
                fest.append((row.serie, str(row.fr.date())))
    r["nulos_en_dia_cerrado"] = len(fest)
    r["nulos_en_dia_cerrado_lista"] = fest[:20]
    r["sabados_mof"] = int(((diarias.fuente == "mof_jgb") & (diarias.fr.dt.weekday == 5)).sum())
    r["fred_diarias_nulas"] = int((diarias.fuente == "fred_alfred").sum())
    R["N01"] = r
    guarda()
    if "solo_N01" in sys.argv:
        return

    # ---------------- N02 ------------------------------------------------------------------
    r = {}
    r["nom6m_filas_2013"] = q1("SELECT count(*) FROM cur WHERE serie='boe:NOM.6M' AND fr>='2013-01-01'")
    r["nom6m_nulos_2013"] = q1("SELECT count(*) FROM cur WHERE serie='boe:NOM.6M' AND fr>='2013-01-01' AND nulo")
    r["nom10y_filas_2013"] = q1("SELECT count(*) FROM cur WHERE serie='boe:NOM.10Y' AND fr>='2013-01-01'")
    r["nom6m_nulos_por_anio_2013"] = dict(q("SELECT year(fr), count(*) FROM cur WHERE serie='boe:NOM.6M' "
                                             "AND fr>='2013-01-01' AND nulo GROUP BY 1 ORDER BY 1"))
    # vista al corte: último registro por (serie, fr) ordenando por fecha de publicación y vintage
    con.execute("""CREATE OR REPLACE TEMP TABLE vista AS
        SELECT serie, fr, fuente, arg_max(nulo, (fp, v)) nulo, arg_max(v, (fp, v)) v
        FROM cur GROUP BY serie, fr, fuente""")
    r["vista_nulos_desde2000"] = q1("SELECT count(*) FROM vista WHERE nulo AND fr>='2000-01-01'")
    r["vista_nulos_desde2000_nom6m"] = q1("SELECT count(*) FROM vista WHERE nulo AND fr>='2000-01-01' "
                                          "AND serie='boe:NOM.6M'")
    # ¿otros plazos con dato esos días?
    r["dias_nom6m_nulo_con_10y_valor"] = q1("""SELECT count(*) FROM cur a JOIN cur b ON a.fr=b.fr
        WHERE a.serie='boe:NOM.6M' AND a.nulo AND a.fr>='2013-01-01' AND b.serie='boe:NOM.10Y' AND NOT b.nulo""")
    R["N02"] = r
    guarda()

    # ---------------- N03 ------------------------------------------------------------------
    s = q("""SELECT serie FROM cur WHERE fr='2025-10-01' GROUP BY serie
             HAVING bool_and(nulo) ORDER BY serie""")
    R["N03"] = {"series_oct2025_siempre_nulo": len(s), "lista": [x[0] for x in s],
                "notas": [x[0] for x in q("SELECT DISTINCT nota FROM cur WHERE fr='2025-10-01' AND nulo")][:3]}
    guarda()

    # ---------------- N04 ------------------------------------------------------------------
    r = {}
    t = df("""WITH val AS (SELECT DISTINCT serie, fr FROM cur WHERE NOT nulo)
              SELECT vista.serie, vista.fr, vista.v FROM vista JOIN val USING (serie, fr) WHERE vista.nulo""")
    t["fr"] = pd.to_datetime(t["fr"])
    r["periodos_nulos_al_corte_con_valor_en_otro_vintage"] = len(t)
    r["series"] = t.serie.nunique()
    r["desde_2000"] = int((t.fr >= "2000-01-01").sum())
    r["desde_2000_por_serie"] = t[t.fr >= "2000-01-01"].serie.value_counts().to_dict()
    for s_ in ["fred:MEDCPIM158SFRBCLE", "fred:TRMMEANCPIM158SFRBCLE"]:
        g = t[t.serie == s_]
        r[s_] = {"periodos": len(g), "vintages": g.v.value_counts().to_dict(),
                 "max_fr": str(g.fr.max().date()) if len(g) else None,
                 "n_2026": int((g.fr >= "2026-01-01").sum())}
    R["N04"] = r
    guarda()

    # ---------------- N05 ------------------------------------------------------------------
    r = {"boc_nulas_2006_09_04": q1("SELECT count(*) FROM cur WHERE fr='2006-09-04' AND nulo AND fuente='boc_curva'"),
         "boc_filas_labour_day_otros_anios": q1("""SELECT count(*) FROM cur WHERE fuente='boc_curva' AND
             month(fr)=9 AND day(fr)<=7 AND dayofweek(fr)=1 AND year(fr)<>2006"""),
         "dgs20_1987_01_01": q("SELECT nulo, count(*) FROM cur WHERE serie='fred:DGS20' AND fr='1987-01-01' GROUP BY 1")}
    R["N05"] = r
    guarda()

    # ---------------- N06 ------------------------------------------------------------------
    r = {}
    con.execute(f"CREATE OR REPLACE TEMP VIEW bas AS SELECT serie, fecha_referencia fr, fecha_publicacion fp, "
                f"vintage v, valor IS NULL nulo FROM '{BASE}'")
    r["nulos_base_trabajo"] = q1("SELECT count(*) FROM bas WHERE nulo")
    r["nulos_base_de_curadas_no_en_curada"] = q1("""
        SELECT count(*) FROM (SELECT serie, fr, v FROM bas WHERE nulo AND fp <= TIMESTAMP '2026-11-13'
                                AND serie IN (SELECT DISTINCT serie FROM cur)) b
        ANTI JOIN (SELECT serie, fr, v FROM cur WHERE nulo) c USING (serie, fr, v)""")
    r["nulos_base_de_curadas_no_en_curada_sin_filtro_fecha"] = q1("""
        SELECT count(*) FROM (SELECT serie, fr, v FROM bas WHERE nulo
                                AND serie IN (SELECT DISTINCT serie FROM cur)) b
        ANTI JOIN (SELECT serie, fr, v FROM cur WHERE nulo) c USING (serie, fr, v)""")
    per = df("""
        WITH b AS (SELECT DISTINCT serie, fr FROM bas WHERE NOT nulo AND fp <= TIMESTAMP '2026-11-13'
                   AND serie IN (SELECT DISTINCT serie FROM cur)),
             c AS (SELECT DISTINCT serie, fr FROM cur WHERE NOT nulo),
             lim AS (SELECT serie, min(fr) fmin, max(fr) fmax FROM cur WHERE NOT nulo GROUP BY 1)
        SELECT b.serie, b.fr, CASE WHEN b.fr > lim.fmax THEN 'final' WHEN b.fr < lim.fmin THEN 'principio'
                                   ELSE 'medio' END pos
        FROM b ANTI JOIN c USING (serie, fr) LEFT JOIN lim USING (serie)""")
    r["periodos_perdidos"] = len(per)
    r["series_afectadas"] = per.serie.nunique()
    r["por_posicion"] = per.pos.value_counts().to_dict()
    r["por_prefijo"] = per.serie.str.split(":").str[0].value_counts().to_dict()
    r["nulos_no_curadas_top"] = dict(q("""SELECT serie, count(*) FROM bas WHERE nulo AND serie NOT IN
        (SELECT DISTINCT serie FROM cur) GROUP BY 1 ORDER BY 2 DESC LIMIT 4"""))
    R["N06"] = r
    guarda()

    # ---------------- F02 ------------------------------------------------------------------
    r = {}
    r["filas_post_corte"] = q1("SELECT count(*) FROM bas WHERE fp > TIMESTAMP '2026-11-13'")
    r["filas_post_corte_ge14"] = q1("SELECT count(*) FROM bas WHERE fp >= TIMESTAMP '2026-11-14'")
    r["series_post_corte"] = q1("SELECT count(DISTINCT serie) FROM bas WHERE fp > TIMESTAMP '2026-11-13'")
    r["post_corte_hasta_hoy"] = q1("SELECT count(*) FROM bas WHERE fp > TIMESTAMP '2026-11-13' AND fp <= TIMESTAMP '2026-11-21'")
    r["post_corte_hasta_hoy_series"] = q1("SELECT count(DISTINCT serie) FROM bas WHERE fp > TIMESTAMP '2026-11-13' AND fp <= TIMESTAMP '2026-11-21'")
    r["post_corte_hasta_20"] = q1("SELECT count(*) FROM bas WHERE fp > TIMESTAMP '2026-11-13' AND fp <= TIMESTAMP '2026-11-20'")
    r["futuras"] = q1("SELECT count(*) FROM bas WHERE fp > TIMESTAMP '2026-11-21'")
    r["max_fp"] = str(q1("SELECT max(fp) FROM bas"))
    r["curadas_hasta_hoy"] = q("""SELECT count(*), count(DISTINCT serie) FROM bas WHERE fp > TIMESTAMP '2026-11-13'
        AND fp <= TIMESTAMP '2026-11-21' AND serie IN (SELECT DISTINCT serie FROM cur)""")[0]
    r["curada_post_corte"] = q1("SELECT count(*) FROM cur WHERE fp > TIMESTAMP '2026-11-13'")
    r["pct"] = round(100 * r["filas_post_corte"] / q1("SELECT count(*) FROM bas"), 3)
    R["F02"] = r
    guarda()

    # ---------------- V01 / V03 -------------------------------------------------------------
    r = {}
    r["fuga"] = q1("SELECT count(*) FROM cur WHERE nota ILIKE '%posible fuga de revisiones%'")
    r["fuga_series"] = q1("SELECT count(DISTINCT serie) FROM cur WHERE nota ILIKE '%posible fuga de revisiones%'")
    r["fuga_por_fuente"] = dict(q("SELECT fuente, count(*) FROM cur WHERE nota ILIKE '%posible fuga de revisiones%' "
                                  "GROUP BY 1 ORDER BY 2 DESC"))
    r["anterior_alfred_sin_fuga"] = q1("""SELECT count(*) FROM cur WHERE nota ILIKE '%anterior a ALFRED%'
        AND NOT nota ILIKE '%posible fuga de revisiones%'""")
    r["anterior_alfred_sin_fuga_2000"] = q("""SELECT count(*), count(DISTINCT serie) FROM cur WHERE
        nota ILIKE '%anterior a ALFRED%' AND NOT nota ILIKE '%posible fuga de revisiones%' AND fr>='2000-01-01'""")[0]
    r["pct_fuga"] = round(100 * r["fuga"] / R["N01"]["filas_curada"], 3)
    r["pct_alfred"] = round(100 * r["anterior_alfred_sin_fuga"] / R["N01"]["filas_curada"], 3)
    tb = q1(f"SELECT count(*) FROM '{BASE}' WHERE nota ILIKE '%posible fuga de revisiones%'")
    r["base_trabajo_pct"] = round(100 * tb / q1("SELECT count(*) FROM bas"), 3)
    R["V01"] = r
    r = {}
    rev = pd.read_csv(TAB / "cobertura_series.csv", usecols=["id", "revisable"])
    con.register("rev", rev)
    r["unico"] = q1("SELECT count(*) FROM cur WHERE v='unico'")
    r["pct"] = round(100 * r["unico"] / R["N01"]["filas_curada"], 3)
    r["unico_revisable"] = q1("SELECT count(*) FROM cur JOIN rev ON cur.serie=rev.id WHERE v='unico' AND rev.revisable")
    r["unico_sin_catalogo"] = q1("SELECT count(*) FROM cur ANTI JOIN rev ON cur.serie=rev.id WHERE v='unico'")
    r["unico_revisable_por_fuente"] = dict(q("SELECT fuente, count(*) FROM cur JOIN rev ON cur.serie=rev.id "
                                             "WHERE v='unico' AND rev.revisable GROUP BY 1"))
    r["unico_por_fuente"] = dict(q("SELECT fuente, count(*) FROM cur WHERE v='unico' GROUP BY 1 ORDER BY 2 DESC"))
    R["V03"] = r
    guarda()

    # ---------------- C01 ------------------------------------------------------------------
    R["C01"] = {"series_mas_1_unidad": q1("SELECT count(*) FROM (SELECT serie FROM cur GROUP BY 1 HAVING count(DISTINCT unidad)>1)"),
                "series_mas_1_divisa": q1("SELECT count(*) FROM (SELECT serie FROM cur GROUP BY 1 HAVING count(DISTINCT coalesce(divisa,'-'))>1)"),
                "registro_escala": q1("SELECT count(*) FROM '" + (CORPUS / "series/registro_cambios.parquet").as_posix() + "' WHERE escala"),
                "registro_escala_en_curada": q1("SELECT count(*) FROM '" + (CORPUS / "series/registro_cambios.parquet").as_posix() + "' WHERE escala AND en_base_curada"),
                "series_escaladas": q1("SELECT count(DISTINCT serie) FROM '" + (CORPUS / "series/registro_cambios.parquet").as_posix() + "' WHERE escala"),
                "series_homogeneizadas": q1("SELECT count(DISTINCT serie) FROM '" + (CORPUS / "series/registro_cambios.parquet").as_posix() + "' WHERE homogeneizacion")}
    # saltos ×100/×1000 entre referencias consecutivas en la vista al corte, lejos de cero (|v|>1 en ambos)
    R["C01"]["saltos_x100_lejos_de_cero"] = q1(f"""
        WITH vv AS (SELECT serie, fecha_referencia fr, arg_max(valor, (fecha_publicacion, vintage)) x
                    FROM '{CUR}' GROUP BY 1,2),
        l AS (SELECT serie, fr, x, lag(x) OVER (PARTITION BY serie ORDER BY fr) x0 FROM vv WHERE x IS NOT NULL)
        SELECT count(*) FROM l WHERE abs(x0)>1 AND abs(x)>1 AND (abs(x/x0) BETWEEN 80 AND 1250 OR abs(x0/x) BETWEEN 80 AND 1250)""")
    guarda()

    # ---------------- C05 ------------------------------------------------------------------
    al = df(f"SELECT alias, canonico FROM '{(CORPUS / 'series/alias.parquet').as_posix()}'")
    con.register("al", al)
    t = df("""WITH pb AS (SELECT serie, min(fp) fp0, min(fr) fr0 FROM bas WHERE NOT nulo GROUP BY 1),
                   pc AS (SELECT serie, min(fp) fp0, min(fr) fr0 FROM cur WHERE NOT nulo GROUP BY 1)
              SELECT al.alias, al.canonico, a.fp0 a_fp, c.fp0 c_fp, a.fr0 a_fr, c.fr0 c_fr
              FROM al LEFT JOIN pb a ON a.serie=al.alias LEFT JOIN pc c ON c.serie=al.canonico""")
    antes = t[t.a_fp < t.c_fp]
    R["C05"] = {"alias": len(t), "empiezan_antes_por_publicacion": len(antes),
                "antes_y_pre2000": int((antes.a_fp < "2000-01-01").sum()),
                "canonico_desde_2000_y_alias_pre2000": int(((antes.a_fp < "2000-01-01") & (antes.c_fp >= "2000-01-01")).sum()),
                "lista_canonico_desde_2000": antes[(antes.a_fp < "2000-01-01") & (antes.c_fp >= "2000-01-01")][["alias", "canonico"]].values.tolist(),
                "por_referencia_antes": int((t.a_fr < t.c_fr).sum()),
                "por_referencia_antes_pre2000": int(((t.a_fr < t.c_fr) & (t.a_fr < "2000-01-01")).sum()),
                "sin_alias_en_base": int(t.a_fp.isna().sum())}
    guarda()

    # ---------------- C08 / C09 ------------------------------------------------------------
    RC = (CORPUS / "series/registro_cambios.parquet").as_posix()
    r = {"retrasadas_en_curada": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND fecha_publicacion_despues > fecha_publicacion_antes"),
         "adelantadas_en_curada": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND fecha_publicacion_despues < fecha_publicacion_antes"),
         "adelantadas_total": q1(f"SELECT count(*) FROM '{RC}' WHERE fecha_publicacion_despues < fecha_publicacion_antes"),
         "retraso_mas_30": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND fecha_publicacion_despues - fecha_publicacion_antes > INTERVAL 30 DAY"),
         "retraso_mas_30_pre2000": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND fecha_publicacion_despues - fecha_publicacion_antes > INTERVAL 30 DAY AND fecha_referencia < '2000-01-01'"),
         "retraso_mas_365_desde_2007": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND fecha_publicacion_despues - fecha_publicacion_antes > INTERVAL 365 DAY AND fecha_referencia >= '2007-01-01'"),
         "con_tope": q1(f"SELECT count(*) FROM '{RC}' WHERE en_base_curada AND con_tope")}
    r["pct_mas30_pre2000"] = round(100 * r["retraso_mas_30_pre2000"] / r["retraso_mas_30"], 1)
    R["C08"] = r
    c9 = {}
    for s_, ini, fin in [("fred:ICSA", "2007-01-01", "2009-05-31"), ("fred:CCSA", "2007-01-01", "2009-08-31")]:
        c9[s_] = q(f"""SELECT count(*), median(date_diff('day', fecha_referencia, fecha_publicacion_antes)),
                        median(date_diff('day', fecha_referencia, fecha_publicacion_despues))
                       FROM '{RC}' WHERE serie='{s_}' AND en_base_curada AND fecha_referencia BETWEEN '{ini}' AND '{fin}'
                       AND fecha_publicacion_despues > fecha_publicacion_antes""")[0]
        c9[s_ + "_fin_tramo"] = str(q1(f"""SELECT max(fecha_referencia) FROM '{RC}' WHERE serie='{s_}' AND en_base_curada
                       AND date_diff('day', fecha_referencia, fecha_publicacion_despues) > 30"""))
    c9["reglas_tramo_no_fiable"] = dict(q(f"SELECT regla, count(*) FROM '{RC}' WHERE en_base_curada AND capa='tramo_no_fiable' "
                                         f"AND fecha_referencia>='2007-01-01' GROUP BY 1 ORDER BY 2 DESC LIMIT 20"))
    R["C09"] = c9
    guarda()

    # ---------------- C11 / L09 / L07 ------------------------------------------------------
    PR = (CORPUS / "series/proyecciones.parquet").as_posix()
    man = json.loads((CORPUS / "series/curada_manifiesto.json").read_text(encoding="utf-8"))
    R["C11"] = {"proyecciones_series": q1(f"SELECT count(DISTINCT serie) FROM '{PR}'"),
                "proyecciones_filas": q1(f"SELECT count(*) FROM '{PR}'"),
                "proyecciones_series_weo": q1(f"SELECT count(DISTINCT serie) FROM '{PR}' WHERE serie LIKE 'imf:%'"),
                "proyecciones_filas_weo": q1(f"SELECT count(*) FROM '{PR}' WHERE serie LIKE 'imf:%'"),
                "manifiesto_claves": {k: v for k, v in man.items() if isinstance(v, (int, str))},
                "filas_base_parquet": q1("SELECT count(*) FROM bas")}
    m = df("""SELECT serie, fuente, min(fp) fp0, min(fr) fr0 FROM cur WHERE NOT nulo GROUP BY 1,2""")
    m2 = df("SELECT serie, min(fp) fp0n FROM cur GROUP BY 1")
    m = m2.merge(m, on="serie", how="left")
    R["L09"] = {"series": len(m), "pub_le_2001_01_02_con_valor": int((m.fp0 <= "2001-01-02").sum()),
                "pub_le_2001_01_02_cualquier_fila": int((m.fp0n <= "2001-01-02").sum()),
                "ref_le_2001_01_02": int((m.fr0 <= "2001-01-02").sum()),
                "ref_le_2000_01_01": int((m.fr0 <= "2000-01-01").sum())}
    R["L09"]["pct"] = round(100 * R["L09"]["pub_le_2001_01_02_con_valor"] / len(m), 1)
    ze = [x[0] for x in q("""SELECT DISTINCT serie FROM cur WHERE regexp_matches(serie,
          '(\\.U2\\.|\\.EA(\\.|$|[0-9])|EA20|EA21|EMU|\\.XM\\.|\\.EU27|\\.EU(\\.|$)|_EA$|\\.I10\\.|\\.I9\\.)') ORDER BY 1""")]
    R["L07"] = {"series_zona_euro_regex": len(ze), "lista": ze}
    guarda()

    series_b()


def series_b():
    cat = pd.read_csv(TAB / "cobertura_series.csv", usecols=["id", "fuente", "frecuencia", "estado"])
    con.execute(f"CREATE OR REPLACE TEMP VIEW cur AS SELECT serie, fecha_referencia fr, fecha_publicacion fp, "
                f"vintage v, valor IS NULL nulo, fuente, nota, unidad, divisa FROM '{CUR}'")
    RC = (CORPUS / "series/registro_cambios.parquet").as_posix()
    # ---------------- N13 / F04 / F05 / V08 ------------------------------------------------
    ult = df("""SELECT serie, fuente, max(fr) fr_max, max(fp) fp_max FROM cur WHERE NOT nulo GROUP BY 1,2""")
    ult = ult.merge(cat.drop(columns=["fuente"]), left_on="serie", right_on="id", how="left")
    eu = ult[ult.serie.str.contains(r"\.UK$|\.US$|HICP_EMP\.UK|HICP_EMP\.US")]
    R["N13"] = {"eurostat_uk_us": eu[eu.fuente == "eurostat"][["serie", "fr_max", "estado"]].astype(str).values.tolist(),
                "activas_en_curada": int((ult.estado == "activa").sum()),
                "retiradas_en_curada": int((ult.estado == "retirada").sum()),
                "estados": ult.estado.value_counts(dropna=False).to_dict()}
    sel = ["bbk:BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A", "yf:GC=F", "yf:^BCOM", "yf:^W5000",
           "eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA20", "oecd:CP.EA20", "oecd:CP.FRA", "oecd:CP.ITA", "oecd:CP.JPN"]
    f4 = ult[ult.serie.isin(sel)][["serie", "fr_max", "fp_max", "estado"]].astype(str).values.tolist()
    R["F04"] = {"ultimas": f4,
                "dias_bbk": (pd.Timestamp(CORTE) - pd.Timestamp(ult.loc[ult.serie == sel[0], "fr_max"].iloc[0])).days}
    # F05: activas cuya última referencia es anterior a 2026-01-01 (mensual o menos)  -> candidatas a paradas
    act = ult[(ult.estado == "activa") & (pd.to_datetime(ult.fr_max) < "2026-01-01")]
    R["F05"] = {"activas_ultima_ref_antes_2026": len(act),
                "lista": act[["serie", "fr_max", "frecuencia"]].astype(str).values.tolist()}
    R["F01"] = {"retiradas_en_curada": int((ult.estado == "retirada").sum()),
                "series_sin_catalogo": int(ult.estado.isna().sum())}
    u = q("""SELECT count(*), min(date_diff('day', fr, fp)), median(date_diff('day', fr, fp)), any_value(v),
             any_value(metodo_publicacion) FROM (SELECT fecha_referencia fr, fecha_publicacion fp, vintage v,
             metodo_publicacion FROM '""" + CUR + "' WHERE serie='fred:USRECD')")[0]
    R["V08"] = {"filas": u[0], "lag_min": u[1], "lag_mediano": u[2], "vintage": u[3], "metodo": u[4],
                "registro": q1(f"SELECT count(*) FROM '{RC}' WHERE serie='fred:USRECD'"),
                "excepciones": sum(1 for l in (SRC / "config/excepciones_publicacion.csv").read_text(encoding="utf-8").splitlines()
                                   if l.startswith("fred:USRECD,") or ",fred:USRECD," in l or l.split(",")[0] in ("USRECD", "fred:USRECD"))}
    guarda()


# ----------------------------------------------------------------------------------------------
# PRECIOS
# ----------------------------------------------------------------------------------------------
PC = (CORPUS / "precios_curados").as_posix() + "/*/*.parquet"
PO = (CORPUS / "precios").as_posix() + "/*/*.parquet"


def _cargar_precios():
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pc AS SELECT ticker, sesion, mercado,
        open IS NULL o_nulo, close IS NULL c_nulo, coalesce(volume,0) > 0 con_vol,
        (open = close AND high = low) plano, close, coalesce(split,1) split, coalesce(dividendo,0) dividendo, divisa
        FROM read_parquet('{PC}', union_by_name=true)""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE po AS SELECT filename f, ticker, sesion, fecha_publicacion fp,
        open IS NULL o_nulo, (open = close AND high = low) plano
        FROM read_parquet('{PO}', filename=true, union_by_name=true)""")


def precios():
    _cargar_precios()
    r = {}
    r["sesiones_curadas"] = q1("SELECT count(*) FROM pc")
    r["cierres_nulos"] = q1("SELECT count(*) FROM pc WHERE c_nulo")
    r["aperturas_nulas"] = q1("SELECT count(*) FROM pc WHERE o_nulo")
    r["aperturas_nulas_crudo"] = q1("SELECT count(*) FROM po WHERE o_nulo")
    r["aperturas_nulas_con_volumen"] = q1("SELECT count(*) FROM pc WHERE o_nulo AND con_vol")
    r["tickers_con_apertura_nula"] = q1("SELECT count(DISTINCT ticker) FROM pc WHERE o_nulo")
    r["antes_2000"] = q1("SELECT count(*) FROM pc WHERE o_nulo AND sesion < '2000-01-01'")
    r["desde_2007"] = q1("SELECT count(*) FROM pc WHERE o_nulo AND sesion >= '2007-01-01'")
    r["desde_2016"] = q1("SELECT count(*) FROM pc WHERE o_nulo AND sesion >= '2016-01-01'")
    r["tickers_mas_20pct"] = q1("SELECT count(*) FROM (SELECT ticker FROM pc GROUP BY 1 HAVING avg(o_nulo::INT) > 0.20)")
    r["por_mercado_top"] = dict(q("SELECT mercado, count(*) FROM pc WHERE o_nulo GROUP BY 1 ORDER BY 2 DESC LIMIT 6"))
    r["pct_xlon"] = round(100 * q1("SELECT avg(o_nulo::INT) FROM pc WHERE mercado='XLON'"), 1)
    r["pct"] = round(100 * r["aperturas_nulas"] / r["sesiones_curadas"], 2)
    # ¿todas las aperturas nulas de la curada eran velas planas en el crudo?
    r["anuladas_no_planas_en_crudo"] = q1("""SELECT count(*) FROM pc JOIN po USING (ticker, sesion)
        WHERE pc.o_nulo AND NOT coalesce(po.plano, false)""")
    R["N07"] = r
    R["N08"] = {t: list(q(f"SELECT count(*) FILTER (WHERE o_nulo), count(*) FROM pc WHERE ticker='{t}'")[0])
                for t in ["VBMFX", "^SKEW"]}
    guarda()

    # N09: sesiones del crudo publicadas hasta el corte que no están en la curada
    r = {}
    r["crudo_total"] = q1("SELECT count(*) FROM po")
    r["crudo_hasta_corte"] = q1("SELECT count(*) FROM po WHERE fp <= TIMESTAMP '2026-11-13'")
    r["crudo_post_corte"] = q1("SELECT count(*) FROM po WHERE fp > TIMESTAMP '2026-11-13'")
    r["crudo_post_corte_tickers"] = q1("SELECT count(DISTINCT ticker) FROM po WHERE fp > TIMESTAMP '2026-11-13'")
    r["hasta_corte_no_en_curada"] = q1("""SELECT count(*) FROM (SELECT ticker, sesion FROM po WHERE fp <= TIMESTAMP '2026-11-13'
        AND ticker IN (SELECT DISTINCT ticker FROM pc)) ANTI JOIN pc USING (ticker, sesion)""")
    r["curada_no_en_crudo"] = q1("SELECT count(*) FROM pc ANTI JOIN po USING (ticker, sesion)")
    r["curada_publicada_post_corte"] = q1("""SELECT count(*) FROM pc JOIN po USING (ticker, sesion)
        WHERE po.fp > TIMESTAMP '2026-11-13'""")
    av = pd.read_csv(TAB / "precios_curados_avisos.csv", usecols=["ticker", "tipo", "n"])
    r["aviso_relleno_n"] = int(av.loc[av.tipo == "sesion_fuera_calendario_relleno", "n"].sum())
    res = pd.read_csv(TAB / "precios_curados_resumen.csv")
    r["tabla_velas_quitadas"] = int(res.velas_quitadas.sum())
    r["tabla_aperturas_anuladas"] = int(res.aperturas_anuladas.sum())
    R["N09"] = r
    R["F02_precios"] = {"sesiones_post_corte": r["crudo_post_corte"], "tickers": r["crudo_post_corte_tickers"]}
    guarda()

    # N12: ficheros del crudo sin curado
    fo = {p.name: p for p in (CORPUS / "precios").glob("*/*.parquet")}
    fc = {p.name for p in (CORPUS / "precios_curados").glob("*/*.parquet")}
    det = {}
    for n in sorted(set(fo) - fc):
        x = q(f"SELECT count(*), min(sesion)::DATE, max(sesion)::DATE FROM '{fo[n].as_posix()}'")[0]
        det[n] = [x[0], str(x[1]), str(x[2])]
    R["N12"] = {"crudo": len(fo), "curados": len(fc), "solo_crudo": det, "solo_curado": sorted(fc - set(fo))}
    guarda()

    # N11 / F03: última sesión de cada ticker frente a la última sesión más frecuente de su mercado
    import exchange_calendars as xc
    from ingesta.mercados_series import eda  # solo el mapa mercado -> nombre de calendario
    ult = df("""SELECT ticker, any_value(mercado) mercado, max(sesion)::DATE u FROM pc GROUP BY 1""")
    ult["u"] = pd.to_datetime(ult["u"])
    moda = ult.groupby("mercado")["u"].agg(lambda s: s.mode().max())
    ult["moda"] = ult.mercado.map(moda)
    atras = ult[ult.u < ult.moda]
    falta = []
    for t in atras.itertuples():
        nombre = eda.CALENDARIO_MERCADO.get(t.mercado)
        try:
            cal = xc.get_calendar(nombre, start="2025-01-02", end="2026-12-31")
            n = len(cal.sessions_in_range(t.u + pd.Timedelta(days=1), t.moda))
        except Exception:
            n = int(np.busday_count((t.u + pd.Timedelta(days=1)).date(), (t.moda + pd.Timedelta(days=1)).date()))
        falta.append((t.ticker, t.mercado, str(t.u.date()), str(t.moda.date()), n))
    R["N11"] = {"tickers_por_detras_de_su_mercado": len(atras), "lista": falta,
                "moda_por_mercado": {k: str(v.date()) for k, v in moda.items()},
                "acaban_2026_11_12": int((ult.u == "2026-11-12").sum()),
                "avisos_no_llega": int((av.tipo == "no_llega_corte").sum()),
                "tickers_curados": len(ult)}
    guarda()

    # N10: huecos de calendario (rachas de sesiones del calendario sin vela) con exchange_calendars
    rachas = {}
    total_falt, tick_falt, desde2000 = 0, 0, 0
    sin_cal = set()
    lst = con.execute("SELECT ticker, any_value(mercado) m, list(sesion ORDER BY sesion) s FROM pc GROUP BY 1").df()
    cache = {}
    for tk, mer, g in lst.itertuples(index=False):
        nombre = eda.CALENDARIO_MERCADO.get(mer)
        ses = pd.DatetimeIndex(g).normalize()
        if nombre is None:
            sin_cal.add(str(mer))
            continue
        if nombre not in cache:
            try:
                cache[nombre] = xc.get_calendar(nombre, start="1962-01-02", end="2026-12-31")
            except ValueError:
                cache[nombre] = xc.get_calendar(nombre, end="2026-12-31")
            except Exception:
                cache[nombre] = None
        cal = cache[nombre]
        if cal is None:
            sin_cal.add(str(mer))
            continue
        a, b = max(ses[0], cal.first_session), min(ses[-1], cal.last_session)
        if a > b:
            continue
        cs = cal.sessions_in_range(a, b)
        cs = cs.tz_localize(None) if cs.tz is not None else cs
        miss = ~cs.isin(ses)
        nm = int(miss.sum())
        if nm:
            total_falt += nm
            tick_falt += 1
            desde2000 += int((miss & (cs >= "2000-01-01")).sum())
            m = np.r_[0, miss.astype(int), 0]
            d = np.diff(m)
            ini, fin = np.where(d == 1)[0], np.where(d == -1)[0]
            lon = fin - ini
            k = int(lon.argmax())
            rachas[tk] = (int(lon[k]), str(cs[ini[k]].date()), str(cs[fin[k] - 1].date()), str(mer))
    top = sorted(rachas.items(), key=lambda x: -x[1][0])
    R["N10"] = {"tickers_con_faltantes": tick_falt, "sesiones_faltantes": total_falt, "faltantes_desde_2000": desde2000,
                "racha_mas_5": sum(1 for v in rachas.values() if v[0] > 5),
                "racha_mas_20": sum(1 for v in rachas.values() if v[0] > 20),
                "top": top[:20], "mercados_sin_calendario": sorted(sin_cal),
                "W5000_mercado": q1("SELECT any_value(mercado) FROM pc WHERE ticker='^W5000'"),
                "W5000_faltantes": rachas.get("^W5000")}
    guarda()

    # C02: saltos de cierre > 50 % sin split ni dividendo ese día ni el siguiente
    con.execute("""CREATE OR REPLACE TEMP TABLE sal AS
        WITH l AS (SELECT ticker, sesion, close c, lag(close) OVER w c0, split, dividendo,
                    lead(split) OVER w split1, lead(dividendo) OVER w div1
                   FROM pc WHERE close IS NOT NULL WINDOW w AS (PARTITION BY ticker ORDER BY sesion))
        SELECT ticker, sesion, c/c0 ratio FROM l
        WHERE c0 IS NOT NULL AND c0 <> 0 AND abs(c/c0 - 1) > 0.5
          AND split = 1 AND coalesce(split1,1) = 1 AND dividendo = 0 AND coalesce(div1,0) = 0""")
    r = {"saltos": q1("SELECT count(*) FROM sal"), "tickers": q1("SELECT count(DISTINCT ticker) FROM sal"),
         "x10": q1("SELECT count(*) FROM sal WHERE ratio >= 10 OR ratio <= 0.1"),
         "desde_2007": q1("SELECT count(*) FROM sal WHERE sesion >= '2007-01-01'"),
         "top": dict(q("SELECT ticker, count(*) FROM sal GROUP BY 1 ORDER BY 2 DESC LIMIT 8")),
         "NVDA": q1("SELECT count(*) FROM sal WHERE ticker='NVDA'"), "VIX": q1("SELECT count(*) FROM sal WHERE ticker='^VIX'"),
         "contrasplits": q1("SELECT count(*) FROM pc WHERE split < 1 AND split > 0"),
         "tickers_contrasplit": q1("SELECT count(DISTINCT ticker) FROM pc WHERE split < 1 AND split > 0"),
         "fraccionarios": q1("SELECT count(*) FROM pc WHERE split <> 1 AND split <> round(split) AND 1/split <> round(1/split)"),
         "tickers_fraccionarios": q1("SELECT count(DISTINCT ticker) FROM pc WHERE split <> 1 AND split <> round(split) AND 1/split <> round(1/split)")}
    # cruce con los avisos de la lista curada (sospechoso / reutilizado)
    import yaml
    lc = yaml.safe_load((SRC / "config/lista_curada.yaml").read_text(encoding="utf-8"))
    marca = _marcas_lista(lc)
    sal = df("SELECT ticker, ratio FROM sal")
    sal["marca"] = sal.ticker.map(lambda t: marca.get(t, ""))
    sin = sal[sal.marca == ""]
    r["saltos_sin_marca"] = len(sin)
    r["tickers_sin_marca"] = sin.ticker.nunique()
    r["x10_sin_marca"] = int(((sin.ratio >= 10) | (sin.ratio <= 0.1)).sum())
    r["tickers_x10_sin_marca"] = sin[(sin.ratio >= 10) | (sin.ratio <= 0.1)].ticker.nunique()
    avs = pd.read_csv(TAB / "precios_curados_avisos.csv", usecols=["ticker", "tipo", "n"])
    con_aviso_salto = set(avs.loc[avs.tipo == "salto_sin_split", "ticker"])
    r["tickers_sin_marca_con_aviso_salto_csv"] = int(sin.ticker.isin(con_aviso_salto).sum() and sin[sin.ticker.isin(con_aviso_salto)].ticker.nunique())
    r["saltos_sin_marca_con_aviso_salto_csv"] = int(sin.ticker.isin(con_aviso_salto).sum())
    r["aviso_csv_salto_sin_split_n"] = int(avs.loc[avs.tipo == "salto_sin_split", "n"].sum())
    r["aviso_csv_salto_sin_split_tickers"] = int(avs.loc[avs.tipo == "salto_sin_split", "ticker"].nunique())
    r["marca_sospechosa"] = int(sal.marca.str.contains("sospech").sum())
    r["marca_reutilizado"] = int(sal.marca.str.contains("reutiliz").sum())
    r["lista_precios_reutilizados"] = sum(1 for v in marca.values() if "reutiliz" in v)
    r["lista_precios_sospechosos"] = sum(1 for v in marca.values() if "sospech" in v)
    r["lista_precios_sospechosos_queda"] = sum(1 for k, v in (lc.get("precios") or {}).items()
                                               if "sospech" in str(v.get("aviso", "")) and v.get("decision") == "queda")
    R["C02"] = r
    guarda()

    # C07: subunidad USX y TWD
    r = {"divisas": dict(q("SELECT divisa, count(DISTINCT ticker) FROM pc GROUP BY 1 ORDER BY 2 DESC")),
         "usx_tickers": [x[0] for x in q("SELECT DISTINCT ticker FROM pc WHERE divisa='USX'")],
         "usx_sesiones": q1("SELECT count(*) FROM pc WHERE divisa='USX'"),
         "usx_sesiones_por_ticker": dict(q("SELECT ticker, count(*) FROM pc WHERE divisa='USX' GROUP BY 1")),
         "twd_post_2020_10_30_por_ticker": dict(q("SELECT ticker, count(*) FROM pc WHERE divisa='TWD' AND sesion > '2020-10-30' GROUP BY 1")),
         "usx_en_divisas_py": linea("divisas.py", r"USX"), "usx_en_universo_py": linea("universo.py", r"USX"),
         "ultima_fecha_ecb_TWD": str(q1(f"SELECT max(fecha_referencia) FROM '{CUR}' WHERE serie='ecb:EXR.D.TWD.EUR' AND valor IS NOT NULL")),
         "ultima_fecha_ecb_CNY": str(q1(f"SELECT max(fecha_referencia) FROM '{CUR}' WHERE serie='ecb:EXR.D.CNY.EUR' AND valor IS NOT NULL")),
         "primera_fecha_ecb_CNY": str(q1(f"SELECT min(fecha_referencia) FROM '{CUR}' WHERE serie='ecb:EXR.D.CNY.EUR' AND valor IS NOT NULL")),
         "cny_sesiones_antes_fx": q1(f"""SELECT count(*) FROM pc WHERE divisa='CNY' AND sesion < (SELECT min(fecha_referencia)
              FROM '{CUR}' WHERE serie='ecb:EXR.D.CNY.EUR' AND valor IS NOT NULL)""")}
    R["C07"] = r
    guarda()


def _marcas_lista(lc) -> dict[str, str]:
    """ticker -> texto del campo aviso de su entrada en lista_curada.yaml (sección precios)."""
    pr = lc.get("precios", {}) or {}
    return {str(k): str(v.get("aviso", "")) for k, v in pr.items() if isinstance(v, dict) and v.get("aviso")}


# ----------------------------------------------------------------------------------------------
# TABLAS, CÓDIGO Y RESTO (lo que no es un recorrido de la base)
# ----------------------------------------------------------------------------------------------
def tablas():
    import yaml
    con.execute(f"CREATE OR REPLACE TEMP VIEW cur AS SELECT serie, fecha_referencia fr, fecha_publicacion fp, "
                f"vintage v, valor IS NULL nulo, fuente, nota FROM '{CUR}'")
    con.execute(f"CREATE OR REPLACE TEMP VIEW bas AS SELECT serie, fecha_referencia fr, fecha_publicacion fp, "
                f"vintage v, valor IS NULL nulo, fuente FROM '{BASE}'")
    RC = (CORPUS / "series/registro_cambios.parquet").as_posix()

    # C01 (complemento): filas ×100 de la homogeneización, en el registro y en la curada
    R.setdefault("C01", {})
    R["C01"]["registro_homog_x100"] = q1(f"SELECT count(*) FROM '{RC}' WHERE homogeneizacion AND factor_escala=100")
    R["C01"]["registro_homog_x100_en_curada"] = q1(f"SELECT count(*) FROM '{RC}' WHERE homogeneizacion AND factor_escala=100 AND en_base_curada")
    # el único salto ×100 lejos de cero: serie y fecha (sin valores)
    R["C01"]["salto_x100_donde"] = [list(map(str, x)) for x in q(f"""
        WITH vv AS (SELECT serie, fecha_referencia fr, arg_max(valor, (fecha_publicacion, vintage)) x
                    FROM '{CUR}' GROUP BY 1,2),
        l AS (SELECT serie, fr, x, lag(x) OVER (PARTITION BY serie ORDER BY fr) x0 FROM vv WHERE x IS NOT NULL)
        SELECT serie, fr::DATE FROM l WHERE abs(x0)>1 AND abs(x)>1 AND (abs(x/x0) BETWEEN 80 AND 1250 OR abs(x0/x) BETWEEN 80 AND 1250)""")]
    # C05 con la definición del 04: primera publicación en la base de trabajo, alias frente a canónico
    al = df(f"SELECT alias, canonico FROM '{(CORPUS / 'series/alias.parquet').as_posix()}'")
    con.register("al", al)
    t = df("""WITH pb AS (SELECT serie, min(fp) fp0 FROM bas GROUP BY 1)
              SELECT al.alias, al.canonico, a.fp0 a_fp, c.fp0 c_fp FROM al LEFT JOIN pb a ON a.serie=al.alias
              LEFT JOIN pb c ON c.serie=al.canonico""")
    m = t[t.a_fp < t.c_fp]
    R["C05"]["base_vs_base_antes"] = len(m)
    R["C05"]["base_vs_base_antes_pre2000"] = int((m.a_fp < "2000-01-01").sum())
    R["C05"]["base_vs_base_canonico_desde_2000"] = int(((m.a_fp < "2000-01-01") & (m.c_fp >= "2000-01-01")).sum())
    R["C05"]["base_vs_base_lista_canonico_2000"] = m[(m.a_fp < "2000-01-01") & (m.c_fp >= "2000-01-01")][["alias", "canonico"]].values.tolist()
    R["C05"]["base_vs_base_canonico_oecd_1999_03"] = int(((m.a_fp < "2000-01-01") & m.canonico.str.startswith("oecd:")
                                                          & (m.c_fp.dt.strftime("%Y-%m") == "1999-03")).sum())
    guarda()

    # N13 (independiente de tools): diarias/semanales de la curada sin publicar en > 14 días hábiles antes del corte
    cat = pd.read_csv(TAB / "cobertura_series.csv", usecols=["id", "frecuencia", "estado"])
    u = df("SELECT serie, max(fp)::DATE fp_max FROM cur WHERE NOT nulo GROUP BY 1").merge(cat, left_on="serie", right_on="id", how="left")
    u["dh"] = [int(np.busday_count(pd.Timestamp(x).date(), pd.Timestamp(CORTE).date())) for x in u.fp_max]
    dw = u[u.frecuencia.isin(["diaria", "semanal"])]
    par = dw[dw.dh > 10]
    R["N13"]["diarias_semanales_mas_10_dh"] = len(par)
    R["N13"]["diarias_semanales_mas_10_dh_por_estado"] = par.estado.value_counts().to_dict()
    R["N13"]["diarias_semanales_mas_10_dh_activas"] = par[par.estado == "activa"].serie.tolist()
    guarda()

    # N14: incidencias de hueco del EDA de series curadas
    inc = pd.read_csv(TAB / "eda_series_incidencias.csv", usecols=["serie", "fuente", "tipo", "fecha", "fecha_fin", "tamano"])
    cs = set(pd.read_csv(TAB / "curada_resumen.csv", usecols=["serie"]).serie)
    h = inc[(inc.tipo.str.contains("hueco")) & inc.serie.isin(cs)]
    R["N14"] = {"incidencias_hueco_curadas": len(h), "series": h.serie.nunique(), "tipos": inc.tipo.value_counts().to_dict(),
                "con_fin_desde_2000": int((pd.to_datetime(h.fecha_fin, errors="coerce") >= "2000-01-01").sum()),
                "isk": h[h.serie == "ecb:EXR.D.ISK.EUR"][["fecha", "fecha_fin"]].astype(str).values.tolist()[:3]}
    guarda()

    # F01: paradas por una regla propia (última referencia nueva hace más de 365 días o retirada)
    pr = df("""WITH p AS (SELECT serie, fr, min(fp) fp1 FROM cur WHERE NOT nulo GROUP BY 1,2)
               SELECT serie, max(fp1)::DATE ult_nueva FROM p GROUP BY 1""").merge(cat, left_on="serie", right_on="id", how="left")
    pr["dias"] = (pd.Timestamp(CORTE) - pd.to_datetime(pr.ult_nueva)).dt.days
    R["F01"]["parado_mas_365_dias_o_retirada"] = int(((pr.dias > 365) | (pr.estado == "retirada")).sum())
    R["F01"]["parado_mas_365_dias"] = int((pr.dias > 365).sum())
    R["F01"]["sin_dato_nuevo_en_45_dias"] = int((pr.dias > 45).sum())
    guarda()

    # F07: pares cerca del umbral
    rp = pd.read_csv(TAB / "redundancia_pares.csv", usecols=["serie_a", "serie_b", "pearson", "spearman", "anios_solape"])
    R["F07"] = {"pares_094_096_5anios": int(((rp.pearson.abs() >= 0.94) & (rp.pearson.abs() <= 0.96) & (rp.anios_solape >= 5)).sum()),
                "pares_094_096_5anios_pearson_firmado": int(((rp.pearson >= 0.94) & (rp.pearson <= 0.96) & (rp.anios_solape >= 5)).sum()),
                "pares_total": len(rp),
                "UMBRAL_ALIAS": linea("seleccion.py", r"^UMBRAL_ALIAS"), "UNICAS_F4": linea("seleccion.py", r"^UNICAS_F4|^DUDOSOS_RESUELTOS_F4"),
                "escribe_lista": linea("seleccion.py", r"lista_curada.yaml\": escribir_yaml")}
    guarda()

    # V04: solo-añadir
    sa = pd.read_csv(TAB / "solo_anadir_ultima.csv")
    sa["pref"] = sa.serie.str.split(":").str[0]
    R["V04"] = {"series": len(sa), "observado": sa.observado.unique().tolist(),
                "guardada_gana_valor_por_prefijo": sa.groupby("pref").guardada_gana_valor.sum().astype(int).to_dict(),
                "guardada_gana_valor_total": int(sa.guardada_gana_valor.sum()),
                "conservadas_por_prefijo": sa.groupby("pref").conservadas.sum().astype(int).to_dict(),
                "conservadas_mas_ya": int(sa.conservadas.sum() + sa.ya_conservadas.sum()),
                "series_bce_con_conservadas": int(((sa.pref == "ecb") & ((sa.conservadas + sa.ya_conservadas) > 0)).sum()),
                "curada_valor_anterior_bce": q1("SELECT count(*) FROM cur WHERE fuente='bce' AND v<>'unico'"),
                "curada_series_bce_vintage_fecha": q1("SELECT count(DISTINCT serie) FROM cur WHERE fuente='bce' AND v<>'unico'"),
                "CARGADORES_SOLO_ANADIR": linea("base.py", r"^CARGADORES_SOLO_ANADIR")}
    guarda()

    # V05: OAS de ICE
    AO = (CORPUS / "archivo/ice_oas/acumulado.parquet").as_posix()
    oas = [x[0] for x in q(f"SELECT DISTINCT serie FROM '{AO}' ORDER BY 1")]
    con.execute("CREATE OR REPLACE TEMP TABLE oas AS SELECT unnest(?::VARCHAR[]) s", [oas])
    R["V05"] = {"series": len(oas), "capturas": len(list((CORPUS / "archivo/ice_oas").glob("captura_*.parquet"))),
                "fechas_por_serie_archivo": sorted(set(x[0] for x in q(f"SELECT count(DISTINCT fecha_referencia) FROM '{AO}' GROUP BY serie"))),
                "rango_archivo": [str(x) for x in q(f"SELECT min(fecha_referencia)::DATE, max(fecha_referencia)::DATE FROM '{AO}'")[0]],
                "fechas_por_serie_base": sorted(set(x[0] for x in q("SELECT count(DISTINCT fr) FROM bas WHERE serie IN (SELECT s FROM oas) GROUP BY serie"))),
                "fechas_por_serie_curada": sorted(set(x[0] for x in q("SELECT count(DISTINCT fr) FROM cur WHERE serie IN (SELECT s FROM oas) GROUP BY serie"))),
                "vintages_por_serie_base": sorted(set(x[0] for x in q("SELECT count(DISTINCT v) FROM bas WHERE serie IN (SELECT s FROM oas) GROUP BY serie"))),
                "ejecuciones_registro": len(pd.read_csv(CORPUS / "archivo/ice_oas/registro.csv")),
                "no_se_integra": linea("archivo_oas.py", r"NO se integra")}
    guarda()

    # V06 / L03: WEO
    W = (CORPUS / "bloque4/imf_weo.parquet").as_posix()
    R["V06"] = {"vintages_bloque4": dict(q(f"SELECT vintage, count(DISTINCT serie) FROM '{W}' GROUP BY 1 ORDER BY 1")),
                "series_bloque4": q1(f"SELECT count(DISTINCT serie) FROM '{W}'"),
                "pub_por_vintage": {str(a): str(b) for a, b in q(f"SELECT vintage, min(fecha_publicacion)::DATE FROM '{W}' GROUP BY 1 ORDER BY 1")},
                "curada_series_imf": q1("SELECT count(DISTINCT serie) FROM cur WHERE fuente='imf_weo'"),
                "curada_filas_imf": q1("SELECT count(*) FROM cur WHERE fuente='imf_weo'"),
                "curada_primera_pub_imf": str(q1("SELECT min(fp)::DATE FROM cur WHERE fuente='imf_weo'")),
                "base_vintages_imf": [x[0] for x in q("SELECT DISTINCT v FROM bas WHERE fuente='imf_weo' ORDER BY 1")],
                "dbnomics_meta": len(list((CORPUS / "crudo/imf_weo").glob("*dbnomics*.meta.json"))),
                "dbnomics_datos": len([p for p in (CORPUS / "crudo/imf_weo").glob("*dbnomics*") if not p.name.endswith(".meta.json")])}
    est = pd.read_csv(TAB / "descargas_3b_estado.csv")
    weo = est[est.id.astype(str).str.contains("WEO|weo|imf", regex=True)]
    R["L03"] = {"filas_estado_weo": len(weo), "estados": weo.estado_3b.value_counts().to_dict(),
                "motivos_muestra": weo.motivo_3b.astype(str).str[:160].unique().tolist()[:3]}
    guarda()

    # V07: ediciones académicas
    ed = {}
    for f in ["ken_french", "shiller", "goyal_welch", "ofr_fsi"]:
        d = CORPUS / "crudo" / f / "ediciones"
        ed[f] = sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []
    dias = sorted({p.name[:8] for f in ["ken_french", "shiller", "goyal_welch", "ofr_fsi"]
                   for p in (CORPUS / "crudo" / f).glob("2026*") if p.is_file()})
    R["V07"] = {"ediciones": ed, "dias_descarga": dias,
                "curada_kf_vintages": dict(q("SELECT v, count(*) FROM cur WHERE fuente='ken_french' GROUP BY 1 ORDER BY 1")),
                "curada_gw_vintages": dict(q("SELECT v, count(*) FROM cur WHERE fuente='goyal_welch' GROUP BY 1 ORDER BY 1")),
                "archivar_ediciones": linea("fuentes/academicos.py", r"^def archivar_ediciones")}
    guarda()

    # V08 (complemento): excepciones de USRECD en el CSV
    ex = pd.read_csv(SRC / "config/excepciones_publicacion.csv")
    col = [c for c in ex.columns if ex[c].astype(str).str.contains("USRECD").any()]
    R["V08"]["excepciones_csv"] = int(ex[col[0]].astype(str).str.contains("USRECD").sum()) if col else 0
    R["V08"]["preprocesado_345"] = (SRC / "config/preprocesado.yaml").read_text(encoding="utf-8").splitlines()[344][:90]
    guarda()

    # C03 / C04 / L04 / L06: lista curada y avisos
    lc = yaml.safe_load((SRC / "config/lista_curada.yaml").read_text(encoding="utf-8"))
    prc = lc.get("precios", {})
    av = pd.read_csv(TAB / "precios_curados_avisos.csv", dtype={"ticker": str})
    al_ = av[av.tipo == "aviso_lista"]
    reut = [k for k, v in prc.items() if "reutiliz" in str(v.get("aviso", ""))]
    R["C03"] = {"reutilizados_lista": len(reut),
                "reutilizados_lista_queda": sum(1 for k in reut if prc[k].get("decision") == "queda"),
                "reutilizados_avisos_csv": int(al_.nota.astype(str).str.contains("reutiliz").sum()),
                "tools_lee_lista_curada": linea("tools.py", r"lista_curada"),
                "sp500_cobertura_tabla": pd.read_csv(TAB / "sp500_cobertura_3b1.csv").astype(str).values.tolist()}
    # huecos > 365 días en ficheros curados de reutilizados
    gaps = df(f"""WITH s AS (SELECT ticker, sesion, lag(sesion) OVER (PARTITION BY ticker ORDER BY sesion) s0
                  FROM read_parquet('{(CORPUS / 'precios_curados').as_posix()}/yahoo/*.parquet'))
                  SELECT ticker, max(date_diff('day', s0, sesion)) g FROM s GROUP BY 1""")
    R["C03"]["reutilizados_con_hueco_mas_365"] = int(gaps[gaps.ticker.isin(reut)].g.gt(365).sum())
    sosp = [k for k, v in prc.items() if "sospech" in str(v.get("aviso", ""))]
    eda_p = pd.read_csv(TAB / "eda_precios.csv", dtype={"ticker": str})
    colprop = eda_p.columns[-1]
    R["C04"] = {"lista_sospechosos": len(sosp), "lista_sospechosos_queda": sum(1 for k in sosp if prc[k].get("decision") == "queda"),
                "avisos_tipo_serie_sospechosa": int((av.tipo == "serie_sospechosa").sum()),
                "eda_precios_serie_sospechosa": int(eda_p[colprop].astype(str).str.contains("serie_sospechosa").sum()),
                "estado_3b_serie_sospechosa": int((est.tipo.astype(str) == "serie_sospechosa").sum())}
    R["L06"] = {"historia_recortada_avisos": int(al_.nota.astype(str).str.contains("historia recortada").sum()),
                "correlacion_baja_avisos": int(al_.nota.astype(str).str.contains("correlación semanal baja").sum()),
                "max_dias_recortados": None}
    guarda()

    # L01 / L10: estado del 3b
    R["L01"] = {"estado_3b": est.estado_3b.value_counts().to_dict(), "filas": len(est),
                "limitaciones": int((est.estado_3b == "limitacion_declarada").sum()),
                "ids_unicos_limitacion": int(est.loc[est.estado_3b == "limitacion_declarada", "id"].nunique()),
                "tipos_limitacion": est.loc[est.estado_3b == "limitacion_declarada", "tipo"].value_counts().to_dict()}
    guarda()

    # L08: cartera
    B = (CORPUS / "cartera/baselines_brutos.parquet").as_posix()
    Cc = (CORPUS / "cartera/baselines_costes.parquet").as_posix()
    R["L08"] = {"brutos": [list(map(str, x)) for x in q(f"SELECT estrategia, min(fecha)::DATE, max(fecha)::DATE FROM '{B}' GROUP BY 1 ORDER BY 1")],
                "costes": [list(map(str, x)) for x in q(f"SELECT estrategia, min(fecha)::DATE, max(fecha)::DATE FROM '{Cc}' GROUP BY 1 ORDER BY 1")],
                "mtime": {p.name: pd.Timestamp(p.stat().st_mtime, unit="s").strftime("%Y-%m-%d") for p in (CORPUS / "cartera").iterdir()},
                "estado_6040": est.loc[est.id.astype(str).str.contains("6040|60/40|ucits", case=False), ["id", "estado_3b"]].astype(str).values.tolist()}
    guarda()

    # L02: supervivencia del S&P 500, cálculo propio: días-tramo (L-V desde 1996) con sesión curada del ticker
    sp = df(f"SELECT ticker, alta, baja FROM '{(CORPUS / 'constituyentes/sp500.parquet').as_posix()}'")
    ses = df(f"""SELECT replace(regexp_extract(filename, '[^/\\\\]+$'), '.parquet', '') tk, sesion::DATE s
                 FROM read_parquet('{(CORPUS / 'precios_curados').as_posix()}/yahoo/*.parquet', filename=true)
                 WHERE sesion >= '1996-01-01'""")
    con.register("sp", sp)
    con.register("ses", ses)
    noreut = set(prc) - set(reut)
    con.execute("CREATE OR REPLACE TEMP TABLE okt AS SELECT unnest(?::VARCHAR[]) tk", [sorted(noreut)])
    import exchange_calendars as xc
    dias = xc.get_calendar("XNYS", start="1996-01-02", end=CORTE).sessions
    con.register("dias", pd.DataFrame({"d": dias.date}))
    base_sql = """FROM dias JOIN sp ON dias.d >= sp.alta::DATE AND dias.d <= coalesce(sp.baja::DATE, DATE '2026-11-13')"""
    tot = q1(f"SELECT count(*) {base_sql}")
    con_p = q1(f"""SELECT count(*) {base_sql} JOIN ses ON ses.tk = sp.ticker AND ses.s = dias.d
                  WHERE sp.ticker IN (SELECT tk FROM okt)""")
    con_p07 = q(f"""SELECT count(*) FILTER (WHERE ses.s IS NOT NULL AND sp.ticker IN (SELECT tk FROM okt)), count(*)
                  {base_sql} LEFT JOIN ses ON ses.tk = sp.ticker AND ses.s = dias.d WHERE dias.d >= DATE '2007-01-01'""")[0]
    leh = q("""SELECT count(*), count(*) FILTER (WHERE ses.s IS NOT NULL AND sp.ticker IN (SELECT tk FROM okt))
               FROM sp LEFT JOIN ses ON ses.tk = sp.ticker AND ses.s = DATE '2008-09-15'
               WHERE sp.alta::DATE <= DATE '2008-09-15' AND coalesce(sp.baja::DATE, DATE '2099-01-01') >= DATE '2008-09-15'""")[0]
    R["L02"] = {"dias_tramo": tot, "con_precio": con_p, "pct": round(100 * con_p / tot, 2),
                "pct_desde_2007": round(100 * con_p07[0] / con_p07[1], 2),
                "lehman_miembros": leh[0], "lehman_con_precio": leh[1],
                "nota": "sesiones XNYS; miembro con precio = sesión curada en su fichero y ticker no marcado reutilizado"}
    guarda()


# ----------------------------------------------------------------------------------------------
# CÓDIGO: las referencias fichero:línea que citan los auditores
# ----------------------------------------------------------------------------------------------
REFERENCIAS = {   # (fichero relativo a SRC, línea citada, patrón que debe aparecer en esa línea)
    "F02": [("curada.py", 79, r"CORTE_G2 = "), ("curada_precios.py", 89, r"CORTE_G2 = "),
            ("seleccion.py", 864, r"FECHA_CORTE = "), ("estado_3b.py", 63, r"FECHA_CORTE = ")],
    "F03": [("proveedores/yahoo.py", 341, r"REVISIONES_TOLERADAS = \(\"volume\", \"dividendo\"\)"),
            ("almacen.py", 319, r"filas guardadas cambiarían")],
    "F05": [("tools.py", 448, r"MAX_DIAS_HABILES_ATRASO = 10"), ("tools.py", 454, r"MAX_DIAS_PASO_ATRASO = 7"),
            ("tools.py", 455, r"MULTIPLO_RITMO = 3")],
    "F06": [("seleccion.py", 165, r"ULTIMO_REFRESCO"), ("estado_3b.py", 73, r"FECHA_TANDA"),
            ("__main__.py", 294, r"FUENTES_CLI = \{"), ("__main__.py", 359, r"--refrescar"),
            ("fuentes/alfred.py", 219, r"refrescar"), ("proveedores/yahoo.py", 204, r"period=\"max\""),
            ("proveedores/yahoo.py", 385, r"startswith\(hoy\)"), ("fuentes/fred.py", 113, r"SOLAPE_DIAS"),
            ("config/lags.yaml", 37, r"regenerarla")],
    "F07": [("seleccion.py", 166, r"UMBRAL_ALIAS = 0.95"), ("seleccion.py", 200, r"UNICAS_F4"),
            ("seleccion.py", 202, r"DUDOSOS_RESUELTOS_F4"), ("seleccion.py", 1351, r"lista_curada.yaml")],
    "V01": [("catalogo.py", 50, r"NOTA_REVISABLE"), ("fuentes/bce.py", 71, r"NOTA_PREVIA")],
    "V03": [("contrato.py", 95, r"unico"), ("fuentes/academicos.py", 50, r"OFR.*unico")],
    "V04": [("base.py", 100, r"CARGADORES_SOLO_ANADIR"), ("base.py", 613, r"guardada_gana_valor")],
    "V05": [("archivo_oas.py", 25, r"NO se integra"), ("archivo_oas.py", 37, r"tarea programada")],
    "V06": [("fuentes/imf.py", 93, r"2025-11-19"), ("fuentes/imf.py", 106, r"EDICIONES_DBNOMICS"),
            ("README.md", 571, r"2025-04 a 2026-10")],
    "V07": [("fuentes/academicos.py", 920, r"def archivar_ediciones")],
    "V08": [("config/preprocesado.yaml", 346, r"vintage_exacto"), ("config/lags.yaml", 518, r"NBER_RECESSION_DAILY")],
    "N13": [("tools.py", 447, r"hasta el 3b-2")],
    "C06": [("tools.py", 501, r"base: BaseLike = \"trabajo\""), ("tools.py", 650, r"base: BaseLike = \"trabajo\"")],
}


def codigo():
    r = {}
    for hid, refs in REFERENCIAS.items():
        ok = []
        for f, n, pat in refs:
            lineas = (SRC / f).read_text(encoding="utf-8").splitlines()
            ok.append([f"{f}:{n}", bool(re.search(pat, lineas[n - 1]))])
        r[hid] = ok
    r["sin_opcion_corte"] = {f: not re.search(r"--corte", (SRC / f).read_text(encoding="utf-8"))
                             for f in ("curada.py", "curada_precios.py", "seleccion.py", "estado_3b.py", "__main__.py")}
    import ast
    tree = ast.parse((SRC / "__main__.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(tree):
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", "") == "FUENTES_CLI" for t in nodo.targets):
            r["n_FUENTES_CLI"] = len(nodo.value.keys)
    r["divisas_py_USX"] = linea("divisas.py", r"USX")
    r["universo_py_USX"] = linea("universo.py", r"USX")
    r["tools_lee_avisos_lista"] = linea("tools.py", r"precios_curados_avisos|aviso_lista|yaml\.safe_load")
    R["_codigo"] = r
    guarda()


# ----------------------------------------------------------------------------------------------
# INFORME: veredictos (verificacion.json) a partir de verificador_cifras.json
# ----------------------------------------------------------------------------------------------
def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)


def informe():
    g = lambda k: R[k]   # noqa: E731
    f = _fmt
    N01, N02, N04, N06, N07, N09, N10, N11 = (g(k) for k in ("N01", "N02", "N04", "N06", "N07", "N09", "N10", "N11"))
    V01, V03, C02, C05, L02, L09 = (g(k) for k in ("V01", "V03", "C02", "C05", "L02", "L09"))
    aud = {}
    for a in ("angulo1.json", "angulo2.json", "angulo3.json"):
        for h in json.loads((AQUI / a).read_text(encoding="utf-8")):
            aud[h["id"]] = h
    V = []

    def v(id_, ver, ca, cv, corr, como):
        V.append({"id": id_, "gravedad_auditor": aud[id_].get("gravedad_propuesta"), "veredicto": ver,
                  "cifra_clave_auditor": ca, "cifra_clave_verificador": cv, "correcciones": corr, "como": como})

    # ------------------------------------------------------------------ ángulo 1
    v("N01", "CORREGIDO", "26.200 nulos en 94 series; 7 festivos; 15.688 vintage antiguo luego publicado; 3.138 retirados; "
      "6.578 plazo de curva; 768 nunca publicado pre-2006; 21 cierre 2025-10",
      f"{f(N01['nulos'])} nulos en {N01['series_con_nulo']} series, {N01['nulos_sin_nota']} sin nota; luego publicado "
      f"{f(N01['causa_simple']['luego_publicado'])}, retirado {f(N01['causa_simple']['retirado'])}, nunca con valor "
      f"{f(N01['causa_simple']['nunca'])} (BoE 5.490 + MoF 1.085 + BoC 6 + FRED 793 = 21 cierre + 771 pre-2006 + 1); "
      f"en día cerrado según exchange_calendars: {N01['nulos_en_dia_cerrado']} (6 BoC 2006-09-04 + fred:DGS20 1987-01-01); "
      f"FRED diarias nulas {N01['fred_diarias_nulas']}; sábados MoF {N01['sabados_mof']}",
      "Totales y causas principales correctos. El desglose se contradice con N05: los 7 «festivos» incluyen "
      "fred:DGS20 1987-01-01, que N05 (y su nota: «hueco permanente: FRED sin valor más de 31 días») dice que no es "
      "festivo; festivos reales = 6 (BoC). Y «plazo de curva no publicado» = 6.578 mete 3 filas FRED diarias (marcas de "
      "hueco) además de las 6.575 de BoE+MoF. La frase del plan sobre festivos no aparece en registro_descarga.md (grep de "
      "26.200/19.619 sin resultados): la discrepancia es con el brief, no con el plan del repo.",
      "DuckDB sobre base_curada: causa = existe otra fila (serie, fecha_referencia) con valor publicada después / solo "
      "antes / nunca; festivos con exchange_calendars (XLON, XTKS, XTSE, XNYS) sobre filas nulas de series diarias")
    v("N02", "CONFIRMADO", "boe:NOM.6M 1.299 nulos de 3.504 desde 2013 (37,1 %); 1.619 nulos ≥2000 en la vista al corte",
      f"{f(N02['nom6m_nulos_2013'])} de {f(N02['nom6m_filas_2013'])}; NOM.10Y con valor en los {f(N02['dias_nom6m_nulo_con_10y_valor'])} "
      f"días; vista al corte ≥2000: {f(N02['vista_nulos_desde2000'])} nulos, {f(N02['vista_nulos_desde2000_nom6m'])} de NOM.6M (80,2 %)",
      "", "conteo directo + vista al corte con arg_max(nulo, (fecha_publicacion, vintage)) por (serie, fecha_referencia)")
    v("N03", "CONFIRMADO", "21 series FRED sin dato de 2025-10 en ningún vintage",
      f"{g('N03')['series_oct2025_siempre_nulo'] - 1} series FRED con fecha_referencia 2025-10-01 nula en todos sus vintages "
      "(la consulta da 22 porque boe:NOM.6M también es nula ese día, sin relación con el cierre)", "",
      "GROUP BY serie HAVING bool_and(valor IS NULL) en fecha_referencia = 2025-10-01")
    m, t = N04["fred:MEDCPIM158SFRBCLE"], N04["fred:TRMMEANCPIM158SFRBCLE"]
    v("N04", "CONFIRMADO", "3.126 periodos nulos al corte con valor previo, 22 series, 218 desde 2000; MEDCPI 43, TRMMEAN 51",
      f"{f(N04['periodos_nulos_al_corte_con_valor_en_otro_vintage'])} en {N04['series']} series, {N04['desde_2000']} desde 2000; "
      f"MEDCPI {m['periodos']} (vintages {m['vintages']}), TRMMEAN {t['periodos']} ({t['vintages']}); los 2 de 2026 son ago–sep",
      "", "vista al corte nula JOIN existencia de alguna fila con valor de la misma (serie, fecha_referencia)")
    v("N05", "CONFIRMADO", "6 filas nulas BoC el 2006-09-04; DGS20 1987-01-01 es marca de hueco",
      f"{g('N05')['boc_nulas_2006_09_04']} filas; 0 filas BoC en el Labour Day de otros años; DGS20 1987-01-01 nula con nota de hueco >31 días",
      "", "consulta por fecha y día de la semana (primer lunes de septiembre)")
    v("N06", "CONFIRMADO", "0 nulos perdidos; 513 periodos en 127 series (502 final, 11 principio, 0 medio)",
      f"nulos trabajo {f(N06['nulos_base_trabajo'])}; nulos de series curadas ausentes de la curada {N06['nulos_base_de_curadas_no_en_curada']}; "
      f"{N06['periodos_perdidos']} periodos en {N06['series_afectadas']} series {N06['por_posicion']}; ust:PAR.30Y 994, deriv:PIB_REAL_USA_VINTAGES 287",
      "", "ANTI JOIN DuckDB base_series (valor, fecha_publicacion ≤ corte) vs base_curada por (serie, fecha_referencia)")
    v("N07", "CONFIRMADO", "430.050 aperturas nulas (3,97 %), 0 cierres, 0 en crudo, 135.969 con volumen, 1.182 tickers, 88 > 20 %",
      f"{f(N07['aperturas_nulas'])} ({N07['pct']} %), cierres {N07['cierres_nulos']}, crudo {N07['aperturas_nulas_crudo']}, "
      f"con volumen {f(N07['aperturas_nulas_con_volumen'])}, {f(N07['tickers_con_apertura_nula'])} tickers; <2000 {f(N07['antes_2000'])}, "
      f"≥2007 {f(N07['desde_2007'])}, ≥2016 {f(N07['desde_2016'])}; XLON {N07['pct_xlon']} %; >20 %: {N07['tickers_mas_20pct']} "
      f"(88 sin VBMFX ni ^SKEW, que pasan del 99 %); anuladas que no eran planas en el crudo: {N07['anuladas_no_planas_en_crudo']}",
      "Matiz: 88 excluye los dos tickers sin apertura (>99 %); con ellos son 90.",
      "DuckDB read_parquet(precios_curados/*/*) y precios/*/* con JOIN por (ticker, sesion)")
    v("N08", "CONFIRMADO", "VBMFX 10.057/10.057; ^SKEW 9.203/9.212", f"{g('N08')}", "", "conteo por ticker")
    v("N09", "CONFIRMADO", "29.611 velas quitadas; 0 sesiones post-corte",
      f"ANTI JOIN crudo (fecha_publicacion ≤ corte) − curada = {f(N09['hasta_corte_no_en_curada'])}; tabla {f(N09['tabla_velas_quitadas'])}; "
      f"aviso relleno {f(N09['aviso_relleno_n'])}; curadas publicadas tras el corte {N09['curada_publicada_post_corte']}; curada fuera del crudo {N09['curada_no_en_crudo']}",
      "", "ANTI JOIN por (ticker, sesion)")
    v("N10", "CONFIRMADO", "653 tickers / 9.126 sesiones faltantes; 17 con racha > 5; 7 > 20; KVUE 13 (2026-10-13..10-29)",
      f"con exchange_calendars desde 1962 y el mapa eda.CALENDARIO_MERCADO: {N10['tickers_con_faltantes']} tickers / "
      f"{f(N10['sesiones_faltantes'])} sesiones ({f(N10['faltantes_desde_2000'])} desde 2000); racha > 5: {N10['racha_mas_5']}; > 20: "
      f"{N10['racha_mas_20']}; top idéntico (BGEO.L 262, CNY 153, DWD 142, 0300.HK 59, ABTC.SW 52, AETH.SW 47, GR 15, KVUE 13); ^W5000 mercado {N10['W5000_mercado']}",
      "Las cifras del auditor son las de la tabla de avisos (sesion_faltante: 653 / 9.126), con el calendario del EDA desde "
      "1990. Con calendario desde 1962 salen 683 / 11.338 y 18 rachas > 5 (se suma HUBB, 6 sesiones en 1972). Desde 2000 "
      "me salen 8.258 frente a 8.524 (diferencia no explicada, 3 %; no cambia ninguna conclusión).",
      "recorrido propio: sesiones de calendario sin vela por ticker y racha máxima de faltantes consecutivos")
    v("N11", "CONFIRMADO", "21 tickers no llegan al corte; 14 bloqueados por revisión de Yahoo; 38 acaban el 12 bien; aviso en 20",
      f"heurística propia (última sesión < moda de su mercado): {N11['tickers_por_detras_de_su_mercado']} + 000001.SS (todo XSHG acaba el "
      f"2026-10-13, así que la moda no lo detecta) = 21; avisos no_llega_corte {N11['avisos_no_llega']}; faltan 23–25 sesiones a los 14 + SNDK; "
      f"KVUE 10 días hábiles (≤ umbral 10 → sin aviso: 20 avisos); acaban el 2026-11-12: {N11['acaban_2026_11_12']}",
      "Matiz: los que acaban el 2026-11-12 son 40 (38 de Yahoo + 2 de Coinbase, que también publica al día siguiente). "
      "Clasificación correcta según las notas de los avisos: GP y LU reutilizados, DWD y GR reutilizados sin nada que refrescar, PARA fusión.",
      "última sesión curada por ticker frente a la moda de su mercado + sesiones de exchange_calendars; notas de precios_curados_avisos.csv")
    v("N12", "CONFIRMADO", "1.624 ficheros crudos, 1.616 curados, 8 truncados", f"{g('N12')['crudo']} / {g('N12')['curados']}; {g('N12')['solo_crudo']}",
      "Los 8 figuran como limitacion_declarada en descargas_3b_estado.csv.", "diferencia de nombres de fichero + recuento de sesiones")
    v("N13", "CONFIRMADO", "aviso de tools: 28 series (24 retiradas + 4 activas); 4 de Eurostat paradas como «activa»",
      f"regla propia (diarias/semanales sin publicar en > 10 días hábiles): {g('N13')['diarias_semanales_mas_10_dh']} = "
      f"{g('N13')['diarias_semanales_mas_10_dh_por_estado']} (las 4 del auditor + ecb:MRO y ecb:DFR, series de eventos que la tool excluye por paso); "
      f"Eurostat UK/US activas paradas: 4 (UK 2020-07/09/11, US 2024-12); tools.py:447 dice «hasta el 3b-2»",
      "Solapa con F05 (mismo defecto del aviso; F05 suma el ESI EA20 como quinta de Eurostat).",
      "max(fecha_publicacion) por serie vs corte, np.busday_count; catálogo de cobertura_series.csv")
    v("N14", "CONFIRMADO", "660 incidencias de hueco en 81 series curadas; 414 con fin ≥2000",
      f"{g('N14')['incidencias_hueco_curadas']} / {g('N14')['series']} / {g('N14')['con_fin_desde_2000']}; ISK {g('N14')['isk']}", "",
      "eda_series_incidencias.csv (tipo hueco_largo) filtrado a curada_resumen.csv")

    # ------------------------------------------------------------------ ángulo 2
    v("F01", "CONFIRMADO", "487 al día, 2 retraso normal, 8 desfasadas, 36 paradas (27 retiradas)",
      f"retiradas en el catálogo {g('F01')['retiradas_en_curada']}; regla propia (sin periodo nuevo en > 365 días o retirada): "
      f"{g('F01')['parado_mas_365_dias_o_retirada']}", "487/2/8 no recalculados (dependen de su umbral de cadencia); 36 y 27 cuadran.",
      "primera publicación de cada fecha_referencia; última de ellas frente al corte")
    F2 = g("F02")
    v("F02", "CONFIRMADO", "14.849 filas post-corte (0,14 %), 828 series; 10.051 ya publicadas; 4.798 futuras; curadas 9.980/214; precios 5.748/1.596",
      f"{f(F2['filas_post_corte'])} ({F2['pct']} %), {F2['series_post_corte']} series; ≤ hoy {f(F2['post_corte_hasta_hoy'])} en {F2['post_corte_hasta_hoy_series']}; "
      f"futuras {f(F2['futuras'])} (máx {F2['max_fp'][:10]}); curadas {F2['curadas_hasta_hoy']}; precios {g('F02_precios')}; "
      "4 constantes de corte en las líneas citadas y ninguna opción --corte", "", "filtros de fecha_publicacion en DuckDB; comprobación de líneas con re")
    v("F03", "DUPLICADO_DE:N11", "21 no llegan; 14 por una vela; 3 historia cambiada; 1.361 revisiones toleradas en 476 tickers",
      "mismos 21 y 14 que N11; logs/revisiones_precios_yahoo.csv 1.361 filas, 476 tickers; yahoo.py:341 y almacen.py:319 correctos",
      "Mismo hallazgo que N11 con otra clasificación. DWD y GR no son «tickers muertos»: según la nota de su aviso son tickers "
      "reutilizados (el fichero es de otra empresa, nada que refrescar); GP y LU también son reutilizados. La de N11 es la buena. "
      "Lo nuevo de F03 (tolerar revisiones OHLC) es una idea de arreglo, no otra cifra.", "notas no_llega_corte de precios_curados_avisos.csv; logs")
    v("F04", "CONFIRMADO", "8 desfasadas: Bundesbank 2026-10-13, GC=F/^BCOM/^W5000 2026-07-17, ESI EA20 y OCDE CP EA20/FRA/ITA 2025-12",
      f"{g('F04')['ultimas']}", "Los días (29, 118, 257, 309) se cuentan desde la última fecha_publicacion; desde la fecha de referencia serían 31 y 119 para Bundesbank y Yahoo.",
      "max(fecha_referencia/fecha_publicacion) con valor por serie")
    v("F05", "CONFIRMADO", "13 «activa» paradas (BIS 3, Eurostat 5, OCDE 4, Philly 1); el aviso de tools solo mira diarias/semanales",
      "BIS DE/FR/IT acaban en 1998-12; Eurostat UK 2020, US 2024-12 y ESI EA20 2025-12; OCDE JPN 2022-04 y EA20/FRA/ITA 2025-12; "
      "philly:ROUTPUT; tools.py:448/454/455 correctos", "Solapa con N13.", "última referencia con valor + estado de cobertura_series.csv")
    v("F06", "CONFIRMADO", "4 constantes de corte, 10 órdenes descargar-<fuente>, sin orden única de refresco",
      f"todas las referencias fichero:línea casan ({sum(ok for _, ok in R['_codigo']['F06'])}/{len(R['_codigo']['F06'])}); FUENTES_CLI = {R['_codigo']['n_FUENTES_CLI']}; sin --corte en ningún CLI",
      "Tiempos de ALFRED (1.052 s, 216 peticiones) no verificados.", "lectura de las líneas citadas + ast de __main__.py")
    v("F07", "CONFIRMADO", "65 pares con correlación 0,94–0,96 y ≥ 5 años",
      f"{g('F07')['pares_094_096_5anios_pearson_firmado']} con Pearson firmado ({g('F07')['pares_094_096_5anios']} con |r|); seleccion.py:166/200/202/1351 correctos",
      "", "redundancia_pares.csv")
    v("V01", "CORREGIDO", "430.665 filas con fuga (4,23 %); 73.559 anteriores a ALFRED sin etiqueta (0,72 %); total 4,95 %",
      f"fuga {f(V01['fuga'])} ({V01['pct_fuga']} %) en {V01['fuga_series']} series, desglose idéntico; «anterior a ALFRED» sin "
      f"etiqueta: {f(V01['anterior_alfred_sin_fuga'])} ({V01['pct_alfred']} %); desde 2000 {V01['anterior_alfred_sin_fuga_2000']}",
      "El auditor filtró fuente = fred_alfred y se dejó 971 filas de philly_rtdsm (philly:ROUTPUT) con la misma nota: son "
      "74.530 (0,73 %) y el total con ellas sube a 4,96 %. Lo de desde 2000 (21.462 en 92 series) y la base de trabajo (5,08 %) cuadran.",
      "ILIKE sobre la nota en toda la curada, sin filtrar por fuente")
    v("V02", "CONFIRMADO", "355.151 filas recuperables vía Wayback; 639 BM; 7.041 BCE/Eurostat; 5.772 BIS; 62.062 USRECD",
      "sumas cuadran con el desglose de V01 (295.998+33.985+15.952+9.216 = 355.151; 6.669+372 = 7.041)",
      "Cifras confirmadas; la existencia de las fuentes (Wayback, archivos WDI, base en tiempo real del BCE) NO es verificable "
      "sin red. Contradice a L10, que da esas vintages por imposibles.", "aritmética sobre los recuentos de V01")
    v("V03", "CONFIRMADO", "1.739.542 filas «unico» (17,07 %); 109.127 revisables (1,07 %)",
      f"{f(V03['unico'])} ({V03['pct']} %); revisables {f(V03['unico_revisable'])} {V03['unico_revisable_por_fuente']}", "",
      "vintage = 'unico' JOIN revisable de cobertura_series.csv")
    v("V04", "CONFIRMADO", "463 correcciones descartadas (Eurostat 372, BIS 86, RBA 5); BCE 132 conservadas; 42 series",
      f"{g('V04')['guardada_gana_valor_por_prefijo']} = {g('V04')['guardada_gana_valor_total']}; conservadas {g('V04')['conservadas_mas_ya']} en "
      f"{g('V04')['series_bce_con_conservadas']} series del BCE; {g('V04')['series']} series; base.py:100 y :613 correctos", "",
      "solo_anadir_ultima.csv agregado por prefijo")
    v("V05", "CONFIRMADO", "3 capturas, 822 fechas por serie (2023-10-10..2026-11-17); base 813–814; curada 808–809",
      f"{g('V05')}", "Los 2 vintages por serie son los del archivo; en la base cada serie OAS tiene 1.", "acumulado.parquet (sin valores) y base/curada filtradas")
    v("V06", "CONFIRMADO", "4 ediciones WEO (2025-04..2026-10), 357 series, 28 en la curada (4.296 filas), primera publicación 2025-04-22",
      f"{g('V06')['vintages_bloque4']}; curada {g('V06')['curada_series_imf']} series / {f(g('V06')['curada_filas_imf'])} filas; primera "
      f"{g('V06')['curada_primera_pub_imf']}; 2025-10 fechada {g('V06')['pub_por_vintage']['2025-10']}; dbnomics {g('V06')['dbnomics_meta']} meta y {g('V06')['dbnomics_datos']} datos",
      "registro_descarga.md:262 omite la 2026-10, como dice el auditor.", "bloque4/imf_weo.parquet y base_curada por fuente imf_weo")
    v("V07", "CONFIRMADO", "Ken French 3 ediciones, Shiller 1, Goyal-Welch 2, OFR 0; 2 días de descarga; 49 filas KF 2026-10",
      f"{g('V07')['ediciones']}; días {g('V07')['dias_descarga']}; curada KF {g('V07')['curada_kf_vintages']}; GW {g('V07')['curada_gw_vintages']}", "",
      "listado de crudo/<fuente>/ediciones y vintages de la curada")
    v("V08", "CONFIRMADO", "USRECD 62.062 filas, lag_fijo 24M, vintage unico; preprocesado.yaml dice vintage_exacto; 153 excepciones",
      f"{f(g('V08')['filas'])} filas, método {g('V08')['metodo']}, vintage {g('V08')['vintage']}, retraso mín/mediano {g('V08')['lag_min']}/{g('V08')['lag_mediano']} días; "
      f"0 filas en registro_cambios; {g('V08')['excepciones_csv']} excepciones; la afirmación está en preprocesado.yaml:345–346",
      "", "base_curada + registro_cambios + excepciones_publicacion.csv")

    # ------------------------------------------------------------------ ángulo 3
    v("C01", "CONFIRMADO", "0 series con > 1 unidad/divisa; 6 escaladas; 27 homogeneizadas; ×100: 34.116 registro / 34.029 curada",
      f"{g('C01')['series_mas_1_unidad']}/{g('C01')['series_mas_1_divisa']}; {g('C01')['series_escaladas']} / {g('C01')['series_homogeneizadas']}; "
      f"×100 {f(g('C01')['registro_homog_x100'])} / {f(g('C01')['registro_homog_x100_en_curada'])}; saltos ×80–×1250 con |v| > 1 entre referencias "
      f"consecutivas: 1 ({g('C01')['salto_x100_donde']}, saldo presupuestario mensual: movimiento real)", "", "DuckDB sobre curada y registro_cambios")
    v("C02", "CORREGIDO", "1.651 saltos > 50 % en 203 tickers; 311 saltos en 163 tickers «sin ningún aviso»; 30 ×10 en 17",
      f"{f(C02['saltos'])} / {C02['tickers']} / ×10 {C02['x10']} / ≥2007 {f(C02['desde_2007'])}; en sospechosos {f(C02['marca_sospechosa'])}, "
      f"reutilizados {C02['marca_reutilizado']}; sin ningún aviso en la lista: {C02['saltos_sin_marca']} saltos en {C02['tickers_sin_marca']} tickers "
      f"(×10: {C02['x10_sin_marca']} en {C02['tickers_x10_sin_marca']}); de esos, con aviso salto_sin_split en precios_curados_avisos.csv: "
      f"{C02['tickers_sin_marca_con_aviso_salto_csv']} de {C02['tickers_sin_marca']}",
      "«Sin ningún aviso» es falso. Los 311/163 solo carecen de la marca sospechoso/reutilizado; contando cualquier aviso de la lista "
      "quedan 298 saltos en 157 tickers (×10: 27 en 14), y los 157 tienen aviso salto_sin_split en precios_curados_avisos.csv. "
      "Lo que sí es cierto es que get_precios no lo avisa (tools.py no lee esa tabla). Totales, contrasplits (277/182) y casos "
      "de la sonda cuadran; los splits fraccionarios dependen de la definición (con split y 1/split no enteros me salen 1.058 en 412).",
      "ventana lag/lead en DuckDB sobre precios_curados; cruce con lista_curada.yaml (campo aviso) y con precios_curados_avisos.csv")
    v("C03", "CONFIRMADO", "112 reutilizados en la lista; 0 con hueco > 1 año; get_precios no lo avisa",
      f"lista {g('C03')['reutilizados_lista']} (todos «queda»), avisos {g('C03')['reutilizados_avisos_csv']}, hueco > 365 días "
      f"{g('C03')['reutilizados_con_hueco_mas_365']}; tools.py no lee la lista ni la tabla de avisos; get_precios('LU'/'GR', base='curada') "
      "solo da «datos atrasados» (y aperturas nulas en GR)", "Los 110/113 recalculados no se han rehecho.",
      "lista_curada.yaml, lag de sesiones en DuckDB, tools.get_precios en solo lectura")
    v("C04", "CONFIRMADO", "37 en la lista (36 quedan); 36 EDA; 35 tipo serie_sospechosa", f"{g('C04')}", "", "lista_curada.yaml, eda_precios.csv, avisos, estado 3b")
    v("C05", "CONFIRMADO", "27 alias empiezan antes; 26 antes de 2000; 2 con canónico desde 2000; 17 con canónico OCDE desde 1999-03",
      f"definición del 04 (primera publicación en la base de trabajo): {C05['base_vs_base_antes']} / {C05['base_vs_base_antes_pre2000']} / "
      f"{C05['base_vs_base_canonico_desde_2000']} {C05['base_vs_base_lista_canonico_2000']}; por referencia {C05['por_referencia_antes']}; "
      f"canónico OCDE que empieza en 1999-03: {C05['base_vs_base_canonico_oecd_1999_03']}",
      "Matiz: de los 26, 17 tienen canónico OCDE, pero solo 16 empiezan en 1999-03 (oecd:CP.CHN empieza en 2000-02). Y la cifra "
      "depende de la definición: frente al canónico ya curado (con fechas prudentes) son 44 / 40 / 6, sumando los 4 factores "
      "diarios F5D→F3D de Ken French.", "min(fecha_publicacion) en base_series para alias y canónico")
    v("C06", "CONFIRMADO", "get_serie y get_precios con base='trabajo' por defecto", "tools.py:501 y :650", "", "lectura de la firma")
    v("C07", "CONFIRMADO", "3 futuros USX sin FX (19.768 sesiones; ZC 6.588); TWD con fixing de 2020-10-30 en 1.465 sesiones por ticker; CNY 618",
      f"USX {g('C07')['usx_sesiones_por_ticker']}; divisas.py sin USX, universo.py:{g('C07')['usx_en_universo_py']}; último fixing TWD "
      f"{g('C07')['ultima_fecha_ecb_TWD'][:10]}; posteriores {g('C07')['twd_post_2020_10_30_por_ticker']}; CNY antes del primer fixing {g('C07')['cny_sesiones_antes_fx']}",
      "", "divisa de los precios curados y rango de ecb:EXR.D.*.EUR en la curada")
    v("C08", "CONFIRMADO", "1.426.536 retrasadas, 0 adelantadas; 314.544 > 30 días (81 % antes de 2000); 18.596 > 365 desde 2007; 108 con tope",
      f"{g('C08')}", "", "registro_cambios: fecha_publicacion_despues frente a _antes, en_base_curada")
    v("C09", "CONFIRMADO", "ICSA 5 → 61 días (2007-01..2009-05); continuadas 13 → 68 hasta 2009-08",
      f"ICSA {g('C09')['fred:ICSA']} (n, mediana antes, después; tramo hasta {g('C09')['fred:ICSA_fin_tramo'][:10]}); CCSA {g('C09')['fred:CCSA']} (hasta {g('C09')['fred:CCSA_fin_tramo'][:10]})",
      "Solo verificadas ICSA y CCSA; el resto de reglas del desglose no se ha recalculado.", "registro_cambios por serie y ventana")
    v("C10", "CONFIRMADO", "verificaciones 13 + 12 (+1 no aplica) en 0; tests 1.217/70 y 1.257/30; ningún test escribió en D:",
      "logs: 1217 passed, 70 skipped / 1257 passed, 30 skipped / 10 passed; snapshots antes y después iguales; además, los 5.560 "
      "ficheros de mercados_series del snapshot siguen con el mismo tamaño hoy", "", "lectura de logs y verificaciones; os.stat frente al snapshot")
    v("C11", "CONFIRMADO", "plan: 243 proyecciones (hoy 309), 25 alias (26), 26 sospechosos (37); filas_base 10.232.074 vs 10.620.113",
      f"proyecciones {g('C11')['proyecciones_series']} series ({g('C11')['proyecciones_filas']} filas); manifiesto resumen.filas_base 10.232.074; parquet "
      f"{f(g('C11')['filas_base_parquet'])}; plan líneas 309, 350, 352 y 276 (1.270 tests)", "", "proyecciones.parquet, curada_manifiesto.json, grep del plan")
    v("L01", "CONFIRMADO", "177 filas: 48 hechos, 1 parcial, 3 resueltos, 124 limitaciones, 1 aplazado; 119 ids distintos",
      f"{g('L01')['estado_3b']}; {g('L01')['ids_unicos_limitacion']} ids únicos", "El agrupado en 13 causas es del auditor (no recalculado).", "descargas_3b_estado.csv")
    v("L02", "CONFIRMADO", "67,78 % días-tramo con precio (67,88 recalculado); 78,68 % desde 2007; Lehman 305 de 498",
      f"cálculo propio con sesiones XNYS: {L02['pct']} %; desde 2007 {L02['pct_desde_2007']} %; Lehman {L02['lehman_con_precio']} de {L02['lehman_miembros']}",
      "Diferencia < 0,5 puntos por definición (excluyo los 112 reutilizados enteros, no por tramo).",
      "constituyentes/sp500.parquet × sesiones XNYS × sesiones de precios_curados/yahoo")
    v("L03", "CORREGIDO", "WEO: 3 ediciones disponibles (2025-04, 2025-10, 2026-04; la 2026-10 «en la API»); faltan 34",
      f"{len(g('V06')['vintages_bloque4'])} ediciones en bloque4/imf_weo.parquet y en la base ({g('V06')['base_vintages_imf']}); 34 limitaciones en el estado 3b",
      "Hay 4 ediciones, no 3: la 2026-10 está en la base y en la curada, no solo en la API (el propio motivo del estado 3b lo dice). "
      "Además duplica V06, que da la cifra buena.", "vintages distintos de imf_weo en bloque4 y en base_series")
    v("L04", "DUPLICADO_DE:C03", "37 sospechosos y 112 reutilizados sin identificador permanente",
      "37 = C04; 112 = C03; 19 filas sp500_supervivencia (estado 3b)", "Mismas cifras que C03/C04.", "lista_curada.yaml")
    v("L05", "DUPLICADO_DE:F04", "Bundesbank parado en 2026-10-13; 7.408 filas", "2026-10-13; 7.408 filas en la curada", "Mismo hecho que F04 (y N13).", "curada_resumen.csv")
    v("L06", "CONFIRMADO", "18 UCITS con historia recortada (16 en estado 3b); 23 con correlación < 0,90; 21 no llegan",
      f"historia recortada {g('L06')['historia_recortada_avisos']}; correlación baja {g('L06')['correlacion_baja_avisos']}; no llegan 21 (= N11)",
      "Lo de 21 no llegan duplica N11; 18/16 duplica C11.", "precios_curados_avisos.csv tipo aviso_lista")
    v("L07", "CORREGIDO", "18 series de zona euro/UE en la curada: 5 cambiante, 6 fija donde importa",
      f"21 = las 18 del auditor + 3 que no tiene. Mi regex sobre los ids da {g('L07')['series_zona_euro_regex']}: no captura bis:WS_CBPOL.M.XM, "
      "bis:WS_EER.M.R.B.XM ni oecd:LI_AA.G4E, y sí ecb:MNA...I10, que el auditor no tiene",
      "Faltan 3 series curadas: ecb:MNA.Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY (PIB real de la zona euro 21 con "
      "composición fija desde 2026: la composición sí importa) e imf:WEO.163.GGXCNL_NGDP y imf:WEO.163.GGXWDG_NGDP (agregado "
      "163 = zona euro del WEO). Son 21 series y al menos 7 «fija donde importa».", "regex sobre ids + catalogo_series.yaml (nombre de I10) + fuentes/imf.py:71")
    v("L08", "CONFIRMADO", "6 estrategias hasta 2026-10-12; 60/40 UCITS desde 2017-11-30 sin versión con costes; 60/40 europea aplazada",
      f"{g('L08')['brutos']}; con costes solo {[b[0] for b in g('L08')['costes']]}; ficheros de 2026-10-13; {g('L08')['estado_6040']}", "",
      "estrategia y fechas de cartera/*.parquet (sin valores)")
    v("L09", "CORREGIDO", "347 de 533 series (65,1 %) visibles desde 2000; 83,5 % por referencia",
      f"con valor publicado ≤ 2001-01-02: {L09['pub_le_2001_01_02_con_valor']} ({L09['pct']} %); contando filas nulas {L09['pub_le_2001_01_02_cualquier_fila']}; "
      "por referencia ≤ 2000-12-31: 445 (83,5 %)",
      "Son 346 (64,9 %): fred:TWEXAFEGSMTH tiene filas nulas desde 1973, pero no publica su primer valor hasta 2006. Con "
      "solo filas nulas no hay nada que ver desde 2000.", "min(fecha_publicacion) con valor no nulo por serie")
    v("L10", "CONFIRMADO", "4 series no publicadas, 3 Philly por diseño, 1 vintages sin fuente, 1 calendarios",
      "recuentos del estado 3b cuadran con L01", "Contradice a V02 (posibles fuentes gratuitas de vintages, sin verificar) y a V04 (el BCE "
      "sí conserva versiones por solo-añadir: 132). «No hay historia de revisiones gratis» debería decir «no encontrada».",
      "descargas_3b_estado.csv")

    assert len(V) == 50 and len({x["id"] for x in V}) == 50
    (AQUI / "verificacion.json").write_text(json.dumps(V, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(Counter(x["veredicto"].split(":")[0] for x in V))


if __name__ == "__main__":
    secs = [a for a in sys.argv[1:] if a in globals()] or ["series", "precios", "tablas", "codigo", "informe"]
    for s in secs:
        globals()[s]()
        print("hecho", s)
