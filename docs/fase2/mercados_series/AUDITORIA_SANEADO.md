# Tema 1 · Auditoría de saneado (2026-11-21)

> **Pregunta del usuario:** «¿Aún queda mucho para sanear todos los datos?»
>
> **Respuesta corta:** no tanto como parece. Los datos que ya tenemos no tienen errores graves: no hay fechas que vean el
> futuro, ni escalas mal puestas, ni datos que el curado haya perdido. Quedan **35 pendientes** (5 bloqueantes,
> 14 importantes y 16 cosméticos), y casi todos son de código o recálculo que se hacen sin red. Los 5 bloqueantes son
> 4 arreglos de código cortos y una regla para el sesgo de supervivencia. Solo en 5 pendientes lo recomendado es no
> hacer nada y declararlo como limitación.

**Alcance.** Solo lo que ya tenemos: las 533 series de la base curada, la base de trabajo y los 1.616 tickers de precios
curados del Tema 1, con el corte 2026-11-13. No entran el catálogo para los agentes ni las tools nuevas.
Las opciones de cada pendiente se eligen en un HTML local (`docs/tfm/internos/tema1_saneado/opciones.html`, ignorado
por git). **Aquí no se aplica ningún arreglo.**

## Cómo se ha hecho

| Fase | Quién | Qué |
|---|---|---|
| A · Auditoría | 3 agentes en paralelo | Ángulo 1: huecos y nulos (N01–N14). Ángulo 2: frescura y vintages (F01–F07, V01–V08). Ángulo 3: sanidad, consistencia y limitaciones (C01–C11, L01–L10). 50 hallazgos |
| A · Verificación | 1 verificador adversarial | Recalcula con código propio la cifra clave de cada hallazgo y comprueba las 35 referencias fichero:línea. Resultado: **41 confirmados, 6 corregidos, 3 duplicados, 0 no reproducibles** |
| B · Opciones | 1 asesor | Agrupa los hallazgos en 35 pendientes y propone de 2 a 5 opciones para cada uno, con coste, red, riesgo, beneficio y recomendación. Comprueba en la web las fuentes alternativas |

Todo ha sido **solo lectura**: nada descargado, reescrito ni publicado en `D:`. Una foto de los 7.545 ficheros del
corpus antes y después de los tests no cambia. Las cifras salen de los scripts de
[`src/ingesta/mercados_series/auditoria_saneado/`](../../../src/ingesta/mercados_series/auditoria_saneado/README.md),
no de copiar el plan. Ninguna salida lleva valores de series ni precios: solo recuentos, fechas, porcentajes e ids.

## La respuesta en cifras

| | Pendientes |
|---|---|
| Bloqueantes | 5 |
| Importantes | 14 |
| Cosméticos | 16 |
| **Total** | **35** |

Opción recomendada por clase:
- 14 arreglos de código;
- 10 recálculos sin red;
- 3 descargas gratis de la misma fuente;
- 3 fuentes alternativas gratuitas, comprobadas en la web;
- 5 «no hacer nada» y declararlo como limitación.

Es decir, 30 pendientes tienen un arreglo que no cuesta dinero, y 24 de ellos no necesitan red.

**Lo primero:** los 4 bloqueantes de código, que suman unas 5–7 horas:
- las tools con `base='curada'` por defecto;
- el aviso de tickers reutilizados;
- la subunidad USX;
- el dólar taiwanés, el único de los cuatro que necesita red (FRED).

Después van la regla del sesgo de supervivencia y los 17 tickers sin refrescar.

## Lo que está bien (no es pendiente)

