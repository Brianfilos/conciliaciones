import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from muni.models import Municipio

User = get_user_model()


def _temporal_del_correo(msg):
    m = re.search(r"Contraseña temporal: (\S+)", msg.body)
    return m.group(1)


class RecuperacionTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="TEST", nombre="Municipio de Prueba")
        self.u = User.objects.create_user("ana", "ana@example.com", "ClaveVieja#2026", municipio=self.mun, rol="OPERADOR")

    def _pedir(self, email="ana@example.com"):
        return self.client.post(reverse("password_reset"), {"email": email})

    def test_envia_temporal_y_respuesta_generica(self):
        r = self._pedir()
        self.assertContains(r, "Si el correo está registrado")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@example.com"])
        self.assertIn("ana", mail.outbox[0].body)
        # versión HTML con el logo de GOBS incrustado
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("cid:logo-gobs", html)
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    def test_correo_desconocido_no_revela_nada(self):
        r = self._pedir("nadie@example.com")
        self.assertContains(r, "Si el correo está registrado")
        self.assertEqual(len(mail.outbox), 0)

    def test_usuario_inactivo_no_recibe(self):
        self.u.is_active = False
        self.u.save()
        self._pedir()
        self.assertEqual(len(mail.outbox), 0)

    def test_limite_de_reenvio(self):
        self._pedir()
        self._pedir()
        self.assertEqual(len(mail.outbox), 1)

    def test_la_temporal_no_bloquea_la_clave_real(self):
        self._pedir()
        c = self.client_class()
        self.assertTrue(c.login(username="ana", password="ClaveVieja#2026"))

    def test_ingreso_con_temporal_obliga_a_cambiar(self):
        self._pedir()
        temporal = _temporal_del_correo(mail.outbox[0])
        r = self.client.post(reverse("login"), {"username": "ana", "password": temporal})
        self.assertEqual(r.status_code, 302)
        # cualquier página lleva al cambio de contraseña
        r = self.client.get(reverse("municipio_home"))
        self.assertRedirects(r, reverse("cambiar_password"), fetch_redirect_response=False)
        r = self.client.post(reverse("cambiar_password"), {"nueva1": "NuevaClave#9931", "nueva2": "NuevaClave#9931"})
        self.assertRedirects(r, reverse("municipio_home"), fetch_redirect_response=False)
        self.u.refresh_from_db()
        self.assertFalse(self.u.debe_cambiar_password)
        self.assertEqual(self.u.password_temporal, "")
        # la temporal ya no sirve y la nueva sí
        c2 = self.client_class()
        self.assertFalse(c2.login(username="ana", password=temporal))
        self.assertTrue(c2.login(username="ana", password="NuevaClave#9931"))

    def test_temporal_vencida(self):
        self._pedir()
        temporal = _temporal_del_correo(mail.outbox[0])
        self.u.refresh_from_db()
        self.u.password_temporal_expira = timezone.now() - timedelta(minutes=1)
        self.u.save()
        self.assertFalse(self.client_class().login(username="ana", password=temporal))

    def test_cambio_rechaza_clave_debil_y_no_coincidente(self):
        self._pedir()
        temporal = _temporal_del_correo(mail.outbox[0])
        self.client.post(reverse("login"), {"username": "ana", "password": temporal})
        r = self.client.post(reverse("cambiar_password"), {"nueva1": "12345678", "nueva2": "12345678"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("cambiar_password"), {"nueva1": "NuevaClave#9931", "nueva2": "OtraDistinta#1"})
        self.assertContains(r, "no coinciden")
        self.u.refresh_from_db()
        self.assertTrue(self.u.debe_cambiar_password)

    def test_cambio_voluntario_pide_la_actual(self):
        self.client.login(username="ana", password="ClaveVieja#2026")
        r = self.client.post(reverse("cambiar_password"),
                             {"actual": "incorrecta", "nueva1": "NuevaClave#9931", "nueva2": "NuevaClave#9931"})
        self.assertContains(r, "actual no es correcta")


class AdministracionUsuariosTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(codigo="TEST", nombre="Municipio de Prueba")
        self.root = User.objects.create_superuser("root", "root@example.com", "Root#Segura2026")
        self.op = User.objects.create_user("op", "op@example.com", "Operador#2026", municipio=self.mun, rol="OPERADOR")

    def test_solo_superusuario(self):
        self.client.login(username="op", password="Operador#2026")
        self.assertEqual(self.client.get(reverse("usuarios")).status_code, 403)
        self.assertEqual(self.client.post(reverse("usuario_nuevo"), {}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("usuarios")).status_code, 302)  # al login

    def test_crear_con_temporal_envia_correo(self):
        self.client.login(username="root", password="Root#Segura2026")
        r = self.client.post(reverse("usuario_nuevo"), {
            "username": "maria", "first_name": "María", "last_name": "Pérez", "email": "maria@example.com",
            "municipio": self.mun.pk, "rol": "ANALITICO", "is_active": "on", "modo_clave": "temporal"})
        self.assertRedirects(r, reverse("usuarios"), fetch_redirect_response=False)
        u = User.objects.get(username="maria")
        self.assertEqual((u.rol, u.municipio), ("ANALITICO", self.mun))
        self.assertTrue(u.debe_cambiar_password)
        self.assertFalse(u.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Tu acceso", mail.outbox[0].subject)
        # y puede entrar con la temporal
        temporal = _temporal_del_correo(mail.outbox[0])
        self.assertTrue(self.client_class().login(username="maria", password=temporal))

    def test_crear_con_clave_manual(self):
        self.client.login(username="root", password="Root#Segura2026")
        self.client.post(reverse("usuario_nuevo"), {
            "username": "luis", "email": "luis@example.com", "municipio": self.mun.pk, "rol": "OPERADOR",
            "is_active": "on", "modo_clave": "manual", "password": "ClaveInicial#5521", "forzar_cambio": "on"})
        u = User.objects.get(username="luis")
        self.assertTrue(u.check_password("ClaveInicial#5521"))
        self.assertTrue(u.debe_cambiar_password)
        self.assertEqual(len(mail.outbox), 0)

    def test_correo_duplicado_y_clave_debil(self):
        self.client.login(username="root", password="Root#Segura2026")
        r = self.client.post(reverse("usuario_nuevo"), {
            "username": "otro", "email": "OP@example.com", "municipio": self.mun.pk, "rol": "OPERADOR",
            "is_active": "on", "modo_clave": "manual", "password": "123"})
        self.assertContains(r, "Ya existe un usuario con ese correo")
        self.assertFalse(User.objects.filter(username="otro").exists())

    def test_no_puede_desactivarse_a_si_mismo(self):
        self.client.login(username="root", password="Root#Segura2026")
        self.client.post(reverse("usuario_accion", args=[self.root.pk]), {"accion": "desactivar"})
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_desactivar_activar_y_reenviar_clave(self):
        self.client.login(username="root", password="Root#Segura2026")
        self.client.post(reverse("usuario_accion", args=[self.op.pk]), {"accion": "desactivar"})
        self.op.refresh_from_db()
        self.assertFalse(self.op.is_active)
        self.assertFalse(self.client_class().login(username="op", password="Operador#2026"))
        self.client.post(reverse("usuario_accion", args=[self.op.pk]), {"accion": "activar"})
        self.client.post(reverse("usuario_accion", args=[self.op.pk]), {"accion": "temporal"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["op@example.com"])
