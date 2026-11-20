"""Paso 3 del Tema 1 · selección (``ingesta.mercados_series.seleccion``).

Unitarios con tablas sintéticas: E2 (dos plazos de una curva nunca son alias), D9 estricto, D4 a
proyecciones, canónico E1 con desempate y caso dudoso, alias en estrella con el filtro de Spearman,
«no medible» con aviso, «no fiable» con tramo conservador, E3 en Eurostat, cadenas de alias y que
ningún ticker sale por fecha de inicio (D10 abierta). El test ``@pytest.mark.datos`` lee las tablas
reales del paso 2 (se salta si falta la base, como el resto del tema) y comprueba la lista curada.
"""
from __future__ import annotations

import pandas as pd
import pytest

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen
from ingesta.mercados_series import seleccion as sel


def _inv(filas: list[dict]) -> pd.DataFrame:
    base = {"fuente": "fred_alfred", "frecuencia": "diaria", "estado": "activa", "nivel_fecha": "B",
            "pub_desde": "1990-01-01", "desde_2000": True, "desde_2000_exacto": False, "metodo_publicacion": "calendario",
            "pct_huecos_desde_2000": 0.0, "es_proyeccion": False, "posible_frontera": None, "clave_regla": "fed_h15",
            "veredicto_desde_2000": "verificada sin medir", "fiable_desde": None}
    return pd.DataFrame([{**base, **f} for f in filas])


def _par(a: str, b: str, fa: str, fb: str, pearson: float = 0.99, spearman: float = 0.99, anios: float = 20.0,
         mismo_concepto: bool = False, regla: str = "diferencia") -> dict:
    return {"serie_a": a, "serie_b": b, "frecuencia": "diaria", "fuente_a": fa, "fuente_b": fb,
            "misma_fuente": fa == fb, "mismo_concepto": mismo_concepto, "pearson": pearson, "spearman": spearman,
            "anios_solape": anios, "base_correlacion": "diaria", "regla_a": regla, "regla_b": regla,
            "outlier_dominado": abs(pearson) >= 0.95 and abs(spearman) < 0.90}


_FIA = pd.DataFrame({"regla": ["fed_h15"], "n_comparaciones": [100]})
_VACIO_CONC = pd.DataFrame(columns=["grupo", "concepto", "pais", "miembros", "n_pares", "n_pares_medidos", "corr_min",
                                    "solape_min_anios_par"])
_VACIO_BMW = pd.DataFrame(columns=["serie", "fuente", "indicador", "es_proyeccion", "pais", "en_alcance_estricto",
                                   "duplica_con_mayor_frecuencia", "series_mayor_frecuencia"])


def _seleccion(inv, pares=None, conc=None, bmw=None, fia=None, **kw) -> pd.DataFrame:
    pares = pd.DataFrame(pares or [], columns=list(_par("a", "b", "x", "y")))
    out, _ = sel.seleccionar_series(inv, _FIA if fia is None else fia, pares, _VACIO_CONC if conc is None else conc,
                                    _VACIO_BMW if bmw is None else bmw, min_comparaciones=20, **kw)
    return out.set_index("id")


# --- E2 -----------------------------------------------------------------------------------------
def test_plazos_de_curva():
    assert sel.plazo_curva("ust:PAR.10Y") == ("ust_par", 120.0)
    assert sel.plazo_curva("fred:DGS3MO") == ("fred_dgs", 3.0)
    assert sel.plazo_curva("fred:DGS10") == ("fred_dgs", 120.0)
    assert sel.plazo_curva("ecb:YC.AAA.15Y") == ("ecb_yc_AAA", 180.0)
    assert sel.plazo_curva("boe:NOM.6M") == ("boe_NOM", 6.0)
    assert sel.plazo_curva("yf:^TNX") == ("yahoo_tesoro", 120.0)
    assert sel.plazo_curva("fred:UNRATE") is None


def test_e2_dos_plazos_de_una_curva_nunca_son_alias():
    inv = _inv([{"id": "ust:PAR.2Y", "fuente": "ust_curva"}, {"id": "ust:PAR.3Y", "fuente": "ust_curva"},
                {"id": "ecb:YC.AAA.15Y", "fuente": "bce_curvas"}, {"id": "ecb:YC.AAA.20Y", "fuente": "bce_curvas"},
                {"id": "fred:DGS10", "pub_desde": "1962-01-02"}, {"id": "ust:PAR.7Y", "fuente": "ust_curva"},
                {"id": "ust:PAR.10Y", "fuente": "ust_curva"}])
    pares = [_par("ust:PAR.2Y", "ust:PAR.3Y", "ust_curva", "ust_curva", 0.999, 0.999),
             _par("ecb:YC.AAA.15Y", "ecb:YC.AAA.20Y", "bce_curvas", "bce_curvas", 0.99, 0.99),
             _par("fred:DGS10", "ust:PAR.7Y", "fred_alfred", "ust_curva", 0.98, 0.98),
             _par("fred:DGS10", "ust:PAR.10Y", "fred_alfred", "ust_curva", 1.0, 1.0)]
    out = _seleccion(inv, pares)
    for s in ("ust:PAR.2Y", "ust:PAR.3Y", "ecb:YC.AAA.15Y", "ecb:YC.AAA.20Y", "ust:PAR.7Y"):
        assert out.at[s, "decision"] == "queda", s
    # el mismo plazo de dos fuentes sí es alias
    assert out.at["ust:PAR.10Y", "decision"] == "alias"
    assert out.at["ust:PAR.10Y", "alias_de"] == "fred:DGS10"
    assert sel.motivo_bloqueo("ust:PAR.2Y", "ust:PAR.3Y", fuente_a="ust_curva", fuente_b="ust_curva").startswith("E2")


