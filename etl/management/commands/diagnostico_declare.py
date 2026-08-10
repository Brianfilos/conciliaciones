"""
Uso:
  python manage.py diagnostico_declare --municipio COPACABANA \
      --declaraciones ruta/archivo.xlsx \
      --actividades ruta/actividades.xlsx

Muestra para cada consecutivo: columnas detectadas, suma de conceptos vs total_40 y diferencia.
"""
import pandas as pd
from django.core.management.base import BaseCommand
from muni.models import Municipio


class Command(BaseCommand):
    help = "Diagnóstico de DECLARE Y PAGUE: muestra columnas, splits y diferencias"

    def add_arguments(self, parser):
        parser.add_argument("--municipio", required=True)
        parser.add_argument("--declaraciones", required=True)
        parser.add_argument("--actividades", required=True)
        parser.add_argument("--consec", default=None,
                            help="Filtrar por un consecutivo específico (opcional)")

    def handle(self, *args, **options):
        from etl.services.motor import MotorETL
        from etl.models import Proceso, Ejecucion

        municipio_codigo = options["municipio"]
        try:
            municipio = Municipio.objects.get(codigo=municipio_codigo)
        except Municipio.DoesNotExist:
            self.stderr.write(f"Municipio '{municipio_codigo}' no encontrado.")
            return

        archivos = {
            "declaraciones": options["declaraciones"],
            "actividades":   options["actividades"],
        }

        # ── Obtener procesador sin correr el motor completo ──────────────────
        from etl.services.copacabana import ProcesadorCopacabana
        from etl.services.base import ProcesadorBase

        proc = ProcesadorCopacabana.__new__(ProcesadorCopacabana)
        proc.proceso_codigo = "DECLAREYPAGUE"
        proc.archivos = archivos
        proc.municipio = municipio
        proc._ciiu_cache = {
            str(c).zfill(4): t
            for c, t in __import__("muni.models", fromlist=["CIIUMunicipio"])
                .CIIUMunicipio.objects
                .filter(municipio=municipio)
                .values_list("codigo", "tipo")
        }

        # ── Leer declaración ─────────────────────────────────────────────────
        dec = pd.read_excel(archivos["declaraciones"])
        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(f"Columnas del Excel de declaraciones ({len(dec)} filas):")
        for c in dec.columns:
            self.stdout.write(f"  '{c}'")

        # ── Detectar columnas clave ──────────────────────────────────────────
        def _fc(cols, n):
            c = next((c for c in cols if f"{n}." in c), None)
            if c is None:
                c = next((c for c in cols
                          if c.strip().startswith(f"{n} ") or c.strip().startswith(f"{n}.")), None)
            return c

        tc   = _fc(dec.columns, "40")
        c17  = _fc(dec.columns, "17")
        c26  = _fc(dec.columns, "26")
        c27  = _fc(dec.columns, "27")
        c28  = _fc(dec.columns, "28")
        c29  = _fc(dec.columns, "29")
        c39  = _fc(dec.columns, "39")

        self.stdout.write(f"\n{'='*70}")
        self.stdout.write("Columnas detectadas:")
        self.stdout.write(f"  col17 (base ICA)    : {c17!r}")
        self.stdout.write(f"  col26 (exoneración) : {c26!r}")
        self.stdout.write(f"  col27 (retenciones) : {c27!r}")
        self.stdout.write(f"  col28 (autorrete.)  : {c28!r}")
        self.stdout.write(f"  col29 (anticipos)   : {c29!r}")
        self.stdout.write(f"  col39 (pago vol.)   : {c39!r}")
        self.stdout.write(f"  tc   (total pagar)  : {tc!r}")

        if not tc:
            self.stderr.write("\n¡ERROR! No se encontró columna 40 (total a pagar). "
                              "La aproximación NO correrá.")
            return

        # ── Ejecutar el procesador completo ──────────────────────────────────
        df_enc, df_det = proc._declare()

        filtro = options.get("consec")

        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(f"{'CONSEC':<20} {'TOTAL_40':>12} {'SUMA_CON':>12} {'DIFF':>10}  CONCEPTOS")
        self.stdout.write("-" * 90)

        for _, enc_row in df_enc.iterrows():
            consec   = str(enc_row.get("consecutivo_cxc", "")).strip()
            if filtro and filtro not in consec:
                continue
            total_40 = pd.to_numeric(enc_row.get("total_a_pagar"), errors="coerce")
            sub = df_det[df_det["consecutivo_cxc"].astype(str).str.strip() == consec]
            if sub.empty:
                self.stdout.write(f"{consec:<20} {'':>12} {'SIN CONCEPTOS':>12}")
                continue
            signed_sum = round(
                sub["valor_total"].apply(lambda x: pd.to_numeric(x, errors="coerce")).fillna(0).sum(), 2)
            diff = round(signed_sum - (total_40 or 0), 2)
            flag = "  ← DIFF GRANDE" if abs(diff) >= 1000 else ("  ✓" if diff == 0 else "  ← revisar")
            total_str = f"{total_40:,.0f}" if pd.notna(total_40) else "N/A"
            self.stdout.write(
                f"{consec:<20} {total_str:>12} {signed_sum:>12,.0f} {diff:>10,.0f}{flag}")
            # Detalle de conceptos
            for _, dr in sub.iterrows():
                vt = pd.to_numeric(dr.get("valor_total"), errors="coerce")
                self.stdout.write(
                    f"  {'':20} {'':12} {dr.get('codigo_concepto',''):>10}  {vt:>12,.0f}")
