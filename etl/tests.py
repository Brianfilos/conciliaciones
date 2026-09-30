from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from etl.models import DetalleCXC, EncabezadoCXC, Ejecucion, EnvioExportacion, Proceso
from muni.models import Municipio

User = get_user_model()


def _adjuntos(mensaje):
    """Solo los archivos de datos (el logo/firma incrustados viajan como imágenes dentro del mensaje)."""
    return [a for a in mensaje.attachments if isinstance(a, tuple)]


def _texto(contenido):
    """Los adjuntos de texto llegan como str; la descarga como bytes (con BOM para Excel)."""
    if isinstance(contenido, bytes):
        contenido = contenido.decode("utf-8")
    return contenido.lstrip("﻿")


def _crear_encabezado(proceso, ejec, consec, pago, valor, nombre="Contribuyente"):
    e = EncabezadoCXC.objects.create(
        proceso=proceso, ejecucion=ejec, consecutivo_cxc=consec, consecutivo_original=consec,
        numero_documento=f"9000{consec}", razon_social=nombre, total_a_pagar=valor, estado_pago=pago,
        datos_extra={"nombre_establecimiento": nombre, "fecha_visita": "2026-05-13 10:00:00.000",
                     "ano": "2026", "bimestre": "2 Marzo/Abril 2026", "tipo_declaracion": "Normal",
                     "radicado": "", "fecha_pago": ""})
    DetalleCXC.objects.create(encabezado=e, codigo_concepto="C1", centro_costo="01", valor_unitario=valor, valor_total=valor)
    return e


@override_settings(EXPORT_FROM_EMAIL="Brian Filos <brian.filos@gobs.com.co>")
class EnvioExportacionTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="TEST", nombre="Municipio de Prueba")
        self.otro_mun = Municipio.objects.create(codigo="OTRO", nombre="Otro Municipio")
        self.p1 = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        self.p2 = Proceso.objects.create(municipio=self.mun, codigo="CXC_RETE", nombre="Retención ICA")
        self.user = User.objects.create_user("op", "op@example.com", "Operador#2026", municipio=self.mun, rol="OPERADOR")
        self.ajeno = User.objects.create_user("aj", "aj@example.com", "Ajeno#2026", municipio=self.otro_mun, rol="OPERADOR")
        for p in (self.p1, self.p2):
            ej = Ejecucion.objects.create(proceso=p, usuario=self.user)
            _crear_encabezado(p, ej, "1001", "✓ PAGO REALIZADO", 1000, "Ana SAS")
            _crear_encabezado(p, ej, "1002", "PENDIENTE DE PAGO", 2000, "Beto SAS")
        self.client.force_login(self.user)

    def _enviar(self, proceso=None, **extra):
        proceso = proceso or self.p1
        datos = {"destinatarios": "cliente@example.com", "formato_actual": "excel", "tab": "encabezado",
                 "filtros": "", "incluir_actual": "1"}
        datos.update(extra)
        return self.client.post(reverse("exportar_correo", args=[proceso.id]), datos)

    def _agregar(self, proceso, **extra):
        datos = {"tab": "encabezado", "filtros": "", "formato_actual": "csv", "registros": "2"}
        datos.update(extra)
        return self.client.post(reverse("envio_agregar", args=[proceso.id]), datos)

    def test_envia_excel_con_remitente_configurado(self):
        r = self._enviar()
        self.assertEqual(r.status_code, 302)
        m = mail.outbox[0]
        self.assertEqual(m.from_email, "Brian Filos <brian.filos@gobs.com.co>")
        self.assertEqual(m.reply_to, ["brian.filos@gobs.com.co"])
        self.assertEqual(m.to, ["cliente@example.com"])
        nombre, contenido, _ = _adjuntos(m)[0]
        self.assertTrue(nombre.endswith(".xlsx"))
        self.assertTrue(contenido.startswith(b"PK"))
        reg = EnvioExportacion.objects.get()
        self.assertTrue(reg.ok)
        self.assertEqual(reg.usuario, self.user)

    def test_el_adjunto_es_igual_a_la_descarga_con_los_mismos_filtros(self):
        self._enviar(formato_actual="csv", filtros="estado_pago=PENDIENTE")
        adjunto = _texto(_adjuntos(mail.outbox[0])[0][1])
        descarga = self.client.get(reverse("exportar", args=[self.p1.id]),
                                   {"format": "csv", "tab": "encabezado", "estado_pago": "PENDIENTE"})
        self.assertEqual(adjunto.strip(), _texto(descarga.content).strip())
        self.assertIn("Beto SAS", adjunto)
        self.assertNotIn("Ana SAS", adjunto)

    def test_tres_vistas_con_filtros_distintos_en_un_solo_correo(self):
        # Se filtra y se agrega el primer proceso, luego se abre el segundo y se envía todo junto
        self._agregar(self.p1, filtros="estado_pago=PENDIENTE", formato_actual="csv")
        self.assertEqual(len(self.client.session["cola_envio"]), 1)
        self._enviar(self.p2, formato_actual="txt", filtros="estado_pago=PAGO+REALIZADO", mensaje="Va todo junto")
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(len(_adjuntos(m)), 2)
        por_nombre = {n: _texto(c) for n, c, _ in _adjuntos(m)}
        auto = next(v for n, v in por_nombre.items() if "CXC_AUTO" in n)
        rete = next(v for n, v in por_nombre.items() if "CXC_RETE" in n)
        self.assertIn("Beto SAS", auto)       # cada adjunto conserva SU filtro
        self.assertNotIn("Ana SAS", auto)
        self.assertIn("Ana SAS", rete)
        self.assertNotIn("Beto SAS", rete)
        self.assertIn("Autorretención", m.body)
        self.assertIn("Retención ICA", m.body)
        self.assertIn("Va todo junto", m.body)
        self.assertEqual(self.client.session["cola_envio"], {})  # la cola se vacía al enviar

    def test_solo_la_cola_sin_la_vista_actual(self):
        self._agregar(self.p1)
        self.client.post(reverse("exportar_correo", args=[self.p2.id]),
                         {"destinatarios": "a@example.com", "tab": "encabezado", "filtros": ""})
        self.assertEqual(len(_adjuntos(mail.outbox[0])), 1)
        self.assertIn("CXC_AUTO", _adjuntos(mail.outbox[0])[0][0])

    def test_quitar_y_vaciar(self):
        self._agregar(self.p1)
        self._agregar(self.p2)
        self.client.post(reverse("envio_quitar"), {"clave": f"{self.p1.id}:encabezado"})
        self.assertEqual(list(self.client.session["cola_envio"]), [f"{self.p2.id}:encabezado"])
        self.client.post(reverse("envio_quitar"), {"vaciar": "1"})
        self.assertEqual(self.client.session["cola_envio"], {})

    def test_si_falla_el_envio_la_cola_se_conserva(self):
        self._agregar(self.p1)
        self.client.post(reverse("exportar_correo", args=[self.p2.id]), {"destinatarios": "correo-malo", "tab": "encabezado"})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(self.client.session["cola_envio"]), 1)

    def test_nada_que_enviar(self):
        self.client.post(reverse("exportar_correo", args=[self.p1.id]), {"destinatarios": "a@example.com", "tab": "encabezado"})
        self.assertEqual(len(mail.outbox), 0)

    def test_varios_destinatarios_y_asunto(self):
        self._enviar(destinatarios="a@example.com; b@example.com  c@example.com", asunto="Mi asunto")
        m = mail.outbox[0]
        self.assertEqual(m.to, ["a@example.com", "b@example.com", "c@example.com"])
        self.assertEqual(m.subject, "Mi asunto")

    def test_correo_invalido_y_demasiados(self):
        self._enviar(destinatarios="no-es-un-correo")
        self._enviar(destinatarios=",".join(f"u{i}@example.com" for i in range(11)))
        self.assertEqual(len(mail.outbox), 0)

    def test_otro_municipio_no_puede_enviar_ni_agregar(self):
        self.client.force_login(self.ajeno)
        self._enviar()
        self._agregar(self.p1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EnvioExportacion.objects.count(), 0)
        self.assertEqual(self.client.session.get("cola_envio", {}), {})

    def test_la_cola_no_mezcla_municipios(self):
        root = User.objects.create_superuser("root", "root@example.com", "Root#2026")
        p_otro = Proceso.objects.create(municipio=self.otro_mun, codigo="CXC_AUTO", nombre="Auto otro")
        self.client.force_login(root)
        self._agregar(self.p1)
        self._agregar(p_otro)
        self.assertEqual(len(self.client.session["cola_envio"]), 1)

    def test_maximo_de_adjuntos(self):
        from etl.services.envio_exportaciones import MAX_ITEMS
        for i in range(MAX_ITEMS + 2):
            p = Proceso.objects.create(municipio=self.mun, codigo=f"X{i}", nombre=f"Extra {i}")
            self._agregar(p)
        self.assertEqual(len(self.client.session["cola_envio"]), MAX_ITEMS)

    @override_settings(EXPORT_MAX_ADJUNTOS_MB=0)
    def test_limite_de_tamano(self):
        self._enviar()
        self.assertEqual(len(mail.outbox), 0)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        self.assertEqual(self._enviar().status_code, 302)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EXPORT_FROM_EMAIL="Brian Filos <brian.filos@gobs.com.co>")
