"""Auditoría ángulo 3 · comprobación de las tools (solo lectura): FX de USX, TWD y CNY, y avisos de un ticker
reutilizado. Imprime solo recuentos y avisos (sin valores). Uso: PYTHONPATH=<worktree>/src python angulo3_tools.py"""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json, os, sys, warnings
os.environ.setdefault("INGESTA_CORPUS_DIR", "D:/tfm_corpus")
sys.path.insert(0, str(_REPO / "src"))
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
from ingesta.mercados_series import tools
OUT = Path(__file__).resolve().parent
C = {}
for tk in ["ZC=F", "2330.TW", "^TWII", "000001.SS", "LU", "GR", "MCIC"]:
    try:
        r = tools.get_precios(tk, "2026-11-13", base="curada", divisa="USD")
        d = r.datos
        sin = int(d["fx_usd"].isna().sum()) if "fx_usd" in d else None
        sin16 = int(d.loc[d["sesion"] >= "2016-01-01", "fx_usd"].isna().sum()) if "fx_usd" in d else None
        C[tk] = {"sesiones": len(d), "sin_fx": sin, "sin_fx_desde_2016": sin16,
                 "avisos": [a[:160] for a in r.avisos]}
    except Exception as e:
        C[tk] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print(tk, C[tk])
json.dump(C, open(OUT / "a3_cifras_tools.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
