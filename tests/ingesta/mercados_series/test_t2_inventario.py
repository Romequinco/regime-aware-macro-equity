"""Paso 2 de la descarga completa del Tema 1 · ``inventario``: reglas del nivel de fecha, historia desde 2000,
proyecciones, veredicto de las reglas C, rutas del BoE y medidas de precios.

Las pruebas unitarias usan tablas pequeñas inventadas (sin red ni corpus). La última lleva
``@pytest.mark.datos`` y se salta si falta ``<corpus>/mercados_series/series/base_series.parquet``.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ingesta.comun.esquema import FichaFuente
from ingesta.mercados_series import almacen
from ingesta.mercados_series import inventario as inv

PUBS = {"publicadores": {"pub_ok": {"verificado": True}, "pub_no": {"verificado": False}}}
LAGS = {"LAG_OK": {"verificado": True}, "LAG_NO": {"verificado": False}}


def _cat() -> dict[str, dict]:
    base = {"frecuencia": "mensual", "unidad": "%", "estado": "activa", "revisable": False}
    return {
        "fred:EXACTA": {**base, "nombre": "exacta", "fuente": "fred_alfred", "metodo": "vintage_exacto",
                        "verificado": False},
        "fred:REGLA_B": {**base, "nombre": "regla verificada", "fuente": "fred_alfred", "metodo": "calendario",
                         "publicador": "pub_ok", "verificado": False},
        "fred:REGLA_C": {**base, "nombre": "regla sin verificar", "fuente": "fred_alfred", "metodo": "lag_fijo",
                         "lag_clave": "LAG_NO", "verificado": False},
        "deriv:B-C": {**base, "nombre": "derivada", "fuente": "calculo_propio", "metodo": "derivada",
                      "componentes": ["fred:REGLA_B", "fred:REGLA_C"], "verificado": False},
        "fred:SEP": {**base, "nombre": "proyección SEP", "fuente": "fred_alfred", "metodo": "vintage_exacto",
                     "proyecciones": "conservar", "verificado": False},
    }


def _filas(serie: str, refs: list[str], pubs: list[str], metodo: str, vintages: list[str] | None = None,
           nota: str | None = None) -> pd.DataFrame:
    return pd.DataFrame({"serie": serie, "fecha_referencia": pd.to_datetime(refs),
                         "fecha_publicacion": pd.to_datetime(pubs),
                         "vintage": vintages or [p[:10] for p in pubs], "metodo_publicacion": metodo,
                         "nota": nota, "divisa": None, "con_valor": True})


def _base() -> pd.DataFrame:
    return pd.concat([
        # referencia antigua, pero se publica por primera vez en 2005: NO tiene historia desde 2000 (D1)
        _filas("fred:EXACTA", ["1990-01-01", "1990-02-01"], ["2005-03-01", "2005-03-01"], "vintage_exacto"),
        # primera publicación el 2001-01-02 (el corte, incluido): SÍ
        _filas("fred:REGLA_B", ["2000-11-01", "2000-12-01", "2001-01-01"],
               ["2001-01-02", "2001-01-02", "2001-02-01"], "calendario"),
        _filas("fred:REGLA_C", ["1999-01-01", "1999-02-01"], ["1999-02-02", "1999-03-02"], "lag_fijo"),
        _filas("deriv:B-C", ["2001-01-01"], ["2001-02-01"], "derivada"),
        # cada vintage (un SEP) da años futuros: fecha_referencia > vintage
        _filas("fred:SEP", ["2027-01-01", "2028-01-01"], ["2027-01-01", "2028-01-01"], "vintage_exacto",
               vintages=["2025-12-10", "2025-12-10"]),
    ], ignore_index=True)


# --- Nivel de la fecha (D2) ---------------------------------------------------------------------
def test_t2_nivel_fecha_reglas():
    assert inv.nivel_fecha("vintage_exacto", False) == "A"
    assert inv.nivel_fecha("cierre_mercado", False) == "A"
    assert inv.nivel_fecha("lag_fijo", True) == "B"
    assert inv.nivel_fecha("calendario", False) == "C"
    assert inv.nivel_fecha("fichero", False, tramo_fiable=True) == "A"   # contrastada con ALFRED
    assert inv.nivel_fecha("lag_fijo", True, tramo_fiable=True) == "A"
    assert inv.nivel_fecha(None, False, tramo_fiable=True) == "D"
    assert inv.nivel_fecha(None, True) == "D"
    assert inv.nivel_fecha("derivada", False, niveles_componentes=["A", "C", "B"]) == "C"
    assert inv.nivel_fecha("derivada", False, niveles_componentes=[]) == "D"


def test_t2_regla_verificada_en_entrada_publicador_o_lag():
    assert inv.regla_verificada({"verificado": True}, PUBS["publicadores"], LAGS)
    assert inv.regla_verificada({"verificado": False, "publicador": "pub_ok"}, PUBS["publicadores"], LAGS)
    assert inv.regla_verificada({"verificado": False, "lag_clave": "LAG_OK"}, PUBS["publicadores"], LAGS)
    assert not inv.regla_verificada({"verificado": False, "publicador": "pub_no", "lag_clave": "LAG_NO"},
                                    PUBS["publicadores"], LAGS)


def test_t2_inventario_series_niveles_historia_y_proyeccion():
    cat = _cat()
    med = inv.medidas_series(_base(), {s: e["frecuencia"] for s, e in cat.items()})
    t = inv.tabla_inventario_series(med, cat, PUBS, LAGS).set_index("id")
    assert t["nivel_fecha"].to_dict() == {"deriv:B-C": "C", "fred:EXACTA": "A", "fred:REGLA_B": "B",
                                          "fred:REGLA_C": "C", "fred:SEP": "A"}
    # D1: por la primera publicación, no por la referencia
    assert not t.loc["fred:EXACTA", "desde_2000"] and t.loc["fred:EXACTA", "ref_desde"] == "1990-01-01"
    assert t.loc["fred:REGLA_B", "desde_2000"] and t.loc["fred:REGLA_C", "desde_2000"]
    assert t.loc["fred:REGLA_B", "pub_desde"] == "2001-01-02"
    # D4
    assert t.loc["fred:SEP", "es_proyeccion"] and t.loc["fred:SEP", "pct_ref_tras_vintage"] == 100.0
    assert not t["es_proyeccion"].drop("fred:SEP").any()
    assert t.loc["fred:REGLA_C", "clave_regla"] == "LAG_NO" and t.loc["fred:REGLA_B", "clave_regla"] == "pub_ok"
    assert list(t.reset_index().columns) == list(inv.COLUMNAS_SERIES_INV)


def test_t2_es_proyeccion_por_catalogo_id_o_medida():
    assert inv.es_proyeccion("fred:X", {"proyecciones": "conservar"}, 0.0)
    assert inv.es_proyeccion("imf:WEO.DEU.PCPIPCH.PROY.H3", {}, 0.0)
    assert inv.es_proyeccion("fred:X", {}, 60.0)
    assert not inv.es_proyeccion("fred:X", {"proyecciones": "recortar"}, 10.0)
    assert not inv.es_proyeccion("fred:X", {}, np.nan)


def test_t2_frontera_y_pais():
    assert inv.posible_frontera("ecb:ESTR", {"fuente": "bce"}) == "tema2"
    assert inv.posible_frontera("fred:NFCI", {"fuente": "fred_alfred", "grupo": "estres_financiero"}) == "tema2"
    assert inv.posible_frontera("yf:^SKEW", {"fuente": "yfinance"}) == "tema4"
    assert inv.posible_frontera("x:Y", {"fuente": "eurostat", "nombre": "Indicador de sentimiento"}) == "tema4"
    assert inv.posible_frontera("fred:DGS10", {"fuente": "fred_alfred", "nombre": "Tesoro"}) is None
    assert inv.posible_frontera("fred:UMCSENT", {"fuente": "fred_alfred", "nombre": "Michigan"}) == "tema4"
    assert inv.posible_frontera("x:Z", {"fuente": "oecd", "nombre": "Consumer Sentiment"}) == "tema4"
    assert inv.posible_frontera("x:Z", {"fuente": "oecd", "nombre": "Confianza del consumidor"}) == "tema4"
    assert inv.pais_zona("wb:USA.SL.UEM.TOTL.ZS", "worldbank") == "USA"
    assert inv.pais_zona("imf:WEO.DEU.PCPIPCH.PROY.H0", "imf_weo") == "DEU"
    assert inv.pais_zona("bis:WS_CBPOL.M.CA", "bis") == "CA"
    assert inv.pais_zona("bis:WS_EER.M.R.B.FR", "bis") == "FR"
    assert inv.pais_zona("ecb:EXR.D.USD.EUR", "bce") is None
    assert inv.pais_zona("deriv:A-B", "calculo_propio", ["USA", "USA"]) == "USA"


def test_t2_huecos_desde_2000_mensual():
    refs = pd.to_datetime(["1999-12-01", "2000-01-01", "2000-02-01", "2000-04-01"])   # falta marzo
    b = pd.DataFrame({"serie": "s", "fecha_referencia": refs, "con_valor": True})
    assert inv.huecos_desde_2000(b, {"s": "mensual"})["s"] == 25.0


# --- Fiabilidad del nivel C ---------------------------------------------------------------------
def test_t2_veredicto_regla():
    assert inv.veredicto_regla(0, None, None, None)[0] == "no medible"
    assert inv.veredicto_regla(100, 6.0, 0.0, 3.0)[0] == "no fiable"          # adelanta en > 5 %
    assert inv.veredicto_regla(100, 4.0, -3.0, 3.0)[0] == "no fiable"         # p05 adelanta > 1 día
    assert inv.veredicto_regla(100, 2.0, 0.0, 3.0)[0] == "fiable con margen"  # adelantos esporádicos
    assert inv.veredicto_regla(100, 0.0, 5.0, 20.0)[0] == "fiable con margen"  # conservadora
    assert inv.veredicto_regla(100, 0.0, 0.0, 2.0)[0] == "fiable"


def test_t2_veredicto_tope_de_dias_para_con_margen():
    assert inv.veredicto_regla(100, 2.0, 0.0, 3.0, adelanto_max=inv.MAX_ADELANTO_MARGEN)[0] == "fiable con margen"
    v, motivo = inv.veredicto_regla(100, 2.0, 0.0, 3.0, adelanto_max=inv.MAX_ADELANTO_MARGEN + 1)
    assert v == "no fiable" and "adelanta hasta" in motivo


def test_t2_tabla_fiabilidad_combina_periodos_y_agregados():
    invent = pd.DataFrame({"id": ["a", "b", "c"], "clave_regla": ["R1", "R1", "R2"], "nivel_fecha": ["C", "C", "C"]})
    por_periodo = pd.DataFrame({"regla": "R1", "serie": "a", "origen": "alfred_previa",
                                "desvio_dias": [-2] + [3] * 9})
    agregados = pd.DataFrame({"regla": ["R1"], "serie": ["b"], "n": [10], "n_adelanta": [0],
                              "adelanto_max": [0.0], "desvio_mediano": [5.0]})
    f = inv.tabla_fiabilidad(invent, {}, por_periodo, agregados, {"publicadores": {}}, {"R1": {"verificado": False}})
    f = f.set_index("regla")
    assert f.loc["R1", "n_comparaciones"] == 20 and f.loc["R1", "pct_adelanta"] == 5.0
    assert f.loc["R1", "pct_retrasa"] == 90.0 and f.loc["R1", "adelanto_max_dias"] == 2.0
    assert f.loc["R1", "n_series_c"] == 2 and f.loc["R1", "nivel"] == "C"
    assert f.loc["R2", "veredicto"] == "no medible"


# --- ALFRED con regla previa, contrastadas y signo del desvío -------------------------------------
PREVIA = {"metodo": "lag_fijo", "lag_clave": "LAG_NO", "lag": "10D", "fin_periodo": "mes", "lag_habiles": None,
          "lag_n_habiles": None, "lag_tramos": None, "primer_vintage": "2020-01-15"}


def _cat_alfred() -> dict[str, dict]:
    base = {"alias": [], "frecuencia": "mensual", "unidad": "%", "estado": "activa", "revisable": True,
            "fuente": "fred_alfred", "verificado": False}
    return {
        "fred:PREVIA": {**base, "nombre": "con regla previa", "metodo": "vintage_exacto",
                        "regla_previa_alfred": dict(PREVIA)},
        "fred:CONTRA_99": {**base, "nombre": "contrastada desde 1996", "metodo": "lag_fijo", "lag_clave": "LAG_NO"},
        "fred:CONTRA_14": {**base, "nombre": "contrastada desde 2014", "metodo": "lag_fijo", "lag_clave": "LAG_NO"},
    }


def _base_previa() -> pd.DataFrame:
    nota_previa = "anterior a ALFRED: valor del primer vintage (2020-01-15)"
    return pd.concat([
        # antes del primer vintage: regla previa (lag_fijo), publicada antes de 2001
        _filas("fred:PREVIA", ["1999-10-01", "1999-11-01"], ["1999-11-10", "1999-12-10"], "lag_fijo",
               nota=nota_previa),
        # primer vintage (relleno: no cuenta) y dos periodos publicados después
        _filas("fred:PREVIA", ["2019-12-01", "2020-01-01", "2020-02-01"],
               ["2020-01-15", "2020-02-05", "2020-03-20"], "vintage_exacto"),
    ], ignore_index=True)


def test_t2_alfred_con_regla_previa_desde_2000_frente_a_exacto():
    cat = _cat_alfred()
    med = inv.medidas_series(_base_previa(), {"fred:PREVIA": "mensual"})
    t = inv.tabla_inventario_series(med, cat, PUBS, LAGS).set_index("id")
    f = t.loc["fred:PREVIA"]
    assert f["nivel_fecha"] == "A" and f["exacto_desde"] == "2020-01-15" and f["fiable_desde"] == "2020-01-15"
    assert f["clave_regla"] == "LAG_NO" and f["regla_previa"] == "LAG_NO"
    assert f["desde_2000"] and not f["desde_2000_exacto"]          # D1 sí; fecha exacta desde 2000, no


def test_t2_signo_del_desvio_previa_y_ediciones():
    cat = _cat_alfred()
    d = inv.comparaciones_previa(_base_previa(), cat)
    # regla: fin de mes + 10 días. Enero: 10-feb frente a 5-feb (retrasa +5); febrero: 10-mar frente a 20-mar
    # (la regla ADELANTA: −10). El periodo del primer vintage no cuenta.
    assert d["desvio_dias"].tolist() == [5, -10] and set(d["regla"]) == {"LAG_NO"}
    ed = {"fred:FICH": {"alias": [], "metodo": "fichero", "lag_clave": "FF", "lag": "45D", "fin_periodo": "mes"}}
    b = _filas("fred:FICH", ["2026-07-01", "2026-08-01"], ["2026-10-30", "2026-10-30"], "fichero",
               vintages=["2026-10", "2026-10"], nota="edición 2026-10: periodo nuevo")
    e = inv.comparaciones_ediciones(b, ed)
    # el periodo nuevo más reciente (agosto): regla 31-ago + 45 = 15-oct, edición 30-oct → adelanta −15
    assert e["desvio_dias"].tolist() == [-15]


def test_t2_contrastada_veredicto_solo_antes_de_contrastada_desde():
    cat = _cat_alfred()
    b = pd.concat([_filas("fred:CONTRA_99", ["1996-01-01", "2010-01-01"], ["1996-02-11", "2010-02-11"], "lag_fijo"),
                   _filas("fred:CONTRA_14", ["1996-01-01", "2010-01-01"], ["1996-02-11", "2010-02-11"], "lag_fijo")],
                  ignore_index=True)
    medida = pd.DataFrame({"serie": ["fred:CONTRA_99", "fred:CONTRA_14"], "primera_vintage": ["1996-12-03", "2014-01-27"],
                           "error": [None, None], "equivalente": [None, None]})
    contr = inv.contrastadas_desde(medida)
    t = inv.tabla_inventario_series(inv.medidas_series(b, {}), cat, PUBS, LAGS, contr)
    # la regla adelanta mucho (no fiable) …
    por_periodo = pd.DataFrame({"regla": "LAG_NO", "serie": "otra", "origen": "alfred_previa",
                                "desvio_dias": [-20] * 5 + [3] * 5})
    f = inv.tabla_fiabilidad(t, cat, por_periodo, inv.agregados_alfred_medida(None, cat), PUBS, LAGS)
    t = inv.anotar_veredictos(t, f).set_index("id")
    assert (t["nivel_fecha"] == "A").all() and (t["clave_regla"] == "LAG_NO").all()
    assert t.loc["fred:CONTRA_99", "contrastada_desde"] == "1996-12-03"
    # … pero solo cuenta antes de contrastada_desde: la de 1996 no tiene riesgo en la ventana desde 2000
    assert t.loc["fred:CONTRA_99", "desde_2000_exacto"] and t.loc["fred:CONTRA_99", "veredicto_desde_2000"] == "sin riesgo"
    assert not t.loc["fred:CONTRA_14", "desde_2000_exacto"]
    assert t.loc["fred:CONTRA_14", "veredicto_desde_2000"] == "no fiable"
    r = f.set_index("regla").loc["LAG_NO"]
    assert r["veredicto"] == "no fiable" and r["n_series"] == 2 and r["n_series_sin_riesgo_2000"] == 1
    assert r["veredicto_desde_2000"] == "no fiable"
    f1 = inv.tabla_fiabilidad(t.reset_index().query("id == 'fred:CONTRA_99'"), cat, por_periodo,
                              inv.agregados_alfred_medida(None, cat), PUBS, LAGS).set_index("regla")
    assert f1.loc["LAG_NO", "veredicto_desde_2000"] == "sin riesgo desde 2000"


# --- BoE (D6), sin red --------------------------------------------------------------------------
ROBOTS = """User-agent: *
Disallow: /boeapps/iadb
Disallow: /boeapps/database/_iadb-FromShowColumns.asp
Disallow: /boeapps/database/ShowChart.asp
"""


def test_t2_rutas_boe_y_ficha(tmp_path):
    rutas = inv.rutas_boe(ROBOTS)
    cand = rutas[rutas["tipo"] == "candidata"].set_index("ruta")
    assert not cand.loc[inv.RUTAS_BOE[0][0], "permitida"] and cand.loc[inv.RUTAS_BOE[0][0], "uso"] == "vetada"
    assert not cand.loc[inv.RUTAS_BOE[1][0], "permitida"]
    assert cand.loc[inv.RUTAS_BOE[2][0], "uso"].startswith("permitida solo en HTML")
    assert (rutas["tipo"] != "candidata").sum() == 3
    ficha = tmp_path / "boe.json"
    real = json.loads((inv.resultados_dir(inv.TEMA) / "fichas" / "boe.json").read_text(encoding="utf-8"))
    ficha.write_text(json.dumps({**real, "mediciones": {}, "notas": ["x"]}), encoding="utf-8")
    inv.actualizar_ficha_boe(rutas, ficha, hoy="2026-11-17")
    inv.actualizar_ficha_boe(rutas, ficha, hoy="2026-11-17")            # idempotente: una sola nota
    d = json.loads(ficha.read_text(encoding="utf-8"))
    assert d["estado_sonda"] == "fallo" and d["mediciones"]["robots"]["rutas_csv_xml_permitidas"] == []
    assert d["mediciones"]["robots"]["motivo"] == inv.MOTIVO_BOE
    assert len(d["notas"]) == 2 and inv.MOTIVO_BOE in d["notas"][1]
    FichaFuente(**d)


# --- Precios ------------------------------------------------------------------------------------
def test_t2_precios_apertura_deslistado_y_universo():
    ses = pd.bdate_range("2020-01-01", "2020-12-31")
    df = pd.DataFrame({"sesion": ses, "open": 1.0, "close": 1.0, "volume": 100.0, "mercado": "XNYS",
                       "divisa": "USD"})
    sin_open = df.assign(open=np.where(np.arange(len(df)) % 10 == 0, np.nan, 1.0))   # 90 % con apertura
    viejo = df[df["sesion"] < "2020-11-01"]
    med = pd.DataFrame([{"ticker": "SPY", "proveedor": "yahoo", **inv.medidas_precios(df)},
                        {"ticker": "OLD", "proveedor": "yahoo", **inv.medidas_precios(viejo)},
                        {"ticker": "NOP", "proveedor": "yahoo", **inv.medidas_precios(sin_open)},
                        {"ticker": "cb:BTC-USD", "proveedor": "coinbase", **inv.medidas_precios(df)}])
    u = {"instrumentos": [{"id": "yf:SPY", "clase": "etf", "bucket": "rv_eeuu", "capa": "estrategica",
                           "mercado": "ARCX", "divisa": "USD", "equivalente_ucits": "yf:CSPX.L",
                           "tickers": {"yahoo": "SPY"}},
                          {"id": "coinbase:BTC-USD", "clase": "cripto", "bucket": "cripto", "capa": "tactica",
                           "mercado": "CRYPTO", "divisa": "USD", "tickers": {"coinbase": "BTC-USD"}}]}
    t = inv.tabla_inventario_precios(med, u).set_index("ticker")
    assert t.loc["SPY", "en_universo"] and t.loc["SPY", "equivalente_ucits"] == "yf:CSPX.L"
    assert t.loc["cb:BTC-USD", "en_universo"] and not t.loc["OLD", "en_universo"]
    assert t.loc["OLD", "deslistado"] and not t.loc["SPY", "deslistado"]
    assert t.loc["SPY", "tiene_apertura"] and not t.loc["NOP", "tiene_apertura"]
    assert t.loc["SPY", "pct_huecos_lv"] == 0.0 and t.loc["SPY", "max_hueco_dias"] == 3
    assert list(t.reset_index().columns) == list(inv.COLUMNAS_PRECIOS_INV)


# --- Cifras de la base real ---------------------------------------------------------------------
@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series().exists(), reason="falta la base real (construir-base --sin-red)")
def test_t2_cifras_de_la_base():
    import pyarrow.parquet as pq

    base = pq.read_table(almacen.ruta_series(), columns=["serie"], read_dictionary=["serie"])
    assert base.num_rows == 10_516_135
    assert base.column("serie").to_pandas().nunique() == 1_434
    precios = almacen.corpus_dir(almacen.TEMA) / "precios"
    assert sum(1 for p in precios.iterdir() if p.is_dir() for _ in p.glob("*.parquet")) == 1_471
