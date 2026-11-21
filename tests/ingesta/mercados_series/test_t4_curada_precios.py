"""Paso 4 del Tema 1 · ``curada_precios``: precios curados con datos SINTÉTICOS y sin red.

Un ticker de la NYSE de junio a noviembre de 2026 con una vela de relleno en el Día del Trabajo (2026-09-07,
cerrado: repite el cierre y no tiene volumen), una vela con movimiento el 2026-07-03 (cerrado, pero no es
relleno: se queda con aviso), dos aperturas de relleno (open == high == low == close, con y sin volumen) y sesiones
publicadas después del corte G2. Se comprueba: se quita el relleno, se anula la apertura sin tocar el cierre, el
corte, un ticker «fuera» no se copia, una vela de relleno con dividendo se queda, una verificación que falla no
publica nada (y deja lo anterior como estaba), la orden es idempotente y ``precios/`` no cambia.

La última prueba lleva ``@pytest.mark.datos`` y se salta si falta la base real del corpus (como el resto del tema):
cura unos pocos tickers reales en una carpeta temporal y, si ya existen, mira las tablas reales.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, curada_precios, visibilidad
from ingesta.mercados_series.contrato import COLUMNAS_PRECIOS, primera_decision_vec

CORTE = curada_precios.CORTE_G2
RELLENO = pd.Timestamp("2026-09-07")         # Labor Day: NYSE cerrada
CERRADO_CON_MOVIMIENTO = pd.Timestamp("2026-07-03")
PLANA_SIN_VOLUMEN = pd.Timestamp("2026-08-10")
PLANA_CON_VOLUMEN = pd.Timestamp("2026-08-11")
NORMAL = pd.Timestamp("2026-08-12")
META_VACIA = pd.DataFrame(columns=["proveedor", "ticker", "clase", "mercado", "tipo_yahoo"]).set_index(
    ["proveedor", "ticker"])


def _precios(ticker: str, semilla: int = 0, dividendo_relleno: float = 0.0, sin_apertura: bool = False) -> pd.DataFrame:
    """Tabla del contrato (as-traded) con fechas de publicación reales del cierre de la NYSE."""
    rng = np.random.default_rng(semilla)
    ses = pd.bdate_range("2026-06-29", "2026-11-20")
    n = len(ses)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = close * np.exp(rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    vol = np.full(n, 1e6)
    div = np.zeros(n)
    i = ses.get_loc(RELLENO)
    close[i] = close[i - 1]
    open_[i] = high[i] = low[i] = close[i]
    vol[i] = 0.0
    div[i] = dividendo_relleno
    for d, v in ((PLANA_SIN_VOLUMEN, np.nan), (PLANA_CON_VOLUMEN, 5e5)):
        j = ses.get_loc(d)
        open_[j] = high[j] = low[j] = close[j]
        vol[j] = v
    if sin_apertura:                                 # fondo con valor liquidativo: sin apertura ni rango
        open_, high, low = close.copy(), close.copy(), close.copy()
    disp = visibilidad.disponible_cierre_serie(pd.Series(ses), "XNYS")
    df = pd.DataFrame({
        "ticker": ticker, "sesion": ses, "mercado": "XNYS", "open": open_, "high": high, "low": low,
        "close": close, "volume": vol, "dividendo": div, "split": 1.0, "divisa": "USD",
        "fecha_publicacion": primera_decision_vec(disp).to_numpy(), "disponible_utc": disp.to_numpy(),
        "fuente": "sintetico", "descargado": pd.Timestamp("2026-11-21", tz="UTC")})
    return df[list(COLUMNAS_PRECIOS)]


LISTA = {"AAA": {"decision": "queda"}, "BBB": {"decision": "queda", "aviso": "serie sospechosa"},
         "ZZZ": {"decision": "fuera"}}


@pytest.fixture
def entorno(tmp_path):
    origen = tmp_path / "precios"
    for k, tk in enumerate(("AAA", "BBB", "ZZZ")):
        almacen.escribir_precios(_precios(tk, semilla=k, dividendo_relleno=0.5 if tk == "BBB" else 0.0), "yahoo",
                                 ruta=origen / "yahoo")
    return {"origen": origen, "destino": tmp_path / "corpus" / "precios_curados", "tablas": tmp_path / "tablas"}


def _curar(e, **kw):
    return curada_precios.curar_precios(e["origen"], e["destino"], e["tablas"], kw.pop("lista", LISTA),
                                        meta=META_VACIA, registro=None, **kw)


def _leer(e, tk):
    return curada_precios.leer_precios_curados(tk, "yahoo", raiz=e["destino"])


def _bytes(carpeta):
    return {p.relative_to(carpeta).as_posix(): p.read_bytes() for p in sorted(carpeta.rglob("*")) if p.is_file()}


def test_quita_la_vela_de_relleno_y_deja_la_que_se_mueve(entorno):
    r = _curar(entorno)
    assert r["ok"], r["verificaciones"]
    c = _leer(entorno, "AAA")
    assert RELLENO not in set(c["sesion"])
    assert CERRADO_CON_MOVIMIENTO in set(c["sesion"])             # día cerrado con movimiento: solo aviso
    av = r["avisos"].set_index(["ticker", "tipo"])
    assert av.loc[("AAA", "sesion_fuera_calendario_relleno"), "accion"] == "quitada"
    assert av.loc[("AAA", "sesion_fuera_calendario_relleno"), "n"] == 1
    assert av.loc[("AAA", "sesion_fuera_calendario"), "accion"] == "solo aviso"
    res = r["resumen"].set_index("ticker")
    assert res.loc["AAA", "velas_quitadas"] == 1
    assert res.loc["AAA", "sesiones_despues"] == res.loc["AAA", "sesiones_antes"] - 1 - res.loc["AAA", "fuera_corte"]


def test_anula_la_apertura_de_relleno_sin_tocar_el_cierre(entorno):
    r = _curar(entorno)
    o = almacen.leer_precios("AAA", "yahoo", ruta=entorno["origen"] / "yahoo").set_index("sesion")
    c = _leer(entorno, "AAA").set_index("sesion")
    for d in (PLANA_SIN_VOLUMEN, PLANA_CON_VOLUMEN):              # la regla exacta del EDA: con o sin volumen
        assert c.loc[d, ["open", "high", "low"]].isna().all()
        assert c.loc[d, "close"] == o.loc[d, "close"]
        assert c.loc[d, "volume"] == o.loc[d, "volume"] or (np.isnan(c.loc[d, "volume"]) and np.isnan(o.loc[d, "volume"]))
    assert (c.loc[NORMAL, ["open", "high", "low", "close"]] == o.loc[NORMAL, ["open", "high", "low", "close"]]).all()
    assert c["open"].isna().sum() == 2
    assert (c["close"] == o.loc[c.index, "close"]).all()
    av = r["avisos"].set_index(["ticker", "tipo"])
    sin, con = av.loc[("AAA", "apertura_igual_cierre")], av.loc[("AAA", "apertura_igual_cierre_con_volumen")]
    assert sin["accion"] == con["accion"] == "nulo" and sin["n"] == con["n"] == 1
    assert sin["primera"] == "2026-08-10" and con["primera"] == "2026-08-11"
    assert r["resumen"].set_index("ticker").loc["AAA", "aperturas_anuladas"] == 2


def test_avisos_de_apertura_con_volumen_y_sin_apertura(tmp_path):
    origen = tmp_path / "precios"
    almacen.escribir_precios(_precios("AAA"), "yahoo", ruta=origen / "yahoo")
    almacen.escribir_precios(_precios("FND", semilla=7, sin_apertura=True), "yahoo", ruta=origen / "yahoo")
    lista = {"AAA": {"decision": "queda"}, "FND": {"decision": "queda"}}
    r = curada_precios.curar_precios(origen, tmp_path / "precios_curados", tmp_path / "tablas", lista,
                                     meta=META_VACIA, registro=None)
    assert r["ok"], r["verificaciones"]
    av = r["avisos"].set_index(["ticker", "tipo"])
    n = curada_precios.leer_precios_curados("FND", "yahoo", raiz=tmp_path / "precios_curados")
    assert n["open"].isna().all() and n["close"].notna().all()
    assert av.loc[("FND", "apertura_igual_cierre_con_volumen"), "n"] == len(n) - 1   # todas con volumen salvo una
    assert av.loc[("FND", "apertura_igual_cierre"), "n"] == 1
    fila = av.loc[("FND", "sin_apertura")]
    assert fila["accion"] == "solo aviso" and fila["n"] == len(n) and "cierre" in fila["nota"]
    assert ("AAA", "sin_apertura") not in av.index                  # 2 de ~100 sesiones sin open: no
    guardado = pd.read_csv(tmp_path / "tablas" / "precios_curados_avisos.csv")
    assert {"apertura_igual_cierre_con_volumen", "sin_apertura"} <= set(guardado["tipo"])


def test_aviso_no_llega_corte_con_su_motivo(tmp_path):
    """3b-2: un fichero cuyo último dato es anterior a la última sesión de su calendario antes del corte lleva
    ``no_llega_corte`` con el motivo de ``estado_3b.MOTIVOS_REFRESCO``; uno que llega, no."""
    from ingesta.mercados_series import estado_3b

    origen = tmp_path / "precios"
    corto = _precios("NESN.SW")
    almacen.escribir_precios(corto[corto["sesion"] <= "2026-10-13"], "yahoo", ruta=origen / "yahoo")
    almacen.escribir_precios(_precios("AAA"), "yahoo", ruta=origen / "yahoo")
    lista = {"AAA": {"decision": "queda"}, "NESN.SW": {"decision": "queda"}}
    r = curada_precios.curar_precios(origen, tmp_path / "precios_curados", tmp_path / "tablas", lista,
                                     meta=META_VACIA, registro=None)
    assert r["ok"], r["verificaciones"]
    av = r["avisos"].set_index(["ticker", "tipo"])
    fila = av.loc[("NESN.SW", "no_llega_corte")]
    assert fila["primera"] == "2026-10-13" and fila["ultima"] == "2026-11-13" and fila["n"] == 23
    assert estado_3b.MOTIVOS_REFRESCO["NESN.SW"] in fila["nota"]
    assert ("AAA", "no_llega_corte") not in av.index
    # sin calendario del mercado: días L-V; Coinbase publica al día siguiente (retraso 1: el 12 es la última)
    assert curada_precios.ultima_sesion_esperada(None) == pd.Timestamp("2026-11-13")
    assert curada_precios.ultima_sesion_esperada("CRYPTO", retraso_dias=1) == pd.Timestamp("2026-11-12")


def test_corte_g2(entorno):
    r = _curar(entorno)
    c = _leer(entorno, "AAA")
    assert c["fecha_publicacion"].max() <= CORTE
    assert c["sesion"].max() == CORTE                              # viernes 13: se publica ese día a las 16:30 NY
    res = r["resumen"].set_index("ticker")
    assert res.loc["AAA", "fuera_corte"] == 5                      # del 16 al 20 de noviembre
    assert res.loc["AAA", "hasta"] == "2026-11-13" and res.loc["AAA", "hasta_original"] == "2026-11-20"


def test_ticker_fuera_no_se_copia(entorno):
    r = _curar(entorno)
    assert r["tickers"] == 2 and r["queda"] == 2
    assert not curada_precios.ruta_precios_curados("yahoo", "ZZZ", entorno["destino"]).exists()
    assert curada_precios.ruta_precios_curados("yahoo", "AAA", entorno["destino"]).exists()
    assert "ZZZ" not in set(r["resumen"]["ticker"]) and "ZZZ" not in set(r["avisos"]["ticker"])
    assert r["avisos"].set_index(["ticker", "tipo"]).loc[("BBB", "aviso_lista"), "nota"] == "serie sospechosa"


def test_relleno_con_dividendo_se_conserva(entorno):
    r = _curar(entorno)
    c = _leer(entorno, "BBB")
    assert RELLENO in set(c["sesion"])
    assert c.set_index("sesion").loc[RELLENO, "dividendo"] == 0.5
    av = r["avisos"].set_index(["ticker", "tipo"])
    assert av.loc[("BBB", "relleno_con_evento"), "accion"] == "solo aviso"
    assert ("BBB", "sesion_fuera_calendario_relleno") not in av.index


def test_verificacion_que_falla_no_publica_nada(entorno, monkeypatch):
    assert _curar(entorno)["ok"]
    antes = _bytes(entorno["destino"])
    tablas_antes = {n: (entorno["tablas"] / n).read_bytes() for n in ("precios_curados_avisos.csv",
                                                                       "precios_curados_resumen.csv")}
    original = curada_precios.curar_ticker

    def roto(p, *a, **k):                                          # un error al montar la tabla: cambia un cierre
        r = original(p, *a, **k)
        r.curado.loc[r.curado.index[0], "close"] *= 1.01
        return r

    monkeypatch.setattr(curada_precios, "curar_ticker", roto)
    r = _curar(entorno)
    assert not r["ok"]
    ver = pd.read_csv(entorno["tablas"] / "precios_curados_verificaciones.csv").set_index("verificacion")
    assert ver.loc["close_intacto", "estado"] == "fallo" and ver.loc["close_intacto", "n_fallos"] == 2
    assert ver.loc["fechas_intactas", "estado"] == "ok"
    assert _bytes(entorno["destino"]) == antes                     # lo anterior, tal cual
    assert {n: (entorno["tablas"] / n).read_bytes() for n in tablas_antes} == tablas_antes
    assert not list(entorno["destino"].parent.glob("precios_curados.*"))


def test_recuento_que_no_cuadra_no_publica(entorno):
    lista = {**LISTA, "SINFICHERO": {"decision": "queda"}}
    r = _curar(entorno, lista=lista)
    assert not r["ok"]
    ver = r["verificaciones"].set_index("verificacion")
    assert ver.loc["recuento_tickers", "estado"] == "fallo" and ver.loc["queda_sin_fichero", "estado"] == "fallo"
    assert not entorno["destino"].exists()


def test_idempotente_y_sin_tocar_el_origen(entorno):
    origen_antes = _bytes(entorno["origen"])
    r1 = _curar(entorno)
    b1 = _bytes(entorno["destino"])
    t1 = _bytes(entorno["tablas"])
    r2 = _curar(entorno)
    assert r1["ok"] and r2["ok"]
    assert _bytes(entorno["destino"]) == b1 and _bytes(entorno["tablas"]) == t1
    assert _bytes(entorno["origen"]) == origen_antes
    assert not list(entorno["destino"].parent.glob("precios_curados.*"))     # ni temporales ni previas
    assert set(r2["verificaciones"]["estado"]) <= {"ok", "no aplica"}
    assert not (set(r2["avisos"].columns) | set(r2["resumen"].columns)) & {"open", "high", "low", "close", "volume"}


def test_misma_ruta_que_almacen_curada():
    for pv, tk in (("yahoo", "^GSPC"), ("coinbase", "cb:BTC-USD")):
        ruta = almacen.ruta_precios(pv, tk, curada=True)
        assert curada_precios.ruta_precios_curados(pv, tk) == ruta
        assert ruta.parent.parent == curada_precios.ruta_curados()


def test_solo_no_escribe_en_el_corpus():
    with pytest.raises(ValueError, match="solo"):
        curada_precios.curar_precios(solo=["AAPL"], registro=None)


# --- Datos reales -------------------------------------------------------------------------------
@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series().exists(), reason="falta la base real (construir-base --sin-red)")
def test_precios_curados_reales(tmp_path):
    if not almacen.tickers_guardados("yahoo"):
        pytest.skip("faltan los precios de Yahoo en el corpus")
    tickers = ["AAPL", "^GSPC", "SGRO.L", "cb:BTC-USD"]
    r = curada_precios.curar_precios(destino=tmp_path / "precios_curados", tablas=tmp_path / "tablas", solo=tickers,
                                     registro=None)
    assert r["ok"], r["verificaciones"]
    assert r["tickers"] == 4 and r["por_proveedor"] == {"coinbase": 1, "yahoo": 3}
    for tk in tickers:
        pv = "coinbase" if tk.startswith("cb:") else "yahoo"
        c = curada_precios.leer_precios_curados(tk, pv, raiz=tmp_path / "precios_curados")
        o = almacen.leer_precios(tk, pv).set_index("sesion")
        assert c["fecha_publicacion"].max() <= CORTE
        # Saneado (P28 y P11): las sesiones añadidas son rellenos de huecos y las de cierre cambiado, picos
        # corregidos; el resto del cierre, intacto.
        avisos_tk = r["avisos"][r["avisos"]["ticker"] == tk].set_index("tipo")
        propias = c[c["sesion"].isin(o.index)]
        assert len(c) - len(propias) == (avisos_tk.loc["relleno_ffill", "n"] if "relleno_ffill" in avisos_tk.index
                                         else 0)
        distinto = propias["close"].to_numpy() != o.loc[propias["sesion"], "close"].to_numpy()
        assert distinto.sum() == (r["resumen"].set_index("ticker").loc[tk, "picos_corregidos"])
    res = r["resumen"].set_index("ticker")
    assert res.loc["SGRO.L", "velas_quitadas"] > 0 and res.loc["^GSPC", "aperturas_anuladas"] > 0
    # Tablas reales del paso 4, si ya se generaron
    tablas = resultados_dir(curada_precios.TEMA) / "tablas"
    if (tablas / "precios_curados_resumen.csv").exists():
        ver = pd.read_csv(tablas / "precios_curados_verificaciones.csv")
        assert set(ver["estado"]) <= {"ok", "no aplica"}
        resumen = pd.read_csv(tablas / "precios_curados_resumen.csv")
        queda = [tk for tk, e in curada_precios.cargar_lista_precios().items() if e.get("decision") == "queda"]
        assert sorted(resumen["ticker"]) == sorted(queda)
        assert pd.to_datetime(resumen["hasta"]).max() <= CORTE
        avisos = pd.read_csv(tablas / "precios_curados_avisos.csv")
        assert list(avisos.columns) == list(curada_precios.COLUMNAS_AVISOS)
        assert set(avisos["accion"]) <= {"quitada", "nulo", "solo aviso", "relleno", "corregido", "split registrado"}
