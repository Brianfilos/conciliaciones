from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from muni.models import Municipio

User = get_user_model()


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Usuario',
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Nombre de usuario',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Contraseña',
        })
    )


class RecuperarForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'form-control', 'placeholder': 'Correo electrónico', 'autofocus': True}))


class CambiarPasswordForm(forms.Form):
    """Cambio de contraseña. Si viene de una contraseña temporal no pide la actual."""
    actual = forms.CharField(label='Contraseña actual', required=False, widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'autocomplete': 'current-password'}))
    nueva1 = forms.CharField(label='Contraseña nueva', widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'autocomplete': 'new-password'}))
    nueva2 = forms.CharField(label='Repite la contraseña nueva', widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'autocomplete': 'new-password'}))

    def __init__(self, usuario, forzado, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario, self.forzado = usuario, forzado
        if forzado:
            del self.fields['actual']

    def clean(self):
        d = super().clean()
        if not self.forzado and not self.usuario.check_password(d.get('actual', '')):
            self.add_error('actual', 'La contraseña actual no es correcta.')
        n1, n2 = d.get('nueva1'), d.get('nueva2')
        if n1 and n2:
            if n1 != n2:
                self.add_error('nueva2', 'Las contraseñas no coinciden.')
            else:
                try:
                    validate_password(n1, self.usuario)
                except forms.ValidationError as e:
                    self.add_error('nueva1', e)
        return d


class UsuarioForm(forms.ModelForm):
    """Alta y edición de usuarios de municipio (solo superusuario)."""
    MODO = [('temporal', 'Generar una contraseña temporal y enviarla por correo (recomendado)'),
            ('manual', 'Definir la contraseña yo mismo')]

    modo_clave = forms.ChoiceField(label='Contraseña inicial', choices=MODO, initial='temporal',
                                   widget=forms.RadioSelect, required=False)
    password = forms.CharField(label='Contraseña', required=False, widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'autocomplete': 'new-password'}))
    forzar_cambio = forms.BooleanField(label='Pedir que la cambie en su primer ingreso', required=False, initial=True)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'municipio', 'rol', 'is_active']
        labels = {'username': 'Usuario', 'first_name': 'Nombres', 'last_name': 'Apellidos',
                  'email': 'Correo electrónico', 'municipio': 'Municipio', 'rol': 'Rol',
                  'is_active': 'Puede ingresar (activo)'}
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'municipio': forms.Select(attrs={'class': 'form-select'}),
            'rol': forms.RadioSelect,
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.creando = self.instance.pk is None
        self.fields['municipio'].queryset = Municipio.objects.filter(activo=True).order_by('orden', 'nombre')
        self.fields['municipio'].required = True
        self.fields['municipio'].empty_label = 'Selecciona un municipio'
        self.fields['first_name'].required = False
        self.fields['last_name'].required = False
        if not self.creando:
            for k in ('modo_clave', 'password', 'forzar_cambio'):
                del self.fields[k]

    def clean_email(self):
        e = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=e).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe un usuario con ese correo.')
        return e

    def clean_is_active(self):
        activo = self.cleaned_data['is_active']
        if not activo and self.actor is not None and self.instance.pk == self.actor.pk:
            raise forms.ValidationError('No puedes desactivar tu propio usuario.')
        return activo

    def clean(self):
        d = super().clean()
        if self.creando and d.get('modo_clave') == 'manual':
            try:
                validate_password(d.get('password') or '', User(username=d.get('username', ''), email=d.get('email', '')))
            except forms.ValidationError as e:
                self.add_error('password', e)
        return d