def test_misma_fuente_solo_versiones_y_otra_clase_de_dato():
    assert sel.motivo_bloqueo("fred:PAYEMS", "fred:USPRIV", fuente_a="fred_alfred", fuente_b="fred_alfred") != ""
    assert sel.motivo_bloqueo("fred:DFF", "fred:EFFR", fuente_a="fred_alfred", fuente_b="fred_alfred",
                              mismo_concepto=True) == ""
    assert sel.motivo_bloqueo("ff:F3D.Mkt-RF", "yf:^NYA", fuente_a="ken_french", fuente_b="yfinance",
                              regla_a="rentabilidad", regla_b="log").startswith("otra clase")


# --- D8 · estrella con Spearman ----------------------------------------------------------------
def test_alias_en_estrella_con_filtro_de_spearman():
    inv = _inv([{"id": "x:A", "fuente": "f1", "nivel_fecha": "A", "pub_desde": "1980-01-01"},
                {"id": "y:B", "fuente": "f2", "pub_desde": "1990-01-01"},
                {"id": "z:C", "fuente": "f3", "pub_desde": "1990-01-01"},
                {"id": "w:D", "fuente": "f4", "pub_desde": "1990-01-01"},
                {"id": "v:E", "fuente": "f5", "pub_desde": "1990-01-01"}])
    pares = [_par("x:A", "y:B", "f1", "f2", 0.97, 0.95),       # directo con el canónico → alias
             _par("y:B", "z:C", "f2", "f3", 0.97, 0.95),       # solo con B (estrella): C se queda
             _par("x:A", "w:D", "f1", "f4", 0.97, 0.80),       # Spearman < 0,90: lo infla un atípico
             _par("x:A", "v:E", "f1", "f5", 0.97, 0.95, anios=3.0)]  # solape < 5 años
    out = _seleccion(inv, pares)
    assert out.at["y:B", "decision"] == "alias" and out.at["y:B", "alias_de"] == "x:A"
    assert out.at["z:C", "decision"] == "queda"
    assert out.at["w:D", "decision"] == "queda"
    assert out.at["v:E", "decision"] == "queda"
    assert out.at["x:A", "regla"] == "canonico"


# --- E1 ----------------------------------------------------------------------------------------
def test_canonico_e1_orden_y_desempate():
    meta = _inv([{"id": "a", "nivel_fecha": "B", "pub_desde": "1960-01-01"},
                 {"id": "b", "nivel_fecha": "B", "pub_desde": "1960-01-01", "frecuencia": "mensual"},
                 {"id": "c", "nivel_fecha": "C", "pub_desde": "1950-06-01"}]).set_index("id", drop=False)
    # nivel B antes que C; a igualdad de nivel e historia, la mayor frecuencia; el empate es dudoso
    c, dudoso, motivo = sel.elegir_canonico(["a", "b", "c"], meta)
    assert c == "a"
    assert dudoso and "empata" in motivo and "c tiene" in motivo
    # oficial antes que derivada o copia
    meta2 = _inv([{"id": "fred:X", "pub_desde": "1960-01-01"},
                  {"id": "deriv:X", "fuente": "calculo_propio", "pub_desde": "1960-01-01"}]).set_index("id", drop=False)
    c2, dudoso2, _ = sel.elegir_canonico(["deriv:X", "fred:X"], meta2)
    assert c2 == "fred:X" and dudoso2  # empatan en nivel e historia: se decide por fuente, pero es dudoso


def test_canonico_dudoso_cuando_el_nivel_se_come_la_historia():
    meta = _inv([{"id": "ecb:H", "nivel_fecha": "A", "pub_desde": "2026-01-28"},
                 {"id": "eurostat:H", "nivel_fecha": "C", "pub_desde": "1997-03-01"}]).set_index("id", drop=False)
    c, dudoso, motivo = sel.elegir_canonico(["ecb:H", "eurostat:H"], meta)
    assert c == "ecb:H" and dudoso and "eurostat:H" in motivo
    meta_ok = _inv([{"id": "p", "nivel_fecha": "A", "pub_desde": "1990-01-01"},
                    {"id": "q", "nivel_fecha": "C", "pub_desde": "1990-06-01"}]).set_index("id", drop=False)
    assert sel.elegir_canonico(["p", "q"], meta_ok)[1] is False


