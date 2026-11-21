"""Inventario del Tema 1 (paso 2 de la descarga completa): una fila por serie y una por fichero de precios.

``python -m ingesta.mercados_series inventario`` escribe en ``results/ingesta/mercados_series/tablas/``
(solo metadatos y medidas, NUNCA valores de las series):

- ``inventario_series.csv``: una fila por serie de la base (``series/base_series.parquet``) con los
  metadatos del catálogo y lo medido en el corpus (``COLUMNAS_SERIES_INV``).
- ``inventario_precios.csv``: una fila por fichero de ``precios/<proveedor>/`` (``COLUMNAS_PRECIOS_INV``).
- ``fiabilidad_c.csv``: cuánto se desvían de la fecha real las reglas de publicación sin verificar (nivel C)
  y algunas verificadas (B) cuando hay con qué compararlas (``tabla_fiabilidad``).
- ``boe_rutas.csv``: qué rutas de la base estadística del Banco de Inglaterra (IADB) permite su ``robots.txt``
  (una sola petición; ``rutas_boe``). La ficha ``fichas/boe.json`` sigue en ``estado_sonda: fallo`` (el esquema común
  ``FichaFuente`` no tiene «bloqueada») y apunta el motivo en ``notas`` y ``mediciones.robots``.

No aplica el filtro del criterio (paso 3): solo mide.

**Nivel de la fecha de publicación** (``nivel_fecha``, D2). Por serie:

- ``A``: tiene un tramo con fecha fiable, que vale desde ``fiable_desde``:
  - fecha exacta de cada dato: filas ``vintage_exacto`` (ALFRED, ediciones del WEO o de la OCDE) o
    ``cierre_mercado``; su primera ``fecha_publicacion`` es ``exacto_desde``;
  - o publicación medida: regla contrastada periodo a periodo con la primera vintage de ALFRED
    (``publicacion_alfred_medida.csv``) y corregida fila a fila con ``config/excepciones_publicacion.csv``
    donde adelantaba; desde ``contrastada_desde`` (``primera_vintage`` de esa tabla; la de la serie equivalente
    si copia su medida; si no, la primera publicación con excepción).
  ``fiable_desde`` = la menor de ``exacto_desde`` y ``contrastada_desde``. Antes de esa fecha la serie se fecha
  con una regla (la ``regla_previa_alfred`` en las ~160 series de ALFRED, la propia en las contrastadas), cuyo
  riesgo mide ``fiabilidad_c.csv``. Sustituye al antiguo umbral de filas medidas (``UMBRAL_MEDIDA``, arbitrario:
  una serie contrastada con pocas excepciones está igual de cubierta que una con muchas).
- ``B``: sin tramo fiable; regla (``calendario``, ``lag_fijo`` o ``fichero``) verificada: ``verificado: true``
  en la entrada del catálogo, en su publicador (``publicaciones.yaml``) o en su retraso (``lags.yaml``).
- ``C``: sin tramo fiable; regla sin verificar en ninguno de los tres sitios.
- ``D``: sin fecha de publicación (método desconocido o todas las ``fecha_publicacion`` nulas).
- ``derivada``: el PEOR nivel de sus ``componentes`` (A < B < C < D; sin componentes conocidos, ``D``) y,
  como ``fiable_desde``, la mayor de las de sus componentes.

**D1 y D2 se miden por separado.** ``desde_2000`` mira cualquier fecha de publicación; ``desde_2000_exacto``
exige que el tramo fiable empiece a tiempo (``fiable_desde <= CORTE_2000``). ``clave_regla`` es la regla que
fecha la serie fuera del tramo fiable (en las de ALFRED, la previa: ``regla_previa``). Veredictos por serie
(de ``fiabilidad_c.csv``): ``veredicto_regla`` (el de ``clave_regla``), ``veredicto_regla_previa`` y
``veredicto_desde_2000``, el riesgo que queda en la ventana desde 2000:

- ``sin riesgo``: fecha exacta o contrastada en toda la ventana (``desde_2000_exacto``);
- el veredicto de su regla, que aplica al tramo anterior a ``fiable_desde`` (o a toda la serie si no tiene);
- ``verificada sin medir`` (B sin comparación), ``exacta`` (A sin regla), ``ver componentes`` (derivadas).

Así se tratan igual una regla B y una C: lo que cuenta es el tramo sin fecha fiable.

**Historia desde 2000** (``desde_2000``, D1): la primera ``fecha_publicacion`` con valor (``pub_desde``),
no la de referencia, es anterior o igual a ``CORTE_2000`` (2001-01-02).

**Proyección** (``es_proyeccion``, D4), si se cumple una de tres:

1. el catálogo la declara previsión (``proyecciones: conservar``: SEP del FOMC);
2. su id lleva ``.PROY.`` (horizontes de previsión del WEO del FMI: ``imf:WEO.DEU.PCPIPCH.PROY.H3``);
3. de forma sistemática (``UMBRAL_PROYECCION``: al menos la mitad de las filas) la ``fecha_referencia`` es
   posterior a la fecha del ``vintage`` en que se publicó (el contrato no deja ``fecha_publicacion <
   fecha_referencia``, así que la marca se mide con el vintage). ``pct_ref_tras_vintage`` da la medida.

**Posible frontera con otro tema** (``posible_frontera``; se cierra con el equipo antes del paso 3):

- ``tema2`` (bancos centrales y riesgo sistémico): fuente del BCE o del BIS (``FUENTES_TEMA2``), el índice de
  estrés de la OFR o una serie del grupo ``estres_financiero`` del catálogo.
- ``tema4`` (noticias y alternativos): ``SKEW``, ``GPR`` o ``EPU`` en el id, un id conocido de sentimiento o
  incertidumbre (``IDS_TEMA4``: Michigan, EPU de FRED…) o, en el nombre, «sentimiento», «confianza del
  consumidor», «incertidumbre» o «geopolít», también en inglés (sentiment, uncertainty, consumer confidence)
  (``_PATRON_TEMA4_ID``, ``_PATRON_TEMA4_NOMBRE``).

**País o zona** (``pais_zona``): el código que lleva el id (ISO-3 en Banco Mundial, WEO y OCDE; ISO-2 en BIS
y Eurostat; agregados como ``EA20`` o ``WLD`` tal cual), el país de la fuente nacional (``PAIS_FUENTE``) o
``None`` si no aplica (tipos de cambio, índices de Yahoo).

**Huecos desde 2000** (``pct_huecos_desde_2000``): periodos sin valor entre el primero y el último con valor
desde 2000-01-01, según la frecuencia del catálogo (días laborables L–V en las diarias, semanas, meses,
trimestres o años). Es una aproximación: en las diarias los festivos cuentan como hueco (~3–4 %).
"""
from __future__ import annotations

import json
import re
import urllib.robotparser
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, catalogo, universo, visibilidad

TEMA = "mercados_series"
CORTE_2000 = pd.Timestamp("2001-01-02")            # D1: primera publicación visible <= esta fecha
INICIO_HUECOS = pd.Timestamp("2000-01-01")
METODOS_EXACTOS = ("vintage_exacto", "cierre_mercado")
METODOS_REGLA = ("calendario", "lag_fijo", "fichero")
NIVELES = ("A", "B", "C", "D")
UMBRAL_PROYECCION = 0.5      # fracción de filas con fecha_referencia > vintage para ser proyección
UMBRAL_APERTURA = 0.95       # fracción de filas con 'open' no nulo para tener apertura
DIAS_DESLISTADO = 30         # último dato más de N días antes del último refresco del proveedor

FUENTES_TEMA2 = ("bce", "bce_curvas", "bis", "ofr_fsi")
GRUPOS_TEMA2 = ("estres_financiero",)
_PATRON_TEMA4_ID = re.compile(r"SKEW|GPR|EPU")
_PATRON_TEMA4_NOMBRE = re.compile(r"sentimiento|confianza del consumidor|incertidumbre|geopol[ií]t|sentiment|"
                                  r"uncertainty|consumer confidence", re.IGNORECASE)
IDS_TEMA4 = frozenset({"fred:UMCSENT", "fred:USEPUINDXD", "fred:USEPUINDXM", "fred:EPUTRADE", "fred:GEPUCURRENT",
                       "fred:CSCICP03USM665S", "yf:^SKEW"})

