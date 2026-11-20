"""Estado del paso 3b-1 (descargas): qué se hizo, qué queda como limitación declarada y qué pasa al 3b-2.

Lee ``tablas/descargas_3b.csv`` (lo genera ``seleccion``) y escribe ``tablas/descargas_3b_estado.csv`` con una
columna ``estado_3b1`` por fila:

- ``hecho``: refrescado o archivado en el 3b-1 (2026-11-19/20): FRED vivo, ALFRED, curvas, BCE, bancos
  centrales básicos, académicas (edición nueva de Ken French), OFR, archivo de las OAS de ICE
  (``archivar-oas``), las derivadas propias (se recalculan en ``construir-base``) y los precios del núcleo
  (Coinbase incluido) y del S&P 500 que llegan a la fecha de corte (G2).
- ``resuelto``: deudas de fechas cubiertas por las decisiones F1–F2 (verificadas en la web) o por las reglas
  conservadoras del plan de preprocesado (H.15 antes de 2005).
- ``limitacion_declarada``: lo que no tiene fuente gratuita y legal (G1, F3), Bundesbank (reto anti-bots), los
  truncados sin historia en Yahoo (``MOTIVOS_TRUNCADOS``), los ficheros del S&P 500 y del núcleo que no llegan
  a la fecha de corte (``MOTIVOS_REFRESCO``), los tickers reutilizados del S&P 500 (fila agregada) y los
  cambios del S&P 500 que la fuente de constituyentes aún no recoge (``CAMBIOS_SP500_POSTERIORES``).
- ``aplazado_3b2``: fuera del alcance H1 (S&P 500 y lo básico): acciones no estadounidenses del nivel ampliado,
  UCITS del universo, macro internacional, series nuevas internacionales, ediciones del WEO y las series de
  la Fase 1 congeladas.

La fila ``refresco:precios:<proveedor>`` de ``descargas_3b.csv`` se parte (``partir_refresco_precios``) con la
última ``sesion`` de cada fichero del corpus (``<corpus>/mercados_series/precios/<proveedor>``), no a mano.
Escribe también ``tablas/sp500_cobertura_3b1.csv``: cobertura histórica del S&P 500 (tramos con fichero, sin
fichero, sin solape, reutilizados y % de días-tramo cubiertos; ``seleccion.resumen_cobertura_sp500``).

Solo metadatos. CLI: ``python -m ingesta.mercados_series estado_3b``.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from ingesta.comun.rutas import corpus_dir, resultados_dir

TEMA = "mercados_series"
FICHERO_ENTRADA = "descargas_3b.csv"
FICHERO_SALIDA = "descargas_3b_estado.csv"
FICHERO_COBERTURA_SP500 = "sp500_cobertura_3b1.csv"
FECHA_CORTE = "2026-11-13"               # G2 (igual que seleccion.FECHA_CORTE)

# Fuentes refrescadas en el 3b-1 (alcance H1).
REFRESCADAS_3B1 = frozenset({
    "fred_alfred", "ust_curva", "ken_french", "shiller", "goyal_welch", "ofr_fsi", "bce", "bce_curvas",
    "boe_curvas", "mof_jgb", "boc_curva", "boc", "boj", "rba", "calculo_propio",
})
# Fuera del alcance H1: se refrescan en el 3b-2.
APLAZADAS_3B2 = frozenset({"oecd", "eurostat", "bis", "worldbank", "imf_weo", "philly_rtdsm", "yfinance"})
LIMITACION_REFRESCO = {"bundesbank": "reto anti-bots en bundesbank.de (/.enodia/challenge): se conserva el "
                                    "crudo del 2026-10-13; no se esquiva"}
# Ficheros del S&P 500 o del núcleo que no llegan a la fecha de corte: por qué (se conserva lo guardado).
MOTIVOS_REFRESCO = {
    "GP": "ticker reutilizado por otra empresa: Yahoo cambia la historia guardada (open)",
    "LU": "ticker reutilizado (Lucent → Lufax): Yahoo cambia la historia guardada (open)",
    "PARA": "Yahoo revisa open/high/low de toda la historia tras la fusión con Skydance (2025); la historia "
            "sigue en SKYD (lote 3b1_altas)",
    "000001.SS": "núcleo: Yahoo revisa una sesión ya guardada (2026-10-13); se conserva lo guardado",
    "NESN.SW": "núcleo: Yahoo revisa una sesión ya guardada (2026-09-07); se conserva lo guardado",
    "KVUE": "adquirido por Kimberly-Clark: sale del S&P 500 el 2026-11-04 (S&P DJI, 2026-10-30; fja05680 aún no "
            "lo recoge); última sesión en Yahoo 2026-10-30",
    "DWD": "ticker reutilizado: el fichero (ECNQUOTE de 2013 a 2017) no es el miembro del S&P 500 (1996-1997); "
           "no hay nada que refrescar",
    "GR": "ticker reutilizado: el fichero (un fondo de 2001 a 2018) no es el miembro del S&P 500 (Goodrich, "
          "1996-2012); no hay nada que refrescar",
}
# Truncados (``redescarga``): Yahoo solo conserva unas pocas sesiones. Por qué, ticker a ticker.
MOTIVOS_TRUNCADOS = {
    "AVB": "deslistado o adquirido: sale del S&P 500 el 2026-08-18 (fja05680)",
    "EQR": "deslistado o adquirido: sale del S&P 500 el 2026-08-18 (fja05680)",
    "EA": "adquirido: sale del S&P 500 el 2026-08-05 (lo sustituye Ferguson; S&P DJI, 2026-07-31)",
    "LEG": "deslistado o adquirido en 2026 (salió del S&P 500 el 2021-12-20)",
    "QRVO": "deslistado o adquirido en 2026 (salió del S&P 500 el 2024-12-23)",
    "WBD": "adquirido por Paramount Skydance (cierre el 2026-10-06): sale del S&P 500 el 2026-10-06 (S&P DJI, "
           "2026-10-01; fja05680 aún no lo recoge)",
    "PSKY": "cambio de ticker: Paramount Skydance cotiza como SKYD en NYSE tras comprar WBD (2026-10); sigue en el "
            "índice y su historia completa está en SKYD (lote 3b1_altas)",
    "BLY": "ticker reutilizado: el fichero (ECNQUOTE de 2016) no es el miembro del S&P 500 de 1996",
}
MOTIVO_TRUNCADO = "Yahoo no tiene más historia (deslistado o ticker reutilizado)"
# Cambios del S&P 500 publicados por S&P DJI después del último cambio de fja05680 (2026-08-18), verificados en
# press.spglobal.com el 2026-11-20: (fecha efectiva, altas, bajas). SKYD es el nuevo ticker de PSKY.
CAMBIOS_SP500_POSTERIORES = (
    ("2026-09-21", ("BE", "P", "ILMN"), ("TAP", "TTD", "BLDR")),
    ("2026-10-01", ("VYLR",), ()),
    ("2026-10-06", ("TWLO",), ("CTVA", "WBD")),
    ("2026-10-06", ("SKYD",), ("PSKY",)),
    ("2026-11-04", ("OKTA",), ("KVUE",)),
)
ALTAS_CON_FICHERO_PREVIO = ("ILMN",)    # miembro anterior: su fichero ya estaba en el lote 3b1
ULTIMO_CAMBIO_FJA = "2026-08-18"
FECHAS_RESUELTAS = {
    "fred:h15_diario_pre2005": "tramo conservador +7 días antes de 2005-06-28 (preprocesado.yaml, h15_diario)",
    "ken_french:ediciones_antiguas": "F1: verificado en la Wayback Machine (anual antes de 2005-09, mensual después)",
    "academicas:reglas_sin_verificar": "F2: publicado_desde verificado en la web (OFR, Goyal-Welch, BIS)",
}
COLUMNAS_EXTRA = ("id", "tipo", "fuente", "prioridad", "detalle", "estado_3b1", "motivo_3b1")


def estado_fila(fila: pd.Series) -> tuple[str, str]:
    """``(estado_3b1, motivo)`` de una fila de ``descargas_3b.csv`` (función pura)."""
    ident, tipo, fuente = str(fila["id"]), str(fila["tipo"]), str(fila.get("fuente", ""))
    if str(fila.get("estado", "")) == "limitacion_declarada":
        return "limitacion_declarada", str(fila.get("motivo", "F3"))
    if tipo == "refresco":
        if ident.startswith("refresco:proyecciones"):
            return "hecho", "SEP refrescado con ALFRED"
        if ident.startswith("refresco:precios:"):
            return "hecho", "refrescado en el 3b-1 (el reparto por fichero lo hace partir_refresco_precios)"
        if fuente in LIMITACION_REFRESCO:
            return "limitacion_declarada", LIMITACION_REFRESCO[fuente]
        if fuente in REFRESCADAS_3B1:
            return "hecho", "refrescado en el 3b-1"
        if fuente in APLAZADAS_3B2:
            return "aplazado_3b2", "fuera del alcance H1 (S&P 500 y lo básico)"
        return "aplazado_3b2", "fuente sin refresco en el 3b-1"
    if tipo == "archivo_periodico":
        if ident.startswith("fred:BAML"):
            return "hecho", "archivar-oas: acumulado sin pérdidas (primera captura 2026-11-19)"
        return "hecho", "edición académica nueva archivada (Ken French 2026-10); Shiller y GW sin edición nueva"
    if tipo == "redescarga":
        return "limitacion_declarada", MOTIVOS_TRUNCADOS.get(ident, MOTIVO_TRUNCADO)
    if tipo == "fechas":
        if ident in FECHAS_RESUELTAS:
            return "resuelto", FECHAS_RESUELTAS[ident]
        return "limitacion_declarada", "G1: prioridad baja sin fuente gratuita y legal"
    if tipo in ("vintages", "constituyentes"):
        return "limitacion_declarada", "G1: prioridad baja sin fuente gratuita y legal"
    if tipo in ("precios", "series", "ediciones"):
        return "aplazado_3b2", "fuera del alcance H1 (S&P 500 y lo básico)"
    return "aplazado_3b2", "sin regla: revisar"


def grupo_fichero(ticker: str, proveedor: str, en_universo: bool, sp500: set[str], nucleo: set[str],
                  ampliado: set[str], otros_3b1: set[str] = frozenset()) -> str:
    """``sp500``, ``nucleo``, ``otros_3b1``, ``ampliado_no_eeuu``, ``universo`` u ``otro`` (función pura).

    Coinbase (BTC y ETH) es núcleo. Un ticker del S&P 500 que también es del núcleo cuenta en el S&P 500.
    ``otros_3b1``: descargados en otros lotes del 3b-1 (``yahoo_3b1_yf``: las series ``yf:`` de índices). El
    nivel ampliado es el S&P 500 histórico más 10 índices no estadounidenses: lo que queda de él, fuera del
    S&P 500 y del núcleo, son las acciones no estadounidenses (3b-2). ``universo``: instrumentos del universo
    fuera de lo anterior (UCITS de Londres y Xetra, 3b-2)."""
    if proveedor == "coinbase":
        return "nucleo"
    if ticker in sp500:
        return "sp500"
    if ticker in nucleo:
        return "nucleo"
    if ticker in otros_3b1:
        return "otros_3b1"
    if ticker in ampliado:
        return "ampliado_no_eeuu"
    return "universo" if en_universo else "otro"


def partir_refresco_precios(precios: pd.DataFrame, ultimas: Mapping[str, pd.Timestamp], sp500: Iterable[str],
                            nucleo: Iterable[str], ampliado: Iterable[str], corte: str = FECHA_CORTE,
                            motivos: Mapping[str, str] | None = None, otros_3b1: Iterable[str] = ()) -> pd.DataFrame:
    """Filas de estado (``COLUMNAS_EXTRA``) que sustituyen a ``refresco:precios:<proveedor>`` (función pura).

    ``precios``: ``seleccion_precios.csv`` (solo cuentan los ``queda``). ``ultimas``: última ``sesion`` de cada
    fichero del corpus. Por proveedor: ``hecho`` con los del S&P 500 y del núcleo que llegan a ``corte`` (y,
    aparte, los de ``otros_3b1``); ``aplazado_3b2`` las acciones no estadounidenses del ampliado y los UCITS
    del universo; y una
    ``limitacion_declarada`` por fichero del S&P 500 o del núcleo que no llega (``motivos`` o «sin datos
    recientes»). La suma de ficheros de las filas es la de ``queda``."""
    sp500, nucleo, ampliado, otros_3b1 = set(sp500), set(nucleo), set(ampliado), set(otros_3b1)
    motivos = dict(MOTIVOS_REFRESCO if motivos is None else motivos)
    q = precios[precios["decision"] == "queda"].copy()
    q["ultima"] = pd.to_datetime(q["id"].map(dict(ultimas)))
    q["grupo"] = [grupo_fichero(str(t), str(p), bool(u), sp500, nucleo, ampliado, otros_3b1)
                  for t, p, u in zip(q["id"], q["proveedor"], q["en_universo"])]
    q["llega"] = q["ultima"] >= pd.Timestamp(corte)
    filas = []

    def _fila(id_: str, prov: str, detalle: str, estado: str, motivo: str, tipo: str = "refresco") -> None:
        filas.append({"id": id_, "tipo": tipo, "fuente": prov, "prioridad": "alta" if estado == "hecho" else
                      "no se descarga", "detalle": detalle, "estado_3b1": estado, "motivo_3b1": motivo})

    for prov, g in q.groupby("proveedor", sort=True):
        basico = g[g["grupo"].isin(["sp500", "nucleo"])]
        hecho = basico[basico["llega"]]
        n_sp, n_nu = int((hecho["grupo"] == "sp500").sum()), int((hecho["grupo"] == "nucleo").sum())
        if len(hecho):
            _fila(f"refresco:precios:{prov}", str(prov), f"{len(hecho)} ficheros (S&P 500 {n_sp}, núcleo {n_nu})",
                  "hecho", f"refrescados en el 3b-1: llegan a la fecha de corte {corte} (última sesión máxima "
                  f"{hecho['ultima'].max():%Y-%m-%d})")
        for grupo, estado, motivo in (
                ("otros_3b1", "hecho", "descargados en otro lote del 3b-1 (yahoo_3b1_yf: series yf: de índices)"),
                ("ampliado_no_eeuu", "aplazado_3b2", "H1: acciones no estadounidenses del nivel ampliado (3b-2)"),
                ("universo", "aplazado_3b2", "H1: instrumentos del universo fuera del S&P 500 y del núcleo, UCITS "
                 "de Londres y Xetra (3b-2)"),
                ("otro", "aplazado_3b2", "fichero sin lote del 3b-1: revisar")):
            n = int((g["grupo"] == grupo).sum())
            if n:
                ult = g.loc[g["grupo"] == grupo, "ultima"].max()
                _fila(f"refresco:precios:{prov}:{grupo}", str(prov), f"{n} ficheros", estado,
                      f"{motivo}; última sesión máxima {ult:%Y-%m-%d}" if pd.notna(ult) else motivo)
        for _, r in basico[~basico["llega"]].sort_values("id").iterrows():
            ult = f"{r['ultima']:%Y-%m-%d}" if pd.notna(r["ultima"]) else "sin fichero"
            _fila(str(r["id"]), str(prov), f"{r['grupo']}; última sesión {ult}", "limitacion_declarada",
                  motivos.get(str(r["id"]), f"sin datos recientes en Yahoo (última sesión {ult})"),
                  tipo="excepcion_refresco")
    return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))


def filas_sp500(resumen_cobertura: pd.DataFrame | None) -> pd.DataFrame:
    """Limitaciones agregadas del S&P 500: tickers reutilizados (con su número de tramos) y cambios de la
    composición posteriores al último de fja05680 (``CAMBIOS_SP500_POSTERIORES``)."""
    filas = []
    if resumen_cobertura is not None and len(resumen_cobertura):
        v = resumen_cobertura.set_index("metrica")["valor"]
        filas.append({
            "id": "sp500:tickers_reutilizados", "tipo": "limitacion_agregada", "fuente": "yahoo",
            "prioridad": "no se descarga",
            "detalle": f"{int(v['tramos_ticker_reutilizado'])} tramos ({int(v['tickers_reutilizados'])} tickers)",
            "estado_3b1": "limitacion_declarada",
            "motivo_3b1": (f"{int(v['tramos_ticker_reutilizado'])} tramos del S&P 500 tienen un fichero que no es el "
                           "miembro (no solapa con ninguno de sus tramos o no es una acción): se quedan con aviso "
                           "'ticker reutilizado' en la lista curada; sin CIK/PERMNO no se trae el miembro (F3)")})
    altas = sorted({t for _, a, _ in CAMBIOS_SP500_POSTERIORES for t in a} - set(ALTAS_CON_FICHERO_PREVIO))
    cambios = "; ".join(f"{f}: +{', '.join(a) or '-'} / -{', '.join(b) or '-'}"
                        for f, a, b in CAMBIOS_SP500_POSTERIORES)
    filas.append({
        "id": "constituyentes:sp500_posterior_fja", "tipo": "constituyentes", "fuente": "sp500_constituyentes",
        "prioridad": "no se descarga", "detalle": cambios, "estado_3b1": "limitacion_declarada",
        "motivo_3b1": (f"fja05680/sp500 refrescado el 2026-11-20 sin cambios: su último cambio es del "
                       f"{ULTIMO_CAMBIO_FJA}. Los cambios posteriores de S&P DJI no están en los tramos; los precios "
                       f"de las altas sí están descargados (lote 3b1_altas: {', '.join(altas)}; "
                       f"{', '.join(ALTAS_CON_FICHERO_PREVIO)} ya tenía fichero y se refrescó en el lote 3b1)")})
    return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))


def construir(entrada: pd.DataFrame, precios_refresco: pd.DataFrame | None = None,
              sp500: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabla de estado: las filas de ``descargas_3b.csv`` con la de ``refresco:precios:*`` partida
    (``precios_refresco``, de ``partir_refresco_precios``) y las limitaciones agregadas del S&P 500 (``sp500``)."""
    out = entrada.copy()
    if precios_refresco is not None:
        provs = set(precios_refresco["fuente"])
        partida = out["id"].isin([f"refresco:precios:{p}" for p in provs])
        out = out[~partida]
    res = out.apply(estado_fila, axis=1, result_type="expand")
    out["estado_3b1"], out["motivo_3b1"] = res[0], res[1]
    extra = [x for x in (precios_refresco, sp500) if x is not None and len(x)]
    return pd.concat([out, *extra], ignore_index=True)


