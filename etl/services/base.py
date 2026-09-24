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
    CONCEPTO_IND_EXON = "10167"
    CONCEPTO_COM_EXON = "10166"
    CONCEPTO_SER_EXON = "10168"
    PREFIJO_RENGLON_TARJETA = ("17.1", "171")

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

    def _leer(self, campo):
        """Insumo tabular: DataFrame (viene de GOBS) o ruta a un Excel subido."""
        origen = self.archivos[campo]
        if isinstance(origen, pd.DataFrame):
            return origen.copy()
        return pd.read_excel(origen)

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
        # Función de búsqueda fuzzy (normaliza acentos, mayúsculas)
        def _fuzz(df, *keywords, exclude=None):
            for kw in keywords:
                kw_n = self._norm(kw)
                for c in df.columns:
                    cn = self._norm(c)
                    if kw_n in cn:
                        if exclude and any(self._norm(ex) in cn for ex in exclude):
                            continue
                        return c
            return None

        rn = {}

        # Tipo de documento — evitar que "NUMERO" aparezca antes
        if "tipo_documento" not in dec.columns:
            c = _fuzz(dec, "Tipo de documento", "Tipo doc", "Tipodocumento",
                      exclude=["NUMERO", "NUMERO"])
            if c:
                rn[c] = "tipo_documento"

        # Número de documento — excluir columnas que contengan "tipo"
        if "numero_documento" not in dec.columns:
            c = _fuzz(dec,
                      "Numero de documento", "Número de documento",
                      "Nro de documento", "Nro. de documento",
                      "Numero documento", "Nro documento",
                      exclude=["tipo", "TIPO"])
            if c:
                rn[c] = "numero_documento"

        # Nombres y apellidos (matching exacto primero, luego fuzzy)
        for exact, target in [
            ("Primer nombre",    "primer_nombre"),
            ("Segundo nombre",   "segundo_nombre"),
            ("Primer apellido",  "primer_apellido"),
            ("Segundo apellido", "segundo_apellido"),
            ("Nombre productor", "razon_social"),
        ]:
            if target not in dec.columns and exact not in rn.values():
                if exact in dec.columns:
                    rn[exact] = target
                else:
                    c = _fuzz(dec, exact)
                    if c and c not in rn:
                        rn[c] = target

        if rn:
            dec.rename(columns=rn, inplace=True)
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
        # Quitar .0 de campos de identidad leídos como float desde Excel
        def _clean_id(v):
            s = str(v).strip()
            if s in ("", "nan", "None"): return ""
            try:
                f = float(s)
                if f == int(f): return str(int(f))
            except (ValueError, TypeError):
                pass
            return s
        for _col in ["numero_documento"]:
            if _col in df.columns:
                df[_col] = df[_col].apply(_clean_id)
        return df

    @staticmethod
    def _norm(s):
        """Quita tildes para comparar columnas con/sin acento."""
        import unicodedata
        return unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().upper()

    def _extra(self, dec, substr, concepto, also=None, prefijo=None):
        # Busca la columna numérica que contiene substr (sin tildes).
        # Excluye columnas de subtotal/total-agregado para no tomar la columna equivocada
        # (ej. '22. Subtotal Autorretenciones, Sanciones e Intereses' cuando se busca "SANCION").
        # Si hay varias, descarta las que resulten completamente no-numéricas (ej. "Tipo de sanción").
        # also: término adicional que TAMBIÉN debe estar en el nombre de la columna (ej. "RETENIDO").
        # prefijo: el nombre debe empezar por alguno de estos renglones (ej. ("17.1", "171")).
        #   Sirve cuando el nombre no basta para distinguir (GOBS trunca "Valor Retenido").
        # "PROFESIONAL" se excluye siempre: "Tarjeta de profesional" no es un valor en pesos.
        candidates = [
            c for c in dec.columns
            if self._norm(substr) in self._norm(c)
            and "SUBTOTAL" not in self._norm(c)
            and "PROFESIONAL" not in self._norm(c)
            and (also is None or self._norm(also) in self._norm(c))
            and (prefijo is None or self._norm(c).startswith(tuple(prefijo)))
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
        dec = self._leer("declaraciones")
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)
        # Fallback: tipo/numero documento vacíos → usar 'Cédula/NIT propietario'
        ced_col = next((c for c in dec.columns
                        if "CEDULA" in self._norm(c) and "NIT" in self._norm(c)), None)
        if ced_col and "numero_documento" in dec.columns:
            mask_empty = dec["numero_documento"].astype(str).str.strip().isin(["", "nan"])
            if mask_empty.any():
                dec.loc[mask_empty, "numero_documento"] = dec.loc[mask_empty, ced_col].astype(str).str.strip()
                if "tipo_documento" in dec.columns:
                    dec.loc[mask_empty, "tipo_documento"] = "NIT"
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

        act = self._leer("actividades")
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
        dec = self._leer("declaraciones")
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
        # Intentar con "RETENIDO" primero (para no tomar Base Gravable); si no existe,
        # caer en búsqueda solo por tipo de actividad (Copa puede no tener esa palabra).
        def _rete_extra(substr, concepto, prefijo=None):
            r = self._extra(dec, substr, concepto, also="RETENIDO", prefijo=prefijo)
            if r is None:
                r = self._extra(dec, substr, concepto, prefijo=prefijo)
            return r

        extras = [e for e in [
            _rete_extra("INDUSTRIAL", self.CONCEPTO_IND_RETE),
            _rete_extra("COMERCIAL",  self.CONCEPTO_COM_RETE),
            _rete_extra("SERVICIOS",  self.CONCEPTO_SER_RETE),
            self._extra(dec, "SANCION", self.CONCEPTO_SAN),
            self._extra(dec, "INTERES", self.CONCEPTO_INT),
            self._extra(dec, "EXCESO",  self.CONCEPTO_EXC_RETE),
            # Renglón 17.1 (Excel) / 171 (GOBS) = valor retenido; el 17 es la base gravable.
            _rete_extra("TARJETA",    self.CONCEPTO_TAR, prefijo=self.PREFIJO_RENGLON_TARJETA),
        ] if e is not None]
        df_det = pd.concat(extras, ignore_index=True) if extras else self._empty_det()
        return df_enc, df_det

    # ── DECLARE Y PAGUE ───────────────────────────────────────────────────────

    def _declare(self):
        dec = self._leer("declaraciones")
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)
        ano = dec.get("Año Gravable", pd.Series([0]*len(dec))).fillna(0)
        c2  = dec.get("Consecutivo 2", pd.Series([0]*len(dec))).fillna(0)
        dec["descripcion"] = ("DECLARE Y PAGUE AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c2.astype(float).astype(int).astype(str))
        def _find_col(cols, n):
            c = next((c for c in cols if f"{n}." in c), None)
            if c is None:
                c = next((c for c in cols
                          if c.strip().startswith(f"{n} ") or c.strip().startswith(f"{n}.")), None)
            return c

        tc = _find_col(dec.columns, "40")
        dec["total_a_pagar"] = pd.to_numeric(dec[tc], errors="coerce") if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", pd.Series([""]*len(dec))).fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        act = self._leer("actividades")
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

        # ── Splits proporcionales por tipo de actividad ──────────────────────
        # Retenciones (27.), autorretenciones (28.), anticipo (29.) y
        # pago voluntario (39.) se distribuyen entre INDUSTRIAL/COMERCIAL/SERVICIOS
        # en proporción al ICA de cada tipo respecto al total del consecutivo.
        split_extras = []
        if not ag.empty and "consecutivo_cxc" in ag.columns:
            total_ica = (ag.groupby("consecutivo_cxc")["valor_unitario"]
                         .sum().reset_index(name="total_ica"))
            ag_pct = (ag[["consecutivo_cxc", "codigo_concepto", "valor_unitario"]]
                      .merge(total_ica, on="consecutivo_cxc", how="left"))
            ag_pct["pct"] = ag_pct.apply(
                lambda r: r["valor_unitario"] / r["total_ica"] if r["total_ica"] else 0,
                axis=1)
            MAPA_EXON = {self.CONCEPTO_IND_DEC: self.CONCEPTO_IND_EXON,
                         self.CONCEPTO_COM_DEC: self.CONCEPTO_COM_EXON,
                         self.CONCEPTO_SER_DEC: self.CONCEPTO_SER_EXON}
            MAPA_RETE = {self.CONCEPTO_IND_DEC: "10150", self.CONCEPTO_COM_DEC: "10151", self.CONCEPTO_SER_DEC: "10152"}
            MAPA_AUTO = {self.CONCEPTO_IND_DEC: "10140", self.CONCEPTO_COM_DEC: "10139", self.CONCEPTO_SER_DEC: "10141"}
            MAPA_ANTI = {self.CONCEPTO_IND_DEC: "10137", self.CONCEPTO_COM_DEC: "10136ANT", self.CONCEPTO_SER_DEC: "10138"}
            MAPA_VOL  = {self.CONCEPTO_IND_DEC: "10148", self.CONCEPTO_COM_DEC: "10147", self.CONCEPTO_SER_DEC: "10149"}
            for num_str, mapa, negate in [
                ("26", MAPA_EXON, True),   # Exoneración      (-)
                ("27", MAPA_RETE, True),   # Retenciones      (-)
                ("28", MAPA_AUTO, True),   # Autorretenciones (-)
                ("29", MAPA_ANTI, True),   # Anticipos        (-)
                ("39", MAPA_VOL,  False),  # Pago voluntario  (+)
            ]:
                src_col = _find_col(dec.columns, num_str)
                if not src_col:
                    continue
                totals = dec[["consecutivo_cxc", src_col]].copy()
                totals[src_col] = pd.to_numeric(totals[src_col], errors="coerce")
                totals = totals[totals[src_col].notna() & (totals[src_col] != 0)]
                if totals.empty:
                    continue
                merged = ag_pct.merge(totals, on="consecutivo_cxc", how="inner")
                merged["nuevo_cod"] = merged["codigo_concepto"].map(mapa)
                merged = merged[merged["nuevo_cod"].notna()].copy()
                merged["valor_split"] = (merged[src_col] * merged["pct"]).round(0)
                if negate:
                    merged["valor_split"] = -merged["valor_split"].abs()
                else:
                    merged["valor_split"] = merged["valor_split"].abs()
                merged = merged[merged["valor_split"] != 0]
                if merged.empty:
                    continue
                t = (merged[["consecutivo_cxc", "nuevo_cod", "valor_split"]]
                     .rename(columns={"nuevo_cod": "codigo_concepto",
                                      "valor_split": "valor_unitario"})
                     .copy())
                t["valor_total"]  = t["valor_unitario"]
                t["centro_costo"] = self.CENTRO
                t["cantidad"]     = 1
                split_extras.append(t[["consecutivo_cxc", "codigo_concepto",
                                       "centro_costo", "cantidad",
                                       "valor_unitario", "valor_total"]])

        df_det = pd.concat([ag] + extras + split_extras, ignore_index=True)

        # ── Ajuste de cierre: sum(conceptos) debe ser exactamente total_40 ────
        # 1. Si total_40 no es múltiplo de 1000, redondearlo al más cercano.
        # 2. Restar el diff residual del concepto positivo de mayor valor.
        if tc and "consecutivo_cxc" in df_det.columns:
            for idx, enc_row in df_enc.iterrows():
                consec   = str(enc_row.get("consecutivo_cxc", "")).strip()
                total_40 = pd.to_numeric(enc_row.get("total_a_pagar"), errors="coerce")
                if pd.isna(total_40):
                    continue
                # Paso 1: normalizar total al múltiplo de 1000 más cercano
                total_norm = round(total_40 / 1000) * 1000
                if total_norm != total_40:
                    total_40 = total_norm
                    df_enc.at[idx, "total_a_pagar"] = total_40
                sub = df_det[df_det["consecutivo_cxc"].astype(str).str.strip() == consec]
                if sub.empty:
                    continue
                signed_sum = round(
                    sub["valor_total"].apply(lambda x: pd.to_numeric(x, errors="coerce")).fillna(0).sum(), 2
                )
                diff = round(signed_sum - total_40, 2)
                if abs(diff) == 0:
                    continue
                # Paso 2: ajustar el concepto positivo más grande para cerrar diff
                pos_mask = sub["valor_total"].apply(
                    lambda x: (pd.to_numeric(x, errors="coerce") or 0) > 0)
                pos_sub = sub[pos_mask].copy() if pos_mask.any() else sub.copy()
                pos_sub["_v"] = pos_sub["valor_total"].apply(
                    lambda x: pd.to_numeric(x, errors="coerce") or 0)
                best_idx = pos_sub["_v"].idxmax()
                new_val  = round(float(pos_sub.at[best_idx, "_v"]) - diff, 2)
                df_det.at[best_idx, "valor_unitario"] = new_val
                df_det.at[best_idx, "valor_total"]    = new_val

        return df_enc, df_det
