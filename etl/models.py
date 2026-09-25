from django.db import models
from django.conf import settings


class Proceso(models.Model):
    municipio = models.ForeignKey("muni.Municipio", on_delete=models.CASCADE, related_name="procesos")
    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    orden = models.IntegerField(default=0)

    class Meta:
        unique_together = [["municipio", "codigo"]]
        ordering = ["orden", "nombre"]

    def __str__(self):
        return f"{self.municipio.nombre} - {self.nombre}"

    def total_registros(self):
        return self.encabezados.count()


class InsumoDefinicion(models.Model):
    TIPO_CHOICES = [("CARGUE", "Cargue por ejecucion"), ("FIJO", "Insumo fijo")]
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE, related_name="insumos")
    nombre = models.CharField(max_length=100)
    nombre_campo = models.CharField(max_length=50)
    extensiones = models.CharField(max_length=50, default=".xlsx")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default="CARGUE")
    requerido = models.BooleanField(default=True)
    orden = models.IntegerField(default=0)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.nombre


class Ejecucion(models.Model):
    ESTADO_CHOICES = [
        ("PENDIENTE", "Pendiente"), ("EJECUTANDO", "Ejecutando"),
        ("COMPLETADO", "Completado"), ("ERROR", "Error"),
    ]
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE, related_name="ejecuciones")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default="PENDIENTE")
    registros_nuevos = models.IntegerField(default=0)
    registros_duplicados = models.IntegerField(default=0)
    error_log = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_inicio"]

    def __str__(self):
        return f"{self.proceso} - {self.fecha_inicio:%d/%m/%Y %H:%M} - {self.estado}"


class InsumoEjecucion(models.Model):
    ejecucion = models.ForeignKey(Ejecucion, on_delete=models.CASCADE, related_name="insumos")
    insumo_def = models.ForeignKey(InsumoDefinicion, on_delete=models.CASCADE)
    archivo = models.FileField(upload_to="insumos_ejecucion/")
    nombre_original = models.CharField(max_length=200)


class EncabezadoCXC(models.Model):
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE, related_name="encabezados")
    ejecucion = models.ForeignKey(Ejecucion, on_delete=models.CASCADE, related_name="encabezados")
    consecutivo_cxc = models.CharField(max_length=20, db_index=True)
    consecutivo_original = models.CharField(max_length=20, blank=True)
    tipo_documento = models.CharField(max_length=10, blank=True)
    numero_documento = models.CharField(max_length=20, blank=True)
    primer_nombre = models.CharField(max_length=100, blank=True)
    segundo_nombre = models.CharField(max_length=100, blank=True)
    primer_apellido = models.CharField(max_length=100, blank=True)
    segundo_apellido = models.CharField(max_length=100, blank=True)
    razon_social = models.CharField(max_length=200, blank=True)
    fecha_cobro = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    descripcion = models.TextField(blank=True)
    total_a_pagar = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    estado_pago = models.CharField(max_length=50, blank=True)
    estado_cxc = models.CharField(max_length=50, blank=True)
    datos_extra = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [["proceso", "consecutivo_cxc"]]
        ordering = ["consecutivo_cxc"]

    def nombre_completo(self):
        if self.razon_social:
            return self.razon_social
        partes = [self.primer_nombre, self.segundo_nombre, self.primer_apellido, self.segundo_apellido]
        return " ".join(p for p in partes if p).strip()


class DetalleCXC(models.Model):
    encabezado = models.ForeignKey(EncabezadoCXC, on_delete=models.CASCADE, related_name="detalles")
    codigo_concepto = models.CharField(max_length=20)
    centro_costo = models.CharField(max_length=120, blank=True)
    cantidad = models.IntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    valor_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["codigo_concepto"]


class EnvioExportacion(models.Model):
    """Registro de cada exportación enviada por correo (los adjuntos contienen datos de contribuyentes)."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="envios_exportacion")
    proceso = models.ForeignKey(Proceso, on_delete=models.SET_NULL, null=True, related_name="envios")
    fecha = models.DateTimeField(auto_now_add=True)
    procesos = models.CharField(max_length=300, blank=True)
    destinatarios = models.TextField()
    asunto = models.CharField(max_length=250, blank=True)
    formato = models.CharField(max_length=10)
    filtros = models.TextField(blank=True)
    adjuntos = models.TextField(blank=True)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} · {self.usuario} → {self.destinatarios}"


MENSAJE_CORREO_DEFECTO = ("Se envía {adjuntos} en el sistema de información InOva del municipio de {municipio}, "
                          "con corte al {fecha} a las {hora}.")
DESPEDIDA_CORREO_DEFECTO = "Quedamos atentos a cualquier inquietud. Puedes responder este mensaje."


class ConfiguracionEnvio(models.Model):
    """Textos y firma de los correos con exportaciones. Una sola fila (pk=1), editable por el superusuario."""
    saludo = models.CharField(max_length=120, default="Cordial saludo,")
    mensaje = models.TextField(default=MENSAJE_CORREO_DEFECTO)
    despedida = models.TextField(default=DESPEDIDA_CORREO_DEFECTO, blank=True)
    firma_imagen = models.ImageField(upload_to="firma/", blank=True)
    firma_texto = models.TextField(blank=True)
    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "configuración del correo de reportes"

    @classmethod
    def obtener(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def __str__(self):
        return "Configuración del correo de reportes"
