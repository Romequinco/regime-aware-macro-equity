"""Saneado de los precios curados del Tema 1 (2026-11-21): reglas que ``curada_precios`` aplica tras el EDA.

Todas son reproducibles (código + ``config/lista_curada.yaml``), no tocan ``precios/`` y respetan el TimeGate:
ningún valor corregido usa un dato posterior y ninguna ``fecha_publicacion``/``disponible_utc`` se adelanta.

- **P21 · mercado corregido** (``MERCADO_CORREGIDO``): ^W5000 llega de Yahoo con el mercado de Londres (metadato
  de Yahoo); es un índice de EE. UU. y se le pone ``XNYS``. ``corregir_mercado`` recalcula ``disponible_utc`` con el
  cierre de Nueva York y se queda con el MÁS TARDÍO de los dos (nunca adelanta) y su ``fecha_publicacion``. El
  calendario del EDA (velas de relleno y huecos) pasa a ser el de la NYSE.
- **P11 · saltos de más del 50 % sin split** (``clasificar_saltos``): los de ``eda.saltos_sin_split`` (sin split ni
  dividendo esa sesión ni la siguiente) con ``|cierre / cierre previo − 1| > 50 %`` (``MIN_CAMBIO``: razón > 1,5 o
  < 0,5, o a menos de ``TOLERANCIA_RATIO`` de un split limpio; el resto de los del EDA, entre −33 % y −50 %, no se
  tocan). Cada salto se clasifica con una regla explícita:

  a. ``pico``: **pico aislado** que revierte en 1–``VENTANA_PICO`` sesiones (todas las sesiones del pico lejos del
     nivel previo, en el mismo sentido, y la de vuelta a menos de ``min(TOLERANCIA_REVERSION, FRACCION_REVERSION ·
     |salto|)`` en log del cierre previo; sin dividendo ni split en la ventana) → error del proveedor: las sesiones
     del pico pasan a la **vela plana del cierre anterior** (``close`` = último cierre bueno; ``open``, ``high`` y
     ``low`` nulos, como toda vela plana en la curada: no es una apertura ejecutable; volumen tal cual).
  b. ``split``: **cambio de nivel persistente** (las ``VENTANA_CONFIRMACION`` sesiones siguientes se quedan a menos
     de la mitad del salto del nuevo nivel) con una razón ``cierre previo / cierre`` a menos de ``TOLERANCIA_RATIO``
     (log) de un split limpio (``RATIOS_LIMPIOS`` y sus inversas: 2, 3, 4, 5, 10, 20, 25, 50, 100), sin ningún
     split registrado a ``VENTANA_CONFIRMACION`` sesiones y, si hay volumen a los dos lados, con el volumen mediano
     de las ``VENTANA_VOLUMEN`` sesiones siguientes frente a las anteriores a menos de x/÷``TOLERANCIA_VOLUMEN`` del
     factor (un split multiplica las acciones; un rally como el de GME del 2021-02-24 no) → acción corporativa no
     registrada (bonus indio, agrupación, cambio de unidad): **se mantiene el precio** y se registra el factor en la
     columna ``split`` de esa sesión (las rentabilidades ajustadas salen bien). Límite declarado: una caída real de
     justo la mitad o un tercio con mucho volumen (RBS en enero de 2009) no se distingue de un split con precio y
     volumen solos; esos casos quedan en el registro para revisarlos a mano.
  c. ``real``: lo demás (quiebra, OPA, crisis, o sin sesiones para confirmar) → **se mantiene**.

  Solo en las clases con acciones corporativas (``CLASES_P11``: acción, ETF, ETP, fondo, otro y sin clase): en
  índices, volatilidad, tipos (^IRX), divisas y futuros todos los saltos son ``real`` (un pico de la volatilidad que
  revierte es real, y un índice no hace splits).

  TimeGate: (a) y (b) solo se saben al ver las sesiones siguientes, así que las sesiones corregidas (a) y la
  ventana de confirmación (b) toman la ``fecha_publicacion`` y el ``disponible_utc`` de la sesión que lo confirma
  (la de vuelta en a, la ``VENTANA_CONFIRMACION``-ésima en b): no se ven antes de que se pudiera saber.
- **P28 · huecos de calendario** (``rellenar_huecos``): sesiones del calendario del mercado (el del EDA,
  ``eda.CALENDARIO_MERCADO`` desde ``eda.INICIO_CALENDARIO``) sin vela entre la primera y la última sesión. Los
  huecos de hasta ``MAX_HUECO`` sesiones seguidas se rellenan hacia atrás con la última vela: ``close`` = cierre
  anterior, ``open``/``high``/``low`` nulos (vela plana), volumen 0, dividendo 0, split 1 y la ``fecha_publicacion``
  y ``disponible_utc`` de la regla normal de su sesión (``visibilidad.disponible_cierre_serie``; nunca antes que la
  vela anterior). Un ticker con algún hueco más largo sale de la curada («fuera» en la lista,
  ``marcar_fuera_en_lista``).
- **P02 · tickers reutilizados**: los de la lista curada con aviso «ticker reutilizado» salen («fuera», motivo
  ``MOTIVO_REUTILIZADO``): sus precios son de otra empresa. El crudo no se toca.

Registro sin valores: ``registro_saltos`` (ticker, sesión, tipo, razón redondeada a 1 decimal, sesiones tocadas y
sesión de confirmación). CLI de la lista: ``python -m ingesta.mercados_series.saneado_precios marcar-lista``
(P02 y P28 sobre ``precios/`` hasta el corte; escribe solo las entradas de precios que cambian y la cabecera).
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingesta.mercados_series import eda, visibilidad
from ingesta.mercados_series.contrato import primera_decision_vec

# --- P21 -------------------------------------------------------------------------------------------------------
MERCADO_CORREGIDO: dict[str, tuple[str, str]] = {
    "^W5000": ("XNYS", "Wilshire 5000 (índice de EE. UU.): Yahoo lo da con el mercado de Londres (XLON); se le "
                       "pone el cierre y el calendario de la NYSE (saneado P21)"),
}

# --- P11 -------------------------------------------------------------------------------------------------------
UMBRAL_SALTO = eda.UMBRAL_SALTO_PRECIO     # |Δlog| > 0,4 (≈ +49 % / −33 %): lejos del nivel previo
MIN_CAMBIO = 0.5                           # P11: solo los saltos de más del 50 % (razón > 1,5 o < 0,5)
VENTANA_PICO = 3
TOLERANCIA_REVERSION = 0.15
FRACCION_REVERSION = 0.25
VENTANA_CONFIRMACION = 3
RATIOS_LIMPIOS = (2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0)
TOLERANCIA_RATIO = 0.02
VENTANA_VOLUMEN = 20
TOLERANCIA_VOLUMEN = 2.0
CLASES_P11 = frozenset({"accion", "etf", "etp", "fondo", "otro", ""})
PICO, SPLIT, REAL = "pico", "split", "real"
TIPOS_SALTO = {PICO: "pico aislado que revierte: vela plana del cierre anterior",
               SPLIT: "cambio de nivel persistente con razón de split limpio: factor en la columna split",
               REAL: "movimiento real o sin confirmar: se mantiene"}
COLUMNAS_SALTOS = ("ticker", "proveedor", "sesion", "tipo", "razon", "factor_split", "sesiones_tocadas",
                   "confirmada_en", "nota")

# --- P28 -------------------------------------------------------------------------------------------------------
MAX_HUECO = 5

# --- P02 -------------------------------------------------------------------------------------------------------
AVISO_REUTILIZADO = "ticker reutilizado"
MOTIVO_REUTILIZADO = "ticker reutilizado: precios de otra empresa (saneado P02, 2026-11-21)"
MOTIVO_HUECO = "hueco de más de {m} sesiones seguidas sin vela ({n} sesiones desde {d}; saneado P28, 2026-11-21)"


@dataclass
class Saneado:
    """Qué cambió ``sanear`` en un ticker (sesiones como ``Timestamp``)."""

    corregidas: set = field(default_factory=set)        # P11 (a): vela plana del cierre anterior
    retrasadas: set = field(default_factory=set)        # P11 (a) y (b): publicación de la sesión que lo confirma
    splits: dict = field(default_factory=dict)          # P11 (b): sesión → factor
    rellenas: set = field(default_factory=set)          # P28: sesiones añadidas
    huecos_largos: list = field(default_factory=list)   # P28: (desde, hasta, n) de más de MAX_HUECO
    saltos: list = field(default_factory=list)          # filas del registro (sin ticker ni proveedor)


# --- P21 -------------------------------------------------------------------------------------------------------
def corregir_mercado(p: pd.DataFrame, mercado: str) -> pd.DataFrame:
    """Copia de ``p`` con ``mercado`` y, por sesión, el ``disponible_utc`` más tardío entre el guardado y el del
    cierre de ``mercado`` (+30 min), con su ``fecha_publicacion``. Nunca adelanta nada."""
    out = p.copy()
    if not len(out):
        return out
    nuevo = visibilidad.disponible_cierre_serie(out["sesion"], mercado)
    viejo = pd.to_datetime(out["disponible_utc"], utc=True)
    disp = nuevo.where(nuevo > viejo, viejo)
    out["mercado"] = mercado
    out["disponible_utc"] = disp.to_numpy()
    out["fecha_publicacion"] = primera_decision_vec(disp).to_numpy()
    return out


# --- P11 -------------------------------------------------------------------------------------------------------
def _ratio_limpio(r: float) -> float | None:
    if not np.isfinite(r) or r <= 0:
        return None
    candidatos = np.r_[np.array(RATIOS_LIMPIOS), 1.0 / np.array(RATIOS_LIMPIOS)]
    d = np.abs(np.log(r / candidatos))
    k = int(np.argmin(d))
    return float(candidatos[k]) if d[k] < TOLERANCIA_RATIO else None


def _volumen_coherente(v: np.ndarray, i: int, factor: float) -> bool:
    """El volumen mediano de las ``VENTANA_VOLUMEN`` sesiones desde ``i`` frente al de las anteriores está a menos de
    x/÷``TOLERANCIA_VOLUMEN`` de ``factor`` (sin volumen a algún lado no se puede mirar y vale)."""
    antes = v[max(0, i - VENTANA_VOLUMEN):i]
    despues = v[i:i + VENTANA_VOLUMEN]
    a = np.nanmedian(antes) if np.isfinite(antes).any() else np.nan
    b = np.nanmedian(despues) if np.isfinite(despues).any() else np.nan
    if not (np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0):
        return True
    return bool(abs(np.log((b / a) / factor)) < np.log(TOLERANCIA_VOLUMEN))


def clasificar_saltos(p: pd.DataFrame, clase: str | None = None) -> list[dict[str, Any]]:
    """Clasifica los saltos sin split de ``p`` (ordenada por sesión, sin cierres nulos): una fila por salto con
    ``i`` (posición), ``tipo``, ``razon``, ``factor``, ``tocadas`` (posiciones que cambian) y ``confirma``
    (posición cuya publicación toman). Los saltos de vuelta y los interiores de un pico van como ``pico``.
    ``clase`` fuera de ``CLASES_P11`` (índices, volatilidad, divisas, futuros): todos ``real``."""
    p = p.reset_index(drop=True)
    corregible = (clase or "") in CLASES_P11
    n = len(p)
    if n < 2:
        return []
    c = p["close"].to_numpy(dtype=float)
    vol = p["volume"].to_numpy(dtype=float)
    spl = p["split"].fillna(1.0).to_numpy(dtype=float)
    evento = (spl != 1.0) | (p["dividendo"].fillna(0.0).to_numpy(dtype=float) > 0)
    ss = eda.saltos_sin_split(p)
    pos = {pd.Timestamp(s): k for k, s in enumerate(p["sesion"])}
    filas: list[dict[str, Any]] = []
    en_pico: dict[int, int] = {}
    for s, no_pos in zip(ss["sesion"], ss["no_positivo"]):
        i = pos[pd.Timestamp(s)]
        razon = c[i] / c[i - 1] if c[i - 1] != 0 else np.nan
        fila = {"i": i, "razon": razon, "factor": None, "tocadas": [], "confirma": None}
        # En el alcance: más del 50 %, o una razón de split limpio (un 2:1 deja el precio en ~0,5, a veces 0,51).
        grande = (not np.isfinite(razon) or razon <= 0 or abs(razon - 1.0) > MIN_CAMBIO
                  or _ratio_limpio(1.0 / razon) is not None)
        if i not in en_pico and not (no_pos or grande):
            continue                                   # salto del EDA de menos del 50 %: fuera del alcance de P11
        if i in en_pico:
            filas.append({**fila, "tipo": PICO, "nota": f"parte del pico que empieza en la sesión {en_pico[i]}"})
            continue
        if no_pos or i == 0 or c[i - 1] <= 0 or c[i] <= 0:
            filas.append({**fila, "tipo": REAL, "nota": "cierre <= 0: se mantiene"})
            continue
        if not corregible:
            filas.append({**fila, "tipo": REAL, "nota": f"clase {clase} sin acciones corporativas: se mantiene"})
            continue
        base = c[i - 1]
        salto = np.log(c[i] / base)
        pico = None
        for k in range(1, VENTANA_PICO + 1):
            if i + k >= n or evento[i:i + k + 1].any() or (c[i:i + k + 1] <= 0).any():
                break
            dentro = np.log(c[i:i + k] / base)
            if not ((np.sign(dentro) == np.sign(salto)) & (np.abs(dentro) > UMBRAL_SALTO)).all():
                break
            if abs(np.log(c[i + k] / base)) <= min(TOLERANCIA_REVERSION, FRACCION_REVERSION * abs(salto)):
                pico = k
                break
        if pico:
            for j in range(i, i + pico + 1):
                en_pico[j] = i
            filas.append({**fila, "tipo": PICO, "tocadas": list(range(i, i + pico)), "confirma": i + pico,
                          "nota": f"revierte en {pico} sesión(es)"})
            continue
        if i + VENTANA_CONFIRMACION >= n:
            filas.append({**fila, "tipo": REAL, "nota": "sin sesiones para confirmar: se mantiene"})
            continue
        siguientes = c[i + 1:i + VENTANA_CONFIRMACION + 1]
        persiste = bool((siguientes > 0).all() and (np.abs(np.log(siguientes / c[i])) < 0.5 * abs(salto)).all())
        cerca = evento[max(0, i - VENTANA_CONFIRMACION):i + VENTANA_CONFIRMACION + 1] & (
            spl[max(0, i - VENTANA_CONFIRMACION):i + VENTANA_CONFIRMACION + 1] != 1.0)
        factor = _ratio_limpio(base / c[i])
        volumen_ok = factor is not None and _volumen_coherente(vol, i, factor)
        if persiste and factor is not None and not cerca.any() and volumen_ok:
            filas.append({**fila, "tipo": SPLIT, "factor": factor,
                          "tocadas": list(range(i, i + VENTANA_CONFIRMACION)), "confirma": i + VENTANA_CONFIRMACION,
                          "nota": "cambio de nivel persistente con razón de split limpio"})
        else:
            motivo = ("no persiste" if not persiste else "razón sin split limpio" if factor is None
                      else "split registrado cerca" if cerca.any() else "el volumen no acompaña al factor")
            filas.append({**fila, "tipo": REAL, "nota": f"movimiento real ({motivo}): se mantiene"})
    return filas


def _copiar_publicacion(out: pd.DataFrame, filas: list[int], de: int) -> None:
    for col in ("disponible_utc", "fecha_publicacion"):
        out.iloc[filas, out.columns.get_loc(col)] = out.iloc[de][col]


def sanear_saltos(p: pd.DataFrame, s: Saneado | None = None,
                  clase: str | None = None) -> tuple[pd.DataFrame, Saneado]:
    """Aplica ``clasificar_saltos`` a ``p`` (ordenada por sesión): (a) vela plana del cierre anterior, (b) factor en
    ``split``; en los dos, la publicación de la sesión que lo confirma. Devuelve la tabla y ``s`` actualizado."""
    s = s or Saneado()
    out = p.reset_index(drop=True).copy()
    filas = clasificar_saltos(out, clase)
    ses = out["sesion"]
    for f in filas:
        if f["tipo"] == PICO and f["tocadas"]:
            base = out.at[f["i"] - 1, "close"]
            for j in f["tocadas"]:
                out.at[j, "close"] = base
                for col in ("open", "high", "low"):
                    out.at[j, col] = np.nan
                s.corregidas.add(pd.Timestamp(ses.iloc[j]))
        elif f["tipo"] == SPLIT:
            out.at[f["i"], "split"] = f["factor"]
            s.splits[pd.Timestamp(ses.iloc[f["i"]])] = f["factor"]
        if f["confirma"] is not None:
            _copiar_publicacion(out, f["tocadas"], f["confirma"])
            s.retrasadas.update(pd.Timestamp(ses.iloc[j]) for j in f["tocadas"])
        razon = f["razon"]
        s.saltos.append({"sesion": pd.Timestamp(ses.iloc[f["i"]]), "tipo": f["tipo"],
                         "razon": round(float(razon), 1) if np.isfinite(razon) else None,
                         "factor_split": f["factor"], "sesiones_tocadas": len(f["tocadas"]),
                         "confirmada_en": pd.Timestamp(ses.iloc[f["confirma"]]) if f["confirma"] is not None else None,
                         "nota": f["nota"]})
    return out, s


# --- P28 -------------------------------------------------------------------------------------------------------
def calendario(mercado: str | None, sesiones_cal: np.ndarray | None = None) -> np.ndarray | None:
    """Sesiones del calendario del EDA para ``mercado`` (``None``: días L-V, como ``eda.sesiones_faltantes``)."""
    if sesiones_cal is not None:
        return np.asarray(sesiones_cal).astype("datetime64[D]")
    nombre = eda.CALENDARIO_MERCADO.get(mercado or "")
    if not nombre:
        return None
    try:
        return eda.sesiones_calendario(nombre)
    except Exception:          # calendario que no resuelve: días L-V
        return None


def huecos(sesiones: Any, mercado: str | None, sesiones_cal: np.ndarray | None = None) -> list[tuple]:
    """Huecos de calendario entre la primera y la última sesión: ``[(posiciones_en_cal, sesiones_faltantes)]``,
    una tupla ``(desde, hasta, n, faltan)`` por racha de sesiones del calendario sin vela."""
    s = np.unique(pd.to_datetime(pd.Series(sesiones)).to_numpy().astype("datetime64[D]"))
    if len(s) < 2:
        return []
    cal = calendario(mercado, sesiones_cal)
    if cal is None:
        cal = np.arange(s[0], s[-1] + np.timedelta64(1, "D"), dtype="datetime64[D]")
        cal = cal[np.is_busday(cal)]
    desde, hasta = max(s[0], cal[0]) if len(cal) else s[0], min(s[-1], cal[-1]) if len(cal) else s[-1]
    cal_r = cal[(cal >= desde) & (cal <= hasta)]
    faltan = np.setdiff1d(cal_r, s)
    if not len(faltan):
        return []
    k = np.searchsorted(cal_r, faltan)
    cortes = np.flatnonzero(np.diff(k) != 1) + 1
    return [(g[0], g[-1], len(g), g) for g in np.split(faltan, cortes)]


def rellenar_huecos(p: pd.DataFrame, mercado: str | None, sesiones_cal: np.ndarray | None = None,
                    s: Saneado | None = None, max_hueco: int = MAX_HUECO) -> tuple[pd.DataFrame, Saneado]:
    """Rellena hacia atrás los huecos de calendario de hasta ``max_hueco`` sesiones (ver el docstring del módulo) y
    apunta los más largos en ``s.huecos_largos`` (no se rellenan)."""
    s = s or Saneado()
    p = p.reset_index(drop=True)
    if len(p) < 2 or mercado is None:
        return p, s
    nuevas = []
    sesiones = p["sesion"].to_numpy().astype("datetime64[D]")
    for desde, hasta, n, faltan in huecos(p["sesion"], mercado, sesiones_cal):
        if n > max_hueco:
            s.huecos_largos.append((pd.Timestamp(desde), pd.Timestamp(hasta), int(n)))
            continue
        i = int(np.searchsorted(sesiones, desde)) - 1          # última vela antes del hueco
        previa, siguiente = p.iloc[i], p.iloc[i + 1]
        dias = pd.Series(pd.to_datetime(faltan.astype("datetime64[ns]")))
        disp = visibilidad.disponible_cierre_serie(dias, mercado)
        tope = pd.Timestamp(previa["disponible_utc"])
        disp = disp.where(disp >= tope, tope)
        nuevas.append(pd.DataFrame({
            "ticker": previa["ticker"], "sesion": dias.to_numpy(), "mercado": previa["mercado"],
            "open": np.nan, "high": np.nan, "low": np.nan, "close": previa["close"], "volume": 0.0,
            "dividendo": 0.0, "split": 1.0, "divisa": previa["divisa"],
            "fecha_publicacion": primera_decision_vec(disp).to_numpy(), "disponible_utc": disp.to_numpy(),
            "fuente": previa["fuente"], "descargado": siguiente["descargado"]}))
        s.rellenas.update(pd.Timestamp(d) for d in dias)
    if not nuevas:
        return p, s
    out = pd.concat([p, *[t.astype(p.dtypes.to_dict()) for t in nuevas]], ignore_index=True)
    return out.sort_values("sesion", kind="mergesort").reset_index(drop=True), s


def sanear(p: pd.DataFrame, mercado: str | None, sesiones_cal: np.ndarray | None = None,
           clase: str | None = None) -> tuple[pd.DataFrame, Saneado]:
    """P11 y después P28 sobre una tabla ya curada por el EDA (ordenada por sesión); ``clase``: la de la lista."""
    out, s = sanear_saltos(p, clase=clase)
    return rellenar_huecos(out, mercado, sesiones_cal, s)


def registro_saltos(tk: str, pv: str, s: Saneado) -> list[dict[str, Any]]:
    """Filas de ``COLUMNAS_SALTOS`` de un ticker (sin precios: tipo, razón con 1 decimal y sesiones)."""
    return [{"ticker": tk, "proveedor": pv, **f,
             "sesion": f["sesion"].strftime("%Y-%m-%d"),
             "confirmada_en": f["confirmada_en"].strftime("%Y-%m-%d") if f["confirmada_en"] is not None else None}
            for f in s.saltos]


# --- Lista curada (P02 y P28) -----------------------------------------------------------------------------------
_LINEA = re.compile(r"^  (?P<clave>'[^']*'|[^:\s][^:]*?): \{(?P<cuerpo>.*)\}\s*$")


def marcar_fuera_en_lista(ruta: Path, fuera: Mapping[str, tuple[str, str]]) -> dict[str, Any]:
    """Pone ``decision: fuera``, ``regla`` y ``motivo`` (el anterior queda detrás, tras «antes:») a los tickers de
    ``fuera`` (``{ticker: (regla, motivo)}``) en la sección ``precios`` de la lista curada y rehace su cabecera
    ``# Precios: N (fuera F, queda Q).``. Solo cambia esas líneas (sin reescribir el YAML). Idempotente."""
    texto = Path(ruta).read_text(encoding="utf-8")
    lineas = texto.split("\n")
    ini = lineas.index("precios:")
    cambiados, decisiones = [], {}
    for k in range(ini + 1, len(lineas)):
        m = _LINEA.match(lineas[k])
        if not m:
            if lineas[k] and not lineas[k].startswith(" "):
                break
            continue
        clave = m.group("clave").strip("'")
        cuerpo = m.group("cuerpo")
        dec = re.search(r"decision: (\w+)", cuerpo).group(1)
        if clave in fuera and dec != "fuera":
            regla, motivo = fuera[clave]
            previo = re.search(r"motivo: ('(?:[^']|'')*'|[^,]*)", cuerpo)
            antes = previo.group(1) if previo else ""
            if antes.startswith("'") and antes.endswith("'"):
                antes = antes[1:-1].replace("''", "'")
            nuevo_motivo = f"{motivo}; antes: {antes}".replace("'", "''")
            cuerpo = re.sub(r"decision: \w+", "decision: fuera", cuerpo, count=1)
            cuerpo = re.sub(r"regla: [^,]*", f"regla: {regla}", cuerpo, count=1)
            cuerpo = (cuerpo.replace(previo.group(0), f"motivo: '{nuevo_motivo}'", 1) if previo
                      else cuerpo + f", motivo: '{nuevo_motivo}'")
            lineas[k] = f"  {m.group('clave')}: {{{cuerpo}}}"
            dec = "fuera"
            cambiados.append(clave)
        decisiones[clave] = dec
    n = len(decisiones)
    n_fuera = sum(d == "fuera" for d in decisiones.values())
    cab = re.compile(r"^# Precios: .*$")
    for k, ln in enumerate(lineas):
        if cab.match(ln):
            lineas[k] = f"# Precios: {n} (fuera {n_fuera}, queda {n - n_fuera})."
            break
    Path(ruta).write_text("\n".join(lineas), encoding="utf-8")
    return {"cambiados": sorted(cambiados), "precios": n, "fuera": n_fuera, "queda": n - n_fuera}


