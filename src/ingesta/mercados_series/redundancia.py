"""Redundancia del Tema 1 (paso 2 de la descarga completa): medidas para decidir D8, D9 y D10.

**No aplica ningún filtro ni elige nada**: mide y deja tablas de sensibilidad para que se decida
viendo los datos (el filtro es el paso 3). Las tablas llevan solo metadatos y medidas, nunca valores
de las series. Salidas en ``results/ingesta/mercados_series/tablas/``:

1. ``redundancia_pares.csv`` (D8). Pares de series de la base que se mueven casi igual.

   - Valor por serie y fecha de referencia: el ÚLTIMO vintage (la fila de mayor ``fecha_publicacion``).
     Para medir redundancia basta y es lo más barato.
   - Fecha de referencia llevada al periodo de su frecuencia (mes, trimestre, semana de lunes a
     domingo), para que el 1 y el 31 de un mes de dos fuentes casen.
   - Regla de cambios por unidad (``regla_cambio``): ``rentabilidad`` (la unidad ya es un cambio:
     se usa tal cual); ``diferencia`` si la unidad es un tipo, un porcentaje, puntos porcentuales o
     básicos, tanto por uno, un índice de difusión, de desviaciones típicas o centrado en 0, o un
     0/1; ``log`` (variación logarítmica) si es un nivel positivo. Una serie ``log`` con algún valor
     <= 0 pasa a ``diferencia``.
   - Solo dentro de la misma frecuencia (diaria, semanal, mensual, trimestral). Las anuales NO se
     correlacionan (pocos puntos): van a la tabla de conceptos.
   - Pearson y Spearman de los cambios en las fechas comunes, ``n``, años de solape (primera a
     última fecha común), fuente y concepto compartidos. Solo pares con |Pearson| >= 0,85 y
     solape >= 3 años. Se usa el valor absoluto: una cotización inversa (USD/EUR frente a EUR/USD)
     también es redundante.
   - Diarias de fuente o mercado distintos (otra hora de fijación u otro huso: BCE a las 14:15 CET
     frente a FRED a mediodía en Nueva York): también la correlación de los cambios semanales; el
     par se queda con la mayor (``base_correlacion``: ``diaria`` o ``semanal``; ``pearson_diaria``
     y ``pearson_semanal`` guardan las dos).
   - ``outlier_dominado``: |Pearson| >= 0,95 (umbral propuesto) y |Spearman| < 0,90; la
     correlación la infla un único atípico (el COVID, casi siempre).

2. ``redundancia_conceptos.csv``. Grupos de «mismo concepto en fuentes distintas», detectados por
   reglas sobre el id y el nombre normalizado (``REGLAS_CONCEPTO``: concepto y país), por
   ``id_origen`` normalizado igual en fuentes distintas, por nombre normalizado igual y por
   ``duplicado_de`` del catálogo. Se confirman con la correlación de cambios de cada par de
   miembros a la frecuencia más baja de los dos (media del periodo; dos diarias de fuentes distintas
   también a semanal, y vale la mayor: ``n_pares_base_semanal``); en los conceptos de tasa
   (inflación, PIB real) los niveles se pasan antes a variación interanual (log × 100). Sin elegir
   el canónico (paso 3). Fuera: proyecciones (``.PROY.`` del WEO y ``proyecciones: conservar``).

3. ``redundancia_sensibilidad.csv`` (D8). Cuántas series pasarían a alias con umbral 0,90, 0,95 y
   0,98 × solape mínimo de 3, 5 y 10 años, por fuente. Un par cuenta si |Pearson| >= umbral,
   |Spearman| >= umbral - 0,05 (``aristas_alias``) y el solape llega. En cada componente conexo de
   esos pares se queda UNA serie, la de más historia (inicio de referencia más antiguo; a igualdad,
   más observaciones; luego el id). Dos recuentos (``contar_alias``): ``n_alias_estrella`` (solo
   es alias la serie con par DIRECTO con la que se queda) y ``n_alias_transitivo`` (todas las demás
   del componente: A~B y B~C juntan A y C aunque A y C no lleguen).

4. ``redundancia_bm_weo.csv`` (D9). Una fila por serie del Banco Mundial y del WEO: indicador,
   país, ``en_alcance_estricto`` (D3: G7, China, el agregado de la zona euro y los agregados
   mundial y emergentes), ``miembro_zona_euro`` (sus 21 países, lectura amplia), cobertura desde
   2000 (por referencia y por primera publicación con valor, D1) y
   ``duplica_con_mayor_frecuencia``: el mismo concepto y país en OCDE, FRED,
   Eurostat o BCE a frecuencia mayor (mensual o trimestral frente a anual), con qué serie(s).

5. ``redundancia_etf.csv`` (paso 3) y ``tickers_sensibilidad.csv`` (D10).

   - Rentabilidad diaria total de ``supervivencia.rentabilidad_total_precios`` (split neutro y
     dividendo reinvertido, ``close_t / (close_{t-1} - D_t)``, el ``close_aj_total`` del TimeGate).
     Se descartan |r| > 50 % (saltos sin split anotado, ver el paso 1).
   - Clase, bucket, mercado y equivalente UCITS de ``inventario_precios.csv`` (el inventario de A1):
     la clase del universo o, fuera de él, el tipo de Yahoo.
   - ETF y ETP: grupos = componentes conexos de los pares con correlación >= 0,98 (solo positiva:
     un inverso no es un ETF casi idéntico), Spearman >= 0,93 y >= 3 años de solape
     (``tipo = grupo``); resumen de cada ``bucket`` del universo (``tipo = bucket``) y cada ETF del
     universo frente a su ``equivalente_ucits`` (``tipo = ucits``). Entre mercados con otro huso u
     otra hora de cierre vale la correlación semanal si es mayor (``base_correlacion``).
   - Tickers: cuántos de los ficheros de precios quedan con inicio <= 2000, 2007 o 2016 (primera
     sesión <= 2 de enero del año siguiente, como D1), con o sin sesiones con volumen > 0 >= 90 %,
     y volumen mediano del último año (365 días hasta la última sesión) > 0, 10.000 o 100.000; en
     total, por clase y por mercado.

Orden: ``python -m ingesta.mercados_series.redundancia [--destino DIR] [--max-tickers N]``.
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ingesta.comun.rutas import resultados_dir

log = logging.getLogger(__name__)

TEMA = "mercados_series"

# --- Parámetros ---------------------------------------------------------------------------------
FRECUENCIAS = ("diaria", "semanal", "mensual", "trimestral", "anual")
FRECUENCIAS_PARES = ("diaria", "semanal", "mensual", "trimestral")
ORDEN_FRECUENCIA = {f: i for i, f in enumerate(FRECUENCIAS)}
PERIODO = {"diaria": "D", "semanal": "W-SUN", "mensual": "M", "trimestral": "Q", "anual": "Y"}
PERIODOS_ANIO = {"diaria": 252, "semanal": 52, "mensual": 12, "trimestral": 4, "anual": 1}

UMBRAL_PARES = 0.85
SOLAPE_PARES = 3.0
MARGEN_SPEARMAN = 0.05      # alias: |Spearman| >= umbral - margen (si no, lo infla un atípico)
UMBRAL_REFERENCIA = 0.95    # umbral propuesto para D8: el de la columna ``outlier_dominado``
UMBRALES = (0.90, 0.95, 0.98)
SOLAPES = (3, 5, 10)
MIN_N_CONCEPTO = 8          # observaciones comunes mínimas para dar la correlación de un par de un concepto

UMBRAL_ETF = 0.98
SOLAPE_ETF = 3.0
SALTO_MAXIMO = 0.5          # |rentabilidad diaria| por encima: salto sin split anotado, se descarta
CORTES_INICIO = (2000, 2007, 2016)
MINIMO_SESIONES_VOLUMEN = 0.90
VOLUMENES_MEDIANOS = (None, 0, 10_000, 100_000)

FUENTES_MAYOR_FRECUENCIA = ("oecd", "fred_alfred", "eurostat", "bce")
CLASES_ETF = ("etf", "etp")

# --- Alcance de países (D3) ---------------------------------------------------------------------
G7 = ("USA", "CAN", "FRA", "DEU", "ITA", "JPN", "GBR")
ZONA_EURO = ("AUT", "BEL", "HRV", "CYP", "EST", "FIN", "FRA", "DEU", "GRC", "IRL", "ITA", "LVA", "LTU",
             "LUX", "MLT", "NLD", "PRT", "SVK", "SVN", "ESP", "BGR")   # BGR desde el 2026-01-01 (EA21)
# Zona euro, mundo y emergentes: del Banco Mundial (renta baja y media) y del WEO (001 mundo, 163 zona euro, 200 emergentes).
AGREGADOS = ("EA", "WLD", "LMY", "MIC", "EMU", "001", "163", "200")

_ISO = {"US": "USA", "UK": "GBR", "GB": "GBR", "DE": "DEU", "FR": "FRA", "IT": "ITA", "JP": "JPN",
        "CA": "CAN", "CN": "CHN", "ES": "ESP", "AU": "AUS", "EA": "EA", "EA19": "EA", "EA20": "EA",
        "EA21": "EA", "U2": "EA", "XM": "EA", "EMU": "EA", "EU27_2020": "EU",
        # Agregados del WEO (3b-2): 163 es la zona euro; 001 (mundo) y 200 (emergentes y en desarrollo) se comparan
        # con los del Banco Mundial (WLD, y LMY: renta baja y media), así D9 y D8 se miden entre ellos.
        "163": "EA", "001": "WLD", "200": "LMY"}


def pais_normalizado(codigo: str | None) -> str | None:
    """Código de país de cualquier fuente (ISO2, ISO3, agregados del BCE/BIS/Eurostat) → ISO3 o ``EA``."""
    if codigo is None:
        return None
    c = str(codigo).upper()
    return _ISO.get(c, c)


def motivo_alcance(pais: str | None) -> str:
    """Por qué ``pais`` está en el alcance de D3 (``''`` si está fuera)."""
    p = pais_normalizado(pais)
    motivos = []
    if p in G7:
        motivos.append("G7")
    if p in ZONA_EURO:
        motivos.append("zona euro (desde 2026)" if p == "BGR" else "zona euro")
    if p == "CHN":
        motivos.append("China")
    if p in AGREGADOS:
        motivos.append("agregado")
    return "; ".join(motivos)


# --- Regla de cambios ---------------------------------------------------------------------------
_RENTABILIDAD = re.compile(r"rentabilidad")
_DIFERENCIA = re.compile(r"%|puntos porcentuales|puntos b[aá]sicos|tanto por uno|difusi[oó]n|desviaciones t[ií]picas"
                         r"|\(0 = |^0/1$|probabilidad")


def regla_cambio(unidad: str | None) -> str:
    """``rentabilidad`` (ya es un cambio), ``diferencia`` (tipos, porcentajes, difusión) o ``log`` (nivel)."""
    u = (unidad or "").strip().lower()
    if _RENTABILIDAD.search(u):
        return "rentabilidad"
    if _DIFERENCIA.search(u):
        return "diferencia"
    return "log"


def cambios(valores: pd.Series, regla: str) -> tuple[pd.Series, str]:
    """Cambios de una serie ordenada por fecha según ``regla``; devuelve también la regla aplicada.

    ``log`` con algún valor <= 0 pasa a ``diferencia``. La primera observación queda NaN (salvo
    ``rentabilidad``, que se usa tal cual).
    """
    v = valores.astype(float)
    if regla == "rentabilidad":
        return v, regla
    if regla == "log":
        if (v.dropna() <= 0).any():
            regla = "diferencia"
        else:
            return np.log(v).diff(), regla
    return v.diff(), regla


def a_periodo(fechas: pd.Series | pd.DatetimeIndex, frecuencia: str) -> pd.DatetimeIndex:
    """Fechas llevadas al inicio del periodo de ``frecuencia`` (diaria: el día)."""
    f = pd.DatetimeIndex(pd.to_datetime(fechas))
    if frecuencia == "diaria":
        return f.normalize()
    return f.to_period(PERIODO[frecuencia]).start_time


# --- Lectura de la base -------------------------------------------------------------------------
def leer_base(ruta: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(último vintage por ``serie``/``fecha_referencia``, resumen por serie) de ``base_series.parquet``.

    El resumen lleva ``fuente``, ``inicio``/``fin`` de referencia, ``n_obs`` y la primera
    ``fecha_publicacion`` de una fila con valor (D1, como el inventario). Solo lee las columnas
    necesarias, con diccionario en las de texto.
    """
    from ingesta.mercados_series import almacen

    r = Path(ruta) if ruta is not None else almacen.ruta_series()
    tabla = pq.read_table(r, columns=["serie", "fecha_referencia", "fecha_publicacion", "valor", "fuente"],
                          read_dictionary=["serie", "fuente"])
    df = tabla.to_pandas()
    del tabla
    primera_pub = df[df["valor"].notna()].groupby("serie", observed=True)["fecha_publicacion"].min()
    fuente = df.groupby("serie", observed=True)["fuente"].first().astype(str)
    df = df.sort_values(["serie", "fecha_referencia", "fecha_publicacion"], kind="stable")
    ult = df.drop_duplicates(["serie", "fecha_referencia"], keep="last")[["serie", "fecha_referencia", "valor"]]
    del df
    ult = ult[ult["valor"].notna()].copy()
    ult["serie"] = ult["serie"].astype(str)
    g = ult.groupby("serie")["fecha_referencia"]
    resumen = pd.DataFrame({"fuente": fuente})
    resumen.index = resumen.index.astype(str)
    primera_pub.index = primera_pub.index.astype(str)
    resumen["primera_publicacion"] = primera_pub
    resumen = resumen.join(pd.DataFrame({"inicio": g.min(), "fin": g.max(), "n_obs": g.size()}))
    resumen.index.name = "serie"
    return ult.reset_index(drop=True), resumen


