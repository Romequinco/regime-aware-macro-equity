"""Carteras de referencia (baselines) del Tema 1, sin mirar al futuro (bloque 8).

Motor (``simular``): en cada fecha de control (último día hábil de cada mes, a las 16:30 de Nueva
York) se llama a ``tools.get_precios`` con ESA fecha para los tickers en cartera y los candidatos
de la estrategia. Con esa respuesta (y solo con ella):

1. se valora el tramo desde el control anterior: en cada día hábil ``d`` del tramo, el precio de
   cada ticker es el cierre ajustado total de la última sesión con ``fecha_publicacion <= d``
   (punto en el tiempo también dentro del tramo), y el valor es
   ``V_prev · Σ w_i · P_i(d) / P_i(control anterior)``: un cociente de precios ajustados con la
   misma base, que no depende de los dividendos o splits posteriores;
2. la estrategia decide los pesos nuevos (o ``None``: no se opera y los pesos derivan) con la
   VISTA DE SEÑAL: solo las sesiones anteriores al cierre con el que se ejecuta (``vista_senal``);
3. se cobra el coste de la rotación (``ModeloCostes`` o ninguno) y se descuenta del valor.

La base de cada ticker se recorta a la ventana que hace falta (``[control anterior o
fecha − ventana, fecha]``): las filas posteriores a la fecha nunca son visibles y los eventos
anteriores a la ventana afectan igual a numerador y denominador, así que el resultado no cambia.
Propiedad clave (test de truncado): la curva en ``t`` no cambia si se añaden precios posteriores.

Convención de ejecución (``ejecucion``, decisión cerrada en el saneado P08, 2026-11-21; ``docs/tfm/arquitectura.md``):

- ``"apertura_t1"`` (por defecto): se decide tras el cierre de ``t`` (la señal ve todo lo publicado hasta ``t``,
  también el cierre de ``t``) y la orden se ejecuta en ``t + 1``: en cada instrumento, la primera sesión con
  ``sesion > t`` (``precio_ejecucion``), a su **apertura**; si esa sesión no tiene apertura (aperturas de relleno
  anuladas en la base curada, fondos con valor liquidativo, índices), a su **cierre**, con aviso. **Nunca al cierre
  de t.** El tramo se valora con lo que se sabe en cada día: hasta que la vela de ejecución de TODOS los
  instrumentos de la orden está publicada, la cartera vieja; desde entonces, la nueva (``V_ejec = Σ u_i · X_i``
  con ``X_i`` el precio de ejecución; el coste se cobra sobre ``V_ejec``). Si a algún instrumento le falta la sesión
  de ejecución en el tramo, la orden espera al control siguiente (aviso).
- ``"cierre_t1"`` (prueba de sensibilidad): igual, pero al cierre de la sesión de ejecución.
- ``"cierre_t"`` (la convención antigua, solo para comparar): se opera al cierre de cada instrumento en la fecha de
  control (ese cierre es el ``P_i(control anterior)`` del tramo siguiente y el precio del coste). Para que la señal
  no use el mismo cierre con el que se ejecuta, ``estrategia.pesos`` recibe las vistas recortadas a
  ``sesion < fecha`` y sin la fila de ejecución (``vista_senal``): la señal de ``t`` usa como mucho el cierre
  anterior al de ejecución, también en instrumentos D+1 y en controles que caen en festivo. Lo comprueba
  ``test_t1_a_baselines_senal_no_usa_cierre_de_ejecucion``.

El hueco entre el cierre de ``t`` y la apertura de ``t + 1`` (coste del salto de apertura) se mide comparando
``apertura_t1`` con ``cierre_t1`` (``informe``).

Todo en USD (los tickers en otra divisa se piden con ``divisa='USD'`` y el FX del BCE visible).
El efectivo no remunera (los pesos suman 1 una vez invertida la cartera).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ingesta.mercados_series import timegate, tools

# Vista de un ticker en una fecha de control: sesion, fecha_publicacion y close (ajuste total).
Vistas = dict[str, pd.DataFrame]
FuncionPesos = Callable[[pd.Timestamp, Vistas, dict[str, float]], dict[str, float] | None]

SPDR_SECTORES: tuple[str, ...] = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC")
INICIO_AGG = pd.Timestamp("2003-09-29")
DIAS_FRESCO = 7  # un ticker está «vivo» en la fecha si tiene una sesión visible en los últimos 7 días
EJECUCIONES = ("apertura_t1", "cierre_t1", "cierre_t")
EJECUCION_POR_DEFECTO = "apertura_t1"


@dataclass
class Estrategia:
    """Una cartera de referencia: candidatos por fecha, regla de pesos y ventana de historia."""

    nombre: str
    universo: Callable[[pd.Timestamp], list[str]]
    pesos: FuncionPesos
    ventana_dias: int = 15
    notas: list[str] = field(default_factory=list)


@dataclass
class Resultado:
    nombre: str
    curva: pd.Series                  # valor en USD por día hábil (punto en el tiempo)
    rebalanceos: pd.DataFrame         # fecha, pesos, rotación, coste
    avisos: list[str] = field(default_factory=list)

    @property
    def rendimientos(self) -> pd.Series:
        return self.curva.pct_change().dropna()

    def drawdown(self) -> pd.Series:
        return self.curva / self.curva.cummax() - 1.0


# --- Utilidades de precio a fecha ---------------------------------------------------------------
def fechas_control(inicio, fin, frecuencia: str = "BME") -> pd.DatetimeIndex:
    """Últimos días hábiles de cada mes entre ``inicio`` y ``fin`` (y ``fin`` al final)."""
    i, f = timegate.fecha_decision(inicio), timegate.fecha_decision(fin)
    fechas = pd.date_range(i, f, freq=frecuencia)
    if len(fechas) == 0 or fechas[-1] != f:
        fechas = fechas.append(pd.DatetimeIndex([f]))
    return fechas


def precio_en(vista: pd.DataFrame, fechas: pd.DatetimeIndex | Sequence) -> np.ndarray:
    """Cierre ajustado de la última sesión con ``fecha_publicacion <= d`` para cada ``d`` (NaN si no hay)."""
    idx = pd.DatetimeIndex(fechas)
    if vista is None or vista.empty:
        return np.full(len(idx), np.nan)
    pub = vista["fecha_publicacion"].to_numpy("datetime64[ns]")
    i = np.searchsorted(pub, idx.to_numpy("datetime64[ns]"), side="right") - 1
    cierres = vista["close"].to_numpy(float)
    return np.where(i >= 0, cierres[np.clip(i, 0, None)], np.nan)


def vista_senal(vista: pd.DataFrame | None, fecha: pd.Timestamp) -> pd.DataFrame | None:
    """Vista para la señal de ``fecha``: sin el cierre con el que se ejecuta ni nada posterior.

    El cierre de ejecución es el de ``precio_en(vista, [fecha])``: la última sesión con
    ``fecha_publicacion <= fecha``. No siempre es la sesión de ``fecha``: en un instrumento D+1 (NAV de
    fondos) es la de la víspera, y si el control cae en festivo del mercado es la última sesión antes
    del festivo. Se quita esa fila (por publicación, no por sesión) y cualquier sesión ``>= fecha``.
    """
    if vista is None:
        return None
    dia = pd.Timestamp(fecha).normalize()
    pub = vista["fecha_publicacion"].to_numpy("datetime64[ns]")
    ejecucion = int(np.searchsorted(pub, dia.to_datetime64(), side="right")) - 1
    previa = np.arange(len(vista)) < ejecucion
    return vista[previa & (vista["sesion"] < dia).to_numpy()].reset_index(drop=True)


def precio_ejecucion(vista: pd.DataFrame | None, fecha: pd.Timestamp, ejecucion: str = EJECUCION_POR_DEFECTO
                     ) -> tuple[pd.Timestamp, float, pd.Timestamp, bool] | None:
    """Precio de ejecución en ``t + 1`` de una orden decidida tras el cierre de ``fecha``.

    Sesión de ejecución: la primera con ``sesion > fecha`` (por día natural: en un fondo D+1 o en un mercado con
    festivo es la siguiente que tenga). ``"apertura_t1"``: su ``open`` y, si falta (nulo o <= 0), su ``close``
    (reserva, con aviso de quien llama); ``"cierre_t1"``: su ``close``. Nunca el cierre de ``fecha``. Devuelve
    ``(sesion, precio, fecha_publicacion, reserva)`` o ``None`` si la vista no tiene esa sesión (aún no publicada).
    """
    if ejecucion not in ("apertura_t1", "cierre_t1"):
        raise ValueError(f"ejecución en t+1 desconocida: {ejecucion!r}")
    if vista is None or vista.empty:
        return None
    dia = pd.Timestamp(fecha).normalize()
    despues = vista[vista["sesion"] > dia]
    if despues.empty:
        return None
    fila = despues.iloc[0]
    cierre = float(fila["close"])
    apertura = float(fila["open"]) if "open" in fila and pd.notna(fila["open"]) else np.nan
    reserva = ejecucion == "apertura_t1" and not (np.isfinite(apertura) and apertura > 0)
    precio = cierre if ejecucion == "cierre_t1" or reserva else apertura
    return pd.Timestamp(fila["sesion"]), precio, pd.Timestamp(fila["fecha_publicacion"]), reserva


def vivo(vista: pd.DataFrame | None, fecha: pd.Timestamp, dias: int = DIAS_FRESCO) -> bool:
    """True si la vista tiene una sesión publicada en los ``dias`` naturales previos a ``fecha``."""
    if vista is None or vista.empty:
        return False
    ultima = vista["fecha_publicacion"].iloc[-1]
    return bool(ultima <= fecha and (fecha - ultima).days <= dias)


def _vista(tk: str, fecha: pd.Timestamp, base: pd.DataFrame | None, desde: pd.Timestamp,
           base_fx: pd.DataFrame | None, avisos: list[str]) -> pd.DataFrame | None:
    """``get_precios(tk, fecha, ajuste='total')`` con la base recortada a ``[desde, fecha]``."""
    if base is None or base.empty:
        return None
    rec = base[(base["sesion"] >= desde) & (base["sesion"] <= fecha)]
    if rec.empty:
        return None
    divisas = set(rec["divisa"].dropna())
    divisa = "original" if divisas <= {"USD"} else "USD"
    r = tools.get_precios(tk, fecha, ajuste="total", divisa=divisa, base=rec, base_fx=base_fx)
    avisos += [a for a in r.avisos if "sin sesiones publicadas" not in a]
    if r.datos.empty:
        return None
    return r.datos[["sesion", "fecha_publicacion", "open", "close"]].reset_index(drop=True)


# --- Motor -------------------------------------------------------------------------------------
def simular(estrategia: Estrategia, precios: dict[str, pd.DataFrame], inicio, fin, *,
            capital: float = 10_000.0, costes: Callable[..., float] | None = None,
            base_fx: pd.DataFrame | None = None, frecuencia: str = "BME",
            ejecucion: str = EJECUCION_POR_DEFECTO) -> Resultado:
    """Simula ``estrategia`` entre ``inicio`` y ``fin`` (fechas de decisión) con ``capital`` USD.

    ``precios``: ``{ticker: tabla del contrato de precios}`` (as-traded, la de ``almacen``).
    ``costes``: ``f(ticker, importe_usd, fecha, precio) -> USD`` (``costes.ModeloCostes``) o None.
    ``ejecucion``: ``EJECUCIONES`` (ver el docstring del módulo; por defecto la apertura de ``t + 1``).
    La curva empieza el primer día en que la estrategia decide invertir.
    """
    if ejecucion not in EJECUCIONES:
        raise ValueError(f"ejecución desconocida {ejecucion!r}; se espera una de {EJECUCIONES}")
    if ejecucion != "cierre_t":
        return _simular_t1(estrategia, precios, inicio, fin, capital=capital, costes=costes, base_fx=base_fx,
                           frecuencia=frecuencia, ejecucion=ejecucion)
    controles = fechas_control(inicio, fin, frecuencia)
    fin_ts = controles[-1]
    pesos: dict[str, float] = {}
    valor = float(capital)
    anterior: pd.Timestamp | None = None
    puntos: list[pd.Series] = []
    filas: list[dict] = []
    avisos: list[str] = []
    for k, fecha in enumerate(controles):
        candidatos = estrategia.universo(fecha)
        necesarios = sorted(set(pesos) | set(candidatos))
        desde = fecha - pd.Timedelta(days=estrategia.ventana_dias)
        if anterior is not None:
            desde = min(desde, anterior - pd.Timedelta(days=DIAS_FRESCO + 3))
        vistas = {tk: _vista(tk, fecha, precios.get(tk), desde, base_fx, avisos) for tk in necesarios}
        if anterior is not None and pesos:
            dias = pd.bdate_range(anterior + pd.Timedelta(days=1), fecha)
            rel = np.zeros(len(dias))
            nuevos_pesos = {}
            for tk, w in pesos.items():
                v = vistas.get(tk)
                p0 = precio_en(v, [anterior])[0]
                p = precio_en(v, dias)
                ratio = p / p0 if np.isfinite(p0) and p0 > 0 else np.full(len(dias), np.nan)
                if np.isnan(ratio).any():
                    avisos.append(f"{estrategia.nombre}: {tk} sin precio visible en parte de "
                                  f"{anterior.date()}..{fecha.date()}: se congela su valor")
                    ratio = pd.Series(ratio).ffill().fillna(1.0).to_numpy()
                rel += w * ratio
                nuevos_pesos[tk] = w * ratio[-1] if len(ratio) else w
            if len(dias):
                puntos.append(pd.Series(valor * rel, index=dias))
                valor = float(valor * rel[-1])
                total = sum(nuevos_pesos.values())
                pesos = {tk: x / total for tk, x in nuevos_pesos.items()} if total > 0 else pesos
        # En el último control solo se valora (la curva en ``fin`` es la de antes de operar).
        senal = {tk: vista_senal(v, fecha) for tk, v in vistas.items()}
        objetivo = estrategia.pesos(fecha, senal, dict(pesos)) if fecha < fin_ts else None
        if objetivo:
            objetivo = {tk: float(w) for tk, w in objetivo.items() if w > 0}
            suma = sum(objetivo.values())
            objetivo = {tk: w / suma for tk, w in objetivo.items()}
            claves = set(objetivo) | set(pesos)
            rotacion = sum(abs(objetivo.get(tk, 0.0) - pesos.get(tk, 0.0)) for tk in claves)
            coste = 0.0
            if costes is not None:
                for tk in claves:
                    importe = abs(objetivo.get(tk, 0.0) - pesos.get(tk, 0.0)) * valor
                    if importe > 0:
                        precio = precio_en(vistas.get(tk), [fecha])[0]
                        coste += float(costes(tk, importe, fecha, precio if np.isfinite(precio) else None))
            if not puntos:
                puntos.append(pd.Series([valor], index=pd.DatetimeIndex([fecha])))
            valor -= coste
            filas.append({"fecha": fecha, "valor_antes": valor + coste, "rotacion": rotacion, "coste": coste,
                          "pesos": dict(sorted(objetivo.items()))})
            pesos = objetivo
        anterior = fecha if pesos else None
    curva = pd.concat(puntos) if puntos else pd.Series(dtype=float)
    curva = curva[~curva.index.duplicated(keep="last")].rename(estrategia.nombre)
    # Avisos repetidos (mismo texto en muchos controles) una sola vez.
    return Resultado(nombre=estrategia.nombre, curva=curva, rebalanceos=pd.DataFrame(filas),
                     avisos=list(dict.fromkeys(avisos)))


def _simular_t1(estrategia: Estrategia, precios: dict[str, pd.DataFrame], inicio, fin, *, capital: float,
                costes: Callable[..., float] | None, base_fx: pd.DataFrame | None, frecuencia: str,
                ejecucion: str) -> Resultado:
    """Motor con ejecución en ``t + 1`` (``"apertura_t1"`` o ``"cierre_t1"``; ver el docstring del módulo)."""
    controles = fechas_control(inicio, fin, frecuencia)
    fin_ts = controles[-1]
    pesos: dict[str, float] = {}          # pesos al cierre del control anterior (cartera ya ejecutada)
    pendiente: dict[str, float] | None = None   # orden decidida en el control anterior, por ejecutar en t+1
    decidida: pd.Timestamp | None = None
    valor = float(capital)
    anterior: pd.Timestamp | None = None
    puntos: list[pd.Series] = []
    filas: list[dict] = []
    avisos: list[str] = []
    for fecha in controles:
        candidatos = estrategia.universo(fecha)
        necesarios = sorted(set(pesos) | set(candidatos) | set(pendiente or {}))
        desde = fecha - pd.Timedelta(days=estrategia.ventana_dias)
        if anterior is not None:
            desde = min(desde, anterior - pd.Timedelta(days=DIAS_FRESCO + 3))
        vistas = {tk: _vista(tk, fecha, precios.get(tk), desde, base_fx, avisos) for tk in necesarios}
        if anterior is not None:
            dias = pd.bdate_range(anterior + pd.Timedelta(days=1), fecha)
            # Cartera vieja en unidades de la vista de hoy (cociente de precios ajustados con la misma base).
            unidades: dict[str, float] = {}
            serie: dict[str, np.ndarray] = {}
            congelados: set[str] = set()          # sin precio en el control anterior: unidades = valor
            for tk, w in pesos.items():
                v = vistas.get(tk)
                p0 = precio_en(v, [anterior])[0]
                p = precio_en(v, dias)
                if not (np.isfinite(p0) and p0 > 0):
                    avisos.append(f"{estrategia.nombre}: {tk} sin precio visible en {anterior.date()}: se congela "
                                  "su valor")
                    unidades[tk], serie[tk] = valor * w, np.ones(len(dias))
                    congelados.add(tk)
                    continue
                if np.isnan(p).any():
                    avisos.append(f"{estrategia.nombre}: {tk} sin precio visible en parte de "
                                  f"{anterior.date()}..{fecha.date()}: se congela su valor")
                    p = pd.Series(p).ffill().fillna(p0).to_numpy()
                unidades[tk], serie[tk] = valor * w / p0, p
            efectivo = 0.0 if pesos else valor     # antes de la primera ejecución todo es efectivo
            viejo = efectivo + sum(unidades[tk] * serie[tk] for tk in unidades) if unidades else np.full(
                len(dias), efectivo)
            curva_tramo = np.asarray(viejo, dtype=float)
            nuevas: dict[str, float] | None = None
            if pendiente is not None and len(dias):
                claves = sorted(set(pendiente) | set(pesos))
                ejec = {tk: precio_ejecucion(vistas.get(tk), decidida, ejecucion) for tk in claves}
                faltan = [tk for tk, e in ejec.items() if e is None or e[2] > fecha]
                if faltan:
                    avisos.append(f"{estrategia.nombre}: orden del {decidida.date()} sin sesión de ejecución "
                                  f"visible para {faltan[:3]}: espera al control siguiente")
                else:
                    x = {tk: e[1] for tk, e in ejec.items()}
                    al_ejecutar = {tk: unidades[tk] * (1.0 if tk in congelados else x[tk]) for tk in unidades}
                    v_ejec = efectivo + sum(al_ejecutar.values())
                    previos = {tk: a / v_ejec for tk, a in al_ejecutar.items()} if v_ejec > 0 else {}
                    rotacion = sum(abs(pendiente.get(tk, 0.0) - previos.get(tk, 0.0)) for tk in claves)
                    coste = 0.0
                    sesion_e = min(e[0] for e in ejec.values())
                    if costes is not None:
                        for tk in claves:
                            importe = abs(pendiente.get(tk, 0.0) - previos.get(tk, 0.0)) * v_ejec
                            if importe > 0:
                                coste += float(costes(tk, importe, ejec[tk][0], x[tk]))
                    reservas = sorted(tk for tk, e in ejec.items() if e[3] and tk in pendiente)
                    if reservas:
                        avisos.append(f"{estrategia.nombre}: sin apertura en la sesión de ejecución de "
                                      f"{reservas[:3]} (orden del {decidida.date()}): se ejecuta a su cierre")
                    despues = v_ejec - coste
                    nuevas = {tk: despues * w / x[tk] for tk, w in pendiente.items()}
                    visible = max(e[2] for tk, e in ejec.items())
                    tras = (dias >= visible)
                    for tk in pendiente:
                        p = precio_en(vistas.get(tk), dias)
                        p = pd.Series(p).ffill().fillna(x[tk]).to_numpy()
                        serie[tk] = p
                    nuevo = sum(nuevas[tk] * serie[tk] for tk in nuevas)
                    curva_tramo = np.where(tras, nuevo, curva_tramo)
                    filas.append({"fecha": decidida, "fecha_ejecucion": sesion_e, "valor_antes": v_ejec,
                                  "rotacion": rotacion, "coste": coste, "pesos": dict(sorted(pendiente.items())),
                                  "reserva_cierre": reservas})
                    pendiente = None
            if len(dias):
                puntos.append(pd.Series(curva_tramo, index=dias))
                valor = float(curva_tramo[-1])
                tenencia = nuevas if nuevas is not None else unidades
                if tenencia:
                    vals = {tk: u * serie[tk][-1] for tk, u in tenencia.items()}
                    total = sum(vals.values())
                    pesos = {tk: x_ / total for tk, x_ in vals.items()} if total > 0 else pesos
        # Decisión tras el cierre de ``fecha``: la señal ve todo lo publicado hasta ``fecha`` (la ejecución es en
        # t+1, que aún no existe). En el último control solo se valora.
        objetivo = estrategia.pesos(fecha, dict(vistas), dict(pesos)) if fecha < fin_ts else None
        if objetivo:
            objetivo = {tk: float(w) for tk, w in objetivo.items() if w > 0}
            suma = sum(objetivo.values())
            pendiente, decidida = {tk: w / suma for tk, w in objetivo.items()}, fecha
            if not puntos:
                puntos.append(pd.Series([valor], index=pd.DatetimeIndex([fecha])))
        anterior = fecha if (pesos or pendiente) else None
    curva = pd.concat(puntos) if puntos else pd.Series(dtype=float)
    curva = curva[~curva.index.duplicated(keep="last")].rename(estrategia.nombre)
    return Resultado(nombre=estrategia.nombre, curva=curva, rebalanceos=pd.DataFrame(filas),
                     avisos=list(dict.fromkeys(avisos)))


# --- Estrategias -------------------------------------------------------------------------------
def buy_hold(ticker: str) -> Estrategia:
    """Compra ``ticker`` en el primer control en que está vivo y no vuelve a operar."""
    def pesos(fecha, vistas, actuales):
        if actuales:
            return None
        return {ticker: 1.0} if vivo(vistas.get(ticker), fecha) else None
    return Estrategia(nombre=f"buy&hold {ticker}", universo=lambda f: [ticker], pesos=pesos)


def cartera_fija(nombre: str, objetivo: dict[str, float], *, mes_rebalanceo: int | None = 12,
                 sustitutos: dict[str, tuple[str, ...]] | None = None) -> Estrategia:
    """Pesos fijos con rebalanceo anual (control de ``mes_rebalanceo``; None = mensual).

    ``sustitutos``: ``{ticker: (preferido, alternativa, ...)}``: en cada control se usa el primero
    vivo (empalme declarado: VBMFX antes de AGG). Un cambio de instrumento fuerza el rebalanceo.
    """
    sustitutos = sustitutos or {}

    def elegir(clave, vistas, fecha):
        for tk in sustitutos.get(clave, (clave,)):
            if vivo(vistas.get(tk), fecha):
                return tk
        return None

    def universo(fecha):
        return sorted({tk for c in objetivo for tk in sustitutos.get(c, (c,))})

    def pesos(fecha, vistas, actuales):
        elegidos = {c: elegir(c, vistas, fecha) for c in objetivo}
        if any(tk is None for tk in elegidos.values()):
            return None
        nuevo = {elegidos[c]: w for c, w in objetivo.items()}
        toca = (not actuales or set(nuevo) != set(actuales)
                or mes_rebalanceo is None or fecha.month == mes_rebalanceo)
        return nuevo if toca else None
    notas = [f"empalme {c}: {' → '.join(reversed(s))} (se usa el primero vivo en cada control)"
             for c, s in sustitutos.items()]
    return Estrategia(nombre=nombre, universo=universo, pesos=pesos, notas=notas)


def sesenta_cuarenta() -> Estrategia:
    """60 % SPY / 40 % AGG con rebalanceo anual (diciembre); VBMFX hasta que AGG está vivo (2003-09-29)."""
    return cartera_fija("60/40 SPY/AGG", {"SPY": 0.6, "AGG": 0.4}, sustitutos={"AGG": ("AGG", "VBMFX")})


def sesenta_cuarenta_europeo(renta_variable: str = "CSPX.L", renta_fija: str = "EUNA.DE") -> Estrategia:
    """60/40 con UCITS invertibles desde la UE (anexo). Sin precios de esos tickers no invierte."""
    return cartera_fija(f"60/40 UCITS {renta_variable}/{renta_fija}", {renta_variable: 0.6, renta_fija: 0.4})


def uno_n(universo: Iterable[str], nombre: str = "1/N ETF") -> Estrategia:
    """Pesos iguales cada mes entre los ETF del universo vivos en la fecha."""
    lista = sorted(set(universo))

    def pesos(fecha, vistas, actuales):
        vivos = [tk for tk in lista if vivo(vistas.get(tk), fecha)]
        return {tk: 1.0 / len(vivos) for tk in vivos} if vivos else None
    return Estrategia(nombre=nombre, universo=lambda f: lista, pesos=pesos)


def momentum_sectorial(sectores: Sequence[str] = SPDR_SECTORES, *, top: int = 3, meses: int = 12,
                       salto: int = 1) -> Estrategia:
    """Momentum 12-1: cada mes, los ``top`` sectores con mayor ``P(t−1m)/P(t−12m) − 1``.

    Elegible: vivo en la fecha y con precio visible en ``t − meses`` (12 meses de historia).
    Pesos iguales. Con menos de ``top`` elegibles no invierte (o mantiene la cartera).
    """
    lista = list(sectores)

    def pesos(fecha, vistas, actuales):
        f_ini = fecha - pd.DateOffset(months=meses)
        f_fin = fecha - pd.DateOffset(months=salto)
        puntos = {}
        for tk in lista:
            v = vistas.get(tk)
            if not vivo(v, fecha):
                continue
            p0, p1 = precio_en(v, [f_ini, f_fin])
            if np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and v["sesion"].iloc[0] <= f_ini:
                puntos[tk] = p1 / p0 - 1.0
        if len(puntos) < top:
            return None
        elegidos = sorted(puntos, key=lambda t: (-puntos[t], t))[:top]
        return {tk: 1.0 / top for tk in elegidos}
    return Estrategia(nombre=f"momentum sectorial {meses}-{salto} top {top}", universo=lambda f: lista,
                      pesos=pesos, ventana_dias=31 * (meses + 1) + 10)


def metricas(resultado: Resultado, rf: pd.Series | None = None) -> dict[str, float]:
    """CAGR, volatilidad anual, Sharpe (con ``rf`` diario por fecha si se da), máx. drawdown y coste total."""
    c = resultado.curva.dropna()
    if len(c) < 2:
        return {}
    anos = (c.index[-1] - c.index[0]).days / 365.25
    r = c.pct_change().dropna()
    exceso = r - (rf.reindex(r.index).fillna(0.0) if rf is not None else 0.0)
    vol = r.std() * np.sqrt(252)
    costes_total = float(resultado.rebalanceos["coste"].sum()) if len(resultado.rebalanceos) else 0.0
    return {"inicio": str(c.index[0].date()), "fin": str(c.index[-1].date()),
            "cagr": (c.iloc[-1] / c.iloc[0]) ** (1 / anos) - 1 if anos > 0 else np.nan,
            "vol": vol, "sharpe": exceso.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
            "max_drawdown": float(resultado.drawdown().min()), "rebalanceos": len(resultado.rebalanceos),
            "coste_total_usd": costes_total}


__all__ = [
    "EJECUCIONES", "EJECUCION_POR_DEFECTO", "Estrategia", "INICIO_AGG", "Resultado", "SPDR_SECTORES", "buy_hold",
    "cartera_fija", "fechas_control", "metricas", "momentum_sectorial", "precio_en", "precio_ejecucion",
    "sesenta_cuarenta", "sesenta_cuarenta_europeo", "simular",
    "uno_n", "vista_senal", "vivo",
]