| Id | Comprobado |
|---|---|
| N01 | Los **26.200** `valor` nulos de la curada (94 series: fred_alfred 19.619, boe_curvas 5.490, mof_jgb 1.085, boc_curva 6) llevan todos su nota. Son información real a esa fecha:<br>- 15.688 son de vintages antiguos que luego traen el dato;<br>- 3.138 son datos retirados en un vintage posterior;<br>- 7.374 no tienen ningún valor (casi todo plazos de curva que no se publicaban ese día).<br>**Solo 6 son festivos** (BoC, 2006-09-04): el plan decía «casi todos festivos», y no es así. No se rellenan ni se borran |
| N06 | La curada no pierde ningún dato interior de la base de trabajo. Solo faltan 513 periodos: 502 al final de la serie, que la fecha prudente deja después del corte, y 11 al arranque de una derivada de 1928 |
| N08 | VBMFX y ^SKEW no tienen apertura de origen (fondo con valor liquidativo e índice) y llevan su aviso `sin_apertura` |
| N09 | Se han quitado 29.611 velas de relleno: el recuento propio, la tabla y el aviso cuadran. Hay 0 sesiones posteriores al corte |
| N14 | Los 660 huecos largos del EDA (81 series) son casi todos reales de la fuente: ISK 2008–2018, DTB1YR 2002–2008… |
| F01 | 487 de 533 series curadas están al día en el corte. De lo parado, 27 series están retiradas por la fuente y bien marcadas |
| V03 | El vintage «unico» está en el **17,07 %** de las filas (1.739.542). El 93,7 % son mercado, tipos de cambio y curvas, que no se revisan. Lo revisable es el 1,07 % (109.127 filas) y lleva aviso |
| C01 | Cada serie tiene una sola unidad y una sola divisa, y no queda ningún salto ×100 o ×1000 lejos de cero. Las filas ×100 son 34.116 en el registro y 34.029 en la curada (87 caen por el corte) |
| C04 | La cifra buena de tickers sospechosos es **37**, de los que 36 se quedan (BLY sale). El 35 y el 36 de otras tablas se explican por BLY e IBTS.L |
| C08 | Capas de fecha: **1.426.536** filas retrasadas y **0** adelantadas |
| C10 | Verificaciones: 13 + 13, de las que 25 dan 0 y 1 no aplica. Tests del tema con el corpus: **1.257 pasan, 0 fallan y 30 se saltan** (en vivo o sin `data/raw`). Enlaces y estructura: 10 pasan. Sin el corpus (worktree sin `.env`) pasan 1.217 y se saltan 70 en silencio (ver P32) |
| L01 | El estado del 3b cuadra: 48 hechos, 1 parcial, 3 resueltos, 124 limitaciones y 1 aplazado (177 filas). Las 124 limitaciones son 119 ids distintos, agrupados en 13 causas |
| L09 | 346 de 533 series (**64,9 %**) se ven desde 2000; el plan decía 347. Por fecha de referencia serían el 83,5 % |
| L10 | Philadelphia no tiene filas a propósito (ALFRED ya la cubre), y los calendarios antiguos de Eurostat están cubiertos por las reglas prudentes |

## Hallazgos por ángulo (cifras verificadas)

### Ángulo 1 · Huecos y nulos

- **N02.** `boe:NOM.6M` está vacío en 1.299 de 3.504 días desde 2013 (37,1 %). Es el 80 % de los nulos visibles desde 2000.
- **N03.** Octubre de 2025 no existe en 21 series de EE. UU. (UNRATE, CPIAUCSL…) por el cierre del Gobierno.
- **N04.** 3.126 periodos de 22 series se publicaron y luego aparecen nulos al corte; 218 de ellos son desde 2000. La
  inflación mediana y recortada de Cleveland pierde agosto y septiembre de 2026 en el vintage del 2026-11-10. Puede
  ser un fallo de ALFRED o del cargador.
- **N05.** Quedan 6 filas nulas del Labour Day canadiense de 2006.
- **N07.**
  - 0 cierres nulos en 10.825.522 sesiones.
  - 430.050 aperturas anuladas a propósito (3,97 %); en el crudo eran 0 nulas.
  - 135.969 de ellas tenían volumen, en 1.182 tickers.
  - El 67 % son anteriores a 2000; desde 2007 quedan 91.498 y desde 2016, 43.222.
  - Londres es lo más afectado. 90 tickers tienen más del 20 % de aperturas vacías (88 sin contar VBMFX y ^SKEW).
- **N10.** Faltan 9.126 sesiones en 653 tickers, con el calendario del EDA desde 1990. Con calendarios desde 1962 serían
  683 tickers y 11.338 sesiones. Solo 17 tickers tienen un hueco de más de 5 sesiones seguidas y 7, de más de 20:
  BGEO.L 262, CNY=X 153, KVUE 13 justo antes de salir.
