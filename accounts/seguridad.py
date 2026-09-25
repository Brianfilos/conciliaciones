import ipaddress
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import IntentoLogin


def ip_cliente(request):
    """Gunicorn está detrás de Nginx: la IP real es la última que Nginx agregó a X-Forwarded-For."""
    ip = request.META.get("REMOTE_ADDR", "")
    try:
        if ipaddress.ip_address(ip).is_loopback:
            ultimo = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
            if ultimo:
                ip = str(ipaddress.ip_address(ultimo))
    except ValueError:
        return None
    return ip or None


def _desde():
    return timezone.now() - timedelta(minutes=settings.LOGIN_VENTANA_MIN)


def bloqueado(request, usuario):
    """True si el usuario o la IP acumularon demasiados fallos recientes."""
    recientes = IntentoLogin.objects.filter(fecha__gte=_desde())
    if usuario and recientes.filter(usuario=usuario.lower()).count() >= settings.LOGIN_MAX_INTENTOS_USUARIO:
        return True
    ip = ip_cliente(request)
    return bool(ip) and recientes.filter(ip=ip).count() >= settings.LOGIN_MAX_INTENTOS_IP


def registrar_fallo(request, usuario):
    IntentoLogin.objects.create(usuario=(usuario or "")[:150].lower(), ip=ip_cliente(request))
    IntentoLogin.objects.filter(fecha__lt=timezone.now() - timedelta(days=2)).delete()


def limpiar(usuario):
    IntentoLogin.objects.filter(usuario=(usuario or "").lower()).delete()
