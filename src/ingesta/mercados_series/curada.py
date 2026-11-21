"""Base curada de series del Tema 1 (paso 4 de la descarga completa): aplica el plan sin tocar la base de trabajo.

``python -m ingesta.mercados_series curar`` lee la base de trabajo (``series/base_series.parquet``, solo lectura y
solo las series que hacen falta), le aplica ``config/lista_curada.yaml`` y ``config/preprocesado.yaml`` con las
funciones de ``preprocesado`` (no se reimplementa ninguna regla de fecha) y escribe en el corpus, junto a la base:

- ``series/base_curada.parquet``: mismo contrato que la base (``contrato.validar_series``). Solo las series
  ``decision: queda`` (también las de ``rol: historia_previa``), con:
  - la fecha curada de ``preprocesado.fechas_curadas`` (E4, tramo E5, H.15 antes de 2005, reconstruidas y externas,
    tope del primer vintage); ``disponible_utc`` nulo donde la fecha cambia (solo se conoce el día);
  - las escalas por vintage (``escalas_por_vintage``: los vintages anteriores, por su factor);
  - la homogeneización (``homogeneizacion``): las ``escalas`` (tanto por uno → %, ×100, con su ``unidad_nueva``; la
    volatilidad realizada después de recalcularla) y las ``unidades_equivalentes`` con su nombre canónico; las de
    ``sin_escalar`` no se tocan;
  - las derivadas (``deriv:*``, ``calculo_propio``) recalculadas con sus componentes curados: las diferencias con
    ``base.derivar_diferencias`` y la volatilidad realizada con la fórmula de ``fuentes.fase1`` (fecha = la máxima de
    los componentes que entran en cada valor). Las primeras sesiones de 1928 de ``deriv:VOLREAL21_GSPC`` que trae
    ``data/raw`` con menos de 21 rentabilidades no salen (no son una volatilidad de 21 sesiones) y se cuentan aparte;
  - una ``nota`` por cada cambio (``NOTA_*``), añadida a la que ya tuviera la fila;
  - el **corte G2** (``CORTE_G2``): fuera toda fila con ``fecha_publicacion`` curada posterior.
- ``series/alias.parquet``: alias → canónico, con su rol, decisión, regla, motivo y correlación
  (``lista_curada.yaml`` y ``tablas/redundancia_pares.csv``). Solo metadatos.
- ``series/proyecciones.parquet``: las filas de las series ``decision: proyecciones``
  (``preprocesado.separar_proyecciones``: columnas del contrato más ``horizonte`` y ``edicion``), con el mismo corte.
- ``series/registro_cambios.parquet``: una fila por cada fila con fecha, ``disponible_utc``, escala o unidad cambiada
  (antes y después, capa y regla, tope, factor y unidad), también las que después quita el corte
  (``en_base_curada = False``).
- ``series/curada_manifiesto.json``: firma (tamaño, ``mtime_ns`` y sha256) de ``base_series.parquet``,
  ``lista_curada.yaml`` y ``preprocesado.yaml``, el corte, la fecha, las salidas (filas y sha256) y las verificaciones.

Y en el repo (solo metadatos, ningún valor): ``tablas/curada_verificaciones.csv`` (las verificaciones de
``salidas_paso4``, todas con ``filas_fallan = 0``) y ``tablas/curada_resumen.csv`` (una fila por serie).

**Si alguna verificación falla, la orden aborta**: solo escribe ``tablas/curada_verificaciones.csv`` con el fallo y no
publica nada en el corpus. Las salidas del corpus se escriben en una carpeta temporal de ``series/`` y se publican
juntas (``_publicar_conjunto``: las anteriores se apartan y, si un renombrado falla, vuelven todas; el manifiesto va el
último). La orden es idempotente: con la misma base y los mismos YAML da los mismos ficheros (salvo la fecha del
manifiesto). La base de trabajo no se abre nunca para escribir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, catalogo, timegate
from ingesta.mercados_series import base as base_mod
from ingesta.mercados_series import preprocesado as pp
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, FECHA, UTC, primera_decision_vec, validar_series
from ingesta.mercados_series.fuentes import fase1

__all__ = [
    "CORTE_G2", "NOTA_CONSERVADORA", "NOTA_TRAMO", "NOTA_TOPE", "NOTA_PENDIENTE", "NOTA_H15", "NOTA_PUBLICADO_DESDE",
    "NOTA_DERIVADA", "NOTA_ESCALA", "COLUMNAS_REGISTRO", "COLUMNAS_ALIAS_CURADA", "COLUMNAS_VERIFICACIONES",
    "COLUMNAS_RESUMEN", "VERIFICACIONES", "ErrorCuracion", "Curada", "ids_derivadas", "escalas_vintage",
    "recalcular_derivadas", "tabla_alias", "homogeneizar", "firma", "construir", "escribir", "curar", "main",
]

TEMA = "mercados_series"
# G2 (PLAN_DESCARGA.md, paso 3b, aprobada el 2026-11-19): fecha de corte del dataset, el último viernes con cierre
# completo antes del 3b-1. Las fuentes acaban entre el 11-16 y el 11-19, así que todas lo cubren. La base curada y
# las proyecciones no llevan nada con fecha_publicacion (curada) posterior; la base de trabajo y el crudo sí lo
# guardan, para el siguiente refresco.
CORTE_G2 = __import__("ingesta.mercados_series.corte", fromlist=["corte_vigente"]).corte_vigente()  # P07

FICHERO_REGISTRO = "registro_cambios.parquet"
FICHERO_MANIFIESTO = "curada_manifiesto.json"
PREFIJO_NUEVO = ".curada_nuevo_"     # carpeta temporal de una publicación (en series/)
PREFIJO_PREVIA = ".curada_previa_"   # copia de la publicación anterior mientras se cambia
_REINTENTOS = 5
TABLA_VERIFICACIONES = "curada_verificaciones.csv"
TABLA_RESUMEN = "curada_resumen.csv"
TABLA_SIMULACION = pp.TABLA_SIMULACION
TOLERANCIA_DERIVADA = base_mod.TOLERANCIA_DERIVADA
FECHAS_TRUNCADO = ("2001-01-02", "2008-09-15", "2020-03-16", "2024-06-03")   # más CORTE_G2
SERIES_TRUNCADO = 25   # series de muestra para la prueba de truncado (las de más filas, orden fijo)

# Notas que se añaden a la de la fila (con «; », como base._anotar). Sin valores: solo de dónde sale la fecha.
# Contrato con el modo curado de tools.py: cada parte añadida contiene «fecha no medible», «tramo conservador» o
# «escala corregida» (así la reconocen las tools y la separan de las notas de la base de trabajo).
NOTA_CONSERVADORA = "fecha no medible: regla conservadora"
NOTA_TRAMO = "tramo conservador"
NOTA_TOPE = "parada en el primer vintage de ALFRED"
NOTA_PENDIENTE = "fecha no medible: regla conservadora pendiente de calendario (fecha sin cambiar)"
NOTA_H15 = "tramo conservador de H.15 diario"
NOTA_PUBLICADO_DESDE = "tramo conservador: índice reconstruido, fecha llevada a publicado_desde"
NOTA_DERIVADA = ("tramo conservador: derivada recalculada con sus componentes curados (fecha = la máxima de los "
                 "componentes)")
NOTA_ESCALA = "escala corregida"

COLUMNAS_REGISTRO = (
    "serie", "fecha_referencia", "vintage", "fecha_publicacion_antes", "fecha_publicacion_despues",
    "disponible_utc_antes", "disponible_utc_despues", "retraso_dias", "capa", "seccion", "grupo", "regla",
    "capa1", "h15", "reconstruida", "derivada", "escala", "homogeneizacion", "con_tope", "factor_escala",
    "unidad_antes", "unidad_despues", "en_base_curada")
COLUMNAS_ALIAS_CURADA = (
    "alias", "canonico", "rol", "decision", "regla", "motivo", "aviso_fecha", "rol_canonico", "correlacion",
    "spearman", "frecuencia_correlacion", "n_correlacion", "anios_solape", "base_correlacion", "origen_correlacion")
COLUMNAS_VERIFICACIONES = ("verificacion", "descripcion", "comprobadas", "filas_fallan", "detalle")
COLUMNAS_RESUMEN = (
    "serie", "rol", "seccion", "regla", "filas", "filas_cambiadas", "filas_escaladas", "filas_cortadas",
    "retraso_mediana_dias", "retraso_max_dias", "desde", "hasta", "publicada_desde", "publicada_hasta")
VERIFICACIONES = {   # salidas_paso4.verificaciones de preprocesado.yaml, en el mismo orden
    "no_adelanta": "ninguna fecha_publicacion curada anterior a la original (antes de y después del corte)",
    "disponible_coherente": "disponible_utc nulo o con primera decisión igual a la fecha curada",
    "orden_vintages": "en cada serie y fecha_referencia, ordenadas por la fecha original, la curada no baja",
    "truncado": "fecha_publicacion >= fecha_referencia, nada posterior al corte G2 y TimeGate en una muestra "
                "(lo visible en una fecha no cambia al quitar lo publicado después)",
    "recuentos_lista": "series de la base curada = las «queda» de lista_curada.yaml (con historia_previa); sin alias "
                       "ni proyecciones dentro",
    "recuentos_alias": "filas de la tabla de alias = alias de lista_curada.yaml; cada canónico en la base curada",
    "recuentos_proyecciones": "series de proyecciones = proyecciones.esperadas de preprocesado.yaml",
    "exactas_sin_cambio": "las filas vintage_exacto y cierre_mercado no cambian por las capas 1 y 2",
    "posteriores_sin_cambio": "las filas publicadas después del corte del tramo (capa 1) o de H.15 (capa 2) no cambian",
    "unidades_homogeneizadas": "homogeneizacion de preprocesado.yaml: escalas a su unidad_nueva, unidades equivalentes "
                               "con su nombre canónico y sin_escalar sin tocar",
    "derivadas": "derivadas recalculadas con sus componentes curados: fecha = la máxima de los componentes, valor del "
                 "cálculo y las mismas claves que en la base de trabajo",
    "simulacion": "registro de cambios y simulación del paso 3 (tablas/preprocesado_simulacion.csv): mismos recuentos",
    "contrato": "la base curada pasa contrato.validar_series (sin errores)",
}

_COLS_TEXTO = ("serie", "vintage", "unidad", "divisa", "fuente", "metodo_publicacion", "nota")
_PATRON_CORR = re.compile(r"(?:\|Pearson\||correlación mínima) (-?\d+(?:\.\d+)?)")


class ErrorCuracion(RuntimeError):
    """Alguna verificación del paso 4 falla: no se escribe nada."""

    def __init__(self, verificaciones: pd.DataFrame):
        self.verificaciones = verificaciones
        malas = verificaciones[verificaciones["filas_fallan"] != 0]
        super().__init__("verificaciones que fallan: " + "; ".join(
            f"{r.verificacion} ({r.filas_fallan}: {r.detalle})" for r in malas.itertuples()))


@dataclass
class Curada:
    """Lo que construye ``construir`` (todo en memoria; ``escribir`` lo lleva al disco)."""

    base: pd.DataFrame
    alias: pd.DataFrame
    proyecciones: pd.DataFrame
    registro: pd.DataFrame
    verificaciones: pd.DataFrame
    resumen: pd.DataFrame
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def correcta(self) -> bool:
        return bool((self.verificaciones["filas_fallan"] == 0).all())


# --- Piezas ----------------------------------------------------------------------------------------------------
def _num(x: float) -> str:
    """Factor en texto con coma decimal: 1000.0 → '1000'; 0.001 → '0,001'."""
    return f"{x:g}".replace(".", ",")


def ids_derivadas(lista: dict[str, dict], catalogo_series: dict[str, dict]) -> list[str]:
    """Series «queda» que son derivadas del catálogo (``metodo: derivada``): se recalculan, no se curan fila a fila."""
    return sorted(s for s, e in lista.items()
                  if e.get("decision") == "queda" and catalogo_series.get(s, {}).get("metodo") == "derivada")


def _componentes(derivadas: Iterable[str], catalogo_series: dict[str, dict]) -> list[str]:
    return sorted({c for s in derivadas for c in catalogo_series[s].get("componentes") or []})


def escalas_vintage(serie: np.ndarray, vintage: np.ndarray, plan: dict[str, Any]) -> np.ndarray:
    """Factor de cada fila según ``escalas_por_vintage``: ``factor`` en los vintages anteriores a
    ``antes_de_vintage`` de su serie, 1 en el resto (el orden de texto ISO es el temporal, como en ``simular``)."""
    f = np.ones(len(serie), dtype=float)
    for e in plan["escalas_por_vintage"]["series"] or []:
        m = (serie == e["serie"]) & (vintage < str(e["antes_de_vintage"]))
        f[m] = float(e["factor"])
    return f


def homogeneizar(serie: np.ndarray, unidad: np.ndarray,
                 plan: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``homogeneizacion`` de ``preprocesado.yaml`` fila a fila: ``(factor, unidad nueva, nota)``.

    - ``escalas``: las series de la lista con esa ``unidad`` se multiplican por ``factor`` y pasan a ``unidad_nueva``
      (tanto por uno → %); las de ``sin_escalar`` no se tocan.
    - ``unidades_equivalentes``: una unidad de la lista distinta de la ``canonica`` se renombra (mismo significado).
    ``nota`` es ``None`` donde nada cambia. Se calcula una vez por par (serie, unidad).
    """
    ho = plan["homogeneizacion"]
    escalas = {sid: e for e in ho["escalas"] or [] for sid in e["series"]}
    equivalentes = {u: par["canonica"] for par in ho["unidades_equivalentes"] or [] for u in par["unidades"]
                    if u != par["canonica"]}
    pares = pd.DataFrame({"s": serie, "u": pd.Series(unidad, dtype=object).fillna("")})
    codigos, unicos = pd.factorize(pd.MultiIndex.from_frame(pares))
    f_u, u_u, n_u = [], [], []
    for sid, u in unicos:
        e = escalas.get(sid)
        if e is not None and u == e["unidad"]:
            f_u.append(float(e["factor"]))
            u_u.append(e["unidad_nueva"])
            n_u.append(f"{NOTA_ESCALA}: ×{_num(float(e['factor']))}, de «{u}» a «{e['unidad_nueva']}» "
                       "(preprocesado.yaml, homogeneizacion.escalas)")
        elif u in equivalentes:
            f_u.append(1.0)
            u_u.append(equivalentes[u])
            n_u.append(f"{NOTA_ESCALA}: unidad «{u}» renombrada a «{equivalentes[u]}», mismo significado "
                       "(preprocesado.yaml, homogeneizacion.unidades_equivalentes)")
        else:
            f_u.append(1.0)
            u_u.append(u or None)
            n_u.append(None)
    return (np.asarray(f_u, dtype=float)[codigos], np.asarray(u_u, dtype=object)[codigos],
            np.asarray(n_u, dtype=object)[codigos])


