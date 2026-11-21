"""Paso 4 de la descarga completa del Tema 1 · ``curada``: la base curada de series (sin tocar la base de trabajo).

Las pruebas unitarias usan el plan del repo (``preprocesado.yaml``) adaptado a unas pocas series sintéticas, sin
red ni corpus. La última lleva ``@pytest.mark.datos`` y se salta si falta la base curada real
(``python -m ingesta.mercados_series curar``).
"""
from __future__ import annotations

import copy
import hashlib

import numpy as np
import pandas as pd
import pytest

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import almacen, catalogo, curada
from ingesta.mercados_series import preprocesado as pp
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, fecha_publicacion_derivada
from ingesta.mercados_series.fuentes import fase1

TABLAS = resultados_dir("mercados_series") / "tablas"
CORTE = pd.Timestamp("2012-06-01")
TRAMO = pd.Timestamp("2010-06-04")
EXTRA = 26
SUBCADENAS = ("fecha no medible", "tramo conservador", "escala corregida")
VOL = "deriv:VOLREAL21_GSPC"
CAT_VOL = {"metodo": "derivada", "componentes": ["yf:^GSPC"], "estado": "activa", "revisable": False,
           "unidad": "tanto por uno anualizado", "divisa": None, "fuente": "calculo_propio"}
SERIES_QUEDA = {"fred:NF", "fred:HP", "fred:ESC", "deriv:NF-B", "gw:M.ltr", "gw:M.svar", "ecb:HICPX", "yf:^GSPC", VOL}


# --- Escenario sintético ------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def plan_real() -> dict:
    return pp.cargar_plan()


def _plan(plan_real: dict) -> dict:
    p = copy.deepcopy(plan_real)
    p["tramo_no_fiable"]["series"] = {"fred:NF": {
        "regla": "UNRATE", "veredicto": "no fiable", "corte": str(TRAMO.date()), "adelanto_dias": EXTRA - 7,
        "medida": "alfred_previa", "n": 100, "dias_extra": EXTRA,
        "conservadora": {"lag": pp.sumar_dias_lag("1M1D", EXTRA), "fin_periodo": "mes"}}}
    p["reconstruidas"]["series"] = {}
    p["reconstruidas"]["externas"] = {}
    p["escalas_por_vintage"]["series"] = [{"serie": "fred:ESC", "antes_de_vintage": "2010-01-01", "factor": 1000.0}]
    p["proyecciones"]["esperadas"] = {"fred_alfred": 1, "total": 1}
    return p


def _filas(serie: str, refs, pub, vintage, valor, metodo: str = "lag_fijo") -> pd.DataFrame:
    n = len(refs)
    return pd.DataFrame({
        "serie": serie, "fecha_referencia": pd.to_datetime(refs), "fecha_publicacion": pd.to_datetime(pub),
        "disponible_utc": pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns, UTC]"),
        "vintage": vintage, "valor": np.asarray(valor, dtype=float), "unidad": "x", "divisa": None,
        "fuente": "fred_alfred", "metodo_publicacion": metodo, "nota": None})


