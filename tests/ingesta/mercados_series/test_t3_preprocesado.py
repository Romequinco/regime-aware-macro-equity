"""Paso 3 de la descarga completa del Tema 1 · ``preprocesado``: el borrador del plan del paso 4 (E4, E5, D4).

Las pruebas unitarias usan el YAML del repo, ``lista_curada.yaml``, las tablas versionadas de los pasos 2 y 3 (solo
metadatos) y datos sintéticos (sin red ni corpus). La última lleva ``@pytest.mark.datos`` y se salta si falta
``<corpus>/mercados_series/series/base_series.parquet``.
"""
from __future__ import annotations

import copy
import fnmatch

import numpy as np
import pandas as pd
import pytest

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, catalogo, eda
from ingesta.mercados_series import preprocesado as pp
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, primera_decision_vec

TABLAS = resultados_dir("mercados_series") / "tablas"


@pytest.fixture(scope="module")
def plan() -> dict:
    return pp.cargar_plan()


@pytest.fixture(scope="module")
def lags() -> dict:
    return catalogo.cargar_lags()


@pytest.fixture(scope="module")
def lista() -> dict:
    return pp.cargar_lista()


@pytest.fixture(scope="module")
def tablas() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_csv(TABLAS / "inventario_series.csv"), pd.read_csv(TABLAS / "fiabilidad_c.csv")


def _barrido(fin_periodo: str) -> pd.Series:
    """Fechas de referencia: mensual, trimestral y anual de varias décadas; diaria con fines de semana y festivos."""
    if fin_periodo == "mes":
        return pd.Series(pd.date_range("1995-01-01", "2026-12-01", freq="MS"))
    if fin_periodo == "trimestre":
        return pd.Series(pd.date_range("1995-01-01", "2026-10-01", freq="QS"))
    if fin_periodo == "anio":
        return pd.Series(pd.date_range("1985-01-01", "2026-01-01", freq="YS"))
    tramos = [("1999-12-01", "2001-12-31"), ("2012-10-15", "2013-04-15"), ("2024-11-15", "2026-01-15")]
    return pd.Series(np.concatenate([pd.date_range(a, b).to_numpy() for a, b in tramos]))


# --- El YAML valida ---------------------------------------------------------------------------------------
def test_plan_valida_y_es_borrador(plan):
    assert plan["estado"] == "borrador"
    assert set(plan["reglas_conservadoras"]) == set(pp.GRUPOS)
    assert all(g["reglas"] for g in plan["reglas_conservadoras"].values())
    assert plan["tramo_no_fiable"]["margen_dias"] == 7
    assert plan["homogeneizacion"]["frecuencias"]["remuestrear"] is False


@pytest.mark.parametrize("romper, error", [
    (lambda p: p.update(estado="aprobado"), "borrador"),
    (lambda p: p["reglas_conservadoras"]["banco_mundial"]["reglas"]["WB_ANUAL"]["actual"].update(lag="6M"),
     "lags.yaml"),
    (lambda p: p["reglas_conservadoras"]["banco_mundial"]["reglas"]["WB_ANUAL"].pop("conservadora"),
     "pendiente_calendario"),
    (lambda p: p["reglas_conservadoras"]["mercado_diario"]["reglas"]["ecb_fx"]["actual"].update(hora="17:00"),
     "publicaciones.yaml"),
    (lambda p: p["tramo_no_fiable"]["series"]["fred:CFNAI"].update(dias_extra=1), "dias_extra"),
    (lambda p: p["incidencias_eda"]["tipos"]["salto"].update(accion="borrar"), "accion"),
    (lambda p: p["homogeneizacion"]["frecuencias"].update(remuestrear=True), "remuestrear"),
    (lambda p: p["reglas_conservadoras"]["academicas"]["reglas"]["FF_MENSUAL"].update(
        conservadora=None, pendiente_calendario=True), "falta"),
    (lambda p: p["reconstruidas"]["externas"]["gw:*"].update(fuente="la web de Goyal"), "URL"),
])
def test_plan_rechaza_errores(romper, error):
    crudo = copy.deepcopy(pp._yaml(pp.RUTA_PLAN))
    romper(crudo)
    with pytest.raises(ValueError, match=error):
        pp.validar_plan(crudo)


