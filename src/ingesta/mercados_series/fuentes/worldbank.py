"""Banco Mundial (API v2 de api.worldbank.org): macro anual de TODOS los países (resto del mundo), bloque 4.

Indicadores (WDI): crecimiento del PIB real (``NY.GDP.MKTP.KD.ZG``), inflación IPC
(``FP.CPI.TOTL.ZG``) y paro, estimación modelizada de la OIT (``SL.UEM.TOTL.ZS``). Una petición por
indicador con todos los países (``/country/all/indicator/<ind>?format=json&per_page=20000&date=1960:<año>``)
y otra
para la lista de países (``/country``), que separa países de agregados (``region.id == 'NA'``). De los
agregados solo entran, de forma explícita, los de D3 (``AGREGADOS``, paso 3b-2): mundo (``WLD``), renta
baja y media (``LMY``, los emergentes) y zona euro (``EMU``, composición actual del Banco Mundial
retropolada); el resto (regionales, por renta, UE...) se descarta.

Rango de años explícito (``date``, paso 3b-2): el 2026-11-20 la API devolvió para ``SL.UEM.TOTL.ZS``
solo el último año (235 filas) con ``per_page=20000`` y sin ``date``, y la serie entera (17.556 filas)
con ``date=1960:2026``; ``tabla_wb`` lo pide siempre y avisa si un indicador llega con un solo año.

Ids ``wb:<ISO3>.<indicador>`` (p. ej. ``wb:ESP.NY.GDP.MKTP.KD.ZG``); ``fecha_referencia`` = 1 de enero
del año. Sin vintages: ``lag_fijo`` conservador ``LAG`` desde el fin del año (el WDI publica el año
``t`` entre abril y julio de ``t+1`` y lo revisa en cada actualización): fin del año siguiente,
``vintage`` = ``unico`` y nota de revisable. Huecos interiores: nulo con nota.

CLI: ``python -m ingesta.mercados_series.fuentes.worldbank [--forzar]``.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from ingesta.comun.esquema import FichaFuente
from ingesta.comun.fichas import guardar_ficha
from ingesta.mercados_series import catalogo as cat_mod
from ingesta.mercados_series.fuentes import _organismos as org

FUENTE = "worldbank"
URL_INDICADOR = "https://api.worldbank.org/v2/country/all/indicator/{indicador}"
URL_PAISES = "https://api.worldbank.org/v2/country"
INDICADORES = {
    "NY.GDP.MKTP.KD.ZG": ("Crecimiento del PIB real", "% anual"),
    "FP.CPI.TOTL.ZG": ("Inflación (IPC), variación anual", "% anual"),
    "SL.UEM.TOTL.ZS": ("Tasa de paro (estimación modelizada OIT)", "% de la población activa"),
}
LAG = "12M"
FIN_PERIODO = "anio"
NOTA_REVISABLE = cat_mod.NOTA_REVISABLE_EDICION
# D3 (paso 3b-2): agregados admitidos de forma explícita (los demás agregados se descartan).
AGREGADOS = {"WLD": "mundo", "LMY": "renta baja y media (emergentes)",
             "EMU": "zona euro (composición actual del Banco Mundial, retropolada)"}
NOTA_AGREGADO = "agregado del Banco Mundial ({nombre}): media ponderada calculada por el Banco Mundial, no un país"
NOTA_ALCANCE = "solo países y los agregados de D3 (WLD, LMY, EMU); el resto de agregados se descarta"
ANIO_INICIO = 1960   # primer año del WDI


def params_indicador(hoy: Any = None) -> dict[str, Any]:
    """Parámetros de la petición de un indicador: rango de años explícito hasta el año en curso."""
    anio = pd.Timestamp(hoy).year if hoy is not None else pd.Timestamp.now().year
    return {"format": "json", "per_page": 20000, "date": f"{ANIO_INICIO}:{anio}"}


def id_serie(iso3: str, indicador: str) -> str:
    return f"wb:{iso3}.{indicador}"


def leer_paises(contenido: bytes | str) -> pd.DataFrame:
    """``/v2/country?format=json`` → ``iso3, nombre, region, ingreso, es_pais``."""
    j = json.loads(contenido)
    filas = [(c["id"], c["name"], c["region"]["value"], c["incomeLevel"]["value"], c["region"]["id"] != "NA")
             for c in j[1]]
    return pd.DataFrame(filas, columns=["iso3", "nombre", "region", "ingreso", "es_pais"])


def codigos_admitidos(paises: pd.DataFrame) -> pd.Series:
    """ISO3 que entran en la tabla: los países y los agregados de ``AGREGADOS`` (D3)."""
    return paises.loc[paises["es_pais"] | paises["iso3"].isin(AGREGADOS), "iso3"]


def leer_indicador(contenido: bytes | str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """``/v2/country/all/indicator/<ind>?format=json`` → ``iso3, anio, valor`` y la cabecera."""
    j = json.loads(contenido)
    cab = j[0]
    if cab.get("pages", 1) > 1:
        raise ValueError(f"respuesta paginada ({cab['pages']} páginas): sube per_page")
    filas = [(o["countryiso3code"] or o["country"]["id"], int(o["date"]), o["value"]) for o in (j[1] or [])]
    df = pd.DataFrame(filas, columns=["iso3", "anio", "valor"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df, {"total": cab.get("total"), "lastupdated": cab.get("lastupdated")}


def tabla_indicador(datos: pd.DataFrame, indicador: str, paises: Iterable[str]) -> pd.DataFrame:
    """Filas del contrato de un indicador para los países dados."""
    nombre, unidad = INDICADORES[indicador]
    trozos = []
    d = datos[datos["iso3"].isin(set(paises))]
    for iso3, g in d.groupby("iso3", sort=True):
        s = g.set_index(pd.to_datetime(g["anio"].astype(str) + "-01-01"))["valor"]
        s = s[~s.index.duplicated(keep="last")]
        s, nota = org.recortar_huecos(s)
        if s.empty:
            continue
        pub = cat_mod.fecha_publicacion_lag(pd.Series(s.index), LAG, FIN_PERIODO)
        nota = nota.map(lambda n: f"{n}; {NOTA_REVISABLE}" if n else NOTA_REVISABLE)
        if iso3 in AGREGADOS:
            nota = nota + "; " + NOTA_AGREGADO.format(nombre=AGREGADOS[iso3])
        trozos.append(org.filas(id_serie(iso3, indicador), s.index, pub.values, s.values, vintage="unico",
                                unidad=unidad, divisa=None, fuente=FUENTE, metodo="lag_fijo", nota=nota.values))
    return org.unir(trozos)


def tabla_wb(indicadores: Iterable[str] = tuple(INDICADORES), *, forzar: bool = False,
             raiz: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Tabla del contrato (países y agregados de D3), informe por indicador y lista de países."""
    contenido, meta_p = org.descargar(FUENTE, "paises.json", URL_PAISES,
                                      params={"format": "json", "per_page": 400}, forzar=forzar, raiz=raiz)
    if contenido is None:
        return org.unir([]), {"paises": meta_p}, pd.DataFrame()
    paises = leer_paises(contenido)
    iso_paises = codigos_admitidos(paises)
    trozos, informe = [], {"paises": {"n_paises": int(paises["es_pais"].sum()),
                                      "n_agregados": int((~paises["es_pais"]).sum()),
                                      "agregados_admitidos": sorted(set(AGREGADOS) & set(iso_paises))}}
    for ind in indicadores:
        contenido, meta = org.descargar(FUENTE, f"{ind}.json", URL_INDICADOR.format(indicador=ind),
                                        params=params_indicador(), forzar=forzar, raiz=raiz,
                                        timeout=120)
        info = {"error": meta.get("error"), "bytes": meta.get("bytes"), "segundos": meta.get("segundos")}
        if contenido is not None:
            datos, cab = leer_indicador(contenido)
            info |= cab
            info["n_anios"] = int(datos["anio"].nunique())
            if info["n_anios"] <= 1:
                info["aviso"] = "la API devolvió un solo año: respuesta incompleta (revisar el parámetro date)"
            trozos.append(tabla_indicador(datos, ind, iso_paises))
        informe[ind] = info
    return org.unir(trozos), informe, paises


