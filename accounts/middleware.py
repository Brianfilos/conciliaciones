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


CSP = "; ".join([
    "default-src 'self'",
    # Las plantillas usan scripts y estilos en línea; el resto solo puede venir del propio sitio y del CDN de Bootstrap
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])


class CabecerasSeguridadMiddleware:
    """Cabeceras que limitan lo que el navegador puede cargar o ejecutar (freno ante XSS,
    clickjacking y fuga de datos), y evitan que páginas con datos queden en caché."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        r = self.get_response(request)
        r.setdefault("Content-Security-Policy", CSP)
        r.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        r.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.path.startswith("/static/"):
            # Datos de contribuyentes: que un equipo compartido no pueda verlos con el botón "atrás"
            r.setdefault("Cache-Control", "no-store")
        return r
