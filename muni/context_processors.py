import os
from django.conf import settings
from .models import Municipio


def _get_gobs_logos():
    gobs_img = os.path.join(str(settings.GOBS_ROOT), 'IMG')
    if not os.path.exists(gobs_img):
        return []
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.svg')
    return sorted(f for f in os.listdir(gobs_img) if f.lower().endswith(exts))


def municipio_context(request):
    ctx = {
        'color_primario': '#1B3A6B',
        'color_secundario': '#2d6a9f',
        'color_texto_header': '#ffffff',
        'fuente_principal': 'Montserrat, sans-serif',
        'municipio_actual': None,
        'logo_url': None,
        'gobs_logos': _get_gobs_logos(),
    }
    if request.user.is_authenticated and hasattr(request.user, 'municipio') and request.user.municipio:
        m = request.user.municipio
        ctx.update({
            'municipio_actual': m,
            'color_primario': m.color_primario,
            'color_secundario': m.color_secundario,
            'color_texto_header': m.color_texto_header,
            'fuente_principal': m.fuente_principal,
            'logo_url': m.get_logo_url(),
            'todos_logos': m.get_todos_logos_urls(),
        })
    return ctx
