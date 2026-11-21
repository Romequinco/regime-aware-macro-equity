"""P32 (auditoría de saneado): que los tests de datos no se salten en silencio cuando falta el corpus.

- Al final de la sesión, si no está la base real (``<corpus>/mercados_series/series/base_series.parquet``), se
  imprime un aviso bien visible con la ruta que se ha mirado y cuántos tests se han saltado.
- Con ``T1_EXIGIR_CORPUS=1`` (para la máquina que tiene el corpus), la sesión **falla** desde el principio si falta.

En la CI (sin corpus) no cambia nada: los tests de datos se siguen saltando, pero ya no en silencio.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ingesta.comun import rutas


def _base_real() -> Path:
    # Sin llamar a rutas.corpus_dir (que crea la carpeta): solo se mira.
    raiz = Path(rutas.env("INGESTA_CORPUS_DIR", str(rutas.ROOT / "corpus")))
    return raiz / "mercados_series" / "series" / "base_series.parquet"


def pytest_sessionstart(session):  # noqa: ARG001
    if os.environ.get("T1_EXIGIR_CORPUS") == "1" and not _base_real().exists():
        pytest.exit(f"T1_EXIGIR_CORPUS=1 y no está la base real en {_base_real()} "
                    "(¿falta INGESTA_CORPUS_DIR en .env?)", returncode=4)


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    if _base_real().exists():
        return
    saltados = len(terminalreporter.stats.get("skipped", []))
    terminalreporter.write_sep("!", "AVISO Tema 1: sin corpus", yellow=True, bold=True)
    terminalreporter.write_line(
        f"No está la base real en {_base_real()}: los tests de datos del Tema 1 se han saltado "
        f"({saltados} tests saltados en total). Si esta máquina tiene el corpus, pon INGESTA_CORPUS_DIR en .env "
        "o lanza con T1_EXIGIR_CORPUS=1 para que falle.")
