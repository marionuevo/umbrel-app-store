"use strict";

/* Panel de estadísticas. Sin librerías: los gráficos son SVG a mano, que para
   dos áreas y unas listas de barras es menos código que traerse una
   dependencia — y así la página funciona sin salir a Internet. */

// ── Formato ──────────────────────────────────────────────────────────────────
const NUM = new Intl.NumberFormat("es-ES");
const NUM1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });
const PAIS = (() => {
  try { return new Intl.DisplayNames(["es"], { type: "region" }); } catch { return null; }
})();

const n = (v) => NUM.format(v || 0);

function bytes(v) {
  v = v || 0;
  if (v < 1024) return v + " B";
  const u = ["kB", "MB", "GB", "TB"];
  let i = -1;
  do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
  return NUM1.format(v) + " " + u[i];
}

function ms(seg) {
  if (!seg) return "0 ms";
  return seg < 1 ? Math.round(seg * 1000) + " ms" : NUM1.format(seg) + " s";
}

function nombrePais(cc) {
  if (!cc) return "Desconocido";
  let nom = cc;
  try { nom = PAIS ? PAIS.of(cc) || cc : cc; } catch { /* código inventado */ }
  // Bandera a partir del código ISO: cada letra a su indicador regional.
  const bandera = /^[A-Z]{2}$/.test(cc)
    ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65))
    : "";
  return (bandera ? bandera + " " : "") + nom;
}

