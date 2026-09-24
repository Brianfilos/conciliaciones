from django.core.management.base import BaseCommand
from muni.models import Municipio
from etl.models import Proceso, InsumoDefinicion


MUNICIPIOS = [
    {"codigo":"COPACABANA","nombre":"Municipio de Copacabana","prefijo_cxc":"903","color_primario":"#21294C","color_secundario":"#1ab4e8","color_texto_header":"#ffffff","fuente_principal":"Montserrat, Arial, sans-serif","tiene_procesos":True,"orden":1},
    {"codigo":"ESTRELLA","nombre":"Municipio La Estrella","prefijo_cxc":"904","color_primario":"#00843a","color_secundario":"#5cb130","color_texto_header":"#ffffff","fuente_principal":"Menco, sans-serif","tiene_procesos":True,"orden":2},
    {"codigo":"CALDAS","nombre":"Municipio de Caldas","prefijo_cxc":"","color_primario":"#1a5e2a","color_secundario":"#237a38","color_texto_header":"#ffffff","tiene_procesos":True,"orden":3},
    {"codigo":"ENVIGADO","nombre":"Municipio de Envigado","prefijo_cxc":"","color_primario":"#1B3A6B","color_secundario":"#2d5fa0","color_texto_header":"#ffffff","tiene_procesos":True,"orden":4},
    {"codigo":"SABANETA","nombre":"Municipio de Sabaneta","prefijo_cxc":"","color_primario":"#1ACC00","color_secundario":"#80FF00","color_texto_header":"#ffffff","fuente_principal":"Barlow Condensed, sans-serif","tiene_procesos":True,"orden":5},
]

PROCESOS = [
    {
        "codigo":"CXC_AUTO","nombre":"Autorretención","descripcion":"Proceso CXC de Autorretención ICA","orden":1,
        "insumos":[
            {"nombre":"Declaraciones Autorretención","nombre_campo":"declaraciones","extensiones":".xlsx","orden":1},
            {"nombre":"Actividades Autorretención","nombre_campo":"actividades","extensiones":".xlsx","orden":2},
            {"nombre":"Archivo CXC (consecutivos y estados)","nombre_campo":"cxc_csv","extensiones":".csv","orden":3},
        ]
    },
    {
        "codigo":"CXC_RETE","nombre":"Retención ICA","descripcion":"Proceso CXC de Retención ICA","orden":2,
        "insumos":[
            {"nombre":"Declaraciones ReteICA","nombre_campo":"declaraciones","extensiones":".xlsx","orden":1},
            {"nombre":"Archivo CXC (consecutivos y estados)","nombre_campo":"cxc_csv","extensiones":".csv","orden":2},
        ]
    },
    {
        "codigo":"DECLAREYPAGUE","nombre":"Declare y Pague","descripcion":"Proceso ICA Declare y Pague anual","orden":3,
        "insumos":[
            {"nombre":"Declaraciones ICA general","nombre_campo":"declaraciones","extensiones":".xlsx","orden":1},
            {"nombre":"Actividades ICA","nombre_campo":"actividades","extensiones":".xlsx","orden":2},
            {"nombre":"Archivo CXC (consecutivos y estados)","nombre_campo":"cxc_csv","extensiones":".csv","orden":3},
        ]
    },
]


