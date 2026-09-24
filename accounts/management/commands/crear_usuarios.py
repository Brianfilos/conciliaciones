from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.correo import generar_temporal
from muni.models import Municipio

User = get_user_model()

# Usuarios base por municipio. Las contraseñas NO se guardan en el código: se generan al
# crear cada usuario, se imprimen una sola vez y piden cambio en el primer ingreso.
# Para altas nuevas usa el panel "Usuarios" de la app (solo superusuario).
USUARIOS = [
    # Operadores
    {"username": "brianestrella",  "municipio": "ESTRELLA",   "rol": "OPERADOR", "email": "brianestrella@cxc.local"},
    {"username": "briancopa",      "municipio": "COPACABANA", "rol": "OPERADOR", "email": "briancopa@cxc.local"},
    {"username": "briancaldas",    "municipio": "CALDAS",     "rol": "OPERADOR", "email": "briancaldas@cxc.local"},
    {"username": "brianenvigado",  "municipio": "ENVIGADO",   "rol": "OPERADOR", "email": "brianenvigado@cxc.local"},
    {"username": "briansabaneta",  "municipio": "SABANETA",   "rol": "OPERADOR", "email": "briansabaneta@cxc.local"},
    # Admins
    {"username": "adminEstrella",  "municipio": "ESTRELLA",   "rol": "ADMIN", "email": "adminestrella@cxc.local"},
    {"username": "adminCopa",      "municipio": "COPACABANA", "rol": "ADMIN", "email": "admincopa@cxc.local"},
    {"username": "adminCaldas",    "municipio": "CALDAS",     "rol": "ADMIN", "email": "admincaldas@cxc.local"},
    {"username": "adminEnvigado",  "municipio": "ENVIGADO",   "rol": "ADMIN", "email": "adminenvigado@cxc.local"},
    {"username": "adminSabaneta",  "municipio": "SABANETA",   "rol": "ADMIN", "email": "adminsabaneta@cxc.local"},
]


class Command(BaseCommand):
    help = "Crea los usuarios base del sistema CXC con contraseñas aleatorias (solo los que no existen)"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="También genera contraseña nueva para los usuarios que ya existen")

    def handle(self, *args, **options):
        entregar = []
        for data in USUARIOS:
            try:
                municipio = Municipio.objects.get(codigo=data["municipio"])
            except Municipio.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Municipio {data['municipio']} no encontrado, omitiendo {data['username']}"))
                continue

            user = User.objects.filter(username=data["username"]).first()
            if user and not options["reset"]:
                self.stdout.write(f"Ya existe: {user.username} (sin cambios)")
                continue
            creado = user is None
            if creado:
                user = User(username=data["username"])
            user.email = data["email"]
            user.municipio = municipio
            user.rol = data["rol"]
            user.is_active = True
            clave = generar_temporal(12)
            user.set_password(clave)
            user.debe_cambiar_password = True
            user.save()
            entregar.append((user.username, clave))
            self.stdout.write(f"{'Creado' if creado else 'Actualizado'}: {user.username} ({data['rol']}) - {municipio.nombre}")

        if entregar:
            self.stdout.write(self.style.WARNING("\nContraseñas iniciales (se muestran solo ahora; piden cambio al ingresar):"))
            for usuario, clave in entregar:
                self.stdout.write(f"  {usuario:16} {clave}")
        self.stdout.write(self.style.SUCCESS("\nListo."))
