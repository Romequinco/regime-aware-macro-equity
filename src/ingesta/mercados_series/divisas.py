"""Divisas: subunidades de cotización y conversión a USD AL LEER con el FX visible en fecha.

Se guarda siempre la divisa original; la conversión se hace en las tools. El BCE publica unidades
de X por 1 EUR (series ``ecb:EXR.D.<X>.EUR``, ~16:00 Europe/Berlin), luego::

    USD por 1 X = (USD/EUR) / (X/EUR)      (X = EUR → USD/EUR; X = USD → 1)

**FX secundario (saneado P03, 2026-11-21):** para las divisas que el BCE no publica o dejó de publicar
(``SERIES_SECUNDARIAS``: el TWD desde el 2020-10-30 y el CNY antes de 2000) se usa la Fed H.10 en FRED
(``fred:DEXTAUS`` y ``fred:DEXCHUS``), que son **unidades de X por 1 USD**: ``USD por 1 X = 1 / DEX``. Mismo
TimeGate que el BCE (``timegate.as_of_series`` con la ``fecha_publicacion`` de la base: la Fed publica la H.10
cada semana, con varios días de retraso sobre la fecha de referencia). En cada ``fecha_referencia`` manda el
BCE si tiene fixing; la Fed rellena solo las fechas sin fixing del BCE.

El TimeGate se aplica a los fixings: solo cuentan los visibles en la fecha de decisión
(``timegate.as_of_series``). Cada fila se convierte con el último fixing visible cuya
``fecha_referencia`` sea <= la de la fila (festivos TARGET: el anterior).

**Tope de antigüedad (saneado P03):** si el fixing que tocaría tiene más de ``TOPE_DIAS_HABILES`` días hábiles
de antigüedad respecto a la fecha de la fila (5 para el BCE, diario; 10 para la Fed H.10, que se publica una vez
por semana y llega con hasta 7-8 días hábiles de retraso), la fila sale ``NaN`` con aviso: nunca se convierte con
un fixing caducado (antes, 2330.TW y ^TWII se convertían con el último TWD del BCE, de 2020).

Cobertura (límite conocido): los tipos de referencia del BCE empiezan el 1999-01-04 y solo cubren
unas 30 divisas (algunas empiezan después de 1999 y el RUB está suspendido desde 2022). Fuera de esa
cobertura y de la secundaria la conversión deja ``NaN`` y un aviso, nunca un FX inventado.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from ingesta.mercados_series import timegate

FechaLike = date | str | pd.Timestamp

# Subunidad de cotización → (divisa ISO, unidades de subunidad por unidad).
SUBUNIDADES: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),   # peniques (Londres)
    "GBX": ("GBP", 100.0),   # alias de GBp en algunas fuentes
    "ZAc": ("ZAR", 100.0),   # céntimos de rand (Johannesburgo)
    "ILA": ("ILS", 100.0),   # agorot (Tel Aviv)
    "USX": ("USD", 100.0),   # centavos de dólar (futuros de maíz, soja y trigo del CBOT: ZC=F, ZS=F, ZW=F; P04)
}
SERIE_FX = "ecb:EXR.D.{divisa}.EUR"
SERIE_USD_EUR = SERIE_FX.format(divisa="USD")
# FX secundario (P03): Fed H.10 en FRED, en UNIDADES DE X POR 1 USD (la inversa del sentido que se devuelve).
SERIES_SECUNDARIAS: dict[str, str] = {"TWD": "fred:DEXTAUS", "CNY": "fred:DEXCHUS"}
FUENTE_BCE, FUENTE_FED = "bce", "fed_h10"
# Antigüedad máxima (días hábiles L-V entre el fixing y la fecha de la fila) por fuente del fixing (P03).
TOPE_DIAS_HABILES: dict[str, int] = {FUENTE_BCE: 5, FUENTE_FED: 10}


def normalizar_subunidad(valores: pd.Series | np.ndarray | float, divisa: str):
    """``(valores / factor, divisa ISO)`` si ``divisa`` es una subunidad; si no, ``(valores, divisa)``.

    Distingue mayúsculas (``GBp`` ≠ ``GBP``). No modifica la entrada.
    """
    if divisa in SUBUNIDADES:
        iso, factor = SUBUNIDADES[divisa]
        return valores / factor, iso
    return valores, divisa


def series_fx(divisas: Sequence[str]) -> set[str]:
    """Ids de la base de series que hacen falta para convertir ``divisas`` (ISO o subunidades) a USD:
    ``ecb:EXR.D.USD.EUR``, ``ecb:EXR.D.<X>.EUR`` y la secundaria de ``SERIES_SECUNDARIAS``."""
    isos = {normalizar_subunidad(1.0, d)[1] for d in divisas} - {"USD"}
    if not isos:
        return set()
    ids = {SERIE_USD_EUR} | {SERIE_FX.format(divisa=d) for d in isos if d != "EUR"}
    return ids | {SERIES_SECUNDARIAS[d] for d in isos if d in SERIES_SECUNDARIAS}


def _fixings(base: pd.DataFrame, serie: str, fecha: FechaLike) -> pd.Series:
    """Fixings de ``serie`` visibles en ``fecha`` (sin huecos), indexados por ``fecha_referencia``."""
    visibles = timegate.as_of_series(base, serie, fecha)
    visibles = visibles[visibles["valor"].notna()]
    return pd.Series(visibles["valor"].to_numpy(float),
                     index=pd.DatetimeIndex(visibles["fecha_referencia"], name="fecha_referencia"))


def _existe(base: pd.DataFrame, serie: str) -> bool:
    return bool(len(base)) and bool((base["serie"] == serie).any())


def _tabla_bce(base_series: pd.DataFrame, divisa: str, fecha: FechaLike) -> pd.Series | None:
    """USD por 1 ``divisa`` del BCE visible en ``fecha``; ``None`` si falta alguna de sus dos series."""
    nombre = f"USD/{divisa}"
    if not _existe(base_series, SERIE_USD_EUR):
        return None
    usd_eur = _fixings(base_series, SERIE_USD_EUR, fecha)
    if divisa == "USD":
        return pd.Series(1.0, index=usd_eur.index, name=nombre)
    if divisa == "EUR":
        return usd_eur.rename(nombre)
    serie = SERIE_FX.format(divisa=divisa)
    if not _existe(base_series, serie):
        return None
    x_eur = _fixings(base_series, serie, fecha)
    comunes = usd_eur.index.intersection(x_eur.index)
    return (usd_eur.loc[comunes] / x_eur.loc[comunes]).rename(nombre)


def _tabla_fed(base_series: pd.DataFrame, divisa: str, fecha: FechaLike) -> pd.Series | None:
    """USD por 1 ``divisa`` de la Fed H.10 (``1 / DEX*``: la serie viene en X por 1 USD) visible en ``fecha``;
    ``None`` si la divisa no tiene secundaria o su serie no está en la base. Los valores <= 0 se descartan."""
    serie = SERIES_SECUNDARIAS.get(divisa)
    if serie is None or not _existe(base_series, serie):
        return None
    x_usd = _fixings(base_series, serie, fecha)
    x_usd = x_usd[x_usd > 0]
    return (1.0 / x_usd).rename(f"USD/{divisa}")


def tabla_fx(base_series: pd.DataFrame, divisa: str, fecha: FechaLike) -> pd.DataFrame:
    """USD por 1 ``divisa`` visible en ``fecha`` con su fuente: columnas ``usd`` y ``fuente``
    (``FUENTE_BCE`` o ``FUENTE_FED``), índice ``fecha_referencia`` ordenado.

    En cada fecha manda el BCE; la Fed H.10 (``SERIES_SECUNDARIAS``) solo cubre las fechas sin fixing del BCE.
    ``KeyError`` si no hay ni serie del BCE ni secundaria; una subunidad es ``ValueError``.
    """
    if divisa in SUBUNIDADES:
        raise ValueError(f"{divisa!r} es una subunidad: normaliza antes con normalizar_subunidad")
    bce = _tabla_bce(base_series, divisa, fecha)
    fed = _tabla_fed(base_series, divisa, fecha)
    if bce is None and fed is None:
        if divisa == "USD":
            bce = pd.Series([], index=pd.DatetimeIndex([], name="fecha_referencia"), dtype=float)
        elif not _existe(base_series, SERIE_USD_EUR):
            raise KeyError(f"no hay serie {SERIE_USD_EUR!r} en la base de FX")
        else:
            extra = f" ni {SERIES_SECUNDARIAS[divisa]!r}" if divisa in SERIES_SECUNDARIAS else ""
            raise KeyError(f"no hay serie del BCE {SERIE_FX.format(divisa=divisa)!r}{extra} para {divisa!r}")
    partes = []
    if bce is not None:
        partes.append(pd.DataFrame({"usd": bce.to_numpy(float), "fuente": FUENTE_BCE}, index=bce.index))
    if fed is not None:
        resto = fed[~fed.index.isin(bce.index)] if bce is not None else fed
        partes.append(pd.DataFrame({"usd": resto.to_numpy(float), "fuente": FUENTE_FED}, index=resto.index))
    out = pd.concat(partes).sort_index(kind="mergesort")
    out.index = pd.DatetimeIndex(out.index, name="fecha_referencia")
    return out


def fx_usd_por_unidad(base_series: pd.DataFrame, divisa: str, fecha: FechaLike) -> pd.Series:
    """USD por 1 unidad de ``divisa`` tal como se conocía en ``fecha`` (BCE y, si falta, Fed H.10).

    Usa ``timegate.as_of_series`` sobre ``ecb:EXR.D.USD.EUR`` y ``ecb:EXR.D.<divisa>.EUR`` y las
    alinea por ``fecha_referencia`` (solo días con ambas); en las fechas sin fixing del BCE, la secundaria de
    ``SERIES_SECUNDARIAS`` (``tabla_fx``). Índice: ``fecha_referencia``; nombre: ``f'USD/{divisa}'``.
    ``USD`` → serie de 1.0 en las fechas de USD/EUR; ``EUR`` → USD/EUR. Una subunidad es ``ValueError``
    (normalizar antes); una divisa sin serie del BCE ni secundaria, ``KeyError``. Los fixings nulos (huecos
    declarados) se descartan.
    """
    return tabla_fx(base_series, divisa, fecha)["usd"].rename(f"USD/{divisa}")


def a_usd(df: pd.DataFrame, columnas: Sequence[str], columna_divisa_o_valor: str,
          base_fx: pd.DataFrame, fecha: FechaLike, columna_fecha: str) -> pd.DataFrame:
    """Copia de ``df`` con ``columnas`` convertidas a USD con el FX visible en ``fecha``.

    ``columna_divisa_o_valor``: nombre de una columna de ``df`` con la divisa de cada fila, o un
    código de divisa común a todas. Primero se normalizan subunidades; después, para la fecha de
    cada fila (``columna_fecha``) se usa el último fixing con ``fecha_referencia <=`` esa fecha
    entre los visibles en ``fecha`` (festivos del BCE: el anterior). Sin fixing previo → ``NaN``
    y la fila se cuenta en ``df.attrs['avisos']``. Añade ``divisa_original`` y ``fx_usd`` (factor
    aplicado) y deja ``divisa = 'USD'``. No modifica ``df``.

    Detalles: ``fx_usd`` es el multiplicador total (incluye la subunidad: GBp → USD/GBP / 100);
    ``fx_fecha`` es la ``fecha_referencia`` del fixing usado (NaT para USD y sin fixing). Si la
    fecha de una fila es posterior al último fixing visible (su fixing aún no se conocía en
    ``fecha``, o fin de semana), se usa ese último y se avisa, salvo que tenga más de
    ``TOPE_DIAS_HABILES`` días hábiles de antigüedad (P03): entonces ``NaN`` y aviso. Las fechas sin fixing
    del BCE usan la Fed H.10 si la divisa está en ``SERIES_SECUNDARIAS`` (aviso). Una divisa sin serie y una
    fila con fecha nula (salvo en USD) dejan ``NaN`` y un aviso. ``avisos`` es una lista de textos
    (se conservan los que ya tuviera ``df``).
    """
    faltan = [c for c in [*columnas, columna_fecha] if c not in df.columns]
    if faltan:
        raise KeyError(f"columnas que no están en df: {faltan}")
    out = df.copy()
    avisos: list[str] = list(df.attrs.get("avisos", []))
    es_columna = columna_divisa_o_valor in df.columns
    divisas = (df[columna_divisa_o_valor] if es_columna
               else pd.Series(columna_divisa_o_valor, index=df.index, dtype=object))
    if divisas.isna().any():
        raise ValueError(f"{int(divisas.isna().sum())} filas sin divisa: no se pueden convertir a USD")
    fechas = pd.to_datetime(df[columna_fecha])
    if isinstance(fechas.dtype, pd.DatetimeTZDtype):
        raise ValueError(f"{columna_fecha!r} debe ser una fecha sin huso (sesión o periodo)")
    fechas = fechas.dt.normalize()
    fecha_decision = timegate.fecha_decision(fecha)

    fx = pd.Series(np.nan, index=df.index, dtype=float)
    fx_fecha = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for original in pd.unique(divisas):
        filas = divisas == original
        uno, iso = normalizar_subunidad(1.0, original)
        if iso == "USD":
            fx[filas] = uno
            continue
        try:
            completa = tabla_fx(base_fx, iso, fecha_decision)
        except KeyError as e:
            avisos.append(f"{int(filas.sum())} filas en {original} sin FX del BCE ({e.args[0]}): valores NaN")
            continue
        tabla = completa["usd"]
        d = fechas[filas].to_numpy("datetime64[ns]")
        sin_fecha = np.isnat(d)
        # searchsorted coloca NaT al final (daría el último fixing): las fechas nulas no tienen FX.
        pos = tabla.index.to_numpy("datetime64[ns]").searchsorted(d, side="right") - 1
        con_fx = (pos >= 0) & ~sin_fecha
        valores = np.full(len(d), np.nan)
        usadas = np.full(len(d), np.datetime64("NaT"), dtype="datetime64[ns]")
        # Tope de antigüedad (P03): un fixing con más de TOPE_DIAS_HABILES[fuente] días hábiles no se usa.
        caducado = np.zeros(len(d), bool)
        if con_fx.any():
            ref = tabla.index.to_numpy("datetime64[D]")[pos[con_fx]]
            tope = np.array([TOPE_DIAS_HABILES[f] for f in completa["fuente"].to_numpy()[pos[con_fx]]])
            # Antigüedad hasta la fecha de la fila, sin pasar de la de decisión: una fila posterior a la decisión
            # (periodo que acaba después) solo puede usar el último fixing visible y se mide hasta la decisión.
            hasta = np.minimum(d[con_fx].astype("datetime64[D]"), np.datetime64(fecha_decision.date(), "D"))
            caducado[con_fx] = np.busday_count(ref, np.maximum(hasta, ref)) > tope
        n_caducado = int(caducado.sum())
        con_fx &= ~caducado
        valores[con_fx] = tabla.to_numpy(float)[pos[con_fx]] * uno
        usadas[con_fx] = tabla.index.to_numpy("datetime64[ns]")[pos[con_fx]]
        n_fed = int((completa["fuente"].to_numpy()[pos[con_fx]] == FUENTE_FED).sum()) if con_fx.any() else 0
        if n_fed:
            avisos.append(f"{n_fed} filas en {original} con el FX secundario de la Fed H.10 "
                          f"({SERIES_SECUNDARIAS[iso]}): el BCE no publica esas fechas")
        if n_caducado:
            avisos.append(f"{n_caducado} filas en {original} con el último fixing visible en {fecha_decision.date()} "
                          f"más viejo que el tope de antigüedad ({TOPE_DIAS_HABILES[FUENTE_BCE]} días hábiles el BCE, "
                          f"{TOPE_DIAS_HABILES[FUENTE_FED]} la Fed H.10): sin FX, valores NaN")
        fx[filas] = valores
        fx_fecha[filas] = usadas
        if sin_fecha.any():
            avisos.append(f"{int(sin_fecha.sum())} filas en {original} con {columna_fecha!r} nula: "
                          f"sin FX, valores NaN")
        sin_fx = int((~con_fx & ~sin_fecha & ~caducado).sum())
        if sin_fx:
            avisos.append(f"{sin_fx} filas en {original} sin fixing del BCE visible en "
                          f"{fecha_decision.date()} anterior o igual a su fecha: valores NaN")
        if len(tabla):
            ultimo = tabla.index.max()
            tarde = int((d[con_fx] > ultimo.to_datetime64()).sum())
            if tarde:
                avisos.append(f"{tarde} filas en {original} posteriores al último fixing visible en "
                              f"{fecha_decision.date()} ({ultimo.date()}): se usa ese fixing")

    for c in columnas:
        out[c] = pd.to_numeric(df[c], errors="raise").astype(float) * fx
    out["divisa_original"] = divisas.astype(object).to_numpy()
    out["fx_usd"] = fx
    out["fx_fecha"] = fx_fecha
    out["divisa"] = "USD"
    if es_columna and columna_divisa_o_valor != "divisa":
        out[columna_divisa_o_valor] = "USD"
    out.attrs["avisos"] = avisos
    return out
