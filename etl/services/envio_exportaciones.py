"""
Envío por correo de exportaciones (Excel / CSV / TXT) de una o varias vistas filtradas.

Cada "ítem" es una vista de un proceso con SUS filtros y SU formato; todos viajan en un solo correo.
Reutiliza ExportarView, así que cada adjunto es exactamente el archivo que se descargaría con esos
filtros (fechas, columnas, estados…). Cada envío queda registrado en EnvioExportacion.
"""
import re
from email.mime.image import MIMEImage
from email.utils import parseaddr
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import dateformat, timezone, translation
from django.core.validators import validate_email
from django.http import QueryDict
from django.test import RequestFactory

from accounts import correo
from etl.models import ConfiguracionEnvio, EnvioExportacion

MAX_DESTINATARIOS = 10
MAX_ITEMS = 6
FORMATOS = {"excel": "Excel", "csv": "CSV", "txt": "TXT"}
TABS = {"encabezado": "Encabezado", "detalle": "Detalle"}

_ETIQUETAS = {
    "fecha_desde": "desde", "fecha_hasta": "hasta", "estado_pago": "pago", "estado": "estado CXC",
    "tipo_doc": "tipo de documento", "q": "búsqueda", "q_consec": "consecutivo", "q_num": "documento",
    "q_nombre": "nombre", "q_desc": "descripción", "q_concepto": "concepto", "q_centro": "centro",
    "q_valor_unit": "valor unitario", "q_valor_tot": "valor total", "q_total_pagar": "total a pagar",
    "caldas_tipo_persona": "tipo de persona", "caldas_periodo": "período", "caldas_ano": "año",
    "caldas_clasi": "clasificación", "env_fecha_pago_desde": "pago desde", "env_fecha_pago_hasta": "pago hasta",
    "env_fecha_pres_desde": "presentación desde", "env_fecha_pres_hasta": "presentación hasta",
}
_IGNORAR = {"tab", "format", "page", "per_page", "csrfmiddlewaretoken", "sort", "dir"}


class EnvioError(Exception):
    """Error que se le puede mostrar tal cual al usuario."""


def etiqueta_filtros(qs):
    """'estado_pago=PENDIENTE&fecha_desde=2026-01-01' -> 'pago: PENDIENTE · desde: 2026-01-01'."""
    q = qs if isinstance(qs, QueryDict) else QueryDict(qs or "")
    partes = [f"{_ETIQUETAS.get(k, k)}: {v.replace('✓', '').strip()}" for k, v in q.items() if v and k not in _IGNORAR]
    return " · ".join(partes) or "sin filtros"


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


def _nombres_unicos(adjuntos):
    """Si dos vistas dan el mismo nombre de archivo, se numeran para que no se pisen."""
    usados, salida = {}, []
    for nombre, contenido, mime in adjuntos:
        n = usados.get(nombre, 0)
        usados[nombre] = n + 1
        if n:
            base, _, ext = nombre.rpartition(".")
            nombre = f"{base}_{n + 1}.{ext}" if base else f"{nombre}_{n + 1}"
        salida.append((nombre, contenido, mime))
    return salida


