"""Tools tipadas del Tema 1 sobre :mod:`ingesta.mercados_series.tools` (Fase 2): series, precios, proyecciones y
búsqueda en el catálogo de agentes.

Solo envuelven: el TimeGate, los alias, la base curada (``BASE_DEFECTO``) y los avisos son los de ``tools.py``. Aquí
se decide **qué ve el LLM**: un resumen y las últimas ``max_filas`` filas, nunca la ventana entera.

Reglas del resumen
------------------
- **Último valor**: la última fila con valor (un hueco declarado al final no cuenta como último; sí sale en ``filas``).
- **Cambio** (``tipo_cambio``), frente al periodo anterior (la observación con valor previa) y frente a hace un año
  (la última observación con fecha de referencia ``<=`` la del último menos un año, como mucho
  ``TOLERANCIA_ANUAL_DIAS`` días antes; si no la hay, ``None``):

  * ``'porcentaje'`` = ``100 * (último / base - 1)`` si la unidad es un **nivel** (importes, recuentos, precios,
    tipos de cambio, índices con base) **y** toda la historia visible es positiva;
  * ``'diferencia'`` = ``último - base``, en la unidad de la serie, en el resto: unidades que son tipos, porcentajes
    o puntos (llevan ``%``, «puntos porcentuales», «puntos básicos», «tanto por uno», «ratio», «0/1», «difusión»,
    «desviaciones», «0 = ...»), unidad desconocida o una historia con ceros o negativos (un índice centrado en 0).

- **Percentil**: % de las observaciones con valor de la historia visible en la fecha (toda, sin recortar por
  ``desde``) que son ``<=`` que el último (él incluido): 100 es el máximo histórico.
- **Mínimo, máximo y n_obs**: de la ventana pedida (``desde`` hasta la fecha), solo filas con valor.

Precios (por ticker, con el ajuste y la divisa pedidos, sobre toda la historia visible): rentabilidades a 1, 3 y 12
meses en % (último cierre frente al último cierre ``<=`` hace k meses, como mucho ``TOLERANCIA_PRECIO_DIAS`` antes),
volatilidad anualizada en % de los rendimientos logarítmicos diarios de los últimos 3 meses (raíz de 252 sesiones;
365 en cripto; al menos ``MIN_RENDIMIENTOS_VOL``) y caída en % desde el cierre máximo de los últimos 12 meses (<= 0).

Los estadísticos derivados (cambios, percentil, rentabilidades, volatilidad, caída) van redondeados a ``CIFRAS`` cifras
significativas; los valores y cierres, tal cual.

Errores: un id o ticker desconocido, o sin nada publicado hasta la fecha, **no lanza**: ``encontrado=False`` con un
aviso neutro (el de ``tools.py``, que no revela si existirá) que remite a ``buscar_series``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import Field, StringConstraints

from herramientas.contrato import Cita, EntradaTool, Modelo, SalidaTool
from herramientas.registro import registrar
from ingesta.comun import rutas
from ingesta.mercados_series import almacen
from ingesta.mercados_series import catalogo as _catalogo
from ingesta.mercados_series import tools as _tools

Agente = Literal["macro", "equity", "risk", "portfolio", "cio"]

FUENTE_SERIES = "mercados_series/base_curada.parquet"
FUENTE_PROYECCIONES = "mercados_series/proyecciones.parquet"
FUENTE_PRECIOS = "mercados_series/precios_curados"
FUENTE_CATALOGO = "results/ingesta/mercados_series/tablas/catalogo_agentes.csv"
FICHERO_MANIFIESTO = "curada_manifiesto.json"   # = curada.FICHERO_MANIFIESTO (sin importar el módulo de curación)

TOLERANCIA_ANUAL_DIAS = 31
TOLERANCIA_PRECIO_DIAS = 31
MIN_RENDIMIENTOS_VOL = 20
SESIONES_ANIO = 252
SESIONES_ANIO_CRIPTO = 365
CIFRAS = 6   # cifras significativas de cambios, percentiles, rentabilidades y volatilidades

_AVISO_BUSCAR = "Usa buscar_series para encontrar el id correcto."
# Unidades que se comparan por diferencia (tipos, porcentajes, puntos, ratios, índices centrados): ver docstring.
_UNIDAD_DIFERENCIA = re.compile(
    r"%|puntos porcentuales|puntos básicos|tanto por uno|ratio|0/1|difusión|desviaciones|\b0 =", re.IGNORECASE)


# --- Huellas para las citas ---------------------------------------------------------------------
_CACHE_HUELLAS: dict[str, tuple[tuple[int, int], Any]] = {}


def _firma(ruta: Path) -> tuple[int, int] | None:
    try:
        st = ruta.stat()
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_size


def _manifiesto() -> dict[str, Any] | None:
    """``curada_manifiesto.json`` del paso 4 (en caché por mtime y tamaño); None si falta o no se puede leer."""
    ruta = almacen.ruta_series(curada=True).parent / FICHERO_MANIFIESTO
    firma = _firma(ruta)
    if firma is None:
        return None
    guardado = _CACHE_HUELLAS.get(str(ruta))
    if guardado is None or guardado[0] != firma:
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            contenido = None
        guardado = _CACHE_HUELLAS[str(ruta)] = (firma, contenido)
    return guardado[1]


def huella_salida(nombre: str, ruta: Path) -> str | None:
    """sha256 de la salida ``nombre`` del manifiesto (``base_curada``, ``proyecciones``...), si su tamaño coincide
    con el del fichero en disco (si no, el manifiesto no describe ese fichero y no se cita huella)."""
    salida = ((_manifiesto() or {}).get("salidas") or {}).get(nombre) or {}
    firma = _firma(ruta)
    if not salida.get("sha256") or firma is None or salida.get("tamano") != firma[1]:
        return None
    return str(salida["sha256"])


def huella_fichero(ruta: Path) -> str | None:
    """sha256 de un fichero (en caché por mtime y tamaño); None si no existe."""
    firma = _firma(ruta)
    if firma is None:
        return None
    guardado = _CACHE_HUELLAS.get(str(ruta))
    if guardado is None or guardado[0] != firma:
        h = hashlib.sha256()
        with ruta.open("rb") as f:
            for bloque in iter(lambda: f.read(1 << 20), b""):
                h.update(bloque)
        guardado = _CACHE_HUELLAS[str(ruta)] = (firma, h.hexdigest())
    return guardado[1]


# --- Conversión ---------------------------------------------------------------------------------
def _fecha(valor: Any) -> date | None:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    return pd.Timestamp(valor).date()


def _real(valor: Any) -> float | None:
    if valor is None or pd.isna(valor):
        return None
    v = float(valor)
    return v if math.isfinite(v) else None


def _texto(valor: Any) -> str | None:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    return str(valor)


def _redondear(valor: float | None) -> float | None:
    """Estadístico derivado a ``CIFRAS`` cifras significativas (sin ruido de coma flotante para el LLM)."""
    return None if valor is None or not math.isfinite(valor) else float(f"{valor:.{CIFRAS}g}")


def _aviso_no_encontrado(e: KeyError, pedido: str, que: str = "serie") -> str:
    """Aviso de un id no servido. «Sin datos publicados» se reescribe con el id PEDIDO: el de ``tools.py`` nombra el
    canónico de un alias ('fred:NFCI' (alias 'NFCI')) y así distinguiría un alias que existirá de un id que no existe."""
    texto = str(e.args[0] if e.args else e)
    if "sin datos publicados hasta" in texto:
        fecha = texto.split("sin datos publicados hasta", 1)[1].split()[0]
        texto = f"{que} {pedido!r} sin datos publicados hasta {fecha} (desconocida o aún no publicada)"
    return f"{texto.rstrip('.')}. {_AVISO_BUSCAR}"


def _ficha_catalogo(id: str) -> dict[str, Any]:
    return _catalogo._cat(None).get(id) or {}


# --- get_serie ----------------------------------------------------------------------------------
class EntradaSerie(EntradaTool):
    id: str = Field(min_length=1, description="Id de la serie con prefijo de fuente (p. ej. 'fred:DGS10') o un alias "
                                              "conocido. Si no lo sabes, búscalo antes con buscar_series.")
    desde: date | None = Field(default=None, description="Primera fecha de referencia de la ventana (AAAA-MM-DD). "
                                                         "Sin ella, toda la historia visible.")
    divisa: Literal["original", "USD"] = Field(default="original", description="'USD' convierte las series "
                                               "monetarias con el tipo de cambio del BCE visible en la fecha.")
    max_filas: int = Field(default=24, ge=0, le=260, description="Últimas filas de la ventana que se devuelven "
                                                                 "además del resumen (0 = solo el resumen).")


class FilaSerie(Modelo):
    fecha_referencia: date
    fecha_publicacion: date
    valor: float | None


class ResumenSerie(Modelo):
    """Resumen de una serie en la fecha de la decisión (reglas en el docstring del módulo)."""

    ultimo_valor: float | None = Field(description="Última observación con valor.")
    fecha_referencia: date | None = Field(description="Periodo del último valor.")
    fecha_publicacion: date | None = Field(description="Cuándo se publicó el último valor (<= fecha de la decisión).")
    tipo_cambio: Literal["diferencia", "porcentaje"] = Field(
        description="'diferencia' (en la unidad de la serie) para tipos, porcentajes y puntos; 'porcentaje' (%) "
                    "para niveles con historia positiva.")
    cambio_periodo: float | None = Field(description="Cambio frente a la observación anterior.")
    fecha_referencia_anterior: date | None
    cambio_anual: float | None = Field(description="Cambio frente a hace un año.")
    fecha_referencia_hace_un_anio: date | None
    percentil_historico: float | None = Field(
        description="% de la historia visible con valor <= último (100 = máximo histórico).")
    n_historia: int = Field(description="Observaciones con valor de toda la historia visible.")
    historia_desde: date | None = Field(description="Primera fecha de referencia con valor de la historia visible.")
    minimo_ventana: float | None
    maximo_ventana: float | None
    n_obs: int = Field(description="Observaciones con valor en la ventana pedida.")


class SalidaSerie(SalidaTool):
    id: str = Field(description="Id pedido.")
    id_servido: str | None = Field(description="Id canónico servido (distinto de id si era un alias).")
    encontrado: bool
    nombre: str | None = None
    unidad: str | None = None
    frecuencia: str | None = None
    divisa: str | None = None
    resumen: ResumenSerie | None = None
    filas: list[FilaSerie] = Field(default_factory=list, description="Últimas max_filas filas de la ventana.")
    filas_omitidas: int = Field(default=0, description="Filas de la ventana que no se devuelven (más antiguas).")


def tipo_cambio(unidad: str | None, valores: pd.Series) -> Literal["diferencia", "porcentaje"]:
    """Regla del cambio: 'porcentaje' solo para un nivel con toda la historia positiva (ver docstring del módulo)."""
    if unidad is None or _UNIDAD_DIFERENCIA.search(unidad):
        return "diferencia"
    v = valores.dropna()
    return "porcentaje" if len(v) and bool((v > 0).all()) else "diferencia"


def _cambio(ultimo: float, base: float | None, tipo: str) -> float | None:
    if base is None or not math.isfinite(base):
        return None
    if tipo == "porcentaje":
        return _redondear(100.0 * (ultimo / base - 1.0)) if base > 0 else None
    return _redondear(ultimo - base)


def resumir_serie(historia: pd.DataFrame, ventana: pd.DataFrame, unidad: str | None) -> ResumenSerie:
    """Resumen de ``historia`` (todo lo visible) con mínimo, máximo y n_obs de ``ventana`` (columnas de get_serie)."""
    h = historia[historia["valor"].notna()].sort_values("fecha_referencia", kind="mergesort")
    v = ventana["valor"].dropna()
    tipo = tipo_cambio(unidad, h["valor"])
    base = {"minimo_ventana": _real(v.min()) if len(v) else None,
            "maximo_ventana": _real(v.max()) if len(v) else None, "n_obs": int(len(v)), "n_historia": int(len(h)),
            "tipo_cambio": tipo, "historia_desde": _fecha(h["fecha_referencia"].iloc[0]) if len(h) else None}
    if h.empty:
        return ResumenSerie(ultimo_valor=None, fecha_referencia=None, fecha_publicacion=None, cambio_periodo=None,
                            fecha_referencia_anterior=None, cambio_anual=None, fecha_referencia_hace_un_anio=None,
                            percentil_historico=None, **base)
    ult = h.iloc[-1]
    ultimo = float(ult["valor"])
    anterior = h.iloc[-2] if len(h) > 1 else None
    objetivo = pd.Timestamp(ult["fecha_referencia"]) - pd.DateOffset(years=1)
    previas = h[(h["fecha_referencia"] <= objetivo)
                & (h["fecha_referencia"] >= objetivo - pd.Timedelta(days=TOLERANCIA_ANUAL_DIAS))]
    hace_un_anio = previas.iloc[-1] if len(previas) else None
    return ResumenSerie(
        ultimo_valor=ultimo, fecha_referencia=_fecha(ult["fecha_referencia"]),
        fecha_publicacion=_fecha(ult["fecha_publicacion"]),
        cambio_periodo=_cambio(ultimo, _real(anterior["valor"]) if anterior is not None else None, tipo),
        fecha_referencia_anterior=_fecha(anterior["fecha_referencia"]) if anterior is not None else None,
        cambio_anual=_cambio(ultimo, _real(hace_un_anio["valor"]) if hace_un_anio is not None else None, tipo),
        fecha_referencia_hace_un_anio=_fecha(hace_un_anio["fecha_referencia"]) if hace_un_anio is not None else None,
        percentil_historico=_redondear(100.0 * float((h["valor"] <= ultimo).mean())), **base)


def _filas_serie(datos: pd.DataFrame, max_filas: int) -> tuple[list[FilaSerie], int]:
    cola = datos.tail(max_filas) if max_filas else datos.iloc[0:0]
    filas = [FilaSerie(fecha_referencia=_fecha(r.fecha_referencia), fecha_publicacion=_fecha(r.fecha_publicacion),
                       valor=_real(r.valor)) for r in cola.itertuples(index=False)]
    return filas, len(datos) - len(filas)


def _cita_series(fecha_publicacion: date | None) -> Cita:
    ruta = almacen.ruta_series(curada=True)
    return Cita(fuente=FUENTE_SERIES, id=huella_salida("base_curada", ruta), fecha_publicacion=fecha_publicacion)


@registrar("get_serie", EntradaSerie, agentes=("macro", "risk", "portfolio", "cio"))
def get_serie(entrada: EntradaSerie, fecha: date) -> SalidaSerie:
    """Serie macro o de mercado tal como se conocía en la fecha de la decisión: resumen (último dato, cambios, percentil histórico) y últimas filas."""
    comun = {"tool": "get_serie", "fecha_consulta": fecha, "id": entrada.id}
    try:
        historia = _tools.get_serie(entrada.id, fecha, divisa=entrada.divisa)
    except KeyError as e:
        return SalidaSerie(**comun, id_servido=None, encontrado=False, citas=[_cita_series(None)],
                           avisos=[_aviso_no_encontrado(e, entrada.id)])
    ventana = historia if entrada.desde is None else _tools.get_serie(
        entrada.id, fecha, desde=entrada.desde, divisa=entrada.divisa)
    filas, omitidas = _filas_serie(ventana.datos, entrada.max_filas)
    ficha = _ficha_catalogo(historia.serie)
    ultima_pub = _fecha(historia.datos["fecha_publicacion"].max()) if len(historia.datos) else None
    return SalidaSerie(
        **comun, id_servido=historia.serie, encontrado=True, citas=[_cita_series(ultima_pub)],
        avisos=list(ventana.avisos), nombre=_texto(ficha.get("nombre")), unidad=historia.unidad,
        frecuencia=_texto(ficha.get("frecuencia")), divisa=historia.divisa,
        resumen=resumir_serie(historia.datos, ventana.datos, historia.unidad), filas=filas, filas_omitidas=omitidas)


# --- get_proyeccion -----------------------------------------------------------------------------
class EntradaProyeccion(EntradaTool):
    id: str = Field(min_length=1, description="Id de la proyección (WEO del FMI o SEP del FOMC, p. ej. "
                                              "'fred:FEDTARMD'). Si no lo sabes, búscalo con buscar_series.")
    desde: date | None = Field(default=None, description="Primer año proyectado (fecha de referencia, AAAA-MM-DD).")


class FilaProyeccion(Modelo):
    fecha_referencia: date = Field(description="Periodo proyectado.")
    fecha_publicacion: date
    valor: float | None
    horizonte: float | None = Field(description="Años entre la edición y el periodo proyectado.")
    edicion: str | None


class SalidaProyeccion(SalidaTool):
    id: str
    id_servido: str | None
    encontrado: bool
    nombre: str | None = None
    unidad: str | None = None
    divisa: str | None = None
    ultima_edicion: str | None = Field(default=None, description="Edición más reciente visible en la fecha.")
    filas: list[FilaProyeccion] = Field(
        default_factory=list, description="Una fila por periodo proyectado, de la última edición visible que lo cubre.")


@registrar("get_proyeccion", EntradaProyeccion, agentes=("macro", "cio"))
def get_proyeccion(entrada: EntradaProyeccion, fecha: date) -> SalidaProyeccion:
    """Proyecciones oficiales (FMI, FOMC) visibles en la fecha de la decisión: por periodo, la última edición publicada, con su horizonte."""
    comun = {"tool": "get_proyeccion", "fecha_consulta": fecha, "id": entrada.id}
    ruta = almacen.ruta_proyecciones()
    try:
        r = _tools.get_proyeccion(entrada.id, fecha, desde=entrada.desde)
    except KeyError as e:
        return SalidaProyeccion(**comun, id_servido=None, encontrado=False,
                                citas=[Cita(fuente=FUENTE_PROYECCIONES, id=huella_salida("proyecciones", ruta))],
                                avisos=[_aviso_no_encontrado(e, entrada.id, "proyección")])
    d = r.datos
    filas = [FilaProyeccion(fecha_referencia=_fecha(x.fecha_referencia), fecha_publicacion=_fecha(x.fecha_publicacion),
                            valor=_real(x.valor), horizonte=_real(x.horizonte), edicion=_texto(x.edicion))
             for x in d.itertuples(index=False)]
    ultima = None
    if len(d):
        orden = d.sort_values(["fecha_publicacion", "edicion"], kind="mergesort")
        ultima = _texto(orden["edicion"].iloc[-1])
    ultima_pub = _fecha(d["fecha_publicacion"].max()) if len(d) else None
    return SalidaProyeccion(
        **comun, id_servido=r.serie, encontrado=True, avisos=list(r.avisos),
        citas=[Cita(fuente=FUENTE_PROYECCIONES, id=huella_salida("proyecciones", ruta), fecha_publicacion=ultima_pub)],
        nombre=_texto(_ficha_catalogo(r.serie).get("nombre")), unidad=r.unidad, divisa=r.divisa,
        ultima_edicion=ultima, filas=filas)


# --- get_precios --------------------------------------------------------------------------------
Ticker = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EntradaPrecios(EntradaTool):
    tickers: list[Ticker] = Field(min_length=1, max_length=10, description="Tickers de Yahoo (p. ej. 'SPY', '^GSPC', "
                               "'0001.HK') o de Coinbase con prefijo 'cb:' (p. ej. 'cb:BTC-USD'). Entre 1 y 10.")
    desde: date | None = Field(default=None, description="Primera sesión de la ventana de filas (AAAA-MM-DD).")
    ajuste: Literal["ninguno", "splits", "total"] = Field(
        default="total", description="'total' (splits y dividendos: rentabilidad total), 'splits' o 'ninguno' (as-traded).")
    divisa: Literal["USD", "original"] = Field(default="USD", description="'USD' convierte con el tipo de cambio del "
                                                                         "BCE visible en cada sesión.")
    max_filas: int = Field(default=20, ge=0, le=260, description="Últimas sesiones OHLCV que se devuelven por ticker "
                                                                 "además del resumen (0 = solo el resumen).")


class FilaPrecio(Modelo):
    sesion: date
    fecha_publicacion: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class ResumenPrecios(Modelo):
    """Resumen de un ticker sobre toda su historia visible (reglas en el docstring del módulo); todo en %."""

    ultima_sesion: date
    ultimo_cierre: float | None
    rentabilidad_1m: float | None = Field(description="% frente al cierre de hace 1 mes.")
    rentabilidad_3m: float | None
    rentabilidad_12m: float | None
    volatilidad_3m: float | None = Field(description="Volatilidad anualizada (%) de los rendimientos diarios a 3 meses.")
    caida_desde_maximo_12m: float | None = Field(description="% desde el cierre máximo de 12 meses (<= 0).")
    n_sesiones: int = Field(description="Sesiones en la ventana pedida.")


class PreciosTicker(Modelo):
    ticker: str = Field(description="Ticker pedido.")
    ticker_servido: str | None = Field(default=None, description="Ticker del almacén (si difiere en mayúsculas).")
    encontrado: bool
    mercado: str | None = None
    divisa: str | None = None
    resumen: ResumenPrecios | None = None
    filas: list[FilaPrecio] = Field(default_factory=list)
    filas_omitidas: int = 0


class SalidaPrecios(SalidaTool):
    ajuste: str
    divisa: str
    tickers: list[PreciosTicker]


def _rentabilidad(cierres: pd.Series, meses: int) -> float | None:
    """% del último cierre frente al último cierre ``<=`` hace ``meses`` (índice: sesiones ordenadas)."""
    ultima = cierres.index[-1]
    objetivo = ultima - pd.DateOffset(months=meses)
    previos = cierres[(cierres.index <= objetivo)
                      & (cierres.index >= objetivo - pd.Timedelta(days=TOLERANCIA_PRECIO_DIAS))]
    if previos.empty or previos.iloc[-1] <= 0:
        return None
    return _redondear(100.0 * (float(cierres.iloc[-1]) / float(previos.iloc[-1]) - 1.0))


def resumir_precios(datos: pd.DataFrame, n_sesiones: int) -> ResumenPrecios:
    """Resumen de un ticker a partir de sus filas de get_precios (toda la historia visible, ordenada por sesión)."""
    d = datos.sort_values("sesion", kind="mergesort")
    cierres = pd.Series(d["close"].to_numpy(dtype=float), index=pd.DatetimeIndex(d["sesion"])).dropna()
    cierres = cierres[cierres > 0]
    vacio = {"rentabilidad_1m": None, "rentabilidad_3m": None, "rentabilidad_12m": None, "volatilidad_3m": None,
             "caida_desde_maximo_12m": None}
    if cierres.empty:
        return ResumenPrecios(ultima_sesion=_fecha(d["sesion"].iloc[-1]), ultimo_cierre=None, n_sesiones=n_sesiones,
                              **vacio)
    ultima = cierres.index[-1]
    tres = cierres[cierres.index > ultima - pd.DateOffset(months=3)]
    previo = cierres[cierres.index <= ultima - pd.DateOffset(months=3)].tail(1)
    rend = np.diff(np.log(pd.concat([previo, tres]).to_numpy()))
    cripto = str(d["mercado"].iloc[-1]).upper() == "CRYPTO"
    anual = SESIONES_ANIO_CRIPTO if cripto else SESIONES_ANIO
    vol = 100.0 * float(np.std(rend, ddof=1)) * math.sqrt(anual) if len(rend) >= MIN_RENDIMIENTOS_VOL else None
    maximo = float(cierres[cierres.index >= ultima - pd.DateOffset(months=12)].max())
    return ResumenPrecios(
        ultima_sesion=_fecha(ultima), ultimo_cierre=float(cierres.iloc[-1]), n_sesiones=n_sesiones,
        rentabilidad_1m=_rentabilidad(cierres, 1), rentabilidad_3m=_rentabilidad(cierres, 3),
        rentabilidad_12m=_rentabilidad(cierres, 12), volatilidad_3m=_redondear(vol),
        caida_desde_maximo_12m=_redondear(100.0 * (float(cierres.iloc[-1]) / maximo - 1.0)))


def _proveedor(tk: str) -> str:
    return "coinbase" if tk.startswith(_tools.PREFIJO_COINBASE) else "yahoo"


def _servido(tk: str, guardados: dict[str, list[str]]) -> str:
    """Ticker del almacén para ``tk``: el mismo, o el único que coincide sin distinguir mayúsculas."""
    candidatos = guardados.get(tk.lower(), [])
    return tk if tk in candidatos or len(candidatos) != 1 else candidatos[0]


def _filas_precios(datos: pd.DataFrame, max_filas: int) -> tuple[list[FilaPrecio], int]:
    cola = datos.tail(max_filas) if max_filas else datos.iloc[0:0]
    filas = [FilaPrecio(sesion=_fecha(r.sesion), fecha_publicacion=_fecha(r.fecha_publicacion), open=_real(r.open),
                        high=_real(r.high), low=_real(r.low), close=_real(r.close), volume=_real(r.volume))
             for r in cola.itertuples(index=False)]
    return filas, len(datos) - len(filas)


@registrar("get_precios", EntradaPrecios, agentes=("equity", "portfolio", "risk", "cio"))
def get_precios(entrada: EntradaPrecios, fecha: date) -> SalidaPrecios:
    """Precios de acciones, ETF, índices o cripto conocidos en la fecha de la decisión: por ticker, resumen (rentabilidades, volatilidad, caída desde máximos) y últimas sesiones OHLCV."""
    pedidos = list(dict.fromkeys(entrada.tickers))
    opciones = {"ajuste": entrada.ajuste, "divisa": entrada.divisa}
    por_ticker: dict[str, PreciosTicker] = {}
    avisos: list[str] = []
    citas: list[Cita] = []
    for proveedor in ("yahoo", "coinbase"):
        lista = [t for t in pedidos if _proveedor(t) == proveedor]
        if not lista:
            continue
        guardados: dict[str, list[str]] = {}
        for g in almacen.tickers_guardados(proveedor, curada=True):
            guardados.setdefault(g.lower(), []).append(g)
        servidos = {t: _servido(t, guardados) for t in lista}
        unicos = list(dict.fromkeys(servidos.values()))
        historia = _tools.get_precios(unicos, fecha, proveedor=proveedor, **opciones)
        ventana = historia if entrada.desde is None else _tools.get_precios(
            unicos, fecha, desde=entrada.desde, proveedor=proveedor, **opciones)
        con_datos = set(historia.datos["ticker"])
        # Un ticker sin datos recibe solo el aviso neutro con el nombre pedido (no se revela el del almacén).
        sin_datos = {s for s in unicos if s not in con_datos}
        avisos += [a for a in ventana.avisos if not any(a.startswith(f"{s}: ") for s in sin_datos)]
        for t in lista:
            s = servidos[t]
            if s not in con_datos:
                por_ticker[t] = PreciosTicker(ticker=t, encontrado=False)
                avisos.append(f"{t}: sin sesiones publicadas hasta {fecha.isoformat()} (ticker desconocido o aún sin "
                              f"datos). Usa buscar_series para encontrar el ticker.")
                continue
            h = historia.datos[historia.datos["ticker"] == s]
            w = ventana.datos[ventana.datos["ticker"] == s]
            filas, omitidas = _filas_precios(w, entrada.max_filas)
            ultima = h.iloc[-1]
            por_ticker[t] = PreciosTicker(
                ticker=t, ticker_servido=s if s != t else None, encontrado=True, mercado=_texto(ultima["mercado"]),
                divisa=_texto(ultima["divisa"]), resumen=resumir_precios(h, len(w)), filas=filas,
                filas_omitidas=omitidas)
            ruta = almacen.ruta_precios(proveedor, s, curada=True)
            cita = Cita(fuente=f"{FUENTE_PRECIOS}/{proveedor}/{ruta.name}", id=huella_fichero(ruta),
                        fecha_publicacion=_fecha(h["fecha_publicacion"].max()))
            if cita not in citas:   # dos pedidos que sirven el mismo ticker ('spy' y 'SPY'): una cita
                citas.append(cita)
    return SalidaPrecios(tool="get_precios", fecha_consulta=fecha, citas=citas, avisos=avisos,
                         ajuste=entrada.ajuste, divisa=entrada.divisa, tickers=[por_ticker[t] for t in pedidos])


# --- buscar_series ------------------------------------------------------------------------------
TipoCatalogo = Literal["serie", "precio", "proyeccion"]   # = catalogo_agentes.TIPOS (lo comprueba un test)


def _vocabulario() -> tuple[str, str]:
    """Descripciones de ``tema`` y ``zona`` con el vocabulario real de ``config/catalogo_agentes.yaml`` (temas y
    códigos de ``zona_nombres`` con su primer nombre), para que el LLM vea las opciones en el esquema."""
    try:
        from ingesta.mercados_series import catalogo_agentes as ca   # perezoso, como en buscar_series

        cfg = ca.cargar_config()
        temas = ", ".join(cfg["temas"])
        zonas = ", ".join(f"{c} ({n[0]})" if n else c for c, n in cfg.get("zona_nombres", {}).items())
    except Exception:   # sin el YAML (no debería pasar): descripción genérica, la validación sigue en catalogo_agentes
        temas, zonas = "ver catalogo_agentes.temas()", "código ISO-2 de país o EA, EU, EM, APAC, WLD"
    return (f"Tema del catálogo, uno de: {temas}. También vale escrito libre («tipos de interés»).",
            f"Zona: código ISO-2 de país o agregado; los principales: {zonas}. También vale el nombre "
            f"(«zona euro», «EE. UU.»).")


_DESC_TEMA, _DESC_ZONA = _vocabulario()


class EntradaBuscar(EntradaTool):
    texto: str | None = Field(default=None, description="Palabras de búsqueda en español o inglés (concepto, país, "
                                                        "indicador, ticker...). Sin texto, filtra solo por los campos.")
    tema: str | None = Field(default=None, description=_DESC_TEMA)
    zona: str | None = Field(default=None, description=_DESC_ZONA)
    agente: Agente | None = Field(default=None, description="Solo lo recomendado para este agente.")
    tipo: TipoCatalogo | None = Field(default=None, description="'serie' (get_serie), 'precio' (get_precios) o "
                                                                "'proyeccion' (get_proyeccion).")
    limite: int = Field(default=10, ge=1, le=50, description="Número máximo de resultados.")


class FichaSerie(Modelo):
    id: str = Field(description="Id para get_serie, get_precios o get_proyeccion según el tipo.")
    tipo: str | None = None
    nombre: str | None = None
    descripcion: str | None = None
    tema: str | None = None
    zona: str | None = None
    frecuencia: str | None = None
    unidad: str | None = None
    divisa: str | None = None
    desde: date | None = Field(default=None, description="Primera fecha de referencia (o sesión) con datos ya "
                                                         "publicados en la fecha de la decisión (aprox.).")
    retraso_tipico_dias: float | None = Field(
        default=None, description="Días típicos entre el periodo y su publicación, medidos en los últimos años "
                                  "(orientativo: el de una fecha antigua pudo ser otro).")
    agentes: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    puntuacion: float | None = Field(default=None, description="Relevancia frente al texto buscado (mayor = mejor).")


class SalidaBuscar(SalidaTool):
    n: int = Field(description="Resultados devueltos.")
    fichas: list[FichaSerie]


def _lista(valor: Any, separador: str) -> list[str]:
    """Lista de un campo del catálogo: ya lista, o texto partido por ``separador`` (regex)."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, np.ndarray, pd.Series)):
        return [str(x) for x in valor if _texto(x) is not None]
    if not isinstance(valor, str) and pd.isna(valor):
        return []
    texto = str(valor).strip()
    if not texto:
        return []
    return [p.strip() for p in re.split(separador, texto) if p.strip()]