PAIS_FUENTE = {
    "fred_alfred": "USA", "ust_curva": "USA", "ken_french": "USA", "goyal_welch": "USA", "shiller": "USA",
    "datahub": "USA", "ofr_fsi": "USA", "philly_rtdsm": "USA", "boc": "CAN", "boc_curva": "CAN",
    "boe_curvas": "GBR", "boj": "JPN", "mof_jgb": "JPN", "bundesbank": "DEU", "rba": "AUS",
    "bce_curvas": "EA",
}

# Veredicto de una regla (fiabilidad_c.csv): ver ``veredicto_regla``.
MAX_PCT_ADELANTA = 5.0       # % de comparaciones en que la regla adelanta la fecha real
MAX_ADELANTO_P05 = 1         # días: el percentil 5 del desvío no puede adelantar más de 1 día
MAX_RETRASO_FIABLE = 7       # días: desvío mediano por encima → regla conservadora («con margen»)
MIN_COMPARACIONES = 20       # por debajo, el motivo avisa de muestra pequeña (el veredicto es orientativo)
MAX_ADELANTO_MARGEN = 7      # días: «fiable con margen» no puede adelantar más; por encima, «no fiable»

COLUMNAS_SERIES_INV = (
    "id", "nombre", "fuente", "frecuencia", "unidad", "divisa", "pais_zona",
    "metodo_publicacion", "estado", "verificado", "revisable", "clave_regla", "regla_verificada", "regla_previa",
    "regla_contrastada", "n_vintages", "ref_desde", "ref_hasta", "pub_desde", "desde_2000", "filas",
    "pct_huecos_desde_2000", "nivel_fecha", "pct_filas_regla", "exacto_desde", "contrastada_desde", "fiable_desde",
    "desde_2000_exacto", "veredicto_regla", "veredicto_regla_previa", "veredicto_desde_2000",
    "pct_ref_tras_vintage", "es_proyeccion", "posible_frontera",
)
COLUMNAS_PRECIOS_INV = (
    "ticker", "proveedor", "en_universo", "id_universo", "clase", "bucket", "capa", "mercado", "divisa",
    "equivalente_ucits", "tipo_yahoo", "desde", "hasta", "sesiones", "sesiones_por_anio", "pct_huecos_lv",
    "max_hueco_dias", "volumen_mediano", "volumen_mediano_ultimo_anio", "tiene_apertura", "deslistado",
    "posible_frontera",
)
COLUMNAS_FIABILIDAD = (
    "regla", "tipo_regla", "nivel", "n_series", "n_series_c", "n_series_previa", "n_series_sin_riesgo_2000",
    "n_series_medidas", "comparaciones",
    "n_comparaciones", "n_por_periodo", "pct_adelanta", "pct_retrasa", "pct_igual", "desvio_mediano_dias",
    "desvio_p05_dias", "desvio_p95_dias", "adelanto_p95_dias", "adelanto_max_dias", "veredicto", "motivo",
    "veredicto_desde_2000",
)
COLUMNAS_BOE = ("ruta", "tipo", "formato", "permitida", "uso", "nota")

URL_ROBOTS_BOE = "https://www.bankofengland.co.uk/robots.txt"
MOTIVO_BOE = "bloqueada por robots.txt: sin ruta CSV/XML permitida; solo páginas HTML"
_BOE = "https://www.bankofengland.co.uk"
# Rutas candidatas de la base estadística (IADB) y, como contraste, las de las curvas (ya descargadas).
RUTAS_BOE = (
    ("/boeapps/database/_iadb-FromShowColumns.asp?csv.x=yes&SeriesCodes=IUDBEDR", "csv", "descarga de series (CSV)"),
    ("/boeapps/database/_iadb-FromShowColumns.asp?xml.x=yes&SeriesCodes=IUDBEDR", "xml", "descarga de series (XML)"),
    ("/boeapps/database/fromshowcolumns.asp?Travel=NIxIRx&SeriesCodes=IUDBEDR", "html", "tabla de series (HTML)"),
    ("/boeapps/database/FromShowColumns.asp?Travel=NIxIRx&SeriesCodes=IUDBEDR", "html", "tabla de series (HTML)"),
    ("/boeapps/database/ShowChart.asp?SeriesCodes=IUDBEDR", "html", "gráfico de una serie"),
    ("/boeapps/database/Bank-Rate.asp", "html", "página del Bank Rate"),
    ("/boeapps/database/index.asp", "html", "portada de la base"),
    ("/boeapps/iadb/FromShowColumns.asp?csv.x=yes&SeriesCodes=IUDBEDR", "csv", "ruta antigua de la IADB (CSV)"),
    ("/statistics/yield-curves", "html", "curvas (contraste: ya descargadas)"),
    ("/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip", "zip", "curvas (contraste: ya descargadas)"),
)


# --- Reglas -------------------------------------------------------------------------------------
def regla_verificada(entrada: dict[str, Any], publicadores: dict[str, dict], lags: dict[str, dict]) -> bool:
    """True si la regla de publicación está verificada en la entrada, en su publicador o en su retraso."""
    if entrada.get("verificado") is True:
        return True
    pub = entrada.get("publicador")
    if pub and publicadores.get(pub, {}).get("verificado") is True:
        return True
    clave = entrada.get("lag_clave")
    return bool(clave and lags.get(clave, {}).get("verificado") is True)


def clave_regla(entrada: dict[str, Any], metodo: str | None) -> str | None:
    """Regla que fecha la serie: el publicador (``calendario``) o la clave del retraso (``lag_fijo``,
    ``fichero``); ``<metodo>:<fuente>`` si no tiene ninguno; ``None`` si el método no es una regla.

    En una serie de ALFRED con ``regla_previa_alfred`` (método dominante ``vintage_exacto`` o ``lag_fijo``),
    la clave es la de la regla previa: la que fecha lo publicado antes del primer vintage.
    """
    previa = entrada.get("regla_previa_alfred")
    if previa and metodo in (*METODOS_EXACTOS, "lag_fijo"):
        return previa["lag_clave"]
    if metodo not in METODOS_REGLA:
        return None
    if metodo == "calendario" and entrada.get("publicador"):
        return entrada["publicador"]
    if metodo in ("lag_fijo", "fichero") and entrada.get("lag_clave"):
        return entrada["lag_clave"]
    return entrada.get("publicador") or f"{metodo}:{entrada.get('fuente')}"


def peor_nivel(niveles: Iterable[str]) -> str:
    """El peor de ``niveles`` (A < B < C < D); ``D`` si no hay ninguno."""
    lista = [n for n in niveles if n in NIVELES]
    return max(lista, key=NIVELES.index) if lista else "D"


def nivel_fecha(metodo: str | None, verificada: bool, tramo_fiable: bool = False,
                niveles_componentes: Iterable[str] | None = None) -> str:
    """Nivel A/B/C/D de la fecha de publicación (regla del docstring del módulo).

    ``metodo``: el ``metodo_publicacion`` dominante; ``verificada``: ``regla_verificada``; ``tramo_fiable``:
    la serie tiene filas exactas o una regla contrastada con ALFRED (``fiable_desde`` no nulo);
    ``niveles_componentes``: los de los componentes de una ``derivada``.
    """
    if metodo == "derivada":
        return peor_nivel(niveles_componentes or [])
    if metodo in METODOS_EXACTOS or (tramo_fiable and metodo in METODOS_REGLA):
        return "A"
    if metodo in METODOS_REGLA:
        return "B" if verificada else "C"
    return "D"


def es_proyeccion(sid: str, entrada: dict[str, Any], pct_ref_tras_vintage: float | None) -> bool:
    """Marca de proyección (D4): catálogo (``proyecciones: conservar``), id ``.PROY.`` o referencias
    sistemáticamente posteriores al vintage (``UMBRAL_PROYECCION``)."""
    if entrada.get("proyecciones") == "conservar" or ".PROY." in sid:
        return True
    return pct_ref_tras_vintage is not None and pd.notna(pct_ref_tras_vintage) \
        and pct_ref_tras_vintage >= 100 * UMBRAL_PROYECCION


def posible_frontera(sid: str, entrada: dict[str, Any]) -> str | None:
    """``tema2``, ``tema4``, ``tema2|tema4`` o ``None`` (regla del docstring del módulo)."""
    temas = []
    if entrada.get("fuente") in FUENTES_TEMA2 or entrada.get("grupo") in GRUPOS_TEMA2:
        temas.append("tema2")
    if (sid in IDS_TEMA4 or _PATRON_TEMA4_ID.search(sid.upper())
            or _PATRON_TEMA4_NOMBRE.search(str(entrada.get("nombre") or ""))):
        temas.append("tema4")
    return "|".join(temas) or None


