"""CLI del Tema 1: ``python -m ingesta.mercados_series <orden>``.

- ``descargar-alfred [--ids ...] [--limite-segundos N] [--refrescar]``: una tanda (reanudable) de
  vintages de ALFRED (``fuentes.alfred.descargar_vintages``); las series con error se reintentan una
  vez. Sale con 2 si quedan series pendientes (repetir la orden sigue donde se quedó) y con 1 si
  alguna sigue con error. Cada tanda deja una fila en ``<corpus>/mercados_series/logs/descargas.csv``.
- ``descargar-fred-vivo [--ids ...] [--max-minutos N] [--completa]``: ídem con la fuente viva de FRED
  (``fuentes.fred.descargar_fred_vivo``: completa la primera vez, incremental después).
- ``descargar-<fuente> [argumentos del módulo]`` (bloques 4 a 6): delega en la CLI de cada extractor
  (``FUENTES_CLI``: bce, eurostat, bis, imf, worldbank, oecd, philly, bancos, curvas, cripto). Sin
  argumentos usa los de ``FUENTES_CLI`` (descarga del día + fichas); los argumentos van tal cual.
- ``descargar-precios --nivel nucleo|ampliado [--fichero CSV] [--etiqueta E]``: precios as-traded de
  Yahoo (``proveedores.yahoo``; reanudable, <= 0,5 tickers/s).
- ``construir-base [--sin-red] [--desde-cero] [--respaldo F] [--reemplazar] [--errores-propios ID ...] [--purgar]
  [--sin-escribir]``:
  une ALFRED > académicos > FRED vivo > fuentes oficiales (BCE, Eurostat, BIS, FMI, Banco Mundial, OCDE,
  bancos centrales, curvas) > Philadelphia Fed (antes de ALFRED) > fase1 (``base.construir_base``), escribe
  ``<corpus>/mercados_series/series/base_series.parquet`` y
  ``results/ingesta/mercados_series/tablas/cobertura_series.csv``. ``--sin-red``: solo crudos ya
  descargados y ``data/raw``. ``--desde-cero``: copia la base guardada a
  ``series/respaldo_bloque2.parquet`` (si no existe ya) y la sustituye entera (cambio de reglas o
  fuentes). Las revisiones de valores de las revisables con vintage ``unico`` se admiten siempre;
  ``--reemplazar`` permite cambiar cualquier fila guardada (correcciones propias) y ``--purgar``
  quitar las series guardadas que ya no se construyen. ``--errores-propios``: series con un error propio de
  fechado declarado (sus filas guardadas solo pueden retrasar su fecha; claves y valores fijos). El
  solo-añadir de las oficiales sin historia de revisiones se aplica siempre, también con ``--desde-cero`` y
  ``--reemplazar``. Cada escritura deja la base anterior en ``series/base_series_previa.parquet`` (y la de
  antes en ``_previa_2``) y el desglose del solo-añadir en ``tablas/solo_anadir_ultima.csv``.
  ``--sin-escribir``: no escribe nada.
- ``informe-alfred``: desde la base guardada, ``tablas/alfred_revisiones_resumen.csv`` (revisiones por
  serie, en %, sin niveles) y ``tablas/alfred_vs_lag.csv`` (adelantos de la regla previa frente a la
  primera publicación real).
- ``resumen [--csv]``: recuentos de la base guardada (y, con ``--csv``, rehace la tabla de cobertura).
- ``inventario [--consultar-boe | --sin-red]`` (paso 2 de la descarga completa): ``inventario.construir_inventario``
  escribe ``tablas/inventario_series.csv``, ``inventario_precios.csv`` y ``fiabilidad_c.csv`` (solo metadatos
  y medidas) e imprime un resumen. El ``robots.txt`` del BoE (una petición: ``tablas/boe_rutas.csv`` y ficha
  ``boe``: motivo del bloqueo, estado ``fallo``) solo se consulta si aún no existe ``boe_rutas.csv`` o con
  ``--consultar-boe``;
  ``--sin-red`` no lo consulta nunca.
- ``redundancia [--destino DIR] [--max-tickers N] [--solo series|precios]`` (paso 2): delega en
  ``redundancia.main`` (pares de series y de ETF por correlación, sensibilidad del umbral, conceptos, Banco
  Mundial/WEO y mínimos de tickers en ``tablas/redundancia_*.csv`` y ``tickers_sensibilidad.csv``).
- ``eda``, ``seleccion`` y ``preprocesado`` (paso 3): delegan en ``<modulo>.main`` con el resto de argumentos.
  Orden de regeneración: ``eda`` → ``seleccion`` (lee ``eda_precios.csv``) → ``preprocesado`` (lee la lista curada).
- ``excepciones-alfred [--ids ...] [--sin-red]``: contrasta las reglas de publicación de las series de
  FRED con la primera vintage de ALFRED (``fuentes.fred.medir_excepciones``) y escribe
  ``config/excepciones_publicacion.csv`` y ``tablas/publicacion_alfred_medida.csv`` (solo fechas).
  Reanudable: lo descargado hoy se sirve de la caché.
- ``archivar-oas [--sin-red] [--sin-crudo]``: captura fechada de la ventana de FRED de las 8 OAS de ICE
  BofA y unión al acumulado sin perder historia (``archivo_oas``; ejecutar cada mes).
- ``curar-precios [--sin-escribir] [--tickers A,B] [--corte AAAA-MM-DD]`` (paso 4): ``<corpus>/mercados_series/precios_curados/`` con los
  tickers «queda», hasta el corte G2 y con las velas de relleno quitadas y las aperturas de relleno a nulo
  (``curada_precios``; no toca ``precios/``). Tablas ``precios_curados_{avisos,resumen,verificaciones}.csv``.
- ``refrescar --corte AAAA-MM-DD [--plan] [--sin-descargas] [--reseleccionar] [--desde PASO] | --mensual``: orden
  única de refresco (``refrescar``, P07 de la auditoría de saneado): descargas, base y curado con el corte pedido, la
  lista curada congelada por defecto y un estado por paso en ``logs/refrescar_estado.csv``.
- ``curar [--sin-escribir] [--corte AAAA-MM-DD]`` (paso 4): ``series/base_curada.parquet`` (mismo contrato: las «queda» con las fechas
  curadas, las escalas por vintage, las derivadas recalculadas y el corte G2), ``alias.parquet``,
  ``proyecciones.parquet`` y ``registro_cambios.parquet`` (``curada``; no toca ``base_series.parquet``). Tablas
  ``curada_verificaciones.csv`` y ``curada_resumen.csv``; si alguna verificación falla, no escribe nada.
- ``catalogo-agentes [--sin-escribir]``: catálogo para los agentes (``catalogo_agentes``): una fila por serie que
  queda en la curada, por proyección y por ticker de ``precios_curados``, solo metadatos y fechas, en
  ``tablas/catalogo_agentes.csv`` y ``catalogo_agentes_resumen.csv`` (escritura atómica). Lo lee ``buscar_series``.

This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _imprimir(d: dict) -> None:
    from ingesta.mercados_series.base import _np_a_py

    print(json.dumps(_np_a_py(d), indent=2, ensure_ascii=False, default=str))


def _registrar_descarga(fila: dict) -> Path:
    """Añade una fila (tanda de descarga, sin valores) a ``<corpus>/mercados_series/logs/descargas.csv``."""
    import pandas as pd

    from ingesta.mercados_series import almacen

    carpeta = almacen.corpus_dir(almacen.TEMA) / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "descargas.csv"
    pd.DataFrame([fila]).to_csv(ruta, mode="a", header=not ruta.exists(), index=False, encoding="utf-8")
    return ruta


def _descargar_alfred(a: argparse.Namespace) -> int:
    import time

    import pandas as pd

    from ingesta.mercados_series import catalogo
    from ingesta.mercados_series.fuentes import alfred

    cat = catalogo.cargar_catalogo()
    cliente = alfred.cliente_alfred()
    t0 = time.monotonic()
    rep = alfred.descargar_vintages(a.ids or None, cliente=cliente, cat=cat, refrescar=a.refrescar,
                                    limite_segundos=a.limite_segundos, registro=print)
    fallidas = rep.loc[rep["estado"] == "error", "serie"].tolist()
    reintentadas = []
    if fallidas and (a.limite_segundos is None or time.monotonic() - t0 < a.limite_segundos):
        print(f"reintento (una vez) de {len(fallidas)} series con error: {fallidas}")
        otra = alfred.descargar_vintages(fallidas, cliente=cliente, cat=cat, registro=print)
        rep = pd.concat([rep[rep["estado"] != "error"], otra], ignore_index=True)
        reintentadas = fallidas
    estados = {k: int(v) for k, v in rep["estado"].value_counts().items()}
    errores = rep.loc[rep["estado"] == "error", ["serie", "error"]].to_dict("records")
    pendientes = rep.loc[rep["estado"] == "pendiente", "serie"].tolist()
    fila = {"fecha": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "orden": "descargar-alfred",
            "peticiones": cliente.peticiones, "segundos": round(time.monotonic() - t0, 1),
            "descargadas": estados.get("descargada", 0), "archivo": estados.get("archivo", 0),
            "pendientes": len(pendientes), "errores": len(errores), "reintentadas": len(reintentadas),
            "series_error": " ".join(e["serie"] for e in errores)}
    print(f"tanda ALFRED: {estados}; {cliente.peticiones} peticiones en {fila['segundos']} s; log -> "
          f"{_registrar_descarga(fila)}")
    if errores:
        print("series con error tras el reintento:", errores)
        return 1
    if pendientes:
        print(f"quedan {len(pendientes)} series: repite la orden para seguir")
        return 2
    return 0


def _descargar_fred_vivo(a: argparse.Namespace) -> int:
    import time

    import pandas as pd

    from ingesta.mercados_series import catalogo
    from ingesta.mercados_series.fuentes import fred

    cat = catalogo.cargar_catalogo()
    cliente = fred.ClienteFred()
    t0 = time.monotonic()
    rep = fred.descargar_fred_vivo(a.ids or None, cliente=cliente, cat=cat, completa=a.completa,
                                   max_segundos=a.max_minutos * 60 if a.max_minutos else None, registro=print)
    reintentadas = sorted(rep["errores"])
    if reintentadas:
        print(f"reintento (una vez) de {len(reintentadas)} series con error: {reintentadas}")
        otra = fred.descargar_fred_vivo(reintentadas, cliente=cliente, cat=cat, completa=a.completa, registro=print)
        rep["errores"] = otra["errores"]
        rep["hechas"] += otra["hechas"]
    fila = {"fecha": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "orden": "descargar-fred-vivo",
            "peticiones": cliente.peticiones, "segundos": round(time.monotonic() - t0, 1),
            "descargadas": len(rep["hechas"]), "archivo": len(rep["cache"]), "pendientes": len(rep["pendientes"]),
            "errores": len(rep["errores"]), "reintentadas": len(reintentadas),
            "series_error": " ".join(sorted(rep["errores"]))}
    print(f"tanda FRED vivo: {len(rep['hechas'])} descargadas, {len(rep['cache'])} ya de hoy, "
          f"{len(rep['pendientes'])} pendientes, {len(rep['errores'])} con error; {cliente.peticiones} peticiones "
          f"en {fila['segundos']} s; log -> {_registrar_descarga(fila)}")
    if rep["errores"]:
        print("series con error tras el reintento:", rep["errores"])
        return 1
    if rep["pendientes"]:
        print(f"quedan {len(rep['pendientes'])} series: repite la orden para seguir")
        return 2
    return 0


def _informe_alfred(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import almacen, catalogo
    from ingesta.mercados_series.base import AVISO_FRED
    from ingesta.mercados_series.fuentes import alfred

    ruta = almacen.ruta_series()
    if not ruta.exists():
        print(f"no hay base en {ruta}: python -m ingesta.mercados_series construir-base", file=sys.stderr)
        return 1
    cat = catalogo.cargar_catalogo()
    ids = alfred.ids_alfred(cat)
    tabla = almacen.leer_series(ids)
    for r in alfred.escribir_tablas_alfred(tabla, cat):
        print("->", r)
    print(AVISO_FRED)
    return 0


def _construir(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import base

    resumen, tabla = base.construir_base(sin_red=a.sin_red, escribir=not a.sin_escribir,
                                         permitir_perdidas=a.reemplazar, purgar=a.purgar,
                                         desde_cero=a.desde_cero, respaldo=a.respaldo,
                                         errores_propios=a.errores_propios or (), registro=print)
    if a.sin_escribir:
        print("ensayo (--sin-escribir): no se escribe ni la base ni la cobertura")
    else:
        print(f"cobertura -> {base.escribir_cobertura(base.cobertura(tabla))}")
        print(f"solo-añadir -> {base.escribir_solo_anadir(resumen.solo_anadir)}")
        print(f"anomalías -> {base.escribir_anomalias(resumen.detalle_anomalias)}")
    _imprimir({k: v for k, v in resumen.como_dict().items() if k != "detalle_anomalias"})
    print(base.AVISO_FRED)
    return 0


def _resumen(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import almacen, base

    ruta = almacen.ruta_series()
    if not ruta.exists():
        print(f"no hay base en {ruta}: python -m ingesta.mercados_series construir-base --sin-red", file=sys.stderr)
        return 1
    tabla = almacen.leer_series()
    print(f"base: {ruta}")
    _imprimir(base.resumen_base(tabla))
    if a.csv:
        print(f"cobertura -> {base.escribir_cobertura(base.cobertura(tabla))}")
    return 0


def _inventario(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import almacen, inventario

    if not almacen.ruta_series().exists():
        print(f"no hay base en {almacen.ruta_series()}: python -m ingesta.mercados_series construir-base --sin-red",
              file=sys.stderr)
        return 1
    consultar = False if a.sin_red else (True if a.consultar_boe else None)
    res = inventario.construir_inventario(consultar_boe_red=consultar, registro=print)
    for nombre, ruta in res.pop("rutas").items():
        print(f"{nombre} -> {ruta}")
    _imprimir(res)
    return 0


def _redundancia(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import redundancia

    argumentos = []
    if a.destino is not None:
        argumentos += ["--destino", str(a.destino)]
    if a.max_tickers is not None:
        argumentos += ["--max-tickers", str(a.max_tickers)]
    if a.solo:
        argumentos += ["--solo", a.solo]
    for nombre, ruta in redundancia.main(argumentos).items():
        print(f"{nombre} -> {ruta}")
    return 0


def _paso3(a: argparse.Namespace) -> int:
    """Delega en ``<modulo>.main`` con el resto de argumentos (pasos 3: seleccion, eda, preprocesado)."""
    import importlib

    modulo = importlib.import_module(f"ingesta.mercados_series.{a.orden}")
    salida = modulo.main(list(a.resto))
    if isinstance(salida, dict):
        for nombre, ruta in salida.items():
            print(f"{nombre} -> {ruta}")
    return 0


def _excepciones(a: argparse.Namespace) -> int:
    import pandas as pd

    from ingesta.comun.rutas import resultados_dir
    from ingesta.mercados_series import catalogo
    from ingesta.mercados_series.base import AVISO_FRED
    from ingesta.mercados_series.fuentes import fred

    cliente = fred.ClienteFred()
    if a.sin_red:
        cliente._transporte = _sin_red
    exc, medida = fred.medir_excepciones(cliente, a.ids or None, registro=print)
    exc = exc[list(catalogo.COLUMNAS_EXCEPCIONES)]
    if a.ids:   # actualización parcial: conserva las excepciones del resto de series
        previas = catalogo.cargar_excepciones()
        exc = pd.concat([previas[~previas["serie"].isin(a.ids)], exc], ignore_index=True)
    exc = exc.copy()
    for c in ("fecha_referencia", "fecha_publicacion"):
        exc[c] = pd.to_datetime(exc[c]).dt.strftime("%Y-%m-%d")
    exc = exc.sort_values(["serie", "fecha_referencia"], kind="mergesort")
    exc.to_csv(catalogo.RUTA_EXCEPCIONES, index=False, encoding="utf-8", lineterminator="\n")
    carpeta = resultados_dir("mercados_series") / "tablas"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_medida = carpeta / "publicacion_alfred_medida.csv"
    medida["origen"] = f"{fred.ORIGEN_EXCEPCION}_{cliente.hoy:%Y%m%d}"
    if a.ids and ruta_medida.exists():
        previa = pd.read_csv(ruta_medida)
        medida = pd.concat([previa[~previa["serie"].isin(a.ids)], medida], ignore_index=True)
    medida.sort_values("serie").to_csv(ruta_medida, index=False, encoding="utf-8", lineterminator="\n")
    errores = int(medida["error"].notna().sum()) if "error" in medida else 0
    print(f"{len(exc)} excepciones -> {catalogo.RUTA_EXCEPCIONES}\nmedida -> {ruta_medida}; "
          f"{cliente.peticiones} peticiones; {errores} series con error (repetir la orden las reintenta)")
    print(AVISO_FRED)
    return 1 if errores else 0


# Orden → (módulo, argumentos por defecto). Las descargas largas son reanudables en cada módulo.
FUENTES_CLI = {
    "bce": ("ingesta.mercados_series.fuentes.bce", ["--fichas"]),
    "eurostat": ("ingesta.mercados_series.fuentes.eurostat", ["--fichas"]),
    "bis": ("ingesta.mercados_series.fuentes.bis", []),
    "imf": ("ingesta.mercados_series.fuentes.imf", []),
    "worldbank": ("ingesta.mercados_series.fuentes.worldbank", []),
    "oecd": ("ingesta.mercados_series.fuentes.oecd", ["--descargar", "--ficha"]),
    "philly": ("ingesta.mercados_series.fuentes.philly_rtdsm", ["--descargar", "--ficha"]),
    "bancos": ("ingesta.mercados_series.fuentes.bancos_centrales", ["--descargar", "--fichas"]),
    "curvas": ("ingesta.mercados_series.fuentes.curvas", ["--descargar", "--fichas", "--escribir"]),
    "cripto": ("ingesta.mercados_series.fuentes.cripto", ["--coinbase", "--binance", "--comparar", "--fichas"]),
}


def _descargar_fuente(a: argparse.Namespace) -> int:
    import importlib

    modulo, defecto = FUENTES_CLI[a.fuente]
    argumentos = list(a.argumentos) or list(defecto)
    print(f"python -m {modulo} {' '.join(argumentos)}")
    r = importlib.import_module(modulo).main(argumentos)
    return int(r or 0)


def _descargar_precios(a: argparse.Namespace) -> int:
    from ingesta.mercados_series.proveedores import yahoo

    argumentos = [a.nivel]
    if a.fichero:
        argumentos += ["--fichero", str(a.fichero)]
    if a.etiqueta:
        argumentos += ["--etiqueta", a.etiqueta]
    return int(yahoo.main(argumentos) or 0)


def _archivar_oas(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import archivo_oas

    return archivo_oas.main(["--sin-red"] * a.sin_red + ["--sin-crudo"] * a.sin_crudo)


def _fijar_corte(a: argparse.Namespace) -> None:
    """``--corte``: pasa el corte por ``T1_CORTE`` antes de importar los módulos que lo leen (P07)."""
    if getattr(a, "corte", None):
        import os

        from ingesta.mercados_series import corte

        os.environ[corte.VARIABLE] = corte._validar(a.corte).date().isoformat()


def _refrescar(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import refrescar

    return refrescar.main(list(a.resto))


def _curar(a: argparse.Namespace) -> int:
    _fijar_corte(a)
    from ingesta.mercados_series import curada

    return curada.main(["--sin-escribir"] * a.sin_escribir)


def _curar_precios(a: argparse.Namespace) -> int:
    _fijar_corte(a)
    from ingesta.mercados_series import curada_precios

    return curada_precios.main(["--sin-escribir"] * a.sin_escribir + (["--tickers", a.tickers] if a.tickers else []))


def _catalogo_agentes(a: argparse.Namespace) -> int:
    from ingesta.mercados_series import catalogo_agentes

    return catalogo_agentes.main(["--sin-escribir"] * a.sin_escribir)


def _sin_red(url: str, params: dict) -> dict:
    raise RuntimeError("sin red (--sin-red): falta en la caché de hoy")


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingesta.mercados_series",
                                description="Tema 1 · base de series y precios (bloques 2 a 6)")
    sub = p.add_subparsers(dest="orden", required=True)
    da = sub.add_parser("descargar-alfred", help="una tanda de vintages de ALFRED (reanudable)")
    da.add_argument("--ids", nargs="*", help="ids del catálogo (por defecto fuentes.alfred.ids_alfred())")
    da.add_argument("--limite-segundos", type=float, default=480.0,
                    help="no empieza otra serie pasado este tiempo (por defecto 480)")
    da.add_argument("--refrescar", action="store_true", help="vuelve a descargar aunque haya archivo completo")
    da.set_defaults(func=_descargar_alfred)
    dv = sub.add_parser("descargar-fred-vivo", help="una tanda de la fuente viva de FRED (reanudable)")
    dv.add_argument("--ids", nargs="*", help="ids del catálogo (por defecto fuentes.fred.ids_fred_vivo())")
    dv.add_argument("--max-minutos", type=float, default=8.0, help="corta entre series tras N minutos (8)")
    dv.add_argument("--completa", action="store_true", help="descarga completa aunque haya archivo previo")
    dv.set_defaults(func=_descargar_fred_vivo)
    c = sub.add_parser("construir-base", help="une ALFRED + FRED vivo + académicos + fase1 y escribe la base")
    c.add_argument("--sin-red", action="store_true", help="solo crudos ya descargados y data/raw")
    c.add_argument("--desde-cero", action="store_true",
                   help="copia la base guardada a series/<respaldo> y la sustituye entera")
    c.add_argument("--respaldo", default="respaldo_bloque2.parquet",
                   help="nombre de la copia previa con --desde-cero (p. ej. respaldo_bloque3.parquet)")
    c.add_argument("--reemplazar", action="store_true",
                   help="permite cambiar filas guardadas (revisiones del último vintage, errores propios)")
    c.add_argument("--errores-propios", nargs="+", default=None, metavar="ID",
                   help="series con un error propio de fechado declarado: sus filas guardadas solo retrasan su fecha")
    c.add_argument("--purgar", action="store_true",
                   help="quita de la base guardada las series que ya no se construyen (las enumera)")
    c.add_argument("--sin-escribir", action="store_true",
                   help="construye y valida sin escribir nada (ni el parquet ni la cobertura)")
    c.set_defaults(func=_construir)
    r = sub.add_parser("resumen", help="recuentos de la base guardada")
    r.add_argument("--csv", action="store_true", help="rehace tablas/cobertura_series.csv")
    r.set_defaults(func=_resumen)
    iv = sub.add_parser("inventario", help="inventario de series y precios, fiabilidad del nivel C y BoE (paso 2)")
    gb = iv.add_mutually_exclusive_group()
    gb.add_argument("--consultar-boe", action="store_true",
                    help="vuelve a consultar el robots.txt del BoE aunque exista tablas/boe_rutas.csv")
    gb.add_argument("--sin-red", action="store_true", help="no consulta el robots.txt del BoE")
    iv.set_defaults(func=_inventario)
    rd = sub.add_parser("redundancia", help="redundancia de series y ETF y sensibilidad de umbrales (paso 2)")
    rd.add_argument("--destino", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    rd.add_argument("--max-tickers", type=int, default=None, help="solo los N primeros tickers por proveedor (prueba)")
    rd.add_argument("--solo", choices=("series", "precios"), default=None)
    rd.set_defaults(func=_redundancia)
    for orden, ayuda in (
        ("eda", "EDA de series y precios: detecta incidencias y propone, no corrige (paso 3)"),
        ("seleccion", "lista curada (queda / alias / fuera / proyecciones) y lista de descargas del paso 3b (paso 3)"),
        ("preprocesado", "valida config/preprocesado.yaml y simula su efecto sin escribir ninguna base (paso 3)"),
        ("estado_3b", "estado de cada fila del 3b (3b-1 y 3b-2): hecho, parcial, resuelto, limitación declarada "
                      "o aplazado"),
    ):
        p3 = sub.add_parser(orden, help=ayuda, add_help=False)
        p3.add_argument("resto", nargs=argparse.REMAINDER, help=f"argumentos de python -m ingesta.mercados_series.{orden}")
        p3.set_defaults(func=_paso3)
    x = sub.add_parser("excepciones-alfred", help="fechas de publicación medidas en ALFRED (excepciones)")
    x.add_argument("--ids", nargs="*", help="ids del catálogo (por defecto fuentes.fred.ids_excepciones())")
    x.add_argument("--sin-red", action="store_true", help="solo lo descargado hoy (caché)")
    x.set_defaults(func=_excepciones)
    ia = sub.add_parser("informe-alfred", help="tablas de revisiones y de adelantos de la regla previa (ALFRED)")
    ia.set_defaults(func=_informe_alfred)
    for fuente, (modulo, defecto) in FUENTES_CLI.items():
        df = sub.add_parser(f"descargar-{fuente}", help=f"delega en {modulo} (por defecto: {' '.join(defecto) or '-'})")
        df.add_argument("argumentos", nargs="*", help="argumentos del módulo (las opciones van tal cual)")
        df.set_defaults(func=_descargar_fuente, fuente=fuente)
    dp = sub.add_parser("descargar-precios", help="precios as-traded de Yahoo (núcleo o ampliado; reanudable)")
    dp.add_argument("--nivel", choices=["nucleo", "ampliado"], default="nucleo")
    dp.add_argument("--fichero", type=Path, default=None,
                    help="CSV con columna 'ticker' (nivel ampliado; por defecto <corpus>/mercados_series/logs/"
                         "tickers_ampliado.csv; una ruta relativa también se busca en <corpus>/mercados_series)")
    dp.add_argument("--etiqueta", default=None)
    dp.set_defaults(func=_descargar_precios)
    ao = sub.add_parser("archivar-oas", help="captura de las OAS de ICE BofA de FRED y unión al acumulado (mensual)")
    ao.add_argument("--sin-red", action="store_true", help="no descarga: solo capturas antiguas y unión")
    ao.add_argument("--sin-crudo", action="store_true", help="no importa la caché cruda de FRED")
    ao.set_defaults(func=_archivar_oas)
    cp = sub.add_parser("curar-precios", help="precios curados del paso 4: tickers «queda», corte G2 y propuestas "
                                              "automáticas del EDA (no toca precios/)")
    cp.add_argument("--sin-escribir", action="store_true", help="construye y verifica sin escribir nada")
    cp.add_argument("--tickers", default=None, help="solo estos tickers, separados por comas (prueba; no escribe)")
    cp.add_argument("--corte", default=None, help="corte AAAA-MM-DD (por defecto config/corte.yaml)")
    cp.set_defaults(func=_curar_precios)
    cu = sub.add_parser("curar", help="base curada de series del paso 4 (alias, proyecciones y registro de cambios; "
                                      "no toca base_series.parquet)")
    cu.add_argument("--sin-escribir", action="store_true", help="construye y verifica sin escribir nada")
    cu.add_argument("--corte", default=None, help="corte AAAA-MM-DD (por defecto config/corte.yaml)")
    cu.set_defaults(func=_curar)
    ca = sub.add_parser("catalogo-agentes", help="catálogo para los agentes y la búsqueda (series, proyecciones y "
                                                 "precios curados; solo metadatos)")
    ca.add_argument("--sin-escribir", action="store_true", help="construye y valida sin escribir los CSV")
    ca.set_defaults(func=_catalogo_agentes)
    rf = sub.add_parser("refrescar", help="orden única de refresco hasta un corte (descargas, base y curado; P07)",
                        add_help=False)
    rf.add_argument("resto", nargs=argparse.REMAINDER, help="argumentos de ingesta.mercados_series.refrescar")
    rf.set_defaults(func=_refrescar)
    a, resto = p.parse_known_args(argv)
    if a.func in (_paso3, _refrescar):
        # Tal cual van tras la orden (parse_known_args separa las opciones de los posicionales y las desordena).
        crudos = list(sys.argv[1:] if argv is None else argv)
        a.resto = crudos[crudos.index(a.orden) + 1:]
    elif resto:
        if a.func is not _descargar_fuente:
            p.error(f"argumentos no reconocidos: {' '.join(resto)}")
        else:
            a.argumentos = [*a.argumentos, *resto]
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
