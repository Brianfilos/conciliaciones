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
