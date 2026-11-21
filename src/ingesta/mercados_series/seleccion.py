"""Selección del Tema 1 (paso 3 de la descarga completa): aplica D1–D9 y E1–E3/E6 y saca la lista curada.

Lee SOLO las tablas de metadatos del paso 2 (``results/ingesta/mercados_series/tablas/``) y la
configuración del tema; no toca la base, el crudo ni ``D:``. Las salidas llevan solo metadatos,
nunca valores de las series.

**Entrada.** ``inventario_series.csv``, ``inventario_precios.csv``, ``fiabilidad_c.csv``,
``redundancia_pares.csv``, ``redundancia_conceptos.csv``, ``redundancia_bm_weo.csv`` y
``redundancia_etf.csv`` (``tickers_sensibilidad.csv`` solo se cita: D10 sigue abierta), más
``catalogo_series.yaml`` (``estado`` y ``duplicado_de``), ``publicaciones.yaml`` (publicadores del
mercado diario) y ``universo.yaml`` (instrumentos sin fichero de precios).

**Reglas de las series**, en este orden (la primera que decide manda; cada una es una función pura):

1. **D2 · nivel D** (``fuera_por_nivel``): sin fecha de publicación → ``fuera``. Hoy no hay ninguna.
2. **D3/D9 · alcance estricto** (``decision_bm_weo``): una serie del Banco Mundial o del WEO fuera de
   G7 + China (+ los agregados de D3, que hoy no están en la base) → ``fuera``.
3. **D4 · proyecciones** (``es_proyeccion``): SEP y horizontes ``.PROY.`` del WEO →
   ``proyecciones`` (tabla aparte, fuera de la base curada).
4. **Catálogo**: ``estado = duplicada`` → ``alias`` de su ``duplicado_de`` (``alias_catalogo``). Las
   ``retirada`` y ``capada`` conservan su estado y siguen por las reglas de abajo.
5. **D9 · duplicada con mayor frecuencia** (``decision_bm_weo``): Banco Mundial o WEO con el mismo
   concepto y país en OCDE, FRED, Eurostat o BCE a mayor frecuencia → ``alias`` de la mejor de
   ellas por E1.
6. **E3 · versiones de Eurostat** (``alias_e3``). Por familia (HICP, ESI, PIB, paro) y zona:
   - HICP: se queda ``HICP_EMP`` (empalmado v1→v2 por fecha de publicación: la única versión con
     toda la historia y el dato vigente); ``prc_hicp_manr`` (ECOICOP v1, retirada en 2026) y
     ``prc_hicp_minr`` (ECOICOP v2, desde 2026) pasan a alias de la empalmada del mismo país.
   - Zona euro: ``EA`` es el agregado de composición cambiante (el oficial de cada fecha);
     ``EA20`` y ``EA21`` son composiciones fijas y pasan a alias de ``EA``. Si una familia no tiene
     ``EA`` (ESI y paro), se queda la composición fija de mejor clave E1 y el motivo lo dice (la
     ``EA`` va a ``descargas_3b.csv``). ``EU27_2020`` es otra zona (la UE): no es versión de nada.
   Los pares Eurostat–Eurostat no pasan por la correlación: los decide E3.
7. **D8 · alias por correlación** (``aristas_admisibles`` + ``alias_estrella``): pares de
   ``redundancia_pares.csv`` con |Pearson| >= 0,95 en la base de ``base_correlacion`` (la diaria
   o la semanal, la mayor), |Spearman| >= 0,90, >= 5 años de solape y sin ``outlier_dominado``
   (``redundancia.aristas_alias``); regla en estrella (``redundancia.contar_alias``): solo es
   alias la serie con par DIRECTO con el canónico de su componente. Antes se quitan las aristas
   que no pueden ser alias (``motivo_bloqueo``):
   - **E2**: dos plazos de una misma curva de la misma fuente (``ust:PAR.*``, ``fred:DGS*``,
     ``GS*``, ``DTB*``, ``DFII*``, curvas del BCE, BoE, MoF, BoC, rendimientos y VIX de Yahoo…)
     nunca son alias: la curva entera se queda. Extensión (interpretación): tampoco dos plazos
     DISTINTOS de fuentes distintas (``fred:DGS10`` ~ ``ust:PAR.7Y``), que no son la misma serie.
   - Dos series con concepto conocido y distinto (``redundancia.concepto_de``: otro país, otra
     medida, otro diferencial) no son alias.
   - Dos series de otra clase de dato (regla de cambios distinta en ``redundancia_pares``:
     rentabilidades frente a un nivel, como ``ff:F3D.Mkt-RF`` ~ ``yf:^NYA``) no son alias.
   - Otra medida del tipo (``medida_tipo``): letras en **base descuento** (``DTB*``, ``TB3MS``),
     **vencimiento constante o par** (``DGS*``, ``GS*``, ``ust:PAR.*``) y **rendimientos de Yahoo**
     (``^IRX``, ``^FVX``, ``^TNX``, ``^TYX``: cierre del mismo día, H.15 se ve en t+1) nunca son
     alias entre sí. Así cada plazo de la curva oficial tiene por canónico H.15 (``fred:DGS*``) y
     ``ust:PAR.*`` es alias suyo cuando el plazo coincide.
   - Dentro de una misma fuente solo son alias las **versiones de una misma serie** (mismo
     concepto en ``redundancia_pares``, mismo concepto por regla o mismo plazo); el resto de pares
     de la misma fuente (``PAYEMS`` ~ ``USPRIV``, ``^GSPC`` ~ ``^RUI``) no.
8. **Grupos de concepto** (``alias_conceptos``, ``redundancia_conceptos.csv``): todos tienen
   canónico E1 (columna ``canonico``). Si el grupo está **confirmado** (todos sus pares medidos,
   correlación mínima >= 0,95 y >= 5 años de solape) pasan a alias del canónico solo los miembros
   de **menor frecuencia** que él, o los anuales entre sí (``destino_concepto_valido``: si el canónico
   está bloqueado por E2 o por la medida, el siguiente por E1): los de la misma frecuencia los mide
   D8 (con Spearman) y una de mayor frecuencia perdería información. Dos fuentes académicas de
   frecuencias distintas (``ff:F3M.*`` y ``ff:F3D.*``) se quedan las dos. La tabla de conceptos no da
   Spearman: la identidad la fija la regla de nombre o id. El resto de miembros se queda con el
   canónico marcado (validación).
9. El resto → ``queda`` (``unica`` si no tiene pareja; ``canonico`` si es el canónico de un grupo).
10. **D1 manda sobre E1** (``historia_previa``): si el alias es visible antes de ``CORTE_D1`` y su
    destino final no, no se hace alias: los dos quedan y el alias lleva ``rol = 'historia_previa'`` y
    ``completa_a = <destino>``. Se recorre por profundidad de la cadena, así la versión que elige E3
    nunca acaba como alias de una serie que no cumple D1 (``HICP_EMP.EA`` frente al HICP del BCE,
    visible solo desde 2026). Fuera de ese caso no cambia nada: DFF → EFFR o ``gw:M.tbl`` → TB3MS siguen
    como alias: solo aportan historia anterior a 2000 (fuera de D1), que se conserva en la base de trabajo
    (``get_serie(..., base="trabajo")``); la base curada sirve el canónico y la tabla de alias solo lleva metadatos.
11. **Cadenas** (``resolver_cadenas``): todo ``alias_de`` apunta a una serie que ``queda`` (A → B → C
    se reescribe A → C). Si el destino no queda (fuera o proyección), la serie se queda.

``rol`` resume la decisión: ``canonico``, ``unica``, ``validacion``, ``historia_previa``, ``alias``,
``fuera`` o ``proyeccion``. ``nota`` lleva las notas fijas de ``NOTAS_SERIES``.

**E1 · canónico** (``clave_e1``, ``elegir_canonico``): mejor nivel de fecha (A > B > C), más
historia visible (``pub_desde`` más antiguo), mayor frecuencia, fuente oficial antes que derivada o
copia (``calculo_propio``, ``datahub``, ``goyal_welch`` o método ``derivada``) y menos huecos desde
2000; a igualdad, el id. ``canonico_dudoso = True`` (en el canónico y en sus alias) si los dos
primeros empatan en nivel y ``pub_desde``, o si otro miembro de peor nivel tiene más de
``MARGEN_HISTORIA_DIAS`` días más de historia (la regla cambia historia por nivel).

**Anotaciones** (no echan a nadie):

- **D1** (``desde_2000``, ``desde_2000_exacto``, del inventario): una serie que empieza después
  de 2000 se queda si es única; si además es alias, sale como alias.
- **D2** (``tratamiento_fecha``), sobre la ventana desde 2000 del ``02`` (``ventana_d2``: el
  ``veredicto_desde_2000``, con «fiable» y «con margen» de reglas con menos de
  ``inventario.MIN_COMPARACIONES`` comparaciones pasados a «no medible»):
  - entran sin aviso «exacta», «sin riesgo», «fiable», «fiable con margen» y «verificada sin medir»;
  - «no fiable»: entra con ``aviso_fecha = 'no fiable'`` y ``tramo_conservador_antes_de =
    fiable_desde`` (``'toda'`` si no hay tramo fiable); la regla del tramo la define el
    preprocesado (E5);
  - «no medible»: entra con ``aviso_fecha = 'no medible'`` y ``regla_conservadora = <grupo>``
    (``grupo_no_medible``: ``mercado_diario``, ``banco_mundial``, ``macro_eurostat_bce_bis``,
    ``academicas``, ``otras_fred``; los mismos grupos que el ``02``);
  - «ver componentes» (derivadas ``deriv:A-B``): el peor trato de sus componentes.
- **E6** (``frontera``): ``tema2`` o ``tema4`` (provisional), de ``posible_frontera``.

**Tickers** (``seleccionar_precios``). D10 sigue ABIERTA: ningún ticker sale por fecha de inicio
ni por volumen (la elegibilidad se aplica punto a punto en la Fase 4). Solo se marcan
``desde_2000``/``desde_2007``/``desde_2016`` (primera sesión <= 2 de enero del año siguiente, como
D1), ``con_volumen`` (``volumen_aplica``: acciones, ETF, ETP, fondos, futuros y cripto; índices,
divisas y volatilidad no tienen volumen en Yahoo), ``deslistado`` y ``alias_etf`` (informativo):
grupos de ``redundancia_etf.csv`` con correlación >= 0,98 y el mismo ``bucket`` (alias del de más
historia) y pares UCITS (el UCITS es alias del ETF de EE. UU., pero los dos se quedan: el UCITS es
el invertible para un minorista de la UE). Fuera solo los ficheros **truncados** (menos de
``MIN_SESIONES`` sesiones con cierre: re-descarga completa en el 3b; un truncado no cuenta como
deslistado). ``aviso = 'serie sospechosa'`` (``serie_sospechosa`` de ``eda_precios.csv`` o la misma
regla: más de 20 saltos sin split o más de un 40 % de cierres repetidos) se queda con aviso y fila en
el 3b. Las acciones llevan ``frontera = 'tema3'`` (universo de empresas común con el Tema 3).
**Tickers reutilizados del S&P 500** (paso 3b-1, ``cobertura_tramos_sp500``): un ticker del S&P 500
histórico (``constituyentes/sp500.parquet``) cuyo fichero no solapa con NINGUNO de sus tramos de
pertenencia, o es de una clase que no puede ser una acción del índice (``CLASES_NO_MIEMBRO``: GR es un
fondo), se queda con ``aviso = 'ticker reutilizado: el fichero no es el miembro del S&P'`` (AT: un ETF de
ARCX desde 2026-09-17, no Alltel; DWD, GP, LU...).
**Avisos del 3b-2**: los instrumentos del universo que Yahoo empieza más de 30 días después de su lanzamiento
(``historia_recortada``) llevan ``aviso = 'historia recortada por Yahoo: faltan N días desde el lanzamiento'``; los
alias UCITS con correlación semanal < 0,9 con su ETF de EE. UU. (``ucits_poco_correlados``), ``AVISO_UCITS``; y los
ficheros rotos verificados a mano (``SOSPECHOSAS_VERIFICADAS``: IBTS.L) son serie sospechosa.

**Decisiones de cierre del paso 3** (``PLAN_DESCARGA.md``):

- **F3 · Q1 = solo Yahoo** (``aplicar_f3``): en ``descargas_3b.csv`` la columna ``estado`` dice
  ``pendiente`` o ``limitacion_declarada``; las filas que dependían de Q1 (deslistados, sospechosas,
  supervivencia, aperturas) y los instrumentos que Yahoo no sirve (``SIN_YAHOO``) pasan a
  ``limitacion_declarada`` con ``prioridad = 'no se descarga'``. Las sospechosas siguen «queda» con
  ``aviso = 'serie sospechosa; limitación declarada (F3)'``.
- **F4 · empates** (``UNICAS_F4``, ``DUDOSOS_RESUELTOS_F4``): ``ecb:DFR``, ``ecb:MRO``,
  ``bis:WS_CBPOL.M.XM`` y ``ff:F3M.Mkt-RF`` no se agrupan con nadie (únicas); el grupo de
  ``shiller:P`` (``datahub:SP500_MENSUAL`` es copia) deja de ser dudoso; el resto de dudosos se
  acepta con E1 y su ``motivo_dudoso`` empieza por «aceptado E1 (F4)».

**Salidas**: ``config/lista_curada.yaml`` (entrada del paso 4; una línea por entrada, sin campos vacíos
ni ``false``) y, en ``tablas/``,
``seleccion_series.csv``, ``seleccion_precios.csv``, ``seleccion_resumen.csv`` (decisión × fuente y
decisión × regla) y ``descargas_3b.csv`` (lo que falta por descargar, con prioridad y motivo).

Orden: ``python -m ingesta.mercados_series.seleccion [--tablas DIR] [--lista RUTA]``.
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ingesta.comun.rutas import resultados_dir
from ingesta.mercados_series import redundancia as red

TEMA = "mercados_series"
RUTA_LISTA = Path(__file__).resolve().parent / "config" / "lista_curada.yaml"

# --- Parámetros (decisiones aprobadas) -----------------------------------------------------------
FECHA_D = "2026-11-17"                   # D1–D10 cerradas (D10 abierta a propósito)
FECHA_E = "2026-11-19"                   # E1–E7 aprobadas tal como se proponen
ULTIMO_REFRESCO = "2026-10-14"
UMBRAL_ALIAS = 0.95                      # D8 (Spearman: umbral - redundancia.MARGEN_SPEARMAN = 0,90)
SOLAPE_ALIAS = 5.0                       # D8: años
UMBRAL_ETF = red.UMBRAL_ETF              # 0,98
MIN_SESIONES = 20
MARGEN_HISTORIA_DIAS = 365               # E1: «más historia» que hace dudar a la regla
CORTE_D1 = pd.Timestamp("2001-01-02")

DECISIONES = ("queda", "alias", "fuera", "proyecciones")
NIVEL_ORDEN = {"A": 0, "B": 1, "C": 2, "D": 3}
ORDEN_FRECUENCIA = {"diaria": 0, "semanal": 1, "mensual": 2, "trimestral": 3, "anual": 4}
FUENTES_COPIA = ("calculo_propio", "datahub", "goyal_welch")
VENTANAS_ENTRAN = ("exacta", "sin riesgo", "fiable", "fiable con margen", "verificada sin medir")

# Grupos «no medible» de D2 (los del notebook 02, sección 3)
FUENTES_MERCADO = ("bce_curvas", "ust_curva", "mof_jgb", "boe_curvas", "boc_curva", "boc", "boj", "bundesbank",
                   "rba")
FUENTES_ACADEMICAS = ("ken_french", "goyal_welch", "shiller", "datahub", "ofr_fsi")
GRUPOS_NO_MEDIBLE = ("mercado_diario", "banco_mundial", "macro_eurostat_bce_bis", "academicas", "otras_fred")

CLASES_CON_VOLUMEN = ("accion", "etf", "etp", "fondo", "futuro", "cripto")

COLUMNAS_SERIES = ["id", "fuente", "frecuencia", "estado", "nivel_fecha", "pub_desde", "desde_2000",
                   "desde_2000_exacto", "decision", "rol", "regla", "motivo", "alias_de", "completa_a", "canonico",
                   "canonico_dudoso", "motivo_dudoso", "aviso_fecha", "regla_conservadora",
                   "tramo_conservador_antes_de", "frontera", "nota"]
COLUMNAS_PRECIOS = ["id", "proveedor", "clase", "bucket", "en_universo", "desde", "hasta", "sesiones", "decision",
                    "regla", "motivo", "alias_de", "tipo_alias", "aviso", "frontera", "desde_2000", "desde_2007",
                    "desde_2016", "volumen_aplica", "con_volumen", "truncado", "deslistado"]
# Notas fijas de series concretas (se copian a la lista curada)
NOTAS_SERIES = {"deriv:PIB_REAL_USA_VINTAGES": "historia_previa 1965–1991: vintages exactos del RTDSM (PNB)"}
# F4 (decisión del usuario, cierre del paso 3): series que no se agrupan con nadie (quedan como únicas):
# DFR y MRO son tipos distintos (facilidad de depósito y operaciones principales); el tipo oficial del BIS
# para la zona euro es uno u otro según el periodo (en la duda, única); Fama-French mensual y diario se
# quedan los dos (el mensual es el oficial de su frecuencia).
UNICAS_F4 = ("ecb:DFR", "ecb:MRO", "bis:WS_CBPOL.M.XM", "ff:F3M.Mkt-RF")
# F4: empates resueltos a mano (sin canonico_dudoso en su grupo): datahub:SP500_MENSUAL es copia de Shiller
DUDOSOS_RESUELTOS_F4 = ("shiller:P",)
NOTA_DUDOSO_F4 = "aceptado E1 (F4)"
# F3 (decisión del usuario): Q1 = solo Yahoo; no se paga ninguna fuente
MOTIVO_F3 = "solo Yahoo (F3): limitación declarada; sesgo de supervivencia medido en la sonda"
AVISO_SOSPECHOSA = "serie sospechosa; limitación declarada (F3)"
# Instrumentos del universo que Yahoo no sirve (README · Deudas pendientes; notas de universo.yaml)
SIN_YAHOO = {"yf:^V2TX": "VSTOXX no está en Yahoo", "yf:AIGA.L": "Yahoo solo devuelve una vela (ticker sin historia)"}
# Serie de precios sospechosa (ticker reciclado o datos basura; misma regla que eda.py de B2)
SOSPECHOSA_SALTOS = 20                   # más de N saltos sin split
SOSPECHOSA_PCT_REPETIDOS = 40.0          # más de este % de cierres repetidos
COLUMNAS_3B = ["id", "tipo", "fuente", "estado", "prioridad", "motivo", "clase", "bucket", "detalle", "depende_de"]


def _vacio(v: Any) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and v == "") or v is pd.NaT


# --- D2 · fecha ----------------------------------------------------------------------------------
def ventana_d2(inv: pd.DataFrame, fia: pd.DataFrame, min_comparaciones: int | None = None) -> pd.Series:
    """Veredicto en la ventana desde 2000 del ``02``: ``veredicto_desde_2000``, salvo que «fiable» o «fiable
    con margen» de una regla con menos de ``MIN_COMPARACIONES`` comparaciones cuentan como «no medible»."""
    if min_comparaciones is None:
        from ingesta.mercados_series.inventario import MIN_COMPARACIONES
        min_comparaciones = MIN_COMPARACIONES
    poco = set(fia.loc[fia["n_comparaciones"] < min_comparaciones, "regla"])
    v = inv["veredicto_desde_2000"].fillna("no medible").astype(str)
    cambia = inv["clave_regla"].isin(poco) & v.isin(["fiable", "fiable con margen"])
    return v.where(~cambia, "no medible")


def grupo_no_medible(fuente: str, clave_regla: str | None, publicadores: Iterable[str] = ()) -> str:
    """Grupo de la regla conservadora de una serie «no medible» (D2): el tipo de dato del ``02``."""
    if (clave_regla and clave_regla in set(publicadores)) or fuente in FUENTES_MERCADO:
        return "mercado_diario"
    if fuente == "worldbank":
        return "banco_mundial"
    if fuente in ("eurostat", "bce", "bis"):
        return "macro_eurostat_bce_bis"
    if fuente in FUENTES_ACADEMICAS:
        return "academicas"
    return "otras_fred"


def fuera_por_nivel(nivel: str | None) -> bool:
    """D2: nivel D (sin fecha de publicación) → fuera."""
    return str(nivel) == "D"


def tratamiento_fecha(ventana: str, fiable_desde: str | None, grupo: str | None) -> dict[str, str | None]:
    """D2 para una serie: ``aviso_fecha``, ``regla_conservadora`` y ``tramo_conservador_antes_de``.

    «no fiable» → tramo conservador antes de ``fiable_desde`` (``'toda'`` si no hay tramo fiable);
    «no medible» → aviso y la regla conservadora de su ``grupo``; el resto de veredictos que entran, sin nada.
    """
    out: dict[str, str | None] = {"aviso_fecha": None, "regla_conservadora": None, "tramo_conservador_antes_de": None}
    if ventana == "no fiable":
        out["aviso_fecha"] = "no fiable"
        out["tramo_conservador_antes_de"] = "toda" if _vacio(fiable_desde) else str(fiable_desde)
    elif ventana == "no medible":
        out["aviso_fecha"] = "no medible"
        out["regla_conservadora"] = grupo or "otras_fred"
    elif ventana not in VENTANAS_ENTRAN:
        raise ValueError(f"veredicto de fecha desconocido: {ventana!r}")
    return out


_DERIVADA = re.compile(r"^deriv:([A-Z0-9]+)-([A-Z0-9]+)$")


def componentes_derivada(sid: str, ids: Iterable[str]) -> list[str]:
    """Componentes ``fred:A`` y ``fred:B`` de una derivada ``deriv:A-B`` que existan en ``ids``."""
    m = _DERIVADA.match(sid)
    if not m:
        return []
    ids = set(ids)
    return [f"fred:{c}" for c in m.groups() if f"fred:{c}" in ids]


def combinar_tratamientos(propio_fiable_desde: str | None, tratos: list[dict[str, str | None]]) -> dict[str, str | None]:
    """«ver componentes»: el peor trato de los componentes (aviso «no medible» y tramo más largo).

    Sin componentes en la base, la derivada se trata como «no medible» de ``otras_fred``."""
    if not tratos:
        return tratamiento_fecha("no medible", None, "otras_fred")
    avisos = [t["aviso_fecha"] for t in tratos if t["aviso_fecha"]]
    grupos = sorted({t["regla_conservadora"] for t in tratos if t["regla_conservadora"]})
    tramos = [t["tramo_conservador_antes_de"] for t in tratos if t["tramo_conservador_antes_de"]]
    if tramos and not _vacio(propio_fiable_desde):
        tramos.append(str(propio_fiable_desde))
    tramo = None
    if tramos:
        tramo = "toda" if "toda" in tramos else max(tramos)
    aviso = "no medible" if "no medible" in avisos else ("no fiable" if avisos else None)
    return {"aviso_fecha": aviso, "regla_conservadora": "; ".join(grupos) or None, "tramo_conservador_antes_de": tramo}


def anotar_fecha(inv: pd.DataFrame, fia: pd.DataFrame, publicadores: Iterable[str] = (),
                 min_comparaciones: int | None = None) -> pd.DataFrame:
    """D2 de todas las series (índice ``id``): ventana, aviso, regla conservadora y tramo."""
    publicadores = set(publicadores)
    ventana = ventana_d2(inv, fia, min_comparaciones)
    inv = inv.assign(_ventana=ventana.to_numpy()).set_index("id", drop=False)
    tratos: dict[str, dict[str, str | None]] = {}
    for sid, r in inv.iterrows():
        if r["_ventana"] == "ver componentes":
            continue
        g = grupo_no_medible(r["fuente"], r["clave_regla"] if not _vacio(r["clave_regla"]) else None, publicadores)
        tratos[sid] = tratamiento_fecha(r["_ventana"], r["fiable_desde"], g)
    for sid, r in inv[inv["_ventana"] == "ver componentes"].iterrows():
        comps = componentes_derivada(sid, tratos)
        tratos[sid] = combinar_tratamientos(r["fiable_desde"], [tratos[c] for c in comps])
    out = pd.DataFrame.from_dict(tratos, orient="index")
    out["ventana_d2"] = inv["_ventana"]
    return out.reindex(inv.index)


# --- E2 · plazos de curva -----------------------------------------------------------------------
_PLAZOS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((f, re.compile(p)) for f, p in (
    ("ust_par", r"^ust:PAR\.(?P<n>\d+)(?P<u>[MWY])$"),
    ("fred_dgs", r"^fred:DGS(?P<n>\d+)(?P<u>MO)?$"),
    ("fred_gs", r"^fred:GS(?P<n>\d+)(?P<u>M)?$"),
    ("fred_dtb", r"^fred:DTB(?P<n>\d+)(?P<u>WK|YR)?$"),
    ("fred_tb", r"^fred:TB(?P<n>\d+)(?P<u>MS)$"),
    ("fred_dfii", r"^fred:DFII(?P<n>\d+)$"),
    ("fred_breakeven", r"^fred:T(?P<n>\d+)YIE$"),
    ("ecb_yc", r"^ecb:YC\.(?P<c>\w+)\.(?P<n>\d+)(?P<u>[MY])$"),
    ("boe", r"^boe:(?P<c>\w+)\.(?P<n>\d+)(?P<u>[MY])$"),
    ("mof_jgb", r"^mof:JGB\.(?P<n>\d+)(?P<u>[MY])$"),
    ("boc_bond", r"^boc:BOND\.(?P<n>\d+)(?P<u>[MY])$"),
    ("boc_bd", r"^boc:BD\.CDN\.(?P<n>\d+)(?P<u>YR)\b"),
    ("rba", r"^rba:FCMYGBAG(?P<n>\d+)D$"),
))
_PLAZOS_FIJOS = {"yf:^IRX": ("yahoo_tesoro", 3.0), "yf:^FVX": ("yahoo_tesoro", 60.0),
                 "yf:^TNX": ("yahoo_tesoro", 120.0), "yf:^TYX": ("yahoo_tesoro", 360.0),
                 "yf:^VIX9D": ("vix", 0.3), "fred:VIXCLS": ("vix", 1.0), "yf:^VIX": ("vix", 1.0),
                 "yf:^VIX3M": ("vix", 3.0), "yf:^VIX6M": ("vix", 6.0), "yf:^VIX1Y": ("vix", 12.0),
                 "fred:VXOCLS": ("vxo", 1.0),
                 "gw:M.tbl": ("gw", 3.0)}


def plazo_curva(sid: str) -> tuple[str, float] | None:
    """``(curva, plazo en meses)`` si ``sid`` es un plazo de una curva conocida (E2); ``None`` si no."""
    if sid in _PLAZOS_FIJOS:
        return _PLAZOS_FIJOS[sid]
    for familia, patron in _PLAZOS:
        m = patron.match(sid)
        if not m:
            continue
        d = m.groupdict()
        n, u = float(d["n"]), (d.get("u") or ("Y" if familia in ("fred_dgs", "fred_gs", "fred_dfii", "fred_breakeven",
                                                                    "rba") else "M"))
        if familia == "fred_dtb" and not d.get("u"):
            u = "M"
        meses = {"M": n, "MO": n, "MS": n, "W": n * 12 / 52, "WK": n * 12 / 52, "Y": 12 * n, "YR": 12 * n}[u]
        curva = f"{familia}_{d['c']}" if d.get("c") else familia
        return curva, round(meses, 2)
    return None


_DESCUENTO = re.compile(r"^fred:(DTB\w+|TB\d+MS)$")
_CMT_PAR = re.compile(r"^(fred:(DGS\w+|GS\d+)|ust:PAR\..+)$")
RENDIMIENTOS_YAHOO = ("yf:^IRX", "yf:^FVX", "yf:^TNX", "yf:^TYX")


def medida_tipo(sid: str) -> str | None:
    """Medida de un tipo del Tesoro de EE. UU.: ``descuento`` (letras en base descuento: ``DTB*``, ``TB3MS``,
    ``gw:M.tbl``), ``cmt_par`` (vencimiento constante o par: ``DGS*``, ``GS*``, ``ust:PAR.*``) o ``yahoo``
    (índices de rendimiento de Cboe en Yahoo, cierre del mismo día). ``None`` si no es ninguna."""
    if sid in RENDIMIENTOS_YAHOO:
        return "yahoo"
    if _DESCUENTO.match(sid) or sid == "gw:M.tbl":
        return "descuento"
    if _CMT_PAR.match(sid):
        return "cmt_par"
    return None


def motivo_bloqueo(a: str, b: str, *, fuente_a: str, fuente_b: str, mismo_concepto: bool = False,
                   regla_a: str | None = None, regla_b: str | None = None) -> str:
    """Por qué el par ``a``–``b`` no puede ser alias (``''`` si puede): E2, E3, clase de dato, conceptos o
    misma fuente. ``regla_a``/``regla_b``: regla de cambios del paso 2 (``rentabilidad``, ``log``,
    ``diferencia``); si difieren, una es otra clase de dato (rentabilidades frente a un nivel, una tasa frente
    a un nivel) y no son alias."""
    if fuente_a == "eurostat" and fuente_b == "eurostat":
        return "E3: versiones de Eurostat (las decide E3)"
    if regla_a and regla_b and not _vacio(regla_a) and not _vacio(regla_b) and regla_a != regla_b:
        return f"otra clase de dato ({regla_a} frente a {regla_b})"
    ma, mb = medida_tipo(a), medida_tipo(b)
    if ma and mb and ma != mb:
        return f"otra medida del tipo ({ma} frente a {mb})"
    pa, pb = plazo_curva(a), plazo_curva(b)
    if pa and pb and pa[1] != pb[1]:
        return ("E2: dos plazos de una misma curva" if fuente_a == fuente_b or pa[0] == pb[0]
                else "E2: plazos distintos")
    ca, cb = red.concepto_de(a), red.concepto_de(b)
    if ca and cb and ca != cb:
        return "conceptos distintos"
    if fuente_a == fuente_b:
        version = bool(mismo_concepto) or (ca is not None and ca == cb) or (pa is not None and pb is not None)
        if not version:
            return "misma fuente y no es versión de la misma serie"
    return ""


def aristas_admisibles(pares: pd.DataFrame, candidatos: Iterable[str]) -> pd.DataFrame:
    """Pares de ``redundancia_pares`` entre ``candidatos`` que pueden ser alias (D8 + E2 + E3) y que pasan
    ``redundancia.aristas_alias`` (|Pearson| >= 0,95 en ``base_correlacion``, |Spearman| >= 0,90, 5 años)."""
    cand = set(candidatos)
    p = pares[pares["serie_a"].isin(cand) & pares["serie_b"].isin(cand)]
    if "outlier_dominado" in p:
        p = p[~p["outlier_dominado"].astype(bool)]
    if p.empty:
        return p.assign(motivo_bloqueo=pd.Series(dtype=object))
    mc = p["mismo_concepto"] if "mismo_concepto" in p else pd.Series(False, index=p.index)
    ra = p["regla_a"] if "regla_a" in p else pd.Series(None, index=p.index)
    rb = p["regla_b"] if "regla_b" in p else pd.Series(None, index=p.index)
    bloqueo = [motivo_bloqueo(a, b, fuente_a=fa, fuente_b=fb, mismo_concepto=bool(m), regla_a=x, regla_b=y)
               for a, b, fa, fb, m, x, y in zip(p["serie_a"], p["serie_b"], p["fuente_a"], p["fuente_b"], mc, ra, rb)]
    p = p.assign(motivo_bloqueo=bloqueo)
    p = p[p["motivo_bloqueo"] == ""]
    return red.aristas_alias(p, UMBRAL_ALIAS, SOLAPE_ALIAS)


# --- E1 · canónico ------------------------------------------------------------------------------
def es_derivada_o_copia(fuente: str, metodo: str | None = None) -> bool:
    """E1: derivada (cálculo propio) o copia de otra fuente (datahub, Goyal-Welch)."""
    return fuente in FUENTES_COPIA or metodo == "derivada"


def clave_e1(sid: str, meta: pd.DataFrame) -> tuple:
    """Orden E1: nivel, ``pub_desde``, frecuencia, oficial antes que derivada/copia, huecos, id."""
    r = meta.loc[sid]
    pub = pd.Timestamp(r["pub_desde"]) if not _vacio(r.get("pub_desde")) else pd.Timestamp.max
    huecos = float(r["pct_huecos_desde_2000"]) if not _vacio(r.get("pct_huecos_desde_2000")) else np.inf
    return (NIVEL_ORDEN.get(str(r["nivel_fecha"]), 9), pub, ORDEN_FRECUENCIA.get(str(r["frecuencia"]), 9),
            int(es_derivada_o_copia(str(r["fuente"]), r.get("metodo_publicacion"))), huecos, sid)


def elegir_canonico(miembros: Iterable[str], meta: pd.DataFrame) -> tuple[str, bool, str]:
    """``(canónico, dudoso, motivo)`` de un grupo por E1 (ver el módulo)."""
    orden = sorted(set(miembros), key=lambda s: clave_e1(s, meta))
    c = orden[0]
    kc = clave_e1(c, meta)
    motivos = []
    if len(orden) > 1 and clave_e1(orden[1], meta)[:2] == kc[:2]:
        # En tercera persona: el motivo se copia a todos los miembros del grupo (incluido orden[1])
        motivos.append(f"{c} y {orden[1]} empatan en nivel y historia (deciden la frecuencia, la fuente y el id)")
    for s in orden[1:]:
        k = clave_e1(s, meta)
        if k[0] > kc[0] and kc[1] != pd.Timestamp.max and (kc[1] - k[1]).days > MARGEN_HISTORIA_DIAS:
            anios = (kc[1] - k[1]).days / 365.25
            motivos.append(f"{s} tiene {anios:.1f} años más de historia con peor nivel "
                           f"({meta.at[s, 'nivel_fecha']} frente a {meta.at[c, 'nivel_fecha']})")
    return c, bool(motivos), "; ".join(motivos)


def alias_estrella(aristas: pd.DataFrame, meta: pd.DataFrame) -> tuple[dict[str, str], list[tuple[set[str], str, bool, str]]]:
    """D8 en estrella con el canónico E1: (``alias → canónico``, [(componente, canónico, dudoso, motivo)]).

    Reutiliza ``redundancia.contar_alias``: se le pasa como ``inicio`` el puesto E1 de cada serie, así su
    ``mas_historia`` elige el canónico E1 y la estrella es la misma lógica del paso 2."""
    if aristas.empty:
        return {}, []
    ids = sorted(set(aristas["serie_a"]) | set(aristas["serie_b"]), key=lambda s: clave_e1(s, meta))
    rango = pd.DataFrame({"inicio": range(len(ids)), "n_obs": 0}, index=ids)
    alias = red.contar_alias(aristas, rango, UMBRAL_ALIAS, SOLAPE_ALIAS, regla="estrella")
    grupos = []
    for g in red.componentes(zip(aristas["serie_a"], aristas["serie_b"])):
        c, dudoso, motivo = elegir_canonico(g, meta)
        grupos.append((g, c, dudoso, motivo))
    return alias, grupos


# --- E3 · versiones de Eurostat -----------------------------------------------------------------
_HICP = (("HICP_EMP", "empalmada", 0), ("prc_hicp_minr", "v2", 1), ("prc_hicp_manr", "v1", 2))
ZONA_EURO_CAMBIANTE = "EA"
ZONAS_EURO_FIJAS = ("EA20", "EA21", "EA19", "EA12")


def version_eurostat(sid: str) -> dict[str, Any] | None:
    """Familia, versión, zona y geo de un id de Eurostat (``None`` si no es de Eurostat)."""
    if not sid.startswith("eurostat:"):
        return None
    cuerpo = sid.split(":", 1)[1]
    dataset, geo = cuerpo.split(".", 1)[0], cuerpo.rsplit(".", 1)[-1]
    familia, version, rango = dataset, "unica", 0
    for prefijo, v, k in _HICP:
        if dataset == prefijo:
            familia, version, rango = "hicp", v, k
    zona = ZONA_EURO_CAMBIANTE if geo in (ZONA_EURO_CAMBIANTE, *ZONAS_EURO_FIJAS) else geo
    return {"familia": familia, "version": version, "rango_version": rango, "zona": zona, "geo": geo,
            "cambiante": geo == ZONA_EURO_CAMBIANTE}


def alias_e3(ids: Iterable[str], meta: pd.DataFrame) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """E3: ``(alias → (preferida, motivo)``, familias de la zona euro sin ``EA`` cambiante)``.

    En cada familia × zona se queda la versión preferida (HICP empalmado; ``EA`` cambiante antes que
    composiciones fijas; luego E1) y el resto pasa a alias de ella."""
    grupos: dict[tuple[str, str], list[str]] = {}
    info = {}
    for s in ids:
        v = version_eurostat(s)
        if v:
            info[s] = v
            grupos.setdefault((v["familia"], v["zona"]), []).append(s)
    alias, sin_ea = {}, []
    for (familia, zona), miembros in sorted(grupos.items()):
        orden = sorted(miembros, key=lambda s: (info[s]["rango_version"], not info[s]["cambiante"], clave_e1(s, meta)))
        pref = orden[0]
        if zona == ZONA_EURO_CAMBIANTE and not info[pref]["cambiante"]:
            sin_ea.append(familia)
        for s in orden[1:]:
            partes = []
            if info[s]["version"] != info[pref]["version"]:
                partes.append(f"versión {info[s]['version']} del HICP (se queda la {info[pref]['version']})")
            if info[s]["geo"] != info[pref]["geo"]:
                partes.append(f"zona {info[s]['geo']} (se queda {info[pref]['geo']}"
                              + (", composición cambiante)" if info[pref]["cambiante"]
                                 else ", sin EA de composición cambiante en la base)"))
            alias[s] = (pref, "E3: " + "; ".join(partes or ["versión de la misma serie"]))
    return alias, sorted(set(sin_ea))


# --- D9 · Banco Mundial y WEO -------------------------------------------------------------------
def decision_bm_weo(fila: Mapping[str, Any]) -> tuple[str, str, list[str]] | None:
    """D3/D9 de una fila de ``redundancia_bm_weo``: ``(decisión, motivo, destinos)`` o ``None`` si no decide.

    Fuera del alcance estricto → ``fuera``; proyección → la decide D4; duplicada con una serie de mayor
    frecuencia → ``alias`` (destinos: ``series_mayor_frecuencia``)."""
    if not bool(fila["en_alcance_estricto"]):
        return "fuera", f"D9: país {fila['pais']} fuera del alcance estricto (G7 + China)", []
    if bool(fila["es_proyeccion"]):
        return None
    if bool(fila["duplica_con_mayor_frecuencia"]):
        destinos = [s.strip() for s in str(fila["series_mayor_frecuencia"]).split(";") if s.strip()]
        return "alias", "D9: duplica una serie de mayor frecuencia", destinos
    return None


# --- Grupos de concepto -------------------------------------------------------------------------
def concepto_confirmado(fila: Mapping[str, Any], umbral: float = UMBRAL_ALIAS, solape: float = SOLAPE_ALIAS) -> bool:
    """Todos los pares medidos, correlación mínima >= ``umbral`` y solape mínimo >= ``solape`` años."""
    try:
        return (int(fila["n_pares_medidos"]) == int(fila["n_pares"]) > 0 and float(fila["corr_min"]) >= umbral
                and float(fila["solape_min_anios_par"]) >= solape)
    except (TypeError, ValueError):
        return False


def destino_concepto_valido(s: str, d: str, meta: pd.DataFrame) -> bool:
    """``s`` puede ser alias de ``d`` en un grupo de concepto confirmado: ``s`` de menor frecuencia que ``d`` (o
    dos anuales), sin bloqueo de ``motivo_bloqueo`` (E2, medida del tipo, conceptos) y sin ser dos fuentes
    académicas de frecuencias distintas (los factores mensuales y diarios de Ken French se quedan los dos)."""
    fs = ORDEN_FRECUENCIA.get(str(meta.at[s, "frecuencia"]), 9)
    fd = ORDEN_FRECUENCIA.get(str(meta.at[d, "frecuencia"]), 9)
    if not (fs > fd or fs == fd == ORDEN_FRECUENCIA["anual"]):
        return False
    a, b = str(meta.at[s, "fuente"]), str(meta.at[d, "fuente"])
    if a in FUENTES_ACADEMICAS and b in FUENTES_ACADEMICAS and fs != fd:
        return False
    return motivo_bloqueo(s, d, fuente_a=a, fuente_b=b, mismo_concepto=True) in (
        "", "E3: versiones de Eurostat (las decide E3)")


def alias_conceptos(conc: pd.DataFrame, meta: pd.DataFrame, candidatos: Iterable[str]
                    ) -> tuple[dict[str, tuple[str, str]], list[tuple[set[str], str, bool, str, int]]]:
    """Canónico E1 de cada grupo de concepto entre ``candidatos`` y alias de los confirmados.

    Devuelve (``alias → (canónico, motivo)``, [(miembros, canónico, dudoso, motivo, grupo)]). Solo pasa a
    alias un miembro de MENOR frecuencia que el canónico, o dos anuales: los pares de la misma frecuencia
    (salvo las anuales) los mide D8 con Spearman en ``redundancia_pares`` y los decide la estrella."""
    cand = set(candidatos)
    alias, grupos = {}, []
    for _, f in conc.iterrows():
        miembros = {m.strip() for m in str(f["miembros"]).split(";") if m.strip() in cand}
        if len(miembros) < 2:
            continue
        c, dudoso, motivo = elegir_canonico(miembros, meta)
        grupos.append((miembros, c, dudoso, motivo, int(f["grupo"])))
        if not concepto_confirmado(f):
            continue
        orden = sorted(miembros, key=lambda x: clave_e1(x, meta))
        for s in sorted(miembros - {c}):
            if s in alias:
                continue
            destino = next((d for d in orden if d != s and destino_concepto_valido(s, d, meta)), None)
            if destino is None:
                continue
            alias[s] = (destino, f"mismo concepto ({f['concepto']}, {f['pais']}; grupo {int(f['grupo'])}, "
                                 f"correlación mínima {float(f['corr_min']):.3f})")
    return alias, grupos


# --- D1 · historia previa -----------------------------------------------------------------------
def historia_previa(decision: Mapping[str, str], alias_de: Mapping[str, str], desde_2000: Mapping[str, bool]
                    ) -> dict[str, str]:
    """D1 manda sobre E1: ``alias → serie a la que completa`` para los alias visibles antes de ``CORTE_D1``
    cuyo destino final no lo es. Esos alias NO se hacen: los dos quedan y el alias se marca
    ``rol = 'historia_previa'`` (``completa_a`` = el destino).

    Se recorre por profundidad de la cadena (primero los alias directos de una serie que queda): así una
    versión elegida por E3 que vuelve a «queda» recoge a sus propias versiones y nunca acaba como alias
    de una serie que no cumple D1."""
    def destino(s: str, revertidas: Mapping[str, str]) -> tuple[str | None, int]:
        visto, x = {s}, alias_de.get(s)
        while x is not None and decision.get(x) == "alias" and x not in revertidas and x not in visto:
            visto.add(x)
            x = alias_de.get(x)
        return (None if x in visto else x), len(visto)

    alias = [s for s, d in decision.items() if d == "alias"]
    revertidas: dict[str, str] = {}
    for s in sorted(alias, key=lambda x: (destino(x, {})[1], x)):
        r, _ = destino(s, revertidas)
        if r is not None and bool(desde_2000.get(s)) and not bool(desde_2000.get(r)):
            revertidas[s] = r
    return revertidas


# --- Cadenas ------------------------------------------------------------------------------------
def resolver_cadenas(decision: dict[str, str], alias_de: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Reescribe ``alias_de`` hasta una serie que ``queda``; devuelve (``alias → raíz``, ``alias → aviso``).

    Si la raíz no queda (fuera, proyección o falta) o hay un ciclo, la serie pasa a ``queda`` (aviso)."""
    raiz, aviso = {}, {}
    for s, d in decision.items():
        if d != "alias":
            continue
        visto, x = [s], alias_de.get(s)
        while x is not None and decision.get(x) == "alias" and x not in visto:
            visto.append(x)
            x = alias_de.get(x)
        if x is None or x in visto or decision.get(x) != "queda":
            aviso[s] = f"alias de {alias_de.get(s)}, que no queda: se queda"
        else:
            raiz[s] = x
            if x != alias_de.get(s):
                aviso[s] = f"vía {' → '.join(visto[1:])}"
    return raiz, aviso


