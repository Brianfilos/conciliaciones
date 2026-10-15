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


class LineaTxtTests(TestCase):
    """Bug real en producción: una dirección de Caldas traía un '|' suelto
    ("CR 52| # 29A 111 OF 314") y el export TXT (separador '|' sin escapar) corría
    código_banco/número_cuenta una posición para esa fila — se veía como si número_cuenta
    hubiera cambiado de "2" a otro valor, cuando en realidad todas las columnas
    posteriores a la dirección quedaban desplazadas."""

    def test_quita_pipes_sueltos_de_los_campos(self):
        from etl.views import _linea_txt
        linea = _linea_txt(["900", "CR 52| # 29A 111 OF 314", "1", "2"])
        self.assertEqual(linea, "900|CR 52  # 29A 111 OF 314|1|2")

    def test_mantiene_el_numero_de_columnas_aunque_haya_varios_pipes(self):
        from etl.views import _linea_txt
        linea = _linea_txt(["a", "b|c|d", "e"])
        self.assertEqual(linea.count("|"), 2)  # 3 campos -> 2 separadores, ni uno más

    def test_none_se_vuelve_cadena_vacia(self):
        from etl.views import _linea_txt
        self.assertEqual(_linea_txt(["x", None, "y"]), "x||y")


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


class FechaDesdeNoObligatoriaConArchivoManualTests(TestCase):
    """Bug real reportado: en un municipio con GOBS (Caldas), el usuario elegía "Cargar
    archivo manual", subía los dos archivos y le daba a "Ejecutar proceso" — y no pasaba
    nada ("le doy a Ejecutar proceso y no da"). Causa: "Declaraciones desde" seguía siendo
    obligatorio en el servidor sin importar el modo elegido en el formulario; el JS solo
    ocultaba el campo (arreglado aparte para que tampoco bloquee el envío en el navegador),
    pero Django igual rechazaba la petición al llegar vacía, recargando la página sin ningún
    aviso visible (el campo con el error volvía a quedar oculto). La fecha no se usa para
    nada cuando se sube un archivo: MotorETL._completar_desde_gobs prioriza el archivo
    sobre GOBS pase lo que pase."""

    def _proceso(self):
        from etl.models import InsumoDefinicion
        mun = Municipio.objects.create(codigo="CALDAS", nombre="Caldas Form Test")
        p = Proceso.objects.create(municipio=mun, codigo="CXC_AUTO", nombre="Autorretención")
        InsumoDefinicion.objects.create(proceso=p, nombre="Declaraciones", nombre_campo="declaraciones",
                                        tipo="CARGUE", extensiones=".xlsx", orden=1)
        InsumoDefinicion.objects.create(proceso=p, nombre="Actividades", nombre_campo="actividades",
                                        tipo="CARGUE", extensiones=".xlsx", orden=2)
        return p

    def _archivo(self, nombre="declaraciones.xlsx"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nombre, b"contenido-de-prueba",
                                  content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_con_archivo_manual_no_exige_fecha_desde(self):
        from etl.forms import EjecutarProcesoForm
        p = self._proceso()
        files = {"declaraciones": self._archivo(), "actividades": self._archivo("actividades.xlsx")}
        form = EjecutarProcesoForm(p, data={}, files=files)
        self.assertFalse(form.fields["fecha_desde"].required)
        self.assertTrue(form.is_valid(), form.errors)

    def test_sin_archivo_manual_fecha_desde_sigue_siendo_obligatoria(self):
        """Modo GOBS (sin subir nada): la fecha sigue haciendo falta, igual que antes."""
        from etl.forms import EjecutarProcesoForm
        p = self._proceso()
        form = EjecutarProcesoForm(p, data={}, files={})
        self.assertTrue(form.fields["fecha_desde"].required)
        self.assertFalse(form.is_valid())
        self.assertIn("fecha_desde", form.errors)


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


class ProcesadorEstrellaRegimenSimpleTests(TestCase):
    """Régimen Simple (RST), La Estrella: a diferencia de Auto/Rete/Declare, la fuente es
    el "Informe Detallado Pagos (giros) ICAC" de DIAN, que no trae consecutivo propio ni
    se cruza con GOBS — cada carga genera CXC nuevas (serie 908).

    Hallazgo clave verificado contra el archivo real de DIAN (GIROS ICAC TERRITORIALES -
    DETALLADO1.xlsx, 104 filas): "Impuesto - Actividad Gravada N" es el valor DECLARADO
    (anual/consolidado), casi siempre mucho mayor que lo que DIAN realmente giró al
    municipio en esa fila (columna "Pago Total ICAC") — la diferencia son retenciones,
    autorretenciones y pagos previos. Sumar ese impuesto declarado tal cual sobrefactura
    hasta 1000x en filas con retenciones grandes. Lo correcto es usarlo solo para repartir
    PROPORCIONALMENTE lo que sí giró DIAN entre INDUSTRIAL/COMERCIAL/SERVICIOS."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="ESTRRST", nombre="Estrella RST Test")
        self.proceso = Proceso.objects.create(municipio=self.mun, codigo="REGIMEN_SIMPLE",
                                              nombre="Régimen Simple (RST)")
        from muni.models import CIIUMunicipio
        CIIUMunicipio.objects.create(municipio=self.mun, codigo="4111", tipo="INDUSTRIAL")
        CIIUMunicipio.objects.create(municipio=self.mun, codigo="4711", tipo="COMERCIAL")
        CIIUMunicipio.objects.create(municipio=self.mun, codigo="6201", tipo="SERVICIOS")

    def _archivo(self, filas):
        """Arma un .xlsx con la misma forma que el informe real de DIAN: 4 filas de
        título/metadatos antes del encabezado (fila 5), igual que GIROS ICAC
        TERRITORIALES - DETALLADO.xlsx."""
        import tempfile
        import pandas as pd
        cols = ["Año Gravable", "Periodo del año (aplica para anticipos)", "Tipo documento",
                "Número de documento contribuyente que paga ICAC",
                "Nombre o Razón Social del Contribuyente", "Número formulario F2593",
                "Fecha pago realizado por contribuyente",
                "Pago Total ICAC para este municipio o distrito",
                "Intereses ICAC territorial", "Sanciones ICAC territorial",
                "Código CIIU - Actividad Gravada 1", "Impuesto - Actividad gravada 1",
                "Código CIIU - Actividad Gravada 2", "Impuesto - Actividad gravada 2",
                "Código CIIU - Actividad Gravada 3", "Impuesto - Actividad gravada 3"]
        df = pd.DataFrame(filas, columns=cols)
        tf = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tf.close()
        with pd.ExcelWriter(tf.name, engine="openpyxl") as xl:
            titulo = pd.DataFrame([[None] * len(cols)] * 4)
            titulo.to_excel(xl, index=False, header=False, startrow=0)
            df.to_excel(xl, index=False, startrow=4)
        self.addCleanup(lambda: __import__("os").remove(tf.name))
        return tf.name

    def _fila(self, **over):
        base = dict.fromkeys([
            "Año Gravable", "Periodo del año (aplica para anticipos)", "Tipo documento",
            "Número de documento contribuyente que paga ICAC",
            "Nombre o Razón Social del Contribuyente", "Número formulario F2593",
            "Fecha pago realizado por contribuyente",
            "Pago Total ICAC para este municipio o distrito",
            "Intereses ICAC territorial", "Sanciones ICAC territorial",
            "Código CIIU - Actividad Gravada 1", "Impuesto - Actividad gravada 1",
            "Código CIIU - Actividad Gravada 2", "Impuesto - Actividad gravada 2",
            "Código CIIU - Actividad Gravada 3", "Impuesto - Actividad gravada 3",
        ], 0)
        base.update({"Año Gravable": 2026, "Periodo del año (aplica para anticipos)": 1,
                     "Tipo documento": "NIT", "Fecha pago realizado por contribuyente": 20260613,
                     "Intereses ICAC territorial": 0, "Sanciones ICAC territorial": 0})
        base.update(over)
        return base

    def _procesar(self, filas):
        from etl.services.estrella import ProcesadorEstrella
        path = self._archivo(filas)
        p = ProcesadorEstrella("REGIMEN_SIMPLE", {"declaraciones": path}, self.mun)
        return p.procesar()

    def test_reparte_proporcionalmente_no_usa_el_impuesto_declarado_directo(self):
        """El caso real que casi se cuela: impuesto declarado (actividad 1) = 20.000.000
        pero DIAN solo giró 10.000 en este periodo. El concepto debe quedar en 10.000, no
        en 20.000.000 — si no, se sobrefactura al contribuyente."""
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900111222",
               "Nombre o Razón Social del Contribuyente": "EMPRESA UNO SAS",
               "Pago Total ICAC para este municipio o distrito": 10000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 20000000})]
        df_enc, df_det = self._procesar(filas)
        self.assertEqual(len(df_enc), 1)
        self.assertEqual(df_enc.iloc[0]["total_a_pagar"], 10000)
        self.assertEqual(len(df_det), 1)
        self.assertEqual(df_det.iloc[0]["codigo_concepto"], "HDA732")  # INDUSTRIAL
        self.assertEqual(df_det.iloc[0]["valor_total"], 10000)

    def test_suma_todas_las_actividades_no_solo_las_dos_primeras(self):
        """GIROS ICAC PENDIENTES.xlsx (la hoja de fórmulas de referencia) solo sumaba las
        actividades 1 y 2 al concepto — un contribuyente con actividad en el renglón 3
        perdía esa plata. Acá debe sumarse igual."""
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900333444",
               "Nombre o Razón Social del Contribuyente": "EMPRESA TRES SAS",
               "Pago Total ICAC para este municipio o distrito": 5000,
               "Código CIIU - Actividad Gravada 3": "6201", "Impuesto - Actividad gravada 3": 5000})]
        df_enc, df_det = self._procesar(filas)
        self.assertEqual(df_enc.iloc[0]["total_a_pagar"], 5000)
        self.assertEqual(df_det.iloc[0]["codigo_concepto"], "HDA734")  # SERVICIOS
        self.assertEqual(df_det.iloc[0]["valor_total"], 5000)

    def test_dos_actividades_de_distinto_tipo_se_reparten_proporcional(self):
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900555666",
               "Nombre o Razón Social del Contribuyente": "EMPRESA MIXTA SAS",
               "Pago Total ICAC para este municipio o distrito": 9000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 3000000,
               "Código CIIU - Actividad Gravada 2": "4711", "Impuesto - Actividad gravada 2": 6000000})]
        df_enc, df_det = self._procesar(filas)
        self.assertEqual(df_enc.iloc[0]["total_a_pagar"], 9000)
        conceptos = dict(zip(df_det["codigo_concepto"], df_det["valor_total"]))
        self.assertEqual(conceptos["HDA732"], 3000)   # INDUSTRIAL: 1/3 de 9000
        self.assertEqual(conceptos["HDA733"], 6000)   # COMERCIAL: 2/3 de 9000
        self.assertEqual(sum(conceptos.values()), 9000)

    def test_intereses_y_sanciones_son_conceptos_aparte_y_entran_al_total(self):
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900777888",
               "Nombre o Razón Social del Contribuyente": "EMPRESA CUATRO SAS",
               "Pago Total ICAC para este municipio o distrito": 13000,
               "Intereses ICAC territorial": 1000, "Sanciones ICAC territorial": 2000,
               "Código CIIU - Actividad Gravada 1": "6201", "Impuesto - Actividad gravada 1": 500000})]
        df_enc, df_det = self._procesar(filas)
        conceptos = dict(zip(df_det["codigo_concepto"], df_det["valor_total"]))
        self.assertEqual(conceptos["IntICOM"], 1000)
        self.assertEqual(conceptos["HD22"], 2000)
        self.assertEqual(conceptos["HDA734"], 10000)  # ICA neto = 13000 - 1000 - 2000
        self.assertEqual(df_enc.iloc[0]["total_a_pagar"], 13000)

    def test_sobretasa_nunca_genera_un_concepto(self):
        """No existe ninguna columna de sobretasa en lo que se lee — por diseño, nunca
        puede aparecer un concepto que no sea uno de los 5 reales."""
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900999000",
               "Nombre o Razón Social del Contribuyente": "EMPRESA CINCO SAS",
               "Pago Total ICAC para este municipio o distrito": 7000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 7000})]
        _, df_det = self._procesar(filas)
        self.assertTrue(set(df_det["codigo_concepto"]) <= {"HDA732", "HDA733", "HDA734", "IntICOM", "HD22"})

    def test_filas_sin_numero_de_documento_se_descartan(self):
        """DIAN a veces agrega una nota al final del reporte que no es una declaración."""
        filas = [
            self._fila(**{"Número de documento contribuyente que paga ICAC": "900111000",
                          "Nombre o Razón Social del Contribuyente": "EMPRESA SEIS SAS",
                          "Pago Total ICAC para este municipio o distrito": 1000,
                          "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000}),
            self._fila(**{"Año Gravable": "NO HUBO AJUSTE DE TRANSFERENCIAS",
                          "Número de documento contribuyente que paga ICAC": None}),
        ]
        df_enc, _ = self._procesar(filas)
        self.assertEqual(len(df_enc), 1)

    def test_fecha_formato_aaaammdd_se_interpreta_bien(self):
        import datetime
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900222111",
               "Nombre o Razón Social del Contribuyente": "EMPRESA SIETE SAS",
               "Fecha pago realizado por contribuyente": 20260613,
               "Pago Total ICAC para este municipio o distrito": 1000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000})]
        df_enc, _ = self._procesar(filas)
        self.assertEqual(df_enc.iloc[0]["fecha_cobro"].date(), datetime.date(2026, 6, 13))

    def test_estado_pago_normaliza_a_pagado(self):
        """DIAN ya giró esa plata antes de que exista el reporte: se carga como pagada."""
        from etl.services.reporteria import normalizar_pago
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900444111",
               "Nombre o Razón Social del Contribuyente": "EMPRESA OCHO SAS",
               "Pago Total ICAC para este municipio o distrito": 1000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000})]
        df_enc, _ = self._procesar(filas)
        self.assertEqual(normalizar_pago(df_enc.iloc[0]["estado_pago"]), "PAGADO")

    def test_consecutivo_arranca_en_9080000001_si_no_hay_nada_previo(self):
        """Bug real encontrado al probar: sin ningún 908 previo (ni en la base ni en el
        CXC externo), el primer consecutivo debía ser 9080000001, no 0000000001 — hay que
        partir del piso de la serie, no de cero."""
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900123123",
               "Nombre o Razón Social del Contribuyente": "EMPRESA ONCE SAS",
               "Pago Total ICAC para este municipio o distrito": 1000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000})]
        df_enc, _ = self._procesar(filas)
        self.assertEqual(df_enc.iloc[0]["consecutivo_cxc"], "9080000001")

    def test_consecutivo_continua_desde_el_mayor_908_del_cxc_externo(self):
        """Aunque nunca hayamos cargado nada de Régimen Simple nosotros mismos, si el CXC
        de Auto/Rete/Declare ya trae un 908 digitado a mano en el sistema externo, la
        numeración nueva debe continuar después de ese, no chocar con él."""
        import tempfile, os
        from etl.models import Proceso as ProcesoModel, InsumoDefinicion, InsumoEjecucion, Ejecucion
        from django.core.files.base import ContentFile
        p_auto = ProcesoModel.objects.create(municipio=self.mun, codigo="CXC_AUTO", nombre="Autorretención")
        insumo_def = InsumoDefinicion.objects.create(
            proceso=p_auto, nombre="Archivo CXC", nombre_campo="cxc_csv", extensiones=".csv")
        u = get_user_model().objects.create_user("rstcons", "rstcons@example.com", "Rst#2026", municipio=self.mun)
        ej = Ejecucion.objects.create(proceso=p_auto, usuario=u)
        csv_contenido = "CONSECUTIVO,ESTADO\n9080009999,ACTIVA\n9040000001,ACTIVA\n"
        InsumoEjecucion.objects.create(
            ejecucion=ej, insumo_def=insumo_def,
            archivo=ContentFile(csv_contenido.encode("latin1"), name="cxc.csv"),
            nombre_original="cxc.csv")

        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900666333",
               "Nombre o Razón Social del Contribuyente": "EMPRESA NUEVE SAS",
               "Pago Total ICAC para este municipio o distrito": 1000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000})]
        df_enc, _ = self._procesar(filas)
        self.assertEqual(df_enc.iloc[0]["consecutivo_cxc"], "9080010000")

    def test_segunda_carga_nunca_reutiliza_ni_actualiza_un_consecutivo_ya_guardado(self):
        """Respuesta confirmada: siempre consecutivo nuevo, nunca se actualiza uno
        existente aunque el documento/periodo se repita (dos giros reales distintos).
        Pasa por MotorETL completo, que despacha el procesador por código de municipio
        ('ESTRELLA' literal, ver motor.py), así que usa su propio municipio/proceso."""
        from etl.services.motor import MotorETL
        from etl.models import Ejecucion, EncabezadoCXC
        mun = Municipio.objects.create(codigo="ESTRELLA", nombre="La Estrella (test motor)")
        proceso = Proceso.objects.create(municipio=mun, codigo="REGIMEN_SIMPLE", nombre="Régimen Simple (RST)")
        u = get_user_model().objects.create_user("rstdup", "rstdup@example.com", "Rst#2026", municipio=mun)
        filas = [self._fila(
            **{"Número de documento contribuyente que paga ICAC": "900888222",
               "Nombre o Razón Social del Contribuyente": "EMPRESA DIEZ SAS",
               "Pago Total ICAC para este municipio o distrito": 1000,
               "Código CIIU - Actividad Gravada 1": "4111", "Impuesto - Actividad gravada 1": 1000})]
        path = self._archivo(filas)
        archivos = {"declaraciones": path}
        ej1 = Ejecucion.objects.create(proceso=proceso, usuario=u)
        MotorETL(ej1).ejecutar(archivos, {})
        ej2 = Ejecucion.objects.create(proceso=proceso, usuario=u)
        MotorETL(ej2).ejecutar(archivos, {})
        self.assertEqual(ej1.estado, "COMPLETADO", ej1.error_log)
        self.assertEqual(ej2.estado, "COMPLETADO", ej2.error_log)
        registros = EncabezadoCXC.objects.filter(proceso=proceso)
        self.assertEqual(registros.count(), 2)
        self.assertEqual(len(set(registros.values_list("consecutivo_cxc", flat=True))), 2)


class ProcesadorEnvigadoColumnasGobsTests(TestCase):
    """El NIT/nombre de la declaración de Envigado debe ser el del ESTABLECIMIENTO/
    contribuyente ("CedulaNIT del productor"/"Nombre del productor", que llegan del cruce
    con establecimientos en gobs_pg._cruzar_establecimientos), no el de quien firma el
    formulario ("24./25. ... Representante Legal"). Bug real en producción: para una
    empresa (TRAVESA SAS, NIT 800205579) el sistema mostró en su lugar la cédula y el
    nombre del representante legal (72001830, JOSE JAVIER HERNANDEZ JIMENEZ) — una
    persona distinta. Antes de eso, un intento de fix previo rompía _rete() con un
    AttributeError porque buscaba columnas que nunca existieron con ese nombre exacto
    ("Cedula/NIT propietario"/"Nombre productor"; los reales en GOBS llevan otra
    redacción). Se prueban ambos esquemas y, sobre todo, que cuando los dos coexisten
    gana el del establecimiento."""

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

    def test_usa_el_nit_del_establecimiento_aunque_tambien_venga_el_representante_legal(self):
        """Caso real: las dos fuentes están presentes a la vez (es lo normal, GOBS siempre
        cruza establecimientos) y debe ganar la del establecimiento, no el representante."""
        import pandas as pd
        from etl.services.envigado import ProcesadorEnvigado
        dec = pd.DataFrame([self._fila_base(**{
            "CedulaNIT del productor": "800205579", "Nombre del productor": "TRAVESA SAS",
            "25. No documento de identidad": "72001830",
            "24. Nombre del Contribuyente o Representante Legal": "JOSE JAVIER HERNANDEZ JIMENEZ",
        })])
        proc = ProcesadorEnvigado("CXC_RETE", {"declaraciones": dec}, self.mun)
        df_enc, _ = proc._rete()
        self.assertEqual(df_enc.iloc[0]["numero_documento"], "800205579")
        self.assertEqual(df_enc.iloc[0]["razon_social"], "TRAVESA SAS")

    def test_usa_el_representante_legal_si_no_hay_dato_del_establecimiento(self):
        """Respaldo: si el cruce con establecimientos no trajo nada para esa fila, es
        mejor mostrar el representante legal que dejar el campo vacío."""
        import pandas as pd
        from etl.services.envigado import ProcesadorEnvigado
        dec = pd.DataFrame([self._fila_base(**{
            "25. No documento de identidad": "72001830",
            "24. Nombre del Contribuyente o Representante Legal": "JOSE JAVIER HERNANDEZ JIMENEZ",
        })])
        proc = ProcesadorEnvigado("CXC_RETE", {"declaraciones": dec}, self.mun)
        df_enc, _ = proc._rete()
        self.assertEqual(df_enc.iloc[0]["numero_documento"], "72001830")
        self.assertEqual(df_enc.iloc[0]["razon_social"], "JOSE JAVIER HERNANDEZ JIMENEZ")

    def test_esquema_viejo_de_excel_sigue_funcionando_como_ultimo_respaldo(self):
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

    def test_consulta_gobs_por_consecutivo_no_por_rango_de_fechas(self):
        """Bug real reportado: en Caldas, exportar 'Pagadas' sin filtro de año traía de
        GOBS TODO el rango de fechas de lo cargado (puede ser años de historia) para
        filtrar después en Python — en producción eso se quedaba cargando sin terminar.
        Debe pedirle a GOBS solo los consecutivos exactos que hacen falta."""
        from unittest.mock import patch
        from etl.services import export_completo
        with patch("etl.services.export_completo.gobs_pg.fuente_para", return_value=self._fuente_falsa()), \
             patch("etl.services.export_completo.gobs_pg.cargar",
                   return_value=({"declaraciones": self._df_falso()}, {})) as mock_cargar:
            export_completo.generar(self.p, {}, None, incluir_duplicados=True)
        _, kwargs = mock_cargar.call_args
        self.assertIn("consecutivos", kwargs)
        self.assertEqual(set(kwargs["consecutivos"]), {"1", "2"})
        self.assertNotIn("desde", kwargs)
        self.assertNotIn("hasta", kwargs)


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


class UnicosRegimenSimpleNuncaDeduplicaTests(TestCase):
    """Régimen Simple (Estrella): cada fila es un giro de DIAN ya desembolsado, no un
    reintento/corrección de una declaración — dos giros del mismo contribuyente en el
    mismo mes son dos obligaciones reales distintas, no una duplicada. Si se agrupara
    como los demás procesos (documento + mes de fecha_cobro), se perdería plata real."""

    def setUp(self):
        self.mun = Municipio.objects.create(codigo="RSTDEDUP", nombre="Estrella RST Dedup Test")
        self.p = Proceso.objects.create(municipio=self.mun, codigo="REGIMEN_SIMPLE", nombre="Régimen Simple (RST)")
        u = User.objects.create_user("rstdedup", "rstdedup@example.com", "Rst#2026", municipio=self.mun)
        self.ej = Ejecucion.objects.create(proceso=self.p, usuario=u)

    def test_mismo_documento_mismo_mes_no_se_colapsa(self):
        from datetime import date
        from etl.services import unicos
        g1 = EncabezadoCXC.objects.create(proceso=self.p, ejecucion=self.ej, consecutivo_cxc="9080000001",
            consecutivo_original="9080000001", numero_documento="900111222", fecha_cobro=date(2026, 5, 10),
            estado_pago="PAGO REALIZADO", total_a_pagar=1000)
        g2 = EncabezadoCXC.objects.create(proceso=self.p, ejecucion=self.ej, consecutivo_cxc="9080000002",
            consecutivo_original="9080000002", numero_documento="900111222", fecha_cobro=date(2026, 5, 15),
            estado_pago="PAGO REALIZADO", total_a_pagar=2000)
        ids_u, ids_e, dup = unicos.calcular(self.p)
        self.assertEqual(set(ids_u), {g1.id, g2.id})
        self.assertEqual(ids_e, [])
        self.assertEqual(dup, {})


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
