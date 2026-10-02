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
    """Cualquier municipio: aunque el proceso use GOBS, se puede seguir subiendo el archivo
    a mano (para el mismo día, sin esperar la sincronización de GOBS de 24h)."""

    def _proceso(self, codigo_municipio):
        from etl.models import InsumoDefinicion
        mun = Municipio.objects.create(codigo=codigo_municipio, nombre=f"Municipio {codigo_municipio}")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        InsumoDefinicion.objects.create(proceso=p, nombre="Declaraciones", nombre_campo="declaraciones",
                                        tipo="CARGUE", extensiones=".xlsx", orden=1)
        InsumoDefinicion.objects.create(proceso=p, nombre="Actividades", nombre_campo="actividades",
                                        tipo="CARGUE", extensiones=".xlsx", orden=2)
        return p

    def _asegurar_opcional(self, codigo_municipio):
        from etl.forms import EjecutarProcesoForm
        p = self._proceso(codigo_municipio)
        form = EjecutarProcesoForm(p)
        self.assertTrue(form.usa_gobs)
        self.assertTrue(form.permite_manual_con_gobs)
        self.assertIn("declaraciones", form.fields)
        self.assertIn("actividades", form.fields)
        self.assertFalse(form.fields["declaraciones"].required)
        self.assertFalse(form.fields["actividades"].required)
        # sigue pudiendo traer de GOBS por fecha
        self.assertIn("fecha_desde", form.fields)

    def test_copacabana_muestra_declaraciones_y_actividades_como_opcionales(self):
        self._asegurar_opcional("COPACABANA")

    def test_estrella_tambien_muestra_declaraciones_y_actividades_como_opcionales(self):
        self._asegurar_opcional("ESTRELLA")

    def test_caldas_tambien_muestra_declaraciones_y_actividades_como_opcionales(self):
        self._asegurar_opcional("CALDAS")

    def test_sin_gobs_el_cargue_sigue_siendo_obligatorio_y_sin_nota_opcional(self):
        """Un municipio/proceso sin fuente GOBS no cambia: el archivo sigue siendo obligatorio."""
        from etl.forms import EjecutarProcesoForm
        p = self._proceso("SIN_GOBS_TEST")  # código que no existe en gobs_pg.FUENTES
        form = EjecutarProcesoForm(p)
        self.assertFalse(form.usa_gobs)
        self.assertFalse(form.permite_manual_con_gobs)
        self.assertTrue(form.fields["declaraciones"].required)
        self.assertNotIn("opcional", form.fields["declaraciones"].label)

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

    def test_valor_mas_largo_que_el_campo_se_recorta_en_vez_de_romper_el_lote(self):
        """Bug real en producción: GOBS trajo un nombre completo en la columna de
        documento de Envigado ('LINA MARIA GARCIA GRAJALES', 26 caracteres) y MySQL tumbó
        todo el lote con 'Datos demasiado largos para la columna numero_documento'
        (max_length=20). _guardar() debe recortar a ese límite en vez de dejar que
        cualquier fuente sucia (GOBS o un Excel) reviente toda la ejecución."""
        import pandas as pd
        from unittest.mock import MagicMock, patch
        from etl.services.motor import MotorETL
        mun = Municipio.objects.create(codigo="MOTORTRUNC", nombre="Motor Truncar Test")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("motortrunc", "motortrunc@example.com", "Trunc#2026", municipio=mun)
        ej = Ejecucion.objects.create(proceso=p, usuario=u)

        df_enc = pd.DataFrame([{
            "consecutivo_cxc": "1", "consecutivo_original": "1",
            "numero_documento": "LINA MARIA GARCIA GRAJALES",  # 26 caracteres, el campo acepta 20
            "razon_social": "LINA MARIA GARCIA GRAJALES",
            "fecha_cobro": "2026-05-01", "total_a_pagar": 100, "estado_pago": "PENDIENTE",
        }])
        df_det = pd.DataFrame(columns=["consecutivo_cxc", "codigo_concepto", "centro_costo",
                                       "cantidad", "valor_unitario", "valor_total"])
        processor_falso = MagicMock()
        processor_falso.procesar.return_value = (df_enc, df_det)

        motor = MotorETL(ej)
        with patch.object(motor, "_get_processor", return_value=processor_falso), \
             patch.object(motor, "_completar_desde_gobs", side_effect=lambda archivos, filtros: archivos):
            motor.ejecutar({}, {})

        ej.refresh_from_db()
        self.assertEqual(ej.estado, "COMPLETADO")
        enc = EncabezadoCXC.objects.get(proceso=p, consecutivo_cxc="1")
        self.assertEqual(enc.numero_documento, "LINA MARIA GARCIA GR")  # recortado a 20
        self.assertEqual(len(enc.numero_documento), 20)


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


class UnicosServiceTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="UNICOSTEST", nombre="Municipio Únicos")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("unicosuser", "unicos@example.com", "Unicos#2026", municipio=self.mun)
        self.ej = Ejecucion.objects.create(proceso=self.p, usuario=u)

    def _crear(self, consec, doc, fecha, estado, total=100):
        from datetime import date as _date
        return EncabezadoCXC.objects.create(
            proceso=self.p, ejecucion=self.ej, consecutivo_cxc=consec, consecutivo_original=consec,
            numero_documento=doc, fecha_cobro=_date.fromisoformat(fecha), estado_pago=estado,
            total_a_pagar=total)

    def test_una_sola_declaracion_por_vigencia_no_se_excluye(self):
        from etl.services import unicos
        e = self._crear("1", "900", "2026-05-15", "PENDIENTE DE PAGO")
        ids_u, ids_e, _ = unicos.calcular(self.p)
        self.assertEqual(ids_u, [e.id])
        self.assertEqual(ids_e, [])

    def test_duplicado_prioriza_la_pagada_aunque_no_sea_la_mas_reciente(self):
        from etl.services import unicos
        pagada = self._crear("1", "900", "2026-05-01", "PAGO REALIZADO")
        self._crear("2", "900", "2026-05-20", "PENDIENTE DE PAGO")  # más reciente, pero no pagada
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(ids_u, [pagada.id])
        self.assertEqual(dup[pagada.id], 1)

    def test_duplicado_sin_ninguna_pagada_prioriza_la_mas_reciente(self):
        from etl.services import unicos
        self._crear("1", "900", "2026-05-01", "PENDIENTE DE PAGO")
        reciente = self._crear("2", "900", "2026-05-20", "PENDIENTE DE PAGO")
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(ids_u, [reciente.id])
        self.assertEqual(dup[reciente.id], 1)

    def test_entre_varias_pagadas_toma_la_mas_reciente(self):
        from etl.services import unicos
        self._crear("1", "900", "2026-05-01", "PAGO REALIZADO")
        pagada_reciente = self._crear("2", "900", "2026-05-20", "PAGO REALIZADO")
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(ids_u, [pagada_reciente.id])

    def test_distinta_vigencia_no_se_agrupan(self):
        """Mismo documento, año distinto (clave_periodo usa fecha_cobro): cada uno es único."""
        from etl.services import unicos
        e1 = self._crear("1", "900", "2026-05-15", "PENDIENTE DE PAGO")
        e2 = self._crear("2", "900", "2025-05-15", "PENDIENTE DE PAGO")
        ids_u, ids_e, _ = unicos.calcular(self.p)
        self.assertEqual(set(ids_u), {e1.id, e2.id})
        self.assertEqual(ids_e, [])

    def test_sin_documento_no_se_fusiona_con_otros_sin_documento(self):
        from etl.services import unicos
        e1 = self._crear("1", "", "2026-05-15", "PENDIENTE DE PAGO")
        e2 = self._crear("2", "", "2026-05-15", "PENDIENTE DE PAGO")
        ids_u, ids_e, _ = unicos.calcular(self.p)
        self.assertEqual(set(ids_u), {e1.id, e2.id})

    def test_build_rows_cuenta_las_declaraciones_excluidas_por_fila(self):
        from etl.services import unicos
        self._crear("1", "900", "2026-05-01", "PENDIENTE DE PAGO")
        self._crear("2", "900", "2026-05-10", "PENDIENTE DE PAGO")
        pagada = self._crear("3", "900", "2026-05-20", "PAGO REALIZADO")
        headers, filas_unicas, filas_excluidas = unicos.build_rows(self.p)
        self.assertEqual(len(filas_unicas), 1)
        self.assertEqual(filas_unicas[0][0], pagada.consecutivo_cxc)
        self.assertEqual(filas_unicas[0][-1], 2)  # 2 excluidas se colapsaron en esta
        self.assertEqual(len(filas_excluidas), 2)


class ReporteUnicosViewTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="UNICOSVIEW", nombre="Municipio Únicos Vista")
        self.otro_mun = Municipio.objects.create(codigo="UNICOSOTRO", nombre="Otro Municipio")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        self.u = User.objects.create_user("unicosview", "unicosview@example.com", "Unicos#2026", municipio=self.mun)
        self.u_otro = User.objects.create_user("unicosotro", "unicosotro@example.com", "Unicos#2026", municipio=self.otro_mun)
        ej = Ejecucion.objects.create(proceso=self.p, usuario=self.u)
        EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="1", consecutivo_original="1",
                                     numero_documento="900", estado_pago="PAGO REALIZADO", total_a_pagar=100)

    def test_descarga_el_excel_de_unicos(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("reporteria_unicos", args=[self.p.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn(f"{self.mun.codigo}_CXC_AUTO_unicos.xlsx", r["Content-Disposition"])

    def test_usuario_de_otro_municipio_no_puede_descargar(self):
        self.client.force_login(self.u_otro)
        r = self.client.get(reverse("reporteria_unicos", args=[self.p.id]))
        self.assertEqual(r.status_code, 302)


class UnicosServiceCaldasEnvigadoTests(TestCase):
    """Caldas/Envigado agrupan la vigencia por año+bimestre (datos_extra), no por el mes
    de fecha_cobro como el resto — camino de clave_periodo que UnicosServiceTests no cubre."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="CALDAS", nombre="Caldas Únicos Test")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("caldasunicos", "caldasunicos@example.com", "Caldas#2026", municipio=self.mun)
        self.ej = Ejecucion.objects.create(proceso=self.p, usuario=u)

    def _crear(self, consec, doc, fecha, estado, ano, periodo, total=100):
        from datetime import date as _date
        return EncabezadoCXC.objects.create(
            proceso=self.p, ejecucion=self.ej, consecutivo_cxc=consec, consecutivo_original=consec,
            numero_documento=doc, fecha_cobro=_date.fromisoformat(fecha), estado_pago=estado,
            total_a_pagar=total, datos_extra={"ano": ano, "periodo": periodo})

    def test_agrupa_por_bimestre_no_por_mes_de_fecha(self):
        from etl.services import unicos
        pendiente = self._crear("1", "800999", "2026-03-05", "PENDIENTE DE PAGO", "2026", "2")
        pagada = self._crear("2", "800999", "2026-04-20", "PAGO REALIZADO", "2026", "2")  # mismo bimestre, mes distinto
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(ids_u, [pagada.id])
        self.assertEqual(ids_e, [pendiente.id])
        self.assertEqual(dup[pagada.id], 1)

    def test_distinto_bimestre_mismo_documento_no_se_fusiona(self):
        from etl.services import unicos
        bim2 = self._crear("1", "800999", "2026-04-20", "PAGO REALIZADO", "2026", "2")
        bim3 = self._crear("2", "800999", "2026-05-01", "PENDIENTE DE PAGO", "2026", "3")
        ids_u, ids_e, _ = unicos.calcular(self.p)
        self.assertEqual(set(ids_u), {bim2.id, bim3.id})
        self.assertEqual(ids_e, [])


class ReporteriaDeduplicaTests(TestCase):
    """calcular(): los KPIs y gráficos principales deben contar cada vigencia una sola vez,
    no una por cada reintento/corrección (ver services/unicos.py)."""

    def setUp(self):
        from datetime import date
        self.mun = Municipio.objects.create(codigo="REPDEDUP", nombre="Municipio Reporteria Dedup")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("repdedup", "repdedup@example.com", "Dedup#2026", municipio=self.mun)
        ej = Ejecucion.objects.create(proceso=self.p, usuario=u)
        # Misma vigencia (documento + mes de fecha_cobro), dos declaraciones: gana la pagada.
        EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="1", consecutivo_original="1",
            numero_documento="900111", fecha_cobro=date(2026, 5, 1), estado_pago="PENDIENTE DE PAGO",
            total_a_pagar=100)
        EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="2", consecutivo_original="2",
            numero_documento="900111", fecha_cobro=date(2026, 5, 20), estado_pago="PAGO REALIZADO",
            total_a_pagar=100)
        # Otro contribuyente, sin duplicado.
        EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="3", consecutivo_original="3",
            numero_documento="900222", fecha_cobro=date(2026, 6, 1), estado_pago="PENDIENTE DE PAGO",
            total_a_pagar=200)

    def test_total_bruto_cuenta_todo_pero_pagadas_pendientes_deduplican(self):
        from etl.services import reporteria
        d = reporteria.calcular(self.mun, {})
        k = d["kpi"]
        self.assertEqual(k["total"], 3)            # crudo: las 3 filas
        self.assertEqual(k["total_unico"], 2)       # deduplicado: 2 vigencias
        self.assertEqual(k["pagadas"], 1)           # la duplicada ganadora (pagada)
        self.assertEqual(k["pendientes"], 1)        # el otro contribuyente
        self.assertEqual(k["pagadas"] + k["pendientes"], k["total_unico"])

    def test_por_proceso_tambien_deduplicado(self):
        from etl.services import reporteria
        d = reporteria.calcular(self.mun, {})
        proc = next(p for p in d["procesos"] if p["id"] == self.p.id)
        self.assertEqual(proc["pagado"] + proc["pendiente"], 2)
        self.assertEqual(proc["unicos"], 2)
        self.assertEqual(proc["duplicadas"], 1)

    def test_mayores_pendientes_no_duplica_valor(self):
        """El contribuyente con el duplicado quedó pagado (no pendiente); el total pendiente
        que se ve en 'mayores saldos' debe ser solo el del otro contribuyente (200), no 300."""
        from etl.services import reporteria
        d = reporteria.calcular(self.mun, {})
        valores = [t["valor"] for t in d["top_pendientes"]]
        self.assertEqual(sum(valores), 200)

    def test_sin_cargar_en_cero_si_el_municipio_no_tiene_csv(self):
        """'Sin cargar en el sistema' solo tiene sentido donde hay un CSV de CXC con el que
        comparar (Estrella/Copacabana). Sin ese insumo, el campo 'cxc' cae en SIN_CARGAR por
        defecto para todos, así que no debe reportarse como si faltara cargar nada (bug real:
        el titular del tablero decía 'N ya se pagaron pero no aparecen en el sistema' en
        Envigado, que no tiene forma de cargar/controlar ese estado)."""
        from etl.services import reporteria
        d = reporteria.calcular(self.mun, {})
        k = d["kpi"]
        self.assertFalse(d["municipio"]["tiene_csv"])
        self.assertEqual(k["sin_cargar"], 0)
        self.assertEqual(k["sin_cargar_pagadas"], 0)
        self.assertEqual(k["en_sistema"], k["total_unico"])


class ProcesadorEnvigadoColumnasGobsTests(TestCase):
    """GOBS cambió la vista de Envigado: 'Cedula/NIT propietario'/'Nombre productor'
    desaparecieron y ahora el NIT/nombre del contribuyente vienen en
    '25. No documento de identidad'/'24. Nombre del Contribuyente o Representante Legal'.
    Esto rompía _rete() con un AttributeError ('str' object has no attribute 'fillna')
    porque dec.get(...) caía en el valor por defecto "" al no encontrar la columna vieja.
    Se prueban ambos esquemas de columnas (el nuevo de GOBS y el viejo de Excel) para no
    volver a romper ninguno de los dos."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="ENVCOLGOBS", nombre="Envigado Columnas Test")

    def _fila_base(self, **extra):
        fila = {
            "Consecutivo 1": "900", "Fecha de presentacion": "2026-05-10",
            "Fecha Pago": "2026-05-15", "Estado Pago": "Pago realizado",
            "1. Periodo declarado": "Bimestre 3", "1.1 Año": 2026,
            "23. Total a pagar": 50000,
        }
        fila.update(extra)
        return fila

    def test_esquema_nuevo_de_gobs(self):
        import pandas as pd
        from etl.services.envigado import ProcesadorEnvigado
        dec = pd.DataFrame([self._fila_base(**{
            "25. No documento de identidad": "900123456",
            "24. Nombre del Contribuyente o Representante Legal": "Empresa Nueva SAS",
        })])
        proc = ProcesadorEnvigado("CXC_RETE", {"declaraciones": dec}, self.mun)
        df_enc, _ = proc._rete()
        self.assertEqual(df_enc.iloc[0]["numero_documento"], "900123456")
        self.assertEqual(df_enc.iloc[0]["razon_social"], "Empresa Nueva SAS")

    def test_esquema_viejo_de_excel_sigue_funcionando(self):
        import pandas as pd
        from etl.services.envigado import ProcesadorEnvigado
        dec = pd.DataFrame([self._fila_base(**{
            "Cedula/NIT propietario": "900654321", "Nombre productor": "Empresa Vieja Ltda",
        })])
        proc = ProcesadorEnvigado("CXC_RETE", {"declaraciones": dec}, self.mun)
        df_enc, _ = proc._rete()
        self.assertEqual(df_enc.iloc[0]["numero_documento"], "900654321")
        self.assertEqual(df_enc.iloc[0]["razon_social"], "Empresa Vieja Ltda")


class ExportCompletoServiceTests(TestCase):
    def setUp(self):
        from datetime import date
        self.mun = Municipio.objects.create(codigo="EXPCOMPLETO", nombre="Municipio Export Completo")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        u = User.objects.create_user("expcompleto", "expcompleto@example.com", "Exp#2026", municipio=self.mun)
        ej = Ejecucion.objects.create(proceso=self.p, usuario=u)
        self.e1 = EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="9040001",
            consecutivo_original="1", numero_documento="900", fecha_cobro=date(2026, 5, 1),
            estado_pago="PAGO REALIZADO", total_a_pagar=100)
        self.e2 = EncabezadoCXC.objects.create(proceso=self.p, ejecucion=ej, consecutivo_cxc="9040002",
            consecutivo_original="2", numero_documento="901", fecha_cobro=date(2026, 5, 2),
            estado_pago="PENDIENTE DE PAGO", total_a_pagar=200)

    def test_columnas_disponibles_sin_fuente_gobs(self):
        from etl.services import export_completo
        self.assertEqual(export_completo.columnas_disponibles("EXPCOMPLETO", "CXC_AUTO"), [])

    def test_generar_sin_fuente_gobs_devuelve_vacio(self):
        from etl.services import export_completo
        headers, filas = export_completo.generar(self.p, {}, None, False)
        self.assertEqual(headers, [])
        self.assertEqual(filas, [])

    def _fuente_falsa(self):
        from etl.services.gobs_pg import Fuente
        return Fuente(schema="esq", declaraciones="vista", col_consecutivo="Consecutivo")

    def _df_falso(self):
        import pandas as pd
        return pd.DataFrame([
            {"Consecutivo": 1, "Nombre": "Ana", "Otro": "x"},
            {"Consecutivo": 2, "Nombre": "Beto", "Otro": "y"},
            {"Consecutivo": 999, "Nombre": "NoDebeSalir", "Otro": "z"},
        ])

    def test_generar_filtra_por_consecutivo_y_columnas_elegidas(self):
        from unittest.mock import patch
        from etl.services import export_completo
        with patch("etl.services.export_completo.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.cargar", return_value=({"declaraciones": self._df_falso()}, {})):
            headers, filas = export_completo.generar(self.p, {}, ["Nombre"], incluir_duplicados=True)
        self.assertEqual(headers, ["Nombre"])
        self.assertEqual(sorted(f[0] for f in filas), ["Ana", "Beto"])

    def test_generar_respeta_filtro_de_pago(self):
        from unittest.mock import patch
        from etl.services import export_completo
        with patch("etl.services.export_completo.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.cargar", return_value=({"declaraciones": self._df_falso()}, {})):
            headers, filas = export_completo.generar(
                self.p, {"pago": "PAGADO"}, ["Nombre"], incluir_duplicados=True)
        self.assertEqual([f[0] for f in filas], ["Ana"])

    def test_sin_columnas_elegidas_trae_todas(self):
        from unittest.mock import patch
        from etl.services import export_completo
        with patch("etl.services.export_completo.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.cargar", return_value=({"declaraciones": self._df_falso()}, {})):
            headers, filas = export_completo.generar(self.p, {}, None, incluir_duplicados=True)
        self.assertEqual(headers, ["Consecutivo", "Nombre", "Otro"])


class ExportarCompletoViewTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="EXPVISTA", nombre="Municipio Export Vista")
        self.otro_mun = Municipio.objects.create(codigo="EXPVISTAOTRO", nombre="Otro Municipio")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        self.u = User.objects.create_user("expvista", "expvista@example.com", "Exp#2026", municipio=self.mun)
        self.u_otro = User.objects.create_user("expvistaotro", "expvistaotro@example.com", "Exp#2026", municipio=self.otro_mun)

    def _fuente_falsa(self):
        from etl.services.gobs_pg import Fuente
        return Fuente(schema="esq", declaraciones="vista", col_consecutivo="Consecutivo")

    def test_sin_proceso_con_gobs_redirige_a_reporteria(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("reporteria_exportar_completo"))
        self.assertRedirects(r, reverse("reporteria"))

    def test_muestra_el_selector_de_columnas(self):
        from unittest.mock import patch
        with patch("etl.services.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.columnas", return_value=["Consecutivo", "Nombre"]):
            self.client.force_login(self.u)
            r = self.client.get(reverse("reporteria_exportar_completo"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Consecutivo")
        self.assertContains(r, "Nombre")

    def test_usuario_de_otro_municipio_no_puede_ver_el_selector(self):
        from unittest.mock import patch
        with patch("etl.services.gobs_pg.fuente_para", return_value=self._fuente_falsa()):
            self.client.force_login(self.u_otro)
            r = self.client.get(reverse("reporteria_exportar_completo") + f"?proceso={self.p.id}")
        # el proceso pedido no es de su municipio y tampoco tiene uno propio con GOBS: a reportería
        self.assertRedirects(r, reverse("reporteria"))

    def test_descargar_genera_el_excel(self):
        from unittest.mock import patch
        import pandas as pd
        df = pd.DataFrame([{"Consecutivo": 1, "Nombre": "Ana"}])
        with patch("etl.services.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.columnas", return_value=["Consecutivo", "Nombre"]), \
             patch("etl.services.export_completo.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.cargar", return_value=({"declaraciones": df}, {})):
            self.client.force_login(self.u)
            r = self.client.get(reverse("reporteria_exportar_completo"),
                                {"proceso": self.p.id, "descargar": "1", "col": ["Consecutivo", "Nombre"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("EXPVISTA_CXC_AUTO_completo.xlsx", r["Content-Disposition"])


class UnicosDeclareYPagueEsAnualTests(TestCase):
    """Declare y Pague es anual: dos reenvíos en meses distintos del mismo año gravable
    deben contarse como UNA sola vigencia, no dos (a diferencia de Auto/Rete)."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="DYPANUAL", nombre="Municipio Declare y Pague")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="DECLAREYPAGUE", nombre="Declare y Pague")
        u = User.objects.create_user("dypanual", "dypanual@example.com", "Dyp#2026", municipio=self.mun)
        self.ej = Ejecucion.objects.create(proceso=self.p, usuario=u)

    def _crear(self, consec, fecha, estado, total=100):
        from datetime import date as _date
        return EncabezadoCXC.objects.create(
            proceso=self.p, ejecucion=self.ej, consecutivo_cxc=consec, consecutivo_original=consec,
            numero_documento="900444555", fecha_cobro=_date.fromisoformat(fecha), estado_pago=estado,
            total_a_pagar=total)

    def test_dos_meses_distintos_mismo_ano_gravable_es_una_sola_vigencia(self):
        from etl.services import unicos
        marzo = self._crear("1", "2024-03-10", "PENDIENTE DE PAGO")
        agosto = self._crear("2", "2024-08-20", "PAGO REALIZADO")  # reenvío posterior, pagado: gana
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(ids_u, [agosto.id])
        self.assertEqual(ids_e, [marzo.id])
        self.assertEqual(dup[agosto.id], 1)

    def test_distinto_ano_gravable_si_se_cuenta_aparte(self):
        from etl.services import unicos
        e2024 = self._crear("1", "2024-03-10", "PENDIENTE DE PAGO")
        e2025 = self._crear("2", "2025-03-10", "PENDIENTE DE PAGO")
        ids_u, ids_e, _ = unicos.calcular(self.p)
        self.assertEqual(set(ids_u), {e2024.id, e2025.id})
        self.assertEqual(ids_e, [])

    def test_autorretencion_en_el_mismo_municipio_sigue_agrupando_por_mes(self):
        """Confirma que el cambio es específico de Declare y Pague, no global."""
        from etl.services import unicos
        p_auto = Proceso.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        from datetime import date
        marzo = EncabezadoCXC.objects.create(proceso=p_auto, ejecucion=self.ej, consecutivo_cxc="10",
            consecutivo_original="10", numero_documento="900444555", fecha_cobro=date(2024, 3, 10),
            estado_pago="PENDIENTE DE PAGO", total_a_pagar=100)
        agosto = EncabezadoCXC.objects.create(proceso=p_auto, ejecucion=self.ej, consecutivo_cxc="11",
            consecutivo_original="11", numero_documento="900444555", fecha_cobro=date(2024, 8, 20),
            estado_pago="PAGO REALIZADO", total_a_pagar=100)
        ids_u, ids_e, _ = unicos.calcular(p_auto)
        # meses distintos: siguen siendo dos vigencias separadas para Autorretención
        self.assertEqual(set(ids_u), {marzo.id, agosto.id})
        self.assertEqual(ids_e, [])


class AutoRefreshLoginTests(TestCase):
    """Respaldo del cron de las 5am: al loguearse, se dispara en segundo plano la
    actualización del municipio de quien entró — sin bloquear el login ni repetirse si
    ya se refrescó hace poco (ver etl/services/auto_refresh.py)."""

    def setUp(self):
        self.mun_caldas = Municipio.objects.create(codigo="CALDAS", nombre="Caldas")
        self.mun_estrella = Municipio.objects.create(codigo="ESTRELLA", nombre="La Estrella")
        self.p = Proceso.objects.create(municipio=self.mun_caldas, codigo="CXC_AUTO", nombre="Autorretención")

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_dispara_actualizar_gobs_para_municipio_sin_bot_propio(self):
        from unittest.mock import patch
        from etl.services import auto_refresh
        with patch("etl.services.auto_refresh.subprocess.Popen") as mock_popen:
            auto_refresh.disparar_para_municipio("CALDAS")
        self.assertEqual(mock_popen.call_count, 1)
        args = mock_popen.call_args[0][0]
        self.assertIn("actualizar_gobs", args)
        self.assertEqual(args[-2:], ["--municipio", "CALDAS"])

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_dispara_actualizar_sofinet_para_estrella_y_copacabana(self):
        from unittest.mock import patch
        from etl.services import auto_refresh
        with patch("etl.services.auto_refresh.subprocess.Popen") as mock_popen:
            auto_refresh.disparar_para_municipio("ESTRELLA")
        args = mock_popen.call_args[0][0]
        self.assertIn("actualizar_sofinet", args)

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_no_repite_si_ya_se_actualizo_hace_poco(self):
        from unittest.mock import patch
        from etl.services import auto_refresh
        u = get_user_model().objects.create_user("autorefresh1", "ar1@example.com", "Ar#2026", municipio=self.mun_caldas)
        Ejecucion.objects.create(proceso=self.p, usuario=u, automatico=True)
        with patch("etl.services.auto_refresh.subprocess.Popen") as mock_popen:
            auto_refresh.disparar_para_municipio("CALDAS")
        mock_popen.assert_not_called()

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_ejecucion_manual_vieja_no_cuenta_para_el_cooldown(self):
        """Solo las ejecuciones automáticas (cron/login) cuentan para el cooldown — si lo
        único reciente fue una carga manual, igual se dispara el respaldo."""
        from unittest.mock import patch
        from etl.services import auto_refresh
        u = get_user_model().objects.create_user("autorefresh2", "ar2@example.com", "Ar#2026", municipio=self.mun_caldas)
        Ejecucion.objects.create(proceso=self.p, usuario=u, automatico=False)
        with patch("etl.services.auto_refresh.subprocess.Popen") as mock_popen:
            auto_refresh.disparar_para_municipio("CALDAS")
        mock_popen.assert_called_once()

    @override_settings(LOGIN_REFRESH_ENABLED=False)
    def test_no_dispara_nada_si_esta_desactivado(self):
        from unittest.mock import patch
        from etl.services import auto_refresh
        with patch("etl.services.auto_refresh.subprocess.Popen") as mock_popen:
            auto_refresh.disparar_para_municipio("CALDAS")
        mock_popen.assert_not_called()

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_un_fallo_al_lanzar_el_proceso_no_se_propaga(self):
        """Un error acá (p.ej. permisos, disco lleno) nunca debe romper el login."""
        from unittest.mock import patch
        from etl.services import auto_refresh
        with patch("etl.services.auto_refresh.subprocess.Popen", side_effect=OSError("sin permiso")):
            auto_refresh.disparar_para_municipio("CALDAS")  # no debe lanzar

    @override_settings(LOGIN_REFRESH_ENABLED=True, LOGIN_REFRESH_COOLDOWN_MIN=30)
    def test_login_real_dispara_el_refresco_sin_romper_si_falla(self):
        """El login en sí: dispara el refresco de fondo y de todas formas deja entrar al
        usuario, aunque el disparo falle."""
        from unittest.mock import patch
        u = get_user_model().objects.create_user("autorefresh3", "ar3@example.com", "Ar#2026", municipio=self.mun_caldas)
        with patch("etl.services.auto_refresh.subprocess.Popen", side_effect=OSError("sin permiso")):
            resp = self.client.post(reverse("login"), {"username": "autorefresh3", "password": "Ar#2026"})
        self.assertEqual(resp.status_code, 302)  # login exitoso pese al fallo del disparo
