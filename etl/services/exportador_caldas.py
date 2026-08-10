"""
Exportador SAIMYR para Caldas — formato de 19 columnas planas.
Una fila por detalle, con la info del tercero repetida en cada fila.
"""

# ── Descripciones de conceptos ────────────────────────────────────────────────
# Para conceptos cuya descripción depende de la clasificación (I/C/S/T)
# clave: (codigo_concepto, clasificacion) o (codigo_concepto, "")
_DESC_CLASI = {
    # AUTO — OCC-209
    ("OCC-209", "I"): "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES INDUSTRIALES",
    ("OCC-209", "C"): "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES COMERCIALES",
    ("OCC-209", "S"): "RETENCIÓN INDUSTRIA Y COMERCIO ACTIVIDADES DE SERVICIO",
    ("OCC-209", "X"): "RETENCIÓN O AUTORRETENCIÓN PRACTICADA EN EXCESO",
    # RETE — OCC-993
    ("OCC-993", "I"): "RETENCION DE INDUSTRIA Y COMERCIO ACTIVIDADES INDUSTRIALES",
    ("OCC-993", "C"): "RETENCION DE INDUSTRIA Y COMERCIO ACTIVIDADES COMERCIALES",
    ("OCC-993", "S"): "RETENCION DE INDUSTRIA Y COMERCIO ACTIVIDADES DE SERVICIO",
    ("OCC-993", "T"): "RETENCIÓN SISTEMA TARJETAS Y MEDIOS DE PAGO",
    ("OCC-993", ""):  "RETENCIONES DECLARACION ANUAL ICA",
    # DECLARE Y PAGUE — actividades ICA
    ("OCC-0048", "I"): "INDUSTRIA Y COMERCIO INDUSTRIA",
    ("OCC-0047", "C"): "INDUSTRIA Y COMERCIO COMERCIAL",
    ("OCC-046",  "S"): "INDUSTRIA Y COMERCIO SERVICIO",
}

# Para conceptos cuya descripción NO depende de la clasificación
_DESC_FIJA = {
    "OCC-04":  "SANCION POR EXTEMPORANEIDAD",
    "OCC-05":  "SANCION POR CORRECCION",
    "OCC-06":  "SANCION POR EMPLAZAMIENTO",
    "OCC-07":  "SANCION POR NO DECLARAR",
    "OCC-08":  "SANCION POR CORRECCION ARITMETICA",
    "OCC-09":  "SANCION POR INEXACTITUD",
    "OCC-10":  "SANCION POR NO ENVIAR INFORMACION",
    "OCC-23":  "INTERESES INDUSTRIA Y COMERCIO",
    "OCC-051": "SOBRETASA BOMBERIL",
    "OCC-209": "MULTAS Y SANCIONES DE INDUSTRIA Y COMERCIO",  # fallback OCC-209 sin clasi
    "OCC-69":  "AVISOS Y TABLEROS",
    "69":      "AVISOS Y TABLEROS",
}

HEADERS = [
    "radicado_externo", "comprobante_pago", "Fecha_pago", "Tipo Persona",
    "tipo_documento_id", "DI_Tercero", "dv",
    "Priemr_apelledo_tercero", "Segundo_apelledo_tercero", "nombres_tercero",
    "dir_tercero", "tel_tercero", "email_tercero",
    "clasificacion", "concepto_externo", "código_cpto_saimyr",
    "valor_pagado", "código_banco", "número_cuenta",
]

# Encabezado de 32 columnas para declaraciones AUTO y RETE
HEADERS_DEC = [
    "radicado_externo", "año", "año_declarado", "Bimestre_declarado",
    "tipo_declaracion", "Código_establecimiento", "Tipo_persona", "DI_declarante", "DV",
    "Primer_apellido", "Segundo_apellido", "Nombre", "Razón_social",
    "Direccion", "Telefono", "Email", "Tipo_empresa",
    "Vlr_tot_reten", "Vlr_tot_devolución", "Vle_tot_sancion",
    "Vlr_total_interese", "Vlr_total_a_pagar",
    "contrador_o_revisor", "DI_c_o_r", "nombre_c_o_r", "Nro_tarj_prof_c_o_r",
    "Firma_declarante", "Firma_c_o_r", "Estado", "Fecha_registro",
    "Contribuyente", "Retencion_autoretencion",
]


