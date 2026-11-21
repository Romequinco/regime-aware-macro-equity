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


# --- P11, P21 y P28 · saneado de los precios curados ------------------------------------------------------------
from ingesta.mercados_series import curada_precios, visibilidad  # noqa: E402
from ingesta.mercados_series import saneado_precios as sp  # noqa: E402
from ingesta.mercados_series.contrato import COLUMNAS_PRECIOS, validar_precios  # noqa: E402

SESIONES = pd.bdate_range("2026-03-02", "2026-06-26")
CAL = SESIONES.to_numpy().astype("datetime64[D]")       # calendario de prueba: todos los días L-V
CORTE = pd.Timestamp("2026-11-13")


def _tabla(close, tk: str = "AAA", mercado: str = "XNYS", sesiones=SESIONES) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    disp = visibilidad.disponible_cierre_serie(pd.Series(sesiones), mercado)
    df = pd.DataFrame({
        "ticker": tk, "sesion": sesiones, "mercado": mercado, "open": close * 1.001, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1e6, "dividendo": 0.0, "split": 1.0, "divisa": "USD",
        "fecha_publicacion": primera_decision_vec(disp).to_numpy(), "disponible_utc": disp.to_numpy(),
        "fuente": "sintetico", "descargado": pd.Timestamp("2026-11-21", tz="UTC")})
    return validar_precios(df[list(COLUMNAS_PRECIOS)])


def _base(n=len(SESIONES), semilla=1):
    rng = np.random.default_rng(semilla)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))


def _curar(p):
    r = curada_precios.curar_ticker(p, CORTE, CAL)
    fallos = curada_precios.verificar_ticker(r.referencia, r.curado, CORTE, CAL, r.saneado)
    return r, fallos


def test_p11_pico_aislado_se_corrige_con_el_cierre_anterior_y_se_publica_al_confirmarse():
    c = _base()
    c[40:42] *= 10.0                    # dos sesiones x10 que vuelven: error de Yahoo
    r, fallos = _curar(_tabla(c))
    assert not any(fallos.values()), fallos
    cur = r.curado.set_index("sesion")
    s40, s41, s42 = SESIONES[40], SESIONES[41], SESIONES[42]
    assert cur.loc[s40, "close"] == cur.loc[s41, "close"] == c[39]
    assert cur.loc[[s40, s41], ["open", "high", "low"]].isna().all().all()
    # TimeGate: las corregidas se ven cuando se ve la vuelta (la sesión 42), nunca antes.
    assert (cur.loc[[s40, s41], "fecha_publicacion"] == cur.loc[s42, "fecha_publicacion"]).all()
    tipos = [x["tipo"] for x in r.saneado.saltos]
    assert tipos == ["pico", "pico"] and r.saneado.corregidas == {s40, s41}


def test_p11_cambio_de_nivel_con_split_limpio_registra_el_factor():
    c = _base()
    c[60:] /= 2.0                        # bonus 1:1 sin registrar: el precio se queda a la mitad
    p = _tabla(c)
    p.loc[p.index >= 60, "volume"] *= 2.0   # y las acciones (el volumen) se duplican
    r, fallos = _curar(p)
    assert not any(fallos.values()), fallos
    cur = r.curado.set_index("sesion")
    assert cur.loc[SESIONES[60], "split"] == 2.0 and (cur["close"].to_numpy() == c).all()   # precio intacto
    assert (cur.loc[SESIONES[60:63], "fecha_publicacion"] == cur.loc[SESIONES[63], "fecha_publicacion"]).all()
    assert [x["tipo"] for x in r.saneado.saltos] == ["split"]
    from ingesta.mercados_series.timegate import ajustar_a_fecha
    aj = ajustar_a_fecha(r.curado, "2026-11-13", avisar=False)["close_aj_total"].to_numpy()
    assert abs(np.log(aj[60] / aj[59])) < 0.05                     # la rentabilidad ajustada sale bien


