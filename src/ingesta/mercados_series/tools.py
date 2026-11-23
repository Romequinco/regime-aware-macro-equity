"""Tools del Tema 1 para los agentes: ``get_serie`` y ``get_precios``.

Ambas aplican el TimeGate (nada con ``fecha_publicacion > fecha``) y devuelven una respuesta con
los datos, sus metadatos y una lista de ``avisos`` legibles (huecos, fechas de publicación
aproximadas, conversiones sin FX, tickers sin datos...). Los errores de uso lanzan
``ValueError`` (ajuste o divisa desconocidos, fecha inválida o ambigua).

Truncado también en los mensajes: la respuesta en ``fecha`` (datos, avisos, metadatos y tipo de
error) es la misma con la base completa que con la base truncada a lo publicado hasta ``fecha``.
Por eso una serie o un ticker sin nada publicado hasta ``fecha`` se trata igual que uno que no
existe, sin revelar si existirá ni cuándo: ``get_serie`` lanza ``KeyError`` y ``get_precios``
añade un aviso neutro; los metadatos salen solo de filas visibles.

``ultimo()`` devuelve un diccionario citable (valores Python, fechas ISO): lo que un agente pone
en su respuesta junto con la fuente y la fecha de publicación.

Dos bases (paso 4), con el mismo TimeGate y el mismo truncado (solo cambia de dónde se lee):

- ``base='curada'`` (**por defecto** desde el saneado del 2026-11-21, P01): la del preprocesado
  (``series/base_curada.parquet``, ``precios_curados/``). **La que usan los agentes y el backtest.** Un alias de ``series/alias.parquet`` sirve su canónico
  con un aviso; las proyecciones no salen por ``get_serie`` (``KeyError`` que remite a
  ``get_proyeccion``); las notas de la curación (fecha no medible, tramo conservador, escala
  corregida) pasan a ``avisos``.
- ``base='trabajo'``: la base tal como se descarga (``series/base_series.parquet``, ``precios/<proveedor>/``), sin
  las fechas prudentes del curado ni el corte. Solo para auditar, depurar y construir: hay que pedirla a mano.

``base`` admite además una tabla del contrato en memoria (como hasta ahora: tests y recortes).
"""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd

from ingesta.mercados_series import almacen, divisas, timegate, visibilidad
from ingesta.mercados_series import catalogo as cat_mod
from ingesta.mercados_series.catalogo import (
    NOTA_EXCEPCION,
    NOTA_PREVIA_ALFRED,
    NOTA_PRIMERA_EDICION,
    NOTA_RECONSTRUIDA,
    es_nota_revisable,
)
from ingesta.mercados_series.contrato import FECHA, REAL, TEXTO, vacio_series
from ingesta.mercados_series.fuentes.alfred import NOTA_REESTIMADA, NOTA_UNIDAD_VINTAGE

FechaLike = date | str | pd.Timestamp
Ajuste = Literal["ninguno", "splits", "total"]

AJUSTES: tuple[str, ...] = ("ninguno", "splits", "total")
DIVISAS_SALIDA: tuple[str, ...] = ("original", "USD")
# Bases que leen las tools (paso 4): la curada (por defecto, BASE_DEFECTO; agentes y backtest) y la de trabajo.
BASES: tuple[str, ...] = ("trabajo", "curada")
# ``base``: una de ``BASES`` o una tabla del contrato en memoria (tests y recortes, como antes del paso 4).
BaseLike = Literal["trabajo", "curada"] | pd.DataFrame | None
#: Base por defecto de las tools (P01 del saneado): la curada. ``base=None`` (el valor por defecto de las firmas) se
#: resuelve a esta constante al llamar; los tests de la base de trabajo la cambian con ``monkeypatch``.
BASE_DEFECTO = "curada"

# Columnas de ``RespuestaSerie.datos`` (más ``divisa_original``, ``fx_usd`` y ``fx_fecha`` si se
# pide USD).
COLUMNAS_DATOS_SERIE: dict[str, str] = {
    "fecha_referencia": FECHA, "valor": REAL, "fecha_publicacion": FECHA, "vintage": TEXTO,
    "metodo_publicacion": TEXTO, "nota": TEXTO,
}
# Columnas de ``RespuestaPrecios.datos`` (ídem). Precios y dividendo con el ajuste pedido; el
# volumen, en acciones de hoy-en-fecha si el ajuste incluye splits.
COLUMNAS_DATOS_PRECIOS: dict[str, str] = {
    "ticker": TEXTO, "sesion": FECHA, "mercado": TEXTO, "open": REAL, "high": REAL, "low": REAL,
    "close": REAL, "volume": REAL, "dividendo": REAL, "split": REAL, "divisa": TEXTO,
    "fecha_publicacion": FECHA, "fuente": TEXTO,
}
_COLUMNAS_FX: dict[str, str] = {"divisa_original": TEXTO, "fx_usd": REAL, "fx_fecha": FECHA}

# Columna de ``timegate.ajustar_a_fecha`` que se publica como cada columna, por ajuste.
_ORIGEN_AJUSTE: dict[str, dict[str, str]] = {
    "ninguno": {},
    "splits": {"open": "open_aj_splits", "high": "high_aj_splits", "low": "low_aj_splits",
               "close": "close_aj_splits", "volume": "volume_aj_splits",
               "dividendo": "dividendo_aj_splits"},
    "total": {"open": "open_aj_total", "high": "high_aj_total", "low": "low_aj_total",
              "close": "close_aj_total", "volume": "volume_aj_splits",
              "dividendo": "dividendo_aj_splits"},
}
_MONETARIAS_PRECIOS = ("open", "high", "low", "close", "dividendo")
# Prefijo de los tickers de Coinbase (``fuentes.cripto``: ``cb:BTC-USD``, ``cb:ETH-USD``; ``proveedor='coinbase'``).
PREFIJO_COINBASE = "cb:"


# --- Utilidades ---------------------------------------------------------------------------------
def _vacio(columnas: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in columnas.items()})


def _iso(valor: Any) -> str | None:
    return None if pd.isna(valor) else pd.Timestamp(valor).date().isoformat()


def _real(valor: Any) -> float | None:
    return None if pd.isna(valor) else float(valor)


def _texto(valor: Any) -> str | None:
    return None if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else str(valor)


def _validar_opcion(valor: str, validas: tuple[str, ...], nombre: str) -> None:
    if valor not in validas:
        raise ValueError(f"{nombre} desconocido {valor!r}; válidos: {list(validas)}")


def _modo_base(base: BaseLike) -> tuple[pd.DataFrame | None, bool]:
    """``(tabla en memoria o None, curada)`` de un ``base`` de las tools.

    ``None`` es ``BASE_DEFECTO`` (la curada, P01); un texto fuera de ``BASES`` lanza ``ValueError``.
    """
    if base is None:
        base = BASE_DEFECTO
    if isinstance(base, str):
        _validar_opcion(base, BASES, "base")
        return None, base == "curada"
    if not isinstance(base, pd.DataFrame):
        raise ValueError(f"base desconocida {type(base).__name__}: usa uno de {list(BASES)} o una tabla del contrato")
    return base, False


# Caché de ``alias_curada``: ruta → ((mtime_ns, tamaño) del fichero, tabla). Se relee si el fichero cambia.
_CACHE_ALIAS: dict[str, tuple[tuple[int, int], dict[str, tuple[str, str | None]]]] = {}


