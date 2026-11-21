"""Paso 3b-2 del Tema 1: ediciones y agregados del WEO (FMI) y refresco del BIS. Sin red y con datos SINTÉTICOS.

- Una edición antigua se fecha en su publicación real (``PUBLICATION_DATE`` del fichero, contrastada con
  ``FECHAS_EDICION``); si el FMI la corrigió después (``UPDATE_DATE``), en la corrección; nunca antes de la regla.
- Las proyecciones de cada edición van a sus series ``.PROY.H<h>`` (tabla aparte, D4), no a las de dato.
- Los agregados (``G001``, ``G163``, ``G200`` en la API) se cargan como ``imf:WEO.001/163/200`` y están en el catálogo.
- En la base de solo-añadir, una edición más antigua que llega después de la vigente conserva su fecha propia.
- El BIS sin red usa el último crudo archivado.
"""
from __future__ import annotations

import pandas as pd
import pytest

from ingesta.mercados_series import base, redundancia, timegate
from ingesta.mercados_series import catalogo as cat_mod
from ingesta.mercados_series.contrato import validar_series
from ingesta.mercados_series.fuentes import bis, imf


def _sdmx(areas: list[str], anios: list[int], valores: dict[tuple[str, str], list[float | None]], *,
          publicacion: str | None = None, actualizacion: str | None = None,
          country_update: str | None = None) -> dict:
    """SDMX-JSON 3.0 sintético con la forma de la API del FMI (atributos de conjunto y de serie)."""
    conceptos = sorted({c for _, c in valores})
    attrs_serie = [{"id": "SCALE"}, {"id": "DECIMALS_DISPLAYED"}, {"id": "OVERLAP"}]
    if country_update is not None:
        attrs_serie.append({"id": "COUNTRY_UPDATE_DATE"})
    attrs_ds = [{"id": "FULL_DESCRIPTION"}, {"id": "PUBLICATION_DATE"}, {"id": "UPDATE_DATE"}]
    series = {}
    for (a, c), vals in valores.items():
        obs = {str(i): [None if v is None else str(v)] for i, v in enumerate(vals)}
        at = [0, 0, 0] + ([country_update] if country_update is not None else [])
        series[f"{areas.index(a)}:{conceptos.index(c)}:0"] = {"attributes": at, "observations": obs}
    return {"data": {
        "structures": [{
            "dimensions": {"series": [{"id": "COUNTRY", "values": [{"id": a} for a in areas]},
                                      {"id": "INDICATOR", "values": [{"id": c} for c in conceptos]},
                                      {"id": "FREQUENCY", "values": [{"id": "A"}]}],
                           "observation": [{"id": "TIME_PERIOD", "values": [{"value": str(y)} for y in anios]}]},
            "attributes": {"dataSet": attrs_ds, "series": attrs_serie}}],
        "dataSets": [{"action": "Replace",
                      "attributes": [None, [publicacion] if publicacion else None,
                                     [actualizacion] if actualizacion else None],
                      "series": series}]}}


# Edición de 2025-04 (sintética): sin COUNTRY_UPDATE_DATE, como la versión 6.0.0 de la API.
ANIOS = [2022, 2023, 2024, 2025, 2026, 2030, 2031]
ED_2025_04 = _sdmx(["USA", "G163"], ANIOS,
                   {("USA", "LUR"): [3.6, 3.6, 4.0, 4.2, 4.3, 4.0, 4.1],
                    ("G163", "NGDP_RPCH"): [3.5, 0.4, 0.9, 0.8, 1.2, 1.3, 1.3]},
                   publicacion="2025-04-22T13:00:00Z", actualizacion="2025-04-22T13:00:00Z")


# --- 1. Una edición antigua se fecha en su publicación real -----------------------------------------
def test_edicion_antigua_fechada_en_su_publicacion_real():
    datos, ed = imf.leer_sdmx(ED_2025_04)
    assert ed == "2025-04"                                     # de PUBLICATION_DATE (sin COUNTRY_UPDATE_DATE)
    f = imf.fechas_sdmx(ED_2025_04)
    assert f["publicacion"] == pd.Timestamp("2025-04-22 13:00", tz="UTC")
    t, _ = imf.tabla_edicion(datos, ed, f)
    validar_series(t)
    assert (t["vintage"] == "2025-04").all()
    assert (t["fecha_publicacion"] == pd.Timestamp(imf.FECHAS_EDICION["2025-04"])).all()      # 2025-04-22
    assert (t["disponible_utc"] == pd.Timestamp("2025-04-22 13:00", tz="UTC")).all()           # 09:00 de Washington
    assert t["nota"].fillna("").str.contains("actualizada").sum() == 0


