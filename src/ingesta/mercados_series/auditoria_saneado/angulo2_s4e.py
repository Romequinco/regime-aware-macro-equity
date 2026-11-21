"""Complemento de s4: revisiones en el sitio que el solo-añadir descarta (guardada_gana_valor) en el último
construir-base (tablas/solo_anadir_ultima.csv). Solo recuentos."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

import pandas as pd

T = (_REPO / "results/ingesta/mercados_series/tablas")
AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
s = pd.read_csv(T / "solo_anadir_ultima.csv")
s["fuente"] = s["serie"].str.split(":").str[0]
cols = ["conservadas", "ya_conservadas", "fechadas_observacion", "mismo_valor", "fecha_propia", "guardada_gana_valor",
        "guardada_gana_nota"]
g = s.groupby("fuente")[cols].sum()
print(g.to_string())
print("observado:", s["observado"].unique().tolist(), "series en la tabla:", len(s))
d["s4e_solo_anadir_ultima"] = {"series": int(len(s)), "observado": s["observado"].unique().tolist(),
                               "totales": {c: int(s[c].sum()) for c in cols},
                               "por_prefijo": {f: {c: int(v) for c, v in r.items() if v} for f, r in g.iterrows()},
                               "series_con_guardada_gana_valor": int((s["guardada_gana_valor"] > 0).sum())}
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