# --- Selección de series ------------------------------------------------------------------------
def _meta(inv: pd.DataFrame) -> pd.DataFrame:
    m = inv.set_index("id", drop=False)
    return m[~m.index.duplicated()]


def seleccionar_series(inv: pd.DataFrame, fia: pd.DataFrame, pares: pd.DataFrame, conc: pd.DataFrame,
                       bmw: pd.DataFrame, duplicado_de: Mapping[str, str] | None = None,
                       publicadores: Iterable[str] = (), min_comparaciones: int | None = None
                       ) -> tuple[pd.DataFrame, list[str]]:
    """Lista curada de series (``COLUMNAS_SERIES``) y familias de la zona euro sin ``EA`` cambiante (E3)."""
    meta = _meta(inv)
    duplicado_de = dict(duplicado_de or {})
    decision: dict[str, str] = {}
    regla: dict[str, str] = {}
    motivo: dict[str, str] = {}
    alias_de: dict[str, str] = {}
    canonico: dict[str, str] = {}
    dudoso: dict[str, str] = {}

    def decide(s: str, d: str, rg: str, mot: str, destino: str | None = None) -> None:
        decision[s], regla[s], motivo[s] = d, rg, mot
        if destino:
            alias_de[s] = destino

    # 1–3: nivel D, alcance estricto, proyecciones
    bm = bmw.set_index("serie") if len(bmw) else pd.DataFrame()
    pendientes_d9: dict[str, tuple[str, list[str]]] = {}
    for s, r in meta.iterrows():
        if fuera_por_nivel(r["nivel_fecha"]):
            decide(s, "fuera", "D2_nivel_D", "D2: nivel D (sin fecha de publicación)")
            continue
        fila_bm = bm.loc[s] if s in bm.index else None
        d9 = decision_bm_weo(fila_bm) if fila_bm is not None else None
        if d9 and d9[0] == "fuera":
            decide(s, "fuera", "D9_fuera_alcance", d9[1])
        elif bool(r["es_proyeccion"]):
            decide(s, "proyecciones", "D4_proyeccion", "D4: proyección (tabla aparte, fuera de la base curada)")
        elif str(r["estado"]) == "duplicada" and duplicado_de.get(s) in meta.index:
            decide(s, "alias", "catalogo_duplicada", f"catálogo: duplicada de {duplicado_de[s]}", duplicado_de[s])
        elif d9 and d9[0] == "alias":
            pendientes_d9[s] = (d9[1], [x for x in d9[2] if x in meta.index])
    libres = [s for s in meta.index if s not in decision]
    # 5: D9 duplicadas con mayor frecuencia → la mejor E1 de sus destinos
    for s, (mot, destinos) in pendientes_d9.items():
        if destinos:
            c = min(destinos, key=lambda x: clave_e1(x, meta))
            decide(s, "alias", "D9_mayor_frecuencia", f"{mot} ({', '.join(destinos)})", c)
    # 6: E3
    libres = [s for s in meta.index if s not in decision]
    e3, sin_ea = alias_e3(libres, meta)
    for s, (pref, mot) in e3.items():
        decide(s, "alias", "E3_version_eurostat", mot, pref)
    # 7: D8 en estrella con E2 (las de UNICAS_F4 no se agrupan con nadie)
    libres = [s for s in meta.index if s not in decision and s not in UNICAS_F4]
    aristas = aristas_admisibles(pares, libres)
    alias, componentes = alias_estrella(aristas, meta)
    directos = {}
    for a, b, base, pe in zip(aristas["serie_a"], aristas["serie_b"], aristas["base_correlacion"], aristas["pearson"]):
        directos[(a, b)] = directos[(b, a)] = (base, pe)
    for g, c, es_dudoso, mot_d in componentes:
        for s in g:
            canonico[s] = c
            if es_dudoso:
                dudoso[s] = mot_d
    for s, c in alias.items():
        base, pe = directos[(s, c)]
        decide(s, "alias", "D8_estrella", f"D8: |Pearson| {abs(pe):.3f} ({base}) con {c}, regla en estrella", c)
    # 8: grupos de concepto
    libres = [s for s in meta.index if s not in decision and s not in UNICAS_F4]
    al_c, grupos_c = alias_conceptos(conc, meta, libres)
    for miembros, c, es_dudoso, mot_d, _ in grupos_c:
        for s in miembros:
            canonico.setdefault(s, c)
            if es_dudoso and canonico[s] == c:
                dudoso.setdefault(s, mot_d)
    for s, (c, mot) in al_c.items():
        decide(s, "alias", "concepto_confirmado", mot, c)
    # 9: el resto se queda (destino de un alias del catálogo, D9 o E3 sin grupo propio: canónico)
    destinos = set(alias_de.values())
    for s in meta.index:
        if s not in decision:
            if canonico.get(s) == s or (s not in canonico and s in destinos):
                decide(s, "queda", "canonico", "queda: canónico E1 de su grupo")
            elif s in canonico:
                decide(s, "queda", "validacion", f"queda: mismo grupo que {canonico[s]} sin llegar a alias")
            else:
                decide(s, "queda", "unica", "queda: sin alias")
    # 10: D1 manda sobre E1 (historia previa) y cadenas
    rol: dict[str, str] = {}
    completa_a: dict[str, str] = {}
    previas = historia_previa(decision, alias_de, meta["desde_2000"].astype(bool).to_dict())
    for s, r in previas.items():
        decide(s, "queda", "historia_previa_d1", f"D1: visible antes de 2001 y {r} no: se quedan las dos "
               f"(completa a {r}; era {regla[s]}: {motivo[s]})")
        alias_de.pop(s, None)
        rol[s], completa_a[s] = "historia_previa", r
    raiz, aviso = resolver_cadenas(decision, alias_de)
    for s, txt in aviso.items():
        if s not in raiz:
            decide(s, "queda", "alias_sin_destino", f"{motivo[s]}; {txt}")
            alias_de.pop(s, None)
        else:
            motivo[s] = f"{motivo[s]} ({txt})"
    for s, x in raiz.items():
        alias_de[s] = x
    # F4: empates resueltos a mano; el resto de dudosos, aceptados con la regla E1
    for s in [s for s in dudoso if canonico.get(s) in DUDOSOS_RESUELTOS_F4 or s in DUDOSOS_RESUELTOS_F4]:
        dudoso.pop(s)
    for s in dudoso:
        dudoso[s] = f"{NOTA_DUDOSO_F4}: {dudoso[s]}"
    # el canónico dudoso se ve también en los alias que apuntan a él
    for s, x in alias_de.items():
        if decision[s] == "alias" and x in dudoso:
            dudoso.setdefault(s, dudoso[x])
    # todo alias tiene canónico: los de D9, E3 y el catálogo no salen de un grupo de correlación
    for s, x in alias_de.items():
        if decision[s] == "alias":
            canonico.setdefault(s, x)
    for s in list(motivo):
        if decision[s] == "alias" and not bool(meta.at[s, "desde_2000"]):
            motivo[s] += "; empieza después de 2000 (D1)"
        if s not in rol:
            rol[s] = {"alias": "alias", "fuera": "fuera", "proyecciones": "proyeccion"}.get(decision[s], regla[s])
    fechas = anotar_fecha(inv, fia, publicadores, min_comparaciones)
    filas = []
    for s, r in meta.iterrows():
        f = fechas.loc[s]
        filas.append({
            "id": s, "fuente": r["fuente"], "frecuencia": r["frecuencia"], "estado": r["estado"],
            "nivel_fecha": r["nivel_fecha"], "pub_desde": r["pub_desde"], "desde_2000": bool(r["desde_2000"]),
            "desde_2000_exacto": bool(r["desde_2000_exacto"]), "decision": decision[s], "rol": rol[s],
            "regla": regla[s], "motivo": motivo[s], "alias_de": alias_de.get(s) if decision[s] == "alias" else None,
            "completa_a": completa_a.get(s),
            "canonico": canonico.get(s), "canonico_dudoso": s in dudoso, "motivo_dudoso": dudoso.get(s),
            "aviso_fecha": f["aviso_fecha"], "regla_conservadora": f["regla_conservadora"],
            "tramo_conservador_antes_de": f["tramo_conservador_antes_de"],
            "frontera": r["posible_frontera"] if not _vacio(r.get("posible_frontera")) else None,
            "nota": NOTAS_SERIES.get(s),
        })
    out = pd.DataFrame(filas, columns=COLUMNAS_SERIES).sort_values("id", kind="mergesort").reset_index(drop=True)
    return out, sin_ea


