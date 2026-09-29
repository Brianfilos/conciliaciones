"""
Bot que entra al portal SOFINET (V6, integralv6.com) de un municipio y descarga el reporte
4030 "Cuentas por cobrar en un rango de fechas" en CSV, tal como lo haría una persona a mano:
Cuentas por Cobrar -> Otros Reportes -> 4030 Reportes Cuentas x cobrar -> Valores separados por
caracteres -> Cuentas por cobrar en un rango de fechas -> 1/01/2022 hasta hoy -> Descargar.

No hay API: es el mismo portal web (ASP.NET WebForms + DevExpress), por eso se automatiza el
navegador con Playwright. Los selectores se verificaron contra el portal real de La Estrella
(2026-09-29): el login es un popup llamado "viewgrande" que abre otro popup para el módulo,
dentro del cual "menu" y "principal" son frames; "Otros Reportes" y "4030..." son <span> con
onclick (no <a>); el radio de rango de fechas dispara un __doPostBack que recarga el frame
"principal" completo (hay que volver a pedir el frame tras el click); el formulario del reporte
es DevExpress (ASPxComboBox/ASPxDateEdit), no HTML plano. El reporte tarda 45-70s en generarse
para el rango completo (2022-hoy), por eso el timeout de descarga es largo.

Si SOFINET cambia esa pantalla, este bot se rompe y hay que ajustar los selectores.
"""
from datetime import date


class SofinetError(Exception):
    """La descarga no se pudo completar (portal caído, credenciales, o pantalla distinta a la esperada)."""


def _fecha_dropdown(d: date) -> str:
    """SOFINET muestra las fechas como '1/01/2022' (día sin cero, mes con cero)."""
    return f"{d.day}/{d.month:02d}/{d.year}"


