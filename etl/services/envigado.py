import re
import pandas as pd
from muni.models import CIIUMunicipio


class ProcesadorEnvigado:
    """
    Procesador ETL para Envigado.
    Diferencias clave vs Copa/Estrella:
    - Sin archivo CXC (no hay consecutivo_cxc con prefijo, se usa Consecutivo directo)
    - Sin campos nombre separados — solo NIT y Nombre productor
    - Conceptos propios: AUTO(8575/8576/8577/8578/8579), RETE(7377/7378/7379)
    - TXT con formato propio por proceso
    """

    CONCEPTO_AUTO = {
        "INDUSTRIAL": {"codigo": "8575", "descripcion": "AUTORRETENCIÓN INDUSTRIA Y COMERCIO - INDUSTRIAL"},
        "COMERCIAL":  {"codigo": "8576", "descripcion": "AUTORRETENCIÓN INDUSTRIA Y COMERCIO - COMERCIAL"},
        "SERVICIOS":  {"codigo": "8577", "descripcion": "AUTORRETENCION INDUSTRIA Y COMERCIO - SERVICIOS"},
    }
    CONCEPTO_SAN_AUTO  = {"codigo": "8578", "descripcion": "SANCIONES"}
    CONCEPTO_INT_AUTO  = {"codigo": "8579", "descripcion": "INTERESES"}

    CONCEPTO_RETE      = {"codigo": "7377", "descripcion": "Retención por industria y comercio"}
    CONCEPTO_SAN_RETE  = {"codigo": "7378", "descripcion": "Sanción RETEICA"}
    CONCEPTO_INT_RETE  = {"codigo": "7379", "descripcion": "interes de mora por RETEICA"}

    @staticmethod
    def _fmt_fecha(v):
        import pandas as pd
        try:
            ts = pd.to_datetime(v, errors="coerce")
            if ts is pd.NaT or pd.isna(ts):
                return ""
            return ts.strftime("%d-%m-%Y")
        except Exception:
            return str(v) if v else ""

    @staticmethod
    def _fmt_estado(v):
        return str(v or "").replace("✓ ", "").replace("✓", "").strip()

    def __init__(self, proceso_codigo, archivos, municipio):
        self.proceso_codigo = proceso_codigo
        self.archivos = archivos
        self.municipio = municipio

    def procesar(self):
        if self.proceso_codigo == "CXC_AUTO":
            return self._auto()
        elif self.proceso_codigo == "CXC_RETE":
            return self._rete()
        raise ValueError(f"Proceso desconocido para Envigado: {self.proceso_codigo}")

    def _tipo_ciiu(self, codigo):
        try:
            return CIIUMunicipio.objects.get(
                municipio=self.municipio,
                codigo=str(codigo).strip().zfill(4)
            ).tipo
        except Exception:
            return ""

    def _fecha(self, v):
        try:
            return pd.to_datetime(v, errors="coerce")
        except Exception:
            return None

    # ── AUTORRETENCIÓN ────────────────────────────────────────────────────────
    def _auto(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        act = pd.read_excel(self.archivos["actividades"])

        dec.columns = [c.strip() for c in dec.columns]
        act.columns = [c.strip() for c in act.columns]

        # Consecutivo como clave (sin transformación)
        consec_col = next((c for c in dec.columns if "Consecutivo" in c), None)
        if not consec_col:
            raise ValueError(f"No se encontró columna 'Consecutivo' en declaraciones. Columnas: {list(dec.columns)}")
        dec["consecutivo_cxc"] = dec[consec_col].astype(str).str.strip()
        dec["consecutivo_original"] = dec["consecutivo_cxc"]

        dec["fecha_cobro"]      = self._fecha(dec.get("Fecha Pago"))
        dec["fecha_vencimiento"] = self._fecha(dec.get("Fecha de presentación"))
        dec["total_a_pagar"]    = dec.get("23. TOTAL A PAGAR ($ COP)")
        dec["estado_pago"]      = dec.get("Estado Pago", pd.Series([""] * len(dec))).fillna("").astype(str).str.replace("✓ ", "", regex=False).str.replace("✓", "", regex=False).str.strip()
        dec["estado_cxc"]       = ""  # Sin archivo CXC

        periodo = dec.get("1. Periodo declarado", pd.Series([""] * len(dec))).fillna("")
        ano     = dec.get("1.1 Año", pd.Series([0] * len(dec))).fillna(0)
        consec  = dec["consecutivo_cxc"]
        dec["descripcion"] = "AUTORRETENCION " + periodo.astype(str) + " " + ano.astype(float).astype(int).astype(str) + " Radicado No. " + consec

        # Guardar sanciones e intereses en datos_extra para el TXT
        san_col = "20.1 Valor sanción ($ COP)"
        int_col = "21. Intereses por mora ($ COP)"
        dec["_san"] = dec.get(san_col, 0).fillna(0)
        dec["_int"] = dec.get(int_col, 0).fillna(0)

        enc_cols = ["consecutivo_cxc", "consecutivo_original", "numero_documento",
                    "razon_social", "fecha_cobro", "fecha_vencimiento",
                    "descripcion", "total_a_pagar", "estado_pago", "estado_cxc"]

        # Map NIT y Nombre
        dec["numero_documento"] = dec.get("Cédula/NIT propietario", dec.get("Cedula/NIT propietario", "")).astype(str)
        dec["razon_social"]     = dec.get("Nombre productor", "").fillna("").astype(str)

        df_enc = dec[[c for c in enc_cols if c in dec.columns]].copy()

        # datos_extra: periodo, año, sanciones, intereses para el TXT
        def make_extra(row):
            return {
                "periodo":      str(row.get("1. Periodo declarado", "")),
                "ano":          str(int(row.get("1.1 Año", 0) or 0)),
                "fecha_pres":   self._fmt_fecha(row.get("Fecha de presentación")),
                "fecha_pago":   self._fmt_fecha(row.get("Fecha Pago")),
                "san":          float(row.get("_san", 0) or 0),
                "intereses":    float(row.get("_int", 0) or 0),
            }
        df_enc["datos_extra"] = dec.apply(make_extra, axis=1)

        # ── DETALLES desde actividades ────────────────────────────────────────
        act_consec_col = next((c for c in act.columns if "Consecutivo" in c), None)
        if not act_consec_col:
            raise ValueError(f"No se encontró columna 'Consecutivo' en actividades. Columnas: {list(act.columns)}")
        act["consecutivo_cxc"] = act[act_consec_col].astype(str).str.strip()

        ciiu_col = (next((c for c in act.columns if "CIIU" in c.upper()), None) or
                   next((c for c in act.columns if "Código" in c and "establecimiento" not in c.lower()), None))
        val_col  = next((c for c in act.columns if "18." in c or "AUTORETENCION" in c.upper()), None)
        nom_col  = next((c for c in act.columns if "establecimiento" in c.lower() and "nombre" in c.lower()), None)

        if ciiu_col:
            act["codigo_ciiu"] = act[ciiu_col].astype(str).apply(
                lambda v: (lambda m: str(int(m.group(1))).zfill(4) if m else v.strip().zfill(4))(re.match(r"^(\d+)", str(v).strip()))
            )
        act["TIPO"] = act["codigo_ciiu"].apply(self._tipo_ciiu) if "codigo_ciiu" in act.columns else ""

        MAPA = {k: v["codigo"] for k, v in self.CONCEPTO_AUTO.items()}
        act["codigo_concepto"] = act["TIPO"].map(MAPA).fillna("")
        act["descripcion_concepto"] = act["TIPO"].map(
            {k: v["descripcion"] for k, v in self.CONCEPTO_AUTO.items()}
        ).fillna("")

        if val_col:
            act.rename(columns={val_col: "valor_unitario"}, inplace=True)
        act["valor_unitario"] = pd.to_numeric(act.get("valor_unitario", 0), errors="coerce").fillna(0)

        # Nombre del establecimiento para el TXT (diferente al nombre del declarante)
        act["nombre_establecimiento"] = act[nom_col].fillna("").astype(str) if nom_col else ""

        act_det = act.groupby(["consecutivo_cxc", "codigo_concepto", "descripcion_concepto"])["valor_unitario"].sum().reset_index()
        act_det["valor_total"] = act_det["valor_unitario"]
        act_det["centro_costo"] = act_det["descripcion_concepto"]  # descripción guardada en centro_costo
        act_det["cantidad"] = 1

        # Sanciones desde declaraciones
        rows_extra = []
        for _, row in dec.iterrows():
            cxc = row["consecutivo_cxc"]
            if row["_san"] and row["_san"] != 0:
                rows_extra.append({
                    "consecutivo_cxc": cxc,
                    "codigo_concepto": self.CONCEPTO_SAN_AUTO["codigo"],
                    "descripcion_concepto": self.CONCEPTO_SAN_AUTO["descripcion"],
                    "valor_unitario": float(row["_san"]),
                    "valor_total": float(row["_san"]),
                    "centro_costo": self.CONCEPTO_SAN_AUTO["descripcion"], "cantidad": 1,
                })
            if row["_int"] and row["_int"] != 0:
                rows_extra.append({
                    "consecutivo_cxc": cxc,
                    "codigo_concepto": self.CONCEPTO_INT_AUTO["codigo"],
                    "descripcion_concepto": self.CONCEPTO_INT_AUTO["descripcion"],
                    "valor_unitario": float(row["_int"]),
                    "valor_total": float(row["_int"]),
                    "centro_costo": self.CONCEPTO_INT_AUTO["descripcion"], "cantidad": 1,
                })
        df_det = pd.concat(
            [act_det[["consecutivo_cxc","codigo_concepto","descripcion_concepto","centro_costo","cantidad","valor_unitario","valor_total"]]] +
            ([pd.DataFrame(rows_extra)] if rows_extra else []),
            ignore_index=True
        )
        return df_enc, df_det

    # ── RETENCIÓN ICA ─────────────────────────────────────────────────────────
    def _rete(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        dec.columns = [c.strip() for c in dec.columns]

        consec_col = "Consecutivo 1" if "Consecutivo 1" in dec.columns else "Consecutivo"
        dec["consecutivo_cxc"]      = dec[consec_col].astype(str).str.strip()
        dec["consecutivo_original"] = dec["consecutivo_cxc"]
        dec["numero_documento"]     = dec.get("Cédula/NIT propietario", dec.get("Cedula/NIT propietario", "")).astype(str)
        dec["razon_social"]         = dec.get("Nombre productor", "").fillna("").astype(str)
        dec["fecha_cobro"]          = self._fecha(dec.get("Fecha Pago"))
        dec["fecha_vencimiento"]    = self._fecha(dec.get("Fecha de presentación"))
        dec["total_a_pagar"]        = dec.get("23. Total a pagar ($ COP)", dec.get("23. TOTAL A PAGAR ($ COP)"))
        dec["estado_pago"]          = dec.get("Estado Pago", pd.Series([""] * len(dec))).fillna("").astype(str).str.replace("✓ ", "", regex=False).str.replace("✓", "", regex=False).str.strip()
        dec["estado_cxc"]           = ""

        periodo = dec.get("1. Periodo declarado", pd.Series([""] * len(dec))).fillna("")
        ano     = dec.get("1.1 Año", pd.Series([0] * len(dec))).fillna(0)
        dec["descripcion"] = "RETENCION ICA " + periodo.astype(str) + " " + ano.astype(float).astype(int).astype(str) + " Radicado No. " + dec["consecutivo_cxc"]

        enc_cols = ["consecutivo_cxc", "consecutivo_original", "numero_documento",
                    "razon_social", "fecha_cobro", "fecha_vencimiento",
                    "descripcion", "total_a_pagar", "estado_pago", "estado_cxc"]
        df_enc = dec[[c for c in enc_cols if c in dec.columns]].copy()

        def make_extra(row):
            return {
                "periodo":    str(row.get("1. Periodo declarado", "")),
                "ano":        str(int(row.get("1.1 Año", 0) or 0)),
                "fecha_pres": self._fmt_fecha(row.get("Fecha de presentación")),
                "fecha_pago": self._fmt_fecha(row.get("Fecha Pago")),
                "total":      (lambda v: float(v) if v is not None and str(v) not in ("", "nan", "NaN") else 0)(row.get("23. Total a pagar ($ COP)", row.get("23. TOTAL A PAGAR ($ COP)", 0))),
            }
        df_enc["datos_extra"] = dec.apply(make_extra, axis=1)

        # ── DETALLES ──────────────────────────────────────────────────────────
        rete_col = next((c for c in dec.columns if "18." in c and "TOTAL" in c.upper() and "RETENCION" in c.upper()), None)
        san_col  = next((c for c in dec.columns if "19.1" in c or ("SANCION" in c.upper() and "VALOR" in c.upper())), None)
        int_col  = next((c for c in dec.columns if "20." in c and "INTERES" in c.upper()), None)
        tot_col  = next((c for c in dec.columns if "23." in c and "TOTAL" in c.upper()), None)

        rows = []
        for _, row in dec.iterrows():
            cxc = row["consecutivo_cxc"]
            # 7377 - Total retenciones (col 18)
            rete_val = float(row[rete_col] or 0) if rete_col and row.get(rete_col) else 0
            if rete_val:
                rows.append({
                    "consecutivo_cxc": cxc,
                    "codigo_concepto": self.CONCEPTO_RETE["codigo"],
                    "descripcion_concepto": self.CONCEPTO_RETE["descripcion"],
                    "valor_unitario": rete_val, "valor_total": rete_val,
                    "centro_costo": self.CONCEPTO_RETE["descripcion"], "cantidad": 1,
                })
            # 7378 - Sanciones
            if san_col and row.get(san_col):
                val = float(row[san_col] or 0)
                if val:
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": self.CONCEPTO_SAN_RETE["codigo"],
                        "descripcion_concepto": self.CONCEPTO_SAN_RETE["descripcion"],
                        "valor_unitario": val, "valor_total": val,
                        "centro_costo": self.CONCEPTO_SAN_RETE["descripcion"], "cantidad": 1,
                    })
            # 7379 - Intereses
            if int_col and row.get(int_col):
                val = float(row[int_col] or 0)
                if val:
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": self.CONCEPTO_INT_RETE["codigo"],
                        "descripcion_concepto": self.CONCEPTO_INT_RETE["descripcion"],
                        "valor_unitario": val, "valor_total": val,
                        "centro_costo": self.CONCEPTO_INT_RETE["descripcion"], "cantidad": 1,
                    })
            # Retención practicada en exceso (sin código):
            # exceso = col18 - col23 - sanciones - intereses  (cuando > 0)
            if rete_val and tot_col:
                total_pagar = float(row.get(tot_col) or 0)
                san_val = float(row.get(san_col) or 0) if san_col else 0
                int_val = float(row.get(int_col) or 0) if int_col else 0
                exceso = rete_val - total_pagar - san_val - int_val
                if exceso > 0.5:  # tolerancia de redondeo
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": "",
                        "descripcion_concepto": "RETENCION PRACTICADA EN EXCESO",
                        "valor_unitario": -exceso, "valor_total": -exceso,
                        "centro_costo": "RETENCION PRACTICADA EN EXCESO", "cantidad": 1,
                    })

        df_det = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["consecutivo_cxc","codigo_concepto","descripcion_concepto","centro_costo","cantidad","valor_unitario","valor_total"]
        )
        return df_enc, df_det
