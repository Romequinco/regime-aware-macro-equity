"""Tests de la base que solo crece en las fuentes sin historia de revisiones (paso 3b, ``base.conservar_revisiones``).

Sin red y con datos SINTÉTICOS (ningún valor real del BCE ni de ALFRED), con las entradas reales del
catálogo: una revisión con la fecha de la regla conserva la fila antigua y fecha la nueva desde su
observación; la fecha propia posterior de la fuente (HICP definitivo) se respeta; los periodos nuevos no
cambian; una revisión en el sitio (vintage ``unico``) conserva lo guardado; ALFRED queda fuera; la
construcción es idempotente; y ``get_serie``/``leer_ultimas`` devuelven en cada fecha la versión visible
entonces, igual con la base completa que truncada.

Arreglos del verificador (paso 3b-1): (1) una versión retirada que vuelve con el mismo valor y la fecha de la
regla no se ve antes que la guardada (LFSI de 2025-07); (2) ``desde_cero`` y ``permitir_perdidas`` también
conservan, y los ``errores_propios`` declarados también, pero pueden retrasar (nunca adelantar) fechas; (3) copia previa
rotatoria en cada construcción (las dos últimas) y desglose ``solo_anadir_ultima.csv``; (4) un periodo nuevo
del BCE se fecha con su ``VALID_FROM``, no con una regla anterior (PIB I10 de 2026-Q3); (6) las ``yf:`` de
``data/raw`` se extienden con el almacén de precios solo si el solape coincide, con la fecha más tardía.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingesta.mercados_series import almacen, base, timegate, tools
from ingesta.mercados_series import catalogo as c
from ingesta.mercados_series.contrato import COLUMNAS_SERIES, ErrorContrato, validar_series
from ingesta.mercados_series.fuentes import alfred, bce
from ingesta.mercados_series.fuentes.bce import NOTA_PREVIA

PARO = "ecb:LFSI.M.U2.S.UNEHRT.TOTAL0.15_74.T"
HICP = "ecb:HICP.M.U2.N.000000.4D0.ANR"
ESTR = "ecb:ESTR"
OBSERVADO = pd.Timestamp("2026-11-19 14:00", tz="UTC")     # 09:00 en Nueva York: decisión del mismo día
DECISION = pd.Timestamp("2026-11-19")
SIN_EXCEPCIONES = pd.DataFrame(columns=["serie", "fecha_referencia", "fecha_publicacion"])


@pytest.fixture(scope="module")
def cat():
    return c.cargar_catalogo()


@pytest.fixture
def corpus_en_tmp(tmp_path, monkeypatch):
    """La ruta por defecto del almacén apunta a ``tmp_path`` (nunca al corpus real)."""
    def corpus_dir(tema=None):
        p = tmp_path / "corpus" / tema if tema else tmp_path / "corpus"
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(almacen, "corpus_dir", corpus_dir)
    return tmp_path


def _filas(cat, sid: str, filas: list[tuple]) -> pd.DataFrame:
    """``(fecha_referencia, fecha_publicacion, disponible_utc | None, vintage, valor, metodo, nota)`` → contrato."""
    e = cat[sid]
    df = pd.DataFrame(filas, columns=["fecha_referencia", "fecha_publicacion", "disponible_utc", "vintage", "valor",
                                      "metodo_publicacion", "nota"])
    df["fecha_referencia"] = pd.to_datetime(df["fecha_referencia"])
    df["fecha_publicacion"] = pd.to_datetime(df["fecha_publicacion"])
    df["disponible_utc"] = pd.to_datetime(df["disponible_utc"], utc=True)
    df = df.assign(serie=sid, unidad=e["unidad"], divisa=e["divisa"], fuente=e["fuente"])
    return df[list(COLUMNAS_SERIES)]


def _bce(cat, *partes: list[tuple], ids=(PARO, HICP, ESTR)) -> dict[str, pd.DataFrame]:
    return {"bce": validar_series(pd.concat([_filas(cat, s, p) for s, p in zip(ids, partes)], ignore_index=True))}


# Lo guardado (primera construcción): paro de julio con la regla (NOTA_PREVIA), HICP flash de septiembre y €STR.
PARO_1 = [("2026-07-01", "2026-09-01", None, "2026-09-01", 6.2, "lag_fijo", NOTA_PREVIA),
          ("2026-08-01", "2026-10-01", "2026-10-01 09:00", "2026-10-01", 6.3, "vintage_exacto", None)]
HICP_1 = [("2026-09-01", "2026-10-02", "2026-10-02 09:00", "2026-10-02", 2.2, "vintage_exacto", None)]
ESTR_1 = [("2026-10-01", "2026-10-02", None, "unico", 1.93, "calendario", None)]
# Descarga posterior: julio revisado (otra versión, misma fecha de la regla), agosto igual y septiembre nuevo;
# HICP definitivo con su fecha propia (16 de octubre); €STR revisado en el sitio y un día nuevo.
PARO_2 = [("2026-07-01", "2026-09-01", None, "2026-11-10", 6.4, "lag_fijo", NOTA_PREVIA),
          PARO_1[1],
          ("2026-09-01", "2026-11-03", "2026-11-03 10:00", "2026-11-03", 6.3, "vintage_exacto", None)]
HICP_2 = [("2026-09-01", "2026-10-16", "2026-10-16 09:00", "2026-10-16", 2.1, "vintage_exacto", None)]
ESTR_2 = [("2026-10-01", "2026-10-02", None, "unico", 1.95, "calendario", None),
          ("2026-10-02", "2026-10-05", None, "unico", 1.92, "calendario", None)]


def _construir(cat, tablas, **kw):
    kw.setdefault("observado", OBSERVADO)
    return base.construir_base(tablas=tablas, catalogo=cat, excepciones=SIN_EXCEPCIONES, **kw)


@pytest.fixture
def construida(cat, corpus_en_tmp):
    """Base del almacén (en tmp) tras la primera y la segunda descarga."""
    _construir(cat, _bce(cat, PARO_1, HICP_1, ESTR_1))
    antes = almacen.leer_series()
    res, _ = _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2))
    return antes, almacen.leer_series(), res


def _fila(df, sid, ref, vintage):
    m = (df["serie"] == sid) & (df["fecha_referencia"] == pd.Timestamp(ref)) & (df["vintage"] == vintage)
    assert m.sum() == 1
    return df[m].iloc[0]


def test_t3b_solo_anadir_fuentes():
    assert set(base.CARGADORES_SOLO_ANADIR) <= set(base.CARGADORES_OFICIALES)
    assert not {"alfred", "oecd", "philly_rtdsm", "fred", "academicos", "fase1"} & set(base.CARGADORES_SOLO_ANADIR)


def test_t3b_revision_conserva_la_antigua_y_fecha_la_nueva(construida):
    antes, despues, res = construida
    # Ninguna fila guardada se pierde ni cambia (salvo la nota de la conservada); sin permitir_perdidas.
    cruce = antes.merge(despues, on=["serie", "fecha_referencia", "vintage"], how="left", suffixes=("", "_d"),
                        indicator=True)
    assert (cruce["_merge"] == "both").all()
    for col in ("valor", "fecha_publicacion", "disponible_utc", "metodo_publicacion"):
        assert ((cruce[col] == cruce[f"{col}_d"]) | (cruce[col].isna() & cruce[f"{col}_d"].isna())).all(), col
    vieja = _fila(despues, PARO, "2026-07-01", "2026-09-01")
    assert vieja["valor"] == 6.2 and vieja["fecha_publicacion"] == pd.Timestamp("2026-09-01")
    assert vieja["nota"] == f"{NOTA_PREVIA}; {base.NOTA_VALOR_ANTERIOR} 2026-11-19"
    nueva = _fila(despues, PARO, "2026-07-01", "2026-11-10")
    assert nueva["valor"] == 6.4 and nueva["fecha_publicacion"] == DECISION and pd.isna(nueva["disponible_utc"])
    assert nueva["nota"] == f"{NOTA_PREVIA}; {base.NOTA_REVISION_OBSERVADA} 2026-11-19 (la regla daba 2026-09-01)"
    s = res.solo_anadir
    assert s["observado"] == "2026-11-19" and s["primera_decision"] == "2026-11-19"
    assert s["conservadas"] == 2 and s["fechadas_observacion"] == 1 and s["fecha_propia"] == 1
    assert s["por_serie"][PARO] == {"conservadas": 1, "fechadas_observacion": 1}


def test_t3b_revision_con_fecha_propia_mayor_se_respeta(construida):
    _, despues, _ = construida
    flash = _fila(despues, HICP, "2026-09-01", "2026-10-02")
    assert flash["valor"] == 2.2 and flash["nota"] == f"{base.NOTA_VALOR_ANTERIOR} 2026-11-19"
    definitivo = _fila(despues, HICP, "2026-09-01", "2026-10-16")
    assert definitivo["fecha_publicacion"] == pd.Timestamp("2026-10-16") and pd.isna(definitivo["nota"])
    assert definitivo["disponible_utc"] == pd.Timestamp("2026-10-16 09:00", tz="UTC")


def test_t3b_periodos_nuevos_no_cambian(construida, cat):
    _, despues, _ = construida
    nuevo = _bce(cat, PARO_2, HICP_2, ESTR_2)["bce"]
    for sid, ref, vintage in ((PARO, "2026-09-01", "2026-11-03"), (ESTR, "2026-10-02", "unico")):
        pd.testing.assert_series_equal(_fila(despues, sid, ref, vintage), _fila(nuevo, sid, ref, vintage),
                                       check_names=False)
    igual = _fila(despues, PARO, "2026-08-01", "2026-10-01")    # misma clave y valor: tal cual
    assert pd.isna(igual["nota"]) and igual["fecha_publicacion"] == pd.Timestamp("2026-10-01")


def test_t3b_revision_en_el_sitio_conserva_lo_guardado(construida):
    _, despues, res = construida
    estr = _fila(despues, ESTR, "2026-10-01", "unico")
    assert estr["valor"] == 1.93 and pd.isna(estr["nota"])
    assert res.solo_anadir["guardada_gana_valor"] == 1 and res.solo_anadir["guardada_gana_nota"] == 0
    assert res.solo_anadir["por_serie"][ESTR] == {"guardada_gana_valor": 1}


def test_t3b2_bandera_cambiada_en_el_sitio_conserva_lo_guardado(cat, corpus_en_tmp):
    """Paso 3b-2: Eurostat quita la «e» de estimado (misma clave y valor, otra nota): gana la guardada, sin error;
    la bandera queda congelada y el cambio se cuenta aparte (``guardada_gana_nota``)."""
    con_e = [("2026-10-01", "2026-10-02", None, "unico", 1.93, "calendario", "bandera e: estimado")]
    sin_e = [("2026-10-01", "2026-10-02", None, "unico", 1.93, "calendario", None)]
    _construir(cat, _bce(cat, PARO_1, HICP_1, con_e))
    res, _ = _construir(cat, _bce(cat, PARO_1, HICP_1, sin_e))
    assert _fila(almacen.leer_series(), ESTR, "2026-10-01", "unico")["nota"] == "bandera e: estimado"
    assert res.solo_anadir["por_serie"][ESTR] == {"guardada_gana_nota": 1}
    assert res.solo_anadir["guardada_gana_valor"] == 0


def test_t3b2_fecha_propia_anterior_del_bce_se_respeta(cat, corpus_en_tmp):
    """Paso 3b-2 (V1): una versión del BCE con VALID_FROM ANTERIOR a la guardada y otro valor (fuente con fecha
    propia documentada, ``FUENTES_FECHA_PROPIA_ANTERIOR``) se queda con su fecha: el as-of entre las dos fechas ve
    la versión antigua y, después de la guardada, la guardada."""
    assert "bce" in base.FUENTES_FECHA_PROPIA_ANTERIOR and "eurostat" not in base.FUENTES_FECHA_PROPIA_ANTERIOR
    _construir(cat, _bce(cat, PARO_1, HICP_2, ESTR_1))                   # guardada: 2,1 del 2026-10-16
    res, _ = _construir(cat, _bce(cat, PARO_1, HICP_2 + HICP_1, ESTR_1))  # llega la flash: 2,2 del 2026-10-02
    b = almacen.leer_series()
    flash = _fila(b, HICP, "2026-09-01", "2026-10-02")
    assert flash["fecha_publicacion"] == pd.Timestamp("2026-10-02") and flash["valor"] == 2.2
    assert flash["disponible_utc"] == pd.Timestamp("2026-10-02 09:00", tz="UTC")
    assert res.solo_anadir["por_serie"][HICP] == {"fecha_propia": 1}
    assert timegate.as_of_series(b, HICP, "2026-10-01").empty
    assert timegate.as_of_series(b, HICP, "2026-10-05").iloc[0]["valor"] == 2.2
    assert timegate.as_of_series(b, HICP, "2026-10-20").iloc[0]["valor"] == 2.1


def test_t3b2_fecha_propia_anterior_de_otra_fuente_no_adelanta(cat, corpus_en_tmp, monkeypatch):
    """Sin la fuente en ``FUENTES_FECHA_PROPIA_ANTERIOR``, la misma versión anterior se fecha con su observación."""
    monkeypatch.setattr(base, "FUENTES_FECHA_PROPIA_ANTERIOR", ())
    _construir(cat, _bce(cat, PARO_1, HICP_2, ESTR_1))
    _construir(cat, _bce(cat, PARO_1, HICP_2 + HICP_1, ESTR_1))
    flash = _fila(almacen.leer_series(), HICP, "2026-09-01", "2026-10-02")
    assert flash["fecha_publicacion"] == DECISION and pd.isna(flash["disponible_utc"])


def test_t3b_idempotente(construida, cat):
    _, despues, _ = construida
    res, _ = _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2))
    pd.testing.assert_frame_equal(almacen.leer_series(), despues)
    assert res.solo_anadir["conservadas"] == 0 and res.solo_anadir["ya_conservadas"] == 2
    assert res.solo_anadir["fechadas_observacion"] == 0     # la revisión ya fechada se toma de lo guardado
    # Otra descarga más tarde no vuelve a fechar ni a anotar lo ya resuelto.
    _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2), observado="2026-12-01 14:00")
    pd.testing.assert_frame_equal(almacen.leer_series(), despues)


def _conservado_igual(despues):
    """Lo conservado y lo fechado por la observación en ``construida`` sigue tal cual en la base guardada."""
    ahora = almacen.leer_series()
    for sid, ref, vintage in ((PARO, "2026-07-01", "2026-09-01"), (PARO, "2026-07-01", "2026-11-10"),
                              (HICP, "2026-09-01", "2026-10-02"), (ESTR, "2026-10-01", "unico")):
        pd.testing.assert_series_equal(_fila(ahora, sid, ref, vintage), _fila(despues, sid, ref, vintage),
                                       check_names=False)


def test_t3b_permitir_perdidas_tambien_conserva(construida, cat):
    """Arreglo 2 del verificador: permitir_perdidas ya no se salta el solo-añadir."""
    _, despues, _ = construida
    res, _ = _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2), permitir_perdidas=True, observado="2026-12-01 14:00")
    _conservado_igual(despues)
    assert res.solo_anadir["ya_conservadas"] == 2 and res.solo_anadir["conservadas"] == 0
    res, _ = base.construir_base(tablas=_bce(cat, PARO_2, HICP_2, ESTR_2), catalogo=cat, excepciones=SIN_EXCEPCIONES,
                                 escribir=False)
    assert res.solo_anadir == {}     # sin base guardada que mirar (ensayo sin ruta)


def test_t3b_desde_cero_conserva_contra_la_guardada(construida, cat):
    """Arreglo 2: una reconstrucción desde cero no pierde lo conservado ni devuelve las revisiones a la regla."""
    _, despues, _ = construida
    res, _ = _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2), desde_cero=True, observado="2026-12-01 14:00")
    assert res.desde_cero and res.respaldo_desde_cero
    _conservado_igual(despues)
    pd.testing.assert_frame_equal(almacen.leer_series(), despues)
    assert res.solo_anadir["ya_conservadas"] == 2 and res.solo_anadir["fechadas_observacion"] == 0


def test_t3b_errores_propios_solo_retrasan(construida, cat):
    """Arreglo 2: un error propio declarado puede retrasar una fecha guardada; nunca adelantarla ni perder filas."""
    _, despues, _ = construida
    corr = despues.copy()
    m = (corr["serie"] == PARO) & (corr["fecha_referencia"] == pd.Timestamp("2026-08-01"))
    corr.loc[m, "fecha_publicacion"] = pd.Timestamp("2026-10-05")
    corr.loc[m, "disponible_utc"] = pd.NaT
    corr.loc[m, "metodo_publicacion"] = "lag_fijo"
    with pytest.raises(ErrorContrato, match="cambiarían"):       # sin declararlo: la base solo crece
        _construir(cat, {"bce": validar_series(corr)})
    res, _ = _construir(cat, {"bce": validar_series(corr)}, errores_propios=[PARO])
    assert res.solo_anadir["fecha_corregida"] == 1 and res.solo_anadir["por_serie"][PARO] == {"fecha_corregida": 1}
    fila = _fila(almacen.leer_series(), PARO, "2026-08-01", "2026-10-01")
    assert fila["fecha_publicacion"] == pd.Timestamp("2026-10-05")
    _conservado_igual(despues)
    # Adelantar una fecha no es una corrección.
    corr.loc[m, "fecha_publicacion"] = pd.Timestamp("2026-09-20")
    with pytest.raises(ErrorContrato, match="adelantarían"):
        _construir(cat, {"bce": validar_series(corr)}, errores_propios=[PARO])
    # El solo-añadir sigue aplicándose a la serie declarada: una fila que ya no viene se conserva.
    sin_fila = corr[~((corr["serie"] == PARO) & (corr["fecha_referencia"] == pd.Timestamp("2026-09-01")))].copy()
    sin_fila.loc[m, "fecha_publicacion"] = pd.Timestamp("2026-10-05")
    res, _ = _construir(cat, {"bce": validar_series(sin_fila)}, errores_propios=[PARO],
                        observado="2026-12-01 14:00")
    assert res.solo_anadir["por_serie"][PARO]["conservadas"] == 1
    sept = _fila(almacen.leer_series(), PARO, "2026-09-01", "2026-11-03")
    assert sept["nota"] == f"{base.NOTA_VALOR_ANTERIOR} 2026-12-01"
    _conservado_igual(despues)


# --- Arreglo 1: una versión retirada que vuelve con el mismo valor no se ve antes de tiempo ------------
# LFSI de 2025-07 (sintético): 6,3 con la regla del 2025-09-10; revisión a 6,4 observada el 2026-11-19 (vintage
# 2026-10-30); el BCE retira esa versión y vuelve a dar 6,4 como vintage 2026-12-03 con la regla del 2025-09-10.
LFSI_1 = [("2025-07-01", "2025-09-10", None, "2025-09-10", 6.3, "lag_fijo", NOTA_PREVIA)]
LFSI_2 = [("2025-07-01", "2025-09-10", None, "2026-10-30", 6.4, "lag_fijo", NOTA_PREVIA)]
LFSI_3 = [("2025-07-01", "2025-09-10", None, "2026-12-03", 6.4, "lag_fijo", NOTA_PREVIA)]


def test_t3b_version_retirada_con_el_mismo_valor_no_se_adelanta(cat, corpus_en_tmp):
    _construir(cat, _bce(cat, LFSI_1, ids=(PARO,)), observado="2025-09-15 14:00")
    _construir(cat, _bce(cat, LFSI_2, ids=(PARO,)))                                   # observado 2026-11-19
    res, _ = _construir(cat, _bce(cat, LFSI_3, ids=(PARO,)), observado="2026-12-04 14:00")
    b = almacen.leer_series()
    assert len(b) == 3                                                                # nada se pierde
    nueva = _fila(b, PARO, "2025-07-01", "2026-12-03")
    assert nueva["valor"] == 6.4 and nueva["fecha_publicacion"] == DECISION and pd.isna(nueva["disponible_utc"])
    assert nueva["nota"] == f"{NOTA_PREVIA}; {base.NOTA_MISMO_VALOR} 2026-11-19 (la regla daba 2025-09-10)"
    assert res.solo_anadir["mismo_valor"] == 1 and res.solo_anadir["conservadas"] == 1
    # Ninguna fila queda antes de la menor fecha guardada con su valor (6,3: 2025-09-10; 6,4: 2026-11-19).
    minimas = b.groupby("valor")["fecha_publicacion"].min()
    assert minimas.to_dict() == {6.3: pd.Timestamp("2025-09-10"), 6.4: DECISION}
    # Vista as-of: 6,3 hasta la observación de la revisión; con la misma fecha (2026-11-19) gana la vintage mayor.
    for f, valor, vintage in (("2025-10-01", 6.3, "2025-09-10"), ("2026-11-18", 6.3, "2025-09-10"),
                              ("2026-11-19", 6.4, "2026-12-03"), ("2026-12-10", 6.4, "2026-12-03")):
        r = timegate.as_of_series(b, PARO, f).iloc[0]
        assert (r["valor"], r["vintage"]) == (valor, vintage), f
        pd.testing.assert_frame_equal(tools.get_serie(PARO, f).datos, tools.get_serie(PARO, f, base=b).datos)
    # Idempotente: otra descarga igual más tarde no cambia nada.
    _construir(cat, _bce(cat, LFSI_3, ids=(PARO,)), observado="2027-01-05 14:00")
    pd.testing.assert_frame_equal(almacen.leer_series(), b)


def test_t3b_mismo_valor_con_regla_posterior_no_cambia(cat, corpus_en_tmp):
    """Si la regla de la versión nueva ya cae después de la guardada, se queda con su regla (sin nota)."""
    _construir(cat, _bce(cat, LFSI_1, ids=(PARO,)), observado="2025-09-15 14:00")
    tarde = [("2025-07-01", "2025-09-12", None, "2025-09-12", 6.3, "lag_fijo", NOTA_PREVIA)]
    res, _ = _construir(cat, _bce(cat, tarde, ids=(PARO,)), observado="2025-09-20 14:00")
    f = _fila(almacen.leer_series(), PARO, "2025-07-01", "2025-09-12")
    assert f["fecha_publicacion"] == pd.Timestamp("2025-09-12") and f["nota"] == NOTA_PREVIA
    assert res.solo_anadir["mismo_valor"] == 0


# --- Arreglo 3: copia previa rotatoria y desglose del solo-añadir --------------------------------------
def test_t3b_copia_previa_en_cada_construccion_y_rota(cat, corpus_en_tmp, monkeypatch):
    ruta = almacen.ruta_series()
    _construir(cat, _bce(cat, PARO_1, HICP_1, ESTR_1))
    assert not list(ruta.parent.glob("*previa*"))                     # sin base anterior, nada que copiar
    versiones = [ruta.read_bytes()]
    for obs in ("2026-11-19 14:00", "2026-12-01 14:00", "2026-12-02 14:00"):
        res, _ = _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2), observado=obs)
        assert res.copia_previa == str(ruta.with_name(f"base_series{base.SUFIJO_PREVIA}"))
        versiones.append(ruta.read_bytes())
    previa, previa_2 = (ruta.with_name(f"base_series{s}") for s in (base.SUFIJO_PREVIA, base.SUFIJO_PREVIA_2))
    assert previa.read_bytes() == versiones[-2] and previa_2.read_bytes() == versiones[-3]
    assert sorted(p.name for p in ruta.parent.iterdir()) == sorted([ruta.name, previa.name, previa_2.name])
    # Una construcción que falla al escribir no rota las copias ni deja temporales.
    antes = (previa.read_bytes(), previa_2.read_bytes(), ruta.read_bytes())

    def falla(*a, **k):
        raise ErrorContrato("series", ["escritura simulada que falla"])

    monkeypatch.setattr(almacen, "escribir_series", falla)
    with pytest.raises(ErrorContrato, match="simulada"):
        _construir(cat, _bce(cat, PARO_2, HICP_2, ESTR_2), observado="2026-12-03 14:00")
    assert (previa.read_bytes(), previa_2.read_bytes(), ruta.read_bytes()) == antes
    assert sorted(p.name for p in ruta.parent.iterdir()) == sorted([ruta.name, previa.name, previa_2.name])


def test_t3b_desglose_solo_anadir(construida, tmp_path):
    _, _, res = construida
    t = pd.read_csv(base.escribir_solo_anadir(res.solo_anadir, tmp_path / "s.csv"))
    assert list(t.columns) == ["serie", "observado", *base.CUENTAS_SOLO_ANADIR] and "valor" not in t.columns
    fila = t.set_index("serie").loc[PARO]
    assert (fila["conservadas"], fila["fechadas_observacion"], fila["observado"]) == (1, 1, "2026-11-19")
    assert set(t["serie"]) == {PARO, HICP, ESTR}
    vacio = pd.read_csv(base.escribir_solo_anadir({}, tmp_path / "v.csv"))
    assert vacio.empty and list(vacio.columns) == list(t.columns)


def test_t3b_cli_escribe_el_desglose(cat, corpus_en_tmp, monkeypatch, capsys):
    from ingesta.mercados_series import __main__ as cli

    monkeypatch.setattr(base, "resultados_dir", lambda tema=None: corpus_en_tmp / "results")
    estado = {"tablas": _bce(cat, PARO_1, HICP_1, ESTR_1)}
    monkeypatch.setattr(base, "tablas_fuentes", lambda **kw: estado["tablas"])
    assert cli.main(["construir-base", "--sin-red"]) == 0
    estado["tablas"] = _bce(cat, PARO_2, HICP_2, ESTR_2)
    assert cli.main(["construir-base", "--sin-red"]) == 0
    t = pd.read_csv(corpus_en_tmp / "results" / "tablas" / base.FICHERO_SOLO_ANADIR)
    assert t.set_index("serie").loc[PARO, "conservadas"] == 1
    assert "solo-añadir ->" in capsys.readouterr().out


# --- Arreglo 4: un periodo nuevo del BCE no se ve antes de su primera versión --------------------------
CAB_HIST = "KEY,FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,ACTION,VALID_FROM,VALID_TO"
PIB = "ecb:MNA.Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY"


def _hist(clave: str, freq: str, area: str, filas: list[tuple[str, float, str]]) -> pd.DataFrame:
    lineas = [CAB_HIST, *(f"{clave},{freq},{area},{p},{v},Replace,{vf}," for p, v, vf in filas)]
    return bce.parsear_csv("\n".join(lineas))


def test_t3b_bce_periodo_nuevo_con_su_valid_from():
    e = bce.SERIES_BCE[PIB]
    # Sintético: la serie entra en el BCE el 2026-10-20 (carga en bloque) y el 2026-Q3 tiene una sola versión, del
    # 2026-11-13; la regla EUROSTAT_PIB lo daba el 2026-11-05.
    hist = _hist("MNA.Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", "Q", "I10",
                 [("2010-Q1", 0.5, "2026-10-20T11:00:00.000+02:00"), ("2026-Q3", 0.2, "2026-11-13T11:00:00.000+01:00")])
    regla = c.fecha_publicacion_clave(pd.Series(pd.to_datetime(["2026-07-01"])), e["previa"]).iloc[0]
    assert regla == pd.Timestamp("2026-11-05")
    t = validar_series(bce.tabla_versiones(PIB, hist, e))
    q3 = t[t["fecha_referencia"] == pd.Timestamp("2026-07-01")].iloc[0]
    assert q3["fecha_publicacion"] == pd.Timestamp("2026-11-13") and q3["metodo_publicacion"] == "vintage_exacto"
    assert q3["disponible_utc"] == pd.Timestamp("2026-11-13 10:00", tz="UTC") and pd.isna(q3["nota"])
    # Lo anterior al historial (regla < primera versión de la serie) sigue fechado como antes.
    viejo = t[t["fecha_referencia"] == pd.Timestamp("2010-01-01")].iloc[0]
    assert viejo["metodo_publicacion"] == "lag_fijo" and viejo["nota"] == bce.NOTA_POSTERIOR_BCE
    assert viejo["fecha_publicacion"] == pd.Timestamp("2026-10-20")
    # Ninguna fila con hora se ve antes de su versión.
    con_hora = t["disponible_utc"].notna()
    assert (t.loc[con_hora, "fecha_publicacion"] >= pd.to_datetime(t.loc[con_hora, "vintage"])).all()


def test_t3b_bce_paro_regla_previa_solo_antes_del_historial():
    e = bce.SERIES_BCE[PARO]
    hist = _hist("LFSI.M.U2.S.UNEHRT.TOTAL0.15_74.T", "M", "U2",
                 [("2010-01", 10.0, "2026-01-23T10:00:00.000+01:00"), ("2026-07", 6.4, "2026-10-30T11:00:00.000+01:00")])
    t = validar_series(bce.tabla_versiones(PARO, hist, e))
    viejo = t[t["fecha_referencia"] == pd.Timestamp("2010-01-01")].iloc[0]
    assert viejo["metodo_publicacion"] == "lag_fijo" and viejo["nota"] == NOTA_PREVIA       # carga en bloque
    julio = t[t["fecha_referencia"] == pd.Timestamp("2026-07-01")].iloc[0]
    # Antes: la regla EUROSTAT_PARO (anterior a su versión) con NOTA_PREVIA; ahora, su VALID_FROM.
    assert julio["fecha_publicacion"] == pd.Timestamp("2026-10-30") and julio["metodo_publicacion"] == "vintage_exacto"
    assert pd.isna(julio["nota"])


def _vint(fecha: str, valor: str, rs: str, re: str = "9999-12-31") -> dict:
    return {"date": fecha, "value": valor, "realtime_start": rs, "realtime_end": re}


def test_t3b_alfred_no_se_aplica(cat, corpus_en_tmp):
    def unrate(filas):
        t, _ = alfred.tabla_serie_alfred("fred:UNRATE", alfred.parsear_vintages(filas), cat["fred:UNRATE"])
        return {"alfred": validar_series(t)}

    v0 = cat["fred:UNRATE"]["regla_previa_alfred"]["primer_vintage"]
    completas = [_vint("1960-01-01", "5.2", v0), _vint("2020-04-01", "14.7", "2020-05-08", "2020-06-04"),
                 _vint("2020-04-01", "14.8", "2020-06-05")]
    _construir(cat, unrate(completas))
    # Sin el primer vintage de abril de 2020 (otra descarga): ALFRED trae su historia, así que es una pérdida.
    with pytest.raises(ErrorContrato, match="desaparecerían"):
        _construir(cat, unrate([completas[0], _vint("2020-04-01", "14.8", "2020-06-05")]))


def test_t3b_get_serie_version_visible_en_cada_fecha(construida):
    _, despues, _ = construida
    casos = {PARO: [("2026-09-01", 6.2), ("2026-11-18", 6.2), ("2026-11-19", 6.4), ("2026-12-01", 6.4)],
             HICP: [("2026-10-02", 2.2), ("2026-10-15", 2.2), ("2026-10-16", 2.1), ("2026-11-19", 2.1)]}
    ref = {PARO: "2026-07-01", HICP: "2026-09-01"}
    for sid, fechas in casos.items():
        for f, esperado in fechas:
            r = tools.get_serie(sid, f)
            fila = r.datos[r.datos["fecha_referencia"] == pd.Timestamp(ref[sid])].iloc[0]
            assert fila["valor"] == esperado, (sid, f)
            # Truncado: la misma respuesta con la base completa, en memoria y cortada a lo publicado hasta f.
            truncada = almacen.leer_series(sid, hasta=f)
            for otra in (tools.get_serie(sid, f, base=despues), tools.get_serie(sid, f, base=truncada)):
                pd.testing.assert_frame_equal(otra.datos, r.datos)
                assert otra.avisos == r.avisos
            pd.testing.assert_frame_equal(almacen.leer_ultimas(sid, f), timegate.as_of_series(despues, sid, f))


# --- Punto 6: series yf: de data/raw extendidas con el almacén de precios -------------------------------
def _yf_raw(raiz, sesiones, cierres, vol_hasta):
    """``data/raw`` sintético: ^GSPC (yfinance, descarga 2024-03-20 15:37 NY) y su vol. realizada."""
    import os

    descarga = pd.Timestamp("2024-03-20 15:37", tz="America/New_York")
    carpeta = raiz / "yfinance"
    carpeta.mkdir(parents=True, exist_ok=True)
    spx = pd.DataFrame({"SP500": cierres}, index=pd.DatetimeIndex(sesiones, name="Date"))
    for nombre, df in (("SP500", spx), ("SP500_DAILY_DRAWDOWN_SRC", spx.rename(columns={"SP500": "SP500_DAILY_DRAWDOWN_SRC"}))):
        df.to_parquet(carpeta / f"{nombre}.parquet")
        os.utime(carpeta / f"{nombre}.parquet", (descarga.timestamp(),) * 2)
    lr = np.log(spx["SP500"]).diff().rolling(21).std(ddof=1) * np.sqrt(252)
    vol = lr[lr.index <= vol_hasta].dropna().rename("REALIZED_VOL_SP500").to_frame()
    vol.to_parquet(carpeta / "REALIZED_VOL_SP500.parquet")
    os.utime(carpeta / "REALIZED_VOL_SP500.parquet", (descarga.timestamp(),) * 2)


def _almacen_gspc(carpeta, sesiones, cierres, mercado="XNYS"):
    from ingesta.mercados_series import visibilidad
    from ingesta.mercados_series.contrato import primera_decision_vec

    ses = pd.Series(pd.DatetimeIndex(sesiones))
    disp = visibilidad.disponible_cierre_serie(ses, mercado)
    df = pd.DataFrame({"ticker": "^GSPC", "sesion": ses, "mercado": mercado, "open": cierres, "high": cierres,
                       "low": cierres, "close": cierres, "volume": 0.0, "dividendo": 0.0, "split": 1.0, "divisa": "USD",
                       "fecha_publicacion": primera_decision_vec(disp), "disponible_utc": disp, "fuente": "yahoo",
                       "descargado": pd.Timestamp("2024-06-01 12:00", tz="UTC")})
    almacen.escribir_precios(df, "yahoo", ruta=carpeta)


def test_t3b_yf_extension_con_el_almacen(tmp_path, cat):
    from ingesta.mercados_series.fuentes import fase1

    rng = np.random.default_rng(3)
    todas = pd.bdate_range("2024-01-02", "2024-05-31")
    cierres = np.round(4000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(todas)))), 2)
    raw = todas < "2024-03-20"                                       # data/raw: hasta la descarga (intradía fuera)
    _yf_raw(tmp_path / "raw", todas[raw], cierres[raw], vol_hasta=pd.Timestamp("2024-03-19"))
    sub = {k: cat[k] for k in ("yf:^GSPC", "deriv:VOLREAL21_GSPC")}
    sin = fase1.tabla_fase1(tmp_path / "raw", sub)
    _almacen_gspc(tmp_path / "precios", todas, cierres)
    inf: dict = {}
    con = fase1.tabla_fase1(tmp_path / "raw", sub, extender_precios=tmp_path / "precios", informe=inf)
    # Sin extender_precios, nada cambia (tabla_fase1 por defecto sigue siendo la de data/raw).
    pd.testing.assert_frame_equal(fase1.tabla_fase1(tmp_path / "raw", sub), sin)
    g_sin, g_con = (t[t["serie"] == "yf:^GSPC"].reset_index(drop=True) for t in (sin, con))
    pd.testing.assert_frame_equal(g_con.iloc[:len(g_sin)], g_sin)            # lo de data/raw, tal cual
    nuevas = g_con.iloc[len(g_sin):]
    assert list(nuevas["fecha_referencia"]) == list(todas[~raw])
    assert np.allclose(nuevas["valor"], cierres[~raw], rtol=0, atol=0)
    assert (nuevas["fecha_publicacion"] == nuevas["fecha_referencia"]).all()     # cierre XNYS + 30 min: mismo día
    assert inf["yf:^GSPC"]["extendida"] and inf["yf:^GSPC"]["nuevas"] == int((~raw).sum())
    # Volatilidad realizada: la de data/raw hasta su fin y calculada desde la ^GSPC extendida después.
    v = con[con["serie"] == "deriv:VOLREAL21_GSPC"].set_index("fecha_referencia")
    calc = np.log(pd.Series(cierres, index=todas)).diff().rolling(21).std(ddof=1) * np.sqrt(252)
    assert v.index.max() == todas[-1] and np.allclose(v["valor"], calc.loc[v.index], rtol=1e-12)
    g = g_con.set_index("fecha_referencia")
    assert (v["fecha_publicacion"] == g.loc[v.index, "fecha_publicacion"]).all()
    validar_series(con)
    # Ninguna fila nueva se ve antes de su disponible_utc.
    assert (con["fecha_publicacion"] >= con["disponible_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
            .dt.normalize()).all()


def test_t3b_yf_extension_regla_mas_tardia_y_solape_distinto(tmp_path, cat):
    from ingesta.mercados_series.fuentes import fase1

    rng = np.random.default_rng(4)
    todas = pd.bdate_range("2024-01-02", "2024-04-30")
    cierres = np.round(4000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(todas)))), 2)
    raw = todas < "2024-03-20"
    _yf_raw(tmp_path / "raw", todas[raw], cierres[raw], vol_hasta=pd.Timestamp("2024-03-19"))
    sub = {"yf:^GSPC": cat["yf:^GSPC"]}
    # Almacén con un mercado que cierra antes (otra bolsa): manda la regla del catálogo (XNYS), más tardía.
    _almacen_gspc(tmp_path / "antes", todas, cierres, mercado="XLON")
    inf: dict = {}
    t = fase1.tabla_fase1(tmp_path / "raw", sub, extender_precios=tmp_path / "antes", informe=inf)
    nuevas = t[t["fecha_referencia"] >= "2024-03-20"]
    from ingesta.mercados_series import visibilidad

    regla = visibilidad.disponible_cierre_serie(nuevas["fecha_referencia"].reset_index(drop=True), "XNYS")
    assert (nuevas["disponible_utc"].reset_index(drop=True) == regla).all()
    assert inf["yf:^GSPC"]["regla_mas_tardia"] == len(nuevas)
    # Un cierre distinto en el solape: no se extiende.
    otro = cierres.copy()
    otro[5] += 1.0
    _almacen_gspc(tmp_path / "distinto", todas, otro)
    inf = {}
    t = fase1.tabla_fase1(tmp_path / "raw", sub, extender_precios=tmp_path / "distinto", informe=inf)
    assert t["fecha_referencia"].max() < pd.Timestamp("2024-03-20")
    assert not inf["yf:^GSPC"]["extendida"] and "1 de" in inf["yf:^GSPC"]["motivo"]
    # Sin el ticker en el almacén: tampoco.
    inf = {}
    fase1.tabla_fase1(tmp_path / "raw", sub, extender_precios=tmp_path / "vacio", informe=inf)
    assert inf["yf:^GSPC"]["motivo"] == "sin el ticker en el almacén de precios"