class EnvioSabanetaTests(TestCase):
    def test_reporte_de_publicidad_solo_pagadas(self):
        mun = Municipio.objects.create(codigo="SABANETA", nombre="Municipio de Sabaneta")
        p = Proceso.objects.create(municipio=mun, codigo="PUBLICIDAD_EXTERIOR", nombre="Publicidad Exterior Visual")
        u = User.objects.create_user("sab", "sab@example.com", "Sabaneta#2026", municipio=mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=p, usuario=u)
        _crear_encabezado(p, ej, "10", "✓ Pago realizado", 500, "Pagó SAS")
        _crear_encabezado(p, ej, "11", "Pendiente de pago", 700, "Debe SAS")
        self.client.force_login(u)
        self.client.post(reverse("exportar_correo", args=[p.id]),
                         {"destinatarios": "x@example.com", "formato_actual": "csv", "tab": "encabezado",
                          "filtros": "", "incluir_actual": "1"})
        adjunto = _texto(_adjuntos(mail.outbox[0])[0][1])
        self.assertIn("Pagó SAS", adjunto)
        self.assertNotIn("Debe SAS", adjunto)


class FiltrosLegiblesTests(TestCase):
    def test_resumen(self):
        from etl.services.envio_exportaciones import etiqueta_filtros
        self.assertEqual(etiqueta_filtros("tab=encabezado&estado_pago=PENDIENTE&fecha_desde=2026-01-01&q="),
                         "pago: PENDIENTE · desde: 2026-01-01")
        self.assertEqual(etiqueta_filtros(""), "sin filtros")


class ExplorerHtmlTests(TestCase):
    def test_el_formulario_de_correo_no_esta_anidado_en_el_de_filtros(self):
        """Un <form> dentro de otro lo descarta el navegador y sus campos pasan a bloquear los filtros."""
        from html.parser import HTMLParser

        class Anidados(HTMLParser):
            def __init__(self):
                super().__init__()
                self.pila, self.maxima, self.filtros_con_campos_de_correo = [], 0, False

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "form":
                    self.pila.append(a.get("id") or a.get("action", ""))
                    self.maxima = max(self.maxima, len(self.pila))
                if tag in ("input", "textarea") and "filter-form" in self.pila and a.get("name") in ("destinatarios", "csrfmiddlewaretoken"):
                    self.filtros_con_campos_de_correo = True

            def handle_endtag(self, tag):
                if tag == "form" and self.pila:
                    self.pila.pop()

        mun = Municipio.objects.create(codigo="TEST", nombre="Municipio de Prueba")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("adm", "adm@example.com", "Admin#2026", municipio=mun, rol="ADMIN")
        self.client.force_login(u)
        html = self.client.get(reverse("dashboard", args=[p.id])).content.decode()
        self.assertIn('id="modal-correo"', html)
        analizador = Anidados()
        analizador.feed(html)
        self.assertEqual(analizador.maxima, 1, "hay formularios anidados")
        self.assertFalse(analizador.filtros_con_campos_de_correo)