# --- D9 y D4 -----------------------------------------------------------------------------------
def test_d9_estricto_y_d4_proyecciones():
    inv = _inv([{"id": "wb:ESP.SL.UEM.TOTL.ZS", "fuente": "worldbank", "frecuencia": "anual"},
                {"id": "wb:USA.SL.UEM.TOTL.ZS", "fuente": "worldbank", "frecuencia": "anual", "nivel_fecha": "C"},
                {"id": "wb:CAN.FP.CPI.TOTL.ZG", "fuente": "worldbank", "frecuencia": "anual"},
                {"id": "fred:UNRATE", "frecuencia": "mensual", "nivel_fecha": "A"},
                {"id": "imf:WEO.USA.LUR.PROY.H1", "fuente": "imf_weo", "frecuencia": "anual", "es_proyeccion": True},
                {"id": "fred:SEP", "es_proyeccion": True}])
    bmw = pd.DataFrame([
        {"serie": "wb:ESP.SL.UEM.TOTL.ZS", "fuente": "worldbank", "es_proyeccion": False, "pais": "ESP",
         "en_alcance_estricto": False, "duplica_con_mayor_frecuencia": False, "series_mayor_frecuencia": ""},
        {"serie": "wb:USA.SL.UEM.TOTL.ZS", "fuente": "worldbank", "es_proyeccion": False, "pais": "USA",
         "en_alcance_estricto": True, "duplica_con_mayor_frecuencia": True, "series_mayor_frecuencia": "fred:UNRATE"},
        {"serie": "wb:CAN.FP.CPI.TOTL.ZG", "fuente": "worldbank", "es_proyeccion": False, "pais": "CAN",
         "en_alcance_estricto": True, "duplica_con_mayor_frecuencia": False, "series_mayor_frecuencia": ""},
        {"serie": "imf:WEO.USA.LUR.PROY.H1", "fuente": "imf_weo", "es_proyeccion": True, "pais": "USA",
         "en_alcance_estricto": True, "duplica_con_mayor_frecuencia": False, "series_mayor_frecuencia": ""}])
    out = _seleccion(inv, bmw=bmw)
    assert out.at["wb:ESP.SL.UEM.TOTL.ZS", "decision"] == "fuera"
    assert "alcance estricto" in out.at["wb:ESP.SL.UEM.TOTL.ZS", "motivo"]
    assert out.at["wb:USA.SL.UEM.TOTL.ZS", "decision"] == "alias"
    assert out.at["wb:USA.SL.UEM.TOTL.ZS", "alias_de"] == "fred:UNRATE"
    assert out.at["wb:CAN.FP.CPI.TOTL.ZG", "decision"] == "queda"
    assert out.at["imf:WEO.USA.LUR.PROY.H1", "decision"] == "proyecciones"
    assert out.at["fred:SEP", "decision"] == "proyecciones"


# --- D2 ----------------------------------------------------------------------------------------
def test_no_medible_con_aviso_y_regla_conservadora():
    t = sel.tratamiento_fecha("no medible", None, "banco_mundial")
    assert t == {"aviso_fecha": "no medible", "regla_conservadora": "banco_mundial", "tramo_conservador_antes_de": None}
    assert sel.grupo_no_medible("ust_curva", "treasury_curva", ["treasury_curva"]) == "mercado_diario"
    assert sel.grupo_no_medible("worldbank", "WB") == "banco_mundial"
    assert sel.grupo_no_medible("bis", "BIS") == "macro_eurostat_bce_bis"
    assert sel.grupo_no_medible("shiller", "x") == "academicas"
    assert sel.grupo_no_medible("fred_alfred", "USREC") == "otras_fred"
    inv = _inv([{"id": "wb:USA.X", "fuente": "worldbank", "veredicto_desde_2000": "no medible", "clave_regla": "WB"}])
    out = _seleccion(inv)
    assert out.at["wb:USA.X", "decision"] == "queda"
    assert out.at["wb:USA.X", "aviso_fecha"] == "no medible"
    assert out.at["wb:USA.X", "regla_conservadora"] == "banco_mundial"


def test_no_fiable_con_tramo_conservador():
    assert sel.tratamiento_fecha("no fiable", "2014-04-02", None)["tramo_conservador_antes_de"] == "2014-04-02"
    assert sel.tratamiento_fecha("no fiable", None, None)["tramo_conservador_antes_de"] == "toda"
    inv = _inv([{"id": "fred:BAAFFM", "veredicto_desde_2000": "no fiable", "fiable_desde": "2011-04-15"},
                {"id": "fred:DBAA", "veredicto_desde_2000": "no fiable", "fiable_desde": "2014-04-02"},
                {"id": "fred:DAAA", "veredicto_desde_2000": "exacta"},
                {"id": "deriv:DBAA-DAAA", "fuente": "calculo_propio", "veredicto_desde_2000": "ver componentes"}])
    out = _seleccion(inv)
    assert out.at["fred:BAAFFM", "decision"] == "queda"
    assert out.at["fred:BAAFFM", "aviso_fecha"] == "no fiable"
    assert out.at["fred:BAAFFM", "tramo_conservador_antes_de"] == "2011-04-15"
    assert out.at["fred:DAAA", "aviso_fecha"] is None or pd.isna(out.at["fred:DAAA", "aviso_fecha"])
    # la derivada hereda el peor trato de sus componentes
    assert out.at["deriv:DBAA-DAAA", "tramo_conservador_antes_de"] == "2014-04-02"


def test_regla_con_pocas_comparaciones_pasa_a_no_medible():
    inv = _inv([{"id": "fred:Z", "veredicto_desde_2000": "fiable con margen", "clave_regla": "R"}])
    fia = pd.DataFrame({"regla": ["R"], "n_comparaciones": [5]})
    assert sel.ventana_d2(inv, fia, 20).iloc[0] == "no medible"


def test_nivel_d_fuera():
    out = _seleccion(_inv([{"id": "x:D", "nivel_fecha": "D"}]))
    assert out.at["x:D", "decision"] == "fuera"


