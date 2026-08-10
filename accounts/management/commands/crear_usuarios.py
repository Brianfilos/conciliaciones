from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from muni.models import Municipio

User = get_user_model()

USUARIOS = [
    # Operadores
    {"username": "brianestrella",  "password": "Estrella2026", "municipio": "ESTRELLA",    "rol": "OPERADOR", "email": "brianestrella@cxc.local"},
    {"username": "briancopa",      "password": "Copa2026",     "municipio": "COPACABANA",  "rol": "OPERADOR", "email": "briancopa@cxc.local"},
    {"username": "briancaldas",    "password": "Caldas2026",   "municipio": "CALDAS",      "rol": "OPERADOR", "email": "briancaldas@cxc.local"},
    {"username": "brianenvigado",  "password": "Envigado2026", "municipio": "ENVIGADO",    "rol": "OPERADOR", "email": "brianenvigado@cxc.local"},
    {"username": "briansabaneta",  "password": "Sabaneta2026", "municipio": "SABANETA",    "rol": "OPERADOR", "email": "briansabaneta@cxc.local"},
    # Admins
    {"username": "adminEstrella",  "password": "AdminEstrella2026", "municipio": "ESTRELLA",   "rol": "ADMIN", "email": "adminestrella@cxc.local"},
    {"username": "adminCopa",      "password": "AdminCopa2026",     "municipio": "COPACABANA", "rol": "ADMIN", "email": "admincopa@cxc.local"},
    {"username": "adminCaldas",    "password": "AdminCaldas2026",   "municipio": "CALDAS",     "rol": "ADMIN", "email": "admincaldas@cxc.local"},
    {"username": "adminEnvigado",  "password": "AdminEnvigado2026", "municipio": "ENVIGADO",   "rol": "ADMIN", "email": "adminenvigado@cxc.local"},
    {"username": "adminSabaneta",  "password": "AdminSabaneta2026", "municipio": "SABANETA",   "rol": "ADMIN", "email": "adminsabaneta@cxc.local"},
]


class Command(BaseCommand):
    help = "Crea los usuarios del sistema CXC"

    def handle(self, *args, **options):
        for data in USUARIOS:
            try:
                municipio = Municipio.objects.get(codigo=data["municipio"])
            except Municipio.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Municipio {data['municipio']} no encontrado, omitiendo {data['username']}"))
                continue

            user, created = User.objects.update_or_create(
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "municipio": municipio,
                    "rol": data["rol"],
                    "is_active": True,
                }
            )
            user.set_password(data["password"])
            user.save()
            self.stdout.write(f"{'Creado' if created else 'Actualizado'}: {user.username} ({data['rol']}) - {municipio.nombre}")

        self.stdout.write(self.style.SUCCESS("\nUsuarios creados correctamente."))