function horaCorta(ts) {
  return new Date(ts * 1000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function etiquetaEjeX(ts, cubo) {
  const d = new Date(ts * 1000);
  if (cubo >= 86400) return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
  if (cubo >= 10800) return d.toLocaleString("es-ES", { day: "numeric", hour: "2-digit", minute: "2-digit" });
  return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function fechaLarga(ts, cubo) {
  const d = new Date(ts * 1000);
  return cubo >= 86400
    ? d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })
    : d.toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ── Series ───────────────────────────────────────────────────────────────────
// Orden fijo. El color sigue a la entidad, así que filtrar no repinta nada.
const SERIES = {
  persona: { etiqueta: "Personas", color: "--serie-persona" },
  bot: { etiqueta: "Bots y buscadores", color: "--serie-bot" },
  sondeo: { etiqueta: "Sondeos", color: "--serie-sondeo" },
  // Serie sintética del gráfico de tráfico: una sola, en el primer color.
  trafico: { etiqueta: "Tráfico", color: "--serie-persona" },
};
const ORDEN = ["persona", "bot", "sondeo"];

function colorEstado(codigo) {
  const c = Math.floor(codigo / 100);
  if (c === 2) return "--est-bien";
  if (c === 3) return "--texto-3";
  if (c === 4) return "--est-aviso";
  if (c >= 5) return "--est-critico";
  return "--texto-3";
}

// ── Estado ───────────────────────────────────────────────────────────────────
const estado = { datos: null, fuente: null, ultimoId: 0, vivas: [] };
const $ = (id) => document.getElementById(id);
const filtros = () => ({
  rango: $("f-rango").value,
  sitio: $("f-sitio").value,
  tipo: $("f-tipo").value,
});

// ── Carga ────────────────────────────────────────────────────────────────────
let cargando = false;

async function cargar() {
  if (cargando) return;
  cargando = true;
  // Sin esqueleto: se mantiene el render anterior atenuado y no salta el diseño.
  $("panel").setAttribute("aria-busy", "true");
  const f = filtros();
  try {
    const r = await fetch(`/api/panel?rango=${f.rango}&sitio=${encodeURIComponent(f.sitio)}&tipo=${f.tipo}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    estado.datos = await r.json();
    pintar();
  } catch (e) {
    $("sub").textContent = "No se pudo cargar: " + e.message;
  } finally {
    cargando = false;
    $("panel").setAttribute("aria-busy", "false");
  }
}

function pintar() {
  const d = estado.datos;
  if (!d) return;
  rellenarSitios(d.sitios);
  pintarTarjetas(d);
  pintarActividad(d);
  pintarTrafico(d);
  pintarPaneles(d);
  pintarPie(d);
}

function rellenarSitios(sitios) {
  const sel = $("f-sitio");
  const actual = sel.value;
  const quiero = ["todos", ...sitios].join("|");
  if (sel.dataset.cargado === quiero) return;
  sel.innerHTML = '<option value="todos">Todos los sitios</option>' +
    sitios.map((s) => `<option value="${s}">${s}</option>`).join("");
  sel.value = sitios.includes(actual) || actual === "todos" ? actual : "todos";
  sel.dataset.cargado = quiero;
}

// ── Tarjetas ─────────────────────────────────────────────────────────────────
function pintarTarjetas(d) {
  const r = d.resumen;
  const rep = r.reparto || {};
  const total = ORDEN.reduce((a, k) => a + ((rep[k] || {}).peticiones || 0), 0);
  const noHumano = ((rep.bot || {}).peticiones || 0) + ((rep.sondeo || {}).peticiones || 0);

  $("k-paginas").textContent = n(r.paginas);
  $("k-paginas-pie").textContent = r.visitantes
    ? NUM1.format(r.paginas / r.visitantes) + " por visitante"
    : "";

  $("k-visitantes").textContent = n(r.visitantes);
  $("k-visitantes-pie").textContent = "direcciones IP distintas";

  $("k-peticiones").textContent = n(r.peticiones);
  $("k-peticiones-pie").textContent = total
    ? `${Math.round((noHumano / total) * 100)}% del tráfico total no es humano`
    : "";

  $("k-bytes").textContent = bytes(r.bytes);
  $("k-bytes-pie").textContent = r.peticiones
    ? bytes(r.bytes / r.peticiones) + " por petición"
    : "";

  $("k-rt").textContent = ms(r.rt);
  $("k-rt-pie").textContent = "tiempo de servicio de nginx";

  const activos = r.activos || 0;
  $("ahora").hidden = false;
  $("activos").textContent = n(activos);
  $("ahora").title = `Visitantes distintos en los últimos ${d.ventana_activos} minutos`;

  const etq = { persona: "personas", bot: "bots", sondeo: "sondeos", todos: "todo el tráfico" }[d.tipo];
  $("nota-filtro").textContent = `Mostrando ${etq}` + (d.sitio !== "todos" ? ` · ${d.sitio}` : "");
}

// ── Gráfico de áreas ─────────────────────────────────────────────────────────
const SVGNS = "http://www.w3.org/2000/svg";
const el = (t, attrs = {}) => {
  const e = document.createElementNS(SVGNS, t);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
};

function escalaBonita(max) {
  if (max <= 0) return { max: 1, paso: 1 };
  const crudo = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(crudo)));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((p) => p >= crudo) || mag * 10;
  return { max: Math.ceil(max / paso) * paso, paso };
}

/* Dibuja áreas apiladas (o una sola) con rejilla, eje y capa de hover.
   claves: lista de series a apilar; valor: función (punto, clave) -> número. */
function areas(caja, puntos, claves, opciones) {
  const { formato = n, etiquetaSerie = (k) => SERIES[k].etiqueta } = opciones;
  caja.innerHTML = "";
  const ancho = caja.clientWidth || 640;
  const alto = caja.clientHeight || 236;

  const svg = el("svg", { viewBox: `0 0 ${ancho} ${alto}`, preserveAspectRatio: "none" });
  svg.setAttribute("role", "img");
  caja.appendChild(svg);

  if (!puntos.length) {
    svg.appendChild(el("text", { x: ancho / 2, y: alto / 2, "text-anchor": "middle", class: "sin-datos" }))
      .textContent = "Sin datos en este periodo";
    return;
  }

  const totales = puntos.map((p) => claves.reduce((a, k) => a + (p[k] || 0), 0));
  const { max, paso } = escalaBonita(Math.max(...totales));

  // El margen se ajusta a la etiqueta más larga del eje: "28,6 MB" no cabe en
  // el hueco que basta para "6000", y recortada no se lee.
  let anchoEtq = 0;
  for (let v = 0; v <= max + 1e-9; v += paso) anchoEtq = Math.max(anchoEtq, formato(v).length);
  const izq = Math.max(44, 14 + anchoEtq * 7), der = 10, arriba = 12, abajo = 28;
  const w = Math.max(10, ancho - izq - der);
  const h = Math.max(10, alto - arriba - abajo);
  const x = (i) => izq + (puntos.length === 1 ? w / 2 : (i * w) / (puntos.length - 1));
  const y = (v) => arriba + h - (v / max) * h;

  // Rejilla y eje Y: líneas continuas de un tono sobre el fondo.
  for (let v = 0; v <= max + 1e-9; v += paso) {
    svg.appendChild(el("line", { x1: izq, y1: y(v), x2: izq + w, y2: y(v), class: "rejilla-linea" }));
    const t = el("text", { x: izq - 8, y: y(v) + 4, "text-anchor": "end", class: "eje-txt" });
    t.textContent = formato(v);
    svg.appendChild(t);
  }

  // Eje X: como mucho 6 marcas, y nunca solapadas.
  const cada = Math.max(1, Math.ceil(puntos.length / 6));
  puntos.forEach((p, i) => {
    if (i % cada && i !== puntos.length - 1) return;
    const t = el("text", { x: x(i), y: arriba + h + 18, "text-anchor": "middle", class: "eje-txt" });
    t.textContent = etiquetaEjeX(p.t, opciones.cubo);
    svg.appendChild(t);
  });

  // Apilado de abajo a arriba. El trazo del color del fondo abre los 2px de
  // separación entre capas sin dibujar un borde.
  const base = new Array(puntos.length).fill(0);
  claves.forEach((clave) => {
    const techo = puntos.map((p, i) => base[i] + (p[clave] || 0));
    let d = "";
    techo.forEach((v, i) => { d += (i ? "L" : "M") + x(i) + "," + y(v); });
    for (let i = puntos.length - 1; i >= 0; i--) d += "L" + x(i) + "," + y(base[i]);
    d += "Z";
    const color = css(SERIES[clave].color);
    svg.appendChild(el("path", { d, fill: color, "fill-opacity": claves.length > 1 ? .82 : .16, class: "capa" }));
    if (claves.length === 1) {
      let l = "";
      techo.forEach((v, i) => { l += (i ? "L" : "M") + x(i) + "," + y(v); });
      svg.appendChild(el("path", { d: l, stroke: color, class: "linea" }));
    }
    techo.forEach((v, i) => { base[i] = v; });
  });

  // El último cubo casi nunca está completo: a media hora de un cubo de una
  // hora, la barra cae a la mitad y parece que el tráfico se ha hundido. Se
  // marca en vez de esconderlo, que el dato es real, solo que parcial.
  if (opciones.parcial && puntos.length > 1) {
    const x0 = x(puntos.length - 1) - (w / (puntos.length - 1)) / 2;
    svg.appendChild(el("rect", {
      x: x0, y: arriba, width: Math.max(2, izq + w - x0), height: h,
      fill: css("--texto-3"), "fill-opacity": .10,
    }));
  }

  // ── Capa de hover: cruz, puntos y tooltip ──────────────────────────────────
  const cruz = el("line", { class: "cruz", y1: arriba, y2: arriba + h, opacity: 0 });
  svg.appendChild(cruz);
  const marcas = claves.map((clave) =>
    svg.appendChild(el("circle", { r: 4.5, fill: css(SERIES[clave].color), class: "punto", opacity: 0 })));

  const capa = el("rect", { x: izq, y: arriba, width: w, height: h, fill: "transparent" });
  capa.style.cursor = "crosshair";
  svg.appendChild(capa);

  const tip = $("tooltip");
  const mostrar = (ev) => {
    const caja2 = svg.getBoundingClientRect();
    const px = ((ev.clientX - caja2.left) / caja2.width) * ancho;
    const i = Math.max(0, Math.min(puntos.length - 1,
      Math.round(((px - izq) / w) * (puntos.length - 1))));
    const p = puntos[i];

    cruz.setAttribute("x1", x(i)); cruz.setAttribute("x2", x(i)); cruz.setAttribute("opacity", 1);
    let acc = 0;
    claves.forEach((clave, j) => {
      acc += p[clave] || 0;
      marcas[j].setAttribute("cx", x(i));
      marcas[j].setAttribute("cy", y(acc));
      marcas[j].setAttribute("opacity", 1);
    });

    const enCurso = opciones.parcial && i === puntos.length - 1;
    let html = `<h4>${fechaLarga(p.t, opciones.cubo)}` +
      (enCurso ? ' <span style="color:var(--texto-3);font-weight:400">· en curso</span>' : "") + "</h4>";
    claves.forEach((clave) => {
      html += `<div class="tt-fila"><span><i style="background:${css(SERIES[clave].color)}"></i>` +
        `${etiquetaSerie(clave)}</span><b>${formato(p[clave] || 0)}</b></div>`;
    });
    if (claves.length > 1) {
      const tot = claves.reduce((a, k) => a + (p[k] || 0), 0);
      html += `<div class="tt-fila" style="margin-top:5px;padding-top:5px;border-top:1px solid var(--borde)">` +
        `<span>Total</span><b>${formato(tot)}</b></div>`;
    }
    tip.innerHTML = html;
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let tx = ev.clientX + 14, ty = ev.clientY - th - 12;
    if (tx + tw > innerWidth - 8) tx = ev.clientX - tw - 14;
    if (ty < 8) ty = ev.clientY + 18;
    tip.style.left = tx + "px";
    tip.style.top = ty + "px";
  };
  const ocultar = () => {
    tip.hidden = true;
    cruz.setAttribute("opacity", 0);
    marcas.forEach((m) => m.setAttribute("opacity", 0));
  };
  capa.addEventListener("mousemove", mostrar);
  capa.addEventListener("mouseleave", ocultar);
  capa.addEventListener("touchstart", (e) => mostrar(e.touches[0]), { passive: true });
  capa.addEventListener("touchmove", (e) => mostrar(e.touches[0]), { passive: true });
  capa.addEventListener("touchend", ocultar);
}

function clavesVisibles(tipo) {
  return tipo === "todos" ? ORDEN : [tipo];
}

function pintarActividad(d) {
  const claves = clavesVisibles(d.tipo);
  areas($("g-actividad"), d.serie, claves, { cubo: d.cubo, formato: n, parcial: true });
  pintarLeyenda($("leyenda-actividad"), claves);
  tablaSerie($("tabla-actividad"), d.serie, claves, d.cubo, n, "Peticiones", true);
}

function pintarTrafico(d) {
  // Los bytes van en su propio gráfico: dos escalas en un mismo eje mentirían.
  // Se suman solo los tipos que el filtro deja ver, para que el gráfico y la
  // tarjeta de "Tráfico servido" cuenten lo mismo.
  const visibles = clavesVisibles(d.tipo);
  const puntos = d.serie.map((p) => ({
    t: p.t,
    trafico: visibles.reduce((a, k) => a + (p["b_" + k] || 0), 0),
  }));
  areas($("g-trafico"), puntos, ["trafico"], { cubo: d.cubo, formato: bytes, parcial: true });
  // Una sola serie no necesita leyenda: el título ya la nombra.
  $("leyenda-trafico").innerHTML = "";
  tablaSerie($("tabla-trafico"), puntos, ["trafico"], d.cubo, bytes, "Tráfico", true);
}

function pintarLeyenda(caja, claves) {
  caja.innerHTML = claves.length < 2 ? "" : claves.map((k) =>
    `<span><i style="background:${css(SERIES[k].color)}"></i>${SERIES[k].etiqueta}</span>`).join("");
}

/* Gemela en tabla de cada gráfico: todo valor es legible sin depender del
   color ni del tooltip. */
function tablaSerie(caja, puntos, claves, cubo, fmt, titulo, parcial) {
  const cab = claves.length > 1
    ? claves.map((k) => `<th class="num">${SERIES[k].etiqueta}</th>`).join("")
    : `<th class="num">${titulo}</th>`;
  caja.innerHTML =
    `<table><thead><tr><th>Momento</th>${cab}</tr></thead><tbody>` +
    puntos.map((p, i) =>
      `<tr><td>${fechaLarga(p.t, cubo)}` +
      (parcial && i === puntos.length - 1 ? ' <span style="color:var(--texto-3)">· en curso</span>' : "") + "</td>" +
      claves.map((k) => `<td class="num">${fmt(p[k] || 0)}</td>`).join("") + "</tr>").join("") +
    "</tbody></table>";
}

// ── Paneles de barras ────────────────────────────────────────────────────────
function barras(caja, titulo, sub, filas, opciones = {}) {
  const {
    etiqueta = (f) => f.clave || "—",
    valor = (f) => f.n,
    texto = (f) => `<b>${n(f.n)}</b>`,
    color = () => "--serie-persona",
  } = opciones;

  if (!filas || !filas.length) {
    caja.innerHTML = `<h2>${titulo}</h2><p class="p-sub">${sub}</p><p class="vacio">Nada que mostrar.</p>`;
    return;
  }
  const max = Math.max(...filas.map(valor)) || 1;
  caja.innerHTML =
    `<h2>${titulo}</h2><p class="p-sub">${sub}</p><div class="barras">` +
    filas.map((f) => {
      const c = css(color(f));
      const pct = (valor(f) / max) * 100;
      return `<div class="barra" style="--pct:${pct.toFixed(1)}%;--barra-color:${c}">` +
        `<span class="b-etq" title="${String(etiqueta(f)).replace(/"/g, "&quot;")}">` +
        `<i style="background:${c}"></i>${etiqueta(f)}</span>` +
        `<span class="b-num">${texto(f)}</span></div>`;
    }).join("") + "</div>";
}

