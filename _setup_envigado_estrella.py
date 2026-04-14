"""
Helper: creates Envigado processes + fixes La Estrella branding.
Run with: python _setup_envigado_estrella.py
"""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from muni.models import Municipio
from etl.models import Proceso, InsumoDefinicion

# ── 1. La Estrella — correct palette + font ────────────────────────────────
estrella = Municipio.objects.get(codigo="ESTRELLA")
estrella.color_primario       = "#00843a"   # verde oscuro (Carriquí)
estrella.color_secundario     = "#5cb130"   # verde lima (Carriquí)
estrella.color_texto_header   = "#ffffff"
estrella.fuente_principal     = "Menco, sans-serif"
estrella.save()
print(f"Estrella actualizada: {estrella.color_primario} / {estrella.color_secundario} / {estrella.fuente_principal}")

# ── 2. Envigado — activar municipio y crear procesos ──────────────────────
envigado = Municipio.objects.get(codigo="ENVIGADO")
envigado.tiene_procesos = True
envigado.save()
print(f"Envigado tiene_procesos = True")

# CXC_AUTO  (no cxc_csv)
auto, created = Proceso.objects.update_or_create(
    municipio=envigado, codigo="CXC_AUTO",
    defaults={"nombre": "Autorretención", "descripcion": "Proceso CXC Autorretención ICA", "orden": 1, "activo": True}
)
print(f"{'Creado' if created else 'Ya existía'}: Envigado CXC_AUTO")

for idata in [
    {"nombre": "Declaraciones Autorretención", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
    {"nombre": "Actividades Autorretención",   "nombre_campo": "actividades",   "extensiones": ".xlsx", "orden": 2},
]:
    InsumoDefinicion.objects.update_or_create(
        proceso=auto, nombre_campo=idata["nombre_campo"],
        defaults={**idata, "tipo": "CARGUE", "requerido": True}
    )
    print(f"  Insumo: {idata['nombre_campo']}")

# CXC_RETE  (no cxc_csv)
rete, created = Proceso.objects.update_or_create(
    municipio=envigado, codigo="CXC_RETE",
    defaults={"nombre": "Retención ICA", "descripcion": "Proceso CXC Retención ICA", "orden": 2, "activo": True}
)
print(f"{'Creado' if created else 'Ya existía'}: Envigado CXC_RETE")

for idata in [
    {"nombre": "Declaraciones ReteICA", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
]:
    InsumoDefinicion.objects.update_or_create(
        proceso=rete, nombre_campo=idata["nombre_campo"],
        defaults={**idata, "tipo": "CARGUE", "requerido": True}
    )
    print(f"  Insumo: {idata['nombre_campo']}")

print("\nListo.")