# --- Tickers ------------------------------------------------------------------------------------
def marcas_inicio(desde: Any) -> dict[str, bool]:
    """``desde_2000``/``desde_2007``/``desde_2016``: primera sesión <= 2 de enero del año siguiente (D1)."""
    d = pd.Timestamp(desde) if not _vacio(desde) else None
    return {f"desde_{a}": bool(d is not None and d <= pd.Timestamp(f"{a + 1}-01-02")) for a in (2000, 2007, 2016)}


def alias_etf(etf: pd.DataFrame, umbral: float = UMBRAL_ETF, buckets: Mapping[str, str] | None = None
              ) -> dict[str, tuple[str, str]]:
    """``ticker → (alias de, tipo)`` de ``redundancia_etf``: grupos >= ``umbral`` (alias del de más historia)
    y pares UCITS (el UCITS, alias informativo de su ETF de EE. UU.).

    En los grupos el alias exige el mismo ``bucket`` del universo que el de más historia (``buckets``; un
    ticker sin bucket, fuera del universo, no lo impide): QUAL (factor) no es alias de SPY (renta variable).
    Los pares UCITS no lo exigen."""
    buckets = dict(buckets or {})
    out: dict[str, tuple[str, str]] = {}
    for _, f in etf.iterrows():
        miembros = [m.strip() for m in str(f["miembros"]).split(";")]
        if f["tipo"] == "grupo" and float(f["corr_min"]) >= umbral:
            inicios = [x.strip() for x in str(f["inicios"]).split(";")]
            orden = sorted(zip(inicios, miembros))
            ref = orden[0][1]
            for _, m in orden[1:]:
                bm, br = buckets.get(m) or "", buckets.get(ref) or ""
                if bm and br and bm != br:
                    continue
                out.setdefault(m, (ref, f"grupo {f['id']} (correlación >= {umbral:.2f})"))
        elif f["tipo"] == "ucits" and len(miembros) == 2:
            out.setdefault(miembros[1], (miembros[0], "ucits"))
    return out