const escapar = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function pintarPaneles(d) {
  const L = d.listas;
  const conVisitantes = (f) => `<b>${n(f.n)}</b> · ${n(f.visitantes)} vis.`;

  barras($("c-sitios"), "Sitios", "Peticiones y visitantes por dominio",
    L.sitios, { etiqueta: (f) => escapar(f.clave), texto: conVisitantes });

  barras($("c-paginas"), "Páginas más vistas", "Solo páginas: las fotos y los ficheros no cuentan",
    L.paginas, { etiqueta: (f) => escapar(f.clave), texto: conVisitantes });

  barras($("c-paises"), "Países", "Según la cabecera CF-IPCountry de Cloudflare",
    L.paises, { etiqueta: (f) => nombrePais(f.clave), texto: conVisitantes });

  const proc = (L.procedencias || []).length ? L.procedencias : L.proc_tipos;
  barras($("c-procedencias"),
    (L.procedencias || []).length ? "De dónde llegan" : "Tipo de procedencia",
    "Dominios que enlazan hacia estas webs",
    proc, { etiqueta: (f) => escapar(f.clave), texto: conVisitantes });

  barras($("c-navegadores"), "Navegadores", "Deducido del user-agent",
    L.navegadores, { etiqueta: (f) => escapar(f.clave) });

  barras($("c-sistemas"), "Sistemas operativos", "Deducido del user-agent",
    L.sistemas, { etiqueta: (f) => escapar(f.clave) });

  barras($("c-dispositivos"), "Dispositivos", "Escritorio, móvil o tableta",
    L.dispositivos, { etiqueta: (f) => escapar(f.clave) });

  barras($("c-estados"), "Códigos de respuesta", "Verde correcto, ámbar del cliente, rojo del servidor",
    L.estados, {
      etiqueta: (f) => `${f.clave} ${textoEstado(f.clave)}`,
      color: (f) => colorEstado(f.clave),
    });

  barras($("c-sondeos"), "Sondeos de vulnerabilidades",
    "Buscan WordPress, .env o phpMyAdmin y se llevan un 404: aquí no hay nada de eso",
    L.sondeos, {
      etiqueta: (f) => escapar(f.clave),
      color: () => "--serie-sondeo",
      texto: (f) => `<b>${n(f.n)}</b> · ${n(f.visitantes)} IP`,
    });
}