def test_p11_rally_que_dobla_sin_volumen_no_es_split():
    """Un precio que se duplica y se queda (GME, 2021-02-24) con el mismo volumen no es un contrasplit: real."""
    c = _base()
    c[60:] *= 2.0
    r, fallos = _curar(_tabla(c))
    assert not any(fallos.values()) and [x["tipo"] for x in r.saneado.saltos] == ["real"]
    assert "volumen" in r.saneado.saltos[0]["nota"] and not r.saneado.splits


def test_p11_indices_no_se_corrigen():
    c = _base()
    c[40:42] *= 10.0
    r = curada_precios.curar_ticker(_tabla(c), CORTE, CAL, clase="indice")
    assert {x["tipo"] for x in r.saneado.saltos} == {"real"} and not r.saneado.corregidas


def test_p11_movimiento_real_se_mantiene():
    c = _base()
    c[70:] *= 0.4                        # caída del 60 % que no revierte y no es un split limpio (razón 2,5)
    r, fallos = _curar(_tabla(c))
    assert not any(fallos.values())
    assert [x["tipo"] for x in r.saneado.saltos] == ["real"] and not r.saneado.splits and not r.saneado.corregidas
    assert (r.curado["close"].to_numpy() == c).all()


def test_p11_cambio_no_registrado_falla():
    c = _base()
    c[40:42] *= 10.0
    r, _ = _curar(_tabla(c))
    f = curada_precios.verificar_ticker(r.referencia, r.curado, CORTE, CAL, sp.Saneado())
    assert f["close_intacto"] == 2 and f["fechas_intactas"] == 2


def test_p28_hueco_corto_se_rellena_y_el_largo_no():
    c = _base()
    p = _tabla(c)
    corto = p[~p["sesion"].isin(SESIONES[30:33])]           # 3 sesiones sin vela
    r, fallos = _curar(corto)
    assert not any(fallos.values()), fallos
    cur = r.curado.set_index("sesion")
    assert len(cur) == len(SESIONES) and r.saneado.rellenas == set(SESIONES[30:33])
    assert (cur.loc[SESIONES[30:33], "close"] == c[29]).all() and (cur.loc[SESIONES[30:33], "volume"] == 0).all()
    assert cur.loc[SESIONES[30:33], ["open", "high", "low"]].isna().all().all()
    pd.testing.assert_series_equal(cur.loc[SESIONES[30:33], "fecha_publicacion"],
                                   p.set_index("sesion").loc[SESIONES[30:33], "fecha_publicacion"])
    largo = p[~p["sesion"].isin(SESIONES[30:37])]           # 7 sesiones: no se rellena, se avisa
    r2, _ = _curar(largo)
    assert not r2.saneado.rellenas and r2.saneado.huecos_largos == [(SESIONES[30], SESIONES[36], 7)]
    avisos = curada_precios.avisos_ticker("AAA", "yahoo", r2, {"decision": "queda"}, sesiones_cal=CAL, corte=CORTE)
    assert "hueco_largo" in {a["tipo"] for a in avisos}


def test_p28_relleno_mal_hecho_falla_la_verificacion():
    p = _tabla(_base())
    r, _ = _curar(p[~p["sesion"].isin(SESIONES[30:32])])
    roto = r.curado.copy()
    roto.loc[roto["sesion"] == SESIONES[30], "close"] *= 1.01
    f = curada_precios.verificar_ticker(r.referencia, roto, CORTE, CAL, r.saneado)
    assert f["rellenos_ffill_validos"] == 2          # la tocada y la siguiente ya no repiten el cierre anterior
    # Una sesión añadida que no está registrada como relleno es un fallo de fechas_intactas.
    f2 = curada_precios.verificar_ticker(r.referencia, r.curado, CORTE, CAL, sp.Saneado())
    assert f2["fechas_intactas"] == 2


def test_p21_w5000_pasa_a_xnys_sin_adelantar_nada():
    ses = pd.bdate_range("2026-01-05", "2026-02-27")
    p = _tabla(_base(len(ses)), tk="^W5000", mercado="XLON", sesiones=ses)
    ref = curada_precios.referencia_ticker(p)
    assert set(ref["mercado"]) == {"XNYS"}
    assert (ref["disponible_utc"] >= p["disponible_utc"]).all()
    assert (ref["disponible_utc"] > p["disponible_utc"]).any()
    validar_precios(ref)                                             # coherente con el cierre de Nueva York


