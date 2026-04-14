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
