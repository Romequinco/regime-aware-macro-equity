"""Cifras derivadas para angulo2.json a partir de angulo2_cifras.json (sin leer datos). Re-ejecutable."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
malas = d["s1_malas"]
activa_parada = {s: v["fuente"] for s, v in malas.items()
                 if v["estado"] == "activa" and v["gratis"].startswith("no: refrescada") and v["fuente"] != "yfinance"}
print("series 'activa' que la fuente ya no publica (refrescadas sin periodos nuevos):", len(activa_parada),
      dict(Counter(activa_parada.values())))
print(sorted(activa_parada))
retiradas = Counter(v["fuente"] for v in malas.values() if v["estado"] == "retirada")
print("retiradas:", sum(retiradas.values()), dict(retiradas))
causas = d["s3b_causas"]["ultimo_estado_log"]
bloqueo = [t for t, v in causas.items() if v["estado"] == "error"]
print("tickers con el último intento de Yahoo en error (ErrorContrato):", len(bloqueo))
f = d["s4_fuga_curada"]
kf = f["por_fuente"]["ken_french"]["filas"]
print("peso de Ken French en la fuga:", round(100 * kf / f["filas_fuga"], 1), "%")
u = d["s4_unico_curada"]
print("unico no revisable:", u["filas_unico"] - u["unico_revisable"], "=",
      round(100 * (u["filas_unico"] - u["unico_revisable"]) / u["filas_unico"], 1), "% de las unico")
s = d["s4e_solo_anadir_ultima"]["totales"]
print("revisiones descartadas (guardada gana valor) en el último construir-base:", s["guardada_gana_valor"])
d["resumen"] = {"activa_pero_parada": len(activa_parada), "activa_pero_parada_ids": sorted(activa_parada),
                "activa_pero_parada_por_fuente": dict(Counter(activa_parada.values())),
                "retiradas": sum(retiradas.values()), "retiradas_por_fuente": dict(retiradas),
                "tickers_bloqueados_errorcontrato": len(bloqueo), "tickers_bloqueados_ids": sorted(bloqueo),
                "pct_ken_french_en_fuga": round(100 * kf / f["filas_fuga"], 1),
                "unico_no_revisable": u["filas_unico"] - u["unico_revisable"],
                "pct_unico_no_revisable": round(100 * (u["filas_unico"] - u["unico_revisable"]) / u["filas_unico"], 1)}
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