def series_sospechosas(eda: pd.DataFrame | None) -> set[str]:
    """Tickers con ``serie_sospechosa`` en ``eda_precios.csv`` (B2); si la columna aún no está, la misma regla:
    más de ``SOSPECHOSA_SALTOS`` saltos sin split o más de un ``SOSPECHOSA_PCT_REPETIDOS`` % de cierres
    repetidos (``cierre_repetido / sesiones``)."""
    if eda is None or eda.empty:
        return set()
    if "serie_sospechosa" in eda:
        marca = eda["serie_sospechosa"].astype(str).str.lower().isin(["true", "1"])
    else:
        ses = pd.to_numeric(eda["sesiones"], errors="coerce").replace(0, np.nan)
        rep_pct = 100 * pd.to_numeric(eda["cierre_repetido"], errors="coerce").fillna(0) / ses
        marca = (pd.to_numeric(eda["saltos_sin_split"], errors="coerce").fillna(0) > SOSPECHOSA_SALTOS) | (
            rep_pct.fillna(0) > SOSPECHOSA_PCT_REPETIDOS)
    return set(eda.loc[marca, "ticker"].astype(str))


CLASE_YAHOO = {"EQUITY": "accion", "ETF": "etf", "INDEX": "indice", "FUTURE": "futuro", "CURRENCY": "divisa",
               "MUTUALFUND": "fondo", "ECNQUOTE": "otro"}


