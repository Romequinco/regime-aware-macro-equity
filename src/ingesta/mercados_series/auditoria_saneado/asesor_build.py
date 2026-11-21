import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
# -*- coding: utf-8 -*-
"""Construye asesor.json y asesor.md a partir de la agrupación del asesor (sin valores de series)."""
import json
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).parent


def op(id, etiqueta, clase, coste, red, riesgo, beneficio, recomendada=False, url=None):
    d = {"id": id, "etiqueta": etiqueta, "clase": clase, "coste": coste, "red": red,
         "riesgo": riesgo, "beneficio": beneficio, "recomendada": recomendada}
    if url:
        d["fuente_url"] = url
    return d


def g(titulo, etiquetas, valores, sufijo=""):
    return {"titulo": titulo, "etiquetas": etiquetas, "valores": valores, "sufijo": sufijo}


NADA_DECLARAR = "No hacer nada y dejarlo como limitación declarada"

P = []

# ---------------------------------------------------------------- BLOQUEANTES
P.append(dict(
    origen=["C06"], tipo="consistencia", gravedad="bloqueante",
    titulo="Las tools leen la base de trabajo si no se les dice nada",
    que_pasa="get_serie y get_precios usan base='trabajo' por defecto. La base de trabajo no lleva las fechas prudentes "
             "del curado ni el corte: 1.426.536 filas que la curada retrasa salen antes, y hay 14.849 filas posteriores "
             "al 2026-11-13. Basta con olvidar el parámetro para que un agente o el backtest vea datos antes de tiempo.",
    por_que_importa="Es el agujero más directo del TimeGate: no hace falta un error de datos, solo un olvido. Los "
                    "baselines de cartera ya se hicieron así (ver P18).",
    cifras={"tools con el defecto peligroso": 2, "filas que la curada retrasa": 1426536,
            "filas de la base de trabajo tras el corte": 14849, "series con filas tras el corte": 828},
    grafico=None,
    opciones=[
        op("a", "No hacer nada y explicarlo en el README", "nada", "≈10 min, sin red", False,
           "alto: un solo olvido mete fechas optimistas y datos posteriores al corte", "ninguno"),
        op("b", "Cambiar el defecto a base='curada' y pedir 'trabajo' a mano solo en los módulos que construyen la base",
           "codigo", "≈1–2 h, sin red", False,
           "medio: puede romper llamadas internas o tests que contaban con el defecto; los tests lo detectan",
           "agentes y backtest usan siempre la curada salvo que pidan otra cosa", True),
        op("c", "Quitar el defecto: obligar a pasar base en cada llamada", "codigo", "≈2–3 h, sin red", False,
           "medio: rompe más llamadas (hay que tocarlas todas)", "lo más explícito; ninguna llamada ambigua"),
    ],
    recomendacion="La opción b cierra el agujero con poco trabajo y deja la base de trabajo para quien construye. La c "
                  "es más estricta, pero obliga a tocar más código sin ganar seguridad para los agentes.",
))
P.append(dict(
    origen=["C03", "L04", "N11"], tipo="consistencia", gravedad="bloqueante",
    titulo="Tickers reutilizados: precios de otra empresa sin aviso en la tool",
    que_pasa="112 tickers del S&P 500 histórico tienen en su fichero la cotización de otra empresa que hoy usa ese "
             "símbolo (p. ej. GR o LU). Están marcados en la lista curada y en la tabla de avisos, pero "
             "get_precios(base='curada') no devuelve esa marca: de LU solo dice «datos atrasados». Ningún fichero "
             "mezcla dos empresas.",
    por_que_importa="Un agente que pida el precio de un miembro antiguo recibe el de otra compañía sin saberlo. En un "
                    "backtest con acciones serían rentabilidades de la empresa equivocada.",
    cifras={"reutilizados marcados": 112, "recalculados hoy (tickers)": 110, "recalculados hoy (tramos)": 113,
            "reutilizados con saltos de más del 50 %": 23, "reutilizados o fusionados entre los 21 sin corte": 5},
    grafico=None,
    opciones=[
        op("a", "No hacer nada: la marca ya está en la lista curada", "nada", "0 h", False,
           "alto: la tool, que es lo que usan los agentes, no la enseña", "ninguno"),
        op("b", "Que get_precios devuelva el aviso de la lista curada (reutilizado, sospechoso, historia recortada, "
                "UCITS poco parecido) y redirigir PARA a SKYD", "codigo", "≈1 h, sin red", False,
           "bajo: solo añade avisos; no cambia ningún precio",
           "el aviso llega a quien usa el dato; sirve también para P11 y P26", True),
        op("c", "Sacar los 112 de los precios curados", "recalculo", "≈1 h, sin red", False,
           "medio: el fichero es válido para la empresa de hoy y otros temas pueden necesitarlo",
           "imposible usarlos por error"),
    ],
    recomendacion="Con el aviso (b) el dato sigue disponible para la empresa correcta y nadie lo usa a ciegas. La "
                  "pertenencia al índice por fecha ya impide que entren en el backtest fuera de su tramo.",
))
P.append(dict(
    origen=["C07"], tipo="consistencia", gravedad="bloqueante",
    titulo="Dólar taiwanés congelado en 2020 al pasar a USD",
    que_pasa="El BCE dejó de publicar el TWD el 2020-10-30. Desde entonces get_precios(divisa='USD') convierte "
             "2330.TW y ^TWII con ese último cambio: 1.465 sesiones por ticker. Hay aviso, pero el número sale como si "
             "fuera bueno. El código usa el último cambio visible sin límite de antigüedad, así que lo mismo pasaría con "
             "cualquier divisa que el BCE deje de publicar.",
    por_que_importa="Seis años de rentabilidades en USD falsas en dos activos de Taiwán; el backtest no lo nota.",
    cifras={"tickers afectados": 2, "sesiones por ticker con cambio caducado": 1465,
            "último cambio del BCE": "2020-10-30", "sesiones en TWD sin FX": "25,8 %"},
    grafico=None,
    opciones=[
        op("a", "No hacer nada: ya hay aviso", "nada", "0 h", False,
           "alto: el valor convertido es falso", "ninguno"),
        op("b", "Tope de antigüedad del cambio (p. ej. más de 5 días hábiles → vacío con aviso)", "codigo",
           "≈1 h, sin red", False, "bajo: TWD queda vacío desde 2020 (los dos tickers, sin USD)",
           "nunca más un cambio viejo, en ninguna divisa"),
        op("c", "Tope de b + cambio secundario de la Fed (H.10) en FRED: DEXTAUS para TWD (y DEXCHUS para CNY), con "
                "su calendario", "alternativa", "≈3–4 h, con red (FRED, que ya usamos)", True,
           "medio: H.10 se publica una vez por semana; hay que darle una fecha de publicación prudente",
           "TWD convertido bien desde 2020; ya estaba previsto como PENDIENTE en divisas.py", True,
           "https://fred.stlouisfed.org/series/DEXTAUS"),
    ],
    recomendacion="La c arregla el dato y además pone el tope de b para todas las divisas. Si no hay tiempo, b como "
                  "mínimo: mejor vacío que falso.",
))
P.append(dict(
    origen=["C07"], tipo="consistencia", gravedad="bloqueante",
    titulo="Tres futuros en centavos de dólar salen vacíos en USD",
    que_pasa="ZC=F, ZS=F y ZW=F (maíz, soja y trigo) cotizan en USX, centavos de dólar. universo.py lo conoce, pero "
             "divisas.SUBUNIDADES no, así que get_precios(divisa='USD') los devuelve vacíos: 6.588 de 6.588 sesiones en "
             "ZC=F y 19.768 en los tres.",
    por_que_importa="Las materias primas agrícolas desaparecen de cualquier cartera o señal en USD.",
    cifras={"tickers": 3, "sesiones vacías en USD": 19768, "sesiones vacías en ZC=F": "6.588 de 6.588",
            "sesiones sin FX en USX": "100 %"},
    grafico=None,
    opciones=[
        op("a", "Pedir esos tres siempre con divisa='original'", "nada", "0 h", False,
           "medio: depende de que todos se acuerden", "ninguno"),
        op("b", "Añadir USX → (USD, 100) a SUBUNIDADES y un test", "codigo", "≈15 min, sin red", False,
           "bajo: mismo mecanismo que GBp", "los tres futuros convertidos bien", True),
    ],
    recomendacion="Es una línea de código con su test; no hay motivo para no hacerlo.",
))
P.append(dict(
    origen=["L02", "N12", "L04"], tipo="limitaciones", gravedad="bloqueante",
    titulo="Sesgo de supervivencia en el S&P 500 histórico",
    que_pasa="Con solo Yahoo (F3) faltan muchas empresas que salieron del índice. Tienen precio el 67,8 % de los "
             "días-tramo (78,7 % desde 2007). El día de Lehman, solo 305 de 498 miembros. Otros 8 ficheros truncados "
             "quedan fuera. Es bloqueante si la cartera de la Fase 4 elige acciones sueltas; con índices y ETF no afecta.",
    por_que_importa="Un backtest con acciones del S&P 500 solo vería a las supervivientes y saldría mejor de lo real. "
                    "Sin medirlo y sin una regla fija, el resultado no es honesto.",
    cifras={"días-tramo con precio": "67,78 %", "desde 2007": "78,68 %", "desde 2016": "88,52 %",
            "miembros con precio el 2008-09-15": "305 de 498", "tramos cerrados sin precio": "591 de 759",
            "ficheros fuera por truncados": 8},
    grafico=g("Días-tramo del S&P 500 con precio", ["Toda la historia", "Desde 2007", "Desde 2016"],
              [67.78, 78.68, 88.52], " %"),
    opciones=[
        op("a", NADA_DECLARAR + " (F3), sin más", "nada", "0 h", False,
           "alto: resultado sesgado sin cifra que lo acote", "ninguno"),
        op("b", "Medir el sesgo y fijar la regla: en cada fecha, solo miembros con precio y con aviso; la cartera "
                "principal con índices y ETF, y las acciones como prueba aparte con el sesgo medido",
           "recalculo", "≈3–4 h, sin red", False, "bajo: no cambia datos; fija cómo se usan",
           "backtest honesto y una cifra clara para la memoria", True),
        op("c", "Precios de deslistados del plan gratis de Tiingo (contradice F3 «solo Yahoo»)", "alternativa",
           "≈1 día, con red y registro", True,
           "medio: licencia «solo uso personal interno» (no se puede compartir con el equipo), 500 símbolos al mes y "
           "sin confirmar que traiga deslistados", "podría cubrir parte de los huecos",
           url="https://www.tiingo.com/about/pricing"),
    ],
    recomendacion="La b respeta F3 y hace el backtest defendible. La c choca con F3 y con su licencia. CRSP por WRDS "
                  "solo tendría sentido si la universidad lo diera, y también contradice F3.",
))

