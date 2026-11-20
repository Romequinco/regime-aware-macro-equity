"""Paso 3b-2 · fuentes macro (R3): Banco Mundial, Eurostat, OCDE, Philadelphia RTDSM y bancos centrales.

Sin red: fixtures sintéticas con el formato real de cada fuente (JSON del Banco Mundial, SDMX-CSV de
Eurostat y de la OCDE, matrices xlsx del RTDSM, hoja ``Data`` de los históricos del RBA y JSON de Valet).
"""
from __future__ import annotations

import io
import json
import zipfile

import openpyxl
import pandas as pd
import pytest
import requests

from ingesta.mercados_series import catalogo
from ingesta.mercados_series.contrato import validar_series
from ingesta.mercados_series.fuentes import b4_comun, bancos_centrales, eurostat, oecd, philly_rtdsm
from ingesta.mercados_series.fuentes import worldbank as wb


@pytest.fixture(scope="module")
def pubs():
    return b4_comun.publicaciones_b4()


# --- Banco Mundial: agregados de D3 -------------------------------------------------------------------
PAISES = json.dumps([{"page": 1, "pages": 1}, [
    {"id": c, "name": n, "region": {"id": r, "value": "x"}, "incomeLevel": {"value": "x"}}
    for c, n, r in [("ESP", "Spain", "ECS"), ("WLD", "World", "NA"), ("LMY", "Low & middle income", "NA"),
                    ("EMU", "Euro area", "NA"), ("EUU", "European Union", "NA"), ("AFE", "Africa E&S", "NA")]]])


def _indicador(isos):
    obs = [{"countryiso3code": c, "country": {"id": c}, "date": str(a), "value": 1.0 + a % 7}
           for c in isos for a in (2023, 2024)]
    return json.dumps([{"page": 1, "pages": 1, "total": len(obs), "lastupdated": "2026-11-11"}, obs])


def test_wb_admite_solo_los_agregados_de_d3():
    paises = wb.leer_paises(PAISES)
    assert set(wb.codigos_admitidos(paises)) == {"ESP", "WLD", "LMY", "EMU"}   # EUU y AFE fuera
    datos, _ = wb.leer_indicador(_indicador(["ESP", "WLD", "LMY", "EMU", "EUU", "AFE"]))
    t = wb.tabla_indicador(datos, "FP.CPI.TOTL.ZG", wb.codigos_admitidos(paises))
    validar_series(t)
    assert set(t["serie"]) == {f"wb:{c}.FP.CPI.TOTL.ZG" for c in ("ESP", "WLD", "LMY", "EMU")}
    agregado = t["serie"].str.startswith(("wb:WLD", "wb:LMY", "wb:EMU"))
    assert t.loc[agregado, "nota"].str.contains("agregado del Banco Mundial").all()
    assert not t.loc[~agregado, "nota"].str.contains("agregado del Banco Mundial").any()
    # misma regla que los países: fin del año siguiente
    assert (t["metodo_publicacion"] == "lag_fijo").all() and (t["vintage"] == "unico").all()


def test_wb_pide_rango_de_anios_explicito():
    """Regresión 2026-11-20: sin ``date`` la API dio solo el último año del paro (235 filas)."""
    p = wb.params_indicador("2026-11-20")
    assert p["date"] == "1960:2026" and p["per_page"] == 20000


def test_wb_catalogo_tiene_los_agregados():
    cat = catalogo.cargar_catalogo()
    for iso in wb.AGREGADOS:
        for ind in wb.INDICADORES:
            e = cat[f"wb:{iso}.{ind}"]
            assert e["fuente"] == "worldbank" and e["lag_clave"] == "WB_ANUAL" and e["nombre"].endswith(f" - {iso}")
    assert not [s for s in cat if s.startswith(("wb:EUU.", "wb:AFE."))]


# --- Eurostat: zona euro de composición cambiante (EA) ---------------------------------------------------
def _csv_esi(geos):
    filas = ["DATAFLOW,LAST UPDATE,freq,indic,s_adj,geo,TIME_PERIOD,OBS_VALUE,OBS_FLAG"]
    for g in geos:
        for m, v in (("2026-08", 95.1), ("2026-09", 95.6)):
            filas.append(f"ESTAT:EI_BSSI_M_R2(1.0),29/09/26 11:00:00,M,BS-ESI-I,SA,{g},{m},{v},")
    return "\n".join(filas) + "\n"