def _desc(codigo_concepto, clasificacion):
    clasi = (clasificacion or "").strip()
    desc = _DESC_CLASI.get((codigo_concepto, clasi))
    if desc:
        return desc
    # intenta sin clasificación (fallback a vacío)
    desc = _DESC_CLASI.get((codigo_concepto, ""))
    if desc:
        return desc
    return _DESC_FIJA.get(codigo_concepto, codigo_concepto)


HEADERS_DEC_ICA = [
    "radicado_externo", "Nit", "Código_establecimiento", "fecha_declaracion", "tipo",
    "fecha_presentacion", "medio_presentacion", "año_declaracion", "año_gravable",
    "tipo_declaracion", "razon_social", "clase", "direccion", "telefono", "tipo_persona",
    "tipo_contribuyente", "fecha_matricula", "email",
    "vlr_total base_gravable", "vlr_total_iyc_anual",
    "DI_rep_legal", "nombre_representante_legal", "contrador_o_revisor",
    "DI_c_o_r", "nombre_c_o_r", "Nro_tarj_prof_c_o_r",
    "vlr_exoneracion", "vlr_sucursales", "vlr_gen_energia",
    "vlr_retencion", "vlr_autorretencion", "vlr_anticipo_anterior", "vlr_anticipo_siguiente",
    "vlr_sanciones", "vlr_saldo_favor", "vlr_interes_mora", "total_a_pagar",
    "vlr_AVISOS Y TABLEROS", "vlr_SOBRETASA BOMBERIL",
]

OCC_ICA_SET  = {"OCC-0048", "OCC-0047", "OCC-046"}
OCC_RET_SET  = {"OCC-993"}
OCC_AUT_SET  = {"OCC-209"}
OCC_SAN_SET  = {"OCC-04","OCC-05","OCC-06","OCC-07","OCC-08","OCC-09","OCC-10"}
OCC_INT_SET  = {"OCC-23"}
OCC_BOM_SET  = {"OCC-051"}
OCC_AVI_SET  = {"69"}


def _totales_ica(enc):
    """Calcula totales financieros de un EncabezadoCXC ICA a partir de sus detalles."""
    t = {"iyc": 0, "ret": 0, "aut": 0, "ant": 0, "san": 0, "int": 0, "bom": 0, "avi": 0, "clase": set()}
    for det in enc.detalles.all():
        v = float(det.valor_total or 0)
        c = det.codigo_concepto or ""
        clasi = (det.centro_costo or "").strip()
        if c in OCC_ICA_SET:
            t["iyc"] += v
            if clasi:
                t["clase"].add(clasi)
        elif c in OCC_RET_SET:
            t["ret"] += abs(v)
        elif c in OCC_AUT_SET:
            t["aut"] += abs(v)
        elif c in OCC_SAN_SET:
            t["san"] += v
        elif c in OCC_INT_SET:
            t["int"] += v
        elif c in OCC_BOM_SET:
            t["bom"] += v
        elif c in OCC_AVI_SET:
            t["avi"] += v
    t["clase"] = "/".join(sorted(t["clase"]))
    return t


