from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password
from django.utils import timezone


class PasswordTemporalBackend(ModelBackend):
    """
    Acepta la contraseña temporal enviada por correo mientras no haya caducado.

    Convive con la contraseña real (ModelBackend): pedir una recuperación no bloquea a nadie.
    Quien entra con la temporal queda marcado con `_con_temporal` y la vista de login lo
    obliga a elegir una contraseña nueva.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        User = get_user_model()
        try:
            usuario = User.objects.get(**{User.USERNAME_FIELD: username})
        except User.DoesNotExist:
            return None
        if not usuario.password_temporal or not usuario.password_temporal_expira:
            return None
        if usuario.password_temporal_expira < timezone.now() or not self.user_can_authenticate(usuario):
            return None
        if check_password(password, usuario.password_temporal):
            usuario._con_temporal = True
            return usuario
        return None
