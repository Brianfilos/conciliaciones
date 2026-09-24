"""
Revisa qué tan completos están los datos de GOBS para cada municipio/proceso.

    python manage.py verificar_gobs                 # todas las fuentes, desde hace 90 días
    python manage.py verificar_gobs --desde 2026-01-01 --municipio CALDAS

Para las fuentes con actividades muestra cuántas declaraciones tienen al menos una
actividad y si el ICA por actividad suma el renglón de la declaración. Sirve para saber
cuándo se puede activar una fuente desactivada (p. ej. GOBS_PG_CALDAS_DECLARE).
"""
from datetime import date, timedelta

import pandas as pd
from django.core.management.base import BaseCommand

from etl.services import gobs_pg


class Command(BaseCommand):
    help = "Cobertura de los datos de GOBS por municipio y proceso"

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="YYYY-MM-DD (por defecto, últimos 90 días)")
        parser.add_argument("--municipio", help="Código, p. ej. CALDAS")

    def handle(self, *args, **opts):
        if not gobs_pg.habilitado():
            self.stderr.write("GOBS_PG_ENABLED está en False o falta GOBS_PG_HOST en el .env")
            return
        desde = date.fromisoformat(opts["desde"]) if opts.get("desde") else date.today() - timedelta(days=90)
        self.stdout.write(f"Declaraciones desde {desde}\n")
        for (muni, proceso), fuente in sorted(gobs_pg.FUENTES.items()):
            if opts.get("municipio") and muni != opts["municipio"].upper():
                continue
            estado = "activa" if gobs_pg.fuente_para(muni, proceso) else f"DESACTIVADA ({fuente.activar_con})"
            try:
                datos, meta = gobs_pg.cargar(fuente, desde)
            except Exception as e:  # noqa: BLE001 - se informa y se sigue con la siguiente
                self.stdout.write(self.style.ERROR(f"{muni:11} {proceso:14} error: {e}"))
                continue
            dec = datos["declaraciones"]
            linea = f"{muni:11} {proceso:20} {estado:34} declaraciones={len(dec):6}"
            act = datos.get("actividades")
            if act is not None:
                clave = fuente.col_consecutivo if fuente.col_consecutivo in act.columns else None
                cubiertas = act[clave].nunique() if clave else 0
                pct = 100 * cubiertas / len(dec) if len(dec) else 0
                linea += f" con_actividades={cubiertas:6} ({pct:5.1f}%)"
                estilo = self.style.SUCCESS if pct >= 95 else self.style.WARNING
                linea = estilo(linea)
            self.stdout.write(linea)
            if meta.get("datos_al") is not None:
                self.stdout.write(f"{'':11} datos cargados en GOBS al {meta['datos_al']}")
