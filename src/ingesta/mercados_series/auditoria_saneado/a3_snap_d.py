import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import os, sys, json
raiz = r"D:/tfm_corpus"
out = {}
for dp, dn, fn in os.walk(raiz):
    for f in fn:
        p = os.path.join(dp, f)
        try:
            s = os.stat(p); out[p] = (s.st_size, s.st_mtime_ns)
        except OSError: pass
json.dump(out, open(sys.argv[1], "w"))
print(len(out))
