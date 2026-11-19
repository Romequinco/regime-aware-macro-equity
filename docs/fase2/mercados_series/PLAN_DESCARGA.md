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

1. **Relevancia.** ¿Sirve para alguna pregunta del sistema: macro, mercados, riesgo o cartera? Qué agente usa cada
   dato se decide más adelante, al construir las tools y los agentes, no al hacer el dataset (decidido el 2026-11-17).
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

## Paso 2 · `02_inventario`: decisiones y plan

**Qué hace.** Cuenta lo que hay, serie a serie y ticker a ticker, con los metadatos que ya existen:
- de `catalogo_series.yaml`: frecuencia, unidad, divisa, método, `revisable`, `estado` (incluida `duplicada`) y
  `verificado`;
- de `universo.yaml`: clase, `bucket` y capa.

A eso le añade lo que se mide en el corpus: cobertura, huecos, primera publicación visible, número de vintages,
volumen y si hay precio de apertura. También mide la redundancia y fija las reglas del criterio. **No aplica el
filtro**, que es el paso 3. Para elegir los umbrales con datos, enseña cuántas series y tickers caerían con cada uno.

**Decisiones antes de lanzar:**

| # | Decisión | Propuesta |
|---|---|---|
| D1 | Qué significa «tiene historia desde 2000» | **Aprobada:** que la **primera publicación visible** (`fecha_publicacion`, no la de referencia) sea ≤ 2001-01-02 |
| D2 | Niveles de fiabilidad de la fecha | **Cerrada (2026-11-17)** tras el análisis del `02`, con un mismo trato para B y C en la ventana desde 2000:<br>- entran «exacta», «sin riesgo», «fiable», «con margen» y «verificada sin medir»;<br>- a las «no fiables» se les quita el tramo sin contrastar (o pasan a una regla conservadora);<br>- las «no medibles» (mercado diario, Banco Mundial, macro de Eurostat, BCE y BIS, académicas) entran **con aviso y con una regla conservadora**: la fecha más tardía plausible según el calendario documentado de cada fuente;<br>- en el backtest se hace una prueba de robustez contra la fecha normal.<br>Las reglas concretas se preparan en el paso 3 y se aplican en el 4 |
| D3 | Países en el alcance | **Aprobada:** EE. UU., zona euro, G7 y China (decidido en la sonda), más los agregados mundial y emergentes del Banco Mundial y del WEO |
| D4 | Proyecciones (SEP, WEO, referencias futuras) | **Aprobada:** tabla aparte de proyecciones, fuera de la base curada |
| D5 | ~~Agente que usa cada serie~~ | **Descartada** (2026-11-17): se decide al construir los agentes, no en el dataset |
| D6 | Ficha del BoE | **Cerrada (2026-11-17):** sin ruta CSV o XML permitida en `robots.txt` (solo HTML), así que no se extrae de HTML. La ficha queda en «fallo» con el motivo (el esquema común no admite «bloqueada»). El tipo oficial va por el BIS y las curvas del BoE ya están. Se reconsidera si alguna serie del BoE no tiene alternativa |
| D7 | Dónde va el inventario | **Aprobada:** `results/ingesta/mercados_series/tablas/inventario_*.csv`, versionado (solo metadatos, sin valores) |

**Se deciden viendo el notebook** (lo enseña con tablas de sensibilidad):

| # | Decisión | Lo que enseña el notebook |
|---|---|---|
| D8 | Umbral de redundancia y solape mínimo | **Aprobada (2026-11-17):** 0,95 con la regla estrella (alias solo si se parece directamente a la que se queda), Pearson y Spearman, 5 años de solape; 102 alias de 557 series comparables |
| D9 | Banco Mundial (594) y WEO (280) | **Aprobada (2026-11-17):** alcance estricto (G7 + China; 24 series del Banco Mundial); fuera lo que ya existe con más frecuencia; las proyecciones del WEO, a su tabla aparte |
| D10 | Mínimos de un ticker (historia y liquidez) | **Abierta a propósito** (2026-11-17). Recomendación académica: sin corte por fecha de inicio en el dataset; la elegibilidad se aplica en el backtest punto a punto (en cada fecha, historia pasada y liquidez medidas solo con datos hasta esa fecha). Se fija en la Fase 4 |

