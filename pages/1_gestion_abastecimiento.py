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
st.set_page_config(page_title="Gestión de Abastecimiento v3.2", layout="wide", page_icon="🚀")

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
# Es una buena práctica inicializar todas las claves que usarás en la sesión.
# Esto previene errores y hace el código más predecible.
def initialize_session_state():
    keys_to_initialize = {
        'df_analisis_maestro': pd.DataFrame(),
        'user_role': None,
        'almacen_nombre': None,
        'solicitud_traslado_especial': [],
        'compra_especial_items': [],
        'orden_a_modificar_id': None, # ID de la orden seleccionada para modificar
    }
    for key, default_value in keys_to_initialize.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

initialize_session_state()

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
        # Forzar columnas clave a string para evitar problemas de tipo
        for col in ['SKU', 'ID_Orden', 'Proveedor', 'Tienda_Destino', 'SKU_Proveedor']:
            if col in df.columns:
                df[col] = df[col].astype(str)
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
        # Asegurar que todas las columnas son string antes de enviar a GSheets
        df_str = df_to_write.astype(str)
        # Reemplazar 'nan' y '<NA>' por strings vacíos para una vista limpia
        df_str.replace({'nan': '', '<NA>': ''}, inplace=True)
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Añade filas a una hoja sin sobreescribir y devuelve el DataFrame añadido con IDs."""
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
    if not proveedor_nombre:
         proveedor_nombre = df_orden.get('Proveedor', 'VARIOS/CONSOLIDADO').iloc[0]

    if tipo_orden == "Compra Sugerencia":
        base_id = f"OC-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    elif tipo_orden == "Compra Especial":
        base_id = f"OC-SP-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        base_id = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
    else:
        return False, "Tipo de orden no reconocido.", pd.DataFrame()

    df_registro['ID_Orden'] = [f"{base_id}-{i}" for i in range(len(df_registro))]

    columnas_finales = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')

    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

# --- 2. FUNCIONES AUXILIARES (Email, PDF, etc.) ---
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
            st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica.")
            
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
    cantidad_col = 'Uds a Comprar' if 'Uds a Comprar' in df_seleccion.columns else 'Cantidad_Solicitada'
    costo_col = 'Costo_Promedio_UND' if 'Costo_Promedio_UND' in df_seleccion.columns else 'Costo_Unitario'

    df_seleccion[cantidad_col] = pd.to_numeric(df_seleccion[cantidad_col], errors='coerce').fillna(0)
    df_seleccion[costo_col] = pd.to_numeric(df_seleccion[costo_col], errors='coerce').fillna(0)
    
    for _, row in df_seleccion.iterrows():
        costo_total_item = row[cantidad_col] * row[costo_col]
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
        y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
        pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
        y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
        pdf.multi_cell(70, 5, str(row['Descripcion']), 1, 'L')
        y3 = pdf.get_y()
        row_height = max(y1, y2, y3) - y_start if max(y1, y2, y3) > y_start else 5
        pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(row[cantidad_col])), 1, 'C')
        pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${row[costo_col]:,.2f}", 1, 'R')
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
        else:
            df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
            workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
            header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
            for col_num, value in enumerate(df.columns.values): worksheet.write(0, col_num, value, header_format)
            for i, col in enumerate(df.columns):
                column_len = df[col].astype(str).map(len).max()
                max_len = max(column_len if pd.notna(column_len) else 0, len(col)) + 2
                worksheet.set_column(i, i, min(max_len, 45))
    return output.getvalue()

def enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo_html, lista_de_adjuntos):
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
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    # ... (código idéntico de la función) ...
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


# --- 3. LÓGICA PRINCIPAL Y CARGA DE DATOS ---
st.title("🚀 Tablero de Control de Abastecimiento v3.2")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real conectado a Google Sheets.")

if st.session_state.df_analisis_maestro.empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos base de inventario.")
    if st.button("Ir a la página principal 🏠"):
        st.switch_page("app.py")
    st.stop()

# Carga y procesamiento de datos
client = connect_to_gsheets()
df_maestro_base = st.session_state.df_analisis_maestro.copy()
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
    df_plan_maestro_calculado = generar_plan_traslados_inteligente(df_maestro)

    if not df_plan_maestro_calculado.empty:
        unidades_cubiertas_por_traslado = df_plan_maestro_calculado.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
        unidades_cubiertas_por_traslado.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado'}, inplace=True)
        df_maestro = pd.merge(df_maestro, unidades_cubiertas_por_traslado, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Cubierto_Por_Traslado'].fillna(0, inplace=True)
    else:
        df_maestro['Cubierto_Por_Traslado'] = 0

    df_maestro['Sugerencia_Compra'] = (df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
    df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
    
    if 'Precio_Venta_Estimado' not in df_maestro.columns or df_maestro['Precio_Venta_Estimado'].sum() == 0:
        df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * 1.30

    return df_maestro, df_plan_maestro_calculado

df_maestro, df_plan_maestro = calcular_estado_inventario_completo(df_maestro_base, df_ordenes_historico)

# --- DICCIONARIOS DE CONTACTO ---
DIRECCIONES_TIENDAS = {
    'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 
    'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32',
    'Laureles': 'Av. Laureles #35-13', 'Opalo': 'Cra. 10 #70-52'
}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448', 'email': 'email@proveedor.com'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917', 'email': 'email@proveedor.com'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589', 'email': 'email@proveedor.com'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893', 'email': 'email@proveedor.com'},
    'VARIOS/CONSOLIDADO': {'nombre': 'N/A', 'celular': '', 'email': ''}
}
CONTACTOS_TIENDAS = {
    'Armenia': {'email': 'tiendapintucoarmenia@ferreinox.co', 'celular': '573165219904'},
    'Olaya': {'email': 'tiendapintucopereira@ferreinox.co', 'celular': '573102368346'},
    'Manizales': {'email': 'tiendapintucomanizales@ferreinox.co', 'celular': '573136086232'},
    'Laureles': {'email': 'tiendapintucolaureles@ferreinox.co', 'celular': '573104779389'},
    'Opalo': {'email': 'tiendapintucodosquebradas@ferreinox.co', 'celular': '573108561506'},
    'FerreBox': {'email': 'compras@ferreinox.co', 'celular': '573127574279'} 
}

# --- FILTROS EN SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Filtros de Gestión")
    opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
    
    if st.session_state.get('user_role') == 'gerente':
        almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    else:
        almacen_options = [st.session_state.get('almacen_nombre')] if st.session_state.get('almacen_nombre') else []
    
    selected_almacen_nombre = st.selectbox("Selecciona la Vista de Tienda:", almacen_options)

    if selected_almacen_nombre == opcion_consolidado: df_vista = df_maestro.copy()
    else: df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_marcas = st.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
    
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else df_vista

# --- 4. INTERFAZ DE USUARIO CON PESTAÑAS ---
tab_titles = ["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"]
tabs = st.tabs(tab_titles)

with tabs[0]: # PESTAÑA 1: DIAGNÓSTICO
    # ... (código sin cambios)
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

with tabs[1]: # PESTAÑA 2: TRASLADOS
    # ... (código sin cambios)
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        st.write("Lógica de traslados automáticos aquí...")

with tabs[2]: # PESTAÑA 3: COMPRAS
    st.header("🛒 Plan de Compras")
    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        if df_plan_compras.empty:
            st.info("No hay sugerencias de compra con los filtros actuales.")
        else:
            df_plan_compras['Proveedor'] = df_plan_compras['Proveedor'].astype(str).str.upper()
            proveedores_disponibles = ["Todos"] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores_compras")

            df_a_mostrar = df_plan_compras.copy()
            if selected_proveedor != 'Todos':
                df_a_mostrar = df_a_mostrar[df_a_mostrar['Proveedor'] == selected_proveedor]
            
            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].astype(int)
            df_a_mostrar['Seleccionar'] = True
            
            edited_df_compras = st.data_editor(df_a_mostrar, key="editor_compras", disabled=['Proveedor', 'SKU', 'Descripcion'])
            df_seleccionados = edited_df_compras[(edited_df_compras['Seleccionar']) & (edited_df_compras['Uds a Comprar'] > 0)]

            if not df_seleccionados.empty:
                st.markdown("---")
                proveedor_final = selected_proveedor if selected_proveedor != 'Todos' else 'VARIOS/CONSOLIDADO'
                
                st.markdown("##### Opciones de Envío y Notificación")
                email_dest_compra = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_compra_input", value=CONTACTOS_PROVEEDOR.get(proveedor_final, {}).get('email', ''))
                celular_dest_compra = st.text_input("📱 Celular para WhatsApp (ej: 573...):", key="celular_compra_input", value=CONTACTOS_PROVEEDOR.get(proveedor_final, {}).get('celular', ''))

                c1, c2, c3 = st.columns(3)
                
                tienda_entrega = df_seleccionados['Almacen_Nombre'].iloc[0]
                direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_entrega, "N/A")
                contacto_proveedor = CONTACTOS_PROVEEDOR.get(proveedor_final, {}).get('nombre', 'N/A')
                orden_num_display = f"OC-{datetime.now().strftime('%Y%m%d-%H%M')}"
                
                pdf_bytes = generar_pdf_orden_compra(df_seleccionados, proveedor_final, tienda_entrega, direccion_entrega, contacto_proveedor, orden_num_display)
                excel_bytes = generar_excel_dinamico(df_seleccionados, f"Compra_{proveedor_final}")

                with c1:
                    if st.button("✅ Enviar y Registrar Orden", use_container_width=True, type="primary", key="btn_registrar_compra"):
                        if email_dest_compra:
                            with st.spinner("Registrando y enviando..."):
                                exito, msg, df_reg = registrar_ordenes_en_sheets(client, df_seleccionados, "Compra Sugerencia", proveedor_nombre=proveedor_final)
                                if exito:
                                    st.success(f"¡Orden registrada! {msg}")
                                    orden_id_real = df_reg['ID_Orden'].iloc[0]
                                    asunto = f"Nueva Orden de Compra {orden_id_real} de Ferreinox"
                                    cuerpo = f"<html><body>Estimados {proveedor_final},<br>Adjunto encontrarán nuestra orden de compra <b>{orden_id_real}</b> en formatos PDF y Excel.</body></html>"
                                    adjuntos = [
                                        {'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_real}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                        {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_{orden_id_real}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
                                    ]
                                    enviado, msg_envio = enviar_correo_con_adjuntos(email_dest_compra.split(','), asunto, cuerpo, adjuntos)
                                    if enviado: st.toast(msg_envio, icon="📧")
                                    else: st.error(msg_envio)
                                    
                                    if celular_dest_compra:
                                        mensaje_wpp = f"Hola {contacto_proveedor}, te enviamos la OC {orden_id_real} al correo. ¡Gracias!"
                                        st.link_button("📲 Notificar por WhatsApp", generar_link_whatsapp(celular_dest_compra, mensaje_wpp), target="_blank")
                                    
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Error al registrar: {msg}")
                        else:
                            st.warning("Por favor, ingrese al menos un correo de destinatario.")
                with c2:
                    st.download_button("📥 Descargar Excel", data=excel_bytes, file_name=f"Compra_{proveedor_final}.xlsx", use_container_width=True)
                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes, file_name=f"OC_{orden_num_display}.pdf", use_container_width=True)

with tabs[3]: # PESTAÑA 4: SEGUIMIENTO
    st.subheader("✅ Seguimiento y Recepción de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes o no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy()
        
        with st.expander("🔄 Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=True):
            # Lógica de filtros...
            df_ordenes_vista = df_ordenes_vista_original.copy() # Aplicar filtros aquí...
            df_ordenes_vista['Seleccionar'] = False
            edited_df_lote = st.data_editor(df_ordenes_vista, key="editor_seguimiento_lote", disabled=True)
            
            def callback_actualizar_lote():
                df_seleccion_lote = edited_df_lote[edited_df_lote['Seleccionar']]
                if not df_seleccion_lote.empty:
                    nuevo_estado_lote = st.session_state.nuevo_estado_lote
                    ids_a_actualizar = df_seleccion_lote['ID_Orden'].tolist()
                    df_historico_modificado = df_ordenes_historico.copy()
                    df_historico_modificado.loc[df_historico_modificado['ID_Orden'].isin(ids_a_actualizar), 'Estado'] = nuevo_estado_lote
                    exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                    if exito:
                        st.toast(f"¡Éxito! Se actualizaron {len(ids_a_actualizar)} órdenes.", icon="✅")
                        st.cache_data.clear()
                    else: st.error(f"Error: {msg}")

            col_lote1, col_lote2 = st.columns([2,1])
            with col_lote1:
                nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
            with col_lote2:
                st.button(f"➡️ Aplicar a seleccionados", on_click=callback_actualizar_lote, use_container_width=True)

        with st.expander("🔍 Gestionar, Modificar o Reenviar una Orden Específica", expanded=True):
            st.markdown("##### 1. Buscar Orden Específica")
            ordenes_unicas = sorted(df_ordenes_vista_original['ID_Orden'].unique().tolist(), reverse=True)
            
            st.selectbox("Busca o selecciona el ID de la orden:", [""] + ordenes_unicas, key="orden_a_modificar_id_select")

            if st.session_state.orden_a_modificar_id_select:
                df_orden_especifica = df_ordenes_vista_original[df_ordenes_vista_original['ID_Orden'] == st.session_state.orden_a_modificar_id_select].copy()
                
                st.markdown("##### 2. Modificar Ítems de la Orden")
                
                df_editada_individual = st.data_editor(
                    df_orden_especifica,
                    key=f"editor_individual_{st.session_state.orden_a_modificar_id_select}",
                    num_rows="dynamic",
                    column_config={"Cantidad_Solicitada": st.column_config.NumberColumn("Nueva Cant.", min_value=0), "Costo_Unitario": st.column_config.NumberColumn("Nuevo Costo", format="$ %.2f")}
                )
                
                st.markdown("##### 3. Acciones para la Orden Modificada")
                
                def callback_guardar_modificacion_individual():
                    df_historico_actualizado = df_ordenes_historico.copy()
                    df_historico_actualizado = df_historico_actualizado.set_index('ID_Orden')
                    df_editada_individual_idx = df_editada_individual.set_index('ID_Orden')
                    df_historico_actualizado.update(df_editada_individual_idx)
                    df_historico_actualizado.reset_index(inplace=True)
                    df_historico_actualizado['Costo_Total'] = pd.to_numeric(df_historico_actualizado['Cantidad_Solicitada'], errors='coerce').fillna(0) * pd.to_numeric(df_historico_actualizado['Costo_Unitario'], errors='coerce').fillna(0)

                    exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_actualizado)
                    if exito:
                        st.success(f"¡Orden {st.session_state.orden_a_modificar_id_select} guardada en GSheets!")
                        st.cache_data.clear()
                    else:
                        st.error(f"Error al guardar: {msg}")

                st.button("💾 Guardar Cambios en GSheets", on_click=callback_guardar_modificacion_individual, type="primary")

                st.markdown("---")
                st.markdown("##### 4. Reenviar Notificación de Corrección")
                email_reenvio = st.text_input("Confirmar correo para reenvío:", key="email_reenvio_mod_input")
                celular_reenvio = st.text_input("Confirmar celular para WhatsApp:", key="celular_reenvio_mod_input")

                if st.button("📧 Enviar Notificación de Corrección"):
                    if email_reenvio or celular_reenvio:
                        with st.spinner("Generando y enviando notificación..."):
                            info_orden = df_editada_individual.iloc[0]
                            orden_id = info_orden['ID_Orden']
                            proveedor_nombre = info_orden['Proveedor']
                            tienda_destino = info_orden['Tienda_Destino']
                            direccion = DIRECCIONES_TIENDAS.get(tienda_destino, "N/A")

                            pdf_mod_bytes = generar_pdf_orden_compra(df_editada_individual, proveedor_nombre, tienda_destino, direccion, "N/A", orden_id)
                            excel_mod_bytes = generar_excel_dinamico(df_editada_individual, f"Detalle_Corregido_{orden_id}")
                            
                            if email_reenvio:
                                asunto = f"**CORRECCIÓN** Orden {orden_id} - Ferreinox"
                                cuerpo = f"<html><body><p>Estimados,</p><p><b>Por favor, tomar nota de la siguiente corrección a nuestra orden {orden_id}.</b> El documento adjunto reemplaza cualquier versión anterior.</p></body></html>"
                                adjuntos = [
                                    {'datos': pdf_mod_bytes, 'nombre_archivo': f"OC_CORREGIDA_{orden_id}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                    {'datos': excel_mod_bytes, 'nombre_archivo': f"Detalle_CORREGIDO_{orden_id}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
                                ]
                                enviado, msg_envio = enviar_correo_con_adjuntos(email_reenvio.split(','), asunto, cuerpo, adjuntos)
                                if enviado: st.success("¡Correo de corrección enviado!")
                                else: st.error(f"Error al enviar correo: {msg_envio}")
                            
                            if celular_reenvio:
                                mensaje_wpp = f"Hola, te enviamos una **CORRECCIÓN** de la orden {orden_id} al correo. Por favor, tomar esta última versión como la válida. ¡Gracias!"
                                st.link_button("📲 Notificar corrección por WhatsApp", generar_link_whatsapp(celular_reenvio, mensaje_wpp), target="_blank")
                    else:
                        st.warning("Por favor, introduce un correo o un número de celular para notificar.")
