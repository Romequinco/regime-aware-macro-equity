"""Tests del modo curado de las tools (paso 4): ``get_serie``/``get_precios`` con ``base='curada'`` y ``get_proyeccion``.

Unitarios: la base curada, la tabla de alias, la de proyecciones y los precios curados se escriben como
parquet sintéticos en ``tmp_path`` (``almacen`` redirigido, como en ``test_t1_tools.py``), junto a una base
de trabajo distinta, para comprobar que cada modo lee lo suyo con el mismo TimeGate y el mismo truncado.
Sin red. El test ``@pytest.mark.datos`` lee el corpus real y se salta si el paso 4 aún no lo ha escrito.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import almacen, tools
from ingesta.mercados_series import sinteticos as s
from ingesta.mercados_series.almacen import escribir_precios, escribir_series
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, UTC, validar_series
from ingesta.mercados_series.tools import get_precios, get_proyeccion, get_serie

SERIE = s.SERIE_VINTAGES
ALIAS = "sint:PARO_ALIAS"
ESCALA = "sint:ESCALA"
PROY = "sint:WEO.PARO.PROY.H1"
DIARIA = s.SERIE_DIARIA                  # cierre diario de 2023-01-02 a 2025-12-31
DIARIA_MENSUAL = "sint:DIARIA_MENSUAL"   # diaria publicada una vez al mes
RETRASO = pd.Timedelta(days=7)          # retraso conservador de la base curada sintética
CORTE_TRAMO = pd.Timestamp("2024-01-01")
NOTA_NO_MEDIBLE = "fecha no medible: regla conservadora sint (7D)"
NOTA_TRAMO = "tramo conservador antes de 2024-01-01: regla conservadora"
NOTA_ESCALA = "escala corregida: tanto por uno → % (×100, preprocesado.yaml)"
FECHAS = ("2023-06-15", "2024-03-14", "2024-03-15", "2025-01-20", "2025-12-20", "2026-03-01")


@pytest.fixture(autouse=True)
def corpus_en_tmp(request, tmp_path, monkeypatch):
    """Las rutas por defecto del almacén apuntan a ``tmp_path``; salvo en los tests ``datos`` (corpus real)."""
    if request.node.get_closest_marker("datos"):
        return None

    def corpus_dir(tema=None):
        p = tmp_path / "corpus" / tema if tema else tmp_path / "corpus"
        p.mkdir(parents=True, exist_ok=True)
        return p
    monkeypatch.setattr(almacen, "corpus_dir", corpus_dir)
    return tmp_path / "corpus"


# --- Datos sintéticos ----------------------------------------------------------------------------
def _con_nota(nota: pd.Series, extra: str, filas: pd.Series | None = None) -> pd.Series:
    filas = pd.Series(True, index=nota.index) if filas is None else filas
    nueva = nota.where(nota.isna(), nota + "; " + extra).fillna(extra)
    return nueva.where(filas, nota)


def _curar(trabajo: pd.DataFrame) -> pd.DataFrame:
    """Versión curada de la serie de vintages: fechas retrasadas ``RETRASO`` y las notas de la curación."""
    out = trabajo.copy()
    out["fecha_publicacion"] = out["fecha_publicacion"] + RETRASO
    out["disponible_utc"] = pd.Series(pd.NaT, index=out.index, dtype=UTC)
    out["nota"] = _con_nota(out["nota"], NOTA_NO_MEDIBLE)
    out["nota"] = _con_nota(out["nota"], NOTA_TRAMO, out["fecha_referencia"] < CORTE_TRAMO)
    return validar_series(out)


def _serie_escala() -> pd.DataFrame:
    refs = pd.date_range("2024-01-01", periods=4, freq="MS")
    return validar_series(pd.DataFrame({
        "serie": ESCALA, "fecha_referencia": refs, "fecha_publicacion": refs + pd.Timedelta(days=40),
        "disponible_utc": pd.Series(pd.NaT, index=range(4), dtype=UTC), "vintage": "unico",
        "valor": [1.5, 1.7, 1.6, 1.8], "unidad": "% anual", "divisa": None, "fuente": s.FUENTE, "metodo_publicacion": "calendario", "nota": NOTA_ESCALA,
    }))


def _proyecciones() -> pd.DataFrame:
    """Dos ediciones (2024-04 y 2024-10) de una proyección a un año, con años proyectados posteriores."""
    filas = []
    for edicion, publicada, valores in (("2024-04", "2024-04-16", (4.0, 4.2)), ("2024-10", "2024-10-22", (4.1, 4.4))):
        for ref, valor in zip(("2024-01-01", "2025-01-01"), valores, strict=True):
            filas.append({"serie": PROY, "fecha_referencia": pd.Timestamp(ref),
                          "fecha_publicacion": pd.Timestamp(publicada), "disponible_utc": pd.NaT,
                          "vintage": edicion, "valor": valor, "unidad": "% de la población activa", "divisa": None,
                          "fuente": s.FUENTE, "metodo_publicacion": "vintage_exacto", "nota": None,
                          "horizonte": float(pd.Timestamp(ref).year - int(edicion[:4])), "edicion": edicion})
    df = pd.DataFrame(filas).assign(disponible_utc=lambda d: pd.Series(pd.NaT, index=d.index, dtype=UTC))
    return df.astype(COLUMNAS_SERIES | {"horizonte": "float64", "edicion": "string"})


def _precios_curados(accion: pd.DataFrame) -> pd.DataFrame:
    """ZZAC sin sus dos primeras sesiones y con tres aperturas de relleno a nulo (como la curación)."""
    out = accion.iloc[2:].copy()
    out.loc[out.index[10:13], "open"] = np.nan
    return out


def _diaria_publicada_al_mes() -> pd.DataFrame:
    """Serie diaria (sesiones de 2024-01 a 2024-06) que se publica una vez al mes, como los factores de Ken French."""
    refs = pd.bdate_range("2024-01-02", "2024-06-28")
    pub = refs + pd.offsets.MonthEnd(1) + pd.Timedelta(days=5)
    return validar_series(pd.DataFrame({
        "serie": DIARIA_MENSUAL, "fecha_referencia": refs, "fecha_publicacion": pub,
        "disponible_utc": pd.Series(pd.NaT, index=range(len(refs)), dtype=UTC), "vintage": "unico",
        "valor": np.linspace(0.1, 0.2, len(refs)), "unidad": "% diario", "divisa": None, "fuente": s.FUENTE,
        "metodo_publicacion": "calendario", "nota": None,
    }))


@pytest.fixture(scope="module")
def vintages():
    return s.serie_con_vintages()


@pytest.fixture(scope="module")
def accion():
    return s.accion_con_eventos()


@pytest.fixture
def bases(vintages, accion):
    """Base de trabajo (paro y ZZAC tal cual) y base curada (paro curado, escala, alias, proyecciones, ZZAC curado)."""
    escribir_series(vintages)
    escribir_precios(accion, "yahoo")
    curada = pd.concat([_curar(vintages), _serie_escala(), s.serie_mercado_diaria(), _diaria_publicada_al_mes()],
                       ignore_index=True)
    escribir_series(curada, almacen.ruta_series(curada=True))
    pd.DataFrame({"alias": [ALIAS], "canonico": [SERIE], "motivo": ["D8: |Pearson| 0.990 con sint:PARO"],
                  "correlacion": [0.99]}).to_parquet(almacen.ruta_alias(), index=False)
    _proyecciones().to_parquet(almacen.ruta_proyecciones(), index=False)
    precios = _precios_curados(accion)
    escribir_precios(precios, "yahoo", almacen.ruta_precios("yahoo", s.TICKER_ACCION, curada=True).parent)
    return {"curada": curada, "precios": precios}


def _iguales(a: tools.RespuestaSerie | tools.RespuestaPrecios, b) -> None:
    pd.testing.assert_frame_equal(a.datos, b.datos)
    assert a.avisos == b.avisos


# --- get_serie(base='curada') --------------------------------------------------------------------
def test_t4_curada_lee_la_base_curada(bases, vintages):
    # 2024-02 sale en su informe en la de trabajo; en la curada, una semana después.
    mes = pd.Timestamp("2024-02-01")
    sale = vintages.loc[vintages["fecha_referencia"] == mes, "fecha_publicacion"].min()
    trabajo = get_serie(SERIE, sale)
    curada = get_serie(SERIE, sale, base="curada")
    assert trabajo.ultimo()["fecha_referencia"] == "2024-02-01"
    assert curada.ultimo()["fecha_referencia"] == "2024-01-01"
    assert (curada.datos["fecha_publicacion"] <= sale).all()
    despues = get_serie(SERIE, sale + RETRASO, base="curada").ultimo()
    assert despues["fecha_referencia"] == "2024-02-01"
    assert despues["fecha_publicacion"] == (sale + RETRASO).date().isoformat()


@pytest.mark.parametrize("fecha", FECHAS)
def test_t4_curada_truncado(bases, fecha):
    """La respuesta curada en ``fecha`` (datos y avisos) es la misma con la base curada truncada a ``fecha``."""
    f = pd.Timestamp(fecha)
    completa = get_serie(SERIE, fecha, base="curada")
    assert (completa.datos["fecha_publicacion"] <= f).all()
    curada = bases["curada"]
    escribir_series(curada[curada["fecha_publicacion"] <= f], almacen.ruta_series(curada=True), permitir_perdidas=True)
    truncada = get_serie(SERIE, fecha, base="curada")
    _iguales(completa, truncada)
    # Y los datos coinciden con los de la tabla en memoria (mismo TimeGate que el modo trabajo).
    pd.testing.assert_frame_equal(completa.datos, get_serie(SERIE, fecha, base=curada).datos)


@pytest.mark.parametrize("fecha", ("2022-06-01", "2023-06-15", "2024-03-15", "2024-12-31"))
def test_t4_curada_truncado_precios(bases, fecha):
    f = pd.Timestamp(fecha)
    kw = {"ajuste": "total", "divisa": "original"}
    completa = get_precios(s.TICKER_ACCION, fecha, base="curada", **kw)
    assert (completa.datos["fecha_publicacion"] <= f).all()
    precios = bases["precios"]
    fichero = almacen.ruta_precios("yahoo", s.TICKER_ACCION, curada=True)
    fichero.unlink()
    corta = precios[precios["fecha_publicacion"] <= f]
    if len(corta):
        escribir_precios(corta, "yahoo", fichero.parent)
    truncada = get_precios(s.TICKER_ACCION, fecha, base="curada", **kw)
    _iguales(completa, truncada)
    pd.testing.assert_frame_equal(completa.datos, get_precios(s.TICKER_ACCION, fecha, base=precios, **kw).datos)


def test_t4_alias_resuelto_con_aviso(bases):
    r = get_serie(ALIAS, "2025-01-20", base="curada")
    assert r.serie == SERIE
    assert any(f"alias de {SERIE}: se sirve el canónico" in a for a in r.avisos)
    assert r.avisos[0].startswith(repr(ALIAS))
    canonico = get_serie(SERIE, "2025-01-20", base="curada")
    pd.testing.assert_frame_equal(r.datos, canonico.datos)
    assert r.avisos[1:] == canonico.avisos
    assert tools.resolver_id(ALIAS, base="curada") == SERIE
    assert tools.resolver_id(ALIAS) == ALIAS                       # la de trabajo no conoce el alias
    with pytest.raises(KeyError, match="sin datos publicados"):
        get_serie(ALIAS, "2025-01-20")
    # El alias no revela nada del futuro: antes de la primera publicación, el KeyError neutro.
    with pytest.raises(KeyError, match="desconocida o aún no publicada"):
        get_serie(ALIAS, "2023-01-02", base="curada")


def test_t4_proyeccion_no_sale_como_serie(bases):
    with pytest.raises(KeyError, match="get_proyeccion"):
        get_serie(PROY, "2024-05-01", base="curada")
    # Sin nada publicado aún, el mismo mensaje que un id desconocido (no revela que será una proyección).
    with pytest.raises(KeyError) as antes:
        get_serie(PROY, "2024-04-15", base="curada")
    assert "proyección" not in str(antes.value) and "desconocida o aún no publicada" in str(antes.value)


def test_t4_get_proyeccion(bases):
    abril = get_proyeccion(PROY, "2024-05-01")
    assert list(abril.datos["edicion"]) == ["2024-04", "2024-04"]
    assert list(abril.datos["valor"]) == [4.0, 4.2]
    assert list(abril.datos["horizonte"]) == [0.0, 1.0]
    assert "proyección" in abril.avisos[0]
    octubre = get_proyeccion(PROY, "2024-10-22")
    assert list(octubre.datos["edicion"]) == ["2024-10", "2024-10"] and list(octubre.datos["valor"]) == [4.1, 4.4]
    assert (octubre.datos["fecha_publicacion"] <= pd.Timestamp("2024-10-22")).all()
    assert get_proyeccion(PROY, "2024-10-22", desde="2025-01-01").datos["valor"].tolist() == [4.4]
    assert octubre.ultimo()["fecha_referencia"] == "2025-01-01"
    with pytest.raises(KeyError, match="desconocida o aún no publicada"):
        get_proyeccion(PROY, "2024-04-15")


def test_t4_avisos_de_la_curacion(bases):
    r = get_serie(SERIE, "2026-03-01", base="curada")
    no_medible = [a for a in r.avisos if a.startswith("fecha de publicación conservadora")]
    tramo = [a for a in r.avisos if a.startswith("fecha de publicación del tramo conservador")]
    assert len(no_medible) == 1 and NOTA_NO_MEDIBLE in no_medible[0]
    assert len(tramo) == 1 and NOTA_TRAMO in tramo[0] and "en 12 periodos" in tramo[0]
    # El hueco declarado no repite las notas de la curación.
    hueco = [a for a in r.avisos if "hueco declarado" in a]
    assert hueco and all("no medible" not in a and "tramo conservador" not in a for a in hueco)
    escala = get_serie(ESCALA, "2024-12-31", base="curada")
    assert any(a.startswith("escala corregida") and "en 4 periodos" in a for a in escala.avisos)
    # Con las mismas filas en memoria (o en la base de trabajo) no hay avisos de la curación.
    en_memoria = get_serie(SERIE, "2026-03-01", base=bases["curada"])
    assert not any(a.startswith(("fecha de publicación conservadora", "fecha de publicación del tramo"))
                   for a in en_memoria.avisos)


def test_t4_precios_curados_avisos(bases):
    r = get_precios([s.TICKER_ACCION, "NOEXISTE"], "2024-12-31", base="curada")
    assert any(a.startswith(f"{s.TICKER_ACCION}: 3 sesiones con apertura nula") for a in r.avisos)
    assert any(a.startswith("NOEXISTE: sin sesiones publicadas") and "base curada" in a for a in r.avisos)
    assert r.datos["open"].isna().sum() == 3
    trabajo = get_precios(s.TICKER_ACCION, "2024-12-31")
    assert not any("apertura nula" in a for a in trabajo.avisos)
    assert len(trabajo.datos) == len(r.datos) + 2


# --- Datos atrasados ------------------------------------------------------------------------------
def _atrasos(avisos: list[str]) -> list[str]:
    return [a for a in avisos if "datos atrasados" in a]


def test_t4_precios_atrasados(bases):
    """ZZAC curado acaba el 2024-12-31: avisa con más de MAX_DIAS_HABILES_ATRASO días hábiles hasta la fecha."""
    assert tools.MAX_DIAS_HABILES_ATRASO == 10
    assert not _atrasos(get_precios(s.TICKER_ACCION, "2024-12-31", base="curada").avisos)
    assert not _atrasos(get_precios(s.TICKER_ACCION, "2025-01-14", base="curada").avisos)    # 10 días hábiles
    atraso = _atrasos(get_precios(s.TICKER_ACCION, "2025-01-15", base="curada").avisos)      # 11
    assert atraso == [f"{s.TICKER_ACCION}: última sesión 2024-12-31: datos atrasados (refresco pendiente o sin "
                      "cotización; 11 días hábiles antes de 2025-01-15)"]
    # Con desde posterior a la última sesión: el aviso de «ninguna sesión» y el de atraso.
    con_desde = get_precios(s.TICKER_ACCION, "2025-03-01", base="curada", desde="2025-01-01").avisos
    assert _atrasos(con_desde) and any("ninguna sesión visible" in a for a in con_desde)
    # La base de trabajo no avisa (sin cambios).
    assert not _atrasos(get_precios(s.TICKER_ACCION, "2025-03-01").avisos)


def test_t4_series_atrasadas(bases):
    # Diaria que se publica cada día y acaba el 2025-12-31.
    assert not _atrasos(get_serie(DIARIA, "2026-01-14", base="curada").avisos)                # 10 días hábiles
    atraso = _atrasos(get_serie(DIARIA, "2026-01-15", base="curada").avisos)
    assert len(atraso) == 1 and atraso[0].startswith(f"{DIARIA}: última fecha de referencia 2025-12-31")
    assert not _atrasos(get_serie(DIARIA, "2026-01-15", base=bases["curada"]).avisos)       # en memoria: no
    # Diaria publicada una vez al mes: el umbral es 3 veces su ritmo (unos 63 días hábiles), no 10.
    ultima_pub = pd.Timestamp("2024-07-05")
    assert not _atrasos(get_serie(DIARIA_MENSUAL, ultima_pub + pd.offsets.BDay(40), base="curada").avisos)
    assert _atrasos(get_serie(DIARIA_MENSUAL, ultima_pub + pd.offsets.BDay(80), base="curada").avisos)
    # Saneado P10: también las mensuales, con su retraso mediano + 2 periodos + margen (antes no avisaban nunca).
    atraso_m = _atrasos(get_serie(SERIE, "2027-06-01", base="curada").avisos)
    assert len(atraso_m) == 1 and "retraso mediano" in atraso_m[0] and "2 periodos" in atraso_m[0]
    assert not _atrasos(get_serie(SERIE, "2026-03-13", base="curada").avisos)


# --- Caché de alias ---------------------------------------------------------------------------------
def test_t4_alias_en_cache(bases, monkeypatch):
    lecturas = []
    leer = almacen.leer_alias
    monkeypatch.setattr(almacen, "leer_alias", lambda *a, **k: lecturas.append(1) or leer(*a, **k))
    tools._CACHE_ALIAS.clear()
    primera = tools.alias_curada()
    for _ in range(3):
        assert tools.alias_curada() == primera
        get_serie(ALIAS, "2025-01-20", base="curada")
    assert len(lecturas) == 1
    tools.alias_curada()[ALIAS] = ("otro", None)            # la copia devuelta no toca la caché
    assert tools.alias_curada() == primera
    # Si el fichero cambia (tamaño y mtime), se relee.
    pd.DataFrame({"alias": [ALIAS, "sint:OTRO_ALIAS"], "canonico": [SERIE, SERIE], "motivo": ["a", "b"],
                  "correlacion": [0.99, 0.98]}).to_parquet(almacen.ruta_alias(), index=False)
    assert "sint:OTRO_ALIAS" in tools.alias_curada()
    assert len(lecturas) == 2
    almacen.ruta_alias().unlink()
    assert tools.alias_curada() == {}


def test_t4_coinbase_con_otro_proveedor():
    r = get_precios("cb:BTC-USD", "2024-03-15")
    assert r.datos.empty and "proveedor='coinbase'" in r.avisos[0]


# --- Modo trabajo sin cambios ---------------------------------------------------------------------
@pytest.mark.parametrize("fecha", FECHAS)
def test_t4_trabajo_sin_cambios(bases, vintages, accion, fecha):
    """Por defecto (y con 'trabajo' o None) se lee la base de trabajo, igual que con la tabla en memoria."""
    por_defecto = get_serie(SERIE, fecha)
    for otra in (get_serie(SERIE, fecha, base="trabajo"), get_serie(SERIE, fecha, base=None),
                 get_serie(SERIE, fecha, base=vintages)):
        _iguales(por_defecto, otra)
    precios = get_precios(s.TICKER_ACCION, fecha, divisa="original")
    for otra in (get_precios(s.TICKER_ACCION, fecha, divisa="original", base="trabajo"),
                 get_precios(s.TICKER_ACCION, fecha, divisa="original", base=None),
                 get_precios(s.TICKER_ACCION, fecha, divisa="original", base=accion)):
        _iguales(precios, otra)
    # El modo trabajo no consulta las tablas aparte del paso 4: una proyección que no está en su base da el
    # KeyError neutro de siempre (no el que remite a get_proyeccion).
    with pytest.raises(KeyError, match="desconocida o aún no publicada"):
        get_serie(PROY, fecha)


def test_t4_base_desconocida():
    with pytest.raises(ValueError, match="base desconocido"):
        get_serie(SERIE, "2024-03-15", base="limpia")
    with pytest.raises(ValueError, match="base desconocido"):
        get_precios(s.TICKER_ACCION, "2024-03-15", base="limpia")
    with pytest.raises(ValueError, match="base desconocido"):
        tools.resolver_id(SERIE, base="limpia")


def test_t4_sin_ficheros_curados():
    """Sin base curada ni tablas aparte: el mismo KeyError neutro y el mismo aviso neutro que un id desconocido."""
    with pytest.raises(KeyError, match="desconocida o aún no publicada"):
        get_serie(SERIE, "2024-03-15", base="curada")
    assert get_precios(s.TICKER_ACCION, "2024-03-15", base="curada").datos.empty
    assert tools.alias_curada() == {}


# --- Corpus real (paso 4) -------------------------------------------------------------------------
FECHA_REAL = "2020-03-16"


@pytest.mark.datos
def test_t4_datos_get_serie_curada():
    ruta = almacen.corpus_dir(almacen.TEMA) / "series" / almacen.FICHERO_SERIES_CURADA
    if not ruta.exists():
        pytest.skip(f"sin base curada ({almacen.FICHERO_SERIES_CURADA}): el paso 4 aún no la ha escrito")
    f = pd.Timestamp(FECHA_REAL)
    r = get_serie("fred:DGS10", FECHA_REAL, base="curada")
    assert r.serie == "fred:DGS10" and len(r.datos)
    assert (r.datos["fecha_publicacion"] <= f).all()
    assert pd.Timestamp(r.ultimo()["fecha_referencia"]) <= f
    truncada = almacen.leer_series("fred:DGS10", hasta=f, validar=False, curada=True)
    pd.testing.assert_frame_equal(r.datos, get_serie("fred:DGS10", FECHA_REAL, base=truncada).datos)
    if "ust:PAR.10Y" in tools.alias_curada():
        alias = get_serie("ust:PAR.10Y", FECHA_REAL, base="curada")
        assert alias.serie == "fred:DGS10"
        assert any("alias de fred:DGS10: se sirve el canónico" in a for a in alias.avisos)


@pytest.mark.datos
def test_t4_datos_get_precios_curada():
    fichero = almacen.corpus_dir(almacen.TEMA) / almacen.CARPETA_PRECIOS_CURADOS / "yahoo"
    if not fichero.exists():
        pytest.skip(f"sin {almacen.CARPETA_PRECIOS_CURADOS}/yahoo: el paso 4 aún no lo ha escrito")
    if not almacen.ruta_precios("yahoo", "SPY", curada=True).exists():
        pytest.skip("SPY aún no está en los precios curados")
    f = pd.Timestamp(FECHA_REAL)
    p = get_precios("SPY", FECHA_REAL, base="curada")
    assert len(p.datos) and (p.datos["fecha_publicacion"] <= f).all()
    assert pd.Timestamp(p.ultimo()["sesion"]) <= f
    crudo = almacen.leer_precios("SPY", curada=True)
    corta = crudo[crudo["fecha_publicacion"] <= f]
    pd.testing.assert_frame_equal(p.datos, get_precios("SPY", FECHA_REAL, base=corta).datos)
