"""
ProcesadorBase — clase base compartida por Copacabana y Estrella.
Separada aquí para que los tracebacks muestren 'base.py' y no 'copacabana.py'.
"""
import pandas as pd
from muni.models import CIIUMunicipio


class ProcesadorBase:
    PREFIJO = "903"
    CSV_SEP = ","
    CENTRO = "1501"
    CONSEC_COL = "Consecutivo 1"
    CONCEPTO_IND_AUTO = "10154"
    CONCEPTO_COM_AUTO = "10156"
    CONCEPTO_SER_AUTO = "10155"
    CONCEPTO_IND_RETE = "10154"
    CONCEPTO_COM_RETE = "10156"
    CONCEPTO_SER_RETE = "10155"
    CONCEPTO_IND_DEC  = "10144"
    CONCEPTO_COM_DEC  = "01100"
    CONCEPTO_SER_DEC  = "10145"
    CONCEPTO_SAN = "10112"
    CONCEPTO_INT = "10113"
    CONCEPTO_EXC = "10153"
    CONCEPTO_EXC_RETE = "10153"
    CONCEPTO_TAR = "10157"

    def __init__(self, proceso_codigo, archivos, municipio):
        self.proceso_codigo = proceso_codigo
        self.archivos = archivos
        self.municipio = municipio
        # Cache CIIU: un solo query en lugar de uno por fila
        self._ciiu_cache = {
            str(c).zfill(4): t
            for c, t in CIIUMunicipio.objects
                .filter(municipio=municipio)
                .values_list("codigo", "tipo")
        }

    def procesar(self):
        if self.proceso_codigo == "CXC_AUTO":
            return self._auto()
        elif self.proceso_codigo == "CXC_RETE":
            return self._rete()
        elif self.proceso_codigo == "DECLAREYPAGUE":
            return self._declare()
        raise ValueError(f"Proceso desconocido: {self.proceso_codigo}")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _cxc_id(self, serie):
        def _fmt(v):
            # Handle float strings like "260689.0" from pandas reading Excel
            try:
                s = str(int(float(str(v).strip())))
            except (ValueError, TypeError):
                s = str(v).strip()
            return self.PREFIJO + "0" * max(0, 10 - len(s) - 3) + s
        return [_fmt(v) for v in serie]

    def _load_cxc(self):
        if "cxc_csv" not in self.archivos:
            return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])
        p = self.archivos["cxc_csv"]

        # 1. Intentar lectura tabular estándar (header en fila 0)
        try:
            df = pd.read_csv(p, encoding="latin1", sep=self.CSV_SEP)
        except Exception:
            df = pd.read_csv(p, encoding="latin1")

        consec_col = next((c for c in df.columns if "CONSECUTIVO" in str(c).upper()), None)

        # 2. Si el header no está en la fila 0, buscar la fila que lo contiene
        if consec_col is None:
            raw = pd.read_csv(p, encoding="latin1", header=None, dtype=str)
            header_row = next(
                (i for i, row in raw.iterrows()
                 if any("CONSECUTIVO" in str(v).upper() for v in row)),
                None
            )
            if header_row is not None:
                df = pd.read_csv(p, encoding="latin1", sep=self.CSV_SEP,
                                 header=header_row, dtype=str)
                consec_col = next((c for c in df.columns if "CONSECUTIVO" in str(c).upper()), None)

        # 3. Si definitivamente no hay columna CONSECUTIVO → devolver vacío (sin crash)
        if consec_col is None:
            return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])

        if consec_col != "CONSECUTIVO":
            df = df.rename(columns={consec_col: "CONSECUTIVO"})

        # Asegurar columna ESTADO
        estado_col = next((c for c in df.columns if "ESTADO" in str(c).upper()), None)
        if estado_col and estado_col != "ESTADO":
            df = df.rename(columns={estado_col: "ESTADO"})
        elif not estado_col:
            df["ESTADO"] = ""

        df["CONSECUTIVO"] = df["CONSECUTIVO"].fillna("")
        df = df[df["CONSECUTIVO"].apply(lambda x: str(x).replace(".", "", 1).isdigit())]
        df["CONSECUTIVO"] = df["CONSECUTIVO"].astype(float).astype(int).astype(str).str.strip()
        return df

    def _tipo_ciiu(self, codigo):
        return self._ciiu_cache.get(str(codigo).zfill(4), "")

    def _base_rename(self, dec, consec_col="Consecutivo 1"):
        rn = {
            "Tipo de documento": "tipo_documento",
            "Numero de documento": "numero_documento",
            "Número de documento": "numero_documento",
            "Primer nombre": "primer_nombre",
            "Segundo nombre": "segundo_nombre",
            "Primer apellido": "primer_apellido",
            "Segundo apellido": "segundo_apellido",
            "Nombre productor": "razon_social",
        }
        dec.rename(columns={k: v for k, v in rn.items() if k in dec.columns}, inplace=True)
        # Solo una columna de fecha: "Fecha de la visita" tiene prioridad sobre "Fecha Pago"
        if "Fecha de la visita" in dec.columns:
            dec.rename(columns={"Fecha de la visita": "fecha_cobro"}, inplace=True)
        elif "Fecha Pago" in dec.columns:
            dec.rename(columns={"Fecha Pago": "fecha_cobro"}, inplace=True)
        if "tipo_documento" in dec.columns:
            dec["razon_social"] = dec.apply(
                lambda r: "" if r.get("tipo_documento") in ["CC", "CE"] else r.get("razon_social", ""), axis=1)
        dec["fecha_cobro"] = pd.to_datetime(dec.get("fecha_cobro"), errors="coerce")
        dec["fecha_vencimiento"] = dec["fecha_cobro"] + pd.Timedelta(days=1)
        dec["consecutivo_original"] = dec.get(consec_col, "").astype(str)
        return dec

    def _merge_cxc(self, dec):
        cxc = self._load_cxc()
        # El CXC tiene una fila por concepto — deduplicar para evitar que el merge
        # expanda filas y genere falsos duplicados en EncabezadoCXC.
        # Prioridad: CANCELADA > cualquier otro estado.
        cxc["_prio"] = cxc["ESTADO"].apply(lambda e: 0 if str(e).upper() == "CANCELADA" else 1)
        cxc = (cxc.sort_values("_prio")
                   .drop_duplicates(subset=["CONSECUTIVO"], keep="first")
                   .drop(columns=["_prio"]))
        dec["consecutivo_cxc"] = dec["consecutivo_cxc"].astype(str).str.strip()
        dec = pd.merge(dec, cxc[["CONSECUTIVO", "ESTADO"]], left_on="consecutivo_cxc", right_on="CONSECUTIVO", how="left")
        dec.drop(columns=["CONSECUTIVO"], errors="ignore", inplace=True)
        dec["estado_cxc"] = dec.get("ESTADO", "").fillna("").astype(str).str.upper()
        return dec

    def _enc(self, dec):
        cols = ["consecutivo_cxc", "consecutivo_original", "tipo_documento", "numero_documento",
                "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
                "razon_social", "fecha_cobro", "fecha_vencimiento", "descripcion",
                "total_a_pagar", "estado_pago", "estado_cxc"]
        df = dec[[c for c in cols if c in dec.columns]].copy()
        df["datos_extra"] = [{}] * len(df)
        return df

    @staticmethod
    def _norm(s):
        """Quita tildes para comparar columnas con/sin acento."""
        import unicodedata
        return unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().upper()

    def _extra(self, dec, substr, concepto, also=None):
        # Busca la columna numérica que contiene substr (sin tildes).
        # Excluye columnas de subtotal/total-agregado para no tomar la columna equivocada
        # (ej. '22. Subtotal Autorretenciones, Sanciones e Intereses' cuando se busca "SANCION").
        # Si hay varias, descarta las que resulten completamente no-numéricas (ej. "Tipo de sanción").
        # also: término adicional que TAMBIÉN debe estar en el nombre de la columna (ej. "RETENIDO").
        candidates = [
            c for c in dec.columns
            if self._norm(substr) in self._norm(c)
            and "SUBTOTAL" not in self._norm(c)
            and (also is None or self._norm(also) in self._norm(c))
        ]
        col = None
        for c in candidates:
            if pd.to_numeric(dec[c], errors="coerce").notna().any():
                col = c
                break
        if col is None:
            return None
        t = dec[["consecutivo_cxc", col]].copy()
        t[col] = pd.to_numeric(t[col], errors="coerce")
        t = t[t[col].notna() & (t[col] != 0)]
        if t.empty:
            return None
        t.rename(columns={col: "valor_unitario"}, inplace=True)
        t["codigo_concepto"] = concepto
        t["valor_total"] = t["valor_unitario"]
        t["centro_costo"] = self.CENTRO
        t["cantidad"] = 1
        return t[["consecutivo_cxc", "codigo_concepto", "centro_costo", "cantidad", "valor_unitario", "valor_total"]]

    def _empty_det(self):
        return pd.DataFrame(columns=["consecutivo_cxc", "codigo_concepto", "centro_costo", "cantidad", "valor_unitario", "valor_total"])

    def _resolve_consec_col(self, dec):
        """Devuelve el nombre real de la columna consecutivo en el DataFrame."""
        if self.CONSEC_COL in dec.columns:
            return self.CONSEC_COL
        # Fallback: primera columna que contenga "Consecutivo"
        fallback = next((c for c in dec.columns if "Consecutivo" in c), None)
        if fallback:
            return fallback
        raise ValueError(
            f"No se encontró columna '{self.CONSEC_COL}' ni ninguna columna 'Consecutivo'. "
            f"Columnas disponibles: {list(dec.columns)}"
        )

    # ── AUTO ─────────────────────────────────────────────────────────────────

    def _auto(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)
        ano = dec.get("1. Año", dec.get("1.1 Año", pd.Series([0]*len(dec)))).fillna(0)
        c1  = dec.get(cname, pd.Series([0]*len(dec))).fillna(0)
        per = dec.get("1.1 Periodo declarado", dec.get("1. Periodo declarado", pd.Series([""]*len(dec)))).fillna("")
        dec["descripcion"] = ("PAGO AUTORETENCIÓN " + per.astype(str) + " "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c1.astype(float).astype(int).astype(str))
        tc = next((c for c in dec.columns if "TOTAL A PAGAR" in c.upper() or "24." in c), None)
        dec["total_a_pagar"] = dec[tc] if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", pd.Series([""]*len(dec))).fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        act = pd.read_excel(self.archivos["actividades"])
        cc = next((c for c in act.columns if "CIIU" in c.upper() or "CODIGO" in c.upper()), None)
        if cc:
            act["codigo"] = act[cc].astype(str).apply(
                lambda v: v.split(" -", 1)[0].strip().zfill(4) if " -" in v else v.strip().zfill(4))
        vc = next((c for c in act.columns if "AUTORETENCION" in c.upper() or "18." in c), None)
        if vc:
            act.rename(columns={vc: "valor"}, inplace=True)
        ac = next((c for c in act.columns if "Consecutivo" in c), None)
        if ac:
            act.rename(columns={ac: cname}, inplace=True)
        act[cname] = act[cname].astype(str)
        dm = dec[[cname, "consecutivo_cxc"]].copy()
        dm[cname] = dm[cname].astype(str)
        act = act.merge(dm, on=cname, how="left")
        MAPA = {"INDUSTRIAL": self.CONCEPTO_IND_AUTO, "COMERCIAL": self.CONCEPTO_COM_AUTO, "SERVICIOS": self.CONCEPTO_SER_AUTO}
        VALIDOS = set(MAPA.values())
        # Intentar extraer el concepto directamente del string CIIU (ej. "4111 -Desc -HDA674 -servicios")
        # Si el tercer segmento (split por ' -') es un concepto válido, usarlo directamente.
        # Si no, caer en la búsqueda por tipo en la BD.
        if cc:
            def _concepto_directo(v):
                parts = str(v).split(" -")
                if len(parts) >= 3:
                    c = parts[2].strip()
                    if c in VALIDOS:
                        return c
                return ""
            act["codigo_concepto"] = act[cc].apply(_concepto_directo)
            mask_empty = act["codigo_concepto"] == ""
            if mask_empty.any() and "codigo" in act.columns:
                act["TIPO"] = ""
                act.loc[mask_empty, "TIPO"] = act.loc[mask_empty, "codigo"].apply(self._tipo_ciiu)
                act.loc[mask_empty, "codigo_concepto"] = act.loc[mask_empty, "TIPO"].map(MAPA).fillna("")
        else:
            act["TIPO"] = act["codigo"].apply(self._tipo_ciiu) if "codigo" in act.columns else ""
            act["codigo_concepto"] = act["TIPO"].map(MAPA).fillna("")
        if "valor" in act.columns and "consecutivo_cxc" in act.columns:
            ag = act.groupby(["consecutivo_cxc", "codigo_concepto"])["valor"].sum().reset_index()
            ag.rename(columns={"valor": "valor_unitario"}, inplace=True)
            ag["valor_total"] = ag["valor_unitario"]
            ag["centro_costo"] = self.CENTRO
            ag["cantidad"] = 1
        else:
            ag = self._empty_det()

        extras = [e for e in [
            self._extra(dec, "SANCION", self.CONCEPTO_SAN),
            self._extra(dec, "INTERES", self.CONCEPTO_INT),
            self._extra(dec, "EXCESO",  self.CONCEPTO_EXC),
        ] if e is not None]
        df_det = pd.concat([ag] + extras, ignore_index=True)
        return df_enc, df_det

    # ── RETE ─────────────────────────────────────────────────────────────────

    def _rete(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)
        ano = dec.get("1. Año", dec.get("1.1 Año", pd.Series([0]*len(dec)))).fillna(0)
        c1  = dec.get(cname, pd.Series([0]*len(dec))).fillna(0)
        per = dec.get("1.1 Periodo declarado", dec.get("1. Periodo declarado", pd.Series([""]*len(dec)))).fillna("")
        dec["descripcion"] = ("PAGO RETENCIÓN " + per.astype(str) + " AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c1.astype(float).astype(int).astype(str))
        tc = next((c for c in dec.columns if "TOTAL A PAGAR" in c.upper() or "23." in c), None)
        dec["total_a_pagar"] = dec[tc] if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", pd.Series([""]*len(dec))).fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)
        extras = [e for e in [
            self._extra(dec, "INDUSTRIAL",  self.CONCEPTO_IND_RETE),
            self._extra(dec, "COMERCIAL",   self.CONCEPTO_COM_RETE),
            self._extra(dec, "SERVICIOS",   self.CONCEPTO_SER_RETE),
            self._extra(dec, "SANCION",     self.CONCEPTO_SAN),
            self._extra(dec, "INTERES",     self.CONCEPTO_INT),
            self._extra(dec, "EXCESO",      self.CONCEPTO_EXC_RETE),
            self._extra(dec, "TARJETA",     self.CONCEPTO_TAR),
        ] if e is not None]
        df_det = pd.concat(extras, ignore_index=True) if extras else self._empty_det()
        return df_enc, df_det

    # ── DECLARE Y PAGUE ───────────────────────────────────────────────────────

    def _declare(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)
        ano = dec.get("Año Gravable", pd.Series([0]*len(dec))).fillna(0)
        c2  = dec.get("Consecutivo 2", pd.Series([0]*len(dec))).fillna(0)
        dec["descripcion"] = ("DECLARE Y PAGUE AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c2.astype(float).astype(int).astype(str))
        tc = next((c for c in dec.columns if "40." in c), None)
        dec["total_a_pagar"] = pd.to_numeric(dec[tc], errors="coerce") if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", pd.Series([""]*len(dec))).fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        act = pd.read_excel(self.archivos["actividades"])
        cc = next((c for c in act.columns if "CODIFIC" in c.upper() or "CODIGO" in c.upper()), None)
        if cc:
            act["codigo"] = act[cc].astype(str).apply(
                lambda v: v.split(" -", 1)[0].strip().zfill(4) if " -" in v else v.strip().zfill(4))
        ic = next((c for c in act.columns if "INDUSTRIA" in c.upper() and "COMERCIO" in c.upper()), None)
        if not ic:
            ic = next((c for c in act.columns if "IMPUESTO" in c.upper()), None)
        # Asegurar que existe columna "Consecutivo 2" en actividades para el merge
        if "Consecutivo 2" not in act.columns:
            ac = next((c for c in act.columns if "Consecutivo" in c), None)
            if ac:
                act.rename(columns={ac: "Consecutivo 2"}, inplace=True)
        act["Consecutivo 2"] = act["Consecutivo 2"].astype(str)
        if "Consecutivo 2" in dec.columns:
            dm = dec[["Consecutivo 2", "consecutivo_cxc"]].copy()
            dm["Consecutivo 2"] = dm["Consecutivo 2"].astype(str).str.replace(r"\.0$", "", regex=True)
            act = act.merge(dm, on="Consecutivo 2", how="left")
        act["TIPO"] = act["codigo"].apply(self._tipo_ciiu) if "codigo" in act.columns else ""
        MAPA = {"INDUSTRIAL": self.CONCEPTO_IND_DEC, "COMERCIAL": self.CONCEPTO_COM_DEC, "SERVICIOS": self.CONCEPTO_SER_DEC}
        act["codigo_concepto"] = act["TIPO"].map(MAPA).fillna("") if "TIPO" in act.columns else ""
        if ic and "consecutivo_cxc" in act.columns:
            ag = act.groupby(["consecutivo_cxc", "codigo_concepto"])[ic].sum().reset_index()
            ag.rename(columns={ic: "valor_unitario"}, inplace=True)
            ag["valor_total"] = ag["valor_unitario"]
            ag["centro_costo"] = self.CENTRO
            ag["cantidad"] = 1
        else:
            ag = self._empty_det()
        extras = [e for e in [
            self._extra(dec, "AVISOS",   "10101"),
            self._extra(dec, "BOMBERIL", "10111"),
            self._extra(dec, "SANCION",  self.CONCEPTO_SAN),
            self._extra(dec, "INTERES",  self.CONCEPTO_INT),
        ] if e is not None]
        df_det = pd.concat([ag] + extras, ignore_index=True)

        # ── Ajuste de redondeo (todos los conceptos son positivos en Copa) ──
        # diff = suma_conceptos - total_40
        # |diff| < 500 → quitar la diferencia del concepto de mayor valor.
        # |diff| >= 500 → aproximar total_40 al siguiente múltiplo de 1000.
        import math as _math

        if tc and "consecutivo_cxc" in df_det.columns:
            for idx, enc_row in df_enc.iterrows():
                consec = enc_row.get("consecutivo_cxc", "")
                total_40 = pd.to_numeric(enc_row.get("total_a_pagar"), errors="coerce")
                if pd.isna(total_40):
                    continue
                sub = df_det[df_det["consecutivo_cxc"] == consec]
                if sub.empty:
                    continue
                signed_sum = round(
                    sub["valor_total"].apply(lambda x: pd.to_numeric(x, errors="coerce")).fillna(0).sum(), 2
                )
                diff = round(signed_sum - total_40, 2)
                if abs(diff) == 0:
                    continue
                if abs(diff) < 500:
                    # Buscar el concepto que al ajustarse quede en múltiplo de 1000.
                    tmp = sub.copy()
                    tmp["_v"] = tmp["valor_total"].apply(
                        lambda x: pd.to_numeric(x, errors="coerce") or 0)
                    tmp["_new"] = tmp["_v"] - diff
                    tmp["_rem"] = tmp["_new"].apply(
                        lambda v: min(v % 1000, 1000 - v % 1000))
                    best_idx = tmp["_rem"].idxmin()
                    new_val = round(float(tmp.at[best_idx, "_new"]), 2)
                    df_det.at[best_idx, "valor_unitario"] = new_val
                    df_det.at[best_idx, "valor_total"]    = new_val
                else:
                    df_enc.at[idx, "total_a_pagar"] = _math.ceil(total_40 / 1000) * 1000

        return df_enc, df_det
