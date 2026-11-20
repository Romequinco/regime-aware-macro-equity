"""FMI: World Economic Outlook por EDICIÓN (vintages ``AAAA-MM``), bloque 4 del Tema 1 (3b-2: G3 y agregados).

Origen: API SDMX 3.0 del FMI (``api.imf.org/external/sdmx/3.0``, agencia ``IMF.RES``). Medido el 2026-11-20 con
``structure/dataflow/*/*/*``: sirve cuatro ediciones del WEO (``VERSIONES_SDMX``):

- ``WEO/9.0.0``: la edición vigente (2026-10);
- ``WEO/6.0.0``: la edición de 2025-04 (sin ``COUNTRY_UPDATE_DATE``; la edición sale de ``PUBLICATION_DATE``);
- ``WEO_2026_APR_VINTAGE/1.0.0`` y ``WEO_2025_OCT_VINTAGE/1.0.0``: las ediciones archivadas de 2026-04 y 2025-10.

La edición de cada fichero sale de sus atributos de conjunto ``PUBLICATION_DATE`` (o, si falta, del
``COUNTRY_UPDATE_DATE`` de las series: mes <= 6 → ``AAAA-04``; si no, ``AAAA-10``) y se contrasta con el nombre del
flujo (``WEO_2025_OCT_VINTAGE`` → 2025-10) y con ``FECHAS_EDICION``.

Ediciones de 2008-04 a 2024-10 (G3): **limitación declarada**. El archivo de www.imf.org por edición
(``/en/Publications/WEO/weo-database/<AAAA>/<Mes>``) no se puede consultar: su ``robots.txt`` responde 403 «Access
Denied» (Akamai) con nuestro User-Agent (medido el 2026-11-20, ``ROBOTS_IMF_ORG``) y la semántica estándar de un 401/403
es «todo prohibido» (``ingesta.comun.http._robots``). DBnomics no se usa (G3; su ``robots.txt`` es ``Disallow: /``):
su lector se conserva solo para los tests y por si algún día lo permite (``--ediciones``; por defecto, ninguna).

Conceptos: PIB real (``NGDP_RPCH``), inflación media (``PCPIPCH``), paro (``LUR``), saldo fiscal (``GGXCNL_NGDP``, % del
PIB) y deuda bruta (``GGXWDG_NGDP``, % del PIB) de EE. UU., G7 y China, y de los agregados ``AGREGADOS`` (mundo ``001``,
zona euro ``163`` y emergentes y en desarrollo ``200``; en la API ``G001``, ``G163`` y ``G200``; el FMI no publica el
paro del mundo ni el de los emergentes, ni el saldo y la deuda del mundo). Ids ``imf:WEO.<área>.<concepto>``;
``fecha_referencia`` = 1 de enero del año.

Publicación: ``vintage`` = edición; ``fecha_publicacion`` = día de publicación de la edición (``FECHAS_EDICION``) a las
09:00 de Washington (``disponible_utc``), salvo las horas de ``HORAS_EDICION`` (la de 2026-10 se midió en la API a las
07:46 de Nueva York). Si el fichero dice otra cosa, manda lo más tardío (``tabla_edicion``): ``PUBLICATION_DATE`` y
``UPDATE_DATE`` del fichero (una edición que el FMI corrigió después de publicarla, como la de 2025-10 el 2025-11-19,
se fecha en la corrección: no se sabe qué valores cambió y así no se adelanta ninguno; lleva ``NOTA_ACTUALIZADA``). Las
ediciones de octubre de 2012 (Tokio), 2018 (Bali), 2023 (Marrakech) y 2026 (Bangkok) se presentaron en la sede de las
Reuniones Anuales: la mañana local cae ANTES de las 09:00 de Washington del mismo día, pero la fecha de decisión
(16:30 de Nueva York) es la misma, así que la regla no adelanta ningún dato.

Dato frente a proyección (D4; los agentes no deben confundirlos): ``imf:WEO.<área>.<concepto>`` solo trae años
ANTERIORES al de la edición (en la de abril el año anterior aún puede ser estimación de algunos países: va en la nota
del concepto). La estimación del año en curso y las proyecciones van a series propias por horizonte
``imf:WEO.<área>.<concepto>.PROY.H<h>`` (``h`` = años desde el de la edición, 0..``HORIZONTE_MAX``), todas con
``fecha_referencia`` = 1 de enero del AÑO DE LA EDICIÓN (el contrato no admite filas publicadas antes de su periodo) y
la nota ``NOTA_PROYECCION`` con el año objetivo; el paso 4 las lleva a la tabla de proyecciones. Más allá de
``HORIZONTE_MAX``, descartadas.

CLI: ``python -m ingesta.mercados_series descargar-imf [--sin-sdmx] [--forzar]`` (o ``python -m
ingesta.mercados_series.fuentes.imf``): tabla en ``<corpus>/mercados_series/bloque4/imf_weo.parquet``, metadatos y
ficha ``imf_weo``.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from ingesta.comun.esquema import FichaFuente
from ingesta.comun.fichas import guardar_ficha
from ingesta.mercados_series.contrato import primera_decision_vec
from ingesta.mercados_series.fuentes import _organismos as org

FUENTE = "imf_weo"
URL_DBNOMICS = "https://api.db.nomics.world/v22/series/IMF/WEO:{edicion}"
URL_SDMX = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/{flujo}/{version}/{clave}"
# Flujos del WEO en la API (``<flujo>/<versión>``; una versión sola es del flujo ``WEO``). Medido el 2026-11-20.
VERSIONES_SDMX = ("WEO/9.0.0", "WEO/6.0.0", "WEO_2026_APR_VINTAGE/1.0.0", "WEO_2025_OCT_VINTAGE/1.0.0")
PAISES = ("USA", "DEU", "FRA", "ITA", "GBR", "JPN", "CAN", "CHN")
AGREGADOS = {"001": "G001", "163": "G163", "200": "G200"}   # código del WEO -> código de la API SDMX
AREAS = (*PAISES, *AGREGADOS)
NOMBRES_AGREGADO = {"001": "mundo", "163": "zona euro", "200": "economías emergentes y en desarrollo"}
CONCEPTOS = {
    "NGDP_RPCH": ("PIB real, variación anual", "% anual"),
    "PCPIPCH": ("Inflación (IPC medio), variación anual", "% anual"),
    "LUR": ("Tasa de paro", "% de la población activa"),
    "GGXCNL_NGDP": ("Saldo de las AA. PP. (capacidad/necesidad de financiación)", "% del PIB"),
    "GGXWDG_NGDP": ("Deuda bruta de las AA. PP.", "% del PIB"),
}
HORA_PUBLICACION = "09:00"
HUSO_PUBLICACION = "America/New_York"
NOTA_ESTIMACION = "estimación del año en curso en la edición (no dato cerrado)"
NOTA_PROYECCION = "proyección del WEO (no es un dato): valor para el año {anio}, horizonte {h} desde el año de la edición"
NOTA_ACTUALIZADA = ("edición actualizada por el FMI el {actualizada} (publicada el {publicada}): fechada en la "
                    "actualización, conservador")
SUFIJO_PROYECCION = ".PROY.H"
HORIZONTE_MAX = 5
# Hora medida o de la sede cuando no es la de Washington (solo cambia disponible_utc, no la fecha de decisión).
HORAS_EDICION = {"2026-10": ("07:46", "America/New_York")}   # primera descarga de la versión 9.0.0 (medida)
# Día de publicación de cada edición (páginas de la edición en imf.org/en/Publications/WEO/Issues/<AAAA>/<MM>/<DD> y
# notas de prensa). 2026-04 (14-abr) y 2026-10 (13-oct, Bangkok) contrastadas el 2026-10-13; 2025-04, 2025-10 y 2026-04
# contrastadas el 2026-11-20 con el PUBLICATION_DATE de sus ficheros en la API (09:00 de Washington, mismo día). Dos
# ficheros traen además un UPDATE_DATE posterior y se fechan en él (manda lo más tardío, instante_edicion): 2026-04
# (UPDATE_DATE 2026-04-15, un día después) y 2025-10 (UPDATE_DATE 2025-11-19).
FECHAS_EDICION = {
    "2008-04": "2008-04-09", "2008-10": "2008-10-08", "2009-04": "2009-04-22", "2009-10": "2009-10-01",
    "2010-04": "2010-04-21", "2010-10": "2010-10-06", "2011-04": "2011-04-11", "2011-09": "2011-09-20",
    "2012-04": "2012-04-17", "2012-10": "2012-10-09", "2013-04": "2013-04-16", "2013-10": "2013-10-08",
    "2014-04": "2014-04-08", "2014-10": "2014-10-07", "2015-04": "2015-04-14", "2015-10": "2015-10-06",
    "2016-04": "2016-04-12", "2016-10": "2016-10-04", "2017-04": "2017-04-18", "2017-10": "2017-10-10",
    "2018-04": "2018-04-17", "2018-10": "2018-10-09", "2019-04": "2019-04-09", "2019-10": "2019-10-15",
    "2020-04": "2020-04-14", "2020-10": "2020-10-13", "2021-04": "2021-04-06", "2021-10": "2021-10-12",
    "2022-04": "2022-04-19", "2022-10": "2022-10-11", "2023-04": "2023-04-11", "2023-10": "2023-10-10",
    "2024-04": "2024-04-16", "2024-10": "2024-10-22", "2025-04": "2025-04-22", "2025-10": "2025-10-14",
    "2026-04": "2026-04-14", "2026-10": "2026-10-13",
}
EDICIONES_DBNOMICS = tuple(e for e in FECHAS_EDICION if e <= "2025-04" and e != "2011-09")   # no se usan (G3)
# Comprobación de G3 (una sola petición, 2026-11-20): el robots.txt de www.imf.org no se deja leer.
ROBOTS_IMF_ORG = {"url": "https://www.imf.org/robots.txt", "medido": "2026-11-20", "estado_http": 403,
                  "respuesta": "Access Denied (Akamai, text/html)",
                  "lectura": "401/403 en robots.txt = todo prohibido (semántica estándar, ingesta.comun.http._robots)",
                  "rutas_afectadas": "https://www.imf.org/en/Publications/WEO/weo-database/<AAAA>/<Mes> y sus ficheros"}
MOTIVO_LIMITACION = ("limitación declarada (G3): ninguna API del FMI sirve la edición (la API SDMX solo tiene "
                     "2025-04, 2025-10, 2026-04 y 2026-10); el archivo de www.imf.org no es accesible (robots.txt "
                     "con 403 de Akamai: todo prohibido) y DBnomics no se usa")
_MESES_FLUJO = {"APR": "04", "OCT": "10", "SEP": "09"}


def id_serie(area: str, concepto: str) -> str:
    return f"imf:WEO.{area}.{concepto}"


def disponible(edicion: str) -> pd.Timestamp:
    """Instante UTC de publicación de la edición (09:00 de Washington del día documentado)."""
    if edicion not in FECHAS_EDICION:
        raise ValueError(f"edición {edicion!r} sin fecha de publicación documentada")
    hora, huso = HORAS_EDICION.get(edicion, (HORA_PUBLICACION, HUSO_PUBLICACION))
    local = pd.Timestamp(f"{FECHAS_EDICION[edicion]} {hora}").tz_localize(huso)
    return local.tz_convert("UTC")


def edicion_de_fecha(texto: str | pd.Timestamp) -> str:
    """``9/30/2026`` → ``2026-10``; ``3/20/2026`` → ``2026-04`` (COUNTRY_UPDATE_DATE o PUBLICATION_DATE)."""
    t = pd.Timestamp(texto)
    return f"{t.year}-{'04' if t.month <= 6 else '10'}"


def edicion_del_flujo(flujo: str) -> str | None:
    """``WEO_2025_OCT_VINTAGE`` → ``2025-10``; ``WEO`` (flujo vivo, sin edición en el nombre) → None."""
    m = re.fullmatch(r"WEO_(\d{4})_([A-Z]{3})_VINTAGE", flujo)
    return f"{m[1]}-{_MESES_FLUJO[m[2]]}" if m and m[2] in _MESES_FLUJO else None


def flujo_version(clave: str) -> tuple[str, str]:
    """``WEO_2026_APR_VINTAGE/1.0.0`` → ``(WEO_2026_APR_VINTAGE, 1.0.0)``; ``9.0.0`` → ``(WEO, 9.0.0)``."""
    flujo, _, version = clave.rpartition("/")
    return flujo or "WEO", version


def area_de_api(codigo: str) -> str:
    """Código de la API SDMX → código del WEO (``G001`` → ``001``; los países, tal cual)."""
    inverso = {v: k for k, v in AGREGADOS.items()}
    return inverso.get(codigo, codigo)


def nombre_area(area: str) -> str:
    return NOMBRES_AGREGADO.get(area, area)


# --- Lectores (sin red) --------------------------------------------------------------------------
def leer_dbnomics(contenido: bytes | str | dict) -> tuple[pd.DataFrame, dict[str, Any]]:
    """JSON de ``/series/IMF/WEO:<ed>`` → ``pais, concepto, anio, valor`` y metadatos (indexed_at). No se usa (G3)."""
    j = contenido if isinstance(contenido, dict) else json.loads(contenido)
    filas, indexado = [], []
    for s in j["series"]["docs"]:
        dim = s.get("dimensions", {})
        pais, concepto = dim.get("weo-country"), dim.get("weo-subject")
        if s.get("indexed_at"):
            indexado.append(s["indexed_at"])
        for p, v in zip(s["period"], s["value"]):
            filas.append((pais, concepto, int(str(p)[:4]), v))
    df = pd.DataFrame(filas, columns=["pais", "concepto", "anio", "valor"])
    df["valor"] = pd.to_numeric(df["valor"].replace({"NA": None}), errors="coerce")
    meta = {"n_series": len(j["series"]["docs"]), "num_found": j["series"].get("num_found"),
            "indexed_at_min": min(indexado) if indexado else None}
    return df, meta


def _json(contenido: bytes | str | dict) -> dict:
    return contenido if isinstance(contenido, dict) else json.loads(contenido)


def fechas_sdmx(contenido: bytes | str | dict) -> dict[str, pd.Timestamp | None]:
    """``PUBLICATION_DATE`` y ``UPDATE_DATE`` (atributos del conjunto de datos, UTC) de un fichero SDMX-JSON del FMI."""
    j = _json(contenido)
    st = j["data"]["structures"][0]
    ids = [a["id"] for a in (st.get("attributes") or {}).get("dataSet", [])]
    valores = j["data"]["dataSets"][0].get("attributes") or []
    out: dict[str, pd.Timestamp | None] = {}
    for nombre, clave in (("PUBLICATION_DATE", "publicacion"), ("UPDATE_DATE", "actualizacion")):
        v = valores[ids.index(nombre)] if nombre in ids and ids.index(nombre) < len(valores) else None
        v = v[0] if isinstance(v, list) and v else v
        out[clave] = pd.Timestamp(v).tz_convert("UTC") if isinstance(v, str) and v else None
    return out


def leer_sdmx(contenido: bytes | str | dict) -> tuple[pd.DataFrame, str | None]:
    """SDMX-JSON 3.0 del FMI → ``pais, concepto, anio, valor`` y la edición.

    La edición sale de ``PUBLICATION_DATE`` si el fichero lo trae y, si no, del mayor ``COUNTRY_UPDATE_DATE``. Los
    agregados vuelven con el código del WEO (``G001`` → ``001``).
    """
    j = _json(contenido)
    st = j["data"]["structures"][0]
    dims = st["dimensions"]["series"]
    pos = {d["id"]: i for i, d in enumerate(dims)}
    anios = [int(v["value"][:4]) for v in st["dimensions"]["observation"][0]["values"]]
    attrs = [a["id"] for a in st["attributes"].get("series", [])]
    i_fecha = attrs.index("COUNTRY_UPDATE_DATE") if "COUNTRY_UPDATE_DATE" in attrs else None
    filas, fechas = [], []
    for clave, s in j["data"]["dataSets"][0]["series"].items():
        idx = [int(k) for k in clave.split(":")]
        pais = area_de_api(dims[pos["COUNTRY"]]["values"][idx[pos["COUNTRY"]]]["id"])
        concepto = dims[pos["INDICATOR"]]["values"][idx[pos["INDICATOR"]]]["id"]
        if i_fecha is not None and i_fecha < len(s.get("attributes", [])) and s["attributes"][i_fecha]:
            fechas.append(pd.Timestamp(s["attributes"][i_fecha]))
        for k, v in s.get("observations", {}).items():
            filas.append((pais, concepto, anios[int(k)], v[0] if v else None))
    df = pd.DataFrame(filas, columns=["pais", "concepto", "anio", "valor"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    publicado = fechas_sdmx(j)["publicacion"]
    if publicado is not None:
        edicion = edicion_de_fecha(publicado)
    else:
        edicion = edicion_de_fecha(str(max(fechas).date())) if fechas else None
    return df, edicion


def id_proyeccion(area: str, concepto: str, h: int) -> str:
    """``imf:WEO.<área>.<concepto>.PROY.H<h>``: estimación (h=0) o proyección a h años de la edición."""
    return f"{id_serie(area, concepto)}{SUFIJO_PROYECCION}{h}"


def es_proyeccion(sid: str) -> bool:
    return SUFIJO_PROYECCION in sid


def instante_edicion(edicion: str, fechas_fichero: dict[str, pd.Timestamp | None] | None = None
                     ) -> tuple[pd.Timestamp, pd.Timestamp, str | None]:
    """``(disponible_utc, fecha_publicacion, nota)`` de una edición: lo más tardío entre la regla (``disponible``) y
    las fechas del fichero (``PUBLICATION_DATE``, ``UPDATE_DATE``). Nunca adelanta la regla documentada."""
    disp = disponible(edicion)
    dia = pd.Timestamp(FECHAS_EDICION[edicion])
    nota = None
    f = fechas_fichero or {}
    candidatos = [t for t in (f.get("publicacion"), f.get("actualizacion")) if t is not None]
    if candidatos and max(candidatos) > disp:
        disp = max(candidatos)
        dia = max(dia, primera_decision_vec(pd.Series([disp])).iloc[0])
    pub, act = f.get("publicacion"), f.get("actualizacion")
    if act is not None and pub is not None and act > pub and act > disponible(edicion):
        nota = NOTA_ACTUALIZADA.format(actualizada=act.tz_convert(HUSO_PUBLICACION).date().isoformat(),
                                       publicada=pub.tz_convert(HUSO_PUBLICACION).date().isoformat())
    return disp, dia, nota


def tabla_edicion(datos: pd.DataFrame, edicion: str,
                  fechas_fichero: dict[str, pd.Timestamp | None] | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Filas del contrato de una edición: datos (años anteriores al de la edición) en ``imf:WEO.<A>.<C>``;
    estimación del año en curso y proyecciones en ``...PROY.H<h>`` (fecha de referencia = año de la edición).

    ``fechas_fichero`` (``fechas_sdmx``): si el fichero dice que la edición salió o se corrigió después de la regla,
    se fecha en lo más tardío (``instante_edicion``)."""
    disp, dia_pub, nota_ed = instante_edicion(edicion, fechas_fichero)
    anio_ed = pd.Timestamp(FECHAS_EDICION[edicion]).year
    d = datos[datos["concepto"].isin(CONCEPTOS) & datos["pais"].isin(AREAS) & datos["valor"].notna()]
    d = d.drop_duplicates(["pais", "concepto", "anio"], keep="first")
    h = d["anio"] - anio_ed
    dato, proy, fuera = h < 0, (h >= 0) & (h <= HORIZONTE_MAX), h > HORIZONTE_MAX
    trozos = []
    comun = {"vintage": edicion, "divisa": None, "fuente": FUENTE, "metodo": "vintage_exacto"}
    for (pais, concepto), g in d[dato].groupby(["pais", "concepto"], sort=True):
        fechas = pd.to_datetime(g["anio"].astype(str) + "-01-01")
        trozos.append(org.filas(id_serie(pais, concepto), fechas.values, [dia_pub] * len(g), g["valor"].values,
                                unidad=CONCEPTOS[concepto][1], disponible_utc=[disp] * len(g), nota=nota_ed,
                                **comun))
    ref_ed = pd.Timestamp(f"{anio_ed}-01-01")
    for (pais, concepto, hh), g in d[proy].assign(h=h[proy]).groupby(["pais", "concepto", "h"], sort=True):
        nota = [NOTA_PROYECCION.format(anio=int(a), h=int(hh)) + ("; " + NOTA_ESTIMACION if hh == 0 else "")
                + (f"; {nota_ed}" if nota_ed else "") for a in g["anio"]]
        trozos.append(org.filas(id_proyeccion(pais, concepto, int(hh)), [ref_ed] * len(g), [dia_pub] * len(g),
                                g["valor"].values, unidad=CONCEPTOS[concepto][1], nota=nota,
                                disponible_utc=[disp] * len(g), **comun))
    return org.unir(trozos), {"filas": int(dato.sum()), "proyecciones": int(proy.sum()),
                              "proyecciones_descartadas": int(fuera.sum())}


