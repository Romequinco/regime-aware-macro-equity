"""Plan de preprocesado del Tema 1 (paso 3 de la descarga completa): borrador que el paso 4 aplicará.

``config/preprocesado.yaml`` es un **borrador**: en el paso 3 no construye ninguna base. Este módulo lo carga y lo
valida, y tiene las funciones puras que dan la fecha conservadora de una fila según su regla. En el paso 3 solo se
usan para **simular** el efecto; el paso 4 las aplicará para construir la base curada aparte (la base actual y el
crudo no se tocan nunca).

``python -m ingesta.mercados_series.preprocesado`` lee la base (solo lectura, con pyarrow y solo las columnas de
fechas y notas de las series que se quedan en ``config/lista_curada.yaml``), aplica el plan en memoria y escribe
``results/ingesta/mercados_series/tablas/preprocesado_simulacion.csv``: por sección, grupo y regla, cuántas filas
cambiarían de fecha, cuántos días se retrasan (mediana, p95 y máximo) y las tres verificaciones (ninguna fila
adelanta, ``disponible_utc`` coherente y orden de vintages). Solo recuentos y días, ningún valor de serie.

**Reglas** (``regla``: un diccionario con el formato de ``config/lags.yaml``):

- de retraso: ``{lag, fin_periodo, habiles?, n_habiles?, tramos?}``, la misma semántica que ``lags.yaml``
  (``catalogo.fecha_publicacion_tramos``: fin del periodo + ``lag``, primer hábil y n-ésimo hábil);
- de publicador: ``{publicador, lag?, habiles?}``: la fecha de decisión que da hoy el publicador de
  ``publicaciones.yaml`` (``visibilidad.disponible_publicador`` + ``contrato.primera_decision_vec``) y, encima,
  ``lag`` en días naturales (``fin_periodo: fecha``) llevado al primer hábil de ``habiles``.

El calendario no se reimplementa: todo pasa por ``catalogo`` y ``visibilidad``.

**Capas de la fecha curada** (``fechas_curadas``), todas con ``max``: nunca adelantan una fecha.

1. Regla conservadora (E4) o tramo no fiable (E5): ``max(actual, min(regla, tope))``. ``tope`` = el primer
   vintage X de las filas con la nota «anterior a ALFRED: valor del primer vintage (X)»: ese valor es público en X
   con seguridad, y no pasar de X mantiene el orden con los vintages reales posteriores.
2. H.15 diario antes de 2005-06-28 (``h15_diario``): + 7 días sobre el publicador.
3. Índices reconstruidos (``reconstruidas``): las filas publicadas antes de ``publicado_desde`` (catálogo) pasan a
   ``publicado_desde``.

Una fila cuya fecha cambia pierde ``disponible_utc`` (nulo: solo se conoce el día), como
``catalogo.aplicar_excepciones`` en las filas sin hora; así ``contrato._coherencia_disponible`` sigue pasando.

**Qué filas toca** (``filas_afectadas``): las capas 1 y 2, solo las que fecha una regla (``inventario.METODOS_REGLA``:
``calendario``, ``lag_fijo`` y ``fichero``), nunca las ``vintage_exacto`` ni las ``cierre_mercado``; en el tramo no
fiable, solo las publicadas antes de ``fiable_desde``. Las derivadas no se tocan aquí: el paso 4 las recalcula con sus
componentes curados (``contrato.fecha_publicacion_derivada``).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, catalogo, inventario, visibilidad
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, primera_decision_vec

__all__ = [
    "RUTA_PLAN", "RUTA_LISTA", "GRUPOS", "ACCIONES_EDA", "SECCIONES", "COLUMNAS_SIMULACION", "COLUMNAS_PROYECCIONES",
    "cargar_plan", "validar_plan", "cargar_lista", "regla_actual", "fecha_regla", "fecha_conservadora",
    "filas_afectadas", "tope_primer_vintage", "sumar_dias_lag", "adelantos_por_serie", "propuesta_tramo",
    "propuesta_escalas_vintage", "propuesta_incidencias", "reglas_poca_muestra", "asignar_series",
    "fechas_curadas", "verificar", "separar_proyecciones", "simular", "main",
]

TEMA = "mercados_series"
RUTA_PLAN = Path(__file__).resolve().parent / "config" / "preprocesado.yaml"
RUTA_LISTA = Path(__file__).resolve().parent / "config" / "lista_curada.yaml"
TABLA_SIMULACION = "preprocesado_simulacion.csv"

GRUPOS = ("mercado_diario", "banco_mundial", "macro_eurostat_bce_bis", "academicas", "otras_fred")
ACCIONES_EDA = ("marcar", "nulo + aviso", "revisar a mano")
SECCIONES = ("version", "estado", "reglas_conservadoras", "tramo_no_fiable", "h15_diario", "reconstruidas",
             "proyecciones", "homogeneizacion", "escalas_por_vintage", "incidencias_eda", "salidas_paso4")
COLUMNAS_PROYECCIONES = (*COLUMNAS_SERIES, "horizonte", "edicion")
COLUMNAS_SIMULACION = ("seccion", "grupo", "regla", "n_series", "filas_regla", "filas_cambian", "pct_cambian",
                       "retraso_mediana_dias", "retraso_p95_dias", "retraso_max_dias", "filas_adelantan",
                       "filas_disponible_incoherente", "filas_orden_roto", "filas_con_tope", "pendiente_calendario")
VEREDICTOS_TRAMO = {"no fiable": "no_fiable", "fiable con margen": "fiable_con_margen"}

_CLAVES_REGLA = {"publicador", "lag", "fin_periodo", "habiles", "n_habiles", "tramos"}
_CLAVES_GRUPO = {"descripcion", "reglas"}
_CLAVES_GRUPO_OPC = {"notas"}
_CLAVES_ENTRADA = {"actual", "fuente", "motivo"}
_CLAVES_ENTRADA_OPC = {"conservadora", "pendiente_calendario", "notas", "regla_de_lags", "fuentes", "alternativas",
                       "falta"}
_CLAVES_ACTUAL_PUB = {"publicador", "dia", "hora", "huso", "habiles"}
_CLAVES_NF_SERIE = {"regla", "veredicto", "corte", "adelanto_dias", "medida", "n", "dias_extra", "conservadora"}
_PATRON_HORIZONTE = re.compile(r"\.PROY\.H(\d+)$")
_PATRON_DIAS = re.compile(r"\d+D")
_PATRON_PREVIA = re.compile(re.escape(catalogo.NOTA_PREVIA_ALFRED) + r" \((\d{4}-\d{2}-\d{2})\)")
_PATRON_COMUNES = re.compile(r"(\d+) fechas comunes")


# --- Carga y validación ---------------------------------------------------------------------------
def _yaml(ruta: Path) -> Any:
    return visibilidad._leer_yaml(ruta)


def cargar_lista(ruta: Path | None = None) -> dict[str, dict[str, Any]]:
    """``config/lista_curada.yaml`` (de B1, paso 3): ``{id: entrada}`` de las series. Fuente de verdad de la
    decisión (queda, alias, fuera, proyecciones), del aviso de fecha y del grupo conservador."""
    return _yaml(Path(ruta) if ruta is not None else RUTA_LISTA)["series"]


def _hora_txt(valor: Any) -> str:
    """Hora de publicaciones.yaml como texto ``HH:MM`` (YAML 1.1 lee 08:30 sin comillas como un entero)."""
    if isinstance(valor, int):
        return f"{valor // 60:02d}:{valor % 60:02d}"
    return str(valor.strftime("%H:%M") if hasattr(valor, "strftime") else valor)


def _validar_regla(regla: Any, donde: str, publicadores: dict[str, Any]) -> dict[str, Any]:
    """Una regla en el formato de lags.yaml (de retraso) o de publicador (ver el docstring del módulo)."""
    if not isinstance(regla, dict):
        raise ValueError(f"{donde}: la regla debe ser un diccionario")
    desconocidas = set(regla) - _CLAVES_REGLA
    if desconocidas:
        raise ValueError(f"{donde}: claves desconocidas {sorted(desconocidas)}")
    try:
        if "publicador" in regla:
            if regla["publicador"] not in publicadores:
                raise ValueError(f"publicador {regla['publicador']!r} no está en publicaciones.yaml")
            if regla.get("lag") is not None and not _PATRON_DIAS.fullmatch(str(regla["lag"])):
                raise ValueError("sobre un publicador el lag solo puede ir en días (\"<n>D\")")
            if regla.get("fin_periodo", "fecha") != "fecha" or regla.get("tramos") or regla.get("n_habiles"):
                raise ValueError("sobre un publicador solo valen lag (días), fin_periodo: fecha y habiles")
            catalogo._validar_habiles(regla.get("habiles"), None, donde)
            return regla
        for campo in ("lag", "fin_periodo"):
            if campo not in regla:
                raise ValueError(f"falta {campo!r}")
        meses, _ = catalogo._partes_lag(regla["lag"])
        if regla["fin_periodo"] not in catalogo.FINES_PERIODO:
            raise ValueError(f"fin_periodo {regla['fin_periodo']!r} no es uno de {list(catalogo.FINES_PERIODO)}")
        if meses and regla["fin_periodo"] == "fecha":
            raise ValueError("un lag en meses necesita fin_periodo mes, trimestre o anio")
        catalogo._validar_habiles(regla.get("habiles"), regla.get("n_habiles"), donde)
        if regla.get("tramos") is not None:
            catalogo._validar_tramos(regla["tramos"], regla["fin_periodo"], donde)
    except ValueError as err:
        raise ValueError(f"{donde}: {err}") from None
    return regla


def regla_actual(clave: str, lags: dict[str, dict] | None = None,
                 publicaciones: dict[str, Any] | None = None) -> dict[str, Any]:
    """La regla que fecha hoy una clave: su entrada de ``lags.yaml`` o su publicador de ``publicaciones.yaml``."""
    lags = lags if lags is not None else catalogo.cargar_lags()
    if clave in lags:
        e = lags[clave]
        return {k: e[k] for k in ("lag", "fin_periodo", "habiles", "n_habiles", "tramos") if e.get(k) is not None}
    pubs = (publicaciones if publicaciones is not None else visibilidad._publicaciones_defecto())["publicadores"]
    if clave in pubs:
        return {"publicador": clave}
    raise KeyError(f"regla {clave!r} ni en lags.yaml ni en los publicadores de publicaciones.yaml")


def _clave_lags(clave: str, entrada: dict[str, Any]) -> str:
    """La clave de lags.yaml o publicaciones.yaml de una entrada del plan (``regla_de_lags`` si la entrada solo
    cambia la regla para algunas fuentes, como el HICP y el ESI de Eurostat, que usan la de CPIAUCSL y UMCSENT)."""
    return entrada.get("regla_de_lags") or clave


def _comparar_actual(clave: str, actual: Any, lags: dict, publicadores: dict, donde: str) -> None:
    """La regla «actual» del plan tiene que ser la de lags.yaml o publicaciones.yaml, tal cual."""
    if not isinstance(actual, dict):
        raise ValueError(f"{donde}: 'actual' debe ser un diccionario")
    if clave in lags:
        e = lags[clave]
        for campo in ("lag", "fin_periodo", "habiles", "n_habiles"):
            if actual.get(campo) != e.get(campo):
                raise ValueError(f"{donde}: actual.{campo} = {actual.get(campo)!r}, pero lags.yaml dice {e.get(campo)!r}")

        def _tr(ts: Any) -> list[dict[str, Any]]:
            return [{k: (str(t.get(k)) if t.get(k) is not None else None) for k in ("desde", "hasta", "lag", "habiles")}
                    for t in ts or []]
        if _tr(e.get("tramos")) != _tr(actual.get("tramos")):
            raise ValueError(f"{donde}: actual.tramos no coincide con lags.yaml")
        return
    if clave not in publicadores:
        raise ValueError(f"{donde}: {clave!r} no está en lags.yaml ni en los publicadores de publicaciones.yaml")
    visibilidad._claves(actual, {"publicador", "dia", "hora", "huso"}, {"habiles"}, donde)
    p = publicadores[clave]
    if actual["publicador"] != clave:
        raise ValueError(f"{donde}: actual.publicador debe ser {clave!r}")
    pares = {"dia": (actual["dia"], p["dia"]), "hora": (_hora_txt(actual["hora"]), _hora_txt(p["hora"])),
             "huso": (actual["huso"], p["huso"]), "habiles": (actual.get("habiles"), p.get("habiles"))}
    for campo, (a, b) in pares.items():
        if a != b:
            raise ValueError(f"{donde}: actual.{campo} = {a!r}, pero publicaciones.yaml dice {b!r}")


def _texto_no_vacio(e: dict, campo: str, donde: str) -> None:
    if not str(e.get(campo) or "").strip():
        raise ValueError(f"{donde}: falta {campo!r}")


def _dias_extra(adelanto: float, veredicto: str, margen: int) -> int:
    """No fiable: techo(adelanto) + margen; fiable con margen: techo(adelanto), sin margen (ronda de corrección)."""
    return math.ceil(float(adelanto)) + (int(margen) if veredicto == "no fiable" else 0)


def validar_plan(crudo: Any, origen: str = "preprocesado.yaml", *, lags: dict[str, dict] | None = None,
                 publicaciones: dict[str, Any] | None = None) -> dict[str, Any]:
    """Valida el borrador y lo devuelve (copia). ``ValueError`` con el sitio exacto del error."""
    if not isinstance(crudo, dict):
        raise ValueError(f"{origen}: se esperaba un diccionario")
    visibilidad._claves(crudo, set(SECCIONES), set(), origen)
    if crudo["estado"] != "borrador":
        raise ValueError(f"{origen}: estado {crudo['estado']!r}; en el paso 3 el plan es un 'borrador'")
    lags = lags if lags is not None else catalogo.cargar_lags()
    pubs = (publicaciones if publicaciones is not None else visibilidad._publicaciones_defecto())["publicadores"]
    plan = copy.deepcopy(crudo)

    # 1. Reglas conservadoras (E4)
    rc = plan["reglas_conservadoras"]
    if not isinstance(rc, dict) or set(rc) != set(GRUPOS):
        raise ValueError(f"{origen}: reglas_conservadoras necesita exactamente los grupos {list(GRUPOS)}")
    vistas: dict[str, str] = {}
    for grupo, g in rc.items():
        dg = f"{origen}: reglas_conservadoras.{grupo}"
        visibilidad._claves(g, _CLAVES_GRUPO, _CLAVES_GRUPO_OPC, dg)
        for clave, e in (g["reglas"] or {}).items():
            de = f"{dg}.{clave}"
            visibilidad._claves(e, _CLAVES_ENTRADA, _CLAVES_ENTRADA_OPC, de)
            if clave in vistas:
                raise ValueError(f"{de}: la regla ya está en el grupo {vistas[clave]!r}")
            vistas[clave] = grupo
            if e.get("regla_de_lags") and not e.get("fuentes"):
                raise ValueError(f"{de}: 'regla_de_lags' necesita 'fuentes' (solo cambia la regla en esas fuentes)")
            base_clave = _clave_lags(clave, e)
            _comparar_actual(base_clave, e["actual"], lags, pubs, de)
            for campo in ("fuente", "motivo"):
                _texto_no_vacio(e, campo, de)
            pendiente = e.get("pendiente_calendario", False)
            if not isinstance(pendiente, bool):
                raise ValueError(f"{de}: pendiente_calendario debe ser true o false")
            if pendiente != (e.get("conservadora") is None):
                raise ValueError(f"{de}: sin 'conservadora' hace falta pendiente_calendario: true (y al revés)")
            if pendiente:
                _texto_no_vacio(e, "falta", de)
            if e.get("conservadora") is not None:
                _validar_regla(e["conservadora"], f"{de}.conservadora", pubs)
                if "publicador" in e["conservadora"] and e["conservadora"]["publicador"] != base_clave:
                    raise ValueError(f"{de}: la conservadora de un publicador se apoya en él mismo ({base_clave!r})")
            for nombre, alt in (e.get("alternativas") or {}).items():
                visibilidad._claves(alt, {"regla", "descripcion"}, {"hasta_vintage"}, f"{de}.alternativas.{nombre}")
                _validar_regla(alt["regla"], f"{de}.alternativas.{nombre}", pubs)

    # 2. Tramo no fiable (E5): una entrada por serie
    nf = plan["tramo_no_fiable"]
    visibilidad._claves(nf, {"descripcion", "margen_dias", "medida", "fuente", "episodios_excluidos", "reglas",
                             "series"}, {"notas", "derivadas"}, f"{origen}: tramo_no_fiable")
    margen = nf["margen_dias"]
    if not isinstance(margen, int) or isinstance(margen, bool) or margen < 0:
        raise ValueError(f"{origen}: tramo_no_fiable.margen_dias debe ser un entero >= 0")
    for i, ep in enumerate(nf["episodios_excluidos"] or []):
        visibilidad._claves(ep, {"desde", "hasta", "reglas", "motivo", "fuente"}, set(),
                            f"{origen}: tramo_no_fiable.episodios_excluidos[{i}]")
    for clave, e in (nf["reglas"] or {}).items():
        de = f"{origen}: tramo_no_fiable.reglas.{clave}"
        visibilidad._claves(e, {"tipo", "actual"}, set(), de)
        esperado = regla_actual(clave, lags, {"publicadores": pubs})
        if e["actual"] != esperado:
            raise ValueError(f"{de}: actual {e['actual']!r} no es la regla de hoy {esperado!r}")
        if e["tipo"] != ("publicador" if "publicador" in esperado else "lag"):
            raise ValueError(f"{de}: tipo {e['tipo']!r} no corresponde a la regla")
    for sid, e in (nf["series"] or {}).items():
        de = f"{origen}: tramo_no_fiable.series.{sid}"
        visibilidad._claves(e, _CLAVES_NF_SERIE, {"nota"}, de)
        if e["regla"] not in (nf["reglas"] or {}):
            raise ValueError(f"{de}: regla {e['regla']!r} no está en tramo_no_fiable.reglas")
        if e["veredicto"] not in VEREDICTOS_TRAMO:
            raise ValueError(f"{de}: veredicto {e['veredicto']!r} no es uno de {list(VEREDICTOS_TRAMO)}")
        extra = _dias_extra(e["adelanto_dias"], e["veredicto"], margen)
        if e["dias_extra"] != extra:
            raise ValueError(f"{de}: dias_extra {e['dias_extra']} != {extra} (techo del adelanto"
                             f"{' + margen' if e['veredicto'] == 'no fiable' else ''})")
        _validar_regla(e["conservadora"], f"{de}.conservadora", pubs)
        if e["conservadora"] != _conservadora_tramo(nf["reglas"][e["regla"]]["actual"], extra):
            raise ValueError(f"{de}: conservadora no es la regla actual + {extra} días")

    # 3. H.15 diario y reconstruidas
    h = plan["h15_diario"]
    visibilidad._claves(h, {"descripcion", "publicador", "hasta", "conservadora", "fuente"}, {"notas"},
                        f"{origen}: h15_diario")
    _validar_regla(h["conservadora"], f"{origen}: h15_diario.conservadora", pubs)
    rec = plan["reconstruidas"]
    visibilidad._claves(rec, {"descripcion", "fuente", "series", "pendiente_calendario"}, {"notas"},
                        f"{origen}: reconstruidas")
    for sid, f in (rec["series"] or {}).items():
        catalogo._fecha_tramo(f, f"{origen}: reconstruidas.series.{sid}")
    for patron, e in (rec["pendiente_calendario"] or {}).items():
        dp = f"{origen}: reconstruidas.pendiente_calendario.{patron}"
        visibilidad._claves(e, {"falta", "web", "motivo"}, set(), dp)

    # 4. Proyecciones (D4)
    pr = plan["proyecciones"]
    visibilidad._claves(pr, {"descripcion", "destino", "columnas", "identificacion", "esperadas"}, {"notas"},
                        f"{origen}: proyecciones")
    if tuple(pr["columnas"]) != COLUMNAS_PROYECCIONES:
        raise ValueError(f"{origen}: proyecciones.columnas debe ser {list(COLUMNAS_PROYECCIONES)}")

    # 5. Homogeneización y escalas por vintage
    ho = plan["homogeneizacion"]
    visibilidad._claves(ho, {"unidades_equivalentes", "escalas", "frecuencias", "alias"},
                        {"no_equivalentes", "sin_escalar", "notas"}, f"{origen}: homogeneizacion")
    for i, par in enumerate(ho["unidades_equivalentes"] or []):
        visibilidad._claves(par, {"unidades", "canonica", "motivo"}, set(),
                            f"{origen}: homogeneizacion.unidades_equivalentes[{i}]")
        if len(par["unidades"]) < 2 or par["canonica"] not in par["unidades"]:
            raise ValueError(f"{origen}: homogeneizacion.unidades_equivalentes[{i}]: hacen falta dos unidades o más y "
                             "la canónica entre ellas")
    for i, esc in enumerate(ho["escalas"] or []):
        visibilidad._claves(esc, {"unidad", "factor", "unidad_nueva", "motivo", "series"}, set(),
                            f"{origen}: homogeneizacion.escalas[{i}]")
        if not isinstance(esc["factor"], (int, float)) or esc["factor"] <= 0 or not esc["series"]:
            raise ValueError(f"{origen}: homogeneizacion.escalas[{i}]: factor > 0 y al menos una serie")
    if ho["frecuencias"].get("remuestrear") is not False:
        raise ValueError(f"{origen}: homogeneizacion.frecuencias.remuestrear debe ser false (frecuencias nativas)")
    ev = plan["escalas_por_vintage"]
    visibilidad._claves(ev, {"descripcion", "fuente", "criterio", "series"}, {"notas"}, f"{origen}: escalas_por_vintage")
    for i, e in enumerate(ev["series"] or []):
        visibilidad._claves(e, {"serie", "antes_de_vintage", "factor"}, {"comunes"},
                            f"{origen}: escalas_por_vintage.series[{i}]")

    # 6. Incidencias del EDA
    for tipo, e in (plan["incidencias_eda"]["tipos"] or {}).items():
        de = f"{origen}: incidencias_eda.tipos.{tipo}"
        visibilidad._claves(e, {"accion", "nota"}, set(), de)
        if e["accion"] not in ACCIONES_EDA:
            raise ValueError(f"{de}: accion {e['accion']!r} no es una de {list(ACCIONES_EDA)}")

    # 7. Salidas del paso 4
    visibilidad._claves(plan["salidas_paso4"], {"ficheros", "verificaciones"}, {"notas"}, f"{origen}: salidas_paso4")
    return plan


def cargar_plan(ruta: Path | None = None) -> dict[str, Any]:
    """``config/preprocesado.yaml`` validado (``validar_plan``)."""
    r = Path(ruta) if ruta is not None else RUTA_PLAN
    return validar_plan(_yaml(r), r.name)


# --- Funciones puras de fechas -------------------------------------------------------------------------
def _tomar(codigos: np.ndarray, valores: np.ndarray) -> np.ndarray:
    nat = np.datetime64("NaT", "ns")
    if not len(valores):
        return np.full(len(codigos), nat, dtype="datetime64[ns]")
    return np.where(codigos >= 0, valores[np.maximum(codigos, 0)], nat).astype("datetime64[ns]")


def _fecha_publicador(fechas: pd.Series, clave: str, publicaciones: dict[str, Any] | None) -> pd.Series:
    """Fecha de decisión del publicador para cada fecha del dato (una llamada por fecha distinta)."""
    cfg = publicaciones if publicaciones is not None else visibilidad._publicaciones_defecto()
    codigos, unicos = pd.factorize(fechas)
    instantes = pd.Series(pd.array([visibilidad.disponible_publicador(clave, d, cfg) for d in unicos],
                                   dtype="datetime64[ns, UTC]"))
    dec = primera_decision_vec(instantes).to_numpy(dtype="datetime64[ns]")
    return pd.Series(_tomar(codigos, dec), index=fechas.index, dtype="datetime64[ns]")


def fecha_regla(fechas_referencia: Any, regla: dict[str, Any],
                publicaciones: dict[str, Any] | None = None) -> pd.Series:
    """Fecha de decisión que da ``regla`` a cada fecha de referencia (``datetime64[ns]``, mismo índice).

    De retraso: ``catalogo.fecha_publicacion_tramos`` (lags.yaml). De publicador: la fecha de decisión del
    publicador más ``lag`` días y, con ``habiles``, el primer hábil (``catalogo.fecha_publicacion_lag``). Se calcula
    una vez por fecha distinta: sirve para millones de filas.
    """
    s = pd.Series(pd.to_datetime(fechas_referencia)).dt.normalize()
    codigos, unicos = pd.factorize(s)
    u = pd.Series(pd.DatetimeIndex(unicos), dtype="datetime64[ns]")
    if "publicador" in regla:
        res = _fecha_publicador(u, regla["publicador"], publicaciones)
        if regla.get("lag") or regla.get("habiles"):
            res = catalogo.fecha_publicacion_lag(res, regla.get("lag") or "0D", "fecha", habiles=regla.get("habiles"))
    else:
        res = catalogo.fecha_publicacion_tramos(u, regla["lag"], regla["fin_periodo"], habiles=regla.get("habiles"),
                                                n_habiles=regla.get("n_habiles"), tramos=regla.get("tramos"))
    return pd.Series(_tomar(codigos, res.to_numpy(dtype="datetime64[ns]")), index=s.index, dtype="datetime64[ns]")


def fecha_conservadora(fechas_referencia: Any, fechas_actuales: Any, regla: dict[str, Any],
                       publicaciones: dict[str, Any] | None = None, tope: Any = None) -> pd.Series:
    """Fecha curada de cada fila: ``max(actual, min(regla conservadora, tope))``. Nunca adelanta una fecha.

    ``tope`` (opcional, por fila): fecha en que el valor ya es público con seguridad (primer vintage de ALFRED); la
    regla no pasa de ahí. Una fila sin fecha actual sigue sin ella (no se inventa); si la regla no da fecha, se queda
    la actual.
    """
    actual = pd.Series(pd.to_datetime(fechas_actuales)).astype("datetime64[ns]")
    regla_f = fecha_regla(pd.Series(pd.to_datetime(fechas_referencia), index=actual.index), regla, publicaciones)
    if tope is not None:
        t = pd.Series(pd.to_datetime(tope), index=actual.index).astype("datetime64[ns]")
        regla_f = regla_f.where(~(t.notna() & (t < regla_f)), t)
    mas_tarde = regla_f.notna() & actual.notna() & (regla_f > actual)
    return actual.where(~mas_tarde, regla_f)


def filas_afectadas(metodos: Any, fechas_publicacion: Any, corte: Any = None) -> pd.Series:
    """Filas que fecha una regla (``inventario.METODOS_REGLA``) y, con ``corte`` (``fiable_desde``), solo las
    publicadas antes de él. Las ``vintage_exacto`` y ``cierre_mercado`` no se tocan nunca."""
    m = pd.Series(metodos).astype(str).isin(inventario.METODOS_REGLA)
    if corte is not None and pd.notna(corte):
        pub = pd.Series(pd.to_datetime(fechas_publicacion), index=m.index)
        m &= pub < pd.Timestamp(corte)
    return m


def tope_primer_vintage(notas: Any) -> pd.Series:
    """El primer vintage X de la nota «anterior a ALFRED: valor del primer vintage (X)»; NaT si no la lleva."""
    s = pd.Series(notas, dtype=object)
    codigos, unicos = pd.factorize(s.astype(str).where(s.notna(), ""))
    x = pd.Series(unicos).str.extract(_PATRON_PREVIA, expand=False)
    fechas = pd.to_datetime(x, errors="coerce").to_numpy(dtype="datetime64[ns]")
    return pd.Series(_tomar(codigos, fechas), index=s.index, dtype="datetime64[ns]")


def sumar_dias_lag(lag: str, dias: int) -> str:
    """``"1M1D"`` + 24 → ``"1M25D"``; ``"24M"`` + 137 → ``"24M137D"``; ``"5D"`` + 22 → ``"27D"`` (formato lags.yaml)."""
    meses, d = catalogo._partes_lag(lag)
    total = d + int(dias)
    return f"{meses}M{total}D" if meses and total else (f"{meses}M" if meses else f"{total}D")


def _conservadora_tramo(actual: dict[str, Any], extra: int) -> dict[str, Any]:
    """Regla del tramo no fiable: la actual con ``extra`` días más (en cada tramo, si los tiene)."""
    if "publicador" in actual:
        return {"publicador": actual["publicador"], "lag": f"{extra}D"}
    out = copy.deepcopy(actual)
    out["lag"] = sumar_dias_lag(actual["lag"], extra)
    for t in out.get("tramos") or []:
        t["lag"] = sumar_dias_lag(t["lag"], extra)
    return out


# --- Propuestas a partir de las tablas del paso 2 y del EDA ------------------------------------------
def reglas_poca_muestra(fiabilidad: pd.DataFrame) -> set[str]:
    """Reglas con menos de ``inventario.MIN_COMPARACIONES`` comparaciones: cuentan como no medibles (como en el 02)."""
    return set(fiabilidad.loc[fiabilidad["n_comparaciones"] < inventario.MIN_COMPARACIONES, "regla"])


def _tablas_paso2() -> dict[str, pd.DataFrame]:
    t = resultados_dir(TEMA) / "tablas"
    return {"inventario": pd.read_csv(t / "inventario_series.csv"), "fiabilidad": pd.read_csv(t / "fiabilidad_c.csv"),
            "alfred_vs_lag": pd.read_csv(t / "alfred_vs_lag.csv"),
            "alfred_medida": pd.read_csv(t / "publicacion_alfred_medida.csv"),
            "excepciones": catalogo.cargar_excepciones()}


def adelantos_por_serie(claves: dict[str, str], tablas: dict[str, pd.DataFrame],
                        episodios: Iterable[dict[str, Any]] = (), lags: dict[str, dict] | None = None,
                        publicaciones: dict[str, Any] | None = None) -> pd.DataFrame:
    """Adelanto máximo medido de cada serie (``{id: clave_regla}``), en días: ``id``, ``adelanto_dias``,
    ``medida``, ``n``.

    - ``alfred_previa``: la regla previa frente a la primera vintage de ALFRED, periodo a periodo
      (``alfred_vs_lag.csv``: ``dias_adelanta_max``, ``n_periodos``).
    - ``excepciones``: la regla contrastada con ALFRED (``publicacion_alfred_medida.csv``): adelanto de cada periodo
      = excepción medida - regla (``config/excepciones_publicacion.csv``), sin los periodos de los
      ``episodios`` excluidos de su regla (Moody's fuera de FRED): ya los corrige la excepción y no se repiten.
    - las dos, si las hay: la mayor; ninguna: ``regla`` (el ``adelanto_max_dias`` de la regla en ``fiabilidad_c.csv``;
      la tabla no guarda percentiles por periodo, así que no hay p99: el máximo es más conservador).
    """
    lags = lags if lags is not None else catalogo.cargar_lags()
    avl = tablas["alfred_vs_lag"].set_index("serie")
    med = tablas["alfred_medida"]
    med = med[med["error"].isna()].set_index("serie") if "error" in med else med.set_index("serie")
    exc = tablas["excepciones"]
    exc_por = {s: g for s, g in exc.groupby("serie")}
    fia = tablas["fiabilidad"].set_index("regla")
    filas = []
    for sid, clave in claves.items():
        cands: list[tuple[float, str, int]] = []
        if sid in avl.index:
            r = avl.loc[sid]
            cands.append((float(r["dias_adelanta_max"] if pd.notna(r["dias_adelanta_max"]) else 0),
                          "alfred_previa", int(r["n_periodos"])))
        if sid in med.index:
            n = int(med.loc[sid, "n_cubiertas"])
            g = exc_por.get(sid)
            if g is not None and len(g):
                refs = pd.to_datetime(g["fecha_referencia"]).reset_index(drop=True)
                fuga = (pd.to_datetime(g["fecha_publicacion"]).reset_index(drop=True)
                        - fecha_regla(refs, regla_actual(clave, lags, publicaciones), publicaciones)).dt.days
                fuera = pd.Series(False, index=refs.index)
                for ep in episodios:
                    if clave in ep["reglas"]:
                        fuera |= (refs >= pd.Timestamp(str(ep["desde"]))) & (refs <= pd.Timestamp(str(ep["hasta"])))
                fuga = fuga[~fuera]
                cands.append((float(max(fuga.max(), 0)) if len(fuga) else 0.0, "excepciones", n))
            else:
                v = med.loc[sid, "fuga_max_dias"]
                cands.append((float(v) if pd.notna(v) else 0.0, "alfred_medida", n))
        if cands:
            a = max(cands, key=lambda c: c[0])
            filas.append({"id": sid, "adelanto_dias": a[0], "medida": a[1], "n": max(c[2] for c in cands)})
        elif clave in fia.index:
            f = fia.loc[clave]
            filas.append({"id": sid, "adelanto_dias": float(f["adelanto_max_dias"]) if pd.notna(f["adelanto_max_dias"])
                          else 0.0, "medida": "regla", "n": int(f["n_comparaciones"])})
    return pd.DataFrame(filas, columns=["id", "adelanto_dias", "medida", "n"])


def _clave_conservadora(plan: dict[str, Any], clave: str | None, fuente: str | None) -> tuple[str, str] | None:
    """``(grupo, entrada)`` de reglas_conservadoras para una regla y una fuente (las entradas con ``regla_de_lags``
    y ``fuentes`` mandan sobre la general)."""
    general = None
    for grupo, g in plan["reglas_conservadoras"].items():
        for nombre, e in (g["reglas"] or {}).items():
            if e.get("regla_de_lags"):
                if e["regla_de_lags"] == clave and fuente in e["fuentes"]:
                    return grupo, nombre
            elif nombre == clave:
                general = (grupo, nombre)
    return general


def propuesta_tramo(plan: dict[str, Any], lista: dict[str, dict], tablas: dict[str, pd.DataFrame] | None = None,
                    lags: dict[str, dict] | None = None,
                    publicaciones: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Series del tramo no fiable (E5, ronda de corrección), una entrada por serie que se queda:

    - ``no fiable`` desde 2000: corte = ``tramo_conservador_antes_de`` de la lista (``toda`` → toda la serie);
      ``dias_extra`` = techo(adelanto de la serie) + margen. Salen de aquí, y van a su grupo de
      ``reglas_conservadoras`` como no medibles, las que tienen una entrada propia por fuente (HICP y ESI de
      Eurostat) y las de menos de ``inventario.MIN_COMPARACIONES`` comparaciones con un grupo para su regla (LIOR3M).
    - ``fiable con margen`` que adelanta antes de su ``fiable_desde`` (adelanto de la serie > 0, sin las reglas de
      poca muestra): ``dias_extra`` = techo(adelanto), sin margen.
    Las derivadas no entran: el paso 4 las recalcula con sus componentes.
    """
    tablas = tablas if tablas is not None else _tablas_paso2()
    lags = lags if lags is not None else catalogo.cargar_lags()
    inv = tablas["inventario"].set_index("id")
    poca = reglas_poca_muestra(tablas["fiabilidad"])
    margen = plan["tramo_no_fiable"]["margen_dias"]
    candidatas: dict[str, tuple[str, Any]] = {}
    for sid, e in lista.items():
        if e.get("decision") != "queda" or sid not in inv.index:
            continue
        r = inv.loc[sid]
        ver, clave = r["veredicto_desde_2000"], r["clave_regla"]
        if r["metodo_publicacion"] == "derivada" or pd.isna(clave):
            continue
        if ver == "no fiable":
            antes = e.get("tramo_conservador_antes_de")
            candidatas[sid] = (ver, None if antes in (None, "toda") else antes)
        elif ver == "fiable con margen" and pd.notna(r["fiable_desde"]) and clave not in poca:
            candidatas[sid] = (ver, r["fiable_desde"])
    ade = adelantos_por_serie({s: inv.loc[s, "clave_regla"] for s in candidatas}, tablas,
                              plan["tramo_no_fiable"]["episodios_excluidos"] or [], lags, publicaciones)
    ade = ade.set_index("id")
    out: dict[str, dict[str, Any]] = {}
    for sid, (ver, corte) in sorted(candidatas.items()):
        clave, fuente = str(inv.loc[sid, "clave_regla"]), inv.loc[sid, "fuente"]
        destino = _clave_conservadora(plan, clave, fuente)
        if sid not in ade.index:
            continue
        a = ade.loc[sid]
        if ver == "no fiable":
            if destino and plan["reglas_conservadoras"][destino[0]]["reglas"][destino[1]].get("regla_de_lags"):
                continue
            if destino and a["medida"] != "regla" and a["n"] < inventario.MIN_COMPARACIONES:
                continue
        elif a["adelanto_dias"] <= 0 or a["medida"] == "regla":
            continue
        extra = _dias_extra(a["adelanto_dias"], ver, margen)
        out[sid] = {"regla": clave, "veredicto": ver, "corte": corte, "adelanto_dias": float(a["adelanto_dias"]),
                    "medida": a["medida"], "n": int(a["n"]), "dias_extra": extra,
                    "conservadora": _conservadora_tramo(regla_actual(clave, lags, publicaciones), extra)}
    return out


def propuesta_escalas_vintage(incidencias: pd.DataFrame, lista: dict[str, dict], factor_log: int = 3,
                              min_comunes: int = 20) -> list[dict[str, Any]]:
    """Cambios de unidad ×1000 confirmados entre vintages (``eda_series_incidencias.csv``, tipo ``cambio_unidad``):
    log10 del factor entero = ±``factor_log``, al menos ``min_comunes`` fechas comunes, sin declarar en el catálogo
    (``unidad_por_vintage``) y serie que se queda. ``factor``: lo que se multiplica a los vintages anteriores para
    llevarlos a la unidad vigente (la del catálogo)."""
    c = incidencias[incidencias["tipo"] == "cambio_unidad"]
    out = []
    for _, r in c.iterrows():
        comunes = _PATRON_COMUNES.search(str(r["nota"]))
        n = int(comunes.group(1)) if comunes else 0
        t = float(r["tamano"])
        if (abs(t - round(t)) < 0.01 and abs(round(t)) == factor_log and n >= min_comunes
                and "unidad_por_vintage" not in str(r["nota"]) and lista.get(r["serie"], {}).get("decision") == "queda"):
            out.append({"serie": r["serie"], "antes_de_vintage": str(r["fecha"]), "factor": float(10 ** round(t)),
                        "comunes": n})
    return sorted(out, key=lambda e: (e["serie"], e["antes_de_vintage"]))


def propuesta_incidencias() -> dict[str, dict[str, str]]:
    """``incidencias_eda.tipos`` desde ``eda.PROPUESTAS`` y ``eda.NOTAS`` (B2): un tipo por clave, sin claves muertas."""
    from ingesta.mercados_series import eda
    return {t: {"accion": a, "nota": eda.NOTAS.get(t, t)} for t, a in eda.PROPUESTAS.items()}


# --- Asignación de cada serie ---------------------------------------------------------------------------
def asignar_series(plan: dict[str, Any], lista: dict[str, dict], inventario_series: pd.DataFrame,
                   fiabilidad: pd.DataFrame | None = None) -> pd.DataFrame:
    """Qué parte del plan toca a cada serie que se queda (``lista_curada.yaml``, fuente de verdad): ``id``,
    ``seccion``, ``grupo``, ``regla``, ``corte``.

    - ``tramo_no_fiable``: las series de ``tramo_no_fiable.series`` (grupo ``no_fiable`` o ``fiable_con_margen``).
    - ``reglas_conservadoras``: aviso «no medible» de la lista, o «no fiable» sacada del tramo (entrada por fuente o
      poca muestra); el grupo es el de su entrada en el plan (la de ``regla_de_lags`` y ``fuentes`` si la hay).
    - ``sin_regla_en_plan``: con aviso y sin entrada en el plan (no debería haber ninguna; los tests lo comprueban).
    Las derivadas y las series sin aviso no se asignan.
    """
    inv = inventario_series.set_index("id")
    poca = reglas_poca_muestra(fiabilidad) if fiabilidad is not None else set()
    tramo = plan["tramo_no_fiable"]["series"] or {}
    filas = []
    for sid, e in lista.items():
        if e.get("decision") != "queda" or sid not in inv.index:
            continue
        r = inv.loc[sid]
        if sid in tramo:
            t = tramo[sid]
            filas.append({"id": sid, "seccion": "tramo_no_fiable", "grupo": VEREDICTOS_TRAMO[t["veredicto"]],
                          "regla": t["regla"], "corte": pd.to_datetime(t["corte"])})
            continue
        if r["metodo_publicacion"] == "derivada":
            continue
        aviso = e.get("aviso_fecha")
        no_medible = (aviso in ("no medible", "no fiable") or r["veredicto_desde_2000"] in ("no medible", "no fiable")
                      or (r["clave_regla"] in poca and r["veredicto_desde_2000"] in ("fiable", "fiable con margen")))
        if not no_medible:
            continue
        destino = _clave_conservadora(plan, r["clave_regla"], r["fuente"])
        if destino is None:
            filas.append({"id": sid, "seccion": "sin_regla_en_plan", "grupo": None, "regla": r["clave_regla"],
                          "corte": pd.NaT})
        else:
            filas.append({"id": sid, "seccion": "reglas_conservadoras", "grupo": destino[0], "regla": destino[1],
                          "corte": pd.NaT})
    return pd.DataFrame(filas, columns=["id", "seccion", "grupo", "regla", "corte"])


# --- Fechas curadas y verificaciones ---------------------------------------------------------------------
def _regla_conservadora(plan: dict[str, Any], seccion: str, grupo: str | None, clave: str,
                        sid: str) -> dict | None:
    if seccion == "tramo_no_fiable":
        return plan["tramo_no_fiable"]["series"][sid]["conservadora"]
    if seccion == "sin_regla_en_plan":
        return None
    return plan["reglas_conservadoras"][grupo]["reglas"][clave].get("conservadora")


def _series_h15(plan: dict[str, Any], catalogo_series: dict[str, dict] | None) -> set[str]:
    cat = catalogo_series if catalogo_series is not None else catalogo.cargar_catalogo()
    pub = plan["h15_diario"]["publicador"]
    return {s for s, e in cat.items() if e.get("publicador") == pub and e.get("frecuencia") == "diaria"}


def fechas_curadas(base: pd.DataFrame, plan: dict[str, Any], asignacion: pd.DataFrame,
                   publicaciones: dict[str, Any] | None = None,
                   catalogo_series: dict[str, dict] | None = None) -> pd.DataFrame:
    """Fecha curada de cada fila de ``base`` (mismo orden e índice) y la parte del plan que la toca.

    ``base``: ``serie``, ``fecha_referencia``, ``fecha_publicacion``, ``metodo_publicacion`` y, si las tiene,
    ``nota`` (tope del primer vintage) y ``disponible_utc``. Columnas: ``fecha_publicacion_curada``,
    ``fecha_capa1`` (solo con la capa 1), ``disponible_utc_curada`` (nula si la fecha cambia), ``seccion``, ``grupo``, ``regla`` (capa 1; nulas en las
    filas no afectadas), ``pendiente`` (regla sin conservadora: su fecha no cambia en la capa 1), ``con_tope``
    (la regla se paró en el primer vintage), ``h15`` y ``reconstruida`` (capas 2 y 3). Función pura.
    """
    cfg = publicaciones if publicaciones is not None else visibilidad._publicaciones_defecto()
    n = len(base)
    actual = base["fecha_publicacion"].to_numpy(dtype="datetime64[ns]")
    nueva = actual.copy()
    seccion, grupo, regla_col = (np.full(n, None, dtype=object) for _ in range(3))
    pendiente, con_tope, h15, reconstruida = (np.zeros(n, dtype=bool) for _ in range(4))
    serie_txt = base["serie"].astype(str)
    por_serie = {str(k): v for k, v in base.groupby(serie_txt, sort=False).indices.items()}
    metodos = base["metodo_publicacion"].astype(str).to_numpy()
    refs = base["fecha_referencia"].to_numpy(dtype="datetime64[ns]")
    tope = (tope_primer_vintage(base["nota"].to_numpy(dtype=object)).to_numpy(dtype="datetime64[ns]")
            if "nota" in base else np.full(n, np.datetime64("NaT", "ns")))

    # Capa 1: regla conservadora o tramo no fiable (agrupando las series con la misma regla)
    lotes: dict[tuple, list[np.ndarray]] = {}
    for _, a in asignacion.iterrows():
        ix = por_serie.get(str(a["id"]))
        if ix is None:
            continue
        ix = ix[filas_afectadas(metodos[ix], actual[ix], a["corte"]).to_numpy()]
        if not len(ix):
            continue
        gru = None if pd.isna(a["grupo"]) else a["grupo"]
        seccion[ix], grupo[ix], regla_col[ix] = a["seccion"], gru, a["regla"]
        regla = _regla_conservadora(plan, a["seccion"], gru, a["regla"], str(a["id"]))
        if regla is None:
            pendiente[ix] = True
            continue
        lotes.setdefault((json.dumps(regla, sort_keys=True, default=str),), []).append(ix)
    for (clave_json,), partes in lotes.items():
        ix = np.concatenate(partes)
        regla = json.loads(clave_json)
        sin_tope = fecha_conservadora(refs[ix], actual[ix], regla, cfg).to_numpy(dtype="datetime64[ns]")
        res = fecha_conservadora(refs[ix], actual[ix], regla, cfg, tope=tope[ix]).to_numpy(dtype="datetime64[ns]")
        con_tope[ix] = res < sin_tope
        nueva[ix] = res

    capa1 = nueva.copy()

    # Capa 2: H.15 diario antes de la fecha del plan
    h = plan["h15_diario"]
    ids_h = _series_h15(plan, catalogo_series) & set(por_serie)
    if ids_h:
        ix = np.concatenate([por_serie[s] for s in sorted(ids_h)])
        ix = ix[(metodos[ix] == "calendario") & (actual[ix] < np.datetime64(str(h["hasta"]), "ns"))]
        if len(ix):
            f = fecha_conservadora(refs[ix], nueva[ix], h["conservadora"], cfg).to_numpy(dtype="datetime64[ns]")
            h15[ix] = f > nueva[ix]
            nueva[ix] = f

    # Capa 3: índices reconstruidos hacia atrás
    for sid, desde in (plan["reconstruidas"]["series"] or {}).items():
        ix = por_serie.get(sid)
        if ix is None:
            continue
        d = np.datetime64(str(desde), "ns")
        ix = ix[actual[ix] < d]
        m = nueva[ix] < d
        reconstruida[ix[m]] = True
        nueva[ix[m]] = d

    if "disponible_utc" in base:
        disp = pd.Series(base["disponible_utc"].to_numpy(), index=base.index)
        disp_cur = disp.where(pd.Series(nueva == actual, index=base.index) | disp.isna(), pd.NaT)
    else:
        disp_cur = pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns, UTC]")
    return pd.DataFrame({"fecha_publicacion_curada": nueva, "fecha_capa1": capa1,
                         "disponible_utc_curada": disp_cur.to_numpy(),
                         "seccion": seccion, "grupo": grupo, "regla": regla_col, "pendiente": pendiente,
                         "con_tope": con_tope, "h15": h15, "reconstruida": reconstruida}, index=base.index)