def test_eurostat_ea_si_se_publica_entra_sin_fecha_de_creacion(tmp_path):
    cli = eurostat.ClienteEurostat(transporte=lambda url, params: _csv_esi(["EA", "EA20", "AL"]),
                                   carpeta=tmp_path, hoy="2026-11-20")
    df, med = eurostat.tabla_eurostat(cli, conjuntos=["ei_bssi_m_r2"])
    sid = "eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.EA"
    assert sid in set(df["serie"]) and med["conjuntos"]["ei_bssi_m_r2"]["ea_cambiante"] is True
    assert eurostat.no_antes_de("ei_bssi_m_r2/M.BS-ESI-I.SA.EA") is None          # EA siempre existió
    assert eurostat.no_antes_de("ei_bssi_m_r2/M.BS-ESI-I.SA.EA20") == pd.Timestamp("2023-03-01")
    assert not set(df["serie"]) & {"eurostat:ei_bssi_m_r2.M.BS-ESI-I.SA.AL"}       # fuera de GEOS


def test_eurostat_sin_ea_queda_medido_como_limitacion(tmp_path):
    cli = eurostat.ClienteEurostat(transporte=lambda url, params: _csv_esi(["EA20", "EA21"]),
                                   carpeta=tmp_path, hoy="2026-11-20")
    df, med = eurostat.tabla_eurostat(cli, conjuntos=["ei_bssi_m_r2"])
    assert med["conjuntos"]["ei_bssi_m_r2"]["ea_cambiante"] is False
    assert not any(s.endswith(".EA") for s in df["serie"])
    assert set(eurostat.SIN_EA) == {"ei_bssi_m_r2", "une_rt_m"} and "PARO_EA" in eurostat.SIN_EA["une_rt_m"]


# --- OCDE: limitaciones y refresco por ediciones -----------------------------------------------------
CAB_OECD = "DATAFLOW,REF_AREA,FREQ,MEASURE,UNIT_MEASURE,ACTIVITY,EDITION,TIME_PERIOD,OBS_VALUE,OBS_STATUS"


def _csv_oecd(area, medida, ediciones):
    filas = [CAB_OECD]
    for ed in ediciones:
        fin = pd.Period(f"{ed[:4]}-{ed[4:]}", "M") - 1
        for per in pd.period_range(fin - 2, fin, freq="M"):
            filas.append(f"OECD.SDD.STES:DSD_STES_REVISIONS@DF_STES_REVISIONS(4.0),{area},M,{medida},IX,_Z,{ed},"
                         f"{per},{100 + int(ed[-2:]) / 10:.2f},A")
    return ("\n".join(filas) + "\n").encode()


def test_oecd_pares_sin_datos_declarados_y_no_se_piden(tmp_path):
    assert set(oecd.SIN_DATOS) == {("EA20", "LI_AA"), ("CHN", "UNEMP")}
    assert "G4E" in oecd.SIN_DATOS[("EA20", "LI_AA")] and "wb:CHN" in oecd.SIN_DATOS[("CHN", "UNEMP")]

    def prohibido(url, params):
        raise AssertionError("no debe pedir un par sin datos")
    inf = oecd.refrescar(["EA20", "CHN"], ["LI_AA", "UNEMP"], hoy="2026-11-20", transporte=prohibido,
                         carpeta=tmp_path)
    assert inf["EA20.LI_AA"]["estado"] == inf["CHN.UNEMP"]["estado"] == "limitacion"
    cat = catalogo.cargar_catalogo()
    assert any("limitación (paso 3b-2" in n for n in cat["oecd:LI_AA.EA20"]["notas"])
    assert any("limitación (paso 3b-2" in n for n in cat["oecd:UNEMP.CHN"]["notas"])


def test_oecd_ediciones_pendientes():
    assert oecd.ediciones_pendientes("2026-10-01", "2026-12-15") == ["202611", "202612"]
    assert oecd.ediciones_pendientes("2026-11-01", "2026-11-20") == []
    assert oecd.url_edicion("USA", "LI_AA", "202611").endswith("/USA.M.LI_AA...202611")