def build_dec_rows(proceso, filtros=None):
    """
    Devuelve (headers, rows):
    - AUTO / RETE → 32 cols (HEADERS_DEC)
    - ICA (DECLAREYPAGUE) → 39 cols (HEADERS_DEC_ICA)
    """
    from etl.models import EncabezadoCXC, DetalleCXC

    filtros = filtros or {}
    qs = EncabezadoCXC.objects.filter(proceso=proceso).prefetch_related("detalles")

    q = filtros.get("q", "")
    if q:
        qs = (qs.filter(consecutivo_cxc__icontains=q) |
              qs.filter(numero_documento__icontains=q) |
              qs.filter(primer_apellido__icontains=q) |
              qs.filter(razon_social__icontains=q))
    if filtros.get("q_consec"):
        qs = qs.filter(consecutivo_cxc__icontains=filtros["q_consec"])
    if filtros.get("q_num"):
        qs = qs.filter(numero_documento__icontains=filtros["q_num"])
    if filtros.get("q_nombre"):
        qn = filtros["q_nombre"]
        qs = (qs.filter(primer_apellido__icontains=qn) |
              qs.filter(primer_nombre__icontains=qn) |
              qs.filter(razon_social__icontains=qn))
    if filtros.get("fecha_desde"):
        qs = qs.filter(fecha_cobro__gte=filtros["fecha_desde"])
    if filtros.get("fecha_hasta"):
        qs = qs.filter(fecha_cobro__lte=filtros["fecha_hasta"])
    if filtros.get("estado"):
        qs = qs.filter(estado_cxc__iexact=filtros["estado"])
    if filtros.get("estado_pago"):
        qs = qs.filter(estado_pago__icontains=filtros["estado_pago"])
    if filtros.get("caldas_tipo_persona"):
        qs = qs.filter(datos_extra__tipo_persona=filtros["caldas_tipo_persona"])
    if filtros.get("caldas_periodo"):
        qs = qs.filter(datos_extra__periodo=filtros["caldas_periodo"])
    if filtros.get("caldas_ano"):
        qs = qs.filter(datos_extra__ano=filtros["caldas_ano"])

    cod = proceso.codigo.upper()
    es_ica = "DECLARE" in cod

    if es_ica:
        # ── ICA: formato 124 columnas — leer archivos originales de la última ejecución ──
        import os, django
        from etl.models import Ejecucion, InsumoEjecucion
        import pandas as pd
        from django.conf import settings

        # Obtener archivos de la última ejecución
        ej = Ejecucion.objects.filter(proceso=proceso, estado="COMPLETADO").first()
        archivos = {}
        if ej:
            for ins in InsumoEjecucion.objects.filter(ejecucion=ej):
                archivos[ins.insumo_def.nombre_campo] = ins.archivo.path

        if "declaraciones" not in archivos or "actividades" not in archivos:
            # Fallback a 39 columnas si no hay archivos
            rows = []
            for enc in qs:
                extra = enc.datos_extra or {}
                t = _totales_ica(enc)
                fecha = enc.fecha_cobro.strftime("%d/%m/%Y %H:%M:%S") if enc.fecha_cobro else ""
                ano = extra.get("ano", "")
                rows.append([enc.consecutivo_cxc, enc.numero_documento, "", fecha, "DEC", fecha, "W",
                    ano, ano, extra.get("tipo_dec",""), enc.razon_social or enc.primer_nombre,
                    t["clase"], extra.get("dir_tercero",""), extra.get("tel_tercero",""),
                    extra.get("tipo_persona",""), "", "", extra.get("email_tercero",""),
                    "", t["iyc"] or "", "", "", "", "", "", "", "", "", "",
                    t["ret"] or "", t["aut"] or "", "", "", t["san"] or "", "",
                    t["int"] or "", enc.total_a_pagar, t["avi"] or "", t["bom"] or ""])
            return HEADERS_DEC_ICA, rows

        # Leer archivos originales
        dec_df = pd.read_excel(archivos["declaraciones"])
        act_df = pd.read_excel(archivos["actividades"])
        dec_df.columns = [c.strip() for c in dec_df.columns]
        act_df.columns = [c.strip() for c in act_df.columns]

        # Indexar actividades por consecutivo
        con_col = next((c for c in act_df.columns if "Consecutivo" in c), None)
        if con_col:
            act_df["_consec"] = act_df[con_col].apply(
                lambda v: str(int(float(v))) if pd.notna(v) and str(v).replace(".","",1).isdigit() else "")

        # Columnas CIIU en actividades
        ciiu_cols = [c for c in act_df.columns if "CIIU" in c.upper() or "CODIF" in c.upper() or "CODIGO" in c.upper()]
        ing_col   = next((c for c in act_df.columns if "INGRESO" in c.upper() or "ING" in c.upper()), None)
        tar_col   = next((c for c in act_df.columns if "TARIFA" in c.upper()), None)
        iyc_col   = next((c for c in act_df.columns if "IMPUESTO" in c.upper() and "IND" in c.upper()), None) or \
                    next((c for c in act_df.columns if "IMPUESTO" in c.upper()), None)

        # Mapa: consecutivo_original (número crudo del Excel) → consecutivo_cxc (prefijado)
        orig_to_cxc = {
            str(orig).strip(): cxc
            for orig, cxc in qs.values_list("consecutivo_original", "consecutivo_cxc")
            if orig
        }

        # Agrupar actividades por consecutivo_cxc usando el original como clave de join
        act_by_consec = {}
        if con_col:
            for _, arow in act_df.iterrows():
                c_raw = arow.get("_consec", "")
                cxc = orig_to_cxc.get(str(c_raw).strip())
                if cxc:
                    act_by_consec.setdefault(cxc, []).append(arow)

        # Headers ICA completos: 124 columnas del formato
        from etl.services.exportador_caldas import HEADERS_DEC_ICA as _ICA_H
        # Añadir hasta 15 bloques CIIU (5 cols cada uno)
        full_headers = list(HEADERS_DEC_ICA)
        for i in range(1, 16):
            for suffix in [f"Codigo_CIIU_{i}", f"vlr_ing_CIIU_{i}", f"tarifa_CIIU_{i}",
                           f"vlr_IyC_anual_CIIU_{i}", f"porc_ingreso_CIIU_{i}"]:
                full_headers.append(suffix)

        rows = []
        for enc in qs:
            extra = enc.datos_extra or {}
            t = _totales_ica(enc)
            fecha = enc.fecha_cobro.strftime("%d/%m/%Y %H:%M:%S") if enc.fecha_cobro else ""
            ano = extra.get("ano", "")

            base_row = [
                enc.consecutivo_cxc,                        # radicado_externo
                enc.numero_documento,                        # Nit
                "",                                          # Código_establecimiento
                fecha,                                       # fecha_declaracion
                "DEC",                                       # tipo
                fecha,                                       # fecha_presentacion
                "W",                                         # medio_presentacion
                ano,                                         # año_declaracion
                ano,                                         # año_gravable
                extra.get("tipo_dec", ""),                   # tipo_declaracion
                enc.razon_social or enc.primer_nombre,       # razon_social
                t["clase"],                                  # clase
                extra.get("dir_tercero", ""),                # direccion
                extra.get("tel_tercero", ""),                # telefono
                extra.get("tipo_persona", ""),               # tipo_persona
                "",                                          # tipo_contribuyente
                "",                                          # fecha_matricula
                extra.get("email_tercero", ""),              # email
                "",                                          # vlr_total base_gravable
                t["iyc"] or "",                             # vlr_total_iyc_anual
                "",                                          # DI_rep_legal
                "",                                          # nombre_representante_legal
                "",                                          # contrador_o_revisor
                "",                                          # DI_c_o_r
                "",                                          # nombre_c_o_r
                "",                                          # Nro_tarj_prof_c_o_r
                "",                                          # vlr_exoneracion
                "",                                          # vlr_sucursales
                "",                                          # vlr_gen_energia
                t["ret"] or "",                             # vlr_retencion
                t["aut"] or "",                             # vlr_autorretencion
                "",                                          # vlr_anticipo_anterior
                "",                                          # vlr_anticipo_siguiente
                t["san"] or "",                             # vlr_sanciones
                "",                                          # vlr_saldo_favor
                t["int"] or "",                             # vlr_interes_mora
                enc.total_a_pagar,                           # total_a_pagar
                t["avi"] or "",                             # vlr_AVISOS Y TABLEROS
                t["bom"] or "",                             # vlr_SOBRETASA BOMBERIL
            ]

            # Agregar bloques CIIU desde actividades (hasta 15)
            acts = act_by_consec.get(enc.consecutivo_cxc, [])
            ciiu_col_act = ciiu_cols[0] if ciiu_cols else None
            for i in range(15):
                if i < len(acts):
                    arow = acts[i]
                    codigo = str(arow.get(ciiu_col_act, "")).strip() if ciiu_col_act else ""
                    ing    = arow.get(ing_col, "") if ing_col else ""
                    tar    = arow.get(tar_col, "") if tar_col else ""
                    iyc    = arow.get(iyc_col, "") if iyc_col else ""
                    total_iyc = t["iyc"] or 1
                    try:
                        porc = round(float(iyc) / total_iyc * 100, 2) if total_iyc and float(iyc) else ""
                    except Exception:
                        porc = ""
                    base_row.extend([codigo, ing, tar, iyc, porc])
                else:
                    base_row.extend(["", "", "", "", ""])

            rows.append(base_row)
        return full_headers, rows

    # ── AUTO / RETE: formato 32 columnas ─────────────────────────────────────
    if "RETE" in cod:
        ret_auto = "R"
        OCC_RETEN = {"OCC-993"}
    else:
        ret_auto = "A"
        OCC_RETEN = {"OCC-209"}
    OCC_SANCIONES = {"OCC-04","OCC-05","OCC-06","OCC-07","OCC-08","OCC-09","OCC-10"}
    OCC_INTERESES = {"OCC-23"}

    rows = []
    for enc in qs:
        extra = enc.datos_extra or {}
        vlr_reten = vlr_exc = vlr_san = vlr_int = 0.0
        for det in enc.detalles.all():
            v = float(det.valor_total or 0)
            c = det.codigo_concepto or ""
            if c in OCC_RETEN:
                (vlr_reten := vlr_reten + v) if v >= 0 else (vlr_exc := vlr_exc + abs(v))
            elif c in OCC_SANCIONES:
                vlr_san += v
            elif c in OCC_INTERESES:
                vlr_int += v

        fecha_reg = enc.fecha_cobro.strftime("%d/%m/%Y %H:%M:%S") if enc.fecha_cobro else ""
        ano_val = extra.get("ano", "")
        try:
            ano_declarado = int(ano_val) if ano_val else ""
        except Exception:
            ano_declarado = ano_val

        rows.append([
            enc.consecutivo_cxc,           # radicado_externo
            ano_val,                        # año
            ano_declarado,                  # año_declarado
            extra.get("periodo", ""),       # Bimestre_declarado
            extra.get("tipo_dec", ""),      # tipo_declaracion
            "",                             # Código_establecimiento
            extra.get("tipo_persona", ""),  # Tipo_persona
            enc.numero_documento,           # DI_declarante
            "",                             # DV
            enc.primer_apellido,            # Primer_apellido
            enc.segundo_apellido,           # Segundo_apellido
            enc.primer_nombre,              # Nombre
            enc.razon_social,               # Razón_social
            extra.get("dir_tercero", ""),   # Direccion
            extra.get("tel_tercero", ""),   # Telefono
            extra.get("email_tercero", ""), # Email
            "",                             # Tipo_empresa
            vlr_reten or "",               # Vlr_tot_reten
            vlr_exc or "",                 # Vlr_tot_devolución
            vlr_san or "",                 # Vle_tot_sancion
            vlr_int or "",                 # Vlr_total_interese
            enc.total_a_pagar,             # Vlr_total_a_pagar
            "",                             # contrador_o_revisor
            "",                             # DI_c_o_r
            "",                             # nombre_c_o_r
            "",                             # Nro_tarj_prof_c_o_r
            "S",                            # Firma_declarante
            "",                             # Firma_c_o_r
            "W",                            # Estado
            fecha_reg,                      # Fecha_registro
            "",                             # Contribuyente
            ret_auto,                       # Retencion_autoretencion
        ])
    return HEADERS_DEC, rows


