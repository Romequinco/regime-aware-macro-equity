# Tema 1 · Plan de la descarga completa (documento temporal)

> **Temporal.** Este documento solo existe en la rama `fase2/t1-descarga`. Al terminar se destila en el
> [README del tema](../../../src/ingesta/mercados_series/README.md) y se borra antes de fusionar con `main`.
> Aquí se apuntan el plan, las decisiones y el estado de cada paso.

## Objetivo

Dejar en el corpus del Tema 1 (`D:/tfm_corpus/mercados_series`) **el máximo de datos útiles para los agentes, sin
meter datos por meter**. Cada serie o ticker tiene que aportar información relevante, más o menos única y no repetida.
El crudo descargado no se borra nunca: la depuración produce una base curada aparte y se puede deshacer.

**Punto de partida (2026-11-17):**

| Qué | Cifra |
|---|---|
| Filas | 10,5 M |
| Series | 1.434 (worldbank 594, imf_weo 280, fred_alfred 241, bce 52, eurostat 47, bis 35, resto < 30) |
| Ficheros de precios | 1.471 (Yahoo 1.469, Coinbase 2) |
| Tamaño en disco | ~2,5 GB |
| Último refresco | 2026-10-13/14 |

## Criterio para quedarse con un dato

Una serie o un ticker se queda si pasa las cuatro preguntas:

1. **Uso.** ¿Qué agente la usa (Macro, Equity, Risk o Portfolio) y para qué pregunta? Si no la usa ninguno, fuera.
2. **Información nueva.** ¿Repite algo que ya tenemos? Un mismo concepto de dos fuentes da una serie canónica y el
   resto se guarda como validación o alias. Una serie casi idéntica a otra, por encima del umbral de redundancia del
   paso 2, se guarda como alias.
3. **Fecha fiable.** ¿Se puede saber cuándo se publicó? Sin fecha de publicación fiable no entra en el backtest.
4. **Historia.** ¿Cubre desde **2000**? Así sirven las dos ventanas en estudio (2007–2026 y 2016–2026), con margen
   para medias y z-scores. Lo que empieza después solo se queda si es único (por ejemplo Polymarket o las OAS de ICE).

## Los pasos

| Paso | Notebook | Qué hace | Termina con |
|---|---|---|---|
| 1 | `01_resumen_sonda` | Resumen muy breve de la sonda: los 9 notebooks antiguos, reflejados y muy resumidos en uno, que se borran después (etiqueta `sonda-tema1`, sin más relevancia) | Notebook corto; notebooks antiguos fuera |
| 2 | `02_inventario` | Recuento de lo que hay, por fuente, concepto, frecuencia, cobertura, agente y fiabilidad de fecha; fija las bases para decidir: umbrales y reglas del criterio | Tabla de inventario + criterio aprobado |
| 3 | `03_seleccion_eda` | Aplica el criterio y saca la lista «se queda / alias / fuera» con su motivo. EDA sencillo de lo que se queda (huecos, rupturas, escalas). Prepara el preprocesado **sin hacerlo**. Lista de lo que falta por descargar | `lista_curada.yaml` y plan de preprocesado aprobados |
| 3b | (script) | Descargas que faltan, en segundo plano y reanudables: refresco hasta hoy, precios de apertura (ejecución en `t+1`, ver [arquitectura](../../tfm/arquitectura.md)), archivo de OAS de ICE, ediciones del WEO, deslistados | Logs de descarga sin pendientes |
| 4 | `04_preprocesado` | Construye la base curada a partir del crudo con la lista aprobada y verifica que todo está bien: TimeGate, truncado y conteos | Base curada + tests en verde |
| 5 | `05_resultado` | Cómo ha quedado, catálogo legible para los agentes y última verificación | Resumen final; este documento se destila en el README y se borra; PR |

## Cómo se trabaja

- **Un bloque por paso.** Los pasos 2 a 5 son cada uno un workflow de menos de 10 agentes:
  1. un agente implementa (módulo en `src/ingesta/mercados_series` + notebook);
  2. dos críticos en paralelo (TimeGate y causalidad; datos y código), con un máximo de 8 hallazgos altos o medios;
  3. una sola ronda de corrección;
  4. un verificador ligero.
  El paso 1 lo hace un único agente. Objetivo: unos 30 minutos por bloque.
- **Parada al final de cada paso** para tu OK. Las decisiones se preguntan de forma clicable, con la recomendación
  primero.
- **Listas grandes antes de actuar.** Como la lista ALFRED de 161 series: la lista curada se enseña y se aprueba antes
  de construir nada.
- **Descargas largas** en un `git worktree` aparte y con `Start-Process`. Nunca se cambia de rama con una descarga en
  marcha: en octubre falló así una descarga de 476 tickers.