def pais_zona(sid: str, fuente: str | None, componentes: Iterable[str | None] = ()) -> str | None:
    """País o zona de la serie según su id y su fuente (``None`` si no aplica)."""
    prefijo, _, resto = sid.partition(":")
    partes = resto.split(".")
    if fuente == "worldbank" and partes and re.fullmatch(r"[A-Z0-9]{3}", partes[0]):
        return partes[0]
    if fuente == "imf_weo" and len(partes) > 1:
        return partes[1]
    if fuente in ("oecd", "eurostat") and len(partes) > 1:
        return partes[-1]
    if fuente == "bis" and len(partes) > 2:
        return partes[-1] if partes[0] == "WS_EER" else partes[2]
    if fuente == "bce":
        return None if partes[0] == "EXR" else "EA"
    if fuente == "calculo_propio":
        paises = {p for p in componentes}
        return paises.pop() if len(paises) == 1 else None
    return PAIS_FUENTE.get(fuente or "")


# --- Medidas de la base -------------------------------------------------------------------------
_COLUMNAS_BASE = ("serie", "fecha_referencia", "fecha_publicacion", "vintage", "valor", "metodo_publicacion",
                  "nota", "divisa")
_TEXTO_BASE = ["serie", "vintage", "metodo_publicacion", "nota", "divisa"]


def leer_base_medidas(ruta: Path | None = None) -> pd.DataFrame:
    """La base sin valores: ``valor`` se sustituye por ``con_valor`` (bool) al leer.

    Solo las columnas de ``_COLUMNAS_BASE``, las de texto como diccionario (categorías): ~0,4 GB con
    10,5 M filas.
    """
    r = Path(ruta) if ruta is not None else almacen.ruta_series()
    t = pq.read_table(r, columns=list(_COLUMNAS_BASE), read_dictionary=_TEXTO_BASE)
    con_valor = pc.is_valid(t["valor"])
    t = t.drop_columns(["valor"]).append_column("con_valor", con_valor)
    return t.to_pandas()


def _como_categoria(s: pd.Series) -> pd.Series:
    return s if isinstance(s.dtype, pd.CategoricalDtype) else s.astype("category")


def _fechas_vintage(vintages: pd.Series) -> pd.Series:
    """Fecha de cada vintage (``AAAA-MM-DD`` o ``AAAA-MM``: primer día del mes); NaT si no es fecha."""
    cats = _como_categoria(vintages)
    fechas = pd.to_datetime(pd.Series(cats.cat.categories.astype(str)), format="ISO8601", errors="coerce")
    return pd.Series(fechas.to_numpy()[cats.cat.codes.to_numpy()], index=vintages.index).where(cats.notna())


