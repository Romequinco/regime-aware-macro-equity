"""Complemento de s4: fred:USRECD (indicador de recesión del NBER) en la curada: método, vintage, retraso aplicado.
Sin valores (solo fechas y recuentos)."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

import pyarrow.parquet as pq

C = Path("D:/tfm_corpus/mercados_series/series")
AQUI = Path(__file__).resolve().parent
d = json.loads((AQUI / "angulo2_cifras.json").read_text(encoding="utf-8"))
out = {}
for sid in ("fred:USRECD", "fred:USREC"):
    for nombre in ("base_curada", "base_series"):
        t = pq.read_table(C / f"{nombre}.parquet", columns=["serie", "fecha_referencia", "fecha_publicacion",
                                                            "metodo_publicacion", "vintage"],
                          filters=[("serie", "=", sid)]).to_pandas()
        if not len(t):
            out[f"{sid}|{nombre}"] = None
            continue
        r = (t["fecha_publicacion"] - t["fecha_referencia"]).dt.days
        out[f"{sid}|{nombre}"] = {"filas": int(len(t)), "metodo": t["metodo_publicacion"].astype(str).value_counts().to_dict(),
                                  "vintage": t["vintage"].astype(str).value_counts().head(3).to_dict(),
                                  "retraso_dias_mediana": float(r.median()), "retraso_min": int(r.min()),
                                  "ult_ref": str(t["fecha_referencia"].max().date()),
                                  "ult_pub": str(t["fecha_publicacion"].max().date())}
        print(sid, nombre, out[f"{sid}|{nombre}"])
rc = pq.read_table(C / "registro_cambios.parquet", columns=["serie", "capa", "regla", "retraso_dias"],
                   filters=[("serie", "=", "fred:USRECD")]).to_pandas()
out["registro_cambios_USRECD"] = {"filas": int(len(rc)), "capa": rc["capa"].astype(str).value_counts().to_dict(),
                                  "regla": rc["regla"].astype(str).value_counts().to_dict(),
                                  "retraso_mediana": float(rc["retraso_dias"].median()) if len(rc) else None}
print(out["registro_cambios_USRECD"])
d["s4c_usrecd"] = out
(AQUI / "angulo2_cifras.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