def clase_ticker(clase: Any, tipo_yahoo: Any) -> str:
    """Clase de un fichero de precios, de ``inventario_precios.csv``: la del universo (``clase``); si no está en el
    universo, la de su ``tipo_yahoo`` (``CLASE_YAHOO``; un tipo desconocido es ``otro``); sin ninguna,
    ``sin_clase``. El mismo criterio en ``seleccion_precios.csv`` y en ``eda_precios.csv``."""
    if not _vacio(clase) and str(clase):
        return str(clase)
    if not _vacio(tipo_yahoo) and str(tipo_yahoo):
        return CLASE_YAHOO.get(str(tipo_yahoo).upper(), "otro")
    return "sin_clase"


def clases_precios(pre: pd.DataFrame) -> dict[str, str]:
    """``ticker → clase`` (``clase_ticker``) de ``inventario_precios.csv``."""
    ty = pre["tipo_yahoo"] if "tipo_yahoo" in pre else pd.Series(None, index=pre.index)
    return {str(t): clase_ticker(c, y) for t, c, y in zip(pre["ticker"], pre["clase"], ty)}


# --- Tickers del S&P 500 reutilizados (paso 3b-1) -------------------------------------------------
#: Un ticker del S&P 500 histórico cuyo fichero de Yahoo no es el miembro: se queda (D10 abierta) con este aviso.
AVISO_REUTILIZADO = "ticker reutilizado: el fichero no es el miembro del S&P"
#: Clases que no pueden ser un miembro del S&P 500 (acciones ordinarias): el fichero es otro instrumento
#: con el mismo ticker aunque sus fechas solapen con el tramo (GR: un fondo de 2001 a 2018, no Goodrich).
CLASES_NO_MIEMBRO = ("etf", "etp", "fondo", "indice", "divisa", "futuro", "volatilidad", "cripto")
FECHA_CORTE = __import__("ingesta.mercados_series.corte", fromlist=["x"]).corte_vigente().date().isoformat()  # G2 (P07)


def ruta_tramos_sp500() -> Path:
    """``<corpus>/mercados_series/constituyentes/sp500.parquet`` (``fuentes.constituyentes.descargar_sp500``)."""
    from ingesta.comun.rutas import corpus_dir

    return corpus_dir(TEMA) / "constituyentes" / "sp500.parquet"