def metadatos(resumen: pd.DataFrame, catalogo: dict[str, dict] | None = None) -> pd.DataFrame:
    """Metadatos por serie de la base: los del catálogo más la cobertura medida (``resumen``)."""
    if catalogo is None:
        from ingesta.mercados_series import catalogo as cat_mod
        catalogo = cat_mod.cargar_catalogo()
    filas = []
    for sid in resumen.index:
        e = catalogo.get(sid, {})
        filas.append({"serie": sid, "nombre": e.get("nombre", ""), "frecuencia": e.get("frecuencia", ""),
                      "unidad": e.get("unidad", ""), "id_origen": e.get("id_origen", "") or "",
                      "estado": e.get("estado", ""), "duplicado_de": e.get("duplicado_de") or "",
                      "mercado": e.get("mercado") or "",
                      "es_proyeccion": ".PROY." in sid or e.get("proyecciones") == "conservar"})
    meta = pd.DataFrame(filas).set_index("serie").join(resumen)
    meta["regla"] = meta["unidad"].map(regla_cambio)
    return meta


# --- Pares (D8) ---------------------------------------------------------------------------------
def matriz_cambios(largo: pd.DataFrame, meta: pd.DataFrame, frecuencia: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Cambios en ancho (fecha de periodo × serie) de las series de ``frecuencia`` y la regla aplicada.

    ``largo``: ``serie, fecha_referencia, valor`` (un valor por serie y fecha). Si dos fechas caen
    en el mismo periodo se queda la última. No modifica ``meta``.
    """
    ids = meta.index[meta["frecuencia"] == frecuencia]
    sub = largo[largo["serie"].isin(ids)]
    columnas, reglas = {}, {}
    for sid, g in sub.groupby("serie", sort=True):
        s = pd.Series(g["valor"].to_numpy(dtype=float), index=a_periodo(g["fecha_referencia"], frecuencia))
        s = s[~s.index.duplicated(keep="last")].sort_index()
        c, regla = cambios(s, meta.at[sid, "regla"])
        columnas[sid] = c
        reglas[sid] = regla
    if not columnas:
        return pd.DataFrame(), reglas
    return pd.DataFrame(columnas).sort_index(), reglas


def cambios_semanales(cambios_diarios: pd.DataFrame, rentabilidad_simple: bool = False) -> pd.DataFrame:
    """Cambios diarios sumados por semana (lunes a domingo): el cambio de la semana.

    Con ``rentabilidad_simple`` (rentabilidades de precios) se suman los ``log1p`` (rentabilidad
    logarítmica de la semana). Una semana sin datos de una serie queda NaN.
    """
    x = np.log1p(cambios_diarios) if rentabilidad_simple else cambios_diarios
    return x.groupby(a_periodo(x.index, "semanal")).sum(min_count=1)


def _solape(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series, float, pd.Timestamp | None, pd.Timestamp | None]:
    m = a.notna() & b.notna()
    if not m.any():
        return a[m], b[m], 0.0, None, None
    idx = a.index[m]
    return a[m], b[m], (idx[-1] - idx[0]).days / 365.25, idx[0], idx[-1]


def _medir(a: pd.Series, b: pd.Series) -> dict[str, object] | None:
    x, y, anios, ini, fin = _solape(a, b)
    if len(x) < 3:
        return None
    return {"pearson": float(x.corr(y)), "spearman": float(x.rank().corr(y.rank())), "n": int(len(x)),
            "anios_solape": round(anios, 2), "inicio_solape": ini.date().isoformat(), "fin_solape": fin.date().isoformat()}


COLUMNAS_PARES = ["serie_a", "serie_b", "frecuencia", "pearson", "spearman", "n", "anios_solape", "inicio_solape",
                  "fin_solape", "base_correlacion", "pearson_diaria", "pearson_semanal"]


def pares_correlados(cambios_ancho: pd.DataFrame, frecuencia: str, *, umbral: float = UMBRAL_PARES,
                     solape_min: float = SOLAPE_PARES, absoluta: bool = True, grupo: pd.Series | None = None,
                     rentabilidad_simple: bool = False) -> pd.DataFrame:
    """Pares con |Pearson| >= ``umbral`` y >= ``solape_min`` años de solape en ``cambios_ancho``.

    - ``absoluta=False``: solo correlaciones positivas (ETF: un inverso no es un ETF casi idéntico).
    - ``grupo`` (diarias): etiqueta por columna (fuente y mercado). En los pares de grupo distinto
      (otra hora de fijación u otro huso) se mide también la correlación de los cambios SEMANALES y
      el par se queda con la mayor de las dos (``base_correlacion``: ``diaria`` o ``semanal``); así
      el BCE (14:15 CET) y FRED (mediodía en Nueva York) no salen como falso negativo.
    - Pearson en bloque con ``DataFrame.corr(min_periods)`` (pre-filtro holgado de la mitad de los
      periodos de ``solape_min``); Spearman, ``n`` y años de solape exactos solo para los candidatos.
      ``pearson``, ``spearman``, ``n`` y el solape son los de la base elegida.
    """
    if cambios_ancho.shape[1] < 2:
        return pd.DataFrame(columns=COLUMNAS_PARES)
    nombres = list(cambios_ancho.columns)

    def _mat(df: pd.DataFrame, f: str) -> np.ndarray:
        c = np.nan_to_num(df.corr(min_periods=max(3, int(solape_min * PERIODOS_ANIO[f] * 0.5))).to_numpy(), nan=0.0)
        return np.abs(c) if absoluta else c

    candidatos = _mat(cambios_ancho, frecuencia) >= umbral
    semanal, distinto = None, None
    if grupo is not None and frecuencia == "diaria":
        g = grupo.reindex(nombres).fillna("").to_numpy()
        distinto = g[:, None] != g[None, :]
        semanal = cambios_semanales(cambios_ancho, rentabilidad_simple)
        candidatos |= distinto & (_mat(semanal, "semanal") >= umbral)
    ii, jj = np.where(np.triu(candidatos, k=1))
    filas = []
    for i, j in zip(ii, jj):
        opciones = {"diaria": _medir(cambios_ancho.iloc[:, i], cambios_ancho.iloc[:, j])}
        if semanal is not None and distinto[i, j]:
            opciones["semanal"] = _medir(semanal.iloc[:, i], semanal.iloc[:, j])
        validas = {k: v for k, v in opciones.items() if v and v["anios_solape"] >= solape_min}
        if not validas:
            continue
        clave = max(validas, key=lambda k: abs(validas[k]["pearson"]) if absoluta else validas[k]["pearson"])
        filas.append({"serie_a": nombres[i], "serie_b": nombres[j], "frecuencia": frecuencia, **validas[clave],
                      "base_correlacion": clave,
                      "pearson_diaria": opciones["diaria"]["pearson"] if opciones["diaria"] else np.nan,
                      "pearson_semanal": opciones["semanal"]["pearson"] if opciones.get("semanal") else np.nan})
    out = pd.DataFrame(filas, columns=COLUMNAS_PARES)
    r = out["pearson"].abs() if absoluta else out["pearson"]
    return out[r >= umbral].reset_index(drop=True)


def componentes(aristas: Iterable[tuple[str, str]]) -> list[set[str]]:
    """Componentes conexos (unión-búsqueda) de un grafo dado por sus aristas; solo los de >= 2 nodos."""
    padre: dict[str, str] = {}

    def raiz(x: str) -> str:
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for a, b in aristas:
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[max(ra, rb)] = min(ra, rb)
    grupos: dict[str, set[str]] = {}
    for x in list(padre):
        grupos.setdefault(raiz(x), set()).add(x)
    return sorted((g for g in grupos.values() if len(g) >= 2), key=lambda g: sorted(g)[0])


def mas_historia(miembros: Iterable[str], meta: pd.DataFrame) -> str:
    """La serie de más historia: inicio de referencia más antiguo; a igualdad, más observaciones; luego el id."""
    return min(miembros, key=lambda s: (meta.at[s, "inicio"], -int(meta.at[s, "n_obs"]), s))


def aristas_alias(pares: pd.DataFrame, umbral: float, solape_min: float, *, absoluta: bool = True) -> pd.DataFrame:
    """Pares que cuentan para alias: |Pearson| >= ``umbral``, |Spearman| >= ``umbral - MARGEN_SPEARMAN``
    (un único atípico, como el COVID, no basta) y solape >= ``solape_min`` años."""
    p, s = (pares["pearson"].abs(), pares["spearman"].abs()) if absoluta else (pares["pearson"], pares["spearman"])
    return pares[(p >= umbral) & (s >= umbral - MARGEN_SPEARMAN) & (pares["anios_solape"] >= solape_min)]


def outlier_dominado(pares: pd.DataFrame, umbral: float = UMBRAL_REFERENCIA) -> pd.Series:
    """|Pearson| >= ``umbral`` pero |Spearman| < ``umbral - MARGEN_SPEARMAN``: lo infla un único atípico."""
    return (pares["pearson"].abs() >= umbral) & (pares["spearman"].abs() < umbral - MARGEN_SPEARMAN)


def contar_alias(pares: pd.DataFrame, meta: pd.DataFrame, umbral: float, solape_min: float, *,
                 regla: str = "estrella") -> dict[str, str]:
    """``alias → serie que se queda`` en cada componente conexo de ``aristas_alias``.

    En cada componente se queda la de más historia (``mas_historia``). ``estrella``: solo es alias
    la serie con par DIRECTO con la que se queda (el resto del componente no cuenta como alias).
    ``transitiva``: todas las demás del componente son alias (A~B y B~C juntan A y C aunque A y C
    no lleguen).
    """
    if regla not in ("estrella", "transitiva"):
        raise ValueError(f"regla desconocida {regla!r}")
    sel = aristas_alias(pares, umbral, solape_min)
    directos = set(zip(sel["serie_a"], sel["serie_b"])) | set(zip(sel["serie_b"], sel["serie_a"]))
    alias = {}
    for g in componentes(zip(sel["serie_a"], sel["serie_b"])):
        queda = mas_historia(g, meta)
        alias.update({s: queda for s in g if s != queda and (regla == "transitiva" or (s, queda) in directos)})
    return alias


def tabla_sensibilidad(pares: pd.DataFrame, meta: pd.DataFrame, umbrales: Iterable[float] = UMBRALES,
                       solapes: Iterable[float] = SOLAPES) -> pd.DataFrame:
    """Series que pasarían a alias por umbral × solape, por fuente y en total, con las dos reglas.

    ``n_alias_estrella`` / ``n_alias_transitivo``: reglas de ``contar_alias``. Las columnas
    ``*_entre_fuentes`` cuentan solo con los pares de fuentes distintas (sin los plazos vecinos de
    una misma curva ni las versiones de una misma fuente).
    """
    comparables = meta["frecuencia"].isin(FRECUENCIAS_PARES)
    base = meta.groupby("fuente").size()
    comp = meta[comparables].groupby("fuente").size()
    entre_fuentes = pares[~pares["misma_fuente"].astype(bool)]
    variantes = (("n_alias_estrella", pares, "estrella"), ("n_alias_transitivo", pares, "transitiva"),
                 ("n_alias_estrella_entre_fuentes", entre_fuentes, "estrella"),
                 ("n_alias_transitivo_entre_fuentes", entre_fuentes, "transitiva"))
    filas = []
    for u in umbrales:
        for s in solapes:
            cuentas = {}
            for nombre, p, regla in variantes:
                alias = contar_alias(p, meta, u, s, regla=regla)
                cuentas[nombre] = (len(alias),
                                   pd.Series([meta.at[a, "fuente"] for a in alias], dtype=object).value_counts())
            for fuente in [*sorted(base.index), "total"]:
                nc = int(comp.sum() if fuente == "total" else comp.get(fuente, 0))
                fila = {"umbral": u, "solape_min_anios": s, "fuente": fuente,
                        "n_series_base": int(base.sum() if fuente == "total" else base.get(fuente, 0)),
                        "n_series_comparables": nc}
                for nombre, (n, por_fuente) in cuentas.items():
                    fila[nombre] = int(n if fuente == "total" else por_fuente.get(fuente, 0))
                fila["pct_alias_estrella"] = round(100 * fila["n_alias_estrella"] / nc, 1) if nc else np.nan
                filas.append(fila)
    return pd.DataFrame(filas)


# --- Conceptos ----------------------------------------------------------------------------------
def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin puntuación y con espacios simples."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _tenor(t: str) -> str:
    t = t.upper().replace("MO", "M").replace("YR", "Y")
    return t if t[-1] in "MWY" else f"{t}Y"


# (concepto, patrón sobre el id; ``p`` = país, ``t`` = plazo, ``pais`` fijo si no hay grupo ``p``)
REGLAS_CONCEPTO: tuple[tuple[str, str, str | None], ...] = (
    # Bonos públicos por plazo (Tesoro de EE. UU. de FRED, de la curva del Tesoro y de los índices Cboe)
    ("bono_gobierno_{t}", r"^fred:DGS(?P<t>\d+(?:MO)?)$", "USA"),
    ("bono_gobierno_{t}", r"^ust:PAR\.(?P<t>\d+[MY])$", "USA"),
    ("bono_gobierno_{t}", r"^fred:GS(?P<t>\d+)$", "USA"),
    ("bono_gobierno_3M", r"^(fred:DTB3|fred:TB3MS|gw:M\.tbl|yf:\^IRX)$", "USA"),
    ("bono_gobierno_6M", r"^fred:DTB6$", "USA"),
    ("bono_gobierno_1Y", r"^fred:DTB1YR$", "USA"),
    ("bono_gobierno_5Y", r"^yf:\^FVX$", "USA"),
    ("bono_gobierno_10Y", r"^(yf:\^TNX|shiller:LONGRATE|datahub:US10Y_MENSUAL|fred:IRLTLT01USM156N)$", "USA"),
    ("bono_gobierno_30Y", r"^yf:\^TYX$", "USA"),
    ("bono_gobierno_{t}", r"^boc:BOND\.(?P<t>\d+Y)$", "CAN"),
    ("bono_gobierno_10Y", r"^boc:BD\.CDN\.10YR", "CAN"),
    ("bono_gobierno_{t}", r"^boe:NOM\.(?P<t>\d+[MY])$", "GBR"),
    ("bono_gobierno_{t}", r"^mof:JGB\.(?P<t>\d+Y)$", "JPN"),
    ("bono_gobierno_10Y", r"^bbk:BBSIS\.D\.I\.ZST\.ZI\.EUR\.S1311\.B\.A604\.R10XX", "DEU"),
    ("bono_gobierno_10Y", r"^rba:FCMYGBAG10D$", "AUS"),
    # Macro por país
    ("inflacion_ipc", r"^wb:(?P<p>\w{3})\.FP\.CPI\.TOTL\.ZG$", None),
    ("inflacion_ipc", r"^imf:WEO\.(?P<p>\w{3})\.PCPIPCH$", None),
    ("inflacion_ipc", r"^oecd:CP\.(?P<p>\w+)$", None),
    ("inflacion_ipc", r"^eurostat:(?:HICP_EMP|prc_hicp_manr\.M\.RCH_A\.CP00|prc_hicp_minr\.M\.RCH_A\.TOTAL)\.(?P<p>\w+)$",
     None),
    ("inflacion_ipc", r"^ecb:HICP\.M\.U2\.N\.000000", "EA"),
    ("inflacion_ipc", r"^(fred:CPIAUCSL|shiller:CPI|gw:M\.infl)$", "USA"),
    ("paro", r"^wb:(?P<p>\w{3})\.SL\.UEM\.TOTL\.ZS$", None),
    ("paro", r"^imf:WEO\.(?P<p>\w{3})\.LUR$", None),
    ("paro", r"^oecd:UNEMP\.(?P<p>\w+)$", None),
    ("paro", r"^eurostat:une_rt_m\.M\.SA\.TOTAL\.PC_ACT\.T\.(?P<p>\w+)$", None),
    ("paro", r"^ecb:LFSI\.M\.U2\.S\.UNEHRT\.TOTAL0", "EA"),
    ("paro", r"^fred:UNRATE$", "USA"),
    ("pib_real", r"^wb:(?P<p>\w{3})\.NY\.GDP\.MKTP\.KD\.ZG$", None),
    ("pib_real", r"^imf:WEO\.(?P<p>\w{3})\.NGDP_RPCH$", None),
    ("pib_real", r"^eurostat:namq_10_gdp\.Q\.CLV_PCH_SM\.SCA\.B1GQ\.(?P<p>\w+)$", None),
    ("pib_real", r"^ecb:MNA\.Q\.Y\.I10\.W2\.S1\.S1\.B\.B1GQ", "EA"),
    ("pib_real", r"^(fred:GDPC1|fred:A191RL1Q225SBEA|fred:BBKMGDP|philly:ROUTPUT|deriv:PIB_REAL_USA_VINTAGES)$", "USA"),
    ("tipo_oficial", r"^bis:WS_CBPOL\.M\.(?P<p>\w\w)$", None),
    ("tipo_oficial", r"^ecb:(DFR|MRO)$", "EA"),
    ("tipo_oficial", r"^fred:(DFF|EFFR|FEDFUNDS)$", "USA"),
    ("tipo_oficial", r"^boc:V39079$", "CAN"),
    ("tipo_oficial", r"^boj:FM01\.STRDCLUCON$", "JPN"),
    ("tipo_oficial", r"^rba:FIRMMCRTD$", "AUS"),
    ("cli_ocde", r"^oecd:LI_AA\.(?P<p>\w+)$", None),
    ("cli_ocde", r"^fred:USALOLITOAASTSAM$", "USA"),
    ("tipo_cambio_efectivo_real", r"^bis:WS_EER\.M\.R\.B\.(?P<p>\w\w)$", None),
    ("tipo_cambio_efectivo_real", r"^fred:RNUSBIS$", "USA"),
    # Mercados y finanzas (EE. UU.)
    ("eurusd", r"^(ecb:EXR\.D\.USD\.EUR|fred:DEXUSEU)$", "EA"),
    ("dolar_monedas_principales", r"^(fred:DTWEXM|fred:TWEXMMTH|yf:DX-Y\.NYB)$", "USA"),
    ("dolar_economias_avanzadas", r"^fred:(DTWEXAFEGS|TWEXAFEGSMTH)$", "USA"),
    ("sp500_precio", r"^(yf:\^GSPC|shiller:P|gw:M\.Index|datahub:SP500_MENSUAL)$", "USA"),
    ("bonos_aaa", r"^(fred:AAA|fred:DAAA|gw:M\.AAA)$", "USA"),
    ("bonos_baa", r"^(fred:BAA|fred:DBAA|gw:M\.BAA)$", "USA"),
    ("diferencial_baa_10a", r"^(fred:BAA10Y|deriv:DBAA-DGS10)$", "USA"),
    ("diferencial_papel_comercial_ff", r"^(fred:CPFF|deriv:DCPF3M-DFF)$", "USA"),
    ("diferencial_10a_ff", r"^(fred:T10YFF|deriv:DGS10-DFF)$", "USA"),
    ("diferencial_5a_ff", r"^(fred:T5YFF|deriv:DGS5-DFF)$", "USA"),
    ("ted_spread", r"^(fred:TEDRATE|deriv:DED3-DTB3)$", "USA"),
    ("tipo_libre_riesgo_ff", r"^(ff:F[35]D\.RF|gw:M\.Rfree)$", "USA"),
    ("ff_{t}", r"^ff:F[35][DM]\.(?P<t>Mkt-RF|SMB|HML)$", "USA"),
    ("dividendos_sp", r"^(shiller:D|gw:M\.D12)$", "USA"),
    ("beneficios_sp", r"^(shiller:E|gw:M\.E12)$", "USA"),
    ("recesion_nber", r"^fred:USRECD?$", "USA"),
    ("consumo_real", r"^fred:PCECC?96$", "USA"),
    ("sentimiento_esi", r"^eurostat:ei_bssi_m_r2\.M\.BS-ESI-I\.SA\.(?P<p>\w+)$", None),
)
_REGLAS = tuple((c, re.compile(p), pais) for c, p, pais in REGLAS_CONCEPTO)
CONCEPTOS_TASA = ("inflacion_ipc", "pib_real")
CONCEPTO_INDICADOR = {"FP.CPI.TOTL.ZG": "inflacion_ipc", "PCPIPCH": "inflacion_ipc", "SL.UEM.TOTL.ZS": "paro",
                      "LUR": "paro", "NY.GDP.MKTP.KD.ZG": "pib_real", "NGDP_RPCH": "pib_real"}


def concepto_de(serie: str) -> tuple[str, str] | None:
    """``(concepto, país)`` de una serie según ``REGLAS_CONCEPTO`` (``None`` si ninguna casa)."""
    for concepto, patron, pais in _REGLAS:
        m = patron.search(serie)
        if m:
            d = m.groupdict()
            if d.get("t"):
                concepto = concepto.format(t=_tenor(d["t"]) if concepto.startswith("bono_") else d["t"])
            nombre = concepto
            return nombre, pais_normalizado(d.get("p") or pais)
    return None


def _id_origen_normalizado(id_origen: str) -> str:
    """Último tramo del ``id_origen`` (tras ``/``) en mayúsculas; vacío si es una fórmula (series derivadas)."""
    t = str(id_origen or "").strip()
    if not t or re.search(r"\s|[()*+]", t):
        return ""
    return t.split("/")[-1].upper()


def grupos_concepto(meta: pd.DataFrame) -> pd.DataFrame:
    """Grupos candidatos (sin correlación): ``grupo, serie, concepto, pais, detectado_por``.

    Aristas: misma ``(concepto, país)`` de ``REGLAS_CONCEPTO``; ``id_origen`` normalizado igual en
    fuentes distintas; nombre normalizado igual; ``duplicado_de`` del catálogo. Sin proyecciones.
    """
    m = meta[~meta["es_proyeccion"]]
    ids = set(m.index)
    aristas: list[tuple[str, str, str]] = []
    clave = {s: concepto_de(s) for s in m.index}
    for por, serie_clave in (("regla", clave),
                             ("id_origen", {s: (_id_origen_normalizado(m.at[s, "id_origen"]),) for s in m.index}),
                             ("nombre", {s: (normalizar(m.at[s, "nombre"]),) for s in m.index})):
        cubos: dict[tuple, list[str]] = {}
        for s, k in serie_clave.items():
            if k and k[0]:
                cubos.setdefault(k, []).append(s)
        for miembros in cubos.values():
            if len(miembros) < 2 or (por != "regla" and m.loc[miembros, "fuente"].nunique() < 2):
                continue
            aristas += [(a, b, por) for a, b in zip(miembros, miembros[1:])]
    for s in m.index:
        d = m.at[s, "duplicado_de"]
        if d and d in ids:
            aristas.append((s, d, "duplicado_de"))
    por_serie: dict[str, set[str]] = {}
    for a, b, por in aristas:
        por_serie.setdefault(a, set()).add(por)
        por_serie.setdefault(b, set()).add(por)
    filas = []
    for i, g in enumerate(componentes((a, b) for a, b, _ in aristas), start=1):
        for s in sorted(g):
            k = clave.get(s)
            filas.append({"grupo": i, "serie": s, "concepto": k[0] if k else "", "pais": k[1] if k else "",
                          "detectado_por": "; ".join(sorted(por_serie.get(s, ())))})
    return pd.DataFrame(filas, columns=["grupo", "serie", "concepto", "pais", "detectado_por"])


def serie_agregada(valores: pd.Series, frecuencia_origen: str, frecuencia_destino: str) -> pd.Series:
    """Serie (índice de fechas de referencia) llevada a ``frecuencia_destino`` con la media del periodo."""
    s = valores.copy()
    s.index = a_periodo(s.index, frecuencia_origen)
    s = s.groupby(level=0).last()
    if frecuencia_destino != frecuencia_origen:
        s = s.groupby(a_periodo(s.index, frecuencia_destino)).mean()
    return s.sort_index()


def correlacion_concepto(a: pd.Series, b: pd.Series, fa: str, fb: str, regla_a: str, regla_b: str,
                         tasa: bool = False, destino: str | None = None) -> dict[str, float]:
    """Correlación de cambios de dos miembros a la frecuencia más baja de los dos (o a ``destino``).

    ``tasa``: los niveles (regla ``log``) se pasan antes a variación interanual (log × 100) para
    compararlos con las tasas. Devuelve ``pearson``, ``n`` y ``anios_solape`` (NaN si n < MIN_N_CONCEPTO).
    """
    destino = destino or max(fa, fb, key=ORDEN_FRECUENCIA.get)
    k = PERIODOS_ANIO[destino] if destino != "diaria" else 252
    series = []
    for s, f, regla in ((a, fa, regla_a), (b, fb, regla_b)):
        x = serie_agregada(s.astype(float), f, destino)
        if tasa and regla == "log" and (x.dropna() > 0).all():
            x, regla = 100 * np.log(x).diff(k), "diferencia"
        series.append(cambios(x, regla)[0])
    x, y, anios, _, _ = _solape(*series[0].align(series[1]))
    if len(x) < MIN_N_CONCEPTO:
        return {"pearson": np.nan, "n": len(x), "anios_solape": round(anios, 2)}
    return {"pearson": float(x.corr(y)), "n": int(len(x)), "anios_solape": round(anios, 2)}


def tabla_conceptos(grupos: pd.DataFrame, meta: pd.DataFrame, largo: pd.DataFrame) -> pd.DataFrame:
    """Un renglón por grupo: miembros, fuentes, frecuencias, solape y correlación mínima entre miembros."""
    if grupos.empty:
        return pd.DataFrame()
    necesarias = set(grupos["serie"])
    valores = {sid: pd.Series(g["valor"].to_numpy(dtype=float), index=pd.DatetimeIndex(g["fecha_referencia"]))
               for sid, g in largo[largo["serie"].isin(necesarias)].groupby("serie")}
    filas = []
    for gid, g in grupos.groupby("grupo"):
        miembros = list(g["serie"])
        conceptos = sorted({c for c in g["concepto"] if c})
        tasa = any(c in CONCEPTOS_TASA for c in conceptos)
        medidas = []
        for a, b in combinations(miembros, 2):
            if a not in valores or b not in valores:
                continue
            args = (valores[a], valores[b], meta.at[a, "frecuencia"], meta.at[b, "frecuencia"], meta.at[a, "regla"],
                    meta.at[b, "regla"], tasa)
            m = {**correlacion_concepto(*args), "base": "diaria"}
            if args[2] == args[3] == "diaria" and meta.at[a, "fuente"] != meta.at[b, "fuente"]:
                w = {**correlacion_concepto(*args, destino="semanal"), "base": "semanal"}   # otra hora de fijación
                if pd.notna(w["pearson"]) and (pd.isna(m["pearson"]) or abs(w["pearson"]) > abs(m["pearson"])):
                    m = w
            medidas.append(m)
        r = pd.DataFrame(medidas) if medidas else pd.DataFrame(columns=["pearson", "n", "anios_solape", "base"])
        medidos = r[r["pearson"].notna()]
        sub = meta.loc[miembros]
        filas.append({
            "grupo": gid, "concepto": "; ".join(conceptos), "pais": "; ".join(sorted({p for p in g["pais"] if p})),
            "n_miembros": len(miembros), "miembros": "; ".join(miembros),
            "fuentes": "; ".join(sorted(sub["fuente"].unique())), "n_fuentes": int(sub["fuente"].nunique()),
            "frecuencias": "; ".join(sorted(sub["frecuencia"].unique(), key=ORDEN_FRECUENCIA.get)),
            "detectado_por": "; ".join(sorted({p for x in g["detectado_por"] for p in x.split("; ") if p})),
            "duplicadas_catalogo": "; ".join(s for s in miembros if sub.at[s, "estado"] == "duplicada"),
            "inicio_comun": sub["inicio"].max().date().isoformat(), "fin_comun": sub["fin"].min().date().isoformat(),
            "solape_comun_anios": round(max(0.0, (sub["fin"].min() - sub["inicio"].max()).days / 365.25), 1),
            "n_pares": len(r), "n_pares_medidos": len(medidos),
            "n_pares_base_semanal": int((medidos["base"] == "semanal").sum()),
            "corr_min": round(medidos["pearson"].min(), 3) if len(medidos) else np.nan,
            "corr_mediana": round(medidos["pearson"].median(), 3) if len(medidos) else np.nan,
            "solape_min_anios_par": medidos["anios_solape"].min() if len(medidos) else np.nan,
        })
    return pd.DataFrame(filas)


# --- Banco Mundial y WEO (D9) -------------------------------------------------------------------
_WB = re.compile(r"^wb:(?P<p>\w{3})\.(?P<i>.+)$")
_WEO = re.compile(r"^imf:WEO\.(?P<p>\w{3})\.(?P<i>[A-Z_]+)(?P<proy>\.PROY\.H\d+)?$")


def pais_indicador(serie: str) -> tuple[str, str, str] | None:
    """``(fuente, país, indicador)`` de un id del Banco Mundial o del WEO (proyecciones con ``.PROY.Hk``)."""
    m = _WB.match(serie)
    if m:
        return "worldbank", m["p"], m["i"]
    m = _WEO.match(serie)
    if m:
        return "imf_weo", m["p"], m["i"] + (m["proy"] or "")
    return None


def tabla_bm_weo(meta: pd.DataFrame, grupos: pd.DataFrame) -> pd.DataFrame:
    """Una fila por serie del Banco Mundial y del WEO con alcance, cobertura y duplicidad (ver el módulo).

    ``en_alcance_estricto``: D3 tal cual (G7, China, el agregado de la zona euro si existe y los
    agregados mundial y emergentes); ``miembro_zona_euro``: país miembro de la zona euro (lectura
    amplia de «zona euro y sus países»). Un país del G7 del euro (DEU, FRA, ITA) es las dos cosas.
    """
    concepto_pais = {}
    for s in meta.index:
        k = concepto_de(s)
        if k and not meta.at[s, "es_proyeccion"]:
            concepto_pais.setdefault(k, []).append(s)
    filas = []
    for s in meta.index:
        pi = pais_indicador(s)
        if pi is None:
            continue
        fuente, pais, indicador = pi
        base_ind = indicador.split(".PROY.")[0]
        concepto = CONCEPTO_INDICADOR.get(base_ind, "")
        proy = bool(meta.at[s, "es_proyeccion"])
        otros = concepto_pais.get((concepto, pais_normalizado(pais)), []) if concepto and not proy else []
        mayor = [o for o in otros if meta.at[o, "fuente"] in FUENTES_MAYOR_FRECUENCIA
                 and ORDEN_FRECUENCIA.get(meta.at[o, "frecuencia"], 9) < ORDEN_FRECUENCIA["anual"]]
        misma = [o for o in otros if o != s and meta.at[o, "fuente"] in ("worldbank", "imf_weo")]
        inicio, pub = meta.at[s, "inicio"], meta.at[s, "primera_publicacion"]
        p = pais_normalizado(pais)
        filas.append({
            "serie": s, "fuente": fuente, "indicador": base_ind, "es_proyeccion": proy, "pais": pais,
            "en_alcance_estricto": bool(p in G7 or p == "CHN" or p in AGREGADOS),
            "miembro_zona_euro": bool(p in ZONA_EURO), "motivo_alcance": motivo_alcance(pais), "concepto": concepto,
            "inicio_referencia": inicio.date().isoformat(), "fin_referencia": meta.at[s, "fin"].date().isoformat(),
            "n_obs": int(meta.at[s, "n_obs"]),
            "cubre_2000_referencia": bool(inicio <= pd.Timestamp("2000-12-31")),
            "primera_publicacion": pub.date().isoformat() if pd.notna(pub) else "",
            "cubre_2000_publicacion": bool(pd.notna(pub) and pub <= pd.Timestamp("2001-01-02")),
            "duplica_con_mayor_frecuencia": bool(mayor), "series_mayor_frecuencia": "; ".join(sorted(mayor)),
            "duplica_bm_weo": "; ".join(sorted(misma)),
        })
    return pd.DataFrame(filas)


# --- Precios: ETF y tickers (D10) ---------------------------------------------------------------
def rentabilidades(precios: pd.DataFrame) -> pd.Series:
    """Rentabilidad diaria total (split neutro, dividendo reinvertido) indexada por sesión; |r| > 50 % → NaN."""
    from ingesta.mercados_series.supervivencia import rentabilidad_total_precios

    r = rentabilidad_total_precios(precios)
    s = pd.Series(r["rentabilidad"].to_numpy(dtype=float), index=pd.DatetimeIndex(r["sesion"]))
    s[s.abs() > SALTO_MAXIMO] = np.nan
    return s[~s.index.duplicated(keep="last")]


def metricas_ticker(precios: pd.DataFrame) -> dict[str, object]:
    """Inicio, fin, sesiones, % de sesiones con volumen > 0 y volumen mediano del último año."""
    ses = pd.DatetimeIndex(precios["sesion"])
    vol = precios["volume"].astype(float)
    fin = ses.max()
    ultimo = vol[ses > fin - pd.Timedelta(days=365)]
    mercado = precios["mercado"].mode()
    return {"inicio": ses.min(), "fin": fin, "sesiones": len(precios),
            "pct_volumen_positivo": float((vol > 0).mean()) if len(vol) else 0.0,
            "volumen_mediano_ultimo_anio": float(ultimo.median()) if len(ultimo) else 0.0,
            "mercado": str(mercado.iloc[0]) if len(mercado) else ""}


def tabla_tickers_sensibilidad(metricas: pd.DataFrame) -> pd.DataFrame:
    """Cuántos tickers quedan por corte de inicio × filtro de sesiones × volumen mediano, en total/clase/mercado."""
    filas = []
    for anio in CORTES_INICIO:
        corte = pd.Timestamp(f"{anio + 1}-01-02")
        for sesiones in (False, True):
            for vmin in VOLUMENES_MEDIANOS:
                ok = metricas["inicio"] <= corte
                if sesiones:
                    ok &= metricas["pct_volumen_positivo"] >= MINIMO_SESIONES_VOLUMEN
                if vmin is not None:
                    ok &= metricas["volumen_mediano_ultimo_anio"] > vmin
                for tipo, col in (("total", None), ("clase", "clase"), ("mercado", "mercado")):
                    claves = metricas[col] if col else pd.Series("total", index=metricas.index)
                    for grupo, idx in claves.groupby(claves).groups.items():
                        filas.append({"inicio_max": anio, "corte_inicio": corte.date().isoformat(),
                                      "filtro_sesiones_volumen_90": sesiones,
                                      "volumen_mediano_min": "sin_filtro" if vmin is None else f">{vmin}",
                                      "desglose": tipo, "grupo": grupo, "n_total": len(idx),
                                      "n_quedan": int(ok.loc[idx].sum())})
    return pd.DataFrame(filas)


COLUMNAS_ETF = ["tipo", "id", "n_miembros", "miembros", "buckets", "clases", "origen", "mercados", "inicios",
                "corr_min", "corr_mediana", "base_correlacion", "corr_diaria", "corr_semanal", "solape_min_anios",
                "n_pares_umbral"]


def cierre_de_mercado() -> dict[str, str]:
    """``mercado → 'huso hora'`` del cierre vigente (``config/mercados.yaml``).

    Dos ETF con la misma etiqueta (NYSE Arca y NYSE, por ejemplo) cierran a la misma hora: solo
    se compara la diaria. Con etiqueta distinta (Londres frente a Nueva York) vale también la semanal.
    """
    import yaml

    from ingesta.mercados_series.universo import RUTA_MERCADOS

    crudo = yaml.safe_load(RUTA_MERCADOS.read_text(encoding="utf-8")) or {}
    return {str(k): f"{v.get('huso', '')} {(v.get('cierres') or [{}])[-1].get('hora', '')}" for k, v in crudo.items()
            if isinstance(v, dict)}


def matriz_mejor(rent: pd.DataFrame, grupo: pd.Series, solape_min: float = SOLAPE_ETF
                 ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(mejor, diaria, semanal): correlaciones de rentabilidades; la mejor toma la semanal si es mayor
    y el par es de mercados distintos (otro huso u otra hora de cierre)."""
    cd = rent.corr(min_periods=max(3, int(solape_min * 252 * 0.5)))
    cw = cambios_semanales(rent, rentabilidad_simple=True).corr(min_periods=max(3, int(solape_min * 52 * 0.5)))
    g = grupo.reindex(rent.columns).fillna("").to_numpy()
    distinto = g[:, None] != g[None, :]
    mejor = cd.where(~(distinto & (cw.fillna(-np.inf) > cd.fillna(-np.inf))), cw)
    return mejor, cd, cw


def grupos_etf(rent: pd.DataFrame, info: pd.DataFrame, *, umbral: float = UMBRAL_ETF,
               solape_min: float = SOLAPE_ETF) -> pd.DataFrame:
    """Grupos de ETF casi idénticos, resumen por ``bucket`` del universo y pares con su equivalente UCITS.

    ``rent``: rentabilidades en ancho (sesión × ticker); ``info``: ``bucket``, ``clase``, ``origen``,
    ``mercado``, ``inicio`` y ``equivalente_ucits`` (id ``yf:...``) por ticker.

    - ``tipo = grupo``: componentes de los pares con correlación >= ``umbral`` (solo positiva),
      Spearman >= ``umbral - MARGEN_SPEARMAN`` y >= ``solape_min`` años; entre mercados distintos
      vale la semanal si es mayor (``base_correlacion``).
    - ``tipo = bucket``: correlación mínima y mediana (la mejor de cada par) dentro del bucket.
    - ``tipo = ucits``: ETF del universo frente a su ``equivalente_ucits``, diaria y semanal.
    """
    cierres = cierre_de_mercado()
    mercado = info["mercado"].astype(str).map(lambda m: cierres.get(m, m))
    pares = pares_correlados(rent, "diaria", umbral=umbral, solape_min=solape_min, absoluta=False, grupo=mercado,
                             rentabilidad_simple=True)
    pares = aristas_alias(pares, umbral, solape_min, absoluta=False)
    mejor, cd, cw = matriz_mejor(rent, mercado, solape_min)
    filas = []

    def _texto(col: str, miembros: list[str]) -> str:
        return "; ".join(sorted({str(info.at[m, col]) for m in miembros if pd.notna(info.at[m, col])
                                 and str(info.at[m, col])}))

    def _comun(miembros: list[str]) -> dict[str, object]:
        cm = mejor.loc[miembros, miembros].to_numpy()[np.triu_indices(len(miembros), k=1)]
        fin = np.isfinite(cm)
        return {"n_miembros": len(miembros), "miembros": "; ".join(miembros), "buckets": _texto("bucket", miembros),
                "clases": _texto("clase", miembros), "origen": _texto("origen", miembros),
                "mercados": _texto("mercado", miembros),
                "inicios": "; ".join(info.at[m, "inicio"].date().isoformat() for m in miembros),
                "corr_min": round(float(np.nanmin(cm)), 4) if fin.any() else np.nan,
                "corr_mediana": round(float(np.nanmedian(cm)), 4) if fin.any() else np.nan,
                "n_pares_umbral": int((cm[fin] >= umbral).sum())}

    for i, g in enumerate(componentes(zip(pares["serie_a"], pares["serie_b"])), start=1):
        miembros = sorted(g, key=lambda t: (info.at[t, "inicio"], t))
        sub = pares[pares["serie_a"].isin(g) & pares["serie_b"].isin(g)]
        filas.append({"tipo": "grupo", "id": f"g{i}", **_comun(miembros),
                      "base_correlacion": "; ".join(sorted(set(sub["base_correlacion"]))),
                      "solape_min_anios": float(sub["anios_solape"].min())})
    uni = info[info["origen"] == "universo"]
    for bucket, g in uni.groupby("bucket"):
        miembros = sorted(t for t in g.index if t in rent.columns)
        if len(miembros) >= 2:
            filas.append({"tipo": "bucket", "id": bucket, **_comun(miembros), "base_correlacion": "mejor"})
    if "equivalente_ucits" in info:
        for t, eq in info["equivalente_ucits"].dropna().items():
            u = str(eq).split(":", 1)[-1]
            if t not in rent.columns or u not in rent.columns or u == t:
                continue
            d, w = cd.at[t, u], cw.at[t, u]
            otro_cierre = mercado.get(t, "") != mercado.get(u, "")
            base = "semanal" if otro_cierre and pd.notna(w) and (pd.isna(d) or w > d) else "diaria"
            filas.append({"tipo": "ucits", "id": f"{t}~{u}", **_comun([t, u]), "base_correlacion": base,
                          "corr_diaria": round(float(d), 4) if pd.notna(d) else np.nan,
                          "corr_semanal": round(float(w), 4) if pd.notna(w) else np.nan})
    return pd.DataFrame(filas, columns=COLUMNAS_ETF)


_CLASE_YAHOO = {"EQUITY": "accion", "ETF": "etf", "CURRENCY": "divisa", "MUTUALFUND": "fondo", "INDEX": "indice",
                "FUTURE": "futuro", "ECNQUOTE": "otro"}


def info_tickers(tablas: Path) -> pd.DataFrame:
    """Clase, bucket, capa, mercado, origen y ``equivalente_ucits`` por ticker, de ``inventario_precios.csv`` (A1).

    ``clase``: la del universo; si el ticker no está en el universo, el tipo de Yahoo (``tipo_yahoo``:
    EQUITY → accion, ETF → etf, CURRENCY → divisa...). Así las clases cuadran con el inventario.
    """
    ruta = tablas / "inventario_precios.csv"
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta}: ejecuta antes el inventario (python -m ingesta.mercados_series inventario)")
    inv = pd.read_csv(ruta, dtype={"ticker": str})
    clase = inv["clase"].where(inv["clase"].notna(), inv["tipo_yahoo"].map(_CLASE_YAHOO)).fillna("sin_clase")
    out = pd.DataFrame({"clase": clase, "bucket": inv["bucket"].fillna(""), "capa": inv["capa"].fillna(""),
                        "mercado": inv["mercado"].fillna(""),
                        "origen": np.where(inv["en_universo"].astype(bool), "universo", "ampliado"),
                        "equivalente_ucits": inv["equivalente_ucits"]})
    out.index = inv["ticker"]
    return out