def _nota_capa1(plan: dict[str, Any], seccion: str, grupo: str | None, regla: str, sid: str) -> str:
    if seccion == "tramo_no_fiable":
        t = plan["tramo_no_fiable"]["series"][sid]
        donde = f"antes de {t['corte']}" if t.get("corte") not in (None, "toda") else "en toda la serie"
        return (f"{NOTA_TRAMO} {donde}: regla {regla} + {t['dias_extra']} días ({t['veredicto']}, "
                "preprocesado.yaml, tramo_no_fiable, E5)")
    return f"{NOTA_CONSERVADORA} {regla} (grupo {grupo}, preprocesado.yaml, E4)"


def _unir(previa: np.ndarray, nueva: np.ndarray) -> np.ndarray:
    """``previa; nueva`` fila a fila (``nueva`` sola si no hay ``previa``; ``previa`` sola si no hay ``nueva``)."""
    return np.array([n if not isinstance(p, str) else (p if not isinstance(n, str) else f"{p}; {n}")
                     for p, n in zip(previa, nueva, strict=True)], dtype=object)


def _notas_nuevas(serie: np.ndarray, cur: pd.DataFrame, plan: dict[str, Any], factor: np.ndarray,
                  desde: dict[str, str]) -> np.ndarray:
    """Texto que se añade a la nota de cada fila (``None`` si ninguno), por capas y en orden fijo."""
    extra = np.full(len(serie), None, dtype=object)

    def _sumar(ix: np.ndarray, textos: np.ndarray) -> None:
        if len(ix):
            extra[ix] = _unir(extra[ix], textos)

    sec = cur["seccion"].to_numpy(dtype=object)
    con = pd.notna(sec)
    if con.any():
        claves = pd.DataFrame({"s": sec[con], "g": cur["grupo"].to_numpy(dtype=object)[con],
                               "r": cur["regla"].to_numpy(dtype=object)[con], "i": serie[con]}).fillna("-")
        codigos, unicos = pd.factorize(pd.MultiIndex.from_frame(claves))
        textos = np.array([_nota_capa1(plan, s, None if g == "-" else g, r, i) for s, g, r, i in unicos], dtype=object)
        t = textos[codigos]
        t = np.where(cur["pendiente"].to_numpy()[con], NOTA_PENDIENTE, t).astype(object)
        tope = cur["con_tope"].to_numpy()[con]
        t[tope] = np.array([f"{x} ({NOTA_TOPE})" for x in t[tope]], dtype=object)
        _sumar(np.flatnonzero(con), t)
    h = plan["h15_diario"]
    h15 = np.flatnonzero(cur["h15"].to_numpy())
    _sumar(h15, np.full(len(h15), f"{NOTA_H15} antes de {h['hasta']}: {h['conservadora'].get('lag', '')} más "
                                  "(preprocesado.yaml, h15_diario)", dtype=object))
    rec = np.flatnonzero(cur["reconstruida"].to_numpy())
    _sumar(rec, np.array([f"{NOTA_PUBLICADO_DESDE} {desde[s]}: antes no se publicaba (preprocesado.yaml, "
                          "reconstruidas)" for s in serie[rec]], dtype=object))
    esc = np.flatnonzero(factor != 1)
    antes = {e["serie"]: str(e["antes_de_vintage"]) for e in plan["escalas_por_vintage"]["series"] or []}
    _sumar(esc, np.array([f"{NOTA_ESCALA} ×{_num(f)} (vintage anterior a {antes[s]}: cambio de unidad entre "
                          "vintages, preprocesado.yaml, escalas_por_vintage)"
                          for s, f in zip(serie[esc], factor[esc], strict=True)], dtype=object))
    return extra


