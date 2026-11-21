"""Complemento de s4: cuántas revisiones ha capturado ya el solo-añadir (notas de base.conservar_revisiones) en las
fuentes sin historia de revisiones. Sin valores."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

C = Path("D:/tfm_corpus/mercados_series/series")
AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
PATRONES = {"valor_anterior": "valor anterior a una revisión observada", "revision_observada": "revisión observada",
            "mismo_valor": "mismo valor"}
out = {}
for nombre in ("base_series", "base_curada"):
    t = pq.read_table(C / f"{nombre}.parquet", columns=["serie", "fuente", "nota"],
                      read_dictionary=["serie", "fuente", "nota"]).to_pandas()
    cats = pd.Series(t["nota"].cat.categories)
    codes = t["nota"].cat.codes.to_numpy()
    r = {}
    for k, pat in PATRONES.items():
        es = cats.str.contains(pat, regex=False).to_numpy()
        m = np.where(codes >= 0, es[np.clip(codes, 0, None)], False)
        r[k] = {"filas": int(m.sum()), "series": int(t.loc[m, "serie"].nunique()),
                "por_fuente": {str(a): int(b) for a, b in t.loc[m, "fuente"].value_counts().items() if b}}
    out[nombre] = r
    print(nombre, json.dumps(r, ensure_ascii=False))
d["s4d_solo_anadir_capturadas"] = out
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