def test_oecd_refresco_solo_ediciones_nuevas_y_cargar_une(tmp_path, pubs):
    (tmp_path / "revisions_USA_LI_AA.csv").write_bytes(_csv_oecd("USA", "LI_AA", ["202609", "202610"]))
    pedidas = []

    def transporte(url, params):
        pedidas.append(url.rsplit(".", 1)[1])
        if url.endswith("202611"):
            return _csv_oecd("USA", "LI_AA", ["202611"])
        raise requests.HTTPError("404 Client Error: Not Found for url: " + url)
    inf = oecd.refrescar(["USA"], ["LI_AA"], hoy="2026-12-15", transporte=transporte, carpeta=tmp_path,
                         segundos=0)
    assert pedidas == ["202611", "202612"]
    assert inf["USA.LI_AA"] == {"ultima_previa": "202610", "nuevas": ["202611"], "estado": "refrescado"}
    assert (tmp_path / "revisions_USA_LI_AA__ed202611.csv").exists()
    # el crudo inicial no se toca y cargar_crudo une los dos (una edición repetida, una vez)
    (tmp_path / "revisions_USA_LI_AA__ed202610.csv").write_bytes(_csv_oecd("USA", "LI_AA", ["202610"]))
    d = oecd.cargar_crudo("USA", "LI_AA", tmp_path)
    assert sorted(d["edicion"].dt.strftime("%Y%m").unique()) == ["202609", "202610", "202611"]
    assert not d.duplicated(["edicion", "periodo"]).any()
    t = oecd.tabla_oecd("USA", "LI_AA", d, publicaciones=pubs)
    validar_series(t)
    assert "2026-11" in set(t["vintage"])
    # segundo refresco el mismo mes: nada que pedir
    pedidas.clear()
    assert oecd.refrescar(["USA"], ["LI_AA"], hoy="2026-11-20", transporte=transporte,
                          carpeta=tmp_path)["USA.LI_AA"]["estado"] == "al_dia" and not pedidas


def test_oecd_refresco_bloqueo_para_la_tanda_y_estado_por_codigo(tmp_path):
    for area in ("USA", "DEU"):
        (tmp_path / f"revisions_{area}_CP.csv").write_bytes(_csv_oecd(area, "CP", ["202603"]))

    def transporte(url, params):
        # Regresión: la edición 202604 contiene «404» en la URL; un 503 no es «edición inexistente».
        if "USA" in url:
            raise requests.HTTPError("503 Server Error: Service Unavailable for url: " + url)
        raise AssertionError("no debe llegar aquí")
    inf = oecd.refrescar(["USA"], ["CP"], hoy="2026-04-20", transporte=transporte, carpeta=tmp_path, segundos=0)
    assert inf["USA.CP"]["estado"] == "fallo"

    def bloqueo(url, params):
        if "USA" in url:
            raise requests.HTTPError("403 Client Error: Forbidden for url: " + url)
        raise AssertionError("tras un 403 no se pide nada más")
    inf = oecd.refrescar(["USA", "DEU"], ["CP"], hoy="2026-05-20", transporte=bloqueo, carpeta=tmp_path, segundos=0)
    assert inf["USA.CP"]["estado"] == "bloqueado" and inf["DEU.CP"]["estado"] == "pendiente_bloqueo"


# --- Philadelphia RTDSM ----------------------------------------------------------------------------------
def _xlsx_sas(df: pd.DataFrame) -> bytes:
    """xlsx con la fecha mal formada que escribe SAS en ``docProps/core.xml`` (``T 9:58:09``)."""
    b = io.BytesIO()
    df.to_excel(b, index=False)
    z = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as nuevo:
        for item in z.infolist():
            datos = z.read(item.filename)
            if item.filename == "docProps/core.xml":
                datos = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
                         b'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                         b'xmlns:dcterms="http://purl.org/dc/terms/" '
                         b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>C1PFD01</dc:creator>'
                         b'<dcterms:created xsi:type="dcterms:W3CDTF">2026-10-30T 9:58:09-04:00</dcterms:created>'
                         b'<dcterms:modified xsi:type="dcterms:W3CDTF">2026-10-30T 9:58:09-04:00</dcterms:modified>'
                         b'</cp:coreProperties>')
            nuevo.writestr(item, datos)
    return salida.getvalue()