def test_no_queda_pendiente_calendario(plan):
    """F1 y F2 cerradas: ninguna regla ni reconstrucción queda pendiente de calendario."""
    assert not [c for g in plan["reglas_conservadoras"].values() for c, e in g["reglas"].items()
                if e.get("pendiente_calendario")]
    assert "pendiente_calendario" not in pp.RUTA_PLAN.read_text(encoding="utf-8")


def test_pendiente_calendario_no_cambia_fechas(plan):
    crudo = copy.deepcopy(pp._yaml(pp.RUTA_PLAN))
    e = crudo["reglas_conservadoras"]["academicas"]["reglas"]["FF_MENSUAL"]
    e.pop("conservadora")
    e.update(pendiente_calendario=True, falta="prueba")
    p = pp.validar_plan(crudo)
    asig = pd.DataFrame([{"id": "ff:X", "seccion": "reglas_conservadoras", "grupo": "academicas",
                          "regla": "FF_MENSUAL", "corte": pd.NaT}])
    b = pd.DataFrame({"serie": "ff:X", "fecha_referencia": pd.to_datetime(["2005-01-01"]),
                      "fecha_publicacion": pd.to_datetime(["2005-03-17"]), "metodo_publicacion": "fichero"})
    cur = pp.fechas_curadas(b, p, asig, catalogo_series={})
    assert cur["pendiente"].all() and (cur["fecha_publicacion_curada"] == b["fecha_publicacion"]).all()


def _conservadora(plan: dict, grupo: str, clave: str) -> dict:
    return plan["reglas_conservadoras"][grupo]["reglas"][clave]["conservadora"]


def test_french_anual_antes_de_2005_09_y_mensual_despues(plan):
    regla = _conservadora(plan, "academicas", "FF_MENSUAL")
    refs = pd.Series(pd.to_datetime(["2003-03-01", "2005-08-15", "2005-09-01", "2025-06-30"]))
    f = pp.fecha_regla(refs, regla)
    assert list(f.dt.date.astype(str)) == ["2005-01-07", "2007-01-07", "2005-12-07", "2025-09-07"]
    # desde 2005-09 cubre los retrasos medidos: septiembre de 2006 aún no estaba el 17 de noviembre; 42 días en 2025
    assert pp.fecha_regla(pd.Series(pd.to_datetime(["2006-09-01"])), regla).iloc[0] > pd.Timestamp("2006-11-17")


def test_goyal_welch_13m_y_2022_fijo(plan):
    regla = _conservadora(plan, "academicas", "GW_ANUAL")
    refs = pd.Series(pd.to_datetime(["2009-06-01", "2021-12-01", "2022-01-01", "2022-12-01", "2023-01-01"]))
    f = pp.fecha_regla(refs, regla)
    assert list(f.dt.date.astype(str)) == ["2011-01-31", "2023-01-31", "2024-04-15", "2024-04-15", "2025-01-31"]
    assert f.iloc[0] > pd.Timestamp("2010-11-10")       # datos hasta 2009 guardados el 2010-11-10


def test_ofr_cubre_dos_habiles_y_bis_cinco_meses_y_medio(plan):
    refs = _barrido("fecha")
    ofr = pp.fecha_regla(refs, _conservadora(plan, "academicas", "OFR_FSI"))
    dos = catalogo.fecha_publicacion_lag(refs, "1D", "fecha", habiles="us_federal", n_habiles=2)
    assert (ofr >= dos.to_numpy()).all()
    q1 = pd.Series([pd.Timestamp("2026-01-01")])
    for clave in ("BIS_WS_CREDIT_GAP", "BIS_WS_DSR"):
        assert pp.fecha_regla(q1, _conservadora(plan, "macro_eurostat_bce_bis", clave)).iloc[0] >= \
            pd.Timestamp("2026-09-14")


