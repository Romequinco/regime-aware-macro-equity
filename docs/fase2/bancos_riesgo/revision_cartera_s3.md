# Revisión para el agente de carteras y almacenamiento en S3

Revisión del 18 de noviembre de 2026. Notebook: `notebooks/fase2/bancos_riesgo/01_sonda.ipynb`.
Bucket indicado por Fernando: `tfm-rag-multiagent`, región comprobada `eu-west-3` (París).

## Dictamen y alcance

La selección es útil como información monetaria y contexto macrofinanciero para
interpretar riesgos y exposiciones de renta variable de Europa, Estados Unidos y
Asia. Todavía no es un histórico completo ni una base con la que pueda atribuirse
causalmente una subida o caída a un documento. La relevancia económica, la
disponibilidad histórica, la calidad de extracción y la cobertura de adquisición
son propiedades distintas y se registran por separado.

En los CSV locales existentes antes de esta revisión hay 79 intentos: 73 OK,
3 pendientes, 2 excluidos y 1 bloqueado por robots. Los JSONL contienen 73
registros y 72 hashes de originales: 51 HTML y 22 PDF. Hay 13 registros sin fecha
de publicación normalizada y ninguna versión con disponibilidad histórica
acreditada. Es una muestra guardada, no una consulta nueva de todas las fuentes
ni una medida del corpus final. La reextracción local de PDF puede cambiar los
conteos de texto completo, pero no acredita fechas ausentes.

## Utilidad por bloque

| Bloque | Aportación al agente de carteras | Evaluación y siguiente necesidad |
|---|---|---|
| Fed: decisión, SEP, comparecencia, actas | Tipos de descuento, expectativas de beneficios, liquidez USD y transmisión internacional | Prioridad alta. Separar cada hora de publicación y distinguir sorpresa monetaria de información sobre crecimiento |
| BCE y BoE | Condiciones de financiación y exposición europea, GBP/EUR, bancos y sectores sensibles a tipos | Prioridad alta. La muestra guardada falla al descubrir discursos BCE y decisiones BoE; no confundir selección con cobertura conseguida |
| Discursos y Beige Book | Contexto entre reuniones, riesgos y cambios de lenguaje | Complementarios. Comparar la misma familia y separar novedad de repetición; cantidad de discursos no equivale a relevancia |
| BoJ, China e India | Política, liquidez, crecimiento, divisas y transmisión a bolsas asiáticas | Cobertura parcial. China está excluida de automatización; India usa muestras fijas; las traducciones inglesas tienen su propia disponibilidad |
| Informes de estabilidad | Crédito, apalancamiento, liquidez, fragilidad de intermediarios y escenarios de cartera | Útiles para riesgo y escenarios. Menor frecuencia; no son una alerta diaria ni un predictor automático de crisis |
| FMI WEO/GFSR | Revisiones del escenario mundial y riesgos transfronterizos | Relevantes, pero sin muestra utilizable en la ejecución guardada por los bloqueos existentes; descarga manual autorizada o adquisición oficial pendiente |
| BIS Quarterly Review | Mecanismos de mercado, financiación internacional y contagio | Contexto, no señal operativa por sí solo; verificar que se obtiene el informe, no únicamente su ficha |
| Canadá, Brasil, México y Suiza | Contexto de divisas, financiación y contagio; Suiza forma parte de Europa | Canadá/Latinoamérica son complementos para este objetivo USA/Europa/Asia. Priorizar según las exposiciones reales; no se amplía su adquisición en esta revisión |
| Literatura | Explicar mecanismos, métodos, límites y alternativas de cartera | El apartado 9 sigue pendiente de selección manual. Tener la sección escrita no significa tener literatura descargada o disponible para RAG |

