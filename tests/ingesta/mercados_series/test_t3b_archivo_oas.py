"""Tests del archivo de las OAS de ICE BofA (paso 3b-1, G4): ``archivo_oas``.

Sin red y con datos SINTÉTICOS (ningún valor real de ICE): la unión no pierde filas, capturas solapadas
(ventana móvil), cambio de valor entre capturas (dos filas con su vintage), idempotencia, el acumulado
nunca encoge, capturas antiguas desde la caché cruda y la orden completa con un transporte falso.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import archivo_oas as ao
from ingesta.mercados_series.fuentes import fred as f

SECRETO = "abcdef0123456789abcdef0123456789"
S1, S2 = "fred:BAMLH0A0HYM2", "fred:BAMLC0A0CM"


def _cap(vintage: str, inicio: str, fin: str, serie: str = S1, base: float = 3.0,
         cambios: dict[str, float] | None = None, puntos: tuple[str, ...] = ()) -> pd.DataFrame:
    """Captura sintética: días hábiles de ``inicio`` a ``fin``, valor = base + 0,01·ordinal del día."""
    fechas = pd.bdate_range(inicio, fin)
    valores = [round(base + 0.01 * (d - pd.Timestamp("2020-01-01")).days, 2) for d in fechas]
    df = pd.DataFrame({"serie": serie, "fecha_referencia": fechas, "valor": valores, "ausente": False,
                       "vintage": vintage, "origen": ao.ORIGEN_CAPTURA})
    for d, v in (cambios or {}).items():
        df.loc[df["fecha_referencia"] == pd.Timestamp(d), "valor"] = v
    for d in puntos:
        m = df["fecha_referencia"] == pd.Timestamp(d)
        df.loc[m, "valor"], df.loc[m, "ausente"] = np.nan, True
    return ao.normalizar(df)


def _claves(df: pd.DataFrame) -> set:
    return set(zip(df["serie"], df["fecha_referencia"], df["valor"].fillna(-999.0)))


# --- Unión ---------------------------------------------------------------------------------------
def test_union_no_pierde_filas_y_conserva_lo_que_sale_de_la_ventana():
    a = _cap("2026-10-12", "2023-10-10", "2026-10-08")
    b = _cap("2026-11-19", "2023-11-20", "2026-11-18")   # la ventana se ha movido: sale oct-nov 2023
    u = ao.unir(a, b)
    assert _claves(a) <= _claves(u) and _claves(b) <= _claves(u)
    assert u["fecha_referencia"].min() == pd.Timestamp("2023-10-10")
    assert u["fecha_referencia"].max() == pd.Timestamp("2026-11-18")
    # una fila por fecha: el solape no duplica y conserva la vintage de la primera captura
    assert not u.duplicated(["serie", "fecha_referencia"]).any()
    solape = u[u["fecha_referencia"].between("2023-11-20", "2026-10-08")]
    assert (solape["vintage"] == "2026-10-12").all()
    assert (u.loc[u["fecha_referencia"] > "2026-10-08", "vintage"] == "2026-11-19").all()
    assert len(u) == len(set(a["fecha_referencia"]) | set(b["fecha_referencia"]))


def test_capturas_solapadas_de_varias_series_y_parciales():
    completa = pd.concat([_cap("2026-10-12", "2023-10-10", "2026-10-08", S1),
                          _cap("2026-10-12", "2023-10-10", "2026-10-08", S2, base=1.0)])
    incremental = _cap("2026-10-13", "2026-08-07", "2026-10-09", S1)   # captura parcial (incremental)
    u = ao.unir(completa, incremental)
    assert set(u["serie"]) == {S1, S2}
    assert len(u[u["serie"] == S2]) == len(completa[completa["serie"] == S2])
    n1 = u[u["serie"] == S1]
    assert len(n1) == len(completa[completa["serie"] == S1]) + 1   # solo el día nuevo (2026-10-09)
    assert n1.loc[n1["fecha_referencia"] == "2026-10-09", "vintage"].item() == "2026-10-13"


def test_cambio_de_valor_entre_capturas_guarda_los_dos():
    a = _cap("2026-10-12", "2026-09-01", "2026-10-08")
    b = _cap("2026-11-19", "2026-09-01", "2026-11-18", cambios={"2026-10-01": 9.99},
             puntos=("2026-10-02",))
    u = ao.unir(a, b)
    d = u[u["fecha_referencia"] == "2026-10-01"].sort_values("vintage")
    assert list(d["vintage"]) == ["2026-10-12", "2026-11-19"]
    assert d["valor"].iloc[0] == a.loc[a["fecha_referencia"] == "2026-10-01", "valor"].item()
    assert d["valor"].iloc[1] == 9.99
    p = u[u["fecha_referencia"] == "2026-10-02"].sort_values("vintage")   # valor → '.' también es cambio
    assert list(p["ausente"]) == [False, True] and p["valor"].iloc[0] > 0
    # vuelve al valor original en una tercera captura: tercera fila (la secuencia es de rachas)
    c = _cap("2026-12-15", "2026-09-01", "2026-12-14")
    u3 = ao.unir(u, c)
    assert list(u3.loc[u3["fecha_referencia"] == "2026-10-01"].sort_values("vintage")["vintage"]) == [
        "2026-10-12", "2026-11-19", "2026-12-15"]
    ao.comprobar_no_encoge(u, u3)


def test_idempotencia_y_orden_indiferente():
    a = _cap("2026-10-12", "2023-10-10", "2026-10-08")
    b = _cap("2026-11-19", "2023-11-20", "2026-11-18", cambios={"2025-01-02": 7.5})
    u = ao.unir(a, b)
    pd.testing.assert_frame_equal(ao.unir(u, b), u)          # repetir la misma captura no duplica
    pd.testing.assert_frame_equal(ao.unir(u, a, b, u), u)
    pd.testing.assert_frame_equal(ao.unir(b, a), u)          # captura antigua añadida después
    assert len(ao.unir(a, a)) == len(a)


def test_acumulado_nunca_encoge():
    rng = np.random.default_rng(0)
    acumulado = ao.vacio()
    inicio = pd.Timestamp("2023-10-10")
    for k in range(12):   # 12 capturas mensuales con ventana móvil, revisiones y '.' al azar
        ini, fin = inicio + pd.DateOffset(months=k), inicio + pd.DateOffset(months=k, years=3)
        fechas = pd.bdate_range(ini, fin)
        cambios = {str(pd.Timestamp(d).date()): float(rng.integers(1, 9)) for d in rng.choice(fechas, 5)}
        cap = _cap(f"{(fin + pd.Timedelta(days=1)).date()}", str(ini.date()), str(fin.date()),
                   cambios=cambios, puntos=(str(pd.Timestamp(rng.choice(fechas)).date()),))
        nuevo = ao.unir(acumulado, cap)
        ao.comprobar_no_encoge(acumulado, nuevo)
        assert len(nuevo) >= len(acumulado) and _claves(acumulado) <= _claves(nuevo)
        acumulado = nuevo
    assert acumulado["fecha_referencia"].min() == pd.Timestamp("2023-10-10")


def test_comprobar_no_encoge_detecta_perdidas():
    a = _cap("2026-10-12", "2026-09-01", "2026-10-08")
    with pytest.raises(ValueError, match="encogería"):
        ao.comprobar_no_encoge(a, a.iloc[:-1])
    otro = a.copy()
    otro.loc[0, "valor"] = 123.0
    with pytest.raises(ValueError, match="perdería"):
        ao.comprobar_no_encoge(a, otro)


# --- Caché cruda y orden completa con transporte falso -------------------------------------------
def _obs_json(fechas, base=3.0, cambio=None) -> list[dict]:
    out = []
    for d in fechas:
        v = round(base + 0.01 * (d - pd.Timestamp("2020-01-01")).days, 2)
        if cambio and d == pd.Timestamp(cambio[0]):
            v = cambio[1]
        out.append({"realtime_start": "2026-10-12", "realtime_end": "9999-12-31", "date": f"{d:%Y-%m-%d}",
                    "value": f"{v}"})
    return out


class Falso:
    """Transporte falso de ``series/observations``: ventana fija por serie; cuenta las llamadas."""

    def __init__(self, ventanas: dict[str, list[dict]]):
        self.ventanas = ventanas
        self.llamadas = 0

    def __call__(self, url: str, params: dict) -> dict:
        assert params["api_key"] == SECRETO and url.endswith("series/observations")
        self.llamadas += 1
        obs = [o for o in self.ventanas[params["series_id"]]
               if o["date"] >= params.get("observation_start", "0000")]
        return {"count": len(obs), "offset": 0, "limit": 100000, "observations": obs}


def test_capturas_crudo_y_archivar(tmp_path):
    crudo, archivo = tmp_path / "crudo", tmp_path / "archivo"
    ids = ("fred:BAMLH0A0HYM2", "fred:BAMLC0A0CM")
    antigua = pd.bdate_range("2023-10-10", "2026-10-08")
    # 2026-10-12: descarga completa de lo vigente (bloque 2); 2026-10-13: incremental; más una de ALFRED
    v1 = Falso({"BAMLH0A0HYM2": _obs_json(antigua), "BAMLC0A0CM": _obs_json(antigua, 1.0)})
    c1 = f.ClienteFred(SECRETO, transporte=v1, carpeta=crudo, hoy="2026-10-12")
    for s in ("BAMLH0A0HYM2", "BAMLC0A0CM"):
        f.descargar_vigente(c1, s)
    c1.observaciones("BAMLH0A0HYM2", realtime_start="2026-03-31", realtime_end="2026-03-31")  # no cuenta
    f.descargar_vigente(f.ClienteFred(SECRETO, transporte=v1, carpeta=crudo, hoy="2026-10-13"), "BAMLH0A0HYM2")
    viejas = ao.capturas_crudo(crudo, ids)
    assert list(viejas) == ["2026-10-12", "2026-10-13"]
    assert viejas["2026-10-12"]["serie"].nunique() == 2
    assert viejas["2026-10-13"]["fecha_referencia"].min() >= pd.Timestamp("2026-08-01")   # incremental
    assert (viejas["2026-10-12"]["origen"] == ao.ORIGEN_CRUDO).all()

    # hoy: la ventana se ha movido y FRED ha revisado un valor
    nueva = pd.bdate_range("2023-11-20", "2026-11-18")
    v2 = Falso({"BAMLH0A0HYM2": _obs_json(nueva, cambio=("2025-06-02", 8.88)),
                "BAMLC0A0CM": _obs_json(nueva, 1.0)})
    hoy = f.ClienteFred(SECRETO, transporte=v2, carpeta=crudo, hoy="2026-11-19")
    rep = ao.archivar(cliente=hoy, carpeta=archivo, carpeta_crudo=crudo, ids=ids)
    assert rep["errores"] == {} and rep["filas_previas"] == 0
    assert sorted(rep["capturas_nuevas"]) == ["2026-10-12", "2026-10-13", "2026-11-19"]
    assert sorted(p.name for p in archivo.glob("captura_*.parquet")) == [
        "captura_2026-10-12.parquet", "captura_2026-10-13.parquet", "captura_2026-11-19.parquet"]
    acum = ao.leer_acumulado(archivo)
    cob = ao.cobertura(acum).set_index("serie")
    assert (cob["inicio"] == "2023-10-10").all() and (cob["fin"] == "2026-11-18").all()
    assert cob.loc["fred:BAMLH0A0HYM2", "fechas_revisadas"] == 1
    assert cob.loc["fred:BAMLC0A0CM", "fechas_revisadas"] == 0
    assert len(acum) == len(set(antigua) | set(nueva)) * 2 + 1
    pd.testing.assert_frame_equal(ao.reconstruir(archivo), acum)

    # repetir el mismo día: caché, sin peticiones nuevas, acumulado idéntico, registro con dos filas
    n = v2.llamadas
    rep2 = ao.archivar(cliente=f.ClienteFred(SECRETO, transporte=v2, carpeta=crudo, hoy="2026-11-19"),
                       carpeta=archivo, carpeta_crudo=crudo, ids=ids)
    assert v2.llamadas == n and rep2["filas"] == rep2["filas_previas"] == len(acum)
    pd.testing.assert_frame_equal(ao.leer_acumulado(archivo), acum)
    assert len(pd.read_csv(archivo / "registro.csv")) == 2
    # sin red: no pide nada y tampoco cambia
    rep3 = ao.archivar(descargar=False, carpeta=archivo, carpeta_crudo=crudo, ids=ids)
    assert rep3["filas"] == len(acum) and rep3["capturas_nuevas"] == []
