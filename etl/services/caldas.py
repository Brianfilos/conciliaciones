"""
ProcesadorCaldas — ETL para Municipio de Caldas.

Diferencias clave vs Copa/Estrella:
- Sin archivo CXC (no hay estado externo)
- Sin prefijo en consecutivo_cxc  (se usa el Consecutivo directo)
- Salida para ERP SAIMYR: concepto externo + código OCC
- Clasificación I/C/S almacenada en centro_costo del detalle
- datos_extra en encabezado guarda: tipo_persona, dv, dir, tel, email, banco, cuenta
- Sanciones múltiples (OCC-04..OCC-10) según "Tipo de sanción"
"""
import pandas as pd
from muni.models import CIIUMunicipio


# ── Mapeo tipo sanción → código OCC ──────────────────────────────────────────
SANCION_OCC = [
    ("extemporane",          "OCC-04"),
    ("no declarar",          "OCC-07"),
    ("no enviar",            "OCC-10"),
    ("emplazamiento",        "OCC-06"),
    ("aritmeti",             "OCC-08"),
    ("inexactitud",          "OCC-09"),
    ("correc",               "OCC-05"),   # corrección (catch-all, va al final)
]

# ── Descripciones conceptos SAIMYR ───────────────────────────────────────────
DESC_AUTO = {
    "I": "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES INDUSTRIALES",
    "C": "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES COMERCIALES",
    "S": "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES DE SERVICIO",
}
DESC_RETE = {
    "I": "RETENCIÓN DE INDUSTRIA Y COMERCIO ACTIVIDADES INDUSTRIALES",
    "C": "RETENCIÓN DE INDUSTRIA Y COMERCIO ACTIVIDADES COMERCIALES",
    "S": "RETENCIÓN DE INDUSTRIA Y COMERCIO ACTIVIDADES DE SERVICIO",
    "T": "RETENCIÓN SISTEMA TARJETAS Y MEDIOS DE PAGO",
}
DESC_DEC = {
    "I": "INDUSTRIA Y COMERCIO INDUSTRIA",
    "C": "INDUSTRIA Y COMERCIO COMERCIAL",
    "S": "INDUSTRIA Y COMERCIO SERVICIO",
}


def _occ_sancion(tipo_str):
    t = str(tipo_str).lower().strip()
    if t in ("ninguna", "", "nan"):
        return None
    for keyword, occ in SANCION_OCC:
        if keyword in t:
            return occ
    return "OCC-04"   # fallback


def _col(df, *keywords):
    """Devuelve el nombre de la primera columna cuyo nombre contiene algún keyword (case-insensitive)."""
    for kw in keywords:
        found = next((c for c in df.columns if kw.upper() in c.upper()), None)
        if found:
            return found
    return None