class PermisosPorMunicipioTests(TestCase):
    """Cada usuario trabaja solo con su municipio y solo su administrador puede borrar."""

    def setUp(self):
        self.a = Municipio.objects.create(codigo="MUNA", nombre="Municipio A")
        self.b = Municipio.objects.create(codigo="MUNB", nombre="Municipio B")
        self.pa = Proceso.objects.create(municipio=self.a, codigo="CXC_AUTO", nombre="Auto A")
        self.op_a = User.objects.create_user("op_a", "opa@example.com", "Operador#2026", municipio=self.a, rol="OPERADOR")
        self.an_a = User.objects.create_user("an_a", "ana@example.com", "Analitico#2026", municipio=self.a, rol="ANALITICO")
        self.adm_a = User.objects.create_user("adm_a", "adma@example.com", "Admin#2026", municipio=self.a, rol="ADMIN")
        self.adm_b = User.objects.create_user("adm_b", "admb@example.com", "Admin#2026", municipio=self.b, rol="ADMIN")
        self.root = User.objects.create_superuser("root", "root@example.com", "Root#2026")
        ej = Ejecucion.objects.create(proceso=self.pa, usuario=self.op_a)
        _crear_encabezado(self.pa, ej, "1", "PENDIENTE DE PAGO", 100)

    def _limpiar(self, usuario):
        self.client.force_login(usuario)
        return self.client.post(reverse("limpiar_proceso", args=[self.pa.id]))

    def test_operador_y_analitico_no_pueden_borrar(self):
        for u in (self.op_a, self.an_a):
            self._limpiar(u)
            self.assertEqual(EncabezadoCXC.objects.filter(proceso=self.pa).count(), 1, u.username)
            self.assertEqual(Ejecucion.objects.filter(proceso=self.pa).count(), 1, u.username)

    def test_admin_de_otro_municipio_no_puede_borrar(self):
        self._limpiar(self.adm_b)
        self.assertEqual(EncabezadoCXC.objects.filter(proceso=self.pa).count(), 1)
        self.assertEqual(Ejecucion.objects.filter(proceso=self.pa).count(), 1)

    def test_admin_del_municipio_si_puede_borrar(self):
        self._limpiar(self.adm_a)
        self.assertEqual(EncabezadoCXC.objects.filter(proceso=self.pa).count(), 0)
        self.assertEqual(Ejecucion.objects.filter(proceso=self.pa).count(), 0)

    def test_superusuario_puede_borrar(self):
        self._limpiar(self.root)
        self.assertEqual(EncabezadoCXC.objects.filter(proceso=self.pa).count(), 0)

    def test_la_zona_de_peligro_solo_se_ve_al_admin(self):
        self.client.force_login(self.op_a)
        self.assertNotContains(self.client.get(reverse("ejecutar_proceso", args=[self.pa.id])), "Limpiar todos los datos")
        self.client.force_login(self.adm_a)
        self.assertContains(self.client.get(reverse("ejecutar_proceso", args=[self.pa.id])), "Limpiar todos los datos")

    def test_admin_de_otro_municipio_no_entra_a_procesos_ajenos(self):
        self.client.force_login(self.adm_b)
        for nombre in ("ejecutar_proceso", "dashboard", "exportar"):
            r = self.client.get(reverse(nombre, args=[self.pa.id]))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertNotIn(str(self.pa.id), r["Location"], nombre)
        self.client.post(reverse("exportar_correo", args=[self.pa.id]), {"destinatarios": "x@example.com", "formato": "csv"})
        self.assertEqual(len(mail.outbox), 0)
        ej = Ejecucion.objects.filter(proceso=self.pa).first()
        self.assertEqual(self.client.get(reverse("ejecucion_status", args=[ej.id])).status_code, 403)

    def test_el_operador_del_municipio_si_trabaja_con_sus_datos(self):
        self.client.force_login(self.op_a)
        for nombre in ("ejecutar_proceso", "dashboard"):
            self.assertEqual(self.client.get(reverse(nombre, args=[self.pa.id])).status_code, 200, nombre)

    def test_ciiu_y_conceptos_solo_el_admin_de_ese_municipio(self):
        from muni.models import CIIUMunicipio, ConceptoMunicipio
        c = CIIUMunicipio.objects.create(municipio=self.a, codigo="0111", descripcion="x", tipo="COMERCIAL")
        k = ConceptoMunicipio.objects.create(municipio=self.a, codigo="K1", descripcion="x")
        for usuario in (self.adm_b, self.op_a):
            self.client.force_login(usuario)
            for nombre, datos in (("cargar_ciiu", {"action": "eliminar", "ciiu_id": c.id}),
                                  ("cargar_conceptos", {"action": "eliminar", "concepto_id": k.id})):
                self.assertEqual(self.client.get(reverse(nombre, args=["MUNA"])).status_code, 302, nombre)
                self.client.post(reverse(nombre, args=["MUNA"]), datos)
        self.assertTrue(CIIUMunicipio.objects.filter(pk=c.pk).exists())
        self.assertTrue(ConceptoMunicipio.objects.filter(pk=k.pk).exists())
        self.client.force_login(self.adm_a)
        self.assertEqual(self.client.get(reverse("cargar_ciiu", args=["MUNA"])).status_code, 200)


