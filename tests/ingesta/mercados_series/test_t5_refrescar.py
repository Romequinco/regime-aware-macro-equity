"""P07 (auditoría de saneado): corte en un solo sitio y orden única ``refrescar``. Sin red ni corpus."""
from __future__ import annotations

import pandas as pd
import pytest

from ingesta.mercados_series import corte, refrescar


def test_corte_vigente_lee_config_y_entorno(tmp_path, monkeypatch):
    cfg = tmp_path / "corte.yaml"
    cfg.write_text('corte: "2026-11-13"\n', encoding="utf-8")
    monkeypatch.delenv(corte.VARIABLE, raising=False)
    assert corte.corte_vigente(cfg) == pd.Timestamp("2026-11-13")
    monkeypatch.setenv(corte.VARIABLE, "2026-11-20")
    assert corte.corte_vigente(cfg) == pd.Timestamp("2026-11-20")
    assert corte.corte_config(cfg) == pd.Timestamp("2026-11-13")


def test_corte_config_del_repo_es_g2(monkeypatch):
    monkeypatch.delenv(corte.VARIABLE, raising=False)
    assert corte.corte_vigente() == pd.Timestamp("2026-11-13")


@pytest.mark.parametrize("malo", ["2026-13-01", "2026-11-13 10:00", "mañana"])
def test_corte_no_valido(malo):
    with pytest.raises(ValueError):
        corte._validar(malo)


def test_validar_corte_no_admite_futuro():
    with pytest.raises(ValueError):
        refrescar.validar_corte("2026-12-01", hoy=pd.Timestamp("2026-11-21"))
    assert refrescar.validar_corte("2026-11-20", hoy=pd.Timestamp("2026-11-21")) == pd.Timestamp("2026-11-20")


def test_pasos_orden_y_lista_congelada():
    t = pd.Timestamp("2026-11-20")
    completos = [p.nombre for p in refrescar.pasos(t)]
    assert completos[0] == "fred-vivo" and completos[-2:] == ["curar", "curar-precios"]
    assert completos.index("precios-yahoo") < completos.index("construir-base") < completos.index("curar")
    assert "seleccion" not in completos                      # G6: lista congelada por defecto
    sin = refrescar.pasos(t, sin_descargas=True)
    assert [p.grupo for p in sin][0] == "base" and "--sin-red" in sin[0].argv
    con = [p.nombre for p in refrescar.pasos(t, reseleccionar=True)]
    assert con.index("seleccion") < con.index("curar")


def test_mensual_es_lo_que_se_pierde_si_no_se_descarga():
    assert [p.nombre for p in refrescar.pasos_mensuales()] == ["fred-vivo", "archivar-oas", "academicos"]


def _lanzador(codigos):
    llamadas = []

    def lanzar(cmd, *, env, log):
        llamadas.append((cmd, env.get(corte.VARIABLE)))
        return codigos.pop(0)
    return lanzar, llamadas


def test_ejecutar_repite_reanudables_y_pasa_el_corte(tmp_path):
    lista = [refrescar.Paso("a", "descargas", ("x",), repetir_si=(2,), max_intentos=5),
             refrescar.Paso("b", "curado", ("y",))]
    lanzar, llamadas = _lanzador([2, 2, 0, 0])
    assert refrescar.ejecutar(lista, pd.Timestamp("2026-11-20"), tmp_path / "logs", lanzar=lanzar,
                              registro=lambda _m: None) == 0
    assert len(llamadas) == 4 and {e for _, e in llamadas} == {"2026-11-20"}
    estado = pd.read_csv(tmp_path / refrescar.FICHERO_ESTADO)
    assert estado["paso"].tolist() == ["a", "b"] and estado["intentos"].tolist() == [3, 1]


def test_ejecutar_para_en_error_salvo_descargas_toleradas(tmp_path):
    lista = [refrescar.Paso("a", "descargas", ("x",)), refrescar.Paso("b", "curado", ("y",))]
    lanzar, llamadas = _lanzador([1, 0])
    assert refrescar.ejecutar(lista, None, tmp_path / "l", lanzar=lanzar, registro=lambda _m: None) == 1
    assert len(llamadas) == 1
    lanzar, llamadas = _lanzador([1, 0])
    assert refrescar.ejecutar(lista, None, tmp_path / "l", lanzar=lanzar, seguir_tras_error_descarga=True,
                              registro=lambda _m: None) == 0
    assert len(llamadas) == 2


def test_ejecutar_se_para_si_la_seleccion_cambia_la_lista(tmp_path, monkeypatch):
    lista = [refrescar.Paso("seleccion", "seleccion", ("seleccion",)), refrescar.Paso("curar", "curado", ("curar",))]
    monkeypatch.setattr(refrescar, "lista_cambiada", lambda _r: " lista_curada.yaml | 4 +-")
    lanzar, llamadas = _lanzador([0, 0])
    assert refrescar.ejecutar(lista, None, tmp_path / "l", lanzar=lanzar, ruta_lista=tmp_path / "lista.yaml",
                              registro=lambda _m: None) == refrescar.SALIDA_PARADA_SELECCION
    assert len(llamadas) == 1
    lanzar, llamadas = _lanzador([0, 0])
    assert refrescar.ejecutar(lista, None, tmp_path / "l", lanzar=lanzar, ruta_lista=tmp_path / "lista.yaml",
                              aceptar_seleccion=True, registro=lambda _m: None) == 0