def _sv(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _split_razon_social(nombre, max_len=25):
    """
    Divide un nombre de empresa en 3 partes (nombres, primer_apellido, segundo_apellido).
    Cada parte tiene máximo max_len caracteres y nunca corta una palabra a la mitad.
    Si una parte no tiene contenido se rellena con '.'.
    """
    words = str(nombre).strip().split()
    parts = []
    remaining = list(words)

    for i in range(3):
        if not remaining:
            parts.append(".")
            continue
        chunk = []
        while remaining:
            test = " ".join(chunk + [remaining[0]])
            if len(test) <= max_len:
                chunk.append(remaining.pop(0))
            else:
                break
        if not chunk:
            # Palabra sola supera max_len — truncar
            chunk = [remaining.pop(0)[:max_len]]
        # En la tercera parte agregar todas las palabras restantes (truncando si es necesario)
        if i == 2 and remaining:
            all_w = chunk + remaining
            final = []
            for w in all_w:
                t = " ".join(final + [w]) if final else w
                if len(t) <= max_len:
                    final.append(w)
                else:
                    break
            chunk = final
        parts.append(" ".join(chunk))

    return parts[0], parts[1], parts[2]


def _num(v):
    """Convierte a float seguro. NaN/None/vacío → 0.0 (evita el bug NaN-truthy)."""
    r = pd.to_numeric(v, errors="coerce")
    return 0.0 if pd.isna(r) else float(r)


class ProcesadorCaldas:

    def __init__(self, proceso_codigo, archivos, municipio):
        self.proceso_codigo = proceso_codigo
        self.archivos = archivos
        self.municipio = municipio

    def _leer(self, campo):
        """Insumo tabular: DataFrame (viene de GOBS) o ruta a un Excel subido."""
        origen = self.archivos[campo]
        if isinstance(origen, pd.DataFrame):
            return origen.copy()
        return pd.read_excel(origen)

    def procesar(self):
        if self.proceso_codigo == "CXC_AUTO":
            return self._auto()
        elif self.proceso_codigo == "CXC_RETE":
            return self._rete()
        elif self.proceso_codigo == "DECLAREYPAGUE":
            return self._declare()
        raise ValueError(f"Proceso desconocido: {self.proceso_codigo}")

    # ── helpers internos ─────────────────────────────────────────────────────

    def _tipo_ciiu(self, codigo):
        try:
            return CIIUMunicipio.objects.get(
                municipio=self.municipio,
                codigo=str(codigo).zfill(4)
            ).tipo
        except Exception:
            return ""

    def _ciiu_code(self, raw):
        """Extrae el código numérico de un string CIIU como '4111-Construcción...'"""
        s = str(raw).strip()
        return s.split("-", 1)[0].strip().zfill(4) if "-" in s else s.zfill(4)

    def _tipo_persona(self, naturaleza):
        s = str(naturaleza).lower()
        return "J" if "jur" in s else "N"

    def _tipo_doc_id(self, tipo):
        t = str(tipo).upper()
        if "NIT" in t:
            return "3"
        if "CE" in t:
            return "2"
        return "1"   # CC por defecto

    def _clasi_char(self, tipo_ciiu):
        """INDUSTRIAL→I, COMERCIAL→C, SERVICIOS→S"""
        t = str(tipo_ciiu).upper()
        if "IND" in t:
            return "I"
        if "COM" in t:
            return "C"
        if "SER" in t:
            return "S"
        return ""

    def _build_enc(self, dec):
        """Construye el DataFrame de encabezado a partir del df de declaraciones."""
        # Detectar columnas por keyword (robusto ante encoding)
        ano_col    = _col(dec, "1.1") or _col(dec, "AÑO GRAVABLE", "AO GRAVABLE", "ANO GRAVABLE")
        per_col    = next((c for c in dec.columns if "PERIODO" in c.upper() and "1." in c), None)
        tipo_col   = next((c for c in dec.columns if "2-3" in c or "TIPO DE DECLAR" in c.upper() or "OPCI" in c.upper()), None)
        nat_col    = next((c for c in dec.columns if "ATUR" in c.upper()), None)   # Naturaleza jurídica
        tipodoc_col= next((c for c in dec.columns if "TIPO DE DOC" in c.upper()), None)
        numdoc_col = next((c for c in dec.columns if "MERO DE DOC" in c.upper()   # Número de documento
                           or ("NIT" in c.upper() and "PROPIET" in c.upper())
                           or ("DULA" in c.upper() and "NIT" in c.upper())), None)
        dir_col    = next((c for c in dec.columns if "IFICACI" in c.upper() and "DIR" in c.upper()), None)
        tel_col    = (next((c for c in dec.columns if "VIL" in c.upper()), None)
                      or next((c for c in dec.columns if "LEFONO" in c.upper()), None))
        email_col  = next((c for c in dec.columns if "MAIL" in c.upper() or "CORREO" in c.upper()), None)
        razon_col  = next((c for c in dec.columns if "RAZON" in c.upper() or "ESTABLECIMIENTO" in c.upper()), None)

        rows = []
        for _, r in dec.iterrows():
            consec_raw = r.get("Consecutivo", "")
            try:
                consec = str(int(float(consec_raw)))
            except Exception:
                consec = str(consec_raw).strip()
            if not consec or consec in ("nan", ""):
                continue

            naturaleza = _sv(r[nat_col]) if nat_col else ""
            tipo_p = self._tipo_persona(naturaleza)

            primer_n  = _sv(r.get("Primer nombre", ""))
            segundo_n = _sv(r.get("Segundo nombre", ""))
            primer_a  = _sv(r.get("Primer apellido", ""))
            segundo_a = _sv(r.get("Segundo apellido", ""))
            razon     = _sv(r[razon_col]) if razon_col else _sv(r.get("Razon Social", ""))

            if tipo_p == "J":
                nombres, ap1, ap2 = _split_razon_social(razon)
            else:
                nombres = (primer_n + " " + segundo_n).strip()
                ap1     = primer_a
                ap2     = segundo_a

            fecha_pago = r.get("Fecha Pago")
            try:
                fecha_pago = pd.to_datetime(fecha_pago, errors="coerce")
            except Exception:
                fecha_pago = None

            # Año y periodo para display en dashboard
            try:
                ano_val = str(int(float(r[ano_col] or 0))) if ano_col and pd.notna(r[ano_col]) else ""
            except Exception:
                ano_val = ""
            per_val  = _sv(r[per_col])  if per_col  else ""
            tipo_dec = _sv(r[tipo_col]) if tipo_col else ""

            rows.append({
                "consecutivo_cxc":      consec,
                "consecutivo_original": consec,
                "tipo_documento":       self._tipo_doc_id(_sv(r[tipodoc_col]) if tipodoc_col else ""),
                "numero_documento":     _sv(r[numdoc_col]) if numdoc_col else "",
                "primer_nombre":        nombres,
                "segundo_nombre":       "",
                "primer_apellido":      ap1,
                "segundo_apellido":     ap2,
                "razon_social":         razon if tipo_p == "J" else "",
                "fecha_cobro":          fecha_pago,
                "fecha_vencimiento":    None,
                "estado_pago":          _sv(r.get("Estado Pago", "")).upper(),
                "estado_cxc":           "",
                "datos_extra": {
                    "tipo_persona":  tipo_p,
                    "ano":           ano_val,
                    "periodo":       per_val,
                    "tipo_dec":      tipo_dec,
                    "dir_tercero":   _sv(r[dir_col])   if dir_col   else "",
                    "tel_tercero":   _sv(r[tel_col])   if tel_col   else "",
                    "email_tercero": _sv(r[email_col]) if email_col else "",
                    "codigo_banco":  "1",
                    "numero_cuenta": "2",
                },
            })
        return pd.DataFrame(rows)

    def _empty_det(self):
        return pd.DataFrame(columns=[
            "consecutivo_cxc", "codigo_concepto", "centro_costo",
            "cantidad", "valor_unitario", "valor_total"
        ])

    def _det_row(self, consec, occ, clasi, valor):
        return {
            "consecutivo_cxc": consec,
            "codigo_concepto": occ,
            "centro_costo":    clasi,    # I / C / S / T  o ""
            "cantidad":        1,
            "valor_unitario":  valor,
            "valor_total":     valor,
        }

    # ── AUTO ─────────────────────────────────────────────────────────────────

    def _auto(self):
        dec = self._leer("declaraciones")
        act = self._leer("actividades")

        df_enc = self._build_enc(dec)

        # Consecutive map  dec → consecutivo_cxc
        consec_map = {}
        for _, r in dec.iterrows():
            try:
                k = str(int(float(r["Consecutivo"])))
                consec_map[k] = k
            except Exception:
                pass

        # CIIU column in actividades
        ciiu_col = _col(act, "CIIU")
        val_col  = _col(act, "18.")
        con_col  = _col(act, "Consecutivo")

        det_rows = []

        # Actividades → OCC-209 por clasificación
        if ciiu_col and val_col and con_col:
            act["_consec"] = act[con_col].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "")
            act["_codigo"] = act[ciiu_col].apply(self._ciiu_code)
            act["_tipo"]   = act["_codigo"].apply(self._tipo_ciiu)
            act["_clasi"]  = act["_tipo"].apply(self._clasi_char)
            act["_val"]    = pd.to_numeric(act[val_col], errors="coerce").fillna(0)

            for (consec, clasi), grp in act.groupby(["_consec", "_clasi"]):
                if not consec or not clasi:
                    continue
                total = grp["_val"].sum()
                if total:
                    det_rows.append(self._det_row(consec, "OCC-209", clasi, total))

        # Sanciones, intereses, exceso desde declaraciones
        for _, r in dec.iterrows():
            try:
                consec = str(int(float(r["Consecutivo"])))
            except Exception:
                continue

            san_col = _col(dec, "20.1")
            int_col = _col(dec, "21.")
            exc_col = _col(dec, "23.")

            if san_col:
                val = _num(r.get(san_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-04", "", val))

            if int_col:
                val = _num(r.get(int_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-23", "", val))

            if exc_col:
                val = _num(r.get(exc_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-209", "X", -abs(val)))

        df_det = pd.DataFrame(det_rows) if det_rows else self._empty_det()

        # descripcion en encabezado
        ano_col = _col(dec, "1.1 A", "1. A")
        per_col = _col(dec, "1. Periodo", "Periodo declarado")
        for idx, row in df_enc.iterrows():
            consec = row["consecutivo_cxc"]
            orig = dec[dec["Consecutivo"].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "") == consec]
            if orig.empty:
                continue
            r = orig.iloc[0]
            ano = int(_num(r.get(ano_col, None))) if ano_col else 0
            per = _sv(r.get(per_col, "")) if per_col else ""
            df_enc.at[idx, "descripcion"] = f"PAGO AUTORETENCIÓN {per} {ano} Radicado No. {consec}"
            tc = _col(dec, "24. TOTAL")
            df_enc.at[idx, "total_a_pagar"] = pd.to_numeric(r.get(tc, None), errors="coerce") if tc else None

        return df_enc, df_det

    # ── RETE ─────────────────────────────────────────────────────────────────

    def _rete(self):
        dec = self._leer("declaraciones")
        df_enc = self._build_enc(dec)
        det_rows = []

        ind_col = _col(dec, "14.1")
        com_col = _col(dec, "15.1")
        ser_col = _col(dec, "16.1")
        tar_col = _col(dec, "17.1")
        san_val = _col(dec, "19.1")
        san_tip = _col(dec, "19. Tipo")
        int_col = _col(dec, "20.")
        exc_col = _col(dec, "22.")    # retención practicada en exceso
        tot_col = _col(dec, "23. Total")

        for _, r in dec.iterrows():
            try:
                consec = str(int(float(r["Consecutivo"])))
            except Exception:
                continue

            # Actividades retenidas por clasificación → OCC-993
            for col, clasi in [(ind_col, "I"), (com_col, "C"), (ser_col, "S"), (tar_col, "T")]:
                if col:
                    val = _num(r.get(col))
                    if val:
                        det_rows.append(self._det_row(consec, "OCC-993", clasi, val))

            # Sanción
            if san_val and san_tip:
                val = _num(r.get(san_val))
                if val:
                    occ = _occ_sancion(r.get(san_tip, "")) or "OCC-04"
                    det_rows.append(self._det_row(consec, occ, "", val))

            # Intereses
            if int_col:
                val = _num(r.get(int_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-23", "", val))

            # Retención practicada en exceso / indebida (negativo)
            if exc_col:
                val = _num(r.get(exc_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-209", "", -abs(val)))

        df_det = pd.DataFrame(det_rows) if det_rows else self._empty_det()

        # descripcion y total
        ano_col = _col(dec, "1.1 A", "1. A")
        per_col = _col(dec, "Periodo")
        for idx, row in df_enc.iterrows():
            consec = row["consecutivo_cxc"]
            orig = dec[dec["Consecutivo"].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "") == consec]
            if orig.empty:
                continue
            r = orig.iloc[0]
            ano = int(_num(r.get(ano_col, None))) if ano_col else 0
            per = _sv(r.get(per_col, "")) if per_col else ""
            df_enc.at[idx, "descripcion"] = f"PAGO RETENCIÓN {per} AÑO {ano} Radicado No. {consec}"
            df_enc.at[idx, "total_a_pagar"] = pd.to_numeric(r.get(tot_col, None), errors="coerce") if tot_col else None

        return df_enc, df_det

    # ── DECLARE Y PAGUE ───────────────────────────────────────────────────────

    def _declare(self):
        dec = self._leer("declaraciones")
        act = self._leer("actividades")

        df_enc = self._build_enc(dec)
        det_rows = []

        # Actividades desde declaraciones-actividades
        ciiu_col = _col(act, "CODIF", "CODIGO")
        val_col  = _col(act, "Impuestos de industria", "IMPUESTO")
        con_col  = _col(act, "Consecutivo")

        if ciiu_col and val_col and con_col:
            act["_consec"] = act[con_col].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "")
            act["_codigo"] = act[ciiu_col].astype(str).apply(
                lambda v: v.strip().split("-")[0].strip().zfill(4))
            act["_tipo"]  = act["_codigo"].apply(self._tipo_ciiu)
            act["_clasi"] = act["_tipo"].apply(self._clasi_char)
            act["_val"]   = pd.to_numeric(act[val_col], errors="coerce").fillna(0)

            OCC_DEC = {"I": "OCC-0048", "C": "OCC-0047", "S": "OCC-046"}
            for (consec, clasi), grp in act.groupby(["_consec", "_clasi"]):
                if not consec or not clasi:
                    continue
                occ = OCC_DEC.get(clasi, "")
                if not occ:
                    continue
                total = grp["_val"].sum()
                if total:
                    det_rows.append(self._det_row(consec, occ, clasi, total))

        # Pago voluntario — proporcional al ICA por clasificación (I/C/S)
        pag_col = _col(dec, "39.")
        if pag_col and ciiu_col and val_col and con_col:
            # Acumular ICA por (consecutivo, clasificación)
            ica_by_type: dict = {}
            for _, ra in act.iterrows():
                ca = str(ra.get("_consec", ""))
                cl = str(ra.get("_clasi", ""))
                va = _num(ra.get(val_col))
                if ca and cl and va:
                    ica_by_type.setdefault(ca, {})
                    ica_by_type[ca][cl] = ica_by_type[ca].get(cl, 0.0) + va

            for _, r in dec.iterrows():
                try:
                    consec = str(int(float(r["Consecutivo"])))
                except Exception:
                    continue
                pag_val = _num(r.get(pag_col))
                if not pag_val:
                    continue
                tipos = ica_by_type.get(consec, {})
                if not tipos:
                    continue
                total_ica = sum(tipos.values())
                if not total_ica:
                    continue
                for clasi, ica_amt in tipos.items():
                    occ = OCC_DEC.get(clasi, "")
                    if not occ:
                        continue
                    part = round(pag_val * ica_amt / total_ica)
                    if part:
                        det_rows.append(self._det_row(consec, occ, clasi, part))

        # Columnas especiales desde declaraciones-general
        san_tip = _col(dec, "31. Sanciones")
        san_val = _col(dec, "Digite valor sanciones")
        int_col = _col(dec, "37.")
        avi_col = _col(dec, "21. Impuesto de Avisos")
        bom_col = _col(dec, "23. Sobretasa")
        ret_col = _col(dec, "27.")    # retenciones
        aut_col = _col(dec, "28.")    # autorretenciones
        tot_col = _col(dec, "35. VALOR A PAGAR", "35.")

        for _, r in dec.iterrows():
            try:
                consec = str(int(float(r["Consecutivo"])))
            except Exception:
                continue

            # Sanciones (tipo determina OCC)
            if san_val and san_tip:
                val = _num(r.get(san_val))
                if val:
                    occ = _occ_sancion(r.get(san_tip, "")) or "OCC-04"
                    det_rows.append(self._det_row(consec, occ, "", val))

            # Intereses
            if int_col:
                val = _num(r.get(int_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-23", "", val))

            # Avisos y tableros
            if avi_col:
                val = _num(r.get(avi_col))
                if val:
                    det_rows.append(self._det_row(consec, "69", "", val))

            # Sobretasa bomberil
            if bom_col:
                val = _num(r.get(bom_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-051", "", val))

            # Retenciones practicadas (negativo)
            if ret_col:
                val = _num(r.get(ret_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-993", "", -abs(val)))

            # Autorretenciones practicadas (negativo)
            if aut_col:
                val = _num(r.get(aut_col))
                if val:
                    det_rows.append(self._det_row(consec, "OCC-209", "", -abs(val)))

        # ── Ajuste por diferencia entre col 40 y suma de conceptos ─────────────
        # Solo se agrega si la diferencia es POSITIVA (col40 > suma_conceptos)
        col40 = _col(dec, "40.")

        if col40:
            # Acumular suma de conceptos por consecutivo
            suma_conceptos: dict = {}
            for row in det_rows:
                c = row["consecutivo_cxc"]
                suma_conceptos[c] = suma_conceptos.get(c, 0.0) + float(row["valor_total"])

            # Tipo CIIU predominante por consecutivo (basado en actividades generadas)
            tipo_predominante: dict = {}
            for row in det_rows:
                c = row["consecutivo_cxc"]
                cl = row.get("centro_costo", "")
                if cl in ("I", "C", "S"):
                    if c not in tipo_predominante:
                        tipo_predominante[c] = {}
                    tipo_predominante[c][cl] = tipo_predominante[c].get(cl, 0.0) + abs(float(row["valor_total"]))

            OCC_DEC = {"I": "OCC-0048", "C": "OCC-0047", "S": "OCC-046"}

            for _, r in dec.iterrows():
                try:
                    consec = str(int(float(r["Consecutivo"])))
                except Exception:
                    continue

                col40_val = _num(r.get(col40))
                if not col40_val:
                    continue

                suma = suma_conceptos.get(consec, 0.0)
                gap = round(col40_val - suma)

                if gap <= 0:
                    continue  # solo diferencias positivas

                # Tipo CIIU predominante para este consecutivo
                tipos = tipo_predominante.get(consec, {})
                if not tipos:
                    # Fallback: buscar en el archivo de actividades por consecutivo
                    if con_col and ciiu_col:
                        act_rows = act[act["_consec"] == consec] if "_consec" in act.columns else pd.DataFrame()
                        for _, ar in act_rows.iterrows():
                            cl = self._clasi_char(self._tipo_ciiu(self._ciiu_code(ar.get(ciiu_col, ""))))
                            if cl in ("I", "C", "S"):
                                tipos[cl] = tipos.get(cl, 0) + 1
                    if not tipos:
                        continue  # sin ningún dato CIIU, omitir

                clasi = max(tipos, key=tipos.get)
                occ = OCC_DEC.get(clasi, "")
                if not occ:
                    continue

                det_rows.append(self._det_row(consec, occ, clasi, gap))

        df_det = pd.DataFrame(det_rows) if det_rows else self._empty_det()

        # descripcion y total
        ano_col = _col(dec, "Año Gravable", "A")
        for idx, row in df_enc.iterrows():
            consec = row["consecutivo_cxc"]
            orig = dec[dec["Consecutivo"].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "") == consec]
            if orig.empty:
                continue
            r = orig.iloc[0]
            ano = int(_num(r.get(ano_col, None))) if ano_col else 0
            df_enc.at[idx, "descripcion"] = f"DECLARE Y PAGUE AÑO GRAVABLE {ano} Radicado No. {consec}"
            df_enc.at[idx, "total_a_pagar"] = pd.to_numeric(r.get(tot_col, None), errors="coerce") if tot_col else None

        return df_enc, df_det