def frecuencias(tabla: pd.DataFrame) -> dict[str, str]:
    return {sid: "anual" for sid in tabla["serie"].unique()}


def patrones_fragmento() -> dict[str, dict[str, Any]]:
    """Una entrada por indicador con id patrón ``wb:*.<indicador>`` (cientos de países: no se enumeran).

    Los agregados de D3 (``AGREGADOS``) van en la lista ``paises`` del catálogo como un código más.
    """
    return {id_serie("*", ind): {
        "alias": None, "nombre": f"Banco Mundial (WDI): {nombre} - todos los países", "fuente": FUENTE,
        "id_origen": ind, "frecuencia": "anual", "unidad": unidad, "divisa": None, "metodo": "lag_fijo",
        "lag_clave": "WB_ANUAL", "revisable": True, "rol_fase1": None,
        "licencia": "Banco Mundial: CC BY 4.0", "estado": "activa", "agentes": ["macro"],
        "notas": [NOTA_REVISABLE, f"lag conservador {LAG} desde el fin del año (WDI publica t en abril-julio de t+1)",
                  NOTA_ALCANCE],
        "verificado": False} for ind, (nombre, unidad) in INDICADORES.items()}


def lags_fragmento() -> dict[str, dict[str, Any]]:
    return {"WB_ANUAL": {"lag": LAG, "fin_periodo": FIN_PERIODO, "verificado": False,
                         "justificacion": "WDI: el año t sale entre abril y julio de t+1; fin de t+1 (conservador)"}}