# --- E3 y cadenas ------------------------------------------------------------------------------
def test_e3_versiones_de_eurostat():
    ids = ["eurostat:HICP_EMP.EA", "eurostat:HICP_EMP.EA20", "eurostat:prc_hicp_manr.M.RCH_A.CP00.EA",
           "eurostat:prc_hicp_minr.M.RCH_A.TOTAL.EA21", "eurostat:prc_hicp_minr.M.RCH_A.TOTAL.DE",
           "eurostat:HICP_EMP.DE", "eurostat:HICP_EMP.EU27_2020",
           "eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA20", "eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA21"]
    inv = _inv([{"id": s, "fuente": "eurostat", "nivel_fecha": "C",
                 "pub_desde": "2026-03-01" if s.endswith("EA21") else "1997-03-01"} for s in ids])
    out = _seleccion(inv)
    assert out.at["eurostat:HICP_EMP.EA", "decision"] == "queda"
    for s in ("eurostat:HICP_EMP.EA20", "eurostat:prc_hicp_manr.M.RCH_A.CP00.EA",
              "eurostat:prc_hicp_minr.M.RCH_A.TOTAL.EA21"):
        assert out.at[s, "alias_de"] == "eurostat:HICP_EMP.EA", s
    assert out.at["eurostat:prc_hicp_minr.M.RCH_A.TOTAL.DE", "alias_de"] == "eurostat:HICP_EMP.DE"
    assert out.at["eurostat:HICP_EMP.EU27_2020", "decision"] == "queda"   # la UE no es versión de la zona euro
    assert out.at["eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA21", "alias_de"] == "eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA20"
    _, sin_ea = sel.alias_e3(ids, inv.set_index("id", drop=False))
    assert sin_ea == ["ei_bssi_m_r2"]


def test_cadenas_de_alias_acaban_en_una_que_queda():
    raiz, aviso = sel.resolver_cadenas({"a": "alias", "b": "alias", "c": "queda", "d": "alias", "e": "fuera"},
                                       {"a": "b", "b": "c", "d": "e"})
    assert raiz == {"a": "c", "b": "c"}
    assert "d" in aviso and "d" not in raiz


def test_duplicada_del_catalogo_es_alias_de_su_duplicado_de():
    inv = _inv([{"id": "fred:T10YFF", "estado": "duplicada"}, {"id": "deriv:DGS10-DFF", "fuente": "calculo_propio"}])
    out = _seleccion(inv, duplicado_de={"fred:T10YFF": "deriv:DGS10-DFF"})
    assert out.at["fred:T10YFF", "decision"] == "alias"
    assert out.at["fred:T10YFF", "alias_de"] == "deriv:DGS10-DFF"
    assert out.at["fred:T10YFF", "estado"] == "duplicada"


# --- Ronda de corrección: D1 sobre E1, medida del tipo, truncados ------------------------------
def test_alias_con_d1_y_canonico_sin_d1_queda_como_historia_previa():
    inv = _inv([{"id": "ecb:H", "fuente": "bce", "nivel_fecha": "A", "pub_desde": "2026-01-28",
                 "desde_2000": False, "frecuencia": "mensual"},
                {"id": "oecd:H", "fuente": "oecd", "nivel_fecha": "C", "pub_desde": "1997-03-01",
                 "frecuencia": "mensual"}])
    out = _seleccion(inv, [_par("ecb:H", "oecd:H", "bce", "oecd", 0.99, 0.99)])
    assert out.at["oecd:H", "decision"] == "queda" and out.at["oecd:H", "rol"] == "historia_previa"
    assert out.at["oecd:H", "completa_a"] == "ecb:H"
    assert out.at["ecb:H", "decision"] == "queda"


def test_el_canonico_no_tapa_la_version_de_e3():
    ids = ["eurostat:HICP_EMP.EA", "eurostat:prc_hicp_manr.M.RCH_A.CP00.EA"]
    inv = _inv([{"id": s, "fuente": "eurostat", "nivel_fecha": "C", "pub_desde": "1997-03-01",
                 "frecuencia": "mensual"} for s in ids]
               + [{"id": "ecb:HICP", "fuente": "bce", "nivel_fecha": "A", "pub_desde": "2026-01-28",
                   "desde_2000": False, "frecuencia": "mensual"}])
    pares = [_par("ecb:HICP", "eurostat:HICP_EMP.EA", "bce", "eurostat", 0.99, 0.99),
             _par("ecb:HICP", "eurostat:prc_hicp_manr.M.RCH_A.CP00.EA", "bce", "eurostat", 0.99, 0.99)]
    out = _seleccion(inv, pares)
    assert out.at["eurostat:HICP_EMP.EA", "rol"] == "historia_previa"
    # la versión v1 sigue siendo alias, pero de la empalmada de E3, no del HICP del BCE
    assert out.at["eurostat:prc_hicp_manr.M.RCH_A.CP00.EA", "alias_de"] == "eurostat:HICP_EMP.EA"
    # fuera de ese caso nada cambia: si el canónico cumple D1, el alias se hace
    raiz = sel.historia_previa({"a": "alias", "b": "queda"}, {"a": "b"}, {"a": True, "b": True})
    assert raiz == {}


def test_base_descuento_frente_a_cmt_bloqueado():
    assert sel.medida_tipo("fred:DTB6") == "descuento" and sel.medida_tipo("fred:TB3MS") == "descuento"
    assert sel.medida_tipo("fred:DGS6MO") == "cmt_par" and sel.medida_tipo("ust:PAR.6M") == "cmt_par"
    assert sel.motivo_bloqueo("fred:DGS6MO", "fred:DTB6", fuente_a="fred_alfred", fuente_b="fred_alfred",
                              mismo_concepto=True).startswith("otra medida")
    inv = _inv([{"id": "fred:DGS6MO"}, {"id": "fred:DTB6", "pub_desde": "1958-12-10"},
                {"id": "ust:PAR.6M", "fuente": "ust_curva", "nivel_fecha": "C"}])
    pares = [_par("fred:DGS6MO", "fred:DTB6", "fred_alfred", "fred_alfred", 0.97, 0.97, mismo_concepto=True),
             _par("fred:DTB6", "ust:PAR.6M", "fred_alfred", "ust_curva", 0.997, 0.99),
             _par("fred:DGS6MO", "ust:PAR.6M", "fred_alfred", "ust_curva", 1.0, 1.0)]
    out = _seleccion(inv, pares)
    assert out.at["fred:DGS6MO", "decision"] == "queda" and out.at["fred:DTB6", "decision"] == "queda"
    assert out.at["ust:PAR.6M", "alias_de"] == "fred:DGS6MO"


