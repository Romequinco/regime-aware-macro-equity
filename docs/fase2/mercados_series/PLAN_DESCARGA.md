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

**Decisiones de cierre del paso 3 (2026-11-19):**

| # | Decisión | Qué se hace |
|---|---|---|
| F1 | Ken French antes de las ediciones archivadas | **Cadencia anual** (opción a, conservadora), **verificada** contra la historia real de la biblioteca (Wayback Machine). Si la verificación da otra cadencia, se usa la medida |
| F2 | Fecha de creación de OFR FSI, Goyal-Welch y BIS (brecha de crédito y DSR) | **Se busca en sus webs** y pasa a `publicado_desde`: no se puede ver nada antes de esa fecha |
| F3 | Q1 · fuente final de precios | **Solo Yahoo.** Los deslistados, los tickers sospechosos y los instrumentos sin precios en Yahoo se quedan como **limitación declarada** (sesgo de supervivencia medido en la sonda). No se paga ninguna fuente. Las filas del 3b que dependían de Q1 pasan a «no se descarga: limitación declarada» |
| F4 | Canónicos dudosos | Se acepta la regla E1. Los empates se resuelven a mano:<br>- `ecb:DFR` y `ecb:MRO` son tipos distintos: los dos se quedan como únicas;<br>- `datahub:SP500_MENSUAL` es una copia de Shiller: alias de `shiller:P`;<br>- Fama-French diario y mensual: los dos se quedan |
| F1–F2 · verificado en la web | Comprobado en la Wayback Machine y en páginas oficiales (2026-11-19) | **Ken French:** biblioteca visible desde 2001-12-18 (diario desde 2002-06, 5 factores desde 2014-12 y 2015-06). Antes de 2005-09, cadencia anual (la propia web decía «at least once a year»); desde entonces, mensual a 17–30 días, a veces más de 45 (regla 2M7D). Reconstruye toda la historia en cada actualización.<br>**OFR FSI:** público desde 2017-10-25.<br>**Goyal-Welch:** desde 2004-04-13; actualización anual de abril a noviembre de t+1. Los datos de 2022 nunca salieron sueltos, así que se ven desde 2024-04-15. Regla nueva: 13M.<br>**BIS:** brecha de crédito desde 2016-09-18 y DSR desde 2015-09-13; trimestral, unos 5,5 meses tras el trimestre |
| F5 | Fronteras con los otros temas | Las series numéricas del BCE y del BIS, SKEW, el ESI y UMCSENT se quedan en el Tema 1; los textos son del Tema 2 y del Tema 4. Las acciones: los precios, en el Tema 1; los informes, en el Tema 3, con la misma lista de empresas. Falta confirmarlo con los compañeros |

## Paso 3b · descargas (G1–G7 aprobadas el 2026-11-19, con el alcance reducido de H1)

**H1 · Alcance de esta tanda (decisión del usuario, 2026-11-19):** centrarse en el **S&P 500 y lo básico**, alineado con lo
que hacen los compañeros (el Tema 3 trabaja con empresas del S&P 500 y deja como opción el S&P 500 histórico con
constituyentes por fecha).

- **Entra en el 3b-1 (ahora):**
  - precios de todos los miembros del S&P 500 a cada fecha (el histórico desde 1996 que Yahoo sirva) y del núcleo del
    universo, refrescados hasta la fecha de corte;
  - redescarga de los truncados que sean del S&P 500;
  - refresco de las series que se quedan de EE. UU. (FRED/ALFRED, curva del Tesoro, Ken French, Shiller, Goyal-Welch,
    OFR) y de lo básico de mercado global (tipos de cambio y tipos oficiales del BCE, curvas soberanas);
  - archivo de las OAS de ICE (G4).
- **Se aplaza al 3b-2:**
  - los 131 instrumentos del universo sin precios (UCITS);
  - las acciones no estadounidenses del nivel ampliado;
  - las 15 series nuevas internacionales;
  - las ediciones del WEO;
  - los agregados del Banco Mundial;
  - el refresco de la macro internacional (OCDE, Eurostat, BIS, Banco Mundial, WEO).

  Siguen en `descargas_3b.csv` como pendientes.

