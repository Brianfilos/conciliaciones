"""
Cálculo del tablero de Reportería de un municipio.

Devuelve un diccionario JSON-serializable con todo lo que dibuja el tablero. Los filtros
son cruzados: cada gráfico se calcula con todos los filtros MENOS el suyo, así al hacer
clic en una barra las demás alternativas siguen visibles (la elegida queda resaltada) y
el resto de gráficos sí se recalcula.

Filtros (todos opcionales): proceso (id), ano, pago (PAGADO | PENDIENTE),
cxc (estado en el sistema de información, o SIN_CARGAR), periodo (clave del eje de tiempo).
"""
import re
import unicodedata
from collections import defaultdict
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from etl.models import EncabezadoCXC, Ejecucion, InsumoDefinicion, Proceso

# Municipios que no traen fecha de declaración utilizable: el tiempo se mide por bimestre.
_POR_BIMESTRE = {"CALDAS", "ENVIGADO"}
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
SIN_CARGAR = "SIN_CARGAR"


_ESTADOS_PAGADO = ("PAGO REALIZADO", "PAGADAS POR OTROS BANCOS")


def normalizar_pago(estado_pago):
    """'✓ PAGO REALIZADO' / 'Pago realizado' / 'Pagadas por otros bancos' -> PAGADO;
    cualquier otro -> PENDIENTE."""
    e = (estado_pago or "").upper()
    return "PAGADO" if any(s in e for s in _ESTADOS_PAGADO) else "PENDIENTE"


def q_estado_pago(valor, prefijo=""):
    """Filtro para la columna Estado Pago (encabezado__estado_pago con prefijo="encabezado__").
    'PAGADO' es el marcador que usa el tablero de Reportería al enlazar al detalle: agrupa
    todos los estados que normalizar_pago cuenta como pagados (ver _ESTADOS_PAGADO), para
    que ese enlace muestre lo mismo que cuenta el tablero. Cualquier otro valor (los que
    vienen del desplegable "Estado Pago", con el texto real de cada municipio) se busca tal
    cual, como siempre."""
    campo = f"{prefijo}estado_pago__icontains"
    if valor.upper() == "PAGADO":
        q = Q()
        for estado in _ESTADOS_PAGADO:
            q |= Q(**{campo: estado})
        return q
    return Q(**{campo: valor})


def clave_periodo(codigo_municipio, fecha, ano, periodo):
    """Clave ordenable del eje de tiempo: 'YYYY-MM', 'YYYY-Bn' o 'YYYY' (anual)."""
    if codigo_municipio in _POR_BIMESTRE:
        ano = str(ano or "").strip()[:4]
        if not ano.isdigit():
            return None
        m = re.search(r"(\d+)", periodo or "")
        return f"{ano}-B{int(m.group(1))}" if m else ano
    return fecha.strftime("%Y-%m") if fecha else None


def etiqueta_periodo(clave):
    if len(clave) == 4:
        return f"{clave} (anual)"
    ano, resto = clave[:4], clave[5:]
    if resto.startswith("B"):
        return f"Bim {resto[1:]} · {ano}"
    return f"{_MESES[int(resto) - 1]} {ano}"


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return t.lower().strip()


def _nombre(razon, nombre, apellido, documento):
    return (razon or f"{nombre or ''} {apellido or ''}".strip() or documento or "Sin nombre").strip()


def _agrupar(filas, clave):
    acc = defaultdict(lambda: [0, 0.0])
    for f in filas:
        a = acc[clave(f)]
        a[0] += 1
        a[1] += f["valor"]
    return acc


