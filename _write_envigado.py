import os
BASE = r"c:\Users\Brian\Desktop\app conciliaciones"

files = {}

# ── etl/services/envigado.py ──────────────────────────────────────────────────
files["etl/services/envigado.py"] = '''import pandas as pd
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
        dec["consecutivo_cxc"] = dec["Consecutivo"].astype(str).str.strip()
        dec["consecutivo_original"] = dec["consecutivo_cxc"]

        dec["fecha_cobro"]      = self._fecha(dec.get("Fecha Pago"))
        dec["fecha_vencimiento"] = self._fecha(dec.get("Fecha de presentación"))
        dec["total_a_pagar"]    = dec.get("23. TOTAL A PAGAR ($ COP)")
        dec["estado_pago"]      = dec.get("Estado Pago", "").fillna("").astype(str)
        dec["estado_cxc"]       = ""  # Sin archivo CXC

        periodo = dec.get("1. Periodo declarado", "").fillna("")
        ano     = dec.get("1.1 Año", 0).fillna(0)
        consec  = dec["consecutivo_cxc"]
        dec["descripcion"] = "AUTORRETENCION " + periodo.astype(str) + " " + ano.astype(int).astype(str) + " Radicado No. " + consec

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
                "fecha_pres":   str(row.get("Fecha de presentación", "")),
                "fecha_pago":   str(row.get("Fecha Pago", "")),
                "san":          float(row.get("_san", 0) or 0),
                "intereses":    float(row.get("_int", 0) or 0),
            }
        df_enc["datos_extra"] = dec.apply(make_extra, axis=1)

        # ── DETALLES desde actividades ────────────────────────────────────────
        act["consecutivo_cxc"] = act["Consecutivo"].astype(str).str.strip()

        ciiu_col = next((c for c in act.columns if "CIIU" in c.upper() or "Código" in c), None)
        val_col  = next((c for c in act.columns if "18." in c or "AUTORETENCION" in c.upper()), None)
        nom_col  = next((c for c in act.columns if "establecimiento" in c.lower() and "nombre" in c.lower()), None)

        if ciiu_col:
            act["codigo_ciiu"] = act[ciiu_col].astype(str).apply(
                lambda v: v.split(" - ", 1)[0].strip().zfill(4) if " - " in v else v.strip().zfill(4)
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
        act_det["centro_costo"] = ""
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
                    "centro_costo": "", "cantidad": 1,
                })
            if row["_int"] and row["_int"] != 0:
                rows_extra.append({
                    "consecutivo_cxc": cxc,
                    "codigo_concepto": self.CONCEPTO_INT_AUTO["codigo"],
                    "descripcion_concepto": self.CONCEPTO_INT_AUTO["descripcion"],
                    "valor_unitario": float(row["_int"]),
                    "valor_total": float(row["_int"]),
                    "centro_costo": "", "cantidad": 1,
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
        dec["estado_pago"]          = dec.get("Estado Pago", "").fillna("").astype(str)
        dec["estado_cxc"]           = ""

        periodo = dec.get("1. Periodo declarado", "").fillna("")
        ano     = dec.get("1.1 Año", 0).fillna(0)
        dec["descripcion"] = "RETENCION ICA " + periodo.astype(str) + " " + ano.astype(int).astype(str) + " Radicado No. " + dec["consecutivo_cxc"]

        enc_cols = ["consecutivo_cxc", "consecutivo_original", "numero_documento",
                    "razon_social", "fecha_cobro", "fecha_vencimiento",
                    "descripcion", "total_a_pagar", "estado_pago", "estado_cxc"]
        df_enc = dec[[c for c in enc_cols if c in dec.columns]].copy()

        def make_extra(row):
            return {
                "periodo":    str(row.get("1. Periodo declarado", "")),
                "ano":        str(int(row.get("1.1 Año", 0) or 0)),
                "fecha_pres": str(row.get("Fecha de presentación", "")),
                "fecha_pago": str(row.get("Fecha Pago", "")),
                "total":      float(row.get("23. Total a pagar ($ COP)", row.get("23. TOTAL A PAGAR ($ COP)", 0)) or 0),
            }
        df_enc["datos_extra"] = dec.apply(make_extra, axis=1)

        # ── DETALLES ──────────────────────────────────────────────────────────
        rete_col = next((c for c in dec.columns if "18." in c and "TOTAL" in c.upper() and "RETENCION" in c.upper()), None)
        san_col  = next((c for c in dec.columns if "19.1" in c or ("SANCION" in c.upper() and "VALOR" in c.upper())), None)
        int_col  = next((c for c in dec.columns if "20." in c and "INTERES" in c.upper()), None)

        rows = []
        for _, row in dec.iterrows():
            cxc = row["consecutivo_cxc"]
            # 7377 - Total retenciones
            if rete_col and row.get(rete_col):
                val = float(row[rete_col] or 0)
                if val != 0:
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": self.CONCEPTO_RETE["codigo"],
                        "descripcion_concepto": self.CONCEPTO_RETE["descripcion"],
                        "valor_unitario": val, "valor_total": val,
                        "centro_costo": "", "cantidad": 1,
                    })
            # 7378 - Sanciones
            if san_col and row.get(san_col):
                val = float(row[san_col] or 0)
                if val != 0:
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": self.CONCEPTO_SAN_RETE["codigo"],
                        "descripcion_concepto": self.CONCEPTO_SAN_RETE["descripcion"],
                        "valor_unitario": val, "valor_total": val,
                        "centro_costo": "", "cantidad": 1,
                    })
            # 7379 - Intereses
            if int_col and row.get(int_col):
                val = float(row[int_col] or 0)
                if val != 0:
                    rows.append({
                        "consecutivo_cxc": cxc,
                        "codigo_concepto": self.CONCEPTO_INT_RETE["codigo"],
                        "descripcion_concepto": self.CONCEPTO_INT_RETE["descripcion"],
                        "valor_unitario": val, "valor_total": val,
                        "centro_costo": "", "cantidad": 1,
                    })

        df_det = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["consecutivo_cxc","codigo_concepto","descripcion_concepto","centro_costo","cantidad","valor_unitario","valor_total"]
        )
        return df_enc, df_det
'''

