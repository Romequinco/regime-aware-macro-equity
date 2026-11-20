"""Base de series del Tema 1 (bloques 2 y 3): une los cargadores, resuelve conflictos y la escribe.

Cargadores (``CARGADORES``), cada uno ya validado contra el contrato y el catálogo:

- ``fase1``       ``data/raw`` de la Fase 1 (``fuentes.fase1.tabla_fase1``): lo que FRED no sirve
                  (yfinance, datahub) y respaldo de las series de FRED.
- ``fred``        FRED como fuente viva (``fuentes.fred.tabla_fred_vivo``): todas las series de FRED del
                  catálogo que no van por ALFRED, con su regla y las excepciones medidas.
- ``academicos``  Ken French, Shiller y Goyal-Welch con vintage por edición ``AAAA-MM`` y la OFR FSI
                  (``fuentes.academicos.tabla_academicos``).
- ``alfred``      vintages exactos de ALFRED de las series ``vintage_exacto`` (``fuentes.alfred.tabla_alfred``).

Una serie, una fuente: si dos cargadores traen el mismo id gana el de mayor ``PRIORIDAD``
(``alfred`` > ``academicos`` > ``fred`` > ``fase1``, el orden de ``catalogo.PRIORIDAD_ORIGENES``; las
derivadas propias se recalculan después). ``data/raw`` solo sirve una serie de FRED si FRED no trae
filas (``ResumenBase.respaldo`` cuenta las fechas que solo tenía la copia descartada). Las copias con
otro id de fuente (estado ``duplicada``) entran con su propio id. Derivadas propias de diferencia
(``deriv:A-B`` con ``id_origen`` ``'A - B'``): si sus dos componentes están en la base se recalculan
con ellos (valor ``A − B`` en las fechas con los dos valores; ``fecha_publicacion`` =
``contrato.fecha_publicacion_derivada``), y se compara con la copia de ``data/raw`` si la hay. Las
demás derivadas (volatilidad realizada) quedan como las fecha su cargador.

Empalme del PIB real de EE. UU. por vintage (``empalmar_pib_real_usa``, id ``EMPALME_PIB_USA``): los
vintages del RTDSM (``philly:ROUTPUT``, PNB real hasta el vintage de 1991-11) hasta el primer vintage de
ALFRED de ``fred:GDPC1`` (1991-12-04, primer vintage con PIB real) y los de ALFRED desde ahí. Un solo
concepto por vintage: desde el corte, toda la vista as-of es PIB (el primer vintage entero se ve en su
publicación y los periodos que solo tenía el PNB se retiran con una fila nula). Cada fila lleva
``NOTA_EMPALME_PIB_USA`` y el tramo (PNB o PIB). Unidad: dólares
constantes de la base de CADA vintage (``unidad_por_vintage``): comparar tasas, no niveles.

Antes de derivar: ``catalogo.aplicar_excepciones`` (fecha = max(regla, primera vintage de ALFRED),
``config/excepciones_publicacion.csv``; solo filas ``unico``, idempotente), así las derivadas heredan
las fechas medidas. Después: ``catalogo.anotar_reconstruidas`` (índices publicados desde
``publicado_desde``) y ``anotar_anomalias`` (picos aislados que se revierten, cierres en fin de semana y
rachas planas: solo se anota la ``nota``, nunca se tocan valores).

``construir_base`` valida la unión (``contrato.validar_series`` + ``catalogo.validar_contra_catalogo``)
y la escribe con ``almacen.escribir_series``: base que solo crece, salvo el ``valor`` de las
revisables con vintage ``unico`` (``revisables``) y, con ``permitir_perdidas``, correcciones propias.
Las series guardadas que ya no se construyen (huérfanas) son un ``ErrorContrato`` salvo
``purgar=True``. ``desde_cero=True`` (cambio de reglas o fuentes, bloque 3) copia antes la base
guardada a ``RESPALDO`` (la primera vez) y la sustituye entera. Cada escritura deja antes la base vigente
en ``<stem>_previa.parquet`` y la previa anterior en ``<stem>_previa_2.parquet`` (rotan: las dos últimas). ``cobertura`` resume la base por serie (solo
metadatos). CLI: ``python -m ingesta.mercados_series construir-base [--sin-red] [--desde-cero]``.

Solo-añadir (paso 3b, ``conservar_revisiones``): las oficiales sin historia de revisiones
(``CARGADORES_SOLO_ANADIR``: BCE, Eurostat, BIS, FMI, Banco Mundial, bancos centrales y curvas) traen solo los
valores de hoy, así que lo guardado es lo único que queda de lo que se sabía antes. Antes de escribir se
compara con la base guardada: una fila guardada que ya no viene se conserva con ``NOTA_VALOR_ANTERIOR``;
una fila nueva que revisa un periodo guardado se ve desde su primera observación (``max(regla, primera
decisión tras la construcción)``, ``NOTA_REVISION_OBSERVADA``), salvo una fecha propia posterior de la
fuente (HICP definitivo del BCE); una versión nueva con el mismo valor que la última guardada nunca queda
antes que ella (``NOTA_MISMO_VALOR``); una clave que vuelve con otro valor (vintage ``unico``, revisión en el
sitio) conserva el guardado. Así la vista as-of de cada fecha es la de entonces y la base no pierde filas.
Se aplica siempre: también desde cero, con ``permitir_perdidas`` y en los ``errores_propios`` declarados
(en esos, además, una fila guardada puede retrasar su fecha: corrección de un fechado propio). Desglose por serie en ``tablas/solo_anadir_ultima.csv``.
OCDE y RTDSM traen todas sus ediciones o vintages (como ALFRED) y no entran.
This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
"""
from __future__ import annotations

import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen
from ingesta.mercados_series import catalogo as cat_mod
from ingesta.mercados_series.contrato import (
    CLAVE_SERIES,
    COLUMNAS_SERIES,
    HUSO_DECISION,
    ErrorContrato,
    fecha_publicacion_derivada,
    primera_decision_vec,
    vacio_series,
    validar_series,
)

TEMA = "mercados_series"
CARGADORES = ("fase1", "philly_rtdsm", "curvas", "bancos_centrales", "oecd", "worldbank", "imf", "bis", "eurostat",
              "bce", "fred", "academicos", "alfred")
# Bloques 4 y 6: cargadores de fuentes oficiales (``catalogo.CARGADOR_POR_FUENTE``). Leen los crudos o las
# tablas ya descargadas en el corpus; las descargas van por la CLI (``descargar-<fuente>``).
CARGADORES_OFICIALES = ("bce", "eurostat", "bis", "imf", "worldbank", "oecd", "bancos_centrales", "curvas",
                        "philly_rtdsm")
# Paso 3b: oficiales SIN historia de revisiones (solo-añadir, ``conservar_revisiones``). Cada descarga trae
# solo los valores de hoy (el BCE, con ``includeHistory``, una versión por observación; el FMI, solo las
# ediciones vigentes del WEO, medido: una en la base; el resto, vintage ``unico``): lo guardado es lo único
# que queda de lo que se sabía antes. Fuera: ``oecd`` (todas las ediciones de ``DF_STES_REVISIONS``, medido:
# 35-331 por serie) y ``philly_rtdsm`` (matrices con todos los vintages del RTDSM), que traen su historia de
# vintages, como ALFRED.
CARGADORES_SOLO_ANADIR = ("bce", "eurostat", "bis", "imf", "worldbank", "bancos_centrales", "curvas")
NOTA_VALOR_ANTERIOR = "valor anterior a una revisión observada el"
NOTA_REVISION_OBSERVADA = ("revisión de un valor ya guardado (fuente sin historia de revisiones): visible desde "
                           "su primera observación, el")
NOTA_MISMO_VALOR = ("versión nueva con el mismo valor que la última guardada (fuente sin historia de revisiones): "
                    "visible desde la guardada, el")
_BLOQUE4 = {"bis": "bis", "imf": "imf_weo", "worldbank": "worldbank"}
# Orden de catalogo.PRIORIDAD_ORIGENES (sin 'derivadas', que no es un cargador: se recalculan tras unir).
PRIORIDAD = {c: i for i, c in enumerate(reversed([o for o in cat_mod.PRIORIDAD_ORIGENES if o in CARGADORES]))}
CARGADOR_DERIVADAS = "derivadas"
EMPALME_PIB_USA = "deriv:PIB_REAL_USA_VINTAGES"
NOTA_EMPALME_PIB_USA = ("empalme por vintage: RTDSM (philly:ROUTPUT) antes del primer vintage de ALFRED de fred:GDPC1 "
                        "y ALFRED desde él; nivel en dólares constantes de la base de cada vintage (comparar tasas)")
TRAMO_PNB = "tramo PNB real (GNP, vintages RTDSM anteriores a 1991-12)"
TRAMO_PIB = "tramo PIB real (GDP, vintages de ALFRED)"
NOTA_RETIRADA_EMPALME = ("sin valor en el primer vintage de ALFRED: el periodo solo existía como PNB del RTDSM y "
                         "se retira en el corte para no mezclar PNB y PIB en un mismo vintage")
RESPALDO = "respaldo_bloque2.parquet"   # copia de la base guardada antes de una reconstrucción desde cero
# Copias rotatorias de la base vigente antes de CADA escritura (paso 3b): la última y la anterior.
SUFIJO_PREVIA = "_previa.parquet"
SUFIJO_PREVIA_2 = "_previa_2.parquet"
FICHERO_SOLO_ANADIR = "solo_anadir_ultima.csv"   # en results/ingesta/mercados_series/tablas/
CUENTAS_SOLO_ANADIR = ("conservadas", "ya_conservadas", "fechadas_observacion", "mismo_valor", "fecha_propia",
                       "guardada_gana_valor", "guardada_gana_nota", "fecha_corregida")
