"""EDA del Tema 1 (paso 3 de la descarga completa, decisión E7): **solo detecta y propone; nunca corrige**.

Mira TODAS las series de la base (``series/base_series.parquet``) y todos los ficheros de
``precios/<proveedor>/``; la lista curada (``seleccion``) decide luego qué se queda y el notebook
``03_seleccion_eda`` filtra. Salidas en ``results/ingesta/mercados_series/tablas/`` (solo fechas, banderas
y medidas de tamaño normalizadas; NUNCA valores de las series ni precios):

- ``eda_series.csv``: una fila por serie con indicadores y banderas (``COLUMNAS_SERIES_EDA``).
- ``eda_series_incidencias.csv``: una fila por incidencia (``COLUMNAS_INC_SERIES``).
- ``eda_precios.csv``: una fila por fichero de precios (``COLUMNAS_PRECIOS_EDA``).
- ``eda_precios_incidencias.csv``: una fila por incidencia (``COLUMNAS_INC_PRECIOS``).
- ``eda_resumen.csv``: recuentos por ámbito, tipo y fuente (series) o clase (precios).

Cada incidencia lleva ``propuesta_paso4``. ``PROPUESTAS`` (público y estable, para ``preprocesado.yaml``) da
la propuesta por defecto de CADA tipo que emite el módulo («marcar», «nulo + aviso», «revisar a mano», «sin
acción» o «reescalar vintages anteriores»); ``EXCEPCIONES_PROPUESTA`` dice cuándo una fila lleva otra. Es una
propuesta: el paso 4 decide. La descripción de cada tipo (``NOTAS``) va una sola vez,
en ``eda_resumen.csv``; la ``nota`` de una incidencia solo añade lo propio (vintage, calendario, tipo
administrado...).

**Series.** Forma de la serie: el ÚLTIMO vintage de cada (``serie``, ``fecha_referencia``) con valor
(``unico`` cuenta como el más reciente; los vintages ``AAAA-MM-DD`` o ``AAAA-MM`` se ordenan por fecha).

1. ``hueco_largo``: racha de más de ``MIN_HUECO`` periodos sin dato entre dos observaciones, según la
   frecuencia del catálogo (diarias: días L–V, así un festivo suelto no cuenta). ``fecha``/``fecha_fin``:
   primer y último periodo que faltan; ``tamano``: periodos.
2. ``salto``: cambio entre observaciones seguidas a más de ``UMBRAL_MAD`` desviaciones robustas
   (1,4826 · MAD) de los cambios de la serie. Cambio en log si la serie es un nivel positivo
   (``usa_log``); si no, diferencia. Si más de la mitad de los cambios son 0 (series escalonadas: tipos
   oficiales, precios administrados), la escala se mide sobre los cambios distintos de 0; los cambios de
   coma flotante (``TOLERANCIA_CAMBIO``) cuentan como 0. La escala es la mayor de la global y la local de
   un año (``VENTANAS_LOCALES``; ver ``saltos_robustos``).
   ``ruptura_nivel``: salto de la mediana móvil (``VENTANAS`` por frecuencia: mediana de las ``w``
   observaciones siguientes menos la de las ``w`` anteriores) a más de ``UMBRAL_MAD`` veces la mayor de
   la dispersión local (IQR / 1,349 de las dos ventanas) y la escala robusta de los cambios; una
   incidencia por tramo seguido sobre el umbral, en su máximo. ``tamano``: desviaciones, con signo.
   Fuera: las ``0/1``. En los tipos de ``base.SIN_RACHAS`` el escalón es normal: «sin acción».
3. ``cambio_unidad``: entre dos vintages consecutivos de una misma fecha de referencia, la mediana de
   ``log10(|nuevo| / |anterior|)`` por vintage es de ``FACTOR_UNIDAD`` (10) o más en valor absoluto.
   Las series con ``unidad_por_vintage`` en el catálogo lo tienen declarado (año base o dólares
   encadenados de cada vintage): se cuentan igual, con propuesta «sin acción». ``tamano``: log10 del factor.
   Si el factor es una potencia de 10 casi exacta (``TOLERANCIA_POTENCIA``) sobre al menos
   ``MIN_FECHAS_UNIDAD`` fechas comunes, es un cambio de unidad confirmado (los seis revisados a mano: ×1000
   en REVOLSL, TOTALSL, BCNSDODNS, CMDEBT y TNWBSHNO, ×0,001 en BOGMBASE): propuesta «reescalar vintages anteriores» y
   ``factor`` = la potencia de 10 por la que se multiplican los vintages ANTERIORES para casar con el nuevo.
4. Escalas raras (``escala_rara``): ``pct_parece_tanto_por_uno`` (unidad en %, todos los valores en
   [-1, 1] y alguno distinto de 0) y ``tanto_por_uno_parece_pct`` (unidad en tanto por uno y mediana de
   |valor| > 1). ``negativo_en_nivel``: valores <= 0 en una serie de nivel que debe ser positiva
   (``es_nivel_positivo``: índices de base 100, puntos de índice, tipos de cambio, precios y recuentos);
   ``tamano``: observaciones.
5. ``racha_plana``: ``base.MIN_RACHA`` o más observaciones diarias seguidas con el mismo valor (el mismo
   criterio ``>=`` que ``base.anotar_anomalias``), salvo ``base.SIN_RACHAS``, los tipos de cambio de H.10 y
   del BCE (paridades fijas) y las ``0/1``. ``tamano``: observaciones. En las series escalonadas por
   construcción (``ESCALONADAS``: el libre de riesgo diario de Ken French, el tipo mensual repartido en días)
   la racha se cuenta, pero con propuesta «sin acción», como el escalón de un tipo administrado.
6. ``fin_de_semana`` (``base.NOTA_FIN_DE_SEMANA``) y ``festivo``: datos ``cierre_mercado`` en sábado o
   domingo, o en un día L–V que el calendario del país (``pais_zona`` de ``inventario_series.csv``,
   ``CALENDARIO_PAIS``) da cerrado. Sin país conocido, solo el fin de semana.

``eda_series.csv`` cuenta también las notas que ya puso ``base.anotar_anomalias`` (pico, fin de semana y
racha) para contrastar.

**Precios.** Por fichero, con ``calidad.incidencias_precios`` (``volumen_cero``, ``cierre_repetido`` y
``dividendo_alto``; su ``salto`` con el split deshecho solo queda como columna ``salto_calidad`` de
``eda_precios.csv``: casi siempre es el mismo evento que ``salto_sin_split``, más informativo) y además:

1. ``salto_sin_split``: |Δlog close| > ``UMBRAL_SALTO_PRECIO`` sin split ni dividendo esa sesión ni la
   siguiente (Yahoo a veces fecha el evento un día tarde). ``abs_dlog``: |Δlog| redondeado.
2. ``contrasplit`` (split < 1; ``abs_dlog``: |log split|) y ``split_fraccionario``: split > 1 no entero
   (3:2, 5:4, acciones liberadas...) que NO explica el movimiento del precio esa sesión,
   |log(close_t · split / close_{t-1})| > ``UMBRAL_SPLIT_RESIDUO`` (``abs_dlog``: ese residuo). Los que sí lo
   explican son eventos normales y no se marcan.
3. ``apertura_igual_cierre``: sesiones con ``open == close`` y ``high == low`` (relleno de Yahoo; importa
   porque se ejecuta a la apertura de t+1). Una fila por ticker (primera y última sesión, ``n`` y ``pct``).
4. ``sesion_faltante``: días hábiles del calendario de ``exchange_calendars`` del mercado (``CALENDARIO_MERCADO``,
   desde ``INICIO_CALENDARIO`` o el límite del calendario) sin vela; ``sesion_fuera_calendario``: velas en
   días que el calendario da cerrados. Mercado sin calendario: días L–V (``calendario = 'L-V'``). Una fila por
   ticker. Las velas fuera de calendario que repiten el cierre previo y no tienen volumen son relleno de
   Yahoo en festivos (sobre todo antes de 2006): ``sesion_fuera_calendario_relleno``, «nulo + aviso»; las
   demás, ``sesion_fuera_calendario``, «revisar a mano». Esas velas NO cuentan en ``cierre_repetido`` ni en
   ``volumen_cero``.
5. ``serie_sospechosa`` (columnas ``serie_sospechosa`` y ``motivo_sospecha`` de ``eda_precios.csv`` y una
   incidencia por ticker): historial roto que la selección deja «con aviso» (``motivos_sospecha``).

Los tipos muy frecuentes (``volumen_cero``, ``cierre_repetido``, ``apertura_igual_cierre``,
``sesion_faltante`` y ``sesion_fuera_calendario``) van agregados: una fila por ticker con la primera y la
última fecha, ``n`` y ``pct`` (de las sesiones). Los demás, una fila por sesión.

En las dos tablas de incidencias se guardan como mucho ``MAX_POR_SERIE`` filas por serie (o ticker) y
tipo, las de mayor tamaño; ``eda_series.csv``, ``eda_precios.csv`` y ``eda_resumen.csv`` cuentan todas.

CLI: ``python -m ingesta.mercados_series.eda [--destino DIR] [--solo series|precios] [--tickers A,B]``.
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import time
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ingesta.comun.rutas import corpus_dir, resultados_dir
from ingesta.mercados_series import almacen, calidad
from ingesta.mercados_series import base as base_mod
from ingesta.mercados_series import catalogo as cat_mod

TEMA = "mercados_series"
log = logging.getLogger(__name__)

# --- Umbrales -----------------------------------------------------------------------------------
UMBRAL_MAD = 8.0                 # desviaciones robustas (saltos y rupturas de nivel)
K_MAD = 1.4826                   # MAD -> desviación típica de una normal
K_IQR = 1.349                    # IQR -> desviación típica de una normal
MIN_HUECO = 3                    # un hueco largo tiene MÁS de 3 periodos sin dato
FACTOR_UNIDAD = 10.0             # cambio de escala entre vintages consecutivos
UMBRAL_SALTO_PRECIO = 0.4        # |Δlog close|
UMBRAL_SPLIT_RESIDUO = 0.2       # |log(close_t · split / close_{t-1})|: el split no explica el precio
TOLERANCIA_POTENCIA = 0.02       # |log10 factor - entero| para un cambio de unidad confirmado
MIN_FECHAS_UNIDAD = 30           # fechas comunes mínimas para confirmarlo
# Serie sospechosa (historial roto): umbrales de motivos_sospecha.
SOSPECHA_SALTOS = 20             # más de 20 saltos sin split
SOSPECHA_PCT_REPETIDO = 40.0     # más del 40 % de cierres repetidos (sin las velas de relleno)
SOSPECHA_PCT_APERTURA = 50.0     # más del 50 % de aperturas iguales al cierre desde 2000 (no en fondos)
MIN_OBS = 12                     # observaciones mínimas para saltos y escalas
VENTANAS = {"diaria": 60, "semanal": 26, "mensual": 12, "trimestral": 8, "anual": 5}
# Ventana (centrada) de la dispersión local de los cambios en los saltos: un año de datos, tres en las mensuales.
VENTANAS_LOCALES = {"diaria": 250, "semanal": 52, "mensual": 36, "trimestral": 20}
TOLERANCIA_CAMBIO = 1e-9         # |cambio| <= 1e-9 · max|serie| cuenta como 0 (ruido de coma flotante)
MAX_POR_SERIE = 100              # filas por serie (o ticker) y tipo en las tablas de incidencias
INICIO_CALENDARIO = "1990-01-01"
CASOS_SALTO = ("AAPL", "ASML.AS", "CL=F", "NVDA", "SHEL.L", "^VIX")
CASOS_SPLIT = ("XLF", "EWJ", "USO", "ETHA", "SAN.MC")

PROPUESTAS = {
    # series
    "hueco_largo": "marcar",
    "salto": "revisar a mano",
    "ruptura_nivel": "revisar a mano",
    "cambio_unidad": "revisar a mano",           # ver EXCEPCIONES_PROPUESTA
    "pct_parece_tanto_por_uno": "revisar a mano",
    "tanto_por_uno_parece_pct": "revisar a mano",
    "negativo_en_nivel": "nulo + aviso",
    "racha_plana": "marcar",
    "fin_de_semana": "marcar",
    "festivo": "marcar",
    # precios
    "salto_sin_split": "revisar a mano",
    "contrasplit": "marcar",
    "split_fraccionario": "marcar",
    "volumen_cero": "marcar",
    "cierre_repetido": "marcar",
    "dividendo_alto": "revisar a mano",
    "apertura_igual_cierre": "nulo + aviso",
    "sesion_faltante": "marcar",
    "sesion_fuera_calendario": "revisar a mano",
    "sesion_fuera_calendario_relleno": "nulo + aviso",
    "serie_sospechosa": "marcar",
}
SIN_ACCION = "sin acción"
REESCALAR = "reescalar vintages anteriores"
# Filas que llevan otra propuesta que la de PROPUESTAS[tipo] (la nota de la fila lo dice).
EXCEPCIONES_PROPUESTA = {
    ("cambio_unidad", "declarado en el catálogo (unidad_por_vintage)"): SIN_ACCION,
    ("cambio_unidad", "potencia de 10 confirmada"): REESCALAR,
    ("hueco_largo", "tipo administrado (base.SIN_RACHAS)"): SIN_ACCION,
    ("salto", "tipo administrado (base.SIN_RACHAS)"): SIN_ACCION,
    ("ruptura_nivel", "tipo administrado (base.SIN_RACHAS)"): SIN_ACCION,
    ("racha_plana", "escalonada por construcción (ESCALONADAS)"): SIN_ACCION,
}
# Series escalonadas por construcción: el libre de riesgo diario de Ken French es el tipo de la letra a un mes
# repartido en los días del mes, así que repite el mismo dato muchos días seguidos sin estar congelado.
ESCALONADAS = ("ff:F3D.RF", "ff:F5D.RF")
NOTAS = {
    "hueco_largo": "periodos seguidos sin dato (frecuencia del catálogo; diarias en días L-V)",
    "salto": "cambio a más de 8 desviaciones robustas de los cambios de la serie",
    "ruptura_nivel": "salto de la mediana móvil (antes frente a después)",
    "cambio_unidad": "cambio de escala entre vintages consecutivos (log10 del factor)",
    "pct_parece_tanto_por_uno": "unidad en %, pero todos los valores en [-1, 1]",
    "tanto_por_uno_parece_pct": "unidad en tanto por uno, pero mediana de |valor| > 1",
    "negativo_en_nivel": "valores <= 0 en una serie de nivel que debe ser positiva",
    "racha_plana": f"{base_mod.NOTA_RACHA} {base_mod.MIN_RACHA} o más observaciones diarias seguidas con el mismo dato",
    "fin_de_semana": base_mod.NOTA_FIN_DE_SEMANA,
    "festivo": "posible error de fecha de la fuente: cierre de mercado en festivo",
    "salto_sin_split": "|Δlog close| > 0,4 sin split ni dividendo esa sesión ni la siguiente",
    "contrasplit": "split < 1 (contrasplit)",
    "split_fraccionario": "split > 1 no entero que no explica el precio: |log(close_t·split/close_t-1)| > 0,2",
    "volumen_cero": "calidad.incidencias_precios: volumen 0 en instrumento con volumen",
    "cierre_repetido": "calidad.incidencias_precios: cierre igual al de la sesión previa",
    "dividendo_alto": "calidad.incidencias_precios: dividendo > 20 % del cierre previo",
    "apertura_igual_cierre": "open == close y high == low: relleno de Yahoo; no vale como apertura de t+1",
    "sesion_faltante": "día hábil del calendario del mercado sin vela",
    "sesion_fuera_calendario": "vela en un día que el calendario del mercado da cerrado (con movimiento o volumen)",
    "sesion_fuera_calendario_relleno": "vela de relleno en día cerrado: repite el cierre y no tiene volumen",
    "serie_sospechosa": "historial roto: muchos saltos sin split, cierres repetidos o aperturas de relleno",
}
AGREGADOS_PRECIOS = ("volumen_cero", "cierre_repetido", "apertura_igual_cierre", "sesion_faltante",
                     "sesion_fuera_calendario", "sesion_fuera_calendario_relleno", "serie_sospechosa")

# Calendarios de exchange_calendars por mercado de config/mercados.yaml (None: días L-V).
CALENDARIO_MERCADO = {
    "XNYS": "XNYS", "XNAS": "XNYS", "ARCX": "XNYS", "NAV_US": "XNYS", "CBOE_IDX": "XNYS", "ICE_MOVE": "XNYS",
    "ICE_DXY": None, "FX_YAHOO": "24/5", "CME": "CMES", "XTSE": "XTSE", "BVMF": "BVMF", "XLON": "XLON",
    "XETR": "XETR", "XPAR": "XPAR", "XAMS": "XAMS", "XMAD": "XMAD", "XMIL": "XMIL", "XSWX": "XSWX",
    "XTKS": "XTKS", "XHKG": "XHKG", "XSHG": "XSHG", "XNSE": "XBOM", "XBOM": "XBOM", "XKRX": "XKRX",
    "XTAI": "XTAI", "XASX": "XASX", "XTAE": "XTAE", "XJSE": "XJSE", "CRYPTO": "24/7", "STOXX_IDX": "XETR",
}
# Calendario para los festivos de las series de cierre de mercado, por pais_zona del inventario.
CALENDARIO_PAIS = {"USA": "XNYS", "US": "XNYS", "JPN": "XTKS", "JP": "XTKS", "GBR": "XLON", "GB": "XLON",
                   "UK": "XLON", "DEU": "XETR", "DE": "XETR", "FRA": "XPAR", "FR": "XPAR", "CAN": "XTSE",
                   "CA": "XTSE", "CHE": "XSWX", "ESP": "XMAD", "ITA": "XMIL", "IT": "XMIL", "AUS": "XASX",
                   "HKG": "XHKG", "KOR": "XKRX", "BRA": "BVMF"}

# --- Columnas de salida -------------------------------------------------------------------------
COLUMNAS_SERIES_EDA = (
    "serie", "fuente", "frecuencia", "metodo", "unidad", "n_obs", "desde", "hasta", "n_vintages",
    "transformacion", "max_hueco_periodos", "max_hueco_desde", "max_hueco_hasta", "n_huecos_largos",
    "n_saltos", "max_salto_desviaciones", "n_rupturas", "max_ruptura_desviaciones", "unidad_por_vintage",
    "n_cambios_unidad", "max_cambio_unidad_log10", "escala_rara", "n_negativos_nivel", "max_racha_plana",
    "n_rachas_planas", "rachas_excluidas", "n_fin_de_semana", "n_festivos", "calendario_festivos",
    "notas_base_pico", "notas_base_fin_de_semana", "notas_base_racha", "banderas",
)
COLUMNAS_INC_SERIES = ("serie", "fuente", "frecuencia", "tipo", "fecha", "fecha_fin", "tamano", "medida", "factor",
                       "nota", "propuesta_paso4")
COLUMNAS_PRECIOS_EDA = (
    "ticker", "proveedor", "clase", "mercado", "calendario", "desde", "hasta", "sesiones", "salto_calidad",
    "volumen_cero", "cierre_repetido", "dividendo_alto", "saltos_sin_split", "max_abs_dlog_sin_split",
    "contrasplits", "splits_fraccionarios", "pct_apertura_igual_cierre", "pct_apertura_igual_cierre_desde_2000",
    "ultima_apertura_igual_cierre", "calendario_desde", "sesiones_faltantes", "pct_sesiones_faltantes",
    "sesiones_fuera_calendario", "fuera_calendario_relleno", "pct_cierre_repetido", "serie_sospechosa",
    "motivo_sospecha", "caso_conocido", "banderas",
)
COLUMNAS_INC_PRECIOS = ("ticker", "proveedor", "clase", "mercado", "tipo", "fecha", "fecha_fin", "n", "abs_dlog",
                        "pct", "nota", "propuesta_paso4")
COLUMNAS_RESUMEN = ("ambito", "tipo", "grupo", "n_filas", "n_eventos", "n_afectadas", "propuesta_paso4",
                    "descripcion")
PROHIBIDAS = frozenset({"valor", "open", "high", "low", "close", "volume", "dividendo"})


# --- Utilidades ---------------------------------------------------------------------------------
def _iso(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    t = pd.Timestamp(v)
    return None if pd.isna(t) else t.strftime("%Y-%m-%d")


def _dias(fechas: Any) -> np.ndarray:
    return np.asarray(pd.to_datetime(fechas)).astype("datetime64[D]")


def escala_robusta(d: np.ndarray) -> float:
    """1,4826 · MAD de los cambios ``d``. Si más de la mitad son 0 (serie escalonada), el centro es 0 y la
    escala es 1,4826 · la mediana de |cambio| de los distintos de 0 (el escalón típico). NaN sin escala."""
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan")
    mad = K_MAD * float(np.median(np.abs(d - np.median(d))))
    if mad > 0:
        return mad
    nz = np.abs(d[d != 0])
    if len(nz) < 2:
        return float("nan")
    mad = K_MAD * float(np.median(nz))
    return mad if mad > 0 else float("nan")


_TASA = re.compile(r"^(%|puntos porcentuales|puntos básicos|tanto por uno|0/1|índice de difusión|"
                   r"índice \((desviaciones|0 =|escalado))")
_NIVEL_POSITIVO = re.compile(r"= 100\)|^índice \(año base|^índice \(100 = |^puntos de índice|^USD por |"
                             r" por 1 [A-Z]{3}$|^miles de (personas|vacantes|viviendas|despidos)$|^número de|"
                             r"^millones de vehículos|^horas semanales|^meses de oferta|^ratio \(")


def es_tasa(unidad: Any) -> bool:
    """La unidad es un tipo, un porcentaje, un tanto por uno, un 0/1 o un índice centrado (cambios en diferencia)."""
    return bool(_TASA.search(str(unidad or "")))


def es_nivel_positivo(unidad: Any) -> bool:
    """La unidad es un nivel que no puede ser <= 0 (índice de base 100, puntos de índice, cambio, precio, recuento)."""
    return bool(_NIVEL_POSITIVO.search(str(unidad or "")))


def usa_log(x: np.ndarray, unidad: Any) -> bool:
    """Cambios en log: nivel positivo (todos los valores > 0) que no es una tasa."""
    return bool(len(x) and (x > 0).all() and not es_tasa(unidad))


def _ordinal(fechas: np.ndarray, frecuencia: str | None) -> np.ndarray | None:
    t = pd.DatetimeIndex(fechas)
    if frecuencia == "semanal":
        return np.floor((fechas.astype("int64") + 3) / 7).astype("int64")
    if frecuencia == "mensual":
        return (t.year * 12 + t.month - 1).to_numpy()
    if frecuencia == "trimestral":
        return (t.year * 4 + (t.month - 1) // 3).to_numpy()
    if frecuencia == "anual":
        return t.year.to_numpy()
    return None


def _desplazar(d: np.datetime64, frecuencia: str | None, n: int) -> np.datetime64:
    """``d`` movida ``n`` periodos (diarias: días L-V)."""
    if frecuencia == "diaria" or frecuencia is None:
        return np.busday_offset(d, n, roll="forward" if n > 0 else "backward")
    t = pd.Timestamp(d)
    off = {"semanal": pd.DateOffset(weeks=n), "mensual": pd.DateOffset(months=n),
           "trimestral": pd.DateOffset(months=3 * n), "anual": pd.DateOffset(years=n)}[frecuencia]
    return np.datetime64((t + off).date(), "D")


# --- Detectores de series (funciones puras; sin valores en la salida) ----------------------------
def huecos(fechas: Any, frecuencia: str | None, min_hueco: int = MIN_HUECO) -> pd.DataFrame:
    """Rachas de más de ``min_hueco`` periodos sin dato: ``desde``, ``hasta`` (periodos que faltan), ``periodos``."""
    f = np.unique(_dias(fechas))
    vacio = pd.DataFrame({"desde": pd.Series(dtype="datetime64[ns]"), "hasta": pd.Series(dtype="datetime64[ns]"),
                          "periodos": pd.Series(dtype="int64")})
    if len(f) < 2:
        return vacio
    orden = _ordinal(f, frecuencia)
    if orden is None:                                    # diaria (o sin frecuencia): días L-V
        falta = np.busday_count(f[:-1], f[1:]) - 1
    else:
        orden = np.unique(orden)
        if len(orden) < 2:
            return vacio
        f = f[np.r_[True, np.diff(_ordinal(f, frecuencia)) != 0]]    # una fecha por periodo
        falta = np.diff(orden) - 1
    falta = np.clip(falta, 0, None)
    i = np.flatnonzero(falta > min_hueco)
    if not len(i):
        return vacio
    desde = [_desplazar(f[k], frecuencia, 1) for k in i]
    hasta = [_desplazar(f[k + 1], frecuencia, -1) for k in i]
    return pd.DataFrame({"desde": pd.to_datetime(desde), "hasta": pd.to_datetime(hasta),
                         "periodos": falta[i].astype("int64")})


def cambios(t: np.ndarray) -> np.ndarray:
    """Cambios entre observaciones seguidas, con los de tamaño de coma flotante (``TOLERANCIA_CAMBIO``) a 0."""
    t = np.asarray(t, dtype=float)
    d = np.diff(t)
    if len(t):
        d[np.abs(d) <= TOLERANCIA_CAMBIO * np.nanmax(np.abs(t))] = 0.0
    return d


def saltos_robustos(fechas: Any, x: Any, log_: bool = False, umbral: float = UMBRAL_MAD,
                    frecuencia: str | None = None) -> pd.DataFrame:
    """Cambios a más de ``umbral`` desviaciones robustas: ``fecha`` (la del valor nuevo) y ``desviaciones``.

    Escala: la mayor de la global (``escala_robusta`` de todos los cambios) y la local (IQR / 1,349 de los
    cambios en una ventana centrada de ``VENTANAS_LOCALES[frecuencia]``). La local solo puede bajar la
    puntuación: evita marcar a cientos los días normales de un periodo agitado (tipos de los 80, 2008) y deja
    igual los saltos de un periodo tranquilo. Sin ventana local para la frecuencia, solo la global.
    """
    f = np.asarray(pd.to_datetime(fechas))
    v = np.asarray(x, dtype=float)
    vacio = pd.DataFrame({"fecha": pd.Series(dtype="datetime64[ns]"), "desviaciones": pd.Series(dtype=float)})
    if len(v) < MIN_OBS:
        return vacio
    t = np.log(v) if log_ else v
    d = cambios(t)
    esc = escala_robusta(d)
    if not np.isfinite(esc):
        return vacio
    den = np.full(len(d), esc)
    wl = VENTANAS_LOCALES.get(frecuencia or "")
    if wl and len(d) >= wl:
        r = pd.Series(d).rolling(wl, center=True, min_periods=wl // 2)
        local = ((r.quantile(0.75) - r.quantile(0.25)) / K_IQR).to_numpy()
        den = np.fmax(den, np.nan_to_num(local))
    z = (d - np.median(d[np.isfinite(d)])) / den
    i = np.flatnonzero(np.abs(z) > umbral)
    return pd.DataFrame({"fecha": f[i + 1], "desviaciones": np.round(z[i], 1)})


def rupturas_nivel(fechas: Any, x: Any, frecuencia: str | None, log_: bool = False,
                   umbral: float = UMBRAL_MAD, ventana: int | None = None) -> pd.DataFrame:
    """Saltos de la mediana móvil (``w`` después menos ``w`` antes) a más de ``umbral`` veces la mayor de la
    dispersión local y la escala de los cambios; una fila por tramo sobre el umbral (en su máximo)."""
    f = np.asarray(pd.to_datetime(fechas))
    v = np.asarray(x, dtype=float)
    w = ventana or VENTANAS.get(frecuencia or "", 12)
    vacio = pd.DataFrame({"fecha": pd.Series(dtype="datetime64[ns]"), "desviaciones": pd.Series(dtype=float)})
    if len(v) < 2 * w + 1:
        return vacio
    t = pd.Series(np.log(v) if log_ else v)
    esc = escala_robusta(cambios(t.to_numpy()))
    if not np.isfinite(esc):
        return vacio
    antes = t.rolling(w)
    med_b = antes.median().shift(1)
    iqr_b = (antes.quantile(0.75) - antes.quantile(0.25)).shift(1)
    inv = t[::-1].reset_index(drop=True).rolling(w)
    med_a = pd.Series(inv.median().to_numpy()[::-1])
    iqr_a = pd.Series((inv.quantile(0.75) - inv.quantile(0.25)).to_numpy()[::-1])
    local = np.fmax(iqr_b.to_numpy(), iqr_a.to_numpy()) / K_IQR
    z = (med_a - med_b).to_numpy() / np.fmax(local, esc)
    sobre = np.abs(np.nan_to_num(z)) > umbral
    if not sobre.any():
        return vacio
    tramo = np.cumsum(np.r_[True, sobre[1:] != sobre[:-1]])
    filas = []
    for k in np.unique(tramo[sobre]):
        idx = np.flatnonzero(tramo == k)
        j = idx[np.argmax(np.abs(z[idx]))]
        filas.append((f[j], round(float(z[j]), 1)))
    return pd.DataFrame(filas, columns=["fecha", "desviaciones"])


def rachas_planas(fechas: Any, x: Any, min_racha: int = base_mod.MIN_RACHA) -> pd.DataFrame:
    """Rachas de ``min_racha`` o más observaciones seguidas con el mismo valor: ``desde``, ``hasta``, ``obs``."""
    f = np.asarray(pd.to_datetime(fechas))
    v = np.asarray(x, dtype=float)
    vacio = pd.DataFrame({"desde": pd.Series(dtype="datetime64[ns]"), "hasta": pd.Series(dtype="datetime64[ns]"),
                          "obs": pd.Series(dtype="int64")})
    if len(v) < min_racha:
        return vacio
    nuevo = np.r_[True, v[1:] != v[:-1]]
    inicio = np.flatnonzero(nuevo)
    largo = np.diff(np.r_[inicio, len(v)])
    k = np.flatnonzero(largo >= min_racha)
    return pd.DataFrame({"desde": f[inicio[k]], "hasta": f[inicio[k] + largo[k] - 1], "obs": largo[k].astype("int64")})


def cambios_unidad(df: pd.DataFrame, factor: float = FACTOR_UNIDAD) -> pd.DataFrame:
    """Cambios de escala entre vintages consecutivos de cada (``serie``, ``fecha_referencia``).

    ``df``: ``serie``, ``fecha_referencia``, ``orden_vintage`` (número creciente), ``vintage`` y ``valor`` (sin
    nulos). Devuelve ``serie``, ``vintage``, ``log10_factor`` (mediana sobre las fechas comunes) y ``n``, solo
    los vintages con |log10_factor| >= log10(``factor``).
    """
    cols = ["serie", "vintage", "log10_factor", "n"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.sort_values(["serie", "fecha_referencia", "orden_vintage"], kind="mergesort")
    v = np.abs(d["valor"].to_numpy(dtype=float))
    serie = (d["serie"].cat.codes.to_numpy() if isinstance(d["serie"].dtype, pd.CategoricalDtype)
             else pd.factorize(d["serie"])[0])
    nombres = d["serie"].to_numpy()
    ref = d["fecha_referencia"].to_numpy()
    misma = np.r_[False, (serie[1:] == serie[:-1]) & (ref[1:] == ref[:-1])]
    previo = np.r_[np.nan, v[:-1]]
    ok = misma & (v > 0) & (previo > 0)
    if not ok.any():
        return pd.DataFrame(columns=cols)
    r = pd.DataFrame({"serie": nombres[ok], "vintage": d["vintage"].to_numpy()[ok],
                      "orden": d["orden_vintage"].to_numpy()[ok], "lr": np.log10(v[ok] / previo[ok])})
    g = r.groupby(["serie", "orden", "vintage"], observed=True, sort=True)["lr"].agg(["median", "size"])
    g = g[np.abs(g["median"]) >= math.log10(factor)].reset_index()
    return pd.DataFrame({"serie": g["serie"].astype(str), "vintage": g["vintage"].astype(str),
                         "log10_factor": g["median"].round(2), "n": g["size"].astype("int64")})


PCT_PEQUENOS = frozenset({"% (tipo del día)"})     # un tipo diario en % es menor que 1 de verdad


def es_potencia_confirmada(log10_factor: float, n: int) -> bool:
    """Cambio de unidad confirmado: potencia de 10 casi exacta sobre ``MIN_FECHAS_UNIDAD`` fechas comunes o más."""
    lf = float(log10_factor)
    return bool(abs(lf) >= 1 and abs(lf - round(lf)) <= TOLERANCIA_POTENCIA and int(n) >= MIN_FECHAS_UNIDAD)


def escala_rara(x: Any, unidad: Any) -> str | None:
    """``pct_parece_tanto_por_uno``, ``tanto_por_uno_parece_pct`` o ``None`` (sin las unidades de ``PCT_PEQUENOS``)."""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    u = str(unidad or "")
    if len(v) < MIN_OBS:
        return None
    if u.startswith("%") and u not in PCT_PEQUENOS and (np.abs(v) <= 1).all() and (v != 0).any():
        return "pct_parece_tanto_por_uno"
    if u.startswith("tanto por uno") and float(np.median(np.abs(v))) > 1:
        return "tanto_por_uno_parece_pct"
    return None


def no_positivos(fechas: Any, x: Any, unidad: Any) -> pd.DataFrame:
    """Valores <= 0 en series de nivel positivo: una fila por tramo seguido (``desde``, ``hasta``, ``obs``)."""
    f = np.asarray(pd.to_datetime(fechas))
    v = np.asarray(x, dtype=float)
    vacio = pd.DataFrame({"desde": pd.Series(dtype="datetime64[ns]"), "hasta": pd.Series(dtype="datetime64[ns]"),
                          "obs": pd.Series(dtype="int64")})
    if not es_nivel_positivo(unidad):
        return vacio
    m = v <= 0
    if not m.any():
        return vacio
    tramo = np.cumsum(np.r_[True, m[1:] != m[:-1]])
    filas = [(f[idx[0]], f[idx[-1]], len(idx)) for k in np.unique(tramo[m]) for idx in [np.flatnonzero(tramo == k)]]
    return pd.DataFrame(filas, columns=["desde", "hasta", "obs"])


@lru_cache(maxsize=None)
def sesiones_calendario(nombre: str) -> np.ndarray:
    """Sesiones (``datetime64[D]``) del calendario de ``exchange_calendars`` desde ``INICIO_CALENDARIO`` (o su
    límite inferior) hasta hoy."""
    import exchange_calendars as xcals
    from exchange_calendars.calendar_utils import _default_calendar_factories as fabricas

    inicio = pd.Timestamp(INICIO_CALENDARIO)
    minimo = fabricas[nombre].bound_min() if nombre in fabricas else None
    if minimo is not None:
        inicio = max(inicio, pd.Timestamp(minimo).tz_localize(None))
    fin = pd.Timestamp.today().normalize()
    cal = xcals.get_calendar(nombre, start=inicio.strftime("%Y-%m-%d"), end=fin.strftime("%Y-%m-%d"))
    return np.asarray(cal.sessions.tz_localize(None) if cal.sessions.tz else cal.sessions).astype("datetime64[D]")


def fechas_raras(fechas: Any, calendario: str | None = None,
                 sesiones: np.ndarray | None = None) -> pd.DataFrame:
    """Fechas en fin de semana (``fin_de_semana``) o en día L-V que el calendario da cerrado (``festivo``)."""
    f = np.unique(_dias(fechas))
    finde = ~np.is_busday(f)
    filas = [pd.DataFrame({"fecha": f[finde].astype("datetime64[ns]"), "tipo": "fin_de_semana"})]
    if calendario is not None or sesiones is not None:
        s = sesiones if sesiones is not None else sesiones_calendario(calendario)
        if len(s):
            dentro = (~finde) & (f >= s[0]) & (f <= s[-1])
            fest = dentro & ~np.isin(f, s)
            filas.append(pd.DataFrame({"fecha": f[fest].astype("datetime64[ns]"), "tipo": "festivo"}))
    return pd.concat(filas, ignore_index=True)


# --- Detectores de precios ----------------------------------------------------------------------
def _ordenar(p: pd.DataFrame) -> pd.DataFrame:
    return p.sort_values("sesion", kind="mergesort").reset_index(drop=True)


def saltos_sin_split(p: pd.DataFrame, umbral: float = UMBRAL_SALTO_PRECIO) -> pd.DataFrame:
    """|Δlog close| > ``umbral`` sin split ni dividendo esa sesión ni la siguiente: ``sesion``, ``abs_dlog``.

    Un cierre <= 0 (el WTI de abril de 2020) deja el Δlog sin definir: se marca con ``abs_dlog`` nulo y
    ``no_positivo = True``.
    """
    p = _ordenar(p[p["close"].notna()])
    c = p["close"].to_numpy(dtype=float)
    vacio = pd.DataFrame({"sesion": pd.Series(dtype="datetime64[ns]"), "abs_dlog": pd.Series(dtype=float),
                          "no_positivo": pd.Series(dtype=bool)})
    if len(c) < 2:
        return vacio
    with np.errstate(divide="ignore", invalid="ignore"):
        dlog = np.r_[np.nan, np.diff(np.log(c))]
    no_pos = np.r_[False, (c[1:] <= 0) | (c[:-1] <= 0)]
    split = p["split"].fillna(1.0).to_numpy(dtype=float)
    div = p["dividendo"].fillna(0.0).to_numpy(dtype=float)
    evento = (split != 1.0) | (div > 0)
    evento_sig = np.r_[evento[1:], False]
    m = ((np.isfinite(dlog) & (np.abs(dlog) > umbral)) | no_pos) & ~evento & ~evento_sig
    return pd.DataFrame({"sesion": p["sesion"].to_numpy()[m], "abs_dlog": np.round(np.abs(dlog[m]), 3),
                         "no_positivo": no_pos[m]})


def splits_raros(p: pd.DataFrame, umbral: float = UMBRAL_SPLIT_RESIDUO) -> pd.DataFrame:
    """Splits < 1 (``contrasplit``; ``abs_dlog`` = |log split|) y splits > 1 no enteros que no explican el
    precio (``split_fraccionario``; ``abs_dlog`` = |log(close_t · split / close_{t-1})| > ``umbral``; sin cierre
    previo con que comprobarlo, también, con ``abs_dlog`` nulo): ``sesion``, ``tipo``, ``abs_dlog``."""
    p = _ordenar(p)
    s = p["split"].to_numpy(dtype=float)
    c = p["close"].to_numpy(dtype=float)
    previo = pd.Series(np.r_[np.nan, c[:-1]]).ffill().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        residuo = np.abs(np.log(c * s / previo))
    ok = np.isfinite(s) & (s > 0) & (s != 1.0)
    contra = ok & (s < 1)
    no_entero = ok & (s > 1) & (np.abs(s - np.round(s)) > 1e-6)
    frac = no_entero & ~(np.isfinite(residuo) & (residuo <= umbral))
    m = contra | frac
    tam = np.where(contra, np.abs(np.log(np.where(ok, s, 1.0))), residuo)
    return pd.DataFrame({"sesion": p["sesion"].to_numpy()[m],
                         "tipo": np.where(contra[m], "contrasplit", "split_fraccionario"),
                         "abs_dlog": np.round(tam[m], 3)}).reset_index(drop=True)


def apertura_igual_cierre(p: pd.DataFrame) -> pd.Series:
    """Máscara de las sesiones con ``open == close`` y ``high == low`` (todas no nulas)."""
    o, h, lo, c = (p[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    return pd.Series(np.isfinite(o) & np.isfinite(c) & (o == c) & (h == lo), index=p.index)


def sesiones_faltantes(sesiones: Any, mercado: str | None,
                       sesiones_cal: np.ndarray | None = None) -> dict[str, Any]:
    """Días hábiles del calendario del mercado sin vela, y velas fuera del calendario.

    ``sesiones_cal`` sustituye al calendario (pruebas). Sin calendario para el mercado: días L-V.
    """
    s = np.unique(_dias(sesiones))
    nombre = CALENDARIO_MERCADO.get(mercado or "") if sesiones_cal is None else "dado"
    vacio = {"calendario": nombre or "L-V", "calendario_desde": None, "faltan": np.array([], "datetime64[D]"),
             "fuera": np.array([], "datetime64[D]"), "esperadas": 0}
    if not len(s):
        return vacio
    if sesiones_cal is not None:
        cal = np.asarray(sesiones_cal).astype("datetime64[D]")
    elif nombre:
        try:
            cal = sesiones_calendario(nombre)
        except Exception as e:          # calendario que no resuelve: L-V, declarado
            log.info("calendario %s no disponible (%s): días L-V", nombre, e)
            nombre, cal = None, None
    else:
        cal = None
    if cal is None:
        cal = np.arange(s[0], s[-1] + np.timedelta64(1, "D"), dtype="datetime64[D]")
        cal = cal[np.is_busday(cal)]
    desde = max(s[0], cal[0]) if len(cal) else s[0]
    hasta = min(s[-1], cal[-1]) if len(cal) else s[-1]
    cal_r = cal[(cal >= desde) & (cal <= hasta)]
    s_r = s[(s >= desde) & (s <= hasta)]
    return {"calendario": nombre or "L-V", "calendario_desde": _iso(desde),
            "faltan": np.setdiff1d(cal_r, s_r), "fuera": np.setdiff1d(s_r, cal_r), "esperadas": int(len(cal_r))}


# --- Series: lectura y recorrido ----------------------------------------------------------------
_COLUMNAS_LECTURA = ["serie", "fecha_referencia", "vintage", "valor", "unidad", "fuente", "metodo_publicacion", "nota"]
_TEXTO_LECTURA = ["serie", "vintage", "unidad", "fuente", "metodo_publicacion", "nota"]


def leer_base(ruta: Path | None = None) -> pd.DataFrame:
    """La base con las columnas que usa el EDA (texto como categorías) y ``orden_vintage`` (``unico`` el último)."""
    r = Path(ruta) if ruta is not None else corpus_dir(TEMA) / "series" / almacen.FICHERO_SERIES
    df = pq.read_table(r, columns=_COLUMNAS_LECTURA, read_dictionary=_TEXTO_LECTURA).to_pandas()
    cats = df["vintage"].cat.categories.astype(str)
    fechas = pd.to_datetime(pd.Series(cats), format="ISO8601", errors="coerce")
    clave = pd.DataFrame({"c": cats, "f": fechas, "u": cats == "unico"}).sort_values(["u", "f", "c"], kind="mergesort")
    rango = np.empty(len(cats), dtype="int32")
    rango[clave.index.to_numpy()] = np.arange(len(cats), dtype="int32")
    codigos = df["vintage"].cat.codes.to_numpy()
    df["orden_vintage"] = np.where(codigos >= 0, rango[np.clip(codigos, 0, None)], -1).astype("int32")
    return df


def ultimo_vintage(base: pd.DataFrame) -> pd.DataFrame:
    """La fila del último vintage de cada (``serie``, ``fecha_referencia``), solo las que tienen valor."""
    cod = base["serie"].cat.codes.to_numpy() if isinstance(base["serie"].dtype, pd.CategoricalDtype) else \
        pd.factorize(base["serie"], sort=True)[0]
    ref = base["fecha_referencia"].to_numpy().astype("int64")
    orden = np.lexsort((base["orden_vintage"].to_numpy(), ref, cod))
    cod_o, ref_o = cod[orden], ref[orden]
    ultimo = np.r_[(cod_o[1:] != cod_o[:-1]) | (ref_o[1:] != ref_o[:-1]), True]
    sel = orden[ultimo]
    out = base.iloc[sel]
    return out[out["valor"].notna()].reset_index(drop=True)


def _pais_zona() -> dict[str, str]:
    r = resultados_dir(TEMA) / "tablas" / "inventario_series.csv"
    if not r.exists():
        return {}
    t = pd.read_csv(r, usecols=["id", "pais_zona"], dtype=str)
    return dict(zip(t["id"], t["pais_zona"].fillna("")))


def _cuenta_notas(base: pd.DataFrame) -> pd.DataFrame:
    """Filas con las notas de ``base.anotar_anomalias`` por serie (pico, fin de semana, racha)."""
    nota = base["nota"]
    cats = pd.Series(nota.cat.categories.astype(str))
    out = {}
    for k, texto in (("notas_base_pico", base_mod.NOTA_PICO), ("notas_base_fin_de_semana", base_mod.NOTA_FIN_DE_SEMANA),
                     ("notas_base_racha", base_mod.NOTA_RACHA)):
        cods = np.flatnonzero(cats.str.contains(texto, regex=False).to_numpy())
        m = np.isin(nota.cat.codes.to_numpy(), cods)
        out[k] = base.loc[m, "serie"].astype(str).value_counts()
    return pd.DataFrame(out).fillna(0).astype(int)


def _recortar(inc: pd.DataFrame, clave: str, orden: str) -> pd.DataFrame:
    """Como mucho ``MAX_POR_SERIE`` filas por (``clave``, ``tipo``), las de mayor |``orden``|."""
    if inc.empty:
        return inc
    a = inc.assign(_o=pd.to_numeric(inc[orden], errors="coerce").abs().fillna(0))
    a = a.sort_values([clave, "tipo", "_o"], ascending=[True, True, False], kind="mergesort")
    a = a.groupby([clave, "tipo"], sort=False).head(MAX_POR_SERIE).drop(columns="_o")
    return a.sort_values([clave, "tipo", "fecha"], kind="mergesort").reset_index(drop=True)


def controles_serie(sid: str, fechas: np.ndarray, x: np.ndarray, entrada: dict[str, Any], *,
                    calendario: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Controles 1, 2, 4, 5 y 6 de una serie (forma del último vintage, ordenada por fecha)."""
    frec = entrada.get("frecuencia")
    unidad = entrada.get("unidad")
    fuente = entrada.get("fuente")
    metodo = entrada.get("metodo")
    fila: dict[str, Any] = {"n_obs": int(len(x)), "desde": _iso(fechas[0]) if len(x) else None,
                            "hasta": _iso(fechas[-1]) if len(x) else None}
    inc: list[dict[str, Any]] = []

    def anota(tipo: str, fecha: Any, fin: Any, tamano: Any, medida: str, propuesta: str | None = None,
              nota: str | None = None) -> None:
        inc.append({"serie": sid, "fuente": fuente, "frecuencia": frec, "tipo": tipo, "fecha": _iso(fecha),
                    "fecha_fin": _iso(fin), "tamano": tamano, "medida": medida, "nota": nota,
                    "propuesta_paso4": propuesta or PROPUESTAS[tipo]})

    administrado = sid in base_mod.SIN_RACHAS
    prop_adm = SIN_ACCION if administrado else None

    # 1. huecos largos
    h = huecos(fechas, frec)
    fila["n_huecos_largos"] = int(len(h))
    if len(h):
        k = int(h["periodos"].idxmax())
        fila.update(max_hueco_periodos=int(h.at[k, "periodos"]), max_hueco_desde=_iso(h.at[k, "desde"]),
                    max_hueco_hasta=_iso(h.at[k, "hasta"]))
        nota_h = "tipo administrado: puede venir solo en las fechas de cambio" if administrado else None
        for r in h.itertuples(index=False):
            anota("hueco_largo", r.desde, r.hasta, int(r.periodos), "periodos", prop_adm, nota_h)
    else:
        fila.update(max_hueco_periodos=0, max_hueco_desde=None, max_hueco_hasta=None)

    # 2. saltos y rupturas de nivel
    binaria = str(unidad or "") == "0/1"
    lg = usa_log(x, unidad)
    fila["transformacion"] = "no aplica (0/1)" if binaria else ("log" if lg else "diferencia")
    prop_salto = prop_adm
    nota_adm = "tipo administrado: el escalón es normal" if administrado else None
    for tipo, det in (("salto", lambda: saltos_robustos(fechas, x, lg, frecuencia=frec)),
                      ("ruptura_nivel", lambda: rupturas_nivel(fechas, x, frec, lg))):
        d = det() if not binaria else pd.DataFrame(columns=["fecha", "desviaciones"])
        pref = "saltos" if tipo == "salto" else "rupturas"
        fila[f"n_{pref}"] = int(len(d))
        fila[f"max_{pref[:-1]}_desviaciones"] = float(d["desviaciones"].abs().max()) if len(d) else None
        for r in d.itertuples(index=False):
            anota(tipo, r.fecha, None, float(r.desviaciones), "desviaciones (MAD)", prop_salto,
                  nota_adm)

    # 4. escalas raras y no positivos
    esc = escala_rara(x, unidad)
    fila["escala_rara"] = esc
    if esc:
        anota(esc, fechas[0], fechas[-1], None, "")
    neg = no_positivos(fechas, x, unidad)
    fila["n_negativos_nivel"] = int(neg["obs"].sum()) if len(neg) else 0
    for r in neg.itertuples(index=False):
        anota("negativo_en_nivel", r.desde, r.hasta, int(r.obs), "observaciones")

    # 5. rachas planas (diarias)
    excluida = (administrado or entrada.get("publicador") in ("fed_h10", "ecb_fx") or binaria)
    fila["rachas_excluidas"] = bool(excluida and frec == "diaria")
    rp = rachas_planas(fechas, x) if frec == "diaria" and not excluida else rachas_planas([], [])
    fila["n_rachas_planas"] = int(len(rp))
    fila["max_racha_plana"] = int(rp["obs"].max()) if len(rp) else 0
    escalonada = sid in ESCALONADAS
    for r in rp.itertuples(index=False):
        anota("racha_plana", r.desde, r.hasta, int(r.obs), "observaciones", SIN_ACCION if escalonada else None,
              f"racha plana de {int(r.obs)} observaciones; escalonada por construcción (ESCALONADAS): no es un dato "
              "congelado" if escalonada else f"{base_mod.NOTA_RACHA} {int(r.obs)} observaciones")

    # 6. fechas raras (cierres de mercado)
    fila["calendario_festivos"] = calendario if metodo == "cierre_mercado" else None
    if metodo == "cierre_mercado":
        fr = fechas_raras(fechas, calendario)
        for tipo, col in (("fin_de_semana", "n_fin_de_semana"), ("festivo", "n_festivos")):
            sub = fr[fr["tipo"] == tipo]
            fila[col] = int(len(sub))
            for f_ in sub["fecha"]:
                anota(tipo, f_, None, None, "")
    else:
        fila["n_fin_de_semana"] = 0
        fila["n_festivos"] = 0
    return fila, inc


