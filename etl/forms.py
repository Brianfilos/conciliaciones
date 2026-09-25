from django import forms
from .models import ConfiguracionEnvio, Proceso, InsumoDefinicion
from .services import gobs_pg

# Insumos que GOBS entrega directamente cuando el proceso tiene fuente PostgreSQL.
# El CSV de CXC (cxc_csv) viene de otro sistema y siempre se sube a mano.
CAMPOS_DESDE_GOBS = {"declaraciones", "actividades"}


class EjecutarProcesoForm(forms.Form):
    def __init__(self, proceso, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.usa_gobs = gobs_pg.fuente_para(proceso.municipio.codigo, proceso.codigo) is not None
        for insumo in proceso.insumos.filter(tipo="CARGUE").order_by("orden"):
            if self.usa_gobs and insumo.nombre_campo in CAMPOS_DESDE_GOBS:
                continue
            self.fields[insumo.nombre_campo] = forms.FileField(
                label=insumo.nombre,
                help_text=f"Formatos: {insumo.extensiones}",
                required=insumo.requerido,
                widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": insumo.extensiones}),
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
            tipo = getattr(f, "content_type", "")
            if tipo and tipo not in ("image/png", "image/jpeg"):
                raise forms.ValidationError("Usa una imagen PNG o JPG.")
        return f