def test_tramo_sale_de_las_tablas(plan, lista, lags):
    propuesta = pp.propuesta_tramo(plan, lista, lags=lags)
    assert propuesta == plan["tramo_no_fiable"]["series"]
    # medidas por serie de la ronda de corrección: sin el episodio de Moody's y sin heredar la regla
    s = plan["tramo_no_fiable"]["series"]
    assert s["fred:DAAA"]["adelanto_dias"] == 5 and s["fred:BAAFFM"]["adelanto_dias"] == 18
    assert s["fred:TEDRATE"]["adelanto_dias"] < 162
    assert {"fred:CFSI", "fred:WALCL", "fred:DPSACBW027SBOG"} <= {k for k, v in s.items()
                                                                if v["veredicto"] == "fiable con margen"}
    assert "fred:LIOR3M" not in s and not any(k.startswith("eurostat:") for k in s)


def test_asignacion_coincide_con_la_lista(plan, lista, tablas):
    inv, fia = tablas
    asig = pp.asignar_series(plan, lista, inv, fia).set_index("id")
    assert not (asig["seccion"] == "sin_regla_en_plan").any()
    queda = {s for s, e in lista.items() if e["decision"] == "queda"}
    assert set(asig.index) <= queda
    derivadas = set(inv.loc[inv["metodo_publicacion"] == "derivada", "id"])
    for sid, e in lista.items():
        if sid not in queda or sid in derivadas:
            continue
        if e.get("aviso_fecha") == "no medible":     # mismo grupo que la lista
            assert asig.loc[sid, "seccion"] == "reglas_conservadoras" and asig.loc[sid, "grupo"] == \
                e["regla_conservadora"], sid
        elif e.get("aviso_fecha") == "no fiable":    # tramo con el corte de la lista, o no medible documentado
            a = asig.loc[sid]
            if a["seccion"] == "tramo_no_fiable":
                antes = e["tramo_conservador_antes_de"]
                assert (pd.isna(a["corte"]) if antes == "toda" else a["corte"] == pd.Timestamp(antes)), sid
            else:
                assert a["regla"] in ("EUROSTAT_HICP", "EUROSTAT_ESI", "LIBOR_3M_QUARTERLY", "DOL_ICSA",
                                          "DOL_CONTINUADAS"), sid   # saneado P12: calendario del DOL


# --- Las reglas conservadoras nunca adelantan -----------------------------------------------------------------
def _pares(plan: dict) -> list[tuple[str, dict]]:
    pares = []
    for g in plan["reglas_conservadoras"].values():
        for c, e in g["reglas"].items():
            base = pp._clave_lags(c, e)
            if e.get("conservadora") is not None:
                pares.append((base, e["conservadora"]))
            pares += [(base, alt["regla"]) for alt in (e.get("alternativas") or {}).values()]
    vistos = set()
    for e in plan["tramo_no_fiable"]["series"].values():
        k = (e["regla"], e["dias_extra"])
        if k not in vistos:
            vistos.add(k)
            pares.append((e["regla"], e["conservadora"]))
    return pares + [(plan["h15_diario"]["publicador"], plan["h15_diario"]["conservadora"])]


def test_conservadora_igual_o_mas_tardia_en_un_barrido(plan, lags):
    """Toda regla conservadora (E4, alternativas, E5 por serie y H.15), sola: >= la actual en cada referencia."""
    malas = []
    for clave, cons in _pares(plan):
        actual = pp.regla_actual(clave, lags)
        refs = _barrido(actual.get("fin_periodo", "fecha"))
        a, k = pp.fecha_regla(refs, actual), pp.fecha_regla(refs, cons)
        assert a.notna().all() and k.notna().all(), clave
        if (k < a).any():
            malas.append((clave, refs[k < a].iloc[0].date()))
    assert not malas, malas


def test_barrido_cubre_habiles_y_tramos(lags):
    refs = _barrido("fecha")
    assert (refs == pd.Timestamp("2025-12-25")).any() and (refs == pd.Timestamp("2000-04-21")).any()
    meses = _barrido("mes")
    f = pp.fecha_regla(meses, pp.regla_actual("EUROSTAT_PARO", lags))
    assert f[meses == pd.Timestamp("2011-12-01")].iloc[0] == pd.Timestamp("2012-02-29")   # fin de M+2
    assert f[meses == pd.Timestamp("2012-01-01")].iloc[0] == pd.Timestamp("2012-03-12")   # 1M10D + hábil TARGET


