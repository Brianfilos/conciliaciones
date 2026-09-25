def cola_envio(request):
    """Vistas filtradas que el usuario tiene agregadas al envío por correo en preparación."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    cola = request.session.get("cola_envio", {})
    return {"envio_cola": list(cola.values()), "envio_cola_n": len(cola)}
