from django.contrib import admin
from .models import ConfiguracionEnvio, EnvioExportacion, Proceso, InsumoDefinicion, Ejecucion, EncabezadoCXC, DetalleCXC, InsumoEjecucion

class InsumoInline(admin.TabularInline):
    model = InsumoDefinicion
    extra = 1

@admin.register(Proceso)
class ProcesoAdmin(admin.ModelAdmin):
    list_display = ["municipio", "codigo", "nombre", "activo", "total_registros"]
    list_filter = ["municipio", "activo"]
    inlines = [InsumoInline]

@admin.register(Ejecucion)
class EjecucionAdmin(admin.ModelAdmin):
    list_display = ["proceso", "usuario", "fecha_inicio", "estado", "registros_nuevos", "registros_duplicados"]
    list_filter = ["estado", "proceso__municipio"]
    readonly_fields = ["fecha_inicio", "fecha_fin", "registros_nuevos", "registros_duplicados", "error_log"]

@admin.register(EncabezadoCXC)
class EncabezadoAdmin(admin.ModelAdmin):
    list_display = ["consecutivo_cxc", "proceso", "numero_documento", "nombre_completo", "total_a_pagar", "estado_pago", "estado_cxc"]
    list_filter = ["proceso__municipio", "proceso", "estado_cxc"]
    search_fields = ["consecutivo_cxc", "numero_documento", "primer_apellido", "razon_social"]

@admin.register(DetalleCXC)
class DetalleAdmin(admin.ModelAdmin):
    list_display = ["encabezado", "codigo_concepto", "valor_unitario", "valor_total", "centro_costo"]
    list_filter = ["encabezado__proceso__municipio"]


@admin.register(EnvioExportacion)
class EnvioExportacionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "usuario", "procesos", "formato", "destinatarios", "ok"]
    list_filter = ["ok", "formato"]
    search_fields = ["destinatarios", "usuario__username", "procesos"]
    readonly_fields = [f.name for f in EnvioExportacion._meta.fields]


@admin.register(ConfiguracionEnvio)
class ConfiguracionEnvioAdmin(admin.ModelAdmin):
    list_display = ["__str__", "actualizado", "actualizado_por"]
