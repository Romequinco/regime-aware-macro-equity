"""Monta angulo3.json (hallazgos) a partir de los a3_cifras_*.json que dejan las otras partes. Sin red ni D:.
Uso: python angulo3_hallazgos.py"""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
A = Path(__file__).resolve().parent


def cargar(n):
    return json.load(open(A / f"a3_cifras_{n}.json", encoding="utf-8"))


S, P, T, K, Z, L = (cargar(n) for n in ("series", "precios", "tools", "capas", "zonaeuro", "limitaciones"))
tests = {}
for nombre, f in (("tema_worktree", "a3_tests_tema.log"), ("tema_con_D", "a3_tests_tema_con_D.log"),
                  ("docs", "a3_tests_docs.log")):
    txt = (A / f).read_text(encoding="utf-8", errors="replace") if (A / f).exists() else ""
    linea = next((l for l in reversed(txt.splitlines()) if re.search(r"\d+ (passed|failed)", l)), "")
    tests[nombre] = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|errors?)", linea)}
snapD = {}
for a, b in (("a3_snap_antes.json", "a3_snap_despues.json"), ("a3_snap_antes2.json", "a3_snap_despues2.json")):
    if (A / a).exists() and (A / b).exists():
        x, y = json.load(open(A / a)), json.load(open(A / b))
        snapD[a] = {"ficheros": len(x), "cambiados": sum(1 for k in x if k in y and x[k] != y[k]),
                    "nuevos": sum(1 for k in y if k not in x), "borrados": sum(1 for k in x if k not in y)}

spr = P["sp500_recalculado"]
fx = P["fx_por_divisa"]
grp = L["por_grupo"]
H = []


def h(**kw):
    kw.setdefault("desglose", None)
    kw.setdefault("difiere_del_plan", None)
    H.append(kw)


# ------------------------------------------------------------------ CONSISTENCIA
h(id="C01", tipo="consistencia", titulo="Unidades y escalas: no queda ningún salto ×100 o ×1000 sin corregir",
  que_pasa=("Cada serie de la base curada tiene una sola unidad y una sola divisa. Las 6 series que cambiaban de "
            "escala entre vintages ya no saltan, y no aparece ningún salto puntual de ×100 o ×1000 lejos de cero. "
            "Los 3 avisos anuales que salen son movimientos reales (probabilidad de recesión en 2008, un índice "
            "cerca de cero)."),
  por_que_importa="Un ×1000 escondido rompe medias, z-scores y cualquier modelo sin avisar.",
  cifras={"series_curada": S["curada_series"], "series_con_mas_de_una_unidad": len(S["series_varias_unidades"]),
          "series_con_mas_de_una_divisa": len(S["series_varias_divisas"]),
          "pares_de_vintages_con_salto_de_escala": len(S["escala_vintage_restantes"]),
          "escaladas_por_vintage_sin_salto": len(S["escala_vintage_6_corregidas_sin_salto"]),
          "homogeneizadas": S["registro_homog_series"],
          "saltos_puntuales_x100_x1000_lejos_de_cero": S["salto_puntual_x100_x1000_lejos_cero"],
          "filas_x100_registro": S["registro_x100_filas"], "filas_x100_en_curada": S["registro_x100_filas_en_curada"],
          "series_que_siguen_en_tanto_por_uno": len(S["tanto_por_uno_restantes"])},
  desglose={"saltos_anuales_x50_revisados": len(S["salto_anual_x50_lejos_de_cero"]),
            "saltos_puntuales_cerca_de_cero_ignorados": S["salto_puntual_x100_x1000"]},
  evidencia="angulo3_series.py §1 (base_curada.parquet y registro_cambios.parquet); a3_out_series.txt",
  difiere_del_plan=("Las dos cifras de filas ×100 están bien: 34.116 en el registro de cambios y 34.029 en la base "
                    "curada (87 quedan fuera por el corte G2). La verificación cita la segunda y el 04 la primera."),
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Citar siempre «34.029 en la curada (34.116 en el registro)» (sin red, gratis)",
                 "ff:F3D.RF en % con todo |valor| ≤ 1 es correcto (tipo diario): documentarlo"])

