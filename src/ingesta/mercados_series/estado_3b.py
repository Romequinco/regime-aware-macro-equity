"""Estado del paso 3b (descargas 3b-1 y 3b-2): qué se hizo, qué queda como limitación declarada y qué sigue aplazado.

Lee ``tablas/descargas_3b.csv`` (lo genera ``seleccion``: lo que falta según el inventario de cada momento) y escribe
``tablas/descargas_3b_estado.csv`` con las columnas ``estado_3b`` y ``motivo_3b`` por fila (las dos tandas; hasta el
3b-2 se llamaban ``estado_3b1`` y ``motivo_3b1``):

- ``hecho``: refrescado, descargado o archivado, **con evidencia en el corpus** (``evidencia_refresco``): un refresco
  exige que el último crudo de la fuente (``MedidasBase.crudos``) sea del día de su tanda o posterior
  (``FECHA_TANDA``: 2026-11-19 el 3b-1, 2026-11-20 el 3b-2) o que la base tenga datos de la fuente posteriores a la
  fecha de corte (``MedidasBase.hasta_fuente``); el archivo de las OAS, una captura de ``archivar-oas`` de la tanda
  (``archivo/ice_oas/registro.csv``); la edición académica y el SEP, el crudo de Ken French y de ALFRED de la tanda.
  Sin evidencia, ``aplazado`` con el motivo.
  - 3b-1 (2026-11-19/20): FRED vivo, ALFRED, curvas, BCE, bancos centrales básicos, académicas (edición nueva de
    Ken French), OFR, archivo de las OAS de ICE (``archivar-oas``), las derivadas propias (se recalculan en
    ``construir-base``) y los precios del núcleo (Coinbase incluido) y del S&P 500 que llegan a la fecha de
    corte (G2).
  - 3b-2 (2026-11-20): refresco de OCDE, Eurostat, BIS, Banco Mundial, WEO y Philadelphia; series ``yf:`` que
    llegan al corte (``partir_refresco_yf``); ediciones del WEO que están en la base; series nuevas con filas
    en la base (agregados del Banco Mundial y del WEO, historia del RBA anterior a 2011); instrumentos del
    universo descargados (lote ``3b2_universo``) y refresco de las acciones no estadounidenses del ampliado
    (lote ``3b2_ampliado``) que llegan al corte.
- ``parcial``: se trajo una parte y el resto es limitación (historia del BoC antes de 2001: solo el objetivo a
  fin de mes desde 1996, ``boc:STATIC_ATABLE_V39079``).
- ``resuelto``: deudas de fechas cubiertas por las decisiones F1–F2 (verificadas en la web) o por las reglas
  conservadoras del plan de preprocesado (H.15 antes de 2005).
- ``limitacion_declarada``: lo que no tiene fuente gratuita y legal (G1, F3), Bundesbank (reto anti-bots), los
  truncados sin historia en Yahoo (``MOTIVOS_TRUNCADOS``), los ficheros que no llegan a la fecha de corte
  (``MOTIVOS_REFRESCO``: entre ellos, los rechazos del almacén porque Yahoo revisa una sesión ya guardada), las
  series ``yf:`` que no se extienden (``MOTIVOS_YF``), las ediciones del WEO de 2008-04 a 2024-10 (G3: el
  ``robots.txt`` de www.imf.org responde 403), las series nuevas que la fuente no publica (zona euro cambiante
  de Eurostat, CLI EA20 y paro de China de la OCDE) o que no aportan nada (Philadelphia: ALFRED ya las cubre),
  los UCITS con la historia recortada por Yahoo (fila agregada), los tickers reutilizados del S&P 500 (fila
  agregada) y los cambios del S&P 500 que la fuente de constituyentes aún no recoge
  (``CAMBIOS_SP500_POSTERIORES``).
- ``aplazado``: no es una descarga y se decide en un paso posterior (``APLAZADOS``, con su motivo), un refresco
  sin evidencia en el corpus, o una fila sin regla (``sin regla: revisar``).

Todo lo medido sale del corpus y de las tablas, no a mano: la última ``sesion`` de cada fichero de precios
(``ultimas_sesiones``), los registros de los lotes de Yahoo (``logs/yahoo_<etiqueta>.jsonl``), el universo
(``inicio_esperado``), la base de series (``medir_base``: primera y última ``fecha_referencia`` por serie y por
fuente y ediciones del WEO), la fecha del último crudo de cada fuente (``fechas_crudo``) y las capturas de las OAS
(``capturas_oas``). La fila ``refresco:precios:<proveedor>`` se parte por fichero (``partir_refresco_precios``) y
la de ``refresco:yfinance`` por serie (``partir_refresco_yf``). Escribe también ``tablas/sp500_cobertura_3b1.csv``:
cobertura histórica del S&P 500 (``seleccion.resumen_cobertura_sp500``).

Solo metadatos. CLI: ``python -m ingesta.mercados_series estado_3b``.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

from ingesta.comun.rutas import corpus_dir, resultados_dir

TEMA = "mercados_series"
FICHERO_ENTRADA = "descargas_3b.csv"
FICHERO_SALIDA = "descargas_3b_estado.csv"
FICHERO_COBERTURA_SP500 = "sp500_cobertura_3b1.csv"
FECHA_CORTE = __import__("ingesta.mercados_series.corte", fromlist=["x"]).corte_vigente().date().isoformat()  # G2 (P07)
ESTADOS = ("hecho", "parcial", "resuelto", "limitacion_declarada", "aplazado")

# Fuentes refrescadas en el 3b-1 (alcance H1) y en el 3b-2 (el resto). ``yfinance`` va serie a serie
# (``partir_refresco_yf``).
REFRESCADAS_3B1 = frozenset({
    "fred_alfred", "ust_curva", "ken_french", "shiller", "goyal_welch", "ofr_fsi", "bce", "bce_curvas",
    "boe_curvas", "mof_jgb", "boc_curva", "boc", "boj", "rba", "calculo_propio",
})
REFRESCADAS_3B2 = frozenset({"oecd", "eurostat", "bis", "worldbank", "imf_weo", "philly_rtdsm"})
FECHA_TANDA = {"3b-1": "2026-11-19", "3b-2": "2026-11-20"}    # primer día de cada tanda de descargas
#: Carpetas de ``<corpus>/mercados_series/crudo/`` de cada fuente (por defecto, la de su nombre). Las derivadas
#: propias no tienen crudo: su evidencia es la base (datos posteriores al corte).
CRUDOS_FUENTE = {"fred_alfred": ("fred", "alfred"), "calculo_propio": ()}
LIMITACION_REFRESCO = {"bundesbank": "reto anti-bots en bundesbank.de (/.enodia/challenge): se conserva el "
                                    "crudo del 2026-10-13; no se esquiva"}
_REVISA = "Yahoo revisa una sesión ya guardada ({}); se conserva lo guardado"
# Ficheros que no llegan a la fecha de corte: por qué (se conserva lo guardado).
MOTIVOS_REFRESCO = {
    "GP": "ticker reutilizado por otra empresa: Yahoo cambia la historia guardada (open)",
    "LU": "ticker reutilizado (Lucent → Lufax): Yahoo cambia la historia guardada (open)",
    "PARA": "Yahoo revisa open/high/low de toda la historia tras la fusión con Skydance (2025); la historia "
            "sigue en SKYD (lote 3b1_altas)",
    "000001.SS": "núcleo: " + _REVISA.format("2026-10-13"),
    "NESN.SW": "núcleo: " + _REVISA.format("2026-09-07"),
    "KVUE": "adquirido por Kimberly-Clark: sale del S&P 500 el 2026-11-04 (S&P DJI, 2026-10-30; fja05680 aún no "
            "lo recoge); última sesión en Yahoo 2026-10-30",
    "DWD": "ticker reutilizado: el fichero (ECNQUOTE de 2013 a 2017) no es el miembro del S&P 500 (1996-1997); "
           "no hay nada que refrescar",
    "GR": "ticker reutilizado: el fichero (un fondo de 2001 a 2018) no es el miembro del S&P 500 (Goodrich, "
          "1996-2012); no hay nada que refrescar",
    # 3b-2 (lote 3b2_ampliado): el almacén rechaza el refresco (ErrorContrato, logs/3b2_precios_stderr.log).
    **{t: _REVISA.format("2026-09-07") for t in (
        "ALC.SW", "CFR.SW", "GIVN.SW", "LOGN.SW", "LONN.SW", "PGHN.SW", "SIKA.SW", "SLHN.SW", "UBSG.SW", "ZURN.SW")},
    "EXO.AS": _REVISA.format("2026-10-13"),
    "JD.L": _REVISA.format("2026-10-13"),
    # Lote 3b1 (yahoo_3b1.jsonl): period='max' devolvió solo el 2026-11-17 y el 18 y se añadieron tras lo guardado.
    "SNDK": ("refresco incompleto del 3b-1: Yahoo solo devolvió el 2026-11-17 y el 2026-11-18 (period='max'); faltan "
             "las sesiones del 2026-10-14 al 2026-11-16 (hueco antes del corte)"),
}
# Series ``yf:`` que no llegan a la fecha de corte (``fuentes.fase1.extender_precios`` no las extiende).
MOTIVOS_YF = {
    "yf:^BCOM": "Yahoo ya no sirve ^BCOM (sin datos, «possibly delisted», lote 3b1_yf del 2026-11-20): se conserva "
                "la descarga de la Fase 1",
    "yf:^W5000": "el solape del almacén con la Fase 1 no coincide (Yahoo da otras sesiones y mercado XLON): "
                 "extender_precios no la extiende; se conserva la Fase 1",
    "yf:GC=F": "el solape no coincide (el futuro continuo de Yahoo cambia con cada vencimiento): extender_precios "
               "no la extiende; se conserva la Fase 1 (el fichero de precios GC=F sí está al día)",
}
MOTIVO_YF = "sin datos recientes en el almacén de precios"
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
# Filas que no son una descarga: se deciden en un paso posterior.
APLAZADOS = {
    "baseline:6040_europeo": ("no es un ticker: es una cartera derivada (60 % CSPX.L, 40 % EUNA.DE desde 2017-11). "
                              "Los precios ya están, también el proxy previo de EUNA.DE (BNDX, lote 3b2_universo); "
                              "el empalme se decide al construir las carteras (cartera.baselines)"),
}

# --- Series nuevas del 3b-2 (tipo ``series``) ---------------------------------------------------------------
#: Se dan por hechas si la base tiene series con el prefijo ``<id>.`` (sin las de proyección).
SERIES_POR_PREFIJO = ("wb:WLD", "wb:LMY", "wb:EMU", "imf:WEO.001", "imf:WEO.163", "imf:WEO.200")
#: Historia larga: ``id -> (series de la base, fecha antes de la cual tiene que empezar)``.
HISTORIA_LARGA = {"rba:historia_pre2011": (("rba:FIRMMCRTD", "rba:FCMYGBAG10D"), "2011-01-01")}
#: Historia larga que solo se trae en parte: ``id -> (serie nueva, fecha objetivo)``; el resto es limitación.
HISTORIA_PARCIAL = {"boc:historia_pre2001": ("boc:STATIC_ATABLE_V39079", "2001-01-01")}


def _motivos_series_3b2() -> dict[str, str]:
    """Limitaciones de las series nuevas, con el motivo de cada extractor (medido el 2026-11-20)."""
    from ingesta.mercados_series.fuentes import eurostat, oecd, philly_rtdsm

    out = {f"eurostat:{fam}.EA": m for fam, m in eurostat.SIN_EA.items()}
    out |= {f"oecd:{medida}.{area}": m for (area, medida), m in oecd.SIN_DATOS.items()}
    out |= {f"philly:{v}": philly_rtdsm.NOTA_SIN_PREVIOS for v in ("EMPLOY", "PCPI", "RUC")}
    return out


def _limitaciones_boc() -> str:
    from ingesta.mercados_series.fuentes import bancos_centrales

    return "; ".join(f"{k}: {v}" for k, v in bancos_centrales.LIMITACIONES.items() if k.startswith("boc:"))


def _motivo_weo() -> str:
    from ingesta.mercados_series.fuentes import imf

    return imf.MOTIVO_LIMITACION


COLUMNAS_EXTRA = ("id", "tipo", "fuente", "prioridad", "detalle", "estado_3b", "motivo_3b")


@dataclass(frozen=True)
class MedidasBase:
    """Lo medido en el corpus (``medir_base``, ``fechas_crudo``, ``capturas_oas``): primera y última
    ``fecha_referencia`` de cada serie y de cada fuente, ediciones del WEO (``vintage`` de ``imf_weo``), día del último
    crudo de cada carpeta de ``crudo/`` y días de las capturas de ``archivar-oas``."""
    desde: Mapping[str, pd.Timestamp] = field(default_factory=dict)
    hasta: Mapping[str, pd.Timestamp] = field(default_factory=dict)
    ediciones_weo: frozenset[str] = frozenset()
    hasta_fuente: Mapping[str, pd.Timestamp] = field(default_factory=dict)
    crudos: Mapping[str, pd.Timestamp] = field(default_factory=dict)
    capturas_oas: frozenset[str] = frozenset()

    def con_prefijo(self, prefijo: str) -> list[str]:
        """Series ``<prefijo>.…`` de la base, sin las de proyección (``.PROY.H``)."""
        return sorted(s for s in self.desde if s.startswith(prefijo + ".") and ".PROY.H" not in s)


def _f(t: pd.Timestamp | None) -> str:
    return f"{pd.Timestamp(t):%Y-%m-%d}" if t is not None and pd.notna(t) else "sin filas"


def evidencia_refresco(fuente: str, tanda: str, medidas: MedidasBase, corte: str = FECHA_CORTE) -> tuple[bool, str]:
    """``(hay, texto)``: hay evidencia de que ``fuente`` se refrescó en ``tanda`` (``FECHA_TANDA``) si el último
    crudo de alguna de sus carpetas (``CRUDOS_FUENTE``) es de ese día o posterior, o si la base tiene datos de la
    fuente posteriores a ``corte`` (solo los trae un refresco del 3b). Función pura."""
    dia = pd.Timestamp(FECHA_TANDA[tanda])
    carpetas = CRUDOS_FUENTE.get(fuente, (fuente,))
    crudo = max((medidas.crudos[c] for c in carpetas if c in medidas.crudos), default=None)
    hasta = medidas.hasta_fuente.get(fuente)
    if crudo is not None and crudo >= dia:
        return True, f"último crudo del {_f(crudo)}"
    if hasta is not None and pd.notna(hasta) and hasta > pd.Timestamp(corte):
        return True, f"datos en la base hasta el {_f(hasta)}, posteriores al corte {corte}"
    return False, (f"sin evidencia de refresco en el {tanda}: último crudo {_f(crudo)}, datos en la base hasta "
                   f"{_f(hasta)}")


def _hecho_si(fuente: str, tanda: str, medidas: MedidasBase, motivo: str) -> tuple[str, str]:
    hay, texto = evidencia_refresco(fuente, tanda, medidas)
    return ("hecho", f"{motivo} ({texto})") if hay else ("aplazado", texto)


def estado_serie_3b2(ident: str, medidas: MedidasBase, esperados: Iterable[str] = ()) -> tuple[str, str]:
    """``(estado, motivo)`` de una serie nueva del 3b-2 con lo que hay en la base (función pura). ``esperados``:
    indicadores pedidos (``detalle`` de la fila); los que no están en la base se nombran en el motivo."""
    if ident in SERIES_POR_PREFIJO:
        ids = medidas.con_prefijo(ident)
        if ids:
            desde = min(medidas.desde[s] for s in ids)
            faltan = sorted(set(esperados) - {s[len(ident) + 1:] for s in ids})
            quien = "el FMI" if ident.startswith("imf:") else "el Banco Mundial"
            return "hecho", (f"descargado en el 3b-2: {len(ids)} series en la base (desde {_f(desde)})"
                             + (f"; {quien} no publica {', '.join(faltan)} para este agregado" if faltan else ""))
        return "aplazado", "sin filas en la base: revisar"
    if ident in HISTORIA_LARGA:
        series, antes = HISTORIA_LARGA[ident]
        desdes = {s: medidas.desde.get(s) for s in series}
        if all(d is not None and d < pd.Timestamp(antes) for d in desdes.values()):
            return "hecho", ("descargado en el 3b-2 (ficheros históricos oficiales): "
                             + ", ".join(f"{s} desde {_f(d)}" for s, d in desdes.items()))
        return "aplazado", "la base no tiene la historia anterior a " + antes + ": revisar"
    if ident in HISTORIA_PARCIAL:
        serie, antes = HISTORIA_PARCIAL[ident]
        d = medidas.desde.get(serie)
        if d is not None and d < pd.Timestamp(antes):
            return "parcial", f"{serie} desde {_f(d)} (objetivo a fin de mes, mensual); el resto es limitación: {_limitaciones_boc()}"
        return "limitacion_declarada", _limitaciones_boc()
    motivos = _motivos_series_3b2()
    if ident in motivos:
        return "limitacion_declarada", motivos[ident]
    return "aplazado", "sin regla: revisar"


def estado_fila(fila: pd.Series, medidas: MedidasBase | None = None) -> tuple[str, str]:
    """``(estado_3b, motivo)`` de una fila de ``descargas_3b.csv`` (función pura; ``medidas``: ``medir_base``)."""
    medidas = medidas or MedidasBase()
    ident, tipo, fuente = str(fila["id"]), str(fila["tipo"]), str(fila.get("fuente", ""))
    if str(fila.get("estado", "")) == "limitacion_declarada":
        return "limitacion_declarada", str(fila.get("motivo", "F3"))
    if ident in APLAZADOS:
        return "aplazado", APLAZADOS[ident]
    if tipo == "refresco":
        if ident.startswith("refresco:proyecciones"):
            return _hecho_si("fred_alfred", "3b-1", medidas, "SEP refrescado con ALFRED")
        if ident.startswith("refresco:precios:"):
            return "hecho", "refrescado (el reparto por fichero lo hace partir_refresco_precios)"
        if fuente in LIMITACION_REFRESCO:
            return "limitacion_declarada", LIMITACION_REFRESCO[fuente]
        if fuente in REFRESCADAS_3B1:
            return _hecho_si(fuente, "3b-1", medidas, "refrescado en el 3b-1")
        if fuente in REFRESCADAS_3B2:
            return _hecho_si(fuente, "3b-2", medidas, "refrescado en el 3b-2")
        if fuente == "yfinance":
            return "hecho", "series yf: desde el almacén de precios (el reparto por serie lo hace partir_refresco_yf)"
        return "aplazado", "fuente sin refresco: revisar"
    if tipo == "archivo_periodico":
        if ident.startswith("fred:BAML"):
            dia = FECHA_TANDA["3b-1"]
            nuevas = sorted(c for c in medidas.capturas_oas if c >= dia)
            if nuevas:
                return "hecho", (f"archivar-oas: acumulado sin pérdidas (capturas del 3b: {', '.join(nuevas)}; "
                                 "archivo/ice_oas/registro.csv)")
            return "aplazado", (f"sin captura de archivar-oas desde el {dia} (archivo/ice_oas/registro.csv: "
                                f"{', '.join(sorted(medidas.capturas_oas)) or 'sin registro'})")
        return _hecho_si("ken_french", "3b-1", medidas, "edición académica nueva archivada (Ken French 2026-10); "
                         "Shiller y GW sin edición nueva")
    if tipo == "redescarga":
        return "limitacion_declarada", MOTIVOS_TRUNCADOS.get(ident, MOTIVO_TRUNCADO)
    if tipo == "fechas":
        if ident in FECHAS_RESUELTAS:
            return "resuelto", FECHAS_RESUELTAS[ident]
        return "limitacion_declarada", "G1: prioridad baja sin fuente gratuita y legal"
    if tipo in ("vintages", "constituyentes"):
        return "limitacion_declarada", "G1: prioridad baja sin fuente gratuita y legal"
    if tipo == "ediciones":
        edicion = ident.rsplit(":", 1)[-1]
        if edicion in medidas.ediciones_weo:
            return "hecho", "descargado en el 3b-2 (API SDMX del FMI): la edición está en la base"
        return "limitacion_declarada", _motivo_weo()
    if tipo == "series":
        esperados = [x.strip() for x in str(fila.get("detalle") or "").split(";") if x.strip()]
        return estado_serie_3b2(ident, medidas, esperados)
    if tipo == "precios":
        # Instrumento del universo que sigue sin fichero tras el lote 3b2_universo.
        return "limitacion_declarada", "F3: Yahoo no lo sirve (sin fichero tras el lote 3b2_universo)"
    return "aplazado", "sin regla: revisar"


def grupo_fichero(ticker: str, proveedor: str, en_universo: bool, sp500: set[str], nucleo: set[str],
                  ampliado: set[str], otros_3b1: set[str] = frozenset()) -> str:
    """``sp500``, ``nucleo``, ``otros_3b1``, ``ampliado_no_eeuu``, ``universo`` u ``otro`` (función pura).

    Coinbase (BTC y ETH) es núcleo. Un ticker del S&P 500 que también es del núcleo cuenta en el S&P 500.
    ``otros_3b1``: descargados en otros lotes del 3b-1 (``yahoo_3b1_yf``: las series ``yf:`` de índices). El
    nivel ampliado es el S&P 500 histórico más 10 índices no estadounidenses: lo que queda de él, fuera del
    S&P 500 y del núcleo, son las acciones no estadounidenses (lote ``3b2_ampliado``). ``universo``: instrumentos
    del universo fuera de lo anterior (UCITS de Londres y Xetra, lote ``3b2_universo``)."""
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


# Grupos que no son el S&P 500 ni el núcleo: (grupo, tanda, motivo del ``hecho``).
GRUPOS_LOTE = (
    ("otros_3b1", "3b-1", "descargados en otro lote del 3b-1 (yahoo_3b1_yf: series yf: de índices)"),
    ("ampliado_no_eeuu", "3b-2", "acciones no estadounidenses del nivel ampliado refrescadas (lote 3b2_ampliado)"),
    ("universo", "3b-2", "instrumentos del universo fuera del S&P 500 y del núcleo, UCITS de Londres y Xetra "
     "(lote 3b2_universo)"),
)


def partir_refresco_precios(precios: pd.DataFrame, ultimas: Mapping[str, pd.Timestamp], sp500: Iterable[str],
                            nucleo: Iterable[str], ampliado: Iterable[str], corte: str = FECHA_CORTE,
                            motivos: Mapping[str, str] | None = None, otros_3b1: Iterable[str] = (),
                            lotes: Mapping[str, Iterable[str]] | None = None,
                            no_llegan: Iterable[str] = ()) -> pd.DataFrame:
    """Filas de estado (``COLUMNAS_EXTRA``) que sustituyen a ``refresco:precios:<proveedor>`` (función pura).

    ``precios``: ``seleccion_precios.csv`` (solo cuentan los ``queda``). ``ultimas``: última ``sesion`` de cada
    fichero del corpus. Por proveedor y grupo (``grupo_fichero``): ``hecho`` con los que llegan a ``corte``
    (``refresco:precios:<proveedor>`` para el S&P 500 y el núcleo; ``refresco:precios:<proveedor>:<grupo>`` para
    los demás, ``GRUPOS_LOTE``) y una ``limitacion_declarada`` por fichero que no llega (``motivos`` o «sin datos
    recientes»). Los del grupo ``otro`` (sin lote) quedan ``aplazado``. La suma de ficheros de las filas es la de
    ``queda``. ``lotes``: ``grupo → tickers`` descargados por primera vez en el lote del grupo (``universo``: los
    ``ok`` de ``3b2_universo``); el ``detalle`` separa esos de los ficheros del grupo que ya estaban (127 = 125 + 2).
    ``no_llegan``: ficheros con aviso ``no_llega_corte`` en los precios curados (``curada_precios``): no llegan
    aunque su última sesión sea posterior al corte (SNDK: hueco antes del corte y dos sesiones después)."""
    lotes = {k: set(v) for k, v in (lotes or {}).items()}
    sp500, nucleo, ampliado, otros_3b1 = set(sp500), set(nucleo), set(ampliado), set(otros_3b1)
    motivos = dict(MOTIVOS_REFRESCO if motivos is None else motivos)
    q = precios[precios["decision"] == "queda"].copy()
    q["ultima"] = pd.to_datetime(q["id"].map(dict(ultimas)))
    q["grupo"] = [grupo_fichero(str(t), str(p), bool(u), sp500, nucleo, ampliado, otros_3b1)
                  for t, p, u in zip(q["id"], q["proveedor"], q["en_universo"])]
    q["llega"] = (q["ultima"] >= pd.Timestamp(corte)) & ~q["id"].isin(set(no_llegan))
    filas = []

    def _fila(id_: str, prov: str, detalle: str, estado: str, motivo: str, tipo: str = "refresco") -> None:
        filas.append({"id": id_, "tipo": tipo, "fuente": prov, "prioridad": "alta" if estado == "hecho" else
                      "no se descarga", "detalle": detalle, "estado_3b": estado, "motivo_3b": motivo})

    for prov, g in q.groupby("proveedor", sort=True):
        basico = g[g["grupo"].isin(["sp500", "nucleo"])]
        hecho = basico[basico["llega"]]
        n_sp, n_nu = int((hecho["grupo"] == "sp500").sum()), int((hecho["grupo"] == "nucleo").sum())
        if len(hecho):
            _fila(f"refresco:precios:{prov}", str(prov), f"{len(hecho)} ficheros (S&P 500 {n_sp}, núcleo {n_nu})",
                  "hecho", f"refrescados en el 3b-1: llegan a la fecha de corte {corte} (última sesión máxima "
                  f"{hecho['ultima'].max():%Y-%m-%d})")
        no_llegan = [basico[~basico["llega"]]]
        for grupo, tanda, motivo in GRUPOS_LOTE:
            gg = g[g["grupo"] == grupo]
            si = gg[gg["llega"]] if grupo != "otros_3b1" else gg
            if len(si):
                detalle = f"{len(si)} ficheros"
                if grupo in lotes:
                    k = int(si["id"].isin(set(lotes[grupo])).sum())
                    detalle += f" ({k} descargados en el lote y {len(si) - k} que ya estaban antes del 3b-2)"
                _fila(f"refresco:precios:{prov}:{grupo}", str(prov), detalle, "hecho",
                      f"{motivo}; última sesión máxima {si['ultima'].max():%Y-%m-%d}"
                      + (f" (llegan a la fecha de corte {corte}, {tanda})" if grupo != "otros_3b1" else ""))
            if grupo != "otros_3b1":
                no_llegan.append(gg[~gg["llega"]])
        otro = g[g["grupo"] == "otro"]
        if len(otro):
            _fila(f"refresco:precios:{prov}:otro", str(prov), f"{len(otro)} ficheros", "aplazado",
                  "fichero sin lote del 3b: revisar")
        for _, r in pd.concat(no_llegan).sort_values("id").iterrows():
            ult = f"{r['ultima']:%Y-%m-%d}" if pd.notna(r["ultima"]) else "sin fichero"
            _fila(str(r["id"]), str(prov), f"{r['grupo']}; última sesión {ult}", "limitacion_declarada",
                  motivos.get(str(r["id"]), f"sin datos recientes en Yahoo (última sesión {ult})"),
                  tipo="excepcion_refresco")
    return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))


def partir_refresco_yf(ids: Iterable[str], hasta: Mapping[str, pd.Timestamp], corte: str = FECHA_CORTE,
                       motivos: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Filas que sustituyen a ``refresco:yfinance`` (función pura): ``hecho`` con las series ``yf:`` que se quedan
    (``ids``) y llegan a ``corte`` en la base (``hasta``: última ``fecha_referencia``), y una
    ``limitacion_declarada`` (``excepcion_refresco``) por serie que no llega (``motivos`` o ``MOTIVO_YF``)."""
    motivos = dict(MOTIVOS_YF if motivos is None else motivos)
    ids = sorted(set(ids))
    if not ids:
        return pd.DataFrame(columns=list(COLUMNAS_EXTRA))
    ult = {s: hasta.get(s) for s in ids}
    llegan = [s for s in ids if ult[s] is not None and pd.notna(ult[s]) and ult[s] >= pd.Timestamp(corte)]
    no = [s for s in ids if s not in llegan]
    filas = [{"id": "refresco:yfinance", "tipo": "refresco", "fuente": "yfinance", "prioridad": "alta",
              "detalle": f"{len(llegan)} de {len(ids)} series que se quedan",
              "estado_3b": "hecho" if llegan else "limitacion_declarada",
              "motivo_3b": (f"extendidas desde el almacén de precios (fuentes.fase1.extender_precios; las de "
                             f"rendimientos del Tesoro con el mercado CGI): llegan a la fecha de corte {corte} "
                             f"(última fecha máxima {max(ult[s] for s in llegan):%Y-%m-%d})") if llegan else
              "ninguna serie llega a la fecha de corte"}]
    for s in no:
        filas.append({"id": s, "tipo": "excepcion_refresco", "fuente": "yfinance", "prioridad": "no se descarga",
                      "detalle": f"última fecha {_f(ult[s])}", "estado_3b": "limitacion_declarada",
                      "motivo_3b": motivos.get(s, MOTIVO_YF)})
    return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))


