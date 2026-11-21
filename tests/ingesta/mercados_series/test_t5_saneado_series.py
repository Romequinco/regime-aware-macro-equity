"""Saneado del Tema 1 (2026-11-21), parte de series: P03, P09, P10, P12, P13, P15, P16, P17, P19, P20, P22, P23, P24,
P29, P30 y P31.

Las pruebas unitarias son sintéticas (sin red ni corpus). Las de ``@pytest.mark.datos`` miran la base curada real y se
saltan si falta (``python -m ingesta.mercados_series curar``).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import almacen, base, catalogo, curada, tools
from ingesta.mercados_series import preprocesado as pp
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, validar_series
from ingesta.mercados_series.fuentes import academicos, alfred, wdi_archivo


def _filas(serie, refs, pubs, valores, *, vintage="unico", fuente="eurostat", metodo="lag_fijo", nota=None):
    n = len(refs)
    return pd.DataFrame({
        "serie": serie, "fecha_referencia": pd.to_datetime(refs), "fecha_publicacion": pd.to_datetime(pubs),
        "disponible_utc": pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns, UTC]"),
        "vintage": vintage, "valor": np.asarray(valores, dtype=float), "unidad": "x", "divisa": None,
        "fuente": fuente, "metodo_publicacion": metodo, "nota": nota})[list(COLUMNAS_SERIES)]


# --- P17: ALFRED, periodo vigente con el mismo valor en dos vintages ------------------------------------------------
def test_p17_compactar_no_inventa_retiradas():
    obs = alfred.parsear_vintages([
        {"date": "2026-08-01", "value": "1.5", "realtime_start": "2026-09-11", "realtime_end": "2026-11-09"},
        {"date": "2026-08-01", "value": "1.5", "realtime_start": "2026-11-10", "realtime_end": "9999-12-31"},
        {"date": "2026-09-01", "value": "2.0", "realtime_start": "2026-10-14", "realtime_end": "9999-12-31"},
    ])
    df, fundidas = alfred._compactar(obs)
    assert fundidas == 1 and df["realtime_end"].isna().all()       # el tramo fundido sigue vigente
    assert alfred._retiradas(df).empty                              # antes salía una fila nula el 2026-11-10


# --- P13: vintage con fecha en Eurostat, BIS y RBA ------------------------------------------------------------------
def test_p13_fechar_vintages_y_conservar_la_correccion():
    guardado = _filas("eurostat:X", ["2026-01-01", "2026-02-01"], ["2026-03-01", "2026-04-01"], [1.0, 2.0],
                      nota=catalogo.NOTA_REVISABLE_EDICION)
    nuevo = _filas("eurostat:X", ["2026-01-01", "2026-02-01", "2026-03-01"], ["2026-03-01", "2026-04-01", "2026-05-01"],
                   [1.0, 2.5, 3.0], nota=catalogo.NOTA_REVISABLE_EDICION)
    obs = pd.Timestamp("2026-11-21 15:00", tz="UTC")
    t, g, migradas = base.fechar_vintages(nuevo, guardado, obs)
    assert migradas == ["eurostat:X"] and set(g["vintage"]) == {"2026-10-13"}
    v = t.set_index("fecha_referencia")["vintage"]
    assert v["2026-01-01"] == "2026-10-13"                           # mismo valor: misma clave que lo guardado
    assert v["2026-02-01"] == "2026-11-21" and v["2026-03-01"] == "2026-11-21"
    assert "posible fuga" not in str(t.set_index("fecha_referencia").loc["2026-02-01", "nota"])
    out, info, _ = base.conservar_revisiones(t, g, ["eurostat:X"], obs)
    out = validar_series(out)
    feb = out[out["fecha_referencia"] == "2026-02-01"].sort_values("fecha_publicacion")
    assert len(feb) == 2 and feb["valor"].tolist() == [2.0, 2.5]     # la corrección ya no se tira
    assert feb["fecha_publicacion"].iloc[1] >= pd.Timestamp("2026-11-21")
    assert info["fechadas_observacion"] == 1
    # Idempotente: la segunda vez todo coincide con lo guardado.
    t2, g2, _ = base.fechar_vintages(nuevo, out, obs + pd.Timedelta(days=1))
    out2, info2, _ = base.conservar_revisiones(t2, g2, ["eurostat:X"], obs + pd.Timedelta(days=1))
    assert info2["fechadas_observacion"] == 0 and info2["conservadas"] == 0


def test_p13_otras_fuentes_no_cambian():
    t = _filas("boe:X", ["2026-01-01"], ["2026-01-02"], [1.0], fuente="boe_curvas")
    t2, g2, mig = base.fechar_vintages(t, t.iloc[:0], pd.Timestamp("2026-11-21", tz="UTC"))
    assert (t2["vintage"] == "unico").all() and mig == []


# --- P30: vacíos en días de mercado cerrado ------------------------------------------------------------------------
def test_p30_vacios_en_festivo_fuera():
    pytest.importorskip("exchange_calendars")
    t = pd.concat([_filas("boc:BOND.2Y", ["2006-09-01", "2006-09-04", "2006-09-05"], ["2006-09-02", "2006-09-05",
                                                                                        "2006-09-06"],
                          [4.0, np.nan, 4.1], fuente="boc_curva", metodo="calendario", nota="hueco"),
                   _filas("boc:BOND.2Y", ["2006-09-06"], ["2006-09-07"], [np.nan], fuente="boc_curva",
                          metodo="calendario", nota="hueco")], ignore_index=True)
    out, n = base.quitar_vacios_cerrados(t)
    assert n == 1 and pd.Timestamp("2006-09-04") not in set(out["fecha_referencia"])   # Labour Day: XTSE cerrado
    assert pd.Timestamp("2006-09-06") in set(out["fecha_referencia"])                   # hueco en día de sesión: sigue


# --- P23: archivo del WDI ---------------------------------------------------------------------------------------------
def _edicion_wdi(ruta, version, valores):
    data = [{"variable": [{"concept": "Country", "id": "USA"}, {"concept": "Time", "id": f"YR{a}"},
                          {"concept": "Series", "id": "FP.CPI.TOTL.ZG"}, {"concept": "Version", "id": version}],
             "value": v} for a, v in valores.items()]
    (ruta / f"{version}.json").write_text(json.dumps({"source": {"data": data}}), encoding="utf-8")


def test_p23_tabla_archivo_estilo_alfred(tmp_path, monkeypatch):
    carpeta = tmp_path / "worldbank" / wdi_archivo.CARPETA
    carpeta.mkdir(parents=True)
    _edicion_wdi(carpeta, "200104", {1999: 2.0, 2000: 3.0})
    _edicion_wdi(carpeta, "200204", {1999: 2.0, 2000: 3.2, 2001: 1.5})
    monkeypatch.setattr(wdi_archivo.org, "ruta_crudo", lambda fuente, raiz=None: tmp_path / fuente)
    cat = {"wb:USA.FP.CPI.TOTL.ZG": {"unidad": "% anual", "divisa": None, "metodo": "lag_fijo"}}
    t = wdi_archivo.tabla_archivo(["wb:USA.FP.CPI.TOTL.ZG"], catalogo=cat)
    assert len(t) == 4                                                  # 2 + (2000 revisado, 2001 nuevo)
    assert set(t["vintage"]) == {"2001-05-01", "2002-05-01"}
    a2000 = t[t["fecha_referencia"] == "2000-01-01"].sort_values("fecha_publicacion")
    assert a2000["valor"].tolist() == [3.0, 3.2]
    assert (t["fecha_publicacion"] >= t["fecha_referencia"]).all()
    assert wdi_archivo.fecha_version("200412") == pd.Timestamp("2005-01-01")


# --- P15 descartado: las capturas de la Wayback que haya en el crudo no cuentan como ediciones ----------------------
def test_p15_descartado_capturas_wayback_ignoradas(tmp_path):
    import json

    ruta = tmp_path / "ofr_fsi" / "ediciones" / "2019-01" / "20190109_fsi.csv"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("Date,OFR FSI" + chr(10) + "2019-01-07,1.0" + chr(10), encoding="utf-8")
    meta = {"origen": academicos.ORIGEN_WAYBACK, "descargado_utc": "2019-01-09T16:03:43+00:00"}
    ruta.with_name(ruta.name + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert academicos.ediciones("ofr_fsi", "fsi.csv", tmp_path) == []
    assert "ofr_fsi" not in academicos.FUENTES_VINTAGE

# --- P29: octubre de 2025 rellenado -----------------------------------------------------------------------------------
def test_p29_relleno_del_mes_no_publicado_y_variaciones():
    refs = ["2025-08-01", "2025-09-01", "2025-11-01", "2025-09-01"]
    pubs = ["2025-09-05", "2025-10-03", "2025-12-16", "2026-01-09"]
    vint = ["2025-09-05", "2025-10-03", "2025-12-16", "2026-01-09"]
    cur = _filas("fred:UNRATE", refs, pubs, [4.3, 4.4, 4.6, 4.5], vintage=vint, fuente="fred_alfred",
                 metodo="vintage_exacto")
    cat = {"fred:UNRATE": {"frecuencia": "mensual", "fuente": "fred_alfred"}}
    cur2, r = curada.rellenar_meses_no_publicados(cur, cat)
    assert len(r) == 1 and cur2.equals(cur)
    f = r.iloc[0]
    assert f["fecha_referencia"] == pd.Timestamp("2025-10-01") and f["valor"] == 4.4   # septiembre visible el 16-dic
    assert f["fecha_publicacion"] == pd.Timestamp("2025-12-16") and f["vintage"] == "2025-12-16"
    assert "relleno: mes no publicado" in f["nota"]
    todo = validar_series(pd.concat([cur, r], ignore_index=True))
    from ingesta.mercados_series import timegate
    antes = timegate.as_of_series(todo, "fred:UNRATE", "2025-12-15")
    assert pd.Timestamp("2025-10-01") not in set(antes["fecha_referencia"])           # nada antes del mes siguiente
    vista = timegate.as_of_series(todo, "fred:UNRATE", "2025-12-16").set_index("fecha_referencia")["valor"]
    var = vista.pct_change()
    assert var.loc["2025-10-01"] == 0 and np.isfinite(var.loc["2025-11-01"])           # sin huecos en las variaciones
    assert curada.rellenar_meses_no_publicados(cur[cur["fecha_referencia"] != "2025-11-01"], cat)[1].empty
    # Con la fila vacía de ALFRED («'.'» en el vintage del mes siguiente): se rellena en el sitio, misma clave y fecha.
    vacia = _filas("fred:UNRATE", ["2025-10-01"], ["2025-12-16"], [np.nan], vintage="2025-12-16", fuente="fred_alfred",
                   metodo="vintage_exacto", nota="ALFRED sin valor ('.') en este vintage")
    con = pd.concat([cur, vacia], ignore_index=True)
    con2, r2 = curada.rellenar_meses_no_publicados(con, cat)
    assert r2.empty and len(con2) == len(con)
    f2 = con2[con2["fecha_referencia"] == "2025-10-01"].iloc[0]
    assert f2["valor"] == 4.4 and f2["fecha_publicacion"] == pd.Timestamp("2025-12-16") and "relleno" in f2["nota"]


# --- P10, P19, P20: avisos de get_serie ------------------------------------------------------------------------------
def test_p10_aviso_atraso_mensual():
    refs = pd.date_range("2023-01-01", "2025-12-01", freq="MS")
    vis = _filas("oecd:X", refs, refs + pd.Timedelta(days=45), np.arange(len(refs)))
    assert tools._aviso_atraso_periodica("oecd:X", vis, pd.Timestamp("2026-03-01")) is None
    a = tools._aviso_atraso_periodica("oecd:X", vis, pd.Timestamp("2026-06-01"))
    assert a and "datos atrasados" in a and "retraso mediano (45 días)" in a
    assert tools._aviso_atraso_periodica("gw:M.X", vis.assign(serie="gw:M.X"), pd.Timestamp("2027-06-01")) is None


def test_p19_aviso_vacios():
    d = pd.DataFrame({"fecha_referencia": pd.date_range("2020-01-01", periods=10), "valor": [1.0] * 6 + [np.nan] * 4})
    assert "4 de 10 periodos (40.0 %) vacíos" in tools._aviso_vacios("boe:NOM.6M", d)
    assert tools._aviso_vacios("x", d.assign(valor=1.0)) is None


def test_p20_p22_avisos_de_la_lista():
    avisos = tools._avisos_lista("oecd:UNEMP.EA20")
    assert any("composición fija" in a for a in avisos)
    assert not any("composición fija" in a for a in tools._avisos_lista("bis:WS_CBPOL.M.XM"))
    bbk = "bbk:BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A"
    assert any("historia previa de ecb:YC.AAA.10Y" in a for a in tools._avisos_lista(bbk))
    assert any(bbk in a for a in tools._avisos_lista("ecb:YC.AAA.10Y"))


# --- P12: calendario del DOL y F1 del RBA -----------------------------------------------------------------------------
def test_p12_reglas_dol_y_rba():
    plan = pp.cargar_plan()
    assert "fred:ICSA" not in plan["tramo_no_fiable"]["series"] and "fred:CCSA" not in plan["tramo_no_fiable"]["series"]
    assert pp._clave_conservadora(plan, "ICSA", "fred_alfred", "fred:ICSA") == ("otras_fred", "DOL_ICSA")
    assert pp._clave_conservadora(plan, "CLAIMS_CONTINUADAS", "fred_alfred", "fred:CCSA") == ("otras_fred",
                                                                                              "DOL_CONTINUADAS")
    assert pp._clave_conservadora(plan, "rba_diario", "rba", "rba:FIRMMCRTD")[1] == "RBA_F1"
    assert pp._clave_conservadora(plan, "rba_diario", "rba", "rba:FCMYGBAG10D")[1] == "rba_diario"
    # Sábado 2008-03-01: el DOL lo publica el jueves 6; la regla conservadora, el sábado 8 (antes, 61 días).
    r = plan["reglas_conservadoras"]["otras_fred"]["reglas"]["DOL_ICSA"]["conservadora"]
    assert pp.fecha_regla(pd.Series([pd.Timestamp("2008-03-01")]), r).iloc[0] == pd.Timestamp("2008-03-08")


# --- Lista curada y catálogo ------------------------------------------------------------------------------------------
def test_lista_saneada():
    lista = pp.cargar_lista()
    cat = catalogo.cargar_catalogo()
    assert not any(e["decision"] in ("queda", "proyecciones") for s, e in lista.items() if s.startswith("imf:"))  # P16
    assert lista["fred:DEXTAUS"]["decision"] == lista["fred:DEXCHUS"]["decision"] == "queda"              # P03
    assert lista["eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA21"]["rol"] == "canonico"                         # P09
    assert lista["eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA20"]["completa_a"].endswith("EA21")
    assert lista["fred:DFF"]["rol"] == "historia_previa" and lista["fred:DFF"]["completa_a"] == "fred:EFFR"  # P24
    assert lista["philly:ROUTPUT"]["decision"] == "fuera"                                                   # P10
    for s, e in lista.items():                                       # ningún alias ni historia previa sin destino
        destino = e.get("alias_de") or (e.get("completa_a") if e.get("decision") == "queda" else None)
        if e.get("decision") in ("alias", "queda") and destino:
            assert lista[destino]["decision"] == "queda", (s, destino)
    assert cat["oecd:CP.JPN"]["estado"] == "retirada" and cat["yf:^BCOM"]["estado"] == "retirada"         # P10, P21


# --- Datos reales -----------------------------------------------------------------------------------------------------
_CURADA = almacen.ruta_series(curada=True)


@pytest.mark.datos
@pytest.mark.skipif(not _CURADA.exists(), reason="sin base curada (python -m ingesta.mercados_series curar)")
def test_datos_curada_saneada():
    import pyarrow.parquet as pq

    ids = set(pq.read_table(_CURADA, columns=["serie"]).column("serie").unique().to_pylist())
    assert not any(s.startswith("imf:") for s in ids)                                       # P16
    assert {"fred:DEXTAUS", "fred:DEXCHUS"} <= ids                                           # P03
    r = tools.get_serie("fred:MEDCPIM158SFRBCLE", "2026-11-13", base="curada")               # P17
    d = r.datos.set_index("fecha_referencia")["valor"]
    assert d.loc["2026-08-01":"2026-09-01"].notna().all()
    u = tools.get_serie("fred:UNRATE", "2026-11-13", base="curada")                          # P29
    assert pd.Timestamp("2025-10-01") in set(u.datos["fecha_referencia"])
    assert any("mes no publicado" in a for a in u.avisos)