# ---------------------------------------------------------------- IMPORTANTES
P.append(dict(
    origen=["N11", "F03", "L06", "N10"], tipo="frescura", gravedad="importante",
    titulo="17 tickers sin refrescar por una vela retocada o un fallo de descarga",
    que_pasa="21 tickers no llegan al corte. En 14 (11 suizos, NESN.SW y UBSG.SW entre ellos, más JD.L, EXO.AS y 000001.SS) Yahoo "
             "retocó una vela antigua y el almacén rechazó el ticker entero: les faltan 23–25 sesiones. SNDK tiene un "
             "hueco del 2026-10-14 al 11-16 y KVUE, 13 sesiones antes de su última vela. Los otros 5 (GP, LU, PARA, "
             "DWD y GR) son reutilizados o muertos (ver P02).",
    por_que_importa="Falta el último mes de grandes europeas. Y en cada refresco quedarán más tickers atrás, porque "
                    "Yahoo retoca velas a menudo (ya se toleraron 1.361 revisiones de volumen y dividendo en 476 tickers).",
    cifras={"no llegan al corte": 21, "por una vela retocada": 14, "sesiones que les faltan": "23–25",
            "SNDK, sesiones de hueco": 23, "KVUE, sesiones de hueco": 13, "la tool avisa en": "20 de 21"},
    grafico=g("Por qué no llegan al corte (tickers)",
              ["Vela antigua retocada", "Historia cambiada (GP, LU, PARA)", "Muertos o adquiridos", "Hueco de SNDK"],
              [14, 3, 3, 1]),
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Tolerar revisiones OHLC aisladas (se conserva la vela guardada, la revisión se apunta y se añaden "
                "las sesiones nuevas, como ya se hace con volumen y dividendo) y redescargar los 14, SNDK y KVUE",
           "codigo", "≈2–3 h, con red (descarga corta)", True,
           "bajo: lo ya guardado no cambia; la revisión queda registrada",
           "17 tickers al día y refrescos futuros que no se atascan", True),
        op("c", "Solo redescargar, sin tocar el código", "gratis", "≈30 min, con red", True,
           "bajo", "puede funcionar hoy, pero el problema volverá"),
    ],
    recomendacion="La b arregla la causa y el síntoma a la vez, con el mismo criterio que ya se usa para volumen y "
                  "dividendos.",
))
P.append(dict(
    origen=["F02", "F06", "F07"], tipo="frescura", gravedad="importante",
    titulo="El corte está escrito en el código y refrescar son unos 20 pasos a mano",
    que_pasa="La fecha 2026-11-13 está en 4 constantes, y hay 2 fechas fijas más. La base de trabajo ya trae una semana "
             "más (9.980 filas de 214 series curadas y 5.748 sesiones de 1.596 tickers), pero no se puede pasar a la "
             "curada sin editar código. Refrescar pide unas 20 órdenes en orden, y una re-selección completa podría "
             "cambiar la lista curada: 65 pares rozan el umbral de 0,95.",
    por_que_importa="Sin esto, cada actualización es lenta y fácil de romper, y los datos se quedan congelados en el "
                    "corte. Mover el corte cambia la decisión G2, así que lo decides tú.",
    cifras={"constantes con el corte": 4, "otras fechas fijas": 2, "filas curables ya descargadas": 9980,
            "sesiones de precios ya descargadas": 5748, "pares junto al umbral 0,95": 65},
    grafico=None,
    opciones=[
        op("a", "Seguir refrescando a mano con los 10 pasos documentados", "nada", "≈1 día por refresco", True,
           "medio: fácil saltarse un paso (p. ej. excepciones-alfred) o cambiar de rama con descargas en marcha",
           "ninguno"),
        op("b", "Corte en un solo sitio (config o --corte) y re-curar con corte 2026-11-20, sin red y con la lista "
                "congelada", "codigo", "≈2 h, sin red", False,
           "bajo: no se descarga nada; cambia G2 (nuevo corte)", "una semana más de datos hoy mismo"),
        op("c", "Orden única «refrescar --corte»: descargas reanudables en segundo plano, bucle de ALFRED y FRED, "
                "excepciones, curar y curar-precios con el corte por argumento y un estado genérico; lista congelada "
                "por defecto y --reseleccionar solo con diff y parada (G6)", "codigo", "≈1–2 días, sin red para "
                "el código", False, "medio: código nuevo que orquesta todo; se prueba con un refresco real",
           "actualizar pasa a ser una orden; la lista curada no cambia sin tu OK", True),
    ],
    recomendacion="La c es lo que de verdad deja los datos «actualizables»; su primer paso es la b, que ya da una "
                  "semana más sin red. Si prefieres ir por partes, empieza por la b.",
))
P.append(dict(
    origen=["N07", "N08"], tipo="nulos", gravedad="importante",
    titulo="Precio de ejecución en t+1: aperturas vacías sin regla de reserva",
    que_pasa="Los cierres están completos (0 vacíos). Pero el curado anuló a propósito 430.050 aperturas de relleno "
             "(3,97 %), 91.498 de ellas desde 2007, y VBMFX y ^SKEW nunca tienen apertura. La arquitectura prefiere "
             "operar a la apertura de t+1, pero está pendiente, y los baselines operan hoy al cierre. Sin una regla, la "
             "cartera no sabe qué precio usar cuando falta la apertura.",
    por_que_importa="Si cada uno improvisa (p. ej. usar el cierre de t), se puede colar un precio que a la hora de "
                    "decidir no existía. Es la pieza que falta para cerrar la convención t+1.",
    cifras={"aperturas vacías": 430050, "% de sesiones": "3,97 %", "desde 2007": 91498, "desde 2016": 43222,
            "tickers con más del 20 % vacías": 88, "cierres vacíos": 0},
    grafico=g("Aperturas vacías por mercado (los 6 con más)",
              ["XLON", "XNYS", "CBOE_IDX", "XNAS", "XKRX", "NAV_US"],
              [166095, 122814, 31777, 14802, 14404, 12344]),
    opciones=[
        op("a", "Decidirlo en la Fase 4", "nada", "0 h", False,
           "medio: llega sin regla al backtest", "ninguno"),
        op("b", "Ejecutar al cierre de t+1 (solo cierres, que están completos)", "codigo", "≈1 h, sin red", False,
           "bajo: más prudente que la apertura", "sin huecos; igual que los baselines; menos realista"),
        op("c", "Apertura de t+1 con reserva: si falta, cierre de t+1 con aviso (nunca el de t); el cierre de t+1 "
                "como prueba de sensibilidad", "codigo", "≈2–3 h, sin red", False,
           "bajo: la reserva es posterior a la decisión, no ve el futuro",
           "cumple la preferencia de la arquitectura y cierra el pendiente", True),
        op("d", "Como c, y además excluir de la elegibilidad los tickers con más de un X % de aperturas vacías (D10)",
           "codigo", "≈3–4 h, sin red", False, "medio: adelanta una parte de D10",
           "menos sesiones con reserva"),
    ],
    recomendacion="La c mantiene la apertura como preferencia, nunca mira atrás en el tiempo y deja el cierre de t+1 "
                  "como prueba de robustez, tal como pide docs/tfm/arquitectura.md.",
))
P.append(dict(
    origen=["F04", "F05"], tipo="frescura", gravedad="importante",
    titulo="Inflación y confianza de la zona euro paradas en su serie canónica",
    que_pasa="Varias series elegidas como canónicas dejaron de publicarse. El IPC de la OCDE para EA20, Francia e "
             "Italia lleva 257 días sin dato al corte, y el ESI EA20, 309. Refrescar no sirve: el crudo del 19-20 de "
             "noviembre no trajo nada. La base ya tiene el sustituto vivo: el ESI EA21 y el HICP de Eurostat y del BCE. "
             "El IPC de la OCDE para Japón no tiene sustituto en la base.",
    por_que_importa="Un agente que pida la inflación del euro verá la de hace ocho meses, y el régimen macro se "
                    "calcularía con datos viejos.",
    cifras={"desfasadas que no se arreglan refrescando": 8, "días sin dato, IPC OCDE": 257,
            "días sin dato, ESI EA20": 309, "series con sustituto ya en la base": "4 de 5"},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "medio: el canónico se queda viejo", "ninguno"),
        op("b", "Cambiar el canónico al ESI EA21 y al HICP (Eurostat/BCE) desde donde para el viejo, con el viejo como "
                "historia previa (como las 9 que ya se empalman)", "recalculo", "≈1–2 h, sin red", False,
           "medio: empalme entre fuentes del mismo concepto; revisar el salto en la unión",
           "inflación y confianza del euro al día sin descargar nada", True),
        op("c", "Solo marcar las viejas como retiradas, sin empalme", "recalculo", "≈30 min, sin red", False,
           "bajo", "el agente sabe que están paradas, pero no tiene la serie al día"),
    ],
    recomendacion="La b da el dato vivo con lo que ya hay en la base; el empalme sigue la misma regla que ya se aplica "
                  "a 9 series.",
))
P.append(dict(
    origen=["N13", "F05"], tipo="frescura", gravedad="importante",
    titulo="Series paradas que no avisan: el aviso solo mira diarias y semanales",
    que_pasa="13 series dicen «activa» y la fuente ya no las publica: BIS de Alemania, Francia e Italia (desde 1998), "
             "Eurostat del Reino Unido (desde 2020), el HICP de EE. UU. de Eurostat (desde 2024-12), la OCDE y el ESI "
             "EA20; ROUTPUT, a propósito. El aviso «datos atrasados» de get_serie solo funciona con paso de 7 días o "
             "menos, así que una mensual parada no avisa.",
    por_que_importa="El agente toma por actual un dato de hace años sin ninguna señal.",
    cifras={"«activa» pero paradas": 13, "retiradas bien marcadas": 27,
            "paradas con una regla para todas las frecuencias": 64, "de ellas, activas": 37},
    grafico=g("«Activa» pero paradas, por fuente", ["Eurostat", "OCDE", "BIS", "Philadelphia"], [5, 4, 3, 1]),
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "medio", "ninguno"),
        op("b", "Marcar las 13 como «retirada» (o «cerrada_en» con su fecha) en el catálogo", "recalculo",
           "≈30 min, sin red", False, "bajo", "el catálogo dice la verdad"),
        op("c", "b + extender el aviso a todas las frecuencias (umbral = retraso mediano + 2 periodos + margen), "
                "sin avisar en las que se retrasan por diseño", "codigo", "≈2 h, sin red", False,
           "bajo: solo añade avisos", "ninguna serie parada pasa sin aviso, hoy ni en el futuro", True),
    ],
    recomendacion="La c arregla las 13 de hoy y las que se paren mañana; el aviso es la defensa general.",
))
P.append(dict(
    origen=["C02", "C04", "L04"], tipo="consistencia", gravedad="importante",
    titulo="Saltos de precio sin split: 30 multiplicados por 10 sin ningún aviso",
    que_pasa="Hay 1.651 saltos de más del 50 % en un día sin split en 203 tickers. Casi todos están en tickers ya "
             "marcados (37 sospechosos y los reutilizados), pero 163 tickers tienen 311 saltos sin ningún aviso, y 30 "
             "son ×10 o ÷10 en 17 tickers, muchos indios: ampliaciones «bonus» que Yahoo no registra como split.",
    por_que_importa="Un ×10 falso es una rentabilidad del 900 % que rompe volatilidades, z-scores y la cartera.",
    cifras={"saltos de más del 50 %": 1651, "tickers": 203, "tickers con saltos sin aviso": 163,
            "saltos sin aviso": 311, "×10 o ÷10 sin aviso": 30, "tickers con ×10 sin aviso": 17,
            "sospechosos marcados": 37},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "alto: los 30 ×10 entran como rentabilidades reales",
           "ninguno"),
        op("b", "Aviso automático «salto sin split» en la lista curada para los 163 tickers", "codigo",
           "≈1 h, sin red", False, "bajo: solo avisos", "nadie los usa a ciegas"),
        op("c", "b + revisar a mano los 30 ×10 y dejar vacía esa sesión (o marcarla) con registro", "recalculo",
           "≈3 h, sin red", False, "medio: decidir a mano qué es error; se registra y se puede deshacer",
           "sin rentabilidades imposibles en el backtest", True),
        op("d", "Contrastar con Stooq (ahora exige una clave que se saca con un captcha: solo a mano)", "alternativa",
           "≈medio día, con red", True, "medio: no automatizable y sin garantía de cobertura",
           "segunda opinión en una muestra", url="https://github.com/pydata/pandas-datareader/issues/1012"),
    ],
    recomendacion="La c quita los errores claros y avisa del resto; con P02 b los avisos llegan a la tool.",
))
P.append(dict(
    origen=["C09"], tipo="consistencia", gravedad="importante",
    titulo="Paro semanal con 8 semanas de retraso en 2007–2009 por exceso de prudencia",
    que_pasa="Para no ver el futuro, el curado retrasa fechas. En 16 reglas el retraso es de 14 días o más y al menos "
             "el doble del original. Lo peor: las peticiones de paro (ICSA) pasan de 5 a 61 días entre 2007-01 y "
             "2009-05, y las continuadas, de 13 a 68. Las expectativas de inflación de Cleveland, de 31 a 109. "
             "rba:FIRMMCRTD hereda 7 días de otra tabla.",
    por_que_importa="En la crisis de 2008 el detector de régimen vería el paro semanal dos meses tarde, justo el dato "
                    "que antes avisa de una recesión.",
    cifras={"reglas con exceso": 16, "filas afectadas desde 2007": 2862, "ICSA: retraso antes": "5 días",
            "ICSA: retraso después": "61 días", "filas del RBA desde 2007": 10020},
    grafico=g("Retraso antes y después del curado", ["ICSA antes", "ICSA después", "Continuadas antes",
                                                     "Continuadas después", "Cleveland antes", "Cleveland después"],
              [5, 61, 13, 68, 31, 109], " días"),
    opciones=[
        op("a", "Dejarlo así y hacer la prueba de robustez con la fecha normal (D2)", "nada", "0 h", False,
           "bajo para el TimeGate", "ninguno: el agente sigue llegando tarde"),
        op("b", "ICSA y continuadas con el calendario del DOL (jueves siguiente + margen corto), que ya está en "
                "publicaciones.yaml, y separar rba:FIRMMCRTD de la regla de la tabla F2", "recalculo",
           "≈2 h, sin red", False,
           "medio: se adelantan fechas; hay que comprobar contra ALFRED que ninguna queda adelantada",
           "paro semanal casi a tiempo en 2008", True),
        op("c", "Revisar las 16 reglas una a una", "recalculo", "≈1 día, sin red", False,
           "medio: igual que b, en más reglas", "recupera también Cleveland, CFNAI y vivienda"),
    ],
    recomendacion="La b recupera el dato más valioso para un detector de crisis con un calendario ya documentado; la "
                  "comprobación con ALFRED evita adelantar nada.",
))
P.append(dict(
    origen=["V04"], tipo="vintages", gravedad="importante",
    titulo="El «solo añadir» tira las correcciones de Eurostat, BIS y RBA",
    que_pasa="En Eurostat, BIS y RBA la base no guarda versiones: si la fuente corrige un dato, gana lo guardado y la "
             "corrección se tira. El 2026-11-20 se tiraron 463. Solo el BCE guarda el «valor anterior» (132 filas). "
             "Así, refrescar no crea historia de revisiones.",
    por_que_importa="Estas series se quedan con la primera cifra vista, que puede estar mal, y nunca tendrán vintages.",
    cifras={"correcciones tiradas el 2026-11-20": 463, "valores anteriores conservados del BCE": 132,
            "series en solo añadir": 42},
    grafico=g("Correcciones tiradas el 2026-11-20", ["Eurostat", "BIS", "RBA"], [372, 86, 5]),
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "medio: datos congelados en la primera cifra", "ninguno"),
        op("b", "Pasar esas series a vintage con fecha (lo guardado con la fecha de su primera descarga; cada "
                "corrección con su fecha de observación), como ya se hace con el BCE", "codigo", "≈3–4 h, sin red",
           False, "medio: cambia el contrato de esas series (no pueden mezclar «unico» y fechas); tests",
           "las correcciones se guardan y cada refresco construye vintages", True),
        op("c", "Guardar las correcciones en un registro aparte, sin tocar la base", "codigo", "≈1 h, sin red",
           False, "bajo", "no se pierden, pero los agentes no las ven"),
    ],
    recomendacion="La b reutiliza la regla que ya funciona en el BCE y hace que refrescar valga para algo en estas "
                  "fuentes.",
))
P.append(dict(
    origen=["V07", "V05", "V03"], tipo="vintages", gravedad="importante",
    titulo="Las ediciones mensuales se pierden si nadie descarga cada mes",
    que_pasa="Ken French, Shiller, Goyal-Welch y la OFR publican ediciones que corrigen el pasado. Hoy hay guardadas 3, "
             "1, 2 y 0 (la OFR se sobrescribe en cada construir-base). Las OAS de ICE solo duran 3 años en FRED y "
             "tenemos 3 capturas. Cada mes sin descargar es una edición perdida para siempre.",
    por_que_importa="Sin ediciones no hay vintages de estas fuentes y la fuga de revisiones (P15) no se puede corregir "
                    "en el futuro.",
    cifras={"días con descarga": 2, "capturas de OAS": 3, "OAS: historia desde": "2023-10-10"},
    grafico=g("Ediciones archivadas", ["Ken French", "Shiller", "Goyal-Welch", "OFR"], [3, 1, 2, 0]),
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "medio: se pierde una edición al mes", "ninguno"),
        op("b", "Recordatorio y las órdenes a mano cada mes", "gratis", "≈15 min al mes, con red", True,
           "bajo, pero depende de acordarse", "ediciones guardadas si nadie se olvida"),
        op("c", "Tarea programada mensual en el PC (archivar-oas, académicas y FRED vivo) y archivar las ediciones de "
                "la OFR en vez de sobrescribir", "codigo", "≈2 h, red cada mes", True,
           "bajo: solo descarga y archiva; la tarea la creas tú o con tu OK",
           "vintages que crecen solos", True),
    ],
    recomendacion="La c ya estaba prevista en G4 como opción; es la única que no depende de la memoria de nadie.",
))
P.append(dict(
    origen=["V01", "V02"], tipo="vintages", gravedad="importante",
    titulo="4,23 % de las filas llevan el valor de hoy, no el de entonces",
    que_pasa="En 430.665 filas (94 series) el valor es el de la última o la primera edición, ya corregido: la fecha es "
             "prudente, pero la cifra puede «saber» del futuro. El 69 % es Ken French. Comprobado hoy en el índice de "
             "la Wayback Machine: guarda 21 versiones distintas del fichero de Ken French (2015–2026), 122 del de "
             "Shiller (2000–2023) y 20 del de la OFR (2019–2026).",
    por_que_importa="El backtest usa cifras corregidas años después, que en su día no se conocían. Es pequeño, pero es "
                    "el tipo de fuga que un tribunal pregunta.",
    cifras={"filas con posible fuga": 430665, "% de la curada": "4,23 %", "series": 94,
            "versiones de Ken French en la Wayback": 21, "versiones de Shiller": 122, "versiones de la OFR": 20},
    grafico=g("Filas con posible fuga, por fuente",
              ["Ken French", "USRECD", "OFR", "Goyal-Welch", "Shiller", "Eurostat", "BIS", "Banco Mundial"],
              [295998, 62062, 33985, 15952, 9216, 6669, 5772, 639]),
    opciones=[
        op("a", "Dejarlo como limitación declarada y hacer la prueba de robustez", "nada", "0 h", False,
           "medio: la fuga queda, aunque medida", "ninguno"),
        op("b", "Recuperar ediciones de la Wayback Machine para Shiller, OFR y Ken French (vintage = fecha de "
                "captura, igual o posterior a la publicación: prudente)", "alternativa", "≈1 día, con red", True,
           "medio: capturas con huecos (Ken French no tiene 2016 ni 2018); Shiller cambió de web en 2023",
           "Shiller casi sin fuga desde 2000; OFR desde 2019; Ken French desde 2015", True,
           "https://web.archive.org/cdx/search/cdx?url=www.econ.yale.edu/~shiller/data/ie_data.xls"),
        op("c", "Solo Shiller (la que más capturas tiene)", "alternativa", "≈medio día, con red", True,
           "bajo", "CAPE y tipos de Shiller sin fuga desde 2000",
           url="https://web.archive.org/cdx/search/cdx?url=www.econ.yale.edu/~shiller/data/ie_data.xls"),
    ],
    recomendacion="La b reduce la fuga donde más pesa y usa la misma fuente con la que ya se verificó F1. Conviene "
                  "empezar con una sonda corta para confirmar que las capturas se leen bien.",
))
P.append(dict(
    origen=["V06", "L03"], tipo="limitaciones", gravedad="importante",
    titulo="El WEO no tiene ediciones antes de 2025: no sirve para el backtest",
    que_pasa="Solo hay 4 ediciones (2025-04 a 2026-10) y faltan 34 (2008-04 a 2024-10). Lo primero visible es del "
             "2025-04-22. Hoy el robots.txt de imf.org responde «Access Denied» a un programa (comprobado), y por eso G3 "
             "lo dejó como limitación. Comprobado también: el archivo oficial tiene una página por edición con el "
             "fichero completo, y hay un fichero oficial único con las previsiones históricas desde abril de 1990. Los "
             "términos del FMI permiten bajar y reutilizar los datos sin fines comerciales citando la fuente, pero "
             "prohíben la descarga masiva automática sin permiso.",
    por_que_importa="Las 28 series del WEO de la curada no existen para 2007–2024, y las previsiones del FMI son de lo "
                    "poco que mira al futuro sin verlo.",
    cifras={"ediciones presentes": 4, "ediciones que faltan": 34, "series del WEO en la curada": 28,
            "visibles desde 2000": "0 de 28", "series de proyección": 306, "primera publicación visible": "2025-04-22"},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR + " (G3)", "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Que tú bajes a mano, en el navegador, el fichero oficial de previsiones históricas (uno solo, desde "
                "1990, indicadores clave) y el extractor lo lea sin red", "alternativa",
           "≈10 min a mano + ≈2–3 h de código, sin red para el código", False,
           "bajo/medio: solo trae algunos indicadores; encaja con G3 si aceptas que una descarga a mano no es un robot",
           "previsiones del FMI desde 1990, con la fecha de cada edición", True,
           "https://www.imf.org/en/Publications/WEO/frequently-asked-questions"),
        op("c", "Que tú bajes a mano las 34 ediciones completas desde la página de cada edición", "alternativa",
           "≈3–4 h a mano + ≈3 h de código", False, "bajo/medio: mucho trabajo manual; misma condición sobre G3",
           "todas las series del WEO con sus vintages",
           url="https://www.imf.org/en/Publications/WEO/weo-database/2008/april"),
    ],
    recomendacion="La b recupera lo más útil (crecimiento, inflación y otros clave por edición) con una sola descarga "
                  "manual, sin robot y dentro de los términos del FMI. Términos: "
                  "https://www.imf.org/en/About/copyright-and-terms",
))
P.append(dict(
    origen=["N04"], tipo="nulos", gravedad="importante",
    titulo="Inflación de Cleveland: agosto y septiembre de 2026 vacíos al corte",
    que_pasa="3.126 periodos de 22 series tenían valor en un vintage y salen vacíos en uno posterior. Casi todos son "
             "cambios de base reales (PCEC96, PNFIC1…). Pero en el IPC mediano y el recortado de Cleveland el vintage "
             "del 2026-11-10 trae vacíos agosto y septiembre de 2026 (43 y 51 periodos vacíos al corte). Puede ser un "
             "fallo de ALFRED o del cargador.",
    por_que_importa="El agente no ve la inflación subyacente más reciente, justo al final del periodo.",
    cifras={"periodos vacíos con valor previo": 3126, "series": 22, "desde 2000": 218,
            "IPC mediano, periodos vacíos": 43, "IPC recortado, periodos vacíos": 51,
            "vintage sospechoso": "2026-11-10"},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "medio: puede ser un fallo nuestro", "ninguno"),
        op("b", "Comprobar en ALFRED el vintage del 2026-11-10 y, si es un fallo, redescargar esas dos series",
           "gratis", "≈30 min, con red", True, "bajo", "se sabe si falta el dato o falla el cargador", True),
        op("c", "En as_of, tratar un vacío tras un valor ya publicado como «sin revisión» y servir el último valor "
                "con aviso", "codigo", "≈1–2 h, sin red", False,
           "medio: ocultaría retiradas reales como la de PCEC96", "nunca un vacío por un fallo de la fuente"),
    ],
    recomendacion="Primero mirar (b): cuesta media hora y dice si hay algo que arreglar. La c cambia una regla general "
                  "por dos series.",
))
P.append(dict(
    origen=["L08"], tipo="limitaciones", gravedad="importante",
    titulo="Cartera: baselines hechos con la base de trabajo y 60/40 europea sin montar",
    que_pasa="Los 6 baselines de cartera/ se calcularon el 2026-10-13 con la base de trabajo (hasta el 2026-10-12), "
             "antes del curado. La 60/40 europea quedó aplazada: sus UCITS empiezan el 2017-11-30 y no tiene versión "
             "con costes.",
    por_que_importa="Los baselines son la vara de medir del TFM: tienen que salir de los mismos datos y del mismo corte "
                    "que el backtest.",
    cifras={"estrategias": 6, "fin de los baselines": "2026-10-12", "inicio de la 60/40 UCITS": "2017-11-30"},
    grafico=None,
    opciones=[
        op("a", "No hacer nada hasta la Fase 4", "nada", "0 h", False, "medio: comparación con datos distintos",
           "ninguno"),
        op("b", "Rehacer los 6 con base='curada' hasta el corte", "recalculo", "≈1 h, sin red", False, "bajo",
           "baselines coherentes con el backtest"),
        op("c", "b + montar la 60/40 europea desde el 2017-11-30, con costes y sin empalme", "recalculo",
           "≈3 h, sin red", False, "bajo: historia corta pero limpia",
           "baselines coherentes y el pendiente aplazado cerrado", True),
        op("d", "b + 60/40 europea empalmando EUNA.DE con BNDX antes de 2017-11 (declarado)", "recalculo",
           "≈4 h, sin red", False, "medio: mezcla un fondo de EE. UU. con uno europeo",
           "historia más larga"),
    ],
    recomendacion="La c cierra el aplazado sin inventar historia; el empalme de d se puede añadir después como "
                  "prueba.",
))
P.append(dict(
    origen=["N02"], tipo="nulos", gravedad="importante",
    titulo="El tipo a 6 meses del Reino Unido falta 1 de cada 3 días desde 2013",
    que_pasa="La curva del BoE no llega al plazo de 6 meses muchos días: desde 2013 faltan 1.299 de 3.504 días "
             "(37,1 %), mientras el 10 años está completo. Es un hueco real de la fuente y el 80 % de los vacíos "
             "visibles desde 2000.",
    por_que_importa="Una pendiente 6M–10Y o un z-score que no trate los vacíos se rompe. No se debe interpolar: sería "
                    "un dato que el BoE nunca publicó.",
    cifras={"días vacíos desde 2013": 1299, "días desde 2013": 3504, "% vacío": "37,1 %",
            "parte de los vacíos visibles desde 2000": "80 %"},
    grafico=None,
    opciones=[
        op("a", "Documentarlo en el catálogo", "nada", "≈10 min, sin red", False, "medio: sigue rompiendo cálculos",
           "ninguno"),
        op("b", "Aviso en get_serie con el % de vacíos de la serie en la ventana pedida (sirve para todas)", "codigo",
           "≈1 h, sin red", False, "bajo: solo avisa", "el agente sabe que debe tratar los vacíos", True),
        op("c", "Usar el plazo de 1 año como corto británico canónico para pendientes", "recalculo",
           "≈1 h, sin red", False, "bajo: concepto algo distinto", "pendientes sin huecos"),
    ],
    recomendacion="El aviso (b) es general y protege también a otras series con huecos; la c se puede sumar si un "
                  "agente necesita la pendiente.",
))

