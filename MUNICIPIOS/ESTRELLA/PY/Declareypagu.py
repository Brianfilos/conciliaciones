"""
Created on Thu Apr 25 2024
@author: brian filos
"""
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

# Crear un nuevo archivo de Excel
wb = Workbook()

# Cargar datos desde el archivo Excel
excel_data = pd.read_excel('declaraciones-general.xlsx')

# Filtrar los datos que quieres exportar
datos_exportar = excel_data[['Consecutivo 1', 'Tipo de documento', 'Número de documento', 'Primer nombre', 
                             'Segundo nombre', 'Primer apellido', 'Segundo apellido', 'Nombre productor', 
                             'Fecha de la visita', 'Estado Pago', 'Consecutivo 2', 'Año Gravable', 
                             '40. Total a pagar con pago voluntario']]

# Obtener la columna "Consecutivo 1" del DataFrame
consecutivo_1 = excel_data['Consecutivo 1']

# Aplicar la transformación a cada valor de la columna "Consecutivo 1"

nueva_columna_consecutivo_cxc = [] #Se inicializa una lista vacía donde se 
                                   #almacenarán los valores transformados de la columna "Consecutivo 1
                                   
for valor in consecutivo_1: # Se itera sobre cada valor en la columna "Consecutivo 1".

    valor_str = str(valor)  # Se convierte el valor a cadena
              #esto se hace para asegurar que se pueda obtener la longitud del valor y concatenar correctamente.
    
    longitud_registro = len(valor_str) #Se calcula la longitud de la cadena resultante 
              #después de convertir el valor a cadena.
    
    cantidad_ceros = 10 - longitud_registro - 3  #Se calcula la cantidad de ceros necesarios
              #para que la longitud total sea 10, restando la longitud actual 
              #del valor más los caracteres adicionales que ya tenemos ('904').
              
    consecutivo_cxc = '904' + '0' * cantidad_ceros + valor_str #Se concatena '904' con la cantidad adecuada de ceros calculados 
              #y el valor original. Esto asegura que la longitud total sea 10,
              #con '904' al principio y el valor original al final.
    
    nueva_columna_consecutivo_cxc.append(consecutivo_cxc) #Se agrega el valor transformado a la lista  

# Agregar la nueva columna "consecutivo_cxc" al DataFrame
excel_data['consecutivo_cxc'] = nueva_columna_consecutivo_cxc

# Renombrar las Columnas
excel_data.rename(columns={'Tipo de documento': 'tipo_documento',
                           'Número de documento': 'numero_documento',
                           'Primer nombre': 'primer_nombre',
                           'Segundo nombre': 'segundo_nombre',
                           'Primer apellido': 'primer_apellido',
                           'Segundo apellido': 'segundo_apellido',
                           'Nombre productor': 'razon_social',
                           'Fecha de la visita': 'fecha_cobro',
                           }, inplace=True)

# Verificar si el valor en 'tipo_documento' es 'CC' o 'CE' y actualizar 'razon_social' en consecuencia
excel_data['razon_social'] = excel_data.apply(lambda row: '' if row['tipo_documento'] in 
                                              ['CC', 'CE'] else row['razon_social'], axis=1)


# Convertir la columna 'fecha_cobro' al formato deseado '%d/%m/%Y'
excel_data['fecha_cobro'] = pd.to_datetime(excel_data['fecha_cobro'], format='%Y-%m-%d %H:%M:%S.%f', errors='coerce')

# Agregar un día a cada fecha de 'fecha_cobro' y almacenar en 'fecha_vencimiento'
excel_data['fecha_vencimiento'] = pd.to_datetime(excel_data['fecha_cobro'], format='%d/%m/%Y') + pd.Timedelta(days=1)

# Llenar los valores faltantes con cero en las columnas 'Año Gravable' y 'Consecutivo 2'
excel_data['Año Gravable'].fillna('0', inplace=True)
excel_data['Consecutivo 2'].fillna('0', inplace=True)

# Convertir la columna 'Año Gravable' y 'Consecutivo 2' a enteros y luego a cadenas para eliminar ".0"
excel_data['descripción'] = 'DECLARE Y PAGUE AÑO GRAVABLE ' + excel_data['Año Gravable'].astype(int).astype(str) + ' Radicado No. ' + excel_data['Consecutivo 2'].astype(int).astype(str)


