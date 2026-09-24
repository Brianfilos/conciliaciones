from django.shortcuts import redirect


class ForzarCambioPasswordMiddleware:
    """Quien entró con una contraseña temporal no puede usar la app hasta elegir una nueva."""

    EXENTAS = ("/cambiar-password/", "/logout/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, "user", None)
        if (u is not None and u.is_authenticated and getattr(u, "debe_cambiar_password", False)
                and not request.path.startswith(self.EXENTAS)):
            return redirect("cambiar_password")
        return self.get_response(request)
