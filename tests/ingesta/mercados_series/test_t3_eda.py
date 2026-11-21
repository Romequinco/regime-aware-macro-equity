"""Paso 3 de la descarga completa del Tema 1 · ``eda``: cada detector con datos sintéticos (hueco, salto robusto,
ruptura de nivel, cambio de unidad entre vintages, racha plana, escalas raras, fechas raras, salto sin split con y
sin evento, contrasplit, apertura igual al cierre y sesiones de menos) y que ninguna salida lleva valores.

La última prueba lleva ``@pytest.mark.datos`` y se salta si falta ``<corpus>/mercados_series/series/base_series.parquet``:
lee las tablas reales de ``results/.../tablas`` (o las genera si faltan) y comprueba columnas y casos conocidos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen
from ingesta.mercados_series import eda


def _ruido(n: int, semilla: int = 0, escala: float = 0.01) -> np.ndarray:
    return np.random.default_rng(semilla).normal(0, escala, n)


# --- Series -------------------------------------------------------------------------------------
def test_hueco_mensual_con_fechas_de_inicio_y_fin():
    fechas = pd.date_range("2000-01-01", "2003-12-01", freq="MS")
    fechas = fechas[~((fechas >= "2001-03-01") & (fechas <= "2001-07-01"))]     # faltan 5 meses
    h = eda.huecos(fechas, "mensual")
    assert len(h) == 1
    assert h.iloc[0]["periodos"] == 5
    assert h.iloc[0]["desde"] == pd.Timestamp("2001-03-01") and h.iloc[0]["hasta"] == pd.Timestamp("2001-07-01")


def test_hueco_diario_en_dias_laborables_y_corto_no_cuenta():
    dias = pd.bdate_range("2020-01-01", "2020-03-31")
    corto = dias[~dias.isin(pd.bdate_range("2020-02-03", "2020-02-05"))]          # 3 días L-V: no es largo
    assert eda.huecos(corto, "diaria").empty
    largo = dias[~dias.isin(pd.bdate_range("2020-02-03", "2020-02-10"))]          # 6 días L-V
    h = eda.huecos(largo, "diaria")
    assert list(h["periodos"]) == [6]
    assert h.iloc[0]["desde"] == pd.Timestamp("2020-02-03") and h.iloc[0]["hasta"] == pd.Timestamp("2020-02-10")


def test_salto_robusto_marca_solo_el_salto():
    n = 400
    fechas = pd.bdate_range("2015-01-01", periods=n)
    x = 100 * np.exp(np.cumsum(_ruido(n)))
    x[200:] *= 1.5                                                                   # +40 % de golpe
    s = eda.saltos_robustos(fechas, x, log_=True, frecuencia="diaria")
    assert list(s["fecha"]) == [fechas[200]]
    assert s.iloc[0]["desviaciones"] > eda.UMBRAL_MAD
    assert eda.saltos_robustos(fechas[:300], 100 * np.exp(np.cumsum(_ruido(300, 1))), log_=True).empty


def test_salto_en_serie_escalonada_usa_el_escalon_tipico():
    # tipo que cambia 0,25 en pocas fechas y una vez 5 puntos: solo se marca el de 5
    x = np.repeat([1.0, 1.25, 1.5, 1.25, 6.25, 6.0], 50)
    fechas = pd.bdate_range("2010-01-01", periods=len(x))
    s = eda.saltos_robustos(fechas, x)
    assert list(s["fecha"]) == [fechas[200]]


def test_ruptura_de_nivel_por_la_mediana_movil():
    n = 240
    fechas = pd.date_range("1990-01-01", periods=n, freq="MS")
    x = 5 + _ruido(n, 2, 0.1)
    x[120:] += 3.0
    r = eda.rupturas_nivel(fechas, x, "mensual")
    assert len(r) == 1 and abs(r.iloc[0]["fecha"] - fechas[120]) <= pd.Timedelta(days=62)
    assert r.iloc[0]["desviaciones"] > 0
    assert eda.rupturas_nivel(fechas, 5 + _ruido(n, 3, 0.1), "mensual").empty


def test_cambio_de_unidad_entre_vintages():
    refs = pd.date_range("2000-01-01", periods=24, freq="MS")
    v1 = pd.DataFrame({"serie": "fred:X", "fecha_referencia": refs, "vintage": "2010-01-05", "orden_vintage": 1,
                       "valor": np.linspace(1000, 1200, 24)})
    v2 = v1.assign(vintage="2011-01-05", orden_vintage=2, valor=v1["valor"] * 1.01)        # revisión normal
    v3 = v1.assign(vintage="2012-01-05", orden_vintage=3, valor=v1["valor"] / 1000)        # millones -> miles de millones
    c = eda.cambios_unidad(pd.concat([v1, v2, v3], ignore_index=True))
    assert list(c["vintage"]) == ["2012-01-05"]
    assert c.iloc[0]["log10_factor"] == pytest.approx(-3.0, abs=0.01)
    assert eda.cambios_unidad(pd.concat([v1, v2], ignore_index=True)).empty


def test_racha_plana_desde_min_racha():
    fechas = pd.bdate_range("2013-01-01", periods=400)
    x = 1 + np.cumsum(_ruido(400, 4))
    x[100:100 + eda.base_mod.MIN_RACHA] = 0.28
    r = eda.rachas_planas(fechas, x)
    assert len(r) == 1 and r.iloc[0]["obs"] == eda.base_mod.MIN_RACHA
    assert r.iloc[0]["desde"] == fechas[100] and r.iloc[0]["hasta"] == fechas[100 + eda.base_mod.MIN_RACHA - 1]
    x[100 + eda.base_mod.MIN_RACHA - 1] = 0.29                                       # una menos: no cuenta
    assert eda.rachas_planas(fechas, x).empty


def test_escalas_raras_y_no_positivos():
    assert eda.escala_rara(np.full(20, 0.03), "% anual") == "pct_parece_tanto_por_uno"
    assert eda.escala_rara(np.full(20, 3.0), "% anual") is None
    assert eda.escala_rara(np.full(20, 0.0003), "% (tipo del día)") is None
    assert eda.escala_rara(np.full(20, 4.5), "tanto por uno anualizado") == "tanto_por_uno_parece_pct"
    fechas = pd.date_range("2000-01-01", periods=5, freq="MS")
    neg = eda.no_positivos(fechas, [100, 101, -1, 0, 102], "índice (2017 = 100)")
    assert list(neg["obs"]) == [2] and neg.iloc[0]["desde"] == fechas[2]
    assert eda.no_positivos(fechas, [1, -1, 2, 3, 4], "miles de millones de USD").empty   # un saldo puede ser < 0


def test_fechas_raras_fin_de_semana_y_festivo():
    fechas = pd.to_datetime(["2024-12-24", "2024-12-25", "2024-12-28", "2024-12-30"])   # 25 festivo, 28 sábado
    sesiones = np.array(["2024-12-24", "2024-12-26", "2024-12-27", "2024-12-30"], dtype="datetime64[D]")
    f = eda.fechas_raras(fechas, sesiones=sesiones)
    assert set(zip(f["tipo"], f["fecha"])) == {("fin_de_semana", pd.Timestamp("2024-12-28")),
                                                ("festivo", pd.Timestamp("2024-12-25"))}


def test_controles_serie_sin_valores_en_la_salida():
    fechas = pd.bdate_range("2015-01-01", periods=300).to_numpy()
    x = 100 * np.exp(np.cumsum(_ruido(300, 5)))
    x[150:] *= 2
    entrada = {"frecuencia": "diaria", "unidad": "puntos de índice", "fuente": "fred_alfred", "metodo": "cierre_mercado"}
    fila, inc = eda.controles_serie("fred:Y", fechas, x, entrada)
    assert fila["n_saltos"] == 1 and fila["transformacion"] == "log"
    df = pd.DataFrame(inc, columns=list(eda.COLUMNAS_INC_SERIES))
    assert set(df["tipo"]) >= {"salto"} and not (eda.PROHIBIDAS & set(df.columns))
    assert set(df["propuesta_paso4"]) <= set(eda.PROPUESTAS.values()) | {eda.SIN_ACCION}


# --- Precios ------------------------------------------------------------------------------------
def _precios(n: int = 60, close: np.ndarray | None = None) -> pd.DataFrame:
    sesion = pd.bdate_range("2020-01-01", periods=n)
    c = close if close is not None else 50 * np.exp(np.cumsum(_ruido(n, 6)))
    return pd.DataFrame({"sesion": sesion, "mercado": "XNYS", "open": c * 1.001, "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": 1e6, "dividendo": 0.0, "split": 1.0})


def test_salto_sin_split_se_marca_y_con_split_no():
    p = _precios()
    p.loc[30:, ["open", "high", "low", "close"]] /= 2                                 # -50 % sin evento
    s = eda.saltos_sin_split(p)
    assert list(s["sesion"]) == [p.at[30, "sesion"]] and s.iloc[0]["abs_dlog"] == pytest.approx(np.log(2), abs=0.02)
    con_split = p.assign(split=np.where(p.index == 30, 2.0, 1.0))
    assert eda.saltos_sin_split(con_split).empty
    split_dia_siguiente = p.assign(split=np.where(p.index == 31, 2.0, 1.0))          # Yahoo un día tarde
    assert eda.saltos_sin_split(split_dia_siguiente).empty


def test_salto_a_cierre_negativo():
    c = np.r_[np.full(10, 20.0), -37.6, np.full(10, 10.0)]
    s = eda.saltos_sin_split(_precios(21, c))
    assert len(s) == 2 and s["no_positivo"].all() and s["abs_dlog"].isna().all()


def test_contrasplit_y_split_fraccionario_solo_si_no_explica_el_precio():
    # cierre plano: el 1,043 (acción liberada) no se marca porque su residuo es pequeño (|log 1,043| < 0,2);
    # el 1,5 sin caída del precio sí; el 1,5 con el precio dividido por 1,5 no.
    c = np.r_[np.full(4, 30.0), np.full(3, 20.0)]
    p = _precios(7, c).assign(split=[1.0, 0.1, 1.043478, 1.5, 1.5, 1.0, 1.0])
    s = eda.splits_raros(p)
    assert list(zip(s["tipo"], s["sesion"])) == [("contrasplit", p.at[1, "sesion"]),
                                                 ("split_fraccionario", p.at[3, "sesion"])]
    assert s.iloc[0]["abs_dlog"] == pytest.approx(np.log(10), abs=1e-3)
    assert s.iloc[1]["abs_dlog"] == pytest.approx(np.log(1.5), abs=1e-3)
    assert eda.splits_raros(_precios(5).assign(split=[1.0, 1.0, 1.043478, 1.0, 1.0])).empty


def test_velas_de_relleno_fuera_de_calendario_se_cuentan_aparte():
    # el calendario cierra las sesiones 20 y 40; la 20 repite el cierre sin volumen (relleno), la 40 se mueve
    p = _precios(60)
    p.loc[20, "close"] = p.at[19, "close"]
    p.loc[20, "volume"] = 0.0
    p.loc[40, "close"] *= 1.05
    cal = np.delete(np.array(p["sesion"]).astype("datetime64[D]"), [20, 40])
    fila, inc = eda.controles_ticker(p, "TEST", "yahoo", {"clase": "accion"}, sesiones_cal=cal)
    assert fila["sesiones_fuera_calendario"] == 2 and fila["fuera_calendario_relleno"] == 1
    assert fila["cierre_repetido"] == 0 and fila["volumen_cero"] == 0            # el relleno no infla estos
    df = pd.DataFrame(inc, columns=list(eda.COLUMNAS_INC_PRECIOS)).set_index("tipo")
    assert df.at["sesion_fuera_calendario_relleno", "propuesta_paso4"] == "nulo + aviso"
    assert df.at["sesion_fuera_calendario_relleno", "fecha"] == eda._iso(p.at[20, "sesion"])
    assert df.at["sesion_fuera_calendario", "propuesta_paso4"] == "revisar a mano"
    assert df.at["sesion_fuera_calendario", "fecha"] == eda._iso(p.at[40, "sesion"])


def test_serie_sospechosa_por_saltos_repetidos_o_aperturas():
    base = {"saltos_sin_split": 0, "pct_cierre_repetido": 1.0, "pct_apertura_igual_cierre_desde_2000": 0.0,
            "clase": "accion", "mercado": "XNYS"}
    assert eda.motivos_sospecha(base) == []
    assert len(eda.motivos_sospecha({**base, "saltos_sin_split": 21})) == 1
    assert eda.motivos_sospecha({**base, "saltos_sin_split": 20}) == []
    assert len(eda.motivos_sospecha({**base, "pct_cierre_repetido": 45.0})) == 1
    assert len(eda.motivos_sospecha({**base, "pct_apertura_igual_cierre_desde_2000": 60.0})) == 1
    # en un fondo (valor liquidativo) la apertura igual al cierre es normal
    assert eda.motivos_sospecha({**base, "clase": "fondo", "pct_apertura_igual_cierre_desde_2000": 100.0}) == []
    # extremo a extremo: un historial con 25 saltos sin split
    c = 50 * np.exp(np.cumsum(np.where(np.arange(200) % 8 == 4, np.where(np.arange(200) % 16 == 4, 0.6, -0.6),
                                       _ruido(200, 7))))
    fila, inc = eda.controles_ticker(_precios(200, c), "ROTO", "yahoo", {"clase": "accion"},
                                     sesiones_cal=np.array(pd.bdate_range("2020-01-01", periods=200), "datetime64[D]"))
    assert fila["saltos_sin_split"] == 25 and fila["serie_sospechosa"] and "saltos sin split" in fila["motivo_sospecha"]
    assert "serie_sospechosa" in {i["tipo"] for i in inc}


def test_cambio_de_unidad_confirmado_solo_potencia_exacta_con_historia():
    assert eda.es_potencia_confirmada(3.0, 787) and eda.es_potencia_confirmada(-3.01, 301)
    assert not eda.es_potencia_confirmada(3.13, 2)          # RECPROUSM156N: dos fechas
    assert not eda.es_potencia_confirmada(1.2, 500)          # no es potencia de 10
    assert set(eda.PROPUESTAS.values()) | set(eda.EXCEPCIONES_PROPUESTA.values()) <= \
        {"marcar", "nulo + aviso", "revisar a mano", "sin acción", "reescalar vintages anteriores"}


def test_apertura_igual_al_cierre():
    p = _precios(4)
    for col in ("open", "high", "low"):
        p.loc[[1, 3], col] = p.loc[[1, 3], "close"]
    p.loc[3, "high"] += 1                                                             # high != low: no es relleno
    assert list(eda.apertura_igual_cierre(p)) == [False, True, False, False]


def test_sesiones_faltantes_con_calendario_dado():
    cal = np.array(pd.bdate_range("2020-01-01", "2020-01-31")).astype("datetime64[D]")
    ses = pd.bdate_range("2020-01-01", "2020-01-31")
    ses = ses[~ses.isin(pd.to_datetime(["2020-01-15", "2020-01-16"]))].append(pd.DatetimeIndex(["2020-01-18"]))
    r = eda.sesiones_faltantes(ses, "XNYS", sesiones_cal=cal)
    assert len(r["faltan"]) == 2 and len(r["fuera"]) == 1 and r["esperadas"] == len(cal)


def test_controles_ticker_y_resumen_sin_precios():
    p = _precios(80)
    p.loc[40:, ["open", "high", "low", "close"]] *= 2
    p.loc[10, ["open", "high", "low"]] = p.at[10, "close"]
    p.loc[60, "split"] = 0.5
    cal = np.array(pd.bdate_range("2020-01-01", periods=80)).astype("datetime64[D]")
    fila, inc = eda.controles_ticker(p, "TEST", "yahoo", {"clase": "accion"}, sesiones_cal=cal)
    assert fila["saltos_sin_split"] == 1 and fila["contrasplits"] == 1
    assert fila["pct_apertura_igual_cierre"] == pytest.approx(100 / 80, abs=0.01)
    df = pd.DataFrame(inc, columns=list(eda.COLUMNAS_INC_PRECIOS))
    assert {"salto_sin_split", "contrasplit", "apertura_igual_cierre"} <= set(df["tipo"])
    res = eda.resumen(None, df)
    assert set(res.columns) == set(eda.COLUMNAS_RESUMEN)
    assert not (eda.PROHIBIDAS & (set(df.columns) | set(fila) | set(res.columns)))


# --- Tablas reales ------------------------------------------------------------------------------
NOMBRES = {
    "eda_series.csv": eda.COLUMNAS_SERIES_EDA, "eda_series_incidencias.csv": eda.COLUMNAS_INC_SERIES,
    "eda_precios.csv": eda.COLUMNAS_PRECIOS_EDA, "eda_precios_incidencias.csv": eda.COLUMNAS_INC_PRECIOS,
    "eda_resumen.csv": eda.COLUMNAS_RESUMEN,
}


@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series().exists(), reason="falta la base real (construir-base --sin-red)")
def test_tablas_reales_eda(tmp_path):
    tablas = resultados_dir(eda.TEMA) / "tablas"
    if all((tablas / n).exists() for n in NOMBRES):
        rutas = {n: tablas / n for n in NOMBRES}
    else:
        if not almacen.tickers_guardados("yahoo"):
            pytest.skip("faltan los precios de Yahoo en el corpus")
        rutas = eda.main(["--destino", str(tmp_path)])
    t = {n: pd.read_csv(r) for n, r in rutas.items()}
    for n, columnas in NOMBRES.items():
        assert list(t[n].columns) == list(columnas), n
        assert not ({"valor", "close", "open"} & set(t[n].columns)), n
    assert t["eda_series.csv"]["serie"].is_unique and len(t["eda_series.csv"]) >= 1_400
    inc = t["eda_precios_incidencias.csv"]
    saltos = set(inc.loc[inc["tipo"] == "salto_sin_split", "ticker"])
    assert {"AAPL", "NVDA"} & saltos
    assert {"ASML.AS", "CL=F", "SHEL.L", "^VIX"} <= saltos
    assert {"EWJ", "USO", "ETHA"} <= set(inc.loc[inc["tipo"] == "contrasplit", "ticker"])
    # los splits no enteros de XLF (2016) y SAN.MC (scrip) explican el movimiento del precio: no se marcan
    assert not {"XLF", "SAN.MC"} & set(inc.loc[inc["tipo"] == "split_fraccionario", "ticker"])
    assert set(inc["propuesta_paso4"]) | set(t["eda_series_incidencias.csv"]["propuesta_paso4"]) <= \
        {"marcar", "nulo + aviso", "revisar a mano", "sin acción", "reescalar vintages anteriores"}
    assert set(inc["tipo"]) | set(t["eda_series_incidencias.csv"]["tipo"]) <= set(eda.PROPUESTAS)
    assert "salto_calidad" not in set(inc["tipo"])                     # un solo detector por salto
    precios = t["eda_precios.csv"].set_index("ticker")
    sospechosos = set(precios.index[precios["serie_sospechosa"].astype(bool)])
    assert {"MCIC", "DIGI", "CPWR", "COMS", "EP", "USBC", "ULVR.L", "GR"} <= sospechosos
    cu = t["eda_series_incidencias.csv"]
    cu = cu[cu["propuesta_paso4"] == "reescalar vintages anteriores"]
    assert {"fred:BOGMBASE", "fred:REVOLSL", "fred:TOTALSL", "fred:BCNSDODNS", "fred:CMDEBT",
            "fred:TNWBSHNO"} <= set(cu["serie"]) and cu["factor"].notna().all()