def test_rendimientos_de_yahoo_frente_a_la_curva_oficial_bloqueados():
    for y, o in (("yf:^IRX", "fred:DGS3MO"), ("yf:^TNX", "fred:DGS10"), ("yf:^TNX", "ust:PAR.10Y"),
                 ("yf:^IRX", "fred:DTB3")):
        assert sel.motivo_bloqueo(y, o, fuente_a="yfinance", fuente_b="fred_alfred").startswith("otra medida")
    inv = _inv([{"id": "fred:DGS10", "pub_desde": "1962-01-03"},
                {"id": "yf:^TNX", "fuente": "yfinance", "nivel_fecha": "A", "pub_desde": "1962-01-03"}])
    out = _seleccion(inv, [_par("fred:DGS10", "yf:^TNX", "fred_alfred", "yfinance", 0.996, 0.99)])
    assert (out["decision"] == "queda").all()


def test_truncado_frente_a_deslistado():
    base = {"proveedor": "yahoo", "clase": "accion", "bucket": None, "en_universo": False, "volumen_mediano": 1e5,
            "posible_frontera": None, "hasta": "2026-08-14"}
    pre = pd.DataFrame([{**base, "ticker": "TRUNC", "desde": "2026-08-14", "sesiones": 1, "deslistado": True},
                        {**base, "ticker": "SALIDO", "desde": "1990-01-02", "hasta": "2017-03-20", "sesiones": 6800,
                         "deslistado": True}])
    out = sel.seleccionar_precios(pre, pd.DataFrame(columns=["tipo", "id", "miembros", "inicios", "corr_min"]),
                                  sospechosas={"SALIDO"}).set_index("id")
    assert out.at["TRUNC", "decision"] == "fuera" and bool(out.at["TRUNC", "truncado"])
    assert not bool(out.at["TRUNC", "deslistado"])
    assert out.at["SALIDO", "decision"] == "queda" and bool(out.at["SALIDO", "deslistado"])
    assert out.at["SALIDO", "aviso"] == sel.AVISO_SOSPECHOSA and out.at["SALIDO", "frontera"] == "tema3"
    assert "limitación declarada (F3)" in out.at["SALIDO", "aviso"]
    vacio = pd.DataFrame(columns=["id", "clase", "capa", "bucket", "tickers", "invertible_minorista_ue"])
    series = pd.DataFrame(columns=["id", "estado", "decision", "fuente"])
    bmw = pd.DataFrame(columns=["fuente", "en_alcance_estricto", "indicador"])
    d = sel.tabla_descargas_3b(series, out.reset_index(), vacio, pd.DataFrame({"id_universo": []}), bmw)
    tipos = d.groupby("id")["tipo"].apply(set)
    assert tipos["TRUNC"] == {"redescarga"}
    assert tipos["SALIDO"] == {"deslistado", "serie_sospechosa"}
    # F3: lo que dependía de Q1 no se descarga (limitación declarada); el truncado sí
    est = d.set_index(["id", "tipo"])
    assert est.loc[("SALIDO", "deslistado"), "estado"] == "limitacion_declarada"
    assert est.loc[("SALIDO", "serie_sospechosa"), "prioridad"] == "no se descarga"
    assert est.loc[("TRUNC", "redescarga"), "estado"] == "pendiente"
    assert "imf_weo:edicion:2026-04" in set(d["id"])
    assert (d.loc[d["tipo"] == "ediciones", "depende_de"] != "").all()


def test_serie_sospechosa_con_la_regla_de_b2():
    eda = pd.DataFrame({"ticker": ["A", "B", "C"], "sesiones": [100, 100, 100], "saltos_sin_split": [21, 0, 5],
                        "cierre_repetido": [0, 41, 10]})
    assert sel.series_sospechosas(eda) == {"A", "B"}
    assert sel.series_sospechosas(eda.assign(serie_sospechosa=[False, False, True])) == {"C"}


def test_factores_academicos_de_frecuencias_distintas_no_son_alias():
    inv = _inv([{"id": "ff:F3D.Mkt-RF", "fuente": "ken_french", "nivel_fecha": "C", "pub_desde": "1963-07-01"},
                {"id": "ff:F3M.Mkt-RF", "fuente": "ken_french", "nivel_fecha": "C", "pub_desde": "1963-07-01",
                 "frecuencia": "mensual"}])
    conc = pd.DataFrame([{"grupo": 37, "concepto": "ff_Mkt-RF", "pais": "USA", "miembros": "ff:F3D.Mkt-RF; ff:F3M.Mkt-RF",
                          "n_pares": 1, "n_pares_medidos": 1, "corr_min": 0.99, "solape_min_anios_par": 60}])
    out = _seleccion(inv, conc=conc)
    assert (out["decision"] == "queda").all()