class SofinetBot:
    FECHA_INICIAL = date(2022, 1, 1)
    TIMEOUT_NAVEGACION = 30000
    TIMEOUT_DESCARGA = 150000  # el reporte completo (2022-hoy) tarda 45-70s en generarse

    def __init__(self, host, usuario, clave):
        self.host = host.rstrip("/")
        self.usuario = usuario
        self.clave = clave

    def descargar_cxc(self, hasta: date = None) -> bytes:
        """Devuelve el contenido del CSV. Lanza SofinetError si algo no salió como se esperaba."""
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        hasta = hasta or date.today()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    contexto_pagina = browser.new_page(accept_downloads=True)
                    principal = self._login(contexto_pagina)
                    cxc = self._abrir_cuentas_por_cobrar(contexto_pagina, principal)
                    principal_frame = self._ir_al_reporte_4030(cxc)
                    principal_frame = self._marcar_rango_de_fechas(cxc, principal_frame)
                    datos = self._configurar_y_descargar(cxc, principal_frame, hasta)
                finally:
                    browser.close()
        except PWTimeout as e:
            raise SofinetError(f"SOFINET ({self.host}) no respondió a tiempo: {e}") from e
        return datos

    # ── pasos ────────────────────────────────────────────────────────────────

    def _login(self, page):
        page.goto(f"https://{self.host}/login.aspx", timeout=self.TIMEOUT_NAVEGACION)
        page.fill("#txtLogin", self.usuario)
        page.fill("#txtContrasena", self.clave)
        try:
            with page.expect_popup(timeout=self.TIMEOUT_NAVEGACION) as popup_info:
                page.click("#btnEntrar")
        except Exception as e:
            raise SofinetError("SOFINET no abrió la ventana principal tras el login "
                               "(¿usuario/clave incorrectos?).") from e
        principal = popup_info.value
        principal.wait_for_load_state("networkidle", timeout=self.TIMEOUT_NAVEGACION)
        return principal

    def _abrir_cuentas_por_cobrar(self, page, principal):
        with page.context.expect_page(timeout=self.TIMEOUT_NAVEGACION) as popup2_info:
            principal.locator("span.FMenuTitle", has_text="Cuentas por Cobrar").click()
        cxc = popup2_info.value
        cxc.wait_for_load_state("networkidle", timeout=self.TIMEOUT_NAVEGACION)
        return cxc

    def _ir_al_reporte_4030(self, cxc):
        menu = cxc.frame(name="menu")
        if menu is None:
            raise SofinetError("No apareció el frame de menú dentro de Cuentas por Cobrar.")
        menu.click("span.tabComun:has-text('Otros Reportes')", timeout=self.TIMEOUT_NAVEGACION)
        cxc.wait_for_timeout(2500)
        try:
            menu.click("span.FMenu2:has-text('4030')", timeout=self.TIMEOUT_NAVEGACION)
        except Exception as e:
            raise SofinetError("No se encontró '4030 Reportes Cuentas x cobrar' en Otros Reportes "
                               "(¿cambió el menú?).") from e
        cxc.wait_for_timeout(2500)
        principal_frame = cxc.frame(name="principal")
        if principal_frame is None:
            raise SofinetError("No cargó la pantalla del reporte 4030.")
        return principal_frame

    def _marcar_rango_de_fechas(self, cxc, principal_frame):
        labels = principal_frame.eval_on_selector_all(
            "label", "els => els.map(e => ({for: e.htmlFor, text: e.textContent.trim()}))")
        exacto = next((l for l in labels if l["text"] == "Cuentas por cobrar en un rango de fechas"), None)
        if not exacto or not exacto["for"]:
            raise SofinetError("No se encontró la opción 'Cuentas por cobrar en un rango de fechas' "
                               "en la lista de reportes 4030.")
        principal_frame.click(f"#{exacto['for']}", timeout=self.TIMEOUT_NAVEGACION)
        # El radio dispara un __doPostBack que recarga TODO el frame: hay que volver a pedirlo
        cxc.wait_for_timeout(4000)
        principal_frame = cxc.frame(name="principal")
        if principal_frame is None or not principal_frame.query_selector("#cbFormatos_I"):
            raise SofinetError("El formulario del reporte no cargó los parámetros esperados "
                               "(tipo de export / fechas) tras marcar el rango de fechas.")
        return principal_frame

    def _configurar_y_descargar(self, cxc, principal_frame, hasta: date):
        # Tipo de exportación -> CSV
        principal_frame.click("#cbFormatos_B-1", timeout=self.TIMEOUT_NAVEGACION)
        cxc.wait_for_timeout(500)
        opciones = principal_frame.eval_on_selector_all(
            "td[id^='cbFormatos_DDD_L_LBI']", "els => els.map(e => ({id: e.id, text: e.textContent.trim()}))")
        csv_opt = next((o for o in opciones if "separados por" in o["text"].lower()), None)
        if not csv_opt:
            raise SofinetError("No se encontró la opción de exportar en CSV "
                               "('valores separados por caracteres') en el desplegable de formato.")
        principal_frame.click(f"#{csv_opt['id']}", timeout=self.TIMEOUT_NAVEGACION)
        cxc.wait_for_timeout(500)

        # Fechas: 1/01/2022 (fijo) hasta la fecha pedida
        principal_frame.fill("#param52_I", _fecha_dropdown(self.FECHA_INICIAL))
        principal_frame.press("#param52_I", "Tab")
        cxc.wait_for_timeout(300)
        principal_frame.fill("#param53_I", _fecha_dropdown(hasta))
        principal_frame.press("#param53_I", "Tab")
        cxc.wait_for_timeout(500)

        try:
            with cxc.expect_download(timeout=self.TIMEOUT_DESCARGA) as descarga_info:
                principal_frame.click("#btDescargar_B", timeout=self.TIMEOUT_NAVEGACION)
        except Exception as e:
            raise SofinetError("SOFINET no generó ninguna descarga (el reporte puede tardar hasta "
                               "2-3 minutos; si el portal está lento, este paso agota el tiempo).") from e
        descarga = descarga_info.value

        ruta = descarga.path()
        if not ruta:
            raise SofinetError("El portal no generó ningún archivo para descargar.")
        with open(ruta, "rb") as f:
            return f.read()


def validar_csv(contenido: bytes) -> str | None:
    """None si el CSV parece válido; si no, el motivo por el que se rechaza."""
    if not contenido or len(contenido) < 20:
        return "el archivo descargado está vacío"
    texto = contenido[:4096].decode("latin1", errors="ignore").upper()
    if "CONSECUTIVO" not in texto:
        return "el archivo no tiene la columna CONSECUTIVO esperada (¿cambió el reporte, o la sesión no quedó autenticada?)"
    if "<HTML" in texto or "LOGIN" in texto:
        return "el portal devolvió una página en vez del CSV (probable fallo de login)"
    return None