**Qué hay.** `descargas_3b.csv` tiene 233 filas pendientes y 34 en limitación declarada (F3). Las pendientes, por tipo:

| Tipo | Filas | Qué es |
|---|---|---|
| Refresco | 26 | Poner al día, una a una, las fuentes de lo que se queda: 229 de FRED/ALFRED, 1.460 precios de Yahoo y 2 de Coinbase, BCE, OCDE… Último refresco: 2026-10-14 |
| Precios del universo | 131 | Instrumentos del universo sin fichero (93 ETF, 7 ETP, 13 futuros, 7 índices, 6 divisas, 4 de volatilidad), casi todos UCITS de Londres, Xetra y Suiza |
| Redescarga | 9 | Ficheros truncados (AT, AVB, BLY, EA, EQR, LEG, PSKY, QRVO, WBD) |
| Series nuevas | 15 | Agregados del Banco Mundial (mundo, renta media/baja, UEM), agregados del WEO, zona euro (EA) del ESI y del paro de Eurostat, CLI EA20 y paro de China de la OCDE, 3 de Philadelphia, historia de BoC antes de 2001 y de RBA antes de 2011 |
| Ediciones del WEO | 37 | Abril y octubre de 2008 a 2026; DBnomics lo prohíbe en `robots.txt` |
| Archivo periódico | 9 | OAS de ICE (FRED solo guarda 3 años) y ediciones académicas |
| Fechas, vintages, constituyentes | 6 | Deudas de verificación (H.15 antes de 2005, calendarios de Eurostat, vintages de BCE/BIS/BM, Nikkei e Ibovespa) |

**Decisiones del 3b** (propuesta primero):

| # | Decisión | Propuesta |
|---|---|---|
| G1 | Alcance | Se hacen las prioridades alta y media. Lo de prioridad baja (vintages de BCE, Eurostat, BIS y BM; constituyentes de Nikkei e Ibovespa; calendarios de Eurostat) pasa a limitación declarada: no hay fuente gratuita y legal. Las fechas de H.15 antes de 2005, de Ken French y de las académicas ya quedan cubiertas por F1, F2 y las reglas conservadoras: se marcan como resueltas |
| G2 | Fecha de corte del dataset | **Fijada: 2026-11-13** (último viernes con cierre completo antes del 3b-1). Las fuentes acaban entre el 11-16 y el 11-19, así que todas lo cubren. El corte **se aplica en el paso 4**: la base curada y los precios curados no llevan nada con `fecha_publicacion` posterior. La base de trabajo y el crudo guardan lo posterior para el siguiente refresco |
| G3 | Ediciones del WEO | Se buscan en el archivo oficial del FMI (`imf.org`, base de datos del WEO por edición) solo si su `robots.txt` lo permite. Si no, limitación declarada. DBnomics, no |
| G4 | Archivo de las OAS de ICE | Una orden nueva, `archivar-oas`, que guarda en el corpus la ventana actual de FRED con la fecha de captura y la une a las capturas anteriores sin perder historia. Se ejecuta ahora y después a mano cada mes (o con una tarea programada en el PC si lo prefieres) |
| G5 | Precios del universo (131) | Se intentan todos en Yahoo con el mismo adaptador (as-traded, reanudable). Los que Yahoo no sirva pasan a limitación declarada (F3) |
| G6 | Después de descargar | Se reconstruye la base (`construir-base`) y se regenera la cadena de los pasos 2 y 3 (inventario, redundancia, EDA, selección, preprocesado). Si la lista curada cambia más allá de las series y tickers nuevos, me paro y te lo enseño |
| G7 | Ejecución | Descargas largas en segundo plano (`Start-Process`) desde esta rama, sin cambiar de rama mientras duran. Todo reanudable y con registro |

**Plan con agentes:**