- **N11.** 21 tickers no llegan al corte:
  - 14 se quedaron parados porque Yahoo retocó una vela antigua y el almacén rechazó el ticker entero (`ErrorContrato`); les faltan 23–25 sesiones;
  - 4 son reutilizados (DWD, GR, GP y LU);
  - además, PARA→SKYD, KVUE (adquirido) y SNDK, con un hueco de 23 sesiones.

  Los que acaban el 2026-11-12 son 40 (38 + 2 de Coinbase) y están bien: su cierre del día 13 se publica después del corte.
- **N12.** 8 ficheros solo están en el crudo (AVB, BLY, EA, EQR, LEG, PSKY, QRVO y WBD). Son truncados de empresas que
  salieron del S&P 500.
- **N13.** La regla de `tools.py` (max(10, 3×ritmo) días hábiles, solo para diarias y semanales) marca 28 series:
  - 24 retiradas por la fuente;
  - 4 activas sin refrescar (Bundesbank, GC=F, ^BCOM y ^W5000).

  Las mensuales y trimestrales paradas no avisan.

### Ángulo 2 · Frescura y vintages

- **F02.**
  - La base de trabajo tiene 14.849 filas posteriores al corte (0,14 %), de 828 series. De ellas, 10.051 ya se han publicado a fecha de hoy y 4.798 llevan fechas futuras (reglas prudentes y proyecciones del SEP hasta 2029).
  - En las series curadas son 9.980 filas de 214 series. En precios, 5.748 sesiones de 1.596 tickers.
  - El corte está escrito en el código en 4 sitios: `curada.py:79`, `curada_precios.py:89`, `seleccion.py:864` y `estado_3b.py:63`. Hay otras 2 fechas fijas: `estado_3b.py:73` y `seleccion.py:165`.
- **F04.** 8 series desfasadas que otro refresco no arregla:
  - Bundesbank (29 días);
  - GC=F, ^BCOM y ^W5000 (118 días);
  - el IPC de la OCDE de EA20, Francia e Italia (257 días);
  - el ESI EA20 (309 días).
- **F05.** 13 series marcadas «activa» ya no las publica la fuente: Eurostat 5, OCDE 4, BIS 3 y Philadelphia 1.
- **F06.** No hay una orden única de refresco (ver más abajo).
- **F07.** 65 pares de series tienen una correlación entre 0,94 y 0,96, junto al umbral 0,95 de alias. Volver a lanzar
  `seleccion` puede cambiar la lista curada (`seleccion.py:1351` reescribe `lista_curada.yaml`).
- **V01.**
  - Aviso «posible fuga de revisiones»: **430.665** filas (**4,23 %**) en 94 series, marcado en `nota`. Ken French es el 68,7 %.
  - A la lista de fuentes del plan le falta el BCE (372 filas).
  - Otras **74.530** filas (0,73 %) anteriores a ALFRED tienen un valor ya revisado sin la etiqueta: 73.559 de FRED y 971 de `philly:ROUTPUT`. Con ellas, la fuga posible es el **4,96 %**.
- **V02.** Hasta 355.151 filas tienen ediciones antiguas en la Wayback Machine (Ken French, Shiller, Goyal-Welch, OFR).
  Para el Banco Mundial están los archivos del WDI, y para Eurostat y el BCE, las bases de revisiones del BCE y de la OCDE.
- **V04.** El solo-añadir tiró 463 correcciones el 2026-11-20: Eurostat 372, BIS 86 y RBA 5. Una serie no puede mezclar
  «unico» con fechas (`contrato.py:337-340`, `base.py:613`). Solo el BCE guarda versiones (132 filas).
- **V05.** El archivo de las OAS de ICE tiene 3 capturas (2026-10-12, 2026-10-13 y 2026-11-19), con 822 fechas por serie
  desde el 2023-10-10. Saltarse un mes no pierde historia; lo anterior a 2023-10 no se puede recuperar.