def alias_curada() -> dict[str, tuple[str, str | None]]:
    """``{alias: (canónico, motivo)}`` de la tabla de alias del paso 4 (``almacen.leer_alias``); vacío sin fichero.

    En caché por ruta, ``mtime`` y tamaño de ``series/alias.parquet``: solo se relee si el fichero cambia.
    Devuelve una copia (la caché no se puede modificar desde fuera).
    """
    ruta = almacen.ruta_alias()
    try:
        st = ruta.stat()
    except FileNotFoundError:
        _CACHE_ALIAS.pop(str(ruta), None)
        return {}
    firma = (st.st_mtime_ns, st.st_size)
    guardado = _CACHE_ALIAS.get(str(ruta))
    if guardado is None or guardado[0] != firma:
        t = almacen.leer_alias(ruta)
        tabla = {str(a): (str(c), _texto(m)) for a, c, m in zip(t["alias"], t["canonico"], t["motivo"], strict=True)
                 if isinstance(a, str) and isinstance(c, str)}
        guardado = _CACHE_ALIAS[str(ruta)] = (firma, tabla)
    return dict(guardado[1])


# Saltos de alias que se siguen como mucho (la tabla apunta al canónico; esto solo evita ciclos).
_MAX_SALTOS_ALIAS = 5


def _resolver_alias_curada(canonico: str, id: str) -> tuple[str, list[str]]:
    """Canónico de la base curada para ``canonico`` (ya resuelto con los alias de la Fase 1) y su aviso.

    Si ``id`` o ``canonico`` es un alias de ``series/alias.parquet``, se sirve el canónico con el
    aviso «alias de X: se sirve el canónico». Es un metadato estático (sin valores ni fechas).
    """
    tabla = alias_curada()
    actual = id if id in tabla else canonico
    if actual not in tabla:
        return canonico, []
    pedido, motivo = actual, None
    for _ in range(_MAX_SALTOS_ALIAS):
        if actual not in tabla:
            break
        actual, motivo = tabla[actual]
    else:
        raise ValueError(f"tabla de alias de la base curada con un ciclo o una cadena demasiado larga en {pedido!r}")
    nombre = repr(pedido) if pedido == id else f"{pedido!r} (alias {id!r})"
    detalle = f" ({motivo})" if motivo else ""
    return actual, [f"{nombre}: alias de {actual}: se sirve el canónico{detalle}"]


def alias_por_defecto() -> dict[str, str]:
    """Alias del catálogo (``catalogo.alias``: nombres de la Fase 1) más los de ``publicaciones.yaml``.

    Un alias no puede estar en los dos ficheros (lo impide ``visibilidad.cargar_publicaciones``).
    """
    return {**visibilidad.cargar_publicaciones(catalogo=False)["alias"], **cat_mod.alias()}


def resolver_id(id: str, alias: dict[str, str] | None = None, *, base: str | None = None) -> str:
    """Id canónico de ``id``: ``alias[id]`` si es un alias; si no, ``id`` tal cual.

    ``alias`` por defecto: ``alias_por_defecto()`` (catálogo de series + ``publicaciones.yaml``).
    ``base='curada'``: además, el canónico de la tabla de alias del paso 4 (``series/alias.parquet``).
    """
    base = BASE_DEFECTO if base is None else base
    _validar_opcion(base, BASES, "base")
    canonico = _resolver_fase1(id, alias)
    if base == "curada":
        canonico, _ = _resolver_alias_curada(canonico, id)
    return canonico


def _resolver_fase1(id: str, alias: dict[str, str] | None) -> str:
    if not isinstance(id, str) or not id:
        raise ValueError(f"id de serie vacío o no textual: {id!r}")
    tabla = alias if alias is not None else alias_por_defecto()
    if id in tabla:
        return tabla[id]
    if alias is None and id not in cat_mod._cat(None):
        # Ids y alias sin distinguir mayúsculas ('gw:M.TBL' → 'gw:M.tbl'), solo si es único.
        return cat_mod.resolver_caja(id) or id
    return id


def _comprobar_excluida(canonico: str, id: str, fecha: pd.Timestamp | None = None, curada: bool = True) -> None:
    """``KeyError`` si el catálogo excluye ``canonico`` de la base de series (ETF ajustadas).

    También un ticker suelto (``'SPY'``) cuyo ``yf:<ticker>`` está excluido. Con ``fecha``, solo si el ETF ya
    tiene alguna sesión publicada en ``precios_curados`` hasta ``fecha``: si no (``XLC`` antes de 2018), sigue y
    acaba en el ``KeyError`` neutro, para no revelar que el ETF existirá (verificación del 2026-11-23).
    """
    cat = cat_mod._cat(None)
    if canonico not in cat and f"yf:{canonico}" in cat:
        canonico = f"yf:{canonico}"
    e = cat.get(canonico)
    if e is None or e["estado"] != "excluida_ajustada":
        return
    if fecha is not None:
        import pyarrow.parquet as pq

        ruta = almacen.ruta_precios("yahoo", str(e["id_origen"]), curada=curada)
        if not ruta.exists() or pq.read_table(ruta, columns=["fecha_publicacion"], filters=[
                ("fecha_publicacion", "<=", fecha.to_datetime64())]).num_rows == 0:
            return
    nombre = repr(canonico) if canonico == id else f"{canonico!r} (alias {id!r})"
    raise KeyError(f"serie {nombre} excluida de la base de series: ETF de yfinance con niveles ajustados a "
                   f"posteriori (auto_adjust=True). Usa get_precios({e['id_origen']!r}, fecha), que reconstruye "
                   f"el ajuste con lo conocido en la fecha (bloque 6)")


# --- Respuestas ---------------------------------------------------------------------------------
@dataclass
class RespuestaSerie:
    """Respuesta de ``get_serie``.

    ``datos``: ``COLUMNAS_DATOS_SERIE`` (una fila por periodo, la vintage visible en ``fecha``;
    con ``divisa_original``, ``fx_usd`` y ``fx_fecha`` si se pidió ``divisa='USD'``).
    ``metodo_publicacion``: el de la última fila. ``divisa``: la de ``valor`` tras la conversión.
    """

    serie: str
    fecha: pd.Timestamp
    datos: pd.DataFrame
    unidad: str | None
    divisa: str | None
    fuente: str | None
    metodo_publicacion: str | None
    avisos: list[str] = field(default_factory=list)

    def ultimo(self) -> dict[str, Any] | None:
        """Última fila (mayor ``fecha_referencia``) como diccionario citable; None sin datos.

        Claves: ``serie, valor, fecha_referencia, fecha_publicacion, vintage, unidad, divisa,
        fuente, metodo_publicacion, nota, fecha_consulta`` (fechas en ISO; ``valor`` None en un
        hueco declarado, con su ``nota``).
        """
        if self.datos.empty:
            return None
        fila = self.datos.iloc[-1]
        return {
            "serie": self.serie, "valor": _real(fila["valor"]),
            "fecha_referencia": _iso(fila["fecha_referencia"]),
            "fecha_publicacion": _iso(fila["fecha_publicacion"]), "vintage": _texto(fila["vintage"]),
            "unidad": self.unidad, "divisa": self.divisa, "fuente": self.fuente,
            "metodo_publicacion": _texto(fila["metodo_publicacion"]), "nota": _texto(fila["nota"]),
            "fecha_consulta": _iso(self.fecha),
        }


