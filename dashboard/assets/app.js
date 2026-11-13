/* Dashboard de campana de factoring. Lee window.DASH (inputs/*.js) y no calcula nada que no este ahi.
   Para conectar el modelo real no se toca este archivo: ver README.md. */
(() => {
"use strict";
const { meta, resumen, simulador, lista, red } = window.DASH;
const MOTION = !matchMedia("(prefers-reduced-motion: reduce)").matches;
const ms = v => (MOTION ? v : 0);
const COLOR = ["#0B5CAB", "#ED590C", "#1A9E5A"];
const NOMBRE_G = meta.grupos.map(g => g.nombre);
const NEUTRAL = "#98A5B8", NAVY = "#002D74";

/* ---------- formato ---------- */
const nf = d3.formatLocale({ decimal: ".", thousands: ",", grouping: [3], currency: ["S/ ", ""] });
const int = nf.format(",.0f");
const pct = (v, d = 0) => nf.format(`.${d}f`)(v * 100) + "%";
function soles(v) {
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e9) return `${s}S/ ${nf.format(".2f")(a / 1e9)} mil M`;
  if (a >= 1e6) return `${s}S/ ${nf.format(".1f")(a / 1e6)} M`;
  if (a >= 1e4) return `${s}S/ ${nf.format(".0f")(a / 1e3)} K`;
  return `${s}S/ ${int(a)}`;
}
const compact = v => {
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e9) return s + nf.format(".3~f")(a / 1e9) + " mil M";
  if (a >= 1e6) return s + nf.format(".3~f")(a / 1e6) + " M";
  if (a >= 1e3) return s + nf.format(".3~f")(a / 1e3) + " K";
  return s + int(a);
};
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"];
const mesTxt = p => `${MESES[p % 100 - 1]} ${String(Math.floor(p / 100)).slice(2)}`;

/* ---------- DOM ---------- */
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  kids.flat().forEach(c => c != null && n.append(c));
  return n;
}
const leyenda = items => el("div", { class: "legend" }, items.map(i =>
  el("span", {}, el("i", { class: i.kind || "", style: `background:${i.color}` }), i.text)));

function tween(node, valor, fmt) {
  const desde = node.__v ?? 0;
  node.__v = valor;
  d3.select(node).interrupt().transition().duration(ms(node.__init ? 260 : 900)).ease(d3.easeCubicOut)
    .tween("text", () => { const i = d3.interpolateNumber(desde, valor); return t => { node.textContent = fmt(i(t)); }; });
  node.__init = true;
}

/* ---------- tooltip ---------- */
const tipEl = document.getElementById("tooltip");
const tip = {
  show(ev, titulo, filas) {
    tipEl.replaceChildren(el("div", { class: "t", text: titulo }),
      ...filas.map(f => el("div", { class: "r" }, f.color ? el("i", { style: `background:${f.color}` }) : null,
        el("b", { text: f.v }), el("span", { text: f.k }))));
    tipEl.hidden = false;
    const b = tipEl.getBoundingClientRect();
    const x = Math.min(ev.clientX + 14, innerWidth - b.width - 8), y = Math.max(ev.clientY - b.height - 12, 8);
    tipEl.style.left = `${x}px`; tipEl.style.top = `${y}px`;
  },
  hide() { tipEl.hidden = true; },
};

/* ---------- parametros y motor del simulador ---------- */
const DEFAULT = {
  cap: meta.supuestos.capacidad_contactos, margen: meta.margen, costo: meta.supuestos.costo_contacto,
  onb: meta.supuestos.costo_onboarding, umbral: meta.supuestos.umbral_habilitacion, incC: true, soloNuevos: false,
};
const BINS = simulador.bins.map(([g, prev, pLo, n, sp, spm, sm]) => ({ g, prev, pLo, n, sp, spm, sm }));
const HAY_C = BINS.some(b => b.g === 2);   // sin no clientes en las predicciones, Captacion no se muestra
const HAY_IMP = resumen.importancia.length > 0;
const GRUPOS_VIS = NOMBRE_G.map((n, i) => ({ n, i })).filter(g => g.i < 2 || HAY_C);
DEFAULT.incC = HAY_C;
const P = { ...DEFAULT };

function correr(mascara = [1, 1, P.incC ? 1 : 0], conCurva = false) {
  const items = [];
  const base = [0, 0, 0];
  let sumaP = 0, sumaM = 0, rentables = 0;
  for (const b of BINS) {
    if (!mascara[b.g] || (P.soloNuevos && b.prev) || (b.g !== 0 && b.pLo < P.umbral - 1e-9)) continue;
    const costo = P.costo + (b.g === 2 ? P.onb : 0);
    const ve = (b.spm / b.n) * P.margen - costo;
    items.push({ ...b, ve, costo });
    base[b.g] += b.n; sumaP += b.sp; sumaM += b.sm;
    if (ve > 0) rentables += b.n;
  }
  items.sort((a, b) => b.ve - a.ve);
  const r = { base, baseTotal: d3.sum(base), rentables, porGrupo: [0, 0, 0], contactos: 0, conv: 0, desembolso: 0, costo: 0, ve: 0, curva: [[0, 0]], pMedia: sumaP / (d3.sum(base) || 1), mMedio: sumaM / (d3.sum(base) || 1) };
  let resto = P.cap, acum = 0, x = 0;
  for (const it of items) {
    if (it.ve <= 0) break;
    if (resto > 0) {
      const t = Math.min(resto, it.n), f = t / it.n;
      r.porGrupo[it.g] += t; r.contactos += t; r.conv += it.sp * f; r.desembolso += it.spm * f;
      r.costo += t * it.costo; r.ve += t * it.ve; resto -= t;
    }
    if (conCurva) {
      const t = Math.min(it.n, meta.capacidad_max - x);
      if (t <= 0) break;
      x += t; acum += t * it.ve; r.curva.push([x, acum]);
    }
  }
  r.ingreso = r.desembolso * P.margen;
  return r;
}

function escenarioHoy() {               // leads contactados al azar, sin priorizar
  let n = 0, spm = 0, sp = 0;
  for (const b of BINS) if (b.g === 0 && !(P.soloNuevos && b.prev)) { n += b.n; spm += b.spm; sp += b.sp; }
  const c = Math.min(P.cap, n);
  return { ve: c * (spm / n * P.margen - P.costo), conv: c * sp / n };
}

const interpolarCurva = (curva, x) => {
  const i = d3.bisector(d => d[0]).left(curva, x);
  if (i <= 0) return 0;
  if (i >= curva.length) return curva[curva.length - 1][1];
  const [x0, y0] = curva[i - 1], [x1, y1] = curva[i];
  return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
};

/* ---------- filas de la lista ---------- */
const FILAS = lista.filas.map(f => Object.fromEntries(lista.campos.map((c, i) => [c, f[i]])));
const POR_ID = new Map(FILAS.map(f => [f.id, f]));
const veFila = f => f.p * f.m * P.margen - P.costo - (f.g === 2 ? P.onb : 0);
const elegible = f => (f.g === 0 || f.p >= P.umbral) && (P.incC || f.g !== 2) && !(P.soloNuevos && f.prev);
function ranking() {
  const out = FILAS.filter(elegible).map(f => ({ f, ve: veFila(f) })).sort((a, b) => b.ve - a.ve);
  out.forEach((o, i) => { o.rank = i + 1; o.dentro = i < P.cap && o.ve > 0; });
  return out;
}

function motivos(f) {
  const m = [];
  if (f.g === 2) m.push("Ya vende a una empresa ancla: la relación comercial existe");
  if (f.pct >= .25) m.push(f.g === 2 ? `El ${pct(f.pct)} de sus cobros observados viene de aceptantes` : `El ${pct(f.pct)} de sus ventas va a aceptantes`);
  if (f.prev) m.push(`Ya operó factoring (${int(f.ops)} operaciones)`);
  if (f.crec != null && f.crec >= .1) m.push(`Ventas crecieron ${pct(Math.exp(f.crec) - 1)} en el año`);
  if (f.dias >= 45) m.push(`Cobra a ${int(f.dias)} días: el adelanto libera caja`);
  if (f.uso != null && f.uso >= .5) m.push(`Usa ${pct(f.uso)} de su línea de crédito`);
  if (f.nac >= 2) m.push(`Vende a ${int(f.nac)} aceptantes`);
  return m.length ? m : ["Perfil similar a empresas que usan factoring"];
}

/* ---------- utilidades de grafico ---------- */
function lienzo(cont, alto, mg) {
  cont.replaceChildren();
  const w = Math.max(cont.clientWidth, 280), h = alto;
  const svg = d3.select(cont).append("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("height", h).attr("role", "img");
  const g = svg.append("g").attr("transform", `translate(${mg.l},${mg.t})`);
  return { svg, g, w: w - mg.l - mg.r, h: h - mg.t - mg.b };
}
function dibujaLinea(path, anim) {
  if (!anim || !MOTION) return;
  const L = path.node().getTotalLength();
  path.attr("stroke-dasharray", `${L} ${L}`).attr("stroke-dashoffset", L)
    .transition().duration(1200).ease(d3.easeCubicInOut).attr("stroke-dashoffset", 0)
    .on("end", function () { d3.select(this).attr("stroke-dasharray", null); });
}
const rectTop = (x, y, w, h, r = 4) => (h <= 0 ? "" : `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`);
const rectRight = (x, y, w, h, r = 4) => (w <= 0 ? "" : `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`);

/* Tarjeta con "Ver tabla": cada grafico tiene su gemelo tabular. */
function tarjeta({ titulo, sub, tabla, extra }) {
  const cuerpo = el("div", { class: "chart" });
  const vistaTabla = el("div", { class: "tbl-wrap", hidden: true });
  let enTabla = false;
  const btn = tabla && el("button", {
    class: "ghost", type: "button", text: "Ver tabla", onclick() {
      enTabla = !enTabla; btn.textContent = enTabla ? "Ver gráfico" : "Ver tabla";
      cuerpo.hidden = enTabla; vistaTabla.hidden = !enTabla;
      if (enTabla) pintarTabla();
    },
  });
  function pintarTabla() {
    const { cols, filas } = tabla();
    vistaTabla.replaceChildren(el("table", { class: "data plain" },
      el("thead", {}, el("tr", {}, cols.map((c, i) => el("th", { class: i ? "r" : "", text: c })))),
      el("tbody", {}, filas.map(f => el("tr", {}, f.map((v, i) => el("td", { class: i ? "r" : "", text: v })))))));
  }
  const nodo = el("div", { class: "card reveal" },
    el("div", { class: "card-head" },
      el("div", {}, el("h3", { text: titulo }), sub ? el("div", { class: "sub", text: sub }) : null),
      el("div", { style: "display:flex;gap:8px;align-items:center" }, extra || null, btn || null)),
    cuerpo, vistaTabla);
  nodo.cuerpo = cuerpo;
  nodo.refrescarTabla = () => { if (enTabla) pintarTabla(); };
  return nodo;
}
const observador = new IntersectionObserver(es => es.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add("in"); observador.unobserve(e.target); }
}), { threshold: .06 });
const revelar = raiz => raiz.querySelectorAll(".reveal").forEach((n, i) => { n.style.transitionDelay = `${Math.min(i, 6) * 50}ms`; observador.observe(n); });