def ultimas_sesiones(raiz: Path | None = None) -> dict[str, pd.Timestamp]:
    """Última ``sesion`` de cada fichero de ``<corpus>/mercados_series/precios/<proveedor>/`` (id del fichero)."""
    import pyarrow.parquet as pq

    from ingesta.mercados_series import almacen

    carpeta = raiz or corpus_dir(TEMA) / "precios"
    out: dict[str, pd.Timestamp] = {}
    for f in sorted(carpeta.glob("*/*.parquet")):
        ses = pq.read_table(f, columns=["sesion"]).column("sesion").to_pandas()
        out[almacen.ticker_de_fichero(f.stem)] = pd.Timestamp(ses.max()) if len(ses) else pd.NaT
    return out


#: Otros lotes de Yahoo del 3b-1 (registro ``logs/yahoo_<etiqueta>.jsonl``) que no son S&P 500 ni núcleo.
LOTES_OTROS_3B1 = ("3b1_yf",)


def conjuntos_lotes() -> tuple[set[str], set[str], set[str], set[str]]:
    """``(sp500, nucleo, ampliado, otros_3b1)``: tickers de Yahoo del S&P 500 histórico (tramos de
    ``sp500.parquet`` y altas de ``CAMBIOS_SP500_POSTERIORES``), del núcleo (``yahoo.NUCLEO``), de la lista del
    nivel ampliado y los ``ok`` de ``LOTES_OTROS_3B1``."""
    from ingesta.mercados_series import seleccion
    from ingesta.mercados_series.proveedores import yahoo

    tramos = pd.read_parquet(seleccion.ruta_tramos_sp500(), columns=["ticker"])
    sp500 = {yahoo.ticker_yahoo_constituyente("sp500", t) for t in tramos["ticker"]}
    sp500 |= {t for _, a, _ in CAMBIOS_SP500_POSTERIORES for t in a}
    lista = yahoo.resolver_fichero(None)
    ampliado = set(pd.read_csv(lista)["ticker"].astype(str)) if lista.exists() else set()
    otros: set[str] = set()
    for lote in LOTES_OTROS_3B1:
        reg = yahoo.leer_registro(lote)
        if len(reg):
            reg = reg.drop_duplicates("ticker", keep="last")
            otros |= set(reg.loc[reg["estado"] == "ok", "ticker"].astype(str))
    return sp500, set(yahoo.NUCLEO), ampliado, otros