def _escenario(plan_real: dict) -> dict:
    refs = pd.date_range("2008-01-01", "2012-12-01", freq="MS")
    pub_nf = catalogo.fecha_publicacion_clave(pd.Series(refs), "UNRATE")
    nf = _filas("fred:NF", refs, pub_nf, "unico", np.arange(len(refs)) + 10.0)
    b = _filas("fred:B", refs, refs + pd.Timedelta(days=40), "unico", np.arange(len(refs)) * 0.5)
    hp = _filas("fred:HP", refs[:12], refs[:12] + pd.Timedelta(days=45), "unico", np.ones(12))
    refs_e = pd.date_range("2008-01-01", periods=6, freq="MS")
    esc = pd.concat([_filas("fred:ESC", refs_e, ["2009-06-01"] * 6, "2009-06-01", np.ones(6), "vintage_exacto"),
                     _filas("fred:ESC", refs_e, ["2011-06-01"] * 6, "2011-06-01", np.full(6, 1000.0),
                            "vintage_exacto")], ignore_index=True)
    proy = _filas("fred:PROYMD", ["2013-01-01", "2014-01-01"], ["2010-09-22"] * 2, "2010-09-22", [2.0, 2.5],
                  "vintage_exacto")
    comp = pd.concat([nf, b], ignore_index=True)
    fd = fecha_publicacion_derivada(comp, ["fred:NF", "fred:B"])
    dv = _filas("deriv:NF-B", fd["fecha_referencia"], fd["fecha_publicacion"], "unico",
                nf.set_index("fecha_referencia").loc[fd["fecha_referencia"], "valor"].to_numpy()
                - b.set_index("fecha_referencia").loc[fd["fecha_referencia"], "valor"].to_numpy(), "derivada")
    dv["fuente"] = "calculo_propio"
    # Homogeneización (la del plan real): GW ×100, sin_escalar intacta, unidad equivalente renombrada, VOLREAL21 ×100
    ltr = _filas("gw:M.ltr", refs[:24], refs[:24] + pd.Timedelta(days=40), "unico", np.full(24, 0.01), "fichero")
    ltr["unidad"] = "tanto por uno mensual"
    svar = _filas("gw:M.svar", refs[:24], refs[:24] + pd.Timedelta(days=40), "unico", np.full(24, 0.002), "fichero")
    svar["unidad"] = "tanto por uno al cuadrado (mensual)"
    hicp = _filas("ecb:HICPX", refs[:24], refs[:24] + pd.Timedelta(days=20), "unico", np.full(24, 2.0))
    hicp["unidad"] = "% interanual"
    sesiones = pd.bdate_range("2009-01-02", periods=60)
    gspc = _filas("yf:^GSPC", sesiones, sesiones, "unico", 900 * np.exp(np.cumsum(np.sin(np.arange(60)) / 50)),
                  "cierre_mercado")
    gspc["unidad"] = "puntos"
    vol = fase1.vol_realizada(VOL, CAT_VOL, gspc, pd.Timestamp.min)
    base = pd.concat([nf, b, hp, esc, proy, dv, ltr, svar, hicp, gspc, vol], ignore_index=True)[list(COLUMNAS_SERIES)]
    lista = {
        "fred:NF": {"decision": "queda", "rol": "canonico", "aviso_fecha": "no fiable"},
        "fred:B": {"decision": "alias", "rol": "alias", "regla": "D8_estrella", "alias_de": "fred:NF",
                   "motivo": "D8: |Pearson| 0.990 (diaria) con fred:NF, regla en estrella"},
        "fred:HP": {"decision": "queda", "rol": "historia_previa", "completa_a": "fred:NF"},
        "fred:ESC": {"decision": "queda", "rol": "unica"},
        "fred:PROYMD": {"decision": "proyecciones", "rol": "proyeccion"},
        "deriv:NF-B": {"decision": "queda", "rol": "unica"},
        **{s: {"decision": "queda", "rol": "unica"} for s in ("gw:M.ltr", "gw:M.svar", "ecb:HICPX", "yf:^GSPC", VOL)},
    }
    inv = pd.DataFrame([
        {"id": "fred:NF", "veredicto_desde_2000": "no fiable", "clave_regla": "UNRATE", "fuente": "fred_alfred",
         "metodo_publicacion": "lag_fijo"},
        {"id": "fred:B", "veredicto_desde_2000": "fiable", "clave_regla": "UNRATE", "fuente": "fred_alfred",
         "metodo_publicacion": "lag_fijo"},
        {"id": "fred:HP", "veredicto_desde_2000": "fiable", "clave_regla": "UNRATE", "fuente": "fred_alfred",
         "metodo_publicacion": "lag_fijo"},
        {"id": "fred:ESC", "veredicto_desde_2000": "exacta", "clave_regla": None, "fuente": "fred_alfred",
         "metodo_publicacion": "vintage_exacto"},
        {"id": "deriv:NF-B", "veredicto_desde_2000": None, "clave_regla": None, "fuente": "calculo_propio",
         "metodo_publicacion": "derivada"}])
    fia = pd.DataFrame({"regla": ["UNRATE"], "n_comparaciones": [100]})
    cat = {"deriv:NF-B": {"metodo": "derivada", "componentes": ["fred:NF", "fred:B"], "id_origen": "fred:NF - fred:B",
                          "estado": "activa", "revisable": False, "unidad": "x", "divisa": None,
                          "fuente": "calculo_propio"}, VOL: CAT_VOL}
    p = _plan(plan_real)
    sim = pp.simular(base=base, plan=p, lista=lista, inventario_series=inv, fiabilidad=fia, catalogo_series=cat)
    pares = pd.DataFrame([{"serie_a": "fred:NF", "serie_b": "fred:B", "frecuencia": "mensual", "pearson": 0.99,
                           "spearman": 0.98, "n": 60, "anios_solape": 5.0, "base_correlacion": "diaria"}])
    return {"base": base, "plan": p, "lista": lista, "inventario_series": inv, "fiabilidad": fia,
            "catalogo_series": cat, "simulacion": sim, "pares": pares}