def _png(ancho=600, alto=200):
    """Imagen PNG de prueba (una firma cualquiera)."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (ancho, alto), (10, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


@override_settings(EXPORT_FROM_EMAIL="Brian Filos <brian.filos@gobs.com.co>")
class ConfiguracionCorreoTests(TestCase):
    def setUp(self):
        import tempfile
        self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media.enable()
        self.addCleanup(self._media.disable)
        self.mun = Municipio.objects.create(codigo="TEST", nombre="Municipio de Prueba")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        self.root = User.objects.create_superuser("root", "root@example.com", "Root#2026")
        self.adm = User.objects.create_user("adm", "adm@example.com", "Admin#2026", municipio=self.mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=self.p, usuario=self.adm)
        _crear_encabezado(self.p, ej, "1", "PENDIENTE DE PAGO", 100, "Ana SAS")
        self.url = reverse("config_correo")

    def _enviar(self, **extra):
        self.client.force_login(self.adm)
        datos = {"destinatarios": "x@example.com", "formato_actual": "csv", "tab": "encabezado", "filtros": "",
                 "incluir_actual": "1", "registros": "1"}
        datos.update(extra)
        self.client.post(reverse("exportar_correo", args=[self.p.id]), datos)
        return mail.outbox[-1]

    def test_solo_el_superusuario_configura(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"saludo": "x", "mensaje": "y"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("config_correo_vista")).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_texto_por_defecto_profesional(self):
        m = self._enviar()
        self.assertIn("Cordial saludo", m.body)
        self.assertIn("sistema de información InOva del municipio de Prueba", m.body)
        self.assertIn("el archivo de pagos que reposa", m.body)
        self.assertIn("Archivo adjunto", m.body)

    def test_mensaje_y_saludo_configurables_con_variables(self):
        self.client.force_login(self.root)
        self.client.post(self.url, {"saludo": "Buen día,", "despedida": "Atentamente,",
                                    "mensaje": "Pagos de {municipio} ({n_archivos} archivo) al {fecha} {hora}. {no_existe}"})
        m = self._enviar()
        self.assertIn("Buen día,", m.body)
        self.assertIn("Pagos de Prueba (1 archivo) al", m.body)
        self.assertIn("{no_existe}", m.body)          # variable desconocida: se deja tal cual, no falla
        self.assertIn("Atentamente,", m.body)
        self.assertNotIn("Cordial saludo", m.body)

    def test_varios_archivos_usan_plural(self):
        self.client.force_login(self.root)
        p2 = Proceso.objects.create(municipio=self.mun, codigo="CXC_RETE", nombre="Retención ICA")
        ej = Ejecucion.objects.create(proceso=p2, usuario=self.adm)
        _crear_encabezado(p2, ej, "2", "PENDIENTE DE PAGO", 50, "Beto SAS")
        self.client.force_login(self.adm)
        self.client.post(reverse("envio_agregar", args=[p2.id]), {"tab": "encabezado", "filtros": "", "formato_actual": "csv"})
        m = self._enviar()
        self.assertIn("los 2 archivos de pagos que reposan", m.body)

    def test_firma_imagen_se_incrusta_y_se_puede_quitar(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.root)
        self.client.post(self.url, {"saludo": "Hola", "mensaje": "M", "despedida": "",
                                    "firma_imagen": SimpleUploadedFile("firma.png", _png(), content_type="image/png")})
        m = self._enviar()
        ids = [a.get("Content-ID") for a in m.attachments if not isinstance(a, tuple)]
        self.assertIn("<firma>", ids)
        self.assertIn("cid:firma", m.alternatives[0][0])
        self.client.force_login(self.root)
        self.client.post(self.url, {"saludo": "Hola", "mensaje": "M", "despedida": "", "quitar_firma": "on"})
        m = self._enviar()
        self.assertNotIn("<firma>", [a.get("Content-ID") for a in m.attachments if not isinstance(a, tuple)])
        self.assertNotIn("cid:firma", m.alternatives[0][0])

    def test_firma_en_texto_si_no_hay_imagen(self):
        self.client.force_login(self.root)
        self.client.post(self.url, {"saludo": "Hola", "mensaje": "M", "despedida": "",
                                    "firma_texto": "Brian Filos\nIngeniero Mecatrónico"})
        m = self._enviar()
        self.assertIn("Ingeniero Mecatrónico", m.body)
        self.assertIn("Ingeniero Mecatrónico", m.alternatives[0][0])

    def test_rechaza_archivos_que_no_son_imagen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.root)
        r = self.client.post(self.url, {"saludo": "Hola", "mensaje": "M", "despedida": "",
                                        "firma_imagen": SimpleUploadedFile("x.png", b"esto no es una imagen", content_type="image/png")})
        self.assertEqual(r.status_code, 200)
        from etl.models import ConfiguracionEnvio
        self.assertFalse(ConfiguracionEnvio.obtener().firma_imagen)

    def test_restablecer_textos(self):
        from etl.models import ConfiguracionEnvio
        self.client.force_login(self.root)
        self.client.post(self.url, {"saludo": "Otro", "mensaje": "Otro mensaje", "despedida": "Chao"})
        self.client.post(self.url, {"restablecer": "1"})
        cfg = ConfiguracionEnvio.obtener()
        self.assertEqual(cfg.saludo, "Cordial saludo,")
        self.assertIn("InOva", cfg.mensaje)

    def test_vista_previa(self):
        self.client.force_login(self.root)
        r = self.client.get(reverse("config_correo_vista"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cordial saludo")
        self.assertContains(r, "Copacabana")
        self.assertNotContains(r, "cid:")            # los cid se sustituyen por imágenes incrustadas en la página
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")


class SubidasSeguridadTests(TestCase):
    def setUp(self):
        from etl.models import InsumoDefinicion
        self.mun = Municipio.objects.create(codigo="SUB", nombre="Municipio Subidas")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        InsumoDefinicion.objects.create(proceso=self.p, nombre="Archivo CXC", nombre_campo="cxc_csv",
                                        tipo="CARGUE", extensiones=".csv", orden=1)
        self.u = User.objects.create_user("op", "op@example.com", "Operador#2026", municipio=self.mun, rol="OPERADOR")

    def test_rechaza_extension_no_declarada(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.u)
        r = self.client.post(reverse("ejecutar_proceso", args=[self.p.id]),
                             {"cxc_csv": SimpleUploadedFile("malo.php", b"<?php ?>")})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Formato no permitido")
        self.assertFalse(Ejecucion.objects.filter(proceso=self.p).exists())

    def test_rechaza_archivo_demasiado_grande(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.u)
        with override_settings(UPLOAD_MAX_MB=0):
            r = self.client.post(reverse("ejecutar_proceso", args=[self.p.id]),
                                 {"cxc_csv": SimpleUploadedFile("a.csv", b"a;b\n1;2\n")})
        self.assertContains(r, "pesa más de")
        self.assertFalse(Ejecucion.objects.filter(proceso=self.p).exists())

    def test_firma_con_tipo_falso_se_rechaza(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from etl.forms import ConfiguracionEnvioForm
        f = ConfiguracionEnvioForm(
            {"saludo": "Hola", "mensaje": "x", "despedida": "y"},
            {"firma_imagen": SimpleUploadedFile("firma.png", b"<svg onload=alert(1)>", content_type="image/png")})
        self.assertFalse(f.is_valid())
        self.assertIn("firma_imagen", f.errors)


class SofinetValidarCsvTests(TestCase):
    def test_rechaza_vacio(self):
        from etl.services.sofinet_bot import validar_csv
        self.assertIsNotNone(validar_csv(b""))

    def test_rechaza_sin_columna_consecutivo(self):
        from etl.services.sofinet_bot import validar_csv
        self.assertIsNotNone(validar_csv(b"A,B\n1,2\n" * 5))

    def test_rechaza_pagina_html_de_login(self):
        from etl.services.sofinet_bot import validar_csv
        self.assertIsNotNone(validar_csv(b"<html><body>Login</body></html>" * 3))

    def test_acepta_csv_con_consecutivo(self):
        from etl.services.sofinet_bot import validar_csv
        self.assertIsNone(validar_csv(b"CONSECUTIVO,ESTADO\n123,PAGADO\n" * 3))


class ActualizarSofinetCommandTests(TestCase):
    def setUp(self):
        from etl.models import InsumoDefinicion
        self.estrella = Municipio.objects.create(codigo="ESTRELLA", nombre="La Estrella")
        self.p_auto = Proceso.objects.create(municipio=self.estrella, codigo="CXC_AUTO", nombre="Autorretención")
        self.p_rete = Proceso.objects.create(municipio=self.estrella, codigo="CXC_RETE", nombre="ReteICA")
        self.p_declare = Proceso.objects.create(municipio=self.estrella, codigo="DECLAREYPAGUE", nombre="Declare y Pague")
        for p in (self.p_auto, self.p_rete, self.p_declare):
            InsumoDefinicion.objects.create(proceso=p, nombre="Archivo CXC", nombre_campo="cxc_csv",
                                            tipo="CARGUE", extensiones=".csv", orden=9)

    def _motor_falso(self, ejecucion):
        from unittest.mock import MagicMock
        m = MagicMock()

        def _ejecutar(archivos, filtros):
            ejecucion.estado = "COMPLETADO"
            ejecucion.registros_nuevos = 3
            ejecucion.registros_duplicados = 1
            ejecucion.save()
        m.ejecutar.side_effect = _ejecutar
        return m

    @override_settings(SOFINET_ESTRELLA_HOST="", SOFINET_COPACABANA_HOST="")
    def test_sin_configuracion_no_hace_nada(self):
        from django.core.management import call_command
        call_command("actualizar_sofinet")
        self.assertEqual(Ejecucion.objects.count(), 0)

    @override_settings(SOFINET_ESTRELLA_HOST="estrella.integralv6.com",
                       SOFINET_ESTRELLA_USER="u", SOFINET_ESTRELLA_PASS="p",
                       SOFINET_COPACABANA_HOST="")
    def test_descarga_valida_ejecuta_los_tres_procesos_y_marca_automatico(self):
        from unittest.mock import patch
        from django.core.management import call_command
        with patch("etl.management.commands.actualizar_sofinet.SofinetBot") as MockBot, \
             patch("etl.management.commands.actualizar_sofinet.MotorETL", side_effect=self._motor_falso) as MockMotor:
            MockBot.return_value.descargar_cxc.return_value = b"CONSECUTIVO,ESTADO\n1,PAGADO\n" * 3
            call_command("actualizar_sofinet")

        self.assertEqual(MockBot.call_count, 1)  # un solo login/descarga sirve para los 3 procesos
        self.assertEqual(MockMotor.call_count, 3)
        ejecuciones = Ejecucion.objects.filter(proceso__municipio=self.estrella)
        self.assertEqual(ejecuciones.count(), 3)
        for ej in ejecuciones:
            self.assertTrue(ej.automatico)
            self.assertEqual(ej.usuario.username, "bot_sofinet")
            self.assertEqual(ej.estado, "COMPLETADO")
        bot_user = User.objects.get(username="bot_sofinet")
        self.assertFalse(bot_user.is_active)
        self.assertFalse(bot_user.has_usable_password())

    @override_settings(SOFINET_ESTRELLA_HOST="estrella.integralv6.com",
                       SOFINET_ESTRELLA_USER="u", SOFINET_ESTRELLA_PASS="p",
                       SOFINET_ALERTA_EMAIL="admin@example.com")
    def test_fallo_en_la_descarga_no_toca_datos_y_avisa(self):
        from unittest.mock import patch
        from django.core.management import call_command
        from etl.services.sofinet_bot import SofinetError
        with patch("etl.management.commands.actualizar_sofinet.SofinetBot") as MockBot:
            MockBot.return_value.descargar_cxc.side_effect = SofinetError("portal caído")
            call_command("actualizar_sofinet", municipio="ESTRELLA")

        self.assertEqual(Ejecucion.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ESTRELLA", mail.outbox[0].subject)

    @override_settings(SOFINET_ESTRELLA_HOST="estrella.integralv6.com",
                       SOFINET_ESTRELLA_USER="u", SOFINET_ESTRELLA_PASS="p",
                       SOFINET_ALERTA_EMAIL="admin@example.com")
    def test_fallo_del_motor_muestra_el_final_del_traceback_no_el_inicio(self):
        """La línea con la excepción real queda al final de un traceback largo: truncar
        desde el inicio (como hacía antes) la esconde siempre. Ver commit que lo corrigió."""
        from unittest.mock import MagicMock, patch
        from django.core.management import call_command

        relleno = "en la pila de llamadas\n" * 100  # > 1500 caracteres
        traceback_largo = relleno + "ValueError: ESTE ES EL ERROR REAL QUE IMPORTA"

        def _motor_con_error(ejecucion):
            m = MagicMock()

            def _ejecutar(archivos, filtros):
                ejecucion.estado = "ERROR"
                ejecucion.error_log = traceback_largo
                ejecucion.save()
            m.ejecutar.side_effect = _ejecutar
            return m

        with patch("etl.management.commands.actualizar_sofinet.SofinetBot") as MockBot, \
             patch("etl.management.commands.actualizar_sofinet.MotorETL", side_effect=_motor_con_error):
            MockBot.return_value.descargar_cxc.return_value = b"CONSECUTIVO,ESTADO\n1,PAGADO\n" * 3
            call_command("actualizar_sofinet", municipio="ESTRELLA")

        self.assertEqual(len(mail.outbox), 3)  # uno por cada proceso que falló
        cuerpo = mail.outbox[0].body
        self.assertIn("ValueError: ESTE ES EL ERROR REAL QUE IMPORTA", cuerpo)

    @override_settings(SOFINET_ESTRELLA_HOST="estrella.integralv6.com",
                       SOFINET_ESTRELLA_USER="u", SOFINET_ESTRELLA_PASS="p")
    def test_csv_invalido_no_ejecuta_nada(self):
        from unittest.mock import patch
        from django.core.management import call_command
        with patch("etl.management.commands.actualizar_sofinet.SofinetBot") as MockBot:
            MockBot.return_value.descargar_cxc.return_value = b"<html>login otra vez</html>"
            call_command("actualizar_sofinet", municipio="ESTRELLA")
        self.assertEqual(Ejecucion.objects.count(), 0)


class ProcesadorSabanetaTests(TestCase):
    def test_captura_los_dos_consecutivos(self):
        import pandas as pd
        from etl.services.sabaneta import ProcesadorSabaneta
        mun = Municipio.objects.create(codigo="SAB2", nombre="Sabaneta Test")
        dec = pd.DataFrame([{
            "Consecutivo 1": 1614, "Consecutivo 2": 159, "Nombre productor": "Grupo plenitud",
            "Nombre del establecimiento": "Grupo plenitud", "Tipo de documento": "NI",
            "Cedula/NIT propietario": "890919160", "Fecha de la visita": "2026-09-11",
            "1. Año": 2026, "2. Bimestre": "4 Julio/Agosto 2026", "3. Tipo de declaracion": "Normal",
            "No. Radicado": 157, "20. TOTAL A PAGAR": 382330, "Estado Pago": "Pago realizado",
            "Fecha Pago": "2026-09-25",
        }])
        proc = ProcesadorSabaneta("PUBLICIDAD_EXTERIOR", {"declaraciones": dec}, mun)
        df_enc, _ = proc.procesar()
        self.assertEqual(len(df_enc), 1)
        fila = df_enc.iloc[0]
        self.assertEqual(fila["consecutivo_cxc"], "159")  # sigue siendo la identidad CXC
        self.assertEqual(fila["datos_extra"]["consecutivo1"], "1614")

    def test_sin_columna_consecutivo1_no_rompe(self):
        """Si GOBS no trae esa columna, se sigue procesando (queda vacío, no explota)."""
        import pandas as pd
        from etl.services.sabaneta import ProcesadorSabaneta
        mun = Municipio.objects.create(codigo="SAB2B", nombre="Sabaneta Sin Consec1")
        dec = pd.DataFrame([{
            "Consecutivo 2": 159, "Nombre productor": "Grupo plenitud", "Estado Pago": "Pendiente",
            "20. TOTAL A PAGAR": 100,
        }])
        proc = ProcesadorSabaneta("PUBLICIDAD_EXTERIOR", {"declaraciones": dec}, mun)
        df_enc, _ = proc.procesar()
        self.assertEqual(df_enc.iloc[0]["datos_extra"]["consecutivo1"], "")


class ExportadorSabanetaTests(TestCase):
    def test_incluye_los_dos_consecutivos(self):
        from etl.services.exportador_sabaneta import HEADERS, build_rows
        mun = Municipio.objects.create(codigo="SAB3", nombre="Sabaneta Export Test")
        p = Proceso.objects.create(municipio=mun, codigo="PUBLICIDAD_EXTERIOR", nombre="Publicidad Exterior Visual")
        u = User.objects.create_user("sabexp", "sabexp@example.com", "Sabaneta#2026", municipio=mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=p, usuario=u)
        EncabezadoCXC.objects.create(
            proceso=p, ejecucion=ej, consecutivo_cxc="159", consecutivo_original="159",
            numero_documento="890919160", razon_social="Grupo plenitud",
            estado_pago="PAGO REALIZADO", total_a_pagar=382330,
            datos_extra={"consecutivo1": "1614", "nombre_establecimiento": "Grupo plenitud"})

        self.assertEqual(HEADERS[0], "Consecutivo 1")
        self.assertEqual(HEADERS[1], "Consecutivo 2")
        headers, filas = build_rows(p, {})
        self.assertEqual(filas[0][0], 1614)
        self.assertEqual(filas[0][1], 159)


class FechaExtraFilterTests(TestCase):
    def test_formatea_timestamp_a_dmy(self):
        from etl.templatetags.etl_extras import fecha_extra
        self.assertEqual(fecha_extra("2026-05-15 12:29:01.000"), "15/05/2026")

    def test_formatea_solo_fecha(self):
        from etl.templatetags.etl_extras import fecha_extra
        self.assertEqual(fecha_extra("2026-05-15"), "15/05/2026")

    def test_vacio_da_guion(self):
        from etl.templatetags.etl_extras import fecha_extra
        self.assertEqual(fecha_extra(""), "—")
        self.assertEqual(fecha_extra(None), "—")

    def test_texto_no_fecha_se_deja_igual(self):
        from etl.templatetags.etl_extras import fecha_extra
        self.assertEqual(fecha_extra("no es una fecha"), "no es una fecha")


class SabanetaDashboardFechasTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="SABANETA", nombre="Sabaneta Dashboard Test")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="PUBLICIDAD_EXTERIOR", nombre="Publicidad Exterior Visual")
        self.u = User.objects.create_user("sabdash", "sabdash@example.com", "Sabaneta#2026",
                                          municipio=self.mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=self.p, usuario=self.u)
        EncabezadoCXC.objects.create(
            proceso=self.p, ejecucion=ej, consecutivo_cxc="100", consecutivo_original="100",
            numero_documento="901", razon_social="Mayo SAS", estado_pago="PAGO REALIZADO",
            total_a_pagar=1000,
            datos_extra={"consecutivo1": "1140", "fecha_visita": "2026-05-15 12:29:01.000",
                        "fecha_pago": "2026-05-15 16:28:08.000"})
        EncabezadoCXC.objects.create(
            proceso=self.p, ejecucion=ej, consecutivo_cxc="90", consecutivo_original="90",
            numero_documento="800", razon_social="Enero SAS", estado_pago="PAGO REALIZADO",
            total_a_pagar=1000,
            datos_extra={"consecutivo1": "900", "fecha_visita": "2026-01-10 09:00:00.000",
                        "fecha_pago": "2026-01-12 10:00:00.000"})
        self.client.force_login(self.u)

    def test_las_fechas_se_muestran_formateadas_no_como_timestamp(self):
        html = self.client.get(reverse("dashboard", args=[self.p.id])).content.decode()
        self.assertIn("15/05/2026", html)
        self.assertNotIn("12:29:01", html)

    def test_filtro_fecha_visita_reduce_a_lo_que_esta_en_el_rango(self):
        r = self.client.get(reverse("dashboard", args=[self.p.id]),
                            {"sab_fvisita_desde": "2026-05-01", "sab_fvisita_hasta": "2026-05-31"})
        self.assertContains(r, "Mayo SAS")
        self.assertNotContains(r, "Enero SAS")

    def test_filtro_fecha_pago_reduce_a_lo_que_esta_en_el_rango(self):
        r = self.client.get(reverse("dashboard", args=[self.p.id]),
                            {"sab_fpago_desde": "2026-01-01", "sab_fpago_hasta": "2026-01-31"})
        self.assertContains(r, "Enero SAS")
        self.assertNotContains(r, "Mayo SAS")

    def test_sin_columna_detalle_ni_estado_cxc_ni_fecha_venc(self):
        html = self.client.get(reverse("dashboard", args=[self.p.id])).content.decode()
        self.assertNotIn("Fecha Venc.", html)
        self.assertNotIn(">Detalle<", html)


class MergeCxcTests(TestCase):
    """_merge_cxc (compartida solo por Estrella y Copacabana): cruce con el CSV de CXC."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="MERGECXC", nombre="Municipio Merge CXC")

    def _procesador(self, csv_texto):
        from io import StringIO
        from etl.services.base import ProcesadorBase
        return ProcesadorBase("CXC_AUTO", {"cxc_csv": StringIO(csv_texto)}, self.mun)

    def test_prioriza_cancelada_sobre_otro_estado_cuando_esta_duplicado(self):
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n100,ANULADA\n100,CANCELADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PENDIENTE DE PAGO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_cxc"], "CANCELADA")

    def test_prioriza_cancelada_sin_importar_el_orden_de_las_filas(self):
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n100,CANCELADA\n100,ANULADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PENDIENTE DE PAGO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_cxc"], "CANCELADA")

    def test_pendiente_de_pago_con_cxc_cancelada_pasa_a_pagadas_por_otros_bancos(self):
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n100,CANCELADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PENDIENTE DE PAGO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_pago"], "PAGADAS POR OTROS BANCOS")

    def test_pago_realizado_no_se_toca_aunque_el_cxc_este_cancelada(self):
        """Solo se reclasifican las PENDIENTE DE PAGO; un pago ya confirmado no cambia."""
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n100,CANCELADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PAGO REALIZADO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_pago"], "PAGO REALIZADO")

    def test_pendiente_con_cxc_anulada_no_cambia_el_estado_de_pago(self):
        """ANULADA no es CANCELADA: el pendiente de pago se deja tal como vino de GOBS."""
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n100,ANULADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PENDIENTE DE PAGO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_pago"], "PENDIENTE DE PAGO")
        self.assertEqual(dec.loc[0, "estado_cxc"], "ANULADA")

    def test_sin_fila_en_el_cxc_no_cambia_nada(self):
        import pandas as pd
        proc = self._procesador("CONSECUTIVO,ESTADO\n999,CANCELADA\n")
        dec = pd.DataFrame({"consecutivo_cxc": ["100"], "estado_pago": ["PENDIENTE DE PAGO"]})
        dec = proc._merge_cxc(dec)
        self.assertEqual(dec.loc[0, "estado_pago"], "PENDIENTE DE PAGO")
        self.assertEqual(dec.loc[0, "estado_cxc"], "")