#EXPORTAR 

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


# Filtrar los datos que quieres exportar (ahora incluyendo la nueva columna 'fecha_vencimiento')
datos_exportar = excel_data[['Consecutivo 2','consecutivo_cxc', 'tipo_documento', 'numero_documento', 'primer_nombre', 
                             'segundo_nombre', 'primer_apellido', 'segundo_apellido', 'razon_social', 
                             'fecha_cobro', 'fecha_vencimiento','descripción',
                             '40. Total a pagar con pago voluntario','Estado Pago','ESTADO']].copy()


# Crear una nueva hoja al archivo de Excel llamada "encabezado"
ws_encabezado = wb.create_sheet(title='encabezado')

# Cargar datos desde el nuevo archivo Excel 'declaraciones-actividades.xlsx'
nuevo_excel_data = pd.read_excel('declaraciones-actividades.xlsx')

# Definir una función para separar el código y la descripción
def separar_codigo_descripcion(valor):
    if isinstance(valor, str):  # Solo aplica split si es una cadena
        partes = valor.split(' - ', 1)
        return partes if len(partes) == 2 else (valor, "")  
    else:
        return (valor, "")  # Devuelve el número tal cual y una cadena vacía si no es str


# Aplicar la función a la columna 'Código según codificación municipal o distrital' y guardar los resultados en nuevas columnas
nuevo_excel_data['codigo'], nuevo_excel_data['descripcion_codigo'] = zip(*nuevo_excel_data['Código según codificación municipal o distrital'].apply(separar_codigo_descripcion))

# Eliminar la columna original 'Código según codificación municipal o distrital'
nuevo_excel_data.drop(columns=['Código según codificación municipal o distrital'], inplace=True)

# Filtrar las columnas requeridas
datos_detalle = nuevo_excel_data[['Consecutivo 2', 'codigo', 'Impuestos de industria y comercio']]

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

# Convertir la columna 'Consecutivo 2' a tipo de datos str en ambos DataFrames
excel_data['Consecutivo 2'] = excel_data['Consecutivo 2'].astype(str)
datos_detalle_fusionados['Consecutivo 2'] = datos_detalle_fusionados['Consecutivo 2'].astype(str)

# Realizar el cruce con la hoja 'declaraciones-general' para obtener las columnas solicitadas
datos_impuesto = excel_data[['Consecutivo 2', '17. TOTAL IMPUESTO ($ COP)', 
                                                                         '21. Impuesto de Avisos y Tableros ($ COP)', 
                                                                         '23. Sobretasa Bomberil', 
                                                                         '27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo', 
                                                                         '28. Menos autorretenciones practicadas a favor de este municipio o distrito en este periodo', 
                                                                         '29. Menos anticipo liquidado en el año anterior', 
                                                                         'Digite valor sanciones a declarar', 
                                                                         '37. INTERESES DE MORA', 
                                                                         '39. Liquide el valor del pago voluntario']]

# Convertir la columna 'Consecutivo 2' a tipo de datos cadena (str) y eliminar los '.0'
datos_impuesto.loc[:, 'Consecutivo 2'] = datos_impuesto['Consecutivo 2'].astype(str).str.replace('\.0', '', regex=True)