@pytest.fixture()
def esc(plan_real) -> dict:
    return _escenario(plan_real)


def _construir(e: dict) -> curada.Curada:
    return curada.construir(e["base"], e["plan"], e["lista"], e["inventario_series"], e["fiabilidad"],
                            e["catalogo_series"], pares=e["pares"], simulacion=e["simulacion"], corte=CORTE)


# --- Pruebas --------------------------------------------------------------------------------------------------------
def test_verificaciones_pasan_en_el_escenario(esc):
    r = _construir(esc)
    assert list(r.verificaciones.columns) == list(curada.COLUMNAS_VERIFICACIONES)
    assert set(r.verificaciones["verificacion"]) == set(curada.VERIFICACIONES)
    assert r.correcta, r.verificaciones.to_string()
    assert list(r.base.columns) == list(COLUMNAS_SERIES)
    assert not any("valor" in c for c in (*r.registro.columns, *r.resumen.columns, *r.alias.columns))


def test_corte(esc):
    r = _construir(esc)
    assert (r.base["fecha_publicacion"] <= CORTE).all()
    o = esc["base"]
    queda = o["serie"].isin(list(SERIES_QUEDA))
    # tras el corte del tramo no cambia ninguna fecha: lo cortado es justo lo publicado después de CORTE
    assert r.info["filas_cortadas"] == int((queda & (o["fecha_publicacion"] > CORTE)).sum()) > 0
    assert len(r.base) == int(queda.sum()) - r.info["filas_cortadas"]
    assert r.registro["en_base_curada"].all()
    otra = curada.construir(o, esc["plan"], esc["lista"], esc["inventario_series"], esc["fiabilidad"],
                            esc["catalogo_series"], pares=esc["pares"], corte=pd.Timestamp("2009-03-01"))
    assert (otra.base["fecha_publicacion"] <= pd.Timestamp("2009-03-01")).all()
    assert (~otra.registro["en_base_curada"]).any()   # filas retrasadas que el corte quita: siguen en el registro
    assert curada.CORTE_G2 == pd.Timestamp("2026-11-13")


def test_escala_por_vintage(esc):
    r = _construir(esc)
    e = r.base[r.base["serie"] == "fred:ESC"]
    assert (e["valor"] == 1000.0).all()
    viejas = e[e["vintage"] < "2010-01-01"]
    assert len(viejas) == 6 and viejas["nota"].str.contains("escala corregida ×1000", regex=False).all()
    assert e.loc[e["vintage"] >= "2010-01-01", "nota"].isna().all()
    reg = r.registro[r.registro["escala"]]
    assert len(reg) == 6 and (reg["factor_escala"] == 1000.0).all() and (reg["capa"] == "escala_vintage").all()
    assert (reg["fecha_publicacion_antes"] == reg["fecha_publicacion_despues"]).all()


def test_derivada_recalculada_con_fecha_maxima(esc):
    r = _construir(esc)
    d = r.base[r.base["serie"] == "deriv:NF-B"].set_index("fecha_referencia")
    nf = r.base[r.base["serie"] == "fred:NF"].set_index("fecha_referencia")
    orig = esc["base"]
    b = orig[orig["serie"] == "fred:B"].set_index("fecha_referencia")
    assert len(d) and len(nf)
    comun = d.index.intersection(nf.index)
    esperada = np.maximum(nf.loc[comun, "fecha_publicacion"].to_numpy(), b.loc[comun, "fecha_publicacion"].to_numpy())
    assert (d.loc[comun, "fecha_publicacion"].to_numpy() == esperada).all()
    assert np.allclose(d.loc[comun, "valor"], nf.loc[comun, "valor"] - b.loc[comun, "valor"])
    od = orig[orig["serie"] == "deriv:NF-B"].set_index("fecha_referencia")
    antes = od.index[od["fecha_publicacion"] < TRAMO].intersection(d.index)
    assert (d.loc[antes, "fecha_publicacion"] > od.loc[antes, "fecha_publicacion"]).any()
    cambiadas = d.loc[antes][d.loc[antes, "fecha_publicacion"] != od.loc[antes, "fecha_publicacion"]]
    assert cambiadas["nota"].str.contains("tramo conservador", regex=False).all()
    assert r.registro.loc[r.registro["serie"] == "deriv:NF-B", "derivada"].sum() == len(cambiadas)


