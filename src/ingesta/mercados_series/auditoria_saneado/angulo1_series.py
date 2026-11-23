"""Auditoría · ángulo 1 (huecos y nulos) · SERIES. SOLO LECTURA.

Lee base_curada.parquet y base_series.parquet con DuckDB (solo columnas de metadatos/fechas y `valor IS NULL`).
Nunca imprime un valor de serie: solo recuentos, fechas e ids. Escribe los resultados en angulo1_series.json.

Uso: PYTHONPATH=<worktree>/src python angulo1_series.py
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

WT = _REPO
sys.path.insert(0, str(WT / "src"))
from ingesta.mercados_series import tools  # noqa: E402  (solo para reutilizar la regla de atraso, lectura)

TAB = WT / "results/ingesta/mercados_series/tablas"
C = "'D:/tfm_corpus/mercados_series/series/base_curada.parquet'"
B = "'D:/tfm_corpus/mercados_series/series/base_series.parquet'"
CORTE = pd.Timestamp("2026-11-13")
OUT = Path(__file__).with_name("angulo1_series.json")

con = duckdb.connect()
con.execute("SET memory_limit='3GB'; SET threads=2")
cob = pd.read_csv(TAB / "cobertura_series.csv", usecols=["id", "frecuencia", "metodo", "estado", "fin", "lag_mediano_dias"])
con.register("cob", cob)
R: dict = {}


def df(q: str) -> pd.DataFrame:
    return con.sql(q).df()


# ---------------------------------------------------------------- 1. nulos en la curada
def nulos_curada():
    tot = df(f"""select count(*) filas, count(distinct serie) series, sum((valor is null)::int) nulos,
                 count(distinct case when valor is null then serie end) series_con_nulo from read_parquet({C})""")
    por_fuente = df(f"""select fuente, sum((valor is null)::int)::int nulos, count(distinct serie) series,
                     count(distinct case when valor is null then serie end) series_con_nulo
                     from read_parquet({C}) group by 1 having nulos>0 order by 2 desc""")
    R["curada_total"] = tot.iloc[0].to_dict()
    R["curada_nulos_por_fuente"] = por_fuente.to_dict("records")
    print("== 1. Nulos en la curada"); print(tot.to_string()); print(por_fuente.to_string())

    # Fila a fila: ¿la misma (serie, ref) tiene valor en un vintage posterior / anterior / nunca?
    q = f"""
    with t as (select serie, fuente, fecha_referencia r, fecha_publicacion p, vintage v, valor is null nul, nota
               from read_parquet({C}) where serie in (select distinct serie from read_parquet({C}) where valor is null)),
    nn as (select serie, r, max(case when not nul then p end) pmax_val, min(case when not nul then p end) pmin_val
           from t group by 1,2),
    ult as (select serie, r, arg_max(nul, (p, v)) ultimo_nulo from t group by 1,2)
    select t.serie, t.fuente, t.r, t.p, t.nota, nn.pmax_val, nn.pmin_val, u.ultimo_nulo, cob.frecuencia
    from t join nn using(serie, r) join ult u using(serie, r) left join cob on cob.id=t.serie where t.nul"""
    n = df(q)
    n["r"] = pd.to_datetime(n["r"])
    diaria = n["frecuencia"].eq("diaria")
    # --- diarias: calendario del publicador
    import exchange_calendars as xc
    from pandas.tseries.holiday import USFederalHolidayCalendar
    cal_fuente = {"boe_curvas": "XLON", "mof_jgb": "XTKS", "boc_curva": "XTSE", "fred_alfred": "XNYS"}
    fest = {}
    inicio_cal = {}
    for fu, nombre in cal_fuente.items():
        from exchange_calendars.calendar_utils import _default_calendar_factories as fab
        b0 = fab[nombre].bound_min()
        ini = max(pd.Timestamp("1975-01-01"), pd.Timestamp(b0).tz_localize(None) if b0 is not None else pd.Timestamp("1975-01-01"))
        c = xc.get_calendar(nombre, start=ini.strftime("%Y-%m-%d"), end="2026-12-31")
        ses = pd.DatetimeIndex(c.sessions.tz_localize(None) if c.sessions.tz else c.sessions)
        bdays = pd.bdate_range(ini, "2026-12-31")
        cerrados = set(bdays.difference(ses))
        inicio_cal[fu] = ini
        if fu == "fred_alfred":
            cerrados |= set(USFederalHolidayCalendar().holidays("1975-01-01", "2026-12-31"))
        fest[fu] = cerrados
    d = n[diaria].copy()
    d["festivo"] = [r in fest.get(f, set()) for r, f in zip(d["r"], d["fuente"])]
    d["finde"] = d["r"].dt.weekday >= 5
    # rachas: días hábiles consecutivos (L-V) nulos dentro de la serie
    d = d.sort_values(["serie", "r"])
    d["bd"] = np.busday_count(np.datetime64("1970-01-01"), d["r"].values.astype("datetime64[D]"))
    d["grupo"] = (d.groupby("serie")["bd"].diff() != 1).cumsum()
    d["racha"] = d.groupby("grupo")["bd"].transform("size")
    d["sin_calendario"] = [r < inicio_cal.get(f, pd.Timestamp("1975-01-01")) for r, f in zip(d["r"], d["fuente"])]
    d["causa"] = np.select([d["festivo"], d["finde"], d["racha"] >= 5], ["festivo", "fin_de_semana", "tramo_plazo_no_publicado(>=5 hábiles)"], "dia_suelto_sin_dato")
    # ¿los otros plazos de la misma curva tienen dato ese día? (indica plazo no publicado, no festivo)
    otros = df(f"""select fuente, fecha_referencia r, count(distinct serie) series_con_valor from read_parquet({C})
                   where valor is not null and fuente in ('boe_curvas','mof_jgb','boc_curva') group by 1,2""")
    otros["r"] = pd.to_datetime(otros["r"])
    d = d.merge(otros, on=["fuente", "r"], how="left")
    d["otros_plazos_con_dato"] = d["series_con_valor"].fillna(0) > 0
    clas_d = d.groupby(["fuente", "serie", "causa"]).agg(filas=("r", "size"), desde=("r", "min"), hasta=("r", "max"),
                                                          con_otros_plazos=("otros_plazos_con_dato", "sum"),
                                                          antes_del_calendario=("sin_calendario", "sum")).reset_index()
    clas_d["desde"] = clas_d["desde"].dt.date.astype(str); clas_d["hasta"] = clas_d["hasta"].dt.date.astype(str)
    print("\n-- diarias: causa de cada nulo"); print(clas_d.to_string())
    R["diarias_causa"] = clas_d.to_dict("records")
    R["diarias_por_causa"] = d.groupby("causa").size().astype(int).to_dict()
    R["diarias_festivo_detalle"] = d.loc[d["causa"] == "festivo", ["serie", "r"]].assign(r=lambda x: x.r.dt.date.astype(str)).to_dict("records")
    # boe/mof por década y nulos desde 2000
    d["decada"] = (d["r"].dt.year // 10) * 10
    R["diarias_por_decada"] = d.groupby(["fuente", "decada"]).size().astype(int).reset_index(name="n").to_dict("records")
    R["diarias_desde_2000"] = d[d["r"] >= "2000-01-01"].groupby(["serie"]).agg(n=("r", "size"), desde=("r", "min"), hasta=("r", "max")).reset_index().astype(str).to_dict("records")
    print("\n-- diarias desde 2000:", R["diarias_desde_2000"])
    # años de boe:NOM.6M
    nom6 = d[d["serie"] == "boe:NOM.6M"].groupby(d["r"].dt.year).size()
    R["boe_NOM6M_por_anio"] = {int(k): int(v) for k, v in nom6.items()}
    print("boe:NOM.6M por año:", R["boe_NOM6M_por_anio"])

    # --- no diarias (ALFRED con vintages)
    m = n[~diaria].copy()
    shutdown = m["r"].eq(pd.Timestamp("2025-10-01"))
    m["causa"] = np.select(
        [shutdown & m["pmax_val"].isna(),
         m["pmax_val"].notna() & (m["pmax_val"] > m["p"]),
         m["pmax_val"].notna() & (m["pmax_val"] < m["p"]),
         m["pmax_val"].isna()],
        ["2025-10_cierre_gobierno_EEUU_nunca_publicado",
         "vintage_antiguo_sin_dato_luego_publicado",
         "dato_retirado_en_vintages_posteriores",
         "nunca_publicado_otro"], "otro")
    clas_m = m.groupby("causa").agg(filas=("r", "size"), series=("serie", "nunique"), ref_min=("r", "min"), ref_max=("r", "max")).reset_index()
    clas_m[["ref_min", "ref_max"]] = clas_m[["ref_min", "ref_max"]].astype(str)
    print("\n-- no diarias: causa"); print(clas_m.to_string())
    R["no_diarias_por_causa"] = clas_m.to_dict("records")
    R["no_diarias_ref_desde_2000"] = int((m["r"] >= "2000-01-01").sum())
    R["no_diarias_ref_desde_2000_por_causa"] = m[m["r"] >= "2000-01-01"].groupby("causa").size().astype(int).to_dict()
    sh = m[m["causa"].str.startswith("2025-10")]
    R["shutdown_series"] = sorted(sh["serie"].unique().tolist())
    otro = m[m["causa"] == "nunca_publicado_otro"]
    R["nunca_publicado_otro"] = otro.groupby("serie").agg(n=("r", "size"), desde=("r", "min"), hasta=("r", "max")).reset_index().astype(str).to_dict("records")
    print("shutdown 2025-10:", len(R["shutdown_series"]), R["shutdown_series"])
    print("nunca publicado (otro):", R["nunca_publicado_otro"])
    # refs ≥ 2000 no superados
    m2 = m[(m["r"] >= "2000-01-01") & (m["causa"] != "vintage_antiguo_sin_dato_luego_publicado")]
    R["no_diarias_desde_2000_permanentes"] = m2.groupby(["serie", "causa"]).agg(n=("r", "size"), desde=("r", "min"), hasta=("r", "max")).reset_index().astype(str).to_dict("records")
    print("no diarias ≥2000 no superadas:", R["no_diarias_desde_2000_permanentes"])
    # nulos por década de fecha_referencia (todas)
    n["decada"] = (n["r"].dt.year // 10) * 10
    R["nulos_por_decada_ref"] = n.groupby("decada").size().astype(int).to_dict()
    print("nulos por década de ref:", R["nulos_por_decada_ref"])
    # notas de los nulos (agrupadas por el primer trozo)
    n["nota_tipo"] = n["nota"].fillna("<sin nota>").str.split(";").str[0]
    R["nulos_por_nota"] = n.groupby(["fuente", "nota_tipo"]).size().astype(int).reset_index(name="n").to_dict("records")
    R["nulos_sin_nota"] = int(n["nota"].isna().sum())
    print("nulos sin nota:", R["nulos_sin_nota"])
    # vista a la fecha de corte: nulos en la última versión
    vu = df(f"""with t as (select serie, fecha_referencia r, valor is null nul, fecha_publicacion p, vintage v from read_parquet({C}))
               select serie, count(*) n, min(r) desde, max(r) hasta, sum((r>=DATE '2000-01-01')::int) desde2000
               from (select serie, r, arg_max(nul,(p,v)) un from t group by 1,2) where un group by 1 order by 2 desc""")
    R["vista_corte_nulos"] = int(vu["n"].sum()); R["vista_corte_series"] = int(len(vu))
    R["vista_corte_nulos_desde2000"] = int(vu["desde2000"].sum())
    R["vista_corte_series_desde2000"] = int((vu["desde2000"] > 0).sum())
    R["vista_corte_desde2000_por_serie"] = {r.serie: int(r.desde2000) for r in vu[vu["desde2000"] > 0].itertuples()}
    print("vista al corte, nulos desde 2000 por serie:", R["vista_corte_desde2000_por_serie"])
    # nulos «retirados»: la (serie, ref) tenía valor en un vintage anterior y el último vintage visible es nulo
    ret = df(f"""with t as (select serie, fecha_referencia r, valor is null nul, fecha_publicacion p, vintage v from read_parquet({C})),
                 g as (select serie, r, arg_max(nul,(p,v)) un, max(case when not nul then p end) pval from t group by 1,2)
                 select serie, count(*) n, sum((r>=DATE '2000-01-01')::int) desde2000, max(r) ref_max from g where un and pval is not null group by 1 order by 2 desc""")
    R["vista_corte_nulo_con_valor_previo_n"] = int(ret["n"].sum()); R["vista_corte_nulo_con_valor_previo_series"] = int(len(ret))
    R["vista_corte_nulo_con_valor_previo_desde2000"] = int(ret["desde2000"].sum())
    R["vista_corte_nulo_con_valor_previo"] = ret.astype(str).to_dict("records")
    print("nulos al corte que antes tenían valor:", R["vista_corte_nulo_con_valor_previo_n"], "en", len(ret), "series; desde 2000:", R["vista_corte_nulo_con_valor_previo_desde2000"])
    print(ret.to_string())
    print(f"\nvista al corte: {R['vista_corte_nulos']} (serie,ref) nulas en {R['vista_corte_series']} series; "
          f"desde 2000: {R['vista_corte_nulos_desde2000']} en {R['vista_corte_series_desde2000']} series")
    return n


# ---------------------------------------------------------------- 2. base de trabajo frente a curada
def trabajo_vs_curada():
    print("\n== 2. Base de trabajo frente a curada")
    bn = df(f"""select fuente, count(*) nulos, count(distinct serie) series,
               count(distinct case when serie in (select distinct serie from read_parquet({C})) then serie end) series_curadas
               from read_parquet({B}) where valor is null group by 1 order by 2 desc""")
    print(bn.to_string()); R["trabajo_nulos_por_fuente"] = bn.to_dict("records")
    R["trabajo_total_nulos"] = int(bn["nulos"].sum())
    # nulos de la base en series curadas que no están (como nulos) en la curada
    falt = df(f"""with b as (select serie, fecha_referencia r, vintage v, fuente from read_parquet({B}) where valor is null
                              and serie in (select distinct serie from read_parquet({C}))),
                  c as (select serie, fecha_referencia r, vintage v from read_parquet({C}) where valor is null)
               select b.fuente, b.serie, count(*) n, min(b.r) desde, max(b.r) hasta from b anti join c using(serie, r, v) group by 1,2""")
    print("nulos de trabajo (series curadas) que no están en la curada:"); print(falt.to_string())
    R["nulos_trabajo_no_en_curada"] = falt.astype(str).to_dict("records")
    # (serie, ref) con valor no nulo en trabajo (publicado <= corte) y sin ninguna fila con valor en la curada
    pierde = df(f"""with b as (select distinct serie, fecha_referencia r from read_parquet({B})
                                where valor is not null and fecha_publicacion <= TIMESTAMP '2026-11-13'
                                and serie in (select distinct serie from read_parquet({C}))),
                     c as (select distinct serie, fecha_referencia r from read_parquet({C}) where valor is not null)
                select serie, count(*) n, min(r) desde, max(r) hasta from b anti join c using(serie, r) group by 1 order by 2 desc""")
    res = pd.read_csv(TAB / "curada_resumen.csv", usecols=["serie", "rol", "seccion", "filas_cortadas", "hasta", "publicada_hasta"])
    res = res.rename(columns={"hasta": "hasta_curada", "publicada_hasta": "publicada_hasta_curada"})
    pierde = pierde.merge(res, on="serie", how="left")
    print("periodos con valor en trabajo (pub<=corte) sin valor en curada:", int(pierde["n"].sum()), "en", len(pierde), "series")
    print(pierde.head(40).to_string())
    R["periodos_perdidos_total"] = int(pierde["n"].sum()); R["periodos_perdidos_series"] = int(len(pierde))
    pierde["antes2000"] = pd.to_datetime(pierde["hasta"]) < pd.Timestamp("2000-01-01")
    R["periodos_perdidos"] = pierde.astype(str).to_dict("records")
    # de las pérdidas, cuántas son el final (empujado más allá del corte por la fecha conservadora)
    fin = df(f"""with b as (select distinct serie, fecha_referencia r from read_parquet({B})
                             where valor is not null and fecha_publicacion <= TIMESTAMP '2026-11-13'
                             and serie in (select distinct serie from read_parquet({C}))),
                  c as (select distinct serie, fecha_referencia r from read_parquet({C}) where valor is not null),
                  cmax as (select serie, max(r) rmax, min(r) rmin from c group by 1)
             select sum((b.r > cmax.rmax)::int) al_final, sum((b.r < cmax.rmin)::int) al_principio,
                    sum((b.r between cmax.rmin and cmax.rmax)::int) en_medio
             from b anti join c using(serie, r) join cmax using(serie)""")
    print(fin.to_string()); R["periodos_perdidos_posicion"] = {k: int(v) for k, v in fin.iloc[0].items()}
    # series de trabajo con nulos que no son curadas (ust_curva, calculo_propio, worldbank)
    nc = df(f"""select fuente, serie, count(*) n from read_parquet({B}) where valor is null
               and serie not in (select distinct serie from read_parquet({C})) group by 1,2 order by 3 desc""")
    R["trabajo_nulos_series_no_curadas"] = nc.to_dict("records")
    print("nulos de trabajo en series NO curadas:"); print(nc.to_string())
    # alias con historia previa a 2000 solo en trabajo (pendiente menor del plan)
    al = pd.read_parquet("D:/tfm_corpus/mercados_series/series/alias.parquet")
    R["alias_columnas"] = list(al.columns); R["alias_n"] = int(len(al))
    print("alias.parquet:", len(al), list(al.columns))


# ---------------------------------------------------------------- 4. series paradas / discontinuadas
def paradas():
    print("\n== 4. Series paradas")
    vis = df(f"""with t as (select serie, fuente, fecha_referencia r, fecha_publicacion p, vintage v, valor is null nul
                            from read_parquet({C}) where fecha_publicacion <= TIMESTAMP '2026-11-13'),
                  u as (select serie, any_value(fuente) fuente, r, arg_max(p,(p,v)) p, arg_max(nul,(p,v)) nul from t group by serie, r),
                  k as (select *, row_number() over (partition by serie order by r desc) rn from u)
               select serie, fuente, r fecha_referencia, p fecha_publicacion, nul, rn from k where rn <= 60""")
    ult = df(f"""with t as (select serie, fecha_referencia r, fecha_publicacion p from read_parquet({C}))
                select serie, max(r) ult_ref, max(p) ult_pub from t group by 1""")
    ultv = df(f"select serie, max(fecha_referencia) ult_ref_valor from read_parquet({C}) where valor is not null group by 1")
    avisos = []
    for s, g in vis.groupby("serie"):
        g = g.sort_values("fecha_referencia")
        g["fecha_referencia"] = pd.to_datetime(g["fecha_referencia"]); g["fecha_publicacion"] = pd.to_datetime(g["fecha_publicacion"])
        a = tools._aviso_atraso_serie(s, g, CORTE)
        if a:
            avisos.append({"serie": s, "fuente": g["fuente"].iloc[0], "ult_ref": str(g["fecha_referencia"].max().date()),
                           "ult_pub": str(g["fecha_publicacion"].max().date()), "dias_habiles": tools._dias_habiles(g["fecha_publicacion"].max(), CORTE)})
    av = pd.DataFrame(avisos)
    print("Regla de tools (diarias/semanales, >max(10, 3×ritmo) días hábiles):", len(av))
    if len(av):
        print(av.to_string())
    R["atraso_tools_n"] = int(len(av)); R["atraso_tools"] = av.to_dict("records")
    R["atraso_tools_por_fuente"] = av.groupby("fuente").size().astype(int).to_dict() if len(av) else {}
    # Regla propia por frecuencia, para TODAS las series: atraso de la última ref visible frente a lo esperable
    u = ult.merge(ultv, on="serie", how="left").merge(cob, left_on="serie", right_on="id", how="left")
    u["fuente"] = u["serie"].str.split(":").str[0]
    for c_ in ("ult_ref", "ult_pub", "ult_ref_valor"):
        u[c_] = pd.to_datetime(u[c_])
    periodo = {"diaria": 1, "semanal": 7, "mensual": 31, "trimestral": 92, "semestral": 183, "anual": 366}
    u["periodo_d"] = u["frecuencia"].map(periodo).fillna(31)
    fin_periodo = u["ult_ref"] + pd.to_timedelta(u["periodo_d"] - 1, unit="D")
    u["dias_desde_fin_periodo"] = (CORTE - fin_periodo).dt.days
    u["esperado"] = u["lag_mediano_dias"].fillna(0) + 2 * u["periodo_d"] + 10
    u["parada"] = u["dias_desde_fin_periodo"] > u["esperado"]
    p = u[u["parada"]].sort_values("dias_desde_fin_periodo", ascending=False)
    cols = ["serie", "fuente", "frecuencia", "estado", "ult_ref", "ult_ref_valor", "ult_pub", "lag_mediano_dias", "dias_desde_fin_periodo", "esperado"]
    print("Regla propia (atraso > lag mediano + 2 periodos + 10 días):", len(p)); print(p[cols].to_string())
    R["parada_propia_n"] = int(len(p)); R["parada_propia"] = p[cols].astype(str).to_dict("records")
    R["parada_propia_por_fuente"] = p.groupby("fuente").size().astype(int).to_dict()
    R["parada_propia_mas_de_1_anio"] = int((p["dias_desde_fin_periodo"] > 365).sum())
    # serie cuya última ref VISIBLE al corte (vista as-of) es nula: acaba en hueco
    v1 = vis[vis["rn"] <= 3].copy()
    acaba = []
    for s_, g in v1.groupby("serie"):
        g = g.sort_values("rn")
        if bool(g["nul"].iloc[0]):
            acaba.append({"serie": s_, "ult_ref": str(pd.Timestamp(g["fecha_referencia"].iloc[0]).date()),
                          "nulas_entre_las_3_ultimas": int(g["nul"].sum())})
    R["acaban_en_nulo"] = acaba
    print("series cuya última ref es nula:", R["acaban_en_nulo"])


# ---------------------------------------------------------------- 5. huecos largos internos (EDA)
def huecos_eda():
    print("\n== 5. Huecos largos del EDA (series que quedan)")
    inc = pd.read_csv(TAB / "eda_series_incidencias.csv")
    res = pd.read_csv(TAB / "curada_resumen.csv", usecols=["serie"])
    cur = set(res["serie"])
    h = inc[inc["tipo"].str.contains("hueco", na=False)].copy()
    R["eda_tipos_incidencia"] = inc["tipo"].value_counts().astype(int).to_dict()
    h["curada"] = h["serie"].isin(cur)
    hc = h[h["curada"]]
    print("huecos (todas):", len(h), "en curadas:", len(hc), "series:", hc["serie"].nunique())
    hc = hc.assign(tamano=pd.to_numeric(hc["tamano"], errors="coerce"))
    top = hc.sort_values("tamano", ascending=False)[["serie", "fuente", "frecuencia", "fecha", "fecha_fin", "tamano", "medida", "propuesta_paso4"]].head(25)
    print(top.to_string())
    R["eda_huecos_curadas_n"] = int(len(hc)); R["eda_huecos_curadas_series"] = int(hc["serie"].nunique())
    R["eda_huecos_curadas_por_fuente"] = hc.groupby("fuente").size().astype(int).to_dict()
    R["eda_huecos_curadas_desde2000"] = int((pd.to_datetime(hc["fecha_fin"], errors="coerce") >= "2000-01-01").sum())
    R["eda_huecos_top"] = top.astype(str).to_dict("records")
    eds = pd.read_csv(TAB / "eda_series.csv", usecols=["serie", "fuente", "frecuencia", "max_hueco_periodos", "max_hueco_desde", "max_hueco_hasta", "n_huecos_largos"])
    eds = eds[eds["serie"].isin(cur) & (eds["n_huecos_largos"] > 0)]
    R["eda_series_con_hueco_largo"] = int(len(eds))
    R["eda_series_hueco_desde2000"] = eds[pd.to_datetime(eds["max_hueco_hasta"], errors="coerce") >= "2000-01-01"].astype(str).to_dict("records")
    print("series curadas con hueco largo (eda_series):", len(eds))
    print(pd.DataFrame(R["eda_series_hueco_desde2000"]).to_string())


if __name__ == "__main__":
    nulos_curada()
    trabajo_vs_curada()
    paradas()
    huecos_eda()
    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\nescrito", OUT)
