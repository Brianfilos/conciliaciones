"""Update Copacabana brand colors and font."""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from muni.models import Municipio

copa = Municipio.objects.get(codigo="COPACABANA")
copa.color_primario     = "#21294C"   # azul marino principal
copa.color_secundario   = "#1ab4e8"   # azul cielo (C=90 M=10 Y=0 K=0)
copa.color_texto_header = "#ffffff"
copa.fuente_principal   = "Montserrat, Arial, sans-serif"
copa.save()
print(f"Copa actualizada: {copa.color_primario} / {copa.color_secundario} / {copa.fuente_principal}")