def test_lista_curada_en_una_linea_sin_vacios(tmp_path):
    series = pd.DataFrame([{"id": "yf:^GSPC", **{c: None for c in sel.CAMPOS_YAML_SERIES}, "decision": "queda",
                            "canonico_dudoso": False}])
    precios = pd.DataFrame([{"id": "SPY", **{c: None for c in sel.CAMPOS_YAML_PRECIOS}, "decision": "queda",
                             "desde_2000": True, "truncado": False}])
    ruta = sel.escribir_yaml(series, precios, tmp_path / "l.yaml")
    import yaml
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("#") and "&" not in texto
    d = yaml.safe_load(texto)
    assert d["series"]["yf:^GSPC"] == {"decision": "queda"}
    assert d["precios"]["SPY"] == {"decision": "queda", "desde_2000": True}
    assert len([x for x in texto.splitlines() if x.startswith("  ")]) == 2


# --- Tickers (D10 abierta) ---------------------------------------------------------------------
def test_ningun_ticker_sale_por_fecha_de_inicio():
    pre = pd.DataFrame([
        {"ticker": "VIEJO", "proveedor": "yahoo", "clase": "etf", "bucket": "rv_eeuu", "en_universo": True,
         "desde": "1993-01-29", "hasta": "2026-10-13", "sesiones": 8000, "volumen_mediano": 1e6, "deslistado": False,
         "posible_frontera": None},
        {"ticker": "NUEVO", "proveedor": "yahoo", "clase": "etf", "bucket": "cripto", "en_universo": True,
         "desde": "2024-07-23", "hasta": "2026-10-13", "sesiones": 560, "volumen_mediano": 0.0, "deslistado": False,
         "posible_frontera": None},
        {"ticker": "^IDX", "proveedor": "yahoo", "clase": "indice", "bucket": None, "en_universo": False,
         "desde": "2015-01-02", "hasta": "2026-10-13", "sesiones": 2900, "volumen_mediano": 0.0, "deslistado": True,
         "posible_frontera": None},
        {"ticker": "VACIO", "proveedor": "yahoo", "clase": None, "bucket": None, "en_universo": False,
         "desde": "2026-08-14", "hasta": "2026-08-14", "sesiones": 1, "volumen_mediano": 10.0, "deslistado": True,
         "posible_frontera": None}])
    etf = pd.DataFrame([{"tipo": "ucits", "id": "VIEJO~UCITS.L", "miembros": "VIEJO; UCITS.L",
                         "inicios": "1993-01-29; 2010-09-15", "corr_min": 0.91}])
    out = sel.seleccionar_precios(pre, etf).set_index("id")
    assert out.at["VIEJO", "decision"] == "queda" and out.at["NUEVO", "decision"] == "queda"
    assert out.at["^IDX", "decision"] == "queda"
    assert out.at["VACIO", "decision"] == "fuera"
    assert bool(out.at["VIEJO", "desde_2000"]) and not bool(out.at["NUEVO", "desde_2016"])
    assert bool(out.at["^IDX", "desde_2016"]) and not bool(out.at["^IDX", "desde_2007"])
    assert not bool(out.at["^IDX", "volumen_aplica"]) and not bool(out.at["NUEVO", "con_volumen"])
    assert bool(out.at["VIEJO", "con_volumen"]) and bool(out.at["^IDX", "deslistado"])


def test_alias_etf_grupos_y_ucits():
    etf = pd.DataFrame([
        {"tipo": "grupo", "id": "g1", "miembros": "IWD; JAVA", "inicios": "2000-05-26; 2021-10-05", "corr_min": 0.981},
        {"tipo": "grupo", "id": "g9", "miembros": "A; B", "inicios": "2000-01-01; 2001-01-01", "corr_min": 0.97},
        {"tipo": "ucits", "id": "SPY~CSPX.L", "miembros": "SPY; CSPX.L", "inicios": "1993-01-29; 2010-09-15",
         "corr_min": 0.91},
        {"tipo": "bucket", "id": "rv", "miembros": "SPY; QQQ", "inicios": "1993-01-29; 1999-03-10", "corr_min": 0.99}])
    a = sel.alias_etf(etf)
    assert a["JAVA"][0] == "IWD"
    assert a["CSPX.L"] == ("SPY", "ucits")
    assert "B" not in a and "QQQ" not in a
    # el alias de grupo exige el mismo bucket (QUAL, factor, no es alias de SPY); el UCITS no
    etf2 = pd.DataFrame([
        {"tipo": "grupo", "id": "g2", "miembros": "SPY; QUAL", "inicios": "1993-01-29; 2013-07-18", "corr_min": 0.98},
        {"tipo": "ucits", "id": "SPY~CSPX.L", "miembros": "SPY; CSPX.L", "inicios": "1993-01-29; 2010-09-15",
         "corr_min": 0.91}])
    a2 = sel.alias_etf(etf2, buckets={"SPY": "rv_eeuu", "QUAL": "factor_eeuu", "CSPX.L": "rv_europa"})
    assert "QUAL" not in a2 and a2["CSPX.L"] == ("SPY", "ucits")


# --- Datos reales ------------------------------------------------------------------------------
@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series().exists(), reason="falta la base real (construir-base --sin-red)")
def test_lista_curada_sobre_las_tablas_reales():
    tablas = resultados_dir("mercados_series") / "tablas"
    s = sel.calcular(tablas)
    series, precios = s["series"], s["precios"]
    inv = pd.read_csv(tablas / "inventario_series.csv")
    assert set(series["id"]) == set(inv["id"]) and series["decision"].isin(sel.DECISIONES).all()
    dec = series.set_index("id")["decision"]
    alias = series[series["decision"] == "alias"]
    assert alias["alias_de"].notna().all()
    assert (alias["alias_de"].map(dec) == "queda").all()
    dentro = series[series["decision"].isin(["queda", "alias"])]
    assert not (dentro["nivel_fecha"] == "D").any()
    # D10 abierta: fuera solo por falta de datos
    fuera = precios[precios["decision"] == "fuera"]
    assert (fuera["sesiones"] < sel.MIN_SESIONES).all()
    # AT (ETF de ARCX desde 2026-09-17, no Alltel) queda con el aviso de ticker reutilizado; GR (fondo) también
    p = precios.set_index("id")
    for t in ("AT", "GR", "DWD"):
        assert p.at[t, "decision"] == "queda" and sel.AVISO_REUTILIZADO in str(p.at[t, "aviso"]), t
    assert sel.AVISO_REUTILIZADO not in str(p.at["AAPL", "aviso"])
    # sin valores: ninguna columna numérica de las tablas es un valor de serie
    assert not {"valor", "close", "open"} & (set(series.columns) | set(precios.columns))


