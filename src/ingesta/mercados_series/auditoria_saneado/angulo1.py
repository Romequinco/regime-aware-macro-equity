"""Auditoría · ángulo 1 (huecos y nulos) del Tema 1. SOLO LECTURA.

Orquesta los dos scripts de medida y compone los hallazgos:
  - angulo1_series.py  -> angulo1_series.json   (nulos de la base curada y de trabajo, series paradas, huecos EDA)
  - angulo1_precios.py -> angulo1_precios.json  (cierres/aperturas nulas, velas quitadas, huecos de calendario,
                                                 no llegan al corte, ficheros solo en crudo)
y escribe angulo1.json (hallazgos). Ningún valor de serie ni precio sale en las salidas: solo recuentos, fechas e ids.

Uso:  set PYTHONPATH=<worktree>/src ;  python angulo1.py [--rehacer]
      (--rehacer vuelve a ejecutar los dos scripts de medida; si no, reutiliza sus JSON si existen)
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

AQUI = Path(__file__).parent
WT = _REPO
C = "'D:/tfm_corpus/mercados_series/series/base_curada.parquet'"


def medir(nombre: str, rehacer: bool) -> dict:
    js = AQUI / f"{nombre}.json"
    if rehacer or not js.exists():
        env = dict(os.environ, PYTHONPATH=str(WT / "src"), PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, str(AQUI / f"{nombre}.py")], check=True, env=env)
    return json.loads(js.read_text(encoding="utf-8"))


def main(rehacer: bool = False):
    S = medir("angulo1_series", rehacer)
    P = medir("angulo1_precios", rehacer)
    T = pd.read_csv(AQUI / "angulo1_precios_tickers.csv")

    # ---- cifras extra (pequeñas)
    con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2")
    nom6 = con.sql(f"""select count(*) filas, sum((valor is null)::int) nulos from read_parquet({C})
                       where serie='boe:NOM.6M' and fecha_referencia >= DATE '2013-01-01'""").df().iloc[0]
    nom10 = con.sql(f"""select count(*) from read_parquet({C}) where serie='boe:NOM.10Y'
                        and fecha_referencia >= DATE '2013-01-01'""").fetchone()[0]
    pct_nom6 = round(100 * float(nom6["nulos"]) / float(nom6["filas"]), 1)
    anios = {int(k): v for k, v in P["anuladas_por_anio"].items()}
    anul_2007 = sum(v for k, v in anios.items() if k >= 2007)
    T["dias_hasta_esperada"] = (pd.to_datetime(T["ultima_esperada"]) - pd.to_datetime(T["ultima"])).dt.days
    no_llega_real = T[T["dias_hasta_esperada"] > 3]
    no_llega_1dia = int((T["dias_hasta_esperada"].between(1, 3)).sum())
    nl = pd.DataFrame(P["no_llega_lista"])
    nl = nl[nl["ticker"].isin(no_llega_real["ticker"])]

    def causa(nota: str) -> str:
        nota = str(nota)
        if "revisa una sesión ya guardada" in nota: return "refresco rechazado (Yahoo revisó una sesión ya guardada)"
        if "reutilizado" in nota: return "ticker reutilizado por otra empresa"
        if "fusión" in nota: return "fusión (la historia sigue en otro ticker)"
        if "adquirido" in nota: return "adquirido / sale del índice"
        if "refresco incompleto" in nota: return "refresco incompleto (fallo de descarga)"
        return "otra"
    nl["causa"] = nl["nota"].map(causa)
    causas_nl = nl.groupby("causa")["ticker"].apply(lambda x: sorted(x)).to_dict()
    retiradas = [a for a in S["atraso_tools"] if a["fuente"] in ("bce", "calculo_propio") or a["serie"].startswith("fred:")]
    activas_tools = [a["serie"] for a in S["atraso_tools"] if a not in retiradas]
    pp = pd.DataFrame(S["parada_propia"])
    pp_act = pp[pp["estado"] != "retirada"]

    def grupo_parada(s: str) -> str:
        if s.startswith(("ff:", "gw:")): return "regla conservadora (dato publicado pero aún no visible al corte)"
        if s.startswith("eurostat:"): return "parada en la fuente sin marcar como retirada (Eurostat: RU tras el Brexit, HICP de EE. UU.)"
        if s.startswith(("yf:", "bbk:")): return "sin refrescar: limitación declarada (Yahoo, Bundesbank)"
        if s.startswith("bis:WS_CBPOL.M."): return "histórica por diseño (tipos nacionales antes del euro)"
        if s.startswith("philly:"): return "histórica por diseño (vintages anteriores a ALFRED)"
        if s in ("ecb:MRO", "ecb:DFR"): return "serie de fechas de cambio (no parada)"
        return "otra"
    pp_act = pp_act.assign(grupo=pp_act["serie"].map(grupo_parada))
    grupos_pp = pp_act.groupby("grupo")["serie"].apply(list).to_dict()

    ev_s = "angulo1_series.py"; ev_p = "angulo1_precios.py"
    H = []

    def h(**k):
        k.setdefault("tipo", "nulos"); k.setdefault("desglose", None); k.setdefault("difiere_del_plan", None)
        H.append(k)

    nd = {r["causa"]: r["filas"] for r in S["no_diarias_por_causa"]}
    h(id="N01", titulo="Los 26.200 nulos de la base curada casi nunca son festivos: son huecos de vintage y plazos de curva sin publicar",
      que_pasa=("La base curada tiene 26.200 filas con valor vacío en 94 series, todas con una nota que explica por qué. "
                "Pero solo 7 caen en un festivo. Casi todas son: vintages antiguos de ALFRED que aún no tenían ese dato "
                "(luego sí se publicó) y días en que el BoE o el MoF japonés no publicaban un plazo de la curva."),
      por_que_importa=("Las filas nulas son información real de «qué se sabía entonces»: no se deben rellenar ni borrar a ciegas. "
                       "Quitarlas como «festivos» sería un error: el 99,97 % no lo son. El código ya descarta los festivos al cargar "
                       "(fred.py, alfred.py, curvas.py, bancos_centrales.py), por eso casi no quedan."),
      cifras={"nulos_curada": S["curada_total"]["nulos"], "series_con_nulo": S["curada_total"]["series_con_nulo"],
              "fred_alfred": 19619, "boe_curvas": 5490, "mof_jgb": 1085, "boc_curva": 6,
              "nulos_sin_nota": S["nulos_sin_nota"], "festivos": S["diarias_por_causa"].get("festivo", 0),
              "vintage_antiguo_luego_publicado": nd.get("vintage_antiguo_sin_dato_luego_publicado"),
              "dato_retirado_en_vintage_posterior": nd.get("dato_retirado_en_vintages_posteriores"),
              "nunca_publicado_pre2006": nd.get("nunca_publicado_otro"),
              "cierre_gobierno_2025_10": nd.get("2025-10_cierre_gobierno_EEUU_nunca_publicado"),
              "curva_plazo_no_publicado_tramos": S["diarias_por_causa"].get("tramo_plazo_no_publicado(>=5 hábiles)"),
              "curva_dia_suelto": S["diarias_por_causa"].get("dia_suelto_sin_dato"),
              "sabados_JGB_1978_1980": S["diarias_por_causa"].get("fin_de_semana")},
      desglose={"por_causa": {"vintage antiguo, luego publicado": nd.get("vintage_antiguo_sin_dato_luego_publicado"),
                              "plazo de curva no publicado": S["diarias_por_causa"].get("tramo_plazo_no_publicado(>=5 hábiles)", 0) + S["diarias_por_causa"].get("dia_suelto_sin_dato", 0) + S["diarias_por_causa"].get("fin_de_semana", 0),
                              "retirado en vintage posterior": nd.get("dato_retirado_en_vintages_posteriores"),
                              "nunca publicado (antes de 2006)": nd.get("nunca_publicado_otro"),
                              "cierre del Gobierno 2025-10": nd.get("2025-10_cierre_gobierno_EEUU_nunca_publicado"),
                              "festivo": S["diarias_por_causa"].get("festivo", 0)},
                "por_decada_ref": S["nulos_por_decada_ref"]},
      evidencia=f"{ev_s}: nulos_curada() — DuckDB sobre base_curada.parquet (valor IS NULL, vintages, nota); calendarios exchange_calendars (XNYS+USFederalHolidayCalendar, XLON, XTKS, XTSE); cobertura_series.csv",
      difiere_del_plan=("Totales iguales (26.200 en 94; 19.619/5.490/1.085/6). Pero «fred_alfred casi todos festivos» es FALSO: de los 19.619 "
                        "de fred_alfred solo 4 son diarios (y son marcas de hueco > 31 días); 19.615 están en series mensuales/trimestrales de ALFRED."),
      gravedad_propuesta="cosmetico",
      ideas_arreglo=["No rellenar ni borrar: son correctos para el TimeGate (sin red)",
                     "Corregir la frase del plan/README: no son festivos (sin red)",
                     "Opcional: en la vista para agentes, ocultar los nulos de vintages superados por defecto (ya lo hace as_of_series al elegir el último vintage) (sin red)"])

    h(id="N02", titulo="boe:NOM.6M (6 meses del Reino Unido) vacío en ~1 de cada 3 días desde 2013",
      que_pasa=(f"La curva del BoE no da el plazo de 6 meses muchos días: desde 2013 faltan {int(nom6['nulos'])} de {int(nom6['filas'])} días ({pct_nom6} %), "
                "y los demás plazos sí tienen dato esos días. Es el mayor hueco reciente de toda la base curada."),
      por_que_importa=("Es el 80 % de los nulos visibles desde 2000 en la vista al corte. Un agente que pida el 6M británico o una pendiente 6M–10Y "
                       "verá huecos frecuentes; un z-score o una media móvil sin tratar los nulos se rompe."),
      cifras={"nulos_desde_2013": int(nom6["nulos"]), "filas_desde_2013": int(nom6["filas"]), "pct": pct_nom6,
              "filas_NOM10Y_desde_2013": int(nom10), "vista_corte_nulos_desde2000_total": S["vista_corte_nulos_desde2000"],
              "boe_NOM6M_desde2000": S["vista_corte_desde2000_por_serie"].get("boe:NOM.6M")},
      desglose={"boe_NOM6M_nulos_por_anio": S["boe_NOM6M_por_anio"]},
      evidencia=f"{ev_s}: nulos_curada() (rachas por serie, otros plazos con dato ese día) y angulo1.py (recuento 2013+)",
      gravedad_propuesta="importante",
      ideas_arreglo=["Avisar en get_serie de la proporción de nulos de la serie (sin red)",
                     "Documentar que el 6M del BoE no es fiable a diario; usar 1Y o SONIA/Bank Rate para el corto británico (sin red; SONIA necesitaría red si no está)",
                     "No interpolar entre plazos: sería un dato que la fuente nunca publicó"])

    h(id="N03", titulo="Octubre de 2025 no existe en 21 series de EE. UU. (cierre del Gobierno)",
      que_pasa=("Por el cierre del Gobierno federal, el BLS nunca publicó el dato de octubre de 2025 del paro, el IPC y otras 19 series. "
                "La base lo guarda como fila nula con nota «hueco permanente», como debe."),
      por_que_importa=("Está dentro de la ventana del backtest: las variaciones mensuales o interanuales de oct/nov-2025, la regla de Sahm y "
                       "cualquier señal macro de esas fechas tienen un agujero. Si alguien rellena hacia delante sin avisar, mete un dato inventado."),
      cifras={"series": len(S["shutdown_series"]), "fecha_referencia": "2025-10-01"},
      desglose={"series": S["shutdown_series"]},
      evidencia=f"{ev_s}: nulos_curada() causa '2025-10_cierre_gobierno_EEUU_nunca_publicado' (ninguna fila con valor en ningún vintage); catalogo_series.yaml anota el hueco",
      gravedad_propuesta="importante",
      ideas_arreglo=["Mantener nulo; que las tools/derivadas que calculan cambios lo traten explícitamente (sin red)",
                     "Para derivadas (variación mensual), calcular nov/oct como nulo y dic/nov normal (sin red)"])

    ret = {r["serie"]: int(float(r["desde2000"])) for r in S["vista_corte_nulo_con_valor_previo"] if float(r["desde2000"]) > 0}
    h(id="N04", titulo="Datos que se publicaron y luego aparecen vacíos: IPC mediana y recortada de Cleveland con ago–sep-2026 nulos al corte",
      que_pasa=("En 22 series de ALFRED hay periodos que un vintage antiguo traía con valor y un vintage posterior trae vacío; la base se queda con "
                "el último, así que al corte salen nulos. El caso más fresco: el IPC mediana y el recortado de la Fed de Cleveland, cuyo vintage del "
                "2026-11-10 deja vacíos agosto y septiembre de 2026 (y el de 2025-10-24, unos 40 meses sueltos de la historia)."),
      por_que_importa=("Un agente que pregunte la inflación subyacente al corte ve los dos últimos meses vacíos aunque se publicaron. Puede ser un "
                       "artefacto de ALFRED o del cargador, no una retirada real. En PCEC96, PNFIC1, PRFIC1 y TDSP sí parece real (cambio de base: "
                       "la historia antigua desaparece del vintage nuevo)."),
      cifras={"periodos_nulos_al_corte_con_valor_previo": S["vista_corte_nulo_con_valor_previo_n"],
              "series": S["vista_corte_nulo_con_valor_previo_series"],
              "desde_2000": S["vista_corte_nulo_con_valor_previo_desde2000"],
              "MEDCPI_periodos": 43, "TRMMEANCPI_periodos": 51, "vintage_con_huecos": "2026-11-10 y 2025-10-24"},
      desglose={"desde_2000_por_serie": ret},
      evidencia=f"{ev_s}: nulos_curada() — vista al corte (arg_max por fecha_publicacion,vintage) con max(fecha_publicacion de filas con valor) anterior",
      gravedad_propuesta="importante",
      ideas_arreglo=["Comprobar en ALFRED/FRED si el vintage 2026-11-10 de MEDCPIM158SFRBCLE y TRMMEANCPIM158SFRBCLE trae de verdad '.' (necesita red)",
                     "Si es artefacto: en as_of, un '.' tras un valor ya publicado se trata como «sin revisión» y se sirve el último valor con aviso (sin red)",
                     "Si es real (cambio de base): dejarlo y documentarlo por serie (sin red)"])

    h(id="N05", titulo="Seis filas nulas de festivo sobrevivieron: Labour Day canadiense de 2006",
      que_pasa=("Las 6 series de bonos de la BoC tienen una fila vacía el 2006-09-04 (Labour Day en Canadá). En los demás años ese festivo no tiene "
                "fila, así que es una incoherencia suelta del cargador. La de DGS20 del 1987-01-01 no es un festivo: es la marca de su hueco de 1987–1993."),
      por_que_importa="Casi nada: 6 filas de 2006. Solo afea los recuentos y podría contar como «dato que falta» en un control de calidad.",
      cifras={"filas": 6, "fecha": "2006-09-04", "DGS20_1987_01_01_marca_de_hueco_no_festivo": S["diarias_por_causa"].get("festivo", 0) - 6},
      evidencia=f"{ev_s}: nulos_curada() causa 'festivo' (XTSE) y consulta de las filas BoC 2006-08-30..09-08",
      gravedad_propuesta="cosmetico",
      ideas_arreglo=["Quitar las filas nulas de BoC en días que el calendario XTSE da cerrados, como hace el cargador con el resto (sin red)"])

    h(id="N06", titulo="La curada no pierde datos de la base de trabajo, salvo el final que la fecha conservadora deja fuera del corte",
      que_pasa=("Todos los nulos de la base de trabajo de las series curadas siguen en la curada (0 perdidos). De los periodos con valor publicados "
                "antes del corte, 513 no están en la curada: 502 son los últimos días o meses (la regla conservadora retrasa su fecha más allá del "
                "2026-11-13) y 11 son el arranque de una derivada de 1928. Ninguno está en medio de una serie."),
      por_que_importa=("Es lo esperado, pero conviene saberlo: al corte, los factores diarios de Ken French acaban el 2026-08-31 y Goyal-Welch en "
                       "2024-12, aunque la fuente ya tenía más. Los nulos de series no curadas (ust:PAR.30Y 994, deriv:PIB_REAL_USA_VINTAGES 287, Banco Mundial 56) se quedan fuera."),
      cifras={"nulos_trabajo_total": S["trabajo_total_nulos"], "nulos_trabajo_no_en_curada_de_series_curadas": len(S["nulos_trabajo_no_en_curada"]),
              "periodos_perdidos": S["periodos_perdidos_total"], "series_afectadas": S["periodos_perdidos_series"],
              "al_final": S["periodos_perdidos_posicion"]["al_final"], "al_principio": S["periodos_perdidos_posicion"]["al_principio"],
              "en_medio": S["periodos_perdidos_posicion"]["en_medio"]},
      desglose={"perdidos_por_prefijo": pd.DataFrame(S["periodos_perdidos"]).assign(
          n=lambda x: x["n"].astype(int), p=lambda x: x["serie"].str.split(":").str[0]).groupby("p")["n"].sum().astype(int).to_dict()},
      evidencia=f"{ev_s}: trabajo_vs_curada() — anti-join DuckDB base_series vs base_curada; curada_resumen.csv (filas_cortadas)",
      difiere_del_plan="No contradice el plan; no he comprobado aparte los 25 alias con historia previa a 2000 que el plan dice que solo están en la base de trabajo.",
      gravedad_propuesta="cosmetico",
      ideas_arreglo=["Documentar en el catálogo hasta dónde llega cada serie al corte frente a la fuente (sin red)"])

    h(id="N07", titulo="Aperturas: 430.050 anuladas a propósito (4 %), el 67 % antes de 2000; 0 cierres nulos",
      que_pasa=("Ningún cierre está vacío en los 10,8 M de sesiones curadas. Las aperturas vacías son 430.050 y todas las puso el curado "
                "(en el crudo había 0): son velas planas (open = close y high = low) que no son una apertura real. 135.969 tenían volumen. "
                "Tocan 1.182 tickers; Londres es el mercado más afectado (17,7 % de sus sesiones)."),
      por_que_importa=("La ejecución del backtest es a la apertura de t+1. Desde 2007 hay "
                       f"{anul_2007} sesiones sin apertura (desde 2016, {P['anuladas_desde_2016']}), y 88 tickers tienen más del 20 % de aperturas vacías: "
                       "el backtest necesita una regla fija para esos casos (usar el cierre, saltar la orden o excluir el ticker)."),
      cifras={"cierres_nulos": P["cierres_nulos"], "sesiones_curadas": P["sesiones_curadas"], "aperturas_anuladas": P["aperturas_anuladas_medidas"],
              "aperturas_nulas_en_crudo": P["aperturas_nulas_ya_en_crudo"], "pct": P["pct_aperturas_anuladas"],
              "con_volumen": P["aperturas_anuladas_con_volumen"], "tickers": P["tickers_con_anuladas"],
              "antes_2000": P["anuladas_antes_2000"], "desde_2007": anul_2007, "desde_2016": P["anuladas_desde_2016"],
              "tickers_mas_20pct": P["open_nulo_mas_20pct_n"]},
      desglose={"por_mercado": {r["mercado"]: int(r["anuladas"]) for r in P["anuladas_por_mercado"][:10]},
                "por_anio": {k: v for k, v in sorted(anios.items()) if k >= 1990},
                "desde2016_top_tickers": P["anuladas_desde2016_top_tickers"]},
      evidencia=f"{ev_p}: recorrido de precios_curados vs precios (pyarrow, is_null de open/close); precios_curados_resumen.csv y precios_curados_avisos.csv",
      gravedad_propuesta="importante",
      ideas_arreglo=["Fijar en la cartera la regla de reserva cuando open es nulo (cierre de t+1 o de t, con aviso) (sin red)",
                     "Elegibilidad punto a punto (D10): excluir tickers con > X % de aperturas nulas en la ventana (sin red)",
                     "Para los ETP/acciones con muchas aperturas planas recientes (SSLN.L, DIGI, SW, CPWR…), revisar si Yahoo las sirve bien ahora (red)"])

    h(id="N08", titulo="VBMFX y ^SKEW no tienen ninguna apertura (confirmado)",
      que_pasa="VBMFX (fondo con valor liquidativo) tiene el 100 % de sus 10.057 sesiones sin apertura y ^SKEW el 99,9 % (9.203 de 9.212). Ya llevan su aviso «sin_apertura».",
      por_que_importa="^SKEW es un índice (no se opera) y VBMFX se compra al valor liquidativo del cierre: no rompe nada si la cartera usa el cierre para ellos.",
      cifras={"VBMFX_sin_open": 10057, "VBMFX_sesiones": 10057, "SKEW_sin_open": 9203, "SKEW_sesiones": 9212},
      evidencia=f"{ev_p}: sin_apertura (> 99 %); precios_curados_avisos.csv tipo sin_apertura",
      gravedad_propuesta="cosmetico",
      ideas_arreglo=["Que la cartera use el cierre para instrumentos con aviso sin_apertura (sin red)"])

    h(id="N09", titulo="29.611 velas de relleno quitadas (cuadra)",
      que_pasa="Las sesiones del crudo hasta el corte menos las curadas dan 29.611, lo mismo que la tabla de resumen y que el aviso de relleno. No queda ninguna sesión publicada después del corte.",
      por_que_importa="Confirma que el curado de precios solo quitó relleno y lo posterior al corte.",
      cifras={"velas_quitadas_medidas": P["velas_quitadas_medidas"], "velas_quitadas_tabla": P["velas_quitadas_tabla"],
              "aviso_relleno": P["aviso_relleno_quitadas_tabla"], "sesiones_post_corte": P["sesiones_post_corte_en_curado"]},
      evidencia=f"{ev_p}: sesiones_crudo_hasta_corte - sesiones (por fichero); precios_curados_resumen.csv; precios_curados_avisos.csv",
      gravedad_propuesta="cosmetico", ideas_arreglo=["Nada que hacer"])

    rt = pd.DataFrame(P["racha_top"]); rt = rt[rt["racha_max"].astype(int) > 5]
    h(id="N10", titulo="Huecos de calendario en precios: 17 tickers con más de 5 sesiones seguidas sin vela (KVUE, justo antes de salir)",
      que_pasa=("Comparando cada ticker con el calendario de su bolsa, faltan 9.126 sesiones en 653 tickers, casi todas sueltas. Solo 17 tickers "
                "tienen un hueco de más de 5 sesiones seguidas (7 de más de 20): BGEO.L un año entero (2011–2012), el yuan 153 sesiones en 2003, "
                "dos ETP suizos en 2019 y KVUE 13 sesiones (2026-10-13 a 10-29) antes de su última vela."),
      por_que_importa=("Un hueco largo hace que una rentabilidad «de un día» sea en realidad de semanas, y que una señal se quede congelada. "
                       "KVUE es reciente y cae en plena salida del S&P 500. ^W5000 lleva el calendario de Londres (metadato de Yahoo), lo que le inventa 206 «faltantes» que son festivos de EE. UU."),
      cifras={"tickers_con_faltantes": P["tickers_con_faltantes"], "sesiones_faltantes": P["sesiones_faltantes_total"],
              "faltantes_desde_2000": P["sesiones_faltantes_desde2000"], "tickers_racha_mas_5": P["tickers_racha_gt5"],
              "tickers_racha_mas_20": P["tickers_racha_gt20"], "eda_paso3_faltantes": P["eda_sesiones_faltantes_total"]},
      desglose={"racha_mas_5_por_mercado": {r["mercado"]: int(r["tickers"]) for r in P["racha_gt5_por_mercado"]},
                "top": [{"ticker": r["ticker"], "racha": int(r["racha_max"]), "desde": r["racha_desde"], "hasta": r["racha_hasta"]} for _, r in rt.iterrows()]},
      evidencia=f"{ev_p}: sesiones del calendario (eda.sesiones_calendario / eda.CALENDARIO_MERCADO) vs sesiones curadas, racha de índices consecutivos; precios_curados_avisos.csv tipo sesion_faltante",
      difiere_del_plan=f"El EDA del paso 3 (sobre el crudo antiguo) contaba {P['eda_sesiones_faltantes_total']} faltantes; sobre los curados actuales salen {P['sesiones_faltantes_total']}.",
      gravedad_propuesta="importante",
      ideas_arreglo=["Re-descargar KVUE 2026-10-13..10-29 (red)",
                     "Marcar en get_precios los saltos de más de 5 sesiones (rentabilidad multi-día) (sin red)",
                     "Corregir el mercado de ^W5000 a XNYS en el metadato (sin red)"])

    h(id="N11", titulo="21 tickers no llegan al corte; 14 se quedaron parados porque Yahoo revisó una sesión antigua",
      que_pasa=("21 ficheros acaban antes de la última sesión de su bolsa anterior al corte (los otros 38 que acaban el 2026-11-12 están bien: "
                "su cierre del 13 se publica después del corte). De los 21, 14 (casi todos suizos del núcleo: NESN, UBSG, ZURN…) se quedaron en "
                "septiembre–octubre porque el almacén rechazó el refresco al ver una sesión ya guardada cambiada; 4 son tickers reutilizados, "
                "uno es una fusión (PARA→SKYD), otro una compra (KVUE) y SNDK tuvo un refresco incompleto."),
      por_que_importa=("A esos 14 + SNDK les faltan 23–25 sesiones justo antes del corte: un agente que pida precios recientes verá un mes "
                       "parado (get_precios avisa «datos atrasados» en 20 de ellos). Son arreglables; los reutilizados y deslistados son limitación."),
      cifras={"no_llegan": int(len(no_llega_real)), "tabla_avisos": P["no_llega_tabla"], "acaban_el_12_por_publicacion": no_llega_1dia,
              "aviso_atraso_tools": P["atraso_tools_precios"]},
      desglose={k: v for k, v in causas_nl.items()},
      evidencia=f"{ev_p}: ultima vs curada_precios.ultima_sesion_esperada; precios_curados_avisos.csv tipo no_llega_corte (nota con el motivo)",
      gravedad_propuesta="importante",
      ideas_arreglo=["Re-descargar los 14 rechazados y SNDK aceptando solo las sesiones nuevas y registrando la revisión aparte (red)",
                     "Para PARA, redirigir al ticker SKYD en la lista curada (sin red)",
                     "Reutilizados (DWD, GR, GP, LU): limitación declarada; recortar el fichero al periodo del miembro real si se puede (sin red)"])

    h(id="N12", titulo="Los 8 ficheros que no pasan a precios curados son truncados de empresas que salieron del S&P 500",
      que_pasa=("AVB, BLY, EA, EQR, LEG, PSKY, QRVO y WBD tienen entre 1 y 13 sesiones en el crudo (Yahoo ya no da su historia porque se "
                "compraron o deslistaron), así que la lista curada los deja fuera por «truncado». Están en el 3b como limitación declarada."),
      por_que_importa=("Varios fueron miembros del S&P 500 durante años (EA, AVB, EQR, WBD, QRVO): su ausencia es sesgo de supervivencia en el "
                       "universo histórico. PSKY sí está cubierto vía SKYD."),
      cifras={"ficheros_crudo": P["ficheros_crudos"], "ficheros_curados": P["ficheros_curados"], "solo_en_crudo": len(P["solo_en_crudo"])},
      desglose={r["ticker"]: f"{r['sesiones']} sesiones ({r['desde']}..{r['hasta']})" for r in P["solo_en_crudo"]},
      evidencia=f"{ev_p}: diferencia de conjuntos de ficheros; lista_curada.yaml (regla truncado); descargas_3b_estado.csv (limitacion_declarada)",
      gravedad_propuesta="importante",
      ideas_arreglo=["Ya es limitación declarada (F3): cuantificar su peso en el S&P 500 por fecha para la memoria (sin red)",
                     "Fuente alternativa de deslistados solo si se reabre Q1 (red, posiblemente de pago)"])

    h(id="N13", titulo="Series paradas: el aviso de tools solo mira diarias y semanales; 4 mensuales/trimestrales de Eurostat están paradas sin avisar",
      que_pasa=("Con la regla de tools.py (diaria o semanal sin publicar más de max(10, 3×ritmo) días hábiles) salen 28 series al corte: 24 son "
                "series retiradas por la fuente (monedas antiguas del BCE, EONIA, TED, VXO…) y 4 activas sin refrescar (Bundesbank, oro, ^BCOM, ^W5000; "
                "las tres de Yahoo paradas en 2026-07-17). Mirando todas las frecuencias salen 37 activas paradas; la mayoría son por diseño, pero "
                "4 de Eurostat (RU parado en 2020 por el Brexit, HICP de EE. UU. en 2024-12) siguen como «activa» y la tool no avisa por ser mensuales o trimestrales."),
      por_que_importa=("Un agente puede usar como «último dato» un valor de hace años sin ningún aviso. Para el backtest no hay fuga, pero las "
                       "señales que dependen de esas series se congelan."),
      cifras={"umbral_tools": "MAX_DIAS_HABILES_ATRASO=10, MULTIPLO_RITMO=3, solo paso mediano <= 7 días",
              "aviso_tools_series": S["atraso_tools_n"], "retiradas_en_aviso": len(retiradas), "activas_en_aviso": len(activas_tools),
              "regla_propia_todas_frecuencias": S["parada_propia_n"], "regla_propia_activas": int(len(pp_act)),
              "regla_propia_mas_de_1_anio": S["parada_propia_mas_de_1_anio"]},
      desglose={"aviso_tools_por_fuente": S["atraso_tools_por_fuente"], "activas_por_grupo": {k: len(v) for k, v in grupos_pp.items()},
                "activas_sin_refrescar": activas_tools, "eurostat_paradas": grupos_pp.get("parada en la fuente sin marcar como retirada (Eurostat: RU tras el Brexit, HICP de EE. UU.)", [])},
      evidencia=f"{ev_s}: paradas() — tools._aviso_atraso_serie sobre la vista al corte (60 últimas referencias) + regla propia: atraso > lag mediano + 2 periodos + 10 días (cobertura_series.csv)",
      difiere_del_plan="El comentario de tools.py (MAX_DIAS_HABILES_ATRASO) aún dice que las acciones no estadounidenses llegan a octubre «hasta el 3b-2»: ya está hecho.",
      gravedad_propuesta="importante",
      ideas_arreglo=["Extender el aviso de atraso a series periódicas con umbral por frecuencia (p. ej. lag mediano + 2 periodos) (sin red)",
                     "Marcar como 'retirada' en el catálogo las de Eurostat del RU (sin red)",
                     "Refrescar GC=F, ^BCOM, ^W5000 y Bundesbank si la fuente lo permite (red; hoy limitación)"])

    top = [r for r in S["eda_huecos_top"] if r["serie"] not in ("ecb:MRO", "ecb:DFR")][:8]
    h(id="N14", titulo="Huecos largos internos (EDA): pocos y casi todos reales de la fuente",
      que_pasa=("El EDA marca 660 huecos en 81 series curadas. Quitando los tipos del BCE (son fechas de cambio, no huecos), los grandes son reales: "
                "la corona islandesa sin cambio oficial del BCE de 2008 a 2018, la letra a 1 año del Tesoro sin emitir de 2002 a 2008, el DGS20 de "
                "1987 a 1993, el tipo oficial de Japón de 2001 a 2006 y el papel comercial a 3 meses en la primavera de 2020. Los de 4–6 días son el 11-S y la Golden Week de 2019."),
      por_que_importa="No son errores, pero un agente que convierta a coronas islandesas o pida el 1Y de 2005 no tendrá dato. Ya llevan nota de hueco permanente cuando son de FRED.",
      cifras={"incidencias_hueco_curadas": S["eda_huecos_curadas_n"], "series": S["eda_huecos_curadas_series"],
              "con_fin_desde_2000": S["eda_huecos_curadas_desde2000"]},
      desglose={"por_fuente": S["eda_huecos_curadas_por_fuente"],
                "top": [{"serie": r["serie"], "desde": r["fecha"], "hasta": r["fecha_fin"], "periodos": r["tamano"]} for r in top]},
      evidencia=f"{ev_s}: huecos_eda() sobre eda_series_incidencias.csv y eda_series.csv, filtrado a las series de curada_resumen.csv",
      gravedad_propuesta="cosmetico",
      ideas_arreglo=["Para ISK, usar otra fuente del cambio 2008–2018 solo si hace falta (red)",
                     "Excluir ecb:MRO/DFR del detector de huecos (son series de eventos) (sin red)"])

    out = AQUI / "angulo1.json"
    out.write_text(json.dumps(H, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for x in H:
        print(f"{x['id']} | {x['gravedad_propuesta']} | {x['titulo']}")
    print("escrito", out)


if __name__ == "__main__":
    main("--rehacer" in sys.argv)