def verificar(base: pd.DataFrame, curadas: pd.DataFrame) -> pd.DataFrame:
    """Las verificaciones del paso 4 fila a fila (``True`` = falla): ``adelanta`` (fecha curada anterior a la
    original), ``disponible_incoherente`` (``disponible_utc`` curado cuya primera decisión no es la fecha curada) y
    ``orden_roto`` (dentro de una serie y una fecha de referencia, ordenadas por la fecha original, la curada baja)."""
    act = base["fecha_publicacion"].to_numpy(dtype="datetime64[ns]")
    cur = curadas["fecha_publicacion_curada"].to_numpy(dtype="datetime64[ns]")
    adelanta = cur < act
    disp = pd.Series(curadas["disponible_utc_curada"].to_numpy(), index=base.index)
    incoh = np.zeros(len(base), dtype=bool)
    nn = disp.notna().to_numpy()
    if nn.any():
        esperada = primera_decision_vec(pd.to_datetime(disp[nn], utc=True)).to_numpy(dtype="datetime64[ns]")
        incoh[nn] = esperada != cur[nn]
    t = pd.DataFrame({"s": base["serie"].astype(str).to_numpy(), "r": base["fecha_referencia"].to_numpy(),
                      "a": act, "c": cur, "i": np.arange(len(base))}).sort_values(["s", "r", "a", "c"], kind="mergesort")
    mismo = (t["s"].to_numpy()[1:] == t["s"].to_numpy()[:-1]) & (t["r"].to_numpy()[1:] == t["r"].to_numpy()[:-1])
    baja = np.zeros(len(t), dtype=bool)
    baja[1:] = mismo & (t["c"].to_numpy()[1:] < t["c"].to_numpy()[:-1])
    orden = np.zeros(len(base), dtype=bool)
    orden[t["i"].to_numpy()[baja]] = True
    return pd.DataFrame({"adelanta": adelanta, "disponible_incoherente": incoh, "orden_roto": orden}, index=base.index)