def _ficha(fila: dict[str, Any]) -> FichaSerie:
    campos = {k: _texto(fila.get(k)) for k in ("tipo", "nombre", "descripcion", "tema", "zona", "frecuencia",
                                               "unidad", "divisa")}
    return FichaSerie(id=str(fila["id"]), **campos, desde=_fecha(fila.get("desde")),
                      retraso_tipico_dias=_real(fila.get("retraso_tipico_dias")),
                      agentes=_lista(fila.get("agentes"), r"[,;|\s]+"),     # catálogo: 'macro|risk'
                      avisos=_lista(fila.get("avisos"), r";\s+"),           # catálogo: 'aviso 1; aviso 2'
                      puntuacion=_real(fila.get("puntuacion")))


@registrar("buscar_series", EntradaBuscar, agentes=("macro", "equity", "risk", "portfolio", "cio"))
def buscar_series(entrada: EntradaBuscar, fecha: date) -> SalidaBuscar:
    """Busca en el catálogo de datos del Tema 1 (series, precios, proyecciones) los ids que encajan con un texto o unos filtros, con su ficha y su puntuación."""
    from ingesta.mercados_series import catalogo_agentes   # perezoso: el paquete no depende de él al importarse

    cita = Cita(fuente=FUENTE_CATALOGO, id=huella_fichero(rutas.ROOT / FUENTE_CATALOGO))
    try:
        tabla = catalogo_agentes.buscar_series(entrada.texto, fecha, tema=entrada.tema, zona=entrada.zona,
                                               agente=entrada.agente, tipo=entrada.tipo, limite=entrada.limite)
    except ValueError as e:
        return SalidaBuscar(tool="buscar_series", fecha_consulta=fecha, citas=[cita], avisos=[str(e)], n=0, fichas=[])
    fichas = [_ficha(f) for f in tabla.head(entrada.limite).to_dict("records")]
    avisos = [] if fichas else ["ningún resultado: prueba con otras palabras o con menos filtros"]
    return SalidaBuscar(tool="buscar_series", fecha_consulta=fecha, citas=[cita], avisos=avisos, n=len(fichas),
                        fichas=fichas)