def test_edicion_corregida_despues_se_fecha_en_la_correccion():
    # 2025-10 (sintética): publicada el 14-oct y actualizada por el FMI el 19-nov a las 16:00 de Nueva York.
    j = _sdmx(["USA"], [2023, 2024, 2025], {("USA", "LUR"): [3.6, 4.0, 4.2]},
              publicacion="2025-10-14T13:00:00Z", actualizacion="2025-11-19T21:00:00Z")
    datos, ed = imf.leer_sdmx(j)
    t, _ = imf.tabla_edicion(datos, ed, imf.fechas_sdmx(j))
    assert ed == "2025-10" and (t["fecha_publicacion"] == pd.Timestamp("2025-11-19")).all()
    assert (t["disponible_utc"] == pd.Timestamp("2025-11-19 21:00", tz="UTC")).all()
    assert t["nota"].str.contains("actualizada por el FMI el 2025-11-19 (publicada el 2025-10-14)", regex=False).all()


def test_fichero_anterior_a_la_regla_no_la_adelanta():
    # 2026-10: el fichero dice 02:00 UTC (mañana de Bangkok); la hora medida (07:46 de Nueva York) es más tardía.
    j = _sdmx(["USA"], [2024, 2025], {("USA", "LUR"): [4.0, 4.2]},
              publicacion="2026-10-13T02:00:00Z", actualizacion="2026-10-13T02:00:00Z", country_update="9/24/2026")
    datos, ed = imf.leer_sdmx(j)
    disp, dia, nota = imf.instante_edicion(ed, imf.fechas_sdmx(j))
    assert ed == "2026-10" and disp == imf.disponible("2026-10") and dia == pd.Timestamp("2026-10-13") and nota is None
    # Sin atributos de conjunto, la edición sale de COUNTRY_UPDATE_DATE y manda la regla documentada.
    sin = _sdmx(["USA"], [2024], {("USA", "LUR"): [4.0]}, country_update="3/20/2026")
    assert imf.fechas_sdmx(sin) == {"publicacion": None, "actualizacion": None}
    assert imf.leer_sdmx(sin)[1] == "2026-04"


def test_flujos_de_ediciones_archivadas():
    assert imf.flujo_version("WEO_2025_OCT_VINTAGE/1.0.0") == ("WEO_2025_OCT_VINTAGE", "1.0.0")
    assert imf.flujo_version("9.0.0") == ("WEO", "9.0.0")
    assert imf.edicion_del_flujo("WEO_2026_APR_VINTAGE") == "2026-04" and imf.edicion_del_flujo("WEO") is None
    url = imf.url_sdmx("WEO_2025_OCT_VINTAGE/1.0.0")
    assert "/IMF.RES/WEO_2025_OCT_VINTAGE/1.0.0/" in url and "G001+G163+G200" in url
    assert "db.nomics" not in url


# --- 2. Las proyecciones de una edición van aparte (D4) -----------------------------------------------
def test_proyecciones_de_la_edicion_van_aparte():
    datos, ed = imf.leer_sdmx(ED_2025_04)
    t, cuenta = imf.tabla_edicion(datos, ed, imf.fechas_sdmx(ED_2025_04))
    dato = t[~t["serie"].map(imf.es_proyeccion)]
    proy = t[t["serie"].map(imf.es_proyeccion)]
    assert dato["fecha_referencia"].dt.year.max() == 2024                     # solo años anteriores al de la edición
    assert set(proy["serie"]) == {imf.id_proyeccion(a, c, h) for a, c in (("USA", "LUR"), ("163", "NGDP_RPCH"))
                                  for h in (0, 1, 5)}
    assert (proy["fecha_referencia"] == pd.Timestamp("2025-01-01")).all()
    assert proy["nota"].str.startswith("proyección del WEO (no es un dato)").all()
    assert cuenta["proyecciones_descartadas"] == 2                            # 2031: más allá de HORIZONTE_MAX
    # Las proyecciones se fechan igual que los datos de su edición.
    assert (proy["fecha_publicacion"] == pd.Timestamp("2025-04-22")).all()


