"""Contrato de tools para los agentes del TFM (ADR-012).

Las fases 3–5 (agentes, cartera, evaluación) importan solo de aquí, nunca de ``regimenes.*`` ni de
``ingesta.*`` directamente. Cada tool es tipada (pydantic), declara qué agentes la usan y recibe la
fecha de la decisión del sistema, no del LLM.

- ``contrato``  modelos comunes: ``Cita``, ``EntradaTool``, ``SalidaTool``.
- ``registro``  ``registrar``, ``catalogo``, ``json_schema``, ``invocar``.
- ``regimen``   ``get_regimen`` (Fase 1).
- ``series``    ``get_serie``, ``get_precios``, ``get_proyeccion`` y ``buscar_series`` (Fase 2, Tema 1): resumen
  más las últimas N filas, nunca la ventana entera.

==================  ===========================================================  =============================
Tool                Qué devuelve                                                 Agentes
==================  ===========================================================  =============================
``get_regimen``     régimen publicado hasta la fecha y consenso de detectores    macro, risk, portfolio, cio
``get_serie``       serie de la base curada: resumen y últimas filas             macro, risk, portfolio, cio
``get_precios``     hasta 10 tickers: resumen (rentabilidades, volatilidad,      equity, portfolio, risk, cio
                    caída desde máximos) y últimas sesiones OHLCV
``get_proyeccion``  proyecciones FMI / FOMC: última edición visible por periodo  macro, cio
``buscar_series``   fichas del catálogo del Tema 1 con su puntuación             todos
==================  ===========================================================  =============================

Uso::

    from datetime import date
    from herramientas import catalogo, invocar, json_schema

    json_schema("get_serie")                                   # lo que ve el LLM (sin fecha)
    s = invocar("get_serie", {"id": "fred:DGS10"}, fecha=date(2020, 3, 16))
    s.resumen.ultimo_valor, s.filas[-1], s.citas
"""

from herramientas import regimen  # noqa: F401  (registra get_regimen en el catálogo)
from herramientas import series  # noqa: F401  (registra get_serie, get_precios, get_proyeccion y buscar_series)
from herramientas.registro import catalogo, invocar, json_schema

__all__ = ["catalogo", "invocar", "json_schema"]
