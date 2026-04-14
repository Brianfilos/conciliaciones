import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

# Leer el archivo 'reteica-declaraciones.xlsx'
excel_data = pd.read_excel('reteica-declaraciones.xlsx')

# Obtener la columna "Consecutivo" del DataFrame de 'reteica-declaraciones.xlsx'
consecutivo_1 = excel_data['Consecutivo'].astype(str)

# Transformar la columna "Consecutivo" en 'consecutivo_cxc'
nueva_columna_consecutivo_cxc = [
    '904' + '0' * (10 - len(str(valor)) - 3) + str(valor) for valor in consecutivo_1
]

# Agregar la nueva columna "consecutivo_cxc" al DataFrame de 'autorretencion-declaraciones.xlsx'
excel_data['consecutivo_cxc'] = nueva_columna_consecutivo_cxc

# Renombrar las columnas para compatibilidad
excel_data.rename(columns={
    'Tipo de documento': 'tipo_documento',
    'Número de documento': 'numero_documento',
    'Primer nombre': 'primer_nombre',
    'Segundo nombre': 'segundo_nombre',
    'Primer apellido': 'primer_apellido',
    'Segundo apellido': 'segundo_apellido',
    'Nombre productor': 'razon_social',
    'Fecha de la visita': 'fecha_cobro'
}, inplace=True)

# Actualizar 'razon_social' basado en 'tipo_documento'
excel_data['razon_social'] = excel_data.apply(
    lambda row: '' if row['tipo_documento'] in ['CC', 'CE'] else row['razon_social'], axis=1
)

# Convertir la columna 'fecha_cobro' al formato deseado
excel_data['fecha_cobro'] = pd.to_datetime(
    excel_data['fecha_cobro'], format='%Y-%m-%d %H:%M:%S.%f', errors='coerce'
)

# Agregar un día a cada fecha de 'fecha_cobro' y almacenar en 'fecha_vencimiento'
excel_data['fecha_vencimiento'] = excel_data['fecha_cobro'] + pd.Timedelta(days=1)

# Llenar los valores faltantes con cero
excel_data['1. Año'].fillna('0', inplace=True)
excel_data['Consecutivo'].fillna('0', inplace=True)

# Crear la columna 'descripción'
excel_data['descripción'] = (
    'PAGO RETENCION ' + excel_data['1.1 Periodo declarado'].astype(str).astype(str)+ 'AÑO GRAVABLE ' + excel_data['1. Año'].astype(int).astype(str) + 
    ' Radicado No. ' + excel_data['Consecutivo'].astype(int).astype(str)
)

# Convertir todas las cadenas en el DataFrame a mayúsculas
excel_data = excel_data.applymap(lambda x: x.upper() if isinstance(x, str) else x)

# Leer el archivo 'cxccopa.csv' (archivo separado por comas)

cxc_data = pd.read_csv('G:\Mi unidad\PYTHON\CXC LA ESTRELLA\CXC\cxcestre.csv', 
                       encoding='latin1', 
                       #skiprows=5, 
                       delimiter=';')  # Cambia el delimitador según sea necesario

# Reemplazar valores NaN en la columna 'CONSECUTIVO' con una cadena vacía temporalmente
cxc_data['CONSECUTIVO'] = cxc_data['CONSECUTIVO'].fillna('')

# Filtrar los valores válidos que se pueden convertir a números
# Esto elimina cadenas vacías o valores que no se pueden convertir a números
cxc_data = cxc_data[cxc_data['CONSECUTIVO'].apply(lambda x: str(x).replace('.', '', 1).isdigit())]

# Convertir la columna 'CONSECUTIVO' a tipo float, luego a int, y finalmente a string
cxc_data['CONSECUTIVO'] = cxc_data['CONSECUTIVO'].astype(float).astype(int).astype(str).str.strip()

# Convertir 'consecutivo_cxc' a string y eliminar espacios adicionales
excel_data['consecutivo_cxc'] = excel_data['consecutivo_cxc'].astype(str).str.strip()

# Verificar los primeros valores de ambas columnas para asegurar que coinciden
print(excel_data['consecutivo_cxc'].head())
print(cxc_data['CONSECUTIVO'].head())

# Realizar el cruce entre el archivo de 'autorretencion-declaraciones.xlsx' y 'cxccopa.csv' basado en 'consecutivo_cxc'
excel_data = pd.merge(excel_data, cxc_data[['CONSECUTIVO', 'ESTADO']], left_on='consecutivo_cxc', right_on='CONSECUTIVO', how='left')

# Eliminar la columna duplicada 'CONSECUTIVO' que se genera tras el merge
excel_data.drop(columns=['CONSECUTIVO'], inplace=True)