def test_alias_y_proyecciones_fuera_historia_previa_dentro(esc):
    r = _construir(esc)
    series = set(r.base["serie"])
    assert series == SERIES_QUEDA
    assert "fred:B" not in series and "fred:PROYMD" not in series
    assert r.alias[["alias", "canonico"]].values.tolist() == [["fred:B", "fred:NF"]]
    assert r.alias.loc[0, "correlacion"] == 0.99 and r.alias.loc[0, "origen_correlacion"] == "redundancia_pares"
    assert set(almacen.COLUMNAS_ALIAS) <= set(r.alias.columns)
    assert list(r.proyecciones.columns) == list(pp.COLUMNAS_PROYECCIONES)
    assert set(r.proyecciones["serie"]) == {"fred:PROYMD"} and r.proyecciones["horizonte"].tolist() == [3, 4]
    assert "fred:HP" in series and len(r.base[r.base["serie"] == "fred:HP"]) == 12


def test_notas_nuevas_las_reconocen_las_tools(esc):
    r = _construir(esc)
    partes = r.base["nota"].dropna().str.split("; ").explode()
    assert len(partes) and partes.str.lower().map(lambda t: any(s in t for s in SUBCADENAS)).all()
    nf = r.base[(r.base["serie"] == "fred:NF")]
    assert nf.loc[nf["nota"].notna(), "nota"].str.startswith("tramo conservador antes de 2010-06-04").all()


def test_aborta_si_una_fecha_adelanta(esc, monkeypatch, tmp_path):
    original = pp.fechas_curadas

    def adelantada(*a, **k):
        cur = original(*a, **k)
        cur.loc[cur.index[0], "fecha_publicacion_curada"] = a[0]["fecha_publicacion"].iloc[0] - pd.Timedelta(days=1)
        return cur

    monkeypatch.setattr(curada.pp, "fechas_curadas", adelantada)
    r = _construir(esc)
    v = r.verificaciones.set_index("verificacion")
    assert v.loc["no_adelanta", "filas_fallan"] >= 1 and not r.correcta
    with pytest.raises(curada.ErrorCuracion):
        curada.escribir(r, tmp_path / "series", tmp_path / "tablas")
    assert not (tmp_path / "series").exists()                         # no se publica nada en el corpus
    assert [f.name for f in (tmp_path / "tablas").iterdir()] == [curada.TABLA_VERIFICACIONES]
    v = pd.read_csv(tmp_path / "tablas" / curada.TABLA_VERIFICACIONES).set_index("verificacion")
    assert v.loc["no_adelanta", "filas_fallan"] >= 1                  # con el fallo


def _hash(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_idempotente_y_no_toca_la_base(esc, tmp_path):
    ruta_base = tmp_path / "trabajo" / almacen.FICHERO_SERIES
    almacen.escribir_series(esc["base"][esc["base"]["serie"] != "fred:PROYMD"], ruta_base)
    # las proyecciones no pasan el contrato (fecha_referencia futura): van al parquet sin validar, como en la base
    t = pd.read_parquet(ruta_base)
    pd.concat([t, esc["base"][esc["base"]["serie"] == "fred:PROYMD"]], ignore_index=True).to_parquet(ruta_base)
    antes = _hash(ruta_base)
    kw = {k: esc[k] for k in ("plan", "lista", "inventario_series", "fiabilidad", "catalogo_series", "simulacion",
                              "pares")}
    salidas = []
    for _ in range(2):
        _, rutas = curada.curar(ruta_base=ruta_base, carpeta_series=tmp_path / "series",
                                carpeta_tablas=tmp_path / "tablas", corte=CORTE, **kw)
        salidas.append({n: (pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p))
                        for n, p in rutas.items() if n != "manifiesto"})
    assert set(salidas[0]) == {"base_curada", "alias", "proyecciones", "registro_cambios", "verificaciones", "resumen"}
    assert set(rutas) == set(salidas[0]) | {"manifiesto"}
    for n in salidas[0]:
        pd.testing.assert_frame_equal(salidas[0][n], salidas[1][n])
    assert _hash(ruta_base) == antes
    assert not list((tmp_path / "series").glob("*.tmp")) and not (tmp_path / "series" / almacen.FICHERO_SERIES).exists()
    assert (salidas[0]["verificaciones"]["filas_fallan"] == 0).all()


