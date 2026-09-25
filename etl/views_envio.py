"""
Envío por correo de exportaciones con una cola en sesión.

Flujo: en cada proceso se filtra y se "agrega al envío"; cuando la cola tiene lo que se quiere,
se envía todo junto en un solo correo (cada adjunto con sus propios filtros y formato).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from accounts import permisos
from .models import Proceso
from .services import envio_exportaciones as envio

SESION = "cola_envio"


def leer_cola(request):
    return request.session.get(SESION, {})


def _volver(request, proceso=None):
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect("dashboard", proceso_id=proceso.id) if proceso else redirect("municipio_home")


def _proceso_permitido(request, proceso_id):
    proceso = get_object_or_404(Proceso, id=proceso_id)
    return proceso if permisos.del_municipio(request.user, proceso.municipio) else None


def _limpio(qs):
    q = QueryDict(qs or "", mutable=True)
    for k in ("format", "csrfmiddlewaretoken"):
        q.pop(k, None)
    return q.urlencode()


@method_decorator(login_required, name="dispatch")
class AgregarAlEnvioView(View):
    """Guarda la vista actual (proceso + pestaña + filtros) en la cola de envío."""

    def post(self, request, proceso_id):
        proceso = _proceso_permitido(request, proceso_id)
        if proceso is None:
            return redirect("municipio_home")
        cola = leer_cola(request)
        if cola and any(it["municipio_id"] != proceso.municipio_id for it in cola.values()):
            messages.error(request, "El envío en preparación es de otro municipio: envíalo o vacíalo antes.")
            return _volver(request, proceso)
        tab = request.POST.get("tab", "encabezado")
        tab = tab if tab in envio.TABS else "encabezado"
        clave = f"{proceso.id}:{tab}"
        if clave not in cola and len(cola) >= envio.MAX_ITEMS:
            messages.error(request, f"El envío ya tiene {envio.MAX_ITEMS} adjuntos (el máximo).")
            return _volver(request, proceso)
        filtros = _limpio(request.POST.get("filtros", ""))
        formato = request.POST.get("formato_actual", "excel")
        cola[clave] = {
            "clave": clave, "proceso_id": proceso.id, "municipio_id": proceso.municipio_id,
            "proceso": proceso.nombre, "tab": tab, "filtros": filtros,
            "resumen": envio.etiqueta_filtros(filtros), "registros": request.POST.get("registros", ""),
            "formato": formato if formato in envio.FORMATOS else "excel",
        }
        request.session[SESION] = cola
        messages.success(request, f"«{proceso.nombre} — {envio.TABS[tab]}» quedó en el envío ({len(cola)} en total). "
                                  "Abre otro proceso, fíltralo y agrégalo, o pulsa «Enviar por correo».")
        return _volver(request, proceso)


@method_decorator(login_required, name="dispatch")
class QuitarDelEnvioView(View):
    def post(self, request):
        cola = leer_cola(request)
        if request.POST.get("vaciar"):
            cola = {}
        else:
            cola.pop(request.POST.get("clave", ""), None)
        request.session[SESION] = cola
        return _volver(request)


@method_decorator(login_required, name="dispatch")
class EnviarExportacionView(View):
    """Envía en un solo correo la cola y, si se marca, la vista actual."""

    def post(self, request, proceso_id):
        proceso = _proceso_permitido(request, proceso_id)
        if proceso is None:
            return redirect("municipio_home")
        volver = _volver(request, proceso)

        items = []
        if request.POST.get("incluir_actual"):
            formato = request.POST.get("formato_actual", "excel")
            items.append({"proceso": proceso, "tab": request.POST.get("tab", "encabezado"),
                          "filtros": _limpio(request.POST.get("filtros", "")), "formato": formato,
                          "registros": request.POST.get("registros", "")})
        cola = leer_cola(request)
        actual = f"{proceso.id}:{request.POST.get('tab', 'encabezado')}"
        for clave, it in cola.items():
            if request.POST.get("incluir_actual") and clave == actual:
                continue  # la vista actual reemplaza a su copia en la cola
            p = _proceso_permitido(request, it["proceso_id"])
            if p is None:
                continue
            formato = request.POST.get(f"formato:{clave}", it["formato"])
            items.append({"proceso": p, "tab": it["tab"], "filtros": it["filtros"], "formato": formato,
                          "registros": it.get("registros", "")})
        try:
            r = envio.enviar(request.user, items, request.POST.get("destinatarios", ""),
                             request.POST.get("asunto", ""), request.POST.get("mensaje", ""))
        except envio.EnvioError as e:
            messages.error(request, str(e))
            return volver
        request.session[SESION] = {}  # la cola se vacía solo cuando el correo salió
        messages.success(
            request, f"Enviado a {', '.join(r['destinatarios'])} desde {r['remitente']} "
                     f"con {len(r['adjuntos'])} adjunto(s): {', '.join(r['adjuntos'])}.")
        return volver


# ── Configuración del correo (solo superusuario) ─────────────────────────────

import base64
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.clickjacking import xframe_options_sameorigin

from accounts.views import SuperusuarioMixin
from .forms import ConfiguracionEnvioForm
from .models import (DESPEDIDA_CORREO_DEFECTO, MENSAJE_CORREO_DEFECTO, ConfiguracionEnvio)


class ConfigCorreoView(SuperusuarioMixin, View):
    def get(self, request):
        from django.shortcuts import render
        cfg = ConfiguracionEnvio.obtener()
        return render(request, "etl/config_correo.html", {"form": ConfiguracionEnvioForm(instance=cfg), "cfg": cfg})

    def post(self, request):
        from django.shortcuts import render
        cfg = ConfiguracionEnvio.obtener()
        if request.POST.get("restablecer"):
            cfg.saludo, cfg.mensaje, cfg.despedida = "Cordial saludo,", MENSAJE_CORREO_DEFECTO, DESPEDIDA_CORREO_DEFECTO
            cfg.actualizado_por = request.user
            cfg.save()
            messages.success(request, "Se restablecieron el saludo, el mensaje y la despedida originales.")
            return redirect("config_correo")
        form = ConfiguracionEnvioForm(request.POST, request.FILES, instance=cfg)
        if not form.is_valid():
            return render(request, "etl/config_correo.html", {"form": form, "cfg": cfg})
        nueva = form.save(commit=False)
        if request.POST.get("quitar_firma") and not request.FILES.get("firma_imagen"):
            nueva.firma_imagen.delete(save=False)
            nueva.firma_imagen = ""
        nueva.actualizado_por = request.user
        nueva.save()
        messages.success(request, "Configuración del correo guardada. Se usará en el próximo envío.")
        return redirect("config_correo")


def _data_uri(datos, subtipo):
    return f"data:image/{subtipo};base64,{base64.b64encode(datos).decode()}"


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ConfigCorreoVistaView(SuperusuarioMixin, View):
    """HTML del correo con datos de ejemplo, para verlo dentro de un iframe."""

    def get(self, request):
        cfg = ConfiguracionEnvio.obtener()
        detalles = [
            {"archivo": "COPACABANA_CXC_AUTO_encabezado_24-09-2026.xlsx", "proceso": "Autorretención",
             "contenido": "Encabezado", "formato": "Excel", "registros": "3.649", "filtros": "pago: PAGO REALIZADO"},
            {"archivo": "COPACABANA_CXC_RETE_encabezado_24-09-2026.csv", "proceso": "Retención ICA",
             "contenido": "Encabezado", "formato": "CSV", "registros": "412", "filtros": "pago: PENDIENTE · desde: 2026-01-01"},
        ]
        ctx = envio.contexto_correo(cfg, "Municipio de Copacabana", detalles,
                                    "Este es un mensaje adicional de ejemplo.", request.user.get_full_name() or request.user.username)
        html = render_to_string("etl/email_exportacion.html", ctx)
        logo = Path(settings.BASE_DIR) / "static" / "img" / "marca" / "logo-gobs-blanco.png"
        if logo.exists():
            html = html.replace("cid:logo-gobs", _data_uri(logo.read_bytes(), "png"))
        firma = envio._datos_firma(cfg)
        if firma:
            html = html.replace("cid:firma", _data_uri(*firma))
        return HttpResponse(html)