def ficha_wb(tabla: pd.DataFrame, informe: dict[str, Any], meta: pd.DataFrame) -> Path:
    med = org.resumen_medido(meta)
    errores = {k: v.get("error") for k, v in informe.items() if isinstance(v, dict) and v.get("error")}
    ultimo = {}
    if not tabla.empty:
        for ind in INDICADORES:
            sub = tabla[tabla["serie"].str.endswith("." + ind) & tabla["valor"].notna()]
            if len(sub):
                por_anio = sub.groupby(sub["fecha_referencia"].dt.year)["serie"].nunique()
                ultimo[ind] = {"ultimo_anio": int(por_anio.index.max()), "paises_ultimo_anio": int(por_anio.iloc[-1]),
                               "paises_penultimo_anio": int(por_anio.iloc[-2]) if len(por_anio) > 1 else None}
    agregados = {}
    if not tabla.empty:
        for iso in AGREGADOS:
            sub = tabla[tabla["serie"].str.startswith(f"wb:{iso}.") & tabla["valor"].notna()]
            agregados[iso] = {s.split(".", 1)[1]: {"inicio": int(g["fecha_referencia"].dt.year.min()),
                                                   "ultimo_anio": int(g["fecha_referencia"].dt.year.max())}
                              for s, g in sub.groupby("serie")}
    ficha = FichaFuente(
        fuente=FUENTE, nombre="Banco Mundial, World Development Indicators (API v2)", tema=org.TEMA,
        agentes=["macro"], rag="serie", url="https://api.worldbank.org/v2/", acceso="api", autenticacion="ninguna",
        coste="0 €", licencia_y_terminos="CC BY 4.0 (términos de datos abiertos del Banco Mundial)",
        cobertura_inicio=med.get("cobertura_inicio"), cobertura_fin=med.get("cobertura_fin"), frecuencia="anual",
        retraso_publicacion=(f"sin vintages: lag fijo {LAG} desde el fin del año (fin de t+1); medido: último año "
                             f"publicado por indicador en 'ultimo_anio' (retraso observado mínimo "
                             f"{med.get('retraso_observado_dias_min')} días desde el fin de ese año)"),
        formato="json", volumen_estimado=f"{med.get('observaciones', 0)} filas en {med.get('series', 0)} series",
        limites="sin clave; per_page hasta 20000 (una página por indicador)",
        estado_sonda="fallo" if tabla.empty else ("parcial" if errores else "ok"),
        mediciones={**med, "errores": errores, "ultimo_anio": ultimo, "agregados": agregados,
                    "informe": informe},
        notas=[NOTA_ALCANCE + " (region.id 'NA')", "paro: estimación modelizada de la OIT, "
               "muy revisada; inflación y PIB revisados en cada actualización del WDI (lastupdated en informe)"])
    return guardar_ficha(ficha)


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Banco Mundial: PIB, inflación y paro anuales de los países y los agregados de D3")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args(argv)
    tabla, informe, _ = tabla_wb(forzar=a.forzar)
    meta = org.medir(tabla, frecuencias(tabla))
    print("tabla:", org.guardar_tabla(tabla, FUENTE), len(tabla), "filas")
    print("metadatos:", org.guardar_metadatos(meta, FUENTE))
    print("ficha:", ficha_wb(tabla, informe, meta))


if __name__ == "__main__":
    main()
