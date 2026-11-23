"""Catálogo para los agentes y búsqueda de series del Tema 1 (Fase 2): qué hay, de qué trata y desde cuándo.

Una fila por serie que **queda** en la base curada (``tipo='serie'``), por proyección del SEP
(``tipo='proyeccion'``, se piden con ``get_proyeccion``) y por ticker de ``precios_curados`` (``tipo='precio'``,
se piden con ``get_precios``). **Solo metadatos y fechas**: ningún valor de serie ni precio.

- ``construir_catalogo()`` lo construye desde el corpus (``<corpus>/mercados_series``: base curada, alias,
  proyecciones, manifiesto y precios curados, solo lectura), ``catalogo_series.yaml``, ``lista_curada.yaml``,
  ``universo.yaml``, las tablas del tema y ``config/catalogo_agentes.yaml`` (lo único escrito a mano: reglas de
  tema, zona y agentes, sinónimos y las descripciones de las series clave).
- ``escribir_catalogo()`` / CLI ``python -m ingesta.mercados_series catalogo-agentes``: deja
  ``results/ingesta/mercados_series/tablas/catalogo_agentes.csv`` y ``catalogo_agentes_resumen.csv`` (escritura
  atómica, ``almacen.escribir_csv_atomico``).
- ``cargar_catalogo()`` lee ese CSV del repo (cacheado): la búsqueda funciona **sin el corpus**.
- ``buscar_series(texto, fecha, *, tema, zona, agente, tipo, limite)``: búsqueda por palabras, determinista y sin
  red. Normaliza (minúsculas, sin acentos, singular/plural simple), expande sinónimos del YAML y pondera
  id/alias exacto > nombre > palabras clave (y trozos del id) > descripción > tema. **TimeGate**: no devuelve
  filas cuya ``primera_publicacion`` es posterior a ``fecha`` (no revela que una serie existirá).

Columnas (``COLUMNAS``): ``id`` y ``tipo``; ``alias`` (ids que resuelven a este: tabla de alias de la curada y
alias de la Fase 1, separados por ``|``); ``nombre`` y ``descripcion``; ``tema`` (vocabulario cerrado del YAML)
y ``subtema``; ``zona``, ``frecuencia``, ``unidad``, ``divisa``, ``fuente``, ``clase`` (solo precios);
``desde`` (primera ``fecha_referencia`` o sesión), ``desde_inicial`` (la primera ya visible en la primera
publicación) y ``desde_completo_en`` (cuándo se publicó ``desde``, si la historia se amplió hacia atrás después;
vacío si no), ``primera_publicacion`` (mínima ``fecha_publicacion``: la del TimeGate), ``retraso_tipico_dias``
(series: mediana, por periodo, de la primera publicación menos la fecha de referencia, en los datos publicados en
vivo de los últimos ``ANIOS_RETRASO`` años antes del corte, ver ``_fechas_series``; precios: mediana de
``fecha_publicacion`` menos la sesión, 0 o 1 según el mercado; proyecciones: vacío; **metadato fijo**, no se
recalcula a la fecha de la decisión: orientativo); ``agentes`` (``|``), ``avisos`` (``; ``; los que solo se saben
desde una fecha llevan « [visible desde AAAA-MM-DD]», ver ``_etiquetar``), ``licencia``, ``palabras_clave`` (``|``),
``rol`` (de la lista curada) y ``descripcion_manual``.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from types import EllipsisType
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ingesta.comun.rutas import RESULTS_INGESTA
from ingesta.mercados_series import almacen, timegate, visibilidad
from ingesta.mercados_series.timegate import FechaLike

TEMA = "mercados_series"
RUTA_CONFIG = Path(__file__).resolve().parent / "config" / "catalogo_agentes.yaml"
CARPETA_TABLAS = RESULTS_INGESTA / TEMA / "tablas"
RUTA_CSV = CARPETA_TABLAS / "catalogo_agentes.csv"
RUTA_RESUMEN = CARPETA_TABLAS / "catalogo_agentes_resumen.csv"
# Nombres de empresa: lista pública ticker -> nombre de la SEC (company_tickers.json), guardada en el crudo del tema.
# Es la foto ACTUAL (empresas que hoy presentan informes): el nombre es el de hoy, no el de cada fecha.
SUBRUTA_SEC_TICKERS = ("crudo", "sec", "company_tickers.json")

TIPOS = ("serie", "proyeccion", "precio")
AGENTES = ("macro", "risk", "equity", "portfolio", "cio")
LIMITE_MAX = 50
SEP = "|"
ANIOS_RETRASO = 5      # ventana (años antes del corte) del retraso típico de las series

COLUMNAS = (
    "id", "tipo", "alias", "tambien_como", "nombre", "descripcion", "tema", "subtema", "zona", "frecuencia", "unidad",
    "divisa", "fuente", "clase", "desde", "desde_inicial", "desde_completo_en", "primera_publicacion", "retraso_tipico_dias",
    "agentes", "avisos", "licencia", "palabras_clave", "rol", "descripcion_manual",
)
COLUMNAS_BUSQUEDA = (
    "id", "tipo", "tambien_como", "nombre", "descripcion", "tema", "zona", "frecuencia", "unidad", "divisa", "desde",
    "retraso_tipico_dias", "agentes", "avisos", "puntuacion",
)
COLUMNAS_RESUMEN = ("dimension", "categoria", "n", *(f"n_{t}" for t in TIPOS))
ROLES_SECUNDARIOS = ("historia_previa", "validacion")

# Avisos del curado de precios (precios_curados_avisos.csv) que interesan a un agente, con su texto corto.
AVISOS_PRECIO = {
    "serie_sospechosa": "serie sospechosa del EDA",
    "hueco_largo": "huecos largos sin rellenar (excepción del saneado P28)",
    "no_llega_corte": "no llega al corte: datos atrasados",
    "sin_apertura": "sin apertura: la ejecución en t+1 usa el cierre",
    "mercado_corregido": "mercado de Yahoo corregido al leer",
}
_AVISO_FECHA = {
    "no medible": "fecha de publicación no medible: regla conservadora",
    "no fiable": "fecha de publicación no fiable: regla conservadora",
}
__all__ = [
    "COLUMNAS", "COLUMNAS_BUSQUEDA", "TIPOS", "AGENTES", "RUTA_CSV", "RUTA_RESUMEN", "RUTA_CONFIG",
    "cargar_config", "construir_catalogo", "resumen_catalogo", "escribir_catalogo", "cargar_catalogo", "temas",
    "buscar_series", "normalizar", "main",
]


# --- Configuración ----------------------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _config_cache(ruta: str, _firma: tuple) -> dict[str, Any]:
    cfg = visibilidad.leer_yaml(Path(ruta))
    faltan = [k for k in ("temas", "temas_reglas", "zonas", "agentes_reglas", "plantillas", "busqueda") if k not in cfg]
    if faltan:
        raise ValueError(f"{Path(ruta).name}: faltan las claves {faltan}")
    if tuple(cfg.get("agentes", ())) != AGENTES:
        raise ValueError(f"{Path(ruta).name}: 'agentes' debe ser {list(AGENTES)}")
    for donde in ("temas_reglas", "agentes_reglas"):
        for i, regla in enumerate(cfg[donde]):
            if donde == "temas_reglas" and regla.get("tema") not in cfg["temas"]:
                raise ValueError(f"{Path(ruta).name}: {donde}[{i}] con tema fuera del vocabulario: {regla.get('tema')!r}")
            if donde == "agentes_reglas" and not set(regla.get("agentes", ())) <= set(AGENTES):
                raise ValueError(f"{Path(ruta).name}: {donde}[{i}] con agentes desconocidos: {regla.get('agentes')}")
    return cfg


def cargar_config(ruta: Path | None = None) -> dict[str, Any]:
    """``config/catalogo_agentes.yaml`` validado (cacheado por fecha y tamaño del fichero)."""
    r = Path(ruta) if ruta is not None else RUTA_CONFIG
    return _config_cache(str(r.resolve()), visibilidad.firma(r))


# --- Normalización del texto ------------------------------------------------------------------------------
def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


# Palabras que no se pasan a singular (acabadas en -s o -es sin ser plurales): «estrés» no es «€STR».
_INVARIABLES = frozenset({"estres", "interes", "mes", "pais", "crisis", "tesis", "analisis", "dosis", "bonus"})


def _singular(p: str) -> str:
    """Singular simple y simétrico (se aplica igual a la búsqueda y a los campos): tipos→tipo, acciones→accion."""
    if not p.isalpha() or len(p) < 4 or p in _INVARIABLES or p.endswith(("is", "us", "ss")):
        return p
    if len(p) >= 6 and p.endswith("es") and p[-3] in "rlndzj":
        return p[:-2]
    if p.endswith("ises"):
        return p[:-2]
    return p[:-1] if p.endswith("s") else p


def normalizar(texto: Any) -> list[str]:
    """Palabras de ``texto``: minúsculas, sin acentos, solo letras y números, en singular simple."""
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return []
    t = _sin_acentos(str(texto)).lower().replace("&", " ")
    return [_singular(p) for p in re.findall(r"[a-z0-9]+", t)]


def _frase(texto: Any) -> str:
    return " ".join(normalizar(texto))


# --- Reglas del YAML --------------------------------------------------------------------------------------
def _cumple(fila: dict[str, Any], si: dict[str, Any] | None) -> bool:
    for campo, cond in (si or {}).items():
        valor = fila.get(campo)
        if isinstance(cond, list):
            if valor not in cond:
                return False
        elif isinstance(cond, str) and cond.startswith("~"):
            if valor is None or not re.search(cond[1:], str(valor), re.IGNORECASE):
                return False
        elif valor != cond:
            return False
    return True


def _zona_pareja(unidad: Any) -> str | None:
    """Zona de un tipo de cambio 'X por 1 Y': la divisa que no es USD (si está) o que no es EUR."""
    m = re.fullmatch(r"([A-Z]{3}) por 1 ([A-Z]{3})", str(unidad or ""))
    if not m:
        return None
    pareja = (m.group(1), m.group(2))
    base = "USD" if "USD" in pareja else "EUR"
    otra = next((d for d in pareja if d != base), None)
    if otra is None:
        return None
    return "EA" if otra == "EUR" else otra[:2]


def _zona(fila: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    for regla in cfg["zonas"]:
        if not _cumple(fila, regla.get("si")):
            continue
        z = regla["zona"]
        if z == "$pais":
            bruto = fila.get("_pais")
            z = cfg["zona_codigos"].get(bruto) if bruto else None
            if z is None and bruto and re.fullmatch(r"[A-Z]{2}", bruto):
                z = bruto
        elif z == "$pareja":
            z = _zona_pareja(fila.get("unidad"))
        elif z == "$mercado":
            z = cfg["zona_mercado"].get(fila.get("mercado"))
        if z:
            return z
    return None


def _clasificar(fila: dict[str, Any], cfg: dict[str, Any]) -> None:
    """Fija tema, subtema, zona y agentes de ``fila`` con las reglas del YAML (``ValueError`` si falta alguno)."""
    regla = next((r for r in cfg["temas_reglas"] if _cumple(fila, r.get("si"))), None)
    if regla is None:
        raise ValueError(f"{fila['id']}: ninguna regla de temas_reglas le da tema")
    fila["tema"], fila["subtema"] = regla["tema"], regla.get("subtema")
    fila["zona"] = _zona(fila, cfg)
    if not fila["zona"]:
        raise ValueError(f"{fila['id']}: ninguna regla de zonas le da zona")
    agentes = {a for r in cfg["agentes_reglas"] if _cumple(fila, r.get("si")) for a in r["agentes"]}
    if not agentes:
        raise ValueError(f"{fila['id']}: ninguna regla de agentes_reglas le da agentes")
    fila["agentes"] = SEP.join(a for a in AGENTES if a in agentes)


def _unir(partes: Iterable[Any], sep: str = SEP) -> str:
    vistos: list[str] = []
    for p in partes:
        if p is None or (isinstance(p, float) and np.isnan(p)):
            continue
        p = str(p).strip()
        if p and p not in vistos:
            vistos.append(p)
    return sep.join(vistos)


def _describir(fila: dict[str, Any], cfg: dict[str, Any], manuales: dict[str, str]) -> None:
    if fila["id"] in manuales:
        fila["descripcion"], fila["descripcion_manual"] = " ".join(str(manuales[fila["id"]]).split()), True
        return
    datos = {
        "nombre": fila["nombre"], "unidad": fila["unidad"], "frecuencia": fila["frecuencia"],
        "fuente": cfg["nombres_fuente"].get(fila["fuente"], fila["fuente"]), "divisa": fila.get("divisa") or "-",
        "clase": cfg["nombres_clase"].get(fila.get("clase"), fila.get("clase")),
        "mercado": cfg["nombres_mercado"].get(fila.get("mercado"), fila.get("mercado")),
        "uso": cfg["temas"][fila["tema"]],
    }
    fila["descripcion"], fila["descripcion_manual"] = cfg["plantillas"][fila["tipo"]].format(**datos), False


def _palabras(fila: dict[str, Any], cfg: dict[str, Any], extra: Iterable[str] = ()) -> str:
    partes = [fila["tema"].replace("_", " ")]
    if fila.get("subtema"):
        partes.append(fila["subtema"].replace("_", " "))
    partes += [fila["zona"], *cfg["zona_nombres"].get(fila["zona"], [])]
    partes.append(cfg["nombres_fuente"].get(fila["fuente"], fila["fuente"]))
    if fila.get("clase"):
        partes.append(cfg["nombres_clase"].get(fila["clase"], fila["clase"]))
    if fila.get("bucket"):
        partes.append(str(fila["bucket"]).replace("_", " "))
    if fila.get("mercado"):
        partes.append(cfg["nombres_mercado"].get(fila["mercado"], fila["mercado"]))
    partes += list(extra)
    partes += cfg.get("palabras_por_id", {}).get(fila["id"], [])
    return _unir(partes)


# --- Lectura del corpus (solo lectura) ------------------------------------------------------------------
def _fecha_txt(x: Any) -> str | None:
    return None if x is None or pd.isna(x) else pd.Timestamp(x).date().isoformat()


def _fechas_series(ruta: Path, corte: pd.Timestamp | None = None) -> pd.DataFrame:
    """Por serie: ``desde``, ``primera_publicacion`` y ``retraso_tipico_dias`` (sin leer ningún valor).

    El retraso típico es el de un dato NUEVO: mediana, por periodo, de su primera ``fecha_publicacion`` menos su
    ``fecha_referencia``, en los periodos publicados en vivo (después de la primera publicación de la serie, que
    carga la historia de golpe) con referencia en los ``ANIOS_RETRASO`` años anteriores a ``corte``; si no hay
    ninguno, en todos los publicados en vivo; y si tampoco, en todos.
    """
    t = pq.read_table(ruta, columns=["serie", "fecha_referencia", "fecha_publicacion"], read_dictionary=["serie"])
    df = t.to_pandas()
    p = df.groupby(["serie", "fecha_referencia"], observed=True, sort=False)["fecha_publicacion"].min().reset_index()
    p["serie"] = p["serie"].astype(str)
    p["dias"] = (p["fecha_publicacion"] - p["fecha_referencia"]).dt.days
    g = p.groupby("serie")
    vivo = p["fecha_publicacion"] > g["fecha_publicacion"].transform("min")
    corte = pd.Timestamp(corte) if corte is not None else p["fecha_referencia"].max()
    reciente = p["fecha_referencia"] >= corte - pd.DateOffset(years=ANIOS_RETRASO)
    retraso = p[vivo & reciente].groupby("serie")["dias"].median()
    retraso = retraso.combine_first(p[vivo].groupby("serie")["dias"].median()).combine_first(g["dias"].median())
    out = _desde_y_ultima(p.rename(columns={"fecha_referencia": "ref"}), "serie")
    out["retraso_tipico_dias"] = retraso.round(1)
    return out


def _desde_y_ultima(p: pd.DataFrame, clave: str) -> pd.DataFrame:
    """De ``p`` (una fila por ``clave`` y ``ref`` con su primera ``fecha_publicacion``): ``desde``, ``desde_inicial``
    (primera referencia ya visible en la primera publicación), ``desde_completo_en`` (publicación en que se vio
    ``desde``: una historia ampliada hacia atrás después; nulo si coincide con la primera), ``primera_publicacion``,
    ``ultima_publicacion`` y ``dias_retirada`` (``tools.dias_sin_publicar_retirada``). Las dos últimas no se
    escriben: sirven para fechar los avisos (``_etiquetar``)."""
    from ingesta.mercados_series import tools

    g = p.groupby(clave)
    pp = g["fecha_publicacion"].transform("min")
    desde = g["ref"].min()
    out = pd.DataFrame({"desde": desde, "primera_publicacion": g["fecha_publicacion"].min()})
    out["desde_inicial"] = p[p["fecha_publicacion"] == pp].groupby(clave)["ref"].min()
    completo = p[p["ref"] == p[clave].map(desde)].groupby(clave)["fecha_publicacion"].min()
    out["desde_completo_en"] = completo.where(out["desde_inicial"] != out["desde"])
    out["ultima_publicacion"] = g["fecha_publicacion"].max()
    out["dias_retirada"] = g["ref"].apply(tools.dias_sin_publicar_retirada)
    return out


def _fechas_precios(carpeta: Path, tickers: Iterable[str]) -> pd.DataFrame:
    partes, retraso = [], {}
    for tk in tickers:
        d = pq.read_table(carpeta / f"{almacen.nombre_fichero_ticker(tk)}.parquet",
                          columns=["sesion", "fecha_publicacion"]).to_pandas()
        partes.append(d.rename(columns={"sesion": "ref"}).assign(ticker=tk))
        retraso[tk] = float((d["fecha_publicacion"] - d["sesion"]).dt.days.median())
    out = _desde_y_ultima(pd.concat(partes, ignore_index=True), "ticker")
    out["retraso_tipico_dias"] = pd.Series(retraso)
    return out


def _componentes_indices(carpeta: Path, cfg: dict[str, Any]) -> dict[str, list[str]]:
    """``{ticker de Yahoo: [«componente del <índice>», ...]}`` y el nombre de la empresa (foto actual)."""
    out: dict[str, list[str]] = {}
    nombres: dict[str, str] = {}
    for indice, conf in cfg.get("constituyentes", {}).items():
        ruta = carpeta / f"{indice}.parquet"
        if not ruta.exists():
            continue
        cols = [c for c in ("ticker", "nombre") if c in pq.read_schema(ruta).names]
        d = pq.read_table(ruta, columns=cols).to_pandas()
        for _, r in d.iterrows():
            tk = str(r["ticker"]).strip()
            if conf.get("ceros"):
                tk = tk.zfill(int(conf["ceros"]))
            if conf.get("punto_por_guion"):
                tk = tk.replace(".", "-")
            if conf.get("sufijo") and not tk.endswith(conf["sufijo"]):
                tk += conf["sufijo"]
            out.setdefault(tk, []).append(f"componente del {conf['nombre']}")
            if "nombre" in r and isinstance(r["nombre"], str) and r["nombre"].strip():
                nombres.setdefault(tk, r["nombre"].strip())
    out["_nombres"] = nombres  # type: ignore[assignment]
    return out


# --- Construcción -----------------------------------------------------------------------------------------
def _alias_por_canonico(cat: dict[str, dict], alias_curada: pd.DataFrame, canonicos: set[str]) -> dict[str, list[str]]:
    """Ids que resuelven a cada canónico: alias de la curada y alias de la Fase 1 (también los de un alias)."""
    from ingesta.mercados_series import tools

    curada = dict(zip(alias_curada["alias"].astype(str), alias_curada["canonico"].astype(str), strict=True))
    out: dict[str, set[str]] = {}
    for a, c in curada.items():
        if c in canonicos:
            out.setdefault(c, set()).add(a)
    for a, sid in tools.alias_por_defecto().items():
        c = curada.get(sid, sid)
        if c in canonicos and a != c:
            out.setdefault(c, set()).add(a)
    return {c: sorted(v) for c, v in out.items()}


# --- Avisos con fecha (TimeGate del catálogo) --------------------------------------------------------------
# Un aviso que solo se sabe desde una fecha (la retirada de una serie, una serie o un ticker que nombra y que aún no
# existía, una nota con una fecha posterior) se guarda en el CSV con la etiqueta « [visible desde AAAA-MM-DD]» y
# ``buscar_series`` solo lo sirve, sin la etiqueta, en una fecha igual o posterior.
ETIQUETA_VISIBLE = " [visible desde {}]"
_PATRON_ETIQUETA = re.compile(r"\s*\[visible desde (\d{4}-\d{2}-\d{2})\]$")
_PATRON_FECHA = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_PATRON_ID = re.compile(r"[\w.^=:\-&]+")
Aviso = tuple[str, "pd.Timestamp | None", bool]   # (texto, visible desde, ¿cuentan sus fechas ISO?)


def _retirada_en(f: pd.Series) -> pd.Timestamp:
    """Desde cuándo se sabe que una serie o un ticker dejó de publicarse (``tools._aviso_retirada``)."""
    return pd.Timestamp(f["ultima_publicacion"]) + pd.Timedelta(days=int(f["dias_retirada"]))


def _etiquetar(avisos: list[Aviso], propia: pd.Timestamp, primeras: dict[str, pd.Timestamp]) -> str:
    """Avisos unidos por ``'; '``, con la etiqueta de visibilidad en los que se saben después de ``propia`` (la
    primera publicación de la fila): la fecha dada, las fechas ISO del texto (si cuentan) y la primera publicación
    de los ids del catálogo que nombra."""
    out = []
    for texto, desde, con_fechas in avisos:
        fechas = [desde] if desde is not None else []
        if con_fechas:
            fechas += [pd.Timestamp(d) for d in _PATRON_FECHA.findall(texto)]
        fechas += [primeras[t.rstrip(".,;:)")] for t in _PATRON_ID.findall(texto) if t.rstrip(".,;:)") in primeras]
        visible = max(fechas) if fechas else None
        out.append(texto + (ETIQUETA_VISIBLE.format(visible.date().isoformat())
                            if visible is not None and visible > propia else ""))
    return _unir(out, "; ")


def avisos_en_fecha(avisos: Any, fecha: pd.Timestamp) -> str | None:
    """Los avisos de una fila del CSV que se sabían en ``fecha``, sin las etiquetas de visibilidad."""
    if avisos is None or (isinstance(avisos, float) and np.isnan(avisos)) or not str(avisos):
        return None
    quedan = []
    for a in str(avisos).split("; "):
        m = _PATRON_ETIQUETA.search(a)
        if m is None:
            quedan.append(a)
        elif pd.Timestamp(m.group(1)) <= fecha:
            quedan.append(a[:m.start()])
    return "; ".join(quedan) or None


def _avisos_a_mano(fila: dict[str, Any], cfg: dict[str, Any]) -> list[Aviso]:
    """Avisos de ``avisos_reglas`` del YAML que cumple la fila (qué usar antes de una serie que se ve tarde)."""
    return [(str(r["aviso"]), None, True) for r in cfg.get("avisos_reglas", []) if _cumple(fila, r.get("si"))]


def _avisos_serie(sid: str, e: dict[str, Any], lc: dict[str, Any], historia_de: dict[str, list[str]],
                  homogeneizadas: set[str], fechas: pd.Series) -> list[Aviso]:
    av: list[Aviso] = []

    def poner(texto: str, desde: pd.Timestamp | None = None, con_fechas: bool = False) -> None:
        av.append((texto, desde, con_fechas))

    if lc.get("decision") == "proyecciones":
        poner("proyección: se pide con get_proyeccion (última edición visible por año)")
    if lc.get("rol") == "historia_previa" and lc.get("completa_a"):
        poner(f"historia previa de {lc['completa_a']}")          # visible desde la primera publicación de completa_a
    elif lc.get("rol") == "validacion":
        poner("serie de validación: hay otra canónica del mismo concepto")
    for previa in historia_de.get(sid, []):
        poner(f"su historia anterior está en {previa}")
    if lc.get("canonico_dudoso"):
        poner("canónico dudoso")
    if e.get("estado") == "retirada":
        poner("retirada: la fuente dejó de publicarla" + (f" (sucesora {e['sucesor']})" if e.get("sucesor") else ""),
              _retirada_en(fechas))
    elif e.get("estado") == "capada":
        poner("historia recortada por la fuente")
    if e.get("publicado_desde"):
        poner(f"reconstruida hacia atrás: no se publicaba antes de {e['publicado_desde']}")
    if lc.get("aviso_fecha") in _AVISO_FECHA:
        poner(_AVISO_FECHA[lc["aviso_fecha"]])
    tramo = lc.get("tramo_conservador_antes_de")
    if tramo:
        poner("fechas conservadoras en toda la historia" if str(tramo) == "toda"
              else f"tramo conservador antes de {tramo}")
    if e.get("metodo") == "vintage_exacto":
        previa = (e.get("regla_previa_alfred") or {}).get("primer_vintage")
        poner("vintages exactos de ALFRED" + (f" (antes de {previa}, valor del primer vintage: posible fuga de "
                                              "revisiones)" if previa else ""))
    elif e.get("revisable"):
        poner("revisable sin vintages: posible fuga de revisiones")
    if sid in homogeneizadas:
        poner("escala homogeneizada en la curada")
    if lc.get("nota"):
        for parte in str(lc["nota"]).split("; "):                # una nota con «; » son varios avisos
            poner(parte, con_fechas=True)
    return av


def _filas_series(cfg: dict[str, Any], *, ruta_curada: Path, ruta_proyecciones: Path, ruta_alias: Path,
                  ruta_manifiesto: Path, registro: Callable[[str], Any]) -> list[dict[str, Any]]:
    from ingesta.mercados_series import catalogo, inventario, preprocesado

    cat = catalogo.cargar_catalogo()
    lista = preprocesado.cargar_lista()
    manifiesto = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
    homogeneizadas = set(manifiesto.get("resumen", {}).get("homogeneizadas", []))
    quedan = sorted(s for s, v in lista.items() if v.get("decision") == "queda")
    proyecciones = sorted(s for s, v in lista.items() if v.get("decision") == "proyecciones")

    registro(f"fechas de la base curada: {ruta_curada}")
    corte = manifiesto.get("corte_g2")
    fechas = _fechas_series(ruta_curada, pd.Timestamp(corte) if corte else None)
    if set(fechas.index) != set(quedan):
        raise RuntimeError(f"la base curada no cuadra con la lista curada: sobran {sorted(set(fechas.index) - set(quedan))[:5]}"
                           f", faltan {sorted(set(quedan) - set(fechas.index))[:5]}")
    esperadas = manifiesto.get("resumen", {}).get("series_curada")
    if esperadas is not None and esperadas != len(quedan):
        raise RuntimeError(f"el manifiesto dice {esperadas} series y la lista curada {len(quedan)}")
    fechas_p = _fechas_series(ruta_proyecciones)
    fechas_p["retraso_tipico_dias"] = np.nan          # una proyección se publica antes de su año: no aplica
    if set(fechas_p.index) != set(proyecciones):
        raise RuntimeError(f"proyecciones.parquet no cuadra con la lista curada: {sorted(fechas_p.index)} != {proyecciones}")

    alias = _alias_por_canonico(cat, almacen.leer_alias(ruta_alias), set(quedan) | set(proyecciones))
    historia_de: dict[str, list[str]] = {}
    for sid in quedan:
        if lista[sid].get("rol") == "historia_previa" and lista[sid].get("completa_a"):
            historia_de.setdefault(lista[sid]["completa_a"], []).append(sid)
    manuales = cfg.get("descripciones", {})
    filas = []
    for tipo, ids, f in (("serie", quedan, fechas), ("proyeccion", proyecciones, fechas_p)):
        for sid in ids:
            e, lc = cat[sid], lista[sid]
            comp = e.get("componentes") or []
            fila = {
                "id": sid, "tipo": tipo, "alias": SEP.join(alias.get(sid, [])), "nombre": e["nombre"],
                "frecuencia": e["frecuencia"], "unidad": e["unidad"], "divisa": e.get("divisa"),
                "fuente": e["fuente"], "clase": None, "licencia": e.get("licencia"), "rol": lc.get("rol"),
                "grupo": e.get("grupo"), "clave": sid in manuales,
                "_pais": inventario.pais_zona(sid, e["fuente"], [inventario.pais_zona(c, cat.get(c, {}).get("fuente"))
                                                                for c in comp]),
                **_columnas_fechas(f.loc[sid]),
                "_avisos": _avisos_serie(sid, e, lc, historia_de, homogeneizadas, f.loc[sid]),
            }
            _clasificar(fila, cfg)
            fila["_avisos"] += _avisos_a_mano(fila, cfg)
            _describir(fila, cfg, manuales)
            fila["palabras_clave"] = _palabras(fila, cfg, [e.get("release")] if e.get("release") else [])
            filas.append(fila)
    return filas


def nombres_sec(ruta: Path) -> dict[str, str]:
    """Ticker (formato Yahoo, ``BRK-B``) -> nombre de empresa de la lista de la SEC; vacío si no está el fichero."""
    if not ruta.exists():
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    nombres: dict[str, str] = {}
    for e in datos.values():
        tk = str(e.get("ticker", "")).upper().replace(".", "-")
        if tk and e.get("title") and tk not in nombres:
            nombres[tk] = str(e["title"]).strip()
    return nombres


def _nombre_precio(tk: str, clase: str, universo_fila: dict[str, Any] | None, cat: dict[str, dict],
                   nombres_comp: dict[str, str], nombres_sec_: dict[str, str] | None = None) -> str:
    if universo_fila and universo_fila.get("nombre"):
        return str(universo_fila["nombre"])
    e = cat.get(f"yf:{tk}")
    if e:
        return re.sub(r"\s*\(cierre ajustado de Yahoo\)$", "", e["nombre"])
    if tk in nombres_comp:
        return f"{nombres_comp[tk]} ({tk})"
    if clase == "accion" and nombres_sec_ and tk in nombres_sec_:
        return f"{nombres_sec_[tk]} ({tk})"
    return f"Acción {tk}" if clase == "accion" else tk


def _columnas_fechas(f: pd.Series) -> dict[str, Any]:
    return {"desde": _fecha_txt(f["desde"]), "desde_inicial": _fecha_txt(f["desde_inicial"]),
            "desde_completo_en": _fecha_txt(f["desde_completo_en"]),
            "primera_publicacion": _fecha_txt(f["primera_publicacion"]), "retraso_tipico_dias": f["retraso_tipico_dias"]}


# Avisos del curado de precios que dicen cómo ACABA la historia: solo se saben cuando ya ha acabado.
_AVISOS_PRECIO_FINAL = ("no_llega_corte",)


def _avisos_precio(tk: str, lp: dict[str, Any], u: dict[str, Any] | None, avisos_curado: dict[str, list[str]],
                   fechas: pd.Series) -> list[Aviso]:
    av: list[Aviso] = []
    if lp.get("aviso"):
        for parte in str(lp["aviso"]).split("; "):
            av.append((parte, None, True))
    if lp.get("truncado"):
        av.append(("historia recortada", None, False))
    if lp.get("deslistado"):
        av.append(("deslistado", _retirada_en(fechas), False))
    for tipo in avisos_curado.get(tk, []):
        av.append((AVISOS_PRECIO[tipo], _retirada_en(fechas) if tipo in _AVISOS_PRECIO_FINAL else None, False))
    clase = lp.get("clase")
    if clase in ("indice", "volatilidad"):
        av.append(("índice: no invertible (señal y contexto)", None, False))
    elif clase == "futuro":
        av.append(("futuro continuo de Yahoo sin roll documentado: solo contexto", None, False))
    elif u is not None and clase in ("etf", "etp", "fondo") and u.get("invertible_minorista_ue") is False:
        av.append(("no invertible para un minorista de la UE (sin KID): señal y referencia", None, False))
        if u.get("equivalente_ucits"):     # visible desde la primera sesión del equivalente (_etiquetar)
            av.append((f"equivalente UCITS {str(u['equivalente_ucits']).removeprefix('yf:')}", None, False))
    if lp.get("alias_de"):
        av.append((f"alias informativo de {lp['alias_de']}", None, False))
    return av


def _filas_precios(cfg: dict[str, Any], *, carpeta_precios: Path, carpeta_constituyentes: Path,
                   registro: Callable[[str], Any], ruta_sec: Path | None = None) -> list[dict[str, Any]]:
    from ingesta.mercados_series import catalogo, curada_precios, universo

    cat = catalogo.cargar_catalogo()
    lista = curada_precios.cargar_lista_precios()
    quedan = {t for t, v in lista.items() if v.get("decision") == "queda"}
    inv = pd.read_csv(CARPETA_TABLAS / "inventario_precios.csv", dtype=str, keep_default_na=False)
    inv = inv.set_index("ticker")
    uni = {i["id"]: i for i in universo.cargar_universo()["instrumentos"]}
    av = pd.read_csv(CARPETA_TABLAS / "precios_curados_avisos.csv", dtype=str, keep_default_na=False)
    av = av[av["tipo"].isin(AVISOS_PRECIO)]
    avisos_curado = {tk: sorted(set(g["tipo"])) for tk, g in av.groupby("ticker")}
    comp = _componentes_indices(carpeta_constituyentes, cfg)
    nombres_comp = comp.pop("_nombres")  # type: ignore[arg-type]
    sec = nombres_sec(ruta_sec) if ruta_sec is not None else {}
    sec.update(cfg.get("nombres_a_mano", {}))      # acciones que la SEC no lista (no estadounidenses)
    manuales = cfg.get("descripciones", {})
    series_ids = set(cat)

    filas = []
    por_proveedor: dict[str, list[str]] = {}
    for prov in sorted(p.name for p in carpeta_precios.iterdir() if p.is_dir()):
        tks = almacen.tickers_guardados(prov, carpeta_precios / prov)
        por_proveedor[prov] = tks
    guardados = {tk for tks in por_proveedor.values() for tk in tks}
    if guardados != quedan:
        raise RuntimeError(f"precios_curados no cuadra con la lista curada: sobran {sorted(guardados - quedan)[:5]}, "
                           f"faltan {sorted(quedan - guardados)[:5]}")
    for prov, tks in por_proveedor.items():
        registro(f"fechas de {len(tks)} tickers de {prov}")
        fechas = _fechas_precios(carpeta_precios / prov, tks)
        for tk in tks:
            lp = lista[tk]
            r = inv.loc[tk] if tk in inv.index else pd.Series(dtype=str)
            u = uni.get(r.get("id_universo")) if r.get("id_universo") else None
            clase = lp.get("clase")
            divisa = r.get("divisa") or (u or {}).get("divisa")
            id_u = r.get("id_universo")
            alias = [id_u] if id_u and id_u != tk and id_u not in series_ids else []
            fila = {
                "id": tk, "tipo": "precio", "alias": SEP.join(alias),
                "nombre": _nombre_precio(tk, clase, u, cat, nombres_comp, sec), "frecuencia": "diaria",
                "unidad": cfg["unidades_precio"][clase].format(divisa=divisa or "-"), "divisa": divisa,
                "fuente": prov, "clase": clase, "licencia": cfg["licencias_precio"][prov], "rol": None,
                "grupo": None, "clave": tk in manuales, "bucket": r.get("bucket") or None,
                "mercado": r.get("mercado") or (u or {}).get("mercado"),
                **_columnas_fechas(fechas.loc[tk]),
                "_avisos": _avisos_precio(tk, lp, u, avisos_curado, fechas.loc[tk]),
            }
            _clasificar(fila, cfg)
            fila["_avisos"] += _avisos_a_mano(fila, cfg)
            _describir(fila, cfg, manuales)
            extra = list(comp.get(tk, []))
            if u:
                extra += [u.get("indice_referencia"), u.get("capa")]
            fila["palabras_clave"] = _palabras(fila, cfg, extra)
            filas.append(fila)
    return filas


def _gemelos(df: pd.DataFrame) -> pd.Series:
    """El mismo dato con la otra tool: ``yf:X`` (serie, get_serie) <-> ``X`` (precio, get_precios)."""
    series = set(df.loc[df["tipo"] == "serie", "id"])
    precios = set(df.loc[df["tipo"] == "precio", "id"])

    def gemelo(fila: pd.Series) -> str | None:
        if fila["tipo"] == "precio" and f"yf:{fila['id']}" in series:
            return f"yf:{fila['id']}"
        if fila["tipo"] == "serie" and str(fila["id"]).startswith("yf:") and fila["id"][3:] in precios:
            return fila["id"][3:]
        return None
    return df.apply(gemelo, axis=1)


def construir_catalogo(*, registro: Callable[[str], Any] | None = None) -> pd.DataFrame:
    """Catálogo para los agentes (``COLUMNAS``) desde el corpus curado (solo lectura) y los YAML del tema.

    Una fila por serie que queda en la base curada, por proyección y por ticker de ``precios_curados``.
    ``RuntimeError`` si la curada, la lista curada, el manifiesto y los precios curados no cuadran; ``ValueError``
    si a una fila no le da tema, zona o agentes ninguna regla del YAML.
    """
    log = registro or (lambda _m: None)
    cfg = cargar_config()
    carpeta = almacen.corpus_dir(TEMA)
    series = carpeta / "series"
    filas = _filas_series(cfg, ruta_curada=series / almacen.FICHERO_SERIES_CURADA,
                          ruta_proyecciones=series / almacen.FICHERO_PROYECCIONES,
                          ruta_alias=series / almacen.FICHERO_ALIAS, ruta_manifiesto=series / "curada_manifiesto.json",
                          registro=log)
    filas += _filas_precios(cfg, carpeta_precios=carpeta / almacen.CARPETA_PRECIOS_CURADOS,
                            carpeta_constituyentes=carpeta / "constituyentes", registro=log,
                            ruta_sec=carpeta.joinpath(*SUBRUTA_SEC_TICKERS))
    primeras = {f["id"]: pd.Timestamp(f["primera_publicacion"]) for f in filas}
    for f in filas:
        f["avisos"] = _etiquetar(f.pop("_avisos"), primeras[f["id"]], primeras)
    df = pd.DataFrame(filas).reindex(columns=list(COLUMNAS))
    df["retraso_tipico_dias"] = pd.to_numeric(df["retraso_tipico_dias"], errors="coerce").astype(float)
    df["descripcion_manual"] = df["descripcion_manual"].astype(bool)
    df["tambien_como"] = _gemelos(df)
    duplicados = df.loc[df["id"].duplicated(), "id"].tolist()
    if duplicados:
        raise RuntimeError(f"ids duplicados en el catálogo: {duplicados[:10]}")
    orden = {t: i for i, t in enumerate(TIPOS)}
    df = df.sort_values(["tipo", "id"], key=lambda s: s.map(orden) if s.name == "tipo" else s, kind="mergesort")
    return df.reset_index(drop=True)


def resumen_catalogo(df: pd.DataFrame) -> pd.DataFrame:
    """Recuentos por tipo, tema, agente y zona (``COLUMNAS_RESUMEN``), con el desglose por tipo."""
    filas = []
    largo = df.assign(agente=df["agentes"].str.split(SEP)).explode("agente")
    for dimension, tabla, col in (("tipo", df, "tipo"), ("tema", df, "tema"), ("agente", largo, "agente"),
                                  ("zona", df, "zona")):
        cuenta = pd.crosstab(tabla[col], tabla["tipo"]).reindex(columns=list(TIPOS), fill_value=0)
        for valor, r in cuenta.sort_index().iterrows():
            filas.append({"dimension": dimension, "categoria": valor, "n": int(r.sum()),
                          **{f"n_{t}": int(r[t]) for t in TIPOS}})
    return pd.DataFrame(filas, columns=list(COLUMNAS_RESUMEN))


def escribir_catalogo(df: pd.DataFrame | None = None, *, registro: Callable[[str], Any] | None = None
                      ) -> dict[str, Path]:
    """Escribe ``catalogo_agentes.csv`` y ``catalogo_agentes_resumen.csv`` (atómicos, sin columnas de valores)."""
    df = construir_catalogo(registro=registro) if df is None else df
    rutas = {"catalogo": almacen.escribir_csv_atomico(df, RUTA_CSV),
             "resumen": almacen.escribir_csv_atomico(resumen_catalogo(df), RUTA_RESUMEN)}
    _catalogo_csv_cache.cache_clear()
    _indice_cache.cache_clear()
    return rutas


# --- Lectura del CSV y búsqueda ---------------------------------------------------------------------------
_TEXTO = [c for c in COLUMNAS if c not in ("retraso_tipico_dias", "descripcion_manual")]


@lru_cache(maxsize=2)
def _catalogo_csv_cache(ruta: str, _firma: tuple) -> pd.DataFrame:
    df = pd.read_csv(ruta, dtype={c: "string" for c in _TEXTO}, keep_default_na=False, na_values={
        "retraso_tipico_dias": [""]})
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan:
        raise ValueError(f"{Path(ruta).name}: faltan columnas {faltan} (regenerar: catalogo-agentes)")
    for c in _TEXTO:
        df[c] = df[c].astype(object).where(df[c] != "", None)
    df["retraso_tipico_dias"] = pd.to_numeric(df["retraso_tipico_dias"], errors="coerce").astype(float)
    df["descripcion_manual"] = df["descripcion_manual"].astype(str).str.lower().eq("true")
    return df[list(COLUMNAS)]


def cargar_catalogo(ruta: Path | None = None) -> pd.DataFrame:
    """``catalogo_agentes.csv`` del repo (cacheado; copia). No necesita el corpus."""
    r = Path(ruta) if ruta is not None else RUTA_CSV
    if not r.exists():
        raise FileNotFoundError(f"no está {r}: python -m ingesta.mercados_series catalogo-agentes")
    return _catalogo_csv_cache(str(r.resolve()), visibilidad.firma(r)).copy()


def temas() -> list[str]:
    """Vocabulario cerrado de temas (``config/catalogo_agentes.yaml``)."""
    return list(cargar_config()["temas"])


def _campo(textos: Iterable[Any]) -> np.ndarray:
    return np.array([f" {_frase(t)} " for t in textos], dtype=object)


@lru_cache(maxsize=2)
def _indice_cache(ruta: str, _firma: tuple, ruta_cfg: str, _firma_cfg: tuple) -> dict[str, Any]:
    df = _catalogo_csv_cache(ruta, _firma)
    exactos, trozos = [], []
    for sid, alias in zip(df["id"], df["alias"], strict=True):
        formas = {_frase(sid), _frase(sid.split(":", 1)[1] if ":" in sid else sid)}
        formas |= {_frase(a) for a in (alias or "").split(SEP) if a}
        formas.discard("")
        exactos.append("|" + "|".join(sorted(formas)) + "|")
        trozos.append(" ".join(sorted(formas)))
    palabras = [f"{p or ''} {t}" for p, t in zip(df["palabras_clave"].str.replace(SEP, " . ", regex=False)
                                                   .fillna(""), trozos, strict=True)]
    return {
        "exactos": np.array(exactos, dtype=object), "nombre": _campo(df["nombre"]), "palabras": _campo(palabras),
        "descripcion": _campo(df["descripcion"]),
        "tema": _campo(df["tema"].fillna("") + " " + df["subtema"].fillna("").str.replace("_", " ")),
        "primera_publicacion": pd.to_datetime(df["primera_publicacion"]).to_numpy(),
    }


def _sinonimos(cfg: dict[str, Any]) -> list[tuple[tuple[str, ...], list[tuple[str, ...]]]]:
    out = []
    for clave, alternativas in cfg["busqueda"].get("sinonimos", {}).items():
        k = tuple(normalizar(clave))
        alts = [tuple(normalizar(a)) for a in alternativas]
        out.append((k, [a for a in alts if a and a != k]))
    return sorted(out, key=lambda x: (-len(x[0]), x[0]))


def _conceptos(texto: str, cfg: dict[str, Any]) -> list[list[tuple[str, float]]]:
    """Términos de la búsqueda; cada uno con sus alternativas (la propia, peso 1; sus sinónimos, ``sinonimo``)."""
    palabras = normalizar(texto)
    vacias = {_singular(_sin_acentos(str(v)).lower()) for v in cfg["busqueda"].get("vacias", [])}
    w = float(cfg["busqueda"]["pesos"]["sinonimo"])
    sinonimos = _sinonimos(cfg)
    conceptos, i = [], 0
    while i < len(palabras):
        for clave, alts in sinonimos:
            if tuple(palabras[i:i + len(clave)]) == clave:
                conceptos.append([(" ".join(clave), 1.0), *((" ".join(a), w) for a in alts)])
                i += len(clave)
                break
        else:
            if palabras[i] not in vacias:
                conceptos.append([(palabras[i], 1.0)])
            i += 1
    return conceptos


def _puntuar(idx: dict[str, Any], filas: np.ndarray, texto: str, cfg: dict[str, Any],
             df: pd.DataFrame) -> np.ndarray:
    p = cfg["busqueda"]["pesos"]
    conceptos = _conceptos(texto, cfg)
    n = len(filas)
    if not conceptos:
        return np.zeros(n)
    total = np.zeros(n)
    aciertos = np.zeros(n)
    campos = (("nombre", p["nombre"]), ("palabras", p["palabras_clave"]), ("descripcion", p["descripcion"]),
              ("tema", p["tema"]))
    for concepto in conceptos:
        mejor = np.zeros(n)
        for alt, w in concepto:
            patron = f" {alt} "
            s = np.where([f"|{alt}|" in x for x in idx["exactos"][filas]], float(p["id_alias"]), 0.0)
            for campo, peso in campos:
                s = np.maximum(s, np.where([patron in x for x in idx[campo][filas]], float(peso), 0.0))
            mejor = np.maximum(mejor, s * w)
        total += mejor
        aciertos += mejor > 0
    puntos = total * aciertos / len(conceptos)
    entera = _frase(texto)
    puntos += np.where([f"|{entera}|" in x for x in idx["exactos"][filas]], float(p["exacto_total"]), 0.0)
    hay = puntos > 0
    # La prima de las series clave solo si casan TODOS los términos: con uno solo («zona euro»), una serie clave de
    # otro concepto (la curva AAA) se colaba en cabeza de muchas búsquedas.
    clave = df["descripcion_manual"].to_numpy()[filas] & (aciertos == len(conceptos))
    secundaria = df["rol"].isin(ROLES_SECUNDARIOS).to_numpy()[filas]
    puntos = puntos + hay * (clave * float(p["clave"]) + secundaria * float(p["secundaria"]))
    return np.where(hay, np.round(puntos, 3), 0.0)


def _validar_opcion(valor: Any, validos: Iterable[str], nombre: str) -> None:
    validos = list(validos)
    if valor is not None and valor not in validos:
        raise ValueError(f"{nombre}={valor!r} no válido; opciones: {validos}")


def _clave_filtro(valor: Any, cfg: dict[str, Any]) -> str:
    vacias = {_singular(_sin_acentos(str(v)).lower()) for v in cfg["busqueda"].get("vacias", [])}
    return " ".join(p for p in normalizar(str(valor).replace("_", " ")) if p not in vacias)


def _resolver_filtro(valor: Any, opciones: Iterable[str], nombre: str, cfg: dict[str, Any],
                     nombres: dict[str, Iterable[str]] | None = None) -> str | None:
    """``valor`` tal cual si es una opción; si no, la opción con la misma forma normalizada (sin acentos ni
    mayúsculas, singular, sin palabras vacías: «tipos de interés» → ``tipos_interes``) o con ese nombre
    (``zona_nombres``: «zona euro» → ``EA``). ``ValueError`` si no hay ninguna."""
    if valor is None:
        return None
    opciones = list(opciones)
    for v in (valor, str(valor).strip().upper(), str(valor).strip().lower()):
        if v in opciones:
            return v
    clave = _clave_filtro(valor, cfg)
    for o in opciones:
        if clave and (clave == _clave_filtro(o, cfg)
                      or clave in {_clave_filtro(n, cfg) for n in (nombres or {}).get(o, [])}):
            return o
    raise ValueError(f"{nombre}={valor!r} no válido; opciones: {opciones}")


def buscar_series(texto: str | None = None, fecha: FechaLike | EllipsisType = ..., *, tema: str | None = None,
                  zona: str | None = None, agente: str | None = None, tipo: str | None = None,
                  limite: int = 10) -> pd.DataFrame:
    """Series, proyecciones y precios del catálogo que encajan con ``texto``, tal como se conocían en ``fecha``.

    ``fecha`` es obligatoria (``timegate.fecha_decision``: día natural ISO ``'AAAA-MM-DD'``, ``date`` o
    ``Timestamp`` a medianoche): solo salen filas con ``primera_publicacion <= fecha``. Filtros opcionales:
    ``tema`` (``temas()``; también sin acentos ni guiones bajos: «tipos de interés»), ``zona`` (código, p. ej.
    ``'EA'``, o un nombre de ``zona_nombres``: «zona euro», «EE. UU.»), ``agente`` (``AGENTES``) y ``tipo``
    (``TIPOS``); ``ValueError`` si no son válidos. Con ``texto``: búsqueda por palabras con sinónimos (``config/catalogo_agentes.yaml``), ordenada
    por ``puntuacion`` (desc.) y por ``id``; sin texto (o vacío), todas las filas filtradas por ``id`` y con
    puntuación 0. ``limite`` entre 1 y ``LIMITE_MAX`` (50). Devuelve ``COLUMNAS_BUSQUEDA``; ``desde`` como texto
    ``AAAA-MM-DD``. Lee el CSV del repo: no necesita el corpus ni la red.

    TimeGate también en los metadatos: los ``avisos`` con etiqueta « [visible desde D]» solo salen (sin ella) si
    ``D <= fecha`` (``avisos_en_fecha``), y ``desde`` es ``desde_inicial`` mientras la historia ampliada hacia atrás
    (``desde_completo_en``) aún no se había publicado. ``retraso_tipico_dias`` es un metadato fijo (últimos
    ``ANIOS_RETRASO`` años antes del corte): orientativo, no se recalcula a la fecha.
    """
    if fecha is ...:
        raise TypeError("buscar_series: falta la fecha de decisión (fecha='AAAA-MM-DD')")
    f = timegate.fecha_decision(fecha)
    if isinstance(limite, bool) or not isinstance(limite, (int, np.integer)) or not 1 <= int(limite) <= LIMITE_MAX:
        raise ValueError(f"limite={limite!r} no válido: entero entre 1 y {LIMITE_MAX}")
    if texto is not None and not isinstance(texto, str):
        raise ValueError(f"texto={texto!r} no válido: texto o None")
    cfg = cargar_config()
    if not RUTA_CSV.exists():
        raise FileNotFoundError(f"no está {RUTA_CSV}: python -m ingesta.mercados_series catalogo-agentes")
    clave_csv = (str(RUTA_CSV.resolve()), visibilidad.firma(RUTA_CSV))
    df = _catalogo_csv_cache(*clave_csv)          # sin copiar: solo se copia la parte que se devuelve
    tema = _resolver_filtro(tema, temas(), "tema", cfg)
    zona = _resolver_filtro(zona, sorted(df["zona"].dropna().unique()), "zona", cfg, cfg.get("zona_nombres"))
    _validar_opcion(agente, AGENTES, "agente")
    _validar_opcion(tipo, TIPOS, "tipo")
    idx = _indice_cache(*clave_csv, str(RUTA_CONFIG.resolve()), visibilidad.firma(RUTA_CONFIG))
    mascara = idx["primera_publicacion"] <= f.to_datetime64()
    if tema is not None:
        mascara &= (df["tema"] == tema).to_numpy()
    if zona is not None:
        mascara &= (df["zona"] == zona).to_numpy()
    if tipo is not None:
        mascara &= (df["tipo"] == tipo).to_numpy()
    if agente is not None:
        mascara &= df["agentes"].fillna("").str.split(SEP).apply(lambda a: agente in a).to_numpy()
    filas = np.flatnonzero(mascara)
    sub = df.iloc[filas].copy()
    if texto is not None and texto.strip() and _conceptos(texto, cfg):
        sub["puntuacion"] = _puntuar(idx, filas, texto, cfg, df)
        sub = sub[sub["puntuacion"] > 0].sort_values(["puntuacion", "id"], ascending=[False, True], kind="mergesort")
    else:
        sub["puntuacion"] = 0.0
        sub = sub.sort_values("id", kind="mergesort")
    # Serie y precio del mismo instrumento (``tambien_como``): sale solo el mejor colocado, con el otro id anotado.
    # El gemelo solo se anota si ya era visible en f (si no, ni siquiera está en ``sub``).
    visibles = set(df["id"].iloc[filas])
    gem = sub["tambien_como"].where(sub["tambien_como"].isin(visibles))
    vistos: set[str] = set()
    quedan = []
    for i, g in zip(sub["id"], gem, strict=True):
        quedan.append(i not in vistos)
        if isinstance(g, str):
            vistos.add(g)
        vistos.add(i)
    quedan_ = np.array(quedan, dtype=bool)        # lista vacía: pandas la leería como selección de columnas
    sub = sub[quedan_].assign(tambien_como=gem[quedan_]).head(int(limite)).copy()
    # TimeGate de los metadatos: avisos que aún no se sabían fuera, y ``desde`` de la historia ya publicada en f.
    sub["avisos"] = [avisos_en_fecha(a, f) for a in sub["avisos"]]
    ampliada = pd.to_datetime(sub["desde_completo_en"])
    sub["desde"] = sub["desde"].where(~(ampliada > f), sub["desde_inicial"])
    return sub[list(COLUMNAS_BUSQUEDA)].reset_index(drop=True)


# --- CLI --------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingesta.mercados_series catalogo-agentes",
                                description="catálogo para los agentes (series, proyecciones y precios; sin valores)")
    p.add_argument("--sin-escribir", action="store_true", help="construye y valida sin escribir los CSV")
    a = p.parse_args(argv)
    df = construir_catalogo(registro=print)
    if a.sin_escribir:
        print("ensayo (--sin-escribir): no se escribe nada")
    else:
        for nombre, ruta in escribir_catalogo(df).items():
            print(f"{nombre} -> {ruta}")
    print(df["tipo"].value_counts().reindex(list(TIPOS)).to_dict())
    print({"descripciones_a_mano": int(df["descripcion_manual"].sum())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