/* ---------- graficos ---------- */
function gHistorico(c, anim) {
  const data = resumen.historico;
  const { g, w, h, svg } = lienzo(c, 260, { t: 16, r: 16, b: 28, l: 64 });
  const x = d3.scalePoint(data.map(d => d.periodo), [0, w]);
  const y = d3.scaleLinear([0, d3.max(data, d => d.desembolso)], [h, 0]).nice();
  g.append("g").attr("class", "grid-l").call(d3.axisLeft(y).ticks(4).tickSize(-w).tickFormat("")).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(4).tickSize(0).tickPadding(8).tickFormat(v => (v ? `S/ ${compact(v)}` : "0"))).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).tickSize(0).tickPadding(8).tickValues(data.filter((_, i) => i % 3 === 0).map(d => d.periodo)).tickFormat(mesTxt));
  const area = d3.area().x(d => x(d.periodo)).y0(h).y1(d => y(d.desembolso)).curve(d3.curveMonotoneX);
  const linea = area.lineY1();
  g.append("path").datum(data).attr("fill", COLOR[0]).attr("opacity", .1).attr("d", area);
  dibujaLinea(g.append("path").datum(data).attr("fill", "none").attr("stroke", COLOR[0]).attr("stroke-width", 2).attr("stroke-linecap", "round").attr("d", linea), anim);
  const xc = x(meta.corte);
  if (xc != null) {
    g.append("line").attr("x1", xc).attr("x2", xc).attr("y1", 0).attr("y2", h).attr("stroke", NEUTRAL);
    const fin_ = xc > w - 220;
    g.append("text").attr("class", "lbl-m").attr("x", fin_ ? xc - 6 : xc + 6).attr("y", 10).attr("text-anchor", fin_ ? "end" : "start").text(fin_ ? "Corte" : "Corte: lo posterior valida el modelo");
  }
  const fin = data[data.length - 1];
  g.append("circle").attr("cx", x(fin.periodo)).attr("cy", y(fin.desembolso)).attr("r", 4).attr("fill", COLOR[0]).attr("stroke", "#fff").attr("stroke-width", 2);
  const cruz = g.append("line").attr("y1", 0).attr("y2", h).attr("stroke", NEUTRAL).style("display", "none");
  svg.append("rect").attr("x", 64).attr("y", 16).attr("width", w).attr("height", h).attr("fill", "transparent")
    .on("pointermove", ev => {
      const px = d3.pointer(ev, g.node())[0];
      const d = data[Math.round(px / (x.step() || 1))] || fin;
      cruz.style("display", null).attr("x1", x(d.periodo)).attr("x2", x(d.periodo));
      tip.show(ev, mesTxt(d.periodo), [{ color: COLOR[0], v: soles(d.desembolso), k: "desembolsado" }, { v: int(d.ops), k: "operaciones" }]);
    }).on("pointerleave", () => { cruz.style("display", "none"); tip.hide(); });
}

function gGanancia(c, anim) {
  const data = [{ x: 0, y: 0 }, ...resumen.backtest.ganancia];
  const { g, w, h, svg } = lienzo(c, 240, { t: 12, r: 16, b: 38, l: 44 });
  const x = d3.scaleLinear([0, 1], [0, w]), y = d3.scaleLinear([0, 1], [h, 0]);
  g.append("g").attr("class", "grid-l").call(d3.axisLeft(y).ticks(4).tickSize(-w).tickFormat("")).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(4).tickSize(0).tickPadding(8).tickFormat(d3.format(".0%"))).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).ticks(5).tickSize(0).tickPadding(8).tickFormat(d3.format(".0%")));
  g.append("text").attr("class", "lbl-m").attr("x", w).attr("y", h + 34).attr("text-anchor", "end").text("% de la base contactada");
  g.append("line").attr("x1", 0).attr("y1", h).attr("x2", w).attr("y2", 0).attr("stroke", NEUTRAL).attr("stroke-width", 2);
  const l = d3.line().x(d => x(d.x)).y(d => y(d.y)).curve(d3.curveMonotoneX);
  dibujaLinea(g.append("path").datum(data).attr("fill", "none").attr("stroke", COLOR[1]).attr("stroke-width", 2).attr("d", l), anim);
  const cruz = g.append("line").attr("y1", 0).attr("y2", h).attr("stroke", NEUTRAL).style("display", "none");
  svg.append("rect").attr("x", 44).attr("y", 12).attr("width", w).attr("height", h).attr("fill", "transparent")
    .on("pointermove", ev => {
      const px = x.invert(d3.pointer(ev, g.node())[0]);
      const d = data[Math.max(1, Math.round(px * 20))] || data[20];
      cruz.style("display", null).attr("x1", x(d.x)).attr("x2", x(d.x));
      tip.show(ev, `Contactando ${pct(d.x)} de la base`, [{ color: COLOR[1], v: pct(d.y), k: "de conversiones" }, { color: NEUTRAL, v: pct(d.x), k: "al azar" }]);
    }).on("pointerleave", () => { cruz.style("display", "none"); tip.hide(); });
}

function gDumbbell(c, filas, anim) {
  const data = filas.slice(0, 9);
  const alto = data.length * 34 + 30;
  const { g, w, h } = lienzo(c, alto, { t: 4, r: 56, b: 26, l: 104 });
  const x = d3.scaleLinear([0, d3.max(data, d => Math.max(d.peso_base, d.peso_top)) * 1.05], [0, w]);
  const y = d3.scaleBand(data.map(d => d.nombre), [0, h]).padding(.3);
  g.append("g").attr("class", "grid-l").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).ticks(4).tickSize(-h).tickFormat("")).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).ticks(4).tickSize(0).tickPadding(8).tickFormat(d3.format(".0%"))).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).tickSize(0).tickPadding(8)).call(s => s.select(".domain").remove());
  const fila = g.selectAll("g.f").data(data).join("g").attr("class", "f").attr("transform", d => `translate(0,${y(d.nombre) + y.bandwidth() / 2})`);
  fila.append("line").attr("x1", d => x(d.peso_base)).attr("x2", d => x(d.peso_top)).attr("stroke", "#B9C5D6").attr("stroke-width", 2);
  fila.append("circle").attr("cx", d => x(d.peso_base)).attr("r", 8).attr("fill", "#fff").attr("stroke", NEUTRAL).attr("stroke-width", 2);
  const top = fila.append("circle").attr("r", 4).attr("fill", COLOR[0]);
  top.attr("cx", d => x(anim && MOTION ? d.peso_base : d.peso_top));
  if (anim) top.transition().delay((_, i) => i * 60).duration(ms(800)).attr("cx", d => x(d.peso_top));
  fila.append("text").attr("class", "lbl").attr("x", w + 52).attr("text-anchor", "end").attr("dy", 4).text(d => `${nf.format(".2f")(d.indice)}x`);
  fila.append("rect").attr("x", -104).attr("y", -14).attr("width", w + 160).attr("height", 28).attr("fill", "transparent")
    .on("pointermove", (ev, d) => tip.show(ev, d.nombre, [{ color: COLOR[0], v: pct(d.peso_top, 1), k: "del top 30%" }, { color: NEUTRAL, v: pct(d.peso_base, 1), k: "de la base" }]))
    .on("pointerleave", tip.hide);
}

function gImportancia(c, anim) {
  const data = resumen.importancia;
  const alto = Math.max(data.length * 38 + 8, 290);
  const { g, w, h } = lienzo(c, alto, { t: 4, r: 52, b: 4, l: 172 });
  const x = d3.scaleLinear([0, d3.max(data, d => d.importancia)], [0, w]);
  const y = d3.scaleBand(data.map(d => d.etiqueta), [0, h]).padding(.34);
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).tickSize(0).tickPadding(10)).call(s => s.select(".domain").remove());
  const bh = Math.min(y.bandwidth(), 20);
  const barra = g.selectAll("path.b").data(data).join("path").attr("fill", COLOR[0]);
  const pos = d => y(d.etiqueta) + (y.bandwidth() - bh) / 2;
  barra.attr("d", d => rectRight(0, pos(d), x(d.importancia), bh));
  if (anim && MOTION) barra.attr("d", d => rectRight(0, pos(d), 5, bh)).transition().delay((_, i) => i * 70).duration(800).ease(d3.easeCubicOut).attrTween("d", d => { const i = d3.interpolateNumber(5, x(d.importancia)); return t => rectRight(0, pos(d), i(t), bh); });
  g.selectAll("text.v").data(data).join("text").attr("class", "lbl").attr("x", d => x(d.importancia) + 6).attr("y", d => pos(d) + bh / 2 + 4).text(d => pct(d.importancia));
  barra.on("pointermove", (ev, d) => tip.show(ev, d.etiqueta, [{ color: COLOR[0], v: pct(d.importancia, 1), k: "de la importancia" }])).on("pointerleave", tip.hide);
}

function gCurvas(c, anim) {
  const esc = [
    { id: "A", nombre: "A · Solo leads", m: [1, 0, 0], color: COLOR[0] },
    { id: "AB", nombre: "A+B · Más habilitadas", m: [1, 1, 0], color: COLOR[1] },
    ...(P.incC ? [{ id: "ABC", nombre: "A+B+C · Más captación", m: [1, 1, 1], color: COLOR[2] }] : []),
  ].map(e => ({ ...e, curva: correr(e.m, true).curva }));
  const { g, w, h, svg } = lienzo(c, 320, { t: 16, r: 24, b: 40, l: 72 });
  const xMax = meta.capacidad_max;
  const x = d3.scaleLinear([0, xMax], [0, w]);
  const grid = d3.range(0, 61).map(i => i / 60 * xMax);
  esc.forEach(e => { e.pts = grid.map(v => [v, interpolarCurva(e.curva, v)]); });
  const y = d3.scaleLinear([0, d3.max(esc, e => d3.max(e.pts, p => p[1])) || 1], [h, 0]).nice();
  g.append("g").attr("class", "grid-l").call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat("")).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(8).tickFormat(v => (v ? `S/ ${compact(v)}` : "0"))).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).ticks(5).tickSize(0).tickPadding(8).tickFormat(v => (v ? compact(v) : "0")));
  g.append("text").attr("class", "lbl-m").attr("x", w).attr("y", h + 36).attr("text-anchor", "end").text("Contactos en la campaña");
  const l = d3.line().x(d => x(d[0])).y(d => y(d[1])).curve(d3.curveMonotoneX);
  esc.forEach(e => dibujaLinea(g.append("path").datum(e.pts).attr("fill", "none").attr("stroke", e.color).attr("stroke-width", 2).attr("stroke-linejoin", "round").attr("d", l), anim));
  const cx = x(P.cap);
  g.append("line").attr("x1", cx).attr("x2", cx).attr("y1", 0).attr("y2", h).attr("stroke", NAVY).attr("stroke-width", 1);
  g.append("text").attr("class", "lbl").attr("x", cx > w - 90 ? cx - 6 : cx + 6).attr("y", 10).attr("text-anchor", cx > w - 90 ? "end" : "start").text("Capacidad");
  esc.forEach(e => g.append("circle").attr("cx", cx).attr("cy", y(interpolarCurva(e.curva, P.cap))).attr("r", 4).attr("fill", e.color).attr("stroke", "#fff").attr("stroke-width", 2));
  const cruz = g.append("line").attr("y1", 0).attr("y2", h).attr("stroke", NEUTRAL).style("display", "none");
  svg.append("rect").attr("x", 72).attr("y", 16).attr("width", w).attr("height", h).attr("fill", "transparent")
    .on("pointermove", ev => {
      const v = Math.max(0, Math.min(xMax, x.invert(d3.pointer(ev, g.node())[0])));
      cruz.style("display", null).attr("x1", x(v)).attr("x2", x(v));
      tip.show(ev, `${int(v)} contactos`, esc.map(e => ({ color: e.color, v: soles(interpolarCurva(e.curva, v)), k: e.nombre })));
    }).on("pointerleave", () => { cruz.style("display", "none"); tip.hide(); });
  return esc;
}