@dataclass
class RespuestaPrecios:
    """Respuesta de ``get_precios``.

    ``datos``: ``COLUMNAS_DATOS_PRECIOS`` (tabla larga, ordenada por ticker y sesión) con el
    ajuste pedido ya aplicado (y ``divisa_original``, ``fx_usd`` y ``fx_fecha`` si se convirtió).
    ``divisa``: 'USD' u 'original'.
    """

    tickers: list[str]
    fecha: pd.Timestamp
    datos: pd.DataFrame
    ajuste: Ajuste
    divisa: str
    avisos: list[str] = field(default_factory=list)

    def ultimo(self, ticker: str | None = None) -> dict[str, Any] | None:
        """Última sesión visible de ``ticker`` como diccionario citable; None sin datos.

        Sin ``ticker`` solo vale si se pidió uno (``ValueError`` con varios: usar ``ultimos``).
        Claves: ``ticker, sesion, valor`` (cierre con el ajuste pedido, que dice ``ajuste``),
        ``fecha_publicacion, fuente, mercado, ajuste, divisa, fx_usd`` (None sin conversión) y
        ``fecha_consulta``.
        """
        if ticker is None:
            if len(self.tickers) != 1:
                raise ValueError(f"varios tickers {self.tickers}: usa ultimo(ticker) o ultimos()")
            ticker = self.tickers[0]
        filas = self.datos[self.datos["ticker"] == ticker]
        if filas.empty:
            return None
        fila = filas.iloc[-1]
        return {
            "ticker": ticker, "sesion": _iso(fila["sesion"]), "valor": _real(fila["close"]),
            "fecha_publicacion": _iso(fila["fecha_publicacion"]), "fuente": _texto(fila["fuente"]),
            "mercado": _texto(fila["mercado"]), "ajuste": self.ajuste, "divisa": _texto(fila["divisa"]),
            "fx_usd": _real(fila["fx_usd"]) if "fx_usd" in filas.columns else None,
            "fecha_consulta": _iso(self.fecha),
        }

    def ultimos(self) -> dict[str, dict[str, Any] | None]:
        """``{ticker: ultimo(ticker)}`` para todos los tickers pedidos (None si no hay datos)."""
        return {tk: self.ultimo(tk) for tk in self.tickers}


# --- get_serie ----------------------------------------------------------------------------------
# Huecos de una respuesta que se detallan uno a uno; con más, un solo aviso con el recuento.
MAX_HUECOS_DETALLADOS = 3


# Notas que tienen su propio aviso (no se repiten en el de huecos).
_NOTAS_CON_AVISO = (NOTA_EXCEPCION, NOTA_RECONSTRUIDA, NOTA_PREVIA_ALFRED, NOTA_REESTIMADA, NOTA_UNIDAD_VINTAGE,
                    cat_mod.NOTA_FUGA_PREVIA)


# Paso 4: notas de la base curada que pasan a ``avisos`` (subcadena de una parte de la nota, sin
# distinguir mayúsculas; las escribe ``curada.py``) y la descripción de su aviso. Solo en ``base='curada'``.
NOTAS_CURADA: dict[str, str] = {
    "fecha no medible": "fecha de publicación conservadora (fecha no medible: regla conservadora de "
                        "preprocesado.yaml, no la fecha real de cada publicación)",
    "tramo conservador": "fecha de publicación del tramo conservador (antes del corte de lista_curada.yaml la "
                         "fecha no es fiable: se retrasa con la regla conservadora)",
    "escala corregida": "escala corregida (valores multiplicados para llevarlos a la unidad vigente; el "
                        "significado no cambia)",
    # Saneado P29: meses que la fuente no publicó (octubre de 2025), rellenados en la curada con el mes anterior.
    "relleno: mes no publicado": "mes no publicado por la fuente, rellenado con el valor del mes anterior (variación "
                                 "0 ese mes; la del mes siguiente mide dos meses)",
}
# Partes de nota distintas que se citan en cada aviso de la curación.
_MAX_NOTAS_CITADAS = 2


def _es_nota_curada(parte: str) -> bool:
    baja = parte.lower()
    return any(marca in baja for marca in NOTAS_CURADA)


def _sin_notas_comunes(nota: Any, curada: bool = False) -> str:
    """Nota de un hueco sin las notas que ya avisan aparte (revisables, excepción, ALFRED, curación...)."""
    partes = [p for p in str(nota or "").split("; ")
              if p and not es_nota_revisable(p) and not p.startswith(_NOTAS_CON_AVISO)
              and not (curada and _es_nota_curada(p))]
    return "; ".join(partes) or "sin nota"


def _contiene(nota: pd.Series, texto: str) -> pd.Series:
    return nota.str.contains(texto, regex=False)


def _avisos_curada(nota: pd.Series) -> list[str]:
    """Un aviso por tipo de nota de la curación (``NOTAS_CURADA``), con el recuento y sus notas distintas."""
    avisos = []
    baja = nota.str.lower()
    for marca, descripcion in NOTAS_CURADA.items():
        filas = baja.str.contains(marca, regex=False)
        if not filas.any():
            continue
        partes = sorted({p for n in nota[filas] for p in n.split("; ") if marca in p.lower()})
        citadas = "; ".join(partes[:_MAX_NOTAS_CITADAS])
        if len(partes) > _MAX_NOTAS_CITADAS:
            citadas += f" (y {len(partes) - _MAX_NOTAS_CITADAS} notas más)"
        avisos.append(f"{descripcion} en {int(filas.sum())} periodos: {citadas}")
    return avisos