def calcular_series(ruta: Path | None = None, catalogo: dict[str, dict] | None = None,
                    registro: Callable[[str], None] | None = None) -> dict[str, pd.DataFrame]:
    """Las tablas de series: ``eda_series.csv`` y ``eda_series_incidencias.csv`` (sin recortar)."""
    out_log = registro or log.info
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    paises = _pais_zona()
    base = leer_base(ruta)
    out_log(f"base: {len(base)} filas, {base['serie'].nunique()} series")
    notas = _cuenta_notas(base)
    n_vint = base.groupby("serie", observed=True)["vintage"].nunique()
    # 3. cambios de unidad entre vintages (todos los vintages con valor)
    mv = (base["vintage"] != "unico").to_numpy() & base["valor"].notna().to_numpy()
    cu = cambios_unidad(base.loc[mv, ["serie", "fecha_referencia", "orden_vintage", "vintage", "valor"]])
    u = ultimo_vintage(base)
    meta = (base.groupby("serie", observed=True)
            .agg(unidad=("unidad", "last"), fuente=("fuente", "last"),
                 metodo=("metodo_publicacion", lambda s: s.mode().iloc[0] if len(s.dropna()) else None)))
    del base
    out_log(f"último vintage: {len(u)} filas con valor")
    filas, incs = [], []
    cod = u["serie"].cat.codes.to_numpy()
    orden = np.argsort(cod, kind="stable")
    limites = np.flatnonzero(np.r_[True, cod[orden][1:] != cod[orden][:-1], True])
    nombres = u["serie"].cat.categories.astype(str)
    fref = u["fecha_referencia"].to_numpy()
    val = u["valor"].to_numpy(dtype=float)
    vistas = set()
    for a, b in zip(limites[:-1], limites[1:]):
        idx = orden[a:b]
        sid = nombres[cod[idx[0]]]
        vistas.add(sid)
        idx = idx[np.argsort(fref[idx], kind="stable")]
        e = dict(cat.get(sid, {}))
        e.setdefault("frecuencia", None)
        if sid in meta.index:                       # lo que dicen las filas manda sobre el catálogo
            e.update({k: meta.at[sid, k] for k in ("unidad", "fuente", "metodo") if pd.notna(meta.at[sid, k])})
        calendario = CALENDARIO_PAIS.get(paises.get(sid, ""))
        fila, inc = controles_serie(sid, fref[idx], val[idx], e, calendario=calendario)
        fila.update(serie=sid, fuente=e["fuente"], frecuencia=e["frecuencia"], metodo=e["metodo"], unidad=e["unidad"])
        filas.append(fila)
        incs.extend(inc)
    for sid in sorted(set(meta.index.astype(str)) - vistas):       # series sin ningún valor
        e = cat.get(sid, {})
        filas.append({"serie": sid, "fuente": meta.at[sid, "fuente"], "frecuencia": e.get("frecuencia"),
                      "metodo": meta.at[sid, "metodo"], "unidad": meta.at[sid, "unidad"], "n_obs": 0})
    tabla = pd.DataFrame(filas).set_index("serie")
    # cambios de unidad -> incidencias y columnas
    declaradas = {s for s, e in cat.items() if e.get("unidad_por_vintage")}
    tabla["unidad_por_vintage"] = [s in declaradas for s in tabla.index]
    tabla["n_cambios_unidad"] = cu.groupby("serie").size().reindex(tabla.index, fill_value=0).astype(int)
    tabla["max_cambio_unidad_log10"] = cu.groupby("serie")["log10_factor"].apply(lambda s: s.abs().max()) \
        .reindex(tabla.index)
    fvint = pd.to_datetime(cu["vintage"], format="ISO8601", errors="coerce")
    for r, fv in zip(cu.itertuples(index=False), fvint):
        decl = r.serie in declaradas
        conf = (not decl) and es_potencia_confirmada(r.log10_factor, r.n)
        extra = ("; declarado en el catálogo (unidad_por_vintage)" if decl
                 else "; potencia de 10 confirmada: multiplicar los vintages anteriores por factor" if conf else "")
        incs.append({"serie": r.serie, "fuente": tabla.at[r.serie, "fuente"] if r.serie in tabla.index else None,
                     "frecuencia": tabla.at[r.serie, "frecuencia"] if r.serie in tabla.index else None,
                     "tipo": "cambio_unidad", "fecha": _iso(fv), "fecha_fin": None, "tamano": float(r.log10_factor),
                     "medida": "log10 del factor",
                     "factor": float(10.0 ** round(float(r.log10_factor))) if conf else None,
                     "nota": f"vintage {r.vintage}, {int(r.n)} fechas comunes" + extra,
                     "propuesta_paso4": SIN_ACCION if decl else REESCALAR if conf else PROPUESTAS["cambio_unidad"]})
    tabla["n_vintages"] = n_vint.reindex(tabla.index).fillna(0).astype(int)
    tabla = tabla.join(notas, how="left")
    for c in ("notas_base_pico", "notas_base_fin_de_semana", "notas_base_racha"):
        tabla[c] = tabla[c].fillna(0).astype(int)
    inc_df = pd.DataFrame(incs, columns=list(COLUMNAS_INC_SERIES))
    tipos = inc_df.groupby("serie")["tipo"].agg(lambda s: ";".join(sorted(set(s))))
    tabla["banderas"] = tipos.reindex(tabla.index)
    tabla = tabla.reset_index().reindex(columns=list(COLUMNAS_SERIES_EDA)).sort_values("serie", kind="mergesort")
    inc_df = inc_df.sort_values(["serie", "tipo", "fecha"], kind="mergesort").reset_index(drop=True)
    return {"eda_series.csv": tabla.reset_index(drop=True), "eda_series_incidencias.csv": inc_df}


