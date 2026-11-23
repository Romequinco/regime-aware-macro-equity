"""Orden única de refresco del Tema 1 (P07 de ``docs/fase2/mercados_series/AUDITORIA_SANEADO.md``).

``python -m ingesta.mercados_series refrescar --corte AAAA-MM-DD [opciones]`` encadena, en este orden, las órdenes
que antes se lanzaban a mano (unas 20), cada una en un proceso aparte con ``T1_CORTE`` en el entorno
(``corte.corte_vigente``), un log por paso en ``<corpus>/mercados_series/logs/refrescar/`` y una fila por paso en
``logs/refrescar_estado.csv`` (estado genérico del refresco: paso, inicio, fin, código de salida, intentos):

1. **Descargas** (con red; todas reanudables):
   - ``descargar-fred-vivo`` repetida mientras salga con 2 (quedan series);
   - ``descargar-alfred --refrescar`` de una sola pasada (sin límite de tiempo, ~20 min);
   - ``excepciones-alfred`` (reescribe ``config/excepciones_publicacion.csv``, versionado);
   - ``archivar-oas`` y las ediciones académicas (``fuentes.academicos --descargar --archivar``);
   - las órdenes ``descargar-<fuente>`` de ``__main__.FUENTES_CLI`` con sus argumentos por defecto;
   - precios de Yahoo: los tickers «queda» de ``config/lista_curada.yaml`` que viven en ``precios/yahoo``
     (CSV generado en ``logs/refrescar/``, no a mano).
2. **Base**: ``construir-base`` (``--sin-red`` si se saltan las descargas) e ``informe-alfred``.
3. **Re-selección** (solo con ``--reseleccionar``): ``inventario --sin-red`` → ``redundancia`` → ``eda`` →
   ``seleccion`` → ``preprocesado``. Por defecto la lista curada queda **congelada** (G6): si la re-selección la
   cambia, la orden **se para** (código 3) y enseña la diferencia; se sigue con ``--aceptar-seleccion``.
4. **Curado**: ``curar`` y ``curar-precios`` con el corte pedido (publicación atómica; si una verificación falla, no
   escriben nada y la orden se para).

El corte pedido no se escribe en ``config/corte.yaml``: cuando el refresco se da por bueno, se cambia allí y se hace
commit. ``--plan`` enseña los pasos sin ejecutar nada. ``--mensual`` es el mantenimiento mensual (P14):
``descargar-fred-vivo``, ``archivar-oas`` y las ediciones académicas, que solo se acumulan si alguien descarga cada mes.

Ejemplos::

    python -m ingesta.mercados_series refrescar --corte 2026-12-11 --plan
    python -m ingesta.mercados_series refrescar --corte 2026-12-11                 # todo (horas: lanzar en segundo plano)
    python -m ingesta.mercados_series refrescar --corte 2026-11-20 --sin-descargas # solo base + curado con lo ya bajado
    python -m ingesta.mercados_series refrescar --corte 2026-12-11 --desde curar   # reanudar desde un paso
    python -m ingesta.mercados_series refrescar --mensual
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ingesta.mercados_series import corte as corte_mod

MAX_TANDAS_FRED = 60            # descargar-fred-vivo: tandas de 8 minutos como mucho
SALIDA_PARADA_SELECCION = 3     # la re-selección cambió la lista curada y no se aceptó
CARPETA_LOGS = "refrescar"
FICHERO_ESTADO = "refrescar_estado.csv"
COLUMNAS_ESTADO = ("corte", "paso", "grupo", "inicio", "fin", "codigo", "intentos", "log")


@dataclass(frozen=True)
class Paso:
    nombre: str
    grupo: str                                  # descargas | base | seleccion | curado
    argv: tuple[str, ...]                       # argumentos de ``python -m <modulo>``
    modulo: str = "ingesta.mercados_series"
    repetir_si: tuple[int, ...] = ()            # códigos de salida que piden repetir la orden (reanudable)
    max_intentos: int = 1
    tolera: tuple[int, ...] = field(default=(0,))


def _fuentes_cli() -> dict[str, tuple[str, list[str]]]:
    from ingesta.mercados_series.__main__ import FUENTES_CLI

    return FUENTES_CLI


def pasos(corte: pd.Timestamp, *, sin_descargas: bool = False, reseleccionar: bool = False,
          fichero_tickers: Path | None = None) -> list[Paso]:
    """Lista de pasos del refresco completo, en orden."""
    etiqueta = f"refresco_{corte:%Y%m%d}"
    out: list[Paso] = []
    if not sin_descargas:
        out += [
            Paso("fred-vivo", "descargas", ("descargar-fred-vivo",), repetir_si=(2,), max_intentos=MAX_TANDAS_FRED),
            Paso("alfred", "descargas", ("descargar-alfred", "--refrescar", "--limite-segundos", "1000000000")),
            Paso("excepciones-alfred", "descargas", ("excepciones-alfred",)),
            Paso("archivar-oas", "descargas", ("archivar-oas",)),
            Paso("academicos", "descargas", ("--descargar", "--archivar"),
                 modulo="ingesta.mercados_series.fuentes.academicos"),
        ]
        out += [Paso(f"descargar-{f}", "descargas", (f"descargar-{f}",)) for f in _fuentes_cli()]
        tickers = str(fichero_tickers) if fichero_tickers else "<logs/refrescar/tickers_yahoo.csv>"
        out.append(Paso("precios-yahoo", "descargas",
                        ("descargar-precios", "--nivel", "ampliado", "--fichero", tickers, "--etiqueta", etiqueta)))
    out += [
        Paso("construir-base", "base", ("construir-base",) + (("--sin-red",) if sin_descargas else ())),
        Paso("informe-alfred", "base", ("informe-alfred",)),
    ]
    if reseleccionar:
        out += [
            Paso("inventario", "seleccion", ("inventario", "--sin-red")),
            Paso("redundancia", "seleccion", ("redundancia",)),
            Paso("eda", "seleccion", ("eda",)),
            Paso("seleccion", "seleccion", ("seleccion",)),
            Paso("preprocesado", "seleccion", ("preprocesado",)),
        ]
    out += [Paso("curar", "curado", ("curar",)), Paso("curar-precios", "curado", ("curar-precios",))]
    return out


def pasos_mensuales() -> list[Paso]:
    """Mantenimiento mensual (P14): lo que solo se acumula si alguien lo descarga cada mes."""
    return [
        Paso("fred-vivo", "mensual", ("descargar-fred-vivo",), repetir_si=(2,), max_intentos=MAX_TANDAS_FRED),
        Paso("archivar-oas", "mensual", ("archivar-oas",)),
        Paso("academicos", "mensual", ("--descargar", "--archivar"), modulo="ingesta.mercados_series.fuentes.academicos"),
    ]


def tickers_yahoo(lista: Path | None = None, origen: Path | None = None) -> list[str]:
    """Tickers «queda» de la lista curada que viven en ``precios/yahoo`` (los de Coinbase van por ``descargar-cripto``)."""
    from ingesta.mercados_series import almacen, curada_precios

    lista_p = curada_precios.cargar_lista_precios(lista)
    origen = Path(origen) if origen else almacen.corpus_dir(almacen.TEMA) / "precios"
    ficheros, _ = curada_precios.ficheros_origen(origen)
    return sorted(tk for tk, e in lista_p.items()
                  if e.get("decision") == "queda" and ficheros.get(tk, ("",))[0] == "yahoo")


def validar_corte(texto: str, hoy: pd.Timestamp | None = None) -> pd.Timestamp:
    t = corte_mod._validar(texto)
    hoy = (hoy or pd.Timestamp.today()).normalize()
    if t > hoy:
        raise ValueError(f"el corte {t.date()} es posterior a hoy ({hoy.date()})")
    return t


def lista_cambiada(ruta: Path) -> str:
    """Diferencia (``git diff --stat``) de la lista curada frente al último commit; vacía si no cambió."""
    r = subprocess.run(["git", "diff", "--stat", "--", str(ruta)], capture_output=True, text=True,
                       cwd=ruta.parent)
    return r.stdout.strip()


def _anotar(ruta: Path, fila: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_ESTADO)
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in COLUMNAS_ESTADO})


def ejecutar(lista: Sequence[Paso], corte: pd.Timestamp | None, carpeta_logs: Path, *,
             lanzar: Callable[..., int] | None = None, seguir_tras_error_descarga: bool = False,
             ruta_lista: Path | None = None, aceptar_seleccion: bool = False, registro=print) -> int:
    """Ejecuta los pasos en orden. Devuelve 0 si todo fue bien; si no, el código del paso que paró la cadena."""
    lanzar = lanzar or _lanzar
    env = dict(os.environ)
    if corte is not None:
        env[corte_mod.VARIABLE] = corte.date().isoformat()
    sello = f"{corte:%Y%m%d}" if corte is not None else "mensual"
    estado = carpeta_logs.parent / FICHERO_ESTADO
    for p in lista:
        log = carpeta_logs / f"{sello}_{p.nombre}.log"
        inicio = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
        codigo, intentos = None, 0
        while intentos < p.max_intentos:
            intentos += 1
            registro(f"[{p.grupo}] {p.nombre} (intento {intentos}): python -m {p.modulo} {' '.join(p.argv)}")
            codigo = lanzar([sys.executable, "-m", p.modulo, *p.argv], env=env, log=log)
            if codigo not in p.repetir_si:
                break
            time.sleep(1)
        _anotar(estado, {"corte": sello, "paso": p.nombre, "grupo": p.grupo, "inicio": inicio,
                         "fin": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "codigo": codigo,
                         "intentos": intentos, "log": log.name})
        if codigo not in p.tolera:
            if p.grupo in ("descargas", "mensual") and seguir_tras_error_descarga:
                registro(f"  {p.nombre}: código {codigo}; sigo (--seguir-tras-error). Log: {log}")
                continue
            registro(f"  {p.nombre}: código {codigo}; paro la cadena. Log: {log}")
            return int(codigo or 1)
        if p.nombre == "seleccion" and ruta_lista is not None:
            dif = lista_cambiada(ruta_lista)
            if dif and not aceptar_seleccion:
                registro("la re-selección CAMBIA la lista curada (G6): reviso antes de curar.\n" + dif +
                         "\nSi está bien: repite con --desde preprocesado --aceptar-seleccion; si no: "
                         "git checkout -- config/lista_curada.yaml")
                return SALIDA_PARADA_SELECCION
    return 0


def _lanzar(cmd: list[str], *, env: dict, log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n### {pd.Timestamp.now(tz='UTC').isoformat(timespec='seconds')} {' '.join(cmd)}\n")
        f.flush()
        return subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT).returncode


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingesta.mercados_series refrescar", description=__doc__.split("\n")[0])
    ap.add_argument("--corte", help="nuevo corte AAAA-MM-DD (obligatorio salvo con --mensual)")
    ap.add_argument("--mensual", action="store_true", help="solo el mantenimiento mensual (P14)")
    ap.add_argument("--plan", action="store_true", help="enseña los pasos y no ejecuta nada")
    ap.add_argument("--sin-descargas", action="store_true", help="solo base y curado con lo ya descargado")
    ap.add_argument("--reseleccionar", action="store_true", help="rehace inventario → selección (lista NO congelada)")
    ap.add_argument("--aceptar-seleccion", action="store_true", help="sigue aunque la re-selección cambie la lista")
    ap.add_argument("--desde", help="empieza en este paso (reanudar)")
    ap.add_argument("--solo", nargs="+", help="solo estos pasos")
    ap.add_argument("--seguir-tras-error", action="store_true", help="un fallo de descarga no para la cadena")
    a = ap.parse_args(argv)

    from ingesta.mercados_series import almacen

    logs = almacen.corpus_dir(almacen.TEMA) / "logs" / CARPETA_LOGS
    if a.mensual:
        corte, lista = None, pasos_mensuales()
    else:
        if not a.corte:
            ap.error("falta --corte AAAA-MM-DD (o usa --mensual)")
        corte = validar_corte(a.corte)
        fichero = logs / f"tickers_yahoo_{corte:%Y%m%d}.csv"
        lista = pasos(corte, sin_descargas=a.sin_descargas, reseleccionar=a.reseleccionar, fichero_tickers=fichero)
    nombres = [p.nombre for p in lista]
    if a.desde:
        if a.desde not in nombres:
            ap.error(f"--desde {a.desde}: pasos posibles: {', '.join(nombres)}")
        lista = lista[nombres.index(a.desde):]
    if a.solo:
        malos = sorted(set(a.solo) - set(nombres))
        if malos:
            ap.error(f"--solo: pasos desconocidos {malos}; posibles: {', '.join(nombres)}")
        lista = [p for p in lista if p.nombre in a.solo]
    vigente = corte_mod.corte_config()
    print(f"refresco: corte {'(mensual)' if corte is None else corte.date()} (vigente en config: {vigente.date()}); "
          f"{len(lista)} pasos")
    for i, p in enumerate(lista, 1):
        print(f"  {i:2d}. [{p.grupo}] {p.nombre}: python -m {p.modulo} {' '.join(p.argv)}")
    if a.plan:
        return 0
    if corte is not None and any(p.nombre == "precios-yahoo" for p in lista):
        logs.mkdir(parents=True, exist_ok=True)
        tks = tickers_yahoo()
        pd.DataFrame({"ticker": tks}).to_csv(fichero, index=False)
        print(f"tickers de Yahoo «queda»: {len(tks)} -> {fichero}")
    ruta_lista = Path(__file__).resolve().parent / "config" / "lista_curada.yaml"
    codigo = ejecutar(lista, corte, logs, seguir_tras_error_descarga=a.seguir_tras_error, ruta_lista=ruta_lista,
                      aceptar_seleccion=a.aceptar_seleccion)
    if codigo == 0 and corte is not None and corte != vigente:
        print(f"refresco terminado con el corte {corte.date()}. Si lo das por bueno, cambia config/corte.yaml a "
              f"\"{corte.date()}\" y haz commit (hoy dice {vigente.date()}).")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