**Lo que hace falta del equipo:** las fronteras con los otros temas:
- con el Tema 3, el universo de empresas común;
- con el Tema 4, SKEW, GPR y EPU;
- con el Tema 2, las series del BCE y del BIS.

El inventario marca los posibles duplicados con otros temas; la frontera se cierra antes del paso 3.

**Plan con 3 agentes:**

| Agente | Cuándo | Qué hace | Entrega |
|---|---|---|---|
| A1 · Inventario | En paralelo con A2 | Módulo `inventario.py` y orden `python -m ingesta.mercados_series inventario`: una fila por serie y una por ticker, con el nivel de fecha A–D, la marca de proyección y la de posible frontera con otro tema. **Análisis del nivel C** (D2): donde haya fecha real con la que comparar (ALFRED, ediciones archivadas), cuántos días se desvía la regla y si adelanta (peligroso) o retrasa (conservador). **BoE** (D6): una sola consulta a su `robots.txt` para ver si alguna ruta está permitida. Al final escribe y ejecuta `02_inventario` | `inventario_series.csv`, `inventario_precios.csv`, `fiabilidad_c.csv`, tests y notebook |
| A2 · Redundancia | En paralelo con A1 | Módulo `redundancia.py`. Correlación de los cambios por pares dentro de cada frecuencia, con solape mínimo. Mismo concepto en dos fuentes (por nombre e id de origen, más la correlación). Grupos de ETF por `bucket` y por la correlación de sus rentabilidades. Tabla de sensibilidad del umbral | `redundancia_pares.csv`, `redundancia_sensibilidad.csv` y tests |
| A3 · Crítico y verificador | Cuando acaban A1 y A2 | Revisa:<br>- la causalidad: historia por fecha de publicación, no por la de referencia;<br>- que las cifras cuadran con el `01`;<br>- que no salen valores en las salidas;<br>- la memoria con 10,5 M filas y 16 GB de RAM;<br>- los tests y el tamaño del notebook (< 2 MB).<br>Máximo 8 hallazgos; una ronda de corrección por A1 y A2 | Informe y verificación final |

Yo preparo las instrucciones de cada agente, reviso los diff, corro los tests, hago el commit en local, actualizo este
documento y me paro para que decidas D8–D10 con preguntas clicables. Unos 40 minutos.

## Paso 3 · `03_seleccion_eda`: plan (E1–E7 aprobadas el 2026-11-19 tal como se proponen)

**Qué hace.**
1. Aplica a las tablas del paso 2 las decisiones D1–D9 y saca la **lista curada**: una entrada por serie y por ticker
   con «se queda», «alias de X» o «fuera», y el motivo.
2. Hace un **EDA sencillo** de lo que se queda.
3. Deja escrito el **plan de preprocesado del paso 4, sin aplicarlo**: reglas de fecha conservadoras, tramos que se
   recortan, canónicos, proyecciones aparte y homogeneización de unidades.
4. Saca la **lista de descargas del paso 3b**.

El crudo y la base actual no se tocan.

**Entregables.**
- `config/lista_curada.yaml` (entrada del paso 4).
- `config/preprocesado.yaml` (borrador; no se ejecuta).
- `tablas/seleccion_resumen.csv`, `tablas/eda_*.csv` y `tablas/descargas_3b.csv`.
- El notebook `03_seleccion_eda`.

**Decisiones del paso 3** (propuesta primero; se preguntan de forma clicable antes de lanzar):

