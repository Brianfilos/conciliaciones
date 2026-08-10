import sqlite3
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from muni.models import Municipio, CIIUMunicipio, ConceptoMunicipio


class Command(BaseCommand):
    help = "Migra CIIU y Conceptos desde db.sqlite3 a la base de datos actual"

    def handle(self, *args, **options):
        sqlite_path = os.path.join(str(settings.BASE_DIR), 'db.sqlite3')
        if not os.path.exists(sqlite_path):
            self.stdout.write(self.style.ERROR("No se encontró db.sqlite3"))
            return

        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # --- Migrar CIIU ---
        self.stdout.write("Migrando CIIU...")
        cur.execute("""
            SELECT c.codigo, c.descripcion, c.tarifa, c.tipo, m.codigo AS mun_codigo
            FROM muni_ciiumunicipio c
            JOIN muni_municipio m ON m.id = c.municipio_id
        """)
        rows = cur.fetchall()
        creados = actualizados = 0
        for row in rows:
            try:
                municipio = Municipio.objects.get(codigo=row['mun_codigo'])
            except Municipio.DoesNotExist:
                continue
            _, created = CIIUMunicipio.objects.update_or_create(
                municipio=municipio,
                codigo=row['codigo'],
                defaults={
                    'descripcion': row['descripcion'] or '',
                    'tarifa': row['tarifa'],
                    'tipo': row['tipo'] or '',
                }
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        self.stdout.write(f"  CIIU: {creados} creados, {actualizados} actualizados")

        # --- Migrar Conceptos ---
        self.stdout.write("Migrando Conceptos...")
        cur.execute("""
            SELECT c.codigo, c.descripcion, c.tipo_proceso, m.codigo AS mun_codigo
            FROM muni_conceptomunicipio c
            JOIN muni_municipio m ON m.id = c.municipio_id
        """)
        rows = cur.fetchall()
        creados = actualizados = 0
        for row in rows:
            try:
                municipio = Municipio.objects.get(codigo=row['mun_codigo'])
            except Municipio.DoesNotExist:
                continue
            _, created = ConceptoMunicipio.objects.update_or_create(
                municipio=municipio,
                codigo=row['codigo'],
                defaults={
                    'descripcion': row['descripcion'] or '',
                    'tipo_proceso': row['tipo_proceso'] or '',
                }
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        self.stdout.write(f"  Conceptos: {creados} creados, {actualizados} actualizados")

        conn.close()
        self.stdout.write(self.style.SUCCESS("\nMigración completada."))