function textoEstado(c) {
  return ({
    200: "OK", 204: "sin contenido", 206: "parcial", 301: "movido", 302: "encontrado",
    304: "sin cambios", 400: "petición mala", 403: "prohibido", 404: "no existe",
    405: "método no permitido", 408: "expiró", 429: "demasiadas", 499: "cliente cortó",
    500: "error interno", 502: "pasarela mala", 503: "no disponible", 504: "pasarela expiró",
  })[c] || "";
}

function pintarPie(d) {
  const desde = new Date(d.desde * 1000).toLocaleString("es-ES");
  $("sub").textContent = `${n(d.resumen.peticiones)} peticiones desde ${desde}`;
  $("pie-txt").textContent =
    `Los datos salen del log de nginx. La IP real se recupera de CF-Connecting-IP; ` +
    `sin ella todo el tráfico parecería venir de la pasarela de Docker.`;
}

// ── Vista de tabla ───────────────────────────────────────────────────────────
document.querySelectorAll(".btn-tabla").forEach((b) => {
  b.addEventListener("click", () => {
    const g = $("g-" + b.dataset.para), t = $("tabla-" + b.dataset.para);
    const mostrarTabla = t.hidden;
    t.hidden = !mostrarTabla;
    g.hidden = mostrarTabla;
    b.textContent = mostrarTabla ? "Ver gráfico" : "Ver tabla";
  });
});