function pasosCascada() {
  const hoy = escenarioHoy();
  const a = correr([1, 0, 0]), ab = correr([1, 1, 0]), abc = correr([1, 1, 1]);
  const pasos = [
    { n: "Hoy (al azar)", v: hoy.ve, tipo: "total", color: NEUTRAL },
    { n: "A · Priorizar", v: a.ve - hoy.ve, color: COLOR[0] },
    { n: "B · Habilitar", v: ab.ve - a.ve, color: COLOR[1] },
  ];
  if (P.incC) pasos.push({ n: "C · Captar", v: abc.ve - ab.ve, color: COLOR[2] });
  pasos.push({ n: "Propuesta", v: (P.incC ? abc : ab).ve, tipo: "total", color: NAVY });
  let acum = 0;
  pasos.forEach(p => { if (p.tipo) { p.y0 = 0; p.y1 = p.v; acum = p.v; } else { p.y0 = acum; p.y1 = acum + p.v; acum += p.v; } });
  return pasos;
}

function gCascada(c) {
  const pasos = pasosCascada();
  const { g, w, h } = lienzo(c, 280, { t: 26, r: 8, b: 30, l: 8 });
  const ext = [0, ...pasos.flatMap(p => [p.y0, p.y1])];
  const y = d3.scaleLinear([Math.min(...ext), Math.max(...ext) * 1.04 || 1], [h, 0]);
  const x = d3.scaleBand(pasos.map(p => p.n), [0, w]).padding(.3);
  const bw = Math.min(x.bandwidth(), 56), off = (x.bandwidth() - bw) / 2;
  g.append("line").attr("x1", 0).attr("x2", w).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", "#C5D0DE");
  pasos.forEach((p, i) => {
    if (i < pasos.length - 1) g.append("line").attr("x1", x(p.n) + off + bw).attr("x2", x(pasos[i + 1].n) + off).attr("y1", y(p.y1)).attr("y2", y(p.y1)).attr("stroke", "#C5D0DE");
    const top = Math.max(p.y0, p.y1), bot = Math.min(p.y0, p.y1);
    const alto = Math.max(y(bot) - y(top), 1);
    g.append("path").attr("d", rectTop(x(p.n) + off, y(top), bw, alto, Math.min(4, alto))).attr("fill", p.color)
      .on("pointermove", ev => tip.show(ev, p.n, [{ color: p.color, v: soles(p.v), k: p.tipo ? "valor esperado" : "aporte" }])).on("pointerleave", tip.hide);
    g.append("text").attr("class", "lbl").attr("x", x(p.n) + x.bandwidth() / 2).attr("y", y(top) - 8).attr("text-anchor", "middle").text((!p.tipo && p.v > 0 ? "+" : "") + soles(p.v));
  });
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).tickSize(0).tickPadding(8)).call(s => s.select(".domain").remove());
}

function gDispersion(c, filas, anim, onClick) {
  const pts = filas.slice(0, 700).reverse();
  const { g, w, h, svg } = lienzo(c, 340, { t: 12, r: 18, b: 40, l: 66 });
  if (!pts.length) { g.append("text").attr("class", "lbl-m").attr("x", w / 2).attr("y", h / 2).attr("text-anchor", "middle").text("Sin empresas para este filtro"); return; }
  const x = d3.scaleLog([Math.max(.005, d3.min(pts, d => d.f.p) * .9), Math.min(1, d3.max(pts, d => d.f.p) * 1.1)], [0, w]);
  const y = d3.scaleLog(d3.extent(pts, d => d.f.m).map((v, i) => v * (i ? 1.15 : .87)), [h, 0]);
  const marcas = [1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8].filter(v => v >= y.domain()[0] && v <= y.domain()[1]);
  g.append("g").attr("class", "grid-l").call(d3.axisLeft(y).tickValues(marcas).tickSize(-w).tickFormat("")).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).tickValues(marcas).tickSize(0).tickPadding(8).tickFormat(v => `S/ ${compact(v)}`)).call(s => s.select(".domain").remove());
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).ticks(5).tickSize(0).tickPadding(8).tickFormat(v => ([.01, .02, .05, .1, .2, .5, 1].includes(+v.toPrecision(2)) ? d3.format(".0%")(v) : "")));
  g.append("text").attr("class", "lbl-m").attr("x", w).attr("y", h + 36).attr("text-anchor", "end").text("Probabilidad de conversión");
  const corte = ranking().filter(o => o.dentro).at(-1);
  if (corte) {
    const ve = corte.ve;
    const lin = d3.range(0, 41).map(i => { const p = x.domain()[0] * Math.pow(x.domain()[1] / x.domain()[0], i / 40); return [p, (ve + P.costo) / (p * P.margen)]; }).filter(d => d[1] >= y.domain()[0] && d[1] <= y.domain()[1]);
    if (lin.length > 1) {
      g.append("path").datum(lin).attr("fill", "none").attr("stroke", NAVY).attr("d", d3.line().x(d => x(d[0])).y(d => y(d[1])));
      g.append("text").attr("class", "lbl").attr("x", x(lin[0][0]) + 4).attr("y", y(lin[0][1]) - 8).text("Límite de capacidad");
    }
  }
  const d = g.selectAll("circle.p").data(pts).join("circle").attr("class", "p")
    .attr("cx", p => x(p.f.p)).attr("cy", p => y(p.f.m)).attr("fill", p => COLOR[p.f.g])
    .attr("fill-opacity", p => (p.dentro ? .85 : .25)).attr("stroke", "#fff").attr("stroke-width", 1).attr("r", anim && MOTION ? 0 : 4);
  if (anim && MOTION) d.transition().delay((_, i) => i * 1).duration(400).attr("r", 4);
  const del = d3.Delaunay.from(pts, p => x(p.f.p), p => y(p.f.m));
  let previo = null;
  svg.append("rect").attr("x", 66).attr("y", 12).attr("width", w).attr("height", h).attr("fill", "transparent").style("cursor", "pointer")
    .on("pointermove", ev => {
      const [mx, my] = d3.pointer(ev, g.node());
      const i = del.find(mx, my), p = pts[i];
      if (previo != null) d3.select(d.nodes()[previo]).attr("r", 4).attr("stroke", "#fff");
      d3.select(d.nodes()[i]).attr("r", 7).attr("stroke", NAVY).raise();
      previo = i; svg.node().__sel = p.f;
      tip.show(ev, `${p.f.id} · ${NOMBRE_G[p.f.g]}`, [{ v: pct(p.f.p, 1), k: "probabilidad" }, { v: soles(p.f.m), k: "monto si convierte" }, { v: soles(p.ve), k: "valor esperado" }]);
    }).on("pointerleave", tip.hide).on("click", () => svg.node().__sel && onClick(svg.node().__sel));
}

