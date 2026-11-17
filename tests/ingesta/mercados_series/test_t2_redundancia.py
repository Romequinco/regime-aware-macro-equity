"""Paso 2 del Tema 1 · redundancia (``ingesta.mercados_series.redundancia``).

Unitarios con datos sintéticos: pares casi iguales, frecuencias que no se mezclan, anuales fuera de
la correlación, regla de alias (componente conexo, estrella frente a transitiva, Spearman frente a
un único atípico), correlación semanal entre husos, regla de cambios por unidad, conceptos y
tickers. El test ``@pytest.mark.datos`` genera las tablas sobre la base real (se salta si falta
``<corpus>/mercados_series/series/base_series.parquet``) y comprueba sus columnas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import almacen
from ingesta.mercados_series import redundancia as r


def _largo(series: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.concat([pd.DataFrame({"serie": k, "fecha_referencia": v.index, "valor": v.to_numpy()})
                      for k, v in series.items()], ignore_index=True)


def _meta(filas: dict[str, tuple[str, str, str]]) -> pd.DataFrame:
    """``serie → (frecuencia, unidad, fuente)`` con inicio, n_obs y regla."""
    m = pd.DataFrame([{"serie": s, "frecuencia": f, "unidad": u, "fuente": fu} for s, (f, u, fu) in filas.items()])
    m = m.set_index("serie")
    m["regla"] = m["unidad"].map(r.regla_cambio)
    m["inicio"] = pd.Timestamp("2000-01-01")
    m["n_obs"] = 100
    return m


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(7)


def test_regla_de_cambios_por_unidad():
    assert r.regla_cambio("% anual") == "diferencia"
    assert r.regla_cambio("puntos porcentuales") == "diferencia"
    assert r.regla_cambio("índice de difusión") == "diferencia"
    assert r.regla_cambio("índice (0 = estrés medio)") == "diferencia"
    assert r.regla_cambio("tanto por uno anual") == "diferencia"
    assert r.regla_cambio("% (rentabilidad diaria)") == "rentabilidad"
    assert r.regla_cambio("puntos de índice") == "log"
    assert r.regla_cambio("miles de personas") == "log"
    assert r.regla_cambio("USD por 1 EUR") == "log"
    s = pd.Series([100.0, 110.0, 99.0])
    c, regla = r.cambios(s, "log")
    assert regla == "log" and np.isclose(c.iloc[1], np.log(1.1))
    c, regla = r.cambios(pd.Series([1.0, -2.0, 3.0]), "log")      # nivel con negativos → diferencia
    assert regla == "diferencia" and c.iloc[1] == -3.0
    c, regla = r.cambios(pd.Series([0.5, 0.7]), "rentabilidad")    # ya es un cambio: tal cual
    assert regla == "rentabilidad" and list(c) == [0.5, 0.7]


def test_dos_series_casi_iguales_salen_como_par(rng):
    fechas = pd.bdate_range("2010-01-01", periods=1500)
    a = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(fechas)))), index=fechas)
    b = a * np.exp(rng.normal(0, 0.0005, len(fechas)))          # casi igual
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(fechas)))), index=fechas)   # independiente
    largo = _largo({"x:A": a, "y:B": b, "x:C": c})
    meta = _meta({"x:A": ("diaria", "puntos de índice", "x"), "y:B": ("diaria", "puntos de índice", "y"),
                   "x:C": ("diaria", "puntos de índice", "x")})
    pares = r.pares_base(largo, meta)
    assert len(pares) == 1
    fila = pares.iloc[0]
    assert {fila["serie_a"], fila["serie_b"]} == {"x:A", "y:B"}
    assert fila["pearson"] > 0.98 and fila["spearman"] > 0.95 and fila["anios_solape"] >= 3


def test_distinta_frecuencia_nunca_se_compara_y_las_anuales_no_entran(rng):
    dias = pd.bdate_range("2005-01-03", periods=2600)
    d = pd.Series(np.cumsum(rng.normal(0, 0.1, len(dias))) + 5, index=dias)
    meses = pd.date_range("2005-01-01", periods=120, freq="MS")
    m = d.reindex(meses, method="ffill").bfill()                  # el mismo dato, mensual
    anios = pd.date_range("1960-01-01", periods=60, freq="YS")
    an = pd.Series(np.cumsum(rng.normal(0, 1, len(anios))), index=anios)
    largo = _largo({"a:D": d, "a:D2": d + 0.0, "b:M": m, "c:Y1": an, "d:Y2": an + 0.0})
    meta = _meta({"a:D": ("diaria", "% anual", "a"), "a:D2": ("diaria", "% anual", "a"),
                  "b:M": ("mensual", "% anual", "b"), "c:Y1": ("anual", "% anual", "c"),
                  "d:Y2": ("anual", "% anual", "d")})
    pares = r.pares_base(largo, meta)
    nombres = set(pares["serie_a"]) | set(pares["serie_b"])
    assert list(zip(pares["serie_a"], pares["serie_b"])) == [("a:D", "a:D2")]
    assert "b:M" not in nombres                                    # la mensual no se cruza con la diaria
    assert not nombres & {"c:Y1", "d:Y2"}                          # anuales idénticas: fuera de la correlación


def test_periodo_casa_principio_y_fin_de_mes():
    inicio = r.a_periodo(pd.Series(pd.to_datetime(["2020-01-01", "2020-01-31"])), "mensual")
    assert inicio[0] == inicio[1] == pd.Timestamp("2020-01-01")
    assert r.a_periodo(pd.Series(pd.to_datetime(["2020-02-15"])), "trimestral")[0] == pd.Timestamp("2020-01-01")


def test_alias_por_componente_conexo_se_queda_la_de_mas_historia():
    pares = pd.DataFrame({"serie_a": ["A", "B", "D"], "serie_b": ["B", "C", "E"], "pearson": [0.99, -0.97, 0.91],
                          "spearman": [0.98, -0.96, 0.90], "anios_solape": [12.0, 4.0, 20.0],
                          "misma_fuente": [False, True, False]})
    meta = pd.DataFrame({"inicio": pd.to_datetime(["1990-01-01", "1980-01-01", "2000-01-01", "1970-01-01",
                                                   "1970-01-01"]),
                         "n_obs": [10, 10, 10, 5, 50], "fuente": ["f1", "f2", "f2", "f3", "f3"],
                         "frecuencia": ["diaria"] * 5}, index=list("ABCDE"))
    assert r.contar_alias(pares, meta, 0.95, 3) == {"A": "B", "C": "B"}   # A~B~C: un componente; B es la más antigua
    assert r.contar_alias(pares, meta, 0.95, 5) == {"A": "B"}             # B-C con 4 años de solape no llega
    assert r.contar_alias(pares, meta, 0.90, 3)["D"] == "E"               # empate de inicio: más observaciones
    sens = r.tabla_sensibilidad(pares, meta, umbrales=(0.95,), solapes=(3,))
    total = sens[sens["fuente"] == "total"].iloc[0]
    assert total["n_alias_estrella"] == 2 and total["n_alias_estrella_entre_fuentes"] == 1
    assert sens.set_index("fuente").at["f2", "n_alias_estrella"] == 1


def test_cadena_sin_par_directo_no_es_alias_en_estrella():
    # A~B y B~C sin par A-C; A es la de más historia.
    pares = pd.DataFrame({"serie_a": ["A", "B"], "serie_b": ["B", "C"], "pearson": [0.97, 0.97],
                          "spearman": [0.96, 0.96], "anios_solape": [10.0, 10.0], "misma_fuente": [False, False]})
    meta = pd.DataFrame({"inicio": pd.to_datetime(["1970-01-01", "1980-01-01", "1990-01-01"]), "n_obs": [9, 9, 9],
                         "fuente": ["f1", "f2", "f3"], "frecuencia": ["mensual"] * 3}, index=list("ABC"))
    assert r.contar_alias(pares, meta, 0.95, 3, regla="estrella") == {"B": "A"}
    assert r.contar_alias(pares, meta, 0.95, 3, regla="transitiva") == {"B": "A", "C": "A"}
    sens = r.tabla_sensibilidad(pares, meta, umbrales=(0.95,), solapes=(3,))
    total = sens[sens["fuente"] == "total"].iloc[0]
    assert (total["n_alias_estrella"], total["n_alias_transitivo"]) == (1, 2)


def test_un_unico_atipico_no_basta_para_alias(rng):
    dias = pd.bdate_range("2010-01-01", periods=2000)
    a, b = rng.normal(0, 1, len(dias)), rng.normal(0, 1, len(dias))
    a[1000], b[1000] = 300.0, -300.0                               # el «COVID»: un salto común enorme
    ancho = pd.DataFrame({"x:A": a, "y:B": b}, index=dias)
    pares = r.pares_correlados(ancho, "diaria")
    assert len(pares) == 1 and abs(pares.at[0, "pearson"]) >= 0.95 and abs(pares.at[0, "spearman"]) < 0.5
    assert bool(r.outlier_dominado(pares).iloc[0])
    pares["misma_fuente"] = False
    meta = pd.DataFrame({"inicio": pd.to_datetime(["2000-01-01"] * 2), "n_obs": [1, 1], "fuente": ["x", "y"],
                         "frecuencia": ["diaria"] * 2}, index=["x:A", "y:B"])
    assert r.contar_alias(pares, meta, 0.95, 3) == {}


def test_desfase_de_huso_lo_recoge_la_correlacion_semanal(rng):
    # Misma noticia: A fija a media sesión (la segunda mitad le llega al día siguiente), B al cierre.
    dias = pd.bdate_range("2010-01-04", periods=2600)
    h1, h2 = rng.normal(0, 1, len(dias)), rng.normal(0, 1, len(dias))
    ancho = pd.DataFrame({"bce:A": h1 + np.r_[0.0, h2[:-1]], "fred:B": h1 + h2}, index=dias)
    grupo = pd.Series({"bce:A": "bce|", "fred:B": "fred|"})
    pares = r.pares_correlados(ancho, "diaria", grupo=grupo)
    assert len(pares) == 1
    fila = pares.iloc[0]
    assert fila["base_correlacion"] == "semanal" and fila["pearson_diaria"] < 0.6 and fila["pearson"] >= 0.85
    assert r.pares_correlados(ancho, "diaria").empty               # sin grupos (misma fuente): solo la diaria


def test_componentes_y_conceptos():
    assert r.componentes([("a", "b"), ("c", "b"), ("x", "y")]) == [{"a", "b", "c"}, {"x", "y"}]
    assert r.concepto_de("fred:DGS10") == r.concepto_de("ust:PAR.10Y") == ("bono_gobierno_10Y", "USA")
    assert r.concepto_de("fred:DTB3") == r.concepto_de("fred:DGS3MO") == ("bono_gobierno_3M", "USA")
    assert r.concepto_de("wb:USA.FP.CPI.TOTL.ZG") == r.concepto_de("oecd:CP.USA") == ("inflacion_ipc", "USA")
    assert r.concepto_de("eurostat:une_rt_m.M.SA.TOTAL.PC_ACT.T.EA21") == ("paro", "EA")
    assert r.concepto_de("ff:F5D.Mkt-RF") == ("ff_Mkt-RF", "USA")
    assert r.concepto_de("fred:VIXCLS") is None
    assert r.pais_indicador("imf:WEO.USA.LUR.PROY.H2") == ("imf_weo", "USA", "LUR.PROY.H2")
    assert r.motivo_alcance("DE") == "G7; zona euro" and r.motivo_alcance("BRA") == ""


def test_grupos_de_concepto_por_regla_y_duplicado_de():
    meta = pd.DataFrame({
        "nombre": ["Tesoro 10", "Curva 10", "Copia", "Otra"], "id_origen": ["DGS10", "PAR.10Y", "x", "y"],
        "fuente": ["fred_alfred", "ust_curva", "datahub", "otra"], "duplicado_de": ["", "", "fred:GS10", ""],
        "es_proyeccion": [False, False, False, False]},
        index=["fred:DGS10", "ust:PAR.10Y", "datahub:COPIA", "fred:GS10"])
    g = r.grupos_concepto(meta)
    assert set(g["serie"]) == {"fred:DGS10", "ust:PAR.10Y", "fred:GS10", "datahub:COPIA"}
    assert g["grupo"].nunique() == 1                               # regla 10Y + duplicado_de los une
    assert "duplicado_de" in g.set_index("serie").at["datahub:COPIA", "detectado_por"]


def test_correlacion_de_concepto_a_la_frecuencia_mas_baja(rng):
    meses = pd.date_range("2000-01-01", periods=240, freq="MS")
    nivel = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.002, 0.003, len(meses)))), index=meses)
    tasa_anual = (100 * np.log(nivel).diff(12)).groupby(meses.year).mean().dropna()
    tasa_anual.index = pd.to_datetime([f"{y}-01-01" for y in tasa_anual.index])
    m = r.correlacion_concepto(nivel, tasa_anual, "mensual", "anual", "log", "diferencia", tasa=True)
    assert m["n"] >= r.MIN_N_CONCEPTO and m["pearson"] > 0.9


def test_tickers_sensibilidad_y_grupos_etf(rng):
    metricas = pd.DataFrame({
        "inicio": pd.to_datetime(["1995-01-03", "2005-01-03", "2015-06-01"]),
        "pct_volumen_positivo": [1.0, 0.5, 0.95], "volumen_mediano_ultimo_anio": [2e5, 5e4, 0.0],
        "clase": ["etf", "indice", "accion"], "mercado": ["ARCX", "XNYS", "XNYS"]}, index=["A", "B", "C"])
    t = r.tabla_tickers_sensibilidad(metricas)
    tot = t[t["desglose"] == "total"].set_index(["inicio_max", "filtro_sesiones_volumen_90", "volumen_mediano_min"])
    assert tot.at[(2000, False, "sin_filtro"), "n_quedan"] == 1
    assert tot.at[(2016, False, "sin_filtro"), "n_quedan"] == 3
    assert tot.at[(2016, True, "sin_filtro"), "n_quedan"] == 2
    assert tot.at[(2016, False, ">10000"), "n_quedan"] == 2
    assert tot.at[(2016, True, ">100000"), "n_quedan"] == 1

    dias = pd.bdate_range("2010-01-01", periods=1200)
    x = rng.normal(0, 0.01, len(dias))
    rent = pd.DataFrame({"SPY": x, "IVV": x + rng.normal(0, 0.0005, len(dias)), "SH": -x,
                         "TLT": rng.normal(0, 0.01, len(dias))}, index=dias)
    info = pd.DataFrame({"bucket": ["rv_eeuu", "rv_eeuu", "", "rf"], "clase": ["etf"] * 4,
                         "origen": ["universo", "universo", "ampliado", "universo"], "mercado": ["ARCX"] * 4,
                         "equivalente_ucits": ["yf:IVV", None, None, None],
                         "inicio": pd.to_datetime(["1993-01-29", "2000-05-19", "2006-06-21", "2002-07-30"])},
                        index=["SPY", "IVV", "SH", "TLT"])
    g = r.grupos_etf(rent, info)
    grupos = g[g["tipo"] == "grupo"]
    assert list(grupos["miembros"]) == ["SPY; IVV"]                # el inverso (SH) no es casi idéntico
    assert "rv_eeuu" in set(g.loc[g["tipo"] == "bucket", "id"])
    ucits = g[g["tipo"] == "ucits"].iloc[0]
    assert ucits["id"] == "SPY~IVV" and ucits["base_correlacion"] == "diaria" and ucits["corr_diaria"] > 0.98


COLUMNAS = {
    "redundancia_pares.csv": {"serie_a", "serie_b", "frecuencia", "fuente_a", "fuente_b", "misma_fuente",
                              "mismo_concepto", "pearson", "spearman", "n", "anios_solape", "base_correlacion",
                              "pearson_diaria", "pearson_semanal", "outlier_dominado"},
    "redundancia_conceptos.csv": {"grupo", "concepto", "pais", "miembros", "fuentes", "frecuencias",
                                  "solape_comun_anios", "corr_min"},
    "redundancia_sensibilidad.csv": {"umbral", "solape_min_anios", "fuente", "n_alias_estrella", "n_alias_transitivo",
                                     "n_alias_estrella_entre_fuentes", "n_alias_transitivo_entre_fuentes"},
    "redundancia_bm_weo.csv": {"serie", "fuente", "indicador", "pais", "en_alcance_estricto", "miembro_zona_euro",
                               "cubre_2000_referencia",
                               "cubre_2000_publicacion", "duplica_con_mayor_frecuencia", "series_mayor_frecuencia"},
    "redundancia_etf.csv": {"tipo", "id", "miembros", "buckets", "corr_min", "base_correlacion", "corr_diaria",
                            "corr_semanal", "solape_min_anios"},
    "tickers_sensibilidad.csv": {"inicio_max", "filtro_sesiones_volumen_90", "volumen_mediano_min", "desglose",
                                 "grupo", "n_total", "n_quedan"},
}


@pytest.mark.datos
def test_tablas_reales_se_generan_con_sus_columnas(tmp_path):
    if not almacen.ruta_series().exists():
        pytest.skip(f"falta la base real {almacen.ruta_series()} (construir-base --sin-red)")
    if not almacen.tickers_guardados("yahoo"):
        pytest.skip("faltan los precios de Yahoo en el corpus")
    if not (r.resultados_dir(r.TEMA) / "tablas" / "inventario_precios.csv").exists():
        pytest.skip("falta tablas/inventario_precios.csv (python -m ingesta.mercados_series inventario)")
    rutas = r.main(["--destino", str(tmp_path), "--max-tickers", "60"])
    assert set(rutas) == set(COLUMNAS)
    for nombre, columnas in COLUMNAS.items():
        df = pd.read_csv(rutas[nombre])
        assert columnas <= set(df.columns), (nombre, columnas - set(df.columns))
        if nombre != "redundancia_etf.csv":                        # con 60 tickers puede no haber 2 ETF
            assert len(df) > 0, nombre
    pares = pd.read_csv(rutas["redundancia_pares.csv"])
    assert (pares["pearson"].abs() >= r.UMBRAL_PARES).all() and (pares["anios_solape"] >= r.SOLAPE_PARES).all()
    assert "anual" not in set(pares["frecuencia"])
    assert "valor" not in set().union(*(pd.read_csv(p, nrows=1).columns for p in rutas.values()))
