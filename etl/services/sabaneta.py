"""
Procesador de Sabaneta — Publicidad Exterior Visual.

No genera conceptos ni detalle de CXC: la salida es un reporte plano de las declaraciones
de publicidad exterior visual pagadas, con las columnas de
MUNICIPIOS/SABANETA/INSUMOS/FIJOS/Publicidad exterior visual.xlsx (ver exportador_sabaneta).

Origen: GOBS alcaldia_de_sabaneta.uvw_f_declaracion_publicidad_exterior_visual__sabaneta
(o un Excel con las mismas columnas).
"""
import re
import unicodedata

import pandas as pd

from etl.services.base import ProcesadorBase


def _nk(s):
    """Clave comparable: sin tildes, mayúsculas y solo letras/números."""
    t = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def _limpio(v):
    if v is None or v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _texto_fecha(v):
    """'2026-05-13 17:29:58.979' como en el reporte de referencia."""
    ts = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"


def _entero_texto(v):
    """'2026.0' -> '2026'."""
    s = _limpio(v)
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except ValueError:
        return s


class ProcesadorSabaneta(ProcesadorBase):
    CONSEC_COL = "Consecutivo 2"

    def procesar(self):
        if self.proceso_codigo == "PUBLICIDAD_EXTERIOR":
            return self._publicidad()
        raise ValueError(f"Proceso desconocido para Sabaneta: {self.proceso_codigo}")

    @staticmethod
    def _c(df, *nombres):
        """Columna cuyo nombre empieza por alguno de `nombres` (ignora tildes y signos)."""
        for n in nombres:
            k = _nk(n)
            for c in df.columns:
                if _nk(c).startswith(k):
                    return c
        return None

    def _publicidad(self):
        dec = self._leer("declaraciones")
        c = self._c
        col = {
            "consec":   c(dec, "Consecutivo 2"),
            "prod":     c(dec, "Nombre productor"),
            "estab":    c(dec, "Nombre del establecimiento"),
            "tipodoc":  c(dec, "Tipo de documento"),
            "nit":      c(dec, "Cedula/NIT propietario"),
            "fvisita":  c(dec, "Fecha de la visita"),
            "ano":      c(dec, "1. Año"),
            "bim":      c(dec, "2. Bimestre"),
            "tipodec":  c(dec, "3. Tipo de declaracion"),
            "rad":      c(dec, "No. Radicado"),
            "total":    c(dec, "20. TOTAL A PAGAR"),
            "estado":   c(dec, "Estado Pago"),
            "fpago":    c(dec, "Fecha Pago"),
        }
        faltan = [k for k in ("consec", "estado", "total") if col[k] is None]
        if faltan:
            raise ValueError(f"Faltan columnas en las declaraciones de publicidad exterior: {faltan}. "
                             f"Columnas disponibles: {list(dec.columns)}")

        def g(fila, k):
            return fila[col[k]] if col[k] else None

        filas = []
        for _, f in dec.iterrows():
            consec = _entero_texto(g(f, "consec"))
            estado = _limpio(g(f, "estado")).replace("✓", "").strip()
            # El reporte solo incluye las declaraciones pagadas.
            if not consec or consec.lower() == "nan" or "PAGO REALIZADO" not in estado.upper():
                continue
            fvisita = pd.to_datetime(g(f, "fvisita"), errors="coerce")
            total = pd.to_numeric(g(f, "total"), errors="coerce")
            filas.append({
                "consecutivo_cxc": consec,
                "consecutivo_original": consec,
                "tipo_documento": _limpio(g(f, "tipodoc")),
                "numero_documento": _limpio(g(f, "nit")),
                "razon_social": _limpio(g(f, "prod")),
                "fecha_cobro": None if pd.isna(fvisita) else fvisita,
                "descripcion": f"PUBLICIDAD EXTERIOR VISUAL {_limpio(g(f, 'bim'))} Radicado No. {consec}".strip(),
                "total_a_pagar": None if pd.isna(total) else float(total),
                "estado_pago": estado,
                "estado_cxc": "",
                "datos_extra": {
                    "nombre_establecimiento": _limpio(g(f, "estab")),
                    "fecha_visita": _texto_fecha(g(f, "fvisita")),
                    "ano": _entero_texto(g(f, "ano")),
                    "bimestre": _limpio(g(f, "bim")),
                    "tipo_declaracion": _limpio(g(f, "tipodec")),
                    "radicado": _entero_texto(g(f, "rad")),
                    "fecha_pago": _texto_fecha(g(f, "fpago")),
                },
            })
        df_enc = pd.DataFrame(filas, columns=[
            "consecutivo_cxc", "consecutivo_original", "tipo_documento", "numero_documento",
            "razon_social", "fecha_cobro", "descripcion", "total_a_pagar", "estado_pago",
            "estado_cxc", "datos_extra"])
        return df_enc, self._empty_det()