def filas_universo_3b2(registro: pd.DataFrame, universo: pd.DataFrame,
                       holgura: pd.Timedelta = pd.Timedelta(days=30)) -> pd.DataFrame:
    """Filas del lote ``3b2_universo`` (función pura): ``hecho`` con los instrumentos ``ok``, una
    ``limitacion_declarada`` por instrumento con error y una limitación agregada con los que empiezan más de
    ``holgura`` después de su ``inicio_esperado`` (historia recortada por Yahoo).

    ``registro``: ``yahoo.leer_registro('3b2_universo')`` (la última fila de cada ticker manda). ``universo``:
    ``universo.tabla_universo()`` (``ticker_yahoo``, ``inicio_esperado``)."""
    if registro is None or not len(registro):
        return pd.DataFrame(columns=list(COLUMNAS_EXTRA))
    reg = registro.drop_duplicates("ticker", keep="last")
    ok = reg[reg["estado"] == "ok"]
    filas = [{"id": "precios:universo:3b2", "tipo": "precios", "fuente": "yahoo", "prioridad": "alta",
              "detalle": f"{len(ok)} de {len(reg)} instrumentos", "estado_3b": "hecho",
              "motivo_3b": (f"descargados en el 3b-2 (lote 3b2_universo, G5): última sesión máxima "
                             f"{pd.to_datetime(ok['fin']).max():%Y-%m-%d}") if len(ok) else "ninguno ok"}]
    for _, r in reg[reg["estado"] != "ok"].sort_values("ticker").iterrows():
        filas.append({"id": f"yf:{r['ticker']}", "tipo": "precios", "fuente": "yahoo", "prioridad": "no se descarga",
                      "detalle": "lote 3b2_universo", "estado_3b": "limitacion_declarada",
                      "motivo_3b": f"F3: Yahoo no lo sirve ({str(r.get('error') or r['estado'])[:160]})"})
    if not len(ok):
        return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))
    esp = universo.dropna(subset=["ticker_yahoo"]).set_index("ticker_yahoo")["inicio_esperado"]
    m = ok.assign(inicio=pd.to_datetime(ok["inicio"]), esperado=ok["ticker"].map(esp)).dropna(subset=["esperado"])
    rec = m[m["inicio"] > m["esperado"] + holgura].sort_values("ticker")
    if len(rec):
        filas.append({
            "id": "precios:universo:historia_recortada", "tipo": "limitacion_agregada", "fuente": "yahoo",
            "prioridad": "no se descarga", "detalle": f"{len(rec)} instrumentos: {', '.join(rec['ticker'])}",
            "estado_3b": "limitacion_declarada",
            "motivo_3b": (f"Yahoo empieza más de {holgura.days} días después del lanzamiento (inicio_esperado, "
                           f"justETF): falta hasta {int((rec['inicio'] - rec['esperado']).dt.days.max())} días de "
                           "historia; se guarda lo que hay (F3: solo Yahoo)")})
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
            "estado_3b": "limitacion_declarada",
            "motivo_3b": (f"{int(v['tramos_ticker_reutilizado'])} tramos del S&P 500 tienen un fichero que no es el "
                           "miembro (no solapa con ninguno de sus tramos o no es una acción): se quedan con aviso "
                           "'ticker reutilizado' en la lista curada; sin CIK/PERMNO no se trae el miembro (F3)")})
    altas = sorted({t for _, a, _ in CAMBIOS_SP500_POSTERIORES for t in a} - set(ALTAS_CON_FICHERO_PREVIO))
    cambios = "; ".join(f"{f}: +{', '.join(a) or '-'} / -{', '.join(b) or '-'}"
                        for f, a, b in CAMBIOS_SP500_POSTERIORES)
    filas.append({
        "id": "constituyentes:sp500_posterior_fja", "tipo": "constituyentes", "fuente": "sp500_constituyentes",
        "prioridad": "no se descarga", "detalle": cambios, "estado_3b": "limitacion_declarada",
        "motivo_3b": (f"fja05680/sp500 refrescado el 2026-11-20 sin cambios: su último cambio es del "
                       f"{ULTIMO_CAMBIO_FJA}. Los cambios posteriores de S&P DJI no están en los tramos; los precios "
                       f"de las altas sí están descargados (lote 3b1_altas: {', '.join(altas)}; "
                       f"{', '.join(ALTAS_CON_FICHERO_PREVIO)} ya tenía fichero y se refrescó en el lote 3b1)")})
    return pd.DataFrame(filas, columns=list(COLUMNAS_EXTRA))