def test_p02_y_p28_marcar_fuera_en_la_lista(tmp_path):
    ruta = tmp_path / "lista.yaml"
    ruta.write_text("# Precios: 3 (fuera 0, queda 3).\nseries:\n  'a:b': {decision: queda}\nprecios:\n"
                    "  AAA: {decision: queda, regla: d10_abierta, motivo: 'queda: D10', aviso: 'ticker reutilizado: x'}\n"
                    "  BBB: {decision: queda, regla: d10_abierta, motivo: 'queda: D10'}\n"
                    "  ^CCC: {decision: queda, regla: d10_abierta, motivo: 'queda: D10'}\n", encoding="utf-8")
    lista = visibilidad.leer_yaml(ruta)["precios"]
    assert sp.tickers_reutilizados(lista) == ["AAA"]
    out = sp.marcar_fuera_en_lista(ruta, {"AAA": ("reutilizado", sp.MOTIVO_REUTILIZADO), "^CCC": ("hueco_largo", "h")})
    assert out == {"cambiados": ["AAA", "^CCC"], "precios": 3, "fuera": 2, "queda": 1}
    nueva = visibilidad.leer_yaml(ruta)
    aaa = nueva["precios"]["AAA"]
    assert aaa["decision"] == "fuera" and aaa["regla"] == "reutilizado"
    assert aaa["motivo"].startswith(sp.MOTIVO_REUTILIZADO) and "antes: queda" in aaa["motivo"]
    assert nueva["precios"]["BBB"]["decision"] == "queda" and nueva["series"] == {"a:b": {"decision": "queda"}}
    assert curada_precios.queda_cabecera(ruta) == 1
    assert sp.marcar_fuera_en_lista(ruta, {"AAA": ("reutilizado", "x")})["cambiados"] == []      # idempotente


# --- P08 · ejecución en t+1 -------------------------------------------------------------------------------------
from ingesta.mercados_series.cartera import baselines as b  # noqa: E402


def _sintetico(tk: str, desde: str, hasta: str, semilla: int, mercado: str = "XNYS", retraso: int = 0):
    from test_t1_b8_cartera import precios_sinteticos
    return precios_sinteticos(tk, desde, hasta, semilla=semilla, mercado=mercado, retraso_pub=retraso)


def test_p08_la_senal_ve_el_cierre_de_t_y_nunca_la_sesion_de_ejecucion():
    precios = {"AAA": _sintetico("AAA", "2010-01-04", "2011-12-30", 5)}
    vistos = []

    def pesos(fecha, vistas, actuales):
        v = vistas["AAA"]
        vistos.append((fecha, v["sesion"].max()))
        return {"AAA": 1.0}

    res = b.simular(b.Estrategia(nombre="espia", universo=lambda f: ["AAA"], pesos=pesos), precios,
                    "2010-03-01", "2011-12-30")
    assert vistos and all(ultima <= fecha for fecha, ultima in vistos)
    assert any(ultima == fecha for fecha, ultima in vistos)              # decide tras el cierre de t
    reb = res.rebalanceos
    assert (reb["fecha_ejecucion"] > reb["fecha"]).all()                 # se ejecuta en t+1, nunca en t


def test_p08_precio_de_ejecucion_apertura_y_reserva_al_cierre():
    p = _sintetico("AAA", "2010-01-04", "2010-02-26", 1)
    v = b._vista("AAA", pd.Timestamp("2010-02-26"), p, pd.Timestamp("2010-01-01"), None, [])
    t = pd.Timestamp("2010-01-29")
    ses, precio, pub, reserva = b.precio_ejecucion(v, t)
    fila = v[v["sesion"] == "2010-02-01"].iloc[0]
    assert ses == pd.Timestamp("2010-02-01") and precio == fila["open"] and not reserva
    assert b.precio_ejecucion(v, t, "cierre_t1")[1] == fila["close"]
    sin_apertura = v.assign(open=np.where(v["sesion"] == "2010-02-01", np.nan, v["open"]))
    _, precio2, _, reserva2 = b.precio_ejecucion(sin_apertura, t)
    assert reserva2 and precio2 == fila["close"]                          # cierre de t+1, nunca el de t
    assert precio2 != v.loc[v["sesion"] == t, "close"].iloc[0]
    assert b.precio_ejecucion(v[v["sesion"] <= t], t) is None             # t+1 aún no publicada


