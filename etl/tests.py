from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from etl.models import DetalleCXC, EncabezadoCXC, Ejecucion, EnvioExportacion, Proceso
from muni.models import Municipio

User = get_user_model()


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
        u = self.user
        for p in (self.p1, self.p2):
            ej = Ejecucion.objects.create(proceso=p, usuario=u)
            _crear_encabezado(p, ej, "1001", "✓ PAGO REALIZADO", 1000, "Ana SAS")
            _crear_encabezado(p, ej, "1002", "PENDIENTE DE PAGO", 2000, "Beto SAS")
        self.url = reverse("exportar_correo", args=[self.p1.id])
        self.client.force_login(self.user)

    def _post(self, **extra):
        datos = {"destinatarios": "cliente@example.com", "formato": "excel", "tab": "encabezado", "filtros": ""}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_envia_excel_con_remitente_configurado(self):
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.from_email, "Brian Filos <brian.filos@gobs.com.co>")
        self.assertEqual(m.reply_to, ["brian.filos@gobs.com.co"])
        self.assertEqual(m.to, ["cliente@example.com"])
        self.assertEqual(len(m.attachments), 1)
        nombre, contenido, mime = m.attachments[0]
        self.assertTrue(nombre.endswith(".xlsx"))
        self.assertTrue(contenido.startswith(b"PK"))  # un .xlsx es un zip
        reg = EnvioExportacion.objects.get()
        self.assertTrue(reg.ok)
        self.assertEqual(reg.usuario, self.user)

    def test_el_adjunto_es_igual_a_la_descarga_con_los_mismos_filtros(self):
        filtros = "estado_pago=PENDIENTE"
        self._post(formato="csv", filtros=filtros)
        adjunto = _texto(mail.outbox[0].attachments[0][1])
        descarga = self.client.get(reverse("exportar", args=[self.p1.id]), {"format": "csv", "tab": "encabezado", "estado_pago": "PENDIENTE"})
        self.assertEqual(adjunto.strip(), _texto(descarga.content).strip())
        self.assertIn("Beto SAS", adjunto)
        self.assertNotIn("Ana SAS", adjunto)

    def test_varios_procesos_en_un_solo_correo(self):
        self._post(formato="csv", otros=[str(self.p2.id)])
        m = mail.outbox[0]
        self.assertEqual(len(m.attachments), 2)
        self.assertIn("Autorretención", m.body)
        self.assertIn("Retención ICA", m.body)

    def test_varios_destinatarios_y_mensaje(self):
        self._post(destinatarios="a@example.com; b@example.com  c@example.com", mensaje="Revisar por favor", asunto="Mi asunto")
        m = mail.outbox[0]
        self.assertEqual(m.to, ["a@example.com", "b@example.com", "c@example.com"])
        self.assertEqual(m.subject, "Mi asunto")
        self.assertIn("Revisar por favor", m.body)

    def test_correo_invalido_y_demasiados(self):
        self._post(destinatarios="no-es-un-correo")
        self.assertEqual(len(mail.outbox), 0)
        self._post(destinatarios=",".join(f"u{i}@example.com" for i in range(11)))
        self.assertEqual(len(mail.outbox), 0)

    def test_otro_municipio_no_puede_enviar(self):
        self.client.force_login(self.ajeno)
        self._post()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EnvioExportacion.objects.count(), 0)

    def test_no_se_pueden_adjuntar_procesos_de_otro_municipio(self):
        ajeno_p = Proceso.objects.create(municipio=self.otro_mun, codigo="CXC_AUTO", nombre="Ajeno")
        self._post(otros=[str(ajeno_p.id)])
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    @override_settings(EXPORT_MAX_ADJUNTOS_MB=0)
    def test_limite_de_tamano(self):
        self._post()
        self.assertEqual(len(mail.outbox), 0)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        self.assertEqual(self._post().status_code, 302)
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
                         {"destinatarios": "x@example.com", "formato": "csv", "tab": "encabezado", "filtros": ""})
        adjunto = _texto(mail.outbox[0].attachments[0][1])
        self.assertIn("Pagó SAS", adjunto)
        self.assertNotIn("Debe SAS", adjunto)


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