| Agente | Cuándo | Qué hace |
|---|---|---|
| C1 · Refresco y redescarga | En paralelo | Comprueba que cada descargador sabe traer solo lo nuevo; si no, lo dice antes de lanzar. Lanza en segundo plano el refresco de las 26 fuentes hasta la fecha de corte y la redescarga de los 9 truncados. Vigila los registros |
| C2 · Series nuevas | En paralelo | Código mínimo en los extractores de `worldbank`, `imf`, `eurostat`, `oecd`, `philly_rtdsm` y bancos centrales para las 15 series nuevas, con su catálogo, fecha de publicación (regla conservadora si no se puede medir) y tests. Las descarga |
| C3 · Universo, WEO y OAS | En paralelo | Fichero de los 131 tickers y descarga en Yahoo (G5). Comprueba `robots.txt` del FMI y, si lo permite, descarga las ediciones del WEO (G3). Orden `archivar-oas` y primera captura (G4) |
| (yo) | Al acabar los tres | `construir-base`, cadena de los pasos 2 y 3, diferencias de la lista curada (G6), `descargas_3b_estado.csv` con lo hecho, lo pendiente y lo que pasa a limitación |
| V1 · Fechas | Al final | Las filas nuevas respetan el TimeGate: ninguna `fecha_publicacion` anterior a su disponibilidad real, refresco sin adelantar nada, aperturas de los nuevos tickers |
| V2 · Cobertura | Al final | Cada fila del 3b está hecha, en limitación con su motivo o pendiente con causa. Recuentos coherentes. Ningún valor en el repo |

El 3b no tiene notebook propio: su resultado se verá en el `05_resultado`. Tiempo: el código, alrededor de una hora; las descargas, varias horas en segundo plano (la de Yahoo es la más larga).

## Paso 3b-2 · el resto de descargas: HECHO (2026-11-20)

**Resultado:**

- **Precios:**
  - 125 instrumentos del universo descargados (UCITS, futuros, índices y divisas);
  - 613 acciones no estadounidenses refrescadas;
  - 12 que Yahoo revisó, con lo guardado conservado.
- **WEO:** ediciones 2025-04, 2025-10 y 2026-04 por la API SDMX del FMI, con sus agregados 001, 163 y 200. Los de la zona euro pasan a alias por D9.
  Las otras 34 ediciones quedan como limitación: `www.imf.org` responde 403 al `robots.txt`.
- **Banco Mundial:** agregados WLD, LMY y EMU.
- **Bancos centrales:** historia del RBA desde 1990 y objetivo mensual de la BoC desde 1996.
- **Refrescos:** BIS, Eurostat, OCDE (edición 202611), Banco Mundial y Philadelphia.
- **Limitaciones medidas:**
  - zona euro cambiante de Eurostat;
  - CLI EA20 y paro de China de la OCDE;
  - tres series de Philadelphia que ya cubre ALFRED.
- **Base:** 10.620.113 filas y 1.521 series, sin perder nada.
- **Base curada:** 533 series.
- **Precios curados:** 1.616 tickers.
- **Avisos nuevos:** historia recortada (18), no llega al corte (21) y UCITS con correlación < 0,90 (23).
- **Estado** (`descargas_3b_estado.csv`, comprobado con evidencia del corpus): 48 hechos, 1 parcial, 3 resueltos, 124 limitaciones y 1 aplazado (cartera 60/40 europea, derivada).
- **Verificación:** dos verificadores (sin fallos de TimeGate; 1 hallazgo alto de cobertura, D9 en el WEO, corregido) y suite con 1.270 tests en verde.

### Plan con el que se lanzó

Lo aplazado por H1 en `descargas_3b_estado.csv`:

| Grupo | Filas pendientes | Qué incluye |
|---|---|---|
| Precios | 751 | 126 instrumentos del universo sin fichero (UCITS de Londres, Xetra y Suiza, futuros, índices, divisas) y refresco de los 623 no estadounidenses del ampliado y de 2 del universo |
| Macro internacional | 6 | Refresco de OCDE, Eurostat, BIS, Banco Mundial, WEO y Philadelphia |
| Series nuevas | 15 | Agregados del Banco Mundial (WLD, LMY, EMU) y del WEO (001, 163, 200), zona euro (EA) del ESI y del paro, CLI EA20 y paro de China de la OCDE, 3 series de Philadelphia, historia de BoC y RBA |
| Ediciones del WEO | 37 | Solo del archivo oficial del FMI y solo si su `robots.txt` lo permite (G3); DBnomics, no |

