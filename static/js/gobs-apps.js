/* Ecosistema GOBS: menú para saltar entre las aplicaciones.
   Mismo archivo en las cuatro apps (Cierre fiscal, Conciliaciones, Cancelaciones RIT y Convertidor).
   Uso: <div data-gobs-apps="conciliaciones"></div> donde va el botón, y este script con defer.
   El valor del atributo marca la app actual. Para cambiar una dirección, editar APPS aquí y copiar
   el archivo a las demás apps. Sin dependencias; respeta "reducir movimiento". */
(function () {
  var APPS = [
    { id: 'cierre', nombre: 'Cierre fiscal', tag: 'La Estrella',
      desc: 'Presupuesto, tesorería, contabilidad y bancos cruzados por fuente.',
      url: 'http://127.0.0.1:8000/', color: '#508DFB',
      ico: '<path d="M3 17h14M5 14V9M10 14V5M15 14v-3"/>' },
    { id: 'conciliaciones', nombre: 'Conciliaciones', tag: 'Municipios',
      desc: 'CxC, Declare y Pague, reportería y analítica por municipio.',
      url: 'https://conciliaciones.filosdev.com/', color: '#6CD3A5',
      ico: '<path d="M3 8l7-4 7 4M5 9v6M10 9v6M15 9v6M3 17h14"/>' },
    { id: 'cancelaciones', nombre: 'Cancelaciones RIT', tag: 'Copacabana',
      desc: 'Revisión de solicitudes, RUES, matriz y resoluciones.',
      url: 'https://cierres.filosdev.com/', color: '#000000',
      ico: '<path d="M4 3h9l3 3v11H4zM7 10l2 2 4-4M7 15h6"/>' },
    { id: 'convertidor', nombre: 'Convertidor', tag: 'Herramientas',
      desc: 'Columnas de Excel a número entero, sin notación científica.',
      url: 'https://herramientas.filosdev.com/convertidor/', color: '#88B0FF',
      ico: '<path d="M3 6h11M11 3l3 3-3 3M17 14H6M9 11l-3 3 3 3"/>' }
  ];

  var CSS = [
    '.ga{position:relative;display:inline-flex;font-family:"Montserrat",system-ui,"Segoe UI",sans-serif;line-height:1.3}',
    '.ga .ga-btn{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 12px 0 10px;border:1px solid #DADBDD;background:#fff;color:#000;',
    ' font:600 13px "Montserrat",system-ui,sans-serif;border-radius:4px;cursor:pointer;white-space:nowrap;',
    ' transition:background-color .2s,color .2s,border-color .2s,transform .2s,box-shadow .2s}',
    '.ga .ga-btn:hover{border-color:#000;transform:translateY(-1px);box-shadow:0 8px 16px -10px rgba(30,60,130,.6)}',
    '.ga .ga-btn[aria-expanded="true"]{background:#000;color:#fff;border-color:#000}',
    '.ga .ga-btn:focus-visible,.ga .ga-pop a.ga-card:focus-visible,.ga .ga-x:focus-visible{outline:2px solid #508DFB;outline-offset:2px}',
    '.ga-grid{display:grid;grid-template-columns:repeat(2,7px);gap:2px}',
    '.ga-grid i{width:7px;height:7px;display:block;background:currentColor}',
    '.ga-grid i:nth-child(2){background:#508DFB}',
    '.ga-grid i:nth-child(3){background:#6CD3A5}',
    '.ga-pop{position:absolute;right:0;top:calc(100% + 10px);z-index:2000;width:min(600px,calc(100vw - 32px));background:#fff;color:#000;',
    ' border:1px solid #E3E4E7;border-radius:6px;overflow:hidden;text-align:left;',
    ' box-shadow:0 2px 4px rgba(10,20,45,.06),0 28px 56px -18px rgba(30,60,130,.42);transform-origin:top right;animation:gaIn .32s cubic-bezier(.2,.8,.2,1) both}',
    '.ga.izq .ga-pop{right:auto;left:0;transform-origin:top left}',
    '.ga-pop[hidden]{display:none}',
    '@keyframes gaIn{from{opacity:0;transform:translateY(-8px) scale(.98)}to{opacity:1;transform:none}}',
    '.ga-head{position:relative;overflow:hidden;background:#000;color:#fff;padding:18px 20px 16px;isolation:isolate}',
    '.ga-head::before,.ga-head::after{content:"";position:absolute;z-index:-1;clip-path:polygon(0 0,100% 0,100% 100%,58% 100%,58% 42%,0 42%)}',
    '.ga-head::before{right:-18px;top:-26px;width:150px;height:120px;background:#508DFB;animation:gaForma .7s cubic-bezier(.2,.8,.2,1) both .05s}',
    '.ga-head::after{right:96px;top:20px;width:80px;height:66px;background:#6CD3A5;opacity:.9;animation:gaForma .7s cubic-bezier(.2,.8,.2,1) both .15s}',
    '@keyframes gaForma{from{opacity:0;transform:translate(30px,-10px)}}',
    '.ga-eye{display:block;font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#88B0FF}',
    '.ga-tit{display:block;font:700 24px/1.05 Georgia,"Times New Roman",serif;letter-spacing:-.01em;margin-top:6px}',
    '.ga-sub{display:block;font-size:12px;color:#AEB1B8;margin-top:6px;max-width:34ch}',
    '.ga .ga-x{position:absolute;right:12px;top:12px;width:30px;height:30px;border:0;border-radius:4px;background:rgba(255,255,255,.16);color:#fff;cursor:pointer;display:grid;place-items:center}',
    '.ga .ga-x:hover{background:rgba(255,255,255,.3);color:#fff}',
    '.ga-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:#E3E4E7}',
    '.ga .ga-pop a.ga-card{position:relative;overflow:hidden;display:flex;flex-direction:column;gap:6px;padding:16px 18px 18px;background:#fff;color:#000;text-decoration:none!important;',
    ' min-width:0;margin:0;border:0;border-radius:0;font-size:13px;font-weight:500;box-shadow:none;transform:none;transition:background-color .25s;animation:gaUp .45s cubic-bezier(.2,.8,.2,1) both}',
    '.ga .ga-pop a.ga-card:nth-child(2){animation-delay:.05s}.ga .ga-pop a.ga-card:nth-child(3){animation-delay:.1s}.ga .ga-pop a.ga-card:nth-child(4){animation-delay:.15s}',
    '@keyframes gaUp{from{opacity:0;transform:translateY(8px)}}',
    '.ga .ga-pop a.ga-card::after{content:"";position:absolute;right:-16px;top:-16px;width:62px;height:62px;background:var(--c);opacity:.16;',
    ' clip-path:polygon(0 0,100% 0,100% 100%,58% 100%,58% 42%,0 42%);transition:opacity .25s,transform .35s cubic-bezier(.2,.8,.2,1)}',
    '.ga .ga-pop a.ga-card:hover{background:#FAFBFF;color:#000;transform:none}',
    '.ga .ga-pop a.ga-card:hover::after{opacity:.95;transform:translate(-4px,4px)}',
    '.ga-ico{width:36px;height:36px;display:grid;place-items:center;background:#000;color:#fff;box-shadow:inset -6px -6px 0 0 var(--c);flex:none}',
    '.ga-ico svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:square}',
    '.ga-n{display:flex;align-items:center;gap:8px;font:700 17px/1.15 Georgia,"Times New Roman",serif;margin-top:4px}',
    '.ga-n svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:square;opacity:0;transform:translateX(-4px);transition:opacity .2s,transform .25s}',
    '.ga .ga-pop a.ga-card:hover .ga-n svg{opacity:1;transform:none}',
    '.ga-t{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#6B6C70}',
    '.ga-d{font-size:12px;color:#3A3A3D;line-height:1.45}',
    '.ga-u{font-size:11px;color:#6B6C70;margin-top:auto;padding-top:4px;word-break:break-all}',
    '.ga .ga-pop a.ga-card.ga-on,.ga .ga-pop a.ga-card.ga-on:hover{background:#F7F7F8;color:#000;cursor:default;box-shadow:none}',
    '.ga .ga-pop a.ga-card.ga-on .ga-u{color:#000;font-weight:700}',
    '.ga .ga-pop a.ga-card.ga-on .ga-u::before{content:"";display:inline-block;width:7px;height:7px;background:#508DFB;margin-right:6px}',
    '.ga-pie{display:flex;justify-content:space-between;gap:10px;padding:10px 18px;font-size:11px;color:#6B6C70;border-top:1px solid #E3E4E7;background:#fff}',
    '.ga-pie b{color:#000}',
    '.ga-oscuro .ga .ga-btn{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.3)}',
    '@media (max-width:640px){.ga .ga-pop{position:fixed;left:16px;right:16px;top:72px;width:auto;max-height:calc(100vh - 88px);overflow:auto}',
    ' .ga-cards{grid-template-columns:1fr}.ga-lbl{display:none}.ga .ga-btn{padding:0 10px}}',
    '@media (prefers-reduced-motion:reduce){.ga *,.ga-pop,.ga-card,.ga-head::before,.ga-head::after{animation:none!important;transition:none!important}}'
  ].join('\n');

  var FLECHA = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 6l4 4-4 4"/></svg>';

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function dominio(u) { return u.replace(/^https?:\/\//, '').replace(/\/$/, ''); }

  function montar(host, n) {
    var actual = host.getAttribute('data-gobs-apps') || '';
    var id = 'ga-pop-' + n;
    host.classList.add('ga');
    var tarjetas = APPS.map(function (a) {
      var on = a.id === actual;
      return '<a class="ga-card' + (on ? ' ga-on' : '') + '" style="--c:' + a.color + '" href="' + esc(a.url) + '"' +
        (on ? ' aria-current="page"' : '') + '>' +
        '<span class="ga-ico"><svg viewBox="0 0 20 20" aria-hidden="true">' + a.ico + '</svg></span>' +
        '<span class="ga-n">' + esc(a.nombre) + FLECHA + '</span>' +
        '<span class="ga-t">' + esc(a.tag) + '</span>' +
        '<span class="ga-d">' + esc(a.desc) + '</span>' +
        '<span class="ga-u">' + (on ? 'Está aquí' : esc(dominio(a.url))) + '</span></a>';
    }).join('');
    host.innerHTML =
      '<button type="button" class="ga-btn" aria-haspopup="true" aria-expanded="false" aria-controls="' + id + '" title="Aplicaciones GOBS">' +
      '<span class="ga-grid" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span class="ga-lbl">Apps GOBS</span></button>' +
      '<div class="ga-pop" id="' + id + '" role="dialog" aria-label="Aplicaciones GOBS" hidden>' +
      '<div class="ga-head"><span class="ga-eye">Ecosistema GOBS</span><span class="ga-tit">Sus aplicaciones</span>' +
      '<span class="ga-sub">Cada herramienta de Estrategias Públicas, a un clic.</span>' +
      '<button type="button" class="ga-x" aria-label="Cerrar"><svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">' +
      '<path d="M5 5l10 10M15 5L5 15" fill="none" stroke="currentColor" stroke-width="1.8"/></svg></button></div>' +
      '<div class="ga-cards">' + tarjetas + '</div>' +
      '<div class="ga-pie"><span><b>Gobs</b> · Estrategias Públicas</span><span>www.gobs.com.co</span></div></div>';

    var btn = host.querySelector('.ga-btn'), pop = host.querySelector('.ga-pop');
    function abrir(si) {
      pop.hidden = !si;
      btn.setAttribute('aria-expanded', si ? 'true' : 'false');
      if (si) { var p = pop.querySelector('.ga-card:not(.ga-on)'); if (p) p.focus({ preventScroll: true }); }
    }
    btn.addEventListener('click', function (e) { e.stopPropagation(); abrir(pop.hidden); });
    host.querySelector('.ga-x').addEventListener('click', function () { abrir(false); btn.focus(); });
    pop.querySelectorAll('.ga-card.ga-on').forEach(function (c) { c.addEventListener('click', function (e) { e.preventDefault(); abrir(false); }); });
    document.addEventListener('click', function (e) { if (!pop.hidden && !host.contains(e.target)) abrir(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !pop.hidden) { abrir(false); btn.focus(); } });
  }

  function iniciar() {
    var hosts = document.querySelectorAll('[data-gobs-apps]');
    if (!hosts.length) return;
    if (!document.getElementById('ga-css')) {
      var st = document.createElement('style'); st.id = 'ga-css'; st.textContent = CSS; document.head.appendChild(st);
    }
    for (var i = 0; i < hosts.length; i++) if (!hosts[i].classList.contains('ga')) montar(hosts[i], i);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})();
