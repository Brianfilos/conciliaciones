/* Tablero de Reportería — SVG a mano, sin librerías.
   Todo texto que viene de los datos entra por textContent (nunca innerHTML). */
(function () {
  'use strict';
  const root = document.getElementById('rp');
  if (!root) return;

  const S1 = '#2a78d6', S2 = '#eb6834';
  const RAMPA = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#104281'];
  const FILTROS = ['proceso', 'ano', 'pago', 'cxc', 'periodo'];
  const SVG_TAGS = new Set(['svg', 'g', 'rect', 'path', 'line', 'text', 'title']);
  const NS = 'http://www.w3.org/2000/svg';

  let datos = JSON.parse(document.getElementById('rp-datos').textContent);
  const st = { municipio: root.dataset.municipio, metrica: 'n', tablas: {} };
  FILTROS.forEach(k => { st[k] = datos.filtros[k] || null; });

  const $ = id => document.getElementById(id);
  const nf = new Intl.NumberFormat('es-CO');
  const dec1 = v => v.toLocaleString('es-CO', { maximumFractionDigits: 1 });
  // Montos en lenguaje corriente: "$ 95.001 millones", "$ 14,5 millones", "$ 4.200"
  function money(v) {
    const a = Math.abs(v);
    if (a >= 1e12) return '$ ' + dec1(v / 1e12) + ' billones';
    if (a >= 1e8) return '$ ' + nf.format(Math.round(v / 1e6)) + ' millones';
    if (a >= 1e6) { const m = Math.round(v / 1e5) / 10; return '$ ' + dec1(m) + (m === 1 ? ' millón' : ' millones'); }
    return '$ ' + nf.format(Math.round(v));
  }
  const moneyEje = v => (Math.abs(v) >= 1e6 ? '$ ' + nf.format(Math.round(v / 1e5) / 10) + ' M' : '$ ' + nf.format(v));
  const moneyFull = v => '$ ' + nf.format(Math.round(v));
  const pct = (a, b) => { if (!b || !a) return '0 %'; const p = (100 * a) / b; return p > 0 && p < 1 ? '<1 %' : Math.round(p) + ' %'; };
  const cap = s => s.charAt(0) + s.slice(1).toLowerCase();
  const nombreCxc = c => (c === 'SIN_CARGAR' ? 'Sin cargar en el sistema' : cap(c));
  const nombrePago = p => (p === 'PAGADO' ? 'Pagadas' : 'Pendientes');

  function el(tag, attrs, ...kids) {
    const e = SVG_TAGS.has(tag) ? document.createElementNS(NS, tag) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const clear = n => { while (n.firstChild) n.removeChild(n.firstChild); return n; };

  /* ── Estado y datos ─────────────────────────────────────────── */
  let ctl = null;
  async function refresh() {
    $('rp-grid').classList.add('loading');
    $('rp-kpis').classList.add('loading');
    if (ctl) ctl.abort();
    ctl = new AbortController();
    const q = new URLSearchParams({ municipio: st.municipio });
    FILTROS.forEach(k => { if (st[k]) q.set(k, st[k]); });
    try {
      const r = await fetch(root.dataset.url + '?' + q, { signal: ctl.signal, credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      datos = await r.json();
      history.replaceState(null, '', '?' + q);
      render();
    } catch (e) {
      if (e.name !== 'AbortError') $('tiempo-note').textContent = 'No se pudo actualizar el tablero (' + e.message + '). Recarga la página.';
    } finally {
      $('rp-grid').classList.remove('loading');
      $('rp-kpis').classList.remove('loading');
    }
  }
  function alternar(k, v) { st[k] = st[k] === v ? null : v; refresh(); }
  function fijar(k, v) { st[k] = v || null; refresh(); }

  /* ── Tooltip: una sola, valores primero ─────────────────────── */
  const tip = $('rp-tip');
  function mostrarTip(x, y, titulo, filas) {
    clear(tip);
    tip.append(el('div', { class: 'rp-tip-t', text: titulo }));
    filas.forEach(f => tip.append(el('div', { class: 'rp-tip-r' },
      el('span', {}, f.color ? el('i', { class: 'rp-key', style: 'background:' + f.color }) : null, f.label),
      el('b', { text: f.valor }))));
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 14)) + 'px';
    tip.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 14)) + 'px';
  }
  const ocultarTip = () => { tip.hidden = true; };
  // Enlaza hover, foco de teclado y clic a una marca
  function marca(hit, { titulo, filas, alClic, etiqueta }) {
    hit.setAttribute('tabindex', '0');
    hit.setAttribute('role', 'button');
    hit.setAttribute('aria-label', etiqueta);
    hit.addEventListener('pointermove', e => mostrarTip(e.clientX, e.clientY, titulo, filas));
    hit.addEventListener('pointerleave', ocultarTip);
    hit.addEventListener('pointerdown', e => { if (e.pointerType === 'touch') mostrarTip(e.clientX, e.clientY, titulo, filas); });
    hit.addEventListener('focus', () => { const b = hit.getBoundingClientRect(); mostrarTip(b.left + b.width / 2, b.top, titulo, filas); });
    hit.addEventListener('blur', ocultarTip);
    hit.addEventListener('click', alClic);
    hit.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alClic(); } });
  }

  /* ── Utilidades de gráficos ─────────────────────────────────── */
  function ticks(max) {
    if (max <= 0) return [0, 1];
    const paso0 = max / 4, mag = Math.pow(10, Math.floor(Math.log10(paso0)));
    const paso = [1, 2, 2.5, 5, 10].map(m => m * mag).find(p => p >= paso0);
    const out = [];
    for (let v = 0; v <= max + paso * 0.999; v += paso) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }
  // Barra con extremo de datos redondeado (4px) y base recta
  function barraV(x, y, w, h) {
    if (h <= 0) return '';
    const r = Math.min(4, h, w / 2);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  function barraH(x, y, w, h, redondo) {
    if (w <= 0) return '';
    const r = redondo ? Math.min(4, w, h / 2) : 0;
    return r
      ? `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`
      : `M${x},${y}H${x + w}V${y + h}H${x}Z`;
  }
  const ancho = n => Math.max(300, Math.floor(n.getBoundingClientRect().width) || 600);
  const cortar = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

  function tabla(cols, filas) {
    return el('div', { class: 'rp-table-scroll' }, el('table', { class: 'rp-table' },
      el('thead', {}, el('tr', {}, cols.map((c, i) => el('th', { class: i ? 'num' : '', text: c })))),
      el('tbody', {}, filas.map(f => el('tr', {}, f.map((c, i) => el('td', { class: i ? 'num' : '', text: c })))))));
  }
  function herramientas(cont, botones) {
    clear(cont);
    botones.forEach(b => cont.append(el('button', { type: 'button', class: 'rp-btn', 'aria-pressed': b.on ? 'true' : 'false', onclick: b.fn, text: b.t })));
  }
  const vacio = (cont, msg) => clear(cont).append(el('div', { class: 'rp-empty', text: msg }));

  /* ── Filtros (una sola fila) ────────────────────────────────── */
  function renderFiltros() {
    const cont = clear($('rp-filters'));
    const procs = datos.procesos.filter(p => p.pagado + p.pendiente > 0);
    if (datos.procesos.length > 1) {
      cont.append(el('div', { class: 'rp-fgroup' }, el('span', { class: 'rp-flabel', text: 'Proceso' }),
        el('div', { class: 'rp-seg' },
          el('button', { type: 'button', 'aria-pressed': String(!st.proceso), onclick: () => fijar('proceso', null), text: 'Todos' }),
          datos.procesos.map(p => el('button', { type: 'button', 'aria-pressed': String(st.proceso === p.id), onclick: () => alternar('proceso', p.id), text: p.nombre })))));
    }
    const anos = datos.anos.slice();
    if (st.ano && !anos.includes(st.ano)) anos.unshift(st.ano);
    if (anos.length) {
      cont.append(el('div', { class: 'rp-fgroup' }, el('label', { class: 'rp-flabel', for: 'f-ano', text: 'Año' }),
        el('select', { id: 'f-ano', class: 'rp-select', onchange: e => fijar('ano', e.target.value) },
          el('option', { value: '', text: 'Todos' }),
          anos.map(a => el('option', { value: a, selected: st.ano === a, text: a })))));
    }
    const chips = [];
    if (st.pago) chips.push(['Pago', nombrePago(st.pago), 'pago']);
    if (st.cxc) chips.push(['Sistema', nombreCxc(st.cxc), 'cxc']);
    if (st.periodo) chips.push(['Período', (datos.tiempo.etiquetas[datos.tiempo.claves.indexOf(st.periodo)] || st.periodo), 'periodo']);
    chips.forEach(([t, v, k]) => cont.append(el('button', { type: 'button', class: 'rp-chip', 'aria-label': 'Quitar filtro ' + t, onclick: () => fijar(k, null) }, t + ':', el('b', { text: v }), ' ✕')));
    if (chips.length || st.proceso || st.ano) {
      cont.append(el('button', { type: 'button', class: 'rp-clear', onclick: () => { FILTROS.forEach(k => { st[k] = null; }); refresh(); }, text: 'Limpiar todo' }));
    }
    cont.append(el('span', { class: 'rp-spacer' }));
    cont.append(el('details', { class: 'rp-explore' },
      el('summary', { class: 'rp-btn', text: 'Explorar registros ▾' }),
      el('div', { class: 'rp-explore-menu' }, datos.explorar.map(x => el('a', { href: x.url, text: x.nombre })))));
  }

  /* ── KPIs ───────────────────────────────────────────────────── */
  function kpi(o) {
    const cuerpo = [
      el('div', { class: 'rp-kpi-l' }, o.color ? el('i', { class: 'rp-dot', style: 'background:' + o.color }) : null, o.etiqueta),
      el('div', { class: 'rp-kpi-v', text: o.valor }),
      o.sub ? el('div', { class: 'rp-kpi-s', text: o.sub, title: o.titulo || '' }) : null,
      o.meter != null ? el('div', { class: 'rp-meter' }, el('i', { style: `width:${o.meter}%;background:${o.color || S1}` })) : null,
    ];
    if (o.clic) return el('button', { type: 'button', class: 'rp-kpi' + (o.hero ? ' rp-kpi-hero' : ''), 'aria-pressed': String(!!o.on), onclick: o.clic }, cuerpo);
    return el('div', { class: 'rp-kpi' + (o.hero ? ' rp-kpi-hero' : '') }, cuerpo);
  }
  function renderKpis() {
    const k = datos.kpi, csv = datos.municipio.tiene_csv;
    const cont = clear($('rp-kpis'));
    cont.append(kpi({ hero: true, etiqueta: 'Declaraciones', valor: nf.format(k.total), sub: 'Valor total ' + money(k.valor), titulo: moneyFull(k.valor) }));
    cont.append(kpi({ etiqueta: 'Pagadas', color: S1, valor: nf.format(k.pagadas), sub: pct(k.pagadas, k.total) + ' · ' + money(k.pagadas_valor), titulo: moneyFull(k.pagadas_valor), meter: k.total ? 100 * k.pagadas / k.total : 0, on: st.pago === 'PAGADO', clic: () => alternar('pago', 'PAGADO') }));
    cont.append(kpi({ etiqueta: 'Pendientes de pago', color: S2, valor: nf.format(k.pendientes), sub: pct(k.pendientes, k.total) + ' · ' + money(k.pendientes_valor) + ' por cobrar', titulo: moneyFull(k.pendientes_valor), meter: k.total ? 100 * k.pendientes / k.total : 0, on: st.pago === 'PENDIENTE', clic: () => alternar('pago', 'PENDIENTE') }));
    if (csv) {
      cont.append(kpi({ etiqueta: 'En el sistema (CSV)', color: S1, valor: nf.format(k.en_sistema), sub: pct(k.en_sistema, k.total) + ' de las declaraciones', meter: k.total ? 100 * k.en_sistema / k.total : 0 }));
      cont.append(kpi({ etiqueta: 'Sin cargar en el sistema', color: S2, valor: nf.format(k.sin_cargar), sub: nf.format(k.sin_cargar_pagadas) + ' de ellas ya están pagadas', meter: k.total ? 100 * k.sin_cargar / k.total : 0, on: st.cxc === 'SIN_CARGAR', clic: () => alternar('cxc', 'SIN_CARGAR') }));
    }
  }

  /* ── Evolución en el tiempo ─────────────────────────────────── */
  function renderTiempo() {
    const T = datos.tiempo, v = st.metrica === 'valor';
    $('tiempo-titulo').textContent = 'Declaraciones por ' + (T.eje === 'bimestre' ? 'bimestre' : 'mes');
    herramientas($('tiempo-tools'), [
      { t: 'Cantidad', on: !v, fn: () => { st.metrica = 'n'; renderTiempo(); } },
      { t: 'Valor $', on: v, fn: () => { st.metrica = 'valor'; renderTiempo(); } },
      { t: st.tablas.tiempo ? 'Ver gráfico' : 'Ver tabla', on: !!st.tablas.tiempo, fn: () => { st.tablas.tiempo = !st.tablas.tiempo; renderTiempo(); } },
    ]);
    clear($('tiempo-legend')).append(
      el('span', {}, el('i', { class: 'rp-dot', style: 'background:' + S1 }), 'Pagadas'),
      el('span', {}, el('i', { class: 'rp-dot', style: 'background:' + S2 }), 'Pendientes'));
    $('tiempo-hint').textContent = 'Haz clic en una barra para filtrar por ese período.' + (v ? ' Ejes en millones de pesos (M).' : '');
    $('tiempo-note').textContent = T.sin_fecha ? nf.format(T.sin_fecha) + ' registros no traen fecha ni período y no aparecen en este gráfico.' : '';
    const body = $('tiempo-body');
    if (!T.claves.length) return vacio(body, 'No hay declaraciones con período para mostrar.');
    const A = v ? T.valor_pagado : T.pagado, B = v ? T.valor_pendiente : T.pendiente;
    const fmt = x => (v ? moneyFull(x) : nf.format(x));
    if (st.tablas.tiempo) {
      return clear(body).append(tabla(['Período', 'Pagadas', 'Pendientes', 'Total'],
        T.claves.map((c, i) => [T.etiquetas[i], fmt(A[i]), fmt(B[i]), fmt(A[i] + B[i])])));
    }
    const W = ancho(body), H = 268, m = { l: v ? 74 : 52, r: 8, t: 10, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b, n = T.claves.length, banda = iw / n;
    const tk = ticks(Math.max(...T.claves.map((_, i) => A[i] + B[i])));
    const ymax = tk[tk.length - 1] || 1;
    const y = val => m.t + ih * (1 - val / ymax);
    const bw = Math.min(24, banda * 0.7);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Declaraciones pagadas y pendientes por período' });
    tk.forEach(t => {
      svg.append(el('line', { class: t ? 'grid' : 'axis', x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
      svg.append(el('text', { x: m.l - 8, y: y(t) + 4, 'text-anchor': 'end', text: v ? moneyEje(t) : nf.format(t) }));
    });
    const cadaK = Math.ceil(66 / banda);
    T.claves.forEach((c, i) => {
      const cx = m.l + banda * i + banda / 2, x = cx - bw / 2, gap = 2;
      const hA = ih * A[i] / ymax, hB = ih * B[i] / ymax;
      const g = el('g', { class: 'band' + (st.periodo && st.periodo !== c ? ' dim' : '') });
      if (A[i] > 0) g.append(el('path', { class: 'mark', d: barraV(x, y(A[i]), bw, hA), fill: S1 }));
      if (B[i] > 0) {  // el segmento de arriba termina donde termina el total; 2px de aire sobre el de abajo
        g.append(el('path', { class: 'mark', d: barraV(x, y(A[i] + B[i]), bw, hB - (A[i] > 0 ? gap : 0)), fill: S2 }));
      }
      const hit = el('rect', { class: 'hit', x: cx - banda / 2, y: m.t, width: banda, height: ih + 6 });
      marca(hit, {
        titulo: T.etiquetas[i], etiqueta: `${T.etiquetas[i]}: ${fmt(A[i])} pagadas, ${fmt(B[i])} pendientes`,
        filas: [{ color: S1, label: 'Pagadas', valor: fmt(A[i]) }, { color: S2, label: 'Pendientes', valor: fmt(B[i]) }, { label: 'Total', valor: fmt(A[i] + B[i]) }],
        alClic: () => alternar('periodo', c),
      });
      g.append(hit);
      svg.append(g);
      if (i % cadaK === 0) svg.append(el('text', { x: cx, y: H - m.b + 17, 'text-anchor': 'middle', text: T.etiquetas[i] }));
    });
    clear(body).append(svg);
  }

  /* ── Estado en el sistema (CSV) ─────────────────────────────── */
  function renderCxc() {
    const card = $('card-cxc'), csv = datos.municipio.tiene_csv;
    card.hidden = !csv;
    if (!csv) return;
    const rows = datos.cxc, total = rows.reduce((s, r) => s + r.n, 0), body = $('cxc-body');
    herramientas($('cxc-tools'), [{ t: st.tablas.cxc ? 'Ver gráfico' : 'Ver tabla', on: !!st.tablas.cxc, fn: () => { st.tablas.cxc = !st.tablas.cxc; renderCxc(); } }]);
    if (!total) return vacio(body, 'Sin datos con estos filtros.');
    if (st.tablas.cxc) return clear(body).append(tabla(['Estado', 'Declaraciones', '%', 'Valor'], rows.map(r => [nombreCxc(r.clave), nf.format(r.n), pct(r.n, total), moneyFull(r.valor)])));
    const W = ancho(body), lw = Math.min(190, W * 0.4), rh = 40, H = rows.length * rh + 8, aw = W - lw - 120;
    const max = Math.max(...rows.map(r => r.n), 1);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Declaraciones por estado en el sistema' });
    svg.append(el('line', { class: 'axis', x1: lw, x2: lw, y1: 0, y2: H }));
    rows.forEach((r, i) => {
      const y0 = i * rh + 8, len = Math.max(r.n ? 3 : 0, aw * r.n / max);
      const g = el('g', { class: 'band' + (st.cxc && st.cxc !== r.clave ? ' dim' : '') });
      g.append(el('text', { class: 't-2', x: 0, y: y0 + 15, text: cortar(nombreCxc(r.clave), 26) }));
      g.append(el('path', { class: 'mark', d: barraH(lw, y0, len, 22, true), fill: r.clave === 'SIN_CARGAR' ? S2 : S1 }));
      g.append(el('text', { class: 't-ink', x: lw + len + 8, y: y0 + 15, text: `${nf.format(r.n)} · ${pct(r.n, total)}` }));
      const hit = el('rect', { class: 'hit', x: 0, y: y0 - 6, width: W, height: rh - 4 });
      marca(hit, {
        titulo: nombreCxc(r.clave), etiqueta: `${nombreCxc(r.clave)}: ${nf.format(r.n)} declaraciones`,
        filas: [{ label: 'Declaraciones', valor: nf.format(r.n) }, { label: 'Participación', valor: pct(r.n, total) }, { label: 'Valor', valor: money(r.valor) }],
        alClic: () => alternar('cxc', r.clave),
      });
      g.append(hit);
      svg.append(g);
    });
    clear(body).append(svg);
  }

  /* ── Cruce pago × sistema (mapa de calor) ───────────────────── */
  function renderCruce() {
    const card = $('card-cruce'), c = datos.cruce;
    card.hidden = !c;
    if (!c) return;
    const body = $('cruce-body');
    const total = c.celdas.flat().reduce((a, b) => a + b, 0);
    if (!total) { $('cruce-note').textContent = ''; return vacio(body, 'Sin datos con estos filtros.'); }
    const W = ancho(body), gap = 2, max = Math.max(...c.celdas.flat(), 1);
    // En pantallas angostas se transpone: estados en filas, Pagadas/Pendientes en columnas
    const T = W < 560;
    const filasK = T ? c.cols : c.filas, colsK = T ? c.filas : c.cols;
    const at = (i, j) => (T ? { pago: c.filas[j], cxc: c.cols[i], val: c.celdas[j][i] } : { pago: c.filas[i], cxc: c.cols[j], val: c.celdas[i][j] });
    const nombreK = k => (k === 'PAGADO' || k === 'PENDIENTE' ? nombrePago(k) : (k === 'SIN_CARGAR' ? 'Sin cargar' : cap(k)));
    const rl = T ? Math.min(128, W * 0.36) : 96, ch = T ? 30 : 44, cellH = T ? 42 : 64;
    const cw = (W - rl) / colsK.length, H = ch + filasK.length * (cellH + gap) + 4;
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Cruce entre pago y estado en el sistema' });
    colsK.forEach((k, j) => svg.append(el('text', { class: 't-2', x: rl + cw * j + cw / 2, y: ch - 12, 'text-anchor': 'middle', text: cortar(nombreK(k), T ? 12 : 13) }, el('title', { text: nombreK(k) }))));
    filasK.forEach((k, i) => {
      const y0 = ch + i * (cellH + gap);
      svg.append(el('text', { class: 't-2', x: 0, y: y0 + cellH / 2 + 4, text: cortar(nombreK(k), T ? 17 : 14) }, el('title', { text: nombreK(k) })));
      colsK.forEach((kc, j) => {
        const { pago, cxc, val } = at(i, j), x0 = rl + cw * j;
        const nivel = val ? Math.min(6, Math.floor(Math.sqrt(val / max) * 7)) : -1;
        const activa = st.pago === pago && st.cxc === cxc, atenuar = (st.pago || st.cxc) && !activa;
        const accion = pago === 'PAGADO' && cxc === 'SIN_CARGAR' && val > 0;
        const g = el('g', { class: 'band' + (atenuar ? ' dim' : '') });
        g.append(el('rect', { class: 'mark', x: x0 + gap / 2, y: y0, width: cw - gap, height: cellH, rx: 6, fill: nivel < 0 ? '#f1f5f9' : RAMPA[nivel] }));
        if (accion) g.append(el('rect', { x: x0 + gap / 2 + 1, y: y0 + 1, width: cw - gap - 2, height: cellH - 2, rx: 5, fill: 'none', stroke: S2, 'stroke-width': 3 }));
        g.append(el('text', { x: x0 + cw / 2, y: y0 + cellH / 2 + 5, 'text-anchor': 'middle', style: `font-size:${T ? 14 : 15}px;font-weight:600;fill:${nivel >= 3 ? '#fff' : '#0f172a'}`, text: nf.format(val) }));
        const hit = el('rect', { class: 'hit', x: x0, y: y0, width: cw, height: cellH });
        marca(hit, {
          titulo: `${nombrePago(pago)} · ${nombreCxc(cxc)}`, etiqueta: `${nombrePago(pago)}, ${nombreCxc(cxc)}: ${nf.format(val)}`,
          filas: [{ label: 'Declaraciones', valor: nf.format(val) }, { label: 'Del total', valor: pct(val, total) }],
          alClic: () => { if (activa) { st.pago = null; st.cxc = null; } else { st.pago = pago; st.cxc = cxc; } refresh(); },
        });
        g.append(hit);
        svg.append(g);
      });
    });
    clear(body).append(svg);
    const pc = c.celdas[0][c.cols.indexOf('SIN_CARGAR')] || 0;
    $('cruce-note').textContent = pc ? `El recuadro naranja marca ${nf.format(pc)} declaraciones ya pagadas que todavía no están en el sistema.` : '';
  }

  /* ── Por proceso ────────────────────────────────────────────── */
  function renderProcesos() {
    const ps = datos.procesos.filter(p => p.pagado + p.pendiente > 0), card = $('card-procesos');
    card.hidden = datos.procesos.length < 2;
    if (card.hidden) return;
    const body = $('procesos-body');
    herramientas($('procesos-tools'), [{ t: st.tablas.proc ? 'Ver gráfico' : 'Ver tabla', on: !!st.tablas.proc, fn: () => { st.tablas.proc = !st.tablas.proc; renderProcesos(); } }]);
    if (!ps.length) return vacio(body, 'Sin datos con estos filtros.');
    if (st.tablas.proc) return clear(body).append(tabla(['Proceso', 'Pagadas', 'Pendientes', 'Total'], ps.map(p => [p.nombre, nf.format(p.pagado), nf.format(p.pendiente), nf.format(p.pagado + p.pendiente)])));
    const W = ancho(body), lw = Math.min(170, W * 0.38), rh = 44, H = ps.length * rh + 6, aw = W - lw - 90;
    const max = Math.max(...ps.map(p => p.pagado + p.pendiente), 1);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Declaraciones por proceso' });
    svg.append(el('line', { class: 'axis', x1: lw, x2: lw, y1: 0, y2: H }));
    ps.forEach((p, i) => {
      const y0 = i * rh + 8, la = aw * p.pagado / max, lb = aw * p.pendiente / max, gap = p.pagado && p.pendiente ? 2 : 0;
      const g = el('g', { class: 'band' + (st.proceso && st.proceso !== p.id ? ' dim' : '') });
      g.append(el('text', { class: 't-2', x: 0, y: y0 + 15, text: cortar(p.nombre, 24) }));
      if (p.pagado) g.append(el('path', { class: 'mark', d: barraH(lw, y0, la, 22, !p.pendiente), fill: S1 }));
      if (p.pendiente) g.append(el('path', { class: 'mark', d: barraH(lw + la + gap, y0, lb, 22, true), fill: S2 }));
      g.append(el('text', { class: 't-ink', x: lw + la + lb + gap + 8, y: y0 + 15, text: nf.format(p.pagado + p.pendiente) }));
      const hit = el('rect', { class: 'hit', x: 0, y: y0 - 8, width: W, height: rh - 4 });
      marca(hit, {
        titulo: p.nombre, etiqueta: `${p.nombre}: ${nf.format(p.pagado)} pagadas, ${nf.format(p.pendiente)} pendientes`,
        filas: [{ color: S1, label: 'Pagadas', valor: nf.format(p.pagado) }, { color: S2, label: 'Pendientes', valor: nf.format(p.pendiente) }],
        alClic: () => alternar('proceso', p.id),
      });
      g.append(hit);
      svg.append(g);
    });
    clear(body).append(svg);
  }

  /* ── Mayores saldos pendientes ──────────────────────────────── */
  function renderTop() {
    const rows = datos.top_pendientes, body = $('top-body');
    if (!rows.length) return vacio(body, st.pago === 'PAGADO' ? 'Con el filtro "Pagadas" no hay saldos pendientes.' : 'No hay saldos pendientes con estos filtros.');
    const max = Math.max(...rows.map(r => r.valor), 1);
    clear(body).append(el('div', { class: 'rp-table-scroll' }, el('table', { class: 'rp-table rp-table-top' },
      el('colgroup', {}, ['34px', 'auto', '108px', '64px', '150px'].map(w => el('col', { style: 'width:' + w }))),
      el('thead', {}, el('tr', {}, [['#', ''], ['Contribuyente', ''], ['Documento', ''], ['Decl.', 'Declaraciones'], ['Valor pendiente', '']].map(([t, ti], i) => el('th', { class: i > 2 ? 'num' : '', title: ti, text: t })))),
      el('tbody', {}, rows.map((r, i) => el('tr', {},
        el('td', { text: i + 1 }),
        el('td', {}, el('div', { class: 'rp-name', title: r.nombre, text: r.nombre })),
        el('td', { text: r.documento }),
        el('td', { class: 'num', text: nf.format(r.n) }),
        el('td', { class: 'num' }, moneyFull(r.valor), el('span', { class: 'rp-bar', style: `width:${Math.max(3, 100 * r.valor / max)}%` }))))))));
  }

  function render() {
    renderFiltros();
    renderKpis();
    renderTiempo();
    renderCxc();
    renderCruce();
    renderProcesos();
    $('card-top').classList.toggle('rp-wide', $('card-procesos').hidden);  // sin gráfico vecino, ocupa todo el ancho
    renderTop();
    $('rp-actualizado').textContent = datos.actualizado ? '· Última ejecución: ' + datos.actualizado : '';
    if (!datos.kpi.total && !FILTROS.some(k => st[k])) {
      $('tiempo-note').textContent = 'Aún no hay datos cargados para este municipio. Ejecuta un proceso desde Analítica.';
    }
  }

  const sel = $('rp-municipio');
  if (sel) sel.addEventListener('change', () => { location.search = '?municipio=' + encodeURIComponent(sel.value); });

  let anchoPrevio = root.getBoundingClientRect().width, t = null;
  new ResizeObserver(() => {
    const w = root.getBoundingClientRect().width;
    if (Math.abs(w - anchoPrevio) < 4) return;
    anchoPrevio = w; clearTimeout(t); t = setTimeout(render, 120);
  }).observe(root);
  document.addEventListener('scroll', ocultarTip, true);
  document.addEventListener('pointerdown', e => { if (!(e.target.closest && e.target.closest('.hit'))) ocultarTip(); });

  render();
})();