- **V06.** El WEO tiene 4 ediciones (2025-04, 2025-10, 2026-04 y 2026-10) y le faltan 34 (de 2008-04 a 2024-10). No se ve
  nada antes del 2025-04-22. Son 28 series en la curada y 306 de proyección.
- **V07.** Ediciones académicas archivadas: Ken French 3, Shiller 1 y Goyal-Welch 2. Solo hubo 2 días de descarga.
- **V08.** `preprocesado.yaml:345` describe USRECD como «vintage_exacto», pero se fecha con una regla de 24 meses.

### Ángulo 3 · Sanidad, consistencia y limitaciones

- **C02.**
  - 1.651 saltos de más del 50 % sin split, en 203 tickers. Casi todos están en tickers marcados como sospechosos o reutilizados.
  - Fuera de esas marcas quedan 298 saltos en 157 tickers; 27 son ×10 o ÷10, en 14 tickers.
  - **Los 157 tienen el aviso `salto_sin_split` en `precios_curados_avisos.csv`, pero `get_precios` no lee esa tabla.** El auditor decía «311 sin ningún aviso»: lo corrigió el verificador.
- **C03.** Hay 112 tickers reutilizados marcados. Ninguno mezcla dos empresas, pero los precios son de la empresa equivocada
  y `get_precios(base='curada')` no lo avisa.
- **C05.** 27 de 109 alias empiezan antes que su canónico y 26 de ellos antes de 2000 (el plan decía 25). En 2 se pierde
  toda la historia previa: DFF→EFFR y el IPC de China del Banco Mundial→`oecd:CP.CHN`.
- **C06.** `get_serie` y `get_precios` usan `base='trabajo'` por defecto (`tools.py:19`).
- **C07.**
  - USX: los futuros de maíz, soja y trigo salen 100 % nulos en USD (19.768 sesiones), porque `divisas.SUBUNIDADES` no tiene USX.
  - TWD: el BCE dejó de publicarlo el 2020-10-30, así que 2330.TW y ^TWII se convierten con un fixing caducado (1.465 sesiones cada uno).
  - El CNY solo pierde 618 sesiones anteriores a 2000.
- **C09.** 16 reglas añaden 14 días o más de mediana y al menos doblan el retraso original:
  - el paro semanal ICSA pasa de 5 a 61 días entre 2007 y 2009-05, y las peticiones continuadas, de 13 a 68;
  - la tabla F1 del RBA hereda la regla de 7 días de la F2.
- **L02.** Sesgo de supervivencia:
  - el 67,78 % de los días-tramo del S&P 500 tiene precio según la tabla (67,45 % recalculado por el verificador);
  - desde 2007 es el 78,7 %, y desde 2016, el 88,5 %;
  - el día de Lehman tienen precio 302–305 de 498 miembros.
- **L07.** Son 21 series de la zona euro (no 18). 5 usan la composición de cada fecha y al menos 7 usan la composición fija
  justo donde importa (entre ellas el PIB real EA21 del BCE).
- **L08.** Los 6 baselines de cartera se calcularon el 2026-10-13 con la base de trabajo y acaban el 2026-10-12. La 60/40
  europea está aplazada; la 60/40 UCITS empieza el 2017-11-30 y no tiene versión con costes.

## Los 35 pendientes y la opción recomendada

Orden: gravedad y, dentro de ella, importancia. Las opciones completas (coste, red, riesgo y beneficio de cada una)
están en el HTML.

