from django.contrib import admin
from .models import Municipio, CIIUMunicipio, ConceptoMunicipio

@admin.register(Municipio)
class MunicipioAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "prefijo_cxc", "tiene_procesos", "activo"]
    list_editable = ["activo", "tiene_procesos"]

@admin.register(CIIUMunicipio)
class CIIUAdmin(admin.ModelAdmin):
    list_display = ["municipio", "codigo", "descripcion", "tipo", "tarifa"]
    list_filter = ["municipio", "tipo"]
    search_fields = ["codigo", "descripcion"]

@admin.register(ConceptoMunicipio)
class ConceptoAdmin(admin.ModelAdmin):
    list_display = ["municipio", "codigo", "descripcion", "tipo_proceso"]
    list_filter = ["municipio", "tipo_proceso"]
