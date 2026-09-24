import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from muni.models import Municipio
from .services import reporteria


def _municipio(request):
    """Municipio a mostrar: el del usuario; un superusuario puede elegir con ?municipio=."""
    u = request.user
    if u.is_superuser or u.municipio_id is None:
        activos = Municipio.objects.filter(activo=True).order_by("orden", "nombre")
        return (activos.filter(codigo=request.GET.get("municipio", "")).first()
                or u.municipio or activos.first())
    return u.municipio


def _filtros(request):
    g = request.GET
    proceso = g.get("proceso", "")
    pago = g.get("pago", "").upper()
    periodo = g.get("periodo", "")
    return {
        "proceso": int(proceso) if proceso.isdigit() else None,
        "ano": g.get("ano") if re.fullmatch(r"\d{4}", g.get("ano", "")) else None,
        "pago": pago if pago in ("PAGADO", "PENDIENTE") else None,
        "cxc": g.get("cxc", "").strip().upper()[:40] or None,
        "periodo": periodo if re.fullmatch(r"\d{4}(-(\d{2}|B\d))?", periodo) else None,
    }


@method_decorator(login_required, name="dispatch")
class ReporteriaView(View):
    def get(self, request):
        municipio = _municipio(request)
        if municipio is None:
            return render(request, "etl/reporteria.html", {"datos": None, "municipios": []})
        datos = reporteria.calcular(municipio, _filtros(request))
        municipios = []
        if request.user.is_superuser or request.user.municipio_id is None:
            municipios = list(Municipio.objects.filter(activo=True).order_by("orden", "nombre")
                              .values("codigo", "nombre"))
        return render(request, "etl/reporteria.html", {
            "datos": datos, "municipios": municipios, "municipio_actual": municipio,
        })


@method_decorator(login_required, name="dispatch")
class ReporteriaDatosView(View):
    def get(self, request):
        municipio = _municipio(request)
        if municipio is None:
            return JsonResponse({"error": "Sin municipio"}, status=404)
        return JsonResponse(reporteria.calcular(municipio, _filtros(request)))
