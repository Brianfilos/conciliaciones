"""
Export completo: las columnas crudas de GOBS (las mismas del Excel original, no solo las
que el sistema ya normalizó) para las declaraciones que cumplen los filtros activos en
Reportería. No hay copia local de esas columnas, así que se vuelve a consultar GOBS cada
vez, acotado al rango de fechas de lo que se va a exportar.

Por defecto solo trae la declaración "única" de cada vigencia (ver services/unicos.py),
igual que ya hace el resto del tablero desde que se deduplicaron los KPIs; se puede pedir
con los reintentos/duplicados incluidos.
"""
from etl.models import EncabezadoCXC
from etl.services import gobs_pg, unicos
from etl.services.reporteria import q_estado_pago


def columnas_disponibles(municipio_codigo, proceso_codigo):
    """Nombres de columna de GOBS para este proceso, o [] si no tiene fuente GOBS."""
    fuente = gobs_pg.fuente_para(municipio_codigo, proceso_codigo)
    if fuente is None:
        return []
    return gobs_pg.columnas(fuente)


def _normalizar_consec(v):
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, TypeError):
        return str(v).strip()


def _encabezados_filtrados(proceso, filtros, incluir_duplicados):
    """Queryset de EncabezadoCXC que cumple los filtros de Reportería (pago, año) para
    este proceso, deduplicado por vigencia salvo que se pida lo contrario."""
    qs = EncabezadoCXC.objects.filter(proceso=proceso)
    if filtros.get("pago"):
        qs = qs.filter(q_estado_pago(filtros["pago"]))
    if filtros.get("ano"):
        qs = qs.filter(fecha_cobro__year=filtros["ano"])
    if not incluir_duplicados:
        ids_u, _, _ = unicos.calcular(proceso)
        qs = qs.filter(id__in=ids_u)
    return qs


def generar(proceso, filtros, columnas_elegidas=None, incluir_duplicados=False):
    """(headers, filas) con las columnas crudas de GOBS elegidas, para las declaraciones
    que cumplen los filtros. [] si el proceso no tiene fuente GOBS o no hay coincidencias."""
    fuente = gobs_pg.fuente_para(proceso.municipio.codigo, proceso.codigo)
    if fuente is None:
        return [], []

    encabezados = _encabezados_filtrados(proceso, filtros, incluir_duplicados)
    from django.db.models import Max, Min
    rango = encabezados.aggregate(desde=Min("fecha_cobro"), hasta=Max("fecha_cobro"))
    consecs_norm = {_normalizar_consec(c) for c in
                    encabezados.values_list("consecutivo_original", flat=True) if c}
    if not consecs_norm:
        return columnas_elegidas or [], []

    datos, _ = gobs_pg.cargar(fuente, rango["desde"], rango["hasta"])
    dec = datos.get("declaraciones")
    col_consec = fuente.col_consecutivo
    if dec is None or dec.empty or col_consec not in dec.columns:
        return columnas_elegidas or [], []

    dec = dec[dec[col_consec].apply(_normalizar_consec).isin(consecs_norm)]

    disponibles = [c for c in dec.columns]
    headers = [c for c in columnas_elegidas if c in disponibles] if columnas_elegidas else disponibles
    if not headers:
        headers = disponibles
    filas = dec[headers].values.tolist()
    return headers, filas
