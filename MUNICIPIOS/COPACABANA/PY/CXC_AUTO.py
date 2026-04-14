import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

# Leer el archivo 'autorretencion-declaraciones.xlsx'
excel_data = pd.read_excel('autorretencion-declaraciones.xlsx')

# Obtener la columna "Consecutivo" del DataFrame de 'autorretencion-declaraciones.xlsx'
consecutivo_1 = excel_data['Consecutivo 1'].astype(str)

# Transformar la columna "Consecutivo" en 'consecutivo_cxc'
nueva_columna_consecutivo_cxc = [
    '903' + '0' * (10 - len(str(valor)) - 3) + str(valor) for valor in consecutivo_1
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
    'Fecha Pago': 'fecha_cobro'
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
excel_data['Consecutivo 1'].fillna('0', inplace=True)

# Crear la columna 'descripción'
excel_data['descripción'] = (
    'PAGO AUTORETENCIÓN '+ excel_data['1.1 Periodo declarado'].astype(str).astype(str) +' ' + excel_data['1. Año'].astype(int).astype(str) + 
    ' Radicado No. ' + excel_data['Consecutivo 1'].astype(int).astype(str)
)

# Convertir todas las cadenas en el DataFrame a mayúsculas
excel_data = excel_data.applymap(lambda x: x.upper() if isinstance(x, str) else x)

# Leer el archivo 'cxccopa.csv' (archivo separado por comas)

cxc_data = pd.read_csv('G:\Mi unidad\PYTHON\CXC COPACABANA\cxccopa.csv', encoding='latin1')


# Reemplazar valores NaN en la columna 'CONSECUTIVO' con una cadena vacía temporalmente
cxc_data['CONSECUTIVO'] = cxc_data['CONSECUTIVO'].fillna('')

# Filtrar los valores válidos que se pueden convertir a números
# Esto elimina cadenas vacías o valores que no se pueden convertir a números
cxc_data = cxc_data[cxc_data['CONSECUTIVO'].apply(lambda x: str(x).replace('.', '', 1).isdigit())]

# Convertir la columna 'CONSECUTIVO' a tipo float, luego a int, y finalmente a string
cxc_data['CONSECUTIVO'] = cxc_data['CONSECUTIVO'].astype(float).astype(int).astype(str).str.strip()

# Convertir 'consecutivo_cxc' a string y eliminar espacios adicionales
excel_data['consecutivo_cxc'] = excel_data['consecutivo_cxc'].astype(str).str.strip()

# Realizar el cruce entre el archivo de 'autorretencion-declaraciones.xlsx' y 'cxccopa.csv' basado en 'consecutivo_cxc'
excel_data = pd.merge(excel_data, cxc_data[['CONSECUTIVO', 'ESTADO']], left_on='consecutivo_cxc', right_on='CONSECUTIVO', how='left')

# Eliminar la columna duplicada 'CONSECUTIVO' que se genera tras el merge
excel_data.drop(columns=['CONSECUTIVO'], inplace=True)

# Filtrar los datos que quieres exportar
datos_exportar = excel_data[[
    'Consecutivo 1', 'consecutivo_cxc', 'tipo_documento', 'numero_documento', 'primer_nombre', 
    'segundo_nombre', 'primer_apellido', 'segundo_apellido', 'razon_social', 
    'fecha_cobro', 'fecha_vencimiento', 'descripción', '20.1 Valor sanción ($ COP)', 
    '21. Intereses por mora ($ COP)', '23. Autorretención practicada en exceso o saldo a favor ($ COP)', 
    '24. TOTAL A PAGAR ($ COP)', 'Estado Pago','ESTADO'
]].copy()


# Crear un nuevo libro de Excel y agregar las hojas
wb = Workbook()
ws_encabezado = wb.create_sheet(title='encabezado')
ws_detalle = wb.create_sheet(title='detalle')

# Eliminar la hoja vacía predeterminada llamada 'Sheet'
if 'Sheet' in wb.sheetnames:
    wb.remove(wb['Sheet'])


# Leer el archivo 'autorretencion-actividades.xlsx'
nuevo_excel_data = pd.read_excel('autorretencion-actividades.xlsx')

# Definir una función para separar el código y la descripción
def separar_codigo_descripcion(valor):
    partes = valor.split(' - ', 1)
    if len(partes) == 2:
        return partes[0].zfill(4), partes[1]
    else:
        return '', valor

# Aplicar la función a la columna 'Código CIIU' y guardar los resultados en nuevas columnas
nuevo_excel_data['codigo'], nuevo_excel_data['descripcion_codigo'] = zip(*nuevo_excel_data['Código CIIU'].apply(separar_codigo_descripcion))

# Eliminar la columna original 'Código CIIU'
nuevo_excel_data.drop(columns=['Código CIIU'], inplace=True)

# Filtrar las columnas requeridas
datos_detalle = nuevo_excel_data[['Consecutivo 1', 'codigo', '18. Total valor autorretención ($ COP)']]

#ACTIVIDADES CIIU

# Cargar el archivo 'CODIFICACION CIIU' en un DataFrame, asegurando que todas las columnas se carguen como texto
codificacion_ciiu_data = pd.read_excel('CODIFICACION CIIU.xlsx', dtype=str)

# Renombrar la columna 'CIIU 4' a 'CRUCE'
codificacion_ciiu_data.rename(columns={'CIIU 4': 'CRUCE'}, inplace=True)

# Convertir la columna 'CRUCE' al formato '0000'
codificacion_ciiu_data['CRUCE'] = codificacion_ciiu_data['CRUCE'].str.zfill(4)

# Ajustar el formato de los códigos en ambas columnas para que coincidan
datos_detalle.loc[:, 'codigo'] = datos_detalle['codigo'].str.strip().str.upper()
codificacion_ciiu_data.loc[:, 'CRUCE'] = codificacion_ciiu_data['CRUCE'].str.strip().str.upper()

# Forzar la capitalización en ambas columnas
datos_detalle.loc[:, 'codigo'] = datos_detalle['codigo'].str.upper()
codificacion_ciiu_data.loc[:, 'CRUCE'] = codificacion_ciiu_data['CRUCE'].str.upper()



# Fusionar los DataFrames basado en la columna 'codigo'
datos_detalle_fusionados = pd.merge(datos_detalle, codificacion_ciiu_data, left_on='codigo', right_on='CRUCE', how='left')


# Renombrar la columna resultante de la fusión a 'CRUCE'
datos_detalle_fusionados.rename(columns={'Unnamed: 3': 'TIPO_SERVICIO'}, inplace=True)

# Eliminar columnas innecesarias
datos_detalle_fusionados.drop(columns=['CRUCE', 'Descripción', 'Tarifa'], inplace=True)

# Eliminar columnas vacías "Unnamed" del DataFrame datos_detalle_fusionados
datos_detalle_fusionados = datos_detalle_fusionados.dropna(axis=1, how='all')

# Hacer el cruce y agregar 'consecutivo_cxc' a detalles_data
datos_detalle_fusionados = datos_detalle_fusionados.merge(datos_exportar[['Consecutivo 1', 'consecutivo_cxc']], on='Consecutivo 1', how='left')

# Convertir la columna 'Consecutivo 1' a tipo de datos str en ambos DataFrames
excel_data['Consecutivo 1'] = excel_data['Consecutivo 1'].astype(str)
datos_detalle_fusionados['Consecutivo 1'] = datos_detalle_fusionados['Consecutivo 1'].astype(str)

# Agrupar los datos por 'Consecutivo 2' y 'Tipo de Servicio', luego sumar los valores de '18. Total valor autorretención ($ COP)'
datos_actividades_agrupados = datos_detalle_fusionados.groupby(['consecutivo_cxc', 'TIPO'])['18. Total valor autorretención ($ COP)'].sum().reset_index()

# Cambiar el nombre de la columna 'Impuestos de industria y comercio' por 'Total Impuestos'
datos_actividades_agrupados.rename(columns={'18. Total valor autorretención ($ COP)': 'valor_unitario'}, inplace=True)



datos_actividades_agrupados.loc[datos_actividades_agrupados['TIPO'] == 'INDUSTRIAL', 'codigo_concepto'] = '10154'
datos_actividades_agrupados.loc[datos_actividades_agrupados['TIPO'] == 'COMERCIAL', 'codigo_concepto'] = '10156'
datos_actividades_agrupados.loc[datos_actividades_agrupados['TIPO'] == 'SERVICIOS', 'codigo_concepto'] = '10155'


# Eliminar las columnas que ya no se neceita en 'encabezado'.
datos_actividades_agrupados = datos_actividades_agrupados.drop(columns=['TIPO'])

# Agregar las columnas adicionales
datos_actividades_agrupados['centro_costo'] = '1501'
datos_actividades_agrupados['cantidad'] = '1'

datos_actividades_agrupados['valor_total'] = datos_actividades_agrupados['valor_unitario']


# Crear el DataFrame 'sanciones' con las columnas deseadas
sanciones = datos_exportar[['consecutivo_cxc', '20.1 Valor sanción ($ COP)']].copy()
sanciones = sanciones[sanciones['20.1 Valor sanción ($ COP)'].notna()]
sanciones['concepto'] = '10112'
sanciones.rename(columns={'20.1 Valor sanción ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'intereses' con las columnas deseadas
intereses = datos_exportar[['consecutivo_cxc', '21. Intereses por mora ($ COP)']].copy()
intereses = intereses[intereses['21. Intereses por mora ($ COP)'].notna()]
intereses['concepto'] = '10113'
intereses.rename(columns={'21. Intereses por mora ($ COP)': 'valor'}, inplace=True)

# Crear el DataFrame 'exce' con las columnas deseadas
exce = datos_exportar[['consecutivo_cxc', '23. Autorretención practicada en exceso o saldo a favor ($ COP)']].copy()
exce = exce[exce['23. Autorretención practicada en exceso o saldo a favor ($ COP)'].notna()]
# Obtener el tipo de actividad para cada consecutivo
tipos_actividad = datos_detalle_fusionados[['consecutivo_cxc', 'TIPO']].drop_duplicates(subset=['consecutivo_cxc'])

# Asignar el código de concepto según el tipo de actividad
def obtener_codigo_concepto(tipo):
    if tipo == 'INDUSTRIAL':
        return '10169'
    elif tipo == 'COMERCIAL':
        return '10153'
    elif tipo == 'SERVICIOS':
        return '10170'
    else:
        return ''

# Unir para obtener el tipo de actividad
exce = exce.merge(tipos_actividad, on='consecutivo_cxc', how='left')
exce['concepto'] = exce['TIPO'].apply(obtener_codigo_concepto)
exce.rename(columns={'23. Autorretención practicada en exceso o saldo a favor ($ COP)': 'valor'}, inplace=True)
exce = exce[['consecutivo_cxc', 'valor', 'concepto']]

# Concatenar los DataFrames
detalle_combined = pd.concat([sanciones, intereses, exce])

# Agregar las columnas adicionales
detalle_combined['centro_costo'] = '1501'
detalle_combined['cantidad'] = '1'

# Renombrar las columnas y duplicar 'valor'
detalle_combined.rename(columns={'concepto': 'codigo_concepto', 'valor': 'valor_unitario'}, inplace=True)
detalle_combined['valor_total'] = detalle_combined['valor_unitario']

# Reordenar las columnas para el archivo de salida
detalle_combined = detalle_combined[['consecutivo_cxc', 'codigo_concepto', 'valor_unitario', 'valor_total', 'centro_costo', 'cantidad']]


# Crear un DataFrame 'actividades' y concatenar con 'detalle_combined'
actividades = pd.concat([datos_actividades_agrupados, detalle_combined])

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




















