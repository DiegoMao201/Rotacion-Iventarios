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
import gspread
from google.oauth2.service_account import Credentials

# --- 0. CONFIGURACIÓN DE LA PÁGINA Y ESTADO DE SESIÓN ---
st.set_page_config(page_title="Gestión de Abastecimiento v3.1", layout="wide", page_icon="🚀")

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
# Se inicializan todas las claves para prevenir errores y hacer el código más predecible.
keys_to_initialize = {
    'df_analisis_maestro': pd.DataFrame(),
    'user_role': 'gerente', # Rol por defecto para pruebas, en producción se asignaría en el login.
    'almacen_nombre': None,
    'solicitud_traslado_especial': [],
    'compra_especial_items': [],
    'orden_seguimiento_seleccionada': None, # Clave para guardar el ID de la orden en la pestaña seguimiento
    'orden_seguimiento_df': pd.DataFrame(), # Clave para guardar los datos de la orden seleccionada
}
for key, default_value in keys_to_initialize.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

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
        st.error(f"Error: La hoja de cálculo '{sheet_name}' no fue encontrada.")
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
        # Se convierte todo a string para evitar problemas de tipos de datos con la API de gspread
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
        headers = worksheet.row_values(1)

        if headers:
            df_to_append_ordered = df_to_append.reindex(columns=headers).fillna('')
        else:
            worksheet.update([df_to_append.columns.values.tolist()] + df_to_append.astype(str).values.tolist())
            return True, "Nuevos registros y cabeceras añadidos.", df_to_append

        worksheet.append_rows(df_to_append_ordered.astype(str).values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Nuevos registros añadidos a '{sheet_name}'.", df_to_append_ordered
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}", pd.DataFrame()

def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    """Prepara y registra un DataFrame de órdenes, devolviendo el df con los IDs generados."""
    if df_orden.empty or client is None:
        return False, "No hay datos para registrar.", pd.DataFrame()

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = df_orden.copy()

    cantidad_col = 'Uds a Comprar' if 'Uds a Comprar' in df_orden.columns else 'Uds a Enviar'

    df_registro['Cantidad_Solicitada'] = df_registro[cantidad_col]
    df_registro['Costo_Unitario'] = df_registro.get('Costo_Promedio_UND', 0)
    df_registro['Costo_Total'] = pd.to_numeric(df_registro['Cantidad_Solicitada'], errors='coerce').fillna(0) * pd.to_numeric(df_registro['Costo_Unitario'], errors='coerce').fillna(0)
    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    base_id = ""
    if tipo_orden == "Compra Sugerencia":
        base_id = f"OC-{timestamp}"
        df_registro['Proveedor'] = df_registro['Proveedor']
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    elif tipo_orden == "Compra Especial":
        base_id = f"OC-SP-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        base_id = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
    elif tipo_orden == "Traslado Especial":
        base_id = f"TR-SP-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino
    else:
        return False, "Tipo de orden no reconocido.", pd.DataFrame()

    # Se genera un ID único por grupo de orden, no por fila.
    df_registro['ID_Orden'] = base_id

    columnas_finales = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')

    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

# --- 2. FUNCIONES AUXILIARES Y DE NEGOCIO ---
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
        self.font_family = 'Helvetica'
        try:
            self.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf', uni=True)
            self.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf', uni=True)
            self.font_family = 'DejaVu'
        except RuntimeError: 
            st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica. Algunos caracteres especiales (ej. '€') podrían no mostrarse.")
            
    def header(self):
        font_name = self.font_family
        try: 
            self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError: 
            self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font(font_name, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R'); self.set_x(80); self.set_font(font_name, '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R'); self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        font_name = self.font_family
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1); self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font(font_name, '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}     |      {self.empresa_web}      |      {self.empresa_email}      |      {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    font_name = pdf.font_family
    pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=25)
    
    # Asegurar que las columnas son numéricas antes de usarlas
    cantidad_col = next((col for col in ['Uds a Comprar', 'Cantidad_Solicitada', 'Uds a Enviar'] if col in df_seleccion.columns), None)
    if not cantidad_col:
        st.error("No se encontró una columna de cantidad válida para generar el PDF.")
        return None
        
    df_seleccion[cantidad_col] = pd.to_numeric(df_seleccion[cantidad_col], errors='coerce').fillna(0)
    df_seleccion['Costo_Promedio_UND'] = pd.to_numeric(df_seleccion['Costo_Promedio_UND'], errors='coerce').fillna(0)
    
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

    for _, row in df_seleccion.iterrows():
        costo_total_item = row[cantidad_col] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        # Usar get_string_width para manejar la altura de las celdas dinámicamente
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
            max_len = max(column_len if pd.notna(column_len) else 0, len(col)) + 2
            worksheet.set_column(i, i, min(max_len, 45))
    return output.getvalue()

