"""
Reporte de Publicidad Exterior Visual de Sabaneta, con las columnas y el orden de
MUNICIPIOS/SABANETA/INSUMOS/FIJOS/Publicidad exterior visual.xlsx.
"""
from etl.models import EncabezadoCXC

HEADERS = [
    "Consecutivo 2", "Nombre productor", "Nombre del establecimiento", "Tipo de documento",
    "Cédula/NIT propietario", "Fecha de la visita", "1. Año", "2. Bimestre",
    "3. Tipo de declaración", "No. Radicado", "20. TOTAL A PAGAR", "Estado Pago", "Fecha Pago",
]


def _entero(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return v


def build_rows(proceso, filtros):
    """Devuelve (HEADERS, filas) aplicando los filtros de la pantalla de consulta."""
    # El reporte incluye solo las declaraciones pagadas (las pendientes se ven en el tablero).
    qs = EncabezadoCXC.objects.filter(proceso=proceso, estado_pago__icontains="PAGO REALIZADO")
    if filtros.get("q"):
        q = filtros["q"]
        qs = (qs.filter(consecutivo_cxc__icontains=q) | qs.filter(numero_documento__icontains=q)
              | qs.filter(razon_social__icontains=q))
    if filtros.get("q_consec"):
        qs = qs.filter(consecutivo_cxc__icontains=filtros["q_consec"])
    if filtros.get("q_num"):
        qs = qs.filter(numero_documento__icontains=filtros["q_num"])
    if filtros.get("q_nombre"):
        qs = qs.filter(razon_social__icontains=filtros["q_nombre"])
    if filtros.get("fecha_desde"):
        qs = qs.filter(fecha_cobro__gte=filtros["fecha_desde"])
    if filtros.get("fecha_hasta"):
        qs = qs.filter(fecha_cobro__lte=filtros["fecha_hasta"])
    if filtros.get("estado_pago"):
        qs = qs.filter(estado_pago__icontains=filtros["estado_pago"])

    filas = []
    for e in qs.order_by("-fecha_cobro", "-consecutivo_cxc"):
        x = e.datos_extra or {}
        filas.append([
            _entero(e.consecutivo_cxc), e.razon_social, x.get("nombre_establecimiento", ""),
            e.tipo_documento, e.numero_documento, x.get("fecha_visita", ""), x.get("ano", ""),
            x.get("bimestre", ""), x.get("tipo_declaracion", ""), x.get("radicado") or None,
            _entero(e.total_a_pagar), e.estado_pago, x.get("fecha_pago", ""),
        ])
    return HEADERS, filas