/* ---------- Vista: Resumen ---------- */
const vResumen = (() => {
  const raiz = document.getElementById("view-resumen");
  const refs = {};
  let concKey = "rubro";
  const metricas = {
    pct_ventas_aceptantes: { k: "pct_acept", f: v => pct(v), txt: "vende más a aceptantes" },
    factoring_previo: { k: "previo", f: v => pct(v), txt: "ya usó factoring" },
    crecimiento_ventas: { k: "crec", f: v => pct(Math.exp(v) - 1), txt: "crece más en ventas" },
    uso_linea_credito: { k: "uso", f: v => pct(v), txt: "usa más su línea de crédito" },
  };
  function frase(x) {
    const conc = resumen.concentracion.rubro.filter(d => d.peso_base >= .05).sort((a, b) => b.indice - a.indice)[0];
    const parte = conc && conc.indice >= 1.15
      ? `se concentra en ${conc.nombre} (${pct(conc.peso_top)} vs ${pct(conc.peso_base)} de la base) porque`
      : "no depende del rubro:";
    const claves = HAY_IMP ? resumen.importancia.map(i => i.variable) : Object.keys(metricas).filter(k => resumen.perfil.top[metricas[k].k] > resumen.perfil.resto[metricas[k].k] * 1.25);
    const drivers = claves.filter(k => metricas[k]).slice(0, 2).map(k => {
      const m = metricas[k];
      return `${m.txt} (${m.f(resumen.perfil.top[m.k])} vs ${m.f(resumen.perfil.resto[m.k])})`;
    });
    return `“Ampliamos la base ${nf.format(".1f")(x)}x; el 30% con mayor probabilidad ${parte} ${drivers.join(" y ")}.”`;
  }
  function concTabla() {
    return { cols: [concKey[0].toUpperCase() + concKey.slice(1), "Base", "Top 30%", "Índice"], filas: resumen.concentracion[concKey].map(d => [d.nombre, pct(d.peso_base, 1), pct(d.peso_top, 1), `${nf.format(".2f")(d.indice)}x`]) };
  }
  function init() {
    const canvas = el("canvas", { "aria-hidden": "true" });
    refs.fig = el("div", { class: "hero-figure", text: "0.0x" });
    refs.note = el("div", { class: "hero-note" });
    refs.pitch = el("span");
    refs.kpi = ["Empresas a contactar", "Conversiones esperadas", "Desembolso esperado", "Valor esperado neto"].map(t => { const b = el("b", { text: "0" }); return { b, n: el("div", { class: "hero-kpi" }, el("span", { text: t }), b) }; });
    const hero = el("div", { class: "hero reveal", "data-sec": "resumen.hero" }, canvas,
      el("div", { class: "hero-grid" },
        el("div", {}, el("div", { class: "eyebrow", text: "¿Cuánto? · Base habilitada" }), refs.fig, el("div", { class: "hero-label", text: "veces la base con lead" }), refs.note),
        el("div", { class: "pitch" }, el("small", { text: "La historia para negocio" }), refs.pitch)),
      el("div", { class: "hero-kpis" }, refs.kpi.map(k => k.n)));

    refs.s1 = el("div", { class: "big", text: "0" }); refs.s1t = el("p"); refs.seg = el("div", { class: "seg-thin", role: "img" });
    refs.s2 = el("div", { class: "big", text: "0" }); refs.s2t = el("p");
    refs.s3 = el("div", { class: "big", text: "0" }); refs.s3t = el("p");
    const etapa = (n, t, big, txt, extra) => el("div", { class: "stage reveal" }, el("div", { class: "stage-top" }, el("div", { class: "dot-n", text: n }), el("h3", { text: t })), big, extra || null, txt);
    const stages = el("div", { class: "stages", "data-sec": "resumen.etapas" },
      etapa(1, "Habilitar", refs.s1, refs.s1t, refs.seg), chevron(), etapa(2, "Valorar", refs.s2, refs.s2t), chevron(), etapa(3, "Priorizar", refs.s3, refs.s3t));

    const sw = el("div", { class: "switch", role: "group", "aria-label": "Dimensión" }, [["rubro", "Rubro"], ["departamento", "Región"], ["segmento", "Tamaño"]].map(([k, t]) => el("button", {
      type: "button", text: t, "aria-pressed": k === concKey ? "true" : "false", onclick(ev) {
        concKey = k; sw.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b === ev.target ? "true" : "false"));
        gDumbbell(refs.conc.cuerpo, resumen.concentracion[k], true); refs.conc.refrescarTabla();
      },
    })));
    refs.conc = tarjeta({ titulo: "¿Quiénes? El top 30% frente a la base", sub: "Participación por grupo; índice = cuánto pesa frente a lo esperado", tabla: concTabla, extra: sw });
    refs.conc.insertBefore(leyenda([{ color: COLOR[0], text: "Top 30% por probabilidad", kind: "round" }, { color: "#fff", text: "Base habilitada", kind: "hollow" }]), refs.conc.cuerpo);
    if (HAY_IMP) refs.imp = tarjeta({ titulo: "¿Por qué? Lo que explica la conversión", sub: "Peso de cada variable en el modelo", tabla: () => ({ cols: ["Variable", "Importancia"], filas: resumen.importancia.map(d => [d.etiqueta, pct(d.importancia, 1)]) }) });

    const pf = resumen.perfil, filaP = (t, k, f) => el("tr", {}, el("td", { text: t }), el("td", { class: "hl", text: f(pf.top[k]) }), el("td", { text: f(pf.resto[k]) }));
    const perfilT = el("div", { class: "card reveal", "data-sec": "resumen.perfil" },
      el("div", { class: "card-head" }, el("div", {}, el("h3", { text: "Cómo es una empresa del top 30%" }), el("div", { class: "sub", text: "Valores típicos frente al resto de la base habilitada" }))),
      el("table", { class: "perfil" }, el("thead", {}, el("tr", {}, el("th", { text: "Indicador" }), el("th", { text: "Top 30%" }), el("th", { text: "Resto" }))),
        el("tbody", {}, filaP("Ventas a aceptantes", "pct_acept", v => pct(v)), filaP("Ya usó factoring", "previo", v => pct(v)), filaP("Crecimiento de ventas", "crec", v => pct(Math.exp(v) - 1)), filaP("Uso de línea de crédito", "uso", v => pct(v)), filaP("Días de crédito", "dias", v => `${int(v)} días`), filaP("Aceptantes por empresa", "n_acept", v => nf.format(".1f")(v)), filaP("Monto si convierte", "monto", soles))),
      HAY_IMP ? el("div", { class: "callout", style: "margin-top:14px", text: `Lo que más pesa en el modelo: ${resumen.importancia[0].etiqueta.toLowerCase()}.` }) : null);

    refs.hist = tarjeta({ titulo: "Factoring desembolsado por mes", sub: "Operaciones reales de las bases, en soles", tabla: () => ({ cols: ["Mes", "Desembolsado", "Operaciones"], filas: resumen.historico.map(d => [mesTxt(d.periodo), soles(d.desembolso), int(d.ops)]) }) });
    const b = resumen.backtest;
    if (b) {
      const g20 = b.ganancia.find(g => g.x === .2);
      refs.gan = tarjeta({ titulo: "¿Qué tan confiable es el ranking?", sub: b.ventana ? `Contra ${int(b.conversiones)} conversiones reales de ${mesTxt(b.ventana)}, en datos de prueba` : `Contra ${int(b.conversiones)} conversiones reales posteriores al corte`, tabla: () => ({ cols: ["% contactado", "% conversiones"], filas: b.ganancia.map(d => [pct(d.x), pct(d.y, 1)]) }) });
      refs.gan.dataset.sec = "resumen.gan";
      refs.gan.insertBefore(el("div", { class: "tiles t3", style: "margin-bottom:12px" },
        ...(b.por_grupo
          ? [el("div", { class: "tile" }, el("span", { text: "Gini ya usan" }), el("b", { text: nf.format(".2f")(b.por_grupo.usan) })),
            el("div", { class: "tile" }, el("span", { text: "Gini nuevas" }), el("b", { text: nf.format(".2f")(b.por_grupo.nuevas) }))]
          : [el("div", { class: "tile" }, el("span", { text: "Gini" }), el("b", { text: nf.format(".2f")(b.gini) })),
            el("div", { class: "tile" }, el("span", { text: "R² del monto" }), el("b", { text: nf.format(".2f")(b.r2_monto) }))]),
        el("div", { class: "tile" }, el("span", { text: "Top 20%" }), el("b", { text: pct(g20.y) }), el("em", { text: "de conversiones" }))), refs.gan.cuerpo);
      refs.gan.insertBefore(leyenda([{ color: COLOR[1], text: "Ranking del modelo", kind: "line" }, { color: NEUTRAL, text: "Al azar", kind: "line" }]), refs.gan.cuerpo);
    }
    refs.conc.dataset.sec = "resumen.conc"; if (refs.imp) refs.imp.dataset.sec = "resumen.imp";
    refs.hist.dataset.sec = "resumen.hist";

    raiz.replaceChildren(hero,
      cabecera("h1", "Del universo a la campaña", "De toda la base a quienes vamos a llamar"), stages,
      cabecera("h2", "Sustento de negocio", "Quiénes son y por qué convierten"),
      el("div", { class: "grid g2", "data-auto": "" }, refs.conc, refs.imp, perfilT, refs.gan),
      cabecera("h3", "Punto de partida", "Cómo viene el negocio"), refs.hist);
    lluvia(canvas);
  }
  function chevron() {
    const c = el("div", { class: "chev", "aria-hidden": "true" });
    c.innerHTML = '<svg viewBox="0 0 22 40"><path d="M3 2l15 18L3 38" fill="none" stroke="currentColor" stroke-width="6"/></svg>';
    return c;
  }
  function update() {
    const r = correr();
    const x = r.baseTotal / (r.base[0] || 1);
    tween(refs.fig, x, v => `${nf.format(".1f")(v)}x`);
    refs.note.textContent = `De ${int(r.base[0])} leads a ${int(r.baseTotal)} empresas`;
    refs.pitch.textContent = frase(x);
    tween(refs.kpi[0].b, r.contactos, int); tween(refs.kpi[1].b, r.conv, int);
    tween(refs.kpi[2].b, r.desembolso, soles); tween(refs.kpi[3].b, r.ve, soles);
    tween(refs.s1, r.baseTotal, int);
    refs.s1t.textContent = `empresas con potencial, de ${int(resumen.embudo.evaluables)} evaluadas. Filtro: lead o P ≥ ${pct(P.umbral, 1)}.`;
    refs.seg.setAttribute("aria-label", r.base.map((n, i) => `${NOMBRE_G[i]}: ${int(n)}`).join(", "));
    refs.seg.replaceChildren(...r.base.map((n, i) => (n ? el("i", { style: `flex-grow:${n};background:${COLOR[i]}`, title: `${NOMBRE_G[i]}: ${int(n)}` }) : null)).filter(Boolean),
      );
    if (!refs.segLeg) { refs.segLeg = el("div", { class: "legend" }); refs.seg.after(refs.segLeg); }
    refs.segLeg.replaceChildren(...r.base.map((n, i) => (n ? el("span", {}, el("i", { style: `background:${COLOR[i]}` }), `${NOMBRE_G[i]} ${compact(n)}`) : null)).filter(Boolean));
    tween(refs.s2, r.rentables, int);
    refs.s2t.textContent = `son rentables de contactar. P. media ${pct(r.pMedia, 1)} y monto medio ${soles(r.mMedio)} por empresa.`;
    tween(refs.s3, r.contactos, int);
    refs.s3t.textContent = r.contactos < P.cap
      ? `contactos: no hay más empresas rentables dentro de la capacidad de ${int(P.cap)}.`
      : `a contactar según la capacidad comercial: ${pct(r.contactos / (r.rentables || 1), 1)} de las rentables.`;
  }
  function draw(anim) {
    gDumbbell(refs.conc.cuerpo, resumen.concentracion[concKey], anim);
    if (refs.imp) gImportancia(refs.imp.cuerpo, anim);
    gHistorico(refs.hist.cuerpo, anim);
    if (refs.gan) gGanancia(refs.gan.cuerpo, anim);
  }
  return { init, update, draw };
})();

/* Lluvia de digitos del fondo de la PPT: muy tenue y solo mientras el Resumen esta visible. */
function lluvia(canvas) {
  if (!MOTION) return;
  const ctx = canvas.getContext("2d");
  let col = [], w = 0, h = 0, ultimo = 0;
  const medir = () => {
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w; canvas.height = h;
    col = d3.range(Math.ceil(w / 34)).map(i => ({ x: i * 34 + 8, y: Math.random() * h, v: .2 + Math.random() * .5 }));
  };
  medir(); addEventListener("resize", medir);
  (function paso(t) {
    requestAnimationFrame(paso);
    if (canvas.offsetParent === null || t - ultimo < 40 || document.hidden) return;
    if (canvas.clientWidth !== w) medir();
    ultimo = t;
    ctx.clearRect(0, 0, w, h);
    ctx.font = "14px Blinker,sans-serif"; ctx.fillStyle = "rgba(160,200,255,.14)";
    for (const c of col) {
      for (let i = 0; i < 7; i++) ctx.fillText((Math.floor(c.y / 30) + i * 7 + c.x) % 3 ? "1" : "0", c.x, ((c.y + i * 22) % (h + 40)));
      c.y += c.v;
      if (c.y > h + 40) c.y = -40;
    }
  })(0);
}