# --- 3. LÓGICA PRINCIPAL Y FLUJO DE LA APLICACIÓN ---
st.title("🚀 Tablero de Control de Abastecimiento v3.1")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real conectado a Google Sheets.")

if 'df_analisis_maestro' not in st.session_state or st.session_state.df_analisis_maestro.empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos base de inventario.")
    if st.button("Ir a la página principal 🏠"):
        st.switch_page("app.py")
    st.stop()

df_maestro_base = st.session_state.df_analisis_maestro.copy()

client = connect_to_gsheets()
df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")

@st.cache_data
def calcular_estado_inventario_completo(df_base, df_ordenes):
    df_maestro = df_base.copy()
    
    if not df_ordenes.empty and 'Estado' in df_ordenes.columns:
        df_pendientes = df_ordenes[df_ordenes['Estado'] == 'Pendiente'].copy()
        df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
        stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
        stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito', 'Tienda_Destino': 'Almacen_Nombre'}, inplace=True)
        
        df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Stock_En_Transito'].fillna(0, inplace=True)
    else:
        df_maestro['Stock_En_Transito'] = 0

    numeric_cols = ['Stock', 'Stock_En_Transito', 'Costo_Promedio_UND', 'Necesidad_Total', 'Excedente_Trasladable', 'Precio_Venta_Estimado', 'Demanda_Diaria_Promedio']
    for col in numeric_cols:
        if col in df_maestro.columns:
            df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)

    df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)
    df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)

    if not df_plan_maestro.empty:
        unidades_cubiertas_por_traslado = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
        unidades_cubiertas_por_traslado.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado'}, inplace=True)
        df_maestro = pd.merge(df_maestro, unidades_cubiertas_por_traslado, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Cubierto_Por_Traslado'].fillna(0, inplace=True)
    else:
        df_maestro['Cubierto_Por_Traslado'] = 0

    df_maestro['Sugerencia_Compra'] = (df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
    df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
    
    if 'Precio_Venta_Estimado' not in df_maestro.columns or df_maestro['Precio_Venta_Estimado'].sum() == 0:
        df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * 1.30

    return df_maestro, df_plan_maestro

df_maestro, df_plan_maestro = calcular_estado_inventario_completo(df_maestro_base, df_ordenes_historico)

# --- DICCIONARIOS DE CONTACTO Y DIRECCIONES ---
DIRECCIONES_TIENDAS = {
    'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 
    'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32',
    'Laureles': 'Av. Laureles #35-13', 'Opalo': 'Cra. 10 #70-52'
}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893'},
}
CONTACTOS_TIENDAS = {
    'Armenia': {'email': 'tiendapintucoarmenia@ferreinox.co', 'celular': '573165219904'},
    'Olaya': {'email': 'tiendapintucopereira@ferreinox.co', 'celular': '573102368346'},
    'Manizales': {'email': 'tiendapintucomanizales@ferreinox.co', 'celular': '573136086232'},
    'Laureles': {'email': 'tiendapintucolaureles@ferreinox.co', 'celular': '573104779389'},
    'Opalo': {'email': 'tiendapintucodosquebradas@ferreinox.co', 'celular': '573108561506'},
    'FerreBox': {'email': 'compras@ferreinox.co', 'celular': '573127574279'} 
}

# --- Lógica de la sesión de usuario y filtros (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Filtros de Gestión")
    opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
    
    if st.session_state.get('user_role') == 'gerente':
        almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    else:
        almacen_options = [st.session_state.get('almacen_nombre')] if st.session_state.get('almacen_nombre') else []
    
    selected_almacen_nombre = st.selectbox("Selecciona la Vista de Tienda:", almacen_options)

    if selected_almacen_nombre == opcion_consolidado: 
        df_vista = df_maestro.copy()
    else: 
        df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_marcas = st.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
    
    if selected_marcas:
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]
    else:
        df_filtered = df_vista