class NormalizarPagoTests(TestCase):
    def test_pago_realizado_es_pagado(self):
        from etl.services.reporteria import normalizar_pago
        self.assertEqual(normalizar_pago("PAGO REALIZADO"), "PAGADO")
        self.assertEqual(normalizar_pago("✓ Pago realizado"), "PAGADO")

    def test_pagadas_por_otros_bancos_es_pagado(self):
        from etl.services.reporteria import normalizar_pago
        self.assertEqual(normalizar_pago("PAGADAS POR OTROS BANCOS"), "PAGADO")

    def test_pendiente_de_pago_es_pendiente(self):
        from etl.services.reporteria import normalizar_pago
        self.assertEqual(normalizar_pago("PENDIENTE DE PAGO"), "PENDIENTE")
        self.assertEqual(normalizar_pago(""), "PENDIENTE")
        self.assertEqual(normalizar_pago(None), "PENDIENTE")


class QEstadoPagoTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="QEP", nombre="Municipio Q Estado Pago")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        self.u = User.objects.create_user("qep", "qep@example.com", "Qep#2026", municipio=self.mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=self.p, usuario=self.u)
        _crear_encabezado(self.p, ej, "1", "PAGO REALIZADO", 100, "Directo SAS")
        _crear_encabezado(self.p, ej, "2", "PAGADAS POR OTROS BANCOS", 100, "Otro banco SAS")
        _crear_encabezado(self.p, ej, "3", "PENDIENTE DE PAGO", 100, "Debe SAS")
        self.client.force_login(self.u)

    def test_pagado_agrupa_pago_realizado_y_pagadas_por_otros_bancos(self):
        r = self.client.get(reverse("dashboard", args=[self.p.id]), {"estado_pago": "PAGADO"})
        self.assertContains(r, "Directo SAS")
        self.assertContains(r, "Otro banco SAS")
        self.assertNotContains(r, "Debe SAS")

    def test_valor_literal_sigue_buscando_tal_cual(self):
        r = self.client.get(reverse("dashboard", args=[self.p.id]), {"estado_pago": "OTROS BANCOS"})
        self.assertContains(r, "Otro banco SAS")
        self.assertNotContains(r, "Directo SAS")
        self.assertNotContains(r, "Debe SAS")

    def test_el_enlace_de_reporteria_pagado_usa_el_marcador_de_grupo(self):
        from etl.services import reporteria
        ctx = reporteria.calcular(self.mun, {"pago": "PAGADO"})
        self.assertIn("estado_pago=PAGADO", ctx["explorar"][0]["url"])