h(id="C02", tipo="consistencia", titulo="Saltos de precio sin split: 1.651, casi todos en tickers ya marcados",
  que_pasa=(f"En los precios curados hay {P['saltos50_total']} días en los que el precio sube o baja más de un 50 % "
            f"sin split ni dividendo, en {P['saltos50_tickers']} tickers. {P['saltos50_en_sospechosas']} están en "
            f"tickers sospechosos y {P['saltos50_en_reutilizados']} en reutilizados (con aviso). Pero "
            f"{P['saltos50_tickers_sin_aviso_n']} tickers tienen {P['saltos50_sin_aviso_eventos']} saltos sin ningún "
            f"aviso, y {P['saltos_x10_sin_aviso']} de ellos son ×10 o ÷10, que huelen a error del proveedor."),
  por_que_importa=("Un ×10 falso en un solo día dispara volatilidades, momentum y drawdowns del backtest; en tickers "
                   "sin aviso nadie lo va a mirar."),
  cifras={"saltos_mas_50": P["saltos50_total"], "tickers": P["saltos50_tickers"], "saltos_x10": P["saltos50_x10"],
          "saltos_desde_2007": P["saltos50_desde2007"], "tickers_sin_aviso": P["saltos50_tickers_sin_aviso_n"],
          "saltos_sin_aviso": P["saltos50_sin_aviso_eventos"], "saltos_sin_aviso_desde_2007": P["saltos50_sin_aviso_desde2007"],
          "x10_sin_aviso": P["saltos_x10_sin_aviso"], "tickers_x10_sin_aviso": len(P["saltos_x10_sin_aviso_tickers"]),
          "contrasplits": P["contrasplits_eventos"], "tickers_con_contrasplit": P["contrasplits_tickers"],
          "splits_fraccionarios": P["split_fraccionario_eventos"],
          "tickers_con_split_fraccionario": P["split_fraccionario_tickers"]},
  desglose={"tickers_x10_sin_aviso": P["saltos_x10_sin_aviso_tickers"], "casos_de_la_sonda": P["casos_sonda"],
            "top_saltos_por_ticker": P["saltos50_top"]},
  evidencia="angulo3_precios.py (|close_t/close_t-1 − 1| > 0,5 sin split ni dividendo ese día ni el siguiente)",
  difiere_del_plan=("La sonda citaba saltos en NVDA (aquí 0) y contrasplits en XLF, EWJ, USO, ETHA y SAN.MC; en la "
                    "curada ninguno de esos tiene un salto > 50 %. Los de ^VIX (10) y CL=F (2, precio negativo de 2020) "
                    "son reales."),
  gravedad_propuesta="importante",
  ideas_arreglo=["Revisar a mano los 30 saltos ×10 sin aviso (17 tickers; muchos indios: ampliaciones «bonus» que "
                 "Yahoo no registra como split) y marcarlos o pasarlos a nulo (sin red)",
                 "Añadir el aviso «salto sin split» a la lista curada para los 163 tickers (sin red, gratis)",
                 "Contrastar una muestra con Stooq (gratis, con red)"])

h(id="C03", tipo="consistencia", titulo="Tickers reutilizados: marcados en la lista, pero la tool no lo avisa",
  que_pasa=(f"La lista curada marca {P['lista_reutilizados']} tickers del S&P 500 cuyo fichero es de otra empresa "
            "que usa hoy el mismo ticker. Los ficheros no mezclan dos empresas (ninguno tiene un hueco de más de un "
            "año), pero son de la empresa equivocada. Y get_precios(base='curada') los sirve sin decirlo: en LU y GR "
            "solo avisa de «datos atrasados»."),
  por_que_importa=("Un agente que pida los precios de un miembro histórico del S&P 500 (Lucent, Goodrich…) recibe "
                   "los de otra empresa y lo da por bueno."),
  cifras={"reutilizados_lista": P["lista_reutilizados"], "reutilizados_en_avisos_csv": P["avisos_reutilizado"],
          "tramos_reutilizados_3b1": 115, "reutilizados_con_hueco_mas_1_anio": len(P["reutilizados_con_hueco_365"]),
          "reutilizados_con_salto_mas_50": len(P["reutilizados_con_salto50"]),
          "recalculado_hoy_tickers": int(spr["tickers_reutilizados"]), "recalculado_hoy_tramos": int(spr["tramos_ticker_reutilizado"])},
  desglose={"en_la_lista_y_no_al_recalcular": P["reutilizados_lista_no_recalculados"],
            "avisos_de_get_precios_LU": T.get("LU", {}).get("avisos"), "avisos_de_get_precios_GR": T.get("GR", {}).get("avisos")},
  evidencia=("seleccion.cobertura_tramos_sp500 (marca: el fichero no solapa con ningún tramo o es de una clase que no "
             "puede ser miembro); config/lista_curada.yaml (aviso); tools.get_precios no lee los avisos de la lista; "
             "angulo3_tools.py"),
  difiere_del_plan=(f"Recalculado hoy con inventario_precios.csv salen {int(spr['tickers_reutilizados'])} tickers y "
                    f"{int(spr['tramos_ticker_reutilizado'])} tramos (frente a 112 y 115 del 3b-1): GENZ y GR cambian "
                    "por el inventario regenerado; la lista conserva los 112."),
  gravedad_propuesta="importante",
  ideas_arreglo=["Que get_precios devuelva el aviso de la lista curada (reutilizado, sospechosa, historia recortada) "
                 "(sin red, gratis)", "O sacar los reutilizados de la curada de precios (decisión D10)"])