# ── Actualizar motor.py para incluir Envigado ────────────────────────────────
files["etl/services/motor.py"] = '''import traceback
from django.utils import timezone
from etl.models import EncabezadoCXC, DetalleCXC
import pandas as pd


class MotorETL:
    def __init__(self, ejecucion):
        self.ejecucion = ejecucion
        self.proceso = ejecucion.proceso
        self.municipio = self.proceso.municipio

    def ejecutar(self, archivos):
        self.ejecucion.estado = "EJECUTANDO"
        self.ejecucion.save()
        try:
            processor = self._get_processor(archivos)
            df_enc, df_det = processor.procesar()
            self._guardar(df_enc, df_det)
            self.ejecucion.estado = "COMPLETADO"
        except Exception:
            self.ejecucion.estado = "ERROR"
            self.ejecucion.error_log = traceback.format_exc()
        finally:
            self.ejecucion.fecha_fin = timezone.now()
            self.ejecucion.save()

    def _get_processor(self, archivos):
        cod  = self.municipio.codigo
        proc = self.proceso.codigo
        if cod == "COPACABANA":
            from etl.services.copacabana import ProcesadorCopacabana
            return ProcesadorCopacabana(proc, archivos, self.municipio)
        elif cod == "ESTRELLA":
            from etl.services.estrella import ProcesadorEstrella
            return ProcesadorEstrella(proc, archivos, self.municipio)
        elif cod == "ENVIGADO":
            from etl.services.envigado import ProcesadorEnvigado
            return ProcesadorEnvigado(proc, archivos, self.municipio)
        else:
            raise NotImplementedError(f"No hay procesador para municipio: {cod}")

    def _guardar(self, df_enc, df_det):
        nuevos = duplicados = 0

        for _, row in df_enc.iterrows():
            consec = str(row.get("consecutivo_cxc", "")).strip()
            if not consec:
                continue
            if EncabezadoCXC.objects.filter(proceso=self.proceso, consecutivo_cxc=consec).exists():
                duplicados += 1
                continue

            def sv(v):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return ""
                return str(v).strip()

            def sd(v):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                try:
                    return pd.to_datetime(v).date()
                except Exception:
                    return None

            def sn(v):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                try:
                    return float(v)
                except Exception:
                    return None

            extra = row.get("datos_extra", {})
            if not isinstance(extra, dict):
                extra = {}

            enc = EncabezadoCXC.objects.create(
                proceso=self.proceso,
                ejecucion=self.ejecucion,
                consecutivo_cxc=consec,
                consecutivo_original=sv(row.get("consecutivo_original", "")),
                tipo_documento=sv(row.get("tipo_documento", "")),
                numero_documento=sv(row.get("numero_documento", "")),
                primer_nombre=sv(row.get("primer_nombre", "")),
                segundo_nombre=sv(row.get("segundo_nombre", "")),
                primer_apellido=sv(row.get("primer_apellido", "")),
                segundo_apellido=sv(row.get("segundo_apellido", "")),
                razon_social=sv(row.get("razon_social", "")),
                fecha_cobro=sd(row.get("fecha_cobro")),
                fecha_vencimiento=sd(row.get("fecha_vencimiento")),
                descripcion=sv(row.get("descripcion", "")),
                total_a_pagar=sn(row.get("total_a_pagar")),
                estado_pago=sv(row.get("estado_pago", "")),
                estado_cxc=sv(row.get("estado_cxc", "")),
                datos_extra=extra,
            )

            detalles = df_det[df_det["consecutivo_cxc"] == consec]
            for _, drow in detalles.iterrows():
                DetalleCXC.objects.create(
                    encabezado=enc,
                    codigo_concepto=sv(drow.get("codigo_concepto", "")),
                    centro_costo=sv(drow.get("centro_costo", "")),
                    cantidad=int(drow.get("cantidad", 1) or 1),
                    valor_unitario=sn(drow.get("valor_unitario")),
                    valor_total=sn(drow.get("valor_total")),
                )
            nuevos += 1

        self.ejecucion.registros_nuevos    = nuevos
        self.ejecucion.registros_duplicados = duplicados
        self.ejecucion.save()
'''

for rel_path, content in files.items():
    full = os.path.join(BASE, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"OK  {rel_path}")
