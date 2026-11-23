"""Tests del catálogo para los agentes y de ``buscar_series`` (``ingesta.mercados_series.catalogo_agentes``).

La mayoría lee la tabla versionada ``results/ingesta/mercados_series/tablas/catalogo_agentes.csv`` y la lista curada
del repo: funcionan sin el corpus. Los ``@pytest.mark.datos`` leen el corpus real (base curada, manifiesto y precios
curados, solo lectura) y se saltan si falta, como el resto de tests de datos del tema (``conftest.py``).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from ingesta.comun import rutas
from ingesta.mercados_series import almacen, catalogo_agentes as ca, curada_precios, preprocesado
from ingesta.mercados_series.catalogo_agentes import buscar_series


def _corpus() -> Path:
    # Sin llamar a almacen.corpus_dir (que crea la carpeta): solo se mira.
    return Path(rutas.env("INGESTA_CORPUS_DIR", str(rutas.ROOT / "corpus"))) / "mercados_series"


@pytest.fixture(scope="module")
def cat() -> pd.DataFrame:
    if not ca.RUTA_CSV.exists():
        pytest.fail(f"falta {ca.RUTA_CSV}: python -m ingesta.mercados_series catalogo-agentes")
    return ca.cargar_catalogo()


@pytest.fixture(scope="module")
def lista() -> tuple[set[str], set[str], set[str]]:
    series = preprocesado.cargar_lista()
    precios = curada_precios.cargar_lista_precios()
    return ({s for s, v in series.items() if v["decision"] == "queda"},
            {s for s, v in series.items() if v["decision"] == "proyecciones"},
            {t for t, v in precios.items() if v["decision"] == "queda"})


# --- La tabla ---------------------------------------------------------------------------------------------
def test_csv_columnas_y_sin_valores(cat):
    assert list(cat.columns) == list(ca.COLUMNAS)
    cabecera = pd.read_csv(ca.RUTA_CSV, nrows=0).columns
    assert not set(cabecera) & set(almacen.COLUMNAS_VALORES)
    assert not {"valor", "open", "high", "low", "close", "volume", "dividendo"} & set(pd.read_csv(ca.RUTA_RESUMEN).columns)


def test_csv_cuadra_con_la_lista_curada(cat, lista):
    series, proyecciones, precios = lista
    assert len(series) == 514 and len(precios) == 1494 and len(proyecciones) == 3
    por_tipo = cat.groupby("tipo")["id"].apply(set)
    assert por_tipo["serie"] == series
    assert por_tipo["proyeccion"] == proyecciones
    assert por_tipo["precio"] == precios


def test_ids_unicos_y_campos_obligatorios(cat):
    assert not cat["id"].duplicated().any()
    assert cat["tipo"].isin(ca.TIPOS).all()
    assert cat["tema"].isin(ca.temas()).all()
    for col in ("nombre", "descripcion", "tema", "zona", "agentes", "frecuencia", "unidad", "fuente", "licencia",
                "desde", "primera_publicacion", "palabras_clave"):
        assert cat[col].notna().all(), col
    agentes = cat["agentes"].str.split(ca.SEP)
    assert agentes.map(lambda a: len(a) > 0 and set(a) <= set(ca.AGENTES)).all()
    assert (cat["desde"] <= cat["primera_publicacion"]).all()
    precios = cat["tipo"] == "precio"
    assert cat.loc[precios, "clase"].notna().all() and cat.loc[~precios, "clase"].isna().all()
    assert cat.loc[precios, "retraso_tipico_dias"].isin([0.0, 1.0]).all()
    assert cat.loc[cat["tipo"] == "proyeccion", "retraso_tipico_dias"].isna().all()
    assert cat.loc[cat["tipo"] == "serie", "retraso_tipico_dias"].notna().all()


def test_reglas_de_agentes(cat):
    d = cat.set_index("id")["agentes"].str.split(ca.SEP)
    assert {"macro", "portfolio"} <= set(d["fred:FEDFUNDS"])
    assert {"risk", "cio"} <= set(d["fred:VIXCLS"])
    assert "equity" in d["ff:F3D.HML"] and "equity" in d["AAPL"]
    assert "portfolio" in d["SPY"] and "portfolio" in d["ecb:EXR.D.USD.EUR"]
    assert "macro" in d["ecb:EXR.D.USD.EUR"] and "macro" in d["fred:DEXJPUS"]   # bilaterales también para macro
    assert "risk" in d["fred:BAMLH0A0HYM2"] and "risk" in d["fred:NFCI"] and "cio" in d["fred:NFCI"]


def test_descripciones_y_palabras_a_mano_existen(cat):
    cfg = ca.cargar_config()
    ids = set(cat["id"])
    assert set(cfg["descripciones"]) <= ids
    assert set(cfg["palabras_por_id"]) <= ids
    manual = cat.set_index("id")["descripcion_manual"]
    assert int(manual.sum()) == len(cfg["descripciones"]) >= 50
    assert manual[list(cfg["descripciones"])].all()


def test_resumen_cuadra_con_el_catalogo(cat):
    res = pd.read_csv(ca.RUTA_RESUMEN)
    tipos = res[res["dimension"] == "tipo"].set_index("categoria")["n"]
    assert tipos.to_dict() == cat["tipo"].value_counts().to_dict()
    for dim in ("tema", "zona"):
        assert res.loc[res["dimension"] == dim, "n"].sum() == len(cat)


# --- Normalización ----------------------------------------------------------------------------------------
def test_normalizar():
    assert ca.normalizar("Tipos de Interés") == ["tipo", "de", "interes"]
    assert ca.normalizar("Acciones") == ["accion"]
    assert ca.normalizar("inflación") == ca.normalizar("INFLACION") == ["inflacion"]
    assert ca.normalizar("bonos") == ca.normalizar("bono")
    assert ca.normalizar("estrés") == ["estres"]          # invariable: no se confunde con €STR
    assert ca.normalizar("fred:DGS10") == ["fred", "dgs10"]
    assert ca.normalizar(None) == []


# --- Búsqueda ---------------------------------------------------------------------------------------------
def _ids(texto, fecha="2024-06-28", n=5, **kw):
    return buscar_series(texto, fecha, limite=n, **kw)["id"].tolist()


def test_buscar_columnas_y_orden():
    r = buscar_series("inflación", "2024-06-28", limite=10)
    assert list(r.columns) == list(ca.COLUMNAS_BUSQUEDA)
    assert len(r) == 10
    claves = list(zip(-r["puntuacion"], r["id"], strict=True))
    assert claves == sorted(claves)
    assert (r["puntuacion"] > 0).all()


@pytest.mark.parametrize(("texto", "fecha", "esperado", "n"), [
    ("inflación eurozona", "2026-11-20", "ecb:HICP.M.U2.N.000000.4D0.ANR", 3),
    ("inflación eurozona", "2024-06-28", "eurostat:HICP_EMP.EA", 3),     # el canónico aún no se publicaba
    ("bono 10 años", "2024-06-28", "fred:DGS10", 1),
    ("volatilidad", "2024-06-28", "fred:VIXCLS", 3),
    ("paro", "2024-06-28", "fred:UNRATE", 1),
    ("desempleo", "2024-06-28", "fred:UNRATE", 1),
    ("EURUSD del BCE", "2024-06-28", "ecb:EXR.D.USD.EUR", 1),
    ("spread high yield", "2024-06-28", "fred:BAMLH0A0HYM2", 1),
    ("curva invertida", "2024-06-28", "fred:T10Y2Y", 2),
    ("estrés financiero", "2024-06-28", "ofr:FSI", 3),
    ("DGS10", "2024-06-28", "fred:DGS10", 1),
    ("fred:DGS10", "2024-06-28", "fred:DGS10", 1),
    ("VIX", "2024-06-28", "fred:VIXCLS", 2),
    ("bitcoin", "2024-06-28", "cb:BTC-USD", 1),
    # Verificación del 2026-11-23: consultas que fallaban o salían pobres.
    ("curva 2s10s", "2020-03-16", "fred:T10Y2Y", 1),
    ("spread high yield", "2008-09-15", "HYG", 2),          # antes de 2023 no hay OAS de ICE BofA visible
    ("bund", "2008-09-15", "bbk:BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A", 1),
    ("sentimiento consumidor", "2008-09-15", "fred:UMCSENT", 1),
])
def test_buscar_sinonimos(texto, fecha, esperado, n):
    assert esperado in _ids(texto, fecha, n)


def test_buscar_paro_por_zona():
    r = buscar_series("paro", "2024-06-28", zona="ea", limite=10)
    assert (r["zona"] == "EA").all() and r["id"].iloc[0] == "ecb:LFSI.M.U2.S.UNEHRT.TOTAL0.15_74.T"
    pd.testing.assert_frame_equal(r, buscar_series("paro", "2024-06-28", zona="zona euro", limite=10))
    assert (buscar_series(None, "2024-06-28", zona="de", limite=50)["zona"] == "DE").all()
    assert (buscar_series(None, "2024-06-28", zona="EE. UU.", limite=50)["zona"] == "US").all()


def test_buscar_tema_tolerante():
    a = buscar_series(None, "2024-06-28", tema="tipos_interes", limite=50)
    pd.testing.assert_frame_equal(a, buscar_series(None, "2024-06-28", tema="Tipos de interés", limite=50))
    assert (buscar_series("ipc", "2024-06-28", tema="inflación")["tema"] == "inflacion").all()


def test_buscar_timegate(cat):
    # Con una fecha antigua no aparecen series que empiezan a publicarse después.
    assert "fred:SOFR" in _ids("SOFR", "2024-06-28")
    assert "fred:SOFR" not in _ids("SOFR", "2010-01-01", 50)
    assert "cb:BTC-USD" not in _ids("bitcoin", "2012-01-01", 50)
    assert "ecb:ESTR" not in _ids("€STR", "2019-01-01", 50)
    assert "fred:VIXCLS" not in _ids("vix", "1985-01-01", 50)
    publicada = cat.set_index("id")["primera_publicacion"]
    for fecha in ("1990-01-01", "2000-06-30", "2015-03-02"):
        for tipo in ca.TIPOS:
            r = buscar_series(None, fecha, tipo=tipo, limite=50)
            assert (r["id"].map(publicada) <= fecha).all()
        r = buscar_series("tipos de interés", fecha, limite=50)
        assert (r["id"].map(publicada) <= fecha).all()
    # Ninguna fila con primera_publicacion posterior a la fecha, aunque el texto sea su id exacto.
    futuras = cat[cat["primera_publicacion"] > "2005-01-01"]
    for sid in futuras["id"].head(30):
        assert sid not in _ids(sid, "2005-01-01", 50)


def test_avisos_en_fecha_quita_lo_que_aun_no_se_sabia():
    texto = "uno; historia previa de zz:B [visible desde 2019-10-03]; tres"
    assert ca.avisos_en_fecha(texto, pd.Timestamp("2019-10-02")) == "uno; tres"
    assert ca.avisos_en_fecha(texto, pd.Timestamp("2019-10-03")) == "uno; historia previa de zz:B; tres"
    assert ca.avisos_en_fecha("solo [visible desde 2030-01-01]", pd.Timestamp("2020-01-01")) is None
    assert ca.avisos_en_fecha(None, pd.Timestamp("2020-01-01")) is None
    primeras = {"zz:A": pd.Timestamp("2000-01-01"), "zz:B": pd.Timestamp("2010-05-01")}
    out = ca._etiquetar([("historia previa de zz:B", None, False), ("tramo antes de 2014-01-27", None, False),
                         ("parado el 2026-10-13", None, True), ("retirada", pd.Timestamp("2022-01-01"), False)],
                        primeras["zz:A"], primeras)
    assert out == ("historia previa de zz:B [visible desde 2010-05-01]; tramo antes de 2014-01-27; "
                   "parado el 2026-10-13 [visible desde 2026-10-13]; retirada [visible desde 2022-01-01]")


def test_buscar_timegate_de_avisos_y_desde(cat):
    """Los avisos que revelan el futuro (retirada, sucesora, canónico posterior, equivalente UCITS aún sin lanzar)
    no salen antes de tiempo, y ``desde`` es el de la historia ya publicada."""
    def ficha(texto, fecha):
        r = buscar_series(texto, fecha, limite=1)
        return r.iloc[0]
    eonia = ficha("ecb:EONIA", "2016-06-24")
    assert eonia["id"] == "ecb:EONIA" and "ESTR" not in str(eonia["avisos"]) and "retirada" not in str(eonia["avisos"])
    assert "retirada" in ficha("ecb:EONIA", "2023-06-01")["avisos"]
    assert "CSPX.L" not in str(ficha("SPY", "2005-01-03")["avisos"]) and "CSPX.L" in ficha("SPY", "2016-01-04")["avisos"]
    assert "[visible desde" not in "".join(buscar_series(None, "2026-11-20", limite=50)["avisos"].dropna())
    ampliadas = cat[cat["desde_completo_en"].notna()].set_index("id")
    sid = "fred:CPIAUCSL"
    assert sid in ampliadas.index
    antes = pd.Timestamp(ampliadas.at[sid, "desde_completo_en"]) - pd.Timedelta(days=1)
    assert ficha(sid, antes.date().isoformat())["desde"] == ampliadas.at[sid, "desde_inicial"]
    assert ficha(sid, "2026-11-20")["desde"] == ampliadas.at[sid, "desde"]
    # En el CSV, todo aviso que nombra un id del catálogo publicado después que la fila lleva su etiqueta.
    primera = cat.set_index("id")["primera_publicacion"]
    for _, f in cat[cat["avisos"].notna()].iterrows():
        for a in f["avisos"].split("; "):
            if "[visible desde" in a:
                continue
            for t in ca._PATRON_ID.findall(a):
                t = t.rstrip(".,;:)")
                assert not (t in primera.index and primera[t] > f["primera_publicacion"]), (f["id"], a)


def test_buscar_determinista():
    a = buscar_series("inflación eurozona", "2024-06-28", limite=20)
    ca._indice_cache.cache_clear()
    ca._catalogo_csv_cache.cache_clear()
    b = buscar_series("inflación eurozona", "2024-06-28", limite=20)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(buscar_series(None, "2024-06-28", agente="cio", limite=50),
                                  buscar_series("", "2024-06-28", agente="cio", limite=50))


def test_buscar_sin_texto_filtra_y_ordena_por_id():
    r = buscar_series(None, "2024-06-28", tema="condiciones_financieras", limite=50)
    assert (r["tema"] == "condiciones_financieras").all() and len(r) > 5
    assert r["id"].tolist() == sorted(r["id"]) and (r["puntuacion"] == 0).all()
    r = buscar_series(None, "2024-06-28", agente="portfolio", tipo="precio", limite=50)
    assert r["agentes"].str.split(ca.SEP).map(lambda a: "portfolio" in a).all()
    assert len(buscar_series(None, "2024-06-28", limite=50)) == 50


def test_buscar_errores():
    with pytest.raises(TypeError):
        buscar_series("paro")
    with pytest.raises(ValueError):
        buscar_series("paro", "2024/06/28")
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", limite=0)
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", limite=51)
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", tema="no_existe")
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", agente="trader")
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", tipo="series")
    with pytest.raises(ValueError):
        buscar_series("paro", "2024-06-28", zona="MARTE")


# --- CLI --------------------------------------------------------------------------------------------------
def test_cli_catalogo_agentes(monkeypatch):
    from ingesta.mercados_series import __main__ as cli

    llamadas = []
    monkeypatch.setattr(ca, "main", lambda argv: llamadas.append(argv) or 0)
    assert cli.main(["catalogo-agentes", "--sin-escribir"]) == 0
    assert cli.main(["catalogo-agentes"]) == 0
    assert llamadas == [["--sin-escribir"], []]


# --- Contra el corpus real (solo lectura) -----------------------------------------------------------------
@pytest.fixture(scope="module")
def corpus() -> Path:
    c = _corpus()
    if not (c / "series" / almacen.FICHERO_SERIES_CURADA).exists():
        pytest.skip(f"falta la base curada en {c} (python -m ingesta.mercados_series curar)")
    return c


@pytest.mark.datos
def test_csv_cuadra_con_la_curada_real(cat, corpus):
    series = set(pc.unique(pq.read_table(corpus / "series" / almacen.FICHERO_SERIES_CURADA,
                                         columns=["serie"])["serie"]).to_pylist())
    proy = set(pc.unique(pq.read_table(corpus / "series" / almacen.FICHERO_PROYECCIONES,
                                       columns=["serie"])["serie"]).to_pylist())
    manifiesto = json.loads((corpus / "series" / "curada_manifiesto.json").read_text(encoding="utf-8"))
    assert manifiesto["resumen"]["series_curada"] == len(series) == 514
    tickers = {t for prov in ("yahoo", "coinbase")
               for t in almacen.tickers_guardados(prov, corpus / almacen.CARPETA_PRECIOS_CURADOS / prov)}
    assert len(tickers) == 1494
    por_tipo = cat.groupby("tipo")["id"].apply(set)
    assert por_tipo["serie"] == series and por_tipo["proyeccion"] == proy and por_tipo["precio"] == tickers


@pytest.mark.datos
def test_csv_al_dia_con_el_corpus(cat, corpus, tmp_path):
    """El CSV versionado es el que sale hoy de construir_catalogo (regenerar con catalogo-agentes si falla)."""
    nuevo = ca.construir_catalogo()
    ruta = almacen.escribir_csv_atomico(nuevo, tmp_path / "catalogo_agentes.csv")
    pd.testing.assert_frame_equal(ca.cargar_catalogo(ruta), cat)


# --- Nombres de empresa y gemelos serie/precio (2026-11-23) ----------------------------------------------
def test_acciones_con_nombre_de_empresa(cat: pd.DataFrame) -> None:
    acciones = cat[(cat["tipo"] == "precio") & (cat["clase"] == "accion")]
    sin_nombre = acciones["nombre"].str.startswith("Acción ")
    assert sin_nombre.sum() <= 5, acciones.loc[sin_nombre, "id"].tolist()
    assert buscar_series("Apple", "2024-06-28", limite=3)["id"].iloc[0] == "AAPL"
    assert buscar_series("Microsoft", "2024-06-28", limite=3)["id"].iloc[0] == "MSFT"


def test_gemelos_serie_precio_simetricos(cat: pd.DataFrame) -> None:
    gem = cat.dropna(subset=["tambien_como"]).set_index("id")["tambien_como"]
    assert len(gem) > 0
    for i, g in gem.items():
        assert gem.get(g) == i, (i, g)
        assert {i, g} == {f"yf:{i.removeprefix('yf:')}", i.removeprefix("yf:")}


@pytest.mark.parametrize("texto", ["S&P 500", "volatilidad", "nasdaq", "dax", "oro"])
def test_busqueda_sin_gemelos_repetidos(texto: str) -> None:
    for f in ("2008-09-15", "2024-06-28"):
        r = buscar_series(texto, f, limite=50)
        ids = set(r["id"])
        assert not any(g in ids for g in r["tambien_como"].dropna()), (texto, f)