def test_fecha_conservadora_nunca_adelanta_y_respeta_el_tope():
    rng = np.random.default_rng(0)
    refs = pd.Series(pd.date_range("2000-01-01", periods=400, freq="MS"))
    actual = refs + pd.to_timedelta(rng.integers(0, 400, len(refs)), unit="D")
    actual.iloc[5] = pd.NaT
    regla = {"lag": "1M1D", "fin_periodo": "mes"}
    nueva = pp.fecha_conservadora(refs, actual, regla)
    ok = actual.notna()
    assert (nueva[ok] >= actual[ok]).all() and pd.isna(nueva.iloc[5])
    assert (nueva[ok] == np.maximum(actual[ok], pp.fecha_regla(refs, regla)[ok])).all()
    tope = refs + pd.Timedelta(days=40)                 # antes de la regla (día 1 de M+2)
    con = pp.fecha_conservadora(refs, actual, regla, tope=tope)
    assert (con[ok] == np.maximum(actual[ok], tope[ok])).all()


def test_tope_primer_vintage_lee_la_nota():
    notas = [f"{catalogo.NOTA_PREVIA_ALFRED} (2011-05-25); otra nota", None, "sin previa"]
    t = pp.tope_primer_vintage(notas)
    assert t.iloc[0] == pd.Timestamp("2011-05-25") and t.iloc[1:].isna().all()


def test_regla_de_publicador_suma_sobre_la_decision():
    refs = pd.Series(pd.to_datetime(["2025-07-03", "2025-12-24", "2026-01-09"]))   # jueves, Nochebuena, viernes
    a = pp.fecha_regla(refs, {"publicador": "treasury_curva"})
    k = pp.fecha_regla(refs, {"publicador": "treasury_curva", "lag": "1D", "habiles": "us_federal"})
    assert list(a.dt.date.astype(str)) == ["2025-07-04", "2025-12-25", "2026-01-10"]
    assert list(k.dt.date.astype(str)) == ["2025-07-07", "2025-12-29", "2026-01-12"]


def test_sumar_dias_lag():
    assert pp.sumar_dias_lag("1M1D", 24) == "1M25D"
    assert pp.sumar_dias_lag("24M", 137) == "24M137D"
    assert pp.sumar_dias_lag("5D", 22) == "27D"
    assert pp.sumar_dias_lag("6M", 0) == "6M"


# --- Tramo no fiable, tope, reconstruidas, disponible_utc y orden -------------------------------------------------
def _plan_sintetico(plan: dict, extra: int = 26) -> dict:
    p = copy.deepcopy(plan)
    p["tramo_no_fiable"]["series"] = {"fred:NF": {
        "regla": "UNRATE", "veredicto": "no fiable", "corte": "2010-06-04", "adelanto_dias": extra - 7,
        "medida": "alfred_previa", "n": 100, "dias_extra": extra,
        "conservadora": {"lag": pp.sumar_dias_lag("1M1D", extra), "fin_periodo": "mes"}}}
    p["reconstruidas"]["series"] = {}
    return p


def _base_sintetica() -> pd.DataFrame:
    refs = pd.date_range("2008-01-01", "2012-12-01", freq="MS")
    regla = catalogo.fecha_publicacion_clave(pd.Series(refs), "UNRATE")
    corte = pd.Timestamp("2010-06-04")
    metodo = np.where(regla < corte, "lag_fijo", "vintage_exacto")
    metodo[-1] = "lag_fijo"                            # una fila por regla DESPUÉS del corte: no se toca
    filas = pd.DataFrame({"serie": "fred:NF", "fecha_referencia": refs, "fecha_publicacion": regla.to_numpy(),
                          "metodo_publicacion": metodo, "nota": None,
                          "disponible_utc": pd.Series(pd.NaT, index=range(len(refs)), dtype="datetime64[ns, UTC]")})
    return filas


def test_tramo_solo_antes_del_corte(plan):
    p = _plan_sintetico(plan)
    b = _base_sintetica()
    asig = pp.asignar_series(p, {"fred:NF": {"decision": "queda", "aviso_fecha": "no fiable"}},
                             pd.DataFrame([{"id": "fred:NF", "veredicto_desde_2000": "no fiable", "clave_regla": "UNRATE",
                                            "fuente": "fred_alfred", "metodo_publicacion": "lag_fijo"}]))
    cur = pp.fechas_curadas(b, p, asig, catalogo_series={})
    antes = b["fecha_publicacion"] < pd.Timestamp("2010-06-04")
    cambia = cur["fecha_publicacion_curada"] != b["fecha_publicacion"]
    assert cambia[antes].all() and not cambia[~antes].any()
    assert ((cur["fecha_publicacion_curada"] - b["fecha_publicacion"]).dt.days[antes] == 26).all()