# Fuentes con fecha propia documentada que puede ser ANTERIOR a la guardada (casos 2 y 2c de conservar_revisiones):
# el WEO (PUBLICATION_DATE / UPDATE_DATE de cada edición, fuentes.imf) y el BCE (VALID_FROM de cada versión,
# fuentes.bce). En las demás, una fecha propia solo se respeta si es posterior.
FUENTES_FECHA_PROPIA_ANTERIOR = ("imf_weo", "bce")
TOLERANCIA_DERIVADA = 1e-9
AVISO_FRED = ("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve "
              "Bank of St. Louis.")

__all__ = [
    "CARGADORES", "CARGADORES_OFICIALES", "CARGADORES_SOLO_ANADIR", "NOTA_VALOR_ANTERIOR",
    "NOTA_REVISION_OBSERVADA", "NOTA_MISMO_VALOR", "conservar_revisiones", "escribir_solo_anadir",
    "SUFIJO_PREVIA", "SUFIJO_PREVIA_2", "EMPALME_PIB_USA", "empalmar_pib_real_usa", "tabla_oficial", "PRIORIDAD", "RESPALDO", "ResumenBase", "tablas_fuentes", "unir", "fechas_solo_respaldo",
    "derivar_diferencias",
    "catalogo_efectivo", "construir_base", "cobertura", "escribir_cobertura", "resumen_base",
    "anotar_anomalias", "NOTA_PICO", "NOTA_FIN_DE_SEMANA", "NOTA_RACHA",
]

# Anomalías que se anotan (sin tocar valores): umbrales medidos sobre la base del bloque 2.
NOTA_PICO = "posible dato erróneo de la fuente: pico aislado que se revierte al día siguiente"
NOTA_FIN_DE_SEMANA = "posible error de fecha de la fuente: cierre de mercado en fin de semana"
NOTA_RACHA = "posible dato congelado de la fuente: racha plana de"
UMBRAL_PICO = 0.4            # |Δlog| de ida y de vuelta
UMBRAL_REVERSION = 0.1       # |log(siguiente / anterior)|: el pico no cambia el nivel
MIN_RACHA = 120              # observaciones diarias seguidas con el mismo valor
# Tipos administrados (constantes entre reuniones del FOMC): una racha plana es normal.
SIN_RACHAS = ("fred:IORB", "fred:DPCREDIT", "fred:DFF", "fred:EFFR", "fred:OBFR", "fred:FEDFUNDS",
              # Bloque 4: tipos oficiales del BCE, del Banco de Canadá y del RBA (fecha de efecto).
              "ecb:DFR", "ecb:MRO", "boc:V39079", "rba:FIRMMCRTD")


@dataclass
class ResumenBase:
    """Lo que hizo ``construir_base`` (diccionario con ``como_dict``)."""

    ruta: str | None
    escrita: bool
    n_filas: int
    n_series: int
    n_valores: int
    n_huecos: int
    segundos: float
    por_cargador: dict[str, int] = field(default_factory=dict)
    filas_por_cargador: dict[str, int] = field(default_factory=dict)
    conflictos: dict[str, dict[str, Any]] = field(default_factory=dict)
    derivadas: dict[str, dict[str, Any]] = field(default_factory=dict)
    sin_datos: list[str] = field(default_factory=list)
    excepciones_aplicadas: int = 0
    huerfanas: list[str] = field(default_factory=list)
    purgadas: list[str] = field(default_factory=list)
    revisables: int = 0
    anomalias: dict[str, int] = field(default_factory=dict)
    detalle_anomalias: list[dict[str, str]] = field(default_factory=list, repr=False)
    por_estado: dict[str, int] = field(default_factory=dict)
    por_metodo: dict[str, int] = field(default_factory=dict)
    por_fuente: dict[str, int] = field(default_factory=dict)
    respaldo: dict[str, int] = field(default_factory=dict)
    alfred: dict[str, Any] = field(default_factory=dict)
    desde_cero: bool = False
    copia_previa: str | None = None
    respaldo_desde_cero: str | None = None
    bytes_disco: int | None = None
    solo_anadir: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Cargadores ---------------------------------------------------------------------------------
def tablas_fuentes(*, sin_red: bool = False, cargadores: Iterable[str] = CARGADORES,
                   catalogo: dict[str, dict] | None = None, raiz_fase1: Path | None = None,
                   raiz_crudo_academicos: Path | None = None, cliente_fred: Any = None,
                   cliente_alfred: Any = None, informe_alfred: dict[str, dict] | None = None,
                   registro: Callable[[str], None] | None = None) -> dict[str, pd.DataFrame]:
    """``{cargador: tabla validada}`` de los ``cargadores`` pedidos.

    ``sin_red=True``: FRED y ALFRED solo desde su archivo crudo y los académicos solo con los crudos
    ya descargados (y ``data/raw``). Sin ``sin_red``, FRED vivo baja lo que no tenga hoy en caché
    (incremental), ALFRED las series sin descarga completa archivada y los académicos la edición del
    día si no está archivada (un fallo de red en un académico no para la construcción: queda en su
    ``.meta.json`` y se usa el último crudo). Las descargas largas van antes y por tandas
    (``descargar-alfred``, ``descargar-fred-vivo``). ``informe_alfred``: se rellena con el informe
    por serie de ``fuentes.alfred.tabla_alfred``.
    """
    from ingesta.mercados_series.fuentes import academicos, alfred, fase1, fred

    log = registro or (lambda _m: None)
    pedidos = list(cargadores)
    desconocidos = sorted(set(pedidos) - set(CARGADORES))
    if desconocidos:
        raise ValueError(f"cargadores desconocidos {desconocidos}; válidos: {list(CARGADORES)}")
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    out: dict[str, pd.DataFrame] = {}
    for nombre in pedidos:
        t0 = time.monotonic()
        if nombre == "fase1":
            # Paso 3b: las yf: de data/raw se extienden con el almacén de precios (solape comprobado).
            ext: dict[str, dict] = {}
            out[nombre] = fase1.tabla_fase1(raiz_fase1, cat, extender_precios=True, informe=ext)
            si = sorted(k for k, v in ext.items() if v.get("nuevas"))
            no = {k: v["motivo"] for k, v in sorted(ext.items()) if not v.get("extendida")}
            log(f"  fase1 extendida con el almacén de precios: {len(si)} series, "
                f"{sum(ext[k]['nuevas'] for k in si)} filas; sin extender: {no}")
        elif nombre == "fred":
            out[nombre] = fred.tabla_fred_vivo(sin_red=sin_red, cliente=cliente_fred, cat=cat, registro=log)
        elif nombre in CARGADORES_OFICIALES:
            out[nombre] = tabla_oficial(nombre, sin_red=sin_red, registro=log)
        elif nombre == "alfred":
            out[nombre] = alfred.tabla_alfred(cliente=cliente_alfred, descargar=not sin_red, cat=cat,
                                              informe=informe_alfred if informe_alfred is not None else {})
        else:
            if not sin_red:
                for f in academicos.FUENTES_CATALOGO:
                    for m in academicos.descargar(f, raiz=raiz_crudo_academicos):
                        if m.get("error"):
                            log(f"  aviso: {f} {m.get('clave')}: {m['error']}")
            out[nombre] = academicos.tabla_academicos(catalogo=cat, raiz_crudo=raiz_crudo_academicos,
                                                      raiz_fase1=raiz_fase1)
        log(f"{nombre}: {len(out[nombre])} filas, {out[nombre]['serie'].nunique()} series "
            f"({time.monotonic() - t0:.0f} s)")
    return out