def test_homogeneizacion_escalas_y_unidades(esc):
    r = _construir(esc)
    o = esc["base"]
    b = r.base
    ltr = b[b["serie"] == "gw:M.ltr"]
    assert (ltr["unidad"] == "% mensual").all() and np.allclose(ltr["valor"], 1.0)          # 0,01 × 100
    assert ltr["nota"].str.contains("escala corregida: ×100", regex=False).all()
    svar = b[b["serie"] == "gw:M.svar"]                                                    # sin_escalar
    assert (svar["unidad"] == "tanto por uno al cuadrado (mensual)").all() and np.allclose(svar["valor"], 0.002)
    assert svar["nota"].isna().all()
    hicp = b[b["serie"] == "ecb:HICPX"]
    assert (hicp["unidad"] == "% (variación interanual)").all() and np.allclose(hicp["valor"], 2.0)
    assert hicp["nota"].str.contains("escala corregida: unidad «% interanual» renombrada", regex=False).all()
    # VOLREAL21: recalculada y después ×100; frente a la base de trabajo ×100
    v = b[b["serie"] == VOL].set_index("fecha_referencia")
    vo = o[o["serie"] == VOL].set_index("fecha_referencia")
    assert len(v) == len(vo) > 0 and (v["unidad"] == "% anualizado").all()
    assert np.allclose(v["valor"], vo.loc[v.index, "valor"] * 100, rtol=0, atol=1e-7)
    reg = r.registro[r.registro["homogeneizacion"]]
    assert set(reg["serie"]) == {"gw:M.ltr", "ecb:HICPX", VOL}
    assert (reg.loc[reg["serie"] == VOL, "unidad_antes"] == "tanto por uno anualizado").all()
    assert (reg.loc[reg["serie"] == VOL, "unidad_despues"] == "% anualizado").all()
    assert (reg.loc[reg["serie"] == "gw:M.ltr", "factor_escala"] == 100).all()
    assert (reg.loc[reg["serie"] == "ecb:HICPX", "factor_escala"] == 1).all()
    v = r.verificaciones.set_index("verificacion")
    assert v.loc["unidades_homogeneizadas", "filas_fallan"] == 0 and v.loc["derivadas", "filas_fallan"] == 0


def test_homogeneizacion_detecta_una_unidad_sin_canonizar(esc):
    p = copy.deepcopy(esc["plan"])
    p["homogeneizacion"]["escalas"] = [e for e in p["homogeneizacion"]["escalas"] if "gw:M.ltr" not in e["series"]]
    sin = _construir({**esc, "plan": p})
    assert sin.base.loc[sin.base["serie"] == "gw:M.ltr", "unidad"].eq("tanto por uno mensual").all()
    f, u, n = curada.homogeneizar(np.array(["gw:M.ltr"]), np.array(["% interanual"]), esc["plan"])
    assert f[0] == 1 and u[0] == "% (variación interanual)" and "escala corregida" in n[0]


def _kw(esc):
    return {k: esc[k] for k in ("plan", "lista", "inventario_series", "fiabilidad", "catalogo_series", "simulacion",
                                "pares")}


def _base_en_disco(esc, tmp_path):
    ruta = tmp_path / "trabajo" / almacen.FICHERO_SERIES
    almacen.escribir_series(esc["base"][esc["base"]["serie"] != "fred:PROYMD"], ruta)
    t = pd.read_parquet(ruta)
    pd.concat([t, esc["base"][esc["base"]["serie"] == "fred:PROYMD"]], ignore_index=True).to_parquet(ruta)
    return ruta


