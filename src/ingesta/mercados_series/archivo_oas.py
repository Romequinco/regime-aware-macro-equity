"""Archivo periódico de las OAS de ICE BofA (paso 3b-1, decisión G4): ``archivar-oas``.

Problema: FRED solo sirve los últimos 3 años de las 8 series de ICE BofA (``fuentes.fred.OAS_ICE``;
licencia de ICE) y ALFRED tampoco guarda lo anterior, así que cada mes sale historia de la ventana.
Este módulo la conserva en el corpus (nunca en el repositorio: copyright de ICE):

- **Captura**: la ventana vigente entera de las 8 series, pedida con ``fuentes.fred.ClienteFred``
  (clave ``FRED_API_KEY`` de ``.env``, ritmo de ``ingesta.comun.http``, caché cruda del día), en
  ``<corpus>/mercados_series/archivo/ice_oas/captura_AAAA-MM-DD.parquet`` (fecha de Nueva York).
  Repetir la orden el mismo día no vuelve a pedir nada (caché) y no cambia la captura.
- **Capturas antiguas**: cada día con una descarga COMPLETA de lo vigente en la caché cruda de FRED
  (``crudo/fred/series_observations/<id>/``, bloques 2 y 3 y los refrescos de ``descargar-fred-vivo``;
  las incrementales cuentan como captura parcial) y sin captura propia se guarda también como
  ``captura_<día>.parquet`` con ``origen = crudo_fred``.
- **Acumulado**: ``acumulado.parquet``, unión de todas las capturas y del acumulado anterior
  (``unir``). Columnas ``ACUMULADO``: ``serie`` (id del catálogo, ``fred:BAML...``),
  ``fecha_referencia``, ``valor`` (nulo si FRED dio ``'.'``), ``ausente``, ``vintage`` (fecha de la
  PRIMERA captura que vio ese valor, ``AAAA-MM-DD``) y ``origen``. Por serie y fecha se guarda la
  secuencia de valores distintos en orden de captura: un valor que no cambia es una sola fila (repetir
  una captura no duplica) y un valor que cambia deja las dos filas, cada una con su vintage. Una fecha
  que sale de la ventana conserva sus filas. ``comprobar_no_encoge`` para la escritura si el acumulado
  nuevo tiene menos filas o pierde algún ``(serie, fecha_referencia, valor)`` del anterior. El
  acumulado se puede rehacer entero desde las capturas (``reconstruir``).

Cómo entra en la base (paso 4; NO se integra aquí ni se toca ``base.py``):

- Cada fila del acumulado es una observación de la serie con su regla actual del catálogo
  (``metodo: calendario``, ``publicador: ice_bofa_fred``): ``fecha_publicacion`` y ``disponible_utc``
  salen de ``fecha_referencia`` con esa regla (``fuentes.fred.tabla_serie``), exactamente igual que
  hoy. La fecha de captura es SOLO la vintage (cuándo lo vimos nosotros), nunca la fecha de publicación.
- Para la vintage ``unico`` de la base basta, por serie y fecha, la fila de vintage más antigua con
  valor (primer valor visto: lo mismo que hace hoy ``fuentes.fred.unir_archivo`` con la caché cruda).
  Si en el paso 4 se quisieran también las filas revisadas, una revisión solo se conoce desde su
  captura: habría que decidir si su ``fecha_publicacion`` es la regla o ``max(regla, captura)``.

Uso: ``python -m ingesta.mercados_series archivar-oas [--sin-red] [--sin-crudo]`` cada mes (antes de
que salgan de la ventana las fechas más antiguas; o con una tarea programada en el PC). ``--sin-red``
no descarga (solo capturas antiguas y unión); ``--sin-crudo`` no importa la caché cruda. Cada
ejecución deja una fila (sin valores) en ``archivo/ice_oas/registro.csv``.

This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import pandas as pd

from ingesta.mercados_series.contrato import FECHA
from ingesta.mercados_series.fuentes import fred

TEMA = "mercados_series"
PREFIJO = "captura_"
ACUMULADO = ("serie", "fecha_referencia", "valor", "ausente", "vintage", "origen")
ORIGEN_CAPTURA = "archivar-oas"
ORIGEN_CRUDO = "crudo_fred"
IDS_OAS = tuple(f"fred:{s}" for s in fred.OAS_ICE)

__all__ = ["ACUMULADO", "IDS_OAS", "ruta_archivo", "vacio", "normalizar", "tabla_captura", "capturar",
           "capturas_crudo", "leer_capturas", "unir", "comprobar_no_encoge", "reconstruir", "leer_acumulado",
           "cobertura", "archivar", "main"]


def ruta_archivo(raiz: Path | None = None) -> Path:
    """``<corpus>/mercados_series/archivo/ice_oas/`` (o ``raiz`` en los tests)."""
    if raiz is None:
        from ingesta.comun.rutas import corpus_dir

        raiz = corpus_dir(TEMA) / "archivo" / "ice_oas"
    raiz = Path(raiz)
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def vacio() -> pd.DataFrame:
    return normalizar(pd.DataFrame(columns=list(ACUMULADO)))


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas ``ACUMULADO`` con sus tipos (fecha naive a medianoche, vintage ``AAAA-MM-DD``)."""
    out = df[list(ACUMULADO)].copy()
    out["serie"] = out["serie"].astype(str)
    out["fecha_referencia"] = pd.to_datetime(out["fecha_referencia"]).dt.normalize().astype(FECHA)
    out["valor"] = pd.to_numeric(out["valor"]).astype("float64")
    out["ausente"] = out["ausente"].astype(bool)
    out["vintage"] = pd.to_datetime(out["vintage"]).dt.strftime("%Y-%m-%d")
    out["origen"] = out["origen"].astype(str)
    return out.reset_index(drop=True)