def _avisos_serie(datos: pd.DataFrame, curada: bool = False) -> list[str]:
    """Avisos de una respuesta, agregados: como mucho uno por tipo (huecos, fechas, revisiones...).

    Bloque 3: una fila ``vintage_exacto`` (ALFRED) no avisa; sí las filas anteriores a ALFRED
    (valor del primer vintage con la fecha de la regla previa), los índices re-estimados enteros,
    la unidad por vintage y las ediciones de los ficheros académicos (vintage ``AAAA-MM``).
    Paso 4 (``curada``): también las notas de la curación (``NOTAS_CURADA``).
    """
    avisos = []
    nulos = datos[datos["valor"].isna()]
    if len(nulos) <= MAX_HUECOS_DETALLADOS:
        for fila in nulos.itertuples(index=False):
            avisos.append(f"{_iso(fila.fecha_referencia)}: valor nulo (hueco declarado): "
                          f"{_sin_notas_comunes(fila.nota, curada)}")
    else:
        notas = sorted({_sin_notas_comunes(n, curada) for n in nulos["nota"]})
        detalle = "; ".join(notas[:3]) + (f" (y {len(notas) - 3} notas más)" if len(notas) > 3 else "")
        avisos.append(f"{len(nulos)} periodos con valor nulo (huecos declarados) entre "
                      f"{_iso(nulos['fecha_referencia'].min())} y {_iso(nulos['fecha_referencia'].max())}: {detalle}")
    nota = datos["nota"].fillna("").astype(str)
    previas = _contiene(nota, NOTA_PREVIA_ALFRED)
    lag = (datos["metodo_publicacion"] == "lag_fijo") & ~previas
    medidas = _contiene(nota, NOTA_EXCEPCION)
    if previas.any():
        primera = nota[previas].iloc[0]
        desde = primera[primera.index(NOTA_PREVIA_ALFRED) + len(NOTA_PREVIA_ALFRED):].split(";")[0].strip(" ()")
        avisos.append(f"{int(previas.sum())} periodos anteriores a ALFRED (primer vintage {desde}): llevan el valor "
                      f"de ese primer vintage, ya revisado, con la fecha de la regla previa (lag_fijo): posible "
                      f"fuga de revisiones y fecha de publicación aproximada")
    if lag.any():
        avisos.append(f"fecha de publicación por regla en {int(lag.sum())} periodos (método lag_fijo: retraso "
                      f"declarado en lags.yaml, no la fecha real de cada publicación; corregido con la primera "
                      f"vintage de ALFRED en {int((lag & medidas).sum())} periodos)")
    elif medidas.any():
        avisos.append(f"fecha de publicación retrasada a la primera vintage de ALFRED en {int(medidas.sum())} "
                      f"periodos (la regla de su publicador la adelantaba)")
    reconstruidas = _contiene(nota, NOTA_RECONSTRUIDA)
    if reconstruidas.any():
        primera = nota[reconstruidas].iloc[0]
        desde = primera[primera.index(NOTA_RECONSTRUIDA) + len(NOTA_RECONSTRUIDA):].split(";")[0].strip()
        avisos.append(f"{int(reconstruidas.sum())} periodos con fecha de publicación anterior a la creación del "
                      f"índice ({desde}): son valores reconstruidos hacia atrás que nadie conocía en su fecha")
    reestimada = _contiene(nota, NOTA_REESTIMADA)
    if reestimada.any():
        exactas = datos.loc[reestimada & (datos["metodo_publicacion"] == "vintage_exacto"), "vintage"]
        ultimo = f" (último vintage visible: {exactas.max()})" if len(exactas) else ""
        avisos.append(f"índice re-estimado entero en cada publicación: los {int(reestimada.sum())} periodos son los "
                      f"del vintage vigente en la fecha{ultimo}; en otra fecha cambian también los valores antiguos")
    if _contiene(nota, NOTA_UNIDAD_VINTAGE).any():
        avisos.append("unidad del vintage vigente (año base o dólares encadenados): los niveles de vintages "
                      "distintos no son comparables entre sí")
    # Ediciones de los ficheros académicos (vintage AAAA-MM): una por descarga archivada.
    vint = datos["vintage"].astype(str)
    edicion = vint.str.fullmatch(r"\d{4}-\d{2}")
    if edicion.any():
        primera_ed = _contiene(nota, NOTA_PRIMERA_EDICION) & edicion
        ediciones = sorted(set(vint[edicion]))
        lista_ed = ", ".join(ediciones) if len(ediciones) <= 6 else f"{ediciones[0]} … {ediciones[-1]}"
        avisos.append(f"valores por edición del fichero (vintage AAAA-MM): {int(edicion.sum())} periodos de "
                      f"{len(ediciones)} ediciones ({lista_ed}); la última visible en la fecha es "
                      f"{ediciones[-1]}" + (f"; {int(primera_ed.sum())} periodos con el valor de la primera edición "
                                            f"archivada: posible fuga de revisiones anteriores a ella"
                                            if primera_ed.any() else ""))
    # Series revisables cargadas con el último vintage o edición (bloque 2): lo dice la nota de la fila.
    revisadas = es_nota_revisable(datos["nota"]) & ~_contiene(nota, NOTA_PRIMERA_EDICION)
    if revisadas.any():
        avisos.append(f"serie revisable con los valores del último vintage o edición en {int(revisadas.sum())} "
                      f"periodos: posible fuga de revisiones (no son los valores que se conocían en su fecha)")
    if curada:
        avisos += _avisos_curada(nota)
    return avisos


# --- Datos atrasados (paso 4, solo base='curada') -------------------------------------------------
# Días hábiles (lunes a viernes, sin festivos) entre el último dato visible y la fecha pedida a partir de los
# cuales se avisa de datos atrasados. 10 (dos semanas): más que cualquier cierre de mercado seguido (Año Nuevo
# chino, Semana Santa) y que el retraso de publicación de una serie diaria, pero salta con un ticker sin
# refrescar (las acciones no estadounidenses llegan a octubre de 2026 hasta el 3b-2) o que dejó de cotizar.
MAX_DIAS_HABILES_ATRASO = 10
# Series: solo diarias o semanales (paso mediano entre las últimas fechas de referencia de 7 días o menos). El
# umbral es el mayor entre MAX_DIAS_HABILES_ATRASO y MULTIPLO_RITMO veces su ritmo de publicación (mediana, en
# días hábiles, entre sus últimas fechas de publicación distintas): una diaria que se publica una vez al mes
# (factores diarios de Ken French) no avisa por eso. Con menos de 3 fechas de publicación distintas (ediciones
# que reescriben toda la historia) no se puede medir el ritmo y no se avisa.
MAX_DIAS_PASO_ATRASO = 7
MULTIPLO_RITMO = 3
_ULTIMAS_ATRASO = 60   # fechas de referencia que se miran para el paso y el ritmo


def _dias_habiles(desde: pd.Timestamp, hasta: pd.Timestamp) -> int:
    """Días de lunes a viernes en ``(desde, hasta]`` (0 si ``hasta <= desde``)."""
    d0 = np.datetime64(pd.Timestamp(desde).date(), "D") + 1
    d1 = np.datetime64(pd.Timestamp(hasta).date(), "D") + 1
    return max(int(np.busday_count(d0, d1)), 0)


def _aviso_atraso_serie(serie: str, visibles: pd.DataFrame, f: pd.Timestamp) -> str | None:
    """Aviso si una serie diaria o semanal lleva sin publicar más de lo que dice su ritmo (ver ``MULTIPLO_RITMO``)."""
    ult = visibles.tail(_ULTIMAS_ATRASO)
    refs = pd.DatetimeIndex(ult["fecha_referencia"].dropna()).sort_values()
    if len(refs) < 3 or np.median(np.diff(refs.values).astype("timedelta64[D]").astype(int)) > MAX_DIAS_PASO_ATRASO:
        return None
    pubs = np.sort(pd.DatetimeIndex(ult["fecha_publicacion"].dropna().unique()).values.astype("datetime64[D]"))
    if len(pubs) < 3:
        return None
    ritmo = float(np.median(np.busday_count(pubs[:-1], pubs[1:])))
    ultima_pub = pd.Timestamp(visibles["fecha_publicacion"].max())
    n = _dias_habiles(ultima_pub, f)
    if n <= max(MAX_DIAS_HABILES_ATRASO, MULTIPLO_RITMO * ritmo):
        return None
    return (f"{serie}: última fecha de referencia {_iso(refs[-1])} (publicada {_iso(ultima_pub)}, {n} días hábiles "
            f"antes de {_iso(f)}): datos atrasados (refresco pendiente o sin publicación)")


# Saneado P10 (2026-11-21): el aviso de datos atrasados vale para TODAS las frecuencias. En las de paso mediano mayor
# de MAX_DIAS_PASO_ATRASO (mensuales, trimestrales, anuales...) avisa si desde la última fecha de referencia visible
# han pasado más días que su retraso mediano de publicación + PERIODOS_ATRASO periodos + MARGEN_ATRASO_DIAS (la misma
# regla que la auditoría de saneado). Las series que se retrasan por diseño (SIN_AVISO_ATRASO: ediciones anuales,
# proyecciones de la CBO, recesiones del NBER fechadas con 24 meses) no avisan por eso. Una serie retirada por la fuente
# (estado «retirada» del catálogo) avisa siempre que su último dato quede atrás.
PERIODOS_ATRASO = 2
MARGEN_ATRASO_DIAS = 10
SIN_AVISO_ATRASO = ("fred:USRECD", "fred:GDPPOT", "fred:NROU", "gw:*")


def _sin_aviso_atraso(serie: str) -> bool:
    return any(fnmatch.fnmatchcase(serie, p) for p in SIN_AVISO_ATRASO)


