import re
import pandas as pd
from etl.services.base import ProcesadorBase

_DATE_RE = re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$')


# Signos para Declare y Pague según CONCEPTOS CXC.xlsx de Estrella
_SIGNO_DEC = {
    "HD75":   +1, "HDA839": +1, "HDA840": +1,
    "HD192":  +1, "HD193":  +1,
    "HD22":   +1, "IntlCOM": +1, "IntICOM": +1,
    "HDA838": +1,
    "HDA831": -1,
    "HDA832": -1, "HDA833": -1, "HDA834": -1,
    "HDA835": -1, "HDA836": -1, "HDA837": -1,
}


class ProcesadorEstrella(ProcesadorBase):
    PREFIJO      = "904"
    CSV_SEP      = ";"
    CONSEC_COL   = "Consecutivo"
    CENTRO       = "07"
    # AUTO / RETE conceptos
    CONCEPTO_IND_AUTO = "HDA675"
    CONCEPTO_COM_AUTO = "HD402"
    CONCEPTO_SER_AUTO = "HDA674"
    CONCEPTO_IND_RETE = "HDA675"
    CONCEPTO_COM_RETE = "HD402"
    CONCEPTO_SER_RETE = "HDA674"
    CONCEPTO_SAN      = "HD22"
    CONCEPTO_INT      = "IntICOM"
    CONCEPTO_EXC      = "HDA806"
    CONCEPTO_EXC_RETE = "HDA806"
    CONCEPTO_TAR      = "HDA676"
    # DECLARE y PAGUE conceptos (diferentes!)
    CONCEPTO_IND_DEC = "HDA839"
    CONCEPTO_COM_DEC = "HD75"
    CONCEPTO_SER_DEC = "HDA840"
    # RÉGIMEN SIMPLE (RST) — conceptos propios, según CXC REGIMEN SIMPLE 13-03-2024.xlsx
    PREFIJO_RST       = "908"
    CONCEPTO_IND_RST  = "HDA732"
    CONCEPTO_COM_RST  = "HDA733"
    CONCEPTO_SER_RST  = "HDA734"

    def procesar(self):
        if self.proceso_codigo == "REGIMEN_SIMPLE":
            return self._regimen_simple()
        return super().procesar()

    def _load_cxc(self):
        if "cxc_csv" not in self.archivos:
            return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])
        return self._load_cxc_de(self.archivos["cxc_csv"])

    def _load_cxc_de(self, p):
        """
        Parsea el reporte SOFINET multi-sección de CXC, desde una ruta cualquiera (no
        solo self.archivos['cxc_csv'] — Régimen Simple la usa para leer el último CXC
        ya cargado por Auto/Rete/Declare sin tener que resubir el mismo archivo).
        Filas de datos: tienen fecha dd/mm/yyyy en col 0.
        CONSECUTIVO = col 5, ESTADO = col 2.
        """
        # Leer crudo sin header para detectar estructura dinámica
        raw = pd.read_csv(p, encoding="latin1", header=None, dtype=str)

        # Buscar la fila de encabezado (la que contiene "CONSECUTIVO")
        header_row_idx = next(
            (i for i, row in raw.iterrows()
             if any("CONSECUTIVO" in str(v).upper() for v in row)),
            None
        )

        if header_row_idx is not None:
            # Leer con ese header para obtener columnas nombradas
            df = pd.read_csv(p, encoding="latin1", header=header_row_idx, dtype=str)
            consec_col = next((c for c in df.columns if "CONSECUTIVO" in str(c).upper()), None)
            estado_col = next((c for c in df.columns if "ESTADO" in str(c).upper()), None)

            if consec_col:
                if consec_col != "CONSECUTIVO":
                    df = df.rename(columns={consec_col: "CONSECUTIVO"})
                if estado_col and estado_col != "ESTADO":
                    df = df.rename(columns={estado_col: "ESTADO"})
                elif not estado_col:
                    df["ESTADO"] = ""

                df["CONSECUTIVO"] = df["CONSECUTIVO"].fillna("")
                df = df[df["CONSECUTIVO"].apply(lambda x: str(x).replace(".", "", 1).isdigit())]
                if df.empty:
                    return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])
                df["CONSECUTIVO"] = df["CONSECUTIVO"].astype(float).astype(int).astype(str).str.strip()
                return df[["CONSECUTIVO", "ESTADO"]].copy()

        return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])

    # ── DECLARE Y PAGUE (override completo para Estrella) ────────────────────

    def _declare(self):
        cname = "Consecutivo 2"   # col radicado: descripción y merge de actividades
        dec = self._leer("declaraciones")
        # El consecutivo_cxc se construye desde Consecutivo 1 (igual que en el py original)
        dec["consecutivo_cxc"] = self._cxc_id(dec["Consecutivo 1"])
        dec = self._base_rename(dec, cname)

        ano = dec.get("Año Gravable", pd.Series([0] * len(dec))).fillna(0)
        c2  = dec.get(cname, pd.Series([0] * len(dec))).fillna(0)
        dec["descripcion"] = ("DECLARE Y PAGUE AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " RADICADO NO. "
                              + c2.astype(float).astype(int).astype(str))

        # Total a pagar es la col 40 (no usar "pago voluntario" que matchea col 39)
        tc = next((c for c in dec.columns if "40." in c), None)
        dec["total_a_pagar"] = pd.to_numeric(dec[tc], errors="coerce") if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", pd.Series([""] * len(dec))).fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        # ── Actividades (ICA por CIIU) ────────────────────────────────────────
        act = self._leer("actividades")
        cc = next((c for c in act.columns if "CODIFIC" in c.upper() or "CODIGO" in c.upper()), None)
        if cc:
            act["codigo"] = act[cc].fillna("").astype(str).apply(
                lambda v: v.split(" -", 1)[0].strip().zfill(4) if " -" in v else v.strip().zfill(4))
        ic = next((c for c in act.columns if "INDUSTRIA" in c.upper() and "COMERCIO" in c.upper()), None)
        if not ic:
            ic = next((c for c in act.columns if "IMPUESTO" in c.upper()), None)
        # Estrella actividades tiene 'Consecutivo 2' — usar directamente
        ac = "Consecutivo 2" if "Consecutivo 2" in act.columns else next(
            (c for c in act.columns if "Consecutivo" in c), None)
        if ac and ac != cname:
            act.rename(columns={ac: cname}, inplace=True)
        act[cname] = act[cname].astype(str)
        if cname in dec.columns:
            dm = dec[[cname, "consecutivo_cxc"]].copy()
            dm[cname] = dm[cname].astype(str).str.replace(r"\.0$", "", regex=True)
            act = act.merge(dm, on=cname, how="left")
        act["TIPO"] = act["codigo"].apply(self._tipo_ciiu) if "codigo" in act.columns else ""
        MAPA = {
            "INDUSTRIAL": self.CONCEPTO_IND_DEC,
            "COMERCIAL":  self.CONCEPTO_COM_DEC,
            "SERVICIOS":  self.CONCEPTO_SER_DEC,
        }
        act["codigo_concepto"] = act["TIPO"].map(MAPA).fillna("")
        if ic and "consecutivo_cxc" in act.columns:
            ag = act.groupby(["consecutivo_cxc", "codigo_concepto"])[ic].sum().reset_index()
            ag.rename(columns={ic: "valor_unitario"}, inplace=True)
            ag["valor_total"] = ag["valor_unitario"]
            ag["centro_costo"] = self.CENTRO
            ag["cantidad"] = 1
        else:
            ag = self._empty_det()

        # ── Extras desde declaraciones ────────────────────────────────────────
        extras = []
        # Retenciones practicadas (-)
        _ret = self._extra(dec, "27.", "HDA831")
        if _ret is not None:
            extras.append(_ret)
        # Autorretenciones (col 28) y Anticipo (col 29) — split proporcional por TIPO
        # Porcentaje = ICA_por_TIPO / Total_ICA_del_consecutivo
        # Autorrete: INDUSTRIAL→HDA832, COMERCIAL→HDA833, SERVICIOS→HDA834
        # Anticipo:  INDUSTRIAL→HDA835, COMERCIAL→HDA836, SERVICIOS→HDA837
        _aut_col = next((c for c in dec.columns if "28." in c), None)
        _ant_col = next((c for c in dec.columns if "29." in c and "ANTICIPO" in c.upper()), None)

        if (_aut_col or _ant_col) and not ag.empty and "consecutivo_cxc" in ag.columns:
            total_ica = (ag.groupby("consecutivo_cxc")["valor_unitario"]
                         .sum().reset_index(name="total_ica"))
            ag_pct = ag[["consecutivo_cxc", "codigo_concepto", "valor_unitario"]].merge(
                total_ica, on="consecutivo_cxc", how="left")
            ag_pct["pct"] = ag_pct.apply(
                lambda r: r["valor_unitario"] / r["total_ica"] if r["total_ica"] else 0, axis=1)

            MAPA_AUT = {
                self.CONCEPTO_IND_DEC: "HDA832",
                self.CONCEPTO_COM_DEC: "HDA833",
                self.CONCEPTO_SER_DEC: "HDA834",
            }
            MAPA_ANT = {
                self.CONCEPTO_IND_DEC: "HDA835",
                self.CONCEPTO_COM_DEC: "HDA836",
                self.CONCEPTO_SER_DEC: "HDA837",
            }

            for orig_col, cod_mapa in [(_aut_col, MAPA_AUT), (_ant_col, MAPA_ANT)]:
                if not orig_col:
                    continue
                totals = dec[["consecutivo_cxc", orig_col]].copy()
                totals[orig_col] = pd.to_numeric(totals[orig_col], errors="coerce")
                totals = totals[totals[orig_col].notna() & (totals[orig_col] != 0)]
                if totals.empty:
                    continue
                merged = ag_pct.merge(totals, on="consecutivo_cxc", how="inner")
                merged["nuevo_concepto"] = merged["codigo_concepto"].map(cod_mapa)
                merged = merged[merged["nuevo_concepto"].notna()].copy()
                merged["valor_split"] = (merged[orig_col] * merged["pct"]).round(0)
                merged = merged[merged["valor_split"] != 0]
                if merged.empty:
                    continue
                t = merged[["consecutivo_cxc", "nuevo_concepto", "valor_split"]].rename(
                    columns={"nuevo_concepto": "codigo_concepto", "valor_split": "valor_unitario"}
                ).copy()
                t["valor_total"]  = t["valor_unitario"]
                t["centro_costo"] = self.CENTRO
                t["cantidad"]     = 1
                extras.append(t[["consecutivo_cxc", "codigo_concepto", "centro_costo",
                                  "cantidad", "valor_unitario", "valor_total"]])
        # Sanciones / intereses / avisos / bomberil
        for substr, cod in [
            ("SANCION",  "HD22"),
            ("INTERES",  "IntICOM"),
            ("Avisos",   "HD192"),
            ("Bomberil", "HD193"),
        ]:
            r = self._extra(dec, substr, cod)
            if r is not None:
                extras.append(r)
        # Pago voluntario (col 39) → HDA838
        _pv_col = next((c for c in dec.columns if "39." in c or ("pago voluntario" in c.lower() and "40." not in c)), None)
        if _pv_col:
            t = dec[["consecutivo_cxc", _pv_col]].copy()
            t[_pv_col] = pd.to_numeric(t[_pv_col], errors="coerce")
            t = t[t[_pv_col].notna() & (t[_pv_col] != 0)]
            if not t.empty:
                t = t.rename(columns={_pv_col: "valor_unitario"})
                t["codigo_concepto"] = "HDA838"
                t["valor_total"]     = t["valor_unitario"]
                t["centro_costo"]    = self.CENTRO
                t["cantidad"]        = 1
                extras.append(t[["consecutivo_cxc", "codigo_concepto", "centro_costo",
                                  "cantidad", "valor_unitario", "valor_total"]])

        df_det = pd.concat([ag] + extras, ignore_index=True)

        # ── Ajuste de cierre ─────────────────────────────────────────────────
        # Se suma cada concepto aplicando su signo.
        # diff = suma_con_signos - total_40
        # El total declarado (total_40) es el valor real y nunca se aproxima;
        # el residuo se descuenta del concepto positivo de mayor valor para que
        # sum(conceptos) cierre exactamente contra total_40.
        if tc and "consecutivo_cxc" in df_det.columns:
            for idx, enc_row in df_enc.iterrows():
                consec = enc_row.get("consecutivo_cxc", "")
                total_40 = pd.to_numeric(enc_row.get("total_a_pagar"), errors="coerce")
                if pd.isna(total_40):
                    continue
                sub = df_det[df_det["consecutivo_cxc"] == consec]
                if sub.empty:
                    continue

                signed_sum = round(sum(
                    (pd.to_numeric(r["valor_total"], errors="coerce") or 0)
                    * _SIGNO_DEC.get(str(r["codigo_concepto"]).strip(), +1)
                    for _, r in sub.iterrows()
                ), 2)
                diff = round(signed_sum - total_40, 2)

                if abs(diff) == 0:
                    continue

                pos_sub = sub[sub["codigo_concepto"].apply(
                    lambda c: _SIGNO_DEC.get(str(c).strip(), +1) > 0
                )].copy()
                if pos_sub.empty:
                    continue
                pos_sub["_v"] = pos_sub["valor_total"].apply(
                    lambda x: pd.to_numeric(x, errors="coerce") or 0)
                best_idx = pos_sub["_v"].idxmax()
                new_val = round(float(pos_sub.at[best_idx, "_v"]) - diff, 2)
                df_det.at[best_idx, "valor_unitario"] = new_val
                df_det.at[best_idx, "valor_total"] = new_val

        return df_enc, df_det

    # ── RETE (override para Estrella) ────────────────────────────────────────
    def _rete(self):
        """
        El archivo reteica de Estrella tiene columnas de Base Gravable Y Valor Retenido
        para cada tipo de actividad. Sin el filtro adicional 'RETENIDO', _extra tomaría
        la Base Gravable (que aparece primero y tiene valores mucho más grandes).
        Se usa also="RETENIDO" para forzar la selección de la columna correcta.
        """
        dec = self._leer("declaraciones")
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)

        ano = dec.get("1. Año", dec.get("1.1 Año", 0)).fillna(0)
        c1  = dec.get(cname, 0).fillna(0)
        per = dec.get("1.1 Periodo declarado", dec.get("1. Periodo declarado", "")).fillna("")
        dec["descripcion"] = ("PAGO RETENCIÓN " + per.astype(str) + " AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c1.astype(float).astype(int).astype(str))

        tc = next((c for c in dec.columns if "TOTAL A PAGAR" in c.upper() or "23." in c), None)
        dec["total_a_pagar"] = pd.to_numeric(dec[tc], errors="coerce") if tc else None
        dec["estado_pago"] = dec.get("Estado Pago", "").fillna("").astype(str).str.upper()
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        extras = [e for e in [
            # "RETENIDO" como filtro secundario para evitar tomar columnas de Base Gravable
            self._extra(dec, "INDUSTRIAL", self.CONCEPTO_IND_RETE, also="RETENIDO"),
            self._extra(dec, "COMERCIAL",  self.CONCEPTO_COM_RETE, also="RETENIDO"),
            self._extra(dec, "SERVICIOS",  self.CONCEPTO_SER_RETE, also="RETENIDO"),
            self._extra(dec, "SANCION",    self.CONCEPTO_SAN),
            self._extra(dec, "INTERES",    self.CONCEPTO_INT),
            self._extra(dec, "EXCESO",     self.CONCEPTO_EXC_RETE),
            # Renglón 17.1 = valor retenido (el 17 es la base gravable, no debe cobrarse)
            self._extra(dec, "TARJETA",    self.CONCEPTO_TAR, prefijo=self.PREFIJO_RENGLON_TARJETA),
        ] if e is not None]
        df_det = pd.concat(extras, ignore_index=True) if extras else self._empty_det()
        return df_enc, df_det

    # ── RÉGIMEN SIMPLE (RST) ─────────────────────────────────────────────────
    # Fuente: "Informe Detallado Pagos (giros) ICAC" de DIAN (GIROS ICAC TERRITORIALES -
    # DETALLADO.xlsx). A diferencia de Auto/Rete/Declare, este archivo no trae un
    # consecutivo propio por fila ni se cruza con GOBS: cada carga genera cuentas por
    # cobrar nuevas (serie 908), una por giro.
    _PAT_ACTIVIDAD_RST = re.compile(r"Actividad [Gg]ravada (\d+)")

    def _col_rst(self, df, *claves):
        """Columna cuyo nombre contiene TODAS las claves (sin tildes/mayúsculas) — el
        exportador de DIAN deja tabs sueltos y a veces corrompe la tilde de 'Código'."""
        for c in df.columns:
            cn = self._norm(c)
            if all(self._norm(k) in cn for k in claves):
                return c
        return None

    def _leer_rst(self):
        """El archivo trae unas filas de título/metadatos antes del encabezado real;
        se busca la fila que trae 'Año Gravable' y 'Tipo documento' a la vez."""
        origen = self.archivos["declaraciones"]
        raw = pd.read_excel(origen, header=None, nrows=20)
        # "Año" llega con doble mojibake en este archivo (normaliza distinto cada vez),
        # así que la detección se apoya en "GRAVABLE"/"TIPO DOCUMENTO", que sí llegan intactos.
        header_row = next(
            (i for i, fila in raw.iterrows()
             if any("GRAVABLE" in self._norm(v) for v in fila)
             and any("TIPO DOCUMENTO" in self._norm(v) for v in fila)),
            None)
        if header_row is None:
            raise ValueError(
                "No se encontró la fila de encabezado del archivo de DIAN "
                "(se busca una fila con 'Año Gravable' y 'Tipo documento').")
        df = pd.read_excel(origen, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        return df

    def _slots_actividad_rst(self, df):
        """{n: {'codigo': col, 'impuesto': col}} para cada 'Actividad Gravada n' (hasta 15)."""
        slots = {}
        for c in df.columns:
            m = self._PAT_ACTIVIDAD_RST.search(c)
            if not m:
                continue
            n, cu = int(m.group(1)), c.upper()
            if "IMPUESTO" in cu:
                slots.setdefault(n, {})["impuesto"] = c
            elif "DIGO" in cu or "CIIU" in cu:
                slots.setdefault(n, {})["codigo"] = c
        return {n: s for n, s in slots.items() if "codigo" in s and "impuesto" in s}

    @staticmethod
    def _limpiar_id_rst(v):
        s = str(v).strip()
        if s in ("", "nan", "None"):
            return ""
        try:
            f = float(s)
            if f == int(f):
                return str(int(f))
        except (ValueError, TypeError):
            pass
        return s

    @staticmethod
    def _fecha_rst(v):
        """Las fechas de este archivo llegan como entero AAAAMMDD (p. ej. 20260613.0),
        no como fecha real."""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        try:
            s_entero = str(int(float(s)))
        except (ValueError, TypeError):
            return pd.to_datetime(v, errors="coerce")
        if len(s_entero) == 8:
            return pd.to_datetime(s_entero, format="%Y%m%d", errors="coerce")
        return pd.to_datetime(v, errors="coerce")

    def _siguiente_consecutivo_rst(self, cuantos):
        """El archivo de DIAN no trae consecutivo propio: se asignan números nuevos de
        la serie 908, continuando donde vaya lo más alto entre (a) lo que ya tengamos
        guardado en este proceso y (b) lo que ya exista en el CXC externo más reciente
        (Auto/Rete/Declare comparten el mismo archivo SOFINET) — puede haber números 908
        digitados allá a mano que todavía no están en nuestra base."""
        from etl.models import EncabezadoCXC, InsumoEjecucion, Proceso
        maximo = int(self.PREFIJO_RST + "0" * 7)  # piso de la serie: 9080000000
        proceso = Proceso.objects.filter(municipio=self.municipio, codigo="REGIMEN_SIMPLE").first()
        if proceso:
            for c in EncabezadoCXC.objects.filter(
                    proceso=proceso, consecutivo_cxc__startswith=self.PREFIJO_RST
            ).values_list("consecutivo_cxc", flat=True):
                try:
                    maximo = max(maximo, int(c))
                except ValueError:
                    continue
        ultimo_insumo = (InsumoEjecucion.objects
            .filter(insumo_def__nombre_campo="cxc_csv",
                    insumo_def__proceso__municipio=self.municipio)
            .order_by("-ejecucion__fecha_inicio").first())
        if ultimo_insumo:
            try:
                cxc = self._load_cxc_de(ultimo_insumo.archivo.path)
                rst = cxc[cxc["CONSECUTIVO"].astype(str).str.startswith(self.PREFIJO_RST)]
                if not rst.empty:
                    maximo = max(maximo, rst["CONSECUTIVO"].astype(int).max())
            except Exception:
                pass  # si el CXC externo no se puede leer, se sigue solo con lo propio
        return [str(maximo + 1 + i).zfill(10) for i in range(cuantos)]

    def _regimen_simple(self):
        dec = self._leer_rst()

        col_doc_tipo   = self._col_rst(dec, "Tipo documento")
        col_doc_num    = self._col_rst(dec, "mero de documento")
        col_nombre     = self._col_rst(dec, "Nombre", "Contribuyente")
        col_m          = self._col_rst(dec, "Pago Total ICAC")
        col_n          = self._col_rst(dec, "Intereses ICAC")
        col_o          = self._col_rst(dec, "Sanciones ICAC")
        col_f2593      = self._col_rst(dec, "mero formulario F2593")
        col_ano        = self._col_rst(dec, "o Gravable")
        col_periodo    = self._col_rst(dec, "Periodo del a")
        col_fecha_pago = self._col_rst(dec, "Fecha pago realizado")

        faltantes = [nom for nom, c in [
            ("Tipo documento", col_doc_tipo), ("Número de documento", col_doc_num),
            ("Pago Total ICAC", col_m), ("Año Gravable", col_ano),
        ] if not c]
        if faltantes:
            raise ValueError("No se encontraron columnas esperadas en el archivo de DIAN: "
                             + ", ".join(faltantes))

        # Solo filas de datos reales: DIAN a veces agrega una nota al final del reporte
        # (p. ej. "NO HUBO AJUSTE DE TRANSFERENCIAS") que no es una declaración.
        dec = dec[pd.to_numeric(dec[col_doc_num], errors="coerce").notna()].reset_index(drop=True)

        if dec.empty:
            return pd.DataFrame(columns=["consecutivo_cxc", "consecutivo_original", "tipo_documento",
                                         "numero_documento", "razon_social", "fecha_cobro",
                                         "fecha_vencimiento", "descripcion", "total_a_pagar",
                                         "estado_pago", "estado_cxc", "datos_extra"]), self._empty_det()

        slots = self._slots_actividad_rst(dec)
        consecutivos = self._siguiente_consecutivo_rst(len(dec))

        filas_enc, filas_det = [], []
        for i, (_, row) in enumerate(dec.iterrows()):
            consec = consecutivos[i]

            # Impuesto declarado por tipo de actividad (base del reparto, no el valor a
            # cobrar: ver nota más abajo). Se suman TODAS las actividades que traiga la
            # fila (hasta 15), no solo las dos primeras.
            sums = {"INDUSTRIAL": 0.0, "COMERCIAL": 0.0, "SERVICIOS": 0.0}
            for s in slots.values():
                cod, imp = row.get(s["codigo"]), row.get(s["impuesto"])
                if pd.isna(cod) or imp is None or pd.isna(imp) or float(imp) == 0:
                    continue
                codigo_norm = self._limpiar_id_rst(cod).zfill(4)
                tipo = self._tipo_ciiu(codigo_norm)
                if tipo in sums:
                    sums[tipo] += float(imp)

            m = float(row.get(col_m) or 0)
            n_val = float(row.get(col_n) or 0) if col_n else 0.0
            o_val = float(row.get(col_o) or 0) if col_o else 0.0
            # "Impuesto - Actividad Gravada N" es el valor DECLARADO (anual/consolidado),
            # casi siempre mayor que lo realmente girado — la diferencia son retenciones,
            # autorretenciones y pagos ya practicados por fuera de este giro. Lo único que
            # de verdad hay que cobrar en esta CXC es lo que GIRÓ DIAN (M); el desglose por
            # actividad se usa solo para repartir esa plata EN PROPORCIÓN a cada tipo, no
            # como el valor directo (se verificó contra el archivo real: sumar el impuesto
            # declarado tal cual sobrefactura hasta 1000x en filas con retenciones previas
            # grandes). Sobretasa NUNCA se calcula aquí (ver GIROS ICAC PENDIENTES.xlsx:
            # cada fila le asignaba un código de concepto distinto — HD193, HD194... — en
            # vez de uno fijo, señal de que es un cálculo que se coló por error).
            ica_neto = round(m - n_val - o_val)
            total_declarado = sum(sums.values())
            split = {}
            if total_declarado > 0 and ica_neto:
                split = {k: round(ica_neto * v / total_declarado) for k, v in sums.items() if v}
                diff = round(sum(split.values()) - ica_neto)
                if diff and split:
                    mayor = max(split, key=split.get)
                    split[mayor] -= diff

            MAPA_CONCEPTO = {"INDUSTRIAL": self.CONCEPTO_IND_RST,
                             "COMERCIAL": self.CONCEPTO_COM_RST,
                             "SERVICIOS": self.CONCEPTO_SER_RST}
            for tipo, valor in split.items():
                if valor:
                    filas_det.append({
                        "consecutivo_cxc": consec, "codigo_concepto": MAPA_CONCEPTO[tipo],
                        "centro_costo": self.CENTRO, "cantidad": 1,
                        "valor_unitario": valor, "valor_total": valor,
                    })
            if n_val:
                filas_det.append({
                    "consecutivo_cxc": consec, "codigo_concepto": self.CONCEPTO_INT,
                    "centro_costo": self.CENTRO, "cantidad": 1,
                    "valor_unitario": n_val, "valor_total": n_val,
                })
            if o_val:
                filas_det.append({
                    "consecutivo_cxc": consec, "codigo_concepto": self.CONCEPTO_SAN,
                    "centro_costo": self.CENTRO, "cantidad": 1,
                    "valor_unitario": o_val, "valor_total": o_val,
                })

            ano = self._limpiar_id_rst(row.get(col_ano))
            periodo = self._limpiar_id_rst(row.get(col_periodo)) if col_periodo else ""
            f2593 = self._limpiar_id_rst(row.get(col_f2593)) if col_f2593 else ""
            fecha_cobro = self._fecha_rst(row.get(col_fecha_pago)) if col_fecha_pago else None
            descripcion = "RÉGIMEN SIMPLE ICA AÑO GRAVABLE " + ano
            if periodo:
                descripcion += " PERIODO " + periodo
            if f2593:
                descripcion += " RADICADO F2593 No. " + f2593

            filas_enc.append({
                "consecutivo_cxc": consec, "consecutivo_original": f2593 or consec,
                "tipo_documento": str(row.get(col_doc_tipo) or "").strip().upper(),
                "numero_documento": self._limpiar_id_rst(row.get(col_doc_num)),
                "razon_social": str(row.get(col_nombre) or "").strip() if col_nombre else "",
                "fecha_cobro": fecha_cobro, "fecha_vencimiento": fecha_cobro,
                "descripcion": descripcion,
                "total_a_pagar": round(sum(split.values()) + n_val + o_val),
                # DIAN ya le giró esta plata al municipio antes de que exista este reporte
                # (trae fecha de giro y de pago del contribuyente diligenciadas): se carga
                # como pagada, no como pendiente de cobro.
                "estado_pago": "PAGO REALIZADO", "estado_cxc": "",
                "datos_extra": {"ano": ano, "periodo": periodo, "f2593": f2593},
            })

        df_enc = pd.DataFrame(filas_enc)
        df_det = pd.DataFrame(filas_det) if filas_det else self._empty_det()
        return df_enc, df_det