# ---------------------------------------------------------------- COSMÉTICOS
P.append(dict(
    origen=["L07", "L10"], tipo="limitaciones", gravedad="cosmetico",
    titulo="Zona euro contada siempre con todos sus países de hoy",
    que_pasa="De 18 series de la zona euro, 5 usan la composición de cada fecha y en 6 la composición fija de hoy "
             "importa (ESI EA20, IPC y paro EA20 de la OCDE, dos del Banco Mundial y la brecha de crédito del BIS). "
             "Eurostat no publica la versión cambiante de algunas, y la OCDE no publica el CLI EA20 ni el paro de "
             "China (el CLI ya tiene sustituto).",
    por_que_importa="Antes de 2015 la zona euro «de hoy» incluye países que aún no estaban; la diferencia es pequeña "
                    "pero existe.",
    cifras={"series de la zona euro": 18, "con composición de cada fecha": 5, "fija donde importa": 6,
            "series que la fuente no publica": 4},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Preferir la versión U2/EA (composición de cada fecha) cuando ya está en la base y avisar en las "
                "fijas", "recalculo", "≈1 h, sin red", False, "bajo", "la mayoría de agregados correctos por fecha",
           True),
        op("c", "ESI desde la web de la Comisión (DG ECFIN; fichero gratis de indicadores principales)",
           "alternativa", "≈2 h, con red", True,
           "medio: la página no dice qué composición de la zona euro usa", "posible ESI de la zona euro cambiante",
           url="https://economy-finance.ec.europa.eu/economic-forecast-and-surveys/business-and-consumer-surveys/"
               "download-business-and-consumer-survey-data/time-series_en"),
    ],
    recomendacion="La b usa lo que ya hay y deja avisado lo que no tiene arreglo; encaja con P09.",
))
P.append(dict(
    origen=["F04", "N13", "N10"], tipo="frescura", gravedad="cosmetico",
    titulo="Oro, materias primas y Wilshire 5000 parados desde julio en las series",
    que_pasa="Las series yf:GC=F, yf:^BCOM y yf:^W5000 vienen del almacén de la Fase 1 y se pararon el 2026-07-17 "
             "(118 días al corte). Pero los ficheros de precios de GC=F y ^W5000 sí están al día (comprobado en la tabla "
             "de frescura); ^BCOM no tiene fichero. Además, ^W5000 lleva el calendario de Londres, lo que le da 206 "
             "huecos falsos.",
    por_que_importa="Un agente ve el oro de hace cuatro meses en get_serie aunque el dato existe en get_precios.",
    cifras={"series paradas": 3, "parada desde": "2026-07-17", "días sin dato al corte": 118,
            "huecos falsos de ^W5000": 206},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Rehacer yf:GC=F y yf:^W5000 desde el almacén de precios (como los 23 índices del 3b-1), poner "
                "^W5000 en XNYS y dar ^BCOM por alias de DBC (al día) o por retirada", "recalculo",
           "≈1–2 h, sin red", False, "bajo: misma vía que ya se usó en el 3b-1", "las tres al día sin descargar",
           True),
        op("c", "Intentar bajar ^BCOM de Yahoo", "gratis", "≈15 min, con red", True, "bajo",
           "quizá recupera ^BCOM"),
    ],
    recomendacion="La b usa datos que ya tenemos al día; la c se puede probar después solo para ^BCOM.",
))
P.append(dict(
    origen=["L05", "F04", "N13"], tipo="limitaciones", gravedad="cosmetico",
    titulo="Bundesbank: el 10 años alemán parado en 2026-10-13",
    que_pasa="La API del Bundesbank pone un reto anti-robots y la serie diaria del Bund a 10 años no se refresca desde "
             "el 2026-10-13 (29 días al corte). La base ya tiene curvas diarias del BCE (desde 2004) y el BCE publica "
             "cada mes el 10 años alemán armonizado.",
    por_que_importa="Es un tipo de referencia europeo; un mes de retraso afecta poco al backtest, pero crecerá.",
    cifras={"series": 1, "última fecha": "2026-10-13", "días sin dato al corte": 29, "filas en la curada": 7408},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Empalmar: Bundesbank como historia previa y, desde donde para, el 10 años de la curva diaria AAA del "
                "BCE (ya en la base), con aviso", "recalculo", "≈1 h, sin red", False,
           "medio: la AAA no es exactamente el Bund", "un 10 años europeo diario al día", True),
        op("c", "Que tú bajes el CSV a mano en el navegador cada mes", "gratis", "≈15 min al mes, con red", True,
           "bajo", "la serie original al día"),
        op("d", "10 años alemán mensual del BCE (estadística de convergencia, IRS)", "alternativa",
           "≈1 h, con red", True, "bajo: solo mensual", "dato oficial alemán sin anti-robots",
           url="https://data.ecb.europa.eu/data/datasets/IRS/data-information"),
    ],
    recomendacion="La b da un dato diario sin red y sin trabajo manual; la c es la alternativa si prefieres la serie "
                  "original.",
))
P.append(dict(
    origen=["L10", "V02", "V03"], tipo="vintages", gravedad="cosmetico",
    titulo="Sin vintages de BCE, Eurostat, BIS y Banco Mundial",
    que_pasa="13.452 filas de estas fuentes llevan el valor de la última edición. G1 lo dejó como limitación por «no "
             "haber fuente gratuita y legal», pero hoy se ha comprobado que sí existen: el archivo del WDI del Banco "
             "Mundial, la Real-Time Database del BCE y la base de revisiones de la OCDE. El BIS no tiene archivo.",
    por_que_importa="Es poca fuga (0,13 % de la curada) y casi toda macro anual o trimestral; el motivo de G1 está mal "
                    "escrito.",
    cifras={"filas afectadas": 13452, "Eurostat": 6669, "BIS": 5772, "Banco Mundial": 639, "BCE": 372},
    grafico=None,
    opciones=[
        op("a", "No hacer nada, pero corregir el motivo de G1 («existe fuente; no compensa»)", "nada",
           "≈10 min, sin red", False, "bajo", "la memoria dice la verdad", True),
        op("b", "Banco Mundial desde el archivo del WDI", "alternativa", "≈medio día, con red", True,
           "bajo", "639 filas con vintage", url="https://databank.worldbank.org/databases/archives"),
        op("c", "Zona euro desde la Real-Time Database del BCE (servicio web desde 2015)", "alternativa",
           "≈1 día, con red", True, "medio: experimental y con su propia definición de zona euro",
           "IPC, paro y PIB con vintages", url="https://data.ecb.europa.eu/data/datasets/RTD/data-information"),
        op("d", "Base de revisiones de la OCDE (MEI)", "alternativa", "≈1 día, con red", True,
           "medio: hay que localizar el conjunto exacto", "revisiones de las series de la OCDE",
           url="https://www.oecd.org/en/publications/undertaking-revisions-and-real-time-data-analysis-using-the-oecd-"
               "main-economic-indicators-original-release-data-and-revisions-database_146528313656.html"),
    ],
    recomendacion="El beneficio es pequeño frente al coste; basta con corregir el motivo. Si sobra tiempo, la b es la "
                  "más barata.",
))
P.append(dict(
    origen=["C05"], tipo="consistencia", gravedad="cosmetico",
    titulo="26 alias con historia anterior a 2000 que la curada no usa",
    que_pasa="27 de 109 alias empiezan antes que su canónico, 26 de ellos antes de 2000. En 2 se pierde toda la "
             "historia previa: DFF frente a EFFR (1954 frente a 2000) y el IPC de China del Banco Mundial frente al de "
             "la OCDE. Esa historia solo está en la base de trabajo.",
    por_que_importa="La regla D1 (desde 2000) se cumple, así que el backtest 2007–2026 no pierde nada; solo afecta a "
                    "estudios largos.",
    cifras={"alias": 109, "empiezan antes que el canónico": 27, "antes de 2000": 26,
            "canónico que no llega a 2000": 2, "ya empalmados como historia previa": 9},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Empalmar como historia previa (DFF antes de EFFR, Shiller antes de GS10…), como las 9 que ya lo "
                "hacen", "recalculo", "≈1–2 h, sin red", False, "bajo/medio: unión de fuentes distintas",
           "series largas en la curada", True),
    ],
    recomendacion="Es barato, sigue una regla ya usada y cierra un pendiente conocido.",
))
P.append(dict(
    origen=["C07"], tipo="consistencia", gravedad="cosmetico",
    titulo="Sin cambio a USD antes de 1999 (y el CNY)",
    que_pasa="El BCE empieza el 1999-01-04, así que antes no hay cambio a USD. El pendiente del CNY es menor de lo que "
             "parecía: solo 618 sesiones anteriores a 2000 (3,1 %) quedan sin cambio, ninguna desde 2007. En otras "
             "divisas el hueco también es sobre todo anterior a 1999.",
    por_que_importa="No afecta al backtest 2007–2026; solo a cálculos largos en USD.",
    cifras={"sesiones en CNY sin cambio": 618, "% en CNY": "3,1 %", "desde 2007": 0,
            "inicio del cambio del BCE": "1999-01-04"},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno", True),
        op("b", "Cambio secundario de la Fed (H.10, series DEX* de FRED) para antes de 1999", "alternativa",
           "≈1–2 h si se hace con P03 c, con red", True, "medio: calendario semanal de publicación",
           "USD completo desde los años 70", url="https://fred.stlouisfed.org/categories/94"),
    ],
    recomendacion="No compensa por sí solo; si se hace P03 c, ampliarlo aquí cuesta poco.",
))
P.append(dict(
    origen=["L06"], tipo="limitaciones", gravedad="cosmetico",
    titulo="UCITS con historia recortada o poco parecidos a su ETF de EE. UU.",
    que_pasa="18 UCITS tienen la historia recortada (16 en el estado del 3b: faltan CSPX.L y ^KS11) y 23 se parecen "
             "poco (correlación menor de 0,90) a su ETF de EE. UU. AIGA.L y ^V2TX no tienen precio en Yahoo.",
    por_que_importa="Los UCITS solo sirven para el anexo europeo (P18); el backtest principal no depende de ellos.",
    cifras={"historia recortada": 18, "correlación menor de 0,90": 23, "sin precio": 2},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR + " y alinear el 16/18", "nada", "≈10 min, sin red", False, "bajo",
           "cifras cuadradas", True),
        op("b", "Usar el ETF de EE. UU. como historia previa del UCITS, con aviso", "recalculo", "≈2 h, sin red",
           False, "medio: en 23 el parecido es bajo", "historia más larga"),
    ],
    recomendacion="No hay fuente gratuita comprobada para la historia previa y el empalme sería poco fiable en 23 casos.",
))
P.append(dict(
    origen=["L01"], tipo="limitaciones", gravedad="cosmetico",
    titulo="Constituyentes: el S&P 500 sin cambios después del 2026-08-18",
    que_pasa="La lista histórica del S&P 500 (repositorio fja05680, licencia MIT) no trae cambios después del "
             "2026-08-18: al corte hay 500 de 503 miembros con precio. Nikkei 225 e Ibovespa no tienen fuente. "
             "Comprobado: S&P DJI publica gratis una nota de prensa por cada cambio (p. ej. la del 2026-09-04).",
    por_que_importa="Solo afecta a los últimos tres meses y a unos pocos miembros.",
    cifras={"miembros con precio al corte": "500 de 503", "última fecha de la lista": "2026-08-18",
            "índices sin constituyentes": 2},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Volver a bajar el repositorio fja05680 por si se actualizó", "gratis", "≈10 min, con red", True,
           "bajo", "lista al día si el autor la actualizó", True),
        op("c", "Añadir a mano los cambios de septiembre a noviembre de 2026 desde las notas de S&P DJI",
           "alternativa", "≈1 h, con red", True, "bajo: pocas filas, con su fuente",
           "lista al día seguro",
           url="https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-"
               "Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600"),
    ],
    recomendacion="Primero la b, que cuesta diez minutos; si el repositorio sigue igual, la c.",
))
P.append(dict(
    origen=["N10", "N14"], tipo="nulos", gravedad="cosmetico",
    titulo="Huecos de más de 5 sesiones en precios sin aviso",
    que_pasa="Faltan 9.126 sesiones en 653 tickers, casi siempre sueltas. Solo 17 tickers tienen un hueco de más de 5 "
             "sesiones seguidas (7 de más de 20): BGEO.L 262, CNY=X 153, DWD 142… La rentabilidad que cruza ese hueco "
             "es de varios días, pero la tool no lo dice.",
    por_que_importa="Una rentabilidad de varias semanas contada como de un día infla la volatilidad.",
    cifras={"sesiones que faltan": 9126, "tickers con alguna": 653, "con hueco de más de 5": 17,
            "con hueco de más de 20": 7},
    grafico=g("Tickers con hueco de más de 5 sesiones, por mercado",
              ["FX", "CME", "XNYS", "XSWX", "Otros"], [5, 4, 2, 2, 4]),
    opciones=[
        op("a", NADA_DECLARAR, "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Aviso en get_precios cuando entre dos velas hay más de 5 sesiones del calendario", "codigo",
           "≈1 h, sin red", False, "bajo: solo avisa", "nadie confunde un salto de semanas con uno de un día",
           True),
    ],
    recomendacion="Barato y general; el hueco de KVUE se arregla en P06 y el de ^W5000 en P21.",
))
P.append(dict(
    origen=["N03"], tipo="nulos", gravedad="cosmetico",
    titulo="Octubre de 2025 no existe en 21 series de EE. UU.",
    que_pasa="Por el cierre del Gobierno, 21 series (paro, IPC, ventas…) no tienen octubre de 2025 en ningún vintage. "
             "Está documentado y debe quedarse vacío.",
    por_que_importa="Una variación mensual mal calculada saltaría de septiembre a noviembre como si fuera un mes.",
    cifras={"series": 21, "mes": "2025-10"},
    grafico=None,
    opciones=[
        op("a", "Dejarlo como está (documentado)", "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Test de que las derivadas y las variaciones dejan vacío ese mes y el siguiente", "codigo",
           "≈30 min, sin red", False, "bajo", "garantía de que nadie lo rellena", True),
    ],
    recomendacion="Un test pequeño evita un error silencioso en derivadas futuras.",
))
P.append(dict(
    origen=["N05"], tipo="nulos", gravedad="cosmetico",
    titulo="Seis filas vacías del festivo canadiense de 2006",
    que_pasa="Las 6 series de bonos de la BoC tienen una fila vacía el 2006-09-04 (Labour Day). Los demás años ese "
             "festivo no tiene fila.",
    por_que_importa="Casi nada; es limpieza.",
    cifras={"filas": 6, "fecha": "2006-09-04"},
    grafico=None,
    opciones=[
        op("a", "Dejarlas", "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Quitar las filas vacías en días que el calendario XTSE da cerrados", "recalculo",
           "≈15 min, sin red", False, "bajo", "coherencia con el resto del cargador", True),
    ],
    recomendacion="Es la misma regla que ya aplica el cargador al resto.",
))
P.append(dict(
    origen=["V01"], tipo="vintages", gravedad="cosmetico",
    titulo="73.559 filas anteriores a ALFRED sin la etiqueta de posible fuga",
    que_pasa="Las filas de FRED anteriores al primer vintage de ALFRED llevan un valor revisado, pero su nota solo dice "
             "«anterior a ALFRED», así que no cuentan en el 4,23 %. Con ellas sería el 4,95 %.",
    por_que_importa="La cifra de fuga que se cite en la memoria debe ser la completa.",
    cifras={"filas": 73559, "% de la curada": "0,72 %", "desde 2000": 21462, "series desde 2000": 92,
            "fuga total con ellas": "4,95 %"},
    grafico=None,
    opciones=[
        op("a", "Contarlas aparte en el informe", "nada", "≈10 min, sin red", False, "bajo", "cifra completa"),
        op("b", "Añadir «posible fuga de revisiones» a su nota", "codigo", "≈30 min, sin red", False, "bajo",
           "la tool avisa de ellas como de las demás", True),
    ],
    recomendacion="Que el aviso salga en la tool, no solo en el informe.",
))
P.append(dict(
    origen=["C10"], tipo="consistencia", gravedad="cosmetico",
    titulo="Los tests de datos se saltan en silencio si falta el corpus",
    que_pasa="Sin INGESTA_CORPUS_DIR, los tests crean <worktree>/corpus vacío y saltan 70 pruebas de datos reales sin "
             "fallar. Con el corpus de D: pasan 1.257 y se saltan 30.",
    por_que_importa="Un «todo en verde» puede no haber mirado los datos.",
    cifras={"saltados sin corpus": 70, "bien con corpus": 1257, "saltados con corpus": 30},
    grafico=None,
    opciones=[
        op("a", "Dejarlo", "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Avisar en la salida (o fallar) si falta el corpus en la máquina que lo tiene y no crear la carpeta "
                "vacía", "codigo", "≈30 min, sin red", False, "bajo", "nadie se fía de un verde vacío", True),
    ],
    recomendacion="Media hora para que el verde signifique algo.",
))
P.append(dict(
    origen=["C11", "N01", "V08", "C04", "V06", "N13", "C05"], tipo="consistencia", gravedad="cosmetico",
    titulo="Cifras y frases desfasadas en el plan y los notebooks",
    que_pasa="El plan dice 243 proyecciones (son 309), 25 alias antiguos (26), 26 sospechosos (37), 1.270 tests (hoy "
             "1.287), no cuenta la edición 2026-10 del WEO y dice que los vacíos de FRED son festivos (solo 7 de "
             "26.200 lo son). preprocesado.yaml llama «vintage exacto» a USRECD, que se fecha con una regla de 24 "
             "meses, y un comentario de tools.py dice «hasta el 3b-2».",
    por_que_importa="El plan se destila en el README y en la memoria: si las cifras no cuadran, el lector desconfía.",
    cifras={"proyecciones (plan / real)": "243 / 309", "sospechosos (plan / real)": "26 / 37",
            "alias antiguos (plan / real)": "25 / 26", "vacíos que son festivos": "7 de 26.200"},
    grafico=None,
    opciones=[
        op("a", "Dejarlo para cuando se destile el plan", "nada", "0 h", False, "bajo", "ninguno"),
        op("b", "Regenerar las cifras del plan y del README desde las tablas y corregir las frases", "gratis",
           "≈1 h, sin red", False, "bajo", "documentos que cuadran con los datos", True),
    ],
    recomendacion="Conviene hacerlo antes de destilar el plan en el README.",
))
P.append(dict(
    origen=["L01", "L04"], tipo="limitaciones", gravedad="cosmetico",
    titulo="Precios de una sola fuente (solo Yahoo, F3): nada con qué contrastar",
    que_pasa="Por F3 todos los precios vienen de Yahoo y no se paga ninguna fuente. Aperturas, splits y sospechosos no "
             "se pueden contrastar con otra. Comprobado: Stooq exige ahora una clave que se saca con un captcha (no "
             "automatizable) y el plan gratis de Tiingo es solo para uso personal interno (500 símbolos al mes).",
    por_que_importa="Es una decisión ya tomada; basta con que la memoria lo diga con sus cifras.",
    cifras={"proveedores de precios": 1, "tickers curados": 1616, "sospechosos": 37, "reutilizados": 112},
    grafico=None,
    opciones=[
        op("a", NADA_DECLARAR + " (F3)", "nada", "0 h", False, "bajo", "respeta la decisión", True),
        op("b", "Contraste manual de una muestra con el plan gratis de Tiingo (contradice F3 «solo Yahoo»)",
           "alternativa", "≈medio día, con red y registro", True,
           "medio: licencia de uso interno; no se puede compartir con el equipo", "una segunda opinión en una muestra",
           url="https://www.tiingo.com/about/pricing"),
    ],
    recomendacion="F3 ya lo decidió y las alternativas gratis tienen trabas de licencia o captcha.",
))
P.append(dict(
    origen=["N07", "C02", "C03", "L02"], tipo="limitaciones", gravedad="cosmetico",
    titulo="D10 abierta: mínimos de historia y liquidez de un ticker",
    que_pasa="D10 se dejó abierta a propósito: la elegibilidad de cada ticker se aplicará en el backtest punto a punto "
             "en la Fase 4. Las piezas ya están: avisos de sospechoso y reutilizado, aperturas vacías y pertenencia al "
             "índice por fecha.",
    por_que_importa="Es la regla que decide qué tickers entran en cada fecha; la usarán P05 y P08.",
    cifras={"tickers curados": 1616, "con regla d10_abierta en la lista": "todos los que se quedan"},
    grafico=None,
    opciones=[
        op("a", "Dejarla para la Fase 4, como se decidió", "nada", "0 h", False, "bajo",
           "respeta D10", True),
        op("b", "Escribir ya una función de elegibilidad punto a punto (historia, liquidez, aperturas vacías, avisos) "
                "sin aplicarla", "codigo", "≈3 h, sin red", False, "bajo: no cambia datos",
           "la Fase 4 empieza con la regla lista"),
    ],
    recomendacion="Respeta la decisión; los arreglos de P02, P05, P08 y P11 dejan preparadas las entradas.",
))