def _aviso_atraso_periodica(serie: str, visibles: pd.DataFrame, f: pd.Timestamp) -> str | None:
    """Aviso de una serie de paso mayor de una semana parada más allá de su retraso mediano + 2 periodos + margen."""
    ult = visibles[visibles["valor"].notna()].tail(_ULTIMAS_ATRASO)
    refs = pd.DatetimeIndex(ult["fecha_referencia"].dropna()).sort_values()
    if len(refs) < 3 or _sin_aviso_atraso(serie):
        return None
    paso = float(np.median(np.diff(refs.values).astype("timedelta64[D]").astype(int)))
    if paso <= MAX_DIAS_PASO_ATRASO:
        return None
    lag = float(np.median((ult["fecha_publicacion"] - ult["fecha_referencia"]).dt.days.tail(12)))
    umbral = lag + PERIODOS_ATRASO * paso + MARGEN_ATRASO_DIAS
    dias = int((f - refs[-1]).days)
    if dias <= umbral:
        return None
    ultima_pub = pd.Timestamp(ult["fecha_publicacion"].max())
    return (f"{serie}: última fecha de referencia {_iso(refs[-1])} (publicada {_iso(ultima_pub)}), {dias} días antes de "
            f"{_iso(f)}, más que su retraso mediano ({lag:.0f} días) + {PERIODOS_ATRASO} periodos de {paso:.0f} días + "
            f"{MARGEN_ATRASO_DIAS}: datos atrasados (serie parada, refresco pendiente o sin publicación)")


#: Una serie retirada solo se avisa como tal cuando lleva sin publicar al menos esto (o 2 periodos, si es más): antes,
#: en la fecha de la decisión aún no se sabía que la fuente la dejaría (TimeGate; verificación del catálogo, 2026-11-23).
MARGEN_RETIRADA_DIAS = 92


def dias_sin_publicar_retirada(referencias: pd.Series) -> int:
    """Días sin publicar a partir de los cuales una serie retirada se da por retirada: ``MARGEN_RETIRADA_DIAS`` o
    2 veces la mediana de la separación entre sus fechas de referencia, si es mayor (una anual, unos dos años)."""
    u = pd.DatetimeIndex(pd.Series(referencias).dropna().unique()).sort_values()
    paso = float(np.median(np.diff(u.values).astype("timedelta64[D]").astype(int))) if len(u) > 1 else 0.0
    return int(max(MARGEN_RETIRADA_DIAS, 2 * paso))


def _aviso_retirada(serie: str, visibles: pd.DataFrame, f: pd.Timestamp) -> str | None:
    """Aviso de una serie que la fuente ya no publica (estado ``retirada`` del catálogo), solo si en ``f`` ya lleva
    ``dias_sin_publicar_retirada`` días sin publicar (si no, revelaría que la retirarán: TimeGate)."""
    e = cat_mod._cat(None).get(serie) or {}
    if e.get("estado") != "retirada":
        return None
    con_valor = visibles.loc[visibles["valor"].notna(), "fecha_referencia"]
    if con_valor.empty:
        return None
    ultima_pub = pd.Timestamp(visibles["fecha_publicacion"].max())
    if (f - ultima_pub).days < dias_sin_publicar_retirada(visibles["fecha_referencia"]):
        return None
    return (f"{serie}: serie retirada por la fuente (catálogo); último dato visible {_iso(con_valor.max())}: no se "
            f"actualiza más, usa su sustituta si la hay")


# Saneado P19: aviso con el % de periodos vacíos (valor nulo) de la ventana pedida, desde este umbral.
MIN_PCT_VACIOS = 1.0


def _aviso_vacios(serie: str, datos: pd.DataFrame) -> str | None:
    """«X de N periodos (P %) vacíos entre A y B» si la ventana devuelta tiene al menos ``MIN_PCT_VACIOS`` % de nulos."""
    n = len(datos)
    if not n:
        return None
    vacios = int(datos["valor"].isna().sum())
    pct = 100.0 * vacios / n
    if pct < MIN_PCT_VACIOS:
        return None
    return (f"{serie}: {vacios} de {n} periodos ({pct:.1f} %) vacíos entre {_iso(datos['fecha_referencia'].min())} y "
            f"{_iso(datos['fecha_referencia'].max())}: trátalos (no se rellenan con valores posteriores)")


# Saneado P20: zona euro con la composición FIJA de hoy retropolada (los países actuales también antes de entrar en el
# euro). La versión de composición de cada fecha (U2 del BCE, EA de Eurostat) se prefiere como canónico donde existe.
_ZONA_EURO_FIJA = re.compile(r"EA2[01]|EA19|\.XM\.|\.XM$|EMU|\.I\d+\.")
_ZONA_EURO_NO_IMPORTA = ("bis:WS_CBPOL.M.XM", "bis:WS_EER.M.R.B.XM")   # tipo oficial y TCE del euro: no cambia el dato
AVISO_ZONA_EURO_FIJA = ("{s}: zona euro con la composición fija de hoy retropolada (antes de su entrada, cuenta países "
                        "que aún no estaban en el euro); la de composición de cada fecha es U2 (BCE) o EA (Eurostat)")

# Lista curada (``config/lista_curada.yaml``) en caché por mtime: historia previa (``completa_a``) y notas.
_CACHE_LISTA: dict[str, tuple[int, dict[str, dict], dict[str, list[str]]]] = {}


def _lista_curada() -> tuple[dict[str, dict], dict[str, list[str]]]:
    from ingesta.mercados_series import preprocesado as pp

    ruta = pp.RUTA_LISTA
    try:
        mt = ruta.stat().st_mtime_ns
    except FileNotFoundError:
        return {}, {}
    g = _CACHE_LISTA.get(str(ruta))
    if g is None or g[0] != mt:
        lista = pp.cargar_lista(ruta)
        previas: dict[str, list[str]] = {}
        for sid, e in lista.items():
            if e.get("completa_a") and e.get("decision") == "queda":
                previas.setdefault(str(e["completa_a"]), []).append(sid)
        g = _CACHE_LISTA[str(ruta)] = (mt, lista, previas)
    return g[1], g[2]


_FECHA_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _nota_visible(nota: str, f: pd.Timestamp | None) -> bool:
    """Una nota de la lista curada que cita una fecha posterior a ``f`` (p. ej. «parado el 2026-10-13») no se sabía."""
    return f is None or all(pd.Timestamp(d) <= f for d in _FECHA_ISO.findall(nota))


def _avisos_lista(serie: str, fecha: FechaLike | None = None,
                  visible: Callable[[str], bool] | None = None) -> list[str]:
    """Avisos estáticos de la lista curada (sin valores): historia previa, composición de la zona euro, notas.

    Con ``fecha`` (``get_serie``), TimeGate: la serie de destino de una historia previa (``completa_a``) o de origen
    solo se nombra si ``visible(id)`` (algo publicado hasta ``fecha``), y una nota que cita una fecha posterior no
    sale. Sin ``fecha``, todos (uso interno y tests).
    """
    lista, previas = _lista_curada()
    f = timegate.fecha_decision(fecha) if fecha is not None else None
    ve = visible if (visible is not None and f is not None) else (lambda _s: True)
    e = lista.get(serie) or {}
    out = []
    if e.get("completa_a") and ve(str(e["completa_a"])):
        out.append(f"{serie}: historia previa de {e['completa_a']} (serie más antigua o parada del mismo concepto; "
                   f"desde donde acaba, usa {e['completa_a']}): no mezclar los dos niveles sin revisar el salto")
    anteriores = [p for p in sorted(previas.get(serie, [])) if ve(p)]
    if anteriores:
        out.append(f"{serie}: su historia anterior está en {', '.join(anteriores)} (historia previa)")
    if _ZONA_EURO_FIJA.search(serie) and serie not in _ZONA_EURO_NO_IMPORTA:
        out.append(AVISO_ZONA_EURO_FIJA.format(s=serie))
    if e.get("nota") and _nota_visible(str(e["nota"]), f):
        out.append(f"{serie}: {e['nota']}")
    return out


