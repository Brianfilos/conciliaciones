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

    def _load_cxc(self):
        """
        Parsea el reporte SOFINET multi-sección de CXC.
        Filas de datos: tienen fecha dd/mm/yyyy en col 0.
        CONSECUTIVO = col 5, ESTADO = col 2.
        """
        if "cxc_csv" not in self.archivos:
            return pd.DataFrame(columns=["CONSECUTIVO", "ESTADO"])
        p = self.archivos["cxc_csv"]

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
        dec = pd.read_excel(self.archivos["declaraciones"])
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
        act = pd.read_excel(self.archivos["actividades"])
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
        dec = pd.read_excel(self.archivos["declaraciones"])
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
            self._extra(dec, "TARJETA",    self.CONCEPTO_TAR),
        ] if e is not None]
        df_det = pd.concat(extras, ignore_index=True) if extras else self._empty_det()
        return df_enc, df_det
