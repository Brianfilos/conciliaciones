import traceback
from django.utils import timezone
from django.db import transaction
from etl.models import EncabezadoCXC, DetalleCXC
from etl.services import gobs_pg
import pandas as pd


class MotorETL:
    def __init__(self, ejecucion):
        self.ejecucion = ejecucion
        self.proceso = ejecucion.proceso
        self.municipio = self.proceso.municipio

    def ejecutar(self, archivos, filtros=None):
        self.ejecucion.estado = "EJECUTANDO"
        self.ejecucion.save()
        try:
            archivos = self._completar_desde_gobs(archivos, filtros or {})
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

    def _completar_desde_gobs(self, archivos, filtros):
        """Si el proceso tiene fuente en GOBS, trae declaraciones/actividades de PostgreSQL.
        Un archivo subido a mano tiene prioridad sobre el dato de GOBS."""
        fuente = gobs_pg.fuente_para(self.municipio.codigo, self.proceso.codigo)
        if fuente is None:
            return archivos
        datos, meta = gobs_pg.cargar(fuente, filtros.get("desde"), filtros.get("hasta"))
        rango = " a ".join(str(f) for f in (filtros.get("desde"), filtros.get("hasta")) if f) or "todo"
        nota = (f"[Origen GOBS PostgreSQL: {meta['declaraciones']} declaraciones ({rango}) | "
                f"datos cargados en GOBS al {meta['datos_al']}]")
        self.ejecucion.error_log = nota
        self.ejecucion.save(update_fields=["error_log"])
        return {**datos, **archivos}

    def _get_processor(self, archivos):
        cod  = self.municipio.codigo
        proc = self.proceso.codigo
        if cod == "COPACABANA":
            from etl.services.copacabana import ProcesadorCopacabana
            return ProcesadorCopacabana(proc, archivos, self.municipio)
        elif cod == "ESTRELLA":
            from etl.services.estrella import ProcesadorEstrella
            return ProcesadorEstrella(proc, archivos, self.municipio)
        elif cod == "CALDAS":
            from etl.services.caldas import ProcesadorCaldas
            return ProcesadorCaldas(proc, archivos, self.municipio)
        elif cod == "ENVIGADO":
            from etl.services.envigado import ProcesadorEnvigado
            return ProcesadorEnvigado(proc, archivos, self.municipio)
        elif cod == "SABANETA":
            from etl.services.sabaneta import ProcesadorSabaneta
            return ProcesadorSabaneta(proc, archivos, self.municipio)
        else:
            raise NotImplementedError(f"No hay procesador para municipio: {cod}")

    def _guardar(self, df_enc, df_det):
        def sv(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return ""
            return str(v).strip()

        def sd(v):
            if v is None or v is pd.NaT:
                return None
            try:
                if pd.isna(v):
                    return None
            except Exception:
                pass
            try:
                ts = pd.to_datetime(v, errors="coerce")
                if ts is pd.NaT or pd.isna(ts):
                    return None
                dt = ts.to_pydatetime()
                return dt.date()
            except Exception:
                return None

        def sn(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            try:
                return float(v)
            except Exception:
                return None

        # 1. Un solo query para saber qué consecutivos ya existen
        existing = set(
            EncabezadoCXC.objects
            .filter(proceso=self.proceso)
            .values_list("consecutivo_cxc", flat=True)
        )

        # 2. Pre-agrupar detalles por consecutivo, acumulando mismo concepto+centro
        # Si el ETL produce dos filas con igual (codigo_concepto, centro_costo)
        # para el mismo consecutivo, se suman sus valores en una sola.
        det_by_consec: dict[str, list] = {}
        for _, drow in df_det.iterrows():
            c = str(drow.get("consecutivo_cxc", "")).strip()
            cod = str(drow.get("codigo_concepto", "")).strip()
            cc  = str(drow.get("centro_costo", "")).strip()
            key = (cod, cc)
            bucket = det_by_consec.setdefault(c, {})
            if key in bucket:
                # Acumular valores en la fila existente
                vu_prev = float(bucket[key].get("valor_unitario") or 0)
                vt_prev = float(bucket[key].get("valor_total")   or 0)
                vu_new  = float(drow.get("valor_unitario") or 0)
                vt_new  = float(drow.get("valor_total")   or 0)
                bucket[key]["valor_unitario"] = vu_prev + vu_new
                bucket[key]["valor_total"]    = vt_prev + vt_new
            else:
                bucket[key] = dict(drow)
        # Convertir cada bucket a lista para uso posterior
        det_by_consec = {c: list(b.values()) for c, b in det_by_consec.items()}

        nuevos = actualizados = 0
        detalles_bulk: list[DetalleCXC] = []

        # 3. Todo en una sola transacción
        with transaction.atomic():
            for _, row in df_enc.iterrows():
                consec = str(row.get("consecutivo_cxc", "")).strip()
                if not consec:
                    continue

                extra = row.get("datos_extra", {})
                if not isinstance(extra, dict):
                    extra = {}

                # Campos comunes del encabezado
                campos = dict(
                    consecutivo_original = sv(row.get("consecutivo_original", "")),
                    tipo_documento       = sv(row.get("tipo_documento", "")),
                    numero_documento     = sv(row.get("numero_documento", "")),
                    primer_nombre        = sv(row.get("primer_nombre", "")),
                    segundo_nombre       = sv(row.get("segundo_nombre", "")),
                    primer_apellido      = sv(row.get("primer_apellido", "")),
                    segundo_apellido     = sv(row.get("segundo_apellido", "")),
                    razon_social         = sv(row.get("razon_social", "")),
                    fecha_cobro          = sd(row.get("fecha_cobro")),
                    fecha_vencimiento    = sd(row.get("fecha_vencimiento")),
                    descripcion          = sv(row.get("descripcion", "")),
                    total_a_pagar        = sn(row.get("total_a_pagar")),
                    estado_pago          = sv(row.get("estado_pago", "")),
                    estado_cxc           = sv(row.get("estado_cxc", "")),
                    datos_extra          = extra,
                )

                if consec in existing:
                    # Actualización completa: todos los campos del encabezado + conceptos
                    enc_qs = EncabezadoCXC.objects.filter(
                        proceso=self.proceso, consecutivo_cxc=consec)
                    enc_qs.update(**campos)
                    enc_obj = enc_qs.first()
                    if enc_obj:
                        enc_obj.detalles.all().delete()
                        for drow in det_by_consec.get(consec, []):
                            detalles_bulk.append(DetalleCXC(
                                encabezado=enc_obj,
                                codigo_concepto=sv(drow.get("codigo_concepto", "")),
                                centro_costo=sv(drow.get("centro_costo", "")),
                                cantidad=int(drow.get("cantidad", 1) or 1),
                                valor_unitario=sn(drow.get("valor_unitario")),
                                valor_total=sn(drow.get("valor_total")),
                            ))
                    actualizados += 1
                    continue

                # Registro nuevo
                enc = EncabezadoCXC.objects.create(
                    proceso=self.proceso,
                    ejecucion=self.ejecucion,
                    consecutivo_cxc=consec,
                    **campos,
                )
                existing.add(consec)  # evita IntegrityError si aparece dos veces en el lote

                for drow in det_by_consec.get(consec, []):
                    detalles_bulk.append(DetalleCXC(
                        encabezado=enc,
                        codigo_concepto=sv(drow.get("codigo_concepto", "")),
                        centro_costo=sv(drow.get("centro_costo", "")),
                        cantidad=int(drow.get("cantidad", 1) or 1),
                        valor_unitario=sn(drow.get("valor_unitario")),
                        valor_total=sn(drow.get("valor_total")),
                    ))
                nuevos += 1

            # 4. Insertar todos los detalles de una sola vez
            if detalles_bulk:
                DetalleCXC.objects.bulk_create(detalles_bulk, batch_size=500)

        self.ejecucion.registros_nuevos       = nuevos
        self.ejecucion.registros_duplicados   = actualizados  # antes "duplicados", ahora son actualizaciones
        if actualizados:
            nota = f"[Actualizados: {actualizados} | Nuevos: {nuevos}]"
            self.ejecucion.error_log = (nota + "\n" + (self.ejecucion.error_log or "")).strip()
        self.ejecucion.save()