# Seleccionar las columnas requeridas para la nueva hoja
df_impuestos = datos_impuesto[['Consecutivo 2', '17. TOTAL IMPUESTO ($ COP)', 
                                                                         '21. Impuesto de Avisos y Tableros ($ COP)', 
                                                                         '23. Sobretasa Bomberil', 
                                                                         '27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo', 
                                                                         '28. Menos autorretenciones practicadas a favor de este municipio o distrito en este periodo', 
                                                                         '29. Menos anticipo liquidado en el año anterior', 
                                                                         'Digite valor sanciones a declarar', 
                                                                         '37. INTERESES DE MORA', 
                                                                         '39. Liquide el valor del pago voluntario']]

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna '27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo'
df_impuestos.loc[:, 'concepto4'] = ''
df_impuestos.loc[:, 'descripcion4'] = ''
df_impuestos.loc[df_impuestos['27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo'] != 0, 'concepto4'] = 'HDA831'
df_impuestos.loc[df_impuestos['27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo'] != 0, 'descripcion4'] = 'RETENCIONES DECLARACION ANUAL ICA'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'ICA'
columnas_seleccionadas = ['Consecutivo 2', 'concepto4', 'descripcion4', '27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo']
RETE = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'RETE'
print(RETE)

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna '21. Impuesto de Avisos y Tableros ($ COP)'
df_impuestos.loc[:, 'concepto5'] = ''
df_impuestos.loc[:, 'descripcion5'] = ''
df_impuestos.loc[datos_impuesto['21. Impuesto de Avisos y Tableros ($ COP)'] != 0, 'concepto5'] = 'HD192'
df_impuestos.loc[datos_impuesto['21. Impuesto de Avisos y Tableros ($ COP)'] != 0, 'descripcion5'] = 'AVISOS Y TABLEROS'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'AT'
columnas_seleccionadas = ['Consecutivo 2', 'concepto5', 'descripcion5','21. Impuesto de Avisos y Tableros ($ COP)']
AT = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'AT'
print(AT)

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna '23. Sobretasa Bomberil'
df_impuestos.loc[:, 'concepto6'] = ''
df_impuestos.loc[:, 'descripcion6'] = ''
df_impuestos.loc[datos_impuesto['23. Sobretasa Bomberil'] != 0, 'concepto6'] = 'HD193'
df_impuestos.loc[datos_impuesto['23. Sobretasa Bomberil'] != 0, 'descripcion6'] = 'SOBRETASA BOMBERIL'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'ST'
columnas_seleccionadas = ['Consecutivo 2', 'concepto6', 'descripcion6','23. Sobretasa Bomberil']
ST = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'ST'
print(ST)

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna 'Digite valor sanciones a declarar'
df_impuestos.loc[:, 'concepto7'] = ''
df_impuestos.loc[:, 'descripcion7'] = ''
df_impuestos.loc[datos_impuesto['Digite valor sanciones a declarar'] != 0, 'concepto7'] = 'HD22'
df_impuestos.loc[datos_impuesto['Digite valor sanciones a declarar'] != 0, 'descripcion7'] = 'SANCIONES'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'ST'
columnas_seleccionadas = ['Consecutivo 2', 'concepto7', 'descripcion7','Digite valor sanciones a declarar']
SANC = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'SANC'
print(SANC)

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna '37. INTERESES DE MORA'
df_impuestos.loc[:, 'concepto8'] = ''
df_impuestos.loc[:, 'descripcion8'] = ''
df_impuestos.loc[datos_impuesto['37. INTERESES DE MORA'] != 0, 'concepto8'] = 'IntICOM'
df_impuestos.loc[datos_impuesto['37. INTERESES DE MORA'] != 0, 'descripcion8'] = 'INTERESES'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'INT'
columnas_seleccionadas = ['Consecutivo 2', 'concepto8', 'descripcion8','37. INTERESES DE MORA']
INT = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'INT'
print(INT)

# Verificar si los consecutivos tienen algún valor diferente de 0 en la columna '39. Liquide el valor del pago voluntario'
df_impuestos.loc[:, 'concepto9'] = ''
df_impuestos.loc[:, 'descripcion9'] = ''
df_impuestos.loc[datos_impuesto['39. Liquide el valor del pago voluntario'] != 0, 'concepto9'] = 'HDA838'
df_impuestos.loc[datos_impuesto['39. Liquide el valor del pago voluntario'] != 0, 'descripcion9'] = 'PAGO VOLUNTARIO ANUAL'