def tabla_captura(sid: str, observaciones: Iterable[dict], vintage: str, origen: str = ORIGEN_CAPTURA
                  ) -> pd.DataFrame:
    """Observaciones JSON de FRED de ``sid`` (id del catálogo) → filas ``ACUMULADO`` de una captura."""
    p = fred.parsear_observaciones(observaciones)
    p = p.drop_duplicates("fecha_referencia", keep="first")
    return normalizar(pd.DataFrame({"serie": sid, "fecha_referencia": p["fecha_referencia"], "valor": p["valor"],
                                    "ausente": p["ausente"], "vintage": vintage, "origen": origen}))


def _clave_valor(df: pd.DataFrame) -> pd.Series:
    """Valor comparable (``'.'`` si ausente; ``repr`` del float, exacto)."""
    return pd.Series([("." if a else repr(float(v))) for v, a in zip(df["valor"], df["ausente"])],
                     index=df.index, dtype=object)


def unir(*partes: pd.DataFrame) -> pd.DataFrame:
    """Unión de acumulados y capturas sin perder filas.

    Por ``(serie, fecha_referencia)`` ordena por ``vintage`` y deja una fila por cada racha de valores
    iguales (la de la primera vintage): un valor repetido en otra captura no añade nada y un valor
    distinto del anterior añade su fila. Una fecha ausente de una captura (fuera de su ventana) no
    cambia nada. Insertar filas en una secuencia de rachas nunca reduce su número: el resultado nunca
    tiene menos filas que cualquiera de las partes ya unidas. Mismo resultado en cualquier orden de
    las partes si cada captura entra entera (``reconstruir`` lo rehace desde todas).
    """
    partes = [normalizar(p) for p in partes if p is not None and len(p)]
    if not partes:
        return vacio()
    todo = pd.concat(partes, ignore_index=True)
    todo["_v"] = _clave_valor(todo)
    todo = todo.sort_values(["serie", "fecha_referencia", "vintage", "origen", "_v"], kind="mergesort")
    todo = todo.reset_index(drop=True)
    mismo_grupo = (todo["serie"].eq(todo["serie"].shift())
                   & todo["fecha_referencia"].eq(todo["fecha_referencia"].shift()))
    repetido = mismo_grupo & todo["_v"].eq(todo["_v"].shift())
    out = todo[~repetido].drop(columns="_v")
    return normalizar(out)


def _claves(df: pd.DataFrame) -> set[tuple]:
    return set(zip(df["serie"], df["fecha_referencia"], _clave_valor(df)))