| Id | Pendiente | Gravedad | Opción recomendada | Clase | Hallazgos |
|---|---|---|---|---|---|
| P01 | Las tools leen la base de trabajo si no se les dice nada | Bloqueante | b) Cambiar el defecto a base='curada' y pedir 'trabajo' a mano solo en los módulos que construyen la base | código | C06 |
| P02 | Tickers reutilizados: precios de otra empresa sin aviso en la tool | Bloqueante | b) Que get_precios devuelva el aviso de la lista curada (reutilizado, sospechoso, historia recortada, UCITS poco parecido) y redirigir PARA a SKYD | código | C03, L04, N11 |
| P03 | Dólar taiwanés congelado en 2020 al pasar a USD | Bloqueante | c) Tope de b + cambio secundario de la Fed (H.10) en FRED: DEXTAUS para TWD (y DEXCHUS para CNY), con su calendario | fuente alternativa | C07 |
| P04 | Tres futuros en centavos de dólar salen vacíos en USD | Bloqueante | b) Añadir USX → (USD, 100) a SUBUNIDADES y un test | código | C07 |
| P05 | Sesgo de supervivencia en el S&P 500 histórico | Bloqueante | b) Medir el sesgo y fijar la regla: en cada fecha, solo miembros con precio y con aviso; la cartera principal con índices y ETF, y las acciones como prueba aparte con el sesgo medido | recálculo | L02, N12, L04 |
| P06 | 17 tickers sin refrescar por una vela retocada o un fallo de descarga | Importante | b) Tolerar revisiones OHLC aisladas (se conserva la vela guardada, la revisión se apunta y se añaden las sesiones nuevas, como ya se hace con volumen y dividendo) y redescargar los 14, SNDK y KVUE | código | N11, F03, L06, N10 |
| P07 | El corte está escrito en el código y refrescar son unos 20 pasos a mano | Importante | c) Orden única «refrescar --corte»: descargas reanudables en segundo plano, bucle de ALFRED y FRED, excepciones, curar y curar-precios con el corte por argumento y un estado genérico; lista congelada por defecto y --reseleccionar solo con diff y parada (G6) | código | F02, F06, F07 |
| P08 | Precio de ejecución en t+1: aperturas vacías sin regla de reserva | Importante | c) Apertura de t+1 con reserva: si falta, cierre de t+1 con aviso (nunca el de t); el cierre de t+1 como prueba de sensibilidad | código | N07, N08 |
| P09 | Inflación y confianza de la zona euro paradas en su serie canónica | Importante | b) Cambiar el canónico al ESI EA21 y al HICP (Eurostat/BCE) desde donde para el viejo, con el viejo como historia previa (como las 9 que ya se empalman) | recálculo | F04, F05 |
| P10 | Series paradas que no avisan: el aviso solo mira diarias y semanales | Importante | c) b + extender el aviso a todas las frecuencias (umbral = retraso mediano + 2 periodos + margen), sin avisar en las que se retrasan por diseño | código | N13, F05 |
| P11 | Saltos de precio sin split: el aviso existe en la tabla, pero la tool no lo enseña | Importante | c) b + revisar a mano los 27 ×10 y dejar vacía esa sesión (o marcarla) con registro | recálculo | C02, C04, L04 |
| P12 | Paro semanal con 8 semanas de retraso en 2007–2009 por exceso de prudencia | Importante | b) ICSA y continuadas con el calendario del DOL (jueves siguiente + margen corto), que ya está en publicaciones.yaml, y separar rba:FIRMMCRTD de la regla de la tabla F2 | recálculo | C09 |
| P13 | El «solo añadir» tira las correcciones de Eurostat, BIS y RBA | Importante | b) Pasar esas series a vintage con fecha (lo guardado con la fecha de su primera descarga; cada corrección con su fecha de observación), como ya se hace con el BCE | código | V04 |
| P14 | Las ediciones mensuales se pierden si nadie descarga cada mes | Importante | c) Tarea programada mensual en el PC (archivar-oas, académicas y FRED vivo) y archivar las ediciones de la OFR en vez de sobrescribir | código | V07, V05, V03 |
| P15 | 4,23 % de las filas llevan el valor de hoy, no el de entonces | Importante | b) Recuperar ediciones de la Wayback Machine para Shiller, OFR y Ken French (vintage = fecha de captura, igual o posterior a la publicación: prudente) | fuente alternativa | V01, V02 |
| P16 | El WEO no tiene ediciones antes de 2025: no sirve para el backtest | Importante | b) Que tú bajes a mano, en el navegador, el fichero oficial de previsiones históricas (uno solo, desde 1990, indicadores clave) y el extractor lo lea sin red | fuente alternativa | V06, L03 |
| P17 | Inflación de Cleveland: agosto y septiembre de 2026 vacíos al corte | Importante | b) Comprobar en ALFRED el vintage del 2026-11-10 y, si es un fallo, redescargar esas dos series | gratis | N04 |
| P18 | Cartera: baselines hechos con la base de trabajo y 60/40 europea sin montar | Importante | c) b + montar la 60/40 europea desde el 2017-11-30, con costes y sin empalme | recálculo | L08 |
| P19 | El tipo a 6 meses del Reino Unido falta 1 de cada 3 días desde 2013 | Importante | b) Aviso en get_serie con el % de vacíos de la serie en la ventana pedida (sirve para todas) | código | N02 |
| P20 | Zona euro contada siempre con todos sus países de hoy | Cosmético | b) Preferir la versión U2/EA (composición de cada fecha) cuando ya está en la base y avisar en las fijas | recálculo | L07, L10 |
| P21 | Oro, materias primas y Wilshire 5000 parados desde julio en las series | Cosmético | b) Rehacer yf:GC=F y yf:^W5000 desde el almacén de precios (como los 23 índices del 3b-1), poner ^W5000 en XNYS y dar ^BCOM por alias de DBC (al día) o por retirada | recálculo | F04, N13, N10 |
| P22 | Bundesbank: el 10 años alemán parado en 2026-10-13 | Cosmético | b) Empalmar: Bundesbank como historia previa y, desde donde para, el 10 años de la curva diaria AAA del BCE (ya en la base), con aviso | recálculo | L05, F04, N13 |
| P23 | Sin vintages de BCE, Eurostat, BIS y Banco Mundial | Cosmético | a) No hacer nada, pero corregir el motivo de G1 («existe fuente; no compensa») | nada / limitación | L10, V02, V03 |
| P24 | 26 alias con historia anterior a 2000 que la curada no usa | Cosmético | b) Empalmar como historia previa (DFF antes de EFFR, Shiller antes de GS10…), como las 9 que ya lo hacen | recálculo | C05 |
| P25 | Sin cambio a USD antes de 1999 (y el CNY) | Cosmético | a) No hacer nada y dejarlo como limitación declarada | nada / limitación | C07 |
| P26 | UCITS con historia recortada o poco parecidos a su ETF de EE. UU. | Cosmético | a) No hacer nada y dejarlo como limitación declarada y alinear el 16/18 | nada / limitación | L06 |
| P27 | Constituyentes: el S&P 500 sin cambios después del 2026-08-18 | Cosmético | b) Volver a bajar el repositorio fja05680 por si se actualizó | gratis | L01 |
| P28 | Huecos de más de 5 sesiones en precios sin aviso | Cosmético | b) Aviso en get_precios cuando entre dos velas hay más de 5 sesiones del calendario | código | N10, N14 |
| P29 | Octubre de 2025 no existe en 21 series de EE. UU. | Cosmético | b) Test de que las derivadas y las variaciones dejan vacío ese mes y el siguiente | código | N03 |
| P30 | Seis filas vacías del festivo canadiense de 2006 | Cosmético | b) Quitar las filas vacías en días que el calendario XTSE da cerrados | recálculo | N05 |
| P31 | 74.530 filas anteriores a ALFRED sin la etiqueta de posible fuga | Cosmético | b) Añadir «posible fuga de revisiones» a su nota | código | V01 |
| P32 | Los tests de datos se saltan en silencio si falta el corpus | Cosmético | b) Avisar en la salida (o fallar) si falta el corpus en la máquina que lo tiene y no crear la carpeta vacía | código | C10 |
| P33 | Cifras y frases desfasadas en el plan y los notebooks | Cosmético | b) Regenerar las cifras del plan y del README desde las tablas y corregir las frases | gratis | C11, N01, V08, C04, V06, N13, C05 |
| P34 | Precios de una sola fuente (solo Yahoo, F3): nada con qué contrastar | Cosmético | a) No hacer nada y dejarlo como limitación declarada (F3) | nada / limitación | L01, L04 |
| P35 | D10 abierta: mínimos de historia y liquidez de un ticker | Cosmético | a) Dejarla para la Fase 4, como se decidió | nada / limitación | N07, C02, C03, L02 |

