import math as _math
import pandas as pd
from etl.services.base import ProcesadorBase


class ProcesadorCopacabana(ProcesadorBase):
    PREFIJO      = "903"
    CSV_SEP      = ","
    CONSEC_COL   = "Consecutivo 1"
    CENTRO       = "1501"
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

    # ── DECLARE Y PAGUE (override para Copa) ────────────────────────────────
    def _declare(self):
        dec = pd.read_excel(self.archivos["declaraciones"])
        cname = self._resolve_consec_col(dec)
        dec["consecutivo_cxc"] = self._cxc_id(dec[cname])
        dec = self._base_rename(dec, cname)

        ano = dec.get("Año Gravable", pd.Series([0] * len(dec))).fillna(0)
        c2  = dec.get("Consecutivo 2", pd.Series([0] * len(dec))).fillna(0)
        dec["descripcion"] = ("DECLARE Y PAGUE AÑO GRAVABLE "
                              + ano.astype(float).astype(int).astype(str)
                              + " Radicado No. " + c2.astype(float).astype(int).astype(str))

        def _fc(cols, n):
            c = next((c for c in cols if f"{n}." in c), None)
            if c is None:
                c = next((c for c in cols
                          if c.strip().startswith(f"{n} ") or c.strip().startswith(f"{n}.")), None)
            return c

        tc = _fc(dec.columns, "40")
        dec["total_a_pagar"] = pd.to_numeric(dec[tc], errors="coerce") if tc else None
        dec["estado_pago"] = (dec.get("Estado Pago", pd.Series([""] * len(dec)))
                               .fillna("").astype(str).str.upper())
        dec = self._merge_cxc(dec)
        df_enc = self._enc(dec)

        # ── Actividades (ICA por CIIU) ─────────────────────────────────────
        act = pd.read_excel(self.archivos["actividades"])
        cc = next((c for c in act.columns if "CODIFIC" in c.upper() or "CODIGO" in c.upper()), None)
        if cc:
            act["codigo"] = act[cc].astype(str).apply(
                lambda v: (v.split(" - ", 1)[0].strip().zfill(4) if " - " in v
                           else v.split(" -", 1)[0].strip().zfill(4) if " -" in v
                           else v.strip().zfill(4)))

        ic_col = next((c for c in act.columns
                       if "INDUSTRIA" in c.upper() and "COMERCIO" in c.upper()), None)
        if not ic_col:
            ic_col = next((c for c in act.columns if "IMPUESTO" in c.upper()), None)

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
        MAPA = {
            "INDUSTRIAL": self.CONCEPTO_IND_DEC,
            "COMERCIAL":  self.CONCEPTO_COM_DEC,
            "SERVICIOS":  self.CONCEPTO_SER_DEC,
        }
        act["codigo_concepto"] = act["TIPO"].map(MAPA).fillna("")

        if ic_col and "consecutivo_cxc" in act.columns:
            ag = act.groupby(["consecutivo_cxc", "codigo_concepto"])[ic_col].sum().reset_index()
            ag.rename(columns={ic_col: "valor_unitario"}, inplace=True)
            ag["valor_total"]  = ag["valor_unitario"]
            ag["centro_costo"] = self.CENTRO
            ag["cantidad"]     = 1
        else:
            ag = self._empty_det()

        # ── Avisos, Bomberil, Sanciones, Intereses (lectura directa por col) ──
        avi_col = next((c for c in dec.columns if "21." in c and "AVISO" in c.upper()), None)
        bom_col = next((c for c in dec.columns if "23." in c and "BOMBERIL" in c.upper()), None)
        # Sanciones: columna "Digite valor sanciones" o cualquier col con "SANCION" y valor numérico
        san_col = next((c for c in dec.columns
                        if "DIGIT" in c.upper() and "SANCION" in c.upper()), None) or \
                  next((c for c in dec.columns
                        if "SANCION" in c.upper() and "TIPO" not in c.upper()), None)
        int_col = next((c for c in dec.columns if "37." in c and "INTERES" in c.upper()), None)

        extras = []
        for col, concepto in [
            (avi_col, "10101"),
            (bom_col, "10111"),
            (san_col, self.CONCEPTO_SAN),
            (int_col, self.CONCEPTO_INT),
        ]:
            if not col:
                continue
            t = dec[["consecutivo_cxc", col]].copy()
            t[col] = pd.to_numeric(t[col], errors="coerce")
            t = t[t[col].notna() & (t[col] != 0)]
            if t.empty:
                continue
            t = t.rename(columns={col: "valor_unitario"})
            t["codigo_concepto"] = concepto
            t["valor_total"]     = t["valor_unitario"]
            t["centro_costo"]    = self.CENTRO
            t["cantidad"]        = 1
            extras.append(t[["consecutivo_cxc", "codigo_concepto", "centro_costo",
                              "cantidad", "valor_unitario", "valor_total"]])

        # ── Splits proporcionales (retenciones, autorretenciones, anticipo, voluntario) ──
        # Porcentaje = ICA_tipo / col_17  (base desde la declaración, igual que el script original)
        col17 = _fc(dec.columns, "17")
        col26 = _fc(dec.columns, "26")
        col27 = _fc(dec.columns, "27")
        col28 = _fc(dec.columns, "28")
        col29 = _fc(dec.columns, "29")
        col39 = _fc(dec.columns, "39")

        MAPA_EXON = {self.CONCEPTO_IND_DEC: self.CONCEPTO_IND_EXON,
                     self.CONCEPTO_COM_DEC: self.CONCEPTO_COM_EXON,
                     self.CONCEPTO_SER_DEC: self.CONCEPTO_SER_EXON}
        MAPA_RETE = {self.CONCEPTO_IND_DEC: "10150", self.CONCEPTO_COM_DEC: "10151", self.CONCEPTO_SER_DEC: "10152"}
        MAPA_AUTO = {self.CONCEPTO_IND_DEC: "10140", self.CONCEPTO_COM_DEC: "10139", self.CONCEPTO_SER_DEC: "10141"}
        MAPA_ANTI = {self.CONCEPTO_IND_DEC: "10137", self.CONCEPTO_COM_DEC: "10136ANT", self.CONCEPTO_SER_DEC: "10138"}
        MAPA_VOL  = {self.CONCEPTO_IND_DEC: "10148", self.CONCEPTO_COM_DEC: "10147",  self.CONCEPTO_SER_DEC: "10149"}

        split_extras = []
        if not ag.empty and "consecutivo_cxc" in ag.columns and col17:
            tot17 = dec[["consecutivo_cxc", col17]].copy()
            tot17[col17] = pd.to_numeric(tot17[col17], errors="coerce")

            ag_pct = ag[["consecutivo_cxc", "codigo_concepto", "valor_unitario"]].merge(
                tot17, on="consecutivo_cxc", how="left")
            ag_pct["pct"] = ag_pct.apply(
                lambda r: (r["valor_unitario"] / r[col17]
                           if pd.notna(r[col17]) and r[col17] != 0 else 0),
                axis=1)

            # negate=True  → concepto con signo "-" (deducción): siempre negativo
            # negate=False → concepto con signo "+" (adición):   siempre positivo
            for src_col, mapa, negate in [
                (col26, MAPA_EXON, True),   # Exoneración      10166/67/68  (-)
                (col27, MAPA_RETE, True),   # Retenciones      10150/51/52  (-)
                (col28, MAPA_AUTO, True),   # Autorretenciones 10139/40/41  (-)
                (col29, MAPA_ANTI, True),   # Anticipos        10136ANT/37/38 (-)
                (col39, MAPA_VOL,  False),  # Pago voluntario  10147/48/49  (+)
            ]:
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
                # Forzar signo correcto independiente del signo en la fuente
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
        # Se usa el valor exacto del renglón 40 sin aproximar.
        if tc and "consecutivo_cxc" in df_det.columns:
            for idx, enc_row in df_enc.iterrows():
                consec   = str(enc_row.get("consecutivo_cxc", "")).strip()
                total_40 = pd.to_numeric(enc_row.get("total_a_pagar"), errors="coerce")
                if pd.isna(total_40):
                    continue
                sub = df_det[df_det["consecutivo_cxc"].astype(str).str.strip() == consec]
                if sub.empty:
                    continue
                signed_sum = round(
                    sub["valor_total"]
                    .apply(lambda x: pd.to_numeric(x, errors="coerce"))
                    .fillna(0).sum(), 2)
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