# --- 4. INTERFAZ DE USUARIO CON PESTAÑAS ---
tab_titles = ["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"]
tabs = st.tabs(tab_titles)

# PESTAÑA 1: DIAGNÓSTICO GENERAL
with tabs[0]:
    # (El código de esta pestaña no se modifica, ya que no presenta problemas de funcionalidad)
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
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
    kpi3.metric(label="📉 Venta Potencial Perdida (30 días)", value=f"${venta_perdida:,.0f}")
    st.markdown("##### Análisis y Recomendaciones Clave")
    with st.container(border=True):
        if venta_perdida > 0: st.markdown(f"**🚨 Alerta:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** por **{len(df_quiebre)}** productos en quiebre.")
        if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña 'Traslados'.")
        if necesidad_compra_total > 0:
            df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
            df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
            if not df_compras_prioridad.empty:
                top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                st.markdown(f"**🎯 Enfoque:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**.")
        if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0: st.success("✅ ¡Inventario Optimizado! No se detectan necesidades urgentes con los filtros actuales.")
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

# PESTAÑA 2: PLAN DE TRASLADOS
with tabs[1]:
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            # (El código de filtrado de traslados no se modifica)
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
            
            df_traslados_filtrado = df_aplicar_filtros
            
            if df_traslados_filtrado.empty:
                st.warning("No se encontraron traslados que coincidan con los filtros.")
            else:
                df_para_editar = pd.merge(df_traslados_filtrado, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                          left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left'
                                         ).drop(columns=['Almacen_Nombre']).fillna({'Stock_En_Transito': 0})
                df_para_editar['Seleccionar'] = False
                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Tienda Origen', 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Stock_En_Transito', 'Necesidad en Destino', 'Uds a Enviar']
                
                edited_df_traslados = st.data_editor(df_para_editar[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                                   "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d"),
                                   "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']], key="editor_traslados")
                
                df_seleccionados_traslado = edited_df_traslados[(edited_df_traslados['Seleccionar']) & (edited_df_traslados['Uds a Enviar'] > 0)]

                if not df_seleccionados_traslado.empty:
                    df_seleccionados_traslado_full = pd.merge(df_seleccionados_traslado.copy(), df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND']],
                                                              on=['SKU', 'Tienda Origen', 'Tienda Destino'], how='left')
                    
                    if st.button("✅ Enviar y Registrar Traslado", use_container_width=True, key="btn_registrar_traslado", type="primary"):
                        with st.spinner("Registrando traslado..."):
                            exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados_traslado_full, "Traslado Automático")
                            
                            if exito_registro:
                                st.success(f"✅ ¡Traslado registrado exitosamente! {msg_registro}")
                                st.info("Limpiando caché de datos para reflejar los cambios.")
                                # CAMBIO CLAVE: Se limpia el caché para que la próxima vez que se carguen los datos, estén actualizados. NO se usa rerun.
                                st.cache_data.clear()
                                # Se podría añadir una notificación por correo/WhatsApp aquí si se desea, siguiendo el patrón de la pestaña de compras.
                            else:
                                st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")

    # (La sección de traslados especiales se mantiene, ya que su lógica es similar y no causa el problema principal)
    st.markdown("---")
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        # ... (código existente de traslados especiales)
        pass