h(id="C04", tipo="consistencia", titulo="Tickers sospechosos: la cifra buena es 37 (36 se quedan)",
  que_pasa=("Las tres cifras salen de sitios distintos y las tres son ciertas. 37 tickers llevan la marca en la "
            "lista curada; 36 se quedan (BLY sale). 36 los detecta el EDA (IBTS.L entra por otra vía); 35 llevan el "
            "aviso de tipo «serie sospechosa» en los precios curados (faltan BLY, que no tiene fichero, e IBTS.L)."),
  por_que_importa="Para la memoria del TFM hay que dar una sola cifra y decir de dónde sale.",
  cifras=P["sospechosas"], desglose=P["sospechosas_diferencias"],
  evidencia="eda_precios.csv, descargas_3b_estado.csv, lista_curada.yaml, precios_curados_avisos.csv",
  difiere_del_plan="El plan (estado del paso 3) decía 26: es de antes del 3b-2 (los UCITS y no estadounidenses).",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Citar «37 marcados (36 en la curada)» y explicar 35/36 en una nota (sin red)"])

al_nb = S["alias_def_nb04_lista"]
h(id="C05", tipo="consistencia", titulo="Alias con historia anterior a 2000: la cifra buena es 26",
  que_pasa=(f"{S['alias_antes_canonico_pub_base']} de {S['alias_n']} alias empiezan antes que su canónico y "
            f"{S['alias_antes_canonico_y_pre2000_pub_base']} de ellos antes de 2000: esa historia extra solo está en "
            f"la base de trabajo. En {S['alias_pre2000_canonico_desde_2000_pub_base']} casos el canónico ni siquiera "
            "llega a 2000, así que se pierde toda la historia previa (el más claro: fred:DFF, el tipo de los fondos "
            "federales desde 1954, alias de fred:EFFR, que empieza en 2000). 17 de los 26 son IPC y paro del Banco Mundial "
            "y de Eurostat cuyo canónico de la OCDE empieza en 1999-03."),
  por_que_importa="Medias largas, z-scores y comparaciones con crisis antiguas necesitan esa historia.",
  cifras={"alias": S["alias_n"], "empiezan_antes": S["alias_antes_canonico_pub_base"],
          "antes_y_pre2000": S["alias_antes_canonico_y_pre2000_pub_base"],
          "canonico_desde_2000": S["alias_pre2000_canonico_desde_2000_pub_base"],
          "por_periodo_de_referencia_antes": S["alias_antes_canonico_ref_curada"],
          "por_periodo_de_referencia_canonico_desde_2000": S["alias_pre2000_canonico_desde_2000_ref_curada"],
          "canonico_oecd_desde_1999": sum(1 for x in al_nb if x["pre2000"] and x["canonico"].startswith("oecd:"))},
  desglose={"pre2000_y_canonico_desde_2000": [f"{x['alias']}→{x['canonico']}" for x in al_nb
                                              if x["pre2000"] and x["canonico_desde_2000"]],
            "por_periodo_de_referencia": [f"{x['alias']}→{x['canonico']}" for x in S["alias_ref_lista"]]},
  evidencia="angulo3_series.py §3 (alias.parquet + primeras fechas en base_series y base_curada); misma definición que el 04",
  difiere_del_plan="El plan dice 25 (de antes del 3b-2); el 04 dice 27 y 26, que son las cifras actuales.",
  gravedad_propuesta="importante",
  ideas_arreglo=["Empalmar el alias antes del inicio del canónico (DFF antes de EFFR, Shiller antes de GS10) como "
                 "historia_previa, igual que las 9 que ya lo hacen (sin red, gratis)"])

h(id="C06", tipo="consistencia", titulo="Las tools leen la base de trabajo si no se les dice otra cosa",
  que_pasa=("get_serie y get_precios tienen base='trabajo' por defecto. La base curada (con las fechas prudentes, el "
            "corte del 2026-11-13 y las velas de relleno quitadas) solo se usa si se pide base='curada'."),
  por_que_importa=("El docstring dice que la curada «es la de los agentes y el backtest». Si un agente o un "
                   "notebook olvida el parámetro, usa fechas menos prudentes y datos posteriores al corte."),
  cifras={"tools_con_defecto_trabajo": 2, "filas_base_trabajo": S["base_filas"], "filas_base_curada": S["curada_filas"]},
  evidencia="src/ingesta/mercados_series/tools.py: get_serie(..., base='trabajo'), get_precios(..., base='trabajo')",
  gravedad_propuesta="importante",
  ideas_arreglo=["Cambiar el defecto a 'curada' o exigir el parámetro en las tools de los agentes (sin red)"])

usx, twd, cny = fx.get("USX", {}), fx.get("TWD", {}), fx.get("CNY", {})
h(id="C07", tipo="consistencia", titulo="Conversión a USD: tres futuros sin FX y el dólar taiwanés congelado en 2020",
  que_pasa=("Los futuros de maíz, soja y trigo cotizan en centavos (USX) y divisas.py no conoce esa subunidad: en USD "
            "salen todos nulos. El BCE dejó de publicar el dólar taiwanés el 2020-10-30 y la tool convierte seis años "
            "de 2330.TW y ^TWII con aquel fixing viejo (avisa, pero el número sale). Lo del yuan es menor: solo faltan "
            "las sesiones anteriores a 2000."),
  por_que_importa="get_precios convierte a USD por defecto: el agente recibe nulos o un cambio de hace seis años.",
  cifras={"usx_tickers": usx.get("tickers"), "usx_sesiones_sin_fx": usx.get("sin_fx"),
          "twd_tickers": twd.get("tickers"), "twd_sesiones_con_fixing_caducado_por_ticker": next((int(m.group(1)) for a in T.get("^TWII", {}).get("avisos", [])
                                                         for m in [re.search(r"(\d+) filas en TWD posteriores", a)] if m), None),
          "usx_ZC_sesiones_nulas_en_USD": T.get("ZC=F", {}).get("sin_fx"),
          "twd_sesiones_fuera_del_rango_fx": twd.get("sin_fx"), "cny_tickers": cny.get("tickers"),
          "cny_sesiones_sin_fx": cny.get("sin_fx"), "cny_sesiones_sin_fx_desde_2007": cny.get("sin_fx_desde_2007")},
  desglose={"pct_sesiones_sin_fx_por_divisa": {k: v["pct_sin_fx"] for k, v in fx.items()},
            "fixing_bce_TWD": P["fx_rangos"].get("TWD"), "fixing_bce_CNY": P["fx_rangos"].get("CNY")},
  evidencia=("angulo3_tools.py: get_precios('ZC=F', base='curada', divisa='USD') → 6.588 de 6.588 nulas, aviso "
             "«no hay serie del BCE ecb:EXR.D.USX.EUR»; 2330.TW y ^TWII → 1.465 filas posteriores al último fixing "
             "(2020-10-30); universo.py sí tiene USX en SUBUNIDADES, divisas.py no"),
  difiere_del_plan=("El plan apunta «USD de las series en CNY sin fixing» como pendiente menor: el CNY solo pierde "
                    "618 sesiones anteriores a 2000; lo grave es USX y TWD, que no están en el plan."),
  gravedad_propuesta="importante",
  ideas_arreglo=["Añadir USX → (USD, 100) a divisas.SUBUNIDADES (sin red, gratis)",
                 "FX secundario de la Fed H.10 en FRED (DEXTAUS para TWD, DEXCHUS para CNY): gratis, con red; ya "
                 "previsto como PENDIENTE en el docstring de divisas.py"])

h(id="C08", tipo="consistencia", titulo="Capas de fecha: 1.426.536 filas retrasadas, ninguna adelantada",
  que_pasa=("Se confirma la cifra del plan: 1.426.536 filas de la base curada tienen la fecha de publicación más "
            "tarde que la original y 0 más temprano. Casi todo es un día de margen en datos diarios de mercado. Los "
            "retrasos de años son reales: datos publicados por primera vez cuando la fuente nació (Ken French, OFR, "
            "NFCI, Sahm)."),
  por_que_importa="Garantiza que el backtest no ve el futuro; a cambio, en algunos sitios se pierde información.",
  cifras={"retrasadas_en_curada": S["retrasadas_en_curada"], "adelantadas": S["adelantadas_registro"],
          "retraso_mas_30_dias": S["retraso_mas_30d"], "pct_de_esas_antes_de_2000": S["retraso_mas_30d_pre2000_pct"],
          "retraso_mas_365_dias_desde_2007": S["retraso_mas_365d_desde2007"], "con_tope_primer_vintage": S["con_tope"]},
  desglose={g: {"filas": v["filas"], "mediana": v["mediana"], "p90": v["p90"]} for g, v in S["retraso_por_grupo"].items()},
  evidencia="angulo3_series.py §6 y angulo3_capas.py (registro_cambios.parquet, en_base_curada y retraso_dias > 0)",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Nada que arreglar en la cifra; ver C09 para los retrasos que parecen excesivos"])

big = K["reglas_retraso_grande_2007"]
h(id="C09", tipo="consistencia", titulo="Prudencia que cuesta información: paro semanal con 8 semanas de retraso en 2007-2009",
  que_pasa=("En el tramo «no fiable» (antes de que ALFRED tenga vintages), algunas reglas retrasan mucho más de lo que "
            "tarda de verdad la publicación. Las peticiones de paro semanal (ICSA) se publican a los 5 días y la curada "
            "las retrasa hasta 61 (×12) de 2007-01 a 2009-05; las continuadas, de 13 a 68 hasta 2009-08. Las "
            "expectativas de inflación de Cleveland pasan de 31 a 109 días hasta 2021-09, y CFNAI y vivienda nueva "
            "doblan su retraso. El tipo oficial de Australia (tabla F1, 1 día medido) usa la regla de 7 días de la tabla F2."),
  por_que_importa=("Justo en la crisis de 2008 el agente vería el paro con dos meses de retraso: las señales de "
                   "recesión llegan tarde y el backtest sale peor de lo que sería en tiempo real."),
  cifras={"reglas_con_retraso_mediano_14d_y_doble": len(big), "filas_afectadas_2007": K["filas_reglas_retraso_grande_2007"],
          "icsa_lag_original_dias": 5, "icsa_lag_curado_dias": 61, "claims_continuadas_lag_original": 13,
          "claims_continuadas_lag_curado": 68, "rba_filas_2007": next((x["filas"] for x in K["mercado_diario_por_regla_2007"]
                                                                       if x["regla"] == "rba_diario"), None),
          "mercado_diario_2007_mediana": K["mercado_diario_2007"]["mediana"],
          "mercado_diario_2007_p90": K["mercado_diario_2007"]["p90"]},
  desglose={k.split("/")[-1]: {"filas": int(v["filas"]), "retraso_mediano": v["retraso_med"], "lag_antes": v["lag_antes_med"],
                               "lag_despues": v["lag_despues_med"]} for k, v in big.items()},
  evidencia="angulo3_capas.py (ventana 2007+, sin reconstruidas; lag = fecha_publicacion − fecha_referencia, mediana)",
  gravedad_propuesta="importante",
  ideas_arreglo=["Para ICSA y continuadas, usar el calendario del DOL (jueves siguiente) + margen pequeño en vez de "
                 "«regla + adelanto máximo + margen» (sin red: el calendario ya está en publicaciones.yaml)",
                 "Separar rba:FIRMMCRTD (F1) de la regla de 7 días de la F2 (sin red)",
                 "Prueba de robustez del backtest con la fecha normal, ya prevista en D2"])

h(id="C10", tipo="consistencia", titulo="Verificaciones en 0 y tests en verde, pero en el worktree no se prueban los datos",
  que_pasa=("Las 13 verificaciones de series y las 13 de precios siguen en 0 fallos (una «no aplica»). La suite del "
            f"tema pasa en el worktree ({tests.get('tema_worktree', {}).get('passed')} bien, "
            f"{tests.get('tema_worktree', {}).get('skipped')} saltados), pero sin .env el corpus apunta a una carpeta "
            "vacía del worktree y los tests de datos reales se saltan. Con INGESTA_CORPUS_DIR=D:/tfm_corpus: "
            f"{tests.get('tema_con_D', {}).get('passed')} bien, {tests.get('tema_con_D', {}).get('failed', 0)} fallan, "
            f"{tests.get('tema_con_D', {}).get('skipped')} saltados. Ningún test escribió en D:."),
  por_que_importa="Un «todo verde» sin los tests de datos no prueba la base real.",
  cifras={"verificaciones_series_0": 13, "verificaciones_precios_0": 12, "verificaciones_no_aplica": 1,
          "tests_worktree": tests.get("tema_worktree"), "tests_con_D": tests.get("tema_con_D"),
          "tests_docs_y_estructura": tests.get("docs"), "ficheros_D_cambiados_por_los_tests": snapD},
  evidencia="curada_verificaciones.csv, precios_curados_verificaciones.csv, a3_tests_*.log, a3_snap_*.json",
  difiere_del_plan="El plan habla de «1.270 tests en verde»; hoy se recogen 1.287 (1.217 + 70 saltados en el worktree).",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Fallar en vez de saltar los tests de datos cuando falta INGESTA_CORPUS_DIR en la máquina con el "
                 "corpus, o avisar en la salida (sin red)", "Los tests crean <worktree>/corpus vacío: inofensivo, pero "
                 "confunde"])

h(id="C11", tipo="consistencia", titulo="Cifras desfasadas en el plan y en los notebooks",
  que_pasa=("Varias cifras del plan son de antes del 3b-2 y no cuadran con el estado final. Ninguna es un error de "
            "datos: son textos sin actualizar."),
  por_que_importa="El plan se destila en el README y en la memoria: las cifras viejas acabarían en el TFM.",
  cifras={"proyecciones_plan": 243, "proyecciones_reales": 309, "alias_previos_plan": 25, "alias_previos_reales": 26,
          "sospechosos_plan_paso3": 26, "sospechosos_reales": 37, "historia_recortada_estado_3b": P["ucits_historia_recortada_estado_3b"],
          "historia_recortada_avisos": P["ucits_historia_recortada_avisos"], "filas_base_manifiesto": 10232074,
          "filas_base_parquet": S["base_filas"], "sp500_pct_tabla": 67.78, "sp500_pct_recalculado": spr["pct_dias_tramo_cubiertos"]},
  desglose={"historia_recortada_solo_en_avisos": P["ucits_historia_recortada_solo_avisos"]},
  evidencia=("registro_descarga.md (tabla de salidas del paso 4 y estado), curada_manifiesto.json (filas_base = lo que lee "
             "curar tras filtrar), descargas_3b_estado.csv (16 instrumentos) frente a precios_curados_avisos.csv (18)"),
  difiere_del_plan="Sí: 243→309, 25→26, 26→37, 18 avisos frente a 16 en el estado del 3b (CSPX.L y ^KS11 solo en avisos)",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Regenerar las cifras del plan desde las tablas antes de destilarlo en el README (sin red)"])

# ------------------------------------------------------------------ LIMITACIONES
h(id="L01", tipo="limitaciones", titulo="Las 124 limitaciones declaradas: 13 causas, 119 ids distintos",
  que_pasa=("El estado del 3b cuadra: 48 hechos, 1 parcial, 3 resueltos, 124 limitaciones y 1 aplazado (177 filas). "
            "Las 124 filas son 119 cosas distintas (DWD y GR salen tres veces, BLY dos). Casi el 60 % son dos causas: "
            "37 tickers sospechosos y 34 ediciones antiguas del WEO."),
  por_que_importa="Es la lista de lo que el dataset no puede dar; la memoria debe agruparla por causa, no por fila.",
  cifras={"estado_3b": L["estado_3b"], "limitaciones": L["limitaciones"], "ids_unicos": L["limitaciones_ids_unicos"]},
  desglose={g: v["filas"] for g, v in grp.items()},
  evidencia="angulo3_limitaciones.py → angulo3_limitaciones.csv (una fila por limitación con su grupo)",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=[f"{v['titulo']}: {v['idea']}" for g, v in grp.items()])

h(id="L02", tipo="limitaciones", titulo="Sesgo de supervivencia del S&P 500: 67,8 % de los días-tramo con precio",
  que_pasa=("De todos los días que cada empresa estuvo en el S&P 500 desde 1996, solo el 67,8 % tiene precio de esa "
            "empresa (67,9 % recalculado hoy). Mejora con el tiempo: 78,7 % desde 2007 y 88,5 % desde 2016. El día de "
            "Lehman (2008-09-15) solo 305 de 498 miembros tienen precio; de 759 empresas que salieron del índice, 591 no "
            "tienen el precio del miembro."),
  por_que_importa=("Las empresas que quebraron o fueron compradas faltan justo en las crisis: un backtest de acciones "
                   "del S&P 500 antes de 2016 sale demasiado bueno."),
  cifras={"pct_dias_tramo": 67.78, "pct_recalculado": spr["pct_dias_tramo_cubiertos"],
          "pct_desde_2007": P["sp500_pct_dias_desde_2007"], "pct_desde_2016": P["sp500_pct_dias_desde_2016"],
          "lehman_miembros": P["sp500_miembros_2008-09-15"][0], "lehman_con_precio": P["sp500_miembros_2008-09-15"][1],
          "2016_miembros": P["sp500_miembros_2016-01-04"][0], "2016_con_precio": P["sp500_miembros_2016-01-04"][1],
          "tramos_cerrados": P["sp500_tramos_cerrados"], "tramos_cerrados_sin_precio_del_miembro": P["sp500_tramos_cerrados_sin_precio"],
          "tramos_sin_fichero": int(spr["tramos_sin_fichero"])},
  evidencia="seleccion.cobertura_tramos_sp500 re-ejecutada (función pura) sobre constituyentes/sp500.parquet e inventario_precios.csv",
  gravedad_propuesta="importante",
  ideas_arreglo=["Tiingo (plan gratuito, guarda deslistados con identificador propio) o Stooq: gratis, con red, a verificar",
                 "CRSP vía WRDS si la universidad da acceso", "Si no: restringir las acciones al universo de cada "
                 "fecha con aviso y medir el sesgo en la memoria"])

h(id="L03", tipo="limitaciones", titulo="WEO: 34 ediciones antiguas sin fuente accesible",
  que_pasa=("Del WEO del FMI solo están las ediciones 2025-04, 2025-10 y 2026-04 (y 2026-10 en la API). Las 34 "
            "anteriores (2008-04 a 2024-10) no se pueden bajar: la web del FMI responde 403 al robots.txt y DBnomics "
            "está descartado."),
  por_que_importa="Sin ediciones viejas, las proyecciones del WEO no se pueden usar en el backtest antes de 2025.",
  cifras={"ediciones_faltan": grp["WEO_ediciones"]["filas"], "ediciones_disponibles": 3, "series_proyeccion_weo": 306},
  evidencia="descargas_3b_estado.csv (tipo ediciones)",
  gravedad_propuesta="importante",
  ideas_arreglo=[grp["WEO_ediciones"]["idea"]])

h(id="L04", tipo="limitaciones", titulo="Tickers sospechosos y reutilizados: sin identificador permanente",
  que_pasa=(f"{grp['sospechosas']['filas']} tickers con el historial roto y {P['lista_reutilizados']} reutilizados se "
            "quedan con aviso. Sin un identificador que no cambie (PERMNO, CIK) no se puede traer el miembro de verdad."),
  por_que_importa="Son exactamente los casos que más distorsionan un backtest de acciones.",
  cifras={"sospechosos": grp["sospechosas"]["filas"], "reutilizados": P["lista_reutilizados"],
          "filas_sp500_supervivencia": grp["sp500_supervivencia"]["filas"]},
  evidencia="angulo3_limitaciones.csv (grupos sospechosas y sp500_supervivencia)",
  gravedad_propuesta="importante", ideas_arreglo=[grp["sospechosas"]["idea"], grp["sp500_supervivencia"]["idea"]])

h(id="L05", tipo="limitaciones", titulo="Bundesbank: el 10 años alemán parado en 2026-10-13",
  que_pasa=("La web del Bundesbank pone un reto anti-bots y no se esquiva. La serie se queda con lo bajado el "
            "2026-10-13: un mes antes del corte."),
  por_que_importa="La tool avisa de datos atrasados, pero el último mes del dataset no tiene el Bund diario.",
  cifras={"series": 1, "ultima_fecha": "2026-10-13", "filas_en_curada": 7408},
  evidencia="descargas_3b_estado.csv (refresco:bundesbank); registro_cambios (bundesbank_diario 7.408 filas)",
  gravedad_propuesta="cosmetico", ideas_arreglo=[grp["bundesbank"]["idea"]])

h(id="L06", tipo="limitaciones", titulo="UCITS: 18 con historia recortada y 23 poco parecidos a su ETF de EE. UU.",
  que_pasa=(f"En {P['ucits_historia_recortada_avisos']} instrumentos Yahoo empieza más tarde que el lanzamiento real "
            f"(hasta 2.039 días menos). En {P['ucits_corr_baja']} la correlación semanal con su equivalente de EE. UU. "
            f"baja de 0,90, así que no sirven como sustituto. Además {P['no_llega_corte']} ficheros no llegan al corte."),
  por_que_importa="La cartera europea y el mapeo UCITS dependen de estos instrumentos.",
  cifras={"historia_recortada": P["ucits_historia_recortada_avisos"], "historia_recortada_en_estado_3b":
          P["ucits_historia_recortada_estado_3b"], "correlacion_menor_090": P["ucits_corr_baja"],
          "no_llegan_al_corte": P["no_llega_corte"]},
  evidencia="precios_curados_avisos.csv (aviso_lista y no_llega_corte)",
  gravedad_propuesta="cosmetico", ideas_arreglo=[grp["universo_ucits"]["idea"], grp["yahoo_revisa"]["idea"]])

h(id="L07", tipo="limitaciones", titulo="Zona euro: 6 series cuentan siempre con todos los países de hoy",
  que_pasa=(f"De {Z['series_zona_euro']} series de la zona euro o la UE en la curada, {len(Z['cambiante'])} siguen la "
            "composición oficial de cada fecha (BCE U2 y Eurostat EA). En 6 la composición es la de hoy hacia atrás y "
            "sí importa: el ESI EA20, el IPC y el paro EA20 de la OCDE, los dos agregados EMU del Banco Mundial y la "
            "brecha de crédito del BIS."),
  por_que_importa="Antes de 2015 mezclan países que aún no estaban en el euro: diferencias pequeñas pero no causales.",
  cifras={"series_zona_euro_ue": Z["series_zona_euro"], "cambiante": len(Z["cambiante"]),
          "fija_donde_importa": len(Z["fija_donde_importa"])},
  desglose={"fija_donde_importa": Z["fija_donde_importa"], "cambiante": Z["cambiante"]},
  evidencia="angulo3_zonaeuro.py (clasificación por el código de área del id)",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Preferir la versión U2/EA cuando exista (BCE SDW, gratis) y marcar las EA20 con aviso (sin red)"])

h(id="L08", tipo="limitaciones", titulo="Cartera: la 60/40 europea aplazada y los baselines sin rehacer",
  que_pasa=("La 60/40 europea está aplazada: hay precios de CSPX.L y EUNA.DE, pero el empalme con el sustituto previo "
            "se decide al construir las carteras. Además todos los baselines (6 estrategias) se calcularon el "
            "2026-10-13 con la base de trabajo y acaban el 2026-10-12, antes del corte y sin la curada; la 60/40 UCITS "
            "solo empieza en 2017-11 y no tiene versión con costes."),
  por_que_importa="Las referencias con las que se compara a los agentes no salen del mismo dataset que ellos usan.",
  cifras={"estrategias": 6, "fin_baselines": "2026-10-12", "inicio_6040_ucits": "2017-11-30", "estado_3b": "aplazado"},
  evidencia="D:/tfm_corpus/mercados_series/cartera/*.parquet (solo estrategia, variante y fechas); descargas_3b_estado.csv",
  gravedad_propuesta="importante",
  ideas_arreglo=["Rehacer los baselines con base='curada' hasta el corte (sin red)",
                 "Empalmar EUNA.DE con BNDX antes de 2017-11 y declararlo (sin red)"])

h(id="L09", tipo="limitaciones", titulo="Cobertura: 65 % de las series se pueden ver desde 2000",
  que_pasa=(f"{S['curada_series_pub_desde_2000']} de {S['curada_series']} series curadas ({S['curada_pct_series_pub_desde_2000']} %) "
            "tienen algo publicado antes del 2001-01-02. Por fecha de referencia serían el "
            f"{S['curada_pct_series_ref_desde_2000']} %: la diferencia es historia que existe pero se publicó más "
            "tarde (Ken French, Goyal-Welch, OFR, curvas del BCE, WEO)."),
  por_que_importa="La ventana 2007–2026 necesita años de historia previa para medias y z-scores.",
  cifras={"series_desde_2000": S["curada_series_pub_desde_2000"], "pct": S["curada_pct_series_pub_desde_2000"],
          "pct_por_referencia": S["curada_pct_series_ref_desde_2000"]},
  desglose=S["desde_2000_por_fuente"],
  evidencia="angulo3_series.py §5 (primera fecha_publicacion de cada serie de la curada ≤ 2001-01-02, criterio D1)",
  gravedad_propuesta="cosmetico",
  ideas_arreglo=["Ninguno que no sea inventar fechas: es una limitación real; documentar por fuente"])

h(id="L10", tipo="limitaciones", titulo="Series que la fuente no publica y vintages sin fuente",
  que_pasa=("Eurostat no publica el ESI ni el paro de la zona euro cambiante; la OCDE no publica el CLI EA20 ni el "
            "paro de China. Tampoco hay historia de revisiones gratis del BCE, Eurostat, BIS y Banco Mundial: sus "
            "valores son los de hoy con una regla de fecha. Las 3 de Philadelphia no son una pérdida (ALFRED ya las cubre)."),
  por_que_importa="La macro europea se ve «revisada»: el backtest conoce datos mejores que los que había en su día.",
  cifras={"no_publicadas": grp["no_publicadas"]["filas"], "philly_por_diseno": grp["philly_por_diseno"]["filas"],
          "vintages_sin_fuente": grp["vintages"]["filas"], "calendarios_sin_verificar": grp["calendarios"]["filas"]},
  evidencia="angulo3_limitaciones.csv", gravedad_propuesta="importante",
  ideas_arreglo=[grp["no_publicadas"]["idea"], grp["vintages"]["idea"], grp["calendarios"]["idea"]])

json.dump(H, open(A / "angulo3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(f"ok: angulo3.json con {len(H)} hallazgos")
for x in H:
    print(f"  {x['id']} [{x['gravedad_propuesta']}] {x['titulo']}")