def _ordinal_periodo(fechas: pd.Series, frecuencia: pd.Series) -> pd.Series:
    """Ordinal del periodo de cada fecha según la frecuencia de su fila (NaN si no aplica: fin de semana
    en las diarias o frecuencia desconocida)."""
    dias = (fechas.to_numpy().astype("datetime64[D]").astype("int64")).astype("float64")
    anio = fechas.dt.year.to_numpy().astype("float64")
    mes = fechas.dt.month.to_numpy().astype("float64")
    out = np.full(len(fechas), np.nan)
    f = frecuencia.to_numpy()
    laborable = fechas.dt.dayofweek.to_numpy() < 5
    out = np.where((f == "diaria") & laborable, dias, out)
    out = np.where(f == "semanal", np.floor((dias + 3) / 7), out)        # semanas de lunes a domingo
    out = np.where(f == "mensual", anio * 12 + mes - 1, out)
    out = np.where(f == "trimestral", anio * 4 + (mes - 1) // 3, out)
    out = np.where(f == "anual", anio, out)
    return pd.Series(out, index=fechas.index)


def huecos_desde_2000(base: pd.DataFrame, frecuencias: dict[str, str]) -> pd.Series:
    """% de periodos sin valor entre el primero y el último con valor desde ``INICIO_HUECOS`` (por serie).

    ``base``: ``serie``, ``fecha_referencia`` y ``con_valor``. Diarias: días laborables L–V.
    """
    serie = _como_categoria(base["serie"])
    m = base["con_valor"].to_numpy(dtype=bool) & (base["fecha_referencia"] >= INICIO_HUECOS).to_numpy()
    if not m.any():
        return pd.Series(dtype="float64")
    nombres = serie.cat.categories.astype(str)
    freq_cat = np.array([frecuencias.get(n) or "" for n in nombres], dtype=object)
    codigos = serie.cat.codes.to_numpy()[m]
    ref = base["fecha_referencia"][m].reset_index(drop=True)
    freq = pd.Series(freq_cat[codigos])
    sub = pd.DataFrame({"codigo": codigos, "ref": ref, "orden": _ordinal_periodo(ref, freq)}).dropna(subset=["orden"])
    unicos = sub.drop_duplicates(["codigo", "orden"])
    g = unicos.groupby("codigo")
    n_obs = g.size()
    esperado = (g["orden"].max() - g["orden"].min() + 1).astype("float64")
    diarias = [c for c in n_obs.index if freq_cat[c] == "diaria"]
    if diarias:
        ini = g["ref"].min().loc[diarias].to_numpy().astype("datetime64[D]")
        fin = g["ref"].max().loc[diarias].to_numpy().astype("datetime64[D]")
        esperado.loc[diarias] = np.busday_count(ini, fin + np.timedelta64(1, "D"))
    out = (100 * (1 - n_obs / esperado)).clip(lower=0).round(2)
    out.index = nombres[out.index]
    return out


def medidas_series(base: pd.DataFrame, frecuencias: dict[str, str] | None = None) -> pd.DataFrame:
    """Medidas por serie (sin valores) de una base con ``con_valor`` (``leer_base_medidas``).

    ``ref_desde``/``ref_hasta``/``pub_desde``: sobre las filas con valor. ``metodo_publicacion``: el de más
    filas. ``pct_medida``: fracción de filas con fecha medida (``catalogo.NOTA_EXCEPCION`` en la nota).
    ``pct_filas_regla``: % de filas fechadas con regla. ``exacto_desde``: primera ``fecha_publicacion`` de
    una fila ``vintage_exacto`` o ``cierre_mercado``. ``pct_ref_tras_vintage``: % de filas con ``fecha_referencia`` posterior a la fecha del vintage.
    """
    serie = _como_categoria(base["serie"]).cat.remove_unused_categories()
    nota = _como_categoria(base["nota"])
    cats_med = pd.Series(nota.cat.categories.astype(str)).str.contains(catalogo.NOTA_EXCEPCION, regex=False)
    codigos = nota.cat.codes.to_numpy()
    medida = (np.where(codigos >= 0, cats_med.to_numpy()[np.clip(codigos, 0, None)], False).astype(bool)
              if len(cats_med) else np.zeros(len(base), dtype=bool))
    metodo = _como_categoria(base["metodo_publicacion"])
    exacta = metodo.isin(METODOS_EXACTOS).to_numpy()
    regla = metodo.isin(METODOS_REGLA).to_numpy() & ~medida
    tras = (base["fecha_referencia"] > _fechas_vintage(base["vintage"])).fillna(False).to_numpy(dtype=bool)
    con_valor = base["con_valor"].to_numpy(dtype=bool)
    aux = pd.DataFrame({"serie": serie, "vintage": _como_categoria(base["vintage"]), "metodo": metodo,
                        "medida": medida, "regla": regla, "tras": tras,
                        "ref": base["fecha_referencia"].where(con_valor),
                        "pub": base["fecha_publicacion"].where(con_valor),
                        "pub_exacta": base["fecha_publicacion"].where(exacta)})
    ga = aux.groupby("serie", observed=True)
    dominante = (aux.groupby(["serie", "metodo"], observed=True).size().reset_index(name="n")
                 .sort_values(["serie", "n"], ascending=[True, False], kind="mergesort")
                 .drop_duplicates("serie").set_index("serie")["metodo"].astype(str))
    out = pd.DataFrame({
        "filas": ga.size(),
        "n_vintages": ga["vintage"].nunique(),
        "ref_desde": ga["ref"].min(), "ref_hasta": ga["ref"].max(), "pub_desde": ga["pub"].min(),
        "metodo_publicacion": dominante,
        "pct_medida": ga["medida"].mean(),
        "pct_filas_regla": (100 * ga["regla"].mean()).round(2),
        "exacto_desde": ga["pub_exacta"].min(),
        "pct_ref_tras_vintage": (100 * ga["tras"].mean()).round(2),
    })
    if "divisa" in base:
        div = (pd.DataFrame({"serie": serie, "divisa": _como_categoria(base["divisa"])})
               .groupby(["serie", "divisa"], observed=True).size().reset_index(name="n")
               .sort_values(["serie", "n"], ascending=[True, False], kind="mergesort")
               .drop_duplicates("serie").set_index("serie")["divisa"].astype(str))
        out["divisa_datos"] = div.reindex(out.index)
    del aux
    out.index = out.index.astype(str)
    out["desde_2000"] = out["pub_desde"].le(CORTE_2000).fillna(False).astype(bool)
    if frecuencias is not None:
        out["pct_huecos_desde_2000"] = huecos_desde_2000(base, frecuencias).reindex(out.index)
    return out


def _iso(v: Any) -> str | None:
    return None if v is None or pd.isna(v) else pd.Timestamp(v).date().isoformat()


def contrastadas_desde(medida: pd.DataFrame | None, excepciones: pd.DataFrame | None = None) -> dict[str, Any]:
    """``{serie: contrastada_desde}``: desde cuándo la regla de la serie está contrastada con ALFRED.

    ``medida``: ``publicacion_alfred_medida.csv`` (``primera_vintage``, la fecha de publicación desde la que
    ALFRED tiene fechas reales; si la fila copia la medida de otra serie, ``equivalente``, la de esa). Filas con
    ``error`` fuera. ``excepciones``: ``config/excepciones_publicacion.csv``; para una serie que solo esté ahí,
    su primera ``fecha_publicacion`` con excepción.
    """
    out: dict[str, Any] = {}
    if excepciones is not None and len(excepciones):
        fechas = pd.to_datetime(excepciones["fecha_publicacion"])
        for sid, f in fechas.groupby(excepciones["serie"]).min().items():
            out[str(sid)] = f
    if medida is None or medida.empty:
        return out
    m = medida[medida["error"].isna()] if "error" in medida else medida
    primera = dict(zip(m["serie"], pd.to_datetime(m["primera_vintage"])))
    for _, r in m.iterrows():
        f = primera.get(r["serie"])
        if pd.isna(f) and isinstance(r.get("equivalente"), str):
            f = primera.get(r["equivalente"])
        if f is not None and pd.notna(f):
            out[r["serie"]] = f
    return out


def tabla_inventario_series(medidas: pd.DataFrame, cat: dict[str, dict] | None = None,
                            publicaciones: dict[str, Any] | None = None,
                            lags: dict[str, dict] | None = None,
                            contrastadas: dict[str, Any] | Iterable[str] = ()) -> pd.DataFrame:
    """Une las ``medidas_series`` con el catálogo: una fila por serie (``COLUMNAS_SERIES_INV``).

    ``contrastadas``: ``contrastadas_desde`` (o solo los ids, sin fecha). Las columnas de veredicto quedan
    vacías: las rellena ``anotar_veredictos`` con ``fiabilidad_c.csv``.
    """
    cat = cat if cat is not None else catalogo.cargar_catalogo()
    pubs = (publicaciones if publicaciones is not None else visibilidad.cargar_publicaciones())["publicadores"]
    lags = lags if lags is not None else catalogo.cargar_lags()
    contr = dict(contrastadas) if isinstance(contrastadas, dict) else {s: pd.NaT for s in contrastadas}
    niveles: dict[str, str] = {}
    fiables: dict[str, Any] = {}
    pendientes: list[str] = []
    filas: dict[str, dict] = {}
    for sid, m in medidas.iterrows():
        e = cat.get(sid, {})
        metodo = m["metodo_publicacion"]
        if pd.isna(m["pub_desde"]) and metodo != "derivada":
            metodo = None
        verif = regla_verificada(e, pubs, lags) if metodo in METODOS_REGLA else None
        previa = e.get("regla_previa_alfred")
        if previa and metodo not in ("derivada", None):
            verif = bool(lags.get(previa["lag_clave"], {}).get("verificado"))
        fechas = [pd.Timestamp(f) for f in (m["exacto_desde"], contr.get(sid)) if f is not None and pd.notna(f)]
        fiables[sid] = min(fechas) if fechas else pd.NaT
        filas[sid] = {"metodo": metodo, "verif": verif}
        if metodo == "derivada":
            pendientes.append(sid)
        else:
            niveles[sid] = nivel_fecha(metodo, bool(verif), bool(fechas) or sid in contr)

    def _componente(sid: str, vistos: frozenset = frozenset()) -> tuple[str, Any]:
        if sid in niveles:
            return niveles[sid], fiables.get(sid, pd.NaT)
        e = cat.get(sid)
        if e is None or sid in vistos:
            return "D", pd.NaT
        if e["metodo"] == "derivada":
            partes = [_componente(c, vistos | {sid}) for c in e.get("componentes") or []]
            fechas = [f for _, f in partes]
            fin = max(fechas) if fechas and all(pd.notna(f) for f in fechas) else pd.NaT
            return peor_nivel(n for n, _ in partes), fin
        return nivel_fecha(e["metodo"], regla_verificada(e, pubs, lags)), pd.NaT

    for sid in pendientes:
        niveles[sid], fiables[sid] = _componente(sid)
    salida = []
    for sid, m in medidas.iterrows():
        e = cat.get(sid, {})
        comp = e.get("componentes") or []
        metodo = filas[sid]["metodo"]
        previa = e.get("regla_previa_alfred")
        fiable = fiables[sid]
        salida.append({
            "id": sid, "nombre": e.get("nombre"), "fuente": e.get("fuente"), "frecuencia": e.get("frecuencia"),
            "unidad": e.get("unidad"), "divisa": e.get("divisa") or m.get("divisa_datos"),
            "pais_zona": pais_zona(sid, e.get("fuente"), [pais_zona(c, cat.get(c, {}).get("fuente")) for c in comp]),
            "metodo_publicacion": metodo, "estado": e.get("estado"),
            "verificado": e.get("verificado"), "revisable": e.get("revisable"),
            "clave_regla": clave_regla(e, metodo), "regla_verificada": filas[sid]["verif"],
            "regla_previa": previa["lag_clave"] if previa else None,
            "regla_contrastada": sid in contr, "n_vintages": int(m["n_vintages"]),
            "ref_desde": _iso(m["ref_desde"]), "ref_hasta": _iso(m["ref_hasta"]), "pub_desde": _iso(m["pub_desde"]),
            "desde_2000": bool(m["desde_2000"]), "filas": int(m["filas"]),
            "pct_huecos_desde_2000": m.get("pct_huecos_desde_2000"), "nivel_fecha": niveles[sid],
            "pct_filas_regla": m["pct_filas_regla"], "exacto_desde": _iso(m["exacto_desde"]),
            "contrastada_desde": _iso(contr.get(sid)), "fiable_desde": _iso(fiable),
            "desde_2000_exacto": bool(pd.notna(fiable) and pd.Timestamp(fiable) <= CORTE_2000),
            "veredicto_regla": None, "veredicto_regla_previa": None, "veredicto_desde_2000": None,
            "pct_ref_tras_vintage": m["pct_ref_tras_vintage"],
            "es_proyeccion": es_proyeccion(sid, e, m["pct_ref_tras_vintage"]),
            "posible_frontera": posible_frontera(sid, e),
        })
    out = pd.DataFrame(salida, columns=list(COLUMNAS_SERIES_INV))
    return out.sort_values("id", kind="mergesort").reset_index(drop=True)


def anotar_veredictos(inventario: pd.DataFrame, fiabilidad: pd.DataFrame) -> pd.DataFrame:
    """Rellena ``veredicto_regla``, ``veredicto_regla_previa`` y ``veredicto_desde_2000`` (docstring del módulo)."""
    out = inventario.copy()
    ver = dict(zip(fiabilidad["regla"], fiabilidad["veredicto"]))
    out["veredicto_regla"] = out["clave_regla"].map(ver)
    out["veredicto_regla_previa"] = out["regla_previa"].map(ver)

    def _ventana(f: pd.Series) -> str:
        if f["desde_2000_exacto"]:
            return "sin riesgo"
        if f["metodo_publicacion"] == "derivada":
            return "ver componentes"
        if isinstance(f["veredicto_regla"], str):
            return f["veredicto_regla"]
        if f["nivel_fecha"] == "B":
            return "verificada sin medir"
        if f["nivel_fecha"] == "A":
            return "exacta"
        return "no medible" if f["nivel_fecha"] == "C" else "sin fecha"

    out["veredicto_desde_2000"] = out.apply(_ventana, axis=1)
    return out


# --- Precios ------------------------------------------------------------------------------------
def medidas_precios(df: pd.DataFrame) -> dict[str, Any]:
    """Medidas de un fichero de precios (``sesion``, ``open``, ``close``, ``volume``, ``mercado``, ``divisa``).

    ``sesiones``: filas con cierre. ``pct_huecos_lv``: 1 − sesiones / días L–V entre la primera y la última
    (aproximación: los festivos cuentan como hueco; en cripto, frente a todos los días). ``max_hueco_dias``:
    mayor salto entre sesiones seguidas, en días naturales. Volúmenes: medianas del total y del último año
    hasta la última sesión. ``tiene_apertura``: ``open`` no nulo en >= ``UMBRAL_APERTURA`` de las filas.
    """
    d = df[df["close"].notna()].sort_values("sesion")
    if d.empty:
        return {"desde": None, "hasta": None, "sesiones": 0, "sesiones_por_anio": np.nan, "pct_huecos_lv": np.nan,
                "max_hueco_dias": np.nan, "volumen_mediano": np.nan, "volumen_mediano_ultimo_anio": np.nan,
                "tiene_apertura": False, "mercado_datos": None, "divisa_datos": None, "descargado_max": None}
    ses = pd.to_datetime(d["sesion"])
    desde, hasta = ses.iloc[0], ses.iloc[-1]
    n = len(d)
    anios = max((hasta - desde).days, 1) / 365.25
    cripto = bool((ses.dt.dayofweek >= 5).mean() > 0.2)
    ini, fin = desde.to_datetime64().astype("datetime64[D]"), hasta.to_datetime64().astype("datetime64[D]")
    esperado = (fin - ini).astype(int) + 1 if cripto else int(np.busday_count(ini, fin + np.timedelta64(1, "D")))
    vol = d["volume"]
    ultimo = vol[ses > hasta - pd.Timedelta(days=365)]
    moda = (lambda s: s.dropna().astype(str).mode().iloc[0] if s.notna().any() else None)
    return {
        "desde": _iso(desde), "hasta": _iso(hasta), "sesiones": n, "sesiones_por_anio": round(n / anios, 1),
        "pct_huecos_lv": round(100 * max(0.0, 1 - n / esperado), 2) if esperado else np.nan,
        "max_hueco_dias": int(ses.diff().dt.days.max()) if n > 1 else 0,
        "volumen_mediano": float(vol.median()) if vol.notna().any() else np.nan,
        "volumen_mediano_ultimo_anio": float(ultimo.median()) if ultimo.notna().any() else np.nan,
        "tiene_apertura": bool(df["open"].notna().mean() >= UMBRAL_APERTURA),
        "mercado_datos": moda(d["mercado"]) if "mercado" in d else None,
        "divisa_datos": moda(d["divisa"]) if "divisa" in d else None,
        # Último refresco de ESTE fichero (columna ``descargado``): un refresco parcial (3b-1) no convierte en
        # deslistados a los tickers que no se refrescaron.
        "descargado_max": (_iso(pd.to_datetime(df["descargado"], utc=True).max().tz_localize(None).normalize())
                           if "descargado" in df and df["descargado"].notna().any() else None),
    }


def _tickers_universo(u: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for i in u["instrumentos"]:
        for prov, t in i["tickers"].items():
            out[(prov, t)] = i
    return out


# Metadatos de los lotes de Yahoo, del más antiguo al más reciente (el posterior manda si trae clase).
TABLAS_TIPO_YAHOO = ("yahoo_ampliado.csv", "yahoo_3b1.csv", "yahoo_3b1_altas.csv", "yahoo_3b1_yf.csv",
                     "yahoo_nucleo.csv", "yahoo_3b2_ampliado.csv", "yahoo_3b2_universo.csv")


def _tipo_yahoo(tablas: Path | None = None) -> dict[str, str]:
    """Tipo de Yahoo (``EQUITY``, ``ETF``, ``INDEX``...) de los lotes de ``TABLAS_TIPO_YAHOO``.

    Solo cuentan las filas con ``estado == 'ok'`` y clase no vacía: un refresco fallido (NESN.SW en el
    núcleo del 3b-1) deja la clase vacía y no debe pisar la clase de otro lote (salía ``sin_clase``).
    """
    carpeta = tablas if tablas is not None else resultados_dir(TEMA) / "tablas"
    out: dict[str, str] = {}
    for nombre in TABLAS_TIPO_YAHOO:
        r = carpeta / nombre
        if not r.exists():
            continue
        t = pd.read_csv(r, dtype=str)
        if not {"ticker", "clase"} <= set(t.columns):
            continue
        estado = t["estado"] if "estado" in t else pd.Series("ok", index=t.index)
        clase = t["clase"].fillna("").str.strip()
        t = t[(estado == "ok") & (clase != "")]
        out.update(dict(zip(t["ticker"], clase[t.index])))
    return out


def tabla_inventario_precios(medidas: pd.DataFrame, u: dict[str, Any] | None = None,
                             tipos: dict[str, str] | None = None) -> pd.DataFrame:
    """Una fila por fichero (``COLUMNAS_PRECIOS_INV``) a partir de ``medidas`` (``ticker``, ``proveedor`` y
    ``medidas_precios``). ``deslistado``: última sesión más de ``DIAS_DESLISTADO`` días antes del último
    refresco de ese fichero (``descargado_max``; si falta, la última sesión del proveedor). Paso 3b-1: con un
    refresco parcial, comparar con el proveedor marcaba como deslistado todo lo no refrescado."""
    u = u if u is not None else universo.cargar_universo()
    tipos = tipos if tipos is not None else {}
    mapa = _tickers_universo(u)
    hasta = pd.to_datetime(medidas["hasta"])
    refresco = hasta.groupby(medidas["proveedor"]).transform("max")
    if "descargado_max" in medidas:
        propio = pd.to_datetime(medidas["descargado_max"])
        refresco = propio.where(propio.notna(), refresco)
    filas = []
    for (_, m), h, r in zip(medidas.iterrows(), hasta, refresco):
        t = m["ticker"]
        t_univ = t.split(":", 1)[1] if m["proveedor"] == "coinbase" and ":" in t else t
        i = mapa.get((m["proveedor"], t_univ))
        filas.append({
            "ticker": t, "proveedor": m["proveedor"], "en_universo": i is not None,
            "id_universo": i["id"] if i else None, "clase": i["clase"] if i else None,
            "bucket": i["bucket"] if i else None, "capa": i["capa"] if i else None,
            "mercado": i["mercado"] if i else m.get("mercado_datos"),
            "divisa": i["divisa"] if i else m.get("divisa_datos"),
            "equivalente_ucits": i.get("equivalente_ucits") if i else None, "tipo_yahoo": tipos.get(t),
            **{c: m[c] for c in ("desde", "hasta", "sesiones", "sesiones_por_anio", "pct_huecos_lv",
                                 "max_hueco_dias", "volumen_mediano", "volumen_mediano_ultimo_anio",
                                 "tiene_apertura")},
            "deslistado": bool(pd.notna(h) and (r - h).days > DIAS_DESLISTADO),
            "posible_frontera": "tema4" if _PATRON_TEMA4_ID.search(t.upper()) else None,
        })
    out = pd.DataFrame(filas, columns=list(COLUMNAS_PRECIOS_INV))
    return out.sort_values(["proveedor", "ticker"], kind="mergesort").reset_index(drop=True)


def medir_ficheros_precios(registro: Callable[[str], None] | None = None) -> pd.DataFrame:
    """``medidas_precios`` de todos los ficheros de ``<corpus>/mercados_series/precios/<proveedor>/``."""
    log = registro or (lambda _m: None)
    raiz = almacen.corpus_dir(TEMA) / "precios"
    filas = []
    for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        ficheros = sorted(carpeta.glob("*.parquet"))
        for f in ficheros:
            df = pq.read_table(f, columns=["sesion", "open", "close", "volume", "mercado", "divisa", "descargado"],
                               read_dictionary=["mercado", "divisa"]).to_pandas()
            filas.append({"ticker": almacen.ticker_de_fichero(f.stem), "proveedor": carpeta.name,
                          **medidas_precios(df)})
        log(f"precios/{carpeta.name}: {len(ficheros)} ficheros")
    return pd.DataFrame(filas)


# --- Fiabilidad del nivel C ---------------------------------------------------------------------
def veredicto_regla(n: int, pct_adelanta: float | None, desvio_p05: float | None,
                    desvio_mediano: float | None, adelanto_max: float | None = None) -> tuple[str, str]:
    """``_veredicto`` con aviso de muestra pequeña (``MIN_COMPARACIONES``) en el motivo."""
    veredicto, motivo = _veredicto(n, pct_adelanta, desvio_p05, desvio_mediano, adelanto_max)
    if 0 < n < MIN_COMPARACIONES:
        motivo += f" (muestra pequeña: {n} comparaciones)"
    return veredicto, motivo


def _veredicto(n: int, pct_adelanta: float | None, desvio_p05: float | None,
               desvio_mediano: float | None, adelanto_max: float | None = None) -> tuple[str, str]:
    """Veredicto propuesto de una regla y su motivo. Desvío = fecha de la regla − fecha real (días):
    negativo, la regla ADELANTA el dato (peligroso); positivo, lo RETRASA (conservador).

    - ``no medible``: sin comparaciones.
    - ``no fiable``: adelanta en más del ``MAX_PCT_ADELANTA`` % de los casos o el percentil 5 del desvío
      adelanta más de ``MAX_ADELANTO_P05`` día, o el mayor adelanto medido pasa de ``MAX_ADELANTO_MARGEN``
      días (un margen así ya no es un margen).
    - ``fiable con margen``: adelanta alguna vez (<= 5 % y como mucho ``MAX_ADELANTO_MARGEN`` días: hace falta
      ese margen) o retrasa más de ``MAX_RETRASO_FIABLE`` días en mediana (segura pero pierde frescura).
    - ``fiable``: nunca adelanta y el desvío mediano es <= ``MAX_RETRASO_FIABLE`` días.
    """
    if not n:
        return "no medible", "sin fecha real con la que comparar"
    if pct_adelanta is not None and pct_adelanta > MAX_PCT_ADELANTA:
        return "no fiable", f"adelanta en el {pct_adelanta:.1f} % de los casos (> {MAX_PCT_ADELANTA:g} %)"
    if desvio_p05 is not None and pd.notna(desvio_p05) and desvio_p05 < -MAX_ADELANTO_P05:
        return "no fiable", f"el percentil 5 adelanta {-desvio_p05:g} días (> {MAX_ADELANTO_P05})"
    if adelanto_max is not None and pd.notna(adelanto_max) and adelanto_max > MAX_ADELANTO_MARGEN:
        return "no fiable", (f"adelanta hasta {adelanto_max:g} días (> {MAX_ADELANTO_MARGEN}) en el "
                             f"{pct_adelanta or 0:.1f} % de los casos")
    if pct_adelanta:
        hasta = f" (hasta {adelanto_max:g} días)" if adelanto_max is not None and pd.notna(adelanto_max) else ""
        return "fiable con margen", f"adelanta en el {pct_adelanta:.1f} % de los casos{hasta}"
    if desvio_mediano is not None and pd.notna(desvio_mediano) and desvio_mediano > MAX_RETRASO_FIABLE:
        return "fiable con margen", f"conservadora: retrasa {desvio_mediano:g} días en mediana"
    return "fiable", "no adelanta nunca y el retraso mediano es pequeño"


def comparaciones_previa(base: pd.DataFrame, cat: dict[str, dict]) -> pd.DataFrame:
    """Regla previa de ALFRED (``lag_fijo``) frente a la primera publicación real, periodo a periodo
    (``fuentes.alfred.comparar_con_lag``: sin los periodos del primer vintage ni los rellenos de historia).

    ``base``: filas de ``leer_base_medidas`` (``con_valor`` en lugar de ``valor``). Devuelve ``regla``,
    ``serie``, ``origen`` y ``desvio_dias``.
    """
    from ingesta.mercados_series.fuentes import alfred

    # Solo series con la historia completa de primeras publicaciones (ALFRED). El historial del BCE está recortado:
    # su «primera versión» guardada de un periodo puede ser una revisión posterior (LFSI de 2026, paso 3b-1) y
    # daría adelantos ficticios de meses.
    ids = [s for s, e in cat.items() if e.get("regla_previa_alfred") and e.get("fuente") in catalogo.FUENTES_ALFRED]
    b = base[base["serie"].isin(ids)]
    partes = []
    for sid, g in b.groupby("serie", observed=True, sort=True):
        sid = str(sid)
        t = pd.DataFrame({"serie": sid, "fecha_referencia": g["fecha_referencia"].to_numpy(),
                          "fecha_publicacion": g["fecha_publicacion"].to_numpy(),
                          "vintage": g["vintage"].astype(str).to_numpy(),
                          "valor": np.where(g["con_valor"].to_numpy(), 1.0, np.nan),   # marcador, no valores
                          "metodo_publicacion": g["metodo_publicacion"].astype(str).to_numpy(),
                          "nota": g["nota"].astype(object).where(g["nota"].notna(), None).to_numpy()})
        try:
            det = alfred.comparar_con_lag(sid, t, cat=cat)["detalle"]
        except (KeyError, ValueError, IndexError):
            continue
        if len(det):
            partes.append(pd.DataFrame({"regla": cat[sid]["regla_previa_alfred"]["lag_clave"], "serie": sid,
                                        "origen": "alfred_previa", "desvio_dias": det["dias"].to_numpy()}))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(
        columns=["regla", "serie", "origen", "desvio_dias"])


def comparaciones_ediciones(base: pd.DataFrame, cat: dict[str, dict]) -> pd.DataFrame:
    """Reglas ``fichero`` de las académicas frente a sus ediciones archivadas.

    En cada edición posterior a la primera archivada, el periodo nuevo MÁS RECIENTE se publicó, como muy
    tarde, en la fecha de esa edición (``fecha_publicacion`` de su fila): desvío = regla − edición. Es una
    cota: un adelanto aparente puede venir de una edición intermedia no archivada. Una comparación por
    regla, edición y fecha de la regla (las tablas de un mismo fichero no cuentan varias veces).
    """
    nota = _como_categoria(base["nota"])
    cats = pd.Series(nota.cat.categories.astype(str))
    nuevas = (cats.str.startswith("edición ") & cats.str.endswith("periodo nuevo")).to_numpy()
    codigos = nota.cat.codes.to_numpy()
    m = (np.where(codigos >= 0, nuevas[np.clip(codigos, 0, None)], False).astype(bool) if len(cats)
         else np.zeros(len(base), dtype=bool)) & base["con_valor"].to_numpy(dtype=bool)
    sub = base.loc[m, ["serie", "fecha_referencia", "fecha_publicacion", "vintage"]].copy()
    if sub.empty:
        return pd.DataFrame(columns=["regla", "serie", "origen", "desvio_dias"])
    sub["serie"] = sub["serie"].astype(str)
    sub["vintage"] = sub["vintage"].astype(str)
    ult = sub.sort_values("fecha_referencia").drop_duplicates(["serie", "vintage"], keep="last")
    filas = []
    for _, r in ult.iterrows():
        e = cat.get(r["serie"])
        if not e or e.get("metodo") not in ("fichero", "lag_fijo") or not e.get("lag"):
            continue
        regla = catalogo.fecha_publicacion_regla(pd.Series([r["fecha_referencia"]]), e).iloc[0]
        filas.append({"regla": e["lag_clave"], "serie": r["serie"], "origen": "ediciones",
                      "vintage": r["vintage"], "fecha_regla": regla,
                      "desvio_dias": int((regla - r["fecha_publicacion"]).days)})
    out = pd.DataFrame(filas)
    if out.empty:
        return pd.DataFrame(columns=["regla", "serie", "origen", "desvio_dias"])
    out = out.drop_duplicates(["regla", "vintage", "fecha_regla"])
    return out[["regla", "serie", "origen", "desvio_dias"]].reset_index(drop=True)


def agregados_alfred_medida(medida: pd.DataFrame, cat: dict[str, dict]) -> pd.DataFrame:
    """Reglas de las series ``lag_fijo`` y ``calendario`` de FRED contrastadas con ALFRED
    (``publicacion_alfred_medida.csv``): solo agregados por serie (``n_cubiertas``, ``n_fugas``,
    ``fuga_max_dias``, ``holgura_mediana_dias``). Sin las que copian la medida de otra (``equivalente``)."""
    if medida is None or medida.empty:
        return pd.DataFrame(columns=["regla", "serie", "n", "n_adelanta", "adelanto_max", "desvio_mediano"])
    m = medida[medida["equivalente"].isna() & medida["error"].isna() & medida["n_cubiertas"].fillna(0).gt(0)]
    filas = []
    for _, r in m.iterrows():
        e = cat.get(r["serie"], {})
        clave = clave_regla(e, r["metodo"])
        if clave is None:
            continue
        filas.append({"regla": clave, "serie": r["serie"], "n": int(r["n_cubiertas"]),
                      "n_adelanta": int(r["n_fugas"] or 0), "adelanto_max": float(r["fuga_max_dias"] or 0),
                      "desvio_mediano": r["holgura_mediana_dias"]})
    return pd.DataFrame(filas, columns=["regla", "serie", "n", "n_adelanta", "adelanto_max", "desvio_mediano"])


def tabla_fiabilidad(inventario: pd.DataFrame, cat: dict[str, dict], por_periodo: pd.DataFrame,
                     agregados: pd.DataFrame, publicaciones: dict[str, Any] | None = None,
                     lags: dict[str, dict] | None = None) -> pd.DataFrame:
    """Una fila por regla (``COLUMNAS_FIABILIDAD``): las de las series de nivel C, las reglas previas de
    ALFRED y las verificadas (B) que se pueden medir.

    ``por_periodo``: desvíos periodo a periodo (``comparaciones_previa`` y ``comparaciones_ediciones``);
    ``agregados``: ``agregados_alfred_medida``. ``pct_adelanta`` cuenta todas las comparaciones;
    ``pct_retrasa``, ``pct_igual`` y los percentiles, solo las de ``por_periodo`` (los agregados no los
    traen). ``desvio_mediano_dias``: el de ``por_periodo`` o, si no hay, la mediana de las medianas por
    serie. ``adelanto_p95_dias``: percentil 95 de los adelantos (solo los casos que adelantan): el margen
    que haría falta. ``adelanto_max_dias``: el mayor adelanto medido.

    ``n_series``: series de ``inventario`` fechadas con la regla (``clave_regla``) fuera de su tramo fiable;
    ``n_series_sin_riesgo_2000``: las que tienen fecha exacta o contrastada en toda la ventana desde 2000
    (``desde_2000_exacto``). ``veredicto_desde_2000``: ``sin riesgo desde 2000`` si son todas; si no, el
    ``veredicto`` (que aplica al tramo anterior a ``fiable_desde``). Igual para B que para C.
    """
    pubs = (publicaciones if publicaciones is not None else visibilidad.cargar_publicaciones())["publicadores"]
    lags = lags if lags is not None else catalogo.cargar_lags()
    inv = inventario[inventario["clave_regla"].notna()]
    c_series = inv[inv["nivel_fecha"] == "C"].groupby("clave_regla")["id"].nunique()
    todas = inv.groupby("clave_regla")["id"].nunique()
    exactas = (inv["desde_2000_exacto"] if "desde_2000_exacto" in inv
               else pd.Series(False, index=inv.index)).astype(bool)
    sin_riesgo = inv[exactas].groupby("clave_regla")["id"].nunique()
    previa = pd.Series([e["regla_previa_alfred"]["lag_clave"] for e in cat.values()
                        if e.get("regla_previa_alfred")]).value_counts()
    medidas_reglas = set(por_periodo["regla"]) | set(agregados["regla"])
    reglas = sorted(set(c_series.index) | set(previa.index) | medidas_reglas)
    filas = []
    for r in reglas:
        tipo = "publicador" if r in pubs else ("retraso" if r in lags else "otra")
        verif = (pubs.get(r, {}).get("verificado") if tipo == "publicador"
                 else lags.get(r, {}).get("verificado") if tipo == "retraso" else False)
        d = por_periodo.loc[por_periodo["regla"] == r, "desvio_dias"].astype(float)
        a = agregados[agregados["regla"] == r]
        n_pp, n_ag = len(d), int(a["n"].sum())
        n = n_pp + n_ag
        n_adel = int((d < 0).sum()) + int(a["n_adelanta"].sum())
        pct_adel = round(100 * n_adel / n, 2) if n else None
        adel = -d[d < 0]
        adel_max = max([float(adel.max()) if len(adel) else 0.0, float(a["adelanto_max"].max()) if len(a) else 0.0])
        mediana = float(d.median()) if n_pp else (float(a["desvio_mediano"].median()) if len(a) else None)
        p05 = float(d.quantile(0.05)) if n_pp else None
        veredicto, motivo = veredicto_regla(n, pct_adel, p05, mediana, adel_max)
        n_s, n_ok = int(todas.get(r, 0)), int(sin_riesgo.get(r, 0))
        series_medidas = set(por_periodo.loc[por_periodo["regla"] == r, "serie"]) | set(a["serie"])
        origenes = sorted(set(por_periodo.loc[por_periodo["regla"] == r, "origen"])
                          | ({"alfred_medida"} if len(a) else set()))
        filas.append({
            "regla": r, "tipo_regla": tipo, "nivel": "B" if verif else "C",
            "n_series": n_s, "n_series_c": int(c_series.get(r, 0)), "n_series_previa": int(previa.get(r, 0)),
            "n_series_sin_riesgo_2000": n_ok,
            "n_series_medidas": len(series_medidas), "comparaciones": "; ".join(origenes) or None,
            "n_comparaciones": n, "n_por_periodo": n_pp, "pct_adelanta": pct_adel,
            "pct_retrasa": round(100 * float((d > 0).mean()), 2) if n_pp else None,
            "pct_igual": round(100 * float((d == 0).mean()), 2) if n_pp else None,
            "desvio_mediano_dias": mediana, "desvio_p05_dias": p05,
            "desvio_p95_dias": float(d.quantile(0.95)) if n_pp else None,
            "adelanto_p95_dias": (float(adel.quantile(0.95)) if len(adel) else adel_max) if n else None,
            "adelanto_max_dias": adel_max if n else None, "veredicto": veredicto, "motivo": motivo,
            "veredicto_desde_2000": "sin riesgo desde 2000" if n_s and n_ok == n_s else veredicto,
        })
    return pd.DataFrame(filas, columns=list(COLUMNAS_FIABILIDAD))


# --- Banco de Inglaterra (D6) -------------------------------------------------------------------
def rutas_boe(texto_robots: str) -> pd.DataFrame:
    """Reglas de ``robots.txt`` del BoE que tocan la base estadística y si cada ruta candidata está permitida.

    Las reglas se interpretan con ``urllib.robotparser`` (agente genérico ``*``), que distingue mayúsculas:
    una variante en minúsculas de una ruta vetada que salga «permitida» NO se usa (el servidor no distingue
    mayúsculas y sería esquivar el veto).
    """
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(texto_robots.splitlines())
    filas = []
    agente = None
    for linea in texto_robots.splitlines():
        lin = linea.split("#", 1)[0].strip()
        if ":" not in lin:
            continue
        k, v = (x.strip() for x in lin.split(":", 1))
        if k.lower() == "user-agent":
            agente = v
        elif k.lower() in ("disallow", "allow") and re.search(r"boeapps|iadb|database|statistic", v, re.I):
            filas.append({"ruta": v, "tipo": f"regla {k.lower()} (user-agent {agente})", "formato": None,
                          "permitida": k.lower() == "allow", "uso": None, "nota": None})
    for ruta, formato, nota in RUTAS_BOE:
        filas.append({"ruta": ruta, "tipo": "candidata", "formato": formato,
                      "permitida": bool(rp.can_fetch("*", _BOE + ruta)), "uso": None, "nota": nota})
    return clasificar_rutas_boe(pd.DataFrame(filas, columns=list(COLUMNAS_BOE)))


def clasificar_rutas_boe(rutas: pd.DataFrame) -> pd.DataFrame:
    """Columna ``uso`` de las rutas candidatas (``tipo == "candidata"``) según ``permitida`` y ``formato``:

    - ``vetada``: ``robots.txt`` la prohíbe;
    - ``no se usa (variante de mayúsculas de una ruta vetada)``: el servidor no distingue mayúsculas;
    - ``permitida (CSV/XML): candidata al paso 3b``: descarga de series que el ``robots.txt`` permite;
    - ``permitida solo en HTML``: tabla o página web, no una descarga CSV o XML (decisión del usuario);
    - ``permitida (curvas, ya descargadas)``: contraste.
    """
    out = rutas.copy()
    cand = out["tipo"] == "candidata"
    vetadas = [str(r).lower() for r in out.loc[~cand & ~out["permitida"].astype(bool), "ruta"]]
    usos = []
    for _, f in out[cand].iterrows():
        ruta = str(f["ruta"])
        if not bool(f["permitida"]):
            usos.append("vetada")
        elif any(ruta.lower().startswith(v) and not ruta.startswith(str(v)) for v in vetadas if v):
            usos.append("no se usa (variante de mayúsculas de una ruta vetada)")
        elif "curvas" in str(f["nota"]):
            usos.append("permitida (curvas, ya descargadas)")
        elif f["formato"] in ("csv", "xml"):
            usos.append("permitida (CSV/XML): candidata al paso 3b")
        else:
            usos.append("permitida solo en HTML (no es descarga CSV/XML): decisión del usuario")
    out.loc[cand, "uso"] = usos
    return out


def consultar_boe(transporte: Callable[[str], str] | None = None) -> str:
    """UNA petición a ``URL_ROBOTS_BOE`` (``ingesta.comun.http.get`` con un solo intento)."""
    if transporte is not None:
        return transporte(URL_ROBOTS_BOE)
    from ingesta.comun import http

    return http.get(URL_ROBOTS_BOE, reintentos=1, timeout=30).text


def actualizar_ficha_boe(rutas: pd.DataFrame, ruta_ficha: Path | None = None, *, hoy: str | None = None) -> Path:
    """Ficha ``fichas/boe.json``: motivo del bloqueo en ``notas`` y ``mediciones.robots`` (``MOTIVO_BOE``).

    ``estado_sonda`` se queda en ``fallo``: ``FichaFuente`` (``comun/esquema.py``, común a los 4 temas) no admite
    «bloqueada», y así ``fuentes.bancos_centrales`` escribe lo mismo. Comprueba que la ficha valida.
    """
    r = Path(ruta_ficha) if ruta_ficha is not None else resultados_dir(TEMA) / "fichas" / "boe.json"
    crudo = r.read_bytes()
    ficha = json.loads(crudo.decode("utf-8"))
    hoy = hoy or pd.Timestamp.today().date().isoformat()
    cand = rutas[rutas["tipo"] == "candidata"]
    uso = cand["uso"].astype(str)
    csv_xml = cand.loc[uso.str.startswith("permitida (CSV/XML)"), "ruta"]
    html = cand.loc[uso.str.startswith("permitida solo en HTML"), "ruta"]
    ficha["estado_sonda"] = "fallo"
    rob = ficha.setdefault("mediciones", {}).setdefault("robots", {})
    rob["consultado"] = hoy
    rob["motivo"] = MOTIVO_BOE if not len(csv_xml) else "robots.txt permite una ruta CSV/XML"
    rob["reglas_base_estadistica"] = [f["ruta"] for _, f in rutas[rutas["tipo"] != "candidata"].iterrows()
                                      if not f["permitida"]]
    rob.pop("rutas_de_series_permitidas", None)
    rob["rutas_csv_xml_permitidas"] = list(csv_xml)
    rob["rutas_html_permitidas"] = list(html)
    nota = (f"robots.txt consultado el {hoy} (paso 2, D6): "
            + (f"descarga CSV/XML permitida en {', '.join(csv_xml)}: se descarga en el paso 3b" if len(csv_xml)
               else MOTIVO_BOE)
            + (f" ({', '.join(html)}); usar el HTML es decisión del usuario" if len(html) else "")
            + "; detalle en tablas/boe_rutas.csv")
    ficha["notas"] = [n for n in ficha.get("notas", []) if not n.startswith("robots.txt consultado")] + [nota]
    texto = json.dumps(ficha, indent=2, ensure_ascii=False)
    if b"\r\n" in crudo:
        texto = texto.replace("\n", "\r\n")
    from ingesta.comun.esquema import FichaFuente

    FichaFuente(**ficha)          # valida los campos (TypeError si sobra o falta alguno)
    if ficha["estado_sonda"] not in ("ok", "parcial", "fallo", "no_probada"):
        raise ValueError(f"estado_sonda {ficha['estado_sonda']!r} fuera del esquema común")
    r.write_bytes(texto.encode("utf-8"))
    return r


# --- Orden --------------------------------------------------------------------------------------
def _leer_tabla(nombre: str) -> pd.DataFrame | None:
    r = resultados_dir(TEMA) / "tablas" / nombre
    return pd.read_csv(r) if r.exists() else None


def _escribir(df: pd.DataFrame, nombre: str) -> Path:
    carpeta = resultados_dir(TEMA) / "tablas"
    carpeta.mkdir(parents=True, exist_ok=True)
    r = carpeta / nombre
    df.to_csv(r, index=False, encoding="utf-8", lineterminator="\n")
    return r


def construir_inventario(*, consultar_boe_red: bool | None = None, registro: Callable[[str], None] | None = None,
                         transporte_boe: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Escribe las cuatro tablas y la ficha del BoE; devuelve un resumen corto.

    ``consultar_boe_red``: ``True`` consulta ``robots.txt``; ``False`` no; ``None`` solo si aún no existe
    ``boe_rutas.csv`` (la consulta es una sola petición y no se repite en cada ejecución).
    """
    log = registro or (lambda _m: None)
    cat = catalogo.cargar_catalogo()
    publicaciones = visibilidad.cargar_publicaciones()
    lags = catalogo.cargar_lags()
    base = leer_base_medidas()
    log(f"base: {len(base)} filas, {base['serie'].nunique()} series")
    frecuencias = {s: e.get("frecuencia") for s, e in cat.items()}
    med = medidas_series(base, frecuencias)
    medida_alfred = _leer_tabla("publicacion_alfred_medida.csv")
    contrastadas = contrastadas_desde(medida_alfred, catalogo.cargar_excepciones())
    inv = tabla_inventario_series(med, cat, publicaciones, lags, contrastadas)
    por_periodo = pd.concat([comparaciones_previa(base, cat), comparaciones_ediciones(base, cat)],
                            ignore_index=True)
    agregados = agregados_alfred_medida(medida_alfred, cat)
    agregados = agregados[~agregados["serie"].isin(set(por_periodo["serie"]))]   # sin contar dos veces una serie
    fiab = tabla_fiabilidad(inv, cat, por_periodo, agregados, publicaciones, lags)
    inv = anotar_veredictos(inv, fiab)
    rutas = {"inventario_series": _escribir(inv, "inventario_series.csv"),
             "fiabilidad_c": _escribir(fiab, "fiabilidad_c.csv")}
    del base
    precios = tabla_inventario_precios(medir_ficheros_precios(log), tipos=_tipo_yahoo())
    rutas["inventario_precios"] = _escribir(precios, "inventario_precios.csv")
    ruta_boe = resultados_dir(TEMA) / "tablas" / "boe_rutas.csv"
    if consultar_boe_red or (consultar_boe_red is None and not ruta_boe.exists()):
        boe = rutas_boe(consultar_boe(transporte_boe))
        rutas["boe_rutas"] = _escribir(boe, "boe_rutas.csv")
        rutas["ficha_boe"] = actualizar_ficha_boe(boe)
    elif ruta_boe.exists():
        boe = pd.read_csv(ruta_boe)
    else:
        boe = pd.DataFrame(columns=list(COLUMNAS_BOE))
    cand = boe[boe["tipo"] == "candidata"]
    c = fiab[fiab["nivel"] == "C"]
    return {
        "series": int(len(inv)), "filas": int(inv["filas"].sum()), "ficheros_precios": int(len(precios)),
        "series_por_fuente": inv["fuente"].value_counts().sort_index().to_dict(),
        "nivel_fecha": inv["nivel_fecha"].value_counts().sort_index().to_dict(),
        "desde_2000": int(inv["desde_2000"].sum()), "desde_2000_exacto": int(inv["desde_2000_exacto"].sum()),
        "desde_2000_exacto_por_nivel": inv[inv["desde_2000_exacto"]]["nivel_fecha"].value_counts().sort_index().to_dict(),
        "veredicto_desde_2000": inv["veredicto_desde_2000"].value_counts().to_dict(),
        "es_proyeccion": int(inv["es_proyeccion"].sum()),
        "posible_frontera": inv["posible_frontera"].value_counts().to_dict(),
        "precios_por_proveedor": precios["proveedor"].value_counts().to_dict(),
        "tickers_con_apertura": int(precios["tiene_apertura"].sum()),
        "tickers_en_universo": int(precios["en_universo"].sum()),
        "tickers_deslistados": int(precios["deslistado"].sum()),
        "reglas_c_por_veredicto": c["veredicto"].value_counts().to_dict(),
        "boe_csv_xml_permitidas": list(cand.loc[cand["uso"].astype(str).str.startswith("permitida (CSV"), "ruta"]),
        "boe_html_permitidas": list(cand.loc[cand["uso"].astype(str).str.startswith("permitida solo en HTML"),
                                             "ruta"]),
        "rutas": {k: str(v) for k, v in rutas.items()},
    }