// ── Hilo en vivo (SSE) ───────────────────────────────────────────────────────
function conectarVivo() {
  if (estado.fuente) estado.fuente.close();
  const f = filtros();
  const url = `/api/vivo?sitio=${encodeURIComponent(f.sitio)}&tipo=todos`;
  const fuente = new EventSource(url);
  estado.fuente = fuente;

  fuente.addEventListener("open", () => { $("estado-vivo").textContent = "en directo"; });
  fuente.addEventListener("error", () => { $("estado-vivo").textContent = "reconectando…"; });
  fuente.addEventListener("peticiones", (ev) => {
    let filas;
    try { filas = JSON.parse(ev.data); } catch { return; }
    if (!filas.length) return;
    $("estado-vivo").textContent = "en directo";
    añadirVivas(filas);
    // Las cifras de arriba se refrescan de vez en cuando, no en cada petición:
    // recalcular agregados 40 veces por minuto no aporta nada.
    programarRefresco();
  });
}

function añadirVivas(filas) {
  const caja = $("vivo");
  const arriba = caja.scrollTop < 24;
  for (const r of filas) {
    const div = document.createElement("div");
    div.className = "v-fila";
    div.innerHTML =
      `<span class="v-hora">${horaCorta(r.ts)}</span>` +
      `<span class="v-tipo" style="color:${css(SERIES[r.tipo].color)}">${SERIES[r.tipo].etiqueta.split(" ")[0]}</span>` +
      `<span class="v-ruta" title="${escapar(r.ruta)}">${escapar(r.ruta)}</span>` +
      `<span class="v-sitio">${escapar(r.host)}</span>` +
      `<span class="v-est" style="color:${css(colorEstado(r.estado))}">${r.estado}</span>`;
    caja.prepend(div);
  }
  while (caja.children.length > 120) caja.lastChild.remove();
  if (arriba) caja.scrollTop = 0;
}

