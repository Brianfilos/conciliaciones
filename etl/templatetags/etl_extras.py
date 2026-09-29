from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, "")


@register.filter
def split(value, sep=","):
    return str(value).split(sep)

@register.filter
def resumen_filtros(querystring):
    """'estado_pago=PENDIENTE&fecha_desde=2026-01-01' -> 'pago: PENDIENTE · desde: 2026-01-01'."""
    from etl.services.envio_exportaciones import etiqueta_filtros
    return etiqueta_filtros(querystring)


@register.filter
def fecha_extra(valor):
    """Una fecha guardada como texto en datos_extra ('2026-05-15 12:29:01.000' o
    '2026-05-15') se muestra como 'd/m/Y', igual que las demás columnas de fecha."""
    if not valor:
        return "—"
    try:
        from datetime import datetime
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return valor