def test_philly_lee_matriz_con_metadatos_sas_mal_formados(pubs):
    m = pd.DataFrame({"DATE": ["1965:Q2", "1965:Q3"], "ROUTPUT65Q4": [600.0, 610.0], "ROUTPUT66Q1": [600.0, 612.0]})
    crudo = _xlsx_sas(m)
    with pytest.raises(TypeError):
        openpyxl.load_workbook(io.BytesIO(crudo))           # lo que fallaba con las matrices de 2026-10
    assert philly_rtdsm.sanear_xlsx(crudo) != crudo
    largo = philly_rtdsm.leer_matriz(crudo)
    assert len(largo) == 4 and set(largo["columna"]) == {"ROUTPUT65Q4", "ROUTPUT66Q1"}
    t = philly_rtdsm.tabla_philly("ROUTPUT", crudo, primer_alfred="1991-12-04", publicaciones=pubs)
    validar_series(t)
    # un xlsx correcto no se toca
    b = io.BytesIO()
    m.to_excel(b, index=False)
    assert philly_rtdsm.sanear_xlsx(b.getvalue()) == b.getvalue()


def test_philly_sin_filas_por_diseno_documentado(pubs):
    # Todos los vintages posteriores al primero de ALFRED: ninguna fila (no es un fallo de descarga).
    m = pd.DataFrame({"DATE": ["1964:11", "1964:12"], "EMPLOY64M12": [60000.0, 60100.0],
                      "EMPLOY65M1": [60000.0, 60150.0]})
    t = philly_rtdsm.tabla_philly("EMPLOY", m, primer_alfred="1955-05-06", publicaciones=pubs)
    assert t.empty
    cat = catalogo.cargar_catalogo()
    for v in ("PCPI", "EMPLOY", "RUC"):
        assert any("sin filas por diseño" in n for n in cat[f"philly:{v}"]["notas"])
    assert "sin filas por diseño" in philly_rtdsm.NOTA_SIN_PREVIOS


# --- Bancos centrales: historia larga ---------------------------------------------------------------------
def _xlsx_rba(codigo: str, fechas: list[str], valores: list[float]) -> bytes:
    wbk = openpyxl.Workbook()
    hoja = wbk.active
    hoja.title = "Data"
    hoja.append(["F1 INTEREST RATES AND YIELDS – MONEY MARKET"])
    hoja.append(["Title", "Cash Rate Target", "Otro"])
    hoja.append(["Series ID", codigo, "FOTRO"])
    for f, v in zip(fechas, valores):
        hoja.append([pd.Timestamp(f).to_pydatetime(), v, 1.0])
    hoja.append([None, None, None])
    wbk.create_sheet("Notes").append(["notas"])
    b = io.BytesIO()
    wbk.save(b)
    return b.getvalue()


def _csv_rba(codigo, fechas, valores):
    filas = ["F1 INTEREST RATES", "Title,Cash Rate Target", f"Series ID,{codigo}"]
    filas += [f"{pd.Timestamp(f):%d-%b-%Y},{v}" for f, v in zip(fechas, valores)]
    return ("﻿" + "\n".join(filas) + "\n").encode("utf-8")


def test_rba_historico_alarga_la_misma_serie(tmp_path, monkeypatch, pubs):
    monkeypatch.setattr(bancos_centrales, "ruta_crudo", lambda fuente: tmp_path)
    (tmp_path / "rba_FIRMMCRTD.csv").write_bytes(_csv_rba("FIRMMCRTD", ["2011-01-04", "2011-01-05"], [4.75, 4.75]))
    h = _xlsx_rba("FIRMMCRTD", ["2010-12-30", "2010-12-31", "2011-01-04"], [4.75, 4.70, 9.99])
    assert list(bancos_centrales.leer_rba_xls(h, "FIRMMCRTD")) == [4.75, 4.70, 9.99]
    (tmp_path / "rba_hist_f01dhist.xls").write_bytes(h)
    t = bancos_centrales.tabla_serie("rba:FIRMMCRTD", publicaciones=pubs)
    validar_series(t)
    assert list(t["fecha_referencia"].dt.strftime("%Y-%m-%d")) == ["2010-12-30", "2010-12-31", "2011-01-04",
                                                                    "2011-01-05"]
    assert list(t["valor"]) == [4.75, 4.70, 4.75, 4.75]               # en la fecha común gana la vigente
    hist = t["nota"].notna()
    assert hist.tolist() == [True, True, False, False]
    assert t.loc[hist, "nota"].str.contains("f01dhist.xls").all()
    # misma regla que la tabla vigente: hábil siguiente (el 31-dic-2010 es viernes → lunes 3-ene)
    assert t["fecha_publicacion"].iloc[1] == pd.Timestamp("2011-01-03")
    assert (t["serie"] == "rba:FIRMMCRTD").all() and (t["metodo_publicacion"] == "calendario").all()


