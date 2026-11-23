"""Auditoría del Tema 1 · ÁNGULO 3 (sanidad, consistencia y limitaciones). SOLO LECTURA.

Ejecuta las partes en orden; cada una imprime sus cifras (recuentos, fechas, ids y porcentajes; nunca valores ni
precios) y guarda un a3_cifras_*.json en esta carpeta. Después, angulo3_hallazgos.py monta angulo3.json.

    python angulo3.py            # todas las partes (≈ 3 min; lee D:/tfm_corpus/mercados_series con columnas mínimas)
    python angulo3.py series     # solo una parte

Partes: series (unidades, escalas, alias, cobertura, capas), precios (saltos, splits, reutilizados, sospechosos, FX,
S&P 500), tools (FX y avisos que devuelven get_precios), capas (retraso frente al original), zonaeuro (composición),
limitaciones (las 124, una por una: angulo3_limitaciones.csv). Escrituras: solo en esta carpeta.
Los tests del tema se lanzan aparte (ver angulo3.md).
"""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import runpy
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PARTES = ["series", "precios", "tools", "capas", "zonaeuro", "limitaciones", "hallazgos"]
pedidas = sys.argv[1:] or PARTES
for p in pedidas:
    print(f"\n######## angulo3_{p}.py ########", flush=True)
    runpy.run_path(str(AQUI / f"angulo3_{p}.py"), run_name="__main__")
