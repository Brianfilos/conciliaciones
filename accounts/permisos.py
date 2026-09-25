"""
Reglas de acceso por municipio (una sola fuente de verdad).

- Cualquier usuario ve y trabaja solo con los datos de SU municipio.
- Borrar datos, ejecuciones, CIIU o conceptos: solo el administrador de ese municipio.
- El superusuario puede todo en todos los municipios.
"""


def del_municipio(usuario, municipio):
    """Puede consultar/trabajar con los datos de ese municipio."""
    return bool(usuario.is_superuser or (usuario.municipio_id and usuario.municipio_id == municipio.id))


def es_admin_de(usuario, municipio):
    """Puede borrar y administrar en ese municipio: su administrador o un superusuario."""
    return bool(usuario.is_superuser
                or (usuario.rol == "ADMIN" and usuario.municipio_id and usuario.municipio_id == municipio.id))