class Command(BaseCommand):
    help = "Inicializa municipios y procesos base en la base de datos"

    def handle(self, *args, **options):
        for data in MUNICIPIOS:
            m, created = Municipio.objects.update_or_create(codigo=data["codigo"], defaults=data)
            self.stdout.write(f"{'Creado' if created else 'Actualizado'}: {m.nombre}")

        for mun_codigo in ["COPACABANA", "ESTRELLA"]:
            try:
                municipio = Municipio.objects.get(codigo=mun_codigo)
            except Municipio.DoesNotExist:
                continue
            for pdata in PROCESOS:
                insumos = pdata.pop("insumos")
                proceso, created = Proceso.objects.update_or_create(
                    municipio=municipio, codigo=pdata["codigo"],
                    defaults={**pdata, "activo": True}
                )
                pdata["insumos"] = insumos
                for idata in insumos:
                    InsumoDefinicion.objects.update_or_create(
                        proceso=proceso, nombre_campo=idata["nombre_campo"],
                        defaults={**idata, "tipo": "CARGUE", "requerido": True}
                    )
                self.stdout.write(f"  Proceso: {proceso}")
        # Envigado — procesos sin insumo cxc_csv
        envigado_procesos = [
            {
                "codigo": "CXC_AUTO", "nombre": "Autorretención",
                "descripcion": "Proceso CXC Autorretención ICA", "orden": 1,
                "insumos": [
                    {"nombre": "Declaraciones Autorretención", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
                    {"nombre": "Actividades Autorretención",   "nombre_campo": "actividades",   "extensiones": ".xlsx", "orden": 2},
                ]
            },
            {
                "codigo": "CXC_RETE", "nombre": "Retención ICA",
                "descripcion": "Proceso CXC Retención ICA", "orden": 2,
                "insumos": [
                    {"nombre": "Declaraciones ReteICA", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
                ]
            },
        ]
        try:
            envigado = Municipio.objects.get(codigo="ENVIGADO")
            for pdata in envigado_procesos:
                insumos = pdata.pop("insumos")
                proceso, created = Proceso.objects.update_or_create(
                    municipio=envigado, codigo=pdata["codigo"],
                    defaults={**pdata, "activo": True}
                )
                pdata["insumos"] = insumos
                for idata in insumos:
                    InsumoDefinicion.objects.update_or_create(
                        proceso=proceso, nombre_campo=idata["nombre_campo"],
                        defaults={**idata, "tipo": "CARGUE", "requerido": True}
                    )
                self.stdout.write(f"  Proceso Envigado: {proceso}")
        except Municipio.DoesNotExist:
            pass

        # Caldas — mismos procesos sin cxc_csv
        procesos_basicos = [
            {
                "codigo": "CXC_AUTO", "nombre": "Autorretención",
                "descripcion": "Proceso CXC Autorretención ICA", "orden": 1,
                "insumos": [
                    {"nombre": "Declaraciones Autorretención", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
                    {"nombre": "Actividades Autorretención",   "nombre_campo": "actividades",   "extensiones": ".xlsx", "orden": 2},
                ]
            },
            {
                "codigo": "CXC_RETE", "nombre": "Retención ICA",
                "descripcion": "Proceso CXC Retención ICA", "orden": 2,
                "insumos": [
                    {"nombre": "Declaraciones ReteICA", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
                ]
            },
            {
                "codigo": "DECLAREYPAGUE", "nombre": "Declare y Pague",
                "descripcion": "Proceso ICA Declare y Pague anual", "orden": 3,
                "insumos": [
                    {"nombre": "Declaraciones ICA general", "nombre_campo": "declaraciones", "extensiones": ".xlsx", "orden": 1},
                    {"nombre": "Actividades ICA",           "nombre_campo": "actividades",   "extensiones": ".xlsx", "orden": 2},
                ]
            },
        ]
        for cod in ["CALDAS"]:
            try:
                municipio = Municipio.objects.get(codigo=cod)
                for pdata in procesos_basicos:
                    insumos = pdata.pop("insumos")
                    proceso, created = Proceso.objects.update_or_create(
                        municipio=municipio, codigo=pdata["codigo"],
                        defaults={**pdata, "activo": True}
                    )
                    pdata["insumos"] = insumos
                    for idata in insumos:
                        InsumoDefinicion.objects.update_or_create(
                            proceso=proceso, nombre_campo=idata["nombre_campo"],
                            defaults={**idata, "tipo": "CARGUE", "requerido": True}
                        )
                    self.stdout.write(f"  Proceso {cod}: {proceso}")
            except Municipio.DoesNotExist:
                pass

        # Sabaneta — solo Publicidad Exterior Visual. Las declaraciones vienen de GOBS;
        # el Excel es el respaldo si GOBS_PG_ENABLED=False. Los procesos genéricos
        # (autorretención, retención, declare y pague) no tienen procesador para Sabaneta.
        try:
            sabaneta = Municipio.objects.get(codigo="SABANETA")
            Proceso.objects.filter(
                municipio=sabaneta, codigo__in=["CXC_AUTO", "CXC_RETE", "DECLAREYPAGUE"]
            ).update(activo=False)
            proceso, _ = Proceso.objects.update_or_create(
                municipio=sabaneta, codigo="PUBLICIDAD_EXTERIOR",
                defaults={"nombre": "Publicidad Exterior Visual",
                          "descripcion": "Proceso CXC de Publicidad Exterior Visual",
                          "orden": 1, "activo": True})
            InsumoDefinicion.objects.update_or_create(
                proceso=proceso, nombre_campo="declaraciones",
                defaults={"nombre": "Declaraciones Publicidad Exterior Visual",
                          "extensiones": ".xlsx", "orden": 1, "tipo": "CARGUE", "requerido": True})
            self.stdout.write(f"  Proceso Sabaneta: {proceso}")
        except Municipio.DoesNotExist:
            pass

        self.stdout.write(self.style.SUCCESS("\nInicialización completada."))
