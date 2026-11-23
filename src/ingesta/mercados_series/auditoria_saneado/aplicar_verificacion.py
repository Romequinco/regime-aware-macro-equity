"""Aplica las correcciones del verificador (verificacion.json) a asesor.json -> pendientes.json del HTML."""
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DESTINO = _REPO / "docs" / "tfm" / "internos" / "tema1_saneado" / "pendientes.json"
d = json.loads((AQUI / "asesor.json").read_text(encoding="utf-8"))
P = {p["id"]: p for p in d["pendientes"]}

# C02: los saltos sí tienen aviso en la tabla; lo que falta es que la tool lo enseñe.
p = P["P11"]
p["titulo"] = "Saltos de precio sin split: el aviso existe en la tabla, pero la tool no lo enseña"
p["que_pasa"] = ("Hay 1.651 saltos de más del 50 % en un día sin split, en 203 tickers. Casi todos están en tickers marcados "
                 "como sospechosos o reutilizados. Fuera de esas marcas quedan 298 saltos en 157 tickers (27 son ×10 o ÷10, "
                 "en 14 tickers, muchos indios: ampliaciones «bonus» que Yahoo no registra como split). Los 157 tienen el "
                 "aviso «salto_sin_split» en precios_curados_avisos.csv, pero get_precios no lee esa tabla.")
p["cifras"] = {"saltos de más del 50 %": 1651, "tickers": 203, "saltos fuera de sospechosos/reutilizados": 298,
               "tickers con esos saltos": 157, "×10 o ÷10": 27, "tickers con ×10": 14,
               "con aviso en la tabla": "157 de 157", "aviso en get_precios": "no"}
for o in p["opciones"]:
    o["etiqueta"] = o["etiqueta"].replace("para los 163 tickers", "en la tool para los 157 tickers").replace(
        "los 30 ×10", "los 27 ×10")
p["recomendacion"] = ("La c quita los ×10 claros y hace que el aviso que ya existe llegue a la tool; con P02 b el mismo "
                      "cambio de get_precios sirve para los dos.")

# V01: 74.530 filas (incluye 971 de philly:ROUTPUT); total 4,96 %.
p = P["P31"]
p["titulo"] = "74.530 filas anteriores a ALFRED sin la etiqueta de posible fuga"
p["que_pasa"] = ("Las filas de FRED (y 971 de philly:ROUTPUT) anteriores al primer vintage de ALFRED llevan un valor revisado, "
                 "pero su nota solo dice «anterior a ALFRED», así que no cuentan en el 4,23 %. Con ellas sería el 4,96 %.")
p["cifras"] = {"filas": 74530, "% de la curada": "0,73 %", "de ellas philly:ROUTPUT": 971, "fuga total con ellas": "4,96 %"}

# L07: 21 series de zona euro, al menos 7 fijas donde importa.
p = P["P20"]
p["que_pasa"] = ("De 21 series de la zona euro, 5 usan la composición de cada fecha y al menos 7 usan la composición fija de hoy "
                 "donde sí importa (ESI EA20, IPC y paro EA20 de la OCDE, dos del Banco Mundial, la brecha de crédito del BIS "
                 "y el PIB real EA21 del BCE). Los dos agregados 163 del WEO también son zona euro. Eurostat no publica la "
                 "versión cambiante de algunas, y la OCDE no publica el CLI EA20.")
p["cifras"] = {"series de la zona euro": 21, "con composición de cada fecha": 5, "fija donde importa": "≥ 7",
               "series que la fuente no publica": 4}

# L02: cifra de la tabla y la recalculada por el verificador.
p = P["P05"]
p["cifras"]["días-tramo con precio"] = "67,78 % (tabla) · 67,45 % (verificador)"
p["cifras"]["miembros con precio el 2008-09-15"] = "302–305 de 498"

# N07: 90 con VBMFX y ^SKEW.
P["P08"]["cifras"]["tickers con más del 20 % vacías"] = 90

# N10: calendario del EDA desde 1990.
P["P28"]["cifras"]["con calendarios desde 1962"] = "683 tickers, 11.338 sesiones"

# Las «bien» corregidas.
for b in d["bien"]:
    if b["id"] == "L09":
        b["texto"] = ("346 de 533 series (64,9 %) se ven desde 2000 (fred:TWEXAFEGSMTH solo tiene nulos antes de 2006); el resto "
                      "nació después (Ken French, OFR, curvas del BCE…). Es una limitación real sin nada que decidir.")
    if b["id"] == "N01":
        b["texto"] = ("Los 26.200 vacíos de la curada (94 series) llevan todos su nota y son información real «a fecha»: 15.688 "
                      "de vintages antiguos que luego traen el dato, 3.138 retirados después y 7.374 sin ningún valor (plazos de "
                      "curva sin publicar). Solo 6 son festivos (BoC, 2006-09-04). No se rellenan ni se borran.")

d["verificacion"] = "41 confirmados, 6 corregidos, 3 duplicados, 0 no reproducibles (cifras corregidas aplicadas)"
DESTINO.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
print("escrito", DESTINO, len(d["pendientes"]), "pendientes")