def tabla_oficial(nombre: str, *, sin_red: bool = True, registro: Callable[[str], None] | None = None) -> pd.DataFrame:
    """Tabla validada de un cargador de ``CARGADORES_OFICIALES`` (bloques 4 y 6) desde el corpus.

    ``bce``/``eurostat``: crudos archivados (``sin_red``) o descarga del día. ``bis``/``imf``/``worldbank``:
    ``<corpus>/mercados_series/bloque4/<fuente>.parquet``. ``oecd``: CSV de ediciones archivados.
    ``bancos_centrales``: crudo de cada serie y sus históricos (``bancos_centrales.tabla_serie``).
    ``curvas``: ``series/curvas_b6.parquet`` o los crudos.
    ``philly_rtdsm``: matrices xlsx (solo vintages anteriores al primero de ALFRED). Lo que falta en
    el corpus se omite con aviso (una fuente sin descargar no para la construcción).
    """
    log = registro or (lambda _m: None)
    corpus = almacen.corpus_dir(TEMA)
    partes: list[pd.DataFrame] = []
    if nombre in ("bce", "eurostat"):
        from ingesta.mercados_series.fuentes import bce, eurostat
        tabla = bce.tabla_bce if nombre == "bce" else eurostat.tabla_eurostat
        try:
            partes.append(tabla(sin_red=sin_red)[0])
        except FileNotFoundError as e:   # sin descarga archivada (sin_red): se omite, no para la construcción
            log(f"  aviso: {nombre}: {e} (python -m ingesta.mercados_series descargar-{nombre})")
    elif nombre in _BLOQUE4:
        ruta = corpus / "bloque4" / f"{_BLOQUE4[nombre]}.parquet"
        if ruta.exists():
            partes.append(pd.read_parquet(ruta))
        else:
            log(f"  aviso: {nombre}: falta {ruta} (python -m ingesta.mercados_series descargar-{nombre})")
    elif nombre == "oecd":
        from ingesta.mercados_series.fuentes import oecd
        for area in oecd.AREAS:
            for medida in oecd.MEDIDAS:
                crudo = oecd.cargar_crudo(area, medida)
                if crudo is not None and len(crudo):
                    t = oecd.tabla_oecd(area, medida, crudo)
                    if len(t):
                        partes.append(t)
    elif nombre == "bancos_centrales":
        from ingesta.mercados_series.fuentes import bancos_centrales as bc
        for sid in bc.SERIES:
            t = bc.tabla_serie(sid)   # crudo vigente + históricos congelados (RBA, paso 3b-2)
            if t is not None:
                partes.append(t)
            else:
                log(f"  aviso: bancos_centrales: {sid} sin crudo")
    elif nombre == "curvas":
        ruta = corpus / "series" / "curvas_b6.parquet"
        if ruta.exists():
            partes.append(pd.read_parquet(ruta))
        else:
            from ingesta.mercados_series.fuentes import curvas
            partes.append(curvas.tabla_curvas(registro=log))
    elif nombre == "philly_rtdsm":
        from ingesta.mercados_series.fuentes import philly_rtdsm as ph
        for v in ph.MAPEO:
            ruta = ph._ruta_local(v)
            if ruta.exists():
                t = ph.tabla_philly(v, ruta)
                if len(t):
                    partes.append(t)
    else:
        raise ValueError(f"cargador oficial desconocido {nombre!r}; válidos: {list(CARGADORES_OFICIALES)}")
    partes = [p for p in partes if len(p)]
    if not partes:
        return vacio_series()
    return validar_series(pd.concat(partes, ignore_index=True)[list(COLUMNAS_SERIES)])


# --- Unión --------------------------------------------------------------------------------------
def unir(tablas: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, Any]]]:
    """Une las tablas de los cargadores con una sola fuente por serie.

    Devuelve ``(tabla, cargador_por_serie, conflictos)``. ``conflictos``: por id servido por más
    de un cargador, ``{'cargadores': [...], 'elegido': ...}`` (gana el de mayor ``PRIORIDAD``).
    """
    desconocidos = sorted(set(tablas) - set(PRIORIDAD))
    if desconocidos:
        raise ValueError(f"cargadores desconocidos {desconocidos}; válidos: {list(PRIORIDAD)}")
    servidores: dict[str, list[str]] = {}
    for nombre, t in tablas.items():
        for sid in pd.unique(t["serie"]):
            servidores.setdefault(str(sid), []).append(nombre)
    elegido = {sid: max(c, key=PRIORIDAD.__getitem__) for sid, c in servidores.items()}
    conflictos = {sid: {"cargadores": sorted(c, key=PRIORIDAD.__getitem__), "elegido": elegido[sid]}
                  for sid, c in sorted(servidores.items()) if len(c) > 1}
    partes = []
    for nombre, t in tablas.items():
        propias = [sid for sid, c in elegido.items() if c == nombre]
        if len(t) and propias:
            partes.append(t[t["serie"].isin(propias)])
    tabla = pd.concat(partes, ignore_index=True)[list(COLUMNAS_SERIES)] if partes else vacio_series()
    return tabla, dict(sorted(elegido.items())), conflictos


def fechas_solo_respaldo(tablas: Mapping[str, pd.DataFrame], elegido: Mapping[str, str]) -> dict[str, int]:
    """Por serie servida por varios cargadores: fechas con valor que solo traía un cargador descartado.

    Mide lo que se pierde al servir una serie desde una sola fuente (p. ej. una fecha de ``data/raw``
    que FRED ya no sirve). Solo las series con alguna; sin valores.
    """
    out: dict[str, int] = {}
    grupos = {n: t.loc[t["valor"].notna()].groupby("serie")["fecha_referencia"] for n, t in tablas.items() if len(t)}
    for sid, ganador in elegido.items():
        if ganador not in grupos or sid not in grupos[ganador].groups:
            continue
        propias = set(grupos[ganador].get_group(sid))
        perdidas: set = set()
        for n, g in grupos.items():
            if n != ganador and sid in g.groups:
                perdidas |= set(g.get_group(sid)) - propias
        if perdidas:
            out[sid] = len(perdidas)
    return dict(sorted(out.items()))


def _es_diferencia(sid: str, entrada: dict[str, Any]) -> bool:
    comp = entrada.get("componentes") or []
    return (entrada["metodo"] == "derivada" and len(comp) == 2
            and str(entrada.get("id_origen", "")).replace(" ", "") == f"{comp[0]}-{comp[1]}")


