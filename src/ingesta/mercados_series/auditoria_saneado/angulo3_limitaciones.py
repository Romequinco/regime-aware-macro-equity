"""Auditoría ángulo 3 · las limitaciones declaradas de descargas_3b_estado.csv, una por una y por grupo.

SOLO LECTURA del repo. Escribe angulo3_limitaciones.csv y a3_cifras_limitaciones.json en la carpeta del script.
Uso: python angulo3_limitaciones.py
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
REPO = _REPO
TAB = REPO / "results/ingesta/mercados_series/tablas"
OUT = Path(__file__).resolve().parent
C: dict = {}

est = pd.read_csv(TAB / "descargas_3b_estado.csv", dtype=str)
C["estado_3b"] = est["estado_3b"].value_counts().to_dict()
C["filas_estado"] = len(est)
print("estado del 3b:", C["estado_3b"], "| filas:", len(est))
lim = est[est["estado_3b"] == "limitacion_declarada"].copy()
C["limitaciones"] = len(lim)
C["limitaciones_ids_unicos"] = int(lim["id"].nunique())
C["limitaciones_ids_repetidos"] = lim["id"].value_counts()[lambda s: s > 1].to_dict()
print("limitaciones:", len(lim), "| ids únicos:", C["limitaciones_ids_unicos"], "| repetidos:", C["limitaciones_ids_repetidos"])
print("no hechas y no limitación:", est.loc[~est["estado_3b"].isin(["hecho", "limitacion_declarada"]),
                                            ["id", "estado_3b"]].to_dict("records"))

YAHOO_REVISA = "Yahoo revisa una sesión ya guardada"
SP_IDS = {"AVB", "BLY", "EA", "EQR", "LEG", "PSKY", "QRVO", "WBD", "DWD", "GR", "GP", "LU", "KVUE", "PARA",
          "sp500:tickers_reutilizados", "supervivencia:salidos_sin_precio", "supervivencia:sp500_quiebras_q"}

GRUPOS = {
    "WEO_ediciones": ("Ediciones antiguas del WEO (2008-04 a 2024-10)",
                      "idea: copias del fichero WEO de cada edición en la Wayback Machine (web.archive.org de "
                      "imf.org/external/pubs/ft/weo/AAAA/NN/weodata) o réplicas académicas de los vintages del WEO; "
                      "gratis, con red; legalidad a verificar (robots de imf.org 403)"),
    "sospechosas": ("Tickers sospechosos (historial roto: saltos sin split, cierres repetidos, aperturas de relleno)",
                    "idea: contrastar con Stooq (gratis, diario, algunos deslistados) o el plan gratuito de Tiingo "
                    "(permaticker); el identificador permanente (PERMNO) solo en CRSP/WRDS (de pago o vía universidad)"),
    "sp500_supervivencia": ("S&P 500: tickers reutilizados, deslistados, adquiridos y salidos sin precio "
                            "(sesgo de supervivencia)",
                            "idea: CIK de SEC EDGAR (gratis) para la identidad; precios de deslistados en Tiingo "
                            "(gratis con límites) o Stooq; CRSP vía WRDS si la universidad da acceso; sin eso, sin remedio"),
    "yahoo_revisa": ("Yahoo revisa o no completa sesiones ya guardadas (no se refresca)",
                     "idea: repetir el refresco más tarde (gratis, con red) o aceptar la revisión con registro; "
                     "remedio barato"),
    "yf_fase1": ("Índices y futuros yf: de la Fase 1 sin extender (^BCOM, ^W5000, GC=F)",
                 "idea: otro símbolo en Yahoo (p. ej. ^FTW5000 para el Wilshire, futuro de oro por vencimiento) "
                 "o Stooq; gratis, con red; ^BCOM probablemente sin fuente gratuita"),
    "universo_ucits": ("Universo/UCITS: sin precio o con historia recortada",
                       "idea: históricos de NAV/precio del emisor (iShares, Xtrackers, Amundi publican CSV gratis) y "
                       "VSTOXX en la web de STOXX (CSV gratis); con red"),
    "aperturas": ("Precios de apertura solo de Yahoo",
                  "idea: contrastar aperturas con Stooq (gratis) en una muestra; sin fuente oficial gratuita"),
    "no_publicadas": ("Series que la fuente no publica (zona euro cambiante de Eurostat, CLI EA20, paro de China)",
                      "idea: ESI de la zona euro en DG ECFIN (gratis); paro de China (encuesta urbana) de la NBS desde "
                      "2018; CLI zona euro: sin fuente, ya hay sustituto G4E; en parte sin remedio"),
    "philly_por_diseno": ("Philadelphia: sin filas por diseño (ALFRED ya lo cubre)",
                          "no hace falta remedio: no es una pérdida de información"),
    "bundesbank": ("Bundesbank: reto anti-bots, refresco parado en 2026-10-13",
                   "idea: API SDMX del Bundesbank (api.statistiken.bundesbank.de) o el 10 años alemán del BCE/FRED "
                   "(IRLTLT01DEM156N, mensual); gratis, con red"),
    "vintages": ("Vintages de BCE, Eurostat, BIS y Banco Mundial (historia de revisiones)",
                 "idea: Real-Time Database del EABCN/BCE para la zona euro (gratis con registro); ediciones del WDI "
                 "archivadas por el Banco Mundial; parcial"),
    "calendarios": ("Calendarios de Eurostat sin verificar (paro antes de 2012, PIB antes de 2003)",
                    "idea: archivo de notas de prensa «euro indicators» de Eurostat y la Wayback Machine (gratis)"),
    "constituyentes": ("Constituyentes: Nikkei 225 e Ibovespa sin fuente; S&P 500 posterior al 2026-08-18",
                       "idea: notas de prensa de S&P DJI y la tabla de cambios de Wikipedia (gratis) para el S&P; "
                       "Nikkei e Ibovespa: avisos de cambios en sus webs (gratis, a mano)"),
}


def grupo(r) -> str:
    t, i = r["tipo"], r["id"]
    m = str(r["motivo_3b"])
    if t == "ediciones":
        return "WEO_ediciones"
    if t == "serie_sospechosa":
        return "sospechosas"
    if i in SP_IDS:
        return "sp500_supervivencia"
    if t == "excepcion_refresco" and (YAHOO_REVISA in m or i == "SNDK"):
        return "yahoo_revisa"
    if t == "excepcion_refresco" and i.startswith("yf:"):
        return "yf_fase1"
    if i in {"yf:AIGA.L", "yf:^V2TX", "precios:universo:historia_recortada"}:
        return "universo_ucits"
    if i == "precios:aperturas":
        return "aperturas"
    if i.startswith("philly:"):
        return "philly_por_diseno"
    if t == "series":
        return "no_publicadas"
    if t == "refresco" and r["fuente"] == "bundesbank":
        return "bundesbank"
    if t == "vintages":
        return "vintages"
    if t == "fechas":
        return "calendarios"
    if t == "constituyentes":
        return "constituyentes"
    return "otro"


lim["grupo"] = lim.apply(grupo, axis=1)


def corto(s: str, n: int = 170) -> str:
    s = str(s).split(" · ")[-1].replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


lim["motivo_resumido"] = lim["motivo_3b"].map(corto)
lim["grupo_titulo"] = lim["grupo"].map(lambda g: GRUPOS.get(g, (g, ""))[0])
lim["sin_remedio_gratis"] = lim["grupo"].map({"WEO_ediciones": "probable (a verificar)", "sospechosas": "parcial",
                                              "sp500_supervivencia": "parcial", "yahoo_revisa": "tiene remedio",
                                              "yf_fase1": "parcial", "universo_ucits": "tiene remedio",
                                              "aperturas": "parcial", "no_publicadas": "parcial",
                                              "philly_por_diseno": "no aplica", "bundesbank": "tiene remedio",
                                              "vintages": "parcial", "calendarios": "tiene remedio",
                                              "constituyentes": "tiene remedio (S&P) / sin remedio (Nikkei, Ibovespa)"})
salida = lim[["id", "tipo", "fuente", "motivo_resumido", "grupo", "grupo_titulo", "sin_remedio_gratis"]]
salida.to_csv(OUT / "angulo3_limitaciones.csv", index=False, encoding="utf-8")
assert len(salida) == 124 and (salida["grupo"] != "otro").all(), salida[salida["grupo"] == "otro"]
cnt = salida.groupby("grupo").agg(filas=("id", "size"), ids=("id", "nunique")).sort_values("filas", ascending=False)
print("por grupo:\n", cnt.to_string())
C["por_grupo"] = {g: {"filas": int(r["filas"]), "ids": int(r["ids"]), "titulo": GRUPOS[g][0], "idea": GRUPOS[g][1]}
                  for g, r in cnt.iterrows()}
C["por_tipo"] = lim["tipo"].value_counts().to_dict()
# filas del S&P que son realmente el mismo ticker contado varias veces
C["sp500_ids"] = sorted(lim.loc[lim["grupo"] == "sp500_supervivencia", "id"].unique().tolist())
# el aplazado y el parcial
C["aplazado"] = est.loc[est["estado_3b"] == "aplazado", ["id", "motivo_3b"]].to_dict("records")
C["parcial"] = est.loc[est["estado_3b"] == "parcial", ["id", "motivo_3b"]].to_dict("records")
C["resuelto"] = est.loc[est["estado_3b"] == "resuelto", ["id"]]["id"].tolist()
print("aplazado:", C["aplazado"])
print("parcial:", C["parcial"])
json.dump(C, open(OUT / "a3_cifras_limitaciones.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok: angulo3_limitaciones.csv y a3_cifras_limitaciones.json")