def comprobar_no_encoge(previo: pd.DataFrame, nuevo: pd.DataFrame) -> None:
    """``ValueError`` si ``nuevo`` tiene menos filas que ``previo`` o pierde algún ``(serie, fecha, valor)``."""
    if len(nuevo) < len(previo):
        raise ValueError(f"el acumulado encogería: {len(previo)} -> {len(nuevo)} filas")
    perdidas = _claves(normalizar(previo)) - _claves(normalizar(nuevo))
    if perdidas:
        raise ValueError(f"el acumulado perdería {len(perdidas)} observaciones, p. ej. {sorted(perdidas)[:3]}")


def _escribir(df: pd.DataFrame, ruta: Path) -> Path:
    tmp = ruta.with_name(ruta.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, ruta)
    return ruta


def _ruta_captura(carpeta: Path, vintage: str) -> Path:
    return carpeta / f"{PREFIJO}{vintage}.parquet"


def leer_capturas(carpeta: Path) -> dict[str, pd.DataFrame]:
    """``{vintage: captura}`` de los ``captura_AAAA-MM-DD.parquet`` de ``carpeta``, por fecha."""
    out = {}
    for f in sorted(Path(carpeta).glob(f"{PREFIJO}*.parquet")):
        out[f.stem[len(PREFIJO):]] = normalizar(pd.read_parquet(f))
    return out


def capturar(cliente: fred.ClienteFred, ids: Sequence[str] = IDS_OAS,
             registro: Callable[[str], None] | None = None) -> tuple[pd.DataFrame, dict[str, str]]:
    """Ventana vigente entera de cada serie (``cliente.observaciones`` sin fechas) → ``(captura, errores)``.

    Vintage = ``cliente.hoy``. Un fallo de red de una serie queda en ``errores`` (sin la clave) y se sigue.
    """
    log = registro or (lambda _m: None)
    vintage = f"{cliente.hoy:%Y-%m-%d}"
    partes, errores = [], {}
    for sid in ids:
        try:
            obs = cliente.observaciones(sid.split(":", 1)[1])
        except fred.ErrorFred as e:
            errores[sid] = str(e)[:200]
            log(f"  {sid}: error {str(e)[:120]}")
            continue
        partes.append(tabla_captura(sid, obs, vintage))
    return (unir(*partes) if partes else vacio()), errores


def capturas_crudo(carpeta_crudo: Path | None = None, ids: Sequence[str] = IDS_OAS,
                   excluir: Iterable[str] = ()) -> dict[str, pd.DataFrame]:
    """Capturas antiguas en la caché cruda de FRED: ``{vintage: captura}`` (``origen = crudo_fred``).

    Un día por cada día con alguna descarga COMPLETA de lo vigente (completa o incremental); varias del
    mismo día se unen con ``fuentes.fred.unir_archivo`` (primer valor no nulo). Las descargas con
    ``realtime_*``, ``vintage_dates`` u ``output_type`` (mediciones de ALFRED) no cuentan. Sin red.
    """
    cliente = fred.ClienteFred(carpeta=carpeta_crudo or fred.ruta_crudo(), clave="sin-red")
    excluir = set(excluir)
    por_dia: dict[str, list[pd.DataFrame]] = {}
    for sid in ids:
        dias: dict[str, list] = {}
        for dia, _p, obs in cliente.descargas_vigentes(sid.split(":", 1)[1]):
            dias.setdefault(dia, []).append((dia, obs))
        for dia, descargas in dias.items():
            vintage = f"{dia[:4]}-{dia[4:6]}-{dia[6:8]}"
            if vintage in excluir:
                continue
            u = fred.unir_archivo(descargas)
            por_dia.setdefault(vintage, []).append(normalizar(pd.DataFrame({
                "serie": sid, "fecha_referencia": u["fecha_referencia"], "valor": u["valor"],
                "ausente": u["ausente"], "vintage": vintage, "origen": ORIGEN_CRUDO})))
    return {v: unir(*p) for v, p in sorted(por_dia.items())}


def reconstruir(carpeta: Path) -> pd.DataFrame:
    """Acumulado rehecho solo desde las capturas guardadas en ``carpeta``."""
    return unir(*leer_capturas(carpeta).values())


def leer_acumulado(carpeta: Path | None = None) -> pd.DataFrame:
    ruta = ruta_archivo(carpeta) / "acumulado.parquet"
    return normalizar(pd.read_parquet(ruta)) if ruta.exists() else vacio()