Agentes:
- **R1 · precios**, en segundo plano.
- **R2 · FMI y BIS**: ediciones y agregados del WEO, y refresco del BIS.
- **R3 · fuentes macro**: Banco Mundial, Eurostat, OCDE, Philadelphia, BoC y RBA, con las series nuevas y su refresco.

Después, la cadena completa (base, pasos 2–3, `curar`, `curar-precios`, estado), los verificadores y los notebooks `03` y `04` regenerados con las cifras nuevas.

## Paso 4 · `04_preprocesado` (lanzado el 2026-11-20)

Aplica a la base de trabajo **sin tocarla** el plan ya decidido:
- `lista_curada.yaml` (pasos 2–3 y 3b);
- `preprocesado.yaml` (E4, E5, reconstruidas, H.15 antes de 2005, tope del primer vintage, escalas por vintage);
- el corte G2 (2026-11-13).

Escribe en el corpus, fuera del repo:

| Salida | Contenido |
|---|---|
| `series/base_curada.parquet` | Mismo contrato que la base. Solo las series que se quedan (también las de `historia_previa`), con las fechas curadas, las escalas corregidas, nada publicado después del corte y las derivadas recalculadas con los componentes curados |
| `series/alias.parquet` | Alias → canónico, motivo y correlación (sin valores) |
| `series/proyecciones.parquet` | Las proyecciones en su tabla aparte: 309 (WEO y SEP) al cerrar el paso 4; 3 del SEP tras el saneado (P16 saca el WEO) |
| `series/registro_cambios.parquet` | Antes y después de cada fecha o escala cambiada |
| `precios_curados/<proveedor>/` | Los tickers que se quedan, hasta el corte y con las propuestas del EDA aplicadas (las velas de relleno fuera de calendario se quitan y las aperturas de relleno pasan a nulo). Los avisos van en `tablas/precios_curados_avisos.csv` |

En el repo solo van resúmenes de metadatos (`tablas/curada_*.csv`) y el notebook `04_preprocesado`. Las tools
`get_serie` y `get_precios` ganan un modo curado.

**Agentes** (igual que en el paso 3):

| Fase | Agentes | Qué hacen |
|---|---|---|
| Construcción | P1 (series), P2 (precios), P3 (tools) | En paralelo |
| Verificación | V1 (TimeGate), V2 (coherencia) | Las verificaciones de `salidas_paso4` de `preprocesado.yaml` |
| Corrección | P1, P2, P3 | Una sola ronda |
| Notebook | N1 (lo construye), N2 (pulido visual) | `04_preprocesado` |

## Saneado (2026-11-21)