def _anadir(nota: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """``nota; extra`` (o solo ``extra`` si la fila no tenía nota). Idempotente: no repite un texto que ya está."""
    out = nota.astype(object).copy()
    m = np.flatnonzero(pd.notna(extra))
    if not len(m):
        return out
    nueva = np.array([None if isinstance(p, str) and x in p else x for p, x in zip(out[m], extra[m], strict=True)],
                     dtype=object)
    out[m] = _unir(out[m], nueva)
    return out


def _vol_realizada(sid: str, entrada: dict[str, Any], comp: pd.DataFrame) -> pd.DataFrame:
    """Volatilidad realizada (``fase1.VOL_REALIZADA``) de toda la serie, con la fórmula de
    ``fase1.vol_realizada``. Fecha de cada valor: la máxima de las ``n + 1`` sesiones del componente que
    entran en él (``disponible_utc`` igual, nulo si alguna lo es)."""
    _, n, _ = fase1.VOL_REALIZADA[sid]
    c = comp[comp["valor"].notna()].sort_values("fecha_referencia", kind="mergesort").reset_index(drop=True)
    filas = fase1.vol_realizada(sid, entrada, c, pd.Timestamp.min)
    if filas.empty:
        return filas
    dias = pd.Series(c["fecha_publicacion"].to_numpy(dtype="datetime64[D]").astype("int64"), dtype=float)
    seg = pd.Series(c["disponible_utc"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[s]")
                    .astype("int64"), dtype=float).where(c["disponible_utc"].notna().to_numpy())
    fp_max = dias.rolling(n + 1, min_periods=n + 1).max()
    disp_max = seg.rolling(n + 1, min_periods=n + 1).max()
    pos = pd.Index(c["fecha_referencia"]).get_indexer(filas["fecha_referencia"])
    filas["fecha_publicacion"] = pd.to_datetime(fp_max.to_numpy()[pos].astype("int64"), unit="D").to_numpy(FECHA)
    d = disp_max.to_numpy()[pos]
    filas["disponible_utc"] = pd.Series(pd.to_datetime(d, unit="s", utc=True)).where(~np.isnan(d)).astype(UTC).array
    return filas


def recalcular_derivadas(comp: pd.DataFrame, ids: Iterable[str],
                         catalogo_series: dict[str, dict]) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Filas del contrato de las derivadas ``ids`` con sus componentes curados ``comp`` (contrato de series).

    Diferencias ``A − B``: ``base.derivar_diferencias`` (fecha y ``disponible_utc`` = los más tardíos de los
    componentes, ``contrato.fecha_publicacion_derivada``). Volatilidad realizada: ``_vol_realizada``. Devuelve
    ``(filas, info)``; ``info[id]['recalculada']`` es ``False`` (con su motivo) si no se pudo.
    """
    out, info = [], {}
    for sid in sorted(ids):
        e = catalogo_series[sid]
        if sid in fase1.VOL_REALIZADA:
            c = comp[comp["serie"] == fase1.VOL_REALIZADA[sid][0]]
            if c.empty:
                info[sid] = {"recalculada": False, "motivo": "sin el componente"}
                continue
            filas = _vol_realizada(sid, e, c)
            info[sid] = {"recalculada": True, "componentes": [fase1.VOL_REALIZADA[sid][0]], "n_filas": len(filas)}
        else:
            nuevo, inf = base_mod.derivar_diferencias(comp[comp["serie"].isin(e.get("componentes") or [])],
                                                      {sid: e})
            info[sid] = inf.get(sid, {"recalculada": False, "motivo": "no es una diferencia A − B del catálogo"})
            if not info[sid].get("recalculada"):
                continue
            filas = nuevo[nuevo["serie"] == sid]
        out.append(filas[list(COLUMNAS_SERIES)])
    if not out:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNAS_SERIES.items()}), info
    return pd.concat(out, ignore_index=True), info


def tabla_alias(lista: dict[str, dict], pares: pd.DataFrame | None = None) -> pd.DataFrame:
    """Alias → canónico (``COLUMNAS_ALIAS_CURADA``), una fila por serie ``decision: alias`` de la lista.

    La correlación es la del par en ``redundancia_pares.csv`` (si hay varias frecuencias, la de mayor |Pearson|);
    si el par no está (duplicadas del catálogo, conceptos confirmados, versiones de Eurostat), la que cita el motivo
    o nula. Solo metadatos.
    """
    filas = []
    p = pares if pares is not None else pd.DataFrame(columns=["serie_a", "serie_b"])
    for sid, e in sorted(lista.items()):
        if e.get("decision") != "alias":
            continue
        can = e.get("alias_de")
        fila = {"alias": sid, "canonico": can, "rol": e.get("rol"), "decision": e["decision"], "regla": e.get("regla"),
                "motivo": e.get("motivo"), "aviso_fecha": e.get("aviso_fecha"),
                "rol_canonico": lista.get(can, {}).get("rol"), "correlacion": np.nan, "spearman": np.nan,
                "frecuencia_correlacion": None, "n_correlacion": np.nan, "anios_solape": np.nan,
                "base_correlacion": None, "origen_correlacion": None}
        m = (((p["serie_a"] == sid) & (p["serie_b"] == can)) | ((p["serie_b"] == sid) & (p["serie_a"] == can)))
        if len(p) and m.any():
            r = p[m].assign(_abs=p.loc[m, "pearson"].abs()).sort_values(["_abs", "frecuencia"],
                                                                         ascending=[False, True]).iloc[0]
            fila.update(correlacion=float(r["pearson"]), spearman=float(r["spearman"]),
                        frecuencia_correlacion=r["frecuencia"], n_correlacion=float(r["n"]),
                        anios_solape=float(r["anios_solape"]), base_correlacion=r.get("base_correlacion"),
                        origen_correlacion="redundancia_pares")
        else:
            c = _PATRON_CORR.search(str(e.get("motivo") or ""))
            if c:
                fila.update(correlacion=float(c.group(1)), origen_correlacion="motivo")
        filas.append(fila)
    t = pd.DataFrame(filas, columns=list(COLUMNAS_ALIAS_CURADA))
    for c in ("correlacion", "spearman", "n_correlacion", "anios_solape"):
        t[c] = t[c].astype(float)
    return t


# --- Construcción ----------------------------------------------------------------------------------------------
def _texto_obj(s: pd.Series | np.ndarray) -> np.ndarray:
    a = pd.Series(s).astype(object).to_numpy()
    return np.where(pd.isna(a), None, a)


def _comparar_simulacion(sim: pd.DataFrame | None, cuentas: dict[tuple, dict[str, float]]) -> tuple[int, int, str]:
    """``(comprobadas, distintas, detalle)``: cada recuento de ``sim`` que tiene su par en ``cuentas``."""
    if sim is None:
        return 0, 1, "falta tablas/preprocesado_simulacion.csv"
    distintas, comprobadas, ejemplos = 0, 0, []
    for r in sim.itertuples(index=False):
        clave = (r.seccion, None if pd.isna(r.grupo) else r.grupo, None if pd.isna(r.regla) else r.regla)
        mio = cuentas.get(clave)
        if mio is None:
            if r.seccion in ("reglas_conservadoras", "tramo_no_fiable") and not r.pendiente_calendario:
                distintas += 1
                ejemplos.append(f"{clave}: sin filas en la curada")
            continue
        for campo, valor in mio.items():
            s = getattr(r, campo)
            if pd.isna(s):
                continue
            comprobadas += 1
            if int(s) != int(valor):
                distintas += 1
                ejemplos.append(f"{'/'.join(str(x) for x in clave if x)}.{campo}: simulación {int(s)}, curada {int(valor)}")
    return comprobadas, distintas, "; ".join(ejemplos[:5]) or "mismos recuentos"


def _fila_ver(nombre: str, comprobadas: int, fallan: int, detalle: str) -> dict[str, Any]:
    return {"verificacion": nombre, "descripcion": VERIFICACIONES[nombre], "comprobadas": int(comprobadas),
            "filas_fallan": int(fallan), "detalle": detalle}


def construir(base: pd.DataFrame, plan: dict[str, Any] | None = None, lista: dict[str, dict] | None = None,
              inventario_series: pd.DataFrame | None = None, fiabilidad: pd.DataFrame | None = None,
              catalogo_series: dict[str, dict] | None = None, *, proyecciones: pd.DataFrame | None = None,
              pares: pd.DataFrame | None = None, simulacion: pd.DataFrame | None = None,
              corte: pd.Timestamp = CORTE_G2, publicaciones: dict[str, Any] | None = None,
              registro: Callable[[str], None] | None = None) -> Curada:
    """Construye en memoria la base curada, sus tablas y las verificaciones. No escribe nada.

    ``base``: filas del contrato de series de la base de trabajo (al menos las «queda», los componentes de las
    derivadas y, si no se da ``proyecciones``, las proyecciones). ``simulacion``: la tabla del paso 3
    (``preprocesado.simular``); sin ella, la verificación ``simulacion`` falla.
    """
    log = registro or (lambda _m: None)
    t0 = time.perf_counter()
    plan = plan if plan is not None else pp.cargar_plan()
    lista = lista if lista is not None else pp.cargar_lista()
    tablas = resultados_dir(TEMA) / "tablas"
    inv = inventario_series if inventario_series is not None else pd.read_csv(tablas / "inventario_series.csv")
    fia = fiabilidad if fiabilidad is not None else pd.read_csv(tablas / "fiabilidad_c.csv")
    cat = catalogo_series if catalogo_series is not None else catalogo.cargar_catalogo()

    queda = {s for s, e in lista.items() if e.get("decision") == "queda"}
    proy_ids = {s for s, e in lista.items() if e.get("decision") == "proyecciones"}
    deriv = ids_derivadas(lista, cat)
    comp = _componentes(deriv, cat)
    serie_txt = base["serie"].astype(str)
    if proyecciones is None:
        proyecciones = base[serie_txt.isin(proy_ids).to_numpy()]
    proyecciones = proyecciones.assign(**{k: _texto_obj(proyecciones[k]) for k in _COLS_TEXTO})
    # Filas que se curan una a una: las «queda» que no son derivadas y los componentes (aunque no se queden, como
    # fred:DFF, alias de fred:EFFR: sus fechas curadas fechan las derivadas y después se quitan).
    m_fila = serie_txt.isin((queda | set(comp)) - set(deriv)).to_numpy()
    b = base[m_fila].reset_index(drop=True)
    orig_deriv = base[serie_txt.isin(deriv).to_numpy()].reset_index(drop=True)
    n_queda_base = int(serie_txt.isin(queda).sum())
    n_base = int(len(base))
    del serie_txt, base   # si el llamador no guarda la base (curar), se libera aquí
    lista_aux = {**lista, **{c: {**lista.get(c, {}), "decision": "queda"} for c in comp if c not in queda}}
    asig = pp.asignar_series(plan, lista_aux, inv, fia)
    cur = pp.fechas_curadas(b, plan, asig, publicaciones=publicaciones, catalogo_series=cat)
    ver = pp.verificar(b, cur)
    log(f"fechas curadas de {len(b)} filas en {time.perf_counter() - t0:.0f} s")

    s_b = b["serie"].astype(str).to_numpy()
    es_queda = np.isin(s_b, list(queda))
    act = b["fecha_publicacion"].to_numpy(dtype="datetime64[ns]")
    nueva = cur["fecha_publicacion_curada"].to_numpy(dtype="datetime64[ns]")
    capa1_f = cur["fecha_capa1"].to_numpy(dtype="datetime64[ns]")
    disp_a = b["disponible_utc"]
    disp_n = pd.Series(cur["disponible_utc_curada"].to_numpy(), dtype=UTC)
    factor = escalas_vintage(s_b, b["vintage"].astype(str).to_numpy(), plan)
    desde = pp.publicado_desde(plan, set(s_b))
    unidad_a = _texto_obj(b["unidad"])
    fh, unidad_n, nota_h = homogeneizar(s_b, unidad_a, plan)
    extra = _unir(_notas_nuevas(s_b, cur, plan, factor, desde), nota_h)
    c = pd.DataFrame({
        "serie": _texto_obj(b["serie"]), "fecha_referencia": b["fecha_referencia"].to_numpy(dtype=FECHA),
        "fecha_publicacion": nueva, "disponible_utc": disp_n.array, "vintage": _texto_obj(b["vintage"]),
        "valor": b["valor"].to_numpy(dtype=float) * factor * fh, "unidad": unidad_n,
        "divisa": _texto_obj(b["divisa"]), "fuente": _texto_obj(b["fuente"]),
        "metodo_publicacion": _texto_obj(b["metodo_publicacion"]), "nota": _anadir(_texto_obj(b["nota"]), extra)})
    log(f"filas curadas montadas ({time.perf_counter() - t0:.0f} s)")

    # Derivadas con los componentes curados
    comp_cur = c[np.isin(s_b, comp)]
    dv, info_deriv = recalcular_derivadas(comp_cur, deriv, cat)
    clave = ["serie", "fecha_referencia", "vintage"]
    od = pd.DataFrame({"serie": _texto_obj(orig_deriv["serie"]), "fecha_referencia": orig_deriv["fecha_referencia"],
                       "vintage": _texto_obj(orig_deriv["vintage"]), "fecha_publicacion": orig_deriv["fecha_publicacion"],
                       "disponible_utc": orig_deriv["disponible_utc"], "valor": orig_deriv["valor"],
                       "unidad": _texto_obj(orig_deriv["unidad"]), "nota": _texto_obj(orig_deriv["nota"])})
    cruce = dv.merge(od, on=clave, how="outer", suffixes=("", "_antes"), indicator=True)
    solo_nuevas = int((cruce["_merge"] == "left_only").sum())
    # Volatilidad realizada: data/raw (Fase 1) trae las primeras sesiones de 1928 con menos de n rentabilidades; la
    # fórmula de fase1 (ventana completa) no las da. Se quitan (no son una volatilidad de n sesiones) y se cuentan.
    solo = cruce[cruce["_merge"] == "right_only"]
    primera = dv.groupby("serie")["fecha_referencia"].min()
    incompleta = solo["serie"].isin(list(fase1.VOL_REALIZADA)).to_numpy() & (
        solo["fecha_referencia"].to_numpy() < solo["serie"].map(primera).to_numpy(dtype="datetime64[ns]"))
    ventana_incompleta = {str(k): int(v) for k, v in solo.loc[incompleta, "serie"].value_counts().items()}
    solo_antes = int((~incompleta).sum())
    cruce = cruce[cruce["_merge"] != "right_only"].reset_index(drop=True)
    fp_d, fp_da = cruce["fecha_publicacion"], cruce["fecha_publicacion_antes"]
    dp_d, dp_da = cruce["disponible_utc"], cruce["disponible_utc_antes"]
    cambia_d = ((fp_d != fp_da) | (dp_d.isna() != dp_da.isna()) | (dp_d.notna() & dp_da.notna() & (dp_d != dp_da))
                ).to_numpy()
    # Homogeneización de las derivadas después de recalcularlas (VOLREAL21: tanto por uno → %)
    unidad_da = _texto_obj(cruce["unidad_antes"].where(cruce["unidad_antes"].notna(), cruce["unidad"]))
    fh_d, unidad_dn, nota_hd = homogeneizar(cruce["serie"].to_numpy(dtype=object), _texto_obj(cruce["unidad"]), plan)
    cruce["valor"] = cruce["valor"].to_numpy(dtype=float) * fh_d
    cruce["unidad"] = unidad_dn
    hom_d = (fh_d != 1) | (unidad_dn != unidad_da)
    nota_d = _texto_obj(cruce["nota_antes"].where(cruce["nota_antes"].notna(), cruce["nota"]))
    extra_d = _unir(np.where(cambia_d, NOTA_DERIVADA, None).astype(object), np.where(hom_d, nota_hd, None))
    cruce["nota"] = _anadir(nota_d, extra_d)
    deriv_filas = cruce[list(COLUMNAS_SERIES)]

    # Comprobación de las derivadas: fecha = la máxima de los componentes y valor del cálculo
    fallan_deriv, comprob_deriv, det_deriv = 0, 0, []
    for sid in deriv:
        inf = info_deriv.get(sid, {})
        if not inf.get("recalculada"):
            fallan_deriv += 1
            det_deriv.append(f"{sid}: sin recalcular ({inf.get('motivo')})")
            continue
        d = deriv_filas[deriv_filas["serie"] == sid].set_index("fecha_referencia")
        comprob_deriv += len(d)
        if sid in fase1.VOL_REALIZADA:
            cc = comp_cur[comp_cur["serie"] == fase1.VOL_REALIZADA[sid][0]]
            cc = cc[cc["valor"].notna()].sort_values("fecha_referencia", kind="mergesort")
            n = fase1.VOL_REALIZADA[sid][1]
            ventana = pd.Series(cc["fecha_publicacion"].to_numpy(dtype="datetime64[D]").astype("int64"),
                                index=cc["fecha_referencia"].to_numpy(), dtype=float).rolling(n + 1).max()
            esperada = pd.to_datetime(ventana.reindex(d.index).to_numpy(), unit="D")
            mal = int((d["fecha_publicacion"].to_numpy(dtype="datetime64[ns]") != esperada.to_numpy()).sum())
        else:
            a, bb = cat[sid]["componentes"]
            pa_ = comp_cur[comp_cur["serie"] == a].drop_duplicates("fecha_referencia").set_index("fecha_referencia")
            pb_ = comp_cur[comp_cur["serie"] == bb].drop_duplicates("fecha_referencia").set_index("fecha_referencia")
            fmax = np.maximum(pa_["fecha_publicacion"].reindex(d.index).to_numpy(dtype="datetime64[ns]"),
                              pb_["fecha_publicacion"].reindex(d.index).to_numpy(dtype="datetime64[ns]"))
            val = pa_["valor"].reindex(d.index).to_numpy(float) - pb_["valor"].reindex(d.index).to_numpy(float)
            mal = int((d["fecha_publicacion"].to_numpy(dtype="datetime64[ns]") != fmax).sum())
            mal += int((~np.isclose(d["valor"].to_numpy(float), val, rtol=0, atol=TOLERANCIA_DERIVADA)).sum())
        if mal:
            fallan_deriv += mal
            det_deriv.append(f"{sid}: {mal} filas")
    if solo_nuevas or solo_antes:
        fallan_deriv += solo_nuevas + solo_antes
        det_deriv.append(f"claves distintas de la base de trabajo: {solo_nuevas} solo en el cálculo, {solo_antes} solo "
                         "en la base")
    adel_deriv = int((fp_d < fp_da).sum())
    ambos = cruce["_merge"] == "both"
    # frente a la base de trabajo con la misma homogeneización (×100 en VOLREAL21, y la tolerancia también)
    dif_valor = (cruce.loc[ambos, "valor"] - cruce.loc[ambos, "valor_antes"] * fh_d[ambos.to_numpy()]).abs()
    tol = TOLERANCIA_DERIVADA * fh_d[ambos.to_numpy()]
    valores_distintos = {str(k): int(v) for k, v in
                         cruce.loc[ambos].loc[(dif_valor > tol).to_numpy(), "serie"].value_counts().items()}
    if valores_distintos:
        fallan_deriv += sum(valores_distintos.values())
        det_deriv.append(f"valores distintos de la base de trabajo: {valores_distintos}")

    # Todo junto (antes del corte): las «queda» curadas fila a fila y las derivadas
    n_es_queda = int(es_queda.sum())
    todo = pd.concat([c[es_queda], deriv_filas], ignore_index=True)
    del c   # lo que queda de ella está en todo (y comp_cur)
    en_corte = (todo["fecha_publicacion"] <= corte).to_numpy()
    cortadas = todo.loc[~en_corte, "serie"].value_counts()
    final = todo[en_corte]
    del todo
    log(f"corte G2 ({corte.date()}): {int((~en_corte).sum())} filas fuera; {len(final)} quedan")
    error_contrato = ""
    try:
        final = validar_series(final)
    except Exception as e:   # noqa: BLE001 - se cuenta como verificación fallida
        error_contrato = str(e)[:500]
    log(f"contrato validado ({time.perf_counter() - t0:.0f} s)")

    # Registro de cambios (antes del corte; en_base_curada dice si la fila sigue tras el corte)
    cambia_f = (nueva != act)
    cambia_disp = (disp_a.isna().to_numpy() != disp_n.isna().to_numpy())
    cambia_disp |= (disp_a.notna().to_numpy() & disp_n.notna().to_numpy()
                    & (disp_a.to_numpy() != disp_n.to_numpy()))
    hom = (fh != 1) | (unidad_n != unidad_a)
    m_reg = es_queda & (cambia_f | cambia_disp | (factor != 1) | hom)
    capa1 = (pd.notna(cur["seccion"].to_numpy(dtype=object)) & (capa1_f != act))
    h15 = cur["h15"].to_numpy()
    recon = cur["reconstruida"].to_numpy()
    esc = factor != 1
    ix = np.flatnonzero(m_reg)
    sec_ix = cur["seccion"].to_numpy(dtype=object)[ix]
    capa_txt = np.where(capa1[ix], sec_ix, None).astype(object)
    for nom, flag in (("h15_diario", h15), ("reconstruidas", recon), ("escala_vintage", esc),
                      ("homogeneizacion", hom), ("disponible", cambia_disp & ~cambia_f)):
        capa_txt = _unir(capa_txt, np.where(flag[ix], nom, None).astype(object))
    capa_txt = np.array(["" if x is None else str(x).replace("; ", "+") for x in capa_txt], dtype=object)
    en_base = en_corte[:n_es_queda]
    pos_queda = np.cumsum(es_queda) - 1
    reg = pd.DataFrame({
        "serie": s_b[ix], "fecha_referencia": b["fecha_referencia"].to_numpy(dtype=FECHA)[ix],
        "vintage": _texto_obj(b["vintage"])[ix], "fecha_publicacion_antes": act[ix],
        "fecha_publicacion_despues": nueva[ix], "disponible_utc_antes": disp_a.astype(UTC).array[ix],
        "disponible_utc_despues": disp_n.array[ix],
        "retraso_dias": ((nueva[ix] - act[ix]) / np.timedelta64(1, "D")).astype(float), "capa": capa_txt,
        "seccion": sec_ix, "grupo": cur["grupo"].to_numpy(dtype=object)[ix],
        "regla": cur["regla"].to_numpy(dtype=object)[ix], "capa1": capa1[ix], "h15": h15[ix], "reconstruida": recon[ix],
        "derivada": False, "escala": esc[ix], "homogeneizacion": hom[ix], "con_tope": cur["con_tope"].to_numpy()[ix],
        "factor_escala": (factor * fh)[ix], "unidad_antes": unidad_a[ix], "unidad_despues": unidad_n[ix],
        "en_base_curada": en_base[pos_queda[ix]]})
    ixd = np.flatnonzero(cambia_d | hom_d)
    en_base_d = en_corte[n_es_queda:]
    capa_d = np.array(["+".join(n for n, f in (("derivada", cd), ("homogeneizacion", hd)) if f)
                       for cd, hd in zip(cambia_d[ixd], hom_d[ixd], strict=True)], dtype=object)
    reg_d = pd.DataFrame({
        "serie": cruce["serie"].to_numpy()[ixd], "fecha_referencia": cruce["fecha_referencia"].to_numpy()[ixd],
        "vintage": cruce["vintage"].to_numpy()[ixd],
        "fecha_publicacion_antes": fp_da.to_numpy(dtype="datetime64[ns]")[ixd],
        "fecha_publicacion_despues": fp_d.to_numpy(dtype="datetime64[ns]")[ixd],
        "disponible_utc_antes": dp_da.astype(UTC).array[ixd], "disponible_utc_despues": dp_d.astype(UTC).array[ixd],
        "retraso_dias": ((fp_d - fp_da).dt.days.to_numpy(dtype=float))[ixd], "capa": capa_d, "seccion": None,
        "grupo": None, "regla": None, "capa1": False, "h15": False, "reconstruida": False, "derivada": cambia_d[ixd],
        "escala": False, "homogeneizacion": hom_d[ixd], "con_tope": False, "factor_escala": fh_d[ixd],
        "unidad_antes": unidad_da[ixd], "unidad_despues": unidad_dn[ixd], "en_base_curada": en_base_d[ixd]})
    registro_t = pd.concat([reg, reg_d], ignore_index=True)[list(COLUMNAS_REGISTRO)]
    registro_t = registro_t.sort_values(["serie", "fecha_referencia", "fecha_publicacion_antes", "vintage"],
                                        kind="mergesort").reset_index(drop=True)
    log(f"registro de cambios: {len(registro_t)} filas ({time.perf_counter() - t0:.0f} s)")

    # Alias y proyecciones
    alias_t = tabla_alias(lista, pares)
    _, proy_t = pp.separar_proyecciones(proyecciones, proy_ids)
    proy_pre = len(proy_t)
    proy_t = proy_t[(proy_t["fecha_publicacion"] <= corte).to_numpy()]
    proy_t = proy_t.sort_values(["serie", "fecha_referencia", "fecha_publicacion", "vintage"],
                                kind="mergesort").reset_index(drop=True)

    # --- Verificaciones ---
    filas_v = []
    adel = int(ver["adelanta"].to_numpy()[es_queda].sum()) + adel_deriv
    filas_v.append(_fila_ver("no_adelanta", int(es_queda.sum()) + len(cruce), adel,
                             "ninguna fila adelanta" if not adel else f"{adel} filas adelantan"))
    incoh = int(ver["disponible_incoherente"].to_numpy()[es_queda].sum())
    nn = deriv_filas["disponible_utc"].notna()
    if nn.any():
        incoh += int((primera_decision_vec(deriv_filas.loc[nn, "disponible_utc"]).to_numpy(dtype="datetime64[ns]")
                      != deriv_filas.loc[nn, "fecha_publicacion"].to_numpy(dtype="datetime64[ns]")).sum())
    filas_v.append(_fila_ver("disponible_coherente", int(es_queda.sum()) + len(deriv_filas), incoh,
                             "coherente" if not incoh else f"{incoh} filas incoherentes"))
    orden = int(ver["orden_roto"].to_numpy()[es_queda].sum())
    filas_v.append(_fila_ver("orden_vintages", int(es_queda.sum()), orden,
                             "orden mantenido" if not orden else f"{orden} filas bajan"))

    fpf, frf = final["fecha_publicacion"], final["fecha_referencia"]
    trunc = int((fpf < frf).sum()) + int((fpf > corte).sum())
    muestra = (final["serie"].value_counts().sort_index(kind="mergesort")
               .sort_values(ascending=False, kind="mergesort").index[:SERIES_TRUNCADO].tolist())
    sub = final[final["serie"].isin(muestra)]
    pruebas = 0
    for s in muestra:
        ss = sub[sub["serie"] == s]
        for d in (*FECHAS_TRUNCADO, corte.date().isoformat()):
            pruebas += 1
            vis = timegate.as_of_series(ss, s, d)
            corto = timegate.as_of_series(ss[ss["fecha_publicacion"] <= pd.Timestamp(d)], s, d)
            if (vis["fecha_publicacion"] > pd.Timestamp(d)).any() or not vis.equals(corto):
                trunc += 1
    filas_v.append(_fila_ver("truncado", len(final) + pruebas, trunc,
                             f"{pruebas} consultas TimeGate ({len(muestra)} series × {len(FECHAS_TRUNCADO) + 1} fechas)"
                             if not trunc else f"{trunc} filas o consultas fallan"))

    en_final = set(final["serie"].astype(str).unique())
    falta = sorted(queda - en_final)
    sobra = sorted(en_final - queda)
    dentro = sorted(en_final & (proy_ids | {s for s, e in lista.items() if e.get("decision") == "alias"}))
    hp = {s for s in queda if lista[s].get("rol") == "historia_previa"}
    falla_l = len(falta) + len(sobra) + len(dentro) + len(hp - en_final)
    filas_v.append(_fila_ver("recuentos_lista", len(queda), falla_l,
                             f"{len(en_final)} series = {len(queda)} «queda» ({len(hp)} de historia_previa)"
                             if not falla_l else f"faltan {falta[:5]}, sobran {sobra[:5]}, alias o proyecciones "
                                                 f"dentro {dentro[:5]}"))
    n_alias = sum(1 for e in lista.values() if e.get("decision") == "alias")
    can_fuera = sorted(set(alias_t["canonico"]) - en_final)
    falla_a = abs(len(alias_t) - n_alias) + len(can_fuera) + int(alias_t["alias"].duplicated().sum())
    filas_v.append(_fila_ver("recuentos_alias", n_alias, falla_a,
                             f"{len(alias_t)} alias; {int(alias_t['correlacion'].notna().sum())} con correlación"
                             if not falla_a else f"{len(alias_t)} filas frente a {n_alias}; canónicos fuera "
                                                 f"{can_fuera[:5]}"))
    esperadas = plan["proyecciones"]["esperadas"]["total"]
    n_proy = int(proy_t["serie"].nunique())
    falla_p = abs(n_proy - esperadas) + abs(len(proy_ids) - esperadas)
    filas_v.append(_fila_ver("recuentos_proyecciones", esperadas, falla_p,
                             f"{n_proy} series, {len(proy_t)} filas ({proy_pre - len(proy_t)} quitadas por el corte)"
                             if not falla_p else f"{n_proy} series frente a {esperadas}"))

    metodos = b["metodo_publicacion"].astype(str).to_numpy()
    exacta = np.isin(metodos, ["vintage_exacto", "cierre_mercado"])
    falla_e = int((exacta & ((capa1_f != act) | h15)).sum())
    filas_v.append(_fila_ver("exactas_sin_cambio", int(exacta.sum()), falla_e,
                             "sin cambios en las capas 1 y 2" if not falla_e else f"{falla_e} filas cambian"))
    cortes = asig.loc[asig["seccion"] == "tramo_no_fiable"].set_index("id")["corte"]
    corte_fila = pd.Series(s_b).map(cortes).to_numpy(dtype="datetime64[ns]")
    tras = ~np.isnat(corte_fila) & (act >= corte_fila)
    tras_h = act >= np.datetime64(str(plan["h15_diario"]["hasta"]), "ns")
    falla_t = int((tras & (capa1_f != act)).sum()) + int((tras_h & h15).sum())
    filas_v.append(_fila_ver("posteriores_sin_cambio", int(tras.sum() + tras_h.sum()), falla_t,
                             "sin cambios tras el corte del tramo ni tras H.15" if not falla_t
                             else f"{falla_t} filas cambian"))
    ho = plan["homogeneizacion"]
    no_canonicas = {u for par in ho["unidades_equivalentes"] or [] for u in par["unidades"] if u != par["canonica"]}
    esperada_u = {sid: e["unidad_nueva"] for e in ho["escalas"] or [] for sid in e["series"]}
    sin_escalar = {sid for e in ho.get("sin_escalar") or [] for sid in e["series"]}
    u_final = final["unidad"].astype(str)
    s_final = final["serie"].astype(str)
    falla_h = int(u_final.isin(no_canonicas).sum())
    m_esc = s_final.isin(esperada_u)
    falla_h += int((m_esc & (u_final != s_final.map(esperada_u))).sum())
    falla_h += int((np.isin(s_b, list(sin_escalar)) & ((fh != 1) | (unidad_n != unidad_a))).sum())
    homog_series = sorted({*registro_t.loc[registro_t["homogeneizacion"], "serie"]})
    filas_v.append(_fila_ver("unidades_homogeneizadas", len(final), falla_h,
                             f"{len(homog_series)} series homogeneizadas ({int(m_esc.sum())} filas escaladas ×100 en "
                             f"{int(s_final[m_esc].nunique())} series); ninguna unidad no canónica" if not falla_h
                             else f"{falla_h} filas con unidad sin homogeneizar"))
    filas_v.append(_fila_ver("derivadas", comprob_deriv, fallan_deriv,
                             f"{len(deriv)} derivadas recalculadas; {int(cambia_d.sum())} filas con fecha nueva; "
                             f"valores distintos de la base de trabajo: {valores_distintos or 'ninguno'}; "
                             f"quitadas por ventana incompleta: {ventana_incompleta or 'ninguna'}"
                             if not fallan_deriv else "; ".join(det_deriv[:5])))

    # Recuentos frente a la simulación del paso 3 (antes del corte; sin las derivadas, que el paso 3 no curaba)
    rq = registro_t[registro_t["serie"].isin(queda - set(deriv))]
    sub_q = cur[es_queda]
    filas_sec = sub_q[sub_q["seccion"].notna()]
    cuentas: dict[tuple, dict[str, float]] = {}
    tam = filas_sec.groupby(["seccion", filas_sec["grupo"].fillna("-"), "regla"]).size()
    camb = rq[rq["capa1"]].groupby(["seccion", rq.loc[rq["capa1"], "grupo"].fillna("-"), "regla"]).size()
    for (s, g, r), n in tam.items():
        cuentas[(s, None if g == "-" else g, r)] = {"filas_regla": n, "filas_cambian": int(camb.get((s, g, r), 0))}
    cuentas[("h15_diario", "capa", None)] = {"filas_cambian": int(rq["h15"].sum())}
    cuentas[("reconstruidas", "capa", None)] = {"filas_cambian": int(rq["reconstruida"].sum())}
    cuentas[("escalas_por_vintage", "valores", None)] = {"filas_regla": int(rq["escala"].sum())}
    cuentas[("proyecciones", "tabla_aparte", None)] = {"filas_regla": proy_pre}
    cuentas[("total", "verificaciones", None)] = {
        "filas_regla": n_queda_base, "filas_cambian": int((rq["retraso_dias"] > 0).sum()),
        "filas_adelantan": adel, "filas_disponible_incoherente": incoh, "filas_orden_roto": orden,
        "filas_con_tope": int(cur["con_tope"].to_numpy()[es_queda].sum())}
    comprobadas, distintas, det_sim = _comparar_simulacion(simulacion, cuentas)
    filas_v.append(_fila_ver("simulacion", comprobadas, distintas, det_sim))
    filas_v.append(_fila_ver("contrato", len(final), 1 if error_contrato else 0, error_contrato or "válida"))
    verif = pd.DataFrame(filas_v, columns=list(COLUMNAS_VERIFICACIONES))

    # Resumen por serie (solo metadatos)
    resumen = _resumen(final, registro_t, cortadas, lista, asig)
    info = {"filas_base": n_base, "filas_queda_base": n_queda_base, "filas_curada": int(len(final)), "homogeneizadas": homog_series,
            "series_curada": int(final["serie"].nunique()), "filas_cortadas": int((~en_corte).sum()),
            "filas_registro": int(len(registro_t)), "alias": int(len(alias_t)), "proyecciones_series": n_proy,
            "proyecciones_filas": int(len(proy_t)), "proyecciones_cortadas": int(proy_pre - len(proy_t)),
            "derivadas_valores_distintos": valores_distintos, "derivadas_ventana_incompleta": ventana_incompleta,
            "derivadas": {s: {k: v for k, v in i.items() if k not in ("copia_fase1",)} for s, i in info_deriv.items()},
            "segundos": round(time.perf_counter() - t0, 1)}
    return Curada(final, alias_t, proy_t, registro_t, verif, resumen, info)


def _resumen(final: pd.DataFrame, registro_t: pd.DataFrame, cortadas: pd.Series, lista: dict[str, dict],
             asig: pd.DataFrame) -> pd.DataFrame:
    g = final.groupby("serie", sort=True)
    r = pd.DataFrame({"filas": g.size(), "desde": g["fecha_referencia"].min(), "hasta": g["fecha_referencia"].max(),
                      "publicada_desde": g["fecha_publicacion"].min(), "publicada_hasta": g["fecha_publicacion"].max()})
    rb = registro_t[registro_t["en_base_curada"]]
    cambio = rb[rb["fecha_publicacion_antes"] != rb["fecha_publicacion_despues"]]
    rg = cambio.groupby("serie")["retraso_dias"]
    r["filas_cambiadas"] = rb.groupby("serie").size()
    r["filas_escaladas"] = rb[rb["escala"] | rb["homogeneizacion"]].groupby("serie").size()
    r["retraso_mediana_dias"] = rg.median()
    r["retraso_max_dias"] = rg.max()
    r["filas_cortadas"] = cortadas
    for col in ("filas_cambiadas", "filas_escaladas", "filas_cortadas"):
        r[col] = r[col].fillna(0).astype(int)
    a = asig.drop_duplicates("id").set_index("id")
    r["rol"] = [lista.get(s, {}).get("rol") for s in r.index]
    r["seccion"] = [a["seccion"].get(s) for s in r.index]
    r["regla"] = [a["regla"].get(s) for s in r.index]
    for col in ("desde", "hasta", "publicada_desde", "publicada_hasta"):
        r[col] = pd.to_datetime(r[col]).dt.strftime("%Y-%m-%d")
    return r.rename_axis("serie").reset_index()[list(COLUMNAS_RESUMEN)]


# --- Lectura y escritura ---------------------------------------------------------------------------------------
def _leer_base(ids: Iterable[str], ruta: Path) -> pd.DataFrame:
    """Filas del contrato de ``ids`` (lectura con filtro; los textos como diccionario para ahorrar memoria)."""
    t = pq.read_table(ruta, columns=list(COLUMNAS_SERIES), filters=[("serie", "in", sorted(set(ids)))],
                      read_dictionary=list(_COLS_TEXTO))
    return t.to_pandas()


def _esquema_df(df: pd.DataFrame) -> pa.Schema:
    return pa.Schema.from_pandas(df, preserve_index=False)


def _renombrar(a: Path, b: Path) -> None:
    """``os.replace`` con reintentos (en Windows falla si otro proceso tiene abierto el destino)."""
    for intento in range(_REINTENTOS):
        try:
            os.replace(a, b)
            return
        except PermissionError:
            if intento == _REINTENTOS - 1:
                raise
            time.sleep(0.2 * (intento + 1))


def firma(ruta: Path) -> dict[str, Any]:
    """Firma de un fichero para el manifiesto: ruta, tamaño, ``mtime_ns`` y sha256 (lectura por bloques)."""
    ruta = Path(ruta)
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 22), b""):
            h.update(bloque)
    st = ruta.stat()
    return {"ruta": str(ruta), "tamano": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "sha256": h.hexdigest()}


def _destinos(carpeta_series: Path | None) -> dict[str, Path]:
    """Ruta final de cada salida del corpus (las de ``almacen`` si no se da otra carpeta)."""
    if carpeta_series is None:
        cs = almacen.ruta_series(curada=True).parent
        d = {"base_curada": almacen.ruta_series(curada=True), "alias": almacen.ruta_alias(),
             "proyecciones": almacen.ruta_proyecciones()}
    else:
        cs = Path(carpeta_series)
        d = {"base_curada": cs / almacen.FICHERO_SERIES_CURADA, "alias": cs / almacen.FICHERO_ALIAS,
             "proyecciones": cs / almacen.FICHERO_PROYECCIONES}
    d["registro_cambios"] = cs / FICHERO_REGISTRO
    d["manifiesto"] = cs / FICHERO_MANIFIESTO   # el último en publicarse: marca un conjunto completo
    if any(p.parent != cs for p in d.values()):
        raise ValueError(f"las salidas del paso 4 deben ir todas a {cs}")
    if d["base_curada"].name == almacen.FICHERO_SERIES:
        raise ValueError("la base curada no puede sobrescribir la base de trabajo")
    return d


def _limpiar_restos(cs: Path, nombres: Iterable[str]) -> None:
    """Restos de una publicación cortada: si falta alguna salida y hay copia previa, la devuelve; borra temporales."""
    for previa in sorted(cs.glob(f"{PREFIJO_PREVIA}*")):
        for n in nombres:
            if (previa / n).exists() and not (cs / n).exists():
                _renombrar(previa / n, cs / n)
        shutil.rmtree(previa, ignore_errors=True)
    for nuevo in cs.glob(f"{PREFIJO_NUEVO}*"):
        shutil.rmtree(nuevo, ignore_errors=True)


def _publicar_conjunto(nuevo: Path, destinos: dict[str, Path]) -> None:
    """Cambia todas las salidas a la vez: aparta las anteriores en una carpeta previa y mueve las nuevas (renombrados
    en la misma carpeta, el manifiesto el último). Si algo falla, vuelven todas las anteriores."""
    cs = destinos["base_curada"].parent
    previa = cs / f"{PREFIJO_PREVIA}{uuid.uuid4().hex[:12]}"
    previa.mkdir()
    movidas: list[Path] = []
    try:
        for p in destinos.values():
            if p.exists():
                _renombrar(p, previa / p.name)
        for p in destinos.values():
            _renombrar(nuevo / p.name, p)
            movidas.append(p)
    except Exception:
        for p in movidas:
            if p.exists():
                p.unlink()
        for p in destinos.values():
            if (previa / p.name).exists():
                _renombrar(previa / p.name, p)
        shutil.rmtree(previa, ignore_errors=True)   # ya vacía: todo ha vuelto a su sitio
        raise
    finally:
        shutil.rmtree(nuevo, ignore_errors=True)
    shutil.rmtree(previa, ignore_errors=True)


def _escribir_tablas(res: Curada, carpeta_tablas: Path | None, *, solo_verificaciones: bool = False) -> dict[str, Path]:
    ct = Path(carpeta_tablas) if carpeta_tablas is not None else resultados_dir(TEMA) / "tablas"
    rutas = {"verificaciones": almacen.escribir_csv_atomico(res.verificaciones, ct / TABLA_VERIFICACIONES)}
    if not solo_verificaciones:
        rutas["resumen"] = almacen.escribir_csv_atomico(res.resumen, ct / TABLA_RESUMEN)
    return rutas


def escribir(res: Curada, carpeta_series: Path | None = None, carpeta_tablas: Path | None = None, *,
             entradas: dict[str, Path] | None = None, corte: pd.Timestamp = CORTE_G2) -> dict[str, Path]:
    """Publica las salidas de ``res`` como un conjunto (``_publicar_conjunto``) con su manifiesto y escribe las tablas
    del repo. Si alguna verificación falla, escribe solo ``tablas/curada_verificaciones.csv`` (con el fallo), no
    publica nada en el corpus y lanza ``ErrorCuracion``.

    ``entradas``: ficheros que se firman en el manifiesto (por defecto ``base_series.parquet``, ``lista_curada.yaml``
    y ``preprocesado.yaml``).
    """
    if not res.correcta:
        _escribir_tablas(res, carpeta_tablas, solo_verificaciones=True)
        raise ErrorCuracion(res.verificaciones)
    destinos = _destinos(carpeta_series)
    cs = destinos["base_curada"].parent
    cs.mkdir(parents=True, exist_ok=True)
    _limpiar_restos(cs, [p.name for p in destinos.values()])
    entradas = entradas if entradas is not None else {"base_series": almacen.ruta_series(),
                                                     "lista_curada": pp.RUTA_LISTA, "preprocesado": pp.RUTA_PLAN}
    nuevo = cs / f"{PREFIJO_NUEVO}{uuid.uuid4().hex[:12]}"
    nuevo.mkdir()
    try:
        esquema_p = pa.schema([*almacen.ESQUEMA_SERIES, pa.field("horizonte", pa.int64()),
                               pa.field("edicion", pa.string())])
        tablas = {
            "base_curada": (res.base, almacen.ESQUEMA_SERIES, almacen.FILAS_POR_GRUPO_SERIES),
            "alias": (res.alias, _esquema_df(res.alias), None),
            "proyecciones": (res.proyecciones[list(pp.COLUMNAS_PROYECCIONES)], esquema_p, None),
            "registro_cambios": (res.registro, _esquema_df(res.registro), almacen.FILAS_POR_GRUPO_SERIES),
        }
        salidas = {}
        for nombre, (df, esquema, grupo) in tablas.items():
            ruta = almacen.escribir_parquet_atomico(df, esquema, nuevo / destinos[nombre].name, filas_por_grupo=grupo)
            f = firma(ruta)
            salidas[nombre] = {"fichero": destinos[nombre].name, "filas": int(len(df)), "tamano": f["tamano"],
                               "sha256": f["sha256"]}
        manifiesto = {
            "version": 1, "creado_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "corte_g2": corte.date().isoformat(),
            "entradas": {k: firma(v) for k, v in entradas.items()},
            "salidas": salidas,
            "verificaciones": {r.verificacion: int(r.filas_fallan) for r in res.verificaciones.itertuples()},
            "resumen": {k: v for k, v in res.info.items() if not isinstance(v, dict)},
        }
        (nuevo / destinos["manifiesto"].name).write_text(
            json.dumps(manifiesto, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(nuevo, ignore_errors=True)
        raise
    _publicar_conjunto(nuevo, destinos)
    return {**destinos, **_escribir_tablas(res, carpeta_tablas)}


def curar(*, ruta_base: Path | None = None, carpeta_series: Path | None = None, carpeta_tablas: Path | None = None,
          plan: dict[str, Any] | None = None, lista: dict[str, dict] | None = None,
          inventario_series: pd.DataFrame | None = None, fiabilidad: pd.DataFrame | None = None,
          catalogo_series: dict[str, dict] | None = None, simulacion: pd.DataFrame | None = None,
          pares: pd.DataFrame | None = None, corte: pd.Timestamp = CORTE_G2, escribir_salidas: bool = True,
          entradas: dict[str, Path] | None = None,
          registro: Callable[[str], None] | None = None) -> tuple[Curada, dict[str, Path]]:
    """Lee la base de trabajo (solo lectura), construye la curada y la publica si todas las verificaciones pasan (si
    no, solo deja ``curada_verificaciones.csv`` con el fallo y lanza ``ErrorCuracion``)."""
    log = registro or (lambda _m: None)
    plan = plan if plan is not None else pp.cargar_plan()
    lista = lista if lista is not None else pp.cargar_lista()
    cat = catalogo_series if catalogo_series is not None else catalogo.cargar_catalogo()
    tablas = resultados_dir(TEMA) / "tablas"
    if simulacion is None and (tablas / TABLA_SIMULACION).exists():
        simulacion = pd.read_csv(tablas / TABLA_SIMULACION)
    if pares is None and (tablas / "redundancia_pares.csv").exists():
        pares = pd.read_csv(tablas / "redundancia_pares.csv")
    ruta = Path(ruta_base) if ruta_base is not None else almacen.ruta_series()
    if entradas is None:
        entradas = {"base_series": ruta, "lista_curada": pp.RUTA_LISTA, "preprocesado": pp.RUTA_PLAN}
    queda = {s for s, e in lista.items() if e.get("decision") == "queda"}
    proy = {s for s, e in lista.items() if e.get("decision") == "proyecciones"}
    ids = queda | proy | set(_componentes(ids_derivadas(lista, cat), cat))
    log(f"base de trabajo (solo lectura): {ruta}")
    res = construir(_leer_base(ids, ruta), plan, lista, inventario_series, fiabilidad, cat, pares=pares,
                    simulacion=simulacion, corte=corte, registro=log)
    if not escribir_salidas:
        return res, {}
    return res, escribir(res, carpeta_series, carpeta_tablas, entradas=entradas, corte=corte)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingesta.mercados_series curar",
                                 description="Construye la base curada del paso 4 (series/base_curada.parquet, alias, "
                                             "proyecciones y registro de cambios) sin tocar la base de trabajo.")
    ap.add_argument("--sin-escribir", action="store_true", help="construye y verifica sin escribir nada")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    try:
        res, rutas = curar(escribir_salidas=not args.sin_escribir, registro=print)
    except ErrorCuracion as e:
        print(e.verificaciones[["verificacion", "comprobadas", "filas_fallan", "detalle"]].to_string(index=False))
        print(f"ERROR: {e}\nSolo se ha escrito tablas/{TABLA_VERIFICACIONES}; no se ha publicado nada.")
        return 1
    print(res.verificaciones[["verificacion", "comprobadas", "filas_fallan", "detalle"]].to_string(index=False))
    i = res.info
    print(f"base curada: {i['filas_curada']} filas de {i['series_curada']} series; {i['filas_cortadas']} filas fuera "
          f"por el corte G2 ({CORTE_G2.date()}); registro {i['filas_registro']} filas; {i['alias']} alias; "
          f"{i['proyecciones_series']} proyecciones ({i['proyecciones_filas']} filas); "
          f"{time.perf_counter() - t0:.0f} s")
    for nombre, ruta in rutas.items():
        print(f"{nombre} -> {ruta}")
    return 0 if res.correcta else 1


if __name__ == "__main__":
    raise SystemExit(main())