let refrescoPendiente = null;
function programarRefresco() {
  if (refrescoPendiente) return;
  refrescoPendiente = setTimeout(() => { refrescoPendiente = null; cargar(); }, 10000);
}

// ── Arranque ─────────────────────────────────────────────────────────────────
["f-rango", "f-sitio", "f-tipo"].forEach((id) =>
  $(id).addEventListener("change", () => { cargar(); conectarVivo(); }));

$("tema").addEventListener("click", () => {
  const oscuro = matchMedia("(prefers-color-scheme: dark)").matches;
  const actual = document.documentElement.dataset.theme || (oscuro ? "dark" : "light");
  document.documentElement.dataset.theme = actual === "dark" ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch { /* modo privado */ }
  if (estado.datos) pintar();
});

try {
  const t = localStorage.getItem("tema");
  if (t) document.documentElement.dataset.theme = t;
} catch { /* sin almacenamiento: se queda con el del sistema */ }

let tempRedibujo = null;
addEventListener("resize", () => {
  clearTimeout(tempRedibujo);
  tempRedibujo = setTimeout(() => { if (estado.datos) { pintarActividad(estado.datos); pintarTrafico(estado.datos); } }, 150);
});

// Un refresco de fondo cubre el caso de que no entre ni una petición: los
// periodos se mueven aunque el tráfico esté parado.
setInterval(cargar, 60000);

cargar();
conectarVivo();