# ---------------------------------------------------------------- numeración y orden
orden_g = {"bloqueante": 0, "importante": 0, "cosmetico": 0}
for i, p in enumerate(P, 1):
    orden_g[p["gravedad"]] += 1
    p["orden"] = orden_g[p["gravedad"]]
    p["id"] = f"P{i:02d}"
    assert sum(o["recomendada"] for o in p["opciones"]) == 1, p["titulo"]
    assert 2 <= len(p["opciones"]) <= 5, p["titulo"]
    for o in p["opciones"]:
        if o["clase"] == "alternativa":
            assert o.get("fuente_url"), (p["titulo"], o["id"])

CLAVES = ["id", "origen", "titulo", "tipo", "gravedad", "orden", "que_pasa", "por_que_importa", "cifras", "grafico",
          "opciones", "recomendacion"]
P = [{k: p[k] for k in CLAVES} for p in P]

BIEN = [
    {"id": "N01", "texto": "Los 26.200 vacíos de la curada llevan todos su nota y son información real «a fecha» "
                           "(vintages antiguos, plazos de curva sin publicar): no se rellenan ni se borran."},
    {"id": "N06", "texto": "La curada no pierde ningún dato interior de la base de trabajo: solo faltan 513 periodos "
                           "finales que la fecha prudente deja después del corte."},
    {"id": "N08", "texto": "VBMFX y ^SKEW no tienen apertura en origen (fondo con valor liquidativo e índice); llevan "
                           "su aviso «sin_apertura»."},
    {"id": "N09", "texto": "Se quitaron 29.611 velas de relleno y el recuento propio, la tabla y el aviso cuadran; 0 "
                           "sesiones posteriores al corte."},
    {"id": "N14", "texto": "Los 660 huecos largos del EDA son casi todos reales de la fuente (ISK 2008–2018, DGS20 "
                           "1987–1993…); los tipos del BCE son series de fechas de cambio, no huecos."},
    {"id": "F01", "texto": "487 de 533 series curadas están al día en el corte; casi todo lo parado está retirado por "
                           "la fuente y bien marcado (27)."},
    {"id": "V03", "texto": "El 17,07 % de filas con vintage «unico» es casi todo (93,7 %) mercado, cambios y curvas, "
                           "que no se revisan; lo revisable es el 1,07 % y lleva aviso."},
    {"id": "C01", "texto": "Unidades y escalas limpias: cada serie tiene una sola unidad y divisa, y no queda ningún "
                           "salto ×100 o ×1000 lejos de cero."},
    {"id": "C04", "texto": "La cifra buena de sospechosos es 37 (36 en la curada); las otras (35, 36) se explican por "
                           "BLY e IBTS.L."},
    {"id": "C08", "texto": "Capas de fecha: 1.426.536 filas retrasadas y 0 adelantadas, como dice el plan."},
    {"id": "C10", "texto": "Las 26 verificaciones dan 0 y con el corpus pasan 1.257 tests sin fallos; los tests no "
                           "cambiaron ningún fichero de D: (7.545 comprobados)."},
    {"id": "L01", "texto": "El estado del 3b cuadra: 48 hechos, 1 parcial, 3 resueltos, 124 limitaciones (119 ids, 13 "
                           "causas) y 1 aplazado."},
    {"id": "L09", "texto": "347 de 533 series (65,1 %) se ven desde 2000; el resto nació después (Ken French, OFR, "
                           "curvas del BCE…). Es una limitación real sin nada que decidir."},
    {"id": "L10", "texto": "Philadelphia sin filas por diseño (ALFRED ya lo cubre) y calendarios de Eurostat antiguos "
                           "cubiertos por reglas prudentes: limitaciones sin nada que decidir."},
]