def test_tope_reconstruidas_disponible_y_orden(plan):
    """Previa con tope X: no pasa de X ni de los vintages reales; reconstruida: a publicado_desde; disponible nulo."""
    p = _plan_sintetico(plan, extra=60)
    p["reconstruidas"]["series"] = {"fred:NF": "2009-06-01"}
    x = "2009-03-15"
    b = pd.DataFrame({
        "serie": "fred:NF",
        "fecha_referencia": pd.to_datetime(["2008-12-01", "2008-12-01", "2009-01-01"]),
        "fecha_publicacion": pd.to_datetime(["2009-02-01", "2009-03-15", "2009-03-01"]),
        "metodo_publicacion": ["lag_fijo", "vintage_exacto", "lag_fijo"],
        "nota": [f"{catalogo.NOTA_PREVIA_ALFRED} ({x})", None, f"{catalogo.NOTA_PREVIA_ALFRED} ({x})"],
        "disponible_utc": pd.to_datetime(["2009-02-01 13:30", "2009-03-15 12:30", None], utc=True)})
    asig = pd.DataFrame([{"id": "fred:NF", "seccion": "tramo_no_fiable", "grupo": "no_fiable", "regla": "UNRATE",
                          "corte": pd.Timestamp("2010-06-04")}])
    p["reconstruidas"]["series"] = {}
    cur = pp.fechas_curadas(b, p, asig, catalogo_series={})
    assert list(cur["fecha_publicacion_curada"]) == [pd.Timestamp(x)] * 3     # la regla (+60) se para en X
    assert cur["con_tope"].iloc[[0, 2]].all()
    ver = pp.verificar(b, cur)
    assert not ver.any().any()
    assert pd.isna(cur["disponible_utc_curada"].iloc[0])                      # cambia de fecha: disponible nulo
    assert cur["disponible_utc_curada"].iloc[1] == b["disponible_utc"].iloc[1]
    p["reconstruidas"]["series"] = {"fred:NF": "2009-06-01"}
    cur = pp.fechas_curadas(b, p, asig, catalogo_series={})
    assert (cur["fecha_publicacion_curada"] == pd.Timestamp("2009-06-01")).all() and cur["reconstruida"].all()
    assert not pp.verificar(b, cur).any().any()


def test_verificar_detecta_fallos():
    b = pd.DataFrame({"serie": "s", "fecha_referencia": pd.to_datetime(["2020-01-01"] * 2),
                      "fecha_publicacion": pd.to_datetime(["2020-02-01", "2020-03-01"])})
    disp = pd.to_datetime(["2020-02-01 12:00", None], utc=True)
    cur = pd.DataFrame({"fecha_publicacion_curada": pd.to_datetime(["2020-04-01", "2020-02-15"]),
                        "disponible_utc_curada": disp})
    v = pp.verificar(b, cur)
    assert v["adelanta"].tolist() == [False, True]
    assert v["disponible_incoherente"].tolist() == [True, False]
    assert v["orden_roto"].sum() == 1
    assert primera_decision_vec(pd.Series(disp[:1])).iloc[0] == pd.Timestamp("2020-02-01")