def derivar_diferencias(base: pd.DataFrame, catalogo: dict[str, dict]) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Recalcula las derivadas ``A − B`` del catálogo cuyos componentes están en ``base``.

    Para cada una (estado cargable, ``_es_diferencia``): valor ``A − B`` en las fechas en que
    los dos componentes tienen valor (vintage ``unico``); ``fecha_publicacion`` y
    ``disponible_utc`` con ``contrato.fecha_publicacion_derivada``. Si la derivada ya estaba en
    ``base`` (copia de ``data/raw``), se sustituye y se mide: fechas comunes, valores distintos
    (más de ``TOLERANCIA_DERIVADA``), diferencia máxima, fechas solo en la copia o solo en el
    cálculo y fechas de publicación distintas. Una derivada con algún componente ausente o con
    vintages que no son ``unico`` se deja como estaba (``info['recalculada'] = False``).
    Devuelve ``(base, info)``.
    """
    info: dict[str, dict[str, Any]] = {}
    nuevas, quitar = [], []
    for sid, e in sorted(catalogo.items()):
        if not _es_diferencia(sid, e) or e["estado"] not in cat_mod.ESTADOS_CARGABLES:
            continue
        a, b = e["componentes"]
        comp = base[base["serie"].isin([a, b]) & base["valor"].notna()]
        presentes = set(comp["serie"])
        if presentes != {a, b} or (comp["vintage"] != "unico").any():
            motivo = ("componentes sin datos: " + ", ".join(sorted({a, b} - presentes)) if presentes != {a, b}
                      else "componentes con vintages")
            info[sid] = {"recalculada": False, "motivo": motivo}
            continue
        fechado = fecha_publicacion_derivada(comp, [a, b]).set_index("fecha_referencia")
        va = comp[comp["serie"] == a].set_index("fecha_referencia")["valor"]
        vb = comp[comp["serie"] == b].set_index("fecha_referencia")["valor"]
        valor = (va.reindex(fechado.index) - vb.reindex(fechado.index)).to_numpy()
        nota = cat_mod.NOTA_REVISABLE if e["revisable"] else None
        filas = pd.DataFrame({
            "serie": sid, "fecha_referencia": fechado.index, "fecha_publicacion": fechado["fecha_publicacion"].to_numpy(),
            "disponible_utc": fechado["disponible_utc"].to_numpy(), "vintage": "unico", "valor": valor,
            "unidad": e["unidad"], "divisa": e["divisa"], "fuente": e["fuente"], "metodo_publicacion": e["metodo"],
            "nota": nota,
        })[list(COLUMNAS_SERIES)]
        medida: dict[str, Any] = {"recalculada": True, "componentes": [a, b], "n_filas": int(len(filas)),
                                  "inicio": _iso(filas["fecha_referencia"].min()),
                                  "fin": _iso(filas["fecha_referencia"].max())}
        copia = base[base["serie"] == sid]
        if len(copia):
            c = copia[copia["valor"].notna()].set_index("fecha_referencia")
            f = filas.set_index("fecha_referencia")
            comunes = c.index.intersection(f.index)
            dif = (c.loc[comunes, "valor"] - f.loc[comunes, "valor"]).abs()
            medida["copia_fase1"] = {
                "fechas_comunes": int(len(comunes)),
                "valores_distintos": int((dif > TOLERANCIA_DERIVADA).sum()),
                "dif_max": float(dif.max()) if len(dif) else None,
                "solo_copia": int(len(c.index.difference(f.index))),
                "solo_calculo": int(len(f.index.difference(c.index))),
                "publicacion_distinta": int((c.loc[comunes, "fecha_publicacion"]
                                             != f.loc[comunes, "fecha_publicacion"]).sum()),
            }
            quitar.append(sid)
        info[sid] = medida
        nuevas.append(filas)
    if not nuevas:
        return base, info
    resto = base[~base["serie"].isin(quitar)]
    return pd.concat([resto, *nuevas], ignore_index=True)[list(COLUMNAS_SERIES)], info


def _iso(valor: Any) -> str | None:
    return None if pd.isna(valor) else pd.Timestamp(valor).date().isoformat()


def _anotar(df: pd.DataFrame, mascara: pd.Series, texto: str | pd.Series) -> None:
    """Añade ``texto`` a la ``nota`` de las filas de ``mascara`` (in situ; idempotente por texto)."""
    if not mascara.any():
        return
    t = texto[mascara] if isinstance(texto, pd.Series) else pd.Series(texto, index=df.index[mascara])
    previa = df.loc[mascara, "nota"]
    ya = previa.fillna("").astype(str).str.contains(t.iloc[0].split(":")[0], regex=False)
    nueva = t.where(previa.isna(), previa.astype(str) + "; " + t)
    df.loc[mascara, "nota"] = nueva.where(~ya, previa)


def empalmar_pib_real_usa(base: pd.DataFrame, catalogo: dict[str, dict]) -> tuple[pd.DataFrame, int]:
    """Añade ``EMPALME_PIB_USA`` (si está en el catálogo y están sus dos tramos), con un solo concepto por vintage.

    - Tramo PNB: vintages del RTDSM (``philly:ROUTPUT``) publicados hasta el primer vintage de ALFRED de
      ``fred:GDPC1`` (``corte``, 1991-12-04).
    - Tramo PIB: todo el primer vintage de ALFRED visible desde su publicación (las filas «anterior a
      ALFRED» de ``fred:GDPC1``, que la base fecha con la regla previa, se refechan a la publicación del
      primer vintage) y los vintages exactos posteriores.
    - Los periodos del tramo PNB que el primer vintage de ALFRED no trae (1947-1958) quedan con una fila
      nula (``NOTA_RETIRADA_EMPALME``) en esa misma fecha: desde el corte ninguna vista as-of mezcla PNB y
      PIB; un vintage posterior que los publique como PIB los vuelve a llenar.

    Devuelve ``(base, filas del empalme)``.
    """
    e = catalogo.get(EMPALME_PIB_USA)
    if e is None:
        return base, 0
    base = base[base["serie"] != EMPALME_PIB_USA]
    rt = base[(base["serie"] == "philly:ROUTPUT") & (base["metodo_publicacion"] == "vintage_exacto")]
    gdp = base[base["serie"] == "fred:GDPC1"]
    al = gdp[gdp["metodo_publicacion"] == "vintage_exacto"]
    if rt.empty or al.empty:
        return base, 0
    entrada_gdp = catalogo.get("fred:GDPC1") or {}
    previa = entrada_gdp.get("regla_previa_alfred") or {}
    corte = pd.Timestamp(previa.get("primer_vintage") or al["fecha_publicacion"].min())
    rt = rt[rt["fecha_publicacion"] <= corte].assign(_tramo=TRAMO_PNB)
    # Un solo formato de vintage por serie (contrato): AAAA-MM del RTDSM -> último día de ese mes (su fecha).
    rt["vintage"] = pd.PeriodIndex(rt["vintage"], freq="M").end_time.strftime("%Y-%m-%d")
    al = al[al["fecha_publicacion"] >= corte].assign(_tramo=TRAMO_PIB)
    # Publicación del primer vintage de ALFRED: la de sus filas exactas si las hay; si no, la hora del publicador.
    v0 = corte.strftime("%Y-%m-%d")
    del_v0 = al[al["vintage"] == v0]
    if len(del_v0):
        pub0, disp0 = del_v0["fecha_publicacion"].min(), del_v0["disponible_utc"].min()
    elif entrada_gdp.get("publicador"):
        from ingesta.mercados_series import visibilidad
        from ingesta.mercados_series.contrato import primera_decision_vec
        disp0 = pd.Timestamp(visibilidad.disponible_publicador(entrada_gdp["publicador"], corte))
        pub0 = primera_decision_vec(pd.Series([disp0], dtype="datetime64[ns, UTC]")).iloc[0]
    else:
        pub0, disp0 = corte, pd.NaT
    # Filas «anterior a ALFRED» (valor del primer vintage fechado con la regla previa): al tramo PIB en pub0.
    pre = gdp[(gdp["metodo_publicacion"] != "vintage_exacto")
              & gdp["nota"].fillna("").astype(str).str.contains(cat_mod.NOTA_PREVIA_ALFRED, regex=False)]
    pre = pre[~pre["fecha_referencia"].isin(del_v0["fecha_referencia"])].copy()
    pre["nota"] = ["; ".join(x for x in str(n).split("; ") if not x.startswith(cat_mod.NOTA_PREVIA_ALFRED)) or None
                   for n in pre["nota"]]
    pre = pre.assign(fecha_publicacion=pub0, disponible_utc=disp0, vintage=v0, metodo_publicacion="vintage_exacto",
                     _tramo=TRAMO_PIB)
    # Periodos del PNB sin valor en el primer vintage de ALFRED: se retiran en pub0 (sin mezclar conceptos).
    con_pib = set(pre["fecha_referencia"]) | set(del_v0["fecha_referencia"])
    solo_pnb = sorted(set(rt["fecha_referencia"]) - con_pib)
    ret = pd.DataFrame({"fecha_referencia": pd.to_datetime(solo_pnb), "fecha_publicacion": pub0,
                        "disponible_utc": disp0, "vintage": v0, "valor": np.nan,
                        "metodo_publicacion": "vintage_exacto", "nota": NOTA_RETIRADA_EMPALME, "_tramo": TRAMO_PIB})
    emp = pd.concat([rt, pre, al, ret], ignore_index=True)
    emp["fecha_publicacion"] = emp["fecha_publicacion"].astype("datetime64[ns]")
    emp["disponible_utc"] = pd.to_datetime(emp["disponible_utc"], utc=True)
    previa_nota = emp["nota"].where(emp["nota"].notna(), None)
    emp["nota"] = [f"{NOTA_EMPALME_PIB_USA}; {t}" + (f"; {n}" if isinstance(n, str) and n else "")
                   for t, n in zip(emp["_tramo"], previa_nota)]
    emp = emp.drop(columns="_tramo").assign(serie=EMPALME_PIB_USA, unidad=e["unidad"], divisa=e["divisa"],
                                            fuente=e["fuente"])
    return pd.concat([base, emp[list(COLUMNAS_SERIES)]], ignore_index=True), int(len(emp))


def anotar_anomalias(base: pd.DataFrame, catalogo: dict[str, dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Anota en ``nota`` las anomalías de las diarias de mercado sin tocar valores ni fechas.

    - ``NOTA_PICO`` (solo ``cierre_mercado``): valor que sube o baja más de ``UMBRAL_PICO`` en log
      respecto al anterior y vuelve al día siguiente (en sentido contrario y a menos de ``UMBRAL_REVERSION``
      del anterior): VXDCLS 2,71 entre 14,86 y 15,51 (2021-07-13).
    - ``NOTA_FIN_DE_SEMANA``: fila de una serie ``cierre_mercado`` en sábado o domingo.
    - ``NOTA_RACHA``: ``MIN_RACHA`` o más observaciones diarias seguidas con el mismo valor
      (DED3 0,28 durante 184 días de 2013), salvo tipos administrados (``SIN_RACHAS``) y tipos de
      cambio de H.10 (paridades fijas anteriores a 1973).

    Devuelve ``(base anotada, anomalías)``; ``anomalías``: ``serie, fecha_referencia, tipo``
    (solo fechas, sin valores).
    """
    out = base.copy()
    filas = []
    diarias = [sid for sid, e in catalogo.items() if e["frecuencia"] == "diaria"
               and e["metodo"] in ("cierre_mercado", "calendario")]
    unico = out["vintage"] == "unico"
    for sid in sorted(set(diarias) & set(out["serie"])):
        m = (out["serie"] == sid) & unico & out["valor"].notna()
        g = out.loc[m].sort_values("fecha_referencia")
        if len(g) < 3:
            continue
        v = g["valor"]
        tipos: dict[str, pd.Series] = {}
        mercado = catalogo[sid]["metodo"] == "cierre_mercado"
        # Picos solo en cierres de mercado (índices de volatilidad de Cboe...): en los tipos cerca de cero
        # o en los saltos de fin de mes de la financiación un |Δlog| grande es normal.
        if mercado and (v > 0).all():
            lv = np.log(v.to_numpy(float))
            ida = np.r_[np.nan, np.diff(lv)]
            vuelta = np.r_[np.diff(lv), np.nan]
            nivel = np.r_[np.nan, lv[2:] - lv[:-2], np.nan]
            pico = ((np.abs(ida) > UMBRAL_PICO) & (np.abs(vuelta) > UMBRAL_PICO) & (np.sign(ida) != np.sign(vuelta))
                    & (np.abs(nivel) < UMBRAL_REVERSION))
            tipos["pico"] = pd.Series(pico, index=g.index)
        if catalogo[sid]["metodo"] == "cierre_mercado":
            tipos["fin_de_semana"] = g["fecha_referencia"].dt.weekday >= 5
        if sid not in SIN_RACHAS and catalogo[sid].get("publicador") not in ("fed_h10", "ecb_fx"):   # paridades fijas
            grupo = (v != v.shift()).cumsum()
            largo = grupo.map(grupo.value_counts())
            tipos["racha"] = largo >= MIN_RACHA
            racha_txt = NOTA_RACHA + " " + largo.astype(str) + " observaciones"
        for tipo, mask in tipos.items():
            mask = mask.fillna(False).astype(bool)
            if not mask.any():
                continue
            idx = mask[mask].index
            texto = {"pico": NOTA_PICO, "fin_de_semana": NOTA_FIN_DE_SEMANA}.get(tipo)
            sel = pd.Series(False, index=out.index)
            sel[idx] = True
            _anotar(out, sel, texto if texto else racha_txt.reindex(out.index))
            filas.append(pd.DataFrame({"serie": sid, "fecha_referencia": g.loc[idx, "fecha_referencia"].to_numpy(),
                                       "tipo": tipo}))
    anom = (pd.concat(filas, ignore_index=True) if filas
            else pd.DataFrame({"serie": pd.Series(dtype=object), "fecha_referencia": pd.Series(dtype="datetime64[ns]"),
                               "tipo": pd.Series(dtype=object)}))
    return out, anom


