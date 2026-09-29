"""
Descarga el CSV de CXC desde el portal SOFINET de cada municipio configurado y actualiza
CXC_AUTO / CXC_RETE con él (más lo que haya nuevo en GOBS para el mismo rango de fechas).

Pensado para correr de madrugada por cron:
    0 5 * * * cd ~/conciliaciones && venv/bin/python manage.py actualizar_sofinet >> logs/sofinet.log 2>&1

    python manage.py actualizar_sofinet                    # todos los municipios configurados
    python manage.py actualizar_sofinet --municipio ESTRELLA

Si la descarga o la carga fallan, no se toca ningún dato: se registra el error y, si
SOFINET_ALERTA_EMAIL está configurado, se avisa por correo.
"""
from datetime import date

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from etl.models import Ejecucion, InsumoDefinicion, InsumoEjecucion, Proceso
from etl.services.motor import MotorETL
from etl.services.sofinet_bot import SofinetBot, SofinetError, validar_csv
from muni.models import Municipio

PROCESOS_CON_CXC = ("CXC_AUTO", "CXC_RETE")


def _config_municipios():
    """Municipios con SOFINET_<CODIGO>_HOST en el .env. Sin eso, se omiten (no es un error)."""
    candidatos = {}
    for codigo in ("ESTRELLA", "COPACABANA"):
        host = getattr(settings, f"SOFINET_{codigo}_HOST", "")
        if host:
            candidatos[codigo] = dict(
                host=host,
                usuario=getattr(settings, f"SOFINET_{codigo}_USER", ""),
                clave=getattr(settings, f"SOFINET_{codigo}_PASS", ""),
            )
    return candidatos


def _usuario_bot():
    from accounts.models import CustomUser
    usuario, creado = CustomUser.objects.get_or_create(
        username="bot_sofinet",
        defaults=dict(email="bot-sofinet@conciliaciones.local", is_active=False,
                     first_name="Bot", last_name="SOFINET"),
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
            subject=f"[Sistema CXC] Falló la actualización automática de SOFINET — {origen}",
            message=(f"La descarga/carga automática desde SOFINET falló para {origen}.\n\n"
                    f"Detalle:\n{detalle}\n\n"
                    "No se modificó ningún dato. Revisa si el portal cambió de pantalla o si la "
                    "clave sigue vigente; mientras tanto puedes cargar el archivo a mano desde "
                    "'Ejecutar proceso'."),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.SOFINET_ALERTA_EMAIL],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 - un fallo al avisar no debe tumbar el comando
        pass


class Command(BaseCommand):
    help = "Descarga el CSV de CXC desde SOFINET y actualiza CXC_AUTO/CXC_RETE"

    def add_arguments(self, parser):
        parser.add_argument("--municipio", help="Código, p. ej. ESTRELLA (por defecto, todos los configurados)")

    def handle(self, *args, **opts):
        registro = _config_municipios()
        if opts.get("municipio"):
            cod = opts["municipio"].upper()
            registro = {cod: registro[cod]} if cod in registro else {}
        if not registro:
            self.stdout.write(self.style.WARNING(
                "No hay municipios con SOFINET_<CODIGO>_HOST configurado en el .env"))
            return

        bot_user = _usuario_bot()
        hoy = date.today()

        for codigo, cfg in registro.items():
            municipio = Municipio.objects.filter(codigo=codigo).first()
            if not municipio:
                self.stderr.write(self.style.ERROR(f"{codigo}: no existe ese municipio en la base de datos"))
                continue

            self.stdout.write(f"{codigo}: descargando de {cfg['host']}...")
            try:
                bot = SofinetBot(cfg["host"], cfg["usuario"], cfg["clave"])
                contenido = bot.descargar_cxc(hasta=hoy)
                motivo = validar_csv(contenido)
                if motivo:
                    raise SofinetError(f"archivo descargado pero no parece válido: {motivo}")
            except Exception as e:  # noqa: BLE001 - se registra y se sigue con el siguiente municipio
                self.stderr.write(self.style.ERROR(f"{codigo}: {e}"))
                _avisar_falla(codigo, str(e))
                continue

            nombre = f"sofinet_{codigo.lower()}_{hoy:%Y%m%d}.csv"
            for proc_codigo in PROCESOS_CON_CXC:
                proceso = Proceso.objects.filter(municipio=municipio, codigo=proc_codigo).first()
                if not proceso:
                    continue
                insumo_def = InsumoDefinicion.objects.filter(proceso=proceso, nombre_campo="cxc_csv").first()
                if not insumo_def:
                    continue

                ejecucion = Ejecucion.objects.create(proceso=proceso, usuario=bot_user, automatico=True)
                ins_ej = InsumoEjecucion.objects.create(
                    ejecucion=ejecucion, insumo_def=insumo_def,
                    archivo=ContentFile(contenido, name=nombre), nombre_original=nombre)

                filtros = {"desde": SofinetBot.FECHA_INICIAL, "hasta": hoy}
                MotorETL(ejecucion).ejecutar({"cxc_csv": ins_ej.archivo.path}, filtros)

                if ejecucion.estado == "COMPLETADO":
                    self.stdout.write(self.style.SUCCESS(
                        f"{codigo} {proc_codigo}: {ejecucion.registros_nuevos} nuevos, "
                        f"{ejecucion.registros_duplicados} actualizados"))
                else:
                    detalle = ejecucion.error_log[:500]
                    self.stderr.write(self.style.ERROR(f"{codigo} {proc_codigo}: ERROR — {detalle}"))
                    _avisar_falla(f"{codigo} {proc_codigo}", detalle)