# --- 3. Los agregados se cargan ------------------------------------------------------------------
def test_agregados_se_cargan_con_el_codigo_del_weo():
    datos, _ = imf.leer_sdmx(ED_2025_04)
    assert set(datos["pais"]) == {"USA", "163"}
    t, _ = imf.tabla_edicion(datos, "2025-04")
    assert "imf:WEO.163.NGDP_RPCH" in set(t["serie"])
    assert imf.area_de_api("G001") == "001" and imf.area_de_api("USA") == "USA"
    frag = imf.fragmento(["imf:WEO.163.NGDP_RPCH", "imf:WEO.200.PCPIPCH.PROY.H2"])
    assert frag["imf:WEO.163.NGDP_RPCH"]["nombre"].endswith("- zona euro")
    assert frag["imf:WEO.163.NGDP_RPCH"]["id_origen"] == "WEO/G163.NGDP_RPCH"
    assert "PROYECCIÓN, no dato" in frag["imf:WEO.200.PCPIPCH.PROY.H2"]["notas"][0]
    for a in imf.AGREGADOS:
        assert a in redundancia.AGREGADOS and redundancia.motivo_alcance(a) == "agregado"     # D3
    # D9 y D8 entre agregados: 163 es la zona euro; 001 y 200 se comparan con WLD y LMY del Banco Mundial.
    assert [redundancia.pais_normalizado(a) for a in ("163", "001", "200", "EMU")] == ["EA", "WLD", "LMY", "EA"]
    assert redundancia.concepto_de("imf:WEO.163.PCPIPCH") == redundancia.concepto_de("wb:EMU.FP.CPI.TOTL.ZG")
    assert redundancia.concepto_de("imf:WEO.001.NGDP_RPCH") == redundancia.concepto_de("wb:WLD.NY.GDP.MKTP.KD.ZG")


def test_nota_d1_calculada():
    assert imf.nota_d1("2025-04-22").endswith("no cumple D1 (<= 2001-01-02) ni llega a 2008")
    assert imf.nota_d1("2005-04-20").endswith("no cumple D1 (<= 2001-01-02) y llega a 2008")
    assert imf.nota_d1("1990-05-01") == "D1: primera publicación visible 1990-05-01: cumple D1 (<= 2001-01-02)"


def test_agregados_en_el_catalogo():
    cat = cat_mod.cargar_catalogo()
    weo = {s: e for s, e in cat.items() if s.startswith("imf:WEO.")}
    for sid in ("imf:WEO.001.NGDP_RPCH", "imf:WEO.001.PCPIPCH", "imf:WEO.163.LUR", "imf:WEO.200.GGXWDG_NGDP",
                "imf:WEO.163.LUR.PROY.H5"):
        assert sid in weo, sid
        assert weo[sid]["metodo"] == "vintage_exacto" and weo[sid]["publicador"] == "imf_weo"
    # El catálogo coincide con el extractor (también en las 280 series de países; el cargador normaliza alias).
    frag = imf.fragmento(sorted(weo))
    campos = ("nombre", "fuente", "id_origen", "frecuencia", "unidad", "metodo", "publicador", "revisable",
              "licencia", "estado", "notas")
    assert all(weo[s][c] == frag[s][c] for s in weo for c in campos)
    assert len(weo) == 357 and all("DBnomics" not in e["licencia"] for e in weo.values())


