"""
Envía un correo de prueba con la configuración actual (.env) y explica el resultado.

    python manage.py probar_correo tu-correo@ejemplo.com
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envía un correo de prueba para verificar la configuración SMTP"

    def add_arguments(self, parser):
        parser.add_argument("destinatario")

    def handle(self, *args, **opts):
        if not getattr(settings, "EMAIL_HOST", ""):
            raise CommandError(
                "EMAIL_HOST está vacío en el .env: sin servidor SMTP los correos solo se imprimen en el log. "
                "Completa las variables EMAIL_* (ver .env.example) y reinicia.")
        self.stdout.write(f"Servidor: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} "
                          f"(TLS={settings.EMAIL_USE_TLS}) usuario={settings.EMAIL_HOST_USER}")
        self.stdout.write(f"Remitente: {settings.DEFAULT_FROM_EMAIL}")
        try:
            n = send_mail(
                "Prueba de correo — Sistema de CXC",
                "Si recibes este mensaje, el correo saliente del sistema está bien configurado.",
                settings.DEFAULT_FROM_EMAIL, [opts["destinatario"]], fail_silently=False)
        except Exception as e:  # noqa: BLE001 - se traduce a una pista útil
            texto = str(e)
            pista = ""
            if "535" in texto or "uthentication" in texto:
                pista = "Usuario o clave SMTP incorrectos (en Brevo: la clave SMTP, no la contraseña de tu cuenta)."
            elif "sender" in texto.lower() or "550" in texto or "553" in texto:
                pista = "El remitente no está verificado en Brevo: verifica el dominio o el correo de DEFAULT_FROM_EMAIL."
            elif "timed out" in texto or "refused" in texto or "unreachable" in texto:
                pista = "No se alcanza el servidor: revisa EMAIL_HOST/EMAIL_PORT y que el firewall permita salir por 587."
            raise CommandError(f"No se pudo enviar: {texto}\n{pista}") from e
        self.stdout.write(self.style.SUCCESS(
            f"Enviado ({n}). Revisa la bandeja de {opts['destinatario']} y también la carpeta de spam."))
