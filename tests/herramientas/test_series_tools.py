"""Tools tipadas del Tema 1 (``herramientas.series``): get_serie, get_precios, get_proyeccion y buscar_series.

Unitarios (sin corpus): el almacén apunta a ``tmp_path`` y las funciones de ``tools.py`` se sustituyen por
respuestas sintéticas. Los ``@pytest.mark.datos`` leen el corpus real (``INGESTA_CORPUS_DIR``) y se saltan si falta.
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import ingesta.mercados_series as paquete_t1
from herramientas import catalogo, invocar, json_schema
from herramientas import series as hs
from ingesta.comun import rutas
from ingesta.mercados_series import almacen
from ingesta.mercados_series import tools as t1

TOOLS = ("get_serie", "get_precios", "get_proyeccion", "buscar_series")
AGENTES = {
    "get_serie": {"macro", "risk", "portfolio", "cio"},
    "get_precios": {"equity", "portfolio", "risk", "cio"},
    "get_proyeccion": {"macro", "cio"},
    "buscar_series": {"macro", "equity", "risk", "portfolio", "cio"},
}
F = date(2024, 6, 14)


@pytest.fixture(autouse=True)
def corpus_en_tmp(request, tmp_path, monkeypatch):
    """Las rutas del almacén apuntan a ``tmp_path`` salvo en los tests ``datos`` (corpus real): nada se escribe en D:."""
    if request.node.get_closest_marker("datos"):
        return None

    def corpus_dir(tema=None):
        p = tmp_path / "corpus" / tema if tema else tmp_path / "corpus"
        p.mkdir(parents=True, exist_ok=True)
        return p
    monkeypatch.setattr(almacen, "corpus_dir", corpus_dir)
    return tmp_path / "corpus"


# --- Datos sintéticos ----------------------------------------------------------------------------
def _serie_mensual(n: int = 30, unidad: str = "índice (2020 = 100)", inicio: float = 100.0,
                   paso: float = 1.0) -> t1.RespuestaSerie:
    ref = pd.date_range("2022-01-01", periods=n, freq="MS")
    datos = pd.DataFrame({
        "fecha_referencia": ref, "valor": inicio + paso * np.arange(n, dtype=float),
        "fecha_publicacion": ref + pd.Timedelta(days=40), "vintage": "x", "metodo_publicacion": "calendario",
        "nota": None})
    datos = datos[datos["fecha_publicacion"] <= pd.Timestamp(F)].reset_index(drop=True)
    return t1.RespuestaSerie(serie="zz:NIVEL", fecha=pd.Timestamp(F), datos=datos, unidad=unidad, divisa=None,
                             fuente="sintetica", metodo_publicacion="calendario", avisos=["aviso sintético"])


def _falso_get_serie(respuesta: t1.RespuestaSerie, llamadas: list | None = None):
    def falso(id, fecha, *, desde=None, divisa="original", **_):
        if llamadas is not None:
            llamadas.append({"id": id, "fecha": fecha, "desde": desde, "divisa": divisa})
        if id != respuesta.serie:
            raise KeyError(f"serie {id!r} sin datos publicados hasta {fecha} (desconocida o aún no publicada)")
        d = respuesta.datos
        if desde is not None:
            d = d[d["fecha_referencia"] >= pd.Timestamp(desde)].reset_index(drop=True)
        return t1.RespuestaSerie(**{**respuesta.__dict__, "datos": d})
    return falso


def _precios(n: int = 400, crecimiento: float = 0.001) -> pd.DataFrame:
    sesiones = pd.bdate_range(end=pd.Timestamp(F), periods=n)
    close = 100.0 * (1.0 + crecimiento) ** np.arange(n)
    return pd.DataFrame({"ticker": "ZZZ", "sesion": sesiones, "mercado": "NYSE", "open": close, "high": close,
                         "low": close, "close": close, "volume": 1.0, "dividendo": 0.0, "split": 1.0,
                         "divisa": "USD", "fecha_publicacion": sesiones, "fuente": "sintetica"})


# --- Catálogo y esquema --------------------------------------------------------------------------
def test_tools_registradas_con_sus_agentes() -> None:
    por_nombre = {t.nombre: t for t in catalogo()}
    for nombre in TOOLS:
        assert set(por_nombre[nombre].agentes) == AGENTES[nombre]
        assert por_nombre[nombre].descripcion
    assert "get_proyeccion" not in [t.nombre for t in catalogo("equity")]
    assert "get_precios" not in [t.nombre for t in catalogo("macro")]


@pytest.mark.parametrize("nombre", TOOLS)
def test_el_esquema_no_tiene_fecha(nombre: str) -> None:
    esquema = json_schema(nombre)
    assert esquema["name"] == nombre and esquema["description"]
    assert "fecha" not in esquema["parameters"].get("properties", {})
    json.dumps(esquema)   # serializable para el LLM


def test_limites_de_las_entradas() -> None:
    with pytest.raises(ValidationError):
        invocar("get_serie", {"id": "x", "max_filas": 261}, fecha=F)
    with pytest.raises(ValidationError):
        invocar("get_serie", {"id": "x", "fecha": "2030-01-01"}, fecha=F)   # la fecha no la elige el LLM
    with pytest.raises(ValidationError):
        invocar("get_precios", {"tickers": []}, fecha=F)
    with pytest.raises(ValidationError):
        invocar("get_precios", {"tickers": [f"T{i}" for i in range(11)]}, fecha=F)
    with pytest.raises(ValidationError):
        invocar("get_precios", {"tickers": ["SPY"], "ajuste": "raro"}, fecha=F)
    with pytest.raises(ValidationError):
        invocar("buscar_series", {"limite": 51}, fecha=F)
    with pytest.raises(ValidationError):
        invocar("buscar_series", {"agente": "trader"}, fecha=F)


# --- get_serie (sintético) -----------------------------------------------------------------------
def test_invocar_impone_la_fecha_del_sistema(monkeypatch) -> None:
    llamadas: list = []
    monkeypatch.setattr(t1, "get_serie", _falso_get_serie(_serie_mensual(), llamadas))
    salida = invocar("get_serie", {"id": "zz:NIVEL", "desde": "2023-01-01", "divisa": "USD"}, fecha=F)
    assert salida.fecha_consulta == F and salida.tool == "get_serie"
    assert llamadas and all(c["fecha"] == F and c["divisa"] == "USD" for c in llamadas)
    assert {c["desde"] for c in llamadas} == {None, date(2023, 1, 1)}   # historia entera y ventana
    assert salida.encontrado and salida.id_servido == "zz:NIVEL" and salida.avisos == ["aviso sintético"]
    assert salida.model_dump_json()


def test_max_filas_y_resumen_coherente(monkeypatch) -> None:
    resp = _serie_mensual()
    monkeypatch.setattr(t1, "get_serie", _falso_get_serie(resp))
    for n in (0, 1, 5, 260):
        s = invocar("get_serie", {"id": "zz:NIVEL", "max_filas": n}, fecha=F)
        assert len(s.filas) == min(n, len(resp.datos))
        assert s.filas_omitidas == len(resp.datos) - len(s.filas)
    s = invocar("get_serie", {"id": "zz:NIVEL", "max_filas": 13}, fecha=F)
    r = s.resumen
    assert r.ultimo_valor == s.filas[-1].valor and r.fecha_referencia == s.filas[-1].fecha_referencia
    assert r.fecha_publicacion == s.filas[-1].fecha_publicacion <= F
    assert r.tipo_cambio == "porcentaje"
    assert r.cambio_periodo == pytest.approx(100 * (s.filas[-1].valor / s.filas[-2].valor - 1), rel=1e-5)
    assert r.fecha_referencia_hace_un_anio == s.filas[0].fecha_referencia   # 13 filas mensuales: hace 12 meses
    assert r.cambio_anual == pytest.approx(100 * (s.filas[-1].valor / s.filas[0].valor - 1), rel=1e-5)
    assert r.percentil_historico == 100.0 and r.n_obs == r.n_historia == len(resp.datos)
    assert r.minimo_ventana <= min(f.valor for f in s.filas) and r.maximo_ventana == max(f.valor for f in s.filas)


def test_desde_recorta_la_ventana_pero_no_la_historia(monkeypatch) -> None:
    monkeypatch.setattr(t1, "get_serie", _falso_get_serie(_serie_mensual(paso=-1.0, inicio=200.0)))
    s = invocar("get_serie", {"id": "zz:NIVEL", "desde": "2024-01-01"}, fecha=F)
    assert all(f.fecha_referencia >= date(2024, 1, 1) for f in s.filas)
    assert s.resumen.n_obs == len(s.filas) < s.resumen.n_historia
    assert s.resumen.percentil_historico == pytest.approx(100 / s.resumen.n_historia, rel=1e-5)   # mínimo histórico
    assert s.resumen.cambio_anual is not None   # la base de hace un año está antes de desde


def test_regla_del_cambio() -> None:
    positiva, cruza = pd.Series([1.0, 2.0]), pd.Series([-1.0, 2.0])
    assert hs.tipo_cambio("índice (2020 = 100)", positiva) == "porcentaje"
    assert hs.tipo_cambio("millones de USD", positiva) == "porcentaje"
    assert hs.tipo_cambio("USD por 1 EUR", positiva) == "porcentaje"
    assert hs.tipo_cambio("índice", cruza) == "diferencia"   # índice centrado en 0
    for unidad in ("% anual", "puntos porcentuales", "puntos básicos (volatilidad)", "tanto por uno", "ratio",
                   "0/1", "índice de difusión", "índice (desviaciones típicas)", "índice (0 = normal)",
                   "puntos de índice (volatilidad implícita anualizada, %)", None):
        assert hs.tipo_cambio(unidad, positiva) == "diferencia", unidad
    tipos = _serie_mensual(unidad="% anual", inicio=1.0, paso=0.25).datos
    r = hs.resumir_serie(tipos, tipos, "% anual")
    assert r.tipo_cambio == "diferencia" and r.cambio_periodo == pytest.approx(0.25)
    assert r.cambio_anual == pytest.approx(3.0)


def test_hueco_final_no_es_el_ultimo_valor() -> None:
    d = _serie_mensual().datos.copy()
    d.loc[d.index[-1], "valor"] = np.nan
    r = hs.resumir_serie(d, d, "índice (2020 = 100)")
    assert r.ultimo_valor == d["valor"].iloc[-2] and r.fecha_referencia == d["fecha_referencia"].iloc[-2].date()
    assert r.n_obs == len(d) - 1


def test_id_desconocido_no_lanza(monkeypatch) -> None:
    # Con el almacén vacío (tmp_path), el get_serie real lanza KeyError y la tool devuelve encontrado=False.
    for tool, args in (("get_serie", {"id": "zz:NO_EXISTE"}), ("get_proyeccion", {"id": "zz:NO_EXISTE"})):
        s = invocar(tool, args, fecha=F)
        assert not s.encontrado and s.id_servido is None
        assert len(s.avisos) == 1 and "buscar_series" in s.avisos[0]
        assert "aún no publicada" in s.avisos[0] and s.citas
    p = invocar("get_precios", {"tickers": ["NO_EXISTE"]}, fecha=F)
    assert not p.tickers[0].encontrado and p.tickers[0].resumen is None and p.tickers[0].filas == []
    assert len(p.avisos) == 1 and "buscar_series" in p.avisos[0]


def test_cita_con_la_huella_del_manifiesto(monkeypatch, corpus_en_tmp: Path) -> None:
    monkeypatch.setattr(t1, "get_serie", _falso_get_serie(_serie_mensual()))
    carpeta = corpus_en_tmp / "mercados_series" / "series"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "base_curada.parquet").write_bytes(b"12345")
    manifiesto = {"salidas": {"base_curada": {"fichero": "base_curada.parquet", "tamano": 5, "sha256": "ab" * 32}}}
    (carpeta / hs.FICHERO_MANIFIESTO).write_text(json.dumps(manifiesto), encoding="utf-8")
    s = invocar("get_serie", {"id": "zz:NIVEL"}, fecha=F)
    assert [c.fuente for c in s.citas] == [hs.FUENTE_SERIES]
    assert s.citas[0].id == "ab" * 32 and s.citas[0].fecha_publicacion == s.resumen.fecha_publicacion
    (carpeta / "base_curada.parquet").write_bytes(b"123456")   # el manifiesto ya no describe el fichero
    assert invocar("get_serie", {"id": "zz:NIVEL"}, fecha=F).citas[0].id is None


# --- get_precios (sintético) ---------------------------------------------------------------------
def test_resumen_de_precios() -> None:
    d = _precios(crecimiento=0.001)
    r = hs.resumir_precios(d, len(d))
    ultimo = d["close"].iloc[-1]
    assert r.ultima_sesion == F and r.ultimo_cierre == pytest.approx(ultimo)
    hace_un_mes = d[d["sesion"] <= pd.Timestamp(F) - pd.DateOffset(months=1)]["close"].iloc[-1]
    assert r.rentabilidad_1m == pytest.approx(100 * (ultimo / hace_un_mes - 1), rel=1e-5)
    assert r.rentabilidad_12m is not None and r.rentabilidad_12m > r.rentabilidad_3m > r.rentabilidad_1m > 0
    assert r.volatilidad_3m == pytest.approx(0.0, abs=1e-6)   # crecimiento constante: sin volatilidad
    assert r.caida_desde_maximo_12m == pytest.approx(0.0, abs=1e-9)
    corta = hs.resumir_precios(d.tail(30), 30)   # sin historia de 3 ni 12 meses
    assert corta.rentabilidad_3m is None and corta.rentabilidad_12m is None


def test_get_precios_respeta_max_filas_y_desde(monkeypatch) -> None:
    datos = _precios()

    def falso(tk, fecha, *, desde=None, ajuste="total", divisa="USD", proveedor="yahoo", **_):
        assert fecha == F
        d = datos[datos["ticker"].isin(tk)]
        if desde is not None:
            d = d[d["sesion"] >= pd.Timestamp(desde)]
        avisos = [f"{t}: sin sesiones publicadas hasta {fecha}" for t in tk if t not in set(d["ticker"])]
        return t1.RespuestaPrecios(tickers=list(tk), fecha=pd.Timestamp(fecha), datos=d.reset_index(drop=True),
                                   ajuste=ajuste, divisa=divisa, avisos=avisos)
    monkeypatch.setattr(t1, "get_precios", falso)
    p = invocar("get_precios", {"tickers": ["ZZZ", "NADA"], "max_filas": 7, "desde": "2024-06-01"}, fecha=F)
    zzz, nada = p.tickers
    assert len(zzz.filas) == 7 and zzz.resumen.n_sesiones == len(zzz.filas) + zzz.filas_omitidas
    assert all(f.sesion >= date(2024, 6, 1) and f.fecha_publicacion <= F for f in zzz.filas)
    assert zzz.resumen.ultimo_cierre == zzz.filas[-1].close and zzz.resumen.ultima_sesion == zzz.filas[-1].sesion
    assert zzz.resumen.rentabilidad_12m is not None   # el resumen usa toda la historia, no solo desde
    assert not nada.encontrado and p.avisos == [a for a in p.avisos if a.startswith("NADA: ")] and len(p.avisos) == 1
    assert [c.fuente for c in p.citas] == [f"{hs.FUENTE_PRECIOS}/yahoo/ZZZ.parquet"]
    assert p.ajuste == "total" and p.divisa == "USD"


# --- buscar_series -------------------------------------------------------------------------------
def _modulo_catalogo_falso(llamadas: list) -> types.ModuleType:
    mod = types.ModuleType("ingesta.mercados_series.catalogo_agentes")

    def buscar_series(texto=None, fecha=None, *, tema=None, zona=None, agente=None, tipo=None, limite=10):
        llamadas.append({"texto": texto, "fecha": fecha, "tema": tema, "agente": agente, "limite": limite})
        if tema == "inventado":
            raise ValueError("tema desconocido 'inventado'")
        return pd.DataFrame([
            {"id": "fred:DGS10", "tipo": "serie", "nombre": "UST 10 años", "descripcion": "rendimiento",
             "tema": "tipos", "zona": "EE. UU.", "frecuencia": "diaria", "unidad": "% anual", "divisa": None,
             "desde": pd.Timestamp("1962-01-02"), "retraso_tipico_dias": 1.0, "agentes": ["macro", "risk"],
             "avisos": [], "puntuacion": 0.9},
            {"id": "SPY", "tipo": "precios", "nombre": "SPDR S&P 500", "descripcion": None, "tema": "renta variable",
             "zona": None, "frecuencia": "diaria", "unidad": None, "divisa": "USD", "desde": "1993-01-29",
             "retraso_tipico_dias": np.nan, "agentes": "equity, portfolio", "avisos": "ETF", "puntuacion": 0.5},
        ][:limite])
    mod.buscar_series = buscar_series
    mod.temas = lambda: ["tipos", "renta variable"]
    return mod


def test_buscar_series_con_modulo_falso(monkeypatch) -> None:
    llamadas: list = []
    falso = _modulo_catalogo_falso(llamadas)
    monkeypatch.setitem(sys.modules, "ingesta.mercados_series.catalogo_agentes", falso)
    monkeypatch.setattr(paquete_t1, "catalogo_agentes", falso, raising=False)
    s = invocar("buscar_series", {"texto": "bono 10 años", "agente": "macro", "limite": 2}, fecha=F)
    assert llamadas[-1] == {"texto": "bono 10 años", "fecha": F, "tema": None, "agente": "macro", "limite": 2}
    assert s.n == 2 and [f.id for f in s.fichas] == ["fred:DGS10", "SPY"]
    assert s.fichas[0].desde == date(1962, 1, 2) and s.fichas[0].agentes == ["macro", "risk"]
    assert s.fichas[1].agentes == ["equity", "portfolio"] and s.fichas[1].avisos == ["ETF"]
    assert s.fichas[1].retraso_tipico_dias is None and s.fichas[0].puntuacion == 0.9
    assert s.citas and s.citas[0].fuente == hs.FUENTE_CATALOGO
    error = invocar("buscar_series", {"tema": "inventado"}, fecha=F)
    assert error.n == 0 and error.avisos == ["tema desconocido 'inventado'"]


def test_esquema_de_buscar_con_el_vocabulario_real() -> None:
    from typing import get_args

    from ingesta.mercados_series import catalogo_agentes

    props = json_schema("buscar_series")["parameters"]["properties"]
    assert set(get_args(hs.TipoCatalogo)) == set(catalogo_agentes.TIPOS)
    assert props["tipo"]["anyOf"][0]["enum"] == list(get_args(hs.TipoCatalogo))
    assert all(t in props["tema"]["description"] for t in catalogo_agentes.temas())
    assert "EA (zona euro)" in props["zona"]["description"] and "US (" in props["zona"]["description"]
    with pytest.raises(ValidationError):
        invocar("buscar_series", {"tipo": "precios"}, fecha=F)


def test_aviso_no_encontrado_es_neutro_con_alias() -> None:
    e = KeyError("serie 'fred:NFCI' (alias 'NFCI') sin datos publicados hasta 2008-09-15 "
                 "(desconocida o aún no publicada)")
    nada = KeyError("serie 'ZZ' sin datos publicados hasta 2008-09-15 (desconocida o aún no publicada)")
    assert hs._aviso_no_encontrado(e, "NFCI").replace("'NFCI'", "X") == \
        hs._aviso_no_encontrado(nada, "ZZ").replace("'ZZ'", "X")
    assert "fred:NFCI" not in hs._aviso_no_encontrado(e, "NFCI")


def test_buscar_series_contra_el_modulo_real() -> None:
    try:
        from ingesta.mercados_series import catalogo_agentes
    except ImportError:
        pytest.skip("catalogo_agentes aún no existe (otro agente lo escribe en paralelo)")
    tema = catalogo_agentes.temas()[0] if catalogo_agentes.temas() else None
    s = invocar("buscar_series", {"texto": "inflación", "limite": 5}, fecha=F)
    assert s.n == len(s.fichas) <= 5 and s.citas
    assert all(f.id for f in s.fichas)
    if tema is not None:
        assert all(f.tema == tema for f in invocar("buscar_series", {"tema": tema}, fecha=F).fichas)


# --- Corpus real ---------------------------------------------------------------------------------
def _corpus_t1() -> Path:
    # Sin rutas.corpus_dir (que crea la carpeta): solo se mira (patrón de tests/ingesta/mercados_series/conftest.py).
    return Path(rutas.env("INGESTA_CORPUS_DIR", str(rutas.ROOT / "corpus"))) / "mercados_series"


_BASE = _corpus_t1() / "series" / "base_curada.parquet"
_SPY = _corpus_t1() / "precios_curados" / "yahoo" / "SPY.parquet"
sin_base = pytest.mark.skipif(not _BASE.is_file(), reason=f"sin base curada en {_BASE}")
ANTIGUA, RECIENTE = date(2005, 1, 3), date(2020, 3, 16)


@pytest.mark.datos
@sin_base
def test_datos_timegate_serie_y_max_filas() -> None:
    s = invocar("get_serie", {"id": "fred:DGS10", "max_filas": 260}, fecha=ANTIGUA)
    assert s.encontrado and len(s.filas) == 260 and s.filas_omitidas > 0
    assert all(f.fecha_publicacion <= ANTIGUA and f.fecha_referencia <= ANTIGUA for f in s.filas)
    assert s.resumen.fecha_publicacion <= ANTIGUA and s.citas[0].fecha_publicacion <= ANTIGUA
    assert s.citas[0].fuente == hs.FUENTE_SERIES and s.citas[0].id and len(s.citas[0].id) == 64
    assert s.resumen.ultimo_valor == s.filas[-1].valor and s.resumen.tipo_cambio == "diferencia"
    assert s.resumen.minimo_ventana <= min(f.valor for f in s.filas if f.valor is not None)
    assert s.resumen.n_obs == s.resumen.n_historia   # sin desde, ventana = historia
    assert len(invocar("get_serie", {"id": "fred:DGS10", "max_filas": 3}, fecha=ANTIGUA).filas) == 3
    reciente = invocar("get_serie", {"id": "fred:DGS10", "max_filas": 1}, fecha=RECIENTE)
    assert reciente.resumen.n_historia > s.resumen.n_historia and reciente.filas[-1].fecha_referencia > ANTIGUA


@pytest.mark.datos
@sin_base
def test_datos_serie_futura_no_se_revela() -> None:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    t = pq.read_table(_BASE, columns=["serie", "fecha_publicacion"])
    primera = t.group_by("serie").aggregate([("fecha_publicacion", "min")])
    tardias = primera.filter(pc.greater(primera["fecha_publicacion_min"], pd.Timestamp("2012-01-01")))
    if not tardias.num_rows:
        pytest.skip("ninguna serie empieza a publicarse después de 2012")
    futura = sorted(tardias["serie"].to_pylist())[0]
    fecha = date(2010, 1, 4)
    s = invocar("get_serie", {"id": futura}, fecha=fecha)
    nada = invocar("get_serie", {"id": "zz:NO_EXISTE"}, fecha=fecha)
    assert not s.encontrado and s.filas == [] and s.resumen is None
    assert s.avisos[0].replace(repr(futura), "X") == nada.avisos[0].replace(repr("zz:NO_EXISTE"), "X")


@pytest.mark.datos
@sin_base
def test_datos_avisos_no_revelan_el_futuro() -> None:
    """Verificación del 2026-11-23: la retirada, la serie que sustituye a una historia previa y las notas con fechas
    posteriores no se avisaban a tiempo (EONIA → €STR en 2016; ^BCOM «dejó de servirse el 2026-07-17»)."""
    s = invocar("get_serie", {"id": "ecb:EONIA", "max_filas": 0}, fecha=date(2016, 6, 24))
    assert s.encontrado and not any("ESTR" in a or "retirada" in a for a in s.avisos)
    s = invocar("get_serie", {"id": "ecb:EONIA", "max_filas": 0}, fecha=date(2023, 6, 1))
    assert any("retirada" in a for a in s.avisos) and any("ecb:ESTR" in a for a in s.avisos)
    s = invocar("get_serie", {"id": "yf:^BCOM", "max_filas": 0}, fecha=date(2016, 6, 24))
    assert s.encontrado and not any("2026" in a or "retirada" in a for a in s.avisos)
    alias = invocar("get_serie", {"id": "NFCI"}, fecha=date(2008, 9, 15))     # alias de fred:NFCI (2011)
    nada = invocar("get_serie", {"id": "NO_EXISTE"}, fecha=date(2008, 9, 15))
    assert alias.avisos[0].replace("'NFCI'", "X") == nada.avisos[0].replace("'NO_EXISTE'", "X")
    xlc = invocar("get_serie", {"id": "yf:XLC"}, fecha=date(2008, 9, 15))     # ETF excluido que cotiza desde 2018
    assert xlc.avisos[0].replace("'yf:XLC'", "X") == nada.avisos[0].replace("'NO_EXISTE'", "X")
    assert "get_precios" in invocar("get_serie", {"id": "yf:XLC"}, fecha=date(2019, 1, 4)).avisos[0]


@pytest.mark.datos
@sin_base
def test_datos_serie_con_desde_y_usd() -> None:
    s = invocar("get_serie", {"id": "fred:CPIAUCSL", "desde": "2019-01-01", "max_filas": 260}, fecha=RECIENTE)
    assert s.encontrado and s.frecuencia and s.unidad and s.resumen.tipo_cambio == "porcentaje"
    assert all(date(2019, 1, 1) <= f.fecha_referencia and f.fecha_publicacion <= RECIENTE for f in s.filas)
    assert s.resumen.n_obs == len([f for f in s.filas if f.valor is not None]) and s.filas_omitidas == 0
    assert s.resumen.minimo_ventana == min(f.valor for f in s.filas if f.valor is not None)
    assert s.resumen.maximo_ventana == max(f.valor for f in s.filas if f.valor is not None)
    assert s.resumen.n_historia > s.resumen.n_obs


@pytest.mark.datos
@pytest.mark.skipif(not _SPY.is_file(), reason=f"sin {_SPY}")
def test_datos_timegate_precios() -> None:
    p = invocar("get_precios", {"tickers": ["SPY", "NO_EXISTE"], "max_filas": 15}, fecha=ANTIGUA)
    spy, nada = p.tickers
    assert spy.encontrado and len(spy.filas) == 15 and not nada.encontrado
    assert all(f.sesion <= ANTIGUA and f.fecha_publicacion <= ANTIGUA for f in spy.filas)
    assert spy.resumen.ultima_sesion == spy.filas[-1].sesion and spy.resumen.ultimo_cierre == spy.filas[-1].close
    assert spy.resumen.rentabilidad_12m is not None and spy.resumen.volatilidad_3m > 0
    assert spy.resumen.caida_desde_maximo_12m <= 0
    assert len(p.citas) == 1 and p.citas[0].id == hashlib.sha256(_SPY.read_bytes()).hexdigest()
    assert p.citas[0].fecha_publicacion <= ANTIGUA
    assert any(a.startswith("NO_EXISTE: ") and "buscar_series" in a for a in p.avisos)


@pytest.mark.datos
@sin_base
def test_datos_proyeccion() -> None:
    r = invocar("get_proyeccion", {"id": "fred:FEDTARMD"}, fecha=RECIENTE)
    if not r.encontrado:
        pytest.skip("fred:FEDTARMD sin proyecciones visibles en el corpus")
    assert r.filas and all(f.fecha_publicacion <= RECIENTE for f in r.filas)
    assert r.ultima_edicion in {f.edicion for f in r.filas}
    assert r.citas[0].fuente == hs.FUENTE_PROYECCIONES and r.citas[0].fecha_publicacion <= RECIENTE
