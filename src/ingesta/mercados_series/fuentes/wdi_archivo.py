"""Vintages del Banco Mundial desde el archivo del WDI (saneado P23).

El cargador del Banco Mundial (``fuentes.worldbank``) solo trae los valores de hoy: vintage «unico» con la fecha de
una regla conservadora y la nota de posible fuga de revisiones. El Banco Mundial guarda cada edición del WDI en su
archivo («WDI Database Archives», fuente 57 de la API v2: 142 ediciones, de 1989-04 a 2026-07, comprobado el
2026-11-21), y la misma API la sirve por edición:
``https://api.worldbank.org/v2/sources/57/country/<ISO3;...>/series/<ind;...>/version/<AAAAMM>/time/all?format=json``.

- ``descargar``: una petición por edición con los países de ``PAISES`` (los de las series del Banco Mundial de la
  lista curada) y los tres indicadores del cargador; crudo en ``crudo/worldbank/archivo_wdi/<AAAAMM>.json`` con su
  ``.meta.json``. Reanudable (una edición ya guardada no se vuelve a pedir), 1 petición/s, robots.txt consultado.
- ``tabla_archivo``: por serie, estilo ALFRED: cada edición aporta solo los años nuevos o con otro valor (y una fila
  nula si deja de dar un año). ``vintage`` = ``fecha_publicacion`` = el primer día del mes siguiente al de la
  edición (la edición sale dentro de su mes: fecha prudente, igual o posterior a la publicación real). La descarga de
  hoy (la tabla del cargador) cuenta como la última edición, con el día de su descarga.

Así el valor de cada año en cada fecha es el que daba la edición vigente entonces: sin fuga de revisiones. Las
series con archivo salen del solo-añadir (``base.construir_base``: traen toda su historia, como la OCDE).
CLI: ``python -m ingesta.mercados_series.fuentes.wdi_archivo [--max N]``.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingesta.comun import http
from ingesta.mercados_series import catalogo as cat_mod
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, vacio_series
from ingesta.mercados_series.fuentes import _organismos as org
from ingesta.mercados_series.fuentes import worldbank as wb

FUENTE = wb.FUENTE
FUENTE_API = "57"
URL_VERSIONES = "https://api.worldbank.org/v2/sources/57/version"
URL_EDICION = "https://api.worldbank.org/v2/sources/57/country/{paises}/series/{series}/version/{version}/time/all"
CARPETA = "archivo_wdi"
# Países y agregados de las series del Banco Mundial que quedan en la lista curada (saneado P23/P24).
PAISES = ("CAN", "CHN", "DEU", "EMU", "FRA", "GBR", "ITA", "JPN", "LMY", "USA", "WLD")
INDICADORES = tuple(wb.INDICADORES)
NOTA_EDICION = "WDI, edición archivada {v} (vintage = primer día del mes siguiente: fecha prudente)"
NOTA_HOY = "WDI, descarga del {d} (última edición)"
NOTA_RETIRADA = "la edición {v} del WDI ya no da este año"
TOLERANCIA = 1e-9

__all__ = ["PAISES", "INDICADORES", "versiones", "descargar", "ediciones_archivadas", "tabla_archivo",
           "aplicar_archivo", "fecha_version"]


def _carpeta(raiz: Path | None = None) -> Path:
    p = org.ruta_crudo(FUENTE, raiz) / CARPETA
    p.mkdir(parents=True, exist_ok=True)
    return p


def fecha_version(version: str) -> pd.Timestamp:
    """``AAAAMM`` → primer día del mes siguiente (fecha prudente de la edición)."""
    return (pd.Timestamp(f"{version[:4]}-{version[4:6]}-01") + pd.offsets.MonthBegin(1)).normalize()


def versiones() -> list[str]:
    """Ediciones del archivo (``AAAAMM``), de la API."""
    r = http.get(URL_VERSIONES, params={"format": "json", "per_page": 1000}, timeout=120)
    var = r.json()["source"][0]["concept"][0]["variable"]
    return sorted(str(v["id"]) for v in var if str(v["id"]).isdigit() and len(str(v["id"])) == 6)


def descargar(*, maximo: int | None = None, raiz: Path | None = None, registro=print) -> pd.DataFrame:
    """Baja las ediciones que faltan (una petición por edición, todos los países e indicadores)."""
    url0 = URL_EDICION.format(paises="CAN", series=INDICADORES[0], version="202607")
    if not http.robots_permite(url0):
        raise PermissionError("robots.txt de api.worldbank.org no permite el archivo del WDI")
    carpeta = _carpeta(raiz)
    filas, nuevas = [], 0
    for v in versiones():
        ruta = carpeta / f"{v}.json"
        if ruta.exists() and ruta.with_name(ruta.name + ".meta.json").exists():
            filas.append({"version": v, "accion": "ya_estaba"})
            continue
        if maximo is not None and nuevas >= maximo:
            filas.append({"version": v, "accion": "pendiente"})
            continue
        nuevas += 1
        url = URL_EDICION.format(paises=";".join(PAISES), series=";".join(INDICADORES), version=v)
        meta: dict[str, Any] = {"fuente": FUENTE, "fuente_api": FUENTE_API, "version": v, "url": url,
                                "descargado_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
        try:
            r = http.get(url, params={"format": "json", "per_page": 20000}, timeout=180, reintentos=3)
            j = r.json()
            if int(j.get("pages", 1)) > 1:
                raise ValueError("respuesta paginada: sube per_page")
            ruta.write_bytes(r.content)
            meta |= {"estado": r.status_code, "bytes": len(r.content), "total": j.get("total"),
                     "lastupdated": j.get("lastupdated")}
            filas.append({"version": v, "accion": "guardada", "filas": j.get("total")})
            registro(f"  WDI {v}: {j.get('total')} filas")
        except Exception as e:  # noqa: BLE001 - se documenta y se sigue (reanudable)
            meta["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            filas.append({"version": v, "accion": "error", "error": meta["error"]})
            registro(f"  WDI {v}: error {meta['error']}")
            continue
        ruta.with_name(ruta.name + ".meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                                           encoding="utf-8")
    return pd.DataFrame(filas)


def _leer(ruta: Path) -> pd.DataFrame:
    """``iso3, indicador, anio, valor`` de una edición archivada (sin valores nulos)."""
    j = json.loads(Path(ruta).read_text(encoding="utf-8"))
    filas = []
    for d in (j.get("source") or {}).get("data") or []:
        var = {x["concept"]: x["id"] for x in d["variable"]}
        if d.get("value") is None:
            continue
        anio = str(var.get("Time", ""))[2:]
        if anio.isdigit():
            filas.append((var.get("Country"), var.get("Series"), int(anio), float(d["value"])))
    return pd.DataFrame(filas, columns=["iso3", "indicador", "anio", "valor"])


def ediciones_archivadas(raiz: Path | None = None) -> list[tuple[str, Path]]:
    """``[(AAAAMM, ruta)]`` de las ediciones guardadas, en orden."""
    carpeta = org.ruta_crudo(FUENTE, raiz) / CARPETA
    if not carpeta.exists():
        return []
    return sorted((p.stem, p) for p in carpeta.glob("[0-9]" * 6 + ".json"))


def tabla_archivo(ids: Iterable[str], hoy: pd.DataFrame | None = None, *, dia_hoy: Any = None,
                  catalogo: dict[str, dict] | None = None, raiz: Path | None = None) -> pd.DataFrame:
    """Filas del contrato (vintage con fecha) de las series ``ids`` (``wb:<ISO3>.<indicador>``) desde el archivo.

    ``hoy``: tabla del cargador del Banco Mundial (valores de hoy) que cuenta como última edición, fechada el
    ``dia_hoy``. Las series sin ninguna edición archivada no salen.
    """
    cat = catalogo if catalogo is not None else cat_mod.cargar_catalogo()
    eds = ediciones_archivadas(raiz)
    if not eds:
        return vacio_series()
    por_ed = []
    for v, ruta in eds:
        d = _leer(ruta)
        d["serie"] = "wb:" + d["iso3"].astype(str) + "." + d["indicador"].astype(str)
        por_ed.append((fecha_version(v), NOTA_EDICION.format(v=v), NOTA_RETIRADA.format(v=v), d))
    if hoy is not None and len(hoy) and dia_hoy is not None:
        h = hoy[hoy["valor"].notna()]
        d = pd.DataFrame({"serie": h["serie"].to_numpy(), "anio": h["fecha_referencia"].dt.year.to_numpy(),
                          "valor": h["valor"].to_numpy(float)})
        dh = pd.Timestamp(dia_hoy).normalize()
        por_ed.append((dh, NOTA_HOY.format(d=dh.date().isoformat()), f"la descarga del {dh.date()} ya no da este año",
                       d))
    por_ed.sort(key=lambda x: x[0])
    trozos = []
    for sid in sorted(set(ids)):
        e = cat.get(sid)
        if e is None:
            continue
        previo: dict[int, float] = {}
        filas = []
        for fecha, nota, nota_ret, d in por_ed:
            s = d[d["serie"] == sid]
            actual = dict(zip(s["anio"].astype(int), s["valor"].astype(float), strict=True))
            if not actual:   # la edición no trae la serie (agregado que aún no existía): no retira nada
                continue
            for anio, valor in actual.items():
                ref = pd.Timestamp(f"{anio}-01-01")
                if ref > fecha:
                    continue
                if anio not in previo or not np.isclose(previo[anio], valor, rtol=0, atol=TOLERANCIA):
                    filas.append((ref, fecha, valor, nota))
            for anio in set(previo) - set(actual):
                filas.append((pd.Timestamp(f"{anio}-01-01"), fecha, np.nan, nota_ret))
            if actual:
                previo = actual
        if not filas:
            continue
        f = pd.DataFrame(filas, columns=["ref", "pub", "valor", "nota"]).drop_duplicates(["ref", "pub"], keep="last")
        trozos.append(org.filas(sid, f["ref"].to_numpy(), f["pub"].to_numpy(), f["valor"].to_numpy(float),
                                vintage=f["pub"].dt.strftime("%Y-%m-%d").to_numpy(), unidad=e["unidad"],
                                divisa=e["divisa"], fuente=FUENTE, metodo=e["metodo"], nota=f["nota"].to_numpy()))
    return org.unir(trozos) if trozos else vacio_series()


def aplicar_archivo(tabla: pd.DataFrame, *, dia_hoy: Any = None, raiz: Path | None = None) -> tuple[pd.DataFrame, int]:
    """La tabla del cargador del Banco Mundial con las series de ``PAISES`` sustituidas por las del archivo del WDI.

    ``dia_hoy``: día de la descarga de ``tabla`` (por defecto, la fecha de modificación del parquet del bloque 4 la
    da quien llama). Devuelve ``(tabla, series sustituidas)``; sin archivo, la tabla tal cual.
    """
    ids = sorted({s for s in tabla["serie"].unique() if str(s).split(":", 1)[-1].split(".", 1)[0] in PAISES})
    if not ids or not ediciones_archivadas(raiz):
        return tabla, 0
    hoy = tabla[tabla["serie"].isin(ids)]
    arch = tabla_archivo(ids, hoy, dia_hoy=dia_hoy, raiz=raiz)
    if arch.empty:
        return tabla, 0
    sust = set(arch["serie"])
    out = pd.concat([tabla[~tabla["serie"].isin(sust)], arch], ignore_index=True)[list(COLUMNAS_SERIES)]
    return out, len(sust)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingesta.mercados_series.fuentes.wdi_archivo",
                                 description="Ediciones archivadas del WDI (Banco Mundial) para las series curadas.")
    ap.add_argument("--max", type=int, default=None, help="tope de ediciones nuevas en esta tanda")
    a = ap.parse_args(argv)
    rep = descargar(maximo=a.max)
    print(rep["accion"].value_counts().to_string())
    return 1 if (rep["accion"] == "error").any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