/* ---------- Vista: Simulador ---------- */
const vSim = (() => {
  const raiz = document.getElementById("view-simulador");
  const refs = {}, ctl = {};
  const defs = [
    { k: "cap", t: "Capacidad comercial", min: 500, max: meta.capacidad_max, step: 100, f: v => `${int(v)}`, n: "Contactos por campaña." },
    { k: "margen", t: "Margen sobre desembolso", min: .01, max: .04, step: .0005, f: v => pct(v, 2), n: `Histórico de las operaciones: ${pct(meta.margen, 2)}.` },
    { k: "costo", t: "Costo por contacto", min: 20, max: 500, step: 10, f: v => `S/ ${int(v)}`, n: "Por empresa contactada." },
    { k: "onb", t: "Onboarding de cliente nuevo", min: 0, max: 3000, step: 50, f: v => `S/ ${int(v)}`, n: "Se suma al costo en Captación." },
    { k: "umbral", t: "Umbral para habilitar", min: .01, max: .1, step: .0025, f: v => pct(v, 2), n: "Probabilidad mínima para entrar sin lead." },
  ].filter(d => d.k !== "onb" || HAY_C);
  let frame = 0;
  function mover() { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => { sincronizar(); update(); draw(false); }); }
  function sincronizar() {
    for (const d of defs) {
      const c = ctl[d.k];
      c.input.value = P[d.k]; c.out.textContent = d.f(P[d.k]);
      c.input.style.setProperty("--p", `${(P[d.k] - d.min) / (d.max - d.min) * 100}%`);
    }
    ctl.incC.checked = P.incC; ctl.soloNuevos.checked = P.soloNuevos;
  }
  function init() {
    const panel = el("div", { class: "panel", "data-sec": "simulador.panel" }, el("h3", { text: "Supuestos de la campaña" }),
      defs.map(d => {
        const input = el("input", { type: "range", min: d.min, max: d.max, step: d.step, id: `c-${d.k}`, "aria-label": d.t, oninput(ev) { P[d.k] = +ev.target.value; mover(); } });
        const out = el("output", { for: `c-${d.k}` });
        ctl[d.k] = { input, out };
        return el("div", { class: "ctl" }, el("div", { class: "ctl-top" }, el("label", { for: `c-${d.k}`, text: d.t }), out), input, el("small", { text: d.n }));
      }));
    const chk = (k, t, n) => {
      const i = el("input", { type: "checkbox", onchange(ev) { P[k] = ev.target.checked; mover(); } });
      ctl[k] = i;
      return el("label", { class: "check" }, i, el("span", {}, t, el("small", { text: n })));
    };
    const chkC = chk("incC", "Incluir Captación", "No clientes que venden a aceptantes.");
    chkC.hidden = !HAY_C;
    panel.append(chkC, chk("soloNuevos", "Solo nuevos en factoring", "Excluye a quienes ya lo usaron."),
      el("button", { class: "ghost", type: "button", text: "Restablecer", onclick() { Object.assign(P, DEFAULT); mover(); } }));

    refs.t = [["Contactos", int], ["Conversiones esperadas", int], ["Desembolso esperado", soles], ["Valor esperado neto", soles]].map(([t, f], i) => { const b = el("b", { text: "0" }), em = el("em"); return { b, em, f, n: el("div", { class: `tile${i === 3 ? " accent" : ""}` }, el("span", { text: t }), b, em) }; });
    refs.aviso = el("div", { class: "alert", hidden: true });
    refs.mix = el("div", { class: "tall-seg", role: "img" }); refs.mixLeg = el("div", { class: "legend" });
    const mix = el("div", { class: "card reveal", "data-sec": "simulador.mix" }, el("h3", { text: "A quién llega la capacidad" }), el("div", { class: "sub", text: "Reparto de los contactos entre grupos" }), refs.mix, refs.mixLeg);
    refs.curva = tarjeta({ titulo: "Valor esperado acumulado según contactos", sub: "Cada escenario ordena por valor esperado y deja de contactar cuando deja de ser rentable", tabla: () => {
      const m = P.incC ? [[1, 0, 0], [1, 1, 0], [1, 1, 1]] : [[1, 0, 0], [1, 1, 0]];
      const cs = m.map(x => correr(x, true).curva);
      return { cols: ["Contactos", "A", "A+B", ...(P.incC ? ["A+B+C"] : [])], filas: [1000, 2500, 5000, 10000, 15000, 20000].map(x => [int(x), ...cs.map(c => soles(interpolarCurva(c, x)))]) };
    } });
    refs.curvaLeg = el("div", { style: "margin-bottom:8px" });
    refs.curva.insertBefore(refs.curvaLeg, refs.curva.cuerpo);
    refs.casc = tarjeta({ titulo: "De dónde sale el valor: las palancas", sub: "Valor esperado neto a igual capacidad", tabla: () => ({ cols: ["Paso", "Valor"], filas: pasosCascada().map(p => [p.n, soles(p.v)]) }) });
    refs.lectura = el("div", { class: "callout left", "data-sec": "simulador.lectura" });
    refs.curva.dataset.sec = "simulador.curva"; refs.casc.dataset.sec = "simulador.casc";

    raiz.replaceChildren(
      cabecera("h4", "Simulador", "¿Cuánto vale cada decisión de capacidad?", "Cambia un supuesto y se recalcula toda la base. Los cambios también se aplican al Resumen y a la Lista."),
      el("div", { class: "sim-layout", "data-auto": "" }, panel, el("div", { class: "stack", "data-auto": "" },
        el("div", { class: "tiles t4", "data-sec": "simulador.tiles" }, refs.t.map(t => t.n)), refs.aviso, refs.lectura, refs.curva, el("div", { class: "grid g-53", "data-auto": "" }, refs.casc, mix))));
    sincronizar();
  }
  function update() {
    const r = correr(), hoy = escenarioHoy();
    [r.contactos, r.conv, r.desembolso, r.ve].forEach((v, i) => tween(refs.t[i].b, v, refs.t[i].f));
    refs.t[0].em.textContent = `de ${int(P.cap)} disponibles`;
    refs.t[1].em.textContent = `${pct(r.conv / (r.contactos || 1), 1)} de conversión`;
    refs.t[2].em.textContent = meta.modelo.horizonte ? `P × monto, ${meta.modelo.horizonte}` : "P × monto";
    refs.t[3].em.textContent = `${soles(r.ingreso)} ingreso − ${soles(r.costo)} costo`;
    refs.aviso.hidden = r.contactos >= P.cap;
    refs.aviso.textContent = `Solo ${int(r.contactos)} empresas son rentables con estos supuestos: el resto de la capacidad no se usa.`;
    const dif = r.ve - hoy.ve, veces = hoy.ve > 0 ? r.ve / hoy.ve : null;
    refs.lectura.replaceChildren(el("b", { text: `Frente a llamar leads al azar, la propuesta suma ${soles(dif)}` }), veces ? ` (${nf.format(".1f")(veces)}x de valor) ` : " ",
      `con los mismos ${int(Math.min(P.cap, r.contactos))} contactos.`);
    const tot = r.contactos || 1;
    refs.mix.setAttribute("aria-label", r.porGrupo.map((n, i) => `${NOMBRE_G[i]}: ${pct(n / tot)}`).join(", "));
    refs.mix.replaceChildren(...r.porGrupo.map((n, i) => (n ? el("div", { style: `flex-grow:${n};background:${COLOR[i]}`, title: `${NOMBRE_G[i]}: ${int(n)}`, text: n / tot > .09 ? pct(n / tot) : "" }) : null)).filter(Boolean));
    refs.mixLeg.replaceChildren(...r.porGrupo.map((n, i) => (n || i < 2 ? el("span", {}, el("i", { style: `background:${COLOR[i]}` }), `${NOMBRE_G[i]}: ${int(n)}`) : null)).filter(Boolean));
  }
  function draw(anim) {
    const esc = gCurvas(refs.curva.cuerpo, anim);
    refs.curvaLeg.replaceChildren(leyenda(esc.map(e => ({ color: e.color, text: e.nombre, kind: "line" }))));
    gCascada(refs.casc.cuerpo);
    refs.curva.refrescarTabla(); refs.casc.refrescarTabla();
  }
  return { init, update, draw };
})();