def _anadir_nota(nota: pd.Series, texto: str | pd.Series) -> pd.Series:
    """``nota`` con ``texto`` al final (separado por ``'; '``); una nota nula pasa a ser ``texto``."""
    t = texto if isinstance(texto, pd.Series) else pd.Series(texto, index=nota.index, dtype=object)
    return t.where(nota.isna(), nota.astype(str) + "; " + t)


def _iguales_valor(a: pd.Series, b: pd.Series) -> np.ndarray:
    """Igualdad de ``valor`` elemento a elemento (dos nulos son iguales)."""
    x, y = a.to_numpy(float), b.to_numpy(float)
    return (x == y) | (np.isnan(x) & np.isnan(y))


def conservar_revisiones(tabla: pd.DataFrame, guardado: pd.DataFrame, series: Iterable[str],
                         observado: Any) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Solo-añadir en las ``series`` de fuentes sin historia de revisiones (``CARGADORES_SOLO_ANADIR``).

    Compara la tabla construida con lo guardado (``guardado``: filas de la base guardada) serie a serie:

    1. Fila guardada cuya clave ``(serie, fecha_referencia, vintage)`` ya no viene: se conserva tal cual
       (es lo que se conocía entonces) con ``NOTA_VALOR_ANTERIOR`` y el día de ``observado`` (en Nueva
       York) al final de la nota (una sola vez).
    2. Fila nueva que revisa un periodo guardado (misma ``serie`` y ``fecha_referencia``, otra clave y
       otro valor que el último guardado): ``fecha_publicacion = max(la suya, primera decisión tras
       observado)``, ``disponible_utc`` nulo (como ``catalogo.aplicar_excepciones``) y
       ``NOTA_REVISION_OBSERVADA`` con la fecha de la regla. Excepción: una fecha propia de la fuente
       (``vintage_exacto`` con ``disponible_utc``) distinta de la última guardada del periodo se respeta si es
       posterior (HICP definitivo) y, solo en ``FUENTES_FECHA_PROPIA_ANTERIOR`` (WEO y BCE, con la fecha documentada
       en la fuente), también si es anterior (una edición más antigua que llega después, como las del WEO en el
       3b-2: su fecha es la de su publicación real y la vista as-of de hoy sigue en la guardada, más tardía).
    2b. Fila nueva de un periodo guardado con el MISMO valor que el último guardado (la fuente retira una
       versión y vuelve a dar el valor con otra vintage, fechada con la regla): nunca antes que esa fila,
       ``fecha_publicacion = max(la suya, la de la última guardada)``, ``disponible_utc`` nulo y
       ``NOTA_MISMO_VALOR``. Sin esto, la vista as-of anterior a la revisión vería ya el valor revisado
       (LFSI de 2025-07: 6,3 del 2025-09-10 y 6,4 del 2026-11-19; el BCE retira la versión del 10-30 y da
       6,4 con vintage 2026-12-03 y la regla del 2025-09-10). En todos los casos 2 y 2b la fila nueva
       queda en o después de la menor ``fecha_publicacion`` guardada con su valor; con la misma fecha,
       gana la vintage mayor (``timegate.as_of_series``), que tiene el mismo valor.
    2c. Fila nueva con fecha propia documentada (``vintage_exacto`` con ``disponible_utc`` de una fuente de
       ``FUENTES_FECHA_PROPIA_ANTERIOR``) anterior a la última guardada y con su mismo valor (una edición antigua
       del WEO que no cambió ese año): se queda con su fecha (cuenta en ``fecha_propia``), porque ese valor ya
       era público entonces. En las demás fuentes va por el caso 2b.
    3. Periodos nuevos: con su regla, sin cambios.
    4. Clave que viene con otro valor (vintage ``unico``: la fuente revisa en el sitio; ``guardada_gana_valor``)
       o con el mismo valor y otra nota (``guardada_gana_nota``), o fila ya marcada por esta función: gana la
       guardada (sin la revisión en la base, nada se ve antes de existir). Con otra nota, la bandera de la fuente
       queda CONGELADA en la de la primera descarga: si Eurostat quita la «e» de estimado de un periodo (refresco
       del 3b-2), la base sigue diciendo «estimado»; lo guardado se respeta y el cambio solo se cuenta.

    Devuelve ``(tabla, info, previsto)``: ``info`` con los recuentos (sin valores) y ``previsto``, las
    filas guardadas de las series cuya nota cambia con la nota que llevarán (``construir_base`` hace con
    ellas la comprobación de ``almacen.escribir_series`` antes de reescribirlas). Idempotente.
    """
    obs = pd.Timestamp(observado)
    obs = obs.tz_localize("UTC") if obs.tzinfo is None else obs.tz_convert("UTC")
    decision = primera_decision_vec(pd.Series([obs], dtype="datetime64[ns, UTC]")).iloc[0]
    dia = obs.tz_convert(HUSO_DECISION).date().isoformat()
    ids = sorted(set(series) & set(guardado["serie"]) & set(tabla["serie"]))
    info: dict[str, Any] = {"observado": dia, "primera_decision": _iso(decision), "series": len(ids),
                            **{k: 0 for k in CUENTAS_SOLO_ANADIR if k != "fecha_corregida"}, "por_serie": {}}
    vacio = guardado.iloc[:0]
    if not ids:
        return tabla, info, vacio
    clave = list(CLAVE_SERIES)
    en = tabla["serie"].isin(ids)
    nuevo = tabla[en].reset_index(drop=True)
    g = guardado[guardado["serie"].isin(ids)].reset_index(drop=True)[list(COLUMNAS_SERIES)]
    pos_g = nuevo[clave].merge(g[clave].assign(_g=np.arange(len(g))), on=clave, how="left")["_g"]
    comun = pos_g.notna().to_numpy()
    gi = pos_g[comun].astype(int).to_numpy()
    nota_g = g["nota"].fillna("").astype(str)
    marcada = (nota_g.str.contains(NOTA_VALOR_ANTERIOR, regex=False)
               | nota_g.str.contains(NOTA_REVISION_OBSERVADA, regex=False)
               | nota_g.str.contains(NOTA_MISMO_VALOR, regex=False)).to_numpy()
    distinto = ~_iguales_valor(nuevo.loc[comun, "valor"], g["valor"].iloc[gi])
    # Misma clave y mismo valor con otra nota: la fuente cambia la bandera en el sitio (Eurostat quita la «e» de
    # estimado en el refresco del 3b-2): gana la guardada, como con otro valor (caso 4).
    otra_nota = nuevo.loc[comun, "nota"].fillna("").astype(str).to_numpy() != nota_g.to_numpy()[gi]
    gana = distinto | otra_nota | marcada[gi]
    usar_g = gi[gana]                                      # clave común: la fila guardada
    quitar_n = np.flatnonzero(comun)[gana]
    # Revisiones con clave nueva de un periodo ya guardado.
    sola = ~comun
    # La última guardada de cada periodo es la que ve hoy la vista as-of (mayor fecha y, con empate, vintage).
    ultima = (g.sort_values(["serie", "fecha_referencia", "fecha_publicacion", "vintage"], kind="mergesort")
              .drop_duplicates(["serie", "fecha_referencia"], keep="last")
              [["serie", "fecha_referencia", "valor", "fecha_publicacion"]]
              .rename(columns={"valor": "_v", "fecha_publicacion": "_p"}))
    ref = nuevo.loc[sola, ["serie", "fecha_referencia"]].merge(ultima, on=["serie", "fecha_referencia"], how="left")
    ref.index = nuevo.index[sola]
    revisa = ref["_p"].notna() & ~pd.Series(_iguales_valor(nuevo.loc[sola, "valor"], ref["_v"]), index=ref.index)
    exacta = (nuevo.loc[sola, "metodo_publicacion"] == "vintage_exacto") & nuevo.loc[sola, "disponible_utc"].notna()
    # Una fecha propia ANTERIOR a la guardada solo se respeta en las fuentes que la documentan (casos 2 y 2c).
    exacta_doc = exacta & nuevo.loc[sola, "fuente"].isin(list(FUENTES_FECHA_PROPIA_ANTERIOR))
    fp = nuevo.loc[sola, "fecha_publicacion"]
    propia = (exacta & (fp > ref["_p"])) | (exacta_doc & (fp < ref["_p"]))
    respeta = revisa & propia
    regla = fp
    fechar = revisa & ~propia & (regla < decision)
    # Edición más antigua con fecha propia y el mismo valor (WEO del 3b-2): su fecha, no la de la guardada (caso 2c).
    propia_igual = ref["_p"].notna() & ~revisa & exacta_doc & (regla < ref["_p"])
    idx = fechar[fechar].index
    if len(idx):
        texto = NOTA_REVISION_OBSERVADA + f" {dia} (la regla daba " + regla[idx].dt.strftime("%Y-%m-%d") + ")"
        nuevo.loc[idx, "nota"] = _anadir_nota(nuevo.loc[idx, "nota"], texto)
        nuevo.loc[idx, "fecha_publicacion"] = decision
        nuevo.loc[idx, "disponible_utc"] = pd.NaT
    # Mismo valor que la última guardada con una fecha anterior a ella: desde la guardada (caso 2b).
    mismo = ref["_p"].notna() & ~revisa & ~exacta_doc & (regla < ref["_p"])
    idx_m = mismo[mismo].index
    if len(idx_m):
        texto = (NOTA_MISMO_VALOR + " " + ref.loc[idx_m, "_p"].dt.strftime("%Y-%m-%d") + " (la regla daba "
                 + regla[idx_m].dt.strftime("%Y-%m-%d") + ")")
        nuevo.loc[idx_m, "nota"] = _anadir_nota(nuevo.loc[idx_m, "nota"], texto)
        nuevo.loc[idx_m, "fecha_publicacion"] = ref.loc[idx_m, "_p"]
        nuevo.loc[idx_m, "disponible_utc"] = pd.NaT
    # Filas guardadas que ya no vienen: se conservan con su nota (una vez).
    viene = g[clave].merge(nuevo[clave].assign(_n=True), on=clave, how="left")["_n"].notna().to_numpy()
    cons = g[~viene].copy()
    ya = cons["nota"].fillna("").astype(str).str.contains(NOTA_VALOR_ANTERIOR, regex=False)
    nuevas_cons = cons.index[~ya]
    cons.loc[nuevas_cons, "nota"] = _anadir_nota(cons.loc[nuevas_cons, "nota"], f"{NOTA_VALOR_ANTERIOR} {dia}")
    partes = [tabla[~en], nuevo.drop(index=quitar_n), g.iloc[usar_g], cons]
    out = pd.concat([p for p in partes if len(p)], ignore_index=True)[list(COLUMNAS_SERIES)]
    # Lo guardado de las series con notas nuevas, con la nota que llevará (comprobación antes de escribir).
    previsto = g[g["serie"].isin(set(cons.loc[nuevas_cons, "serie"]))].copy()
    previsto.loc[nuevas_cons, "nota"] = cons.loc[nuevas_cons, "nota"]     # cons conserva el índice de g
    cuentas = {
        "conservadas": cons.loc[nuevas_cons, "serie"], "ya_conservadas": cons.loc[ya[ya].index, "serie"],
        "fechadas_observacion": nuevo.loc[idx, "serie"], "mismo_valor": nuevo.loc[idx_m, "serie"],
        "fecha_propia": nuevo.loc[respeta[respeta].index.union(propia_igual[propia_igual].index), "serie"],
        "guardada_gana_valor": g["serie"].iloc[gi[distinto]],
        "guardada_gana_nota": g["serie"].iloc[gi[otra_nota & ~distinto]],
    }
    por_serie: dict[str, dict[str, int]] = {}
    for k, s in cuentas.items():
        info[k] = int(len(s))
        for sid, n in s.value_counts().items():
            por_serie.setdefault(str(sid), {})[k] = int(n)
    info["por_serie"] = dict(sorted(por_serie.items()))
    return out, info, previsto


def _comprobar_solo_crece(previsto: pd.DataFrame, nuevo: pd.DataFrame, revisables: Iterable[str]) -> None:
    """La comprobación de ``almacen.escribir_series`` contra ``previsto`` (lo guardado con sus notas nuevas).

    Las series de ``previsto`` se reescriben enteras (``purgar``) porque su nota cambia una vez; antes se
    comprueba aquí que ninguna fila guardada se pierde ni cambia salvo esa nota. ``ErrorContrato`` si no.
    """
    rev = set(revisables)
    fijas = previsto[~previsto["serie"].isin(rev)]
    problemas = almacen._perdidas_series(fijas, nuevo) if len(fijas) else []
    revisadas = previsto[previsto["serie"].isin(rev)]
    if len(revisadas):
        sin_valor = tuple(c for c in almacen.VIGILADAS_SERIES if c != "valor")
        problemas += [f"revisables: {p}" for p in almacen._cambios(revisadas, nuevo, list(CLAVE_SERIES), sin_valor)]
    if problemas:
        raise ErrorContrato("series", problemas)


def _comprobar_correccion(guardado: pd.DataFrame, nuevo: pd.DataFrame) -> dict[str, int]:
    """Corrección de un error propio de fechado declarado: ``guardado`` contra ``nuevo`` (mismas series).

    Ninguna clave guardada se pierde, ningún ``valor``, ``unidad``, ``divisa`` ni ``fuente`` cambia y la
    ``fecha_publicacion`` nueva nunca es anterior a la guardada (más tarde no filtra nada). Pueden cambiar la
    fecha (a más tarde), ``disponible_utc``, el método y la nota. Devuelve cuántas filas guardadas cambian
    por serie; ``ErrorContrato`` si no se cumple.
    """
    clave = list(CLAVE_SERIES)
    fijas = tuple(c for c in almacen.VIGILADAS_SERIES
                  if c not in ("fecha_publicacion", "disponible_utc", "metodo_publicacion", "nota"))
    problemas = almacen._cambios(guardado, nuevo, clave, fijas)
    cruce = guardado.merge(nuevo, on=clave, how="inner", suffixes=("", "_n"))
    antes = cruce["fecha_publicacion_n"] < cruce["fecha_publicacion"]
    if antes.any():
        ej = cruce.loc[antes, clave].head(5).astype(str).agg(", ".join, axis=1).tolist()
        problemas.append(f"{int(antes.sum())} filas guardadas adelantarían su fecha_publicacion (p. ej. {ej}): una "
                         f"corrección de fechado solo puede retrasar")
    if problemas:
        raise ErrorContrato("series", [f"errores propios: {p}" for p in problemas])
    cambia = np.zeros(len(cruce), dtype=bool)
    for col in ("fecha_publicacion", "disponible_utc", "metodo_publicacion", "nota"):
        cambia |= ~almacen._iguales(cruce[col], cruce[f"{col}_n"]).to_numpy()
    return {str(k): int(v) for k, v in cruce.loc[cambia, "serie"].value_counts().sort_index().items()}


def _copia_temporal(ruta: Path | None) -> Path | None:
    """Copia de la base vigente junto a ella (``<stem>_previa.tmp``) antes de escribir; None si no hay base."""
    if ruta is None or not Path(ruta).exists():
        return None
    tmp = Path(ruta).with_name(f"{Path(ruta).stem}_previa.tmp")
    shutil.copy2(ruta, tmp)
    return tmp


def _rotar_previas(ruta: Path, temporal: Path) -> Path:
    """Tras una escritura correcta: ``_previa`` pasa a ``_previa_2`` y la copia temporal a ``_previa``."""
    previa = ruta.with_name(f"{ruta.stem}{SUFIJO_PREVIA}")
    if previa.exists():
        previa.replace(ruta.with_name(f"{ruta.stem}{SUFIJO_PREVIA_2}"))
    temporal.replace(previa)
    return previa


def escribir_solo_anadir(info: Mapping[str, Any], ruta: Path | None = None) -> Path:
    """``tablas/solo_anadir_ultima.csv``: el desglose ``solo_anadir`` de la última construcción, por serie.

    Una fila por serie con algún recuento (``CUENTAS_SOLO_ANADIR``) y el día de la observación; solo
    recuentos, sin valores. Sin series afectadas, solo la cabecera.
    """
    if ruta is None:
        carpeta = resultados_dir(TEMA) / "tablas"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / FICHERO_SOLO_ANADIR
    por_serie = dict(info.get("por_serie") or {})
    filas = [{"serie": sid, "observado": info.get("observado"), **{k: int(c.get(k, 0)) for k in CUENTAS_SOLO_ANADIR}}
             for sid, c in sorted(por_serie.items())]
    pd.DataFrame(filas, columns=["serie", "observado", *CUENTAS_SOLO_ANADIR]).to_csv(ruta, index=False,
                                                                                     encoding="utf-8")
    return Path(ruta)


def catalogo_efectivo(catalogo: dict[str, dict]) -> dict[str, dict]:
    """Catálogo para validar la base: ``pendiente_alfred`` con ``vintage_exacto`` cuenta como cargable.

    Es lo que pide ese estado (WEI cargado con todas sus vintages de ALFRED), igual que en
    ``fuentes.fred.tabla_fred_sustitutos``.
    """
    return {sid: (dict(e, estado="activa") if e["estado"] == "pendiente_alfred"
                  and e["metodo"] == "vintage_exacto" else e) for sid, e in catalogo.items()}


# --- Construcción -------------------------------------------------------------------------------
def construir_base(*, sin_red: bool = False, escribir: bool = True, ruta: Path | None = None,
                   permitir_perdidas: bool = False, purgar: bool = False, catalogo: dict[str, dict] | None = None,
                   tablas: Mapping[str, pd.DataFrame] | None = None, raiz_fase1: Path | None = None,
                   raiz_crudo_academicos: Path | None = None, cliente_fred: Any = None,
                   excepciones: pd.DataFrame | None = None, cliente_alfred: Any = None,
                   desde_cero: bool = False, respaldo: str = RESPALDO, observado: Any = None,
                   errores_propios: Iterable[str] = (), registro: Callable[[str], None] | None = None) -> tuple[ResumenBase, pd.DataFrame]:
    """Une ALFRED + FRED vivo + académicos + fase1, resuelve conflictos, valida y (si ``escribir``) guarda.

    ``tablas``: tablas ya cargadas por cargador (tests; sin ellas, ``tablas_fuentes``).
    ``ruta``: parquet de destino (por defecto ``almacen.ruta_series()``, es decir
    ``<corpus>/mercados_series/series/base_series.parquet``). Las revisables con vintage ``unico``
    pueden cambiar de valor (``almacen.escribir_series(revisables=...)``: ediciones académicas
    nuevas); ``permitir_perdidas`` (correcciones propias) deja cambiar cualquier fila. Series
    guardadas que ya no se construyen: ``ErrorContrato`` salvo ``purgar=True`` (se quitan y se
    enumeran en ``resumen.purgadas``). ``excepciones``: tabla de ``catalogo.cargar_excepciones``
    (por defecto, el CSV de config). ``desde_cero`` (reconstrucción tras cambiar reglas o fuentes):
    la primera vez copia la base guardada a ``<carpeta>/<respaldo>`` (si ya existe, se conserva) y la
    sustituye entera, sin comprobar pérdidas ni huérfanas; se niega (``ErrorContrato``) si alguna serie de
    ALFRED no tiene descarga completa archivada, salvo ``permitir_perdidas``. Copia previa: en CADA escritura
    la base vigente pasa a ``<stem>_previa.parquet`` y la previa anterior a ``<stem>_previa_2.parquet`` (como
    mucho las dos últimas; la rotación solo se hace si la escritura sale bien; ``resumen.copia_previa``).
    Solo-añadir (``conservar_revisiones``): en las series de ``CARGADORES_SOLO_ANADIR`` ya guardadas, las
    filas que ya no vienen se conservan y las revisiones se fechan desde ``observado`` (instante en que se
    observa la descarga; por defecto, el inicio de la construcción, lo más conservador a mano). Las series
    con filas conservadas nuevas se reescriben enteras tras comprobar que no pierden ni cambian nada salvo
    esa nota. Se aplica también con ``desde_cero`` (contra la base guardada, antes de sustituirla) y con
    ``permitir_perdidas``: sin ella, una reconstrucción perdería las filas conservadas y devolvería las
    revisiones a la fecha de la regla. Recuentos en ``resumen.solo_anadir`` (``escribir_solo_anadir``).
    ``errores_propios``: ids con un error propio de fechado declarado: pasan por el solo-añadir como las demás
    y, después, sus filas guardadas pueden cambiar de ``fecha_publicacion`` solo a más tarde, de
    ``disponible_utc``, de método o de nota, nunca de clave ni de valor (``_comprobar_correccion``);
    ``permitir_perdidas`` queda para corregir errores propios que no caben ahí.
    Devuelve ``(resumen, tabla validada)``. ``ErrorContrato`` si la unión no cumple el contrato o el
    catálogo, o si la escritura perdería o cambiaría filas guardadas.
    """
    t0 = time.monotonic()
    t_obs = pd.Timestamp.now(tz="UTC")
    log = registro or (lambda _m: None)
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    informe_alfred: dict[str, dict] = {}
    if tablas is None:
        tablas = tablas_fuentes(sin_red=sin_red, catalogo=cat, raiz_fase1=raiz_fase1,
                                raiz_crudo_academicos=raiz_crudo_academicos, cliente_fred=cliente_fred,
                                cliente_alfred=cliente_alfred, informe_alfred=informe_alfred, registro=log)
    union, elegido, conflictos = unir(tablas)
    respaldo_fechas = fechas_solo_respaldo(tablas, elegido)
    union, n_exc = cat_mod.aplicar_excepciones(union, excepciones, catalogo=cat)
    log(f"excepciones de publicación (ALFRED) aplicadas: {n_exc} filas")
    union, derivadas = derivar_diferencias(union, cat)
    union, n_emp = empalmar_pib_real_usa(union, cat)
    if n_emp:
        log(f"empalme del PIB real de EE. UU. por vintage: {n_emp} filas")
        elegido[EMPALME_PIB_USA] = CARGADOR_DERIVADAS  # sin esto, el resumen falla tras escribir la base
    union = cat_mod.anotar_reconstruidas(union, cat)
    union, anomalias = anotar_anomalias(union, cat)
    for sid, d in derivadas.items():
        if d.get("recalculada"):
            elegido[sid] = CARGADOR_DERIVADAS
    tabla = validar_series(union)
    efectivo = catalogo_efectivo(cat)
    cat_mod.validar_contra_catalogo(tabla, efectivo)
    duplicadas = tabla.duplicated(["serie", "fecha_referencia", "vintage"]).sum()
    if duplicadas:   # validar_series ya lo impide; se deja explícito por la unión
        raise ErrorContrato("series", [f"{int(duplicadas)} claves repetidas tras la unión"])
    destino = Path(ruta) if ruta is not None else None
    servidas = set(tabla["serie"])
    # En un ensayo sin ruta no se toca el corpus (ruta_series crea la carpeta): sin huérfanas que mirar.
    ruta_guardada = destino if destino is not None else (almacen.ruta_series() if escribir else None)
    guardadas = (set(almacen.leer_series(ruta=ruta_guardada)["serie"])
                 if ruta_guardada is not None and ruta_guardada.exists() else set())
    huerfanas = sorted(guardadas - servidas)
    from ingesta.mercados_series.fuentes.alfred import AVISO_SIN_ARCHIVO

    sin_archivo = sorted(sid for sid, i in informe_alfred.items()
                         if AVISO_SIN_ARCHIVO in (i.get("avisos") or []))
    if desde_cero and escribir and sin_archivo and not permitir_perdidas:
        # Con un crudo parcial (disco desmontado, descarga a medias) desde cero perdería esas series.
        raise ErrorContrato("series", [f"{len(sin_archivo)} series de ALFRED sin descarga completa archivada: "
                                       f"{sin_archivo[:10]}; desde cero las quitaría de la base. Descárgalas "
                                       f"(descargar-alfred) o fuerza con permitir_perdidas (--reemplazar)"])
    reemplazo = bool(desde_cero and escribir and ruta_guardada is not None and ruta_guardada.exists())
    if huerfanas and escribir and not purgar and not reemplazo:
        raise ErrorContrato("series", [f"{len(huerfanas)} series guardadas ya no se construyen (huérfanas): "
                                       f"{huerfanas[:10]}; get_serie las seguiría sirviendo. Revisa el catálogo "
                                       f"o quítalas con purgar=True (--purgar)"])
    # Solo-añadir (fuentes sin historia de revisiones): lo guardado que ya no viene se conserva y las
    # revisiones se fechan desde su observación. También desde cero y con permitir_perdidas (lo guardado es lo
    # único que queda de lo que se sabía antes), también en los errores_propios declarados.
    errores = set(errores_propios)
    solo_ids = sorted(sid for sid in servidas if elegido.get(sid) in CARGADORES_SOLO_ANADIR and sid in guardadas)
    solo_anadir: dict[str, Any] = {}
    previsto = vacio_series()
    if solo_ids:
        previo = almacen.leer_series(solo_ids, ruta=ruta_guardada, validar=False)
        tabla, solo_anadir, previsto = conservar_revisiones(tabla, previo, solo_ids,
                                                            observado if observado is not None else t_obs)
        tabla = validar_series(tabla)
        cat_mod.validar_contra_catalogo(tabla[tabla["serie"].isin(solo_ids)], efectivo)
        log(f"solo-añadir ({len(solo_ids)} series): {solo_anadir['conservadas']} filas guardadas conservadas "
            f"como valor anterior, {solo_anadir['fechadas_observacion']} revisiones fechadas con su observación, "
            f"{solo_anadir['mismo_valor']} versiones con el mismo valor fechadas desde la guardada, "
            f"{solo_anadir['fecha_propia']} con fecha propia de la fuente, {solo_anadir['guardada_gana_valor']} "
            f"claves con otro valor y {solo_anadir['guardada_gana_nota']} con el mismo valor y otra nota (gana la "
            f"guardada)")
    revisables = sorted(sid for sid in servidas if cat.get(sid, {}).get("revisable")
                        and (tabla.loc[tabla["serie"] == sid, "vintage"] == "unico").all())
    escrita = None
    copia_previa = respaldo_nuevo = None
    if escribir:
        # Series con filas conservadas nuevas: su nota guardada cambia una vez, así que se comprueba aquí que
        # nada se pierde (lo mismo que escribir_series) y se reescriben enteras. Errores propios declarados:
        # claves y valores fijos; la fecha solo puede ir a más tarde (_comprobar_correccion).
        corregidas = sorted(errores & servidas & guardadas)
        if corregidas:
            guardado_err = almacen.leer_series(corregidas, ruta=ruta_guardada, validar=False)
            # Con las notas que el solo-añadir pone a lo conservado (lo único que cambia en esas filas).
            previsto_err = previsto[previsto["serie"].isin(corregidas)]
            if len(previsto_err):
                clave = list(CLAVE_SERIES)
                notas = guardado_err[clave].merge(previsto_err[[*clave, "nota"]], on=clave, how="left")["nota"]
                guardado_err = guardado_err.assign(nota=notas.where(notas.notna(), guardado_err["nota"]).to_numpy())
            n_corr = _comprobar_correccion(guardado_err, tabla[tabla["serie"].isin(corregidas)])
            por_serie = {k: dict(v) for k, v in (solo_anadir.get("por_serie") or {}).items()}
            for sid in corregidas:
                por_serie.setdefault(sid, {})["fecha_corregida"] = n_corr.get(sid, 0)
            solo_anadir = {**solo_anadir, "errores_propios": corregidas,
                           "fecha_corregida": sum(n_corr.values()), "por_serie": dict(sorted(por_serie.items()))}
            log(f"errores propios declarados ({len(corregidas)} series): {sum(n_corr.values())} filas guardadas cambian de "
                f"fecha (solo a más tarde), método o nota; claves y valores sin cambios")
        reescritas = sorted(set(previsto["serie"]) | set(corregidas))
        if len(previsto):
            _comprobar_solo_crece(previsto[~previsto["serie"].isin(corregidas)],
                                  tabla[tabla["serie"].isin(reescritas)], revisables)
        if reemplazo and not ruta_guardada.with_name(respaldo).exists():
            # Respaldo fijo de una reconstrucción desde cero (bloque 2): solo la primera vez.
            respaldo_nuevo = ruta_guardada.with_name(respaldo)
            shutil.copy2(ruta_guardada, respaldo_nuevo)
            log(f"respaldo de la base guardada: {respaldo_nuevo}")
        temporal = _copia_temporal(ruta_guardada)
        # Desde cero: se quitan todas las series guardadas y se escribe la tabla nueva entera.
        quitar = sorted(guardadas) if reemplazo else sorted({*(huerfanas if purgar else ()), *reescritas})
        try:
            escrita = almacen.escribir_series(tabla, destino, permitir_perdidas=permitir_perdidas or reemplazo,
                                              revisables=revisables, purgar=quitar)
        except BaseException:
            if temporal is not None:
                temporal.unlink(missing_ok=True)
            raise
        if temporal is not None:
            copia_previa = str(_rotar_previas(ruta_guardada, temporal))
            log(f"copia previa de la base: {copia_previa} (la anterior, en *{SUFIJO_PREVIA_2})")
        log(f"base escrita en {escrita}" + (f"; purgadas {huerfanas}" if (purgar or reemplazo) and huerfanas else ""))
    cargables = [sid for sid, e in efectivo.items() if e["estado"] in cat_mod.ESTADOS_CARGABLES]
    por_serie = {sid: cat[sid] for sid in servidas if sid in cat}
    resumen = ResumenBase(
        ruta=str(escrita) if escrita is not None else (str(destino) if destino else None),
        escrita=escrita is not None, n_filas=int(len(tabla)), n_series=len(servidas),
        n_valores=int(tabla["valor"].notna().sum()), n_huecos=int(tabla["valor"].isna().sum()),
        segundos=round(time.monotonic() - t0, 1),
        por_cargador=dict(sorted(Counter(elegido[s] for s in servidas).items())),
        filas_por_cargador={k: int(v) for k, v in sorted(
            tabla["serie"].map(elegido).value_counts().items())},
        conflictos=conflictos, derivadas=derivadas,
        sin_datos=sorted(set(cargables) - servidas),
        excepciones_aplicadas=n_exc, huerfanas=huerfanas,
        purgadas=huerfanas if (escribir and (purgar or reemplazo)) else [],
        revisables=len(revisables),
        anomalias={k: int(v) for k, v in anomalias["tipo"].value_counts().sort_index().items()},
        detalle_anomalias=[{"serie": r.serie, "fecha_referencia": _iso(r.fecha_referencia), "tipo": r.tipo}
                           for r in anomalias.itertuples(index=False)],
        por_estado=dict(sorted(Counter(e["estado"] for e in por_serie.values()).items())),
        por_metodo=dict(sorted(Counter(e["metodo"] for e in por_serie.values()).items())),
        por_fuente=dict(sorted(Counter(e["fuente"] for e in por_serie.values()).items())),
        respaldo=respaldo_fechas, alfred=_resumen_alfred(informe_alfred), desde_cero=reemplazo,
        copia_previa=copia_previa, respaldo_desde_cero=str(respaldo_nuevo) if respaldo_nuevo else None, bytes_disco=Path(escrita).stat().st_size if escrita is not None else None,
        solo_anadir=solo_anadir,
    )
    return resumen, tabla


def _resumen_alfred(informe: dict[str, dict]) -> dict[str, Any]:
    """Recuentos del informe por serie de ``fuentes.alfred.tabla_alfred`` (sin valores) y sus avisos
    relevantes (sin archivo, primer vintage distinto del catálogo, filas publicadas antes de su periodo)."""
    if not informe:
        return {}
    suma = {k: int(sum(int(i.get(k) or 0) for i in informe.values()))
            for k in ("filas_alfred", "filas", "previas", "puntos", "retiradas", "fundidas",
                      "proyecciones_visibles", "proyecciones_descartadas")}
    claves = ("sin ", "primer vintage medido")
    avisos = {sid: [a for a in i.get("avisos", []) if a.startswith(claves) or "antes de su fecha" in a]
              for sid, i in sorted(informe.items())}
    return {"series": len(informe), **suma, "avisos": {k: v for k, v in avisos.items() if v}}


# --- Cobertura (solo metadatos) -----------------------------------------------------------------
COLUMNAS_COBERTURA = ("id", "alias", "fuente", "frecuencia", "metodo", "estado", "duplicado_de", "sucesor",
                      "revisable", "inicio", "fin", "n_obs", "n_huecos", "n_vintages", "lag_mediano_dias",
                      "lag_min_dias", "lag_max_dias")


def cobertura(base: pd.DataFrame, catalogo: dict[str, dict] | None = None) -> pd.DataFrame:
    """Una fila por serie de ``base`` con metadatos del catálogo y cobertura medida (sin valores).

    ``inicio``/``fin``: primera y última ``fecha_referencia`` con valor; ``n_obs``: periodos con
    valor; ``n_huecos``: periodos con valor nulo; ``lag_*_dias``: ``fecha_publicacion −
    fecha_referencia`` en días naturales sobre la primera publicación de cada periodo.
    """
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    if base.empty:
        return pd.DataFrame(columns=list(COLUMNAS_COBERTURA))
    orden = base.sort_values(["serie", "fecha_referencia", "fecha_publicacion"], kind="mergesort")
    primera = orden.drop_duplicates(["serie", "fecha_referencia"], keep="first")
    lag = (primera["fecha_publicacion"] - primera["fecha_referencia"]).dt.days
    con_valor = primera["valor"].notna()
    g_lag = lag.groupby(primera["serie"])
    g_val = primera.loc[con_valor].groupby("serie")["fecha_referencia"]
    medidas = pd.DataFrame({
        "inicio": g_val.min(), "fin": g_val.max(), "n_obs": g_val.size(),
        "n_huecos": (~con_valor).groupby(primera["serie"]).sum(),
        "n_vintages": base.groupby("serie")["vintage"].nunique(),
        "lag_mediano_dias": g_lag.median(), "lag_min_dias": g_lag.min(), "lag_max_dias": g_lag.max(),
    })
    filas = []
    for sid, m in medidas.iterrows():
        e = cat.get(sid, {})
        filas.append({
            "id": sid, "alias": " | ".join(e.get("alias") or []), "fuente": e.get("fuente"),
            "frecuencia": e.get("frecuencia"), "metodo": e.get("metodo"), "estado": e.get("estado"),
            "duplicado_de": e.get("duplicado_de"), "sucesor": e.get("sucesor"), "revisable": e.get("revisable"),
            "inicio": _iso(m["inicio"]), "fin": _iso(m["fin"]),
            "n_obs": int(m["n_obs"]) if pd.notna(m["n_obs"]) else 0, "n_huecos": int(m["n_huecos"]),
            "n_vintages": int(m["n_vintages"]), "lag_mediano_dias": float(m["lag_mediano_dias"]),
            "lag_min_dias": int(m["lag_min_dias"]), "lag_max_dias": int(m["lag_max_dias"]),
        })
    out = pd.DataFrame(filas, columns=list(COLUMNAS_COBERTURA))
    return out.sort_values("id", kind="mergesort").reset_index(drop=True)


def escribir_anomalias(detalle: list[dict[str, str]], ruta: Path | None = None) -> Path:
    """``tablas/anomalias_series.csv``: serie, fecha y tipo de cada anomalía anotada (sin valores)."""
    if ruta is None:
        carpeta = resultados_dir(TEMA) / "tablas"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "anomalias_series.csv"
    pd.DataFrame(detalle, columns=["serie", "fecha_referencia", "tipo"]).to_csv(ruta, index=False, encoding="utf-8")
    return Path(ruta)


def escribir_cobertura(cob: pd.DataFrame, ruta: Path | None = None) -> Path:
    """``results/ingesta/mercados_series/tablas/cobertura_series.csv`` (o ``ruta``)."""
    if ruta is None:
        carpeta = resultados_dir(TEMA) / "tablas"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "cobertura_series.csv"
    cob.to_csv(ruta, index=False, encoding="utf-8")
    return Path(ruta)


def resumen_base(base: pd.DataFrame | None = None, catalogo: dict[str, dict] | None = None) -> dict[str, Any]:
    """Recuentos de la base guardada (o de ``base``): filas, series, y series por fuente, método y estado."""
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    t = base if base is not None else almacen.leer_series()
    ids = sorted(set(t["serie"]))
    conteo = {campo: dict(sorted(Counter(str(cat.get(s, {}).get(campo)) for s in ids).items()))
              for campo in ("fuente", "frecuencia", "metodo", "estado")}
    return {"n_filas": int(len(t)), "n_series": len(ids), "n_valores": int(t["valor"].notna().sum()),
            "n_huecos": int(t["valor"].isna().sum()),
            "inicio": _iso(t["fecha_referencia"].min()) if len(t) else None,
            "fin": _iso(t["fecha_referencia"].max()) if len(t) else None,
            "no_catalogadas": [s for s in ids if s not in cat], **conteo}


def _np_a_py(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _np_a_py(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_np_a_py(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    return v