def _visible_en_curada(serie: str, f: pd.Timestamp) -> bool:
    """¿Tiene ``serie`` alguna fila publicada hasta ``f`` en la base curada? (solo lee la columna de fechas)."""
    import pyarrow.parquet as pq

    ruta = almacen.ruta_series(curada=True)
    if not ruta.exists():
        return False
    filtros = [("serie", "==", serie), ("fecha_publicacion", "<=", f.to_datetime64())]
    return pq.read_table(ruta, columns=["fecha_publicacion"], filters=filtros).num_rows > 0


_MESES_PERIODO = (1, 3, 6, 12)


def _meses_periodo(referencias: pd.Series) -> int:
    """Meses del periodo de una serie (1, 3, 6 o 12) o 0 si es diaria o no se puede inferir.

    Periódica = todas las ``fecha_referencia`` son día 1 y hay al menos dos; el periodo es la
    separación mínima en meses entre referencias consecutivas.
    """
    u = pd.DatetimeIndex(referencias.dropna().unique()).sort_values()
    if len(u) < 2 or (u.day != 1).any():
        return 0
    paso = int(np.diff(u.year * 12 + u.month).min())
    return paso if paso in _MESES_PERIODO else 0


def get_serie(id: str, fecha: FechaLike, *, desde: FechaLike | None = None, divisa: str = "original",
              base: BaseLike = None, alias: dict[str, str] | None = None,
              base_fx: pd.DataFrame | None = None) -> RespuestaSerie:
    """Serie ``id`` tal como se conocía en ``fecha`` (``timegate.as_of_series``).

    ``id``: canónico con prefijo de fuente (``'fred:DGS10'``) o alias de la Fase 1 (``'VIX'``),
    resuelto con ``alias`` o, por defecto, con ``alias_por_defecto()`` (catálogo de series y
    ``publicaciones.yaml``). Una ETF que el catálogo excluye de la base (``excluida_ajustada``)
    lanza ``KeyError`` con un mensaje que remite a ``get_precios`` (si ya cotizaba en ``fecha``; si no, el neutro).
    ``desde``: recorta por ``fecha_referencia >= desde`` (con un aviso si no queda nada).

    ``base`` (paso 4; mismo TimeGate y mismo truncado en las dos):

    - ``'curada'`` (por defecto: ``None`` se resuelve a ``BASE_DEFECTO``, P01 del saneado): la base curada
      (``series/base_curada.parquet``). **Es la de los agentes y el backtest.** Un id que es alias en ``series/alias.parquet`` (también tras resolver el alias de la
      Fase 1) sirve su canónico con el aviso «alias de X: se sirve el canónico»; una proyección (tabla
      aparte ``series/proyecciones.parquet``) lanza ``KeyError`` que remite a ``get_proyeccion``, solo si
      tiene algo publicado hasta ``fecha`` (si no, el mensaje neutro); las notas de la curación
      (``NOTAS_CURADA``: fecha no medible, tramo conservador, escala corregida) añaden su aviso.
      Una serie diaria o semanal que lleva sin publicar más de ``MAX_DIAS_HABILES_ATRASO`` días hábiles
      (o ``MULTIPLO_RITMO`` veces su ritmo de publicación, si es mayor) avisa «datos atrasados»; las
      mensuales, trimestrales o anuales no. El FX de ``divisa='USD'`` sale también de la base curada.
    - ``'trabajo'``: la base de trabajo del almacén (``almacen.leer_ultimas``), sin las fechas prudentes del
      curado ni el corte. Solo para auditar, depurar y construir: hay que pedirla a mano.
    - una tabla del contrato en memoria (tests, recortes): se usa tal cual, sin alias ni avisos de
      la curación.

    ``base_fx``: tabla con el FX (por defecto la tabla de ``base`` si se pasó una, si no el almacén
    de la base elegida).

    ``divisa``: ``'original'`` o ``'USD'``. Con ``'USD'`` los datos llevan siempre
    ``divisa_original``, ``fx_usd`` y ``fx_fecha`` (como ``get_precios``): una serie en USD lleva
    ``fx_usd = 1``; una no monetaria, ``fx_usd`` nulo y un aviso. El FX es el del BCE visible en
    ``fecha`` en el fin del periodo de cada valor: la fecha de referencia en una serie diaria; el
    último día del mes, trimestre, semestre o año en una periódica (fechas de referencia en día
    1, periodo inferido de las visibles; con un solo periodo visible, su día 1). Si ese día aún no
    tenía fixing visible en ``fecha`` (periodo en curso), se usa el último visible y se avisa.

    ``KeyError`` si no hay nada publicado del id hasta ``fecha``, tanto si no existe como si se
    publicará después (no se revela cuál). Unidad, divisa y fuente salen de filas visibles. Un
    periodo con valor nulo (hueco permanente) se devuelve nulo y añade un aviso con su nota (con
    más de ``MAX_HUECOS_DETALLADOS``, uno solo con el recuento, el primero, el último y las notas
    distintas); el método ``lag_fijo`` añade el aviso «fecha de publicación por regla»; una fecha
    retrasada a la primera vintage de ALFRED, una serie reconstruida hacia atrás y una revisable
    cargada con el último vintage o edición (``catalogo.NOTAS_REVISABLE``) añaden el suyo. Bloque 3:
    las filas ``vintage_exacto`` de ALFRED no avisan; sí las anteriores a ALFRED (valor del primer
    vintage con la fecha de la regla previa), los índices re-estimados enteros, la unidad por
    vintage y las ediciones de los ficheros académicos (vintage ``AAAA-MM``). Como mucho un aviso
    por tipo. Un id sin alias se resuelve sin distinguir mayúsculas si es único.
    """
    f = timegate.fecha_decision(fecha)
    _validar_opcion(divisa, DIVISAS_SALIDA, "divisa")
    tabla_base, curada = _modo_base(base)
    canonico = _resolver_fase1(id, alias)
    avisos: list[str] = []
    if curada:
        canonico, avisos = _resolver_alias_curada(canonico, id)
    _comprobar_excluida(canonico, id, f if tabla_base is None else None, curada)
    corte = timegate.fecha_decision(desde) if desde is not None else None
    # Del almacén: solo la serie, lo publicado hasta f y la última fila por periodo (resuelto en Arrow).
    tabla = tabla_base if tabla_base is not None else almacen.leer_ultimas(canonico, f, curada=curada)
    visibles = timegate.as_of_series(tabla, canonico, f)
    if visibles.empty:
        nombre = repr(canonico) if canonico == id else f"{canonico!r} (alias {id!r})"
        if curada and not almacen.leer_proyecciones(canonico, f).empty:
            raise KeyError(f"serie {nombre}: es una proyección (tabla aparte de la base curada, no un dato de su "
                           f"fecha de referencia): usa get_proyeccion({canonico!r}, fecha)")
        raise KeyError(f"serie {nombre} sin datos publicados hasta {_iso(f)} "
                       f"(desconocida o aún no publicada)")
    # Unidad, divisa y fuente son constantes por serie (contrato); se toman de lo visible.
    meta = visibles.iloc[-1]
    unidad, divisa_serie, fuente = _texto(meta["unidad"]), _texto(meta["divisa"]), _texto(meta["fuente"])

    meses = _meses_periodo(visibles["fecha_referencia"])
    datos = visibles[list(COLUMNAS_DATOS_SERIE)]
    if corte is not None:
        datos = datos[datos["fecha_referencia"] >= corte]
        if datos.empty:
            avisos.append(f"{canonico}: ningún periodo visible en {_iso(f)} desde {_iso(corte)}")
    datos = datos.reset_index(drop=True)
    avisos += _avisos_serie(datos, curada)
    if curada:
        atraso = (_aviso_retirada(canonico, visibles, f) or _aviso_atraso_serie(canonico, visibles, f)
                  or _aviso_atraso_periodica(canonico, visibles, f))
        if atraso:
            avisos.append(atraso)
        avisos += _avisos_lista(canonico, f, lambda s: _visible_en_curada(s, f))
        vacios = _aviso_vacios(canonico, datos)
        if vacios:
            avisos.append(vacios)

    columnas = dict(COLUMNAS_DATOS_SERIE)
    divisa_salida = divisa_serie
    if divisa == "USD":
        columnas |= _COLUMNAS_FX
        if divisa_serie is None:
            avisos.append(f"{canonico} no es monetaria (sin divisa): se devuelve sin convertir")
            datos = datos.assign(divisa_original=None, fx_usd=np.nan, fx_fecha=pd.NaT)
        elif _es_tipo_de_cambio(canonico):
            # Las cotizaciones del BCE (X por 1 EUR) llevan divisa X, pero son tipos de cambio, no importes:
            # convertirlas daría USD por EUR con la unidad «X por 1 EUR». Mismo criterio que fred:DEX*.
            avisos.append(f"{canonico} es un tipo de cambio (cotización, no un importe en {divisa_serie}): "
                          "se devuelve sin convertir")
            datos = datos.assign(divisa_original=divisa_serie, fx_usd=np.nan, fx_fecha=pd.NaT)
        else:
            fx = base_fx if base_fx is not None else (
                tabla_base if tabla_base is not None else _base_fx([divisa_serie], curada=curada))
            ref = datos["fecha_referencia"]
            fecha_fx = ref + pd.offsets.MonthEnd(meses) if meses else ref
            convertidos = divisas.a_usd(datos.assign(divisa=divisa_serie, fecha_fx=fecha_fx), ["valor"],
                                        "divisa", fx, f, "fecha_fx")
            avisos += convertidos.attrs.get("avisos", [])
            datos = convertidos.drop(columns=["divisa", "fecha_fx"])
            divisa_salida = "USD"
    datos = datos[list(columnas)].astype(columnas).reset_index(drop=True)
    datos.attrs = {}
    metodo = _texto(datos["metodo_publicacion"].iloc[-1]) if len(datos) else None
    return RespuestaSerie(serie=canonico, fecha=f, datos=datos, unidad=unidad, divisa=divisa_salida,
                          fuente=fuente, metodo_publicacion=metodo, avisos=avisos)