# --- Descarga ------------------------------------------------------------------------------------
def descargar_dbnomics(edicion: str, *, forzar: bool = False, raiz: Path | None = None):
    """No se usa (G3): DBnomics está en ``Disallow: /``. Se conserva por si algún día lo permite."""
    params = {"dimensions": json.dumps({"weo-country": list(PAISES), "weo-subject": list(CONCEPTOS)}),
              "observations": 1, "limit": 1000}
    return org.descargar(FUENTE, f"dbnomics_WEO_{edicion}.json", URL_DBNOMICS.format(edicion=edicion),
                         params=params, forzar=forzar, raiz=raiz)


def url_sdmx(version: str) -> str:
    flujo, ver = flujo_version(version)
    claves_api = [AGREGADOS.get(a, a) for a in AREAS]
    clave = f"{'+'.join(claves_api)}.{'+'.join(CONCEPTOS)}.A"
    return URL_SDMX.format(flujo=flujo, version=ver, clave=clave)


def descargar_sdmx(version: str, *, forzar: bool = False, raiz: Path | None = None):
    """Un flujo del WEO (países y agregados) como crudo ``<hoy>_sdmx_<flujo>_<versión>.json``."""
    flujo, ver = flujo_version(version)
    return org.descargar(FUENTE, f"sdmx_{flujo}_{ver}.json", url_sdmx(version),
                         params={"dimensionAtObservation": "TIME_PERIOD", "attributes": "all"},
                         headers={"Accept": "application/json"}, forzar=forzar, raiz=raiz)