cuenta = Counter(p["gravedad"] for p in P)
clases_rec = Counter(next(o["clase"] for o in p["opciones"] if o["recomendada"]) for p in P)
sin_red = sum(1 for p in P if (lambda r: r["clase"] != "nada" and not r["red"])(next(o for o in p["opciones"] if o["recomendada"])))

def miles(n):
    return f"{n:,}".replace(",", ".")

RESUMEN = [
    f"Quedan {len(P)} pendientes: {cuenta['bloqueante']} bloqueantes, {cuenta['importante']} importantes y "
    f"{cuenta['cosmetico']} cosméticos. Los datos no tienen errores graves de fecha ni de escala, y "
    f"{len(BIEN)} comprobaciones salen bien.",
    f"{len(P) - clases_rec['nada']} se arreglan gratis (arreglo de código, recálculo, descarga gratuita o fuente "
    f"alternativa gratuita comprobada en la web), y {sin_red} de ellos sin red.",
    f"En {clases_rec['nada']} lo mejor es dejarlo como limitación declarada, por las decisiones ya tomadas (F3, D10) "
    "o porque el beneficio es pequeño. El sesgo de supervivencia no tiene remedio gratis: hay que medirlo y fijar "
    "una regla.",
    "Lo primero: los 4 bloqueantes de código (tools con base='curada' por defecto, aviso de tickers reutilizados, USX "
    "y el dólar taiwanés). Son unas 5–7 horas; solo el del dólar taiwanés necesita red (FRED). Después, la regla del sesgo de supervivencia y los 17 "
    "tickers sin refrescar.",
]