def test_tabla_weo_con_las_cuatro_ediciones_y_d1(monkeypatch):
    fichas = {
        "WEO/9.0.0": _sdmx(["USA", "G001"], [2024, 2025, 2026], {("USA", "LUR"): [4.0, 4.2, 4.3],
                                                                  ("G001", "NGDP_RPCH"): [3.3, 3.2, 3.1]},
                           publicacion="2026-10-13T02:00:00Z", actualizacion="2026-10-13T02:00:00Z"),
        "WEO/6.0.0": ED_2025_04,
        "WEO_2026_APR_VINTAGE/1.0.0": _sdmx(["USA"], [2025, 2026], {("USA", "LUR"): [4.2, 4.3]},
                                            publicacion="2026-04-14T13:00:00Z"),
        # Un flujo archivado cuyo fichero es de otra edición: se descarta con el motivo.
        "WEO_2025_OCT_VINTAGE/1.0.0": _sdmx(["USA"], [2024], {("USA", "LUR"): [4.0]},
                                            publicacion="2025-04-22T13:00:00Z"),
    }
    monkeypatch.setattr(imf, "descargar_sdmx", lambda v, **k: (fichas[v], {"bytes": 1}))
    monkeypatch.setattr(imf, "descargar_dbnomics", lambda *a, **k: pytest.fail("DBnomics no se usa (G3)"))
    t, informe = imf.tabla_weo()
    assert sorted(t["vintage"].unique()) == ["2025-04", "2026-04", "2026-10"]
    assert "el flujo es de 2025-10" in informe["sdmx_WEO_2025_OCT_VINTAGE/1.0.0"]["error"]
    assert informe["2026-04"]["fecha_publicacion"] == "2026-04-14"
    assert imf.primera_publicacion(t) == "2025-04-22"                          # D1: no llega a 2001 ni a 2008
    assert "imf:WEO.001.NGDP_RPCH" in set(t["serie"])


# --- 4. Base de solo-añadir: la edición antigua que llega después conserva su fecha ---------------------
def test_edicion_antigua_tras_la_vigente_conserva_su_fecha_en_la_base():
    sid = "imf:WEO.USA.LUR"

    def edicion(ed: str, valores: list[float]) -> pd.DataFrame:
        j = _sdmx(["USA"], [2023, 2024], {("USA", "LUR"): valores})
        return imf.tabla_edicion(imf.leer_sdmx(j)[0], ed)[0]

    guardado = edicion("2026-10", [3.6, 4.1])                                  # lo que ya está en la base
    nueva = pd.concat([guardado, edicion("2025-04", [3.6, 4.0])], ignore_index=True)   # 2023 igual, 2024 distinto
    out, info, _ = base.conservar_revisiones(validar_series(nueva), guardado, [sid],
                                             observado=pd.Timestamp("2026-11-20 15:00", tz="UTC"))
    vieja = out[out["vintage"] == "2025-04"].set_index("fecha_referencia")
    assert (vieja["fecha_publicacion"] == pd.Timestamp("2025-04-22")).all()       # ni la observación ni la guardada
    assert vieja["disponible_utc"].notna().all() and vieja["nota"].isna().all()
    assert info["fecha_propia"] == 2 and info["fechadas_observacion"] == 0 and info["mismo_valor"] == 0
    # Vista as-of: la edición de 2025-04 hasta el 2026-10-13; la vigente después (y hoy).
    for f, esperado in (("2025-06-01", 4.0), ("2026-10-12", 4.0), ("2026-10-13", 4.1), ("2026-11-20", 4.1)):
        r = timegate.as_of_series(out, sid, f)
        assert r.loc[r["fecha_referencia"] == pd.Timestamp("2024-01-01"), "valor"].iloc[0] == esperado, f


# --- 5. BIS: el refresco sin red usa el último crudo archivado --------------------------------------------
def test_bis_sin_red_usa_el_ultimo_crudo(tmp_path):
    carpeta = tmp_path / "bis"
    carpeta.mkdir()
    cab = "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
    (carpeta / "20261013_WS_CBPOL.csv").write_text(cab + "M,US,2026-09,4.25\n", encoding="utf-8")
    (carpeta / "20261120_WS_CBPOL.csv").write_text(cab + "M,US,2026-09,4.25\nM,US,2026-10,4.00\n", encoding="utf-8")
    t, _ = bis.tabla_bis(["WS_CBPOL"], sin_red=True, raiz=tmp_path)
    assert t["fecha_referencia"].max() == pd.Timestamp("2026-10-01")
    assert t.set_index("fecha_referencia").loc["2026-10-01", "fecha_publicacion"] == pd.Timestamp("2026-11-07")
