"""Ediciones antiguas de los ficheros académicos desde la Wayback Machine (saneado P15).

Ken French, Shiller y la OFR FSI no tienen historia de ediciones propia antes de nuestro archivo (2026-10-12):
la base llevaba el valor de hoy con la fecha de la regla («posible fuga de revisiones»). La Wayback Machine
(web.archive.org) guarda capturas antiguas de esos mismos ficheros. Esta orden las recupera y las deja en el
archivo de ediciones del crudo, con la FECHA DE CAPTURA como fecha de la edición:

- índice CDX (``https://web.archive.org/cdx/search/cdx``, ``collapse=digest``: una fila por contenido distinto,
  solo estado 200) de cada URL original (``OBJETIVOS``: la URL vigente y las antiguas, p. ej. la de Yale de
  Shiller hasta 2023);
- cada captura se baja tal cual (``/web/<timestamp>id_/<url>``: los bytes originales, sin la barra de la
  Wayback), se comprueba con el SHA-1 del índice y se guarda en
  ``crudo/<fuente>/ediciones/<AAAA-MM>/<AAAAMMDD>_<fichero>`` (día y mes de la captura en Nueva York) con su
  ``.meta.json`` (``origen: wayback``, ``descargado_utc`` = instante de la captura, URL original, timestamp y
  digest). No se guarda ``Last-Modified``: la fecha de la edición es la de la captura, igual o posterior a la
  publicación real (prudente). Las cabeceras originales que da la Wayback van aparte (``cabeceras_wayback``).

``fuentes.academicos.ediciones`` lee esos ficheros como cualquier otra edición archivada; ``_tabla_ediciones``
guarda solo los valores nuevos o que cambian respecto a la edición anterior (estilo ALFRED), fechados con la
captura. Una captura que no se puede leer (formato antiguo, columna que no existía) se salta en la carga.

Reanudable (una captura ya guardada no se vuelve a pedir), ≤ 1 petición por segundo a web.archive.org con
``ingesta.comun.http`` (User-Agent identificable, robots.txt consultado) y un registro por captura en
``<corpus>/mercados_series/logs/wayback.csv`` (solo metadatos). CLI:
``python -m ingesta.mercados_series.fuentes.wayback [--fuentes ken_french shiller ofr_fsi] [--max N] [--indice]``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from ingesta.comun import http
from ingesta.mercados_series import almacen
from ingesta.mercados_series.contrato import HUSO_DECISION
from ingesta.mercados_series.fuentes import academicos

TEMA = "mercados_series"
CDX = "https://web.archive.org/cdx/search/cdx"
RAW = "https://web.archive.org/web/{ts}id_/{url}"
POR_SEGUNDO = 0.5            # peticiones por segundo a web.archive.org (≤ 1, con margen)
PAUSA_ERROR = 20.0           # segundos tras un error de la Wayback antes de seguir
FUENTES = ("ken_french", "shiller", "ofr_fsi")
ORIGEN = "wayback"
LOG = "wayback.csv"

# fuente -> clave del fichero -> URLs originales (sin esquema) que la Wayback indexa. La primera es la vigente.
OBJETIVOS: dict[str, dict[str, tuple[str, ...]]] = {
    "ken_french": {c: (academicos.FICHEROS["ken_french"][c][1].split("://", 1)[1],)
                   for c in academicos.FICHEROS["ken_french"]},
    "shiller": {"ie_data.xls": (academicos.URL_SHILLER.split("://", 1)[1],
                                "www.econ.yale.edu/~shiller/data/ie_data.xls")},
    "ofr_fsi": {"fsi.csv": (academicos.URL_OFR.split("://", 1)[1],)},
}

__all__ = ["OBJETIVOS", "FUENTES", "ORIGEN", "indice", "descargar", "capturas_archivadas", "main"]


def _sha1_b32(contenido: bytes) -> str:
    """Digest de la Wayback: SHA-1 en base 32."""
    return base64.b32encode(hashlib.sha1(contenido).digest()).decode("ascii")


def indice(url: str) -> list[dict[str, str]]:
    """Capturas con contenido distinto (estado 200) de ``url`` en la Wayback: timestamp, original, digest, mimetype."""
    if not http.robots_permite(CDX):
        raise PermissionError("robots.txt de web.archive.org no permite el índice CDX")
    r = http.get(CDX, params={"url": url, "output": "json", "fl": "timestamp,original,digest,statuscode,mimetype",
                              "filter": "statuscode:200", "collapse": "digest"},
                 por_segundo=POR_SEGUNDO, timeout=120, reintentos=4)
    filas = r.json() if r.text.strip() else []
    if not filas:
        return []
    cab = filas[0]
    return [dict(zip(cab, f, strict=True)) for f in filas[1:]]


def _instante(ts: str) -> pd.Timestamp:
    return pd.Timestamp(pd.to_datetime(ts, format="%Y%m%d%H%M%S")).tz_localize("UTC")


def _destino(fuente: str, clave: str, ts: str, raiz: Path | None = None) -> Path:
    nombre = academicos.FICHEROS[fuente][clave][0]
    local = _instante(ts).tz_convert(HUSO_DECISION)
    return (academicos.ruta_crudo(fuente, raiz) / academicos.CARPETA_EDICIONES / local.strftime("%Y-%m")
            / f"{local.strftime('%Y%m%d')}_{nombre}")


def capturas_archivadas(fuente: str, raiz: Path | None = None) -> list[dict[str, Any]]:
    """Metas de las capturas de la Wayback ya guardadas de ``fuente`` (solo metadatos)."""
    carpeta = academicos.ruta_crudo(fuente, raiz) / academicos.CARPETA_EDICIONES
    out = []
    for m in sorted(carpeta.glob("*/*.meta.json")):
        meta = json.loads(m.read_text(encoding="utf-8"))
        if meta.get("origen") == ORIGEN:
            out.append(meta)
    return out


def _registrar(filas: list[dict[str, Any]]) -> Path | None:
    if not filas:
        return None
    carpeta = almacen.corpus_dir(TEMA) / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / LOG
    pd.DataFrame(filas).to_csv(ruta, mode="a", header=not ruta.exists(), index=False, encoding="utf-8")
    return ruta


def descargar(fuentes: Iterable[str] = FUENTES, *, raiz: Path | None = None, maximo: int | None = None,
              registro=print) -> pd.DataFrame:
    """Baja las capturas que faltan de ``fuentes`` al archivo de ediciones del crudo. Devuelve una fila por captura.

    ``accion``: ``guardada`` | ``ya_estaba`` | ``mismo_contenido`` (el sha256 ya está archivado) |
    ``mismo_dia`` (otra captura distinta el mismo día: se queda la primera) | ``pendiente`` | ``error``.
    ``maximo``: tope de descargas nuevas en esta tanda (reanudable).
    """
    filas: list[dict[str, Any]] = []
    nuevas = 0
    for fuente in fuentes:
        if fuente not in OBJETIVOS:
            raise ValueError(f"fuente {fuente!r} sin objetivos en la Wayback ({list(OBJETIVOS)})")
        for clave, urls in OBJETIVOS[fuente].items():
            shas = {hashlib.sha256(p.read_bytes()).hexdigest() for p, _ in academicos.crudos(fuente, clave, raiz)}
            capturas = []
            for url in urls:
                try:
                    capturas += indice(url)
                except Exception as e:  # noqa: BLE001 - se registra y se sigue con la siguiente URL
                    registro(f"  {fuente}/{clave}: índice de {url} falló: {type(e).__name__}: {str(e)[:200]}")
                    time.sleep(PAUSA_ERROR)
            capturas.sort(key=lambda c: c["timestamp"])
            registro(f"{fuente}/{clave}: {len(capturas)} capturas distintas en el índice")
            for c in capturas:
                ts, original = c["timestamp"], c["original"]
                ruta = _destino(fuente, clave, ts, raiz)
                fila = {"fuente": fuente, "clave": clave, "timestamp": ts, "original": original,
                        "digest": c.get("digest"), "fichero": f"{ruta.parent.name}/{ruta.name}"}
                ruta_meta = ruta.with_name(ruta.name + ".meta.json")
                if ruta.exists() and ruta_meta.exists():
                    previa = json.loads(ruta_meta.read_text(encoding="utf-8")).get("timestamp")
                    filas.append({**fila, "accion": "ya_estaba" if previa == ts else "mismo_dia"})
                    continue
                if maximo is not None and nuevas >= maximo:
                    filas.append({**fila, "accion": "pendiente"})
                    continue
                url_raw = RAW.format(ts=ts, url=original)
                nuevas += 1
                try:
                    r = http.get(url_raw, por_segundo=POR_SEGUNDO, timeout=180, reintentos=4)
                except Exception as e:  # noqa: BLE001
                    filas.append({**fila, "accion": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"})
                    registro(f"  error {ts}: {type(e).__name__}")
                    time.sleep(PAUSA_ERROR)
                    continue
                contenido = r.content
                tipo = r.headers.get("Content-Type", "")
                if not contenido or "html" in tipo.lower():
                    filas.append({**fila, "accion": "error", "error": f"respuesta vacía o HTML ({tipo})"})
                    continue
                if c.get("digest") and _sha1_b32(contenido) != c["digest"]:
                    filas.append({**fila, "accion": "error", "error": "SHA-1 distinto del índice CDX"})
                    continue
                sha = hashlib.sha256(contenido).hexdigest()
                if sha in shas:
                    filas.append({**fila, "accion": "mismo_contenido"})
                    continue
                meta = {
                    "fuente": fuente, "clave": clave, "origen": ORIGEN, "url": f"https://{original.split('://')[-1]}",
                    "url_wayback": url_raw, "timestamp": ts, "digest_sha1": c.get("digest"),
                    "mimetype": c.get("mimetype"), "descargado_utc": _instante(ts).isoformat(),
                    "obtenido_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "estado": r.status_code,
                    "bytes": len(contenido), "sha256": sha,
                    "cabeceras_wayback": {k: v for k, v in r.headers.items()
                                          if k.lower().startswith("x-archive-orig-") or k == "Content-Type"},
                    "nota": ("captura de la Wayback Machine: fecha de la edición = instante de la captura (igual o "
                             "posterior a la publicación real); sin Last-Modified a propósito"),
                }
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(contenido)
                ruta_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                shas.add(sha)
                filas.append({**fila, "accion": "guardada", "bytes": len(contenido)})
                registro(f"  {fuente}/{clave} {ts}: guardada ({len(contenido)} bytes)")
    out = pd.DataFrame(filas)
    _registrar([{**f, "registrado_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")} for f in filas
                if f.get("accion") in ("guardada", "error")])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingesta.mercados_series.fuentes.wayback",
                                 description="Ediciones antiguas de Ken French, Shiller y la OFR desde la Wayback.")
    ap.add_argument("--fuentes", nargs="*", default=list(FUENTES))
    ap.add_argument("--max", type=int, default=None, help="tope de descargas nuevas en esta tanda")
    ap.add_argument("--indice", action="store_true", help="solo cuenta las capturas del índice (sin bajar nada)")
    a = ap.parse_args(argv)
    if a.indice:
        for f in a.fuentes:
            for clave, urls in OBJETIVOS[f].items():
                n = sum(len(indice(u)) for u in urls)
                print(f"{f}/{clave}: {n} capturas distintas")
        return 0
    rep = descargar(a.fuentes, maximo=a.max)
    if len(rep):
        print(rep.groupby(["fuente", "accion"]).size().to_string())
    return 1 if len(rep) and (rep["accion"] == "error").any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
