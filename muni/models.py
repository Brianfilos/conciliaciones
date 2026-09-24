import os
from django.db import models
from django.conf import settings


class Municipio(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=100)
    prefijo_cxc = models.CharField(max_length=10, blank=True)
    color_primario = models.CharField(max_length=7, default='#1B3A6B')
    color_secundario = models.CharField(max_length=7, default='#2d6a9f')
    color_texto_header = models.CharField(max_length=7, default='#ffffff')
    fuente_principal = models.CharField(max_length=100, default='Montserrat, sans-serif')
    activo = models.BooleanField(default=True)
    tiene_procesos = models.BooleanField(default=False)
    orden = models.IntegerField(default=0)

    class Meta:
        ordering = ['orden', 'nombre']
        app_label = 'muni'

    def __str__(self):
        return self.nombre

    @property
    def ruta_base(self):
        return os.path.join(str(settings.MUNICIPIOS_ROOT), self.codigo)

    @property
    def ruta_img(self):
        # Los logos viajan con el código (static/img/logos/<codigo>/); la carpeta
        # MUNICIPIOS/ es solo material de trabajo local y no existe en el servidor.
        return os.path.join(str(settings.BASE_DIR), 'static', 'img', 'logos', self.codigo.lower())

    @property
    def logos(self):
        img_path = self.ruta_img
        if not os.path.exists(img_path):
            return []
        exts = ('.png', '.jpg', '.jpeg', '.svg', '.webp')
        return sorted([f for f in os.listdir(img_path) if f.lower().endswith(exts)])

    @property
    def logo_principal(self):
        logos = self.logos
        for f in logos:
            if 'logo' in f.lower() and 'letra' not in f.lower():
                return f
        return logos[0] if logos else None

    def get_logo_url(self):
        logo = self.logo_principal
        if logo:
            return self._url_logo(logo)
        return None

    def get_todos_logos_urls(self):
        return [self._url_logo(f) for f in self.logos]

    def _url_logo(self, archivo):
        from urllib.parse import quote
        # Sin pasar por el manifiesto de hashes: el archivo original también queda en STATIC_ROOT
        return f"{settings.STATIC_URL}img/logos/{quote(self.codigo.lower())}/{quote(archivo)}"


class CIIUMunicipio(models.Model):
    TIPO_CHOICES = [
        ('INDUSTRIAL', 'Industrial'),
        ('COMERCIAL', 'Comercial'),
        ('SERVICIOS', 'Servicios'),
    ]
    municipio = models.ForeignKey(Municipio, on_delete=models.CASCADE, related_name='ciiu')
    codigo = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=300, blank=True)
    tarifa = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES, blank=True)

    class Meta:
        unique_together = [['municipio', 'codigo']]
        app_label = 'muni'

    def __str__(self):
        return f"{self.codigo} - {self.tipo}"


class ConceptoMunicipio(models.Model):
    municipio = models.ForeignKey(Municipio, on_delete=models.CASCADE, related_name='conceptos')
    codigo = models.CharField(max_length=20)
    descripcion = models.CharField(max_length=200, blank=True)
    tipo_proceso = models.CharField(max_length=30, blank=True)

    class Meta:
        unique_together = [['municipio', 'codigo']]
        app_label = 'muni'

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"
