"""
Carga los conceptos desde los archivos CONCEPTOS.xlsx de cada municipio
ubicados en MUNICIPIOS/<CODIGO>/INSUMOS/FIJOS/
"""
import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings
from muni.models import Municipio, ConceptoMunicipio


# Configuración por municipio: (nombre_archivo, col_codigo, col_descripcion, col_tipo)
CONFIG = {
    "CALDAS": {
        "archivo": "CONCEPTOS.xlsx",
        "col_codigo": "HOM CALDAS",
        "col_desc": "DESCRICION",
        "col_tipo": "PROCESOS",
        "header": 0,
    },
    "COPACABANA": {
        "archivo": "CONCEPTOS.xlsx",
        "col_codigo": "HOM COPA",
        "col_desc": "DESCRICION",
        "col_tipo": "PROCESOS",
        "header": 1,
    },
    "ENVIGADO": {
        "archivo": "CONCEPTOS.xlsx",
        "col_codigo": "CODIGO",
        "col_desc": "DESCRICION",
        "col_tipo": "PROCESOS",
        "header": 0,
    },
    "ESTRELLA": {
        "archivo": "CONCEPTOS CXC.xlsx",
        "col_codigo": "HOM COPA",
        "col_desc": "DESCRICION",
        "col_tipo": "PROCESOS",
        "header": 1,
    },
    "SABANETA": {
        "archivo": "CONCEPTOS.xlsx",
        "col_codigo": "HOM SABANETA",
        "col_desc": "DESCRICION",
        "col_tipo": "PROCESOS",
        "header": 0,
    },
}


class Command(BaseCommand):
    help = "Carga conceptos desde archivos CONCEPTOS.xlsx de cada municipio"

    def handle(self, *args, **options):
        base = settings.BASE_DIR

        for cod_muni, cfg in CONFIG.items():
            try:
                municipio = Municipio.objects.get(codigo=cod_muni)
            except Municipio.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Municipio {cod_muni} no existe, omitiendo"))
                continue

            ruta = os.path.join(str(base), "MUNICIPIOS", cod_muni, "INSUMOS", "FIJOS", cfg["archivo"])
            if not os.path.exists(ruta):
                self.stdout.write(self.style.WARNING(f"  {cod_muni}: archivo no encontrado -> {ruta}"))
                continue

            try:
                df = pd.read_excel(ruta, header=cfg.get("header", 0), dtype=str)
                df.columns = [str(c).strip() for c in df.columns]
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  {cod_muni}: error leyendo Excel -> {e}"))
                continue

            col_cod  = cfg["col_codigo"]
            col_desc = cfg["col_desc"]
            col_tipo = cfg["col_tipo"]

            # Buscar columna de código (puede variar ligeramente)
            real_cod = next((c for c in df.columns if col_cod.upper() in c.upper()), None)
            real_desc = next((c for c in df.columns if col_desc.upper() in c.upper()), None)
            real_tipo = next((c for c in df.columns if col_tipo.upper() in c.upper()), None)

            if not real_cod:
                self.stdout.write(self.style.WARNING(
                    f"  {cod_muni}: columna código '{col_cod}' no encontrada. Columnas: {list(df.columns)}"
                ))
                continue

            creados = actualizados = omitidos = 0
            # Para manejar duplicados de código, acumular descripciones
            vistos: dict = {}
            for _, row in df.iterrows():
                codigo = str(row.get(real_cod, "") or "").strip()
                if not codigo or codigo.lower() in ("nan", "none", ""):
                    continue
                desc  = str(row.get(real_desc, "") or "").strip() if real_desc else ""
                tipo  = str(row.get(real_tipo, "") or "").strip() if real_tipo else ""

                if codigo in vistos:
                    # Acumular descripciones distintas
                    if desc and desc not in vistos[codigo]["descripcion"]:
                        vistos[codigo]["descripcion"] += f" / {desc}"
                else:
                    vistos[codigo] = {"descripcion": desc, "tipo_proceso": tipo}

            for codigo, datos in vistos.items():
                _, created = ConceptoMunicipio.objects.update_or_create(
                    municipio=municipio,
                    codigo=codigo,
                    defaults={
                        "descripcion": datos["descripcion"][:200],
                        "tipo_proceso": datos["tipo_proceso"][:30],
                    }
                )
                if created:
                    creados += 1
                else:
                    actualizados += 1

            self.stdout.write(
                f"  {cod_muni}: {creados} creados, {actualizados} actualizados"
            )

        self.stdout.write(self.style.SUCCESS("\nConceptos cargados correctamente."))
