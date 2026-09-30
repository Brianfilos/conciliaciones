"""
"Únicos": cuando una misma vigencia (documento + período) tiene varias declaraciones
(reintentos, correcciones), el reporte debe contar esa obligación una sola vez, no una
por cada copia. Regla: si alguna copia quedó pagada, se toma la más reciente entre las
pagadas; si ninguna pagó, se toma la más reciente de todas (la última presentada es la
que reemplaza a las anteriores para esa vigencia).

Generaliza en una sola regla los criterios que antes se aplicaban a mano y distintos
por municipio/proceso (ver scripts/UNICOS AUTOS y scripts/UNICOS DECLARE Y PAGUE),
reutilizando la misma noción de "período" que ya usa el tablero de Reportería
(reporteria.clave_periodo), para que "vigencia" signifique lo mismo en todas partes —
salvo Declare y Pague, que es anual y se trata aparte (ver PROCESOS_ANUALES).
"""
from collections import defaultdict
from datetime import date

from etl.models import EncabezadoCXC
from etl.services.reporteria import clave_periodo, normalizar_pago


# Declare y Pague es una declaración ANUAL (una por año gravable), a diferencia de
# Autorretención/Retención que se presentan cada mes o bimestre. clave_periodo() agrupa
# por mes/bimestre de la fecha de la visita, que es lo correcto para esas dos, pero para
# Declare y Pague dos reenvíos del mismo contribuyente en meses distintos del mismo año
# gravable son la MISMA vigencia, no dos — hay que quedarse solo con el año.
PROCESOS_ANUALES = {"DECLAREYPAGUE"}


def calcular(proceso):
    """Devuelve (ids_unicos, ids_excluidos, duplicados_por_elegido).
    duplicados_por_elegido: {id del registro elegido: cuántas copias se excluyeron}."""
    codigo = proceso.municipio.codigo
    es_anual = proceso.codigo in PROCESOS_ANUALES
    filas = list(EncabezadoCXC.objects.filter(proceso=proceso).values(
        "id", "numero_documento", "fecha_cobro", "estado_pago",
        "datos_extra__ano", "datos_extra__periodo"))

    grupos = defaultdict(list)
    for f in filas:
        doc = (f["numero_documento"] or "").strip()
        clave = clave_periodo(codigo, f["fecha_cobro"], f["datos_extra__ano"], f["datos_extra__periodo"])
        if es_anual and clave:
            clave = clave[:4]  # año gravable, sin importar el mes/bimestre de la visita
        # Sin documento o sin fecha utilizable: no se puede agrupar de forma confiable,
        # así que cada registro queda como su propio grupo (no se pierde ni se fusiona nada).
        llave = (doc, clave) if doc and clave else ("_sin_agrupar_", f["id"])
        grupos[llave].append(f)

    ids_unicos, ids_excluidos, duplicados_por_elegido = [], [], {}
    for filas_grupo in grupos.values():
        if len(filas_grupo) == 1:
            ids_unicos.append(filas_grupo[0]["id"])
            continue
        pagadas = [f for f in filas_grupo if normalizar_pago(f["estado_pago"]) == "PAGADO"]
        candidatas = pagadas or filas_grupo
        elegido = max(candidatas, key=lambda f: f["fecha_cobro"] or date.min)
        ids_unicos.append(elegido["id"])
        duplicados_por_elegido[elegido["id"]] = len(filas_grupo) - 1
        ids_excluidos.extend(f["id"] for f in filas_grupo if f["id"] != elegido["id"])

    return ids_unicos, ids_excluidos, duplicados_por_elegido


HEADERS = ["Consecutivo", "Tipo Documento", "Número Documento", "Nombre / Razón Social",
          "Fecha", "Descripción", "Total a Pagar", "Estado Pago", "Declaraciones excluidas"]


def build_rows(proceso):
    """(headers, filas_unicas, filas_excluidas) listas para exportar a Excel."""
    ids_unicos, ids_excluidos, duplicados = calcular(proceso)

    def _filas(ids):
        qs = (EncabezadoCXC.objects.filter(id__in=ids)
              .order_by("-fecha_cobro", "-consecutivo_cxc"))
        return [[
            e.consecutivo_cxc, e.tipo_documento, e.numero_documento, e.nombre_completo(),
            e.fecha_cobro, e.descripcion, e.total_a_pagar, e.estado_pago,
            duplicados.get(e.id, 0),
        ] for e in qs]

    return HEADERS, _filas(ids_unicos), _filas(ids_excluidos)
