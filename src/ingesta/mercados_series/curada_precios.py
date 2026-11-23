"""Paso 4 del Tema 1 · precios curados: los tickers que se quedan, hasta el corte y con las propuestas del EDA.

Lee ``<corpus>/mercados_series/precios/<proveedor>/`` (**nunca lo toca**) y escribe
``<corpus>/mercados_series/precios_curados/<proveedor>/<fichero>.parquet``, con los mismos nombres de fichero que
``almacen`` (``almacen.nombre_fichero_ticker``) y el mismo esquema (``contrato.COLUMNAS_PRECIOS``, validado con
``contrato.validar_precios``). Qué hace con cada fichero:

1. **Solo los que se quedan**: los tickers con ``decision: queda`` en la sección ``precios`` de
   ``config/lista_curada.yaml`` (Yahoo y Coinbase; la lista no dice el proveedor: sale de la carpeta del fichero).
2. **Corte G2** (``CORTE_G2`` = 2026-11-13, último viernes con cierre completo antes del 3b-1;
   ``docs/fase2/mercados_series/PLAN_DESCARGA.md``): fuera las sesiones con ``fecha_publicacion`` posterior. En
   Coinbase la vela de un día se publica al siguiente (00:30 UTC), así que su última sesión curada es la del 12.
3. **Acciones automáticas del EDA** (``incidencias_eda`` de ``config/preprocesado.yaml``, de ``eda.PROPUESTAS``):
   - ``sesion_fuera_calendario_relleno`` («nulo + aviso»): las velas en un día que el calendario del mercado da
     cerrado, que repiten el cierre anterior y no tienen volumen (``eda.velas_fuera_calendario``, la misma regla
     que el EDA) se **quitan**: no son sesiones reales. Si una lleva dividendo o split, se queda (perderlo
     cambiaría el ajuste) y va como aviso (``relleno_con_evento``).
   - ``apertura_igual_cierre`` («nulo + aviso»): en las sesiones con ``open == close`` y ``high == low``
     (``eda.apertura_igual_cierre``, la regla exacta del EDA, con o sin volumen) ``open``, ``high`` y ``low``
     pasan a nulo y el ``close`` se queda. La ejecución es a la apertura de t+1 (``docs/tfm/arquitectura.md``):
     una apertura de relleno no es un precio ejecutable. También se anulan las que tienen volumen: un OHLC plano
     no es una apertura ejecutable (en Londres antes de 2011 Yahoo rellenaba así sesiones con volumen). Los
     avisos las separan: ``apertura_igual_cierre`` (sin volumen) y ``apertura_igual_cierre_con_volumen``
     (``APERTURA_CON_VOLUMEN``), con su recuento por ticker; las dos con acción ``nulo``.
     **Impacto en ``cartera/costes.py``:** ``_ohlc_sin_splits`` exige ``high``, ``low`` y ``close`` > 0, así que
     si la cartera pasa a leer los precios curados los pares (t-1, t) con una de estas sesiones se descartan en
     los spreads de Abdi-Ranaldo y Corwin-Schultz (antes entraban con un rango nulo, que sesgaba el spread a 0).
   - **Instrumentos sin apertura** (``sin_apertura``, ``UMBRAL_SIN_APERTURA``): si tras el curado más del 99 %
     de las sesiones quedan sin ``open`` (fondos con valor liquidativo como VBMFX, índices como ^SKEW), un aviso
     por ticker dice que la ejecución en t+1 tendrá que usar el cierre: no hay apertura que usar.
   - ``negativo_en_nivel`` («nulo + aviso») es un tipo de series: el EDA no lo emite en precios (un cierre <= 0,
     como el WTI de abril de 2020, va como ``salto_sin_split`` con nota y el contrato admite precios negativos).
     No se aplica; la verificación ``negativo_en_nivel`` lo deja dicho.
   Lo demás («marcar», «revisar a mano») no cambia datos: va como aviso (``solo aviso``).
4. **Saneado del 2026-11-21** (``saneado_precios``, reglas y TimeGate en su docstring):
   - P21: el mercado de ``saneado_precios.MERCADO_CORREGIDO`` (^W5000 → XNYS) se pone ANTES de todo lo demás, con
     el ``disponible_utc`` más tardío de los dos (nunca adelanta); aviso ``mercado_corregido``.
   - P11: los saltos de más del 50 % sin split se clasifican (pico aislado → vela plana del cierre anterior; cambio
     de nivel con razón de split limpio → factor en ``split``; real → se mantiene), con la publicación de la sesión
     que lo confirma. Registro sin valores en ``precios_curados_saltos.csv``; avisos ``salto_pico_corregido``
     (``corregido``), ``salto_split_registrado`` (``split registrado``) y ``salto_real`` (``solo aviso``).
   - P28: los huecos de calendario de hasta 5 sesiones se rellenan con la última vela (``relleno_ffill``, acción
     ``relleno``); un hueco más largo es ``hueco_largo`` y el ticker debe estar «fuera» en la lista.
   - P02: ningún «queda» con aviso de ticker reutilizado (verificación ``reutilizados_fuera``).

Salidas en ``results/ingesta/mercados_series/tablas/`` (solo metadatos, ninguna columna de precios):

- ``precios_curados_avisos.csv`` (``COLUMNAS_AVISOS``): una fila por ticker y tipo, con ``n``, primera y última
  fecha, la acción aplicada (``quitada``, ``nulo`` o ``solo aviso``) y la propuesta del EDA; los tipos del EDA salen
  de ``eda.controles_ticker`` sobre lo que queda tras el corte (datos del 3b-1, no la tabla vieja del paso 3), y el
  ``aviso`` de la lista curada (serie sospechosa, ticker reutilizado, historia recortada, alias UCITS con poca
  correlación, limitación F3) va como tipo ``aviso_lista``. ``no_llega_corte`` (3b-2, ``aviso_no_llega_corte``):
  el último dato es anterior a la última sesión de su calendario que se publica hasta el corte; ``n`` = sesiones
  que faltan y la nota lleva el motivo de ``estado_3b.MOTIVOS_REFRESCO`` si lo hay (rechazos del almacén, tickers
  reutilizados, adquiridos).
- ``precios_curados_resumen.csv`` (``COLUMNAS_RESUMEN``): por ticker, sesiones antes y después, fuera por el corte,
  velas quitadas, aperturas anuladas y hasta dónde llega.
- ``precios_curados_verificaciones.csv`` (``COLUMNAS_VERIFICACIONES``): ``ok``, ``fallo`` o ``no aplica``.
- ``precios_curados_saltos.csv`` (``saneado_precios.COLUMNAS_SALTOS``): una fila por salto sin split clasificado
  (tipo, razón redondeada a 1 decimal, sesiones tocadas y de confirmación; sin precios).

**Verificaciones** (``VERIFICACIONES``), sobre cada fichero antes de publicar nada: fechas de publicación y
disponibilidad iguales a las originales (salvo las retrasadas por P11 y P21, que solo pueden ir más tarde); solo
faltan las velas posteriores al corte y las de relleno fuera de calendario, y solo sobran las de relleno de huecos
(P28, dentro del calendario y marcadas: no chocan con las quitadas, que eran velas fuera de calendario); ninguna
sesión posterior al corte; ``close`` y el resto de columnas iguales salvo ``open``/``high``/``low``, que solo pasan
a nulo en las sesiones de relleno, y lo registrado por P11 (cada cambio con su regla); esquema válido (y el parquet escrito se relee igual); recuentos frente a la
lista curada (1.491 «queda» en el 3b-1 y 1.616 en el 3b-2, también frente a su cabecera); y ``precios/`` sin cambios (tamaño y fecha
de cada fichero leído). Si alguna falla no se publica nada: la carpeta ``precios_curados`` y las tablas de avisos y
resumen se quedan como estaban; solo se escribe ``precios_curados_verificaciones.csv`` para ver qué falló.

**Escritura atómica e idempotente**: todo se escribe en una carpeta hermana temporal
(``precios_curados.nuevo_<id>``) y, con todo verificado, se cambia por la anterior (renombrado; la anterior pasa a
``precios_curados.previa_<id>`` y se borra). Las tablas, con temporal y ``os.replace``. Repetir la orden con la
misma entrada da los mismos ficheros. Unos 1.500 ficheros en unos 6 minutos.

CLI: ``python -m ingesta.mercados_series curar-precios [--sin-escribir] [--tickers A,B]`` (``--tickers``: prueba
sobre unos pocos, sin escribir). Para leer: ``leer_precios_curados`` y ``ruta_precios_curados``.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ingesta.comun.rutas import corpus_dir, resultados_dir
from ingesta.mercados_series import almacen, eda, visibilidad
from ingesta.mercados_series import saneado_precios as sp
from ingesta.mercados_series.contrato import COLUMNAS_PRECIOS, ErrorContrato, validar_precios

TEMA = "mercados_series"
# Corte G2 (PLAN_DESCARGA.md, paso 3b): nada con fecha_publicacion posterior entra en los precios curados.
CORTE_G2 = __import__("ingesta.mercados_series.corte", fromlist=["corte_vigente"]).corte_vigente()  # P07
CARPETA_CURADOS = almacen.CARPETA_PRECIOS_CURADOS     # "precios_curados", la de almacen.ruta_precios(curada=True)
RUTA_LISTA = Path(__file__).resolve().parent / "config" / "lista_curada.yaml"

QUITADA, NULO, SOLO_AVISO = "quitada", "nulo", "solo aviso"
RELLENADA, CORREGIDA, SPLIT_REGISTRADO = "relleno", "corregido", "split registrado"     # saneado P28 y P11
RELLENO_FFILL, HUECO_LARGO, MERCADO_CORREGIDO = "relleno_ffill", "hueco_largo", "mercado_corregido"
AVISO_SALTO = {sp.PICO: ("salto_pico_corregido", CORREGIDA), sp.SPLIT: ("salto_split_registrado", SPLIT_REGISTRADO),
               sp.REAL: ("salto_real", SOLO_AVISO)}
RELLENO = "sesion_fuera_calendario_relleno"
APERTURA = "apertura_igual_cierre"
APLICADOS = {RELLENO: QUITADA, APERTURA: NULO}       # tipos del EDA que cambian datos y su acción
APERTURA_CON_VOLUMEN = "apertura_igual_cierre_con_volumen"   # aviso propio: OHLC plano con volumen > 0 (también nulo)
SIN_APERTURA = "sin_apertura"
NO_LLEGA_CORTE = "no_llega_corte"   # el último dato es anterior a la última sesión del calendario antes del corte
UMBRAL_SIN_APERTURA = 99.0   # % de sesiones curadas sin open por encima del cual el instrumento no tiene apertura
COLUMNAS_OHL = ("open", "high", "low")
# Columnas que no pueden cambiar en una sesión que se queda (además del close y de las fechas).
INTACTAS = ("ticker", "mercado", "volume", "dividendo", "split", "divisa", "fuente", "descargado")

COLUMNAS_AVISOS = ("ticker", "proveedor", "tipo", "n", "primera", "ultima", "accion", "propuesta_eda", "nota")
COLUMNAS_RESUMEN = ("ticker", "proveedor", "sesiones_antes", "fuera_corte", "velas_quitadas", "aperturas_anuladas",
                    "sesiones_despues", "desde", "hasta", "hasta_original", "rellenos_ffill", "picos_corregidos",
                    "splits_registrados")
COLUMNAS_VERIFICACIONES = ("verificacion", "estado", "n_fallos", "detalle")
VERIFICACIONES = {
    "fechas_intactas": "fecha_publicacion y disponible_utc de cada sesión curada iguales a las originales",
    "quitadas_solo_relleno": "solo faltan las sesiones posteriores al corte y las velas de relleno fuera de "
                             "calendario (repiten el cierre, sin volumen ni evento)",
    "sin_posteriores_corte": "ninguna sesión curada con fecha_publicacion posterior al corte G2",
    "close_intacto": "el close de las sesiones que quedan no cambia",
    "resto_intacto": "mercado, volumen, dividendo, split, divisa, fuente y descargado no cambian",
    "anulaciones_solo_en_relleno": "open/high/low solo cambian a nulo y solo en sesiones con open == close y "
                                   "high == low",
    "esquema_valido": "cada fichero pasa contrato.validar_precios y el parquet escrito se relee igual",
    "recuento_tickers": "tickers escritos = tickers «queda» de la lista curada",
    "cabecera_lista": "las entradas «queda» de la lista curada = las de su cabecera",
    "queda_sin_fichero": "ningún ticker «queda» sin fichero en precios/",
    "ficheros_sin_decision": "ningún fichero de precios/ sin entrada en la lista curada",
    "ticker_en_dos_proveedores": "ningún ticker con fichero en dos proveedores",
    "origen_intacto": "precios/ sin cambios: mismo tamaño y fecha de cada fichero leído",
    "negativo_en_nivel": "tipo de series: el EDA no lo emite en precios",
    # Saneado del 2026-11-21 (saneado_precios)
    "rellenos_ffill_validos": "las sesiones añadidas (P28) rellenan huecos de calendario de hasta 5 sesiones con la "
                              "última vela: cierre anterior, open/high/low nulos, volumen y dividendo 0, split 1 y "
                              "publicación de su sesión (nunca antes que la vela anterior)",
    "saltos_corregidos_validos": "cada cambio de P11 está registrado y sigue su regla: pico = cierre de la vela buena "
                                 "anterior y open/high/low nulos; split = razón limpia; publicación solo más tarde",
    "mercado_corregido_sin_adelanto": "el mercado corregido (P21) no adelanta ningún disponible_utc",
    "reutilizados_fuera": "ningún ticker «queda» con aviso de ticker reutilizado (P02)",
    "sin_huecos_largos": "ningún ticker «queda» con un hueco de calendario de más de 5 sesiones (P28; salvo las excepciones del usuario, saneado_precios.EXCEPCIONES_HUECO)",
}
_REINTENTOS = 5
_CABECERA = re.compile(r"^#\s*Precios:\s*([\d.]+)\s*\((.*)\)", re.MULTILINE)


# --- Rutas y lectura --------------------------------------------------------------------------------
def ruta_curados() -> Path:
    """``<corpus>/mercados_series/precios_curados`` (``almacen.CARPETA_PRECIOS_CURADOS``)."""
    return corpus_dir(TEMA) / CARPETA_CURADOS


def ruta_precios_curados(proveedor: str, ticker: str, raiz: Path | None = None) -> Path:
    """``precios_curados/<proveedor>/<almacen.nombre_fichero_ticker(ticker)>.parquet``: la misma ruta que
    ``almacen.ruta_precios(proveedor, ticker, curada=True)``, que leen las tools (``raiz``: otra carpeta)."""
    if raiz is None:
        return almacen.ruta_precios(proveedor, ticker, curada=True)
    return Path(raiz) / proveedor / f"{almacen.nombre_fichero_ticker(ticker)}.parquet"


def leer_precios_curados(ticker: str, proveedor: str = "yahoo", raiz: Path | None = None) -> pd.DataFrame:
    """Precios curados validados de ``ticker`` (``almacen.leer_precios(..., curada=True)``; tabla vacía del
    contrato si no hay fichero)."""
    if raiz is None:
        return almacen.leer_precios(ticker, proveedor, curada=True)
    return almacen.leer_precios(ticker, proveedor, ruta=Path(raiz) / proveedor)


def cargar_lista_precios(ruta: Path | None = None) -> dict[str, dict[str, Any]]:
    """Sección ``precios`` de ``config/lista_curada.yaml``: ``{ticker: entrada}``."""
    return visibilidad.leer_yaml(Path(ruta or RUTA_LISTA))["precios"]


def queda_cabecera(ruta: Path | None = None) -> int | None:
    """Los «queda» de la cabecera de la lista (``# Precios: 1499 (fuera 8, queda 1491).``); None si no está."""
    m = _CABECERA.search(Path(ruta or RUTA_LISTA).read_text(encoding="utf-8"))
    q = re.search(r"queda\s+([\d.]+)", m.group(2)) if m else None
    return int(q.group(1).replace(".", "")) if q else None


def ficheros_origen(origen: Path) -> tuple[dict[str, tuple[str, Path]], list[str]]:
    """``{ticker: (proveedor, fichero)}`` de ``origen/<proveedor>/*.parquet`` y los tickers en dos proveedores."""
    out: dict[str, tuple[str, Path]] = {}
    dobles = []
    for carpeta in sorted(p for p in Path(origen).iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for f in sorted(carpeta.glob("*.parquet")):
            tk = almacen.ticker_de_fichero(f.stem)
            if tk in out:
                dobles.append(tk)
                continue
            out[tk] = (carpeta.name, f)
    return out, sorted(set(dobles))


# --- Curado de un ticker ----------------------------------------------------------------------------
@dataclass
class Curado:
    """Resultado de ``curar_ticker``: la tabla curada y, sobre las sesiones hasta el corte (``hasta_corte``),
    las máscaras de lo aplicado."""

    curado: pd.DataFrame
    hasta_corte: pd.DataFrame
    quitada: np.ndarray          # velas de relleno quitadas
    anulada: np.ndarray          # sesiones con open/high/low a nulo
    relleno_con_evento: np.ndarray
    fuera_corte: int
    saneado: sp.Saneado = field(default_factory=sp.Saneado)    # P11 y P28
    referencia: pd.DataFrame | None = None                     # el original con el mercado de P21 (o el original)


def _sin_volumen(p: pd.DataFrame) -> np.ndarray:
    return ~(np.nan_to_num(p["volume"].to_numpy(dtype=float)) > 0)


def _con_evento(p: pd.DataFrame) -> np.ndarray:
    return (p["split"].fillna(1.0).to_numpy(dtype=float) != 1.0) | (p["dividendo"].fillna(0.0).to_numpy(dtype=float) > 0)


def referencia_ticker(original: pd.DataFrame) -> pd.DataFrame:
    """El original con el mercado corregido de ``saneado_precios.MERCADO_CORREGIDO`` (P21), o el original."""
    tk = str(original["ticker"].iloc[0]) if len(original) else ""
    if tk in sp.MERCADO_CORREGIDO:
        return sp.corregir_mercado(original, sp.MERCADO_CORREGIDO[tk][0])
    return original


def curar_ticker(original: pd.DataFrame, corte: pd.Timestamp = CORTE_G2,
                 sesiones_cal: np.ndarray | None = None, *, sanear: bool = True,
                 clase: str | None = None) -> Curado:
    """Corte G2, acciones automáticas del EDA y saneado (P21, P11 y P28) sobre un fichero validado (ordenado por
    sesión). ``sanear=False``: sin P11 ni P28 (el mercado de P21 se corrige siempre). ``clase``: la de la lista
    curada (P11 solo corrige acciones, ETF, ETP y fondos).

    ``sesiones_cal`` sustituye al calendario del mercado (pruebas; ver ``eda.sesiones_faltantes``).
    """
    referencia = referencia_ticker(original)
    hasta = referencia[referencia["fecha_publicacion"] <= corte].reset_index(drop=True)
    mercado = hasta["mercado"].iloc[0] if len(hasta) else None
    _, _, relleno = eda.velas_fuera_calendario(hasta, mercado, sesiones_cal)
    evento = _con_evento(hasta) if len(hasta) else np.zeros(0, bool)
    quitada = relleno & ~evento
    anulada = eda.apertura_igual_cierre(hasta).to_numpy() & ~quitada
    cur = hasta.loc[~quitada].copy()
    nulos = anulada[~quitada]
    for col in COLUMNAS_OHL:
        cur.loc[nulos, col] = np.nan
    saneado = sp.Saneado()
    if sanear and len(cur):
        cur, saneado = sp.sanear(cur.reset_index(drop=True), mercado, sesiones_cal, clase)
    return Curado(curado=validar_precios(cur), hasta_corte=hasta, quitada=quitada, anulada=anulada,
                  relleno_con_evento=relleno & evento, fuera_corte=int(len(original) - len(hasta)),
                  saneado=saneado, referencia=referencia)


def _distintos(a: pd.Series, b: pd.Series) -> np.ndarray:
    """Distintos elemento a elemento (dos nulos son iguales)."""
    return ~((a == b) | (a.isna() & b.isna())).to_numpy()


def _ratios_limpios() -> np.ndarray:
    r = np.array(sp.RATIOS_LIMPIOS)
    return np.r_[r, 1.0 / r]


def verificar_ticker(original: pd.DataFrame, curado: pd.DataFrame, corte: pd.Timestamp = CORTE_G2,
                     sesiones_cal: np.ndarray | None = None, saneado: sp.Saneado | None = None) -> dict[str, int]:
    """Fallos de cada verificación por sesión de un ticker, comparando la tabla curada con la ORIGINAL (no con
    las máscaras de ``curar_ticker``: así un error al montar la tabla se ve). ``original``: la referencia de P21
    (``referencia_ticker``). ``saneado``: lo que P11 y P28 dicen haber cambiado; cada cambio se comprueba con su
    regla y un cambio no registrado falla en la verificación de siempre."""
    s = saneado or sp.Saneado()
    f = dict.fromkeys(("fechas_intactas", "quitadas_solo_relleno", "sin_posteriores_corte", "close_intacto",
                       "resto_intacto", "anulaciones_solo_en_relleno", "rellenos_ffill_validos",
                       "saltos_corregidos_validos"), 0)
    o = original.set_index("sesion")
    c = curado.set_index("sesion")
    nuevas = c.index.difference(o.index)
    rellenas = nuevas[nuevas.isin(list(s.rellenas))]
    f["fechas_intactas"] += len(nuevas) - len(rellenas)
    if len(rellenas):
        f["rellenos_ffill_validos"] += _fallos_rellenos(c, rellenas)
    comunes = c.index.intersection(o.index)
    oc, cc = o.loc[comunes], c.loc[comunes]
    retrasada = comunes.isin(list(s.retrasadas))
    corregida = comunes.isin(list(s.corregidas))
    con_split = comunes.isin(list(s.splits))
    fechas_dist = (_distintos(oc["fecha_publicacion"], cc["fecha_publicacion"])
                   | _distintos(oc["disponible_utc"], cc["disponible_utc"]))
    f["fechas_intactas"] += int((fechas_dist & ~retrasada).sum())
    antes = ((cc["disponible_utc"] < oc["disponible_utc"]) | (cc["fecha_publicacion"] < oc["fecha_publicacion"])
             ).to_numpy()
    f["saltos_corregidos_validos"] += int((retrasada & antes).sum())
    f["sin_posteriores_corte"] = int((c["fecha_publicacion"] > corte).sum())
    f["close_intacto"] = int((_distintos(oc["close"], cc["close"]) & ~corregida).sum())
    intactas = [k for k in INTACTAS if k != "split"]
    f["resto_intacto"] = int((np.logical_or.reduce([_distintos(oc[k], cc[k]) for k in intactas])
                              | (_distintos(oc["split"], cc["split"]) & ~con_split)).sum())
    if con_split.any():
        valor = cc.loc[con_split, "split"].to_numpy(float)
        limpio = np.isclose(valor[:, None], _ratios_limpios()[None, :], rtol=1e-12).any(axis=1)
        registrado = np.array([s.splits[pd.Timestamp(x)] for x in comunes[con_split]], dtype=float)
        sin_split_antes = (oc.loc[con_split, "split"].to_numpy(float) == 1.0)
        f["saltos_corregidos_validos"] += int((~limpio | (valor != registrado) | ~sin_split_antes).sum())
    if corregida.any():
        # Cierre de la vela buena anterior (la última no corregida antes) y open/high/low nulos.
        cs = c["close"]
        buena = pd.Series(np.where(c.index.isin(list(s.corregidas)), np.nan, cs.to_numpy(float)),
                          index=c.index).ffill().shift(1)
        sel = comunes[corregida]
        mal = (cs.loc[sel].to_numpy(float) != buena.loc[sel].to_numpy(float)) | ~np.logical_and.reduce(
            [c.loc[sel, k].isna().to_numpy() for k in COLUMNAS_OHL])
        f["saltos_corregidos_validos"] += int(mal.sum())
    plano = ((oc["open"] == oc["close"]) & (oc["high"] == oc["low"])).to_numpy()
    cambia = np.logical_or.reduce([_distintos(oc[k], cc[k]) for k in COLUMNAS_OHL])
    a_nulo = np.logical_and.reduce([cc[k].isna().to_numpy() for k in COLUMNAS_OHL])
    f["anulaciones_solo_en_relleno"] = int((cambia & ~(plano & a_nulo) & ~corregida).sum())
    # Las que faltan hasta el corte deben ser relleno: fuera de calendario, mismo cierre que la anterior, sin
    # volumen ni evento.
    hasta = original[original["fecha_publicacion"] <= corte].reset_index(drop=True)
    falta = ~hasta["sesion"].isin(c.index).to_numpy()
    if falta.any():
        mercado = hasta["mercado"].iloc[0]
        # el calendario, solo con las sesiones con cierre (como eda.velas_fuera_calendario)
        sf = eda.sesiones_faltantes(hasta.loc[hasta["close"].notna(), "sesion"], mercado, sesiones_cal)
        fuera = np.isin(hasta["sesion"].to_numpy().astype("datetime64[D]"), sf["fuera"])
        cl = hasta["close"].to_numpy(dtype=float)
        repite = np.r_[False, cl[1:] == cl[:-1]]
        ok = fuera & repite & _sin_volumen(hasta) & ~_con_evento(hasta)
        f["quitadas_solo_relleno"] = int((falta & ~ok).sum())
    return f


def _fallos_rellenos(c: pd.DataFrame, rellenas: pd.Index) -> int:
    """Fallos de las velas de relleno de P28 en la tabla curada ``c`` (indexada por sesión)."""
    pos = c.index.get_indexer(rellenas)
    if (pos <= 0).any():
        return int(len(pos))
    fallos = 0
    cl = c["close"].to_numpy(float)
    malas = ((cl[pos] != cl[pos - 1]) | ~np.logical_and.reduce([c[k].isna().to_numpy()[pos] for k in COLUMNAS_OHL])
             | (c["volume"].to_numpy(float)[pos] != 0) | (c["dividendo"].to_numpy(float)[pos] != 0)
             | (c["split"].to_numpy(float)[pos] != 1.0))
    fallos += int(malas.sum())
    regla = visibilidad.disponible_cierre_serie(pd.Series(rellenas), str(c["mercado"].iloc[0])).to_numpy()
    disp = c["disponible_utc"].to_numpy()
    fallos += int(((disp[pos] < regla) | (disp[pos] < disp[pos - 1])).sum())
    # Rachas de sesiones rellenas seguidas: como mucho sp.MAX_HUECO.
    racha = np.split(pos, np.flatnonzero(np.diff(pos) != 1) + 1)
    fallos += sum(len(r) for r in racha if len(r) > sp.MAX_HUECO)
    return fallos


# --- Avisos -----------------------------------------------------------------------------------------
def _iso(v: Any) -> str | None:
    return None if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d")


def _fila_aviso(tk: str, pv: str, tipo: str, sesiones: Any, accion: str, propuesta: str | None,
                nota: str | None = None, n: int | None = None) -> dict[str, Any]:
    s = pd.to_datetime(pd.Series(sesiones))
    return {"ticker": tk, "proveedor": pv, "tipo": tipo, "n": int(len(s) if n is None else n),
            "primera": _iso(s.min()) if len(s) else None, "ultima": _iso(s.max()) if len(s) else None,
            "accion": accion, "propuesta_eda": propuesta, "nota": nota}


def _calendario(mercado: str | None, sesiones_cal: np.ndarray | None = None) -> np.ndarray | None:
    """Sesiones del calendario del mercado (``eda.CALENDARIO_MERCADO``) o ``sesiones_cal``; ``None``: días L-V."""
    if sesiones_cal is not None:
        return np.asarray(sesiones_cal).astype("datetime64[D]")
    nombre = eda.CALENDARIO_MERCADO.get(mercado or "")
    if not nombre:
        return None
    try:
        return eda.sesiones_calendario(nombre)
    except Exception:          # calendario que no resuelve: días L-V (como eda.sesiones_faltantes)
        return None


def ultima_sesion_esperada(mercado: str | None, corte: pd.Timestamp = CORTE_G2, retraso_dias: int = 0,
                           sesiones_cal: np.ndarray | None = None) -> pd.Timestamp | None:
    """Última sesión del calendario del mercado (``eda.CALENDARIO_MERCADO``; sin calendario, días L-V) que se
    publica hasta ``corte``: la última con ``sesion + retraso_dias <= corte`` (Coinbase publica al día siguiente)."""
    tope = np.datetime64((pd.Timestamp(corte) - pd.Timedelta(days=int(retraso_dias))).date(), "D")
    cal = _calendario(mercado, sesiones_cal)
    if cal is None:
        dias = np.arange(tope - np.timedelta64(14, "D"), tope + np.timedelta64(1, "D"), dtype="datetime64[D]")
        cal = dias[np.is_busday(dias)]
    cal = cal[cal <= tope]
    return pd.Timestamp(cal[-1]) if len(cal) else None


def aviso_no_llega_corte(tk: str, pv: str, h: pd.DataFrame, corte: pd.Timestamp = CORTE_G2,
                         motivos: Mapping[str, str] | None = None,
                         sesiones_cal: np.ndarray | None = None) -> dict[str, Any] | None:
    """Aviso ``no_llega_corte``: el último dato publicado hasta el corte (``h``, ordenada por sesión) es anterior a
    la última sesión de su calendario que se publica hasta el corte (``ultima_sesion_esperada``, con el retraso de
    publicación del propio ticker). ``n`` = sesiones del calendario que faltan; la nota lleva el motivo de
    ``estado_3b.MOTIVOS_REFRESCO`` si lo hay. ``None`` si llega."""
    if not len(h):
        return None
    ultima = pd.Timestamp(h["sesion"].iloc[-1]).normalize()
    retraso = max(0, (pd.Timestamp(h["fecha_publicacion"].iloc[-1]).normalize() - ultima).days)
    mercado = h["mercado"].iloc[-1] if "mercado" in h else None
    esperada = ultima_sesion_esperada(mercado, corte, retraso, sesiones_cal)
    if esperada is None or ultima >= esperada:
        return None
    cal = _calendario(mercado, sesiones_cal)
    u, e = np.datetime64(ultima.date(), "D"), np.datetime64(esperada.date(), "D")
    faltan = (int(((cal > u) & (cal <= e)).sum()) if cal is not None
              else int(np.busday_count(u + np.timedelta64(1, "D"), e + np.timedelta64(1, "D"))))
    motivo = dict(motivos or {}).get(tk)
    nota = (f"último dato {ultima:%Y-%m-%d}, anterior a la última sesión del calendario antes del corte "
            f"({esperada:%Y-%m-%d})" + (f": {motivo}" if motivo else ""))
    return _fila_aviso(tk, pv, NO_LLEGA_CORTE, [ultima, esperada], SOLO_AVISO, None, nota, n=faltan)


def avisos_ticker(tk: str, pv: str, r: Curado, entrada: Mapping[str, Any], meta: Mapping[str, Any] | None = None,
                  sesiones_cal: np.ndarray | None = None, motivos: Mapping[str, str] | None = None,
                  corte: pd.Timestamp = CORTE_G2) -> list[dict[str, Any]]:
    """Avisos de un ticker: lo aplicado (desde las máscaras), el resto de tipos del EDA (``eda.controles_ticker``
    sobre lo que queda tras el corte, solo aviso), ``no_llega_corte`` (``aviso_no_llega_corte``, con ``motivos``)
    y el ``aviso`` de la lista curada."""
    h = r.hasta_corte
    filas = []
    falta = aviso_no_llega_corte(tk, pv, h, corte, motivos, sesiones_cal)
    if falta:
        filas.append(falta)
    if r.quitada.any():
        filas.append(_fila_aviso(tk, pv, RELLENO, h.loc[r.quitada, "sesion"], QUITADA, eda.PROPUESTAS[RELLENO]))
    if r.relleno_con_evento.any():
        filas.append(_fila_aviso(tk, pv, "relleno_con_evento", h.loc[r.relleno_con_evento, "sesion"], SOLO_AVISO,
                                 eda.PROPUESTAS[RELLENO], "vela de relleno con dividendo o split: se conserva"))
    if r.anulada.any():
        sin_vol = _sin_volumen(h)
        for tipo, m, nota in ((APERTURA, r.anulada & sin_vol, "open, high y low a nulo (sin volumen)"),
                              (APERTURA_CON_VOLUMEN, r.anulada & ~sin_vol,
                               "open, high y low a nulo: OHLC plano con volumen > 0, no es una apertura ejecutable")):
            if m.any():
                filas.append(_fila_aviso(tk, pv, tipo, h.loc[m, "sesion"], NULO, eda.PROPUESTAS[APERTURA], nota))
    c = r.curado
    if len(c):
        pct = 100.0 * float(c["open"].isna().sum()) / len(c)
        if pct > UMBRAL_SIN_APERTURA:
            filas.append(_fila_aviso(tk, pv, SIN_APERTURA, c.loc[c["open"].isna(), "sesion"], SOLO_AVISO, None,
                                     f"{pct:.1f} % de las sesiones curadas sin open (> {UMBRAL_SIN_APERTURA:.0f} %): "
                                     "no hay apertura; la ejecución en t+1 tendrá que usar el cierre"))
    if len(h):
        _, inc = eda.controles_ticker(h, tk, pv, dict(meta or {}), sesiones_cal=sesiones_cal)
        d = pd.DataFrame(inc, columns=list(eda.COLUMNAS_INC_PRECIOS))
        d = d[~d["tipo"].isin(list(APLICADOS))]
        for tipo, g in d.groupby("tipo", sort=True):
            fin = g["fecha_fin"].fillna(g["fecha"])
            notas = "; ".join(sorted(set(g["nota"].dropna().astype(str))))[:300] or None
            filas.append({"ticker": tk, "proveedor": pv, "tipo": tipo, "n": int(g["n"].sum()),
                          "primera": g["fecha"].min(), "ultima": fin.max(), "accion": SOLO_AVISO,
                          "propuesta_eda": eda.PROPUESTAS.get(tipo), "nota": notas})
    else:
        filas.append(_fila_aviso(tk, pv, "sin_sesiones_hasta_corte", [], SOLO_AVISO, None,
                                 f"ninguna sesión publicada hasta el corte {CORTE_G2:%Y-%m-%d}"))
    aviso = entrada.get("aviso")
    if aviso:
        filas.append(_fila_aviso(tk, pv, "aviso_lista", r.curado["sesion"], SOLO_AVISO, None, str(aviso)))
    # Saneado del 2026-11-21 (saneado_precios)
    san = r.saneado
    if tk in sp.MERCADO_CORREGIDO:
        filas.append(_fila_aviso(tk, pv, MERCADO_CORREGIDO, r.curado["sesion"], SOLO_AVISO, None,
                                 sp.MERCADO_CORREGIDO[tk][1]))
    if san.rellenas:
        filas.append(_fila_aviso(tk, pv, RELLENO_FFILL, sorted(san.rellenas), RELLENADA, None,
                                 f"hueco de calendario de hasta {sp.MAX_HUECO} sesiones: vela plana del cierre "
                                 "anterior (open/high/low nulos, volumen 0); no vale como apertura de t+1"))
    for desde, hasta_h, n in san.huecos_largos:
        filas.append(_fila_aviso(tk, pv, HUECO_LARGO, [desde, hasta_h], SOLO_AVISO, None,
                                 f"hueco de {n} sesiones seguidas sin vela (> {sp.MAX_HUECO}): no se rellena; el "
                                 "ticker debe salir de la curada (saneado P28)", n=n))
    for tipo in (sp.PICO, sp.SPLIT, sp.REAL):
        g = [x for x in san.saltos if x["tipo"] == tipo]
        if g:
            nombre, accion = AVISO_SALTO[tipo]
            filas.append(_fila_aviso(tk, pv, nombre, [x["sesion"] for x in g], accion, eda.PROPUESTAS["salto_sin_split"],
                                     sp.TIPOS_SALTO[tipo] + " (saneado P11; ver precios_curados_saltos.csv)"))
    return filas


# --- Escritura --------------------------------------------------------------------------------------
def _renombrar(a: Path, b: Path) -> None:
    for intento in range(_REINTENTOS):
        try:
            os.replace(a, b)
            return
        except PermissionError:
            if intento == _REINTENTOS - 1:
                raise
            time.sleep(0.2 * (intento + 1))


def _csv_atomico(df: pd.DataFrame, ruta: Path) -> Path:
    """Tabla de metadatos sin columnas de precios (``eda.PROHIBIDAS``), con ``almacen.escribir_csv_atomico``."""
    return almacen.escribir_csv_atomico(df, ruta, prohibidas=eda.PROHIBIDAS)


def _limpiar_restos(destino: Path) -> None:
    """Quita temporales de una ejecución cortada; si falta ``destino`` y hay una previa, la devuelve."""
    previas = sorted(destino.parent.glob(f"{destino.name}.previa_*"))
    if not destino.exists() and previas:
        _renombrar(previas.pop(), destino)
    for p in [*destino.parent.glob(f"{destino.name}.nuevo_*"), *previas]:
        shutil.rmtree(p, ignore_errors=True)


def _publicar(nuevo: Path, destino: Path) -> None:
    """Cambia ``destino`` por ``nuevo`` (dos renombrados; si el segundo falla, vuelve la anterior)."""
    previa = destino.with_name(f"{destino.name}.previa_{uuid.uuid4().hex[:12]}")
    if destino.exists():
        _renombrar(destino, previa)
    try:
        _renombrar(nuevo, destino)
    except Exception:
        if previa.exists():
            _renombrar(previa, destino)
        raise
    shutil.rmtree(previa, ignore_errors=True)


def _firma(f: Path) -> tuple[int, int]:
    s = f.stat()
    return s.st_size, s.st_mtime_ns


# --- Orden completa ---------------------------------------------------------------------------------
def curar_precios(origen: Path | None = None, destino: Path | None = None, tablas: Path | None = None,
                  lista: Mapping[str, Mapping[str, Any]] | None = None, *, ruta_lista: Path | None = None,
                  solo: Iterable[str] | None = None, escribir: bool = True, corte: pd.Timestamp = CORTE_G2,
                  meta: pd.DataFrame | None = None, sesiones_cal: np.ndarray | None = None,
                  registro: Callable[[str], None] | None = print) -> dict[str, Any]:
    """Construye los precios curados (ver el docstring del módulo) y devuelve el resumen de la ejecución.

    ``origen``: la carpeta ``precios`` (por defecto la del corpus); ``destino``: ``precios_curados``; ``tablas``:
    ``results/.../tablas``; ``lista``: la sección ``precios`` de la lista curada (si no, ``ruta_lista`` o la del
    repo, y entonces también se mira su cabecera). ``solo``: solo esos tickers (prueba; los recuentos se miran
    sobre ellos) y no puede escribir en la carpeta del corpus. ``escribir=False``: verifica sin escribir nada.
    """
    t0 = time.time()
    log = registro or (lambda _m: None)
    origen = Path(origen or corpus_dir(TEMA) / "precios")
    por_defecto = destino is None
    destino = Path(destino or ruta_curados())
    tablas = Path(tablas or resultados_dir(TEMA) / "tablas")
    cabecera = None
    if lista is None:
        lista = cargar_lista_precios(ruta_lista)
        cabecera = queda_cabecera(ruta_lista)
    solo_set = set(solo) if solo is not None else None
    if solo_set is not None and escribir and por_defecto:
        raise ValueError("con 'solo' no se escribe en la carpeta del corpus: pasa otro destino o escribir=False")
    meta = eda.meta_precios() if meta is None else meta
    from ingesta.mercados_series import estado_3b

    motivos = estado_3b.MOTIVOS_REFRESCO          # motivo de los avisos no_llega_corte

    ficheros, dobles = ficheros_origen(origen)
    if solo_set is not None:
        ficheros = {tk: v for tk, v in ficheros.items() if tk in solo_set}
        lista = {tk: e for tk, e in lista.items() if tk in solo_set}
        cabecera = None
    queda = sorted(tk for tk, e in lista.items() if (e or {}).get("decision") == "queda")
    sin_decision = sorted(set(ficheros) - set(lista))
    sin_fichero = [tk for tk in queda if tk not in ficheros]
    firmas = {tk: _firma(f) for tk, (_, f) in ficheros.items()}

    nuevo = destino.with_name(f"{destino.name}.nuevo_{uuid.uuid4().hex[:12]}")
    fallos = dict.fromkeys(VERIFICACIONES, 0)
    ejemplos: dict[str, list[str]] = {k: [] for k in VERIFICACIONES}
    avisos, resumen, escritos, saltos = [], [], [], []
    total = {"quitadas": 0, "anuladas": 0, "fuera_corte": 0, "rellenos_ffill": 0, "picos_corregidos": 0,
             "splits_registrados": 0}

    def falla(clave: str, n: int, ejemplo: str) -> None:
        if n:
            fallos[clave] += n
            if len(ejemplos[clave]) < 5:
                ejemplos[clave].append(ejemplo)

    if escribir:
        _limpiar_restos(destino)
    try:
        for i, tk in enumerate(t for t in queda if t in ficheros):
            pv, f = ficheros[tk]
            try:
                original = validar_precios(pq.read_table(f).to_pandas())
                if set(original["ticker"]) - {tk}:
                    raise ErrorContrato("precios", [f"{f.name} contiene otro ticker"])
                r = curar_ticker(original, corte, sesiones_cal, clase=(lista[tk] or {}).get("clase"))
            except ErrorContrato as e:
                falla("esquema_valido", 1, f"{tk}: {str(e)[:200]}")
                continue
            for clave, n in verificar_ticker(r.referencia, r.curado, corte, sesiones_cal, r.saneado).items():
                falla(clave, n, tk)
            if tk in sp.MERCADO_CORREGIDO:
                falla("mercado_corregido_sin_adelanto",
                      int((r.referencia["disponible_utc"] < original["disponible_utc"]).sum()), tk)
            falla("sin_huecos_largos", int(bool(r.saneado.huecos_largos) and tk not in sp.EXCEPCIONES_HUECO), tk)
            saltos += sp.registro_saltos(tk, pv, r.saneado)
            if escribir:
                ruta = ruta_precios_curados(pv, tk, nuevo)
                almacen.escribir_parquet_atomico(r.curado, almacen.ESQUEMA_PRECIOS, ruta)
                leido = pq.read_table(ruta).to_pandas()
                if not leido.equals(r.curado[list(COLUMNAS_PRECIOS)]):
                    falla("esquema_valido", 1, f"{tk}: el parquet escrito no se relee igual")
            escritos.append(tk)
            m = (pv, tk)
            avisos += avisos_ticker(tk, pv, r, lista[tk], meta.loc[m].to_dict() if m in meta.index else {},
                                    sesiones_cal, motivos, corte)
            c = r.curado
            resumen.append({"ticker": tk, "proveedor": pv, "sesiones_antes": len(original),
                            "fuera_corte": r.fuera_corte, "velas_quitadas": int(r.quitada.sum()),
                            "aperturas_anuladas": int(r.anulada.sum()), "sesiones_despues": len(c),
                            "desde": _iso(c["sesion"].min()) if len(c) else None,
                            "hasta": _iso(c["sesion"].max()) if len(c) else None,
                            "hasta_original": _iso(original["sesion"].max()) if len(original) else None,
                            "rellenos_ffill": len(r.saneado.rellenas), "picos_corregidos": len(r.saneado.corregidas),
                            "splits_registrados": len(r.saneado.splits)})
            total["rellenos_ffill"] += len(r.saneado.rellenas)
            total["picos_corregidos"] += len(r.saneado.corregidas)
            total["splits_registrados"] += len(r.saneado.splits)
            total["quitadas"] += int(r.quitada.sum())
            total["anuladas"] += int(r.anulada.sum())
            total["fuera_corte"] += r.fuera_corte
            if (i + 1) % 250 == 0:
                log(f"  {i + 1}/{len(queda)} tickers ({time.time() - t0:.0f} s)")

        # Recuentos y origen intacto
        falla("recuento_tickers", len(set(queda) ^ set(escritos)),
              f"{len(escritos)} escritos frente a {len(queda)} «queda»")
        if cabecera is not None:
            falla("cabecera_lista", abs(cabecera - len(queda)), f"cabecera {cabecera}, entradas {len(queda)}")
        falla("queda_sin_fichero", len(sin_fichero), ", ".join(sin_fichero[:5]))
        falla("ficheros_sin_decision", len(sin_decision), ", ".join(sin_decision[:5]))
        reutilizados = sp.tickers_reutilizados(lista)
        falla("reutilizados_fuera", len(reutilizados), ", ".join(reutilizados[:5]))
        dobles = [tk for tk in dobles if solo_set is None or tk in solo_set]
        falla("ticker_en_dos_proveedores", len(dobles), ", ".join(dobles[:5]))
        cambiados = [tk for tk, (_, fi) in ficheros.items() if not fi.exists() or _firma(fi) != firmas[tk]]
        falla("origen_intacto", len(cambiados), ", ".join(cambiados[:5]))

        ok = not any(fallos.values())
        filas_v = []
        for clave, texto in VERIFICACIONES.items():
            estado = "no aplica" if clave == "negativo_en_nivel" else ("fallo" if fallos[clave] else "ok")
            if clave == "cabecera_lista" and cabecera is None:
                estado = "no aplica"
            detalle = texto
            if clave == "recuento_tickers":
                detalle += f" ({len(escritos)} de {len(queda)})"
            elif clave == "cabecera_lista" and cabecera is not None:
                detalle += f" ({cabecera})"
            elif clave == "negativo_en_nivel":
                detalle += ("; los cierres <= 0 van como salto_sin_split con nota y el contrato admite precios "
                            "negativos: no se cambian")
            if ejemplos[clave]:
                detalle += "; p. ej. " + "; ".join(ejemplos[clave])
            filas_v.append({"verificacion": clave, "estado": estado, "n_fallos": fallos[clave], "detalle": detalle})
        ver = pd.DataFrame(filas_v, columns=list(COLUMNAS_VERIFICACIONES))
        av = pd.DataFrame(avisos, columns=list(COLUMNAS_AVISOS)).sort_values(
            ["proveedor", "ticker", "tipo"], kind="mergesort").reset_index(drop=True)
        av["n"] = av["n"].astype("int64")
        res = pd.DataFrame(resumen, columns=list(COLUMNAS_RESUMEN)).sort_values(
            ["proveedor", "ticker"], kind="mergesort").reset_index(drop=True)
        sal = pd.DataFrame(saltos, columns=list(sp.COLUMNAS_SALTOS)).sort_values(
            ["proveedor", "ticker", "sesion"], kind="mergesort").reset_index(drop=True)
        rutas: dict[str, Path] = {}
        if escribir:
            rutas["precios_curados_verificaciones.csv"] = _csv_atomico(ver, tablas / "precios_curados_verificaciones.csv")
            if ok:
                nuevo.mkdir(parents=True, exist_ok=True)      # también sin ningún ticker
                _publicar(nuevo, destino)
                rutas["precios_curados"] = destino
                rutas["precios_curados_avisos.csv"] = _csv_atomico(av, tablas / "precios_curados_avisos.csv")
                rutas["precios_curados_resumen.csv"] = _csv_atomico(res, tablas / "precios_curados_resumen.csv")
                rutas["precios_curados_saltos.csv"] = _csv_atomico(sal, tablas / "precios_curados_saltos.csv")
    finally:
        if nuevo.exists():
            shutil.rmtree(nuevo, ignore_errors=True)
    por_proveedor = res.groupby("proveedor").size().to_dict() if len(res) else {}
    return {"ok": ok, "tickers": len(escritos), "por_proveedor": por_proveedor, "queda": len(queda),
            **total, "segundos": round(time.time() - t0, 1), "verificaciones": ver, "avisos": av, "resumen": res,
            "saltos": sal, "rutas": rutas}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sin-escribir", action="store_true", help="construye y verifica sin escribir nada")
    p.add_argument("--tickers", default=None, help="solo estos tickers, separados por comas (prueba; no escribe)")
    a = p.parse_args(argv)
    solo = a.tickers.split(",") if a.tickers else None
    r = curar_precios(solo=solo, escribir=not (a.sin_escribir or solo))
    print(f"tickers curados: {r['tickers']} de {r['queda']} «queda» ({r['por_proveedor']}); fuera por el corte "
          f"{CORTE_G2:%Y-%m-%d}: {r['fuera_corte']} sesiones; velas de relleno quitadas: {r['quitadas']}; "
          f"aperturas anuladas: {r['anuladas']}; rellenos de huecos (P28): {r['rellenos_ffill']}; sesiones de picos "
          f"corregidas (P11): {r['picos_corregidos']}; splits registrados (P11): {r['splits_registrados']}; "
          f"{r['segundos']} s")
    if len(r["saltos"]):
        print("saltos sin split por tipo (P11):", r["saltos"]["tipo"].value_counts().to_dict())
    print(r["verificaciones"][["verificacion", "estado", "n_fallos"]].to_string(index=False))
    for nombre, ruta in r["rutas"].items():
        print(f"{nombre} -> {ruta}")
    if not r["ok"]:
        print("ALGUNA VERIFICACIÓN FALLA: no se publica nada (solo precios_curados_verificaciones.csv)")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