# Verificar si el cruce trajo valores para la columna 'ESTADO'
print(excel_data[['consecutivo_cxc', 'ESTADO']].head())

# Filtrar los datos que quieres exportar
datos_exportar = excel_data[[
    'Consecutivo', 'consecutivo_cxc', 'tipo_documento', 'numero_documento', 'primer_nombre', 
    'segundo_nombre', 'primer_apellido', 'segundo_apellido', 'razon_social', 
    'fecha_cobro', 'fecha_vencimiento', 'descripción','14.1 Actividad Industrial - Valor Retenido ($ COP)','15.1. Actividad Comercial - Valor Retenido ($ COP)','16.1 Actividad Servicios - Valor Retenido ($ COP)', '19.1 Valor Sanción ($ COP)', '17.1 Sistema de pago con tarjetas y demas medios de pago - Valor Retenido ($ COP)',
    '20. Intereses por mora ($ COP)', '22. Retención practicada en exceso, indebidas o por operaciones anuladas, rescindidas o resueltas', 
    '23. Total a pagar ($ COP)', 'Estado Pago','ESTADO'
]].copy()

# Crear un nuevo libro de Excel y agregar las hojas
wb = Workbook()
ws_encabezado = wb.create_sheet(title='encabezado')
ws_detalle = wb.create_sheet(title='detalle')

# Eliminar la hoja vacía predeterminada llamada 'Sheet'
if 'Sheet' in wb.sheetnames:
    wb.remove(wb['Sheet'])

# Leer el archivo 'autorretencion-actividades.xlsx'
actividades_data = pd.read_excel('reteica-declaraciones.xlsx', dtype=str)  # Asegurar que se cargue como texto

# Dividir la columna 'Código CIIU' en cuatro columnas
actividades_data[['CIIU_Part1', 'CIIU_Part2', 'CIIU_Part3', 'CIIU_Part4']] = actividades_data['7. Código Actividad Económica CIIU'].str.split('-', expand=True)

# Crear un nuevo DataFrame con las columnas deseadas
detalles_data = actividades_data[['Consecutivo', 'CIIU_Part1', 'CIIU_Part2', 'CIIU_Part3', 'CIIU_Part4', '14.1 Actividad Industrial - Valor Retenido ($ COP)','15.1. Actividad Comercial - Valor Retenido ($ COP)','16.1 Actividad Servicios - Valor Retenido ($ COP)']]

# Asegurarse de que 'Consecutivo' esté en texto en ambos DataFrames para el cruce
datos_exportar['Consecutivo'] = datos_exportar['Consecutivo'].astype(str)
detalles_data['Consecutivo'] = detalles_data['Consecutivo'].astype(str)

# Hacer el cruce y agregar 'consecutivo_cxc' a detalles_data
detalles_data = detalles_data.merge(datos_exportar[['Consecutivo', 'consecutivo_cxc']], on='Consecutivo', how='left')

# Convertir '18. Total valor autorretención ($ COP)' a numérico
#detalles_data['14.1 Actividad Industrial - Valor Retenido ($ COP)','15.1. Actividad Comercial - Valor Retenido ($ COP)','16.1 Actividad Servicios - Valor Retenido ($ COP)'] = pd.to_numeric(detalles_data['14.1 Actividad Industrial - Valor Retenido ($ COP)','15.1. Actividad Comercial - Valor Retenido ($ COP)','16.1 Actividad Servicios - Valor Retenido ($ COP)'], errors='coerce')


# Renombrar las columnas
#detalles_data.rename(columns={
   # 'CIIU_Part4': 'concepto',
    #'14.1 Actividad Industrial - Valor Retenido ($ COP)': 'valor_unitario'
#}, inplace=True)

# Homologar los valores de la columna 'concepto'
#detalles_data['codigo_concepto'] = detalles_data['concepto'].replace({
   # 'comercial': 'HD402',
    #'industrial': 'HDA675',
   #'servicios': 'HDA674'
#})

# Agregar las columnas adicionales
#detalles_data['centro_costo'] = '7'
#detalles_data['cantidad'] = '1'

#detalles_data['valor_total'] = detalles_data['valor_unitario']

# Eliminar las columnas que se agregó automáticamente en la fusión
#detalles_data.drop(columns=['Consecutivo','CIIU_Part1','CIIU_Part2','CIIU_Part3','concepto'], inplace=True)