class CargueManualOpcionalTests(TestCase):
    """Copacabana: aunque el proceso use GOBS, se puede seguir subiendo el archivo a mano
    (para el mismo día, sin esperar la sincronización de GOBS de 24h)."""

    def _proceso(self, codigo_municipio):
        from etl.models import InsumoDefinicion
        mun = Municipio.objects.create(codigo=codigo_municipio, nombre=f"Municipio {codigo_municipio}")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        InsumoDefinicion.objects.create(proceso=p, nombre="Declaraciones", nombre_campo="declaraciones",
                                        tipo="CARGUE", extensiones=".xlsx", orden=1)
        InsumoDefinicion.objects.create(proceso=p, nombre="Actividades", nombre_campo="actividades",
                                        tipo="CARGUE", extensiones=".xlsx", orden=2)
        return p

    def test_copacabana_muestra_declaraciones_y_actividades_como_opcionales(self):
        from etl.forms import EjecutarProcesoForm
        p = self._proceso("COPACABANA")
        form = EjecutarProcesoForm(p)
        self.assertTrue(form.usa_gobs)
        self.assertTrue(form.permite_manual_con_gobs)
        self.assertIn("declaraciones", form.fields)
        self.assertIn("actividades", form.fields)
        self.assertFalse(form.fields["declaraciones"].required)
        self.assertFalse(form.fields["actividades"].required)
        # sigue pudiendo traer de GOBS por fecha
        self.assertIn("fecha_desde", form.fields)

    def test_estrella_no_muestra_cargue_manual_cuando_usa_gobs(self):
        from etl.forms import EjecutarProcesoForm
        p = self._proceso("ESTRELLA")
        form = EjecutarProcesoForm(p)
        self.assertTrue(form.usa_gobs)
        self.assertFalse(form.permite_manual_con_gobs)
        self.assertNotIn("declaraciones", form.fields)
        self.assertNotIn("actividades", form.fields)

    def test_copacabana_con_archivo_manual_reemplaza_gobs_en_esa_ejecucion(self):
        """El motor ya prioriza lo subido a mano sobre GOBS (_completar_desde_gobs);
        esta prueba fija ese contrato para que no se rompa sin darnos cuenta."""
        from etl.services.motor import MotorETL
        from unittest.mock import patch
        mun = Municipio.objects.create(codigo="COPACABANA", nombre="Copacabana Motor Test")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("copmot", "copmot@example.com", "Copacabana#2026", municipio=mun, rol="ADMIN")
        ej = Ejecucion.objects.create(proceso=p, usuario=u)
        motor = MotorETL(ej)
        with patch("etl.services.motor.gobs_pg.fuente_para", return_value="fuente-falsa"), \
             patch("etl.services.motor.gobs_pg.cargar", return_value=({"declaraciones": "DE_GOBS"}, {"declaraciones": 1, "datos_al": None})):
            resultado = motor._completar_desde_gobs({"declaraciones": "DEL_ARCHIVO_SUBIDO"}, {})
        self.assertEqual(resultado["declaraciones"], "DEL_ARCHIVO_SUBIDO")


