# Auditoría de saneado del Tema 1 (2026-11-21)

Scripts de **solo lectura** que sacan las cifras de
[`registro_saneado.md`](../../../../docs/fase2/mercados_series/registro_saneado.md). Leen el corpus
(`D:/tfm_corpus/mercados_series`) y las tablas de `results/ingesta/mercados_series/tablas/`, sin escribir en ninguno de
los dos. No son parte del paquete: son scripts sueltos, sin `__init__.py`.

**Cómo se ejecutan.** Escriben sus salidas (JSON, CSV y TXT con recuentos, fechas e ids, nunca valores ni precios)
**junto a sí mismos**. Por eso conviene copiarlos a una carpeta de trabajo fuera del repo y lanzarlos allí:

```powershell
$env:REPO_TFM = "<ruta del repo>"; $env:PYTHONPATH = "$env:REPO_TFM/src"; $env:INGESTA_CORPUS_DIR = "D:/tfm_corpus"
python angulo1.py --rehacer; python angulo2.py; python angulo3.py; python verificador.py
python asesor_build.py; python aplicar_verificacion.py; python generar_html.py
```

Si se ejecutan aquí dentro, el `.gitignore` de esta carpeta impide versionar las salidas. Sin `REPO_TFM`, la raíz del
repo se deduce de la ruta del script (cuatro carpetas más arriba).

| Script | Qué mide |
|---|---|
| `angulo1*.py` | Huecos y nulos: nulos por serie y causa, aperturas anuladas, velas de relleno, huecos de calendario, no llegan al corte, series paradas |
| `angulo2*.py` | Frescura y vintages: al día o parado por serie y ticker, filas tras el corte, mecanismo de refresco (fichero:línea), fuga de revisiones, «unico», WEO, OAS, ediciones académicas |
| `angulo3*.py` | Sanidad: escalas y unidades, saltos sin split, reutilizados y sospechosos, alias anteriores a 2000, conversión a USD, capas de fecha, zona euro, las 124 limitaciones, verificaciones y tests |
| `a3_snap_d.py` | Foto de tamaños y fechas de los ficheros de `D:` para comprobar que nada cambió |
| `verificador.py` | Recalcula de forma independiente la cifra clave de los 50 hallazgos |
| `asesor_build.py` | Construye los 35 pendientes con sus opciones (`asesor.json`) |
| `aplicar_verificacion.py` | Aplica las correcciones del verificador y escribe `docs/tfm/internos/tema1_saneado/pendientes.json` |
| `generar_html.py` | `opciones.html` autocontenido (sin CDN) en `docs/tfm/internos/tema1_saneado/` (carpeta ignorada) |