# Crear el DataFrame 'sanciones' con las columnas deseadas
industrial = datos_exportar[['consecutivo_cxc', '14.1 Actividad Industrial - Valor Retenido ($ COP)']].copy()
industrial = industrial[industrial['14.1 Actividad Industrial - Valor Retenido ($ COP)'].notna()]
industrial['concepto'] = 'HDA675'
industrial.rename(columns={'14.1 Actividad Industrial - Valor Retenido ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'sanciones' con las columnas deseadas
comercial = datos_exportar[['consecutivo_cxc', '15.1. Actividad Comercial - Valor Retenido ($ COP)']].copy()
comercial = comercial[comercial['15.1. Actividad Comercial - Valor Retenido ($ COP)'].notna()]
comercial['concepto'] = 'HD402'
comercial.rename(columns={'15.1. Actividad Comercial - Valor Retenido ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'sanciones' con las columnas deseadas
servicios = datos_exportar[['consecutivo_cxc', '16.1 Actividad Servicios - Valor Retenido ($ COP)']].copy()
servicios = servicios[servicios['16.1 Actividad Servicios - Valor Retenido ($ COP)'].notna()]
servicios['concepto'] = 'HDA674'
servicios.rename(columns={'16.1 Actividad Servicios - Valor Retenido ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'sanciones' con las columnas deseadas
sanciones = datos_exportar[['consecutivo_cxc', '19.1 Valor Sanción ($ COP)']].copy()
sanciones = sanciones[sanciones['19.1 Valor Sanción ($ COP)'].notna()]
sanciones['concepto'] = 'HD22'
sanciones.rename(columns={'19.1 Valor Sanción ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'intereses' con las columnas deseadas
intereses = datos_exportar[['consecutivo_cxc', '20. Intereses por mora ($ COP)']].copy()
intereses = intereses[intereses['20. Intereses por mora ($ COP)'].notna()]
intereses['concepto'] = 'IntICOM'
intereses.rename(columns={'20. Intereses por mora ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'exce' con las columnas deseadas
exce = datos_exportar[['consecutivo_cxc', '22. Retención practicada en exceso, indebidas o por operaciones anuladas, rescindidas o resueltas']].copy()
exce = exce[exce['22. Retención practicada en exceso, indebidas o por operaciones anuladas, rescindidas o resueltas'].notna()]
exce['concepto'] = 'HDA806'
exce.rename(columns={'22. Retención practicada en exceso, indebidas o por operaciones anuladas, rescindidas o resueltas': 'valor'}, inplace=True)

# Crear el DataFrame 'exce' con las columnas deseadas
tar = datos_exportar[['consecutivo_cxc', '17.1 Sistema de pago con tarjetas y demas medios de pago - Valor Retenido ($ COP)']].copy()
tar = tar[tar['17.1 Sistema de pago con tarjetas y demas medios de pago - Valor Retenido ($ COP)'].notna()]
tar['concepto'] = 'HDA676'
tar.rename(columns={'17.1 Sistema de pago con tarjetas y demas medios de pago - Valor Retenido ($ COP)': 'valor'}, inplace=True)


# Concatenar los DataFrames
detalle_combined = pd.concat([sanciones, intereses, exce,tar,industrial,comercial,servicios])

# Agregar las columnas adicionales
detalle_combined['centro_costo'] = '07'
detalle_combined['cantidad'] = '1'

# Renombrar las columnas y duplicar 'valor'
detalle_combined.rename(columns={'concepto': 'codigo_concepto', 'valor': 'valor_unitario'}, inplace=True)
detalle_combined['valor_total'] = detalle_combined['valor_unitario']

# Reordenar las columnas para el archivo de salida
detalle_combined = detalle_combined[['consecutivo_cxc', 'codigo_concepto', 'valor_unitario', 'valor_total', 'centro_costo', 'cantidad']]


# Crear un DataFrame 'actividades' y concatenar con 'detalle_combined'
actividades = pd.concat([detalle_combined])


# Reordenar las columnas para el archivo de salida
actividades = actividades[['consecutivo_cxc', 'codigo_concepto', 'centro_costo', 'cantidad', 'valor_unitario', 'valor_total']]


# Guardar los datos en la hoja "detalle"
for r in dataframe_to_rows(actividades, index=False, header=True):
    ws_detalle.append(r)

# Guardar los datos en la hoja "encabezado"
for r in dataframe_to_rows(datos_exportar, index=False, header=True):
    ws_encabezado.append(r)

# Pedir el nombre del archivo al usuario
archivo_guardar = input("Ingrese el nombre del archivo para guardar (sin extensión): ") + ".xlsx"

# Guardar el archivo de Excel con el nombre especificado
wb.save(archivo_guardar)
print(f"Archivo guardado como: {archivo_guardar}")
