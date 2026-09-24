import os
import mimetypes
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import HttpResponse, Http404
from django.conf import settings
from django.contrib import messages
import pandas as pd
from django.db import models as models
from .models import Municipio, CIIUMunicipio, ConceptoMunicipio


@method_decorator(login_required, name="dispatch")
class MunicipioHomeView(View):
    def get(self, request):
        municipio = request.user.municipio
        if not municipio:
            return render(request, "home_sin_municipio.html")
        procesos = []
        if municipio.tiene_procesos:
            from etl.models import Proceso
            procesos = Proceso.objects.filter(municipio=municipio, activo=True)
        return render(request, "municipios/home.html", {"municipio": municipio, "procesos": procesos})


@method_decorator(login_required, name="dispatch")
class AdminMunicipioView(View):
    def _get_municipios(self, request):
        # Superusuario ve todos; admin normal ve solo el suyo
        if request.user.is_superuser:
            return Municipio.objects.all()
        if request.user.municipio:
            return Municipio.objects.filter(id=request.user.municipio.id)
        return Municipio.objects.none()

    def get(self, request):
        if not request.user.is_admin:
            return redirect("municipio_home")
        from etl.models import Proceso
        municipios = self._get_municipios(request)
        # Agregar procesos a cada municipio para mostrar en la plantilla
        mun_list = []
        for mun in municipios:
            procesos = Proceso.objects.filter(municipio=mun, activo=True).order_by("orden", "nombre")
            mun_list.append({"mun": mun, "procesos": procesos})
        return render(request, "municipios/admin_municipio.html", {"mun_list": mun_list})

    def post(self, request):
        if not request.user.is_admin:
            return redirect("municipio_home")
        mun_id = request.POST.get("municipio_id")
        municipio = get_object_or_404(Municipio, id=mun_id)
        # Verificar que el admin tenga acceso a este municipio
        if not request.user.is_superuser and request.user.municipio != municipio:
            return redirect("municipio_home")
        municipio.color_primario = request.POST.get("color_primario", municipio.color_primario)
        municipio.color_secundario = request.POST.get("color_secundario", municipio.color_secundario)
        municipio.color_texto_header = request.POST.get("color_texto_header", municipio.color_texto_header)
        municipio.fuente_principal = request.POST.get("fuente_principal", municipio.fuente_principal)
        municipio.save()
        messages.success(request, f"Municipio {municipio.nombre} actualizado.")
        return redirect("admin_municipio")