salida = {"fecha": "2026-11-21", "resumen_texto": RESUMEN, "bien": BIEN, "pendientes": P}
(AQUI / "asesor.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------------------------------------------------------------- asesor.md
GR = {"bloqueante": "bloqueante", "importante": "importante", "cosmetico": "cosmético"}
L = ["# Auditoría del Tema 1 · asesor: pendientes y opciones", "",
     "Fecha: 2026-11-21. Fuente: `angulo1`, `angulo2` y `angulo3` (cifras de los auditores, pendientes de cuadrar con "
     "el verificador). Datos completos en `asesor.json`.", ""]
L += [f"- {t}" for t in RESUMEN] + [""]
L += ["## Tabla resumen", "", "| id | título | gravedad | orden | opción recomendada | clase | origen |",
      "|---|---|---|---|---|---|---|"]
for p in P:
    r = next(o for o in p["opciones"] if o["recomendada"])
    L.append(f"| {p['id']} | {p['titulo']} | {GR[p['gravedad']]} | {p['orden']} | {r['id']}) {r['etiqueta']} | "
             f"{r['clase']} | {', '.join(p['origen'])} |")
L += ["", "## Las 124 limitaciones: a qué pendiente va cada grupo", "",
      "| grupo | filas | pendiente |", "|---|---|---|",
      "| Tickers sospechosos | 37 | P11 (y P34) |", "| Ediciones antiguas del WEO | 34 | P16 |",
      "| S&P 500: reutilizados, deslistados, adquiridos | 19 | P05 y P02 |",
      "| Yahoo revisa o no completa sesiones | 15 | P06 |",
      "| Series que la fuente no publica | 4 | P20 |", "| Philadelphia sin filas por diseño | 3 | bien (nada que decidir) |",
      "| Universo/UCITS | 3 | P26 |", "| Índices y futuros yf de la Fase 1 | 3 | P21 |",
      "| Constituyentes | 2 | P27 |", "| Bundesbank | 1 | P22 |",
      "| Calendarios de Eurostat | 1 | bien (cubierto por reglas prudentes) |",
      "| Vintages de BCE, Eurostat, BIS y BM | 1 | P23 |", "| Aperturas solo de Yahoo | 1 | P08 y P34 |", ""]
L += ["## Fuentes alternativas comprobadas en la web (2026-11-21)", "",
      "Solo se consultaron páginas públicas y el índice de capturas de la Wayback Machine (metadatos); no se envió "
      "ningún dato del usuario.", "",
      "| fuente | URL | qué se comprobó | usada en |", "|---|---|---|---|",
      "| FRED · DEXTAUS (H.10 de la Fed) | https://fred.stlouisfed.org/series/DEXTAUS | Existe: TWD por USD, diario, H.10 de la Fed (publicación semanal). La página dio error 500 al leerla; la última fecha se vio solo en el buscador | P03 |",
      "| FRED · cambios diarios H.10 (DEX*) | https://fred.stlouisfed.org/categories/94 | Categoría «Daily Rates» con los DEX*; FRED ya es fuente del proyecto | P25 |",
      "| FMI · FAQ del WEO | https://www.imf.org/en/Publications/WEO/frequently-asked-questions | Las previsiones históricas desde abril de 1990 de los indicadores clave están en un solo Excel oficial; archivo de ediciones desde abril de 1999 | P16 |",
      "| FMI · página de la edición de abril de 2008 | https://www.imf.org/en/Publications/WEO/weo-database/2008/april | Ofrece «Entire Dataset», «By Countries» y «By Country Groups» | P16 |",
      "| FMI · términos de uso | https://www.imf.org/en/About/copyright-and-terms | Se permite bajar y reutilizar datos sin fines comerciales citando al FMI; se prohíbe la descarga masiva automática sin permiso | P16 |",
      "| FMI · robots.txt | https://www.imf.org/robots.txt | Responde «Access Denied» (Akamai) a un programa: no se puede leer, como ya vio el 3b-2 | P16 |",
      "| Wayback Machine · índice CDX | https://web.archive.org/cdx/search/cdx?url=www.econ.yale.edu/~shiller/data/ie_data.xls | Versiones distintas con respuesta 200: Ken French (F-F_Research_Data_Factors_CSV.zip) 21, de 2015 a 2026 (sin 2016 ni 2018); Shiller (ie_data.xls) 122, de 2000 a 2023; OFR (fsi.csv) 20, de 2019 a 2026 | P15 |",
      "| Bundesbank · ayuda de la API SDMX | https://statistiken.bundesbank.de/content/991448 | API gratis sin clave (no menciona anti-robots); la base antigua cerró el 2026-06-30 según el buscador | P22 |",
      "| BCE · tipos a largo plazo de convergencia (IRS) | https://data.ecb.europa.eu/data/datasets/IRS/data-information | Existe la serie mensual del 10 años alemán (M.DE.L.L40…); publicación mensual | P22 |",
      "| BCE · Real-Time Database (RTD) | https://data.ecb.europa.eu/data/datasets/RTD/data-information | Según el buscador, vintages por servicio web desde 2015 y en bloque antes; experimental. La página dio 503 al leerla | P23 |",
      "| Banco Mundial · WDI Database Archives | https://databank.worldbank.org/databases/archives | Versiones anteriores del WDI desde 1989, gratis en DataBank | P23 |",
      "| OCDE · base de revisiones del MEI | https://www.oecd.org/en/publications/undertaking-revisions-and-real-time-data-analysis-using-the-oecd-main-economic-indicators-original-release-data-and-revisions-database_146528313656.html | Existe la base de datos originales y revisiones; el conjunto exacto (DF_STES_REVISIONS) no se confirmó en una página oficial | P23 |",
      "| Comisión Europea · DG ECFIN, encuestas | https://economy-finance.ec.europa.eu/economic-forecast-and-surveys/business-and-consumer-surveys/download-business-and-consumer-survey-data/time-series_en | ZIP gratis de indicadores principales (ESI) desestacionalizados; la página no dice qué composición de la zona euro usa | P20 |",
      "| S&P DJI · notas de prensa | https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600 | Nota pública y gratis de cambios del S&P 500 posteriores al 2026-08-18 | P27 |",
      "| GitHub · fja05680/sp500 | https://github.com/fja05680/sp500 | Repositorio con licencia MIT; la página no enseña la fecha del último cambio | P27 |",
      "| Tiingo · precios | https://www.tiingo.com/about/pricing | Plan gratis: más de 30 años de historia, 500 símbolos al mes, «solo uso personal interno»; no dice si trae deslistados. Contradice F3 | P05, P34 |",
      "| Stooq (incidencia de pandas-datareader) | https://github.com/pydata/pandas-datareader/issues/1012 | La descarga CSV exige ahora una clave que se saca con un captcha: no automatizable | P11 |",
      "",
      "**No se pudo verificar:** si Stooq o Tiingo traen deslistados; el paro urbano de China de la NBS; CSV de NAV de "
      "los emisores de UCITS; CRSP/WRDS (de pago o vía universidad). Por eso no salen como opción `alternativa`.",
      "",
      "**Nota:** al comprobar que el Excel de previsiones históricas del WEO existía, WebFetch lo guardó en la carpeta "
      "`tool-results` de la sesión (no se abrió ni se usó). Se puede borrar.", ""]
(AQUI / "asesor.md").write_text("\n".join(L), encoding="utf-8")
print(len(P), dict(cuenta), dict(clases_rec), "sin red:", sin_red)