def test_p08_apertura_frente_a_cierre_t1_y_truncado():
    """Las dos variantes en t+1 dan curvas distintas (el salto de apertura) y ninguna mira al futuro."""
    precios = {"AAA": _sintetico("AAA", "2008-01-02", "2010-12-31", 3),
               "NAV": _sintetico("NAV", "2008-01-02", "2010-12-31", 4, mercado="NAV_US", retraso=1)}
    precios["NAV"] = precios["NAV"].assign(open=np.nan, high=np.nan, low=np.nan)   # fondo: solo valor liquidativo
    est = lambda: b.uno_n(["AAA", "NAV"])                                  # noqa: E731
    a = b.simular(est(), precios, "2008-02-01", "2010-12-31")
    c = b.simular(est(), precios, "2008-02-01", "2010-12-31", ejecucion="cierre_t1")
    assert not np.allclose(a.curva.to_numpy(), c.curva.to_numpy())
    assert any("se ejecuta a su cierre" in x for x in a.avisos)           # el NAV no tiene apertura: reserva
    corte = pd.Timestamp("2009-06-15")
    trunc = {tk: t[t["fecha_publicacion"] <= corte] for tk, t in precios.items()}
    for modo in ("apertura_t1", "cierre_t1"):
        completo = b.simular(est(), precios, "2008-02-01", "2010-12-31", ejecucion=modo)
        cortado = b.simular(est(), trunc, "2008-02-01", corte, ejecucion=modo)
        comun = completo.curva.loc[:corte]
        np.testing.assert_allclose(cortado.curva.loc[comun.index].to_numpy(), comun.to_numpy(), rtol=1e-12)


# --- P05 · sesgo de supervivencia -------------------------------------------------------------------------------
from ingesta.mercados_series import supervivencia as sv  # noqa: E402


def _tramos_sinteticos() -> pd.DataFrame:
    return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"],
                         "alta": pd.to_datetime(["2010-01-04", "2010-01-04", "2010-06-01"]),
                         "baja": pd.to_datetime([None, "2010-09-01", None]),
                         "fecha_publicacion": pd.to_datetime(["2010-01-04", "2010-01-04", "2010-06-01"])})


def test_p05_miembros_con_precio_y_aviso():
    tramos = _tramos_sinteticos()
    pubs = {"AAA": pd.bdate_range("2010-01-04", "2010-12-31"), "BBB": pd.bdate_range("2010-01-04", "2010-03-31")}
    con, sin, aviso = sv.miembros_con_precio("2010-07-01", tramos, pubs.get)
    assert con == ["AAA"] and sin == ["BBB", "CCC"]
    assert "2 de 3 miembros" in aviso and "66.7 %" in aviso


def test_p05_medir_sesgo_curado_solo_porcentajes():
    tramos = _tramos_sinteticos()
    ses = pd.bdate_range("2010-01-04", "2010-12-31")
    rent = {"AAA": pd.DataFrame({"sesion": ses, "rentabilidad": 0.001}),
            "BBB": pd.DataFrame({"sesion": ses[:60], "rentabilidad": -0.002})}
    gspc = pd.Series(0.0005, index=ses)
    diario, tabla = sv.medir_sesgo_curado(tramos, desde="2010-01-04", hasta="2010-12-31", lector=rent.get, excluir=set(),
                                          indice=gspc, spy=gspc)
    assert list(tabla.columns) == list(sv.COLUMNAS_SESGO) and list(tabla["periodo"]) == ["2010", "total (anualizada)"]
    assert diario.loc["2010-02-01", "con_precio"] == 2 and diario.loc["2010-07-01", "sin_precio"] == 2
    fila = tabla.iloc[0]
    assert 0 < fila["pct_cobertura_min"] < fila["pct_cobertura_max"] == 100.0
    assert not {"close", "open", "valor"} & set(tabla.columns)