def construir(entrada: pd.DataFrame, precios_refresco: pd.DataFrame | None = None,
              sp500: pd.DataFrame | None = None, medidas: MedidasBase | None = None,
              yf_refresco: pd.DataFrame | None = None, universo_3b2: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabla de estado: las filas de ``descargas_3b.csv`` con su estado (``estado_fila`` y ``medidas``), la de
    ``refresco:precios:*`` partida (``precios_refresco``), la de ``refresco:yfinance`` partida (``yf_refresco``), el
    lote del universo (``universo_3b2``) y las limitaciones agregadas del S&P 500 (``sp500``)."""
    out = entrada.copy()
    quitar: set[str] = set()
    if precios_refresco is not None:
        quitar |= {f"refresco:precios:{p}" for p in set(precios_refresco["fuente"])}
    if yf_refresco is not None and len(yf_refresco):
        quitar.add("refresco:yfinance")
    if universo_3b2 is not None and len(universo_3b2):
        # Los instrumentos del lote con error ya tienen su fila (y la misma id que la de descargas_3b.csv).
        quitar |= set(universo_3b2.loc[universo_3b2["tipo"] == "precios", "id"]) - {"precios:universo:3b2"}
    out = out[~out["id"].isin(quitar)]
    res = out.apply(lambda f: estado_fila(f, medidas), axis=1, result_type="expand")
    out["estado_3b"], out["motivo_3b"] = res[0], res[1]
    extra = [x for x in (precios_refresco, yf_refresco, universo_3b2, sp500) if x is not None and len(x)]
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


def medir_base(ruta: Path | None = None) -> MedidasBase:
    """Primera y última ``fecha_referencia`` de cada serie de la base y ediciones (``vintage``) del WEO."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from ingesta.mercados_series import almacen

    ruta = ruta or almacen.ruta_series()
    t = pq.read_table(ruta, columns=["serie", "fuente", "fecha_referencia"])
    g = t.group_by("serie").aggregate([("fecha_referencia", "min"), ("fecha_referencia", "max")]).to_pandas()
    f = t.group_by("fuente").aggregate([("fecha_referencia", "max")]).to_pandas()
    w = pq.read_table(ruta, columns=["vintage"], filters=[("fuente", "==", "imf_weo")])
    ediciones = frozenset(str(v) for v in pc.unique(w.column("vintage")).to_pylist() if v)
    return MedidasBase(desde=dict(zip(g["serie"], pd.to_datetime(g["fecha_referencia_min"]))),
                       hasta=dict(zip(g["serie"], pd.to_datetime(g["fecha_referencia_max"]))),
                       ediciones_weo=ediciones,
                       hasta_fuente=dict(zip(f["fuente"], pd.to_datetime(f["fecha_referencia_max"]))))


def fechas_crudo(raiz: Path | None = None) -> dict[str, pd.Timestamp]:
    """Día (fecha de modificación) del fichero más reciente de cada carpeta de ``<corpus>/mercados_series/crudo/``."""
    carpeta = raiz or corpus_dir(TEMA) / "crudo"
    out: dict[str, pd.Timestamp] = {}
    if not carpeta.exists():
        return out
    for d in sorted(p for p in carpeta.iterdir() if p.is_dir()):
        tiempos = [f.stat().st_mtime for f in d.rglob("*") if f.is_file()]
        if tiempos:
            out[d.name] = pd.Timestamp(max(tiempos), unit="s").normalize()
    return out


def no_llegan_corte(tablas: Path) -> set[str]:
    """Tickers con aviso ``no_llega_corte`` en ``tablas/precios_curados_avisos.csv`` (vacío si no hay tabla)."""
    ruta = tablas / "precios_curados_avisos.csv"
    if not ruta.exists():
        return set()
    a = pd.read_csv(ruta, dtype={"ticker": str}, usecols=["ticker", "tipo"])
    return set(a.loc[a["tipo"] == "no_llega_corte", "ticker"])


def capturas_oas(ruta: Path | None = None) -> frozenset[str]:
    """Días de las capturas de ``archivar-oas`` (columna ``capturas_nuevas`` de ``archivo/ice_oas/registro.csv``)."""
    ruta = ruta or corpus_dir(TEMA) / "archivo" / "ice_oas" / "registro.csv"
    if not ruta.exists():
        return frozenset()
    reg = pd.read_csv(ruta, dtype=str)
    return frozenset(c for x in reg.get("capturas_nuevas", pd.Series(dtype=str)).dropna() for c in x.split() if c)


#: Otros lotes de Yahoo del 3b-1 (registro ``logs/yahoo_<etiqueta>.jsonl``) que no son S&P 500 ni núcleo.
LOTES_OTROS_3B1 = ("3b1_yf",)
LOTE_UNIVERSO_3B2 = "3b2_universo"


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
    from ingesta.mercados_series import universo
    from ingesta.mercados_series.proveedores import yahoo

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tablas", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    a = p.parse_args(argv)
    tablas = a.tablas or resultados_dir(TEMA) / "tablas"
    precios = pd.read_csv(tablas / "seleccion_precios.csv", dtype={"id": str})
    series = pd.read_csv(tablas / "seleccion_series.csv", dtype={"id": str})
    sp500, nucleo, ampliado, otros = conjuntos_lotes()
    reg_uni = yahoo.leer_registro(LOTE_UNIVERSO_3B2)
    lote_uni = (set(reg_uni.drop_duplicates("ticker", keep="last").query("estado == 'ok'")["ticker"].astype(str))
                if len(reg_uni) else set())
    partidas = partir_refresco_precios(precios, ultimas_sesiones(), sp500, nucleo, ampliado, otros_3b1=otros,
                                       lotes={"universo": lote_uni}, no_llegan=no_llegan_corte(tablas))
    medidas = replace(medir_base(), crudos=fechas_crudo(), capturas_oas=capturas_oas())
    yf_ids = series.loc[(series["fuente"] == "yfinance") & (series["decision"] == "queda"), "id"]
    resumen = cobertura_sp500(tablas)
    tabla = construir(pd.read_csv(tablas / FICHERO_ENTRADA), partidas, filas_sp500(resumen), medidas,
                      partir_refresco_yf(yf_ids, medidas.hasta),
                      filas_universo_3b2(reg_uni, universo.tabla_universo(), yahoo.HOLGURA_INICIO))
    destino = tablas / FICHERO_SALIDA
    tabla.to_csv(destino, index=False, encoding="utf-8", lineterminator="\n")
    rutas = {"descargas_3b_estado": destino}
    print(tabla.groupby(["estado_3b", "tipo"]).size().to_string())
    if resumen is not None:
        rutas["sp500_cobertura_3b1"] = tablas / FICHERO_COBERTURA_SP500
        resumen.to_csv(rutas["sp500_cobertura_3b1"], index=False, encoding="utf-8", lineterminator="\n")
        print(resumen.to_string(index=False))
    return rutas


if __name__ == "__main__":
    main()