def medir_precios(tablas: Path, max_tickers: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(métricas por ticker, rentabilidades en ancho de los ETF/ETP) de todos los ficheros de precios."""
    from ingesta.mercados_series import almacen

    info = info_tickers(tablas)
    filas, rent = [], {}
    for proveedor in ("yahoo", "coinbase"):
        tickers = almacen.tickers_guardados(proveedor)
        if max_tickers is not None:
            tickers = tickers[:max_tickers]
        for t in tickers:
            p = almacen.leer_precios(t, proveedor)
            if p.empty:
                continue
            m = metricas_ticker(p)
            if t in info.index:
                d = info.loc[t].to_dict()
                m["mercado"] = d.pop("mercado") or m["mercado"]
            else:
                d = {"clase": "sin_clase", "bucket": "", "capa": "", "origen": "otro", "equivalente_ucits": np.nan}
            filas.append({"ticker": t, "proveedor": proveedor, **d, **m})
            if d["clase"] in CLASES_ETF:
                rent[t] = rentabilidades(p)
    metricas = pd.DataFrame(filas).set_index("ticker")
    return metricas, (pd.DataFrame(rent).sort_index() if rent else pd.DataFrame())


# --- Orden ---------------------------------------------------------------------------------------
def pares_base(largo: pd.DataFrame, meta: pd.DataFrame, *, umbral: float = UMBRAL_PARES,
               solape_min: float = SOLAPE_PARES) -> pd.DataFrame:
    """Pares de ``pares_correlados`` frecuencia a frecuencia (nunca entre frecuencias; sin anuales).

    En las diarias, los pares de fuente o mercado distintos miden también la correlación semanal.
    Añade ``regla_a``/``regla_b`` (la regla aplicada: ``log`` → ``diferencia`` si hay valores <= 0)
    sin tocar ``meta``.
    """
    t0 = time.time()
    grupo = meta["fuente"].astype(str) + "|" + meta.get("mercado", pd.Series("", index=meta.index)).astype(str)
    pares, todas = [], {}
    for f in FRECUENCIAS_PARES:
        ancho, reglas = matriz_cambios(largo, meta, f)
        todas.update(reglas)
        p = pares_correlados(ancho, f, umbral=umbral, solape_min=solape_min, grupo=grupo if f == "diaria" else None)
        log.info("%s: %d series, %d pares (%.0f s)", f, ancho.shape[1], len(p), time.time() - t0)
        pares.append(p)
        del ancho
    pares = [p for p in pares if len(p)]
    out = pd.concat(pares, ignore_index=True) if pares else pd.DataFrame(columns=COLUMNAS_PARES)
    out["regla_a"] = out["serie_a"].map(todas)
    out["regla_b"] = out["serie_b"].map(todas)
    return out


def calcular_series(ruta_base: Path | None = None) -> dict[str, pd.DataFrame]:
    """Tablas 1 a 4 (pares, conceptos, sensibilidad, Banco Mundial y WEO) desde la base guardada."""
    t0 = time.time()
    largo, resumen = leer_base(ruta_base)
    meta = metadatos(resumen)
    log.info("base leída: %d filas de último vintage, %d series (%.0f s)", len(largo), len(meta), time.time() - t0)
    grupos = grupos_concepto(meta)
    concepto_serie = {s: c for s, c in zip(grupos["serie"], grupos["grupo"])}
    pares = pares_base(largo, meta)
    pares.insert(3, "fuente_a", pares["serie_a"].map(meta["fuente"]))
    pares.insert(4, "fuente_b", pares["serie_b"].map(meta["fuente"]))
    pares.insert(5, "misma_fuente", pares["fuente_a"] == pares["fuente_b"])
    ga, gb = pares["serie_a"].map(concepto_serie), pares["serie_b"].map(concepto_serie)
    pares.insert(6, "mismo_concepto", ga.notna() & (ga == gb))
    pares.insert(7, "grupo_concepto", ga.where(pares["mismo_concepto"]).astype("Int64"))
    pares["outlier_dominado"] = outlier_dominado(pares)
    for c in ("pearson", "spearman", "pearson_diaria", "pearson_semanal"):
        pares[c] = pares[c].astype(float).round(4)
    conceptos = tabla_conceptos(grupos, meta, largo)
    log.info("conceptos: %d grupos (%.0f s)", len(conceptos), time.time() - t0)
    return {"redundancia_pares.csv": pares.sort_values("pearson", key=abs, ascending=False),
            "redundancia_conceptos.csv": conceptos,
            "redundancia_sensibilidad.csv": tabla_sensibilidad(pares, meta),
            "redundancia_bm_weo.csv": tabla_bm_weo(meta, grupos)}


def calcular_precios(tablas: Path, max_tickers: int | None = None) -> dict[str, pd.DataFrame]:
    """Tablas 5 (grupos de ETF y sensibilidad de los tickers)."""
    t0 = time.time()
    metricas, rent = medir_precios(tablas, max_tickers)
    log.info("precios: %d tickers, %d ETF/ETP (%.0f s)", len(metricas), rent.shape[1], time.time() - t0)
    etf = grupos_etf(rent, metricas) if rent.shape[1] >= 2 else pd.DataFrame(columns=COLUMNAS_ETF)
    return {"redundancia_etf.csv": etf, "tickers_sensibilidad.csv": tabla_tickers_sensibilidad(metricas)}


def main(argv: list[str] | None = None) -> dict[str, Path]:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--destino", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    p.add_argument("--max-tickers", type=int, default=None, help="solo los N primeros tickers por proveedor (prueba)")
    p.add_argument("--solo", choices=("series", "precios"), default=None)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tablas = resultados_dir(TEMA) / "tablas"
    destino = a.destino or tablas
    destino.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    salidas: dict[str, pd.DataFrame] = {}
    if a.solo in (None, "series"):
        salidas.update(calcular_series())
    if a.solo in (None, "precios"):
        salidas.update(calcular_precios(tablas, a.max_tickers))
    rutas = {}
    for nombre, df in salidas.items():
        rutas[nombre] = destino / nombre
        df.to_csv(rutas[nombre], index=False, encoding="utf-8", lineterminator="\n")
        print(f"{nombre}: {len(df)} filas")
    print(f"tiempo total: {math.ceil(time.time() - t0)} s")
    return rutas


if __name__ == "__main__":
    main()
