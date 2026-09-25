from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from .models import Proceso
from .services import envio_exportaciones as envio


@method_decorator(login_required, name="dispatch")
class EnviarExportacionView(View):
    """Envía por correo la exportación actual (con sus filtros) y, si se pide, la de otros procesos."""

    def post(self, request, proceso_id):
        proceso = get_object_or_404(Proceso, id=proceso_id)
        # Mismo criterio de acceso que la exportación
        if proceso.municipio != request.user.municipio and not request.user.is_admin:
            return redirect("municipio_home")
        destino = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
            destino = ""
        volver = redirect(destino) if destino else redirect("dashboard", proceso_id=proceso.id)

        ids = [int(i) for i in request.POST.getlist("otros") if i.isdigit()]
        otros = list(Proceso.objects.filter(id__in=ids, municipio=proceso.municipio, activo=True)
                     .exclude(id=proceso.id))
        try:
            r = envio.enviar(
                request.user, proceso, request.POST.get("formato", "excel"), request.POST.get("tab", "encabezado"),
                request.POST.get("filtros", ""), request.POST.get("destinatarios", ""),
                request.POST.get("asunto", ""), request.POST.get("mensaje", ""), otros)
        except envio.EnvioError as e:
            messages.error(request, str(e))
            return volver
        messages.success(
            request, f"Enviado a {', '.join(r['destinatarios'])} desde {r['remitente']} "
                     f"con {len(r['adjuntos'])} adjunto(s): {', '.join(r['adjuntos'])}.")
        return volver