| # | Decisión | Propuesta |
|---|---|---|
| E1 | Cuál es el **canónico** de cada concepto en varias fuentes (p. ej. el 10 años: FRED, curva del Tesoro, Fase 1, ^TNX) | Regla automática por orden: mejor nivel de fecha (A > B > C) → más historia visible → mayor frecuencia → fuente oficial frente a derivada. El notebook enseña los casos en que la regla duda, para que los resuelvas tú |
| E2 | **Plazos vecinos de una curva** (salen como alias a 0,95: 1M, 2Y, 3Y, 7Y, 20Y del Tesoro…) | **No** se tratan como alias: la curva entera se queda, porque los agentes y la cartera pueden pedir cualquier plazo y la pendiente se calcula entre plazos. La regla de alias se aplica solo entre fuentes o entre versiones de una misma serie |
| E3 | **Versiones de Eurostat** (HICP v1/v2, agregados EA/EA20/EA21) | Se queda la zona euro de composición cambiante (la oficial de cada fecha) y una versión del HICP; el resto como alias |
| E4 | **Regla conservadora** de cada grupo «no medible» (D2) | La fecha más tardía plausible según el calendario documentado de cada fuente, a partir de `publicaciones.yaml`, las fichas y las notas de la sonda, con la fuente citada en el YAML. Sin red; si falta algún calendario, se te pregunta antes de buscarlo fuera |
| E5 | Tramo **«no fiable»** (antes de `fiable_desde`) | No se borra: pasa a una regla conservadora (la regla, más el adelanto máximo medido, más un margen). Así se conserva la historia sin dejar ver el futuro |
| E6 | **Fronteras** con los Temas 2 y 4 (122 y 8 series marcadas) | Se quedan de forma provisional con la marca «frontera» hasta que lo hables con tus compañeros; no bloquean el paso 3 |
| E7 | **Qué mira el EDA** | En series: huecos largos, saltos y rupturas de nivel, cambios de unidad entre vintages, escalas raras y rachas planas. En precios: saltos sin split (AAPL, ASML.AS, CL=F, NVDA, SHEL.L, ^VIX), contrasplits y aperturas iguales al cierre. Solo detecta y propone; no corrige |

**Plan con 3 agentes** (mismas reglas que en el paso 2):

| Agente | Cuándo | Qué hace | Entrega |
|---|---|---|---|
| B1 · Selección | En paralelo con B2 | Módulo `seleccion.py` y orden `seleccion`: aplica D1–D9 y E1–E3/E6 sobre `inventario_*` y `redundancia_*`, y genera la lista curada con su motivo y la lista del 3b. Al final escribe y ejecuta el `03` | `lista_curada.yaml`, `seleccion_resumen.csv`, `descargas_3b.csv`, tests y notebook |
| B2 · EDA y plan de preprocesado | En paralelo con B1 (trabaja sobre todo lo que no es «fuera» seguro) | Módulo `eda.py` y orden `eda` con los controles de E7. Borrador de `preprocesado.yaml` con E4 y E5 por grupo y regla, citando la fuente de cada calendario | `eda_*.csv`, `preprocesado.yaml` (borrador) y tests |
| B3 · Crítico y verificador | Cuando acaban B1 y B2 | Revisa:<br>- que la lista aplica de verdad las decisiones;<br>- que ninguna regla conservadora adelanta;<br>- que no quedan canónicos ambiguos sin señalar;<br>- que no hay valores en las salidas;<br>- tests y tamaño.<br>Máximo 8 hallazgos y una sola ronda de corrección | Informe |

Yo me encargo de las instrucciones de los agentes, la revisión, los tests, el commit en local, este documento y las preguntas
clicables al final. Calculo unos 45 minutos.

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
| 2 | Hecho (2026-11-17): módulos `inventario` y `redundancia` (órdenes del mismo nombre), 10 tablas de metadatos en `results/.../tablas/`, notebook `02_inventario` (230 KB). Crítico: 8 hallazgos, corregidos en una ronda. Pendiente de tus decisiones D2 (grupos «a decidir»), D6, D8, D9 y D10 | este |
| 3 | Hecho (2026-11-19): módulos `seleccion`, `eda` y `preprocesado` (órdenes del mismo nombre), `config/lista_curada.yaml`, `config/preprocesado.yaml` (borrador sin aplicar), 15 tablas y notebook `03_seleccion_eda` (0,84 MB, 11 figuras).<br>- Series: quedan 516, alias 105, fuera 570, proyecciones 243.<br>- Tickers: quedan 1.462 (26 con aviso de sospecha).<br>- Simulación: 1,07 M filas se retrasan y 0 se adelantan.<br>- 3b: 268 descargas.<br>Proceso: 3 constructores, 2 verificadores (16 hallazgos, corregidos en una ronda) y 2 agentes del notebook.<br>Pendiente de tus decisiones:<br>- Ken French (`pendiente_calendario`);<br>- fecha de creación de OFR FSI, Goyal-Welch y BIS (buscar fuera);<br>- Q1;<br>- canónicos dudosos;<br>- fronteras | este |
| 3b | Pendiente | |
| 4 | Pendiente | |
| 5 | Pendiente | |
