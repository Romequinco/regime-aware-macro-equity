"""Tests del saneado de precios del Tema 1 (agente A, 2026-11-21): P03, P04, P06, P08, P11, P21 y P28.

Sin red y sin el corpus: tablas sintéticas en ``tmp_path`` (``ingesta.mercados_series.sinteticos``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import almacen
from ingesta.mercados_series import sinteticos as s
from ingesta.mercados_series.almacen import escribir_precios, leer_precios
from ingesta.mercados_series.contrato import ErrorContrato


# --- P06 · revisiones OHLC aisladas ------------------------------------------------------------------
def test_p06_revision_ohlc_aislada_se_tolera_y_se_apunta(tmp_path):
    """Yahoo retoca el open de UNA vela antigua (los suizos del 2026-09-07): con ``max_revisiones_ohlc`` se
    conserva la vela guardada, se añaden las sesiones nuevas y la revisión queda en el registro."""
    carpeta = tmp_path / "yahoo"
    accion = s.accion_con_eventos()
    primera = accion[accion["sesion"] < "2024-07-01"]
    escribir_precios(primera, "yahoo", carpeta)
    antes = leer_precios(s.TICKER_ACCION, "yahoo", carpeta)
    segunda = accion[accion["sesion"] >= "2024-06-03"].assign(descargado=pd.Timestamp("2025-02-01", tz="UTC"))
    retocada = segunda["sesion"].iloc[1]
    segunda.loc[segunda["sesion"] == retocada, "open"] *= 1.01
    with pytest.raises(ErrorContrato, match="solo crece"):
        escribir_precios(segunda, "yahoo", carpeta, revisiones_toleradas=("volume", "dividendo"))
    escribir_precios(segunda, "yahoo", carpeta, revisiones_toleradas=("volume", "dividendo"), max_revisiones_ohlc=3)
    leido = leer_precios(s.TICKER_ACCION, "yahoo", carpeta)
    assert len(leido) == len(accion)
    pd.testing.assert_frame_equal(leido[leido["sesion"] < "2024-07-01"].reset_index(drop=True),
                                  antes.reset_index(drop=True))
    reg = pd.read_csv(almacen.ruta_revisiones_precios("yahoo", carpeta))
    assert list(reg["columna"]) == ["open"] and pd.Timestamp(reg["sesion"].iloc[0]) == retocada


def test_p06_revision_de_toda_la_historia_sigue_siendo_error(tmp_path):
    """Más de ``max_revisiones_ohlc`` sesiones retocadas (ticker reutilizado, PARA): sigue siendo error."""
    carpeta = tmp_path / "yahoo"
    accion = s.accion_con_eventos()
    escribir_precios(accion[accion["sesion"] < "2024-07-01"], "yahoo", carpeta)
    segunda = accion.assign(descargado=pd.Timestamp("2025-02-01", tz="UTC"))
    segunda["close"] = segunda["close"] * 1.05
    with pytest.raises(ErrorContrato, match="no es una revisión aislada"):
        escribir_precios(segunda, "yahoo", carpeta, max_revisiones_ohlc=3)
    # Otra columna vigilada (mercado, fechas) no se tolera aunque el OHLC sí.
    otra = accion[accion["sesion"] >= "2024-06-03"].assign(descargado=pd.Timestamp("2025-02-01", tz="UTC"))
    otra.loc[otra.index[0], "split"] = 3.0
    with pytest.raises(ErrorContrato, match="split"):
        escribir_precios(otra, "yahoo", carpeta, max_revisiones_ohlc=3)


# --- P03 y P04 · divisas ----------------------------------------------------------------------------
from ingesta.mercados_series import divisas  # noqa: E402
from ingesta.mercados_series.contrato import primera_decision_vec, validar_series  # noqa: E402


def _fx(serie: str, dias, valores, publicado=None, unidad: str = "x") -> pd.DataFrame:
    """Filas de FX SINTÉTICAS visibles a las 16:00 Europe/Berlin de ``publicado`` (por defecto, su día)."""
    dias = pd.DatetimeIndex(pd.to_datetime(dias))
    pub = pd.DatetimeIndex(pd.to_datetime(publicado)) if publicado is not None else dias
    disp = (pub + pd.Timedelta(hours=16)).tz_localize("Europe/Berlin").tz_convert("UTC")
    return pd.DataFrame({
        "serie": serie, "fecha_referencia": dias, "fecha_publicacion": primera_decision_vec(pd.Series(disp)).to_numpy(),
        "disponible_utc": disp, "vintage": pub.strftime("%Y-%m-%d"), "valor": list(valores), "unidad": unidad,
        "divisa": None, "fuente": "prueba", "metodo_publicacion": "calendario", "nota": None})


def _filas(fechas, divisa, valores) -> pd.DataFrame:
    return pd.DataFrame({"sesion": pd.to_datetime(fechas), "close": valores, "divisa": divisa})


DIAS_BCE = pd.bdate_range("2020-10-26", "2020-10-30")         # el BCE deja de publicar el TWD el 2020-10-30
DIAS_FED = pd.bdate_range("2020-10-26", "2020-11-20")


def _base_twd(con_fed: bool) -> pd.DataFrame:
    partes = [_fx("ecb:EXR.D.USD.EUR", pd.bdate_range("2020-10-26", "2020-11-20"), [1.2] * 20),
              _fx("ecb:EXR.D.TWD.EUR", DIAS_BCE, [34.0] * 5)]
    if con_fed:
        # H.10: X por 1 USD, publicada el lunes siguiente a la semana de referencia.
        lunes = [d + pd.offsets.Week(weekday=0) for d in DIAS_FED]
        partes.append(_fx("fred:DEXTAUS", DIAS_FED, [28.0] * len(DIAS_FED), publicado=lunes, unidad="TWD por USD"))
    return validar_series(pd.concat(partes, ignore_index=True))


def test_p04_usx_centavos_de_dolar():
    """ZC=F, ZS=F y ZW=F cotizan en USX: en USD ya no salen vacíos (valor / 100, sin FX)."""
    assert divisas.SUBUNIDADES["USX"] == ("USD", 100.0)
    df = _filas(["2024-03-26", "2024-03-27"], "USX", [450.0, 460.0])
    out = divisas.a_usd(df, ["close"], "divisa", divisas.pd.DataFrame(columns=["serie"]), "2024-04-03", "sesion")
    assert out["close"].tolist() == pytest.approx([4.5, 4.6]) and out["divisa"].eq("USD").all()
    assert out["fx_usd"].tolist() == pytest.approx([0.01, 0.01]) and out.attrs["avisos"] == []


def test_p03_tope_de_antiguedad_sin_secundaria():
    """Sin la Fed, una sesión de TWD con el último fixing del BCE de hace más de 5 días hábiles sale NaN (antes
    se convertía con el fixing de 2020 para siempre)."""
    base = _base_twd(con_fed=False)
    df = _filas(["2020-10-30", "2020-11-06", "2020-11-09"], "TWD", [100.0, 100.0, 100.0])
    out = divisas.a_usd(df, ["close"], "divisa", base, "2020-11-20", "sesion")
    assert out["close"].iloc[0] == pytest.approx(100.0 * 1.2 / 34.0)
    assert out["close"].iloc[1] == pytest.approx(100.0 * 1.2 / 34.0)   # 5 días hábiles: aún vale
    assert np.isnan(out["close"].iloc[2])                              # 6: caducado
    assert any("tope de antigüedad" in a for a in out.attrs["avisos"])


def test_p03_fed_h10_rellena_y_respeta_su_publicacion():
    """Con DEXTAUS (TWD por USD): USD por TWD = 1 / DEX en las fechas sin BCE, y solo lo ya publicado por la Fed."""
    base = _base_twd(con_fed=True)
    assert "fred:DEXTAUS" in divisas.series_fx(["TWD"]) and "fred:DEXCHUS" in divisas.series_fx(["CNY"])
    df = _filas(["2020-10-30", "2020-11-10", "2020-11-13"], "TWD", [100.0, 100.0, 100.0])
    out = divisas.a_usd(df, ["close"], "divisa", base, "2020-11-20", "sesion")
    assert out["close"].iloc[0] == pytest.approx(100.0 * 1.2 / 34.0)       # manda el BCE
    assert out["close"].iloc[1] == pytest.approx(100.0 / 28.0)             # la Fed, en el sentido correcto
    assert out["close"].iloc[2] == pytest.approx(100.0 / 28.0)
    assert any("Fed H.10" in a for a in out.attrs["avisos"])
    # El viernes 2020-11-13 la Fed aún no ha publicado esa semana (sale el lunes 16): el 13 usa el viernes 6,
    # 5 días hábiles: vale; nunca el fixing del 13 antes de publicarse.
    antes = divisas.a_usd(_filas(["2020-11-13"], "TWD", [100.0]), ["close"], "divisa", base, "2020-11-13", "sesion")
    assert antes["fx_fecha"].iloc[0] == pd.Timestamp("2020-11-06")
    # Truncado: añadir fixings publicados después no cambia nada.
    tarde = _fx("fred:DEXTAUS", ["2020-11-13"], [1.0], publicado=["2020-12-01"], unidad="TWD por USD")
    con_tarde = validar_series(pd.concat([base, tarde], ignore_index=True))
    pd.testing.assert_frame_equal(
        divisas.a_usd(_filas(["2020-11-13"], "TWD", [100.0]), ["close"], "divisa", con_tarde, "2020-11-13", "sesion"),
        antes)
