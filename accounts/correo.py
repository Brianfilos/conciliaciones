"""Contraseñas temporales y su envío por correo."""
import logging
import secrets
from datetime import timedelta
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

log = logging.getLogger(__name__)

# Sin caracteres que se confunden al leerlos (0/O, 1/l/I)
_MAYUS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_MINUS = "abcdefghijkmnpqrstuvwxyz"
_DIGITOS = "23456789"


def generar_temporal(largo=10):
    """Contraseña aleatoria legible, con mayúscula, minúscula y número."""
    todos = _MAYUS + _MINUS + _DIGITOS
    while True:
        p = "".join(secrets.choice(todos) for _ in range(largo))
        if any(c in _MAYUS for c in p) and any(c in _MINUS for c in p) and any(c in _DIGITOS for c in p):
            return p


def asignar_temporal(usuario):
    """Guarda (con hash) una contraseña temporal nueva y devuelve el texto plano."""
    plano = generar_temporal()
    usuario.password_temporal = make_password(plano)
    usuario.password_temporal_expira = timezone.now() + timedelta(hours=settings.PASSWORD_TEMPORAL_HORAS)
    usuario.debe_cambiar_password = True
    usuario.save(update_fields=["password_temporal", "password_temporal_expira", "debe_cambiar_password"])
    return plano


def temporal_reciente(usuario, minutos=5):
    """True si ya se emitió una temporal hace poco (frena el reenvío repetido)."""
    if not usuario.password_temporal_expira:
        return False
    emitida = usuario.password_temporal_expira - timedelta(hours=settings.PASSWORD_TEMPORAL_HORAS)
    return emitida > timezone.now() - timedelta(minutes=minutos)


def limpiar_temporal(usuario):
    usuario.password_temporal = ""
    usuario.password_temporal_expira = None


def enviar_temporal(usuario, plano, motivo="recuperacion"):
    """Envía el correo con la contraseña temporal. Devuelve True si el servidor de correo lo aceptó."""
    logo = Path(settings.BASE_DIR) / "static" / "img" / "marca" / "logo-gobs.png"
    ctx = {
        "usuario": usuario, "temporal": plano, "horas": settings.PASSWORD_TEMPORAL_HORAS,
        "login_url": settings.SITE_URL.rstrip("/") + "/login/", "motivo": motivo,
        "con_logo": logo.exists(),
    }
    asunto = ("Tu acceso al Sistema de CXC" if motivo == "alta" else "Contraseña temporal — Sistema de CXC")
    msg = EmailMultiAlternatives(
        asunto, render_to_string("accounts/email_temporal.txt", ctx),
        settings.DEFAULT_FROM_EMAIL, [usuario.email])
    msg.attach_alternative(render_to_string("accounts/email_temporal.html", ctx), "text/html")
    if ctx["con_logo"]:
        # Logo incrustado en el mensaje (cid): se ve aunque el cliente bloquee imágenes remotas
        msg.mixed_subtype = "related"
        img = MIMEImage(logo.read_bytes(), _subtype="png")
        img.add_header("Content-ID", "<logo-gobs>")
        img.add_header("Content-Disposition", "inline", filename="logo-gobs.png")
        msg.attach(img)
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001 - sin correo configurado o rechazado: se informa a quien administra
        log.exception("No se pudo enviar la contraseña temporal a %s", usuario.email)
        return False