def test_reconstruidas_coinciden_con_el_catalogo(plan, lista):
    cat = catalogo.cargar_catalogo()
    queda = {s for s, e in lista.items() if e["decision"] == "queda"}
    esperadas = {s: str(e["publicado_desde"]) for s, e in cat.items() if e.get("publicado_desde") and s in queda}
    assert {k: str(v) for k, v in plan["reconstruidas"]["series"].items()} == esperadas
    assert "fred:STLFSI4" in esperadas
    ext = plan["reconstruidas"]["externas"]
    assert all("https://" in e["fuente"] for e in ext.values())
    esperado = {"ofr:FSI": "2017-10-25", "ofr:FSI_CREDIT": "2017-10-25", "gw:M.lty": "2004-04-13",
                "bis:WS_CREDIT_GAP.Q.CA.P.A.C": "2016-09-18", "bis:WS_DSR.Q.CA.P": "2015-09-13",
                "ff:F3M.Mkt-RF": "2001-12-18", "ff:F3D.HML": "2002-06-04", "ff:F5M.SMB": "2014-12-19",
                "ff:F5D.RMW": "2015-06-01", "ff:MOMD.Mom": "2005-07-26", "ff:IND5D.Hlth": "2005-07-26",
                "fred:NFCI": "2011-05-25"}
    pd_ = pp.publicado_desde(plan, esperado)
    assert {k: pd_[k] for k in esperado} == esperado
    # toda serie que se queda de estas fuentes tiene su publicado_desde
    for sid in queda:
        if sid.startswith(("ofr:", "gw:", "ff:", "bis:WS_CREDIT_GAP", "bis:WS_DSR")):
            assert any(fnmatch.fnmatch(sid, pat) for pat in ext), sid


def test_reconstruida_externa_no_deja_ver_antes(plan):
    b = pd.DataFrame({"serie": "gw:M.lty", "fecha_referencia": pd.to_datetime(["1990-01-01", "2010-01-01"]),
                      "fecha_publicacion": pd.to_datetime(["1991-08-01", "2011-08-01"]),
                      "metodo_publicacion": "fichero", "nota": None})
    asig = pd.DataFrame(columns=["id", "seccion", "grupo", "regla", "corte"])
    cur = pp.fechas_curadas(b, plan, asig, catalogo_series={})
    assert list(cur["fecha_publicacion_curada"]) == [pd.Timestamp("2004-04-13"), pd.Timestamp("2011-08-01")]


# --- Proyecciones (D4) --------------------------------------------------------------------------------------------
def test_proyecciones_se_separan():
    b = pd.DataFrame({
        "serie": ["imf:WEO.DEU.NGDP_RPCH", "imf:WEO.DEU.NGDP_RPCH.PROY.H2", "fred:UNRATEMD", "fred:UNRATEMD"],
        "fecha_referencia": pd.to_datetime(["2025-01-01", "2028-01-01", "2026-01-01", "2027-01-01"]),
        "fecha_publicacion": pd.to_datetime(["2026-10-14", "2026-10-14", "2025-12-10", "2025-12-10"]),
        "vintage": ["2026-10", "2026-10", "2025-12-10", "2025-12-10"]})
    for c in COLUMNAS_SERIES:
        if c not in b:
            b[c] = None
    resto, proy = pp.separar_proyecciones(b, {"imf:WEO.DEU.NGDP_RPCH.PROY.H2", "fred:UNRATEMD"})
    assert list(resto["serie"]) == ["imf:WEO.DEU.NGDP_RPCH"] and len(resto) + len(proy) == len(b)
    assert list(proy["horizonte"]) == [2, 1, 2]
    assert list(proy["edicion"]) == ["2026-10", "2025-12-10", "2025-12-10"]
    assert set(pp.COLUMNAS_PROYECCIONES) <= set(proy.columns)
    assert (proy["fecha_publicacion"] == b.loc[proy.index, "fecha_publicacion"]).all()


def test_proyecciones_esperadas_cuadran(plan, tablas, lista):
    inv, _ = tablas
    p = inv[inv["es_proyeccion"].astype(bool)]
    # Saneado P16: el WEO sale de la curada (decision fuera); las demás proyecciones siguen en la tabla aparte.
    p = p[p["id"].map(lambda s: lista.get(s, {}).get("decision")) == "proyecciones"]
    esperadas = plan["proyecciones"]["esperadas"]
    assert len(p) == esperadas["total"] == sum(e["decision"] == "proyecciones" for e in lista.values())
    assert p["fuente"].value_counts().to_dict() == {k: v for k, v in esperadas.items() if k != "total" and v}


# --- Homogeneización, escalas por vintage e incidencias -----------------------------------------------------------
def test_homogeneizacion_sin_reglas_muertas(plan, tablas, lista):
    inv, _ = tablas
    unidades = set(inv["unidad"].dropna())
    queda = {s for s, e in lista.items() if e["decision"] == "queda"}
    ho = plan["homogeneizacion"]
    for par in ho["unidades_equivalentes"]:
        assert set(par["unidades"]) <= unidades, par
    for esc in ho["escalas"]:
        assert set(esc["series"]) == set(inv.loc[inv["unidad"] == esc["unidad"], "id"]) & queda


