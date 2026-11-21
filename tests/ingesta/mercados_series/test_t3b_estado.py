"""Estado del paso 3b (``estado_3b``, tandas 3b-1 y 3b-2): reglas por tipo de fila, sin red ni datos."""
from __future__ import annotations

import pandas as pd
import pytest

from ingesta.mercados_series import estado_3b as e

T = pd.Timestamp
MEDIDAS = e.MedidasBase(
    desde={"wb:WLD.FP.CPI.TOTL.ZG": T("1960-01-01"), "imf:WEO.001.NGDP_RPCH": T("2025-01-01"),
           "imf:WEO.001.NGDP_RPCH.PROY.H1": T("2025-01-01"), "rba:FIRMMCRTD": T("1976-01-01"),
           "rba:FCMYGBAG10D": T("1995-01-01"), "boc:STATIC_ATABLE_V39079": T("1996-01-01"),
           "yf:^GSPC": T("1927-12-30"), "yf:^BCOM": T("1991-01-02")},
    hasta={"yf:^GSPC": T("2026-11-18"), "yf:^BCOM": T("2026-07-17"), "yf:^TNX": T("2026-11-19")},
    ediciones_weo=frozenset({"2025-04", "2025-10", "2026-04", "2026-10"}),
    hasta_fuente={"calculo_propio": T("2026-11-18"), "shiller": T("2026-10-01")},
    crudos={"fred": T("2026-11-19"), "alfred": T("2026-11-19"), "ken_french": T("2026-11-19"),
            "oecd": T("2026-11-20"), "philly_rtdsm": T("2026-11-20"), "bis": T("2026-10-13")},
    capturas_oas=frozenset({"2026-10-12", "2026-11-19"}))