def test_manifiesto(esc, tmp_path):
    import json

    ruta = _base_en_disco(esc, tmp_path)
    lista, plan = tmp_path / "lista.yaml", tmp_path / "plan.yaml"
    lista.write_text("lista", encoding="utf-8")
    plan.write_text("plan", encoding="utf-8")
    _, rutas = curada.curar(ruta_base=ruta, carpeta_series=tmp_path / "series", carpeta_tablas=tmp_path / "tablas",
                            corte=CORTE, entradas={"base_series": ruta, "lista_curada": lista, "preprocesado": plan},
                            **_kw(esc))
    m = json.loads(rutas["manifiesto"].read_text(encoding="utf-8"))
    assert rutas["manifiesto"] == tmp_path / "series" / curada.FICHERO_MANIFIESTO
    assert m["corte_g2"] == "2012-06-01" and m["creado_utc"]
    assert set(m["entradas"]) == {"base_series", "lista_curada", "preprocesado"}
    assert m["entradas"]["base_series"]["sha256"] == hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert m["entradas"]["lista_curada"]["tamano"] == 5 and m["entradas"]["base_series"]["mtime_ns"] > 0
    for n in ("base_curada", "alias", "proyecciones", "registro_cambios"):
        assert m["salidas"][n]["sha256"] == _hash(rutas[n])
    assert set(m["verificaciones"]) == set(curada.VERIFICACIONES) and not any(m["verificaciones"].values())


def test_publicacion_atomica_conserva_el_conjunto_anterior(esc, tmp_path, monkeypatch):
    ruta = _base_en_disco(esc, tmp_path)
    cs = tmp_path / "series"
    _, rutas = curada.curar(ruta_base=ruta, carpeta_series=cs, carpeta_tablas=tmp_path / "tablas", corte=CORTE,
                            **_kw(esc))
    antes = {f.name: _hash(f) for f in cs.iterdir()}
    assert set(antes) == {p.name for n, p in rutas.items() if n not in ("verificaciones", "resumen")}
    original = curada._renombrar

    def falla(a, b):
        if a.parent.name.startswith(curada.PREFIJO_NUEVO) and b.name == almacen.FICHERO_PROYECCIONES:
            raise OSError("disco lleno (simulado)")
        original(a, b)

    monkeypatch.setattr(curada, "_renombrar", falla)
    with pytest.raises(OSError):
        curada.curar(ruta_base=ruta, carpeta_series=cs, carpeta_tablas=tmp_path / "tablas", corte=pd.Timestamp(
            "2011-01-01"), **_kw(esc))
    assert {f.name: _hash(f) for f in cs.iterdir()} == antes        # el conjunto anterior, entero y sin restos
    monkeypatch.setattr(curada, "_renombrar", original)
    curada.curar(ruta_base=ruta, carpeta_series=cs, carpeta_tablas=tmp_path / "tablas", corte=pd.Timestamp(
        "2011-01-01"), **_kw(esc))
    assert not list(cs.glob(".curada_*")) and _hash(cs / almacen.FICHERO_SERIES_CURADA) != antes["base_curada.parquet"]


# --- Datos reales ---------------------------------------------------------------------------------------------------
@pytest.mark.datos
@pytest.mark.skipif(not almacen.ruta_series(curada=True).exists(),
                    reason="falta la base curada real (python -m ingesta.mercados_series curar)")
def test_base_curada_real():
    import pyarrow.parquet as pq

    lista = pp.cargar_lista()
    queda = {s for s, e in lista.items() if e["decision"] == "queda"}
    t = pq.read_table(almacen.ruta_series(curada=True), columns=["serie", "fecha_publicacion"]).to_pandas()
    assert set(t["serie"].astype(str)) == queda
    assert (t["fecha_publicacion"] <= curada.CORTE_G2).all()
    ver = pd.read_csv(TABLAS / curada.TABLA_VERIFICACIONES)
    assert set(ver["verificacion"]) == set(curada.VERIFICACIONES)
    assert (ver["filas_fallan"] == 0).all(), ver.to_string()
    assert "unidades_homogeneizadas" in set(ver["verificacion"])
    m = __import__("json").loads((almacen.ruta_series(curada=True).parent / curada.FICHERO_MANIFIESTO).read_text("utf-8"))
    assert m["corte_g2"] == curada.CORTE_G2.date().isoformat() and not any(m["verificaciones"].values())
    alias = almacen.leer_alias()
    assert len(alias) == sum(1 for e in lista.values() if e["decision"] == "alias")
    assert set(alias["canonico"]) <= queda
    proy = pq.read_table(almacen.ruta_proyecciones(), columns=["serie"]).to_pandas()
    assert proy["serie"].nunique() == pp.cargar_plan()["proyecciones"]["esperadas"]["total"]
    res = pd.read_csv(TABLAS / curada.TABLA_RESUMEN)
    assert len(res) == len(queda) and res["filas"].sum() == len(t)