def _es_tipo_de_cambio(serie: str) -> bool:
    """True en las cotizaciones de divisas del BCE (``divisas.SERIE_FX``: ``ecb:EXR.D.<X>.EUR``)."""
    prefijo, _, sufijo = divisas.SERIE_FX.partition("{divisa}")
    return serie.startswith(prefijo) and serie.endswith(sufijo)


def _base_fx(divisas_necesarias: Sequence[str], curada: bool = False) -> pd.DataFrame:
    """Series de FX que hacen falta para convertir ``divisas_necesarias`` (BCE y la secundaria de la Fed H.10,
    ``divisas.series_fx``; leídas del almacén, de la base curada con ``curada``)."""
    ids = divisas.series_fx(divisas_necesarias)
    if not ids:
        return vacio_series()
    return almacen.leer_series(sorted(ids), curada=curada)


# --- get_precios --------------------------------------------------------------------------------
def _precios_ticker(tk: str, base: pd.DataFrame | None, proveedor: str, curada: bool = False) -> pd.DataFrame:
    if base is not None:
        return base[base["ticker"] == tk]
    return almacen.leer_precios(tk, proveedor, curada=curada)


def _publicar_ajuste(ajustado: pd.DataFrame, ajuste: str) -> pd.DataFrame:
    """Columnas de salida con el ajuste pedido (las ajustadas ocupan el sitio de las crudas)."""
    out = ajustado.copy()
    for destino, origen in _ORIGEN_AJUSTE[ajuste].items():
        out[destino] = ajustado[origen]
    out = out[list(COLUMNAS_DATOS_PRECIOS)]
    out.attrs = {}
    return out