@pytest.mark.parametrize(("fila", "esperado"), [
    ({"id": "refresco:fred_alfred", "tipo": "refresco", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo"}, "hecho"),
    ({"id": "refresco:oecd", "tipo": "refresco", "fuente": "oecd"}, "hecho"),
    ({"id": "refresco:philly_rtdsm", "tipo": "refresco", "fuente": "philly_rtdsm"}, "hecho"),
    ({"id": "refresco:bundesbank", "tipo": "refresco", "fuente": "bundesbank"}, "limitacion_declarada"),
    # sin evidencia en el corpus: crudo del BIS anterior al 3b-2, Shiller sin crudo ni datos tras el corte
    ({"id": "refresco:bis", "tipo": "refresco", "fuente": "bis"}, "aplazado"),
    ({"id": "refresco:shiller", "tipo": "refresco", "fuente": "shiller"}, "aplazado"),
    # derivadas propias: sin crudo, con datos posteriores al corte en la base
    ({"id": "refresco:calculo_propio", "tipo": "refresco", "fuente": "calculo_propio"}, "hecho"),
    ({"id": "refresco:fuente_nueva", "tipo": "refresco", "fuente": "fuente_nueva"}, "aplazado"),
    ({"id": "refresco:proyecciones:fred_alfred", "tipo": "refresco", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "fred:BAMLH0A0HYM2", "tipo": "archivo_periodico", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "AVB", "tipo": "redescarga", "fuente": "yahoo"}, "limitacion_declarada"),
    ({"id": "ken_french:ediciones_antiguas", "tipo": "fechas", "fuente": "ken_french"}, "resuelto"),
    ({"id": "eurostat:calendarios", "tipo": "fechas", "fuente": "eurostat"}, "limitacion_declarada"),
    ({"id": "yf:XYZ.L", "tipo": "precios", "fuente": "yahoo"}, "limitacion_declarada"),
    ({"id": "baseline:6040_europeo", "tipo": "precios", "fuente": "yahoo"}, "aplazado"),
    ({"id": "wb:WLD", "tipo": "series", "fuente": "worldbank"}, "hecho"),
    ({"id": "wb:LMY", "tipo": "series", "fuente": "worldbank"}, "aplazado"),     # sin filas en MEDIDAS: revisar
    ({"id": "imf:WEO.001", "tipo": "series", "fuente": "imf_weo"}, "hecho"),
    ({"id": "rba:historia_pre2011", "tipo": "series", "fuente": "rba"}, "hecho"),
    ({"id": "boc:historia_pre2001", "tipo": "series", "fuente": "boc"}, "parcial"),
    ({"id": "eurostat:une_rt_m.EA", "tipo": "series", "fuente": "eurostat"}, "limitacion_declarada"),
    ({"id": "oecd:LI_AA.EA20", "tipo": "series", "fuente": "oecd"}, "limitacion_declarada"),
    ({"id": "oecd:UNEMP.CHN", "tipo": "series", "fuente": "oecd"}, "limitacion_declarada"),
    ({"id": "philly:RUC", "tipo": "series", "fuente": "philly_rtdsm"}, "limitacion_declarada"),
    ({"id": "imf_weo:edicion:2025-04", "tipo": "ediciones", "fuente": "imf_weo"}, "hecho"),
    ({"id": "imf_weo:edicion:2008-04", "tipo": "ediciones", "fuente": "imf_weo"}, "limitacion_declarada"),
    ({"id": "DWD", "tipo": "deslistado", "fuente": "yahoo", "estado": "limitacion_declarada",
      "motivo": "F3"}, "limitacion_declarada"),
])
def test_estado_fila(fila: dict, esperado: str) -> None:
    assert e.estado_fila(pd.Series(fila), MEDIDAS)[0] == esperado


def test_hecho_exige_evidencia() -> None:
    """Refresco, archivo de las OAS, edición académica y SEP: «hecho» solo con evidencia en el corpus."""
    oas = pd.Series({"id": "fred:BAMLH0A0HYM2", "tipo": "archivo_periodico", "fuente": "fred_alfred"})
    est, mot = e.estado_fila(oas, MEDIDAS)
    assert est == "hecho" and "2026-11-19" in mot and "2026-10-12" not in mot
    sin = e.MedidasBase()
    assert e.estado_fila(oas, sin)[0] == "aplazado"
    for fila in ({"id": "academicas:archivo_periodico", "tipo": "archivo_periodico", "fuente": "academicas"},
                 {"id": "refresco:proyecciones:fred_alfred", "tipo": "refresco", "fuente": "fred_alfred"},
                 {"id": "refresco:oecd", "tipo": "refresco", "fuente": "oecd"}):
        assert e.estado_fila(pd.Series(fila), MEDIDAS)[0] == "hecho"
        est, mot = e.estado_fila(pd.Series(fila), sin)
        assert est == "aplazado" and mot.startswith("sin evidencia de refresco")
    hay, texto = e.evidencia_refresco("bis", "3b-2", MEDIDAS)
    assert not hay and "2026-10-13" in texto


def test_motivos_de_las_series_nuevas() -> None:
    """Los motivos salen de los extractores; la historia parcial del BoC dice desde cuándo y qué falta."""
    est, mot = e.estado_fila(pd.Series({"id": "boc:historia_pre2001", "tipo": "series", "fuente": "boc"}), MEDIDAS)
    assert est == "parcial" and "1996-01-01" in mot and "Statistics Canada" in mot
    _, mot = e.estado_fila(pd.Series({"id": "imf_weo:edicion:2010-10", "tipo": "ediciones"}), MEDIDAS)
    assert "robots.txt" in mot and "403" in mot
    _, mot = e.estado_fila(pd.Series({"id": "imf:WEO.001", "tipo": "series"}), MEDIDAS)
    assert mot.startswith("descargado en el 3b-2: 1 series")      # sin la de proyección
    _, mot = e.estado_fila(pd.Series({"id": "imf:WEO.001", "tipo": "series", "detalle": "LUR; NGDP_RPCH"}), MEDIDAS)
    assert mot.endswith("el FMI no publica LUR para este agregado")
    # sin medidas, nada se da por hecho
    assert e.estado_fila(pd.Series({"id": "imf_weo:edicion:2025-04", "tipo": "ediciones"}))[0] == \
        "limitacion_declarada"


def test_partir_refresco_precios_por_lote_y_fecha_de_corte() -> None:
    """La fila del refresco de precios se parte con la última sesión de cada fichero (no a mano)."""
    precios = pd.DataFrame([
        {"id": "AAPL", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "KVUE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "SPY", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "NESN.SW", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "SAP.DE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "BMW.DE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "UBSG.SW", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "CSPX.L", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "IUAA.L", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "RARO", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "WBD", "proveedor": "yahoo", "decision": "fuera", "en_universo": False},
        {"id": "cb:BTC-USD", "proveedor": "coinbase", "decision": "queda", "en_universo": True},
    ])
    ultimas = {"AAPL": "2026-11-19", "KVUE": "2026-10-30", "SPY": "2026-11-18", "NESN.SW": "2026-10-13",
               "SAP.DE": "2026-11-19", "BMW.DE": "2026-11-19", "UBSG.SW": "2026-10-13", "CSPX.L": "2026-11-19",
               "IUAA.L": "2026-11-19", "RARO": "2026-11-19", "WBD": "2026-10-05", "cb:BTC-USD": "2026-11-19"}
    out = e.partir_refresco_precios(precios, {k: pd.Timestamp(v) for k, v in ultimas.items()},
                                    sp500={"AAPL", "KVUE", "WBD"}, nucleo={"AAPL", "SPY", "NESN.SW"},
                                    ampliado={"AAPL", "KVUE", "SAP.DE", "BMW.DE", "UBSG.SW"}, corte="2026-11-13",
                                    motivos={"NESN.SW": "Yahoo revisa una sesión guardada",
                                             "UBSG.SW": "Yahoo revisa una sesión ya guardada (2026-09-07)"},
                                    lotes={"universo": {"IUAA.L"}}).set_index("id")
    assert out.at["refresco:precios:yahoo", "estado_3b"] == "hecho"
    assert out.at["refresco:precios:yahoo", "detalle"] == "2 ficheros (S&P 500 1, núcleo 1)"
    assert out.at["refresco:precios:yahoo:ampliado_no_eeuu", "estado_3b"] == "hecho"
    assert out.at["refresco:precios:yahoo:ampliado_no_eeuu", "detalle"] == "2 ficheros"
    assert out.at["refresco:precios:yahoo:universo", "estado_3b"] == "hecho"
    assert out.at["refresco:precios:yahoo:universo", "detalle"] == \
        "2 ficheros (1 descargados en el lote y 1 que ya estaban antes del 3b-2)"
    assert out.at["refresco:precios:yahoo:otro", "estado_3b"] == "aplazado"
    assert out.at["KVUE", "estado_3b"] == "limitacion_declarada" and "2026-10-30" in out.at["KVUE", "motivo_3b"]
    assert out.at["NESN.SW", "motivo_3b"] == "Yahoo revisa una sesión guardada"
    # rechazo del almacén en el 3b-2: limitación con su motivo
    assert out.at["UBSG.SW", "estado_3b"] == "limitacion_declarada"
    assert "2026-09-07" in out.at["UBSG.SW", "motivo_3b"]
    assert out.at["refresco:precios:coinbase", "estado_3b"] == "hecho"
    assert "WBD" not in out.index      # fuera (truncado): va por su fila de redescarga
    # todos los «queda» están en alguna fila
    n = out["detalle"].str.extract(r"^(\d+) ficheros")[0].dropna().astype(int).sum()
    assert n + (out["tipo"] == "excepcion_refresco").sum() == (precios["decision"] == "queda").sum()
    # con aviso no_llega_corte de los precios curados (hueco antes del corte), no llega aunque su última sea posterior
    otra = e.partir_refresco_precios(precios, {k: pd.Timestamp(v) for k, v in ultimas.items()},
                                     sp500={"AAPL", "KVUE", "WBD"}, nucleo={"AAPL", "SPY", "NESN.SW"},
                                     ampliado={"AAPL", "KVUE", "SAP.DE", "BMW.DE", "UBSG.SW"}, corte="2026-11-13",
                                     no_llegan={"AAPL"}).set_index("id")
    assert otra.at["AAPL", "estado_3b"] == "limitacion_declarada"
    assert otra.at["refresco:precios:yahoo", "detalle"] == "1 ficheros (S&P 500 0, núcleo 1)"


def test_motivos_refresco_de_los_rechazos_del_3b2() -> None:
    sw = [t for t, m in e.MOTIVOS_REFRESCO.items() if t.endswith(".SW") and "2026-09-07" in m]
    assert len(sw) == 11      # NESN.SW (3b-1) y 10 del lote 3b2_ampliado
    for t in ("EXO.AS", "JD.L"):
        assert e.MOTIVOS_REFRESCO[t] == "Yahoo revisa una sesión ya guardada (2026-10-13); se conserva lo guardado"


def test_partir_refresco_yf() -> None:
    out = e.partir_refresco_yf(["yf:^GSPC", "yf:^TNX", "yf:^BCOM", "yf:^W5000"], MEDIDAS.hasta).set_index("id")
    assert out.at["refresco:yfinance", "estado_3b"] == "hecho"
    assert out.at["refresco:yfinance", "detalle"] == "2 de 4 series que se quedan"
    assert out.at["yf:^BCOM", "estado_3b"] == "limitacion_declarada" and "2026-07-17" in out.at["yf:^BCOM", "detalle"]
    assert out.at["yf:^W5000", "motivo_3b"] == e.MOTIVOS_YF["yf:^W5000"]       # sin filas en la base
    assert set(out["tipo"]) == {"refresco", "excepcion_refresco"}


def test_filas_universo_3b2() -> None:
    registro = pd.DataFrame([
        {"ticker": "CSPX.L", "estado": "ok", "inicio": "2010-05-20", "fin": "2026-11-19"},
        {"ticker": "IUAA.L", "estado": "ok", "inicio": "2017-04-13", "fin": "2026-11-19"},
        {"ticker": "XDEW.DE", "estado": "ok", "inicio": "2014-08-15", "fin": "2026-11-19"},
        {"ticker": "EUNK.DE", "estado": "ok", "inicio": "2009-10-20", "fin": "2026-11-18"},
        {"ticker": "MALO.L", "estado": "error", "error": "vacío"},
    ])
    universo = pd.DataFrame({"ticker_yahoo": ["CSPX.L", "IUAA.L", "XDEW.DE", "EUNK.DE", "MALO.L"],
                             "inicio_esperado": pd.to_datetime(["2010-05-19", "2011-09-13", "2014-06-10",
                                                                "2009-09-25", None])})
    out = e.filas_universo_3b2(registro, universo).set_index("id")
    assert out.at["precios:universo:3b2", "detalle"] == "4 de 5 instrumentos"
    assert "2026-11-19" in out.at["precios:universo:3b2", "motivo_3b"]
    assert out.at["yf:MALO.L", "estado_3b"] == "limitacion_declarada"
    # EUNK.DE empieza 25 días tarde (dentro de la holgura); XDEW.DE, 66
    assert out.at["precios:universo:historia_recortada", "detalle"] == "2 instrumentos: IUAA.L, XDEW.DE"
    assert e.filas_universo_3b2(pd.DataFrame(), universo).empty


def test_construir_parte_el_refresco_y_anade_el_sp500() -> None:
    entrada = pd.DataFrame([
        {"id": "refresco:bce", "tipo": "refresco", "fuente": "bce", "prioridad": "alta"},
        {"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo", "prioridad": "alta"},
        {"id": "refresco:yfinance", "tipo": "refresco", "fuente": "yfinance", "prioridad": "alta"},
        {"id": "yf:MALO.L", "tipo": "precios", "fuente": "yahoo", "prioridad": "alta"},
        {"id": "WBD", "tipo": "redescarga", "fuente": "yahoo", "prioridad": "media"},
        {"id": "XYZ", "tipo": "redescarga", "fuente": "yahoo", "prioridad": "media"}])
    partidas = pd.DataFrame([{"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo",
                              "prioridad": "alta", "detalle": "1 ficheros", "estado_3b": "hecho", "motivo_3b": "x"}])
    resumen = pd.DataFrame({"metrica": ["tramos_ticker_reutilizado", "tickers_reutilizados"], "valor": [136, 120]})
    universo = e.filas_universo_3b2(pd.DataFrame([{"ticker": "MALO.L", "estado": "error", "error": "vacío"}]),
                                    pd.DataFrame({"ticker_yahoo": ["MALO.L"], "inicio_esperado": [pd.NaT]}))
    out = e.construir(entrada, partidas, e.filas_sp500(resumen), MEDIDAS,
                      e.partir_refresco_yf(["yf:^GSPC", "yf:^BCOM"], MEDIDAS.hasta), universo)
    assert out["estado_3b"].notna().all() and set(out["estado_3b"]) <= set(e.ESTADOS)
    for i in ("refresco:precios:yahoo", "refresco:yfinance", "yf:MALO.L"):
        assert (out["id"] == i).sum() == 1
    ind = out.set_index("id")
    assert ind.at["refresco:yfinance", "detalle"] == "1 de 2 series que se quedan"
    assert ind.at["sp500:tickers_reutilizados", "detalle"].startswith("136 tramos")
    assert ind.at["constituyentes:sp500_posterior_fja", "estado_3b"] == "limitacion_declarada"
    assert "adquirido por Paramount Skydance" in ind.at["WBD", "motivo_3b"]
    assert ind.at["XYZ", "motivo_3b"] == e.MOTIVO_TRUNCADO
    # 000001.SS y NESN.SW son del núcleo: su motivo no es «fuera de H1»
    for t in ("000001.SS", "NESN.SW"):
        assert "fuera del alcance" not in e.MOTIVOS_REFRESCO[t] and "revisa una sesión" in e.MOTIVOS_REFRESCO[t]