@method_decorator(login_required, name="dispatch")
class CargarCIIUView(View):
    def get(self, request, codigo):
        if not request.user.is_admin:
            return redirect("municipio_home")
        municipio = get_object_or_404(Municipio, codigo=codigo)
        q = request.GET.get("q", "").strip()
        qs = CIIUMunicipio.objects.filter(municipio=municipio).order_by("codigo")
        if q:
            qs = qs.filter(models.Q(codigo__icontains=q) | models.Q(descripcion__icontains=q))
        from django.core.paginator import Paginator
        paginator = Paginator(qs, 50)
        page = paginator.get_page(request.GET.get("page", 1))
        return render(request, "municipios/cargar_ciiu.html", {
            "municipio": municipio,
            "count": CIIUMunicipio.objects.filter(municipio=municipio).count(),
            "page_obj": page,
            "q": q,
        })

    def post(self, request, codigo):
        if not request.user.is_admin:
            return redirect("municipio_home")
        municipio = get_object_or_404(Municipio, codigo=codigo)
        action = request.POST.get("action", "importar")

        if action == "eliminar":
            ciiu_id = request.POST.get("ciiu_id")
            CIIUMunicipio.objects.filter(id=ciiu_id, municipio=municipio).delete()
            messages.success(request, "Registro eliminado.")
            return redirect(f"{request.path}?q={request.POST.get('q','')}&page={request.POST.get('page',1)}")

        if action == "editar":
            ciiu_id = request.POST.get("ciiu_id")
            obj = get_object_or_404(CIIUMunicipio, id=ciiu_id, municipio=municipio)
            obj.descripcion = request.POST.get("descripcion", obj.descripcion)[:300]
            obj.tipo = request.POST.get("tipo", obj.tipo).upper()[:15]
            try:
                obj.tarifa = float(request.POST.get("tarifa", obj.tarifa or 0))
            except (ValueError, TypeError):
                pass
            obj.save()
            messages.success(request, f"CIIU {obj.codigo} actualizado.")
            return redirect(f"{request.path}?q={request.POST.get('q','')}&page={request.POST.get('page',1)}")

        # importar
        archivo = request.FILES.get("archivo")
        if not archivo:
            messages.error(request, "Selecciona un archivo.")
            return redirect("cargar_ciiu", codigo=codigo)
        try:
            df = pd.read_excel(archivo, dtype=str)
            df.columns = [c.strip() for c in df.columns]
            col_ciiu = next((c for c in df.columns if "CIIU" in c.upper()), None)
            col_desc = next((c for c in df.columns if "DESC" in c.upper()), None)
            col_tarifa = next((c for c in df.columns if "TARIFA" in c.upper()), None)
            col_tipo = next((c for c in df.columns if "TIPO" in c.upper()), None)
            created, updated = 0, 0
            for _, row in df.iterrows():
                codigo_ciiu = str(row.get(col_ciiu, "") or "").strip().zfill(4)
                if not codigo_ciiu or codigo_ciiu == "0000":
                    continue
                defaults = {"descripcion": str(row.get(col_desc, "") or "")[:300], "tipo": str(row.get(col_tipo, "") or "").upper()[:15]}
                if col_tarifa:
                    try:
                        defaults["tarifa"] = float(str(row.get(col_tarifa, 0) or 0).replace(",", "."))
                    except Exception:
                        pass
                obj, was_created = CIIUMunicipio.objects.update_or_create(municipio=municipio, codigo=codigo_ciiu, defaults=defaults)
                created += 1 if was_created else 0
                updated += 0 if was_created else 1
            messages.success(request, f"CIIU: {created} nuevos, {updated} actualizados.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("cargar_ciiu", codigo=codigo)


@method_decorator(login_required, name="dispatch")
class CargarConceptosView(View):
    def get(self, request, codigo):
        if not request.user.is_admin:
            return redirect("municipio_home")
        municipio = get_object_or_404(Municipio, codigo=codigo)
        q = request.GET.get("q", "").strip()
        qs = ConceptoMunicipio.objects.filter(municipio=municipio).order_by("codigo")
        if q:
            qs = qs.filter(models.Q(codigo__icontains=q) | models.Q(descripcion__icontains=q))
        from django.core.paginator import Paginator
        paginator = Paginator(qs, 50)
        page = paginator.get_page(request.GET.get("page", 1))
        return render(request, "municipios/cargar_conceptos.html", {
            "municipio": municipio,
            "count": ConceptoMunicipio.objects.filter(municipio=municipio).count(),
            "page_obj": page,
            "q": q,
        })

    def post(self, request, codigo):
        if not request.user.is_admin:
            return redirect("municipio_home")
        municipio = get_object_or_404(Municipio, codigo=codigo)
        action = request.POST.get("action", "importar")

        if action == "eliminar":
            concepto_id = request.POST.get("concepto_id")
            ConceptoMunicipio.objects.filter(id=concepto_id, municipio=municipio).delete()
            messages.success(request, "Concepto eliminado.")
            return redirect(f"{request.path}?q={request.POST.get('q','')}&page={request.POST.get('page',1)}")

        if action == "editar":
            concepto_id = request.POST.get("concepto_id")
            obj = get_object_or_404(ConceptoMunicipio, id=concepto_id, municipio=municipio)
            obj.descripcion = request.POST.get("descripcion", obj.descripcion)[:200]
            obj.tipo_proceso = request.POST.get("tipo_proceso", obj.tipo_proceso)[:30]
            obj.save()
            messages.success(request, f"Concepto {obj.codigo} actualizado.")
            return redirect(f"{request.path}?q={request.POST.get('q','')}&page={request.POST.get('page',1)}")

        archivo = request.FILES.get("archivo")
        if not archivo:
            messages.error(request, "Selecciona un archivo.")
            return redirect("cargar_conceptos", codigo=codigo)
        try:
            df = pd.read_excel(archivo, dtype=str)
            df.columns = [c.strip() for c in df.columns]
            col_cod = next((c for c in df.columns if "COD" in c.upper()), df.columns[0])
            col_desc = next((c for c in df.columns if "DESC" in c.upper()), None)
            col_tipo = next((c for c in df.columns if "TIPO" in c.upper() or "PROCESO" in c.upper()), None)
            created, updated = 0, 0
            for _, row in df.iterrows():
                cod = str(row.get(col_cod, "") or "").strip()
                if not cod:
                    continue
                defaults = {"descripcion": str(row.get(col_desc, "") or "")[:200] if col_desc else ""}
                if col_tipo:
                    defaults["tipo_proceso"] = str(row.get(col_tipo, "") or "")[:30]
                obj, was_created = ConceptoMunicipio.objects.update_or_create(municipio=municipio, codigo=cod, defaults=defaults)
                created += 1 if was_created else 0
                updated += 0 if was_created else 1
            messages.success(request, f"Conceptos: {created} nuevos, {updated} actualizados.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("cargar_conceptos", codigo=codigo)