## Las 124 limitaciones, por causa

| Causa | Filas | Pendiente |
|---|---|---|
| Tickers sospechosos | 37 | P11 (y P34) |
| Ediciones antiguas del WEO | 34 | P16 |
| S&P 500: reutilizados, deslistados y salidos | 19 | P05 y P02 |
| Yahoo revisa o no completa sesiones | 15 | P06 |
| Series que la fuente no publica | 4 | P20 |
| Philadelphia (sin filas por diseño) | 3 | Bien: nada que decidir |
| UCITS | 3 | P26 |
| Índices y futuros `yf:` de la Fase 1 | 3 | P21 |
| Constituyentes | 2 | P27 |
| Bundesbank | 1 | P22 |
| Calendarios de Eurostat | 1 | Bien: cubierto por las reglas prudentes |
| Vintages de BCE, Eurostat, BIS y Banco Mundial | 1 | P23 |
| Aperturas solo de Yahoo | 1 | P08 y P34 |

Las 124 filas son 119 ids distintos: DWD y GR salen tres veces, y BLY, dos.

## Refrescar: lo que hay hoy y lo que falta para una sola orden

**Lo que ya existe:**
- **FRED vivo:** incremental, desde 62 días antes del último dato (`fred.py:113`).
- **ALFRED:** sin `--refrescar` se salta lo ya archivado (`alfred.py:219`); con él baja enteras las 161 series.
- **Yahoo:** baja siempre la historia completa (`yahoo.py:204`), y el almacén la mezcla con lo guardado.
- **`construir-base`:** aplica el solo-añadir.
- **`curar` y `curar-precios`:** publicación atómica.
- **`archivar-oas`:** une las capturas.

