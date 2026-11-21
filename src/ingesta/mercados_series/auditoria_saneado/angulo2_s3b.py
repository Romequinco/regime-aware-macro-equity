"""Complemento de s3: por qué no llegan al corte los 21 tickers (logs JSONL de Yahoo y avisos). Sin valores."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

import pandas as pd

C = Path("D:/tfm_corpus/mercados_series")
T = (_REPO / "results/ingesta/mercados_series/tablas")
AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
malos = list(d["s3_malos"])
filas = []
for f in sorted((C / "logs").glob("yahoo_*.jsonl")):
    for linea in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linea)
        except Exception:
            continue
        if r.get("ticker") in malos:
            filas.append({"lote": f.stem, "ticker": r.get("ticker"), "estado": r.get("estado"),
                          "descargado": str(r.get("descargado"))[:10], "error": str(r.get("error") or "")[:110]})
df = pd.DataFrame(filas)
ult = df.sort_values("descargado").groupby("ticker").tail(1) if len(df) else df
with pd.option_context("display.width", 250, "display.max_colwidth", 110, "display.max_rows", 100):
    print(ult.to_string(index=False))
    sin = sorted(set(malos) - set(df["ticker"])) if len(df) else malos
    print("sin ninguna fila en los JSONL de Yahoo:", sin)
    av = pd.read_csv(T / "precios_curados_avisos.csv")
    a = av[(av["tipo"] == "no_llega_corte") & av["ticker"].isin(malos)]
    print(a[["ticker", "nota"]].to_string(index=False) if "nota" in a else a.to_string())
    s = av[av["ticker"] == "SNDK"]
    print(s.drop(columns=[c for c in s.columns if c in ("valor",)]).to_string(index=False))
    e = pd.read_csv(T / "descargas_3b_estado.csv")
    m = e[e["id"].astype(str).isin(malos)][["id", "tipo", "estado_3b", "motivo_3b"]]
    print(m.to_string(index=False))
res = {"ultimo_estado_log": ult.set_index("ticker")[["lote", "estado", "descargado"]].to_dict("index") if len(ult) else {},
       "sin_log": sin}
d["s3b_causas"] = res
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