def enviar(usuario, items, destinatarios_txt, asunto, mensaje):
    """
    items: lista de dicts {"proceso": Proceso, "tab": str, "filtros": str (querystring), "formato": str}.
    Un solo correo con un adjunto por ítem.
    """
    if not items:
        raise EnvioError("No hay nada para enviar: agrega al menos una vista.")
    if len(items) > MAX_ITEMS:
        raise EnvioError(f"Máximo {MAX_ITEMS} adjuntos por correo.")
    destinatarios = parsear_destinatarios(destinatarios_txt)
    municipio = items[0]["proceso"].municipio
    if any(it["proceso"].municipio_id != municipio.id for it in items):
        raise EnvioError("Un mismo correo no puede mezclar municipios.")

    adjuntos, detalles = [], []
    for it in items:
        if it["formato"] not in FORMATOS:
            raise EnvioError("Formato no válido.")
        tab = it["tab"] if it["tab"] in TABS else "encabezado"
        params = QueryDict(it["filtros"] or "", mutable=True)
        params["format"], params["tab"] = it["formato"], tab
        adj = _exportar(usuario, it["proceso"], params)
        adjuntos.append(adj)
        detalles.append({"proceso": it["proceso"].nombre, "contenido": TABS[tab], "formato": FORMATOS[it["formato"]],
                         "registros": it.get("registros") or "", "filtros": etiqueta_filtros(params)})
    adjuntos = _nombres_unicos(adjuntos)
    total = sum(len(c) for _, c, _ in adjuntos)
    limite = settings.EXPORT_MAX_ADJUNTOS_MB * 1024 * 1024
    if total > limite:
        raise EnvioError(f"Los adjuntos pesan {total / 1048576:.1f} MB y el máximo por correo es "
                         f"{settings.EXPORT_MAX_ADJUNTOS_MB} MB. Aplica más filtros o envía menos vistas.")

    remitente = settings.EXPORT_FROM_EMAIL
    for d, (nombre, _, _) in zip(detalles, adjuntos):
        d["archivo"] = nombre
    nombres_proc = list(dict.fromkeys(it["proceso"].nombre for it in items))
    cfg = ConfiguracionEnvio.obtener()
    contexto = contexto_correo(cfg, municipio.nombre, detalles, mensaje, usuario.get_full_name() or usuario.username)
    corto = contexto["municipio_corto"]
    asunto_defecto = f"Pagos InOva — {corto} — {timezone.localtime():%d-%m-%Y}"
    msg = EmailMultiAlternatives(
        (asunto or "").strip() or asunto_defecto, render_to_string("etl/email_exportacion.txt", contexto),
        remitente, destinatarios, reply_to=[settings.EXPORT_REPLY_TO or parseaddr(remitente)[1] or remitente])
    msg.attach_alternative(render_to_string("etl/email_exportacion.html", contexto), "text/html")
    if contexto["con_logo"]:
        correo.incrustar_logo(msg)
    if contexto["con_firma"]:
        incrustar_firma(msg, cfg)
    for nombre, contenido, mime in adjuntos:
        msg.attach(nombre, contenido, mime.split(";")[0])

    formatos = {it["formato"] for it in items}
    registro = EnvioExportacion.objects.create(
        usuario=usuario, proceso=items[0]["proceso"], procesos=", ".join(nombres_proc)[:300],
        destinatarios=", ".join(destinatarios), asunto=msg.subject[:250],
        formato=formatos.pop() if len(formatos) == 1 else "mixto",
        filtros="\n".join(f"{d['archivo']}: {d['filtros']}" for d in detalles), adjuntos=", ".join(n for n, _, _ in adjuntos))
    try:
        msg.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 - se registra y se explica al usuario
        registro.ok, registro.error = False, str(e)[:500]
        registro.save(update_fields=["ok", "error"])
        raise EnvioError("No se pudo enviar el correo. Revisa la configuración de Brevo "
                         "(remitente verificado e IP autorizada).") from e
    return {"destinatarios": destinatarios, "adjuntos": [n for n, _, _ in adjuntos], "remitente": remitente}


def aplicar_variables(texto, valores):
    """Reemplaza {municipio}, {fecha}… sin fallar si el texto trae otras llaves."""
    return re.sub(r"\{(\w+)\}", lambda m: str(valores.get(m.group(1), m.group(0))), texto or "")


def _datos_firma(cfg):
    """(bytes, subtipo) de la imagen de firma, o None si no hay o no se puede leer."""
    if not cfg.firma_imagen:
        return None
    try:
        from PIL import Image
        with cfg.firma_imagen.open("rb") as f:
            datos = f.read()
        return datos, Image.open(BytesIO(datos)).format.lower()
    except Exception:  # noqa: BLE001 - archivo faltante o dañado: el correo sale sin imagen
        return None


def incrustar_firma(msg, cfg):
    d = _datos_firma(cfg)
    if not d:
        return False
    msg.mixed_subtype = "related"
    img = MIMEImage(d[0], _subtype=d[1])
    img.add_header("Content-ID", "<firma>")
    img.add_header("Content-Disposition", "inline", filename=f"firma.{d[1]}")
    msg.attach(img)
    return True


def contexto_correo(cfg, municipio_nombre, detalles, mensaje_usuario, remitente_nombre, ahora=None):
    """Datos con los que se dibuja el correo (también los usa la vista previa)."""
    ahora = ahora or timezone.localtime()
    with translation.override("es"):
        fecha_larga = dateformat.format(ahora, r"j \d\e F \d\e Y")
    corto = re.sub(r"^Municipio (de )?", "", municipio_nombre)
    n = len(detalles)
    adjuntos_txt = "el archivo de pagos que reposa" if n == 1 else f"los {n} archivos de pagos que reposan"
    valores = {"municipio": corto, "fecha": fecha_larga, "hora": ahora.strftime("%H:%M"),
               "adjuntos": adjuntos_txt, "n_archivos": n}
    return {
        "municipio": municipio_nombre, "municipio_corto": corto, "items": detalles,
        "saludo": aplicar_variables(cfg.saludo, valores), "cuerpo": aplicar_variables(cfg.mensaje, valores),
        "despedida": aplicar_variables(cfg.despedida, valores), "mensaje": (mensaje_usuario or "").strip(),
        "firma_texto": (cfg.firma_texto or "").strip(), "con_firma": _datos_firma(cfg) is not None,
        "remitente_nombre": remitente_nombre, "con_logo": correo.logo_disponible(),
    }
