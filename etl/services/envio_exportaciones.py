"""
Envío por correo de las exportaciones (Excel / CSV / TXT) de uno o varios procesos.

Reutiliza ExportarView, así que el adjunto es exactamente el archivo que se descargaría con los
mismos filtros (fechas, columnas, estados…). Cada envío queda registrado en EnvioExportacion.
"""
import re
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.http import QueryDict
from django.test import RequestFactory

from etl.models import EnvioExportacion

MAX_DESTINATARIOS = 10
FORMATOS = {"excel": "Excel", "csv": "CSV", "txt": "TXT"}
# Filtros que tienen sentido en cualquier proceso: se reutilizan al adjuntar procesos adicionales
FILTROS_COMPARTIDOS = ("fecha_desde", "fecha_hasta", "estado_pago", "estado", "tipo_doc")


class EnvioError(Exception):
    """Error que se le puede mostrar tal cual al usuario."""


def parsear_destinatarios(texto):
    partes = [p for p in re.split(r"[,;\s]+", texto or "") if p]
    if not partes:
        raise EnvioError("Escribe al menos un correo destinatario.")
    if len(partes) > MAX_DESTINATARIOS:
        raise EnvioError(f"Máximo {MAX_DESTINATARIOS} destinatarios por envío.")
    for p in partes:
        try:
            validate_email(p)
        except ValidationError:
            raise EnvioError(f"El correo «{p}» no es válido.") from None
    return list(dict.fromkeys(p.lower() for p in partes))


def _exportar(usuario, proceso, params):
    """Ejecuta la exportación existente y devuelve (nombre_archivo, bytes, mime)."""
    from etl.views import ExportarView  # import tardío: evita ciclos
    req = RequestFactory().get(f"/etl/exportar/{proceso.id}/", params)
    req.user = usuario
    resp = ExportarView().get(req, proceso.id)
    if resp.status_code != 200 or not resp.has_header("Content-Disposition"):
        raise EnvioError(f"No se pudo generar la exportación de «{proceso.nombre}».")
    m = re.search(r'filename="([^"]+)"', resp["Content-Disposition"])
    return (m.group(1) if m else f"{proceso.municipio.codigo}_{proceso.codigo}.dat"), resp.content, resp["Content-Type"]


def _resumen_filtros(qs):
    ignorar = {"tab", "format", "page", "per_page", "csrfmiddlewaretoken"}
    return "; ".join(f"{k}={v}" for k, v in qs.items() if v and k not in ignorar) or "sin filtros"


def enviar(usuario, proceso, formato, tab, filtros_qs, destinatarios_txt, asunto, mensaje, otros_procesos=()):
    if formato not in FORMATOS:
        raise EnvioError("Formato no válido.")
    destinatarios = parsear_destinatarios(destinatarios_txt)

    filtros = QueryDict(filtros_qs or "", mutable=True)
    principal = filtros.copy()
    principal["format"], principal["tab"] = formato, tab or "encabezado"
    trabajos = [(proceso, principal)]
    for extra in otros_procesos:
        p = QueryDict("", mutable=True)
        for k in FILTROS_COMPARTIDOS:
            if filtros.get(k):
                p[k] = filtros[k]
        p["format"], p["tab"] = formato, tab or "encabezado"
        trabajos.append((extra, p))

    adjuntos = [_exportar(usuario, pr, params) for pr, params in trabajos]
    total = sum(len(c) for _, c, _ in adjuntos)
    limite = settings.EXPORT_MAX_ADJUNTOS_MB * 1024 * 1024
    if total > limite:
        raise EnvioError(f"Los adjuntos pesan {total / 1048576:.1f} MB y el máximo por correo es "
                         f"{settings.EXPORT_MAX_ADJUNTOS_MB} MB. Aplica más filtros o envía menos procesos.")

    remitente = settings.EXPORT_FROM_EMAIL
    procesos_txt = ", ".join(pr.nombre for pr, _ in trabajos)
    cuerpo = "\n".join([
        "Hola,",
        "",
        (mensaje or "").strip() or "Adjunto el reporte solicitado.",
        "",
        f"Municipio: {proceso.municipio.nombre}",
        f"Procesos: {procesos_txt}",
        f"Formato: {FORMATOS[formato]}",
        f"Filtros del proceso principal: {_resumen_filtros(filtros)}",
        "",
        f"Enviado desde el Sistema de CXC por {usuario.get_full_name() or usuario.username}.",
    ])
    msg = EmailMessage(
        (asunto or "").strip() or f"Reporte {proceso.municipio.nombre} — {proceso.nombre}",
        cuerpo, remitente, destinatarios,
        reply_to=[settings.EXPORT_REPLY_TO or parseaddr(remitente)[1] or remitente])
    for nombre, contenido, mime in adjuntos:
        msg.attach(nombre, contenido, mime.split(";")[0])

    registro = EnvioExportacion.objects.create(
        usuario=usuario, proceso=proceso, procesos=procesos_txt, destinatarios=", ".join(destinatarios),
        asunto=msg.subject, formato=formato, filtros=filtros_qs or "",
        adjuntos=", ".join(n for n, _, _ in adjuntos))
    try:
        msg.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 - se registra y se explica al usuario
        registro.ok, registro.error = False, str(e)[:500]
        registro.save(update_fields=["ok", "error"])
        raise EnvioError("No se pudo enviar el correo. Revisa la configuración de Brevo "
                         "(remitente verificado e IP autorizada).") from e
    return {"destinatarios": destinatarios, "adjuntos": [n for n, _, _ in adjuntos], "remitente": remitente}