def cobertura_tramos_sp500(tramos: pd.DataFrame, pre: pd.DataFrame, clases: Mapping[str, str] | None = None,
                           corte: str = FECHA_CORTE) -> pd.DataFrame:
    """Una fila por tramo de pertenencia al S&P 500 con su fichero de Yahoo (sin red ni valores).

    ``tramos``: ``sp500.parquet`` (``ticker, alta, baja``; ``baja`` excluida, vacía si sigue: hasta ``corte``).
    ``pre``: ``inventario_precios.csv`` (``ticker, proveedor, desde, hasta``). Columnas: ``ticker``,
    ``ticker_yahoo`` (``BRK.B`` → ``BRK-B``), ``alta``, ``fin`` (excluido), ``tiene_fichero``, ``desde``,
    ``hasta``, ``solapa`` (el fichero cubre algún día del tramo), ``dias_tramo``, ``dias_cubiertos`` (días
    naturales) y ``reutilizado``: el ticker tiene fichero y este no es ningún miembro (no solapa con NINGUNO de
    sus tramos o es de una clase que no puede ser una acción del índice, ``CLASES_NO_MIEMBRO``). No se marcan
    los truncados (``es_truncado``: LEG y QRVO son la misma empresa, deslistada en 2026, y Yahoo solo guarda
    la última sesión; salen de la lista con su propio motivo) ni los instrumentos del universo (``en_universo``:
    su identidad la declara ``universo.yaml``; GLD es el ETF de oro del núcleo)."""
    from ingesta.mercados_series.proveedores.yahoo import ticker_yahoo_constituyente

    clases = dict(clases or {})
    yh = pre[pre["proveedor"] == "yahoo"].drop_duplicates("ticker").set_index("ticker")
    fin_abierto = pd.Timestamp(corte) + pd.Timedelta(days=1)
    t = tramos[["ticker", "alta", "baja"]].copy()
    t["ticker_yahoo"] = [ticker_yahoo_constituyente("sp500", x) for x in t["ticker"]]
    t["alta"] = pd.to_datetime(t["alta"])
    t["fin"] = pd.to_datetime(t["baja"]).fillna(fin_abierto).clip(upper=fin_abierto)
    t["tiene_fichero"] = t["ticker_yahoo"].isin(yh.index)
    desde = pd.to_datetime(t["ticker_yahoo"].map(yh["desde"]))
    hasta = pd.to_datetime(t["ticker_yahoo"].map(yh["hasta"]))
    t["desde"], t["hasta"] = desde.dt.strftime("%Y-%m-%d"), hasta.dt.strftime("%Y-%m-%d")
    t["dias_tramo"] = (t["fin"] - t["alta"]).dt.days.clip(lower=0)
    ini = pd.concat([desde, t["alta"]], axis=1).max(axis=1)
    fin = pd.concat([hasta + pd.Timedelta(days=1), t["fin"]], axis=1).min(axis=1)
    t["dias_cubiertos"] = (fin - ini).dt.days.where(t["tiene_fichero"], 0).fillna(0).clip(lower=0).astype(int)
    t["solapa"] = t["dias_cubiertos"] > 0
    no_miembro = t["ticker_yahoo"].map(lambda x: clases.get(x) in CLASES_NO_MIEMBRO)
    algun_solape = t.groupby("ticker_yahoo")["solapa"].transform("any")
    sesiones = pd.to_numeric(t["ticker_yahoo"].map(yh["sesiones"]), errors="coerce") if "sesiones" in yh else None
    excluido = pd.Series(False, index=t.index)
    if sesiones is not None:
        excluido |= sesiones.fillna(MIN_SESIONES) < MIN_SESIONES
    if "en_universo" in yh:
        excluido |= t["ticker_yahoo"].map(yh["en_universo"]).astype("boolean").fillna(False).astype(bool)
    t["reutilizado"] = t["tiene_fichero"] & ~excluido & (~algun_solape | no_miembro)
    return t[["ticker", "ticker_yahoo", "alta", "fin", "tiene_fichero", "desde", "hasta", "solapa", "dias_tramo",
              "dias_cubiertos", "reutilizado"]].reset_index(drop=True)


def tickers_reutilizados(cobertura: pd.DataFrame) -> dict[str, str]:
    """``ticker_yahoo → detalle`` (fichero y tramos del S&P) de los tramos con ``reutilizado``."""
    out: dict[str, str] = {}
    for tk, g in cobertura[cobertura["reutilizado"]].groupby("ticker_yahoo", sort=True):
        tramos = ", ".join(f"{a:%Y-%m-%d} a {f:%Y-%m-%d}" for a, f in zip(g["alta"], g["fin"]))
        out[str(tk)] = f"fichero {g['desde'].iloc[0]} a {g['hasta'].iloc[0]}; en el S&P 500: {tramos}"
    return out


def resumen_cobertura_sp500(cobertura: pd.DataFrame) -> pd.DataFrame:
    """Cobertura histórica del S&P 500 (``metrica, valor``): tramos con fichero que solapa, sin fichero, con
    fichero sin solape, de tickers reutilizados y % de días-tramo cubiertos (sin contar los reutilizados)."""
    c = cobertura
    dias = int(c["dias_tramo"].sum())
    abiertos = c["fin"] > pd.Timestamp(FECHA_CORTE)
    cubiertos = int(c.loc[~c["reutilizado"], "dias_cubiertos"].sum())
    filas = [
        ("tramos", len(c)),
        ("tramos_con_fichero", int(c["tiene_fichero"].sum())),
        ("tramos_con_fichero_que_solapa", int((c["tiene_fichero"] & c["solapa"]).sum())),
        ("tramos_con_fichero_sin_solape", int((c["tiene_fichero"] & ~c["solapa"]).sum())),
        ("tramos_sin_fichero", int((~c["tiene_fichero"]).sum())),
        ("tramos_ticker_reutilizado", int(c["reutilizado"].sum())),
        ("tickers_reutilizados", int(c.loc[c["reutilizado"], "ticker_yahoo"].nunique())),
        ("tramos_abiertos", int(abiertos.sum())),
        ("tramos_abiertos_con_fichero_que_solapa", int((abiertos & c["solapa"] & ~c["reutilizado"]).sum())),
        ("dias_tramo", dias),
        ("dias_tramo_cubiertos", cubiertos),
        ("pct_dias_tramo_cubiertos", round(100 * cubiertos / dias, 2) if dias else None),
    ]
    return pd.DataFrame(filas, columns=["metrica", "valor"], dtype=object)


# --- Avisos del 3b-2: historia recortada, alias UCITS con poca correlación, sospechosas verificadas ----------------
#: Un instrumento del universo que Yahoo empieza más de estos días después de su lanzamiento (``inicio_esperado``,
#: justETF) tiene la historia recortada (igual que ``proveedores.yahoo.HOLGURA_INICIO``).
HOLGURA_HISTORIA_DIAS = 30
AVISO_RECORTADA = "historia recortada por Yahoo: faltan {n} días desde el lanzamiento"
#: Un alias UCITS cuya correlación semanal con su ETF de EE. UU. no llega a esto lleva aviso (``redundancia_etf``).
UMBRAL_UCITS_SEMANAL = 0.9
AVISO_UCITS = "alias UCITS con correlación semanal baja con {etf} ({c} < {u})"
#: Ficheros que el EDA no marca (menos de 20 saltos) pero están rotos, verificados a mano (3b-2, 2026-11-20). El
#: resto de alias UCITS con poca correlación la explica la divisa: cotizan en GBP o GBp en Londres y su ETF en USD,
#: así que en un fondo de poca volatilidad (letras y bonos del Tesoro) la rentabilidad semanal es casi solo el tipo
#: de cambio (IBTM.L 0,5 e ITPS.L 0,4 desde 2010, ya sin saltos; IDTL.L, en USD, 0,94 con TLT).
SOSPECHOSAS_VERIFICADAS = {
    "IBTS.L": ("letras del Tesoro de 1 a 3 años con 32 sesiones de más de un 10 % desde 2010, velas a la mitad que "
               "se revierten al día siguiente en 2008 y un salto ×145 el 2009-01-02 sin split: fichero roto"),
}


def historia_recortada(pre: pd.DataFrame, universo: pd.DataFrame,
                       holgura: int = HOLGURA_HISTORIA_DIAS) -> dict[str, int]:
    """``ticker → días`` que faltan desde el lanzamiento: instrumentos del universo (``id_universo`` de
    ``inventario_precios``) cuyo fichero empieza más de ``holgura`` días después de su ``inicio_esperado``."""
    if universo is None or "inicio_esperado" not in universo or "id_universo" not in pre:
        return {}
    esperado = pd.to_datetime(universo.set_index("id")["inicio_esperado"])
    out = {}
    for t, u, d in zip(pre["ticker"], pre["id_universo"], pre["desde"]):
        e = esperado.get(u) if not _vacio(u) else None
        if e is None or pd.isna(e) or _vacio(d):
            continue
        n = int((pd.Timestamp(d) - e).days)
        if n > holgura:
            out[str(t)] = n
    return out


def ucits_poco_correlados(etf: pd.DataFrame, umbral: float = UMBRAL_UCITS_SEMANAL) -> dict[tuple[str, str], float]:
    """``(ucits, etf) → correlación semanal`` de los pares UCITS de ``redundancia_etf`` por debajo de ``umbral``
    (sin la semanal, la de su base)."""
    out: dict[tuple[str, str], float] = {}
    if etf is None or etf.empty:
        return out
    for _, f in etf[etf["tipo"] == "ucits"].iterrows():
        miembros = [m.strip() for m in str(f["miembros"]).split(";")]
        c = f.get("corr_semanal")
        c = float(c) if not _vacio(c) else float(f["corr_min"])
        if len(miembros) == 2 and c < umbral:
            out[(miembros[1], miembros[0])] = c
    return out


def es_truncado(sesiones: int) -> bool:
    """Fichero truncado (menos de ``MIN_SESIONES`` sesiones con cierre): sin datos útiles, se re-descarga entero.
    Un truncado no se cuenta como deslistado: su última sesión no dice nada de la salida."""
    return int(sesiones) < MIN_SESIONES


def seleccionar_precios(pre: pd.DataFrame, etf: pd.DataFrame, clases: Mapping[str, str] | None = None,
                        sospechosas: Iterable[str] = (), reutilizados: Mapping[str, str] | None = None,
                        recortados: Mapping[str, int] | None = None) -> pd.DataFrame:
    """Lista curada de ficheros de precios (``COLUMNAS_PRECIOS``). D10 abierta: fuera solo los truncados.

    ``aviso = 'serie sospechosa'`` (ticker reciclado o datos basura, ``series_sospechosas`` y
    ``SOSPECHOSAS_VERIFICADAS``): se queda con aviso. ``reutilizados`` (``tickers_reutilizados``: ticker del S&P 500
    cuyo fichero no es el miembro): se queda con ``AVISO_REUTILIZADO``. 3b-2: ``recortados``
    (``historia_recortada``) llevan ``AVISO_RECORTADA`` y los alias UCITS con correlación semanal < 0,9 con su ETF
    (``ucits_poco_correlados``), ``AVISO_UCITS``. Los avisos se unen con «; ». Las acciones llevan
    ``frontera = 'tema3'`` (universo de empresas común con el Tema 3)."""
    clases = dict(clases or {})
    sospechosas = set(sospechosas) | set(SOSPECHOSAS_VERIFICADAS)
    reutilizados = dict(reutilizados or {})
    recortados = dict(recortados or {})
    poca_corr = ucits_poco_correlados(etf)
    buckets = {str(k): v for k, v in zip(pre["ticker"], pre["bucket"]) if not _vacio(v)}
    alias = alias_etf(etf, buckets=buckets)
    filas = []
    for _, r in pre.iterrows():
        t = r["ticker"]
        clase = clases.get(t) or (r["clase"] if not _vacio(r.get("clase")) else "sin_clase")
        sesiones = int(r["sesiones"]) if not _vacio(r.get("sesiones")) else 0
        vol_aplica = clase in CLASES_CON_VOLUMEN
        vol = r.get("volumen_mediano")
        truncado = es_truncado(sesiones)
        if truncado:
            d, rg, mot = "fuera", "truncado", (f"fichero truncado: {sesiones} sesiones con cierre (< {MIN_SESIONES}); "
                                               "re-descarga completa en el 3b")
        else:
            d, rg, mot = "queda", "d10_abierta", "queda: D10 abierta (elegibilidad punto a punto en la Fase 4)"
        a = alias.get(t)
        if a and d == "queda":
            mot += (f"; alias informativo de {a[0]} (UCITS: invertible para un minorista de la UE; los dos se quedan)"
                    if a[1] == "ucits" else f"; alias ETF informativo de {a[0]} ({a[1]})")
        avisos = [AVISO_SOSPECHOSA] * (t in sospechosas) + [AVISO_REUTILIZADO] * (t in reutilizados)
        if t in recortados:
            avisos.append(AVISO_RECORTADA.format(n=recortados[t]))
        if a and a[1] == "ucits" and (t, a[0]) in poca_corr:
            avisos.append(AVISO_UCITS.format(etf=a[0], c=f"{poca_corr[(t, a[0])]:.3f}".replace(".", ","),
                                             u=f"{UMBRAL_UCITS_SEMANAL:.2f}".replace(".", ",")))
        aviso = "; ".join(avisos) or None
        if t in SOSPECHOSAS_VERIFICADAS and d == "queda":
            mot += f"; serie sospechosa verificada: {SOSPECHOSAS_VERIFICADAS[t]}: {MOTIVO_F3}"
        elif t in sospechosas and d == "queda":
            mot += f"; serie sospechosa (ticker reciclado o datos basura): {MOTIVO_F3}"
        if t in reutilizados:
            mot += f"; {AVISO_REUTILIZADO} ({reutilizados[t]})"
        frontera = r["posible_frontera"] if not _vacio(r.get("posible_frontera")) else None
        filas.append({
            "id": t, "proveedor": r["proveedor"], "clase": clase, "bucket": r["bucket"] if not _vacio(r.get("bucket"))
            else None, "en_universo": bool(r["en_universo"]), "desde": r["desde"], "hasta": r["hasta"],
            "sesiones": sesiones, "decision": d, "regla": rg, "motivo": mot, "alias_de": a[0] if a else None,
            "tipo_alias": ("ucits" if a[1] == "ucits" else "grupo_etf") if a else None, "aviso": aviso,
            "frontera": frontera or ("tema3" if clase == "accion" else None),
            **marcas_inicio(r["desde"]), "volumen_aplica": vol_aplica,
            "con_volumen": bool(vol_aplica and not _vacio(vol) and float(vol) > 0),
            "truncado": truncado, "deslistado": bool(r["deslistado"]) and not truncado,
        })
    return pd.DataFrame(filas, columns=COLUMNAS_PRECIOS).sort_values("id", kind="mergesort").reset_index(drop=True)