def test_escalas_por_vintage_salen_del_eda(plan, lista):
    inc = pd.read_csv(TABLAS / "eda_series_incidencias.csv")
    propuesta = pp.propuesta_escalas_vintage(inc, lista)
    assert [{k: (str(v) if k == "antes_de_vintage" else v) for k, v in e.items()}
            for e in plan["escalas_por_vintage"]["series"]] == propuesta
    assert {e["serie"] for e in propuesta} == {"fred:BOGMBASE", "fred:REVOLSL", "fred:TOTALSL", "fred:BCNSDODNS",
                                               "fred:CMDEBT", "fred:TNWBSHNO"}
    assert {e["serie"]: e["factor"] for e in propuesta}["fred:BOGMBASE"] == 0.001


def test_incidencias_sincronizadas_con_el_eda(plan):
    tipos = plan["incidencias_eda"]["tipos"]
    assert set(tipos) == set(eda.PROPUESTAS)            # ninguna clave muerta ni ningún tipo sin acción
    assert all(tipos[t]["accion"] == a for t, a in eda.PROPUESTAS.items())
    resumen = pd.read_csv(TABLAS / "eda_resumen.csv")
    assert set(resumen["tipo"]) <= set(tipos)


# --- Simulación ----------------------------------------------------------------------------------------------------
def test_simular_con_tablas_sinteticas(plan):
    p = _plan_sintetico(plan)
    b = pd.concat([_base_sintetica(),
                   pd.DataFrame({"serie": "bis:NM", "fecha_referencia": pd.to_datetime(["2008-01-01"] * 3),
                                 "fecha_publicacion": pd.to_datetime(["2009-01-01"] * 3),
                                 "metodo_publicacion": "lag_fijo", "nota": None,
                                 "disponible_utc": pd.Series(pd.NaT, index=range(3), dtype="datetime64[ns, UTC]")})],
                  ignore_index=True)
    inv = pd.DataFrame([
        {"id": "fred:NF", "veredicto_desde_2000": "no fiable", "clave_regla": "UNRATE", "fuente": "fred_alfred",
         "metodo_publicacion": "lag_fijo", "es_proyeccion": False},
        {"id": "bis:NM", "veredicto_desde_2000": "no medible", "clave_regla": "BIS_WS_EER", "fuente": "bis",
         "metodo_publicacion": "lag_fijo", "es_proyeccion": False}])
    lista = {"fred:NF": {"decision": "queda", "aviso_fecha": "no fiable"},
             "bis:NM": {"decision": "queda", "aviso_fecha": "no medible"}}
    fia = pd.DataFrame({"regla": ["UNRATE", "BIS_WS_EER"], "n_comparaciones": [100, 0]})
    sim = pp.simular(base=b, plan=p, lista=lista, inventario_series=inv, fiabilidad=fia, catalogo_series={})
    assert list(sim.columns) == list(pp.COLUMNAS_SIMULACION)
    s = sim.set_index("regla")
    assert s.loc["UNRATE", "filas_regla"] == s.loc["UNRATE", "filas_cambian"] == 28
    assert s.loc["BIS_WS_EER", "filas_regla"] == 3
    tot = sim[sim["seccion"] == "total"].iloc[0]
    assert tot["filas_adelantan"] == tot["filas_disponible_incoherente"] == tot["filas_orden_roto"] == 0
    assert not any("valor" in c for c in sim.columns)    # solo recuentos y días


# --- Datos reales ---------------------------------------------------------------------------------------------------
@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series().exists(), reason="falta la base real (construir-base --sin-red)")
def test_simulacion_real_pasa_las_verificaciones(plan):
    sim = pp.simular(plan=plan)
    tot = sim[sim["seccion"] == "total"].iloc[0]
    assert tot["filas_adelantan"] == 0 and tot["filas_disponible_incoherente"] == 0 and tot["filas_orden_roto"] == 0
    assert not (sim["seccion"] == "sin_regla_en_plan").any()
    rec = sim[sim["seccion"] == "reconstruidas"].iloc[0]
    assert rec["filas_cambian"] > 0