- **Reglas fijas.**
  - Solo carpetas del tema, más `notebooks/fase2/mercados_series` y este documento.
  - No se tocan `src/regimenes`, `data/raw` ni la huella de la Fase 1.
  - Los datos, solo en `D:`.
  - Notebooks ejecutados de menos de 2 MB.
  - Commits sin coautoría.
- **Decisiones de la sonda que no se reabren:** USD base, decisión a las 16:30 de Nueva York, precios as-traded,
  vintages de ALFRED, ids `fuente:ID`, huecos permanentes como nulo con aviso, países EE. UU. + zona euro + G7 + China.

## Decisiones tomadas

| Fecha | Decisión |
|---|---|
| 2026-11-17 | Cinco pasos con un notebook por paso, más el paso 3b de descargas entre el 3 y el 4 |
| 2026-11-17 | Este documento vive en la rama y se borra al fusionar |
| 2026-11-17 | Notebooks de la sonda: reflejados y muy resumidos en el `01`, borrados, con la etiqueta `sonda-tema1` |
| 2026-11-17 | Historia mínima desde 2000, salvo datos únicos |
| 2026-11-17 | Las descargas que faltan entran en el paso 3b, solo de lo que se queda |

## Decisiones pendientes

| Paso | Decisión | Propuesta |
|---|---|---|
| 2 | Umbral de redundancia | Correlación de los cambios ≥ 0,95 en el periodo común → alias |
| 2 | Banco Mundial (594) y WEO (280): ¿qué indicadores y países? | Solo los países del alcance y los indicadores sin equivalente mensual o trimestral |
| 3 | Fuente canónica de cada concepto (p. ej. el 10 años: FRED, curva del Tesoro o Fase 1) | La de fecha de publicación más fiable y más historia |
| 3 | Un ETF por exposición (SPY/IVV/VOO, sectoriales de varios emisores) | El de más historia; los demás solo para el mapeo UCITS |
| 3b | Fuente final de precios (Q1 del plan de datos): Yahoo, EODHD (~20 €/mes), Tiingo o WRDS | Decide los deslistados y los precios de apertura |
| 4 | Forma de la base curada | Fichero aparte junto a `base_series.parquet`; frecuencias nativas, sin re-muestrear |
| 5 | Formato del catálogo para los agentes | Tabla con id, descripción, agente, frecuencia, desde y fiabilidad de fecha |
| Fuera | Fronteras con los compañeros | Universo de empresas común con el Tema 3; SKEW, GPR y EPU en el Tema 4; series del BCE y del BIS sin duplicar con el Tema 2 |

## Rescatado de la sonda (para los pasos siguientes y la memoria del TFM)

Lo que dejaban los notebooks antiguos y no recoge el README (originales en la etiqueta `sonda-tema1`):

- **Paso 2:** `fred_alfred` tiene `fecha_referencia` hasta 2029-01-01, seguramente horizontes del SEP u otras
  proyecciones. Hay que revisarlo y decidir si van a una tabla aparte. La ficha `boe` dice `fallo` y el README dice
  «bloqueada»: hay que unificarlo.
- **Paso 3 (EDA):**
  - En Yahoo, el inicio mediano es 1985 en EE. UU. y 1997 fuera, y antes de 2000 hay un 92 % frente a un 67 %.
  - Hay saltos sin split en AAPL, ASML.AS, CL=F, NVDA, SHEL.L y ^VIX.
  - Hay contrasplits o splits fraccionarios en XLF, EWJ, USO, ETHA y SAN.MC.
- **Memoria del TFM:**
  - Vintages: en 2008 el empleo se publicó como unos 1,9 M de empleos perdidos y hoy son unos 3,5 M. La semana de
    Lehman del NFCI tiene 401 valores distintos.
  - Costes: el multiplicador de crisis tiene mediana 1,03 en calma (2017), 6,9 en 2008 y 10 en 2020.
  - DTB3 se ve con un día de retraso mediano (p95, 3 días).
  - Figuras (reloj de decisión, Gantt y mapas de calor de cobertura, fuga del ajustado de Yahoo): siguen en la
    etiqueta; se exportan si hacen falta.

## Estado

| Paso | Estado | Commit |
|---|---|---|
| 1 | Hecho (2026-11-17): `01_resumen_sonda` (21 KB); 9 notebooks borrados; enlaces del README y de `docs/fase2` al día; el test de salidas de notebooks cubre ya todos los del tema | este |
| 2 | Pendiente | |
| 3 | Pendiente | |
| 3b | Pendiente | |
| 4 | Pendiente | |
| 5 | Pendiente | |
