"""Fecha de corte del dataset del Tema 1 en un solo sitio (P07 de ``AUDITORIA_SANEADO.md``).

Orden de prioridad:

1. la variable de entorno ``T1_CORTE`` (``AAAA-MM-DD``), que pone ``refrescar --corte`` (y ``curar --corte`` /
   ``curar-precios --corte``) para un refresco sin tocar la configuración;
2. ``config/corte.yaml`` (clave ``corte``), el corte vigente versionado.

Los módulos que antes tenían la fecha escrita (``curada.CORTE_G2``, ``curada_precios.CORTE_G2``,
``seleccion.FECHA_CORTE``, ``estado_3b.FECHA_CORTE``) la leen de aquí al importarse. Todas sus funciones ya aceptan
``corte=`` como argumento; el valor por defecto es este.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import yaml

VARIABLE = "T1_CORTE"
RUTA_CONFIG = Path(__file__).resolve().parent / "config" / "corte.yaml"


def corte_config(ruta: Path | None = None) -> pd.Timestamp:
    """Corte de ``config/corte.yaml`` (sin mirar el entorno)."""
    datos = yaml.safe_load((ruta or RUTA_CONFIG).read_text(encoding="utf-8")) or {}
    if "corte" not in datos:
        raise ValueError(f"{ruta or RUTA_CONFIG}: falta la clave 'corte'")
    return _validar(str(datos["corte"]))


def corte_vigente(ruta: Path | None = None) -> pd.Timestamp:
    """Corte que usan los módulos: ``T1_CORTE`` si está definida; si no, ``config/corte.yaml``."""
    valor = os.environ.get(VARIABLE, "").strip()
    return _validar(valor) if valor else corte_config(ruta)


def _validar(texto: str) -> pd.Timestamp:
    try:
        t = pd.Timestamp(texto)
    except (ValueError, TypeError) as e:
        raise ValueError(f"corte no válido: {texto!r} (formato AAAA-MM-DD)") from e
    if t != t.normalize() or t.tzinfo is not None:
        raise ValueError(f"corte no válido: {texto!r} (solo fecha, sin hora ni zona)")
    return t