# --- Decisiones de cierre: F3 y F4 --------------------------------------------------------------
def test_f3_solo_yahoo_limitacion_declarada():
    d3b = pd.DataFrame([
        sel._fila3b("DWD", "deslistado", "yahoo", "media", "deslistado", depende_de=sel.Q1),
        sel._fila3b("MCIC", "serie_sospechosa", "yahoo", "media", "sospechosa", depende_de="Q1 (CRSP/PERMNO)"),
        sel._fila3b("yf:^V2TX", "precios", "yahoo", "media", "universo sin fichero"),
        sel._fila3b("yf:CSPX.MI", "precios", "yahoo", "alta", "universo sin fichero (UCITS europeo)"),
        sel._fila3b("refresco:fred_alfred", "refresco", "fred_alfred", "alta", "refresco")])
    out = sel.aplicar_f3(d3b).set_index("id")
    for s in ("DWD", "MCIC", "yf:^V2TX"):
        assert out.at[s, "estado"] == "limitacion_declarada" and out.at[s, "prioridad"] == "no se descarga"
        assert out.at[s, "motivo"].startswith(sel.MOTIVO_F3)
    for s in ("yf:CSPX.MI", "refresco:fred_alfred"):
        assert out.at[s, "estado"] == "pendiente" and out.at[s, "prioridad"] in ("alta", "media", "baja")


def test_f4_empates_resueltos_a_mano():
    inv = _inv([
        {"id": "ecb:DFR", "fuente": "bce", "nivel_fecha": "C", "pub_desde": "1999-01-01"},
        {"id": "ecb:MRO", "fuente": "bce", "nivel_fecha": "C", "pub_desde": "1999-01-01"},
        {"id": "bis:WS_CBPOL.M.XM", "fuente": "bis", "nivel_fecha": "C", "pub_desde": "1999-02-01",
         "frecuencia": "mensual"},
        {"id": "shiller:P", "fuente": "shiller", "nivel_fecha": "C", "pub_desde": "1871-03-01", "frecuencia": "mensual"},
        {"id": "datahub:SP500_MENSUAL", "fuente": "datahub", "nivel_fecha": "C", "pub_desde": "1871-03-01",
         "frecuencia": "mensual"},
        {"id": "ff:F3D.Mkt-RF", "fuente": "ken_french", "nivel_fecha": "C", "pub_desde": "1963-07-01"},
        {"id": "ff:F3M.Mkt-RF", "fuente": "ken_french", "nivel_fecha": "C", "pub_desde": "1963-07-01",
         "frecuencia": "mensual"},
        {"id": "x:A", "fuente": "f1", "nivel_fecha": "A", "pub_desde": "2000-01-01"},
        {"id": "y:B", "fuente": "f2", "nivel_fecha": "C", "pub_desde": "1950-01-01"}])
    conc = pd.DataFrame([
        {"grupo": 4, "concepto": "tipo_oficial", "pais": "EA", "miembros": "bis:WS_CBPOL.M.XM; ecb:DFR; ecb:MRO",
         "n_pares": 3, "n_pares_medidos": 3, "corr_min": 0.86, "solape_min_anios_par": 27},
        {"grupo": 37, "concepto": "ff_Mkt-RF", "pais": "USA", "miembros": "ff:F3D.Mkt-RF; ff:F3M.Mkt-RF",
         "n_pares": 1, "n_pares_medidos": 1, "corr_min": 0.99, "solape_min_anios_par": 60}])
    pares = [_par("ecb:DFR", "ecb:MRO", "bce", "bce", 0.99, 0.99, mismo_concepto=True),
             _par("datahub:SP500_MENSUAL", "shiller:P", "datahub", "shiller", 1.0, 1.0, mismo_concepto=True),
             _par("x:A", "y:B", "f1", "f2", 0.99, 0.99)]
    out = _seleccion(inv, pares, conc=conc)
    for s in ("ecb:DFR", "ecb:MRO", "bis:WS_CBPOL.M.XM", "ff:F3M.Mkt-RF"):
        assert out.at[s, "decision"] == "queda" and out.at[s, "rol"] == "unica", s
        assert not bool(out.at[s, "canonico_dudoso"]), s
    assert out.at["datahub:SP500_MENSUAL", "alias_de"] == "shiller:P"
    assert not bool(out.at["datahub:SP500_MENSUAL", "canonico_dudoso"]) and not bool(out.at["shiller:P", "canonico_dudoso"])
    assert not bool(out.at["ff:F3D.Mkt-RF", "canonico_dudoso"])
    # el resto de dudosos: se aceptan con E1 y se marcan
    assert bool(out.at["x:A", "canonico_dudoso"])
    assert out.at["x:A", "motivo_dudoso"].startswith(sel.NOTA_DUDOSO_F4)