Auditoría de solo lectura y saneado con las opciones que eligió el usuario en el HTML: detalle, cifras y estado de
cada pendiente (P01–P35) en [`AUDITORIA_SANEADO.md`](AUDITORIA_SANEADO.md#resultado-del-saneado-2026-11-21).

**Después del saneado:**
- **Base de trabajo:** 10.675.327 filas de 1.523 series.
- **Base curada:** 10.212.510 filas de 514 series. Salen 48: las 28 del WEO y 20 paradas. Entran 27 que eran alias,
  ahora como historia previa, y 2 nuevas.
- **Alias y proyecciones:** 59 alias; 3 proyecciones, todas del SEP.
- **Precios curados:** 1.494 tickers. Salen 112 reutilizados y 10 con huecos de más de 5 sesiones (^SKEW y 4 futuros se quedan por excepción).
- **Verificaciones:** las 13 + 13 siguen en 0, y hay 5 nuevas de precios, también en 0. P15 (Wayback) se probó y se descartó.
- **Corte:** sigue en 2026-11-13, en un solo sitio (`config/corte.yaml`).
- **Refresco:** `refrescar --corte`. Las tools leen la base curada por defecto.

**Cifras de este documento que el saneado corrige:**
- **Nulos de `fred_alfred`:** no son «casi todos festivos». Solo 6 de los 26.200 nulos lo eran.
- **Alias con historia anterior a 2000:** 26, no 25.
- **Proyecciones:** 309, no 243.
- **Tickers sospechosos:** 37.
- **Historia recortada:** la cifra buena es 18, la de los avisos (P26); la de `descargas_3b_estado.csv` es 16.

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
| 3b | **3b-1 HECHO (2026-11-19/20; alcance H1)**:<br>- **Series:** FRED vivo, ALFRED (161), BCE, curvas, BoC/BoJ/RBA, Ken French (edición 2026-10), Shiller, GW, OFR y 23 índices `yf:` desde el almacén de precios (^GSPC, ^VIX…, rendimientos del Tesoro).<br>- **Precios:** 834 del S&P 500 y del núcleo al día, 6 altas del S&P (BE, P, VYLR, TWLO, OKTA, SKYD) y Coinbase.<br>- **OAS de ICE:** `archivar-oas`; la primera captura recupera 29 días.<br>- **Base:** 10.598.317 filas, sin perder ninguna. Las fuentes sin historia de revisiones solo crecen (132 valores anteriores del BCE conservados y 130 revisiones fechadas desde su observación). Copia previa rotatoria y `tablas/solo_anadir_ultima.csv`.<br>- **Estado** (`tablas/descargas_3b_estado.csv`): 28 hechos, 3 resueltos, 61 limitaciones declaradas y 187 aplazadas al 3b-2.<br>- **Limitaciones principales:** Bundesbank (anti-bots); 112 tickers del S&P reutilizados; KVUE y los truncados; la composición del S&P posterior al 2026-08-18 (fja05680 sin cambios); ^BCOM, ^W5000 y GC=F.<br>- **Cobertura histórica del S&P 500:** 67,8 % de los días-tramo (`tablas/sp500_cobertura_3b1.csv`).<br>- **Corte G2 (2026-11-13):** se aplica en el paso 4.<br>**Pendiente: 3b-2** (UCITS, acciones no estadounidenses, macro internacional, series nuevas, ediciones del WEO) | este |
| 4 | **HECHO (2026-11-20; cifras actualizadas tras el 3b-2).**<br>**Base curada** (`curada.py`, orden `curar`):<br>- 10.189.709 filas de 533 series, corte 2026-11-13.<br>- 1.426.536 filas retrasadas por las capas del plan y 0 adelantadas.<br>- Escalas por vintage (6 series) y unidades homogeneizadas (27).<br>- Derivadas recalculadas.<br>- 109 alias y 309 proyecciones en tablas aparte.<br>- Registro de cambios y manifiesto firmado; publicación atómica.<br>**Precios curados** (`curada_precios.py`, `curar-precios`):<br>- 1.616 tickers.<br>- 29.611 velas de relleno quitadas.<br>- 430.050 aperturas de relleno anuladas (las que tienen volumen, con aviso propio).<br>- VBMFX y ^SKEW, sin apertura.<br>**Tools:** `get_serie`/`get_precios(base='curada')`, `get_proyeccion`, alias con aviso y aviso de datos atrasados.<br>**Verificaciones:** 13 + 13 en 0, revisadas por dos verificadores y corregidas en una ronda.<br>**Notebook:** `04_preprocesado`.<br>**Pendientes menores:** USD de las series en CNY sin fixing visible; la historia anterior a 2000 de 26 alias solo estaba en la base de trabajo (resuelto en el saneado, P24) | este |
| 5 | **Notebook `05_resultado` hecho (2026-11-20)**: la foto final del dataset (533 series de 23 fuentes, 1.616 tickers, corte 2026-11-13, 26 verificaciones en 0, 124 limitaciones declaradas). **Pendiente:** el catálogo formal para los agentes, destilar este plan en el README, integrar main (3 commits del Tema 2) y la PR | este |
| saneado | **Hecho (2026-11-21)**: auditoría (35 pendientes) y saneado elegido por el usuario; ver [`AUDITORIA_SANEADO.md`](AUDITORIA_SANEADO.md). notebooks `03`–`05` regenerados | rama `fase2/t1-saneado` |