#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'INT'
columnas_seleccionadas = ['Consecutivo 2', 'concepto9', 'descripcion9','39. Liquide el valor del pago voluntario']
VOL = df_impuestos[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'INT'
print(VOL)

# Agrupar los datos por 'Consecutivo 2' y 'Tipo de Servicio', luego sumar los valores de 'Impuestos de industria y comercio'
datos_actividades_agrupados = datos_detalle_fusionados.groupby(['Consecutivo 2', 'TIPO'])['Impuestos de industria y comercio'].sum().reset_index()

# Cambiar el nombre de la columna 'Impuestos de industria y comercio' por 'Total Impuestos'
datos_actividades_agrupados.rename(columns={'Impuestos de industria y comercio': 'Total Impuestos'}, inplace=True)

# Eliminar las columnas que ya no se neceita en 'encabezado'.
#datos_exportar = datos_exportar.drop(columns=['Consecutivo 2'])

# Convertir la columna 'Consecutivo 2' en la hoja 'encabezado' al tipo de datos texto y eliminar '.0'
datos_exportar['Consecutivo 2'] = datos_exportar['Consecutivo 2'].astype(str).str.replace('\.0', '', regex=True)

# Leer el archivo novedades.xlsx
noved_data = pd.read_excel('NOVEDADES.xlsx')

# Asegurar que la columna 'Consecutivo 2' sea de tipo cadena en ambos DataFrames
noved_data['Consecutivo 2'] = noved_data['Consecutivo 2'].astype(str)
datos_exportar['Consecutivo 2'] = datos_exportar['Consecutivo 2'].astype(str)

# Hacer el cruce (merge) entre el DataFrame 'datos_exportar' y 'novedades_data' basado en 'Consecutivo 2'
# Solo traemos la columna 'estado' desde el DataFrame 'novedades_data'
datos_exportar = pd.merge(datos_exportar, noved_data[['Consecutivo 2', 'estado']], 
                          on='Consecutivo 2', how='left')

# Convertir la columna 'Consecutivo 2' a texto en la hoja 'encabezado' y eliminar '.0'
datos_exportar['Consecutivo 2'] = datos_exportar['Consecutivo 2'].astype(str).str.replace('\.0', '', regex=True)


# Agregar los datos a la hoja de Excel
for row in dataframe_to_rows(datos_exportar, index=False, header=True):
    ws_encabezado.append(row)
    
 # Realizar el cruce entre las hojas 'actividades' y 'encabezado' antes de exportar

# Realizar la fusión basada en la columna 'Consecutivo 2'
df_porcentaje = pd.merge(datos_actividades_agrupados, datos_impuesto[['Consecutivo 2', '17. TOTAL IMPUESTO ($ COP)', 
'27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo', 
'28. Menos autorretenciones practicadas a favor de este municipio o distrito en este periodo', 
'29. Menos anticipo liquidado en el año anterior','21. Impuesto de Avisos y Tableros ($ COP)', 
'23. Sobretasa Bomberil','Digite valor sanciones a declarar', '37. INTERESES DE MORA']], on='Consecutivo 2', how='left')

# Seleccionar las columnas requeridas para la nueva hoja
df_porcentaje = df_porcentaje[[*datos_actividades_agrupados.columns, '17. TOTAL IMPUESTO ($ COP)', 
'27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo', 
'28. Menos autorretenciones practicadas a favor de este municipio o distrito en este periodo', 
'29. Menos anticipo liquidado en el año anterior','Digite valor sanciones a declarar', 
'37. INTERESES DE MORA','21. Impuesto de Avisos y Tableros ($ COP)', '23. Sobretasa Bomberil']]


# Calcular el porcentaje del valor en la columna "g" con respecto al valor total en la columna "b"
df_porcentaje['Porcentaje'] = ((df_porcentaje['Total Impuestos']) * 1) / df_porcentaje['17. TOTAL IMPUESTO ($ COP)']

# Calcular la retencion por actividad

#df_porcentaje['retencion'] = df_porcentaje['27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo'] *df_porcentaje['Porcentaje']

# Calcular la autorretencion por actividad
df_porcentaje['autorrete'] = df_porcentaje['28. Menos autorretenciones practicadas a favor de este municipio o distrito en este periodo'] *df_porcentaje['Porcentaje']

# Calcular la autorretencion por actividad
df_porcentaje['anticipo'] = df_porcentaje['29. Menos anticipo liquidado en el año anterior'] *df_porcentaje['Porcentaje']


# Renombrar la columna 'Total Impuestos' a 'ICA'
df_porcentaje.rename(columns={'Total Impuestos': 'ICA'}, inplace=True)

# Eliminar las columnas que ya no se neceita.
df_porcentaje.drop(columns=['17. TOTAL IMPUESTO ($ COP)','29. Menos anticipo liquidado en el año anterior','Porcentaje'], inplace=True)

# Añadir columna 'concepto1' con valores predeterminados
df_porcentaje['concepto1'] = ''

# Definir los valores de 'concepto1' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'concepto1'] = 'HDA839'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'concepto1'] = 'HD75'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'concepto1'] = 'HDA840'

# Añadir columna 'descripcion1' con valores predeterminados
df_porcentaje['descripcion1'] = ''

# Definir los valores de 'concepto1' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'descripcion1'] = 'INDUSTRIA Y COMERCIO INDUSTRIA'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'descripcion1'] = 'INDUSTRIA Y COMERCIO COMERCIAL'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'descripcion1'] = 'INDUSTRIA Y COMERCIO SERVICIO'


# Añadir columna 'concepto2' con valores predeterminados
df_porcentaje['concepto2'] = ''

# Definir los valores de 'concepto2' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'concepto2'] = 'HDA832'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'concepto2'] = 'HDA833'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'concepto2'] = 'HDA834'

# Añadir columna 'descripcion2' con valores predeterminados
df_porcentaje['descripcion2'] = ''

# Definir los valores de 'concepto1' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'descripcion2'] = 'AUTORRETENCIONES INDUSTRIAL'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'descripcion2'] = 'AUTORRETENCIONES COMERCIAL'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'descripcion2'] = 'AUTORRETENCIONES SERVICIOS'


# Añadir columna 'concepto3' con valores predeterminados
df_porcentaje['concepto3'] = ''

# Definir los valores de 'concepto2' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'concepto3'] = 'HDA835'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'concepto3'] = 'HDA836'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'concepto3'] = 'HDA837'

# Añadir columna 'descripcion3' con valores predeterminados
df_porcentaje['descripcion3'] = ''

# Definir los valores de 'concepto1' según el valor en la columna 'TIPO'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'INDUSTRIAL', 'descripcion3'] = 'ANTICIPO INDUSTRIAL'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'COMERCIAL', 'descripcion3'] = 'ANTICIPO COMERCIAL'
df_porcentaje.loc[df_porcentaje['TIPO'] == 'SERVICIOS', 'descripcion3'] = 'ANTICIPO SERVICIOS'


#CREAR DATAFRAMES 
# Seleccionar las columnas específicas para crear el DataFrame 'ICA'
columnas_seleccionadas = ['Consecutivo 2', 'concepto1', 'descripcion1', 'ICA']
ICA = df_porcentaje[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'ICA'
print(ICA.head())

# Seleccionar las columnas específicas para crear el DataFrame 'AUTORRETENCIONES'
columnas_seleccionadas = ['Consecutivo 2', 'concepto2', 'descripcion2', 'autorrete']
AUTO = df_porcentaje[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'AUTO'
print(AUTO.head())

# Seleccionar las columnas específicas para crear el DataFrame 'anticipo'
columnas_seleccionadas = ['Consecutivo 2', 'concepto3', 'descripcion3', 'anticipo']
ANTI = df_porcentaje[columnas_seleccionadas]

# Mostrar las primeras filas del DataFrame 'AUTO'
print(ANTI.head())

# crear dataframes para no indexar directamente 
df_ica = ICA.copy()
df_auto = AUTO.copy()
df_anti= ANTI.copy()
df_rete= RETE.copy()
df_at = AT.copy()
df_st = ST.copy()
df_sanc = SANC.copy()
df_int = INT.copy()
df_vol = VOL.copy()
# Eliminar los encabezados originales de cada DataFrame
df_ica.rename(columns={'Consecutivo 2': 'declaracion', 'concepto1': 'codigo_concepto', 'descripcion1': 'descripcion', 'ICA': 'Valor'}, inplace=True)
df_auto.rename(columns={'Consecutivo 2': 'declaracion', 'concepto2': 'codigo_concepto', 'descripcion2': 'descripcion', 'autorrete': 'Valor'}, inplace=True)
df_anti.rename(columns={'Consecutivo 2': 'declaracion', 'concepto3': 'codigo_concepto', 'descripcion3': 'descripcion', 'anticipo': 'Valor'}, inplace=True)
df_rete.rename(
    columns={
        "Consecutivo 2": "declaracion",
        "concepto4": "codigo_concepto",
        "descripcion4": "descripcion",
        "27. Menos retenciones que le practicaron a favor de este municipio o distrito en este periodo": "Valor",
    },
    inplace=True,
)
df_at.rename(columns={'Consecutivo 2': 'declaracion', 'concepto5': 'codigo_concepto', 'descripcion5': 'descripcion', '21. Impuesto de Avisos y Tableros ($ COP)': 'Valor'}, inplace=True)
df_st.rename(columns={'Consecutivo 2': 'declaracion', 'concepto6': 'codigo_concepto', 'descripcion6': 'descripcion', '23. Sobretasa Bomberil': 'Valor'}, inplace=True)
df_sanc.rename(columns={'Consecutivo 2': 'declaracion', 'concepto7': 'codigo_concepto', 'descripcion7': 'descripcion', 'Digite valor sanciones a declarar': 'Valor'}, inplace=True)
df_int.rename(columns={'Consecutivo 2': 'declaracion', 'concepto8': 'codigo_concepto', 'descripcion8': 'descripcion', '37. INTERESES DE MORA': 'Valor'}, inplace=True)
df_vol.rename(columns={'Consecutivo 2': 'declaracion', 'concepto9': 'codigo_concepto', 'descripcion9': 'descripcion', '39. Liquide el valor del pago voluntario': 'Valor'}, inplace=True)

# Concatenar los DataFrames
df_detalles = pd.concat([df_ica,df_auto,df_anti,df_rete,df_at,df_st,df_sanc,df_int,df_vol])

# Reordenar las columnas para tener los encabezados deseados
df_detalles = df_detalles[['declaracion','codigo_concepto', 'descripcion', 'Valor']]



# Crear un nuevo archivo de Excel y una nueva hoja en el archivo de Excel llamada "detalles"

ws_detalles = wb.create_sheet(title='detalles')



# Fusionar las hojas 'detalles' y 'encabezado' basado en la columna 'declaracion' ('Consecutivo 2')
df_detalles_fusionado = pd.merge(df_detalles, datos_exportar[['Consecutivo 2', 'consecutivo_cxc']], left_on='declaracion', right_on='Consecutivo 2', how='left')

# Convertir la columna 'Consecutivo 2' en la hoja 'detalles' al tipo de datos correcto
df_detalles_fusionado['declaracion'] = df_detalles_fusionado['declaracion'].astype(str)


# Eliminar la columna 'Consecutivo 2' que se agregó automáticamente en la fusión
df_detalles_fusionado.drop(columns=['Consecutivo 2'], inplace=True)
# Agregar las nuevas columnas 'CENTRO DE COSTOS' y 'CANTIDAD' con los valores especificados
df_detalles_fusionado['centro_costo'] = '07'
df_detalles_fusionado['cantidad'] = '1'

# Duplicar la columna 'Valor' en el DataFrame df_detalles_fusionado
df_detalles_fusionado['valor_unitario'] = df_detalles_fusionado['Valor']
df_detalles_fusionado['valor_total'] = df_detalles_fusionado['Valor']

# Reordenar las columnas para tener los encabezados deseados
df_detalles_fusionado = df_detalles_fusionado[['declaracion','consecutivo_cxc', 'codigo_concepto','centro_costo', 'cantidad', 'valor_unitario', 'valor_total']]



# Escribir los datos en la hoja de Excel
for row in dataframe_to_rows(df_detalles_fusionado, index=False, header=True):
    ws_detalles.append(row)
    
    
# Eliminar la hoja vacía 'Sheet' del archivo de Excel
try:
    del wb['Sheet']
except KeyError:
    pass


# Pedir al usuario el nombre del archivo de destino
nombre_archivo = input("Por favor, ingresa el nombre del archivo de destino (sin extensión): ")

# Guardar el archivo de Excel con todas las hojas
wb.save(f"{nombre_archivo}.xlsx")

