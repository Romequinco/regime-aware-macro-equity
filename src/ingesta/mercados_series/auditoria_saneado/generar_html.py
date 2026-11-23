"""Genera ``opciones.html`` (autocontenido, sin CDN) a partir de ``pendientes.json``.

Uso: python generar.py   (lee y escribe en docs/tfm/internos/tema1_saneado, carpeta ignorada)

``pendientes.json``: {"fecha": str, "resumen_texto": [str], "pendientes": [ {id, titulo, tipo, gravedad,
que_pasa, por_que_importa, cifras: {..}, grafico: {titulo, etiquetas: [], valores: [], sufijo} | null,
opciones: [{id, etiqueta, clase, coste, red, riesgo, beneficio, recomendada}], recomendacion} ]}
Solo metadatos y recuentos: ningún valor de serie ni precio.
"""
from __future__ import annotations
import os as _os  # noqa: E402
from pathlib import Path as _P  # noqa: E402
_REPO = _P(_os.environ.get("REPO_TFM") or _P(__file__).resolve().parents[4])

import html
import json
from pathlib import Path

AQUI = _REPO / "docs" / "tfm" / "internos" / "tema1_saneado"

PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Saneado del Tema 1</title>
<style>
:root {
  --bg: #f8f9fa; --card: #ffffff; --ink: #212529; --ink2: #495057; --line: #dee2e6; --soft: #e9ecef;
  --ok: #2b8a3e; --ok-bg: #ebfbee; --warn: #d9480f; --warn-bg: #fff4e6; --bad: #e03131; --bad-bg: #fff5f5;
  --lim: #868e96; --lim-bg: #f1f3f5; --acc: #1971c2;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #17191c; --card: #212428; --ink: #e9ecef; --ink2: #adb5bd; --line: #343a40; --soft: #2b2f34;
    --ok: #51cf66; --ok-bg: #1f3325; --warn: #ffa94d; --warn-bg: #3a2a1a; --bad: #ff8787; --bad-bg: #3b2020;
    --lim: #adb5bd; --lim-bg: #2b2f34; --acc: #74c0fc;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1080px; margin: 0 auto; padding: 24px 16px 80px; }
h1 { font-size: 26px; margin: 0 0 4px; }
.sub { color: var(--ink2); margin: 0 0 20px; }
.resumen { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.kpi b { display: block; font-size: 28px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.kpi span { color: var(--ink2); font-size: 13px; }
.kpi.bad b { color: var(--bad); } .kpi.warn b { color: var(--warn); } .kpi.ok b { color: var(--ok); } .kpi.lim b { color: var(--lim); }
.barra { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: var(--soft); margin: 6px 0 4px; }
.barra i { display: block; height: 100%; }
.leyenda { font-size: 13px; color: var(--ink2); display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 18px; }
.leyenda em { font-style: normal; display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.texto-resumen { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; }
.texto-resumen p { margin: 4px 0; }
.filtros { position: sticky; top: 0; z-index: 5; background: var(--bg); padding: 10px 0; border-bottom: 1px solid var(--line); margin-bottom: 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.filtros .grupo { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-right: 10px; }
.filtros .grupo > span { font-size: 12px; color: var(--ink2); text-transform: uppercase; letter-spacing: .04em; margin-right: 2px; }
.chip { border: 1px solid var(--line); background: var(--card); color: var(--ink); border-radius: 999px; padding: 4px 11px; font-size: 13px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.acciones { margin-left: auto; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.btn { border: 0; background: var(--acc); color: #fff; border-radius: 8px; padding: 8px 14px; font-size: 14px; font-weight: 600; cursor: pointer; }
.btn.sec { background: var(--card); color: var(--ink); border: 1px solid var(--line); font-weight: 500; }
.progreso { font-size: 13px; color: var(--ink2); }
.tarjeta { background: var(--card); border: 1px solid var(--line); border-left: 6px solid var(--lim); border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; }
.tarjeta.bloqueante { border-left-color: var(--bad); } .tarjeta.importante { border-left-color: var(--warn); } .tarjeta.cosmetico { border-left-color: var(--ok); }
.tarjeta.elegida { outline: 2px solid var(--acc); outline-offset: -1px; }
.cab { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.cab h2 { font-size: 18px; margin: 0; flex: 1 1 360px; }
.id { font: 600 13px ui-monospace, Consolas, monospace; color: var(--ink2); }
.et { font-size: 12px; border-radius: 4px; padding: 1px 7px; font-weight: 600; }
.et.bloqueante { background: var(--bad-bg); color: var(--bad); } .et.importante { background: var(--warn-bg); color: var(--warn); }
.et.cosmetico { background: var(--ok-bg); color: var(--ok); } .et.tipo { background: var(--soft); color: var(--ink2); font-weight: 500; }
.cuerpo { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; margin-top: 8px; }
@media (max-width: 760px) { .cuerpo { grid-template-columns: 1fr; } .acciones { margin-left: 0; } .filtros { position: static; } }
.cuerpo p { margin: 6px 0; }
.lbl { font-size: 12px; font-weight: 700; color: var(--ink2); text-transform: uppercase; letter-spacing: .04em; margin-top: 10px; }
.cifras { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.cifra { background: var(--soft); border-radius: 6px; padding: 3px 8px; font-size: 13px; }
.cifra b { font-variant-numeric: tabular-nums; }
.graf { font-size: 12px; color: var(--ink2); }
.graf .fila { display: grid; grid-template-columns: 110px 1fr 70px; gap: 6px; align-items: center; margin: 3px 0; }
.graf .fila .nom { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.graf .fila .bar { height: 10px; background: var(--acc); border-radius: 3px; min-width: 2px; opacity: .75; }
.graf .fila .num { text-align: right; font-variant-numeric: tabular-nums; }
.opciones { margin-top: 6px; display: grid; gap: 8px; }
.op { display: grid; grid-template-columns: 22px 1fr; gap: 8px; border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; cursor: pointer; }
.op:hover { border-color: var(--acc); }
.op input { margin-top: 4px; accent-color: var(--acc); }
.op.marcada { border-color: var(--acc); background: var(--soft); }
.op .t { font-weight: 600; }
.op .rec { color: var(--ok); font-weight: 700; }
.op .meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12.5px; color: var(--ink2); margin-top: 3px; }
.op .meta span b { color: var(--ink); font-weight: 600; }
.clase { font-size: 11px; border-radius: 4px; padding: 0 6px; margin-left: 6px; font-weight: 600; background: var(--soft); color: var(--ink2); white-space: nowrap; }
.clase.nada { background: var(--lim-bg); color: var(--lim); } .clase.gratis, .clase.recalculo { background: var(--ok-bg); color: var(--ok); }
.clase.codigo, .clase.alternativa { background: var(--warn-bg); color: var(--warn); }
textarea { width: 100%; margin-top: 10px; min-height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 7px 9px; font: inherit; font-size: 14px; background: var(--card); color: var(--ink); resize: vertical; }
.recomendacion { font-size: 13.5px; background: var(--ok-bg); border-radius: 6px; padding: 6px 10px; margin-top: 10px; }
.oculta { display: none; }
#aviso { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--bg); padding: 10px 16px; border-radius: 8px; font-size: 14px; opacity: 0; transition: opacity .25s; pointer-events: none; }
#aviso.ver { opacity: 1; }
#bien summary { cursor: pointer; }
#bien ul { margin: 8px 0 2px; padding-left: 20px; }
#bien li { margin: 3px 0; }
#salida { width: 100%; min-height: 160px; font: 13px ui-monospace, Consolas, monospace; display: none; margin-bottom: 14px; }
footer { color: var(--ink2); font-size: 12.5px; margin-top: 30px; }
</style>
</head>
<body>
<main>
<h1>Saneado del Tema 1: qué queda y qué eliges</h1>
<p class="sub">Auditoría de las series y precios que ya tenemos (corte 2026-11-13, revisado el __FECHA__). Una tarjeta por pendiente: elige una opción en cada una y pulsa «Copiar mi selección».</p>
<div class="resumen" id="kpis"></div>
<div id="barra-res"></div>
<div class="texto-resumen" id="texto-res"></div>
<details class="texto-resumen" id="bien"><summary><b>Lo que ya está bien</b> (comprobado, no es pendiente)</summary><ul id="bien-lista"></ul></details>
<div class="filtros" id="filtros">
  <div class="grupo" data-grupo="gravedad"><span>Gravedad</span></div>
  <div class="grupo" data-grupo="tipo"><span>Tipo</span></div>
  <div class="acciones">
    <span class="progreso" id="progreso"></span>
    <button class="btn sec" id="recomendadas" type="button">Marcar las recomendadas</button>
    <button class="btn" id="copiar" type="button">Copiar mi selección</button>
  </div>
</div>
<textarea id="salida" readonly aria-label="Texto de la selección"></textarea>
<div id="tarjetas"></div>
<footer>Solo metadatos, recuentos, fechas y porcentajes: ningún valor de serie ni precio. La selección se guarda en este navegador (localStorage) si está disponible. Detalle y cifras: docs/fase2/mercados_series/registro_saneado.md (rama fase2/t1-saneado).</footer>
</main>
<div id="aviso" role="status"></div>
<script id="datos" type="application/json">__DATOS__</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("datos").textContent);
  var P = D.pendientes;
  var CLAVE = "tema1_saneado_seleccion_v1";
  var GRAV = [["bloqueante", "Bloqueante"], ["importante", "Importante"], ["cosmetico", "Cosmético"]];
  var TIPOS = [["nulos", "Nulos y huecos"], ["frescura", "Frescura"], ["vintages", "Vintages"], ["consistencia", "Consistencia"], ["limitaciones", "Limitaciones"]];
  var CLASES = {nada: "no hacer nada / limitación", gratis: "arreglo gratis", alternativa: "fuente alternativa", codigo: "arreglo de código", recalculo: "recálculo"};
  var sel = {};
  try { sel = JSON.parse(localStorage.getItem(CLAVE) || "{}") || {}; } catch (e) { sel = {}; }
  function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(sel)); } catch (e) { /* sin almacenamiento */ } }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function fmt(v) { return typeof v === "number" ? v.toLocaleString("es-ES") : esc(v); }
  function el(tag, cls, htmlStr) { var e = document.createElement(tag); if (cls) e.className = cls; if (htmlStr != null) e.innerHTML = htmlStr; return e; }
  function recOf(p) { return p.opciones.filter(function (o) { return o.recomendada; })[0] || p.opciones[0]; }

  // ---------- resumen ----------
  var nG = {bloqueante: 0, importante: 0, cosmetico: 0}, nGratis = 0, nCodigo = 0, nLim = 0;
  P.forEach(function (p) {
    nG[p.gravedad] = (nG[p.gravedad] || 0) + 1;
    var c = recOf(p).clase;
    if (c === "nada") nLim++; else if (c === "codigo") nCodigo++; else nGratis++;
  });
  var kp = document.getElementById("kpis");
  [["", P.length, "pendientes en total"], ["bad", nG.bloqueante, "bloqueantes"], ["warn", nG.importante, "importantes"], ["ok", nG.cosmetico, "cosméticos"],
   ["ok", nGratis, "se arreglan gratis (dato, fuente o recálculo)"], ["warn", nCodigo, "piden sobre todo código"], ["lim", nLim, "limitación sin remedio (declarar)"]].forEach(function (k) {
    kp.appendChild(el("div", "kpi " + k[0], "<b>" + k[1] + "</b><span>" + k[2] + "</span>"));
  });
  var tot = P.length || 1;
  document.getElementById("barra-res").innerHTML =
    '<div class="barra" aria-hidden="true"><i style="width:' + (100 * nGratis / tot) + '%;background:var(--ok)"></i><i style="width:' + (100 * nCodigo / tot) +
    '%;background:var(--warn)"></i><i style="width:' + (100 * nLim / tot) + '%;background:var(--lim)"></i></div>' +
    '<div class="leyenda"><span><em style="background:var(--ok)"></em>gratis con la opción recomendada</span><span><em style="background:var(--warn)"></em>código</span><span><em style="background:var(--lim)"></em>limitación sin remedio</span></div>';
  document.getElementById("texto-res").innerHTML = (D.resumen_texto || []).map(function (t) { return "<p>" + esc(t) + "</p>"; }).join("") +
    (D.verificacion ? "<p><b>Verificación:</b> " + esc(D.verificacion) + ".</p>" : "");
  document.getElementById("bien-lista").innerHTML = (D.bien || []).map(function (x) { return "<li><b>" + esc(x.id) + "</b> · " + esc(x.texto) + "</li>"; }).join("");
  if (!(D.bien || []).length) document.getElementById("bien").style.display = "none";

  // ---------- filtros ----------
  var filtro = {gravedad: {}, tipo: {}};
  function chips(grupo, lista) {
    var g = document.querySelector('.grupo[data-grupo="' + grupo + '"]');
    lista.forEach(function (x) {
      var n = P.filter(function (p) { return p[grupo] === x[0]; }).length;
      if (!n) return;
      var b = el("button", "chip", esc(x[1]) + " · " + n);
      b.type = "button"; b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () {
        filtro[grupo][x[0]] = !filtro[grupo][x[0]];
        b.setAttribute("aria-pressed", filtro[grupo][x[0]] ? "true" : "false");
        aplicar();
      });
      g.appendChild(b);
    });
  }
  chips("gravedad", GRAV); chips("tipo", TIPOS);
  function pasa(p, grupo) { var f = filtro[grupo], act = Object.keys(f).filter(function (k) { return f[k]; }); return !act.length || act.indexOf(p[grupo]) >= 0; }
  function aplicar() { P.forEach(function (p) { document.getElementById("t-" + p.id).classList.toggle("oculta", !(pasa(p, "gravedad") && pasa(p, "tipo"))); }); }

  // ---------- tarjetas ----------
  var cont = document.getElementById("tarjetas");
  var nomTipo = {}; TIPOS.forEach(function (t) { nomTipo[t[0]] = t[1]; });
  var nomGrav = {}; GRAV.forEach(function (t) { nomGrav[t[0]] = t[1]; });
  function grafico(g) {
    if (!g || !g.etiquetas || !g.etiquetas.length) return "";
    var mx = Math.max.apply(null, g.valores.map(function (v) { return Math.abs(v); })) || 1;
    var s = '<div class="lbl">' + esc(g.titulo || "") + '</div><div class="graf">';
    g.etiquetas.forEach(function (e, i) {
      var v = g.valores[i];
      s += '<div class="fila"><span class="nom" title="' + esc(e) + '">' + esc(e) + '</span><span><span class="bar" style="display:block;width:' +
        (100 * Math.abs(v) / mx).toFixed(1) + '%"></span></span><span class="num">' + fmt(v) + esc(g.sufijo || "") + "</span></div>";
    });
    return s + "</div>";
  }
  P.forEach(function (p) {
    var t = el("article", "tarjeta " + p.gravedad); t.id = "t-" + p.id;
    var cifras = Object.keys(p.cifras || {}).map(function (k) { return '<span class="cifra">' + esc(k) + ": <b>" + fmt(p.cifras[k]) + "</b></span>"; }).join("");
    var ops = p.opciones.map(function (o) {
      var rid = "r-" + p.id + "-" + o.id;
      return '<label class="op" for="' + rid + '"><input type="radio" name="op-' + p.id + '" id="' + rid + '" value="' + esc(o.id) + '"><div>' +
        '<div class="t">' + esc(o.id) + ") " + esc(o.etiqueta) + (o.recomendada ? ' <span class="rec">(recomendada)</span>' : "") +
        '<span class="clase ' + esc(o.clase) + '">' + esc(CLASES[o.clase] || o.clase) + "</span></div>" +
        '<div class="meta"><span>Coste: <b>' + esc(o.coste) + "</b></span><span>Red: <b>" + (o.red ? "sí" : "no") + "</b></span><span>Riesgo: <b>" + esc(o.riesgo) +
        "</b></span></div>" + '<div class="meta"><span>Beneficio: <b>' + esc(o.beneficio) + "</b></span></div></div></label>";
    }).join("");
    t.innerHTML = '<div class="cab"><span class="id">' + esc(p.id) + "</span><h2>" + esc(p.titulo) + '</h2><span class="et ' + p.gravedad + '">' + nomGrav[p.gravedad] +
      '</span><span class="et tipo">' + esc(nomTipo[p.tipo] || p.tipo) + "</span></div>" +
      '<div class="cuerpo"><div><div class="lbl">Qué pasa</div><p>' + esc(p.que_pasa) + '</p><div class="lbl">Por qué importa</div><p>' + esc(p.por_que_importa) +
      '</p><div class="cifras">' + cifras + "</div></div><div>" + grafico(p.grafico) + "</div></div>" +
      '<div class="lbl">Opciones</div><div class="opciones">' + ops + "</div>" +
      (p.recomendacion ? '<div class="recomendacion"><b>Por qué la recomendada:</b> ' + esc(p.recomendacion) + "</div>" : "") +
      '<textarea placeholder="Nota libre (opcional)" aria-label="Nota para ' + esc(p.id) + '"></textarea>';
    cont.appendChild(t);
    var s = sel[p.id] || {};
    t.querySelectorAll('input[type="radio"]').forEach(function (r) {
      if (r.value === s.op) r.checked = true;
      r.addEventListener("change", function () { sel[p.id] = sel[p.id] || {}; sel[p.id].op = r.value; guardar(); pintar(p.id); });
    });
    var ta = t.querySelector("textarea"); ta.value = s.nota || "";
    ta.addEventListener("input", function () { sel[p.id] = sel[p.id] || {}; sel[p.id].nota = ta.value; guardar(); });
    pintar(p.id, true);
  });
  function pintar(id, sinProgreso) {
    var t = document.getElementById("t-" + id), s = sel[id] || {};
    t.querySelectorAll(".op").forEach(function (l) { l.classList.toggle("marcada", l.querySelector("input").value === s.op); });
    t.classList.toggle("elegida", !!s.op);
    if (!sinProgreso) progreso();
  }
  function progreso() {
    var n = P.filter(function (p) { return sel[p.id] && sel[p.id].op; }).length;
    document.getElementById("progreso").textContent = n + " de " + P.length + " elegidas";
  }
  progreso();

  document.getElementById("recomendadas").addEventListener("click", function () {
    P.forEach(function (p) {
      sel[p.id] = sel[p.id] || {};
      if (!sel[p.id].op) { var r = recOf(p); sel[p.id].op = r.id; var i = document.getElementById("r-" + p.id + "-" + r.id); if (i) i.checked = true; }
      pintar(p.id, true);
    });
    guardar(); progreso(); avisar("Marcadas las recomendadas donde no habías elegido nada");
  });

  // ---------- copiar ----------
  function texto() {
    var l = ["Saneado T1 · mi selección (" + P.filter(function (p) { return sel[p.id] && sel[p.id].op; }).length + "/" + P.length + ")"];
    P.forEach(function (p) {
      var s = sel[p.id] || {};
      if (!s.op && !(s.nota && s.nota.trim())) return;
      var o = p.opciones.filter(function (x) { return x.id === s.op; })[0];
      var r = p.id + " → " + (o ? o.id + " (" + o.etiqueta + ")" : "sin opción");
      if (s.nota && s.nota.trim()) r += " · nota: " + s.nota.trim().replace(/\s+/g, " ");
      l.push(r);
    });
    var sin = P.filter(function (p) { return !(sel[p.id] && sel[p.id].op); }).map(function (p) { return p.id; });
    if (sin.length) l.push("Sin elegir: " + sin.join(", "));
    return l.join("\n");
  }
  function avisar(m) { var a = document.getElementById("aviso"); a.textContent = m; a.classList.add("ver"); setTimeout(function () { a.classList.remove("ver"); }, 2200); }
  document.getElementById("copiar").addEventListener("click", function () {
    var t = texto(), out = document.getElementById("salida");
    out.value = t;
    function respaldo() { out.style.display = "block"; out.focus(); out.select(); var ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      avisar(ok ? "Selección copiada: pégala en el chat" : "Selecciona el texto de arriba y cópialo (Ctrl+C)"); }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(t).then(function () { out.style.display = "block"; avisar("Selección copiada: pégala en el chat"); }, respaldo);
    } else { respaldo(); }
  });
})();
</script>
</body>
</html>
"""


def main() -> None:
    datos = json.loads((AQUI / "pendientes.json").read_text(encoding="utf-8"))
    orden = {"bloqueante": 0, "importante": 1, "cosmetico": 2}
    datos["pendientes"].sort(key=lambda p: (orden[p["gravedad"]], p.get("orden", 99), p["id"]))
    for p in datos["pendientes"]:
        p["opciones"].sort(key=lambda o: not o.get("recomendada", False))
    crudo = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    salida = PLANTILLA.replace("__DATOS__", crudo).replace("__FECHA__", html.escape(datos.get("fecha", "")))
    (AQUI / "opciones.html").write_text(salida, encoding="utf-8")
    print("escrito", AQUI / "opciones.html", len(salida) // 1024, "KB", len(datos["pendientes"]), "pendientes")


if __name__ == "__main__":
    main()
