"""
Refresca desde GOBS los procesos de Caldas, Envigado y Sabaneta (los únicos insumos que
usan son "declaraciones"/"actividades", ambos servidos por GOBS: no necesitan ningún
archivo a mano). Estrella y Copacabana ya se refrescan con `actualizar_sofinet`, que trae
todo el histórico (2022-hoy) junto con el CSV de SOFINET — repetirlos aquí sería
procesarlos dos veces por nada.

Pensado para correr de madrugada por cron, antes del bot de SOFINET:
    0 5 * * * cd ~/conciliaciones && venv/bin/python manage.py actualizar_gobs >> logs/gobs.log 2>&1
    5 5 * * * cd ~/conciliaciones && venv/bin/python manage.py actualizar_sofinet >> logs/sofinet.log 2>&1

    python manage.py actualizar_gobs                     # todos los municipios/procesos con fuente GOBS activa
    python manage.py actualizar_gobs --municipio CALDAS
    python manage.py actualizar_gobs --dias 30            # por defecto: settings.GOBS_REFRESH_DIAS

Si un proceso falla, no se toca ningún dato: se registra el error y, si SOFINET_ALERTA_EMAIL
está configurado (la misma variable que usa actualizar_sofinet), se avisa por correo.
"""
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from etl.models import Ejecucion, Proceso
from etl.services import gobs_pg
from etl.services.motor import MotorETL
from muni.models import Municipio

MUNICIPIOS_SIN_BOT_PROPIO = ("CALDAS", "ENVIGADO", "SABANETA")


def _usuario_bot():
    from accounts.models import CustomUser
    usuario, creado = CustomUser.objects.get_or_create(
        username="bot_gobs",
        defaults=dict(email="bot-gobs@conciliaciones.local", is_active=False,
                     first_name="Bot", last_name="GOBS"),
    )
    if creado:
        usuario.set_unusable_password()
        usuario.save()
    return usuario


def _avisar_falla(origen, detalle):
    if not settings.SOFINET_ALERTA_EMAIL:
        return
    try:
        send_mail(
            subject=f"[Sistema CXC] Falló la actualización automática de GOBS — {origen}",
            message=(f"La actualización automática desde GOBS falló para {origen}.\n\n"
                    f"Detalle:\n{detalle}\n\n"
                    "No se modificó ningún dato. Puedes cargarlo a mano desde 'Ejecutar "
                    "proceso' mientras se revisa."),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.SOFINET_ALERTA_EMAIL],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 - un fallo al avisar no debe tumbar el comando
        pass


class Command(BaseCommand):
    help = "Refresca desde GOBS los procesos de Caldas, Envigado y Sabaneta"

    def add_arguments(self, parser):
        parser.add_argument("--municipio", help="Código, p. ej. CALDAS (por defecto, todos)")
        parser.add_argument("--dias", type=int, help="Días atrás a repasar (por defecto: settings.GOBS_REFRESH_DIAS)")

    def handle(self, *args, **opts):
        if not gobs_pg.habilitado():
            self.stdout.write(self.style.WARNING(
                "GOBS_PG_ENABLED está en False o falta GOBS_PG_HOST en el .env: nada que refrescar."))
            return

        municipios = [opts["municipio"].upper()] if opts.get("municipio") else list(MUNICIPIOS_SIN_BOT_PROPIO)
        dias = opts.get("dias") or settings.GOBS_REFRESH_DIAS
        hoy = date.today()
        desde = hoy - timedelta(days=dias)
        bot_user = _usuario_bot()

        for codigo in municipios:
            municipio = Municipio.objects.filter(codigo=codigo).first()
            if not municipio:
                self.stderr.write(self.style.ERROR(f"{codigo}: no existe ese municipio en la base de datos"))
                continue

            for proceso in Proceso.objects.filter(municipio=municipio, activo=True).order_by("orden"):
                if gobs_pg.fuente_para(codigo, proceso.codigo) is None:
                    continue  # este proceso no tiene fuente GOBS (o está desactivada)

                ejecucion = Ejecucion.objects.create(proceso=proceso, usuario=bot_user, automatico=True)
                MotorETL(ejecucion).ejecutar({}, {"desde": desde, "hasta": hoy})

                if ejecucion.estado == "COMPLETADO":
                    self.stdout.write(self.style.SUCCESS(
                        f"{codigo} {proceso.codigo}: {ejecucion.registros_nuevos} nuevos, "
                        f"{ejecucion.registros_duplicados} actualizados"))
                else:
                    log = ejecucion.error_log or ""
                    detalle = ("…\n" + log[-1500:]) if len(log) > 1500 else log
                    self.stderr.write(self.style.ERROR(f"{codigo} {proceso.codigo}: ERROR — {detalle}"))
                    _avisar_falla(f"{codigo} {proceso.codigo}", detalle)