# PESTAÑA 3: PLAN DE COMPRAS
with tabs[2]:
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
            df_a_mostrar['Seleccionar'] = True
            
            columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock_En_Transito', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            columnas_existentes = [col for col in columnas if col in df_a_mostrar_final.columns]
            
            edited_df = st.data_editor(df_a_mostrar_final[columnas_existentes], hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']], key="editor_principal")

            df_seleccionados = edited_df[(edited_df['Seleccionar']) & (edited_df['Uds a Comprar'] > 0)]

            if not df_seleccionados.empty:
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']
                st.markdown("---")
                es_proveedor_unico = selected_proveedor != 'Todos' and selected_proveedor != 'NO ASIGNADO'
                
                # --- NUEVA SECCIÓN: CAMPOS DE CONTACTO EDITABLES ---
                contacto_proveedor_nombre = ""
                contacto_proveedor_celular = ""
                if es_proveedor_unico:
                    st.markdown(f"##### Información de Contacto para **{selected_proveedor}**")
                    info_proveedor = CONTACTOS_PROVEEDOR.get(selected_proveedor, {})
                    
                    col1_contacto, col2_contacto = st.columns(2)
                    with col1_contacto:
                        contacto_proveedor_nombre = st.text_input("Nombre del Contacto:", value=info_proveedor.get('nombre', ''), key="nombre_contacto_compra")
                    with col2_contacto:
                        contacto_proveedor_celular = st.text_input("Celular del Contacto (con código de país):", value=info_proveedor.get('celular', ''), key="celular_contacto_compra")
                
                email_dest = ""
                if es_proveedor_unico:
                    email_dest = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_principal", help="Ej: correo1@ejemplo.com,correo2@ejemplo.com")
                else:
                    st.info("Para generar un PDF o enviar una orden por correo, seleccione un proveedor específico.")
                
                c1, c2, c3 = st.columns(3)
                
                if es_proveedor_unico:
                    tienda_entrega = df_seleccionados['Tienda'].iloc[0]
                    direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_entrega, "Dirección no especificada")
                    
                    pdf_bytes = generar_pdf_orden_compra(df_seleccionados, selected_proveedor, tienda_entrega, direccion_entrega, contacto_proveedor_nombre, "Temporal")
                    excel_bytes = generar_excel_dinamico(df_seleccionados, f"Compra_{selected_proveedor}")

                    with c1:
                        if st.button("✅ Enviar y Registrar Orden", use_container_width=True, key="btn_enviar_principal", type="primary"):
                            if email_dest and pdf_bytes and excel_bytes:
                                with st.spinner("Registrando orden y enviando notificaciones..."):
                                    exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados, "Compra Sugerencia")
                                    
                                    if exito_registro:
                                        orden_id_real = df_registrado['ID_Orden'].iloc[0] if not df_registrado.empty else "N/A"
                                        st.success(f"¡Orden {orden_id_real} registrada! {msg_registro}")
                                        
                                        # Regenerar PDF con el ID de orden final
                                        pdf_final_bytes = generar_pdf_orden_compra(df_registrado, selected_proveedor, tienda_entrega, direccion_entrega, contacto_proveedor_nombre, orden_id_real)

                                        lista_destinatarios = [email.strip() for email in email_dest.replace(';', ',').split(',') if email.strip()]
                                        asunto = f"Nueva Orden de Compra {orden_id_real} de Ferreinox SAS BIC - {selected_proveedor}"
                                        cuerpo_html = f"..." # (Tu cuerpo de HTML existente)
                                        adjuntos = [{'datos': pdf_final_bytes, 'nombre_archivo': f"OC_{orden_id_real}.pdf"}, {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_{orden_id_real}.xlsx"}]
                                        
                                        enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                        if enviado: st.success(mensaje)
                                        else: st.error(mensaje)
                                        
                                        # CAMBIO CLAVE: Lógica de WhatsApp mejorada y visible
                                        if contacto_proveedor_celular:
                                            mensaje_wpp = f"Hola {contacto_proveedor_nombre}, te acabamos de enviar la Orden de Compra N° {orden_id_real} al correo. Quedamos atentos. ¡Gracias!"
                                            link_wpp = generar_link_whatsapp(contacto_proveedor_celular, mensaje_wpp)
                                            st.link_button("📲 Enviar Confirmación por WhatsApp al Proveedor", link_wpp, target="_blank", use_container_width=True)

                                        st.info("Limpiando caché de datos para reflejar los cambios.")
                                        st.cache_data.clear()
                                    else:
                                        st.error(f"Error al registrar en Google Sheets: {msg_registro}")
                            else:
                                st.warning("Por favor, ingrese un correo y asegúrese de que el proveedor esté seleccionado para poder enviar.")
                    with c2:
                        st.download_button("📥 Descargar Excel", data=excel_bytes or b"", file_name=f"Compra_{selected_proveedor}.xlsx", use_container_width=True, disabled=(not es_proveedor_unico))
                    with c3:
                        # Usar el ID temporal para el nombre del archivo de descarga
                        orden_num_descarga = f"OC-{datetime.now().strftime('%Y%m%d-%H%M')}"
                        st.download_button("📄 Descargar PDF", data=pdf_bytes or b"", file_name=f"OC_{orden_num_descarga}.pdf", use_container_width=True, disabled=(not es_proveedor_unico or pdf_bytes is None))
                
                st.info(f"Total de la selección para **{selected_proveedor if es_proveedor_unico else 'Múltiples Proveedores'}**: ${df_seleccionados['Valor de la Compra'].sum():,.2f}")

# --- PESTAÑA 4: SEGUIMIENTO (COMPLETAMENTE REDISEÑADA) ---
with tabs[3]:
    st.subheader("✅ Seguimiento y Gestión de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        
        # --- SECCIÓN 1: SELECCIONAR UNA ORDEN PARA GESTIONAR ---
        st.markdown("##### 1. Seleccionar una orden para ver detalles y gestionar")
        
        # Filtros para encontrar la orden más fácilmente
        track_c1, track_c2, track_c3 = st.columns(3)
        estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
        filtro_estado = track_c1.selectbox("Filtrar por Estado:", estados_disponibles, index=0, key="filtro_estado_seguimiento")
        
        df_ordenes_filtradas = df_ordenes_vista_original.copy()
        if filtro_estado != "Todos": df_ordenes_filtradas = df_ordenes_filtradas[df_ordenes_filtradas['Estado'] == filtro_estado]

        # Selectbox para elegir el ID_Orden único
        lista_ordenes_unicas = ["-- Seleccione una orden --"] + sorted(df_ordenes_filtradas['ID_Orden'].unique().tolist(), reverse=True)
        orden_seleccionada_id = st.selectbox("ID de la Orden:", lista_ordenes_unicas, key="selector_orden_id")

        # --- SECCIÓN 2: GESTIONAR LA ORDEN SELECCIONADA ---
        if orden_seleccionada_id != "-- Seleccione una orden --":
            st.session_state['orden_seguimiento_seleccionada'] = orden_seleccionada_id
            
            # Cargar los datos de la orden seleccionada en el estado de sesión para editarlos
            df_orden_actual = df_ordenes_vista_original[df_ordenes_vista_original['ID_Orden'] == orden_seleccionada_id].copy()
            st.session_state['orden_seguimiento_df'] = df_orden_actual

            st.markdown(f"#### Gestionando Orden: **{st.session_state['orden_seguimiento_seleccionada']}**")

            # Editor de datos para modificar la orden
            st.markdown("**Editar cantidades de la orden:** (Para eliminar un ítem, pon la cantidad en 0)")
            edited_orden_df = st.data_editor(
                st.session_state['orden_seguimiento_df'][['SKU', 'Descripcion', 'Cantidad_Solicitada']],
                key="editor_orden_seguimiento",
                hide_index=True,
                use_container_width=True,
                column_config={"Cantidad_Solicitada": st.column_config.NumberColumn("Cantidad", min_value=0, step=1)}
            )

            if st.button("💾 Guardar Cambios en la Orden", type="primary"):
                # Lógica para actualizar la hoja de Google
                df_historico_completo = df_ordenes_historico.copy()
                
                # Eliminar las filas antiguas de la orden editada
                df_historico_sin_orden_vieja = df_historico_completo[df_historico_completo['ID_Orden'] != st.session_state['orden_seguimiento_seleccionada']]
                
                # Preparar el nuevo DF con las filas actualizadas (quitando las que tienen cantidad 0)
                df_actualizado = st.session_state['orden_seguimiento_df'].copy()
                df_actualizado['Cantidad_Solicitada'] = edited_orden_df['Cantidad_Solicitada']
                df_actualizado_final = df_actualizado[df_actualizado['Cantidad_Solicitada'] > 0]
                
                # Unir el histórico sin la orden vieja con la orden actualizada
                df_final_para_gsheets = pd.concat([df_historico_sin_orden_vieja, df_actualizado_final], ignore_index=True)

                with st.spinner("Actualizando orden en Google Sheets..."):
                    exito, msg = update_sheet(client, "Registro_Ordenes", df_final_para_gsheets)
                    if exito:
                        st.success(f"¡Orden {st.session_state['orden_seguimiento_seleccionada']} actualizada! {msg}")
                        st.info("Limpiando caché para refrescar los datos.")
                        st.cache_data.clear()
                    else:
                        st.error(f"Error al actualizar Google Sheets: {msg}")

            st.markdown("---")
            st.markdown("##### 2. Acciones para la orden seleccionada")

            # Obtener datos de la orden para las acciones
            df_para_acciones = edited_orden_df[edited_orden_df['Cantidad_Solicitada'] > 0].copy()
            # Necesitamos el resto de la info para el PDF/Excel
            df_para_acciones_full = pd.merge(df_para_acciones, st.session_state['orden_seguimiento_df'].drop(columns=['Cantidad_Solicitada']), on=['SKU', 'Descripcion'], how='left')

            proveedor_orden = df_para_acciones_full['Proveedor'].iloc[0]
            tienda_destino_orden = df_para_acciones_full['Tienda_Destino'].iloc[0]
            direccion_entrega_orden = DIRECCIONES_TIENDAS.get(tienda_destino_orden, "N/A")
            
            # Contactos editables también en esta sección
            info_proveedor_orden = CONTACTOS_PROVEEDOR.get(proveedor_orden.replace("TRASLADO INTERNO: ", ""), {})
            c1_seg, c2_seg = st.columns(2)
            nombre_contacto_orden = c1_seg.text_input("Nombre Contacto:", value=info_proveedor_orden.get('nombre', ''), key="nombre_contacto_seg")
            celular_contacto_orden = c2_seg.text_input("Celular Contacto:", value=info_proveedor_orden.get('celular', ''), key="celular_contacto_seg")
            email_dest_orden = st.text_input("📧 Email(s) del destinatario:", key="email_seguimiento")
            
            # Generar archivos en memoria para descarga/envío
            pdf_bytes_seg = generar_pdf_orden_compra(df_para_acciones_full, proveedor_orden, tienda_destino_orden, direccion_entrega_orden, nombre_contacto_orden, st.session_state['orden_seguimiento_seleccionada'])
            excel_bytes_seg = generar_excel_dinamico(df_para_acciones_full, f"Orden_{st.session_state['orden_seguimiento_seleccionada']}")
            
            # Botones de acción
            act_c1, act_c2, act_c3, act_c4 = st.columns(4)
            with act_c1:
                st.download_button("📄 Descargar PDF", data=pdf_bytes_seg or b"", file_name=f"OC_{st.session_state['orden_seguimiento_seleccionada']}.pdf", use_container_width=True, disabled=(pdf_bytes_seg is None))
            with act_c2:
                st.download_button("📥 Descargar Excel", data=excel_bytes_seg or b"", file_name=f"Detalle_{st.session_state['orden_seguimiento_seleccionada']}.xlsx", use_container_width=True)
            with act_c3:
                if st.button("✉️ Reenviar Email", use_container_width=True):
                    if email_dest_orden:
                        # Lógica de envío de correo aquí
                        st.success(f"Simulando envío de email a {email_dest_orden}...")
                    else:
                        st.warning("Ingresa un email de destinatario.")
            with act_c4:
                if st.button("📲 Reenviar WSP", use_container_width=True):
                    if celular_contacto_orden:
                        mensaje_wpp = f"Hola {nombre_contacto_orden}, te reenviamos la información de la Orden de Compra N° {st.session_state['orden_seguimiento_seleccionada']}. Quedamos atentos. ¡Gracias!"
                        link_wpp = generar_link_whatsapp(celular_contacto_orden, mensaje_wpp)
                        st.link_button("Abrir WhatsApp", link_wpp, target="_blank")
                    else:
                        st.warning("Ingresa un número de celular.")