def _iso(t: pd.Timestamp | None) -> str | None:
    return None if t is None else t.isoformat()


def tabla_weo(ediciones: Iterable[str] = (), *, sdmx: bool = True, forzar: bool = False,
              raiz: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Tabla del contrato con las ediciones de la API SDMX del FMI e informe por edición.

    ``ediciones``: ediciones de DBnomics (por defecto ninguna: G3). Una edición servida por DBnomics manda sobre la
    misma de la API (comportamiento heredado); una que DBnomics no pudo servir no cuenta como vista."""
    trozos, informe = [], {}
    vistas: set[str] = set()   # ediciones con filas (una edición que DBnomics no pudo servir no cuenta)
    for ed in ediciones:
        contenido, meta = descargar_dbnomics(ed, forzar=forzar, raiz=raiz)
        info = {"origen": "dbnomics", "error": meta.get("error"), "bytes": meta.get("bytes")}
        if contenido is not None:
            datos, m = leer_dbnomics(contenido)
            t, cuenta = tabla_edicion(datos, ed)
            info |= m | cuenta
            if m.get("indexed_at_min"):
                info["indexado_tras_publicacion"] = bool(pd.Timestamp(m["indexed_at_min"]) >= disponible(ed))
            trozos.append(t)
            if len(t):
                vistas.add(ed)
        informe[ed] = info
    if sdmx:
        for v in VERSIONES_SDMX:
            contenido, meta = descargar_sdmx(v, forzar=forzar, raiz=raiz)
            if contenido is None:
                informe[f"sdmx_{v}"] = {"origen": "sdmx", "error": meta.get("error")}
                continue
            datos, ed = leer_sdmx(contenido)
            esperada = edicion_del_flujo(flujo_version(v)[0])
            if esperada is not None and ed is not None and ed != esperada:
                informe[f"sdmx_{v}"] = {"origen": "sdmx", "edicion": ed, "error": f"el flujo es de {esperada}"}
                continue
            if ed is None or ed in vistas or ed not in FECHAS_EDICION:
                informe[f"sdmx_{v}"] = {"origen": "sdmx", "edicion": ed, "descartada": "repetida o sin fecha"}
                continue
            f = fechas_sdmx(contenido)
            t, cuenta = tabla_edicion(datos, ed, f)
            fallo = (informe.get(ed) or {}).get("error")
            disp, dia, nota = instante_edicion(ed, f)
            informe[ed] = {"origen": f"sdmx {v}", "bytes": meta.get("bytes"), **cuenta,
                           "publicacion_fichero": _iso(f["publicacion"]), "actualizacion_fichero": _iso(f["actualizacion"]),
                           "dia_documentado": FECHAS_EDICION[ed], "fecha_publicacion": dia.date().isoformat(),
                           "disponible_utc": disp.isoformat(), "fechada_en_la_actualizacion": nota is not None,
                           "areas": sorted(set(datos["pais"]) & set(AREAS)),
                           **({"error_dbnomics": fallo} if fallo else {})}
            vistas.add(ed)
            trozos.append(t)
    return org.unir(trozos), informe


def ids_proyeccion(ids: Iterable[str]) -> list[str]:
    """Todas las series de proyección (H0..HORIZONTE_MAX) de unas series base del WEO."""
    out = []
    for sid in ids:
        if es_proyeccion(sid):
            continue
        _, area, concepto = sid.split(":", 1)[1].split(".")
        out += [id_proyeccion(area, concepto, h) for h in range(HORIZONTE_MAX + 1)]
    return out


def frecuencias(tabla: pd.DataFrame) -> dict[str, str]:
    return {sid: "anual" for sid in tabla["serie"].unique()}


NOTA_EDICIONES = ("ediciones en la API SDMX del FMI: 2025-04, 2025-10, 2026-04 y 2026-10; las de 2008-04 a 2024-10, "
                  "limitación declarada (robots.txt de www.imf.org con 403 de Akamai: todo prohibido; DBnomics no se "
                  "usa, G3)")


def fragmento(ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Entradas del catálogo de las series del WEO (vintage por edición), países y agregados."""
    out = {}
    for sid in sorted(ids):
        partes = sid.split(":", 1)[1].split(".")
        area, concepto = partes[1], partes[2]
        nombre, unidad = CONCEPTOS[concepto]
        if es_proyeccion(sid):
            h = int(sid.rsplit(SUFIJO_PROYECCION, 1)[1])
            nombre = (f"WEO del FMI: {'estimación del año en curso' if h == 0 else f'proyección a {h} años'} "
                      f"de {nombre.lower()} - {nombre_area(area)}")
            notas = ["PROYECCIÓN, no dato: vintage = edición del WEO (AAAA-MM); fecha_referencia = 1 de enero del "
                     f"año de la edición; el valor es el del año de la edición + {h}"]
        else:
            nombre = f"WEO del FMI: {nombre} - {nombre_area(area)}"
            notas = ["vintage = edición del WEO (AAAA-MM); solo años anteriores al de la edición (la estimación del "
                     "año en curso y las proyecciones van a .PROY.H<h>); en la edición de abril el año anterior "
                     "aún puede ser estimación en algunos países"]
        if area in AGREGADOS:
            notas.append(f"agregado {AGREGADOS[area]} del WEO en la API SDMX ({nombre_area(area)}), calculado por el "
                         "FMI con su composición de cada edición")
        out[sid] = {"alias": None, "nombre": nombre, "fuente": FUENTE,
                    "id_origen": f"WEO/{AGREGADOS.get(area, area)}.{concepto}", "frecuencia": "anual",
                    "unidad": unidad, "divisa": None, "metodo": "vintage_exacto", "publicador": "imf_weo",
                    "revisable": True, "rol_fase1": None,
                    "licencia": "FMI: uso libre con cita (términos de imf.org)",
                    "estado": "activa", "agentes": ["macro"], "notas": [*notas, NOTA_EDICIONES],
                    "verificado": False}
    return out


def publicador_fragmento() -> dict[str, Any]:
    return {"imf_weo": {"hora": HORA_PUBLICACION, "huso": HUSO_PUBLICACION, "dia": "mismo",
                        "fuente": "https://www.imf.org/en/Publications/WEO", "verificado": False,
                        "notas": ["la fecha de cada edición está en fuentes.imf.FECHAS_EDICION (notas de prensa) y se "
                                  "contrasta con el PUBLICATION_DATE/UPDATE_DATE del fichero (manda lo más tardío)"]}}


def primera_publicacion(tabla: pd.DataFrame) -> str | None:
    """Primera ``fecha_publicacion`` visible de las series de dato (sin proyecciones), para D1."""
    d = tabla[~tabla["serie"].map(es_proyeccion)] if len(tabla) else tabla
    return None if d.empty else d["fecha_publicacion"].min().date().isoformat()


def nota_d1(primera: str | None) -> str:
    """Nota de D1 de la ficha, calculada con la primera publicación visible (no fija)."""
    if primera is None:
        return "D1: sin publicaciones visibles"
    cumple = primera <= "2001-01-02"
    llega_2008 = primera <= "2008-12-31"
    return (f"D1: primera publicación visible {primera}: {'cumple' if cumple else 'no cumple'} D1 (<= 2001-01-02)"
            + ("" if cumple else (" y llega a 2008" if llega_2008 else " ni llega a 2008")))


def ficha_weo(tabla: pd.DataFrame, informe: dict[str, Any], meta: pd.DataFrame) -> Path:
    med = org.resumen_medido(meta)
    for k in ("retraso_observado_dias_min", "retraso_observado_dias_mediana", "lag_aplicado_dias_mediana"):
        med.pop(k, None)   # sin sentido con vintages por edición (el año en curso aún no ha terminado)
    ediciones = sorted(e for e in informe if e in FECHAS_EDICION and not informe[e].get("error")
                       and informe[e].get("filas"))
    faltan = sorted(set(FECHAS_EDICION) - set(ediciones))
    errores = {e: i["error"] for e, i in informe.items() if i.get("error")}
    sospechas = [e for e, i in informe.items() if i.get("indexado_tras_publicacion") is False]
    actualizadas = sorted(e for e, i in informe.items() if i.get("fechada_en_la_actualizacion"))
    primera = primera_publicacion(tabla)
    areas = sorted({sid.split(".")[1] for sid in tabla["serie"].unique()}) if len(tabla) else []
    ficha = FichaFuente(
        fuente=FUENTE, nombre="FMI World Economic Outlook por edición (API SDMX del FMI)",
        tema=org.TEMA, agentes=["macro"], rag="serie", url="https://api.imf.org/external/sdmx/3.0/",
        acceso="api", autenticacion="ninguna", coste="0 €",
        licencia_y_terminos="FMI: reutilización con cita (copyright IMF, https://www.imf.org/external/terms.htm)",
        cobertura_inicio=med.get("cobertura_inicio"), cobertura_fin=med.get("cobertura_fin"),
        frecuencia="anual; dos ediciones al año (abril y octubre)",
        retraso_publicacion=("vintage exacto por edición: día de publicación documentado a las 09:00 de Washington, "
                             "contrastado con el PUBLICATION_DATE del fichero (manda lo más tardío, también el "
                             "UPDATE_DATE si el FMI corrigió la edición); 2026-10: 07:46 de Nueva York, medida; el año "
                             "en curso y las proyecciones a 1-5 años en series .PROY.H<h> aparte (D4)"),
        formato="SDMX-JSON 3.0 (api.imf.org)",
        volumen_estimado=f"{len(ediciones)} ediciones, {med.get('observaciones', 0)} filas, {med.get('series', 0)} series",
        limites="sin clave; 1 petición/s; la API solo sirve las ediciones de 2025-04 a 2026-10",
        estado_sonda="fallo" if tabla.empty else ("parcial" if faltan or errores else "ok"),
        mediciones={**med, "ediciones": ediciones, "ediciones_limitacion": faltan,
                    "motivo_limitacion": MOTIVO_LIMITACION, "robots_www_imf_org": ROBOTS_IMF_ORG,
                    "flujos_sdmx": list(VERSIONES_SDMX), "areas": areas, "errores": errores,
                    "primera_publicacion_visible": primera,
                    "cumple_D1": bool(primera is not None and primera <= "2001-01-02"),
                    "visible_desde_2008": bool(primera is not None and primera <= "2008-12-31"),
                    "ediciones_fechadas_en_la_actualizacion": actualizadas,
                    "ediciones_indexadas_antes_de_la_fecha_documentada": sospechas,
                    "proyecciones_descartadas": int(sum(i.get("proyecciones_descartadas", 0) for i in informe.values())),
                    "proyecciones_separadas": int(sum(i.get("proyecciones", 0) for i in informe.values())),
                    "por_edicion": informe},
        notas=[f"G3 (3b-2, {ROBOTS_IMF_ORG['medido']}): el robots.txt de www.imf.org responde 403 «Access Denied» de "
               "Akamai con nuestro User-Agent; 401/403 = todo prohibido, así que el archivo por edición "
               "(/en/Publications/WEO/weo-database/<AAAA>/<Mes>) no se consulta ni se esquiva",
               f"ediciones de 2008-04 a 2024-10 ({len(faltan)}): {MOTIVO_LIMITACION}",
               "DBnomics no se usa (G3); su lector queda en el código solo para los tests",
               nota_d1(primera),
               "API SDMX: WEO/9.0.0 (2026-10), WEO/6.0.0 (2025-04, sin COUNTRY_UPDATE_DATE: edición por "
               "PUBLICATION_DATE), WEO_2026_APR_VINTAGE y WEO_2025_OCT_VINTAGE (medido con structure/dataflow/*/*/*)",
               "agregados 001 (mundo), 163 (zona euro) y 200 (emergentes y en desarrollo): G001, G163 y G200 en la API; "
               "el FMI no publica el paro del mundo ni el de los emergentes, ni el saldo y la deuda del mundo",
               "FECHAS_EDICION: 2025-04, 2025-10, 2026-04 y 2026-10 coinciden con el PUBLICATION_DATE de sus ficheros "
               "(2026-10: 02:00 UTC, mañana de Bangkok; disponible_utc = la hora medida, más tardía)",
               "Estimación del año en curso y proyecciones en series .PROY.H0-H5 (no se mezclan con los datos)"])
    return guardar_ficha(ficha)


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="FMI WEO por edición (API SDMX del FMI)")
    ap.add_argument("--ediciones", nargs="*", default=[],
                    help="ediciones de DBnomics (no se usa, G3: por defecto ninguna)")
    ap.add_argument("--sin-sdmx", action="store_true", help="no consulta la API SDMX del FMI")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args(argv)
    tabla, informe = tabla_weo(a.ediciones, sdmx=not a.sin_sdmx, forzar=a.forzar)
    meta = org.medir(tabla, frecuencias(tabla))
    print("tabla:", org.guardar_tabla(tabla, FUENTE), len(tabla), "filas")
    print("metadatos:", org.guardar_metadatos(meta, FUENTE))
    print("ficha:", ficha_weo(tabla, informe, meta))


if __name__ == "__main__":
    main()
