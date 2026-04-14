from django import forms
from .models import Proceso, InsumoDefinicion


class EjecutarProcesoForm(forms.Form):
    def __init__(self, proceso, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for insumo in proceso.insumos.filter(tipo="CARGUE").order_by("orden"):
            self.fields[insumo.nombre_campo] = forms.FileField(
                label=insumo.nombre,
                help_text=f"Formatos: {insumo.extensiones}",
                required=insumo.requerido,
                widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": insumo.extensiones}),
            )