def get_precios(tk: str | Sequence[str], fecha: FechaLike, *, desde: FechaLike | None = None,
                ajuste: Ajuste = "total", divisa: str = "USD", base: BaseLike = None,
                base_fx: pd.DataFrame | None = None, proveedor: str = "yahoo") -> RespuestaPrecios:
    """Precios de ``tk`` (uno o varios) con el ajuste que se conocía en ``fecha``.

    ``ajuste``: ``'ninguno'`` (as-traded), ``'splits'`` o ``'total'`` (splits y dividendos), vía
    ``timegate.ajustar_a_fecha`` POR TICKER y con ``fecha`` (nunca con eventos posteriores).
    ``divisa``: ``'USD'`` (subunidades normalizadas y FX del BCE visible en ``fecha``, por sesión)
    u ``'original'``. ``desde`` recorta por ``sesion >= desde`` DESPUÉS de ajustar (el ajuste no
    depende de ``desde``).

    ``base`` (paso 4; mismo TimeGate, mismo ajuste a la fecha y mismo truncado en las dos):

    - ``'curada'`` (por defecto: ``None`` se resuelve a ``BASE_DEFECTO``, P01 del saneado):
      ``precios_curados/<proveedor>/``, con las propuestas del EDA aplicadas (sin velas de
      relleno fuera de calendario; aperturas de relleno a nulo, con un aviso por ticker). **Es la de los
      agentes y el backtest.** Un ticker que la curación deja fuera recibe el mismo aviso neutro que uno
      desconocido. Si la última sesión visible queda más de ``MAX_DIAS_HABILES_ATRASO`` días hábiles antes
      de ``fecha``, avisa «última sesión AAAA-MM-DD: datos atrasados (refresco pendiente o sin
      cotización)»: ticker sin refrescar (acciones no estadounidenses hasta el 3b-2) o que dejó de cotizar.
      El FX de ``divisa='USD'`` sale de la base curada de series.
    - ``'trabajo'``: ``precios/<proveedor>/`` (``almacen.leer_precios``), la descarga tal cual. Solo para
      auditar, depurar y construir: hay que pedirla a mano.
    - una tabla de precios del contrato en memoria (tests, recortes): se usa tal cual.

    ``base_fx``: tabla de series con el FX (por defecto ``almacen.leer_series`` de la base elegida).

    ``proveedor``: carpeta del almacén (``'yahoo'`` por defecto). La cripto de Coinbase va en
    ``proveedor='coinbase'`` con prefijo ``cb:`` en el ticker: ``get_precios('cb:BTC-USD', fecha,
    proveedor='coinbase')`` (también ``cb:ETH-USD``). Vela diaria UTC, visible en D+1 a las 00:30 UTC
    (mercado ``CRYPTO``), en USD, sin dividendos ni splits. Un ticker ``cb:`` pedido a otro proveedor
    no aporta filas y su aviso lo recuerda.

    Un ticker sin nada publicado hasta ``fecha`` no lanza: no aporta filas y añade el mismo aviso
    neutro tanto si no existe como si cotizará después (no se revela cuál ni desde cuándo). Un
    ticker que ``desde`` deja sin filas, los dividendos que no se pueden ajustar y las sesiones
    sin FX también se avisan.
    """
    f = timegate.fecha_decision(fecha)
    _validar_opcion(ajuste, AJUSTES, "ajuste")
    _validar_opcion(divisa, DIVISAS_SALIDA, "divisa")
    lista = [tk] if isinstance(tk, str) else list(tk)
    if not lista or not all(isinstance(t, str) and t for t in lista):
        raise ValueError(f"tickers vacíos o no textuales: {tk!r}")
    tickers = list(dict.fromkeys(lista))
    corte = timegate.fecha_decision(desde) if desde is not None else None
    tabla_base, curada = _modo_base(base)
    donde = " en la base curada" if curada else ""

    avisos: list[str] = []
    tablas = []
    for t in tickers:
        crudo = _precios_ticker(t, tabla_base, proveedor, curada)
        # avisar=False: los avisos vuelven en attrs, sin tocar el estado global de warnings.
        ajustado = timegate.ajustar_a_fecha(crudo, f, avisar=False)
        if ajustado.empty:
            pista = (f"; los tickers {PREFIJO_COINBASE} son de proveedor='coinbase'"
                     if t.startswith(PREFIJO_COINBASE) and proveedor != "coinbase" else "")
            avisos.append(f"{t}: sin sesiones publicadas hasta {_iso(f)} (ticker desconocido para "
                          f"{proveedor!r}{donde} o aún sin datos{pista})")
            continue
        avisos += ajustado.attrs.get("avisos", [])
        if curada:
            ultima = pd.Timestamp(ajustado["sesion"].max())
            n = _dias_habiles(ultima, f)
            if n > MAX_DIAS_HABILES_ATRASO:
                avisos.append(f"{t}: última sesión {_iso(ultima)}: datos atrasados (refresco pendiente o sin "
                              f"cotización; {n} días hábiles antes de {_iso(f)})")
        salida = _publicar_ajuste(ajustado, ajuste)
        if corte is not None:
            salida = salida[salida["sesion"] >= corte]
            if salida.empty:
                avisos.append(f"{t}: ninguna sesión visible en {_iso(f)} desde {_iso(corte)}")
                continue
        if curada and salida["open"].isna().any():
            n = int(salida["open"].isna().sum())
            avisos.append(f"{t}: {n} sesiones con apertura nula (relleno del proveedor quitado en la base curada: "
                          f"open == close y high == low); no valen como apertura de t+1")
        tablas.append(salida)

    columnas = dict(COLUMNAS_DATOS_PRECIOS)
    datos = pd.concat(tablas, ignore_index=True) if tablas else _vacio(columnas)
    if divisa == "USD":
        columnas |= _COLUMNAS_FX
        if len(datos):
            necesarias = sorted(set(datos["divisa"]))
            fx = base_fx if base_fx is not None else _base_fx(necesarias, curada=curada)
            datos = divisas.a_usd(datos, list(_MONETARIAS_PRECIOS), "divisa", fx, f, "sesion")
            avisos += datos.attrs.get("avisos", [])
            datos.attrs = {}
        else:
            datos = _vacio(columnas)
    datos = datos[list(columnas)].astype(columnas).reset_index(drop=True)
    return RespuestaPrecios(tickers=tickers, fecha=f, datos=datos, ajuste=ajuste, divisa=divisa,
                            avisos=avisos)


# --- get_proyeccion (paso 4) --------------------------------------------------------------------
# Columnas de más de ``get_proyeccion`` (tabla de proyecciones del paso 4, preprocesado.yaml).
COLUMNAS_PROYECCION: dict[str, str] = {"horizonte": REAL, "edicion": TEXTO}


def get_proyeccion(id: str, fecha: FechaLike, *, desde: FechaLike | None = None,
                   alias: dict[str, str] | None = None) -> RespuestaSerie:
    """Proyección ``id`` (WEO del FMI o SEP del FOMC) tal como se conocía en ``fecha``.

    Lee la tabla aparte de la base curada (``series/proyecciones.parquet``, paso 4): las
    proyecciones no salen por ``get_serie(base='curada')`` porque no son datos de su fecha de
    referencia. Mismo TimeGate y truncado que ``get_serie``: solo filas con ``fecha_publicacion <=
    fecha``; por cada ``fecha_referencia`` (año proyectado), la de la última edición visible (mayor
    ``fecha_publicacion`` y, en empate, mayor ``vintage``). ``datos`` lleva ``COLUMNAS_DATOS_SERIE``
    más ``horizonte`` (años desde la edición) y ``edicion``. ``KeyError`` neutro si no hay nada
    publicado hasta ``fecha`` (no se revela si existirá). ``desde`` recorta por ``fecha_referencia``.
    Avisos: el de proyección (siempre), los de ``get_serie`` y los de la curación.
    """
    f = timegate.fecha_decision(fecha)
    canonico = _resolver_fase1(id, alias)
    corte = timegate.fecha_decision(desde) if desde is not None else None
    tabla = almacen.leer_proyecciones(canonico, f)
    nombre = repr(canonico) if canonico == id else f"{canonico!r} (alias {id!r})"
    if tabla.empty:
        raise KeyError(f"proyección {nombre} sin datos publicados hasta {_iso(f)} (desconocida o aún no publicada)")
    for col, tipo in COLUMNAS_PROYECCION.items():
        if col not in tabla.columns:
            tabla[col] = tabla["vintage"] if col == "edicion" else pd.Series(index=tabla.index, dtype=tipo)
    orden = tabla.sort_values(["fecha_referencia", "fecha_publicacion", "vintage"], kind="mergesort")
    visibles = orden.drop_duplicates("fecha_referencia", keep="last").reset_index(drop=True)
    meta = visibles.iloc[-1]
    columnas = dict(COLUMNAS_DATOS_SERIE) | COLUMNAS_PROYECCION
    datos = visibles[list(columnas)].astype(columnas)
    ediciones = sorted(set(datos["edicion"].dropna()))
    ultima = ediciones[-1] if ediciones else "sin edición"
    avisos = [f"{canonico}: proyección, no un dato observado de su periodo: cada fecha_referencia lleva la última "
              f"edición visible en {_iso(f)} ({len(ediciones)} ediciones; la última, {ultima})"]
    if corte is not None:
        datos = datos[datos["fecha_referencia"] >= corte]
        if datos.empty:
            avisos.append(f"{canonico}: ningún periodo visible en {_iso(f)} desde {_iso(corte)}")
    datos = datos.reset_index(drop=True)
    avisos += _avisos_serie(datos, curada=True)
    datos.attrs = {}
    metodo = _texto(datos["metodo_publicacion"].iloc[-1]) if len(datos) else None
    return RespuestaSerie(serie=canonico, fecha=f, datos=datos, unidad=_texto(meta["unidad"]),
                          divisa=_texto(meta["divisa"]), fuente=_texto(meta["fuente"]),
                          metodo_publicacion=metodo, avisos=avisos)


__all__ = [
    "AJUSTES", "BASES", "COLUMNAS_DATOS_PRECIOS", "COLUMNAS_DATOS_SERIE", "COLUMNAS_PROYECCION", "DIVISAS_SALIDA",
    "MAX_DIAS_HABILES_ATRASO", "NOTAS_CURADA", "PREFIJO_COINBASE", "RespuestaPrecios", "RespuestaSerie", "alias_curada", "alias_por_defecto", "get_precios",
    "get_proyeccion", "get_serie", "resolver_id",
]
