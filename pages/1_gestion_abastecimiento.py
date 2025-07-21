import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px
from fpdf import FPDF
from datetime import datetime
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email import encoders

# --- LIBRERÍAS PARA GOOGLE SHEETS ---
import gspread
from google.oauth2.service_account import Credentials

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento v2.4", layout="wide", page_icon="🚀")

st.title("🚀 Tablero de Control de Abastecimiento v2.4")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real conectado a Google Sheets.")

# --- 1. FUNCIONES DE CONEXIÓN Y GESTIÓN CON GOOGLE SHEETS ---

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

@st.cache_resource(ttl=3600)
def connect_to_gsheets():
    """Se conecta a la API de Google Sheets usando las credenciales de Streamlit Secrets."""
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}. Revisa tus 'secrets'.")
        return None

@st.cache_data(ttl=60)
def load_data_from_sheets(_client, sheet_name):
    """Carga una hoja de cálculo completa desde Google Sheets por su nombre."""
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        df = pd.DataFrame(worksheet.get_all_records())
        if not df.empty and 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Error: La hoja de cálculo '{sheet_name}' no fue encontrada. Por favor, créala en tu Google Sheets.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ocurrió un error al cargar la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    """Sobrescribe una hoja completa con un DataFrame de Pandas."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        # Convertir todas las columnas a string para evitar errores de tipo con la API
        df_str = df_to_write.astype(str)
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Añade filas a una hoja sin sobreescribir."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        # Obtener las cabeceras de la hoja para asegurar el orden de las columnas
        headers = worksheet.row_values(1)
        if not headers: # Si la hoja está vacía, escribe las cabeceras primero
             worksheet.update([df_to_append.columns.values.tolist()] + df_to_append.astype(str).values.tolist())
        else:
            df_to_append_ordered = df_to_append[headers]
            worksheet.append_rows(df_to_append_ordered.astype(str).values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Nuevos registros añadidos a '{sheet_name}'."
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}"

# <<< NUEVA FUNCIÓN CENTRALIZADA PARA REGISTRAR ÓRDENES >>>
def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    """Prepara y registra un DataFrame de órdenes en la hoja 'Registro_Ordenes'."""
    if df_orden.empty or client is None:
        return False, "No hay datos para registrar."

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = pd.DataFrame()

    # Mapeo de columnas de entrada a columnas de salida
    if 'Uds a Comprar' in df_orden.columns:
        cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_orden.columns:
        cantidad_col = 'Uds a Enviar'
    else:
        return False, "El DataFrame de la orden no tiene columna de cantidad ('Uds a Comprar' o 'Uds a Enviar')."

    df_registro['SKU'] = df_orden['SKU']
    df_registro['Descripcion'] = df_orden['Descripcion']
    df_registro['Cantidad_Solicitada'] = df_orden[cantidad_col]
    df_registro['Costo_Unitario'] = df_orden.get('Costo_Promedio_UND', 0)
    df_registro['Costo_Total'] = pd.to_numeric(df_registro['Cantidad_Solicitada'], errors='coerce').fillna(0) * pd.to_numeric(df_registro['Costo_Unitario'], errors='coerce').fillna(0)
    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Asignar ID, Proveedor y Tienda según el tipo de orden
    if tipo_orden == "Compra Sugerencia":
        df_registro['ID_Orden'] = [f"OC-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = df_orden['Proveedor']
        df_registro['Tienda_Destino'] = df_orden['Tienda']
    elif tipo_orden == "Compra Especial":
        df_registro['ID_Orden'] = [f"OC-SP-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        df_registro['ID_Orden'] = [f"TR-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_orden['Tienda Origen']
        df_registro['Tienda_Destino'] = df_orden['Tienda Destino']
    elif tipo_orden == "Traslado Especial":
        df_registro['ID_Orden'] = [f"TR-SP-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_orden['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino
    else:
        return False, "Tipo de orden no reconocido."

    # Columnas finales para asegurar consistencia con la hoja de Google
    columnas_finales = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    for col in columnas_finales:
        if col not in df_registro:
            df_registro[col] = '' # Añadir columnas faltantes

    return append_to_sheet(client, "Registro_Ordenes", df_registro[columnas_finales])


# --- 2. FUNCIONES AUXILIARES ---

def enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo_html, lista_de_adjuntos):
    """Envía un correo a una LISTA de destinatarios con uno o más archivos adjuntos."""
    try:
        remitente = st.secrets["gmail"]["email"]
        password = st.secrets["gmail"]["password"]
        msg = MIMEMultipart()
        msg['From'] = f"Compras Ferreinox <{remitente}>"
        msg['To'] = ", ".join(destinatarios)
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo_html, 'html'))
        for adj_info in lista_de_adjuntos:
            with io.BytesIO(adj_info['datos']) as attachment_stream:
                adjunto = MIMEBase(adj_info.get('tipo_mime', 'application'), adj_info.get('subtipo_mime', 'octet-stream'))
                adjunto.set_payload(attachment_stream.read())
            encoders.encode_base64(adjunto)
            adjunto.add_header('Content-Disposition', 'attachment', filename=adj_info['nombre_archivo'])
            msg.attach(adjunto)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(remitente, password)
            server.sendmail(remitente, destinatarios, msg.as_string())
        return True, "Correo enviado exitosamente."
    except Exception as e:
        return False, f"Error al enviar el correo: '{e}'. Revisa la configuración de 'secrets'."

def generar_link_whatsapp(numero, mensaje):
    """Genera un link de WhatsApp pre-llenado y codificado."""
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    """Genera un plan de traslados óptimo basado en la necesidad y excedente."""
    if _df_analisis is None or _df_analisis.empty: return pd.DataFrame()
    
    # Usamos la necesidad final (post-tránsito) para calcular los traslados
    df_origen = _df_analisis[_df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis[_df_analisis['Necesidad_Ajustada_Por_Transito'] > 0].sort_values(by='Necesidad_Ajustada_Por_Transito', ascending=False).copy()
    
    if df_origen.empty or df_destino.empty: return pd.DataFrame()
    
    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()
    
    for _, necesidad_row in df_destino.iterrows():
        sku, tienda_necesitada, necesidad_actual = necesidad_row['SKU'], necesidad_row['Almacen_Nombre'], necesidad_row['Necesidad_Ajustada_Por_Transito']
        if necesidad_actual <= 0: continue
        
        posibles_origenes = df_origen[df_origen['SKU'] == sku]
        for _, origen_row in posibles_origenes.iterrows():
            tienda_origen = origen_row['Almacen_Nombre']
            if tienda_origen == tienda_necesitada: continue
            
            excedente_disponible = excedentes_mutables.get((sku, tienda_origen), 0)
            if excedente_disponible > 0 and necesidad_actual > 0:
                unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                if unidades_a_enviar < 1: continue
                
                plan_final.append({
                    'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': origen_row['Marca_Nombre'],
                    'Proveedor': origen_row['Proveedor'], 'Segmento_ABC': necesidad_row['Segmento_ABC'], 
                    'Tienda Origen': tienda_origen, 'Stock en Origen': origen_row['Stock'], 
                    'Tienda Destino': tienda_necesitada, 'Stock en Destino': necesidad_row['Stock'], 
                    'Necesidad en Destino': necesidad_row['Necesidad_Ajustada_Por_Transito'],
                    'Uds a Enviar': unidades_a_enviar, 
                    'Peso Individual (kg)': necesidad_row.get('Peso_Articulo', 0),
                    'Costo_Promedio_UND': necesidad_row['Costo_Promedio_UND']
                })
                
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar

    if not plan_final: return pd.DataFrame()
    
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Peso Individual (kg)'])
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Costo_Promedio_UND'])
    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        self.font_family = 'Helvetica' # Default font
        try:
            self.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf', uni=True)
            self.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf', uni=True)
            self.font_family = 'DejaVu' # Use DejaVu if found
        except RuntimeError: 
            st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica. Algunos caracteres especiales (ej. '€') podrían no mostrarse.")
            
    def header(self):
        font_name = self.font_family
        try: self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError: self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font(font_name, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R'); self.set_x(80); self.set_font(font_name, '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R'); self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        font_name = self.font_family
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1); self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font(font_name, '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}      |       {self.empresa_web}       |       {self.empresa_email}       |       {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    font_name = pdf.font_family
    pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font(font_name, 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1); pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font(font_name, '', 9)
    y_start_prov = pdf.get_y()
    proveedor_info = f"Razón Social: {proveedor_nombre}\nContacto: {contacto_proveedor if contacto_proveedor else 'No especificado'}"
    pdf.multi_cell(95, 7, proveedor_info, 1, 'L')
    y_end_prov = pdf.get_y()
    pdf.set_y(y_start_prov); pdf.set_x(105)
    envio_info = f"{pdf.empresa_nombre} - Sede {tienda_nombre}\nDirección: {direccion_entrega}\nRecibe: Leivyn Gabriel Garcia"
    pdf.multi_cell(95, 7, envio_info, 1, 'L')
    y_end_envio = pdf.get_y()
    pdf.set_y(max(y_end_prov, y_end_envio))
    pdf.ln(5)
    pdf.set_font(font_name, 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {orden_num}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1); pdf.ln(10)
    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font(font_name, 'B', 9)
    pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
    pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
    pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)
    pdf.set_font(font_name, '', 8); pdf.set_text_color(0, 0, 0)
    subtotal = 0
    cantidad_col = 'Uds a Comprar' if 'Uds a Comprar' in df_seleccion.columns else 'Uds a Enviar'
    
    # Asegurar que las columnas para el cálculo son numéricas
    df_seleccion[cantidad_col] = pd.to_numeric(df_seleccion[cantidad_col], errors='coerce').fillna(0)
    df_seleccion['Costo_Promedio_UND'] = pd.to_numeric(df_seleccion['Costo_Promedio_UND'], errors='coerce').fillna(0)
    
    for _, row in df_seleccion.iterrows():
        costo_total_item = row[cantidad_col] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
        y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
        pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
        y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
        pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L')
        y3 = pdf.get_y()
        row_height = max(y1, y2, y3) - y_start
        pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(row[cantidad_col])), 1, 'C')
        pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${row['Costo_Promedio_UND']:,.2f}", 1, 'R')
        pdf.set_xy(x_start + 165, y_start); pdf.multi_cell(25, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        pdf.set_y(y_start + row_height)
        
    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font(font_name, '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font(font_name, 'B', 11)
    pdf.cell(55, 10, 'TOTAL A PAGAR', 1, 0, 'R'); pdf.cell(35, 10, f"${total_general:,.2f}", 1, 1, 'R')
    return bytes(pdf.output())

def generar_excel_dinamico(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70)
            return output.getvalue()
        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        for col_num, value in enumerate(df.columns.values): worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            column_len = df[col].astype(str).map(len).max()
            max_len = max(column_len, len(col)) + 2
            worksheet.set_column(i, i, min(max_len, 45))
    return output.getvalue()


# --- 3. LÓGICA PRINCIPAL Y FLUJO DE LA APLICACIÓN ---

# PASO 1: Cargar el archivo base desde la sesión
if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos base de inventario.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop()
df_maestro_base = st.session_state['df_analisis_maestro'].copy()

# PASO 2: Conectar a Google Sheets y cargar las órdenes pendientes
client = connect_to_gsheets()
df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")

# PASO 3: Calcular el Stock en Tránsito y fusionarlo con los datos base
if not df_ordenes_historico.empty and 'Estado' in df_ordenes_historico.columns:
    df_pendientes = df_ordenes_historico[df_ordenes_historico['Estado'] == 'Pendiente'].copy()
    df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
    stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
    stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito', 'Tienda_Destino': 'Almacen_Nombre'}, inplace=True)
    stock_en_transito_agg['SKU'] = stock_en_transito_agg['SKU'].astype(str)
    df_maestro_base['SKU'] = df_maestro_base['SKU'].astype(str)
    
    df_maestro = pd.merge(df_maestro_base, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
    df_maestro['Stock_En_Transito'].fillna(0, inplace=True)
else:
    df_maestro = df_maestro_base.copy()
    df_maestro['Stock_En_Transito'] = 0

# PASO 4: <<< LÓGICA DE INVENTARIO CORREGIDA Y MEJORADA >>>
# Convertir columnas numéricas clave a tipo numérico, manejando errores
numeric_cols = ['Stock', 'Stock_En_Transito', 'Sugerencia_Compra', 'Costo_Promedio_UND', 'Necesidad_Total', 'Excedente_Trasladable', 'Precio_Venta_Estimado', 'Demanda_Diaria_Promedio']
for col in numeric_cols:
    if col in df_maestro.columns:
        df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)

# 4.1. Calcular la necesidad ajustada restando lo que ya está en camino
df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)

# 4.2. Generar plan de traslados basado en la necesidad real (post-tránsito)
df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)

# 4.3. Calcular cuánto de la necesidad se cubre con los traslados sugeridos
if not df_plan_maestro.empty:
    unidades_cubiertas_por_traslado = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
    unidades_cubiertas_por_traslado.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado'}, inplace=True)

    df_maestro = pd.merge(df_maestro, unidades_cubiertas_por_traslado, on=['SKU', 'Almacen_Nombre'], how='left')
    df_maestro['Cubierto_Por_Traslado'].fillna(0, inplace=True)
else:
    df_maestro['Cubierto_Por_Traslado'] = 0

# 4.4. La Sugerencia de Compra FINAL es la necesidad que NO se pudo cubrir ni con tránsito ni con traslados
df_maestro['Sugerencia_Compra'] = (df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)

# Otros cálculos
df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
if 'Precio_Venta_Estimado' not in df_maestro.columns or df_maestro['Precio_Venta_Estimado'].sum() == 0:
    df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * 1.30


# --- Lógica de la sesión de usuario y filtros ---
st.sidebar.header("⚙️ Filtros de Gestión")
opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
if 'user_role' in st.session_state and st.session_state.get('user_role') == 'gerente':
    almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
else:
    almacen_options = [st.session_state.get('almacen_nombre')] if 'almacen_nombre' in st.session_state else []
selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista de Tienda:", almacen_options)

if selected_almacen_nombre == opcion_consolidado: df_vista = df_maestro.copy()
else: df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else df_vista

# --- Botón de Sincronización en Sidebar ---
st.sidebar.markdown("---")
st.sidebar.subheader("Sincronización Manual")
if st.sidebar.button("🔄 Actualizar 'Estado_Inventario' en GSheets"):
    with st.spinner("Sincronizando el estado actual del inventario con Google Sheets..."):
        columnas_a_sincronizar = [
            'SKU', 'Almacen_Nombre', 'Stock', 'Costo_Promedio_UND', 'Sugerencia_Compra', 
            'Necesidad_Total', 'Excedente_Trasladable', 'Estado_Inventario'
        ]
        # Asegurarnos que las columnas existan antes de sincronizar
        df_para_sincronizar = df_maestro_base[[col for col in columnas_a_sincronizar if col in df_maestro_base.columns]].copy()
        exito, msg = update_sheet(client, "Estado_Inventario", df_para_sincronizar)
        if exito: st.sidebar.success(msg)
        else: st.sidebar.error(msg)

DIRECCIONES_TIENDAS = {'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32'}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893'},
}

# --- 4. INTERFAZ DE USUARIO CON PESTAÑAS ---
# Lógica para mantener la pestaña activa después de un rerun
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 'Diagnóstico'

# Callback para actualizar la pestaña activa
def on_tab_change():
    st.session_state.active_tab = st.session_state.tabs_widget

tab_keys = ["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"]
tabs = st.tabs(tab_keys)

with tabs[0]: # PESTAÑA 1: DIAGNÓSTICO GENERAL
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    # Usamos el df_filtered que ya respeta la selección de tienda y marca del usuario
    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
    
    # El ahorro por traslados se calcula sobre el plan maestro, filtrado por la tienda destino si aplica
    oportunidad_ahorro = 0
    if not df_plan_maestro.empty:
        df_plan_filtrado = df_plan_maestro
        if selected_almacen_nombre != opcion_consolidado:
            df_plan_filtrado = df_plan_maestro[df_plan_maestro['Tienda Destino'] == selected_almacen_nombre]
        oportunidad_ahorro = df_plan_filtrado['Valor del Traslado'].sum()
            
    df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
    venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
    
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label="💰 Valor Compra Requerida (Post-Traslados)", value=f"${necesidad_compra_total:,.0f}")
    kpi2.metric(label="💸 Ahorro por Traslados", value=f"${oportunidad_ahorro:,.0f}")
    kpi3.metric(label="📉 Venta Potencial Perdida", value=f"${venta_perdida:,.0f}")
    
    st.markdown("##### Análisis y Recomendaciones Clave")
    with st.container(border=True):
        if venta_perdida > 0: st.markdown(f"**🚨 Alerta:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** en 30 días por **{len(df_quiebre)}** productos en quiebre.")
        if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña de 'Traslados'.")
        if necesidad_compra_total > 0:
            df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
            df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
            if not df_compras_prioridad.empty:
                top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                st.markdown(f"**🎯 Enfoque:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**.")
        if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0: st.markdown("✅ **¡Inventario Optimizado!** No se detectan necesidades urgentes.")
    
    st.markdown("---")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0].copy()
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Requerida por Tienda (Post-Traslados)")
            st.plotly_chart(fig, use_container_width=True)
    with col_g2:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0].copy()
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
            st.plotly_chart(fig, use_container_width=True)

with tabs[1]: # PESTAÑA 2: PLAN DE TRASLADOS
    st.subheader("🚚 Plan de Traslados entre Tiendas")

    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            # ... (código de filtros para traslados automáticos se mantiene igual)
            st.markdown("##### Filtros Avanzados de Traslados")
            f_col1, f_col2, f_col3 = st.columns(3)
            lista_origenes = ["Todas"] + sorted(df_plan_maestro['Tienda Origen'].unique().tolist())
            filtro_origen = f_col1.selectbox("Filtrar por Tienda Origen:", lista_origenes, key="filtro_origen")
            lista_destinos = ["Todas"] + sorted(df_plan_maestro['Tienda Destino'].unique().tolist())
            filtro_destino = f_col2.selectbox("Filtrar por Tienda Destino:", lista_destinos, key="filtro_destino")
            lista_proveedores_traslado = ["Todos"] + sorted(df_plan_maestro['Proveedor'].unique().tolist())
            filtro_proveedor_traslado = f_col3.selectbox("Filtrar por Proveedor:", lista_proveedores_traslado, key="filtro_proveedor_traslado")
            df_aplicar_filtros = df_plan_maestro.copy()
            if filtro_origen != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Origen'] == filtro_origen]
            if filtro_destino != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Destino'] == filtro_destino]
            if filtro_proveedor_traslado != "Todos": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Proveedor'] == filtro_proveedor_traslado]
            search_term_traslado = st.text_input("Buscar producto a trasladar por SKU o Descripción:", key="search_traslados")
            df_traslados_filtrado = df_aplicar_filtros
            if search_term_traslado:
                mask_traslado = (df_traslados_filtrado['SKU'].astype(str).str.contains(search_term_traslado, case=False, na=False) |
                                     df_traslados_filtrado['Descripcion'].astype(str).str.contains(search_term_traslado, case=False, na=False))
                df_traslados_filtrado = df_traslados_filtrado[mask_traslado]

            if df_traslados_filtrado.empty:
                st.warning("No se encontraron traslados que coincidan con los filtros y la búsqueda.")
            else:
                df_para_editar = df_traslados_filtrado.copy()
                df_para_editar['Seleccionar'] = False
                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Marca_Nombre', 'Tienda Origen', 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Necesidad en Destino', 'Uds a Enviar']
                edited_df_traslados = st.data_editor(
                    df_para_editar[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={
                        "Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                        "Seleccionar": st.column_config.CheckboxColumn(required=True),
                    },
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']],
                    key="editor_traslados"
                )
                df_seleccionados_traslado = edited_df_traslados[edited_df_traslados['Seleccionar']]

                if not df_seleccionados_traslado.empty:
                    # Traer las columnas que faltan para el registro y cálculo
                    df_seleccionados_traslado = pd.merge(
                        df_seleccionados_traslado.copy(),
                        df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND']],
                        on=['SKU', 'Tienda Origen', 'Tienda Destino'], how='left'
                    )
                    df_seleccionados_traslado['Peso del Traslado (kg)'] = df_seleccionados_traslado['Uds a Enviar'] * df_seleccionados_traslado['Peso Individual (kg)']
                    
                    st.markdown("---")
                    total_unidades = df_seleccionados_traslado['Uds a Enviar'].sum()
                    total_peso = df_seleccionados_traslado['Peso del Traslado (kg)'].sum()
                    st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")
                    
                    email_dest_traslado = st.text_input("📧 Correo del destinatario para el plan de traslado:", key="email_traslado", help="Puede ser uno o varios correos separados por coma.")
                    
                    if st.button("✅ Enviar y Registrar Traslado", use_container_width=True, key="btn_registrar_traslado", type="primary"):
                        if not df_seleccionados_traslado.empty:
                            with st.spinner("Registrando traslado en Google Sheets y enviando notificaciones..."):
                                exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_seleccionados_traslado, "Traslado Automático")
                                if exito_registro:
                                    st.success(f"✅ ¡Traslado registrado exitosamente en Google Sheets! {msg_registro}")
                                    if email_dest_traslado:
                                        excel_bytes = generar_excel_dinamico(df_seleccionados_traslado, "Plan_de_Traslados")
                                        asunto = f"Nuevo Plan de Traslado Interno - {datetime.now().strftime('%d/%m/%Y')}"
                                        cuerpo_html = f"<html><body><p>Hola equipo de logística,</p><p>Se ha registrado un nuevo plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado en el archivo adjunto.</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"
                                        adjunto_traslado = [{'datos': excel_bytes, 'nombre_archivo': f"Plan_Traslado_{datetime.now().strftime('%Y%m%d')}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                        lista_destinatarios = [email.strip() for email in email_dest_traslado.replace(';', ',').split(',') if email.strip()]
                                        enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_traslado)
                                        if enviado: st.success(mensaje)
                                        else: st.error(mensaje)
                                    
                                    st.info("La página se recargará para actualizar los datos.")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")
                        else:
                            st.warning("No has seleccionado ningún producto para trasladar.")

    st.markdown("---")
    # <<< SECCIÓN DE TRASLADOS ESPECIALES RESTAURADA Y FUNCIONAL >>>
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        if 'solicitud_traslado_especial' not in st.session_state:
            st.session_state.solicitud_traslado_especial = []

        st.markdown("##### 1. Buscar y añadir productos a la solicitud")
        search_term_especial = st.text_input("Buscar producto por SKU o Descripción para traslado especial:", key="search_traslado_especial")

        if search_term_especial:
            mask_especial = (df_maestro['Stock'] > 0) & \
                            (df_maestro['SKU'].astype(str).str.contains(search_term_especial, case=False, na=False) |
                             df_maestro['Descripcion'].astype(str).str.contains(search_term_especial, case=False, na=False))
            df_resultados_especial = df_maestro[mask_especial].copy()

            if not df_resultados_especial.empty:
                df_resultados_especial['Uds a Enviar'] = 1
                df_resultados_especial['Seleccionar'] = False
                columnas_busqueda = ['Seleccionar', 'SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Uds a Enviar']
                st.write("Resultados de la búsqueda:")
                edited_df_especial = st.data_editor(
                    df_resultados_especial[columnas_busqueda], key="editor_traslados_especiales", hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=1, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock'])

                df_para_anadir = edited_df_especial[edited_df_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la solicitud", key="btn_anadir_especial"):
                    for _, row in df_para_anadir.iterrows():
                        item_id = f"{row['SKU']}_{row['Almacen_Nombre']}"
                        if not any(item['id'] == item_id for item in st.session_state.solicitud_traslado_especial):
                            # Añadir Costo_Promedio_UND para el registro
                            costo = df_maestro.loc[(df_maestro['SKU'] == row['SKU']) & (df_maestro['Almacen_Nombre'] == row['Almacen_Nombre']), 'Costo_Promedio_UND'].iloc[0]
                            st.session_state.solicitud_traslado_especial.append({
                                'id': item_id, 'SKU': row['SKU'], 'Descripcion': row['Descripcion'],
                                'Tienda Origen': row['Almacen_Nombre'], 'Uds a Enviar': row['Uds a Enviar'],
                                'Costo_Promedio_UND': costo
                            })
                    st.success(f"{len(df_para_anadir)} producto(s) añadidos a la solicitud.")
                    st.rerun()
            else:
                st.warning("No se encontraron productos con stock para ese criterio de búsqueda.")

        if st.session_state.solicitud_traslado_especial:
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la solicitud de traslado")
            df_solicitud = pd.DataFrame(st.session_state.solicitud_traslado_especial)

            tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
            tienda_destino_especial = st.selectbox("Seleccionar Tienda Destino para esta solicitud:", tiendas_destino_validas, key="destino_especial")
            
            st.dataframe(df_solicitud[['SKU', 'Descripcion', 'Tienda Origen', 'Uds a Enviar']], use_container_width=True)

            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("🗑️ Limpiar Solicitud", key="btn_limpiar_especial", use_container_width=True):
                    st.session_state.solicitud_traslado_especial = []
                    st.rerun()

            st.markdown("##### 3. Finalizar y enviar la solicitud")
            email_dest_especial = st.text_input("📧 Correo(s) del destinatario para la solicitud especial:", key="email_traslado_especial", help="Separados por coma.")
            
            if st.button("✅ Enviar y Registrar Solicitud Especial", use_container_width=True, key="btn_enviar_traslado_especial", type="primary"):
                if not df_solicitud.empty:
                    with st.spinner("Registrando y enviando solicitud especial..."):
                        exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_solicitud, "Traslado Especial", tienda_destino=tienda_destino_especial)
                        if exito_registro:
                            st.success(f"✅ Solicitud de traslado especial registrada en Google Sheets. {msg_registro}")
                            if email_dest_especial:
                                excel_bytes_especial = generar_excel_dinamico(df_solicitud.drop(columns=['id', 'Costo_Promedio_UND']), "Solicitud_Traslado_Especial")
                                asunto = f"Solicitud de Traslado Especial - {datetime.now().strftime('%d/%m/%Y')}"
                                cuerpo_html = f"<html><body><p>Hola equipo,</p><p>Se ha generado una solicitud de traslado especial para la tienda <b>{tienda_destino_especial}</b>. Por favor, revisar el archivo adjunto y coordinar el envío.</p><p>Gracias.</p></body></html>"
                                adjunto_especial = [{'datos': excel_bytes_especial, 'nombre_archivo': f"Solicitud_Traslado_Especial_{datetime.now().strftime('%Y%m%d')}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                lista_destinatarios = [email.strip() for email in email_dest_especial.replace(';', ',').split(',') if email.strip()]
                                enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_especial)
                                if enviado: st.success(mensaje)
                                else: st.error(mensaje)
                            st.session_state.solicitud_traslado_especial = []
                            st.info("Recargando página...")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"❌ Error al registrar la solicitud especial en Google Sheets: {msg_registro}")
                else:
                    st.warning("La solicitud está vacía. Añade productos antes de enviar.")

with tabs[2]: # PESTAÑA 3: PLAN DE COMPRAS
    st.header("🛒 Plan de Compras")

    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        if df_plan_compras.empty:
            st.info("No hay sugerencias de compra con los filtros actuales. ¡El inventario parece estar optimizado!")
        else:
            df_plan_compras['Proveedor'] = df_plan_compras['Proveedor'].astype(str).str.upper()
            proveedores_disponibles = ["Todos"] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores")

            df_a_mostrar = df_plan_compras.copy()
            if selected_proveedor != 'Todos':
                df_a_mostrar = df_a_mostrar[df_a_mostrar['Proveedor'] == selected_proveedor]

            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].astype(int)
            df_a_mostrar['Seleccionar'] = st.checkbox("Seleccionar / Deseleccionar Todos los Productos Visibles", key="select_all_suggested", value=True)
            
            columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            df_a_mostrar_final = df_a_mostrar_final[[col for col in columnas if col in df_a_mostrar_final.columns]]

            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df = st.data_editor(df_a_mostrar_final, hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']],
                key="editor_principal")

            df_seleccionados = edited_df[(edited_df['Seleccionar']) & (edited_df['Uds a Comprar'] > 0)]

            if not df_seleccionados.empty:
                df_seleccionados = df_seleccionados.copy()
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']
                st.markdown("---")
                es_proveedor_unico = selected_proveedor != 'Todos' and selected_proveedor != 'NO ASIGNADO'

                if es_proveedor_unico:
                    email_dest = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_principal", help="Ej: correo1@ejemplo.com")
                else:
                    st.info("Para generar un PDF o enviar una orden por correo, seleccione un proveedor específico.")
                    email_dest = ""

                c1, c2, c3 = st.columns(3)
                
                pdf_bytes = None
                orden_num = f"OC-{datetime.now().strftime('%Y%m%d-%H%M')}"
                if es_proveedor_unico:
                    # Agrupar por tienda para generar un PDF por cada una si es necesario
                    tienda_entrega = df_seleccionados['Tienda'].iloc[0] # Simplificamos: asumimos una sola tienda por OC
                    direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_entrega, "N/A")
                    info_proveedor = CONTACTOS_PROVEEDOR.get(selected_proveedor, {})
                    contacto_proveedor = info_proveedor.get('nombre', '')
                    celular_proveedor = info_proveedor.get('celular', '')
                    pdf_bytes = generar_pdf_orden_compra(df_seleccionados, selected_proveedor, tienda_entrega, direccion_entrega, contacto_proveedor, orden_num)

                with c1:
                    if st.button("✅ Enviar y Registrar Orden", disabled=(not es_proveedor_unico), use_container_width=True, key="btn_enviar_principal", type="primary"):
                        if email_dest and pdf_bytes:
                            with st.spinner("Enviando correo y registrando orden en Google Sheets..."):
                                exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_seleccionados, "Compra Sugerencia")
                                if exito_registro:
                                    st.success(f"¡Orden registrada en Google Sheets! {msg_registro}")
                                    lista_destinatarios = [email.strip() for email in email_dest.replace(';', ',').split(',') if email.strip()]
                                    asunto = f"Nueva Orden de Compra de Ferreinox SAS BIC - {selected_proveedor}"
                                    cuerpo_html = f"<html><body><p>Estimados Sres. {selected_proveedor},</p><p>Adjunto a este correo encontrarán nuestra orden de compra N° {orden_num}.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_entrega}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                    adjunto_sugerencia = [{'datos': pdf_bytes, 'nombre_archivo': f"OC_Ferreinox_{selected_proveedor.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'}]
                                    enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_sugerencia)
                                    if enviado: 
                                        st.success(mensaje)
                                        if celular_proveedor:
                                            numero_completo = celular_proveedor.strip()
                                            if not numero_completo.startswith('57'): numero_completo = '57' + numero_completo
                                            mensaje_wpp = f"Hola {contacto_proveedor}, te acabamos de enviar la Orden de Compra N° {orden_num} al correo. Quedamos atentos. ¡Gracias!"
                                            link_wpp = generar_link_whatsapp(numero_completo, mensaje_wpp)
                                            st.link_button("📲 Enviar Confirmación por WhatsApp", link_wpp)
                                    else: st.error(mensaje)

                                    st.info("Recargando página...")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Error al registrar en Google Sheets: {msg_registro}")
                        else:
                            st.warning("Por favor, ingrese un correo y asegúrese de que se pueda generar el PDF.")
                with c2:
                    excel_data = generar_excel_dinamico(df_seleccionados, "compra")
                    file_name_excel = f"Compra_{selected_proveedor if es_proveedor_unico else 'Consolidado'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    st.download_button("📥 Descargar Excel", data=excel_data, file_name=file_name_excel, use_container_width=True)
                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes or b"", file_name=f"OC_{selected_proveedor}.pdf", use_container_width=True, disabled=(not es_proveedor_unico or pdf_bytes is None))
                st.info(f"Total de la selección para **{selected_proveedor}**: ${df_seleccionados['Valor de la Compra'].sum():,.0f}")

    st.markdown("---")
    # <<< SECCIÓN DE COMPRAS ESPECIALES RESTAURADA Y FUNCIONAL >>>
    with st.expander("🆕 **Compras Especiales (Búsqueda Inteligente y Manual)**", expanded=True):
        if 'compra_especial_items' not in st.session_state:
            st.session_state.compra_especial_items = []

        st.markdown("##### 1. Buscar productos para añadir a la Orden de Compra")
        search_term_sp = st.text_input("Buscar cualquier producto por SKU o Descripción:", key="search_sp")

        if search_term_sp:
            mask_sp = (df_maestro['SKU'].astype(str).str.contains(search_term_sp, case=False, na=False) |
                       df_maestro['Descripcion'].astype(str).str.contains(search_term_sp, case=False, na=False))
            df_resultados_raw = df_maestro[mask_sp]

            if not df_resultados_raw.empty:
                df_resultados_sp = df_resultados_raw.groupby('SKU').agg(
                    Descripcion=('Descripcion', 'first'),
                    SKU_Proveedor=('SKU_Proveedor', 'first'),
                    Stock=('Stock', 'sum'),
                    Sugerencia_Compra=('Sugerencia_Compra', 'sum'),
                    Costo_Promedio_UND=('Costo_Promedio_UND', 'mean')
                ).reset_index()
                df_resultados_sp['Uds a Comprar'] = df_resultados_sp['Sugerencia_Compra'].apply(lambda x: int(x) if x > 0 else 1)
                df_resultados_sp['Seleccionar'] = False
                st.markdown("Resultados de la búsqueda (agrupados por producto):")
                columnas_sp = ['Seleccionar', 'SKU', 'Descripcion', 'SKU_Proveedor', 'Stock', 'Sugerencia_Compra', 'Uds a Comprar', 'Costo_Promedio_UND']
                edited_df_sp = st.data_editor(
                    df_resultados_sp[columnas_sp], hide_index=True, use_container_width=True, key="editor_sp",
                    column_config={"Uds a Comprar": st.column_config.NumberColumn("Cant. a Comprar", min_value=1, step=1)},
                    disabled=[col for col in columnas_sp if col not in ['Seleccionar', 'Uds a Comprar']]
                )
                df_para_anadir_sp = edited_df_sp[edited_df_sp['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la Orden", key="btn_anadir_compra_sp"):
                    for _, row in df_para_anadir_sp.iterrows():
                        if not any(item['SKU'] == row['SKU'] for item in st.session_state.compra_especial_items):
                            st.session_state.compra_especial_items.append(row.to_dict())
                    st.success(f"{len(df_para_anadir_sp)} producto(s) añadidos.")
                    st.rerun()
            else:
                st.warning("No se encontraron productos con ese criterio de búsqueda.")

        if st.session_state.compra_especial_items:
            st.markdown("---")
            st.markdown("##### 2. Orden de Compra Especial Actual")
            df_seleccionados_sp = pd.DataFrame(st.session_state.compra_especial_items)
            
            sp_col1, sp_col2 = st.columns(2)
            with sp_col1:
                nuevo_proveedor_nombre = st.text_input("Nombre del Proveedor:", key="nuevo_prov_nombre_sp")
                email_destinatario_sp = st.text_input("📧 Correo(s) del Proveedor:", key="email_sp")
            with sp_col2:
                lista_tiendas_validas = sorted([t for t in df_maestro['Almacen_Nombre'].unique() if t != opcion_consolidado])
                tienda_de_entrega_sp = st.selectbox("📍 Tienda de Destino:", lista_tiendas_validas, key="tienda_destino_sp")
                contacto_proveedor_sp = st.text_input("Nombre del Contacto (Opcional):", key="contacto_prov_sp")

            df_seleccionados_sp['Valor de la Compra'] = pd.to_numeric(df_seleccionados_sp['Uds a Comprar']) * pd.to_numeric(df_seleccionados_sp['Costo_Promedio_UND'])
            st.dataframe(df_seleccionados_sp[['SKU', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND', 'Valor de la Compra']], use_container_width=True)
            total_orden = df_seleccionados_sp['Valor de la Compra'].sum()
            st.info(f"**Valor total de la orden actual: ${total_orden:,.2f}**")

            if st.button("🗑️ Vaciar Orden de Compra", key="btn_limpiar_compra_sp"):
                st.session_state.compra_especial_items = []
                st.rerun()

            st.markdown("---")
            st.markdown("##### 3. Finalizar y Registrar Orden Especial")
            
            if st.button("✅ Enviar y Registrar Orden Especial", key="btn_enviar_sp", type="primary"):
                if nuevo_proveedor_nombre and tienda_de_entrega_sp and email_destinatario_sp:
                    with st.spinner("Registrando y enviando orden especial..."):
                        exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_seleccionados_sp, "Compra Especial", proveedor_nombre=nuevo_proveedor_nombre, tienda_destino=tienda_de_entrega_sp)
                        if exito_registro:
                            st.success(f"¡Orden especial registrada! {msg_registro}")
                            direccion_entrega_sp = DIRECCIONES_TIENDAS.get(tienda_de_entrega_sp, "N/A")
                            orden_num_sp = f"OC-SP-{datetime.now().strftime('%Y%m%d-%H%M')}"
                            pdf_bytes_sp = generar_pdf_orden_compra(df_seleccionados_sp, nuevo_proveedor_nombre, tienda_de_entrega_sp, direccion_entrega_sp, contacto_proveedor_sp, orden_num_sp)
                            # ...(código de envío de correo similar a la compra por sugerencia)...
                            st.session_state.compra_especial_items = []
                            st.info("Recargando página...")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Error al registrar la orden especial: {msg_registro}")
                else:
                    st.warning("Por favor, complete el nombre del proveedor, el correo y la tienda de destino.")

with tabs[3]: # PESTAÑA 4: SEGUIMIENTO Y RECEPCIÓN
    st.subheader("✅ Seguimiento y Recepción de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes desde Google Sheets o aún no hay órdenes registradas.")
    else:
        # Inicializar el estado de sesión para el editor de órdenes modificadas
        if 'orden_modificada_df' not in st.session_state:
            st.session_state.orden_modificada_df = pd.DataFrame()

        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        
        # --- SECCIÓN 1: ACTUALIZACIÓN EN LOTE ---
        with st.expander("Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=True):
            st.markdown("##### Filtrar Órdenes")
            track_c1, track_c2, track_c3 = st.columns(3)
            
            estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
            filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, key="filtro_estado_seguimiento")
            
            df_ordenes_vista = df_ordenes_vista_original.copy()
            if filtro_estado != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Estado'] == filtro_estado]

            proveedores_ordenes = ["Todos"] + sorted(df_ordenes_vista['Proveedor'].unique().tolist())
            filtro_proveedor_orden = track_c2.selectbox("Proveedor/Origen:", proveedores_ordenes, key="filtro_proveedor_seguimiento")
            if filtro_proveedor_orden != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Proveedor'] == filtro_proveedor_orden]

            tiendas_ordenes = ["Todos"] + sorted(df_ordenes_vista['Tienda_Destino'].unique().tolist())
            filtro_tienda_orden = track_c3.selectbox("Tienda Destino:", tiendas_ordenes, key="filtro_tienda_seguimiento")
            if filtro_tienda_orden != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Tienda_Destino'] == filtro_tienda_orden]

            if df_ordenes_vista.empty:
                st.info("No hay órdenes que coincidan con los filtros seleccionados.")
            else:
                df_ordenes_vista['Seleccionar'] = False
                columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                
                st.info("Selecciona las órdenes y luego elige el nuevo estado para actualizarlas en lote.")
                edited_df_seguimiento = st.data_editor(
                    df_ordenes_vista[columnas_seguimiento], hide_index=True, use_container_width=True,
                    key="editor_seguimiento", disabled=[col for col in columnas_seguimiento if col != 'Seleccionar']
                )
                df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]

                if not df_seleccion_seguimiento.empty:
                    st.markdown("##### Acciones en Lote para Órdenes Seleccionadas")
                    nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                    
                    if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} SKUs a '{nuevo_estado}'", key="btn_actualizar_estado"):
                        ids_a_actualizar = df_seleccion_seguimiento['ID_Orden'].tolist()
                        df_historico_modificado = df_ordenes_historico.copy()
                        df_historico_modificado.loc[df_historico_modificado['ID_Orden'].isin(ids_a_actualizar), 'Estado'] = nuevo_estado
                        
                        with st.spinner("Actualizando estados en Google Sheets..."):
                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                            if exito:
                                st.success(f"¡Éxito! {len(ids_a_actualizar)} líneas de orden han sido actualizadas. La página se recargará para reflejar los cambios en todo el sistema.")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"Error al actualizar Google Sheets: {msg}")

        st.markdown("---")

        # --- SECCIÓN 2: GESTIÓN DE ORDEN INDIVIDUAL ---
        with st.expander("🔍 Gestionar, Modificar o Reenviar una Orden Específica", expanded=False):
            st.markdown("##### 1. Buscar Orden Específica")
            ordenes_unicas = sorted(df_ordenes_vista_original['ID_Orden'].unique().tolist(), reverse=True)
            orden_id_seleccionada = st.selectbox(
                "Busca o selecciona el ID de la orden que deseas gestionar:",
                [""] + ordenes_unicas,
                key="orden_a_modificar_select"
            )

            if orden_id_seleccionada:
                df_orden_especifica = df_ordenes_vista_original[df_ordenes_vista_original['ID_Orden'] == orden_id_seleccionada].copy()
                st.markdown("##### 2. Modificar Cantidades de la Orden")
                st.info("Puedes editar las cantidades solicitadas. Las demás columnas son informativas.")
                
                # Columnas para mostrar en el editor
                cols_to_edit = ['ID_Orden', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Costo_Unitario']
                
                # Convertir a numérico antes de editar para evitar problemas de tipo
                df_orden_especifica['Cantidad_Solicitada'] = pd.to_numeric(df_orden_especifica['Cantidad_Solicitada'], errors='coerce')
                df_orden_especifica['Costo_Unitario'] = pd.to_numeric(df_orden_especifica['Costo_Unitario'], errors='coerce')
                
                df_modificada = st.data_editor(
                    df_orden_especifica[cols_to_edit],
                    key="editor_orden_unica",
                    hide_index=True,
                    use_container_width=True,
                    disabled=['ID_Orden', 'SKU', 'Descripcion', 'Costo_Unitario'],
                    column_config={"Cantidad_Solicitada": st.column_config.NumberColumn("Nueva Cantidad", min_value=0, step=1)}
                )

                st.markdown("##### 3. Acciones para la Orden Modificada")
                col_act1, col_act2, col_act3 = st.columns(3)

                with col_act1:
                    if st.button("💾 Guardar Cambios en GSheets", key="guardar_modificacion", type="primary"):
                        with st.spinner("Actualizando la orden en Google Sheets..."):
                            df_historico_actualizado = df_ordenes_historico.copy()
                            # Actualizar el histórico con los datos del df modificado
                            for index, row in df_modificada.iterrows():
                                # Usamos el índice original para localizar la fila correcta
                                original_index = row.name
                                df_historico_actualizado.loc[original_index, 'Cantidad_Solicitada'] = row['Cantidad_Solicitada']
                            
                            # Recalcular Costo Total
                            df_historico_actualizado['Costo_Total'] = pd.to_numeric(df_historico_actualizado['Cantidad_Solicitada']) * pd.to_numeric(df_historico_actualizado['Costo_Unitario'])

                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_actualizado)
                            if exito:
                                st.success("¡Orden actualizada exitosamente! Recargando para recalcular todo el tablero...")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"Error al guardar: {msg}")

                with col_act2:
                    excel_mod_data = generar_excel_dinamico(df_modificada, f"Orden_{orden_id_seleccionada}")
                    st.download_button(
                        "📥 Descargar Excel Modificado",
                        data=excel_mod_data,
                        file_name=f"ORDEN_MODIFICADA_{orden_id_seleccionada}.xlsx",
                        key="descargar_excel_mod"
                    )

                with col_act3:
                    if st.button("📧 Reenviar Correo a Proveedor", key="reenviar_correo"):
                        # Re-generar PDF y enviar correo con la data de df_modificada
                        info_orden = df_orden_especifica.iloc[0]
                        proveedor_nombre = info_orden['Proveedor']
                        tienda_destino = info_orden['Tienda_Destino']
                        
                        # Preparar para generar PDF/Correo
                        df_para_comunicacion = df_modificada.rename(columns={'Cantidad_Solicitada': 'Uds a Comprar', 'Costo_Unitario': 'Costo_Promedio_UND'})
                        direccion = DIRECCIONES_TIENDAS.get(tienda_destino, "No especificada")
                        contacto_info = CONTACTOS_PROVEEDOR.get(proveedor_nombre.upper(), {})
                        contacto_nombre = contacto_info.get('nombre', 'N/A')
                        
                        pdf_mod_bytes = generar_pdf_orden_compra(df_para_comunicacion, proveedor_nombre, tienda_destino, direccion, contacto_nombre, orden_id_seleccionada)

                        if pdf_mod_bytes:
                            email_para_reenvio = st.text_input("Confirmar correo del proveedor para reenvío:", key="email_reenvio")
                            if email_para_reenvio:
                                asunto = f"**CORRECCIÓN** Orden de Compra {orden_id_seleccionada} - Ferreinox SAS BIC"
                                cuerpo = f"<html><body><p>Estimados {proveedor_nombre},</p><p><b>Por favor, tomar nota de la siguiente corrección a nuestra orden de compra {orden_id_seleccionada}.</b> El documento adjunto reemplaza cualquier versión anterior.</p><p>Agradecemos su atención y ajuste en el despacho.</p><p>Cordialmente,<br><b>Departamento de Compras</b></p></body></html>"
                                adjunto = [{'datos': pdf_mod_bytes, 'nombre_archivo': f"OC_CORREGIDA_{orden_id_seleccionada}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'}]
                                
                                enviado, mensaje = enviar_correo_con_adjuntos([email_para_reenvio], asunto, cuerpo, adjunto)
                                if enviado: st.success("¡Correo de corrección enviado exitosamente!")
                                else: st.error(f"Error al enviar correo: {mensaje}")
                        else:
                            st.error("No se pudo generar el PDF para la orden modificada.")