def calcular(municipio, filtros):
    codigo = municipio.codigo
    procesos = list(Proceso.objects.filter(municipio=municipio, activo=True).order_by("orden", "nombre"))
    tiene_csv = InsumoDefinicion.objects.filter(
        proceso__municipio=municipio, nombre_campo="cxc_csv").exists()

    # Import local: evita el ciclo de imports (unicos.py ya importa de aquí clave_periodo/normalizar_pago)
    from etl.services import unicos as _unicos
    unicos_por_proceso = {p.id: _unicos.calcular(p) for p in procesos}
    ids_unicos = {i for ids_u, _, _ in unicos_por_proceso.values() for i in ids_u}

    raw = (EncabezadoCXC.objects.filter(proceso__municipio=municipio, proceso__activo=True)
           .values_list("id", "proceso_id", "estado_pago", "estado_cxc", "total_a_pagar", "fecha_cobro",
                        "datos_extra__ano", "datos_extra__periodo", "razon_social", "primer_nombre",
                        "primer_apellido", "numero_documento", "consecutivo_cxc"))
    # filas_todas: cada declaración, con reintentos/correcciones (para la cifra "todas" del
    # tablero). filas: solo la que "gana" cada vigencia (ver unicos.py) — es lo que se usa
    # para Pagadas/Pendientes/gráficos/mayores pendientes, para no contar una misma
    # obligación varias veces.
    filas_todas, filas = [], []
    for rid, pid, ep, ec, total, fecha, ano, periodo, razon, nom, ape, doc, consec in raw.iterator(chunk_size=5000):
        clave = clave_periodo(codigo, fecha, ano, periodo)
        r = {
            "proceso": pid,
            "pago": normalizar_pago(ep),
            "cxc": (ec or "").strip().upper() or SIN_CARGAR,
            "valor": float(total or 0),
            "periodo": clave,
            "ano": clave[:4] if clave else None,
            "nombre": _nombre(razon, nom, ape, doc),
            "doc": doc or "",
            "consec": consec,
            "fecha": fecha,
        }
        r["buscable"] = _sin_tildes(r["nombre"] + " " + r["doc"])
        filas_todas.append(r)
        if rid in ids_unicos:
            filas.append(r)

    f = {k: filtros.get(k) for k in ("proceso", "ano", "pago", "cxc", "periodo", "doc", "q")}
    palabras = _sin_tildes(f["q"]).split() if f["q"] else []

    def aplicar(excluir=(), datos=None):
        def ok(r):
            return ((("proceso" in excluir) or not f["proceso"] or r["proceso"] == f["proceso"])
                    and (("ano" in excluir) or not f["ano"] or r["ano"] == f["ano"])
                    and (("pago" in excluir) or not f["pago"] or r["pago"] == f["pago"])
                    and (("cxc" in excluir) or not f["cxc"] or r["cxc"] == f["cxc"])
                    and (("periodo" in excluir) or not f["periodo"] or r["periodo"] == f["periodo"])
                    and (not f["doc"] or r["doc"] == f["doc"])
                    and all(w in r["buscable"] for w in palabras))
        return [r for r in (datos if datos is not None else filas) if ok(r)]

    activas = aplicar()
    n = len(activas)
    pagadas = [r for r in activas if r["pago"] == "PAGADO"]
    pend = [r for r in activas if r["pago"] == "PENDIENTE"]
    # "Sin cargar en el sistema" solo tiene sentido donde hay un CSV de CXC con el que
    # comparar (Estrella/Copacabana). En los demás municipios el campo "cxc" siempre cae en
    # SIN_CARGAR por defecto (no hay insumo que lo llene), así que mostrarlo ahí diría que
    # "nada está en el sistema" cuando en realidad no hay forma de saberlo.
    sin_cargar = [r for r in activas if r["cxc"] == SIN_CARGAR] if tiene_csv else []

    activas_todas = aplicar(datos=filas_todas)

    kpi = {
        # "Declaraciones": todas, con reintentos (coherente con su propia etiqueta en el tablero).
        "total": len(activas_todas), "valor": sum(r["valor"] for r in activas_todas),
        # Base para los porcentajes de Pagadas/Pendientes: el total ya deduplicado, no el de arriba
        # (si no, los % quedarían mal — numerador deduplicado sobre denominador sin deduplicar).
        "total_unico": n,
        "pagadas": len(pagadas), "pagadas_valor": sum(r["valor"] for r in pagadas),
        "pendientes": len(pend), "pendientes_valor": sum(r["valor"] for r in pend),
        "en_sistema": n - len(sin_cargar), "sin_cargar": len(sin_cargar),
        "sin_cargar_pagadas": sum(1 for r in sin_cargar if r["pago"] == "PAGADO"),
    }

    # Estado de pago (sin su propio filtro)
    g = _agrupar(aplicar(("pago",)), lambda r: r["pago"])
    pago = [{"clave": k, "n": g[k][0], "valor": g[k][1]} for k in ("PAGADO", "PENDIENTE")]

    # Estado en el sistema (CSV): estados presentes, sin cargar al final
    cxc, cruce = [], None
    if tiene_csv:
        g = _agrupar(aplicar(("cxc",)), lambda r: r["cxc"])
        estados = sorted((k for k in g if k != SIN_CARGAR), key=lambda k: -g[k][0])
        cxc = [{"clave": k, "n": g[k][0], "valor": g[k][1]} for k in estados]
        cxc.append({"clave": SIN_CARGAR, "n": g[SIN_CARGAR][0], "valor": g[SIN_CARGAR][1]})
        base = aplicar(("pago", "cxc"))
        cols = [c["clave"] for c in cxc]
        celdas = defaultdict(int)
        for r in base:
            celdas[(r["pago"], r["cxc"])] += 1
        cruce = {"filas": ["PAGADO", "PENDIENTE"], "cols": cols,
                 "celdas": [[celdas[(fila, c)] for c in cols] for fila in ("PAGADO", "PENDIENTE")]}

    # Evolución en el tiempo (sin filtro de periodo)
    base = aplicar(("periodo",))
    por = defaultdict(lambda: {"PAGADO": [0, 0.0], "PENDIENTE": [0, 0.0]})
    for r in base:
        if r["periodo"]:
            a = por[r["periodo"]][r["pago"]]
            a[0] += 1
            a[1] += r["valor"]
    claves = sorted(por)
    tiempo = {
        "eje": "bimestre" if codigo in _POR_BIMESTRE else "mes",
        "claves": claves,
        "etiquetas": [etiqueta_periodo(c) for c in claves],
        "pagado": [por[c]["PAGADO"][0] for c in claves],
        "pendiente": [por[c]["PENDIENTE"][0] for c in claves],
        "valor_pagado": [por[c]["PAGADO"][1] for c in claves],
        "valor_pendiente": [por[c]["PENDIENTE"][1] for c in claves],
        "sin_fecha": sum(1 for r in base if not r["periodo"]),
    }

    # Por proceso (sin filtro de proceso)
    base = aplicar(("proceso",))
    cnt = defaultdict(lambda: {"PAGADO": 0, "PENDIENTE": 0})
    for r in base:
        cnt[r["proceso"]][r["pago"]] += 1
    lista_procesos = []
    for p in procesos:
        ids_u, ids_e, _ = unicos_por_proceso[p.id]
        lista_procesos.append({
            "id": p.id, "codigo": p.codigo, "nombre": p.nombre,
            "pagado": cnt[p.id]["PAGADO"], "pendiente": cnt[p.id]["PENDIENTE"],
            "unicos": len(ids_u), "duplicadas": len(ids_e),
            "unicos_url": reverse("reporteria_unicos", args=[p.id]),
        })

    # Mayores saldos pendientes (respeta todos los filtros, solo pendientes)
    top = defaultdict(lambda: [0, 0.0, ""])
    for r in pend:
        a = top[r["nombre"]]
        a[0] += 1
        a[1] += r["valor"]
        a[2] = a[2] or r["doc"]
    top_pend = [{"nombre": k, "documento": v[2], "n": v[0], "valor": v[1]}
                for k, v in sorted(top.items(), key=lambda kv: -kv[1][1])[:10]]

    anos = sorted({r["ano"] for r in aplicar(("ano",)) if r["ano"]}, reverse=True)

    # Enlaces para explorar los registros en la pantalla de detalle existente
    q = {}
    if f["pago"]:
        # "PAGADO" es un marcador de grupo (ver q_estado_pago): agrupa todos los estados
        # que normalizar_pago cuenta como pagados, no un texto literal de estado_pago.
        q["estado_pago"] = "PAGADO" if f["pago"] == "PAGADO" else "PENDIENTE"
    if f["cxc"] and f["cxc"] != SIN_CARGAR:
        q["estado"] = f["cxc"]
    if f["doc"]:
        q["q_num"] = f["doc"]
    elif f["q"]:
        q["q"] = f["q"]
    explorar = [{"nombre": p.nombre,
                 "url": reverse("dashboard", args=[p.id]) + (("?" + urlencode(q)) if q else "")}
                for p in procesos]

    # Con un contribuyente o un texto de búsqueda: sus declaraciones una por una
    detalle = None
    if f["doc"] or f["q"]:
        nombres_proceso = {p.id: p.nombre for p in procesos}
        orden = sorted(activas, key=lambda r: (r["periodo"] or "", r["consec"]), reverse=True)
        detalle = {"total": len(orden), "filas": [{
            "consecutivo": r["consec"], "proceso": nombres_proceso.get(r["proceso"], ""),
            "periodo": etiqueta_periodo(r["periodo"]) if r["periodo"] else "",
            "fecha": r["fecha"].strftime("%d/%m/%Y") if r["fecha"] else "",
            "pago": r["pago"], "cxc": r["cxc"], "valor": r["valor"], "nombre": r["nombre"], "doc": r["doc"],
        } for r in orden[:150]]}
    contribuyente = None
    if f["doc"] and activas:
        contribuyente = {"nombre": activas[0]["nombre"], "doc": f["doc"]}

    ult = (Ejecucion.objects.filter(proceso__municipio=municipio, estado="COMPLETADO")
           .order_by("-fecha_fin").values_list("fecha_fin", flat=True).first())

    return {
        "municipio": {"codigo": codigo, "nombre": municipio.nombre, "tiene_csv": tiene_csv},
        "filtros": f, "anos": anos, "kpi": kpi, "pago": pago, "cxc": cxc, "cruce": cruce,
        "tiempo": tiempo, "procesos": lista_procesos, "top_pendientes": top_pend,
        "explorar": explorar, "detalle": detalle, "contribuyente": contribuyente,
        "actualizado": timezone.localtime(ult).strftime("%d/%m/%Y %H:%M") if ult else None,
    }


def buscar(municipio, texto, limite=8):
    """Sugerencias para el buscador: contribuyentes (por documento) que coinciden con el texto."""
    texto = (texto or "").strip()
    if len(texto) < 2:
        return []
    qs = (EncabezadoCXC.objects.filter(proceso__municipio=municipio, proceso__activo=True)
          .filter(Q(razon_social__icontains=texto) | Q(primer_nombre__icontains=texto)
                  | Q(primer_apellido__icontains=texto) | Q(numero_documento__icontains=texto))
          .values_list("numero_documento", "razon_social", "primer_nombre", "primer_apellido",
                       "estado_pago", "total_a_pagar")[:5000])
    acc = {}
    for doc, razon, nom, ape, ep, total in qs:
        if not doc:
            continue
        a = acc.setdefault(doc, {"documento": doc, "nombre": _nombre(razon, nom, ape, doc),
                                 "n": 0, "pendientes": 0, "valor_pendiente": 0.0})
        a["n"] += 1
        if normalizar_pago(ep) == "PENDIENTE":
            a["pendientes"] += 1
            a["valor_pendiente"] += float(total or 0)
    return sorted(acc.values(), key=lambda a: (-a["n"], a["nombre"]))[:limite]