/* ---------- Ficha ---------- */
const drawer = document.getElementById("drawer"), scrim = document.getElementById("scrim");
function cerrarFicha() {
  drawer.classList.remove("on"); scrim.classList.remove("on"); drawer.setAttribute("aria-hidden", "true");
  setTimeout(() => { scrim.hidden = true; }, ms(300));
}
function abrirFicha(f) {
  const ve = veFila(f);
  const barras = el("div", { class: "chart" });
  const dato = (k, v) => el("div", {}, el("span", { text: k }), v ?? "Sin dato");
  drawer.replaceChildren(
    el("div", { class: "dr-head" }, el("button", { class: "dr-close", type: "button", "aria-label": "Cerrar ficha", text: "×", onclick: cerrarFicha }),
      el("h2", { text: f.id }), el("p", { text: `${NOMBRE_G[f.g]} · ${lista.rubros[f.rubro]} · ${lista.departamentos[f.depto]}` })),
    el("div", { class: "dr-body" },
      el("div", { class: "tiles t3" },
        el("div", { class: "tile" }, el("span", { text: "Probabilidad" }), el("b", { text: pct(f.p, 1) })),
        el("div", { class: "tile" }, el("span", { text: "Monto" }), el("b", { text: soles(f.m) })),
        el("div", { class: "tile accent" }, el("span", { text: "Valor esperado" }), el("b", { text: soles(ve) }))),
      el("h4", { text: "Por qué contactarla" }), el("ul", { class: "motivos" }, motivos(f).slice(0, 4).map(m => el("li", { text: m }))),
      el("h4", { text: f.g === 2 ? "Cobros mensuales observados" : "Ventas mensuales" }), barras,
      el("h4", { text: "Datos" }),
      el("div", { class: "dl" }, dato("Segmento", lista.segmentos[f.seg]), dato("Rating", f.rating), dato("Antigüedad", f.antig != null ? `${nf.format(".1f")(f.antig)} años` : null),
        dato("Productos con el banco", f.prod), dato(f.g === 2 ? "Cobros observados 12 meses" : "Ventas 12 meses", soles(f.ventas)), dato("Días de crédito", f.dias != null ? int(f.dias) : null), dato("Aceptantes", int(f.nac)), dato("Uso de línea", f.uso != null ? pct(f.uso) : null)),
      f.ancla ? el("h4", { text: "Principal aceptante" }) : null,
      f.ancla ? el("p", {}, !tabOculta("red") && red.anclas.some(a => a.id === f.ancla)
        ? el("button", { class: "link", type: "button", text: f.ancla, onclick() { cerrarFicha(); vRed.elegir(f.ancla); ir("red"); } }) : f.ancla,
      ` · ${soles(f.volAncla)} en 12 meses`) : null));
  scrim.hidden = false;
  requestAnimationFrame(() => { scrim.classList.add("on"); drawer.classList.add("on"); });
  drawer.setAttribute("aria-hidden", "false"); drawer.focus({ preventScroll: true }); drawer.scrollTop = 0;
  if (f.serie) requestAnimationFrame(() => {
    const data = f.serie.map((v, i) => ({ v, p: lista.periodos[i] }));
    const { g, w, h } = lienzo(barras, 120, { t: 8, r: 4, b: 22, l: 4 });
    const x = d3.scaleBand(data.map(d => d.p), [0, w]).padding(.3), y = d3.scaleLinear([0, d3.max(data, d => d.v) || 1], [h, 0]);
    g.selectAll("path").data(data).join("path").attr("fill", COLOR[0]).attr("d", d => rectTop(x(d.p), h, x.bandwidth(), 0))
      .on("pointermove", (ev, d) => tip.show(ev, mesTxt(d.p), [{ color: COLOR[0], v: soles(d.v * 1000), k: "" }])).on("pointerleave", tip.hide)
      .transition().delay((_, i) => i * 30).duration(ms(500)).attrTween("d", d => t => rectTop(x(d.p), y(d.v * t), x.bandwidth(), (h - y(d.v)) * t, 3));
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${h})`).call(d3.axisBottom(x).tickSize(0).tickPadding(6).tickValues([data[0].p, data[11].p]).tickFormat(mesTxt)).call(s => s.select(".domain").remove());
  });
  else barras.append(el("p", { class: "sub", text: "Sin historial mensual." }));
}
scrim.addEventListener("click", cerrarFicha);
addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (drawer.classList.contains("on")) cerrarFicha();
  else vAjustes.cerrar();
});

/* ---------- Vista: Lista ---------- */
const vLista = (() => {
  const raiz = document.getElementById("view-lista");
  const refs = {};
  const F = { grupos: [1, 1, 1], rubro: -1, seg: -1, depto: -1, q: "", soloDentro: true };
  const orden = { k: "ve", dir: -1 };
  let pagina = 0, vista = [];
  const POR_PAG = 20;
  const columnas = [
    { k: "rank", t: "#", r: 1 }, { k: "id", t: "Empresa" }, { k: "g", t: "Grupo" }, { k: "rubro", t: "Rubro" }, { k: "seg", t: "Tamaño" },
    { k: "depto", t: "Región" }, { k: "p", t: "Probabilidad", r: 1 }, { k: "m", t: "Monto", r: 1 }, { k: "ve", t: "Valor esperado", r: 1 }, { t: "Motivo principal" },
  ];
  function filtrar() {
    const q = F.q.trim().toUpperCase();
    vista = ranking().filter(({ f, dentro }) => F.grupos[f.g] && (F.rubro < 0 || f.rubro === F.rubro) && (F.seg < 0 || f.seg === F.seg) && (F.depto < 0 || f.depto === F.depto) && (!q || f.id.includes(q)) && (!F.soloDentro || dentro));
    const v = o => (orden.k === "rank" ? o.rank : orden.k === "ve" ? o.ve : o.f[orden.k]);
    vista.sort((a, b) => (d3.ascending(v(a), v(b)) || a.rank - b.rank) * (orden.k === "id" || v(a) !== v(b) ? orden.dir : 1));
  }
  function refrescar(anim = false) { pagina = 0; filtrar(); resumenFiltro(); tabla(); gDispersion(refs.mapa.cuerpo, [...vista].sort((a, b) => b.ve - a.ve), anim, abrirFicha); }
  function resumenFiltro() {
    const s = (fn) => d3.sum(vista, fn);
    tween(refs.t[0], vista.length, int); tween(refs.t[1], s(o => o.f.p), int);
    tween(refs.t[2], s(o => o.f.p * o.f.m), soles); tween(refs.t[3], s(o => o.ve), soles);
  }
  function tabla() {
    const ini = pagina * POR_PAG, filas = vista.slice(ini, ini + POR_PAG);
    refs.tbody.replaceChildren(...filas.map(o => {
      const f = o.f;
      const tr = el("tr", { class: o.dentro ? "" : "fuera", tabindex: 0, onclick: () => abrirFicha(f), onkeydown(ev) { if (ev.key === "Enter") abrirFicha(f); } },
        el("td", { class: "r", text: int(o.rank) }), el("td", { text: f.id }),
        el("td", {}, el("span", { class: "pill" }, el("i", { style: `background:${COLOR[f.g]}` }), NOMBRE_G[f.g])),
        el("td", { text: lista.rubros[f.rubro] }), el("td", { text: lista.segmentos[f.seg] }), el("td", { text: lista.departamentos[f.depto] }),
        el("td", { class: "r" }, el("span", { class: "pbar" }, el("i", { style: `width:${Math.min(f.p * 200, 100)}%` })), pct(f.p, 1)),
        el("td", { class: "r", text: soles(f.m) }), el("td", { class: "r", text: soles(o.ve) }), el("td", { class: "motivo", text: motivos(f)[0] }));
      return tr;
    }));
    const paginas = Math.max(1, Math.ceil(vista.length / POR_PAG));
    refs.pagTxt.textContent = vista.length ? `${int(ini + 1)}–${int(Math.min(ini + POR_PAG, vista.length))} de ${int(vista.length)} empresas` : "Sin empresas para este filtro";
    refs.prev.disabled = pagina === 0; refs.next.disabled = pagina >= paginas - 1;
    refs.ths.forEach(({ th, c }) => { const on = c.k === orden.k; th.classList.toggle("sorted", on); th.textContent = c.t + (on ? (orden.dir < 0 ? " ↓" : " ↑") : ""); th.setAttribute("aria-sort", on ? (orden.dir < 0 ? "descending" : "ascending") : "none"); });
  }
  function csv() {
    const esc = v => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
    const cab = ["orden", "id_empresa", "grupo", "rubro", "segmento", "departamento", "p_conversion", "monto_esperado", "valor_esperado", "motivo_1", "motivo_2", "motivo_3"];
    const filas = vista.map(o => { const f = o.f, m = motivos(f); return [o.rank, f.id, NOMBRE_G[f.g], lista.rubros[f.rubro], lista.segmentos[f.seg], lista.departamentos[f.depto], f.p, f.m, Math.round(o.ve), m[0], m[1], m[2]].map(esc).join(","); });
    const blob = new Blob(["﻿" + [cab.join(","), ...filas].join("\n")], { type: "text/csv;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob), download: "empresas_a_contactar.csv" });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  function init() {
    const chips = el("div", { class: "chipset", role: "group", "aria-label": "Grupo" }, GRUPOS_VIS.map(({ n, i }) => el("button", {
      class: "chip", type: "button", "aria-pressed": "true", onclick(ev) { F.grupos[i] = F.grupos[i] ? 0 : 1; ev.currentTarget.setAttribute("aria-pressed", F.grupos[i] ? "true" : "false"); refrescar(); },
    }, el("i", { style: `background:${COLOR[i]}` }), n)));
    const sel = (k, t, ops) => el("select", { class: "select", "aria-label": t, onchange(ev) { F[k] = +ev.target.value; refrescar(); } },
      el("option", { value: -1, text: t }), ops.map((o, i) => el("option", { value: i, text: o })));
    const dentro = el("input", { type: "checkbox", checked: true, onchange(ev) { F.soloDentro = ev.target.checked; refrescar(); } });
    refs.btn = el("button", { class: "btn", type: "button", text: "Descargar CSV", onclick: csv });
    const filtros = el("div", { class: "filters", "data-sec": "lista.filtros" }, chips, sel("rubro", "Rubro", lista.rubros), sel("seg", "Tamaño", lista.segmentos.slice(0, 3)), sel("depto", "Región", lista.departamentos),
      el("input", { class: "search", type: "search", placeholder: "Buscar ID", "aria-label": "Buscar empresa por ID", oninput(ev) { F.q = ev.target.value; refrescar(); } }),
      el("label", { class: "check", style: "margin:0;align-items:center" }, dentro, "Solo dentro de capacidad"), el("div", { class: "spacer" }), refs.btn);
    refs.t = [];
    const tiles = el("div", { class: "tiles t4", "data-sec": "lista.tiles" }, ["Empresas", "Conversiones esperadas", "Desembolso esperado", "Valor esperado neto"].map((t, i) => { const b = el("b", { text: "0" }); refs.t.push(b); return el("div", { class: `tile${i === 3 ? " accent" : ""}` }, el("span", { text: t }), b); }));
    refs.mapa = tarjeta({ titulo: "Mapa de oportunidades", sub: "Hasta 700 empresas con mayor valor. Claras: quedan fuera de la capacidad." });
    refs.mapa.insertBefore(leyenda(GRUPOS_VIS.map(({ n, i }) => ({ color: COLOR[i], text: n, kind: "round" }))), refs.mapa.cuerpo);
    refs.mapa.dataset.sec = "lista.mapa";
    refs.ths = columnas.map(c => {
      const th = el("th", { class: c.r ? "r" : "", scope: "col", text: c.t, ...(c.k ? { "data-k": c.k, tabindex: 0 } : {}) });
      const ordenar = () => { if (orden.k === c.k) orden.dir *= -1; else { orden.k = c.k; orden.dir = ["id", "rubro", "seg", "depto", "g", "rank"].includes(c.k) ? 1 : -1; } pagina = 0; filtrar(); tabla(); };
      if (c.k) { th.addEventListener("click", ordenar); th.addEventListener("keydown", e => { if (e.key === "Enter") ordenar(); }); }
      return { th, c };
    });
    refs.tbody = el("tbody");
    refs.pagTxt = el("span");
    refs.prev = el("button", { class: "ghost", type: "button", text: "Anterior", onclick() { pagina--; tabla(); } });
    refs.next = el("button", { class: "ghost", type: "button", text: "Siguiente", onclick() { pagina++; tabla(); } });
    const tablaCard = el("div", { class: "card reveal", "data-sec": "lista.tabla" }, el("div", { class: "tbl-wrap" }, el("table", { class: "data" }, el("thead", {}, el("tr", {}, refs.ths.map(t => t.th))), refs.tbody)),
      el("div", { class: "pager" }, refs.pagTxt, el("div", {}, refs.prev, refs.next)));
    raiz.replaceChildren(
      cabecera("h5", "Lista a contactar", "A qué empresas llamar primero", `Ordenadas por valor esperado con los supuestos del simulador. Se incluyen las ${int(FILAS.length)} empresas de mayor valor. Toca una fila para ver su ficha.`),
      filtros, el("div", { class: "stack" }, tiles, refs.mapa, tablaCard));
  }
  return { init, update() { filtrar(); resumenFiltro(); tabla(); }, draw(anim) { gDispersion(refs.mapa.cuerpo, [...vista].sort((a, b) => b.ve - a.ve), anim, abrirFicha); } };
})();

/* ---------- Vista: Red ---------- */
const vRed = (() => {
  const raiz = document.getElementById("view-red");
  const refs = {};
  let actual = red.anclas[0]?.id, sim = null;
  const maxPot = d3.max(red.anclas, a => a.potencial) || 1;
  function listaAnclas() {
    refs.anclas.replaceChildren(...red.anclas.map((a, i) => el("button", {
      class: "anchor", type: "button", "aria-pressed": a.id === actual ? "true" : "false", onclick() { elegir(a.id); },
    }, el("div", { class: "anchor-row" }, el("span", {}, el("b", { text: a.id })), el("span", { text: soles(a.potencial) })),
    el("div", { class: "anchor-row sub", style: "color:var(--muted);font-size:13px" }, el("span", { text: `${i + 1}. ${a.rubro} · ${a.departamento}` }), el("span", { text: `${compact(a.n_oport)} prov.` })),
    el("div", { class: "anchor-bar" }, el("i", { style: `width:${a.potencial / maxPot * 100}%` })))));
  }
  function elegir(id) {
    actual = id; if (!refs.anclas) return;
    listaAnclas(); ficha(); grafo(true); refs.card?.refrescarTabla();
  }
  function ficha() {
    const a = red.anclas.find(x => x.id === actual);
    refs.tiles.replaceChildren(...[
      ["Potencial sin explotar", soles(a.potencial), "Σ P × monto de nuevos"],
      ["Proveedores con oportunidad", int(a.n_oport), `de ${int(a.n_prov)} proveedores`],
      HAY_C ? ["No clientes", int(a.n_captacion), "proveedores a captar"] : ["Ya usan factoring", int(a.n_usa), "proveedores"],
      ["Volumen con factoring", pct(a.pct_vol_usa, 1), "de lo que compra"],
    ].map(([t, v, n], i) => el("div", { class: `tile${i === 0 ? " accent" : ""}` }, el("span", { text: t }), el("b", { text: v }), el("em", { text: n }))));
    refs.txt.replaceChildren(el("b", { text: `Estrategia de cadena con ${a.id}: ` }),
      `el banco ya conoce al pagador y ${int(a.n_oport)} de sus proveedores califican${HAY_C ? `; ${int(a.n_captacion)} aún no son clientes` : ""}.`);
  }
  function grafo(anim) {
    const a = red.anclas.find(x => x.id === actual);
    const c = refs.card.cuerpo;
    if (sim) sim.stop();
    const alto = Math.min(620, Math.max(420, c.clientWidth * .62));
    const { g, w, h } = lienzo(c, alto, { t: 0, r: 0, b: 0, l: 0 });
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) / 2 - 24;
    const rad = d3.scaleSqrt([0, d3.max(a.proveedores, p => p[4] * p[5]) || 1], [5, 17]);
    const dist = d3.scaleLog(d3.extent(a.proveedores, p => p[4]).map(v => v || .01), [R, R * .36]);
    const nodos = a.proveedores.map(([id, gr, prev, vol, p, m], i) => {
      const ang = i / a.proveedores.length * 2 * Math.PI * 7.3, r = dist(p || .01);
      return { id, gr, prev, vol, p, m, r: rad(p * m), obj: r, x: cx + Math.cos(ang) * r, y: cy + Math.sin(ang) * r };
    });
    const centro = { id: a.id, centro: true, fx: cx, fy: cy, r: 30 };
    const enlaces = nodos.map(n => ({ source: centro, target: n }));
    const lin = g.append("g").selectAll("line").data(enlaces).join("line").attr("stroke", "#C9D5E4").attr("stroke-width", d => Math.max(1, Math.min(2.5, Math.log10(d.target.vol) / 3))).attr("x1", cx).attr("y1", cy).attr("x2", cx).attr("y2", cy);
    const nod = g.append("g").selectAll("circle").data(nodos).join("circle")
      .attr("r", anim && MOTION ? 0 : d => d.r).attr("fill", d => (d.prev ? "#fff" : COLOR[d.gr])).attr("stroke", d => (d.prev ? COLOR[d.gr] : "#fff")).attr("stroke-width", 2)
      .attr("tabindex", 0).attr("role", "button").attr("aria-label", d => `${d.id}, ${NOMBRE_G[d.gr]}, ${pct(d.p, 1)}`).style("cursor", "pointer")
      .on("pointermove", (ev, d) => tip.show(ev, `${d.id} · ${NOMBRE_G[d.gr]}${d.prev ? " · ya usa factoring" : ""}`, [{ v: pct(d.p, 1), k: "probabilidad" }, { v: soles(d.m), k: "monto si convierte" }, { v: soles(d.vol), k: "le vende a la ancla" }]))
      .on("pointerleave", tip.hide)
      .on("click", (ev, d) => { const f = POR_ID.get(d.id); if (f) abrirFicha(f); })
      .on("keydown", (ev, d) => { if (ev.key === "Enter") { const f = POR_ID.get(d.id); if (f) abrirFicha(f); } });
    const hub = g.append("g").attr("transform", `translate(${cx},${cy})`);
    hub.append("circle").attr("r", 30).attr("fill", NAVY).attr("stroke", "#fff").attr("stroke-width", 3);
    hub.append("text").attr("text-anchor", "middle").attr("dy", 4).attr("fill", "#fff").attr("font-size", 11).attr("font-weight", 700).text("Ancla");
    if (anim && MOTION) nod.transition().delay((_, i) => 120 + i * 18).duration(500).ease(d3.easeBackOut).attr("r", d => d.r);
    const tick = () => {
      nodos.forEach(n => { n.x = Math.max(n.r + 2, Math.min(w - n.r - 2, n.x)); n.y = Math.max(n.r + 2, Math.min(h - n.r - 2, n.y)); });
      lin.attr("x1", cx).attr("y1", cy).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      nod.attr("cx", d => d.x).attr("cy", d => d.y);
    };
    sim = d3.forceSimulation([centro, ...nodos])
      .force("rad", d3.forceRadial(d => d.obj || 0, cx, cy).strength(d => (d.centro ? 0 : .5)))
      .force("col", d3.forceCollide(d => d.r + 3).strength(.9))
      .force("carga", d3.forceManyBody().strength(-14))
      .alphaDecay(.035).on("tick", tick);
    if (!MOTION) { sim.stop(); sim.tick(250); tick(); }
    else if (!anim) { sim.tick(250); tick(); sim.stop(); }
  }
  function init() {
    refs.anclas = el("div", { class: "anchors" });
    refs.tiles = el("div", { class: "tiles t4", "data-sec": "red.tiles" });
    refs.txt = el("div", { class: "callout left", "data-sec": "red.txt" });
    refs.card = tarjeta({ titulo: "Proveedores de la ancla seleccionada", sub: `Muestra de ${int(d3.max(red.anclas, a => a.proveedores.length))} con mayor valor por grupo. Más cerca del centro: mayor probabilidad. Tamaño: P × monto.`, tabla: () => {
      const a = red.anclas.find(x => x.id === actual);
      return { cols: ["Proveedor", "Grupo", "Probabilidad", "Monto", "Le vende a la ancla"], filas: a.proveedores.map(([id, gr, prev, vol, p, m]) => [id, NOMBRE_G[gr] + (prev ? " · ya usa" : ""), pct(p, 1), soles(m), soles(vol)]) };
    } });
    refs.card.insertBefore(leyenda([...GRUPOS_VIS.map(({ n, i }) => ({ color: COLOR[i], text: n, kind: "round" })), { color: "#fff", text: "Ya usa factoring", kind: "hollow" }]), refs.card.cuerpo);
    refs.card.dataset.sec = "red.card";
    raiz.replaceChildren(
      cabecera("h6", "Red de aceptantes", "Una ancla arrastra a sus proveedores", `Las ${int(red.anclas.length)} anclas con más potencial concentran ${pct(red.totales.top_share)} del valor sin explotar entre ${int(red.totales.aceptantes)} aceptantes.`),
      el("div", { class: "red-layout", "data-auto": "" },
        el("div", { class: "card reveal", "data-sec": "red.anclas" }, el("h3", { text: "Anclas por potencial", style: "margin-bottom:10px" }), refs.anclas),
        el("div", { class: "stack", "data-auto": "" }, refs.tiles, refs.txt, refs.card)));
    listaAnclas(); ficha();
  }
  return { init, update() {}, draw: grafo, elegir };
})();

/* ---------- ajustes: pestañas, secciones y textos ---------- */
const SECCIONES = {
  resumen: [["hero", "Indicador principal"], ["etapas", "Habilitar, Valorar y Priorizar"], ["conc", "¿Quiénes? Top 30% frente a la base"], ...(HAY_IMP ? [["imp", "¿Por qué? Variables del modelo"]] : []), ["perfil", "Perfil del top 30%"],
    ...(resumen.backtest ? [["gan", "¿Qué tan confiable es el ranking?"]] : []), ["hist", "Factoring desembolsado por mes"]],
  simulador: [["panel", "Panel de supuestos"], ["tiles", "Indicadores"], ["lectura", "Comparación frente a hoy"], ["curva", "Valor acumulado según contactos"], ["casc", "Palancas de valor"], ["mix", "A quién llega la capacidad"]],
  lista: [["filtros", "Filtros y descarga CSV"], ["tiles", "Indicadores"], ["mapa", "Mapa de oportunidades"], ["tabla", "Tabla de empresas"]],
  red: [["anclas", "Anclas por potencial"], ["tiles", "Indicadores de la ancla"], ["txt", "Estrategia de cadena"], ["card", "Proveedores de la ancla"]],
};
/* Una cabecera se oculta cuando todas las secciones que introduce estan ocultas. */
const CABECERAS = [["resumen", "h1", ["etapas"]], ["resumen", "h2", ["conc", "imp", "perfil", "gan"]], ["resumen", "h3", ["hist"]], ["simulador", "h4"], ["lista", "h5"], ["red", "h6"]];
const CLAVE_AJUSTES = "dash-ajustes-v1";
const ajustesBase = () => ({ titulo: "", pie: "", tabsOcultas: [], tabsNombres: {}, seccionesOcultas: [], ...JSON.parse(JSON.stringify(window.DASH.ajustes || {})) });
function leerAjustes() {
  try { return { ...ajustesBase(), ...JSON.parse(localStorage.getItem(CLAVE_AJUSTES) || "{}") }; } catch { return ajustesBase(); }
}
const AJ = leerAjustes();
const tabOculta = v => AJ.tabsOcultas.includes(v);
const secOculta = (v, id) => AJ.seccionesOcultas.includes(`${v}.${id}`);
const primeraVisible = () => Object.keys(SECCIONES).find(v => !tabOculta(v));
const cabeceraVisible = (v, ids) => !ids || SECCIONES[v].some(([id]) => ids.includes(id) && !secOculta(v, id));

function cabecera(id, eyebrow, titulo, sub) {
  return el("div", { class: `section-head${sub ? "" : " section-gap"}` },
    el("div", { class: "eyebrow", "data-cab": id, "data-t": eyebrow }), el("h2", { class: "h-title", text: titulo }),
    sub ? el("p", { class: "h-sub", text: sub }) : null);
}
/* Reparte el ancho entre lo que quedo visible: mas interno primero, porque un contenedor vacio cuenta como oculto. */
function acomodar(raiz) {
  [...raiz.querySelectorAll("[data-auto]")].reverse().forEach(c => {
    const vis = [...c.children].filter(n => !n.hasAttribute("data-off") && !n.hidden);
    c.toggleAttribute("data-off", !vis.length);
    c.classList.toggle("solo", vis.length === 1);
    [...c.children].forEach(n => n.classList.remove("ancho"));
    if (c.classList.contains("g2") && vis.length % 2) vis.at(-1).classList.add("ancho");
  });
}
function aplicarVista(v) {
  const raiz = document.getElementById(`view-${v}`);
  raiz.querySelectorAll("[data-sec]").forEach(n => n.toggleAttribute("data-off", AJ.seccionesOcultas.includes(n.dataset.sec)));
  let n = 0;
  for (const [vista, id, ids] of CABECERAS) {
    if (tabOculta(vista) || !cabeceraVisible(vista, ids)) continue;
    n++;
    const nodo = vista === v && raiz.querySelector(`[data-cab=${id}]`);
    if (nodo) nodo.textContent = `${String(n).padStart(2, "0")} | ${nodo.dataset.t}`;
  }
  CABECERAS.filter(c => c[0] === v).forEach(([, id, ids]) => raiz.querySelector(`[data-cab=${id}]`)?.parentElement.toggleAttribute("data-off", !cabeceraVisible(v, ids)));
  acomodar(raiz);
}
function aplicarAjustes(redibujar = true) {
  const titulo = AJ.titulo || TITULO_BASE;
  document.getElementById("brandTitulo").textContent = titulo;
  document.title = titulo;
  document.getElementById("footMarca").textContent = AJ.pie || PIE_BASE;
  tabs.forEach(b => { b.hidden = tabOculta(b.dataset.view); b.textContent = AJ.tabsNombres[b.dataset.view] || b.dataset.nombre; });
  hechas.forEach(aplicarVista);
  if (actual && tabOculta(actual)) ir(primeraVisible());
  else if (actual && redibujar) { VISTAS[actual].draw(false); ponerTinta(); }
}

const vAjustes = (() => {
  const panel = document.getElementById("ajustes"), boton = document.getElementById("btnAjustes");
  const ctl = { tabs: {}, secs: {} };
  let hecho = false;
  function guardar() {
    try { localStorage.setItem(CLAVE_AJUSTES, JSON.stringify(AJ)); } catch { /* sin almacenamiento: vale solo para esta sesion */ }
    aplicarAjustes();
    sincronizar();
  }
  const alternar = (lista, clave, visible) => (visible ? lista.filter(x => x !== clave) : [...lista, clave]);
  function interruptor(texto, onchange) {
    const input = el("input", { type: "checkbox", role: "switch", onchange });
    const label = el("label", { class: "aj-sw" }, input, el("i", { "aria-hidden": "true" }), texto ? el("span", { text: texto }) : null);
    return { input, label };
  }
  function sincronizar() {
    const visibles = Object.keys(SECCIONES).filter(v => !tabOculta(v));
    for (const v of Object.keys(SECCIONES)) {
      const c = ctl.tabs[v], on = !tabOculta(v);
      c.sw.input.checked = on;
      c.sw.input.disabled = on && visibles.length === 1;
      c.sw.label.title = c.sw.input.disabled ? "Debe quedar al menos una pestaña" : "";
      c.nombre.value = AJ.tabsNombres[v] || "";
      c.secs.hidden = !on;
      const secsOn = SECCIONES[v].filter(([id]) => !secOculta(v, id)).length;
      SECCIONES[v].forEach(([id]) => {
        const s = ctl.secs[`${v}.${id}`], visible = !secOculta(v, id);
        s.input.checked = visible;
        s.input.disabled = visible && secsOn === 1;
        s.label.title = s.input.disabled ? "Debe quedar al menos una sección" : "";
      });
    }
    ctl.titulo.value = AJ.titulo; ctl.pie.value = AJ.pie;
  }
  function descargar() {
    const { titulo, pie, tabsOcultas, tabsNombres, seccionesOcultas } = AJ;
    const txt = `window.DASH=window.DASH||{};window.DASH.ajustes=${JSON.stringify({ titulo, pie, tabsOcultas, tabsNombres, seccionesOcultas })};\n`;
    const a = el("a", { href: URL.createObjectURL(new Blob([txt], { type: "text/javascript" })), download: "ajustes.js" });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  function restablecer() {
    try { localStorage.removeItem(CLAVE_AJUSTES); } catch { /* nada que borrar */ }
    Object.assign(AJ, ajustesBase());
    aplicarAjustes();
    sincronizar();
  }
  function construir() {
    const campo = (t, ph, k) => {
      const input = el("input", { class: "aj-input", type: "text", placeholder: ph, "aria-label": t, oninput(ev) { AJ[k] = ev.target.value; guardar(); } });
      ctl[k] = input;
      return el("label", { class: "aj-campo" }, el("span", { text: t }), input);
    };
    const pestanas = Object.keys(SECCIONES).map(v => {
      const base = tabs.find(b => b.dataset.view === v).dataset.nombre;
      const sw = interruptor("", ev => { AJ.tabsOcultas = alternar(AJ.tabsOcultas, v, ev.target.checked); guardar(); });
      sw.input.setAttribute("aria-label", `Mostrar la pestaña ${base}`);
      const nombre = el("input", { class: "aj-input", type: "text", placeholder: base, "aria-label": `Nombre de la pestaña ${base}`, oninput(ev) { AJ.tabsNombres = { ...AJ.tabsNombres, [v]: ev.target.value }; guardar(); } });
      const secs = el("div", { class: "aj-secs" }, SECCIONES[v].map(([id, t]) => {
        const s = interruptor(t, ev => { AJ.seccionesOcultas = alternar(AJ.seccionesOcultas, `${v}.${id}`, ev.target.checked); guardar(); });
        ctl.secs[`${v}.${id}`] = s;
        return s.label;
      }));
      ctl.tabs[v] = { sw, nombre, secs };
      return el("div", { class: "aj-tab" }, el("div", { class: "aj-tab-top" }, sw.label, nombre), secs);
    });
    const dato = (k, v) => el("div", {}, el("span", { text: k }), v);
    panel.replaceChildren(
      el("div", { class: "dr-head" }, el("button", { class: "dr-close", type: "button", "aria-label": "Cerrar ajustes", text: "×", onclick: cerrar }),
        el("h2", { text: "Ajustes" }), el("p", { text: "Los cambios se ven al instante y quedan guardados en este navegador." })),
      el("div", { class: "dr-body" },
        el("h4", { text: "Textos" }), campo("Título", TITULO_BASE, "titulo"), campo("Pie de página", PIE_BASE, "pie"),
        el("h4", { text: "Pestañas y secciones" }), pestanas,
        el("h4", { text: "Datos cargados" }),
        el("div", { class: "dl" }, dato("Dataset", meta.dataset?.nombre || "Sin dato"), dato("Carpeta", meta.dataset?.carpeta || "Sin dato"), dato("Corte", mesTxt(meta.corte)),
          dato("Modelo", `${meta.modelo.nombre} · ${meta.modelo.version}`), dato("Monto", meta.modelo.monto || "Del modelo"), dato("Actualizado", meta.generado), dato("Empresas evaluadas", int(resumen.embudo.evaluables))),
        el("ol", { class: "aj-pasos" },
          el("li", { text: "Copia las bases nuevas en una carpeta e indícala en dataset.json." }),
          el("li", { text: "Haz doble clic en ACTUALIZAR.bat." }),
          el("li", { text: "Recarga esta página." })),
        el("button", { class: "ghost", type: "button", text: "Recargar página", onclick() { location.reload(); } }),
        el("h4", { text: "Llevar a otra computadora" }),
        el("p", { class: "aj-nota", text: "Descarga ajustes.js y reemplaza el archivo dashboard/inputs/ajustes.js." }),
        el("div", { class: "aj-acciones" }, el("button", { class: "btn", type: "button", text: "Descargar ajustes.js", onclick: descargar }), el("button", { class: "ghost", type: "button", text: "Restablecer", onclick: restablecer }))));
    hecho = true;
  }
  function abrir() {
    if (!hecho) construir();
    sincronizar();
    panel.classList.add("on"); panel.setAttribute("aria-hidden", "false"); boton.setAttribute("aria-expanded", "true");
    panel.focus({ preventScroll: true });
  }
  function cerrar() {
    if (!panel.classList.contains("on")) return;
    panel.classList.remove("on"); panel.setAttribute("aria-hidden", "true"); boton.setAttribute("aria-expanded", "false");
    boton.focus({ preventScroll: true });
  }
  boton.addEventListener("click", () => (panel.classList.contains("on") ? cerrar() : abrir()));
  return { cerrar };
})();

/* ---------- navegacion ---------- */
const VISTAS = { resumen: vResumen, simulador: vSim, lista: vLista, red: vRed };
const hechas = new Set();
let actual = null;
const tabs = [...document.querySelectorAll(".tabs button")], ink = document.querySelector(".tab-ink");
tabs.forEach(b => { b.dataset.nombre = b.textContent; });
const TITULO_BASE = document.getElementById("brandTitulo").textContent, PIE_BASE = document.getElementById("footMarca").textContent;
function ponerTinta() {
  const b = tabs.find(t => t.getAttribute("aria-selected") === "true");
  if (b) { ink.style.width = `${b.offsetWidth}px`; ink.style.transform = `translateX(${b.offsetLeft}px)`; }
}
function ir(nombre) {
  if (!VISTAS[nombre] || tabOculta(nombre)) nombre = primeraVisible();
  if (location.hash.slice(1) !== nombre) history.replaceState(null, "", `#${nombre}`);
  actual = nombre;
  tip.hide();
  for (const k in VISTAS) document.getElementById(`view-${k}`).hidden = k !== nombre;
  tabs.forEach(b => b.setAttribute("aria-selected", b.dataset.view === nombre ? "true" : "false"));
  ponerTinta();
  const v = VISTAS[nombre], raiz = document.getElementById(`view-${nombre}`);
  const primera = !hechas.has(nombre);
  if (primera) { v.init(); hechas.add(nombre); aplicarVista(nombre); revelar(raiz); }
  v.update();
  v.draw(primera);
  scrollTo({ top: 0, behavior: "instant" });
}
tabs.forEach(b => b.addEventListener("click", () => ir(b.dataset.view)));
addEventListener("hashchange", () => ir(location.hash.slice(1)));
let rz;
addEventListener("resize", () => {
  clearTimeout(rz);
  rz = setTimeout(() => {
    if (actual) VISTAS[actual].draw(false);
    ponerTinta();
  }, 150);
});

/* ---------- cabecera ---------- */
const badge = document.getElementById("modelBadge");
if (meta.modelo.tipo === "simulado") badge.remove();
else { badge.textContent = `${meta.modelo.nombre} · ${meta.modelo.version}`; badge.classList.add("real"); }
document.getElementById("brandSub").textContent = `Datos al corte ${mesTxt(meta.corte)}`;
document.getElementById("footInfo").textContent = `Actualizado ${meta.generado}`;
aplicarAjustes(false);
document.fonts?.ready.then(() => ir(location.hash.slice(1) || primeraVisible()));
window.__dash = { P, correr, ranking, ir, AJ };
})();