**Pasos de hoy hasta un corte nuevo** (unas 20 órdenes):
1. `descargar-fred-vivo` y `descargar-alfred --refrescar`, cada uno repetido hasta que salga con 0.
2. `excepciones-alfred`.
3. `archivar-oas` y las académicas.
4. Las 10 órdenes `descargar-<fuente>`.
5. `descargar-precios` por niveles, con los CSV de `logs/`.
6. `construir-base` e `informe-alfred`.
7. `inventario` → `redundancia` → `eda` → `seleccion` → `preprocesado`.
8. **Editar el corte en el código.**
9. `curar` y `curar-precios`.
10. El estado, los notebooks y los tests.

**Lo que falta** para `refrescar --corte AAAA-MM-DD` (pendiente P07):
- el corte en un solo sitio;
- un orquestador de descargas reanudables en segundo plano;
- la lista de tickers sacada de `lista_curada.yaml`;
- tolerar revisiones OHLC aisladas de Yahoo (P06);
- `excepciones-alfred` dentro de la cadena;
- un estado genérico del refresco;
- la lista curada congelada por defecto, con `--reseleccionar` solo mostrando la diferencia y parando (G6);
- una tarea mensual para las ediciones (P14).

**Atajo sin red:** con el corte como parámetro, `curar` y `curar-precios` con el corte en 2026-11-20 meterían la semana
que ya está descargada.

## Fuentes alternativas comprobadas en la web (2026-11-21)

Solo se consultaron páginas públicas y el índice de capturas de la Wayback Machine, sin enviar ningún dato del usuario.