# --- Precios: recorrido ------------------------------------------------------------------------
def _meta_precios() -> pd.DataFrame:
    r = resultados_dir(TEMA) / "tablas" / "inventario_precios.csv"
    if not r.exists():
        return pd.DataFrame(columns=["ticker", "proveedor", "clase", "mercado", "tipo_yahoo"]).set_index(
            ["proveedor", "ticker"])
    t = pd.read_csv(r, usecols=["ticker", "proveedor", "clase", "mercado", "tipo_yahoo"], dtype=str)
    return t.set_index(["proveedor", "ticker"])


def _clase(meta: dict[str, Any]) -> str:
    """La clase de ``inventario_precios.csv`` con el mismo criterio que la selección (``seleccion.clase_ticker``)."""
    from ingesta.mercados_series.seleccion import clase_ticker
    return clase_ticker(meta.get("clase"), meta.get("tipo_yahoo"))


def controles_ticker(p: pd.DataFrame, ticker: str, proveedor: str, meta: dict[str, Any] | None = None, *,
                     sesiones_cal: np.ndarray | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Controles de un fichero de precios (tabla del contrato o sus columnas de precio)."""
    meta = meta or {}
    p = _ordenar(p.assign(ticker=ticker))
    clase = _clase(meta)
    moda = p["mercado"].dropna().astype(str).mode() if "mercado" in p else pd.Series(dtype=str)
    mercado = moda.iloc[0] if len(moda) else meta.get("mercado")
    tipo_yahoo = meta.get("tipo_yahoo") if isinstance(meta.get("tipo_yahoo"), str) else ""
    n = int(p["close"].notna().sum())
    fila: dict[str, Any] = {"ticker": ticker, "proveedor": proveedor, "clase": clase, "mercado": mercado,
                            "desde": _iso(p["sesion"].iloc[0]) if len(p) else None,
                            "hasta": _iso(p["sesion"].iloc[-1]) if len(p) else None, "sesiones": n,
                            "caso_conocido": ticker in CASOS_SALTO or ticker in CASOS_SPLIT}
    inc: list[dict[str, Any]] = []

    def anota(tipo: str, fecha: Any, fin: Any = None, n_: int = 1, abs_dlog: Any = None, pct: Any = None,
              nota: str | None = None) -> None:
        inc.append({"ticker": ticker, "proveedor": proveedor, "clase": clase, "mercado": mercado, "tipo": tipo,
                    "fecha": _iso(fecha), "fecha_fin": _iso(fin), "n": int(n_), "abs_dlog": abs_dlog, "pct": pct,
                    "nota": nota, "propuesta_paso4": PROPUESTAS[tipo]})

    def agregada(tipo: str, fechas: Any) -> int:
        f = np.sort(_dias(fechas)) if len(fechas) else np.array([], "datetime64[D]")
        if len(f):
            anota(tipo, f[0], f[-1], len(f), pct=round(100 * len(f) / max(n, 1), 2))
        return int(len(f))

    # 4 (antes, para apartar las velas de relleno). Sesiones de menos y velas fuera de calendario
    sf = sesiones_faltantes(p.loc[p["close"].notna(), "sesion"], mercado, sesiones_cal)
    fuera = set(sf["fuera"].tolist())
    dias = _dias(p["sesion"])
    en_fuera = np.isin(dias, sf["fuera"])
    c = p["close"].to_numpy(dtype=float)
    repite = np.r_[False, c[1:] == c[:-1]]
    vol = p["volume"].to_numpy(dtype=float)
    relleno = en_fuera & repite & ~(np.nan_to_num(vol) > 0)
    fila["calendario"] = sf["calendario"]
    fila["calendario_desde"] = sf["calendario_desde"]
    fila["sesiones_faltantes"] = int(len(sf["faltan"]))
    fila["pct_sesiones_faltantes"] = round(100 * len(sf["faltan"]) / sf["esperadas"], 2) if sf["esperadas"] else None
    fila["sesiones_fuera_calendario"] = int(len(fuera))
    fila["fuera_calendario_relleno"] = int(relleno.sum())
    nota_cal = f"calendario {sf['calendario']} desde {sf['calendario_desde']}"
    for tipo, f in (("sesion_faltante", sf["faltan"]), ("sesion_fuera_calendario", dias[en_fuera & ~relleno]),
                    ("sesion_fuera_calendario_relleno", dias[relleno])):
        if len(f):
            base_pct = sf["esperadas"] if tipo == "sesion_faltante" else max(n, 1)
            anota(tipo, f.min(), f.max(), len(f), pct=round(100 * len(f) / max(base_pct, 1), 2), nota=nota_cal)

    # calidad.incidencias_precios (volumen cero, cierre repetido, dividendo alto; el salto, solo como columna)
    q = calidad.incidencias_precios(p, {ticker: tipo_yahoo})
    q = q[~(q["tipo"].isin(["volumen_cero", "cierre_repetido"]) & np.isin(_dias(q["sesion"]), sf["fuera"]))]
    for tipo in calidad.TIPOS:
        sub = q[q["tipo"] == tipo]
        clave = "salto_calidad" if tipo == "salto" else tipo
        if tipo == "salto":
            fila[clave] = int(len(sub))
            continue
        if tipo in ("volumen_cero", "cierre_repetido"):
            fila[clave] = agregada(clave, sub["sesion"])
            continue
        fila[clave] = int(len(sub))
        v = sub["valor"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            tam = np.abs(np.log(1.0 / (1.0 - np.minimum(v, 0.999999))))
        for s, t in zip(sub["sesion"], tam):
            anota(clave, s, abs_dlog=round(float(t), 3) if np.isfinite(t) else None)

    # 1. saltos sin split
    ss = saltos_sin_split(p)
    fila["saltos_sin_split"] = int(len(ss))
    fila["max_abs_dlog_sin_split"] = float(ss["abs_dlog"].max()) if len(ss) else None
    for r in ss.itertuples(index=False):
        anota("salto_sin_split", r.sesion, abs_dlog=float(r.abs_dlog) if np.isfinite(r.abs_dlog) else None,
              nota="cierre <= 0: Δlog no definido" if r.no_positivo else None)

    # 2. contrasplits y splits fraccionarios
    sp = splits_raros(p)
    fila["contrasplits"] = int((sp["tipo"] == "contrasplit").sum())
    fila["splits_fraccionarios"] = int((sp["tipo"] == "split_fraccionario").sum())
    for r in sp.itertuples(index=False):
        anota(r.tipo, r.sesion, abs_dlog=float(r.abs_dlog))

    # 3. apertura igual al cierre
    plano = apertura_igual_cierre(p)
    ses = pd.to_datetime(p["sesion"])
    fila["pct_apertura_igual_cierre"] = round(100 * float(plano.sum()) / max(n, 1), 2)
    d2000 = ses >= "2000-01-01"
    n2000 = int((d2000 & p["close"].notna()).sum())
    fila["pct_apertura_igual_cierre_desde_2000"] = (round(100 * float((plano & d2000).sum()) / n2000, 2)
                                                    if n2000 else None)
    fila["ultima_apertura_igual_cierre"] = _iso(ses[plano].max()) if plano.any() else None
    agregada("apertura_igual_cierre", ses[plano])

    # 5. serie sospechosa
    fila["pct_cierre_repetido"] = round(100 * fila["cierre_repetido"] / max(n, 1), 2)
    motivos = motivos_sospecha(fila)
    fila["serie_sospechosa"] = bool(motivos)
    fila["motivo_sospecha"] = "; ".join(motivos) or None
    if motivos:
        anota("serie_sospechosa", fila["desde"], fila["hasta"], n, nota=fila["motivo_sospecha"])
    fila["banderas"] = ";".join(sorted({i["tipo"] for i in inc})) or None
    return fila, inc


def motivos_sospecha(fila: dict[str, Any]) -> list[str]:
    """Motivos de ``serie_sospechosa`` de una fila de ``eda_precios`` (lista vacía si no lo es):

    - más de ``SOSPECHA_SALTOS`` saltos sin split;
    - más de ``SOSPECHA_PCT_REPETIDO`` % de cierres repetidos (sin las velas de relleno en días cerrados);
    - más de ``SOSPECHA_PCT_APERTURA`` % de aperturas iguales al cierre desde 2000, salvo en fondos
      (``clase`` ``fondo`` o mercado ``NAV_US``: el valor liquidativo no tiene apertura y eso es normal).
    """
    out = []
    if (fila.get("saltos_sin_split") or 0) > SOSPECHA_SALTOS:
        out.append(f"{fila['saltos_sin_split']} saltos sin split (> {SOSPECHA_SALTOS})")
    if (fila.get("pct_cierre_repetido") or 0) > SOSPECHA_PCT_REPETIDO:
        out.append(f"{fila['pct_cierre_repetido']:.1f} % de cierres repetidos (> {SOSPECHA_PCT_REPETIDO:.0f} %)")
    pa = fila.get("pct_apertura_igual_cierre_desde_2000")
    fondo = fila.get("clase") == "fondo" or fila.get("mercado") == "NAV_US"
    if not fondo and pa is not None and not pd.isna(pa) and pa > SOSPECHA_PCT_APERTURA:
        out.append(f"{pa:.1f} % de aperturas iguales al cierre desde 2000 (> {SOSPECHA_PCT_APERTURA:.0f} %)")
    return out


_COLUMNAS_PRECIO = ["sesion", "mercado", "open", "high", "low", "close", "volume", "dividendo", "split"]


def calcular_precios(tickers: Iterable[str] | None = None,
                     registro: Callable[[str], None] | None = None) -> dict[str, pd.DataFrame]:
    """Las tablas de precios: ``eda_precios.csv`` y ``eda_precios_incidencias.csv`` (sin recortar)."""
    out_log = registro or log.info
    raiz = corpus_dir(TEMA) / "precios"
    meta = _meta_precios()
    solo = set(tickers) if tickers else None
    filas, incs = [], []
    for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        n = 0
        for f in sorted(carpeta.glob("*.parquet")):
            tk = almacen.ticker_de_fichero(f.stem)
            if solo is not None and tk not in solo:
                continue
            p = pq.read_table(f, columns=_COLUMNAS_PRECIO, read_dictionary=["mercado"]).to_pandas()
            m = meta.loc[(carpeta.name, tk)].to_dict() if (carpeta.name, tk) in meta.index else {}
            fila, inc = controles_ticker(p, tk, carpeta.name, m)
            filas.append(fila)
            incs.extend(inc)
            n += 1
        out_log(f"precios/{carpeta.name}: {n} ficheros")
    tabla = pd.DataFrame(filas).reindex(columns=list(COLUMNAS_PRECIOS_EDA))
    tabla = tabla.sort_values(["proveedor", "ticker"], kind="mergesort").reset_index(drop=True)
    inc_df = pd.DataFrame(incs, columns=list(COLUMNAS_INC_PRECIOS))
    inc_df = inc_df.sort_values(["ticker", "tipo", "fecha"], kind="mergesort").reset_index(drop=True)
    return {"eda_precios.csv": tabla, "eda_precios_incidencias.csv": inc_df}


# --- Resumen y orden ----------------------------------------------------------------------------
def resumen(inc_series: pd.DataFrame | None, inc_precios: pd.DataFrame | None) -> pd.DataFrame:
    """Recuentos por ámbito, tipo y grupo (fuente en series, clase en precios) y el total por tipo
    (``grupo = '(todas)'``). ``n_eventos``: sesiones en los tipos agregados de precios; filas en el resto."""
    partes = []
    for ambito, inc, grupo, clave in (("series", inc_series, "fuente", "serie"),
                                      ("precios", inc_precios, "clase", "ticker")):
        if inc is None or inc.empty:
            continue
        d = inc.assign(_n=inc["n"] if "n" in inc else 1, _g=inc[grupo].fillna("sin_" + grupo).astype(str))
        for por_grupo in (True, False):
            claves = ["tipo", "_g"] if por_grupo else ["tipo"]
            g = d.groupby(claves).agg(n_filas=("tipo", "size"), n_eventos=("_n", "sum"),
                                      n_afectadas=(clave, "nunique"),
                                      propuesta_paso4=("propuesta_paso4", lambda s: "; ".join(sorted(set(s)))))
            g = g.reset_index()
            g["grupo"] = g["_g"] if por_grupo else "(todas)"
            g["ambito"] = ambito
            partes.append(g)
    if not partes:
        return pd.DataFrame(columns=list(COLUMNAS_RESUMEN))
    out = pd.concat(partes, ignore_index=True)
    out["descripcion"] = out["tipo"].map(NOTAS)
    out = out.reindex(columns=list(COLUMNAS_RESUMEN))
    out["n_eventos"] = out["n_eventos"].astype("int64")
    out["_t"] = out["grupo"] != "(todas)"
    return (out.sort_values(["ambito", "tipo", "_t", "grupo"], ascending=[False, True, True, True], kind="mergesort")
            .drop(columns="_t").reset_index(drop=True))


def _memoria_pico_mb() -> float | None:
    try:
        import psutil

        info = psutil.Process().memory_info()
        return round(getattr(info, "peak_wset", info.rss) / 2**20, 0)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> dict[str, Path]:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--destino", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    p.add_argument("--solo", choices=("series", "precios"), default=None)
    p.add_argument("--tickers", default=None, help="solo estos tickers, separados por comas (prueba)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    destino = a.destino or resultados_dir(TEMA) / "tablas"
    destino.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    salidas: dict[str, pd.DataFrame] = {}
    if a.solo in (None, "series"):
        salidas.update(calcular_series())
        log.info(f"series: {math.ceil(time.time() - t0)} s")
    if a.solo in (None, "precios"):
        salidas.update(calcular_precios(a.tickers.split(",") if a.tickers else None))
    salidas["eda_resumen.csv"] = resumen(salidas.get("eda_series_incidencias.csv"),
                                         salidas.get("eda_precios_incidencias.csv"))
    if "eda_series_incidencias.csv" in salidas:
        salidas["eda_series_incidencias.csv"] = _recortar(salidas["eda_series_incidencias.csv"], "serie", "tamano")
    if "eda_precios_incidencias.csv" in salidas:
        salidas["eda_precios_incidencias.csv"] = _recortar(salidas["eda_precios_incidencias.csv"], "ticker",
                                                           "abs_dlog")
    rutas = {}
    for nombre, df in salidas.items():
        malas = PROHIBIDAS & set(df.columns)
        if malas:
            raise RuntimeError(f"{nombre} lleva columnas de valores: {sorted(malas)}")
        rutas[nombre] = destino / nombre
        df.to_csv(rutas[nombre], index=False, encoding="utf-8", lineterminator="\n")
        print(f"{nombre}: {len(df)} filas")
    print(f"tiempo total: {math.ceil(time.time() - t0)} s; memoria pico: {_memoria_pico_mb()} MB")
    return rutas


if __name__ == "__main__":
    main()