# --- Resumen y descargas del 3b ----------------------------------------------------------------
def tabla_resumen(series: pd.DataFrame, precios: pd.DataFrame) -> pd.DataFrame:
    """Recuentos por decisión × fuente (o proveedor) y por decisión × regla, de series y de precios."""
    partes = []
    for tipo, df, col in (("series", series, "fuente"), ("precios", precios, "proveedor")):
        for desglose, c in (("fuente", col), ("regla", "regla")):
            g = df.groupby(["decision", c]).size().reset_index(name="n").rename(columns={c: "grupo"})
            g.insert(0, "desglose", desglose)
            g.insert(0, "tipo", tipo)
            partes.append(g)
        t = df.groupby("decision").size().reset_index(name="n")
        t.insert(0, "grupo", "total")
        t.insert(0, "desglose", "total")
        t.insert(0, "tipo", tipo)
        partes.append(t[["tipo", "desglose", "decision", "grupo", "n"]])
    out = pd.concat(partes, ignore_index=True)[["tipo", "desglose", "decision", "grupo", "n"]]
    return out.sort_values(["tipo", "desglose", "decision", "grupo"], kind="mergesort").reset_index(drop=True)


_PRIORIDAD_CAPA = {"estrategica": "alta", "baseline": "alta", "tactica": "media", "contexto": "media"}
WEO_EDICIONES = (*(f"{a}-{m}" for a in range(2008, 2026) for m in ("04", "10")), "2026-04")  # 2026-10 ya está
AGREGADOS_BM = (("WLD", "mundo"), ("LMY", "emergentes (renta baja y media)"), ("EMU", "zona euro"))
AGREGADOS_WEO = (("001", "mundo"), ("200", "emergentes y en desarrollo"), ("163", "zona euro"))
Q1 = "Q1: fuente final de precios (Yahoo, EODHD, Tiingo o WRDS)"

# Huecos de valor de «Deudas pendientes» del README (2026-10-13) que se arreglan descargando
DEUDAS_README = (
    ("supervivencia:salidos_sin_precio", "precios", "wrds_crsp|tiingo", "media",
     "supervivencia: 459 de 759 salidos del índice sin precio en Yahoo (la PIT cubre el 66 % de cada mes)", Q1),
    ("supervivencia:sp500_quiebras_q", "precios", "wrds_crsp", "baja",
     "S&P 500: 28 tramos con ticker de quiebra (sufijo Q/QQ); el mapeo exige CIK/PERMNO", Q1),
    ("constituyentes:nikkei225_ibovespa", "constituyentes", "otra", "baja",
     "constituyentes de Nikkei 225 e Ibovespa sin fuente", ""),
    ("baseline:6040_europeo", "precios", "yahoo", "media",
     "el 60/40 europeo arranca en 2017-11 (EUNA.DE): agregado UCITS más antiguo o empalme con BNDX", ""),
    ("fred:h15_diario_pre2005", "fechas", "fed_h15", "media",
     "H.15 diario antes de 2005-06-28: archivo de h15/update para contrastar la fecha (hoy, edición semanal)", ""),
    ("ken_french:ediciones_antiguas", "fechas", "ken_french", "media",
     "ediciones archivadas de Ken French anteriores al archivo propio (regla «+45 días» sin verificar)", ""),
    ("academicas:reglas_sin_verificar", "fechas", "goyal_welch|nber|ofr_fsi", "baja",
     "ediciones de Goyal-Welch, NBER y OFR para verificar sus reglas de fecha", ""),
    ("academicas:archivo_periodico", "archivo_periodico", "academicas", "media",
     "archivo periódico de las ediciones académicas (se reeditan enteras)", ""),
    ("rba:historia_pre2011", "series", "rba", "media", "historia larga del RBA (antes de 2011)", ""),
    ("boc:historia_pre2001", "series", "boc", "media", "historia larga del Banco de Canadá (antes de 2001)", ""),
    ("oecd:LI_AA.EA20", "series", "oecd", "media", "sin filas en la base (CLI de la zona euro; G4E es sustituto)", ""),
    ("oecd:UNEMP.CHN", "series", "oecd", "media", "sin filas en la base", ""),
    ("philly:EMPLOY", "series", "philly_rtdsm", "media", "sin filas en la base", ""),
    ("philly:PCPI", "series", "philly_rtdsm", "media", "sin filas en la base", ""),
    ("philly:RUC", "series", "philly_rtdsm", "media", "sin filas en la base", ""),
    ("vintages:bce_eurostat_bis_bm", "vintages", "bce|eurostat|bis|worldbank", "baja",
     "historia de revisiones de BCE, Eurostat, BIS y Banco Mundial (hoy, valores de hoy con regla)", ""),
    ("eurostat:calendarios", "fechas", "eurostat", "baja",
     "calendarios de Eurostat sin verificar: paro antes de 2012, PIB antes de 2003, CREACION_GEO de EA20/EA21", ""),
    ("precios:aperturas", "precios", "yahoo", "media",
     "precios de apertura para la ejecución en t+1 (arquitectura): validar o rehacer según la fuente final", Q1),
)


def _fila3b(id_: str, tipo: str, fuente: str, prioridad: str, motivo: str, clase: str = "", bucket: str = "",
            detalle: str = "", depende_de: str = "") -> dict[str, str]:
    return {"id": id_, "tipo": tipo, "fuente": fuente, "estado": "pendiente", "prioridad": prioridad,
            "motivo": motivo, "clase": clase, "bucket": bucket, "detalle": detalle, "depende_de": depende_de}


def aplicar_f3(d3b: pd.DataFrame) -> pd.DataFrame:
    """F3 (Q1 = solo Yahoo): las filas que dependían de Q1 (deslistados, sospechosas, supervivencia, aperturas)
    y los instrumentos que Yahoo no sirve (``SIN_YAHOO``) dejan de ser descargas pendientes:
    ``estado = 'limitacion_declarada'``, ``prioridad = 'no se descarga'`` y el motivo de F3 delante.
    El resto queda ``estado = 'pendiente'`` con su prioridad (los UCITS de bolsas europeas se intentan en Yahoo)."""
    d = d3b.copy()
    limit = d["depende_de"].astype(str).str.contains("Q1") | d["id"].isin(list(SIN_YAHOO))
    d.loc[limit, "estado"] = "limitacion_declarada"
    d.loc[limit, "prioridad"] = "no se descarga"
    d.loc[limit, "motivo"] = MOTIVO_F3 + " · " + d.loc[limit, "motivo"].astype(str)
    sin = d["id"].isin(list(SIN_YAHOO))
    d.loc[sin, "detalle"] = d.loc[sin, "id"].map(SIN_YAHOO)
    return d


def tabla_descargas_3b(series: pd.DataFrame, precios: pd.DataFrame, universo: pd.DataFrame, pre: pd.DataFrame,
                       bmw: pd.DataFrame, sin_ea: Iterable[str] = ()) -> pd.DataFrame:
    """Lo que falta por descargar en el paso 3b (``COLUMNAS_3B``), con prioridad, motivo y fuente."""
    filas = []
    n_proy_weo = int(((series["decision"] == "proyecciones") & (series["fuente"] == "imf_weo")).sum())
    con_fichero = set(pre["id_universo"].dropna())
    for _, u in universo[~universo["id"].isin(con_fichero)].sort_values("id").iterrows():
        prio = "alta" if bool(u.get("invertible_minorista_ue")) else _PRIORIDAD_CAPA.get(str(u["capa"]), "media")
        prov = str(u.get("tickers") or "yahoo").split("=")[0] or "yahoo"
        filas.append(_fila3b(u["id"], "precios", prov, prio, f"instrumento del universo sin fichero de precios "
                             f"(capa {u['capa']})", str(u["clase"]), str(u["bucket"]),
                             "invertible minorista UE" if bool(u.get("invertible_minorista_ue")) else ""))
    for e in WEO_EDICIONES:
        filas.append(_fila3b(f"imf_weo:edicion:{e}", "ediciones", "imf_weo", "alta",
                             "D1: el WEO solo tiene la edición de 2026; hacen falta las ediciones 2008–2025 (dato y "
                             "proyecciones) para su historia visible",
                             detalle=f"DBnomics en Disallow; trae también las {n_proy_weo} series de proyecciones "
                             "del WEO (tabla aparte, D4)",
                             depende_de="permiso o archivo del FMI"))
    ind_bm = sorted(bmw.loc[(bmw["fuente"] == "worldbank") & bmw["en_alcance_estricto"], "indicador"].unique())
    ind_weo = sorted(bmw.loc[(bmw["fuente"] == "imf_weo") & bmw["en_alcance_estricto"], "indicador"].unique())
    for cod, nombre in AGREGADOS_BM:
        filas.append(_fila3b(f"wb:{cod}", "series", "worldbank", "media", f"D3: agregado {nombre} del Banco Mundial "
                             "(hoy lo descarta fuentes/worldbank.py)", detalle="; ".join(ind_bm)))
    for cod, nombre in AGREGADOS_WEO:
        filas.append(_fila3b(f"imf:WEO.{cod}", "series", "imf_weo", "media", f"D3: agregado {nombre} del WEO",
                             detalle="; ".join(ind_weo)))
    for fam in sin_ea:
        filas.append(_fila3b(f"eurostat:{fam}.EA", "series", "eurostat", "media", "E3: falta la zona euro de "
                             "composición cambiante (EA); hoy solo hay composiciones fijas", detalle=fam))
    capadas = series[series["estado"] == "capada"]
    for s in capadas["id"]:
        filas.append(_fila3b(s, "archivo_periodico", "fred_alfred", "alta", "OAS de ICE: FRED solo guarda 3 años "
                             "(ventana móvil); archivo periódico para acumular historia"))
    # Refresco: solo lo que se queda (los alias se guardan aparte y no se refrescan). Las proyecciones van a su
    # tabla (D4): las del WEO llegan con las ediciones; las demás, en su propia fila de refresco.
    for f, n in series[series["decision"] == "queda"].groupby("fuente").size().items():
        filas.append(_fila3b(f"refresco:{f}", "refresco", str(f), "alta", f"refresco hasta hoy (último: "
                             f"{ULTIMO_REFRESCO})", detalle=f"{n} {'serie que se queda' if n == 1 else 'series que se quedan'}"))
    proy = series[series["decision"] == "proyecciones"]
    for f, n in proy[proy["fuente"] != "imf_weo"].groupby("fuente").size().items():
        filas.append(_fila3b(f"refresco:proyecciones:{f}", "refresco", str(f), "media", f"refresco de las proyecciones "
                             f"hasta hoy (último: {ULTIMO_REFRESCO}); tabla aparte (D4)", detalle=f"{n} proyecciones"))
    for p, n in precios[precios["decision"] == "queda"].groupby("proveedor").size().items():
        filas.append(_fila3b(f"refresco:precios:{p}", "refresco", str(p), "alta", f"refresco hasta hoy (último: "
                             f"{ULTIMO_REFRESCO})", detalle=f"{n} ficheros"))
    for _, r in precios[precios["truncado"]].iterrows():
        filas.append(_fila3b(r["id"], "redescarga", str(r["proveedor"]), "media",
                             f"re-descarga completa: fichero truncado ({r['sesiones']} sesiones, {r['desde']} a "
                             f"{r['hasta']})", str(r["clase"])))
    aviso = precios["aviso"].fillna("").astype(str)
    for _, r in precios[precios["deslistado"]].iterrows():
        if AVISO_REUTILIZADO in str(r["aviso"] or ""):
            # DWD (ECNQUOTE de 2013 a 2017) o GR (un fondo de 2001 a 2018): el fichero no es el miembro del S&P,
            # así que ni su historia ni su salida son las del miembro.
            mot = (f"{AVISO_REUTILIZADO} (fichero {r['desde']} a {r['hasta']}): falta la historia del miembro y "
                   "su salida")
        else:
            mot = f"deslistado (última sesión {r['hasta']}): historia completa y salida"
        filas.append(_fila3b(r["id"], "deslistado", str(r["proveedor"]), "media", mot, str(r["clase"]),
                             depende_de=Q1))
    for _, r in precios[aviso.str.contains(AVISO_SOSPECHOSA, regex=False)].iterrows():
        filas.append(_fila3b(r["id"], "serie_sospechosa", str(r["proveedor"]), "media",
                             "serie sospechosa (ticker reciclado o datos basura: saltos sin split o cierres "
                             "repetidos): rehacer con identificador permanente", str(r["clase"]),
                             depende_de="Q1 (CRSP/PERMNO)"))
    for id_, tipo, fuente, prio, mot, dep in DEUDAS_README:
        filas.append(_fila3b(id_, tipo, fuente, prio, mot, detalle="README · Deudas pendientes", depende_de=dep))
    out = aplicar_f3(pd.DataFrame(filas, columns=COLUMNAS_3B))
    orden = {"alta": 0, "media": 1, "baja": 2, "no se descarga": 3}
    return (out.assign(_o=out["prioridad"].map(orden)).sort_values(["_o", "tipo", "id"], kind="mergesort")
            .drop(columns="_o").reset_index(drop=True))