# --- Proyecciones (D4) --------------------------------------------------------------------------------
def separar_proyecciones(base: pd.DataFrame, ids_proyeccion: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(base sin proyecciones, tabla de proyecciones)``. La tabla lleva las columnas de la base más
    ``horizonte`` (años entre la referencia y la edición: el ``H<h>`` del id del WEO o la diferencia de años con el
    vintage) y ``edicion`` (el vintage). No cambia ninguna fila; solo las reparte."""
    ids = set(ids_proyeccion)
    m = base["serie"].astype(str).isin(ids)
    proy = base[m].copy()
    edicion = proy["vintage"].astype(str)
    fecha_ed = pd.to_datetime(edicion, format="ISO8601", errors="coerce")
    h_id = proy["serie"].astype(str).str.extract(_PATRON_HORIZONTE, expand=False)
    h_vintage = pd.to_datetime(proy["fecha_referencia"]).dt.year - fecha_ed.dt.year
    proy["horizonte"] = pd.to_numeric(h_id, errors="coerce").fillna(h_vintage).astype("Int64")
    proy["edicion"] = edicion
    return base[~m].copy(), proy


# --- Simulación ------------------------------------------------------------------------------------------
def _leer_base_fechas(ids: Iterable[str], ruta: Path | None = None) -> pd.DataFrame:
    """Solo las columnas de fechas, método, vintage y nota de la base, solo de ``ids`` (lectura; sin valores)."""
    r = Path(ruta) if ruta is not None else almacen.ruta_series()
    cols = ["serie", "fecha_referencia", "fecha_publicacion", "disponible_utc", "vintage", "metodo_publicacion",
            "nota"]
    t = pq.read_table(r, columns=cols, filters=[("serie", "in", sorted(set(ids)))],
                      read_dictionary=["serie", "vintage", "metodo_publicacion", "nota"])
    return t.to_pandas()


def _resumen(sec: str, gru: str | None, clave: str | None, n_series: int, g: pd.DataFrame | None,
             pendiente: bool = False) -> dict[str, Any]:
    fila: dict[str, Any] = {"seccion": sec, "grupo": gru, "regla": clave, "n_series": int(n_series),
                            "filas_regla": 0 if g is None else int(len(g))}
    if pendiente:
        return {**fila, "filas_cambian": None, "pendiente_calendario": True}
    dias = np.array([], dtype=float) if g is None else g["dias"].to_numpy(dtype=float)
    cambian = dias[dias > 0]
    return {**fila, "filas_cambian": int(len(cambian)),
            "pct_cambian": round(100 * len(cambian) / len(dias), 2) if len(dias) else None,
            "retraso_mediana_dias": float(np.median(cambian)) if len(cambian) else None,
            "retraso_p95_dias": float(np.percentile(cambian, 95)) if len(cambian) else None,
            "retraso_max_dias": float(cambian.max()) if len(cambian) else None,
            "filas_adelantan": 0 if g is None else int(g["adelanta"].sum()),
            "filas_disponible_incoherente": 0 if g is None else int(g["disponible_incoherente"].sum()),
            "filas_orden_roto": 0 if g is None else int(g["orden_roto"].sum()),
            "filas_con_tope": 0 if g is None else int(g["con_tope"].sum()), "pendiente_calendario": False}


def simular(base: pd.DataFrame | None = None, plan: dict[str, Any] | None = None,
            lista: dict[str, dict] | None = None, inventario_series: pd.DataFrame | None = None,
            fiabilidad: pd.DataFrame | None = None, catalogo_series: dict[str, dict] | None = None,
            registro: Callable[[str], None] | None = None) -> pd.DataFrame:
    """Efecto del plan sobre las series que se quedan, en memoria: una fila por sección, grupo y regla
    (``COLUMNAS_SIMULACION``; días de la capa 1), más una por capa (``h15_diario``, ``reconstruidas``; días hasta la
    fecha final), la de ``escalas_por_vintage``
    (filas afectadas; no cambian fechas) y la de ``proyecciones`` (filas que irían a su tabla aparte). Las
    verificaciones se cuentan por grupo y en una fila ``total``. No escribe nada."""
    log = registro or (lambda _m: None)
    plan = plan if plan is not None else cargar_plan()
    lista = lista if lista is not None else cargar_lista()
    tablas = resultados_dir(TEMA) / "tablas"
    inv = inventario_series if inventario_series is not None else pd.read_csv(tablas / "inventario_series.csv")
    fia = fiabilidad if fiabilidad is not None else pd.read_csv(tablas / "fiabilidad_c.csv")
    asig = asignar_series(plan, lista, inv, fia)
    queda = {s for s, e in lista.items() if e.get("decision") == "queda"}
    proy_ids = {s for s, e in lista.items() if e.get("decision") == "proyecciones"}
    if base is None:
        t0 = time.perf_counter()
        base = _leer_base_fechas(queda | proy_ids)
        log(f"base (solo fechas): {len(base)} filas en {time.perf_counter() - t0:.1f} s")
    serie_txt = base["serie"].astype(str)
    b = base[serie_txt.isin(queda).to_numpy()]
    cur = fechas_curadas(b, plan, asig, catalogo_series=catalogo_series)
    ver = verificar(b, cur)
    dias = ((cur["fecha_publicacion_curada"].to_numpy(dtype="datetime64[ns]")
             - b["fecha_publicacion"].to_numpy(dtype="datetime64[ns]")) / np.timedelta64(1, "D"))
    dias1 = ((cur["fecha_capa1"].to_numpy(dtype="datetime64[ns]")
              - b["fecha_publicacion"].to_numpy(dtype="datetime64[ns]")) / np.timedelta64(1, "D"))
    todo = pd.concat([cur, ver], axis=1).assign(dias=dias, serie=serie_txt[serie_txt.isin(queda)].to_numpy())
    afect = todo[todo["seccion"].notna().to_numpy()]
    # por grupo, los días de su capa (la 1); las capas 2 y 3 tienen su fila propia
    afect = afect.assign(grupo=afect["grupo"].fillna("-"), dias=dias1[todo["seccion"].notna().to_numpy()])
    grupos_filas = {k: g for k, g in afect.groupby(["seccion", "grupo", "regla"], sort=False)}
    n_series = asig.assign(grupo=asig["grupo"].fillna("-")).groupby(["seccion", "grupo", "regla"]).size()
    filas = []
    for (sec, gru, clave), n in n_series.items():
        g = grupos_filas.get((sec, gru, clave))
        pend = sec == "sin_regla_en_plan" or (g is not None and bool(g["pendiente"].any()))
        filas.append(_resumen(sec, None if gru == "-" else gru, clave, n, g, pend))
    for capa in ("h15", "reconstruida"):
        g = todo[todo[capa].to_numpy()]
        filas.append(_resumen("h15_diario" if capa == "h15" else "reconstruidas", "capa", None,
                              g["serie"].nunique(), g))
    ev = plan["escalas_por_vintage"]["series"] or []
    if ev and "vintage" in b:
        vint = b["vintage"].astype(str).to_numpy()
        n_filas = sum(int(((serie_txt[serie_txt.isin(queda)].to_numpy() == e["serie"])
                           & (vint < str(e["antes_de_vintage"]))).sum()) for e in ev)
        filas.append({"seccion": "escalas_por_vintage", "grupo": "valores", "regla": None, "n_series": len(ev),
                      "filas_regla": n_filas, "filas_cambian": 0})
    if proy_ids:
        filas.append({"seccion": "proyecciones", "grupo": "tabla_aparte", "regla": None, "n_series": len(proy_ids),
                      "filas_regla": int(serie_txt.isin(proy_ids).sum()), "filas_cambian": 0})
    filas.append({"seccion": "total", "grupo": "verificaciones", "regla": None, "n_series": int(b["serie"].nunique()),
                  "filas_regla": int(len(b)), "filas_cambian": int((dias > 0).sum()),
                  "filas_adelantan": int(ver["adelanta"].sum()),
                  "filas_disponible_incoherente": int(ver["disponible_incoherente"].sum()),
                  "filas_orden_roto": int(ver["orden_roto"].sum()), "filas_con_tope": int(cur["con_tope"].sum())})
    for f in filas:
        log(f"{f['seccion']}/{f['grupo']}/{f['regla']}: {f.get('filas_cambian')} de {f['filas_regla']} filas cambian")
    return pd.DataFrame(filas, columns=list(COLUMNAS_SIMULACION))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ingesta.mercados_series.preprocesado",
                                 description="Valida el borrador del plan de preprocesado y simula su efecto "
                                             "(sin escribir ninguna base).")
    ap.add_argument("--solo-validar", action="store_true", help="solo carga y valida config/preprocesado.yaml")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    plan = cargar_plan()
    print(f"plan válido: {sum(len(g['reglas'] or {}) for g in plan['reglas_conservadoras'].values())} reglas "
          f"conservadoras, {len(plan['tramo_no_fiable']['series'] or {})} series del tramo no fiable")
    if args.solo_validar:
        return
    sim = simular(plan=plan, registro=print)
    carpeta = resultados_dir(TEMA) / "tablas"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / TABLA_SIMULACION
    sim.to_csv(ruta, index=False, encoding="utf-8", lineterminator="\n")
    tot = sim[sim["seccion"] == "total"].iloc[0]
    print(f"{ruta}: {int(tot['filas_cambian'])} filas cambiarían de fecha; {int(tot['filas_adelantan'])} adelantan; "
          f"{int(tot['filas_disponible_incoherente'])} con disponible_utc incoherente; "
          f"{int(tot['filas_orden_roto'])} con el orden de vintages roto; {time.perf_counter() - t0:.0f} s")
    if tot["filas_adelantan"] or tot["filas_disponible_incoherente"] or tot["filas_orden_roto"]:
        raise SystemExit("ERROR: alguna verificación falla")


if __name__ == "__main__":
    main()