La justificación empírica debe apoyarse en sorpresas y ventanas de publicación.
La [base de eventos de la Fed de San Francisco](https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/)
incluye precios y sorpresas alrededor de anuncios, comparecencias y actas. La
[investigación del BCE sobre información y política](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2133.en.pdf)
explica por qué una variación de tipos y una noticia sobre perspectivas económicas
pueden tener efectos bursátiles distintos. Estas referencias justifican estudiar
las comunicaciones; no garantizan predicción fuera de muestra.

## Cobertura adicional que conviene planificar

1. Identificar los índices/ETF y sectores concretos de Europa, USA y Asia, sus
   divisas, sesiones y horas de decisión. Asia no es equivalente a Japón: según
   el universo invertible pueden faltar China/Hong Kong, Taiwán, Corea o Singapur.
   No se añaden fuentes automáticamente por proximidad geográfica.
2. Coordinar con el Tema 1 las publicaciones de inflación, empleo, PIB y actividad,
   y sus vintages. El notebook se concentra en autoridades monetarias; eso no
   equivale a cubrir todas las noticias macroeconómicas. Usar calendarios y
   publicaciones originales de [BLS](https://www.bls.gov/about-bls/dissemination.htm),
   [Eurostat](https://ec.europa.eu/eurostat/en/news/euro-indicators/release-calendar)
   y los organismos estadísticos de los mercados asiáticos pertinentes.
3. Incorporar expectativas conocidas antes del anuncio cuando existan fuentes
   reproducibles: consenso fechado, futuros/OIS u otra medida declarada. Un
   aumento de tipos no es automáticamente una sorpresa restrictiva.
4. Guardar la comparación con la edición anterior usando únicamente versiones
   disponibles al corte. Las reacciones de precios posteriores son etiquetas de
   evaluación, no metadatos que puedan entrar al contexto de decisión del agente.

## PDF, TXT y fragmentos

Se conserva el original exacto (PDF/HTML y, si se incorporan, otros formatos) y
su SHA-256. El texto se guarda como TXT UTF-8 y también dentro del documento
normalizado JSON. Un PDF no se sustituye por su TXT: las tablas, gráficos y
maquetación pueden contener información que la extracción textual no representa.

La extracción PDF completa es independiente del tamaño de la muestra de la sonda.
`max_paginas=None` procesa todas las páginas; limitar a 40 marca la extracción
como parcial. El TXT usa separadores de página `\f`; los fragmentos JSONL guardan
`pagina`, `chunk_id`, `documento_id` y `version_id` para volver al original.

Una página sin texto activa revisión OCR: puede ser una imagen o una página
intencionadamente vacía; no se afirma automáticamente que necesite OCR. No se ha
instalado un motor OCR. Los documentos sin texto suficiente se conservan como
original y metadatos, sin declararlos textos completos aptos para backtesting.
Las limitaciones de [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
requieren validar tablas, columnas, orden de lectura y escaneados con muestras.

## Estructura que respeta el bucket existente

```text
s3://tfm-rag-multiagent/
  politica_monetaria/<entidad>/<hash>.pdf o .html
  estabilidad_financiera/<entidad>/<hash>.pdf o .html
  informes_macro/<entidad>/<hash>.<extension>
  mercados_internacionales/<entidad>/<hash>.<extension>
  literatura/<entidad>/<hash>.<extension>
  procesados/txt/<documento_id>_<hash_texto>.txt
  procesados/json/<artefacto>.json
  procesados/fragmentos/<artefacto>.jsonl
  catalogo/documentos.csv
  catalogo/ejecuciones/<ejecucion_id>/documentos.csv
  catalogo/ejecuciones/<ejecucion_id>/intentos.csv
  catalogo/ejecuciones/<ejecucion_id>/manifiesto.json
```

`tipo_dato` es el tema/carpeta: por ejemplo `politica_monetaria`.
`formato_original` identifica PDF, HTML u otro formato. No son el mismo campo.
Los informes macro y la literatura solo tendrán objetos cuando se consigan
documentos: una carpeta vacía no acredita cobertura.

Los originales usan un nombre por hash para conservar revisiones. TXT y JSON
mantienen referencias al original. La misma página puede producir una declaración
y un segmento Q&A: comparten original, pero conservan identidades y textos
distintos; no deben contarse como eventos independientes al entrenar/evaluar.

El catálogo consolidado conserva una fila por documento/versión/extractor. No
duplica una repetición de la misma extracción ni elimina versiones anteriores.
Cada ejecución conserva además su snapshot, configuración sin secretos, errores
y hashes de artefactos. Solo incorpora documentos efectivamente obtenidos de las
familias activas; una intención de descarga no se presenta como un documento.

## Campos principales del catálogo

| Grupo | Campos y significado |
|---|---|
| Identidad | `documento_id`, `version_id`, `nombre`, `url`, `tipo_dato`, `formato_original`, `entidad`, `familia` |
| Aplicación | `region_emisora`, `mercados_objetivo`, `funcion`, `idioma`, `licencia`. Los mercados son el universo de estudio, no un impacto demostrado |
| Fechas | `fecha_evento`, `fecha_publicacion`, `precision_publicacion`, `publicacion_utc`, `anuncio_utc`, `zona_fuente`, `fecha_aplicacion`, `primera_observacion_utc`, `consulta_utc` |
| Evidencia temporal | `evidencia_publicacion`, `version_acreditada`, `evidencia_version`, disponibilidades y motivos de exclusión |
| Calidad | `texto_completo`, páginas totales/procesadas/sin texto, `requiere_revision_ocr`, `estado_extraccion`, `original_disponible` |
| Acceso y trazabilidad | Claves de original/TXT/JSON/fragmentos, URIs S3, hashes, versión de extractor/esquema y ejecución |

No se inventa una fecha ni una licencia para completar el CSV. Lo desconocido
queda vacío o como pendiente. El catálogo de prueba no sustituye la revisión de
las condiciones de cada fuente antes de distribuir el corpus.

## Reglas temporales para backtesting

Las [actas FOMC se publican semanas después de la reunión](https://www.federalreserve.gov/faqs/minutes-federal-open-market-committee-fomc.htm).
Un estudio escrito después de una crisis tampoco puede usarse para anticiparla.
La fecha de descarga, el nombre del PDF y S3 LastModified no son publicación.

- **Modo acreditado, predeterminado:** texto completo, original disponible,
  versión acreditada con evidencia y disponibilidad anterior o igual al corte.
  Una marca booleana sin explicación de la versión no basta para el catálogo.
- **Modo observado:** permite usar la copia solo desde su primera observación
  verificada. Es útil para evaluación desde el comienzo de la captura; no permite
  retroceder un texto de hoy al año que aparece impreso en él.
- Una fecha diaria con zona conocida se admite desde el día local siguiente.
  Es una cota conservadora, no una hora observada. No permite estudiar una
  reacción intradía; las fechas incompletas no se convierten en el primer día del mes.
- Filtrar antes de recuperar fragmentos y construir el prompt. Recuperar sobre
  todo el corpus y eliminar fechas al final puede dejar al agente sin evidencia
  histórica relevante y no evita el acceso previo a textos futuros.
- Guardar por separado el instante de decisión, el calendario de cada bolsa y
  la primera ejecución posible. Un comunicado USA puede llegar después del cierre
  europeo y antes de la siguiente sesión asiática. Las ventanas de respuesta
  deben respetar esas sesiones y las divisas de precios/rentabilidades.

La disponibilidad de un documento es solo una parte del control de anticipación:
hay que aislar también memoria del agente, resúmenes, resultados derivados,
entrenamiento y etiquetas futuras. Un LLM actual puede conocer crisis posteriores
por sus pesos; el filtrado del RAG no demuestra que ese conocimiento desaparezca.
Separar entrenamiento y evaluación cronológicamente, registrar corte del modelo
y aplicar las pruebas de contaminación ya planteadas en `docs/fase2/plan_datos.md`.

## Literatura que conviene evaluar, sin adquisición automática

El apartado 9 mantiene la selección editorial de Fernando. Estos son candidatos
para su lectura, no documentos ya seleccionados o incorporados:

| Referencia oficial | Por qué puede servir |
|---|---|
| [Bernanke y Kuttner, FEDS 2004-16](https://www.federalreserve.gov/econres/feds/what-explains-the-stock-market39s-reaction-to-federal-reserve-policy.htm) | Distinguir cambios de tipos esperados y no esperados al estudiar renta variable |
| [Gürkaynak, Sack y Swanson, FEDS 2004-66](https://www.federalreserve.gov/econres/feds/do-actions-speak-louder-than-words-the-response-of-asset-prices-to-monetary-policy-actions-and-statements.htm) | Separar decisión actual y trayectoria futura comunicada |
| [Jarociński y Karadi, ECB WP 2133, 2018](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2133.en.pdf) | Separar información sobre la economía de un shock monetario |
| [Base y estudio USMPD, Fed de San Francisco, 2025](https://www.frbsf.org/research-and-insights/publications/working-papers/2025/12/financial-market-effects-of-fomc-communication-evidence-from-a-new-event-study-database/) | Diseñar ventanas y distinguir anuncios, comparecencias y actas |

Evaluar después evidencia sobre Asia, contagio, liquidez y riesgo de cartera.
Cada referencia necesita edición exacta, fecha de disponibilidad de esa copia,
acceso permitido, ámbito, límites y una ficha de lectura. La versión de 2025
puede orientar el diseño del investigador, pero no entrar como conocimiento de
un agente que decide en 2008.

## Uso desde el notebook

La última sección prepara el corpus local bajo `corpus/bancos_riesgo/s3/`, con
las mismas claves que S3. Permite cargar los JSONL guardados y reextraer sus PDF
sin red. La copia anterior de `local/sonda` y su caché se conservan.

`ACCION_S3 = "ninguna"` prepara los archivos; `"simular"` ejecuta `--dryrun`;
`"subir"` envía los objetos. Usa la sesión de AWS CLI y opcionalmente un perfil.
No crea buckets ni cambia permisos. Primero sube originales/procesados y, solo
si termina bien, publica el catálogo. No usa `--delete`.

Las versiones por hash y los snapshots de ejecución pertenecen al pipeline, no
dependen de activar S3 Versioning. El catálogo consolidado presupone un escritor
coordinado: para varios ordenadores que escriban a la vez haría falta reconciliar
los catálogos antes de publicar. S3 almacena los objetos; los filtros, consultas
y modelos los ejecutará la aplicación.

## Validación de esta revisión

Se ha ejecutado la configuración, la selección y la exportación del notebook
con las descargas web bloqueadas durante la prueba. Los 22 PDF guardados se
reextrajeron completos; no se volvió a adquirir la muestra de fuentes.
Resultado: 73 registros, 72 originales, 73 TXT, 13 publicaciones sin normalizar,
9 documentos con páginas sin texto pendientes de revisión y 0 versiones
históricas acreditadas. Las carpetas `literatura` e `informes_macro` siguen sin
documentos de esta muestra; sus carencias no se rellenan con otras fuentes.

Se ejecutó la simulación y después la subida al bucket indicado: 295 objetos,
69,80 MiB. Se comprobaron presencia y tamaño de todos los archivos subidos, y
se descargó el catálogo para contrastar su SHA-256 con el local. Esta comprobación
valida la transferencia, no la exactitud de las fechas ni la calidad semántica.

Las 46 pruebas sin red del tema pasan, incluidas conservación del original,
extracción parcial/por páginas, PDF sin texto, versiones, evidencia temporal,
límites futuros, carga de muestras guardadas y orden de publicación en S3.
Ruff, validación del notebook, compilación de sus celdas y `git diff --check`
también pasan. No se ha ejecutado una recolección nueva de todas las fuentes
ni un backtest del agente.