def cobertura(acumulado: pd.DataFrame) -> pd.DataFrame:
    """Por serie: primera y última fecha con valor, fechas, filas, vintages y fechas con valor revisado."""
    con = acumulado[~acumulado["ausente"]]
    g = con.groupby("serie")
    out = pd.DataFrame({
        "inicio": g["fecha_referencia"].min().dt.strftime("%Y-%m-%d"),
        "fin": g["fecha_referencia"].max().dt.strftime("%Y-%m-%d"),
        "fechas": g["fecha_referencia"].nunique(),
        "filas": acumulado.groupby("serie").size(),
        "vintages": acumulado.groupby("serie")["vintage"].nunique(),
        "fechas_revisadas": (acumulado.groupby(["serie", "fecha_referencia"]).size() > 1).groupby(level="serie").sum(),
    })
    return out.reset_index()


def archivar(*, cliente: fred.ClienteFred | None = None, carpeta: Path | None = None, descargar: bool = True,
             importar_crudo: bool = True, carpeta_crudo: Path | None = None, ids: Sequence[str] = IDS_OAS,
             registro: Callable[[str], None] | None = None) -> dict:
    """Captura de hoy + capturas antiguas de la caché cruda + unión al acumulado (sin encoger).

    Devuelve ``{captura, nuevas, errores, filas_previas, filas, ruta}`` (solo recuentos y rutas).
    """
    log = registro or (lambda _m: None)
    carpeta = ruta_archivo(carpeta)
    escritas, errores = [], {}
    if descargar:
        cliente = cliente or fred.ClienteFred()
        vintage = f"{cliente.hoy:%Y-%m-%d}"
        captura, errores = capturar(cliente, ids, registro=log)
        ruta = _ruta_captura(carpeta, vintage)
        if ruta.exists():   # mismo día: se conserva lo ya capturado y se añaden las series que faltaban
            previa = normalizar(pd.read_parquet(ruta))
            captura = unir(previa, captura[~captura["serie"].isin(set(previa["serie"]))])
        if len(captura):
            _escribir(captura, ruta)
            escritas.append(vintage)
            log(f"captura {vintage}: {captura['serie'].nunique()} series, {len(captura)} filas -> {ruta}")
    if importar_crudo:
        existentes = set(leer_capturas(carpeta))
        for vintage, cap in capturas_crudo(carpeta_crudo, ids, excluir=existentes).items():
            _escribir(cap, _ruta_captura(carpeta, vintage))
            escritas.append(vintage)
            log(f"captura antigua {vintage} (caché cruda de FRED): {cap['serie'].nunique()} series, {len(cap)} filas")
    previo = leer_acumulado(carpeta)
    nuevo = unir(previo, *leer_capturas(carpeta).values())
    comprobar_no_encoge(previo, nuevo)
    ruta_acum = _escribir(nuevo, carpeta / "acumulado.parquet")
    fila = {"fecha_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "capturas_nuevas": " ".join(escritas), "filas_previas": len(previo), "filas": len(nuevo),
            "series": nuevo["serie"].nunique(), "errores": " ".join(sorted(errores))}
    reg = carpeta / "registro.csv"
    pd.DataFrame([fila]).to_csv(reg, mode="a", header=not reg.exists(), index=False, encoding="utf-8")
    return {"capturas_nuevas": escritas, "errores": errores, "filas_previas": len(previo), "filas": len(nuevo),
            "ruta": str(ruta_acum)}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingesta.mercados_series archivar-oas",
                                description="Archivo de las OAS de ICE BofA (ventana móvil de 3 años en FRED)")
    p.add_argument("--sin-red", action="store_true", help="no descarga: solo capturas antiguas y unión")
    p.add_argument("--sin-crudo", action="store_true", help="no importa la caché cruda de FRED")
    a = p.parse_args(argv)
    rep = archivar(descargar=not a.sin_red, importar_crudo=not a.sin_crudo, registro=print)
    print(f"acumulado: {rep['filas_previas']} -> {rep['filas']} filas -> {rep['ruta']}")
    print(cobertura(leer_acumulado()).to_string(index=False))
    print(fred.AVISO_FRED)
    if rep["errores"]:
        print("series con error:", rep["errores"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