# --- Paso 3b-1: tickers reutilizados del S&P 500 ------------------------------------------------
def _tramos(filas: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{"ticker": t, "alta": pd.Timestamp(a), "baja": pd.Timestamp(b) if b else pd.NaT}
                         for t, a, b in filas])


def _pre_yahoo(filas: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{"ticker": t, "proveedor": "yahoo", "desde": d, "hasta": h} for t, d, h in filas])


def test_t3b_ticker_reutilizado_sin_solape_o_de_otra_clase():
    """AT: ETF de 2026 (el miembro, Alltel, salió en 2007): reutilizado. GR: fondo que solapa en fechas con
    Goodrich: reutilizado por la clase. MULTI: dos tramos y el fichero solapa con uno: no. BRK.B → BRK-B."""
    tramos = _tramos([("AT", "1996-01-02", "2007-11-19"), ("GR", "1996-01-02", "2012-07-27"),
                      ("MULTI", "1996-01-02", "2000-01-03"), ("MULTI", "2015-01-02", None),
                      ("BRK.B", "2010-02-16", None), ("SINF", "1996-01-02", "1999-01-04")])
    pre = _pre_yahoo([("AT", "2026-09-17", "2026-11-18"), ("GR", "2001-01-02", "2018-02-22"),
                      ("MULTI", "2016-01-04", "2026-11-18"), ("BRK-B", "1996-05-09", "2026-11-18")])
    cob = sel.cobertura_tramos_sp500(tramos, pre, {"AT": "etf", "GR": "fondo", "MULTI": "accion"},
                                     corte="2026-11-13")
    r = sel.tickers_reutilizados(cob)
    assert set(r) == {"AT", "GR"} and r["AT"].startswith("fichero 2026-09-17 a 2026-11-18")
    # truncado (LEG: la misma empresa, deslistada en 2026) y del universo (GLD, núcleo): sin marca
    t2 = _tramos([("LEG", "1999-10-18", "2021-12-20"), ("GLD", "1996-01-02", "1997-05-06")])
    p2 = _pre_yahoo([("LEG", "2026-08-26", "2026-08-26"), ("GLD", "2004-11-18", "2026-11-18")]).assign(
        sesiones=[1, 5535], en_universo=[False, True])
    assert sel.tickers_reutilizados(sel.cobertura_tramos_sp500(t2, p2, {"GLD": "etf"})) == {}
    c = cob.set_index(["ticker", "alta"])
    assert not c.loc[("MULTI", pd.Timestamp("1996-01-02")), "solapa"]
    assert not c.loc[("MULTI", pd.Timestamp("1996-01-02")), "reutilizado"]
    assert c.loc[("BRK.B", pd.Timestamp("2010-02-16")), "ticker_yahoo"] == "BRK-B"
    # tramo abierto: hasta el corte (incluido); BRK-B lo cubre entero
    brk = c.loc[("BRK.B", pd.Timestamp("2010-02-16"))]
    assert brk["dias_cubiertos"] == brk["dias_tramo"] == (pd.Timestamp("2026-11-14") - pd.Timestamp("2010-02-16")).days
    res = sel.resumen_cobertura_sp500(cob).set_index("metrica")["valor"]
    assert res["tramos"] == 6 and res["tramos_sin_fichero"] == 1 and res["tramos_ticker_reutilizado"] == 2
    assert res["tramos_con_fichero_sin_solape"] == 2      # AT y el primer tramo de MULTI
    assert res["tickers_reutilizados"] == 2 and 0 < res["pct_dias_tramo_cubiertos"] < 100


def test_t3b_reutilizado_queda_con_aviso_y_motivo_propio_en_el_3b():
    base = {"proveedor": "yahoo", "clase": "accion", "bucket": None, "en_universo": False, "volumen_mediano": 1e5,
            "posible_frontera": None}
    pre = pd.DataFrame([{**base, "ticker": "DWD", "desde": "2013-12-16", "hasta": "2017-03-20", "sesiones": 451,
                         "deslistado": True},
                        {**base, "ticker": "SALIDO", "desde": "1990-01-02", "hasta": "2017-03-20", "sesiones": 6800,
                         "deslistado": True}])
    etf = pd.DataFrame(columns=["tipo", "id", "miembros", "inicios", "corr_min"])
    out = sel.seleccionar_precios(pre, etf, sospechosas={"DWD"},
                                  reutilizados={"DWD": "fichero 2013-12-16 a 2017-03-20"}).set_index("id")
    assert out.at["DWD", "decision"] == "queda" and not bool(out.at["DWD", "truncado"])
    assert out.at["DWD", "aviso"] == f"{sel.AVISO_SOSPECHOSA}; {sel.AVISO_REUTILIZADO}"
    assert sel.AVISO_REUTILIZADO in out.at["DWD", "motivo"]
    vacio = pd.DataFrame(columns=["id", "clase", "capa", "bucket", "tickers", "invertible_minorista_ue"])
    series = pd.DataFrame(columns=["id", "estado", "decision", "fuente"])
    bmw = pd.DataFrame(columns=["fuente", "en_alcance_estricto", "indicador"])
    d = sel.tabla_descargas_3b(series, out.reset_index(), vacio, pd.DataFrame({"id_universo": []}), bmw)
    d = d.set_index(["id", "tipo"])
    assert "historia completa y salida" not in d.at[("DWD", "deslistado"), "motivo"]
    assert sel.AVISO_REUTILIZADO in d.at[("DWD", "deslistado"), "motivo"]
    assert "historia completa y salida" in d.at[("SALIDO", "deslistado"), "motivo"]
    assert ("DWD", "serie_sospechosa") in d.index      # el aviso compuesto sigue dando su fila de sospechosa