| Fuente | URL | Qué se comprobó | Pendiente |
|---|---|---|---|
| FRED · DEXTAUS (H.10 de la Fed) | https://fred.stlouisfed.org/series/DEXTAUS | Existe: TWD por USD, diario. La página dio error 500 y la última fecha solo se vio en el buscador | P03 |
| FMI · FAQ del WEO | https://www.imf.org/en/Publications/WEO/frequently-asked-questions | Un Excel oficial con las previsiones históricas desde abril de 1990 | P16 |
| FMI · términos de uso | https://www.imf.org/en/About/copyright-and-terms | Se permite bajar y reutilizar sin fines comerciales; se prohíbe la descarga masiva automática sin permiso | P16 |
| FMI · robots.txt | https://www.imf.org/robots.txt | Responde «Access Denied» a un programa (igual que en el 3b-2) | P16 |
| Wayback Machine · índice CDX | https://web.archive.org/cdx/search/cdx | Versiones distintas: Ken French 21 (2015–2026), Shiller 122 (2000–2023), OFR 20 (2019–2026) | P15 |
| Bundesbank · API SDMX | https://statistiken.bundesbank.de/content/991448 | API gratis y sin clave | P22 |
| BCE · IRS (tipos a largo plazo) | https://data.ecb.europa.eu/data/datasets/IRS/data-information | Existe el 10 años alemán mensual | P22 |
| BCE · Real-Time Database | https://data.ecb.europa.eu/data/datasets/RTD/data-information | Vintages según el buscador; la página dio 503 | P23 |
| Banco Mundial · archivos del WDI | https://databank.worldbank.org/databases/archives | Versiones antiguas del WDI desde 1989, gratis | P23 |
| Comisión Europea · encuestas (ESI) | https://economy-finance.ec.europa.eu/economic-forecast-and-surveys/business-and-consumer-surveys/download-business-and-consumer-survey-data/time-series_en | ZIP gratis; la página no dice qué composición de la zona euro usa | P20 |
| S&P DJI · notas de prensa | https://press.spglobal.com/ | Cambios del S&P 500 posteriores al 2026-08-18, públicos | P27 |
| GitHub · fja05680/sp500 | https://github.com/fja05680/sp500 | Licencia MIT; la página no muestra la fecha del último cambio | P27 |
| Tiingo | https://www.tiingo.com/about/pricing | Plan gratis solo para uso personal interno y 500 símbolos al mes; contradice F3. No se recomienda | P05, P34 |
| Stooq | https://github.com/pydata/pandas-datareader/issues/1012 | Ahora pide una clave que se saca con un captcha: no se puede automatizar | P11 |

**No se pudo verificar:**
- si Stooq o Tiingo traen empresas deslistadas;
- el paro urbano de China de la NBS;
- los CSV de valor liquidativo de los emisores de UCITS;
- CRSP/WRDS.

Por eso ninguna de esas fuentes sale como opción «fuente alternativa».

**Dos decisiones anteriores que la web matiza:**
- **G1.** Su motivo («sin fuente gratuita y legal») no es exacto: existen los archivos del WDI, la base en tiempo real
  del BCE y la base de revisiones de la OCDE. Aun así se recomienda no hacer nada y solo corregir el motivo (P23).
- **G3.** El robots.txt del FMI sigue bloqueando a un programa, pero la descarga a mano del Excel histórico la permiten
  los términos del FMI (P16).

## Cifras del plan que cambian

| Dónde | Plan | Bueno | Fuente |
|---|---|---|---|
| Nulos de `fred_alfred` | «casi todos festivos» | 6 festivos de 26.200 nulos | N01 |
| Fuentes con posible fuga | 8 | 9 (falta el BCE, 372 filas) | V01 |
| Fuga total con las anteriores a ALFRED | — | 4,96 % | V01 (corregido) |
| Alias con historia anterior a 2000 | 25 | 26 | C05 |
| Proyecciones | 243 | 309 | C11 |
| Tickers sospechosos | 26 / 35 / 36 | 37 (36 se quedan) | C04 |
| Historia recortada | 16 (estado) | 18 (avisos) | L06 |
| Series desde 2000 | 347 (65,1 %) | 346 (64,9 %) | L09 (corregido) |
| Series de la zona euro | 18 | 21 | L07 (corregido) |
| Ediciones del WEO | 3 | 4 (también 2026-10) | V06/L03 (corregido) |
| Tests | 1.270 | 1.287 recogidos (1.257 pasan con el corpus) | C11/C10 |

## Lo que no se ha comprobado

- Ni el verificador ni los auditores han usado la red para recalcular datos: la causa de N04 (Cleveland) y la última
  fecha de DEXTAUS se comprueban al aplicar el arreglo.
- El verificador no recalculó:
  - la clasificación 487/2/8 de F01;
  - las reglas de C09 aparte de ICSA y las peticiones continuadas;
  - los 110/113 recalculados de C03;
  - los tiempos de ALFRED de F06.
- Las cifras de L02 dependen del método: 67,78 % en la tabla, 67,88 % para el auditor y 67,45 % para el verificador.
