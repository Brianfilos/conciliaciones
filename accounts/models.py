from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    ROL_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('OPERADOR', 'Operador'),
        ('ANALITICO', 'Analítico'),
    ]
    municipio = models.ForeignKey(
        'muni.Municipio',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='usuarios'
    )
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default='OPERADOR')
    email = models.EmailField(unique=True, blank=False)

    # Contraseña temporal (recuperación por correo). Se guarda con hash, caduca y NO reemplaza
    # a la contraseña real: si el usuario no la usa, su contraseña de siempre sigue funcionando.
    password_temporal = models.CharField(max_length=128, blank=True, default='')
    password_temporal_expira = models.DateTimeField(null=True, blank=True)
    # Obliga a elegir una contraseña nueva en el próximo ingreso
    debe_cambiar_password = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

    @property
    def is_admin(self):
        return self.rol == 'ADMIN' or self.is_superuser

    @property
    def is_operador(self):
        return self.rol == 'OPERADOR'

    @property
    def is_analitico(self):
        return self.rol == 'ANALITICO'

    def nombre_completo(self):
        return self.get_full_name() or self.username


class IntentoLogin(models.Model):
    """Ingresos fallidos; sirven para bloquear temporalmente la fuerza bruta."""
    usuario = models.CharField(max_length=150, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
