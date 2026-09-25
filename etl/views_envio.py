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
                          "filtros": _limpio(request.POST.get("filtros", "")), "formato": formato})
        cola = leer_cola(request)
        actual = f"{proceso.id}:{request.POST.get('tab', 'encabezado')}"
        for clave, it in cola.items():
            if request.POST.get("incluir_actual") and clave == actual:
                continue  # la vista actual reemplaza a su copia en la cola
            p = _proceso_permitido(request, it["proceso_id"])
            if p is None:
                continue
            formato = request.POST.get(f"formato:{clave}", it["formato"])
            items.append({"proceso": p, "tab": it["tab"], "filtros": it["filtros"], "formato": formato})
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
