"""Bancos centrales del Tema 1 (bloque 4): tipos oficiales y bonos a 10 años de Canadá, Japón,
Alemania y Australia; el Banco de Inglaterra queda documentado como vetado por robots.txt.

- Banco de Canadá (Valet, JSON): ``V39079`` (objetivo del tipo a un día, diario desde 2009-04-21) y
  ``BD.CDN.10YR.DQ.YLD`` (bono a 10 años, diario desde 2001-01-02).
  ``https://www.bankofcanada.ca/valet/observations/<serie>/json``. Historia larga (paso 3b-2): Valet no
  tiene nada diario anterior (medido el 2026-11-20 con ``start_date=1950-01-01``); el objetivo a fin de
  mes desde 1996-01 es ``STATIC_ATABLE_V39079`` (tabla A de Valet, mensual): serie aparte
  ``boc:STATIC_ATABLE_V39079`` (``fecha_referencia`` = día 1 del mes; visible el hábil siguiente al fin
  de mes). El bono a 10 años antes de 2001 no está en Valet (los vectores mensuales de Statistics Canada
  que sirve empiezan en 2005 y el de 10 años, V122543, da 404): limitación (``LIMITACIONES``).
- Banco de Japón (API de stat-search, 2026): ``getDataCode`` con ``db=FM01`` y
  ``code=STRDCLUCON`` (tipo call sin garantía a un día). El IPC de Japón NO está en el BoJ (lo
  publica el MIC): se toma de la OCDE (``oecd:CP.JPN``, con ediciones).
- Bundesbank (API REST SDMX, CSV en alemán: separador ``;`` y coma decimal): curva Svensson a 10
  años (``BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A``). ``'.'`` = sin valor.
- RBA (tablas CSV F1 y F2 diarias): ``FIRMMCRTD`` (cash rate target) y ``FCMYGBAG10D`` (bono a 10).
  Las tablas vigentes empiezan en 2011-01-04 (F1) y 2013-05-20 (F2); la historia anterior sale de los
  ficheros históricos oficiales del RBA (``HISTORICOS``: ``xls-hist/f01dhist.xls``, 1976-2010, y
  ``xls-hist/f02dhist.xls``, 1995-2013, congelados), con el mismo código de serie: se unen en la misma
  serie (gana la tabla vigente en las fechas comunes; el tramo histórico lleva ``NOTA_HISTORICO``).
- Banco de Inglaterra (IADB): ``robots.txt`` prohíbe ``/boeapps/iadb`` y
  ``/boeapps/database/_iadb-FromShowColumns.asp`` (la ruta de descarga CSV): no se descarga ni se
  busca otra ruta; se documenta en la ficha ``boe`` (alternativa: series del Reino Unido en FRED/OCDE).

Publicación (conservadora, publicadores del fragmento): el dato del día D se da por público el hábil
siguiente a las 12:00 locales (``siguiente_habil``) → ``vintage`` ``unico`` (no se revisan),
``metodo_publicacion`` ``calendario``. Un hueco de la fuente (``'.'``, ``null``) se descarta (son
festivos sin dato; no se inventan filas).

Mensuales (``fin_periodo: mes``): la fila del mes M es el valor a fin de mes, visible el hábil
siguiente al último día de M a las 12:00 locales.

CLI: ``python -m ingesta.mercados_series.fuentes.bancos_centrales [--series ...] [--descargar] [--fichas]``
(``--descargar`` baja también los históricos que falten; son ficheros congelados).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from ingesta.comun.http import get, robots_permite
from ingesta.mercados_series.fuentes.b4_comun import TEMA, guardar_crudo, ruta_crudo, tabla_contrato

SERIES: dict[str, dict[str, Any]] = {
    "boc:V39079": {"fuente": "boc", "publicador": "boc_valet", "codigo": "V39079",
                   "url": "https://www.bankofcanada.ca/valet/observations/V39079/json"},
    "boc:BD.CDN.10YR.DQ.YLD": {"fuente": "boc", "publicador": "boc_valet", "codigo": "BD.CDN.10YR.DQ.YLD",
                               "url": "https://www.bankofcanada.ca/valet/observations/BD.CDN.10YR.DQ.YLD/json"},
    # Paso 3b-2: historia del objetivo a fin de mes desde 1996 (la diaria V39079 empieza en 2009-04-21).
    "boc:STATIC_ATABLE_V39079": {"fuente": "boc", "publicador": "boc_valet", "codigo": "STATIC_ATABLE_V39079",
                                 "url": "https://www.bankofcanada.ca/valet/observations/STATIC_ATABLE_V39079/json",
                                 "fin_periodo": "mes"},
    "boj:FM01.STRDCLUCON": {"fuente": "boj", "publicador": "boj_diario", "codigo": "STRDCLUCON",
                            "url": "https://www.stat-search.boj.or.jp/api/v1/getDataCode",
                            "params": {"format": "json", "lang": "en", "db": "FM01", "code": "STRDCLUCON",
                                       "startDate": "198501"}},
    "bbk:BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A": {
        "fuente": "bundesbank", "publicador": "bundesbank_diario",
        "codigo": "BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
        "url": "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
        "params": {"format": "csv", "lang": "de"}},
    "rba:FIRMMCRTD": {"fuente": "rba", "publicador": "rba_diario", "codigo": "FIRMMCRTD",
                      "url": "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"},
    "rba:FCMYGBAG10D": {"fuente": "rba", "publicador": "rba_diario", "codigo": "FCMYGBAG10D",
                        "url": "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"},
}
URL_BOE = "https://www.bankofengland.co.uk/boeapps/database/_iadb-FromShowColumns.asp?csv.x=yes&SeriesCodes=IUDBEDR"
UNIDAD = "% anual"
# Paso 3b-2: ficheros históricos oficiales (congelados) que alargan una serie con el MISMO código.
URL_RBA_HIST = "https://www.rba.gov.au/statistics/tables/xls-hist/{fichero}"
HISTORICOS: dict[str, list[dict[str, str]]] = {
    "rba:FIRMMCRTD": [{"fichero": "f01dhist.xls", "url": URL_RBA_HIST.format(fichero="f01dhist.xls"),
                       "crudo": "rba_hist_f01dhist.xls", "tramo": "1976-2010 (objetivo diario desde 1990-08-02)"}],
    "rba:FCMYGBAG10D": [{"fichero": "f02dhist.xls", "url": URL_RBA_HIST.format(fichero="f02dhist.xls"),
                         "crudo": "rba_hist_f02dhist.xls", "tramo": "1995-2013"}],
}
NOTA_HISTORICO = ("tramo histórico del RBA ({fichero}, fichero congelado de xls-hist): mismo código de serie que la "
                  "tabla vigente; misma regla de publicación (hábil siguiente a las 12:00 de Sídney)")
# Historia larga que no tiene fuente oficial estable y legal (paso 3b-2, medido el 2026-11-20).
LIMITACIONES = {
    "boc:V39079 (diaria antes de 2009-04-21)": (
        "Valet no sirve el objetivo diario antes de 2009-04-21 (ni V39079 ni B114039); se añade el objetivo a fin de "
        "mes desde 1996-01 (boc:STATIC_ATABLE_V39079). Antes de 1996 no había objetivo del tipo a un día (el tipo "
        "oficial era el Bank Rate; el tipo oficial mensual largo ya está en bis:WS_CBPOL.M.CA, desde 1960)"),
    "boc:BD.CDN.10YR.DQ.YLD (antes de 2001-01-02)": (
        "Valet no tiene el bono de referencia a 10 años antes de 2001: los vectores mensuales de Statistics Canada "
        "que sirve (V122538, V122539, V122487) empiezan en 2005 y el de 10 años (V122543) da 404. La fuente sería "
        "la tabla 10-10-0122-01 de Statistics Canada (otro publicador, fuera del alcance de este extractor)"),
}

__all__ = ["SERIES", "URL_BOE", "HISTORICOS", "NOTA_HISTORICO", "LIMITACIONES", "leer_boc", "leer_boj",
           "leer_bundesbank", "leer_rba", "leer_rba_xls", "leer", "unir_historico", "tabla_banco", "tabla_serie",
           "descargar", "descargar_historicos", "estado_boe", "fichas_bancos"]


# --- Lectores (bytes crudos → serie fecha → valor, sin nulos) ------------------------------------
def _serie(fechas: Any, valores: Any) -> pd.Series:
    s = pd.Series(pd.to_numeric(pd.Series(list(valores)), errors="coerce").to_numpy(),
                  index=pd.to_datetime(pd.Series(list(fechas))).to_numpy())
    s = s[~s.index.duplicated(keep="last")].dropna().sort_index()
    s.index.name = "fecha"
    return s


def leer_boc(contenido: bytes, codigo: str) -> pd.Series:
    obs = json.loads(contenido)["observations"]
    return _serie([o["d"] for o in obs], [(o.get(codigo) or {}).get("v") for o in obs])


def leer_boj(contenido: bytes, codigo: str) -> pd.Series:
    doc = json.loads(contenido)
    for rs in doc.get("RESULTSET") or []:
        if rs.get("SERIES_CODE") == codigo:
            v = rs["VALUES"]
            fechas = pd.to_datetime(pd.Series(v["SURVEY_DATES"]).astype(str), format="%Y%m%d")
            return _serie(fechas, v["VALUES"])
    raise ValueError(f"BoJ: serie {codigo} ausente de la respuesta")


def leer_bundesbank(contenido: bytes, codigo: str | None = None) -> pd.Series:
    texto = contenido.decode("utf-8-sig")
    filas = [ln.split(";") for ln in texto.splitlines() if ln[:4].isdigit() and ln[4:5] == "-"]
    fechas = [f[0] for f in filas]
    valores = [f[1].replace(".", "").replace(",", ".") if f[1].strip() not in (".", "") else None for f in filas]
    return _serie(fechas, valores)


def leer_rba(contenido: bytes, codigo: str) -> pd.Series:
    texto = contenido.decode("utf-8-sig", errors="replace")
    lineas = texto.splitlines()
    i = next(k for k, ln in enumerate(lineas) if ln.startswith("Series ID"))
    filas = list(csv.reader(io.StringIO("\n".join(lineas[i:]))))
    col = [c.strip() for c in filas[0]].index(codigo)
    datos = [(f[0], f[col] if col < len(f) else None) for f in filas[1:] if f]
    fechas = pd.to_datetime(pd.Series([d for d, _ in datos]), format="%d-%b-%Y", errors="coerce")
    ok = fechas.notna().to_numpy()
    valores = [v for (_, v), b in zip(datos, ok) if b]
    return _serie(fechas[ok], valores)


def leer_rba_xls(contenido: bytes, codigo: str) -> pd.Series:
    """Fichero histórico del RBA (``xls-hist``, hoja ``Data``): fila ``Series ID``/``Mnemonic`` con los códigos
    y debajo una fila por fecha (fecha en la primera columna)."""
    hoja = pd.read_excel(io.BytesIO(contenido), sheet_name="Data", header=None)
    primera = hoja.iloc[:, 0].astype(str).str.strip()
    filas = hoja.index[primera.isin(["Series ID", "Mnemonic"])]
    if not len(filas):
        raise ValueError("RBA histórico: falta la fila 'Series ID' o 'Mnemonic'")
    cab = [str(c).strip() for c in hoja.iloc[filas[0]]]
    if codigo not in cab:
        raise ValueError(f"RBA histórico: serie {codigo} ausente")
    datos = hoja.iloc[filas[0] + 1:]
    fechas = pd.to_datetime(datos.iloc[:, 0], errors="coerce")
    ok = fechas.notna().to_numpy()
    return _serie(fechas[ok], datos.iloc[:, cab.index(codigo)][ok])


_LECTORES = {"boc": leer_boc, "boj": leer_boj, "bundesbank": leer_bundesbank, "rba": leer_rba}


def leer(sid: str, contenido: bytes) -> pd.Series:
    info = SERIES[sid]
    return _LECTORES[info["fuente"]](contenido, info["codigo"])


def unir_historico(vigente: pd.Series, historicos: list[tuple[str, pd.Series]]) -> tuple[pd.Series, pd.Series]:
    """Une la serie vigente con sus tramos históricos (mismo código): ``(serie, nota)``.

    Del histórico solo entran las fechas anteriores a la primera de la vigente (en las comunes gana la
    vigente y no se mezclan fuentes dentro de un mismo tramo); su nota es ``NOTA_HISTORICO``.
    """
    partes, notas = [vigente], [pd.Series(None, index=vigente.index, dtype=object)]
    inicio = vigente.index.min() if len(vigente) else pd.Timestamp.max
    for fichero, h in historicos:
        h = h[h.index < inicio]
        if len(h):
            partes.append(h)
            notas.append(pd.Series(NOTA_HISTORICO.format(fichero=fichero), index=h.index, dtype=object))
            inicio = min(inicio, h.index.min())
    s = pd.concat(partes).sort_index()
    nota = pd.concat(notas).reindex(s.index)
    s.index.name = "fecha"
    return s, nota


def tabla_banco(sid: str, serie: pd.Series, *, publicaciones: dict[str, Any] | None = None,
                nota: pd.Series | None = None) -> pd.DataFrame:
    """Filas del contrato (vintage ``unico``, ``calendario``) de una serie de banco central.

    Diaria: visible el hábil siguiente a la fecha (publicador). Mensual (``fin_periodo: mes``): la fila
    del mes lleva el día 1 y se da por visible el hábil siguiente al último día del mes.
    """
    info = SERIES[sid]
    ref = pd.DatetimeIndex(serie.index)
    dia = ref
    if info.get("fin_periodo") == "mes":
        ref = ref.to_period("M").to_timestamp()
        dia = ref + pd.offsets.MonthEnd(0)
    return tabla_contrato(sid, ref, dia, serie.to_numpy(), vintage="unico", unidad=UNIDAD,
                          divisa=None, fuente=info["fuente"], metodo="calendario", publicador=info["publicador"],
                          nota=None if nota is None else nota.to_numpy(), publicaciones=publicaciones)


def tabla_serie(sid: str, *, publicaciones: dict[str, Any] | None = None) -> pd.DataFrame | None:
    """Tabla de ``sid`` desde los crudos del corpus (vigente + históricos de ``HISTORICOS``); None sin crudo."""
    info = SERIES[sid]
    ruta = ruta_crudo(info["fuente"]) / _nombre_crudo(sid)
    if not ruta.exists():
        return None
    s = leer(sid, ruta.read_bytes())
    historicos = []
    for h in HISTORICOS.get(sid, []):
        rh = ruta_crudo(info["fuente"]) / h["crudo"]
        if rh.exists():
            historicos.append((h["fichero"], leer_rba_xls(rh.read_bytes(), info["codigo"])))
    s, nota = unir_historico(s, historicos)
    return tabla_banco(sid, s, publicaciones=publicaciones, nota=nota)


def _nombre_crudo(sid: str) -> str:
    return sid.replace(":", "_").replace("/", "_") + (".json" if SERIES[sid]["fuente"] in ("boc", "boj") else ".csv")


def descargar(sids: Iterable[str] = tuple(SERIES)) -> dict[str, dict[str, Any]]:
    """Descarga cada serie (una petición, reintento único si falla) y guarda el crudo en el corpus."""
    informe: dict[str, dict[str, Any]] = {}
    for sid in sids:
        info = SERIES[sid]
        if not robots_permite(info["url"]):
            informe[sid] = {"estado": "vetado_robots", "url": info["url"]}
            continue
        t = time.monotonic()
        try:
            r = get(info["url"], params=info.get("params"), timeout=90, reintentos=2)
        except Exception as e:  # noqa: BLE001 — bloqueo o error: se documenta y se sigue
            informe[sid] = {"estado": "fallo", "error": str(e)[:200], "url": info["url"]}
            continue
        ruta = guardar_crudo(info["fuente"], _nombre_crudo(sid), r.content)
        informe[sid] = {"estado": "ok", "bytes": len(r.content), "segundos": round(time.monotonic() - t, 2),
                        "ruta": str(ruta)}
        if sid in HISTORICOS:
            informe[sid]["historicos"] = descargar_historicos(sid)
    return informe


def descargar_historicos(sid: str, *, forzar: bool = False) -> dict[str, dict[str, Any]]:
    """Baja (una vez) los ficheros históricos congelados de ``sid``; robots.txt antes; no lanza."""
    informe: dict[str, dict[str, Any]] = {}
    fuente = SERIES[sid]["fuente"]
    for h in HISTORICOS.get(sid, []):
        destino = ruta_crudo(fuente) / h["crudo"]
        if destino.exists() and not forzar:
            informe[h["fichero"]] = {"estado": "en_cache", "bytes": destino.stat().st_size}
            continue
        if not robots_permite(h["url"]):
            informe[h["fichero"]] = {"estado": "vetado_robots", "url": h["url"]}
            continue
        try:
            r = get(h["url"], timeout=90, reintentos=2)
        except Exception as e:  # noqa: BLE001 — se documenta y se sigue
            informe[h["fichero"]] = {"estado": "fallo", "error": str(e)[:200], "url": h["url"]}
            continue
        if "html" in r.headers.get("Content-Type", "").lower():
            informe[h["fichero"]] = {"estado": "fallo", "error": "respuesta HTML (no se esquiva)", "url": h["url"]}
            continue
        guardar_crudo(fuente, h["crudo"], r.content)
        informe[h["fichero"]] = {"estado": "ok", "bytes": len(r.content), "url": h["url"]}
    return informe


def estado_boe() -> dict[str, Any]:
    """Comprueba robots.txt del Banco de Inglaterra para la descarga CSV de la IADB (no descarga)."""
    return {"url": URL_BOE, "robots_permite": robots_permite(URL_BOE),
            "robots_permite_iadb": robots_permite("https://www.bankofengland.co.uk/boeapps/iadb/")}


# --- Fichas -------------------------------------------------------------------------------------
_META = {
    "boc": ("Banco de Canadá (Valet)", "https://www.bankofcanada.ca/valet/docs", "json",
            "Términos del Banco de Canadá (https://www.bankofcanada.ca/terms/): uso libre citando la fuente"),
    "boj": ("Banco de Japón (API de stat-search)", "https://www.stat-search.boj.or.jp/info/api_manual_en.pdf", "json",
            "Banco de Japón: uso libre citando la fuente"),
    "bundesbank": ("Deutsche Bundesbank (API de la base estadística)", "https://api.statistiken.bundesbank.de/doc/index.html",
                   "csv", "Deutsche Bundesbank: uso libre citando la fuente"),
    "rba": ("Reserve Bank of Australia (tablas estadísticas)", "https://www.rba.gov.au/statistics/tables/", "csv",
            "RBA: CC BY 4.0"),
}


def fichas_bancos(informe: dict[str, dict] | None = None, *, guardar: bool = True,
                  hoy: Any = None, fuentes: Iterable[str] | None = None) -> dict[str, Any]:
    """Fichas ``boc``, ``boj``, ``bundesbank``, ``rba`` (medidas con los crudos) y ``boe`` (robots).

    ``fuentes``: solo esas fichas (las demás no se reescriben y conservan su registro de descarga).
    """
    from ingesta.comun.esquema import FichaFuente
    from ingesta.comun.fichas import guardar_ficha

    hoy = pd.Timestamp(hoy or pd.Timestamp.now(tz="America/New_York").date())
    rutas: dict[str, Any] = {}
    pedidas = set(fuentes) if fuentes is not None else set(_META) | {"boe"}
    for fuente, (nombre, url, formato, lic) in _META.items():
        if fuente not in pedidas:
            continue
        med: dict[str, Any] = {}
        for sid, info in SERIES.items():
            if info["fuente"] != fuente:
                continue
            ruta = ruta_crudo(fuente) / _nombre_crudo(sid)
            if not ruta.exists():
                med[sid] = {"estado": (informe or {}).get(sid, {}).get("estado", "sin_descargar"),
                            "error": (informe or {}).get(sid, {}).get("error")}
                continue
            s = leer(sid, ruta.read_bytes())
            t = tabla_serie(sid)
            ultimo = s.index.max()
            med[sid] = {"inicio": t["fecha_referencia"].min().date().isoformat(), "fin": ultimo.date().isoformat(),
                        "inicio_tabla_vigente": s.index.min().date().isoformat(),
                        "filas_tramo_historico": int(t["nota"].notna().sum()),
                        "n_obs": int(len(t)), "filas_contrato": int(len(t)), "bytes": ruta.stat().st_size,
                        "dias_naturales_ultimo_dato_a_sonda": int((hoy - ultimo).days),
                        "fecha_publicacion_mediana_menos_fecha_dias": float(
                            (t["fecha_publicacion"] - t["fecha_referencia"]).dt.days.median())}
        ok = [m for m in med.values() if "n_obs" in m]
        ficha = FichaFuente(
            fuente=fuente, nombre=nombre, tema=TEMA, agentes=["macro", "risk"], rag="serie", url=url,
            acceso="api" if fuente != "rba" else "descarga", autenticacion="ninguna", coste="0 €",
            licencia_y_terminos=lic,
            cobertura_inicio=min((m["inicio"] for m in ok), default=None),
            cobertura_fin=max((m["fin"] for m in ok), default=None),
            frecuencia="diaria" + (" (y mensual: STATIC_ATABLE_V39079, objetivo a fin de mes)" if fuente == "boc"
                                   else ""),
            retraso_publicacion=("medido en la sonda: días naturales del último dato a la fecha de la sonda: "
                                 + "; ".join(f"{s.split(':', 1)[1]} {m['dias_naturales_ultimo_dato_a_sonda']}"
                                             for s, m in med.items() if "n_obs" in m)
                                 + ". Regla conservadora: hábil siguiente a las 12:00 locales"),
            formato=formato, volumen_estimado=f"{sum(m.get('bytes', 0) for m in ok) / 1e6:.2f} MB ({len(ok)} series)",
            limites="sin clave; 1 petición/s; reintento único ante error",
            estado_sonda="ok" if ok and len(ok) == len(med) else ("parcial" if ok else "fallo"),
            mediciones={"series": med, "descarga": {k: v for k, v in (informe or {}).items() if k in med}},
            notas=["vintage 'unico': series de mercado/política monetaria sin revisiones",
                   "huecos de la fuente (festivos, '.') descartados: no se inventan filas"]
                  + (["IPC de Japón: no lo publica el BoJ (MIC/e-Stat); se usa oecd:CP.JPN"] if fuente == "boj" else [])
                  + [f"historia anterior a la tabla vigente: {s} con {h['fichero']} ({h['tramo']}), CC BY 4.0"
                     for s, hs in HISTORICOS.items() if SERIES[s]["fuente"] == fuente for h in hs]
                  + [f"limitación {k}: {v}" for k, v in LIMITACIONES.items() if k.startswith(fuente + ":")],
            fecha_sonda=hoy.date().isoformat())
        rutas[fuente] = guardar_ficha(ficha) if guardar else ficha
    if "boe" not in pedidas:
        return rutas
    boe = estado_boe()
    ficha = FichaFuente(
        fuente="boe", nombre="Banco de Inglaterra (Interactive Database, IADB)", tema=TEMA, agentes=["macro", "risk"],
        rag="serie", url="https://www.bankofengland.co.uk/boeapps/database/", acceso="descarga",
        autenticacion="ninguna", coste="0 €", licencia_y_terminos="Banco de Inglaterra: términos de uso del sitio",
        cobertura_inicio=None, cobertura_fin=None, frecuencia="diaria",
        retraso_publicacion="no medido (fuente vetada por robots.txt)", formato="csv",
        volumen_estimado="0 (no descargado)",
        limites=("robots.txt: Disallow /boeapps/iadb y /boeapps/database/_iadb-FromShowColumns.asp (la ruta CSV) "
                 "y ShowChart.asp: no se rastrea ni se buscan rutas alternativas"),
        estado_sonda="fallo", mediciones={"robots": boe},
        notas=["Vetado por robots.txt (comprobado en la sonda); no se esquiva",
               "Alternativas: Bank Rate y gilts del Reino Unido vía FRED (p. ej. IRLTLT01GBM156N, mensual, OCDE) "
               "o la OCDE; decisión del integrador"],
        fecha_sonda=hoy.date().isoformat())
    rutas["boe"] = guardar_ficha(ficha) if guardar else ficha
    return rutas


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--series", nargs="*", default=list(SERIES))
    p.add_argument("--descargar", action="store_true")
    p.add_argument("--fichas", action="store_true")
    a = p.parse_args(argv)
    informe = descargar(a.series) if a.descargar else None
    if informe:
        for k, v in informe.items():
            print(k, v.get("estado"), v.get("bytes"), v.get("error") or "")
    if a.fichas:
        fuentes = sorted({SERIES[s]["fuente"] for s in a.series}) if a.series != list(SERIES) else None
        for k, r in fichas_bancos(informe, fuentes=fuentes).items():
            print(k, r)


if __name__ == "__main__":
    main()