# --- YAML ---------------------------------------------------------------------------------------
class _SinAnclas(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # noqa: ARG002 - sin anclas YAML
        return True


def _limpio(v: Any) -> Any:
    if _vacio(v):
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


# El resto de columnas (fuente, estado, nivel, canónico, fechas...) está en seleccion_*.csv
CAMPOS_YAML_SERIES = ("decision", "rol", "regla", "motivo", "alias_de", "completa_a", "canonico_dudoso",
                      "aviso_fecha", "regla_conservadora", "tramo_conservador_antes_de", "frontera", "nota")
CAMPOS_YAML_PRECIOS = ("decision", "regla", "motivo", "alias_de", "tipo_alias", "aviso", "frontera", "clase",
                       "desde_2000", "desde_2007", "desde_2016", "con_volumen", "truncado", "deslistado")


def cabecera_yaml(series: pd.DataFrame, precios: pd.DataFrame) -> str:
    n_s = series["decision"].value_counts().to_dict()
    n_p = precios["decision"].value_counts().to_dict()
    return "\n".join([
        "# Lista curada del Tema 1 (paso 3 de la descarga completa): entrada del paso 4 (preprocesado).",
        "# Una entrada por serie y por fichero de precios con su decisión (queda | alias | fuera | proyecciones),",
        "# el motivo y las marcas para el preprocesado. Solo metadatos: ningún valor de las series.",
        "#",
        "# De dónde sale: results/ingesta/mercados_series/tablas/ (inventario_series, inventario_precios,",
        "# fiabilidad_c, redundancia_pares, redundancia_conceptos, redundancia_bm_weo, redundancia_etf),",
        "# eda_precios.csv (serie_sospechosa, de B2), catalogo_series.yaml (estado, duplicado_de),",
        "# publicaciones.yaml y universo.yaml. Una línea por entrada; los campos vacíos o false no se escriben.",
        "#",
        f"# Decisiones aplicadas: D1, D2, D3/D9, D4, D8 ({FECHA_D}); D10 ABIERTA (ningún ticker sale por inicio",
        f"# ni volumen); E1, E2, E3, E6 ({FECHA_E}). El detalle de cada regla, en el docstring de seleccion.py.",
        "#",
        "# Regenerar: python -m ingesta.mercados_series.seleccion (sin red; no toca la base ni el crudo).",
        f"# Series: {sum(n_s.values())} ({', '.join(f'{k} {v}' for k, v in sorted(n_s.items()))}).",
        f"# Precios: {sum(n_p.values())} ({', '.join(f'{k} {v}' for k, v in sorted(n_p.items()))}).",
        "",
    ])


def linea_yaml(clave: str, campos: Mapping[str, Any]) -> str:
    """Una entrada en una línea (estilo flujo), sin los campos ``null`` ni ``false``."""
    d = {k: _limpio(v) for k, v in campos.items()}
    d = {k: v for k, v in d.items() if v is not None and v is not False}
    texto = yaml.dump({clave: d}, Dumper=_SinAnclas, allow_unicode=True, sort_keys=False, width=10**6,
                      default_flow_style=True).strip()
    return texto[1:-1]  # sin las llaves del mapa exterior


def escribir_yaml(series: pd.DataFrame, precios: pd.DataFrame, ruta: Path) -> Path:
    """``lista_curada.yaml``: cabecera comentada y ``series``/``precios`` ordenados por id, una línea por entrada
    (sin los campos vacíos ni ``false``) y sin anclas."""
    lineas = []
    for nombre, df, campos in (("series", series, CAMPOS_YAML_SERIES), ("precios", precios, CAMPOS_YAML_PRECIOS)):
        lineas.append(f"{nombre}:")
        for _, r in df.sort_values("id", kind="mergesort").iterrows():
            lineas.append("  " + linea_yaml(str(r["id"]), {c: r[c] for c in campos}))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(cabecera_yaml(series, precios) + "\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    return ruta


# --- Orden --------------------------------------------------------------------------------------
def _leer(tablas: Path, nombre: str) -> pd.DataFrame:
    ruta = tablas / nombre
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta}: ejecuta antes el paso 2 (inventario y redundancia)")
    return pd.read_csv(ruta, dtype={"ticker": str})


def calcular(tablas: Path) -> dict[str, Any]:
    """Todas las salidas (DataFrames) desde las tablas del paso 2 y la configuración del tema."""
    from ingesta.mercados_series import catalogo, universo, visibilidad

    inv = _leer(tablas, "inventario_series.csv")
    pre = _leer(tablas, "inventario_precios.csv")
    fia = _leer(tablas, "fiabilidad_c.csv")
    pares = _leer(tablas, "redundancia_pares.csv")
    conc = _leer(tablas, "redundancia_conceptos.csv")
    bmw = _leer(tablas, "redundancia_bm_weo.csv")
    etf = _leer(tablas, "redundancia_etf.csv")
    cat = catalogo.cargar_catalogo()
    dup = {s: e["duplicado_de"] for s, e in cat.items() if e.get("estado") == "duplicada" and e.get("duplicado_de")}
    pubs = visibilidad.cargar_publicaciones()["publicadores"]
    series, sin_ea = seleccionar_series(inv, fia, pares, conc, bmw, dup, pubs)
    clases = clases_precios(pre)
    ruta_eda = tablas / "eda_precios.csv"
    eda = pd.read_csv(ruta_eda, dtype={"ticker": str}) if ruta_eda.exists() else None
    tramos = pd.read_parquet(ruta_tramos_sp500()) if ruta_tramos_sp500().exists() else None
    cob = cobertura_tramos_sp500(tramos, pre, clases) if tramos is not None else None
    reutilizados = tickers_reutilizados(cob) if cob is not None else {}
    uni = universo.tabla_universo()
    precios = seleccionar_precios(pre, etf, clases, series_sospechosas(eda), reutilizados,
                                  historia_recortada(pre, uni))
    descargas = tabla_descargas_3b(series, precios, uni, pre, bmw, sin_ea)
    return {"series": series, "precios": precios, "resumen": tabla_resumen(series, precios), "descargas": descargas,
            "cobertura_sp500": cob}


def dudosos(series: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Canónicos dudosos (uno por canónico), los de más alias y más historia en juego primero."""
    d = series[series["canonico_dudoso"] & (series["id"] == series["canonico"])].copy()
    n_alias = series[series["decision"] == "alias"].groupby("alias_de").size()
    d["n_alias"] = d["id"].map(n_alias).fillna(0).astype(int)
    # el grupo: el canónico y todo lo que cuelga de él (canonico, alias_de o completa_a)
    cuelga = pd.concat([series[["id", c]].rename(columns={c: "raiz"})
                        for c in ("canonico", "alias_de", "completa_a") if c in series])
    cuelga = cuelga[cuelga["raiz"].notna() & (cuelga["id"] != cuelga["raiz"])].drop_duplicates()
    d["n_grupo"] = 1 + d["id"].map(cuelga.groupby("raiz")["id"].nunique()).fillna(0).astype(int)
    return d.sort_values(["n_alias", "n_grupo", "id"], ascending=[False, False, True]).head(n)


def main(argv: list[str] | None = None) -> dict[str, Path]:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tablas", type=Path, default=None, help="carpeta de las tablas (por defecto results/.../tablas)")
    p.add_argument("--lista", type=Path, default=RUTA_LISTA, help="ruta de lista_curada.yaml")
    a = p.parse_args(argv)
    tablas = a.tablas or resultados_dir(TEMA) / "tablas"
    s = calcular(tablas)
    rutas = {"lista_curada.yaml": escribir_yaml(s["series"], s["precios"], a.lista)}
    for nombre, clave in (("seleccion_series.csv", "series"), ("seleccion_precios.csv", "precios"),
                          ("seleccion_resumen.csv", "resumen"), ("descargas_3b.csv", "descargas")):
        rutas[nombre] = tablas / nombre
        s[clave].to_csv(rutas[nombre], index=False, encoding="utf-8", lineterminator="\n")
    ns, np_ = s["series"]["decision"].value_counts().to_dict(), s["precios"]["decision"].value_counts().to_dict()
    print(f"series: {len(s['series'])} -> " + ", ".join(f"{k} {ns.get(k, 0)}" for k in DECISIONES))
    print(f"precios: {len(s['precios'])} -> " + ", ".join(f"{k} {np_.get(k, 0)}" for k in DECISIONES))
    print(f"canónicos dudosos: {int((s['series']['canonico_dudoso'] & (s['series']['id'] == s['series']['canonico'])).sum())}")
    print("descargas 3b por prioridad: " + ", ".join(f"{k} {v}" for k, v in
                                                     s["descargas"]["prioridad"].value_counts().items()))
    for nombre, ruta in rutas.items():
        print(f"  {nombre}: {ruta}")
    return rutas


if __name__ == "__main__":
    main()
