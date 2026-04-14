import traceback
from django.utils import timezone
from django.db import transaction
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
        elif cod == "CALDAS":
            from etl.services.caldas import ProcesadorCaldas
            return ProcesadorCaldas(proc, archivos, self.municipio)
        elif cod == "ENVIGADO":
            from etl.services.envigado import ProcesadorEnvigado
            return ProcesadorEnvigado(proc, archivos, self.municipio)
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

        # 2. Pre-agrupar detalles por consecutivo en un dict (evita N filtros pandas)
        det_by_consec: dict[str, list] = {}
        for _, drow in df_det.iterrows():
            c = str(drow.get("consecutivo_cxc", "")).strip()
            det_by_consec.setdefault(c, []).append(drow)

        nuevos = duplicados = actualizados = 0
        detalles_bulk: list[DetalleCXC] = []

        # 3. Todo en una sola transacción
        with transaction.atomic():
            for _, row in df_enc.iterrows():
                consec = str(row.get("consecutivo_cxc", "")).strip()
                if not consec:
                    continue
                if consec in existing:
                    # Actualizar estado_pago y estado_cxc si el archivo trae datos nuevos
                    new_ep = sv(row.get("estado_pago", ""))
                    new_ec = sv(row.get("estado_cxc", ""))
                    if new_ep or new_ec:
                        n = EncabezadoCXC.objects.filter(
                            proceso=self.proceso, consecutivo_cxc=consec
                        ).exclude(
                            estado_pago=new_ep, estado_cxc=new_ec
                        ).update(estado_pago=new_ep, estado_cxc=new_ec)
                        actualizados += n
                    duplicados += 1
                    continue

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
                existing.add(consec)  # evita IntegrityError si el mismo consecutivo aparece dos veces en el lote

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

        self.ejecucion.registros_nuevos    = nuevos
        self.ejecucion.registros_duplicados = duplicados
        if actualizados:
            nota = f"[Estados actualizados: {actualizados}]"
            self.ejecucion.error_log = (nota + "\n" + self.ejecucion.error_log).strip()
        self.ejecucion.save()