def tickers_reutilizados(lista: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Tickers «queda» de la lista con aviso de ticker reutilizado (P02)."""
    return sorted(tk for tk, e in lista.items()
                  if (e or {}).get("decision") == "queda" and AVISO_REUTILIZADO in str((e or {}).get("aviso") or ""))


def tickers_con_hueco_largo(lista: Mapping[str, Mapping[str, Any]], origen: Path | None = None,
                            corte: pd.Timestamp | None = None) -> dict[str, tuple]:
    """``{ticker: (desde, hasta, n)}`` del hueco más largo de cada ticker «queda» con un hueco de calendario de más de
    ``MAX_HUECO`` sesiones, tras el corte y las velas de relleno quitadas (``curada_precios.curar_ticker``)."""
    from ingesta.comun.rutas import corpus_dir
    from ingesta.mercados_series import curada_precios as cp
    from ingesta.mercados_series.contrato import validar_precios
    import pyarrow.parquet as pq

    corte = cp.CORTE_G2 if corte is None else corte
    ficheros, _ = cp.ficheros_origen(Path(origen or corpus_dir(cp.TEMA) / "precios"))
    out = {}
    for tk, e in sorted(lista.items()):
        if (e or {}).get("decision") != "queda" or tk not in ficheros:
            continue
        r = cp.curar_ticker(validar_precios(pq.read_table(ficheros[tk][1]).to_pandas()), corte)
        if r.saneado.huecos_largos:
            out[tk] = max(r.saneado.huecos_largos, key=lambda h: h[2])
    return out


def main(argv: list[str] | None = None) -> int:
    from ingesta.mercados_series import curada_precios as cp

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("orden", choices=["marcar-lista"])
    ap.add_argument("--sin-escribir", action="store_true")
    a = ap.parse_args(argv)
    lista = cp.cargar_lista_precios()
    fuera = {tk: ("reutilizado", MOTIVO_REUTILIZADO) for tk in tickers_reutilizados(lista)}
    largos = tickers_con_hueco_largo(lista)
    for tk, (d, _h, n) in largos.items():
        fuera.setdefault(tk, ("hueco_largo", MOTIVO_HUECO.format(m=MAX_HUECO, n=n, d=f"{d:%Y-%m-%d}")))
    print(f"reutilizados: {sum(r == 'reutilizado' for r, _ in fuera.values())}; con hueco de más de {MAX_HUECO} "
          f"sesiones: {len(largos)} ({', '.join(f'{t} {v[2]}' for t, v in largos.items())})")
    if a.sin_escribir:
        return 0
    print(marcar_fuera_en_lista(cp.RUTA_LISTA, fuera))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
