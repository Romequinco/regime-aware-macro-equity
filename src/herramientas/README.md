# `herramientas` · contrato de tools para los agentes

Puente entre los datos (Fase 1 [`regimenes`](../regimenes/README.md) y Fase 2 [`ingesta`](../ingesta))
y los agentes de las fases 3–5. Los agentes importan **solo** de este paquete. Así el detector de régimen o
una fuente pueden cambiar sin romperlos. La decisión está en
[ADR-012](../../docs/decisions/ADR-012-estructura-repo.md) y el catálogo previsto en
[`docs/tfm/arquitectura.md`](../../docs/tfm/arquitectura.md).

| Módulo | Qué hace |
|---|---|
| `contrato.py` | Modelos pydantic comunes: `Cita`, `EntradaTool` (lo que elige el LLM) y `SalidaTool` (respuesta con citas y avisos) |
| `registro.py` | `registrar` (decorador), `catalogo(agente)`, `json_schema(nombre)` (lo que ve el LLM) e `invocar(nombre, args, fecha=...)` |
| `regimen.py` | `get_regimen`: envoltorio tipado de `regimenes.regimen.get_regimen` |
| `series.py` | `get_serie`, `get_precios`, `get_proyeccion` y `buscar_series`: envoltorios tipados de [`ingesta.mercados_series.tools`](../ingesta/mercados_series/tools.py) y del catálogo de agentes del Tema 1 |

## Tools

| Tool | Qué devuelve al LLM | Agentes |
|---|---|---|
| `get_regimen` | Régimen de mercado publicado hasta la fecha y el consenso de detectores | macro, risk, portfolio, cio |
| `get_serie` | Serie macro o de mercado de la base curada: resumen (último dato, cambio frente al periodo anterior y a hace un año, percentil histórico, mínimo y máximo de la ventana) y las últimas `max_filas` (24) filas | macro, risk, portfolio, cio |
| `get_precios` | Hasta 10 tickers (Yahoo, o Coinbase con `cb:`): por ticker, último cierre, rentabilidad a 1, 3 y 12 meses, volatilidad a 3 meses, caída desde el máximo de 12 meses y las últimas `max_filas` (20) sesiones OHLCV | equity, portfolio, risk, cio |
| `get_proyeccion` | Proyecciones oficiales (WEO del FMI, SEP del FOMC): por periodo, la última edición visible, con su horizonte | macro, cio |
| `buscar_series` | Fichas del catálogo de datos del Tema 1 que encajan con un texto o unos filtros (tema, zona, agente, tipo), con su `puntuacion` | todos |

Las tools de datos devuelven un **resumen más las últimas N filas**, nunca la ventana entera, para no saturar al
modelo. Las reglas del resumen (cuándo el cambio es una diferencia y cuándo un %, el percentil, la volatilidad) están
en el docstring de [`series.py`](series.py). Un id o ticker desconocido, o sin nada publicado a la fecha, no lanza:
devuelve `encontrado=False` y un aviso neutro con el id pedido (no revela si existirá ni a qué canónico
apunta un alias) que remite a `buscar_series`. Los avisos y el `desde` de las fichas de `buscar_series` también
pasan el TimeGate (ver el catálogo de agentes en el [README del tema](../ingesta/mercados_series/README.md)).
El esquema de `buscar_series` lleva el vocabulario real: `tipo` cerrado (`serie`, `precio`, `proyeccion`) y los
temas y las zonas de `config/catalogo_agentes.yaml` en la descripción de `tema` y `zona`.

## Reglas

1. **La fecha la pone el sistema, nunca el LLM.** `registrar` rechaza un modelo de entrada con campo
   `fecha`, e `invocar` la recibe aparte. Así ninguna tool puede mirar el futuro (TimeGate).
2. **Toda salida lleva citas.** Cada `SalidaTool` dice de qué fichero o serie sale, con su huella. Esas
   citas son las que usa el memo final.
3. **Solo se envuelve.** La lógica vive en su paquete (`regimenes`, `ingesta/<tema>/tools.py`). Aquí solo se
   tipa y se registra.

```python
from datetime import date
from herramientas import catalogo, invocar, json_schema

[t.nombre for t in catalogo("macro")]                          # tools del agente macro
json_schema("get_serie")                                       # esquema para el LLM (sin fecha)
invocar("get_regimen", {}, fecha=date(2020, 3, 16)).estado     # 'crisis'

f = date(2020, 3, 16)                                          # la pone el sistema, no el LLM
invocar("buscar_series", {"texto": "bono 10 años", "agente": "macro"}, fecha=f).fichas
s = invocar("get_serie", {"id": "fred:DGS10", "max_filas": 5}, fecha=f)
s.resumen.ultimo_valor, s.resumen.cambio_anual, s.citas        # resumen, sin la historia entera
p = invocar("get_precios", {"tickers": ["SPY", "cb:BTC-USD"]}, fecha=f)
p.tickers[0].resumen.rentabilidad_12m
salida = s.model_dump_json()                                   # lo que se pasa al LLM
```