def cobertura_sp500(tablas: Path) -> pd.DataFrame | None:
    """Resumen de la cobertura histórica del S&P 500 (``seleccion.resumen_cobertura_sp500``) o ``None``."""
    from ingesta.mercados_series import seleccion

    if not seleccion.ruta_tramos_sp500().exists():
        return None
    pre = pd.read_csv(tablas / "inventario_precios.csv", dtype={"ticker": str})
    cob = seleccion.cobertura_tramos_sp500(pd.read_parquet(seleccion.ruta_tramos_sp500()), pre,
                                           seleccion.clases_precios(pre))
    return seleccion.resumen_cobertura_sp500(cob)


def main(argv: list[str] | None = None) -> dict[str, Path]:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tablas", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    a = p.parse_args(argv)
    tablas = a.tablas or resultados_dir(TEMA) / "tablas"
    precios = pd.read_csv(tablas / "seleccion_precios.csv", dtype={"id": str})
    sp500, nucleo, ampliado, otros = conjuntos_lotes()
    partidas = partir_refresco_precios(precios, ultimas_sesiones(), sp500, nucleo, ampliado, otros_3b1=otros)
    resumen = cobertura_sp500(tablas)
    tabla = construir(pd.read_csv(tablas / FICHERO_ENTRADA), partidas, filas_sp500(resumen))
    destino = tablas / FICHERO_SALIDA
    tabla.to_csv(destino, index=False, encoding="utf-8", lineterminator="\n")
    rutas = {"descargas_3b_estado": destino}
    print(tabla.groupby(["estado_3b1", "tipo"]).size().to_string())
    if resumen is not None:
        rutas["sp500_cobertura_3b1"] = tablas / FICHERO_COBERTURA_SP500
        resumen.to_csv(rutas["sp500_cobertura_3b1"], index=False, encoding="utf-8", lineterminator="\n")
        print(resumen.to_string(index=False))
    return rutas


if __name__ == "__main__":
    main()