def test_rba_sin_historico_igual_que_antes(tmp_path, monkeypatch, pubs):
    monkeypatch.setattr(bancos_centrales, "ruta_crudo", lambda fuente: tmp_path)
    assert bancos_centrales.tabla_serie("rba:FCMYGBAG10D") is None                 # sin crudo
    (tmp_path / "rba_FCMYGBAG10D.csv").write_bytes(_csv_rba("FCMYGBAG10D", ["2013-05-20"], [3.1]))
    t = bancos_centrales.tabla_serie("rba:FCMYGBAG10D", publicaciones=pubs)
    assert len(t) == 1 and t["nota"].isna().all()
    assert set(bancos_centrales.HISTORICOS) == {"rba:FIRMMCRTD", "rba:FCMYGBAG10D"}
    assert all(h["url"].startswith("https://www.rba.gov.au/statistics/tables/xls-hist/")
               for hs in bancos_centrales.HISTORICOS.values() for h in hs)


def test_rba_descarga_historicos_una_vez(tmp_path, monkeypatch):
    monkeypatch.setattr(bancos_centrales, "ruta_crudo", lambda fuente: tmp_path)
    (tmp_path / "rba_hist_f02dhist.xls").write_bytes(b"x")
    inf = bancos_centrales.descargar_historicos("rba:FCMYGBAG10D")
    assert inf == {"f02dhist.xls": {"estado": "en_cache", "bytes": 1}}           # congelado: no se vuelve a pedir


def test_boc_objetivo_mensual_a_fin_de_mes(pubs):
    valet = json.dumps({"observations": [{"d": "1996-01-01", "STATIC_ATABLE_V39079": {"v": "5.56"}},
                                         {"d": "1996-02-01", "STATIC_ATABLE_V39079": {"v": "5.19"}},
                                         {"d": "1996-03-01", "STATIC_ATABLE_V39079": {"v": ""}}]}).encode()
    s = bancos_centrales.leer("boc:STATIC_ATABLE_V39079", valet)
    t = bancos_centrales.tabla_banco("boc:STATIC_ATABLE_V39079", s, publicaciones=pubs)
    validar_series(t)
    assert list(t["fecha_referencia"].dt.strftime("%Y-%m-%d")) == ["1996-01-01", "1996-02-01"]
    # el valor de enero (fin de mes, miércoles 31) se ve el hábil siguiente; febrero (jueves 29) el 1-mar
    assert list(t["fecha_publicacion"].dt.strftime("%Y-%m-%d")) == ["1996-02-01", "1996-03-01"]
    assert (t["fecha_publicacion"] > t["fecha_referencia"] + pd.offsets.MonthEnd(0)).all()
    cat = catalogo.cargar_catalogo()
    e = cat["boc:STATIC_ATABLE_V39079"]
    assert e["frecuencia"] == "mensual" and e["publicador"] == "boc_valet" and e["fuente"] == "boc"
    assert set(bancos_centrales.LIMITACIONES) == {"boc:V39079 (diaria antes de 2009-04-21)",
                                                  "boc:BD.CDN.10YR.DQ.YLD (antes de 2001-01-02)"}


def test_base_carga_bancos_con_historico(tmp_path, monkeypatch):
    from ingesta.mercados_series import base
    monkeypatch.setattr(bancos_centrales, "ruta_crudo", lambda fuente: tmp_path)
    (tmp_path / "rba_FIRMMCRTD.csv").write_bytes(_csv_rba("FIRMMCRTD", ["2011-01-04"], [4.75]))
    (tmp_path / "rba_hist_f01dhist.xls").write_bytes(_xlsx_rba("FIRMMCRTD", ["2010-12-31"], [4.75]))
    t = base.tabla_oficial("bancos_centrales")
    assert set(t["serie"]) == {"rba:FIRMMCRTD"} and len(t) == 2 and t["nota"].notna().sum() == 1
