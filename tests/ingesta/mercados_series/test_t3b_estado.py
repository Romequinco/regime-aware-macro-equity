"""Estado del paso 3b-1 (``estado_3b``): reglas por tipo de fila, sin red ni datos."""
from __future__ import annotations

import pandas as pd
import pytest

from ingesta.mercados_series import estado_3b as e


@pytest.mark.parametrize(("fila", "esperado"), [
    ({"id": "refresco:fred_alfred", "tipo": "refresco", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo"}, "hecho"),
    ({"id": "refresco:oecd", "tipo": "refresco", "fuente": "oecd"}, "aplazado_3b2"),
    ({"id": "refresco:bundesbank", "tipo": "refresco", "fuente": "bundesbank"}, "limitacion_declarada"),
    ({"id": "refresco:proyecciones:fred_alfred", "tipo": "refresco", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "fred:BAMLH0A0HYM2", "tipo": "archivo_periodico", "fuente": "fred_alfred"}, "hecho"),
    ({"id": "AVB", "tipo": "redescarga", "fuente": "yahoo"}, "limitacion_declarada"),
    ({"id": "ken_french:ediciones_antiguas", "tipo": "fechas", "fuente": "ken_french"}, "resuelto"),
    ({"id": "eurostat:calendarios", "tipo": "fechas", "fuente": "eurostat"}, "limitacion_declarada"),
    ({"id": "yf:SWDA.L", "tipo": "precios", "fuente": "yahoo"}, "aplazado_3b2"),
    ({"id": "wb:WLD", "tipo": "series", "fuente": "worldbank"}, "aplazado_3b2"),
    ({"id": "imf:WEO.2008-04", "tipo": "ediciones", "fuente": "imf_weo"}, "aplazado_3b2"),
    ({"id": "DWD", "tipo": "deslistado", "fuente": "yahoo", "estado": "limitacion_declarada",
      "motivo": "F3"}, "limitacion_declarada"),
])
def test_estado_fila(fila: dict, esperado: str) -> None:
    assert e.estado_fila(pd.Series(fila))[0] == esperado


def test_partir_refresco_precios_por_lote_y_fecha_de_corte() -> None:
    """La fila del refresco de precios se parte con la última sesión de cada fichero (no a mano)."""
    precios = pd.DataFrame([
        {"id": "AAPL", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "KVUE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "SPY", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "NESN.SW", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "SAP.DE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "BMW.DE", "proveedor": "yahoo", "decision": "queda", "en_universo": False},
        {"id": "CSPX.L", "proveedor": "yahoo", "decision": "queda", "en_universo": True},
        {"id": "WBD", "proveedor": "yahoo", "decision": "fuera", "en_universo": False},
        {"id": "cb:BTC-USD", "proveedor": "coinbase", "decision": "queda", "en_universo": True},
    ])
    ultimas = {"AAPL": "2026-11-19", "KVUE": "2026-10-30", "SPY": "2026-11-18", "NESN.SW": "2026-10-13",
               "SAP.DE": "2026-10-13", "BMW.DE": "2026-10-13", "CSPX.L": "2026-10-09", "WBD": "2026-10-05",
               "cb:BTC-USD": "2026-11-19"}
    out = e.partir_refresco_precios(precios, {k: pd.Timestamp(v) for k, v in ultimas.items()},
                                    sp500={"AAPL", "KVUE", "WBD"}, nucleo={"AAPL", "SPY", "NESN.SW"},
                                    ampliado={"AAPL", "KVUE", "SAP.DE", "BMW.DE"}, corte="2026-11-13",
                                    motivos={"NESN.SW": "Yahoo revisa una sesión guardada"}).set_index("id")
    assert out.at["refresco:precios:yahoo", "estado_3b1"] == "hecho"
    assert out.at["refresco:precios:yahoo", "detalle"] == "2 ficheros (S&P 500 1, núcleo 1)"
    assert out.at["refresco:precios:yahoo:ampliado_no_eeuu", "estado_3b1"] == "aplazado_3b2"
    assert out.at["refresco:precios:yahoo:ampliado_no_eeuu", "detalle"] == "2 ficheros"
    assert out.at["refresco:precios:yahoo:universo", "estado_3b1"] == "aplazado_3b2"
    assert out.at["KVUE", "estado_3b1"] == "limitacion_declarada" and "2026-10-30" in out.at["KVUE", "motivo_3b1"]
    assert out.at["NESN.SW", "motivo_3b1"] == "Yahoo revisa una sesión guardada"
    assert out.at["refresco:precios:coinbase", "estado_3b1"] == "hecho"
    assert "WBD" not in out.index      # fuera (truncado): va por su fila de redescarga
    # todos los «queda» están en alguna fila
    n = out["detalle"].str.extract(r"^(\d+) ficheros")[0].dropna().astype(int).sum()
    assert n + (out["tipo"] == "excepcion_refresco").sum() == (precios["decision"] == "queda").sum()


def test_construir_parte_el_refresco_y_anade_el_sp500() -> None:
    entrada = pd.DataFrame([
        {"id": "refresco:bce", "tipo": "refresco", "fuente": "bce", "prioridad": "alta"},
        {"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo", "prioridad": "alta"},
        {"id": "WBD", "tipo": "redescarga", "fuente": "yahoo", "prioridad": "media"},
        {"id": "XYZ", "tipo": "redescarga", "fuente": "yahoo", "prioridad": "media"}])
    partidas = pd.DataFrame([{"id": "refresco:precios:yahoo", "tipo": "refresco", "fuente": "yahoo",
                              "prioridad": "alta", "detalle": "1 ficheros", "estado_3b1": "hecho", "motivo_3b1": "x"}])
    resumen = pd.DataFrame({"metrica": ["tramos_ticker_reutilizado", "tickers_reutilizados"], "valor": [136, 120]})
    out = e.construir(entrada, partidas, e.filas_sp500(resumen))
    assert out["estado_3b1"].notna().all() and (out["id"] == "refresco:precios:yahoo").sum() == 1
    ind = out.set_index("id")
    assert ind.at["sp500:tickers_reutilizados", "detalle"].startswith("136 tramos")
    assert ind.at["constituyentes:sp500_posterior_fja", "estado_3b1"] == "limitacion_declarada"
    assert "adquirido por Paramount Skydance" in ind.at["WBD", "motivo_3b1"]
    assert ind.at["XYZ", "motivo_3b1"] == e.MOTIVO_TRUNCADO
    # 000001.SS y NESN.SW son del núcleo: su motivo no es «fuera de H1»
    for t in ("000001.SS", "NESN.SW"):
        assert "fuera del alcance" not in e.MOTIVOS_REFRESCO[t] and "revisa una sesión" in e.MOTIVOS_REFRESCO[t]
