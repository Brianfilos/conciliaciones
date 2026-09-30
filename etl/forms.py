from django import forms
from django.conf import settings
from .models import ConfiguracionEnvio, Proceso, InsumoDefinicion
from .services import gobs_pg

# Insumos que GOBS entrega directamente cuando el proceso tiene fuente PostgreSQL.
# El CSV de CXC (cxc_csv) viene de otro sistema y siempre se sube a mano.
CAMPOS_DESDE_GOBS = {"declaraciones", "actividades"}


def _validador_archivo(extensiones):
    """Solo las extensiones que el insumo declara y un tamaño razonable (la validación del
    navegador con `accept` no protege: cualquiera puede saltársela)."""
    permitidas = {e.strip().lower() for e in (extensiones or "").split(",") if e.strip()}
    permitidas = {e if e.startswith(".") else f".{e}" for e in permitidas}

    def validar(f):
        nombre = (getattr(f, "name", "") or "").lower()
        if permitidas and not any(nombre.endswith(e) for e in permitidas):
            raise forms.ValidationError(f"Formato no permitido. Usa: {', '.join(sorted(permitidas))}.")
        if getattr(f, "size", 0) > settings.UPLOAD_MAX_MB * 1024 * 1024:
            raise forms.ValidationError(f"El archivo pesa más de {settings.UPLOAD_MAX_MB} MB.")
    return validar


# Municipios donde GOBS a veces se queda corto (se actualiza cada 24h) y hace falta poder
# cargar el mismo día a mano: se deja visible el cargue manual como alternativa opcional,
# que reemplaza lo que traiga GOBS solo para esa ejecución (ver MotorETL._completar_desde_gobs).
MUNICIPIOS_CON_CARGUE_MANUAL_OPCIONAL = {"COPACABANA"}


class EjecutarProcesoForm(forms.Form):
    def __init__(self, proceso, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.usa_gobs = gobs_pg.fuente_para(proceso.municipio.codigo, proceso.codigo) is not None
        self.permite_manual_con_gobs = proceso.municipio.codigo in MUNICIPIOS_CON_CARGUE_MANUAL_OPCIONAL
        for insumo in proceso.insumos.filter(tipo="CARGUE").order_by("orden"):
            cubierto_por_gobs = self.usa_gobs and insumo.nombre_campo in CAMPOS_DESDE_GOBS
            if cubierto_por_gobs and not self.permite_manual_con_gobs:
                continue
            label = insumo.nombre
            if cubierto_por_gobs:
                label += " (opcional: si subes un archivo, reemplaza lo que traiga GOBS solo en esta ejecución)"
            self.fields[insumo.nombre_campo] = forms.FileField(
                label=label,
                help_text=f"Formatos: {insumo.extensiones}",
                required=False if cubierto_por_gobs else insumo.requerido,
                widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": insumo.extensiones}),
                validators=[_validador_archivo(insumo.extensiones)],
            )
        if self.usa_gobs:
            fecha = lambda: forms.DateInput(attrs={"class": "form-control", "type": "date"})
            self.fields["fecha_desde"] = forms.DateField(
                label="Declaraciones desde", required=True, widget=fecha(),
                help_text="Fecha de la declaración (inclusive).")
            self.fields["fecha_hasta"] = forms.DateField(
                label="Declaraciones hasta", required=False, widget=fecha(),
                help_text="Opcional. Vacío = hasta la última cargada en GOBS.")

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("fecha_desde"), datos.get("fecha_hasta")
        if desde and hasta and hasta < desde:
            self.add_error("fecha_hasta", "La fecha final no puede ser anterior a la inicial.")
        return datos


class ConfiguracionEnvioForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionEnvio
        fields = ["saludo", "mensaje", "despedida", "firma_imagen", "firma_texto"]
        widgets = {
            "saludo": forms.TextInput(attrs={"class": "form-control"}),
            "mensaje": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "despedida": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "firma_imagen": forms.FileInput(attrs={"class": "form-control", "accept": "image/png,image/jpeg"}),
            "firma_texto": forms.Textarea(attrs={"class": "form-control", "rows": 3,
                                                 "placeholder": "Nombre\nCargo\nTeléfono · correo"}),
        }

    def clean_firma_imagen(self):
        f = self.cleaned_data.get("firma_imagen")
        if f and hasattr(f, "size"):
            if f.size > 2 * 1024 * 1024:
                raise forms.ValidationError("La imagen pesa más de 2 MB.")
            # El tipo que declara el navegador se puede falsificar: se comprueba el contenido real
            try:
                from PIL import Image
                f.seek(0)
                formato = Image.open(f).format
                f.seek(0)
            except Exception:  # noqa: BLE001 - cualquier fallo = no es una imagen válida
                formato = None
            if formato not in ("PNG", "JPEG"):
                raise forms.ValidationError("Usa una imagen PNG o JPG válida.")
        return f