def build_rows(proceso, filtros=None):
    """
    Devuelve (HEADERS, rows) con el formato SAIMYR de 19 columnas.
    filtros: dict con claves opcionales: q, fecha_desde, fecha_hasta, estado
    """
    from etl.models import EncabezadoCXC

    filtros = filtros or {}
    qs = EncabezadoCXC.objects.filter(proceso=proceso).prefetch_related("detalles")

    q = filtros.get("q", "")
    if q:
        qs = (qs.filter(consecutivo_cxc__icontains=q) |
              qs.filter(numero_documento__icontains=q) |
              qs.filter(primer_apellido__icontains=q) |
              qs.filter(razon_social__icontains=q))
    if filtros.get("q_consec"):
        qs = qs.filter(consecutivo_cxc__icontains=filtros["q_consec"])
    if filtros.get("q_num"):
        qs = qs.filter(numero_documento__icontains=filtros["q_num"])
    if filtros.get("q_nombre"):
        qn = filtros["q_nombre"]
        qs = (qs.filter(primer_apellido__icontains=qn) |
              qs.filter(primer_nombre__icontains=qn) |
              qs.filter(razon_social__icontains=qn))
    if filtros.get("fecha_desde"):
        qs = qs.filter(fecha_cobro__gte=filtros["fecha_desde"])
    if filtros.get("fecha_hasta"):
        qs = qs.filter(fecha_cobro__lte=filtros["fecha_hasta"])
    if filtros.get("estado"):
        qs = qs.filter(estado_cxc__iexact=filtros["estado"])
    if filtros.get("estado_pago"):
        qs = qs.filter(estado_pago__icontains=filtros["estado_pago"])
    if filtros.get("caldas_tipo_persona"):
        qs = qs.filter(datos_extra__tipo_persona=filtros["caldas_tipo_persona"])
    if filtros.get("caldas_periodo"):
        qs = qs.filter(datos_extra__periodo=filtros["caldas_periodo"])
    if filtros.get("caldas_ano"):
        qs = qs.filter(datos_extra__ano=filtros["caldas_ano"])
    caldas_clasi = filtros.get("caldas_clasi", "")
    if caldas_clasi:
        qs = qs.filter(detalles__centro_costo__icontains=caldas_clasi).distinct()

    MAIN_OCCS = {"OCC-993", "OCC-209", "OCC-0048", "OCC-0047", "OCC-046"}

    rows = []
    for enc in qs:
        extra = enc.datos_extra or {}
        d = enc.fecha_cobro
        fecha = d.strftime("%d/%m/%Y") if d else ""

        # Clasificación del concepto principal (I/C/S) para heredar a sanciones/intereses
        detalles = list(enc.detalles.all())
        enc_clasi = next(
            ((det.centro_costo or "").strip()
             for det in detalles
             if det.codigo_concepto in MAIN_OCCS and (det.centro_costo or "").strip()),
            ""
        )

        for det in detalles:
            if caldas_clasi and (det.centro_costo or "").strip().upper() != caldas_clasi.upper():
                continue
            clasi = (det.centro_costo or "").strip() or enc_clasi
            rows.append([
                enc.consecutivo_cxc,                    # radicado_externo
                enc.consecutivo_cxc,                    # comprobante_pago
                fecha,                                  # Fecha_pago
                extra.get("tipo_persona", ""),          # Tipo Persona
                enc.tipo_documento,                     # tipo_documento_id
                enc.numero_documento,                   # DI_Tercero
                extra.get("dv", ""),                    # dv
                enc.primer_apellido,                    # Priemr_apelledo_tercero
                enc.segundo_apellido,                   # Segundo_apelledo_tercero
                enc.primer_nombre,                      # nombres_tercero
                extra.get("dir_tercero", ""),           # dir_tercero
                extra.get("tel_tercero", ""),           # tel_tercero
                extra.get("email_tercero", ""),         # email_tercero
                clasi,                                  # clasificacion
                _desc(det.codigo_concepto, clasi),      # concepto_externo
                det.codigo_concepto,                    # código_cpto_saimyr
                f"{float(det.valor_total):.2f}" if det.valor_total is not None else "0.00",  # valor_pagado
                extra.get("codigo_banco", "1"),         # código_banco
                extra.get("numero_cuenta", "2"),        # número_cuenta
            ])
    return HEADERS, rows