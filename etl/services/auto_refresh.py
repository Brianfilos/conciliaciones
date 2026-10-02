"""
Respaldo del cron de madrugada: si el usuario entra y el municipio no se refrescó hace
poco, se dispara en segundo plano (sin bloquear el login) el mismo comando que corre a
las 5am, pero solo para su municipio — `actualizar_sofinet` para Estrella/Copacabana
(que traen el CSV junto con GOBS), `actualizar_gobs` para los demás.

No reemplaza el cron (sigue siendo lo que mantiene los datos al día aunque nadie entre
un día), es una red de seguridad para cuando el cron no corrió.
"""
import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MUNICIPIOS_CON_BOT_SOFINET = ("ESTRELLA", "COPACABANA")


def _en_cooldown(codigo):
    from etl.models import Ejecucion
    limite = timezone.now() - timedelta(minutes=settings.LOGIN_REFRESH_COOLDOWN_MIN)
    return Ejecucion.objects.filter(
        proceso__municipio__codigo=codigo, automatico=True, fecha_inicio__gte=limite,
    ).exists()


def disparar_para_municipio(codigo):
    """Lanza `actualizar_gobs`/`actualizar_sofinet --municipio <codigo>` como proceso
    aparte, sin esperar a que termine. No hace nada si LOGIN_REFRESH_ENABLED está
    desactivado, si ya se refrescó hace menos de LOGIN_REFRESH_COOLDOWN_MIN minutos, o si
    algo falla al lanzarlo — un problema aquí nunca debe impedir el login."""
    if not settings.LOGIN_REFRESH_ENABLED or not codigo:
        return
    try:
        if _en_cooldown(codigo):
            return
        comando = "actualizar_sofinet" if codigo in MUNICIPIOS_CON_BOT_SOFINET else "actualizar_gobs"
        manage_py = str(Path(settings.BASE_DIR) / "manage.py")
        log_path = Path(settings.BASE_DIR) / "logs" / "login_refresh.log"
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "a") as log:
            subprocess.Popen(
                [sys.executable, manage_py, comando, "--municipio", codigo],
                stdout=log, stderr=log, cwd=str(settings.BASE_DIR),
                start_new_session=True,  # sigue corriendo aunque termine el request
            )
    except Exception:  # noqa: BLE001 - nunca debe romper el login
        logger.exception("No se pudo disparar el refresco automático al loguearse (%s)", codigo)