class ActualizarGobsCommandTests(TestCase):
    def setUp(self):
        self.caldas = Municipio.objects.create(codigo="CALDAS", nombre="Caldas Test")
        self.p_auto = Proceso.objects.create(municipio=self.caldas, codigo="CXC_AUTO", nombre="Autorretención")
        self.p_rete = Proceso.objects.create(municipio=self.caldas, codigo="CXC_RETE", nombre="ReteICA")

    def _motor_falso(self, ejecucion):
        from unittest.mock import MagicMock
        m = MagicMock()

        def _ejecutar(archivos, filtros):
            ejecucion.estado = "COMPLETADO"
            ejecucion.registros_nuevos = 2
            ejecucion.registros_duplicados = 0
            ejecucion.save()
        m.ejecutar.side_effect = _ejecutar
        return m

    def test_sin_gobs_habilitado_no_hace_nada(self):
        from unittest.mock import patch
        from django.core.management import call_command
        with patch("etl.management.commands.actualizar_gobs.gobs_pg.habilitado", return_value=False):
            call_command("actualizar_gobs")
        self.assertEqual(Ejecucion.objects.count(), 0)

    def test_corre_solo_los_procesos_con_fuente_gobs_activa(self):
        from unittest.mock import patch
        from django.core.management import call_command
        with patch("etl.management.commands.actualizar_gobs.gobs_pg.habilitado", return_value=True), \
             patch("etl.management.commands.actualizar_gobs.gobs_pg.fuente_para",
                   side_effect=lambda cod, proc: "fuente-falsa" if proc == "CXC_AUTO" else None), \
             patch("etl.management.commands.actualizar_gobs.MotorETL", side_effect=self._motor_falso) as MockMotor:
            call_command("actualizar_gobs", municipio="CALDAS")

        self.assertEqual(MockMotor.call_count, 1)  # solo CXC_AUTO tenía fuente
        ejecuciones = Ejecucion.objects.filter(proceso__municipio=self.caldas)
        self.assertEqual(ejecuciones.count(), 1)
        ej = ejecuciones.first()
        self.assertEqual(ej.proceso.codigo, "CXC_AUTO")
        self.assertTrue(ej.automatico)
        self.assertEqual(ej.usuario.username, "bot_gobs")
        bot_user = User.objects.get(username="bot_gobs")
        self.assertFalse(bot_user.is_active)
        self.assertFalse(bot_user.has_usable_password())

    def test_omite_estrella_y_copacabana_por_defecto(self):
        """Esos dos ya se refrescan con actualizar_sofinet; no deben correr dos veces."""
        from etl.management.commands.actualizar_gobs import MUNICIPIOS_SIN_BOT_PROPIO
        self.assertNotIn("ESTRELLA", MUNICIPIOS_SIN_BOT_PROPIO)
        self.assertNotIn("COPACABANA", MUNICIPIOS_SIN_BOT_PROPIO)

    @override_settings(SOFINET_ALERTA_EMAIL="admin@example.com")
    def test_fallo_no_toca_datos_y_avisa(self):
        from unittest.mock import MagicMock, patch
        from django.core.management import call_command

        def _motor_con_error(ejecucion):
            m = MagicMock()

            def _ejecutar(archivos, filtros):
                ejecucion.estado = "ERROR"
                ejecucion.error_log = "boom"
                ejecucion.save()
            m.ejecutar.side_effect = _ejecutar
            return m

        with patch("etl.management.commands.actualizar_gobs.gobs_pg.habilitado", return_value=True), \
             patch("etl.management.commands.actualizar_gobs.gobs_pg.fuente_para", return_value="fuente-falsa"), \
             patch("etl.management.commands.actualizar_gobs.MotorETL", side_effect=_motor_con_error):
            call_command("actualizar_gobs", municipio="CALDAS")

        self.assertEqual(len(mail.outbox), 2)  # uno por cada proceso (CXC_AUTO y CXC_RETE)
        self.assertIn("CALDAS", mail.outbox[0].subject)
