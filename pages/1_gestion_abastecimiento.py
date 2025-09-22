# -*- coding: utf-8 -*-
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
from email.mime.base import MIMEBase
from email import encoders
import gspread
from google.oauth2.service_account import Credentials
import logging
import os

# --- 0. CONFIGURACIÓN DE LA PÁGINA Y ESTADO DE SESIÓN ---
st.set_page_config(page_title="Gestión de Abastecimiento v5.6.0", layout="wide", page_icon="⚙️")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
keys_to_initialize = {
    'df_analisis_maestro': pd.DataFrame(),
    'user_role': None,
    'almacen_nombre': None,
    'solicitud_traslado_especial': [],
    'compra_especial_items': [],
    'order_to_edit': None, # Guarda el ID del grupo de la orden que se está editando
    'contacto_manual': {},
    'notificaciones_pendientes': [],
    'orden_a_editar_df': pd.DataFrame(), # DF para la orden que se está editando en seguimiento
    'items_to_add_to_order': pd.DataFrame(), # DF para agregar nuevos items en seguimiento
    'df_compras_editor': pd.DataFrame(), # DF persistente para el editor de compras
    'df_traslados_editor': pd.DataFrame(), # DF persistente para el editor de traslados
    'last_filters_compras': None, # Guarda el estado de los filtros de compras para saber cuándo refrescar
    'last_filters_traslados': None, # Guarda el estado de los filtros de traslados para saber cuándo refrescar
    'df_seguimiento_editor': pd.DataFrame(), # DF persistente para el editor de seguimiento
    'last_filters_seguimiento': None, # Guarda el estado de los filtros de seguimiento para saber cuándo refrescar
    'tiendas_compra_especial_seleccionadas': [], # Almacena las tiendas para la compra especial consolidada
}
for key, default_value in keys_to_initialize.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# --- 1. FUNCIONES DE CONEXIÓN Y GESTIÓN CON GOOGLE SHEETS ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

@st.cache_resource(ttl=3600)
def connect_to_gsheets():
    """Establece conexión con la API de Google Sheets usando las credenciales de Streamlit."""
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        client = gspread.authorize(creds)
        logging.info("Conexión exitosa con Google Sheets.")
        return client
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}. Revisa tus 'secrets'.")
        return None

@st.cache_data(ttl=60)
def load_data_from_sheets(_client, sheet_name):
    """Carga datos de una hoja específica de Google Sheets en un DataFrame de Pandas."""
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        df = pd.DataFrame(worksheet.get_all_records())
        if not df.empty and 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str)
        if 'ID_Orden' in df.columns and not df.empty:
            df['ID_Grupo'] = df['ID_Orden'].astype(str).apply(lambda x: '-'.join(x.split('-')[:-1]))
        logging.info(f"Hoja '{sheet_name}' cargada correctamente con {len(df)} filas.")
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Error: La hoja de cálculo '{sheet_name}' no fue encontrada. Por favor, créala en tu Google Sheets.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ocurrió un error al cargar la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    """Actualiza una hoja completa en Google Sheets, borrando el contenido anterior."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        df_str = df_to_write.astype(str).replace(np.nan, '')
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
        logging.info(f"Hoja '{sheet_name}' actualizada con {len(df_to_write)} filas.")
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        logging.error(f"Error al actualizar la hoja '{sheet_name}': {e}")
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Añade nuevos registros al final de una hoja de Google Sheets existente."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        headers = worksheet.row_values(1)
        df_to_append_str = df_to_append.astype(str).replace(np.nan, '')

        if not headers:
            worksheet.update([df_to_append_str.columns.values.tolist()] + df_to_append_str.values.tolist())
            return True, "Nuevos registros y cabeceras añadidos.", df_to_append
        
        df_to_append_ordered = df_to_append_str.reindex(columns=headers).fillna('')
        worksheet.append_rows(df_to_append_ordered.values.tolist(), value_input_option='USER_ENTERED')
        logging.info(f"{len(df_to_append)} registros añadidos a '{sheet_name}'.")
        return True, f"Nuevos registros añadidos a '{sheet_name}'.", df_to_append_ordered
    except Exception as e:
        logging.error(f"Error al añadir registros en la hoja '{sheet_name}': {e}")
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}", pd.DataFrame()

# --- MODIFICACIÓN CLAVE: registrar_ordenes_en_sheets ---
# Ahora guarda costo y peso para todas las órdenes, simplificando la lógica posterior.
def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    """Prepara y registra un DataFrame de órdenes en la hoja 'Registro_Ordenes' con IDs de grupo."""
    if df_orden.empty or client is None: return False, "No hay datos para registrar.", pd.DataFrame()

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = df_orden.copy()

    # Identificar columnas de cantidad, costo y peso dinámicamente
    cantidad_col = next((col for col in ['Uds a Comprar', 'Uds a Enviar', 'Cantidad_Solicitada'] if col in df_orden.columns), None)
    costo_col = next((col for col in ['Costo_Promedio_UND', 'Costo_Unitario'] if col in df_orden.columns), None)
    peso_col = next((col for col in ['Peso_Articulo', 'Peso Individual (kg)', 'Peso_Unitario_kg'] if col in df_orden.columns), None)
    
    if not cantidad_col: return False, "No se encontró la columna de cantidad.", pd.DataFrame()

    # Estandarizar columnas y calcular totales
    df_registro['Cantidad_Solicitada'] = pd.to_numeric(df_registro[cantidad_col], errors='coerce').fillna(0)
    df_registro['Costo_Unitario'] = pd.to_numeric(df_registro.get(costo_col, 0), errors='coerce').fillna(0)
    df_registro['Peso_Unitario_kg'] = pd.to_numeric(df_registro.get(peso_col, 0), errors='coerce').fillna(0)
    
    df_registro['Costo_Total'] = df_registro['Cantidad_Solicitada'] * df_registro['Costo_Unitario']
    df_registro['Peso_Total_kg'] = df_registro['Cantidad_Solicitada'] * df_registro['Peso_Unitario_kg']

    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    id_grupo = ""
    if tipo_orden == "Compra Sugerencia":
        id_grupo = f"OC-{timestamp}"
        df_registro['Proveedor'] = df_registro['Proveedor']
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    elif tipo_orden == "Compra Especial":
        id_grupo = f"OC-SP-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
        df_registro['Costo_Unitario'] = df_registro['Costo_Promedio_UND'] # Asegurar costo
    elif tipo_orden == "Traslado Automático":
        id_grupo = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
        # Corrección: Mantener el costo para traslados para valorar el inventario movido
        # df_registro['Costo_Unitario'] = 0 # Traslados no tienen costo de compra
        # df_registro['Costo_Total'] = 0
    elif tipo_orden == "Traslado Especial":
        id_grupo = f"TR-SP-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino
        # Corrección: Mantener el costo para traslados
        # df_registro['Costo_Unitario'] = 0 # Traslados no tienen costo de compra
        # df_registro['Costo_Total'] = 0

    df_registro['ID_Grupo'] = id_grupo
    df_registro['ID_Orden'] = [f"{id_grupo}-{i+1}" for i in range(len(df_registro))]

    # Columnas finales según la nueva estructura de Google Sheets
    columnas_finales = [
        'ID_Grupo', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 
        'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total',
        'Peso_Unitario_kg', 'Peso_Total_kg'
    ]
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')

    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)


# --- 2. FUNCIONES AUXILIAres Y DE UI ---
def enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo_html, lista_de_adjuntos):
    """Envía un correo electrónico con adjuntos usando las credenciales de Gmail de los secrets."""
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
                part = MIMEBase(adj_info.get('tipo_mime', 'application'), adj_info.get('subtipo_mime', 'octet-stream'))
                part.set_payload(attachment_stream.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment', filename=adj_info['nombre_archivo'])
                msg.attach(part)

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(remitente, password)
            server.sendmail(remitente, destinatarios, msg.as_string())
        return True, "Correo enviado exitosamente."
    except Exception as e:
        return False, f"Error al enviar el correo: '{e}'. Revisa la configuración de 'secrets'."

def generar_link_whatsapp(numero, mensaje):
    """Codifica un mensaje y genera un enlace de WhatsApp 'wa.me'."""
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"

def whatsapp_button(label, url, key):
    """Muestra un botón estilizado en HTML para abrir un enlace de WhatsApp."""
    st.markdown(f"""
    <a href="{url}" target="_blank" style="text-decoration: none;">
        <div style="
            display: inline-block; padding: 8px 16px; background-color: #25D366; color: white; 
            border-radius: 5px; text-align: center; font-weight: bold; cursor: pointer; margin-top: 5px;
        ">
            {label}
        </div>
    </a>""", unsafe_allow_html=True)

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    """Algoritmo para generar un plan de traslados óptimo basado en excedentes y necesidades."""
    if _df_analisis is None or _df_analisis.empty: return pd.DataFrame()

    df_origen = _df_analisis[_df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis[_df_analisis['Necesidad_Ajustada_Por_Transito'] > 0].sort_values(by='Necesidad_Ajustada_Por_Transito', ascending=False).copy()

    if df_origen.empty or df_destino.empty: return pd.DataFrame()

    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()

    for _, necesidad_row in df_destino.iterrows():
        sku, tienda_necesitada, necesidad_actual = necesidad_row['SKU'], necesidad_row['Almacen_Nombre'], necesidad_row['Necesidad_Ajustada_Por_Transito']
        if necesidad_actual <= 0: continue

        posibles_origenes = df_origen[(df_origen['SKU'] == sku) & (df_origen['Almacen_Nombre'] != tienda_necesitada)]

        for _, origen_row in posibles_origenes.iterrows():
            tienda_origen = origen_row['Almacen_Nombre']
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
    df_resultado['Peso Individual (kg)'] = pd.to_numeric(df_resultado['Peso Individual (kg)'], errors='coerce').fillna(0)
    df_resultado['Uds a Enviar'] = pd.to_numeric(df_resultado['Uds a Enviar'], errors='coerce').fillna(0)
    df_resultado['Costo_Promedio_UND'] = pd.to_numeric(df_resultado['Costo_Promedio_UND'], errors='coerce').fillna(0)
    
    df_resultado['Peso Total (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Costo_Promedio_UND']

    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)

class PDF(FPDF):
    """Clase personalizada para generar PDFs de Órdenes de Compra con cabecera y pie de página de la empresa."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        self.font_family = 'Helvetica'

        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            font_path_regular = os.path.join(script_dir, 'fonts', 'DejaVuSans.ttf')
            font_path_bold = os.path.join(script_dir, 'fonts', 'DejaVuSans-Bold.ttf')
            
            if os.path.exists(font_path_regular) and os.path.exists(font_path_bold):
                self.add_font('DejaVu', '', font_path_regular, uni=True)
                self.add_font('DejaVu', 'B', font_path_bold, uni=True)
                self.font_family = 'DejaVu'
            else:
                logging.warning("Archivos de fuente 'DejaVu' no encontrados. Se usará Helvetica.")
        except Exception as e:
            logging.warning(f"No se pudo cargar la fuente 'DejaVu' (Error: {e}). Se usará Helvetica.")

    def header(self):
        font_name = self.font_family
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(script_dir, 'LOGO FERREINOX SAS BIC 2024.png')
            
            if os.path.exists(logo_path):
                self.image(logo_path, x=10, y=8, w=65)
            else:
                self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO NO ENCONTRADO]', 1, 0, 'C')
                logging.warning(f"No se encontró el archivo del logo en la ruta: {logo_path}")

        except Exception as e:
            self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO ERROR]', 1, 0, 'C')
            logging.error(f"Error al cargar el logo: {e}")

        self.set_y(12); self.set_x(80); self.set_font(font_name, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R')
        self.set_x(80); self.set_font(font_name, '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R')
        self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        font_name = self.font_family
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1); self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font(font_name, '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}     |      {self.empresa_web}     |      {self.empresa_email}     |      {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C')
        self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num):
    """Genera un archivo PDF para una orden de compra a partir de un DataFrame."""
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    font_name = pdf.font_family
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=25)

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

    pdf.set_y(max(y_end_prov, y_end_envio)); pdf.ln(5)

    pdf.set_font(font_name, 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {orden_num}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1); pdf.ln(10)

    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font(font_name, 'B', 9)
    headers = ['Cód. Interno', 'Cód. Prov.', 'Descripción del Producto', 'Cant.', 'Costo Unit.', 'Costo Total']
    widths = [25, 30, 70, 15, 25, 25]
    for i, header in enumerate(headers):
        pdf.cell(widths[i], 8, header, 1, 0, 'C', 1)
    pdf.ln()

    pdf.set_font(font_name, '', 8); pdf.set_text_color(0, 0, 0)
    subtotal = 0

    cantidad_col = next((c for c in ['Uds a Comprar', 'Uds a Enviar', 'Cantidad_Solicitada'] if c in df_seleccion.columns), None)
    costo_col = next((c for c in ['Costo_Promedio_UND', 'Costo_Unitario'] if c in df_seleccion.columns), None)
    if not cantidad_col or not costo_col: return None

    df_seleccion[cantidad_col] = pd.to_numeric(df_seleccion[cantidad_col], errors='coerce').fillna(0)
    df_seleccion[costo_col] = pd.to_numeric(df_seleccion[costo_col], errors='coerce').fillna(0)

    for _, row in df_seleccion.iterrows():
        costo_total_item = row[cantidad_col] * row[costo_col]
        subtotal += costo_total_item

        pdf.set_font(font_name, '', 8)
        initial_y = pdf.get_y()
        line_height = 5
        lines = pdf.multi_cell(widths[2], line_height, str(row.get('Descripcion', '')), 0, 'L', split_only=True)
        max_h = len(lines) * line_height

        pdf.cell(widths[0], max_h, str(row.get('SKU', '')), 1, 0, 'L')
        pdf.cell(widths[1], max_h, str(row.get('SKU_Proveedor', 'N/A')), 1, 0, 'L')
        
        current_x = pdf.get_x()
        current_y = pdf.get_y()
        pdf.multi_cell(widths[2], line_height, str(row.get('Descripcion', '')), 1, 'L')
        pdf.set_y(current_y)
        pdf.set_x(current_x + widths[2])

        pdf.cell(widths[3], max_h, str(int(row[cantidad_col])), 1, 0, 'C')
        pdf.cell(widths[4], max_h, f"${row[costo_col]:,.2f}", 1, 0, 'R')
        pdf.cell(widths[5], max_h, f"${costo_total_item:,.2f}", 1, 1, 'R')

    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font(font_name, '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font(font_name, 'B', 11)
    pdf.cell(55, 10, 'TOTAL A PAGAR', 1, 0, 'R'); pdf.cell(35, 10, f"${total_general:,.2f}", 1, 1, 'R')
    return bytes(pdf.output())

# --- INICIO DEL BLOQUE CORREGIDO: Función de Excel Estandarizada y Robusta ---
def generar_excel_dinamico(df, nombre_hoja, tipo_orden):
    """
    Genera un archivo Excel en memoria a partir de un DataFrame, con formato unificado y cálculo de ancho de columna robusto.
    """
    output = io.BytesIO()
    nombre_hoja_truncado = nombre_hoja[:31]
    
    df_excel = df.copy()
    
    # Mapa flexible para estandarizar nombres de columnas
    rename_map = {
        'Uds a Enviar': 'Cantidad', 'Uds a Comprar': 'Cantidad', 'Cantidad_Solicitada': 'Cantidad',
        'Tienda Origen': 'Origen', 'Proveedor': 'Origen',
        'Tienda Destino': 'Destino', 'Tienda_Destino': 'Destino', 'Tienda': 'Destino',
        'Peso Individual (kg)': 'Peso_Unitario_kg', 'Peso_Articulo': 'Peso_Unitario_kg',
        'Peso Total (kg)': 'Peso_Total_kg',
        'Costo_Promedio_UND': 'Costo_Unitario',
        'Valor del Traslado': 'Costo_Total', 'Valor de la Compra': 'Costo_Total',
    }

    df_excel.rename(columns=rename_map, inplace=True)

    # Asegurar que las columnas calculadas existen y son numéricas
    if 'Cantidad' in df_excel.columns:
        df_excel['Cantidad'] = pd.to_numeric(df_excel['Cantidad'], errors='coerce').fillna(0)
        
        if 'Peso_Unitario_kg' in df_excel.columns:
            df_excel['Peso_Unitario_kg'] = pd.to_numeric(df_excel['Peso_Unitario_kg'], errors='coerce').fillna(0)
            if 'Peso_Total_kg' not in df_excel.columns:
                df_excel['Peso_Total_kg'] = df_excel['Cantidad'] * df_excel['Peso_Unitario_kg']

        if 'Costo_Unitario' in df_excel.columns:
            df_excel['Costo_Unitario'] = pd.to_numeric(df_excel['Costo_Unitario'], errors='coerce').fillna(0)
            if 'Costo_Total' not in df_excel.columns:
                df_excel['Costo_Total'] = df_excel['Cantidad'] * df_excel['Costo_Unitario']

    # Definir el orden final y seleccionar columnas existentes
    COLS_FINALES_EXCEL = ['SKU', 'Descripcion', 'Cantidad', 'Origen', 'Destino', 'Peso_Unitario_kg', 'Peso_Total_kg', 'Costo_Unitario', 'Costo_Total']
    cols_existentes_en_df = [col for col in COLS_FINALES_EXCEL if col in df_excel.columns]
    df_final = df_excel[cols_existentes_en_df].fillna('')
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df_final.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja_truncado}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja_truncado)
            writer.sheets[nombre_hoja_truncado].set_column('A:A', 70)
            return output.getvalue()

        df_final.to_excel(writer, index=False, sheet_name=nombre_hoja_truncado, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja_truncado]
        
        # Formatos de celda
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '$#,##0.00'})
        weight_format = workbook.add_format({'num_format': '0.00 "kg"'})
        
        # Escribir cabeceras con formato
        for col_num, value in enumerate(df_final.columns.values): 
            worksheet.write(0, col_num, value.replace('_', ' ').title(), header_format)

        # Aplicar formatos numéricos a columnas específicas
        col_map = {col: i for i, col in enumerate(df_final.columns)}
        if 'Costo_Unitario' in col_map: worksheet.set_column(col_map['Costo_Unitario'], col_map['Costo_Unitario'], 15, money_format)
        if 'Costo_Total' in col_map: worksheet.set_column(col_map['Costo_Total'], col_map['Costo_Total'], 15, money_format)
        if 'Peso_Unitario_kg' in col_map: worksheet.set_column(col_map['Peso_Unitario_kg'], col_map['Peso_Unitario_kg'], 15, weight_format)
        if 'Peso_Total_kg' in col_map: worksheet.set_column(col_map['Peso_Total_kg'], col_map['Peso_Total_kg'], 15, weight_format)

        # Lógica robusta para ajustar anchos de columna automáticamente
        for i, col in enumerate(df_final.columns):
            # Omitir columnas con formato especial ya definido
            if col in ['Costo_Unitario', 'Costo_Total', 'Peso_Unitario_kg', 'Peso_Total_kg']:
                continue

            # Calcular longitud del encabezado
            header_len = len(str(col))

            # Calcular longitud máxima de los datos en la columna de forma segura
            if not df_final[col].empty:
                # Usar una list comprehension para convertir todo a string y obtener la longitud.
                # `default=0` previene errores en secuencias vacías.
                data_max_len = max((len(str(x)) for x in df_final[col]), default=0)
            else:
                data_max_len = 0
            
            # Usar el valor mayor (encabezado o datos) y añadir un búfer.
            # Limitar el ancho máximo a 50 para evitar columnas excesivamente anchas.
            max_len = max(header_len, data_max_len) + 2
            worksheet.set_column(i, i, min(max_len, 50))
            
    return output.getvalue()
# --- FIN DEL BLOQUE CORREGIDO ---


# --- DICCIONARIOS DE CONTACTO Y DIRECCIONES ---
DIRECCIONES_TIENDAS = {
    'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26',
    'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32',
    'Laureles': 'Av. Laureles #35-13', 'Opalo': 'Cra. 10 #70-52'
}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448', 'email': 'jhon.duque@abracol.com'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917', 'email': 'sara.lara@saint-gobain.com'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589', 'email': 'julian.nanes@goya.com'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893', 'email': 'juan.martinez@yale.com'},
}
CONTACTOS_TIENDAS = {
    'Armenia': {'email': 'tiendapintucoarmenia@ferreinox.co', 'celular': '573165219904', 'nombre': 'Equipo Armenia'},
    'Olaya': {'email': 'tiendapintucopereira@ferreinox.co', 'celular': '573102368346', 'nombre': 'Equipo Olaya'},
    'Manizales': {'email': 'tiendapintucomanizales@ferreinox.co', 'celular': '573136086232', 'nombre': 'Equipo Manizales'},
    'Laureles': {'email': 'tiendapintucolaureles@ferreinox.co', 'celular': '573104779389', 'nombre': 'Equipo Laureles'},
    'Opalo': {'email': 'tiendapintucodosquebradas@ferreinox.co', 'celular': '573108561506', 'nombre': 'Equipo Opalo'},
    'FerreBox': {'email': 'compras@ferreinox.co', 'celular': '573127574279', 'nombre': 'Equipo FerreBox'}
}

# --- 3. LÓGICA PRINCIPAL Y FLUJO DE LA APP ---
st.title("🚀 Tablero de Control de Abastecimiento v5.6.0")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real conectado a Google Sheets.")

if 'df_analisis_maestro' not in st.session_state or st.session_state.df_analisis_maestro.empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos base de inventario.")
    st.stop()

df_maestro_base = st.session_state.df_analisis_maestro.copy()
client = connect_to_gsheets()
df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")

@st.cache_data
def calcular_estado_inventario_completo(df_base, df_ordenes):
    """Función central que calcula el estado completo del inventario, incluyendo tránsito, traslados y sugerencias de compra."""
    df_maestro = df_base.copy()

    if not df_ordenes.empty and 'Estado' in df_ordenes.columns:
        df_pendientes = df_ordenes[df_ordenes['Estado'] == 'Pendiente'].copy()
        if not df_pendientes.empty:
            df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
            stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
            stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito', 'Tienda_Destino': 'Almacen_Nombre'}, inplace=True)
            df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
            df_maestro['Stock_En_Transito'].fillna(0, inplace=True)
        else:
            df_maestro['Stock_En_Transito'] = 0
    else:
        df_maestro['Stock_En_Transito'] = 0

    numeric_cols = ['Stock', 'Costo_Promedio_UND', 'Necesidad_Total', 'Excedente_Trasladable', 'Precio_Venta_Estimado', 'Demanda_Diaria_Promedio', 'Peso_Articulo']
    for col in numeric_cols:
        if col in df_maestro.columns:
            df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)
        else: 
            df_maestro[col] = 0


    df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro.get('Necesidad_Total', 0) - df_maestro.get('Stock_En_Transito', 0)).clip(lower=0)
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

# --- 4. NAVEGACIÓN Y FILTROS EN SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Filtros de Gestión")
    opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
    almacenes_disponibles = sorted(df_maestro['Almacen_Nombre'].unique().tolist())

    if st.session_state.get('user_role') == 'gerente':
        almacen_options = [opcion_consolidado] + almacenes_disponibles
    else:
        almacen_options = [st.session_state.get('almacen_nombre')] if st.session_state.get('almacen_nombre') in almacenes_disponibles else []

    if not almacen_options:
        st.warning("No hay almacenes disponibles para tu usuario.")
        st.stop()

    selected_almacen_nombre = st.selectbox("Selecciona la Vista de Tienda:", almacen_options, key="sb_almacen")

    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_maestro.copy()
    else:
        df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre].copy()

    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    default_marcas = [m for m in marcas_unicas if m]
    selected_marcas = st.multiselect("Filtrar por Marca:", default_marcas, default=default_marcas)

    if selected_marcas:
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)].copy()
    else:
        df_filtered = df_vista.copy()

    st.markdown("---")
    st.header("Menú Principal")
    tab_titles = ["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"]
    active_tab = st.radio("Navegación", tab_titles, key='active_tab', label_visibility="collapsed")
    st.markdown("---")
    
    st.subheader("Sincronización de Datos")
    if st.button("🔄 Forzar Recarga de Datos"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.session_state.notificaciones_pendientes = [] # Limpiar notificaciones al recargar
        st.rerun()
        
    if st.button("Sincronizar 'Estado_Inventario' en GSheets"):
        with st.spinner("Sincronizando..."):
            cols_to_sync = ['SKU', 'Almacen_Nombre', 'Stock', 'Costo_Promedio_UND', 'Sugerencia_Compra', 'Necesidad_Total', 'Excedente_Trasladable', 'Estado_Inventario']
            df_to_sync = df_maestro[[c for c in cols_to_sync if c in df_maestro.columns]].copy()
            exito, msg = update_sheet(client, "Estado_Inventario", df_to_sync)
            if exito: st.success(msg)
            else: st.error(msg)

# --- 5. CONTENIDO DE LAS PESTAÑAS ---

# --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
if active_tab == tab_titles[0]:
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")

    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
    oportunidad_ahorro = 0
    if not df_plan_maestro.empty:
        df_plan_filtrado = df_plan_maestro.copy()
        if selected_almacen_nombre != opcion_consolidado:
            df_plan_filtrado = df_plan_maestro[df_plan_maestro['Tienda Destino'] == selected_almacen_nombre]
        oportunidad_ahorro = df_plan_filtrado['Valor del Traslado'].sum()

    df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
    venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label="💰 Valor Compra Requerida (Post-Traslados)", value=f"${necesidad_compra_total:,.0f}")
    kpi2.metric(label="💸 Ahorro por Traslados", value=f"${oportunidad_ahorro:,.0f}")
    kpi3.metric(label="📉 Venta Potencial Perdida (30 días)", value=f"${venta_perdida:,.0f}")

    with st.container(border=True):
        if venta_perdida > 0: st.markdown(f"**🚨 Alerta:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** por **{len(df_quiebre)}** productos en quiebre.")
        if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña 'Traslados'.")
        if necesidad_compra_total > 0:
            df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
            df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
            if not df_compras_prioridad.empty:
                top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                st.markdown(f"**🎯 Enfoque:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**.")
        if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0:
            st.success("✅ ¡Inventario Optimizado! No se detectan necesidades urgentes con los filtros actuales.")

    st.markdown("---")
    col_g1, col_g2 = st.columns(2)
    df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0].copy()
    if not df_compras_chart.empty:
        df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
        with col_g1:
            data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Requerida por Tienda (Post-Traslados)")
            st.plotly_chart(fig, use_container_width=True)
        with col_g2:
            fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
            st.plotly_chart(fig, use_container_width=True)

# --- PESTAÑA 2: PLAN DE TRASLADOS ---
if active_tab == tab_titles[1]:
    st.subheader("🚚 Plan de Traslados entre Tiendas")

    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            st.markdown("##### Filtros Avanzados de Traslados")
            f_col1, f_col2, f_col3 = st.columns(3)
            
            # --- INICIO DE MODIFICACIÓN: FILTRO DE ORIGEN A MULTISELECT ---
            lista_origenes = sorted(df_plan_maestro['Tienda Origen'].unique().tolist())
            filtro_origen = f_col1.multiselect("Filtrar por Tienda(s) Origen:", lista_origenes, default=lista_origenes, key="filtro_origen_multi")
            # --- FIN DE MODIFICACIÓN ---

            lista_destinos = ["Todas"] + sorted(df_plan_maestro['Tienda Destino'].unique().tolist())
            filtro_destino = f_col2.selectbox("Filtrar por Tienda Destino:", lista_destinos, key="filtro_destino")

            lista_proveedores_traslado = ["Todos"] + sorted(df_plan_maestro['Proveedor'].unique().tolist())
            filtro_proveedor_traslado = f_col3.selectbox("Filtrar por Proveedor:", lista_proveedores_traslado, key="filtro_proveedor_traslado")
            
            current_filters = f"{filtro_origen}-{filtro_destino}-{filtro_proveedor_traslado}"
            if st.session_state.last_filters_traslados != current_filters:
                df_aplicar_filtros = df_plan_maestro.copy()
                
                # --- INICIO DE MODIFICACIÓN: LÓGICA DE FILTRADO PARA MULTISELECT ---
                if filtro_origen: 
                    df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Origen'].isin(filtro_origen)]
                # --- FIN DE MODIFICACIÓN ---
                
                if filtro_destino != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Destino'] == filtro_destino]
                if filtro_proveedor_traslado != "Todos": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Proveedor'] == filtro_proveedor_traslado]

                df_para_editar = pd.merge(df_aplicar_filtros, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                          left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left'
                                          ).drop(columns=['Almacen_Nombre']).fillna({'Stock_En_Transito': 0})
                df_para_editar['Seleccionar'] = False
                st.session_state.df_traslados_editor = df_para_editar.copy()
                st.session_state.last_filters_traslados = current_filters
                # No rerun here, let the rest of the code run

            if st.session_state.df_traslados_editor.empty:
                st.warning("No se encontraron traslados que coincidan con los filtros.")
            else:
                with st.form(key="traslados_automatico_form"):
                    st.markdown("Seleccione y/o ajuste las cantidades a enviar. **Haga clic en 'Confirmar Cambios' para procesar.**")
                    
                    column_order = [
                        "Seleccionar", "SKU", "Descripcion", "Stock en Origen", "Stock en Destino",
                        "Uds a Enviar", "Stock_En_Transito", "Tienda Origen", "Tienda Destino",
                        "Necesidad en Destino", "Proveedor", "Marca_Nombre", "Segmento_ABC",
                        "Costo_Promedio_UND", "Valor del Traslado", "Peso Total (kg)", "Peso Individual (kg)"
                    ]
                    
                    display_columns = [col for col in column_order if col in st.session_state.df_traslados_editor.columns]
                    
                    edited_df_traslados = st.data_editor(
                        st.session_state.df_traslados_editor[display_columns],
                        hide_index=True, use_container_width=True,
                        column_config={
                            "Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                            "Costo_Promedio_UND": st.column_config.NumberColumn(label="Costo UND", format="$ {:,.0f}"),
                            "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d"),
                            "Stock en Origen": st.column_config.NumberColumn(format="%d"),
                            "Stock en Destino": st.column_config.NumberColumn(format="%d"),
                            "Necesidad en Destino": st.column_config.NumberColumn(format="%.1f"),
                            "Valor del Traslado": st.column_config.NumberColumn(format="$ {:,.0f}"),
                            "Peso Total (kg)": st.column_config.NumberColumn(format="%.2f kg"),
                            "Peso Individual (kg)": st.column_config.NumberColumn(format="%.2f kg"),
                            "Seleccionar": st.column_config.CheckboxColumn(required=True),
                        },
                        disabled=[c for c in display_columns if c not in ['Seleccionar', 'Uds a Enviar']],
                        key="editor_traslados")
                    
                    form_t1, form_t2, form_t3 = st.columns([1,1.2,4])
                    select_all_t = form_t1.form_submit_button("Seleccionar Todos")
                    deselect_all_t = form_t2.form_submit_button("Deseleccionar Todos")
                    submitted = form_t3.form_submit_button("⚙️ Confirmar Cambios en la Selección", type="primary")
                    
                    if select_all_t:
                        edited_df_traslados['Seleccionar'] = True
                        st.session_state.df_traslados_editor = edited_df_traslados.copy()
                        st.rerun() # Rerun to update the data editor state
                    if deselect_all_t:
                        edited_df_traslados['Seleccionar'] = False
                        st.session_state.df_traslados_editor = edited_df_traslados.copy()
                        st.rerun() # Rerun to update the data editor state

                    if submitted:
                        st.session_state.df_traslados_editor = edited_df_traslados
                        st.success("Cambios confirmados. Proceda a descargar el Excel o registrar el traslado a continuación.")
                
                df_seleccionados_traslado_full = st.session_state.df_traslados_editor[
                    (st.session_state.df_traslados_editor['Seleccionar']) & 
                    (st.session_state.df_traslados_editor['Uds a Enviar'] > 0)
                ].copy()

                if not df_seleccionados_traslado_full.empty:
                    # RECALCULAR VALORES TRAS EDICIÓN
                    df_seleccionados_traslado_full['Uds a Enviar'] = pd.to_numeric(df_seleccionados_traslado_full['Uds a Enviar'], errors='coerce').fillna(0)
                    df_seleccionados_traslado_full['Peso Individual (kg)'] = pd.to_numeric(df_seleccionados_traslado_full['Peso Individual (kg)'], errors='coerce').fillna(0)
                    df_seleccionados_traslado_full['Costo_Promedio_UND'] = pd.to_numeric(df_seleccionados_traslado_full['Costo_Promedio_UND'], errors='coerce').fillna(0)
                    df_seleccionados_traslado_full['Peso Total (kg)'] = df_seleccionados_traslado_full['Uds a Enviar'] * df_seleccionados_traslado_full['Peso Individual (kg)']
                    df_seleccionados_traslado_full['Valor del Traslado'] = df_seleccionados_traslado_full['Uds a Enviar'] * df_seleccionados_traslado_full['Costo_Promedio_UND']
                    
                    st.markdown("---")
                    total_unidades = df_seleccionados_traslado_full['Uds a Enviar'].sum()
                    total_peso = df_seleccionados_traslado_full['Peso Total (kg)'].sum()
                    total_valor = df_seleccionados_traslado_full['Valor del Traslado'].sum()
                    
                    resumen_col1, resumen_col2 = st.columns([3,1])
                    with resumen_col1:
                        st.info(f"**Resumen de la Carga Seleccionada:** {int(total_unidades)} Unidades | **{total_peso:,.2f} kg** de Peso Total | **${total_valor:,.2f}** en Valor")

                    with resumen_col2:
                        excel_bytes = generar_excel_dinamico(df_seleccionados_traslado_full, "Traslados_Seleccionados", "Traslado Automático")
                        st.download_button(
                            label="📥 Descargar Selección en Excel",
                            data=excel_bytes,
                            file_name=f"seleccion_traslados_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.ms-excel",
                            use_container_width=True
                        )
                        
                    with st.form("form_traslado_auto_enviar"):
                        destinos_implicados = df_seleccionados_traslado_full['Tienda Destino'].unique().tolist()
                        origenes_implicados = df_seleccionados_traslado_full['Tienda Origen'].unique().tolist()
                        
                        emails_destinos = [CONTACTOS_TIENDAS.get(d, {}).get('email', '') for d in destinos_implicados]
                        emails_origenes = [CONTACTOS_TIENDAS.get(o, {}).get('email', '') for o in origenes_implicados]
                        
                        emails_predefinidos = list(set(filter(None, emails_destinos + emails_origenes)))
                        
                        email_dest_traslado = st.text_input("📧 Correo(s) de destinatario(s) (separar con coma o punto y coma):", value=", ".join(emails_predefinidos), key="email_traslado")

                        st.markdown("##### Contactos para Notificación WhatsApp")
                        all_tiendas_implicadas = list(set(destinos_implicados + origenes_implicados))
                        for tienda in all_tiendas_implicadas:
                            c1, c2 = st.columns(2)
                            st.session_state.contacto_manual.setdefault(tienda, CONTACTOS_TIENDAS.get(tienda, {}))
                            nombre_actual = c1.text_input(f"Nombre contacto {tienda}", value=st.session_state.contacto_manual[tienda].get("nombre", ''), key=f"nombre_contacto_aut_{tienda}")
                            celular_actual = c2.text_input(f"Celular {tienda}", value=st.session_state.contacto_manual[tienda].get("celular", ''), key=f"celular_contacto_aut_{tienda}")
                            st.session_state.contacto_manual[tienda]["nombre"] = nombre_actual
                            st.session_state.contacto_manual[tienda]["celular"] = celular_actual

                        if st.form_submit_button("✅ Enviar y Registrar Traslado", use_container_width=True, type="primary"):
                            with st.spinner("Registrando traslado y enviando notificaciones..."):
                                df_para_notificar_email = df_seleccionados_traslado_full.copy()
                                
                                exito_registro, msg_registro, df_registrado_gsheets = registrar_ordenes_en_sheets(client, df_seleccionados_traslado_full, "Traslado Automático")
                                if exito_registro:
                                    st.success(f"✅ ¡Traslado registrado exitosamente! {msg_registro}")
                                    if email_dest_traslado:
                                        excel_bytes_email = generar_excel_dinamico(df_para_notificar_email, "Plan_de_Traslados", "Traslado Automático")
                                        id_grupo_registrado = df_registrado_gsheets['ID_Grupo'].iloc[0]
                                        asunto = f"Nuevo Plan de Traslado Interno - {id_grupo_registrado}"
                                        cuerpo_html = f"""<html><body><p>Hola equipo,</p><p>Se ha registrado un nuevo plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado en el archivo adjunto.</p><p><b>ID de Grupo de Traslado:</b> {id_grupo_registrado}</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"""
                                        adjunto = [{'datos': excel_bytes_email, 'nombre_archivo': f"Plan_Traslado_{id_grupo_registrado}.xlsx"}]
                                        destinatarios_finales = [e.strip() for e in email_dest_traslado.replace(';', ',').split(',') if e.strip()]
                                        enviado, msg = enviar_correo_con_adjuntos(destinatarios_finales, asunto, cuerpo_html, adjunto)
                                        if enviado: st.success(msg)
                                        else: st.error(msg)

                                    st.session_state.notificaciones_pendientes = []
                                    for destino, df_grupo_destino in df_para_notificar_email.groupby('Tienda Destino'):
                                        info_tienda = st.session_state.contacto_manual.get(destino, {})
                                        numero_wpp = info_tienda.get("celular", "").strip()
                                        if numero_wpp:
                                            nombre_contacto = info_tienda.get("nombre", "equipo de " + destino)
                                            id_grupo_tienda = df_registrado_gsheets['ID_Grupo'].iloc[0] # Usar el ID de grupo único
                                            peso_total_destino = pd.to_numeric(df_grupo_destino['Peso Total (kg)'], errors='coerce').sum()
                                            mensaje_wpp = f"Hola {nombre_contacto}, se ha generado una nueva orden de traslado hacia su tienda (Grupo ID: {id_grupo_tienda}). El peso total de la carga es de *{peso_total_destino:,.2f} kg*. Por favor, estar atentos a la recepción. ¡Gracias!"
                                            st.session_state.notificaciones_pendientes.append({
                                                "label": f"📲 Notificar a {destino} por WhatsApp",
                                                "url": generar_link_whatsapp(numero_wpp, mensaje_wpp),
                                                "key": f"wpp_traslado_aut_{destino}"
                                            })
                                    st.rerun()
                                else:
                                    st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")


    # --- INICIO BLOQUE MODIFICADO: TRASLADOS ESPECIALES ---
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        st.markdown("##### 1. Buscar y añadir productos a la solicitud")
        search_term_especial = st.text_input("Buscar producto por SKU o Descripción para traslado especial:", key="search_traslado_especial")
        
        # Guardar el estado de los ítems a añadir para evitar que desaparezcan
        if 'traslado_especial_items_to_add' not in st.session_state:
            st.session_state['traslado_especial_items_to_add'] = pd.DataFrame()

        if search_term_especial:
            mask_especial = (df_maestro['Stock'] > 0) & (df_maestro['SKU'].str.contains(search_term_especial, case=False, na=False) | df_maestro['Descripcion'].str.contains(search_term_especial, case=False, na=False))
            df_resultados_especial = df_maestro[mask_especial].copy()
            
            if not df_resultados_especial.empty:
                df_resultados_especial['Uds a Enviar'] = 1
                df_resultados_especial['Seleccionar'] = False
                cols_busqueda = ['Seleccionar', 'SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Stock_En_Transito', 'Uds a Enviar']
                
                # Use a unique key for this data editor
                edited_df_especial = st.data_editor(
                    df_resultados_especial[cols_busqueda], key="editor_traslados_especiales_busqueda", use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(min_value=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Stock_En_Transito'])
                
                # Check for changes in the data editor
                df_for_add = edited_df_especial[edited_df_especial['Seleccionar']].copy()
                st.session_state['traslado_especial_items_to_add'] = df_for_add

            else:
                st.warning("No se encontraron productos con stock para ese criterio de búsqueda.")

        if not st.session_state['traslado_especial_items_to_add'].empty:
            if st.button("➕ Añadir seleccionados a la solicitud", key="btn_anadir_especial"):
                new_items = st.session_state['traslado_especial_items_to_add'].to_dict('records')
                for row in new_items:
                    item_id = f"{row['SKU']}_{row['Almacen_Nombre']}"
                    if not any(item['id'] == item_id for item in st.session_state.solicitud_traslado_especial):
                        item_data = df_maestro.loc[(df_maestro['SKU'] == row['SKU']) & (df_maestro['Almacen_Nombre'] == row['Almacen_Nombre'])].iloc[0]
                        st.session_state.solicitud_traslado_especial.append({
                            'id': item_id, 'SKU': row['SKU'], 'Descripcion': row['Descripcion'],
                            'Tienda Origen': row['Almacen_Nombre'], 'Uds a Enviar': row['Uds a Enviar'], 
                            'Costo_Promedio_UND': item_data['Costo_Promedio_UND'],
                            'Peso Individual (kg)': item_data['Peso_Articulo'],
                            'Borrar': False # Nueva columna para borrado
                        })
                st.success(f"{len(new_items)} producto(s) añadidos a la solicitud.")
                st.session_state['traslado_especial_items_to_add'] = pd.DataFrame() # Clear the staging area
                st.rerun()


        if st.session_state.solicitud_traslado_especial:
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la solicitud de traslado")
            
            with st.form("form_traslado_especial"):
                df_solicitud_actual = pd.DataFrame(st.session_state.solicitud_traslado_especial)
                
                # Recalculate values for the data editor based on latest inputs
                df_solicitud_actual['Valor del Traslado'] = df_solicitud_actual['Uds a Enviar'] * df_solicitud_actual['Costo_Promedio_UND']
                df_solicitud_actual['Peso Total (kg)'] = df_solicitud_actual['Uds a Enviar'] * df_solicitud_actual['Peso Individual (kg)']


                tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
                tienda_destino_especial = st.selectbox("Confirmar Tienda Destino para esta solicitud:", tiendas_destino_validas, key="destino_especial")
                
                edited_df_solicitud = st.data_editor(
                    df_solicitud_actual,
                    key="editor_solicitud_traslado",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Uds a Enviar": st.column_config.NumberColumn(min_value=0, step=1, required=True),
                        "Costo_Promedio_UND": st.column_config.NumberColumn(format="$%.2f", required=True),
                        "Peso Individual (kg)": st.column_config.NumberColumn(format="%.2f kg", required=True),
                        "Borrar": st.column_config.CheckboxColumn(required=True),
                        "Valor del Traslado": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                        "Peso Total (kg)": st.column_config.NumberColumn(format="%.2f kg", disabled=True),
                    },
                    disabled=['id', 'SKU', 'Descripcion', 'Tienda Origen']
                )
                
                # Emails y contactos
                tiendas_origen_especial = edited_df_solicitud['Tienda Origen'].unique().tolist()
                emails_origenes_especial = [CONTACTOS_TIENDAS.get(o, {}).get('email', '') for o in tiendas_origen_especial]
                email_destino_especial_list = [CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('email', '')]
                emails_predefinidos_especial = list(set(filter(None, emails_origenes_especial + email_destino_especial_list)))
                email_dest_especial = st.text_input("📧 Correo(s) de destinatario(s) (separar con coma):", value=", ".join(emails_predefinidos_especial), key="email_traslado_especial")
                
                nombre_contacto_especial = st.text_input("Nombre contacto destino", value=CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('nombre', ''), key="nombre_especial")
                celular_contacto_especial = st.text_input("Celular destino", value=CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('celular', ''), key="celular_especial")

                submit_col, clear_col = st.columns([2, 1])
                submitted_special = submit_col.form_submit_button("✅ Enviar y Registrar Solicitud Especial", use_container_width=True, type="primary")
                cleared_special = clear_col.form_submit_button("🗑️ Limpiar Solicitud", use_container_width=True)
                
                if submitted_special:
                    st.session_state.solicitud_traslado_especial = edited_df_solicitud.to_dict('records')
                    df_solicitud_final = edited_df_solicitud[edited_df_solicitud['Borrar'] == False].copy()

                    if df_solicitud_final.empty:
                        st.warning("La solicitud está vacía. No hay nada que registrar.")
                    else:
                        with st.spinner("Procesando..."):
                            exito, msg, df_reg_gsheets = registrar_ordenes_en_sheets(client, df_solicitud_final, "Traslado Especial", tienda_destino=tienda_destino_especial)
                            if exito:
                                st.success(f"✅ Solicitud especial registrada. {msg}")
                                st.session_state.notificaciones_pendientes = []
                                id_grupo_reg = df_reg_gsheets['ID_Grupo'].iloc[0]
                                excel_bytes_especial = generar_excel_dinamico(df_solicitud_final, "Traslado_Especial", "Traslado Especial")
                                asunto = f"Nueva Solicitud de Traslado Especial - {id_grupo_reg}"
                                cuerpo = f"Se ha generado una nueva solicitud de traslado especial (ID: {id_grupo_reg}) a la tienda {tienda_destino_especial}. Ver detalles en adjunto."
                                adjuntos = [{'datos': excel_bytes_especial, 'nombre_archivo': f"Traslado_Especial_{id_grupo_reg}.xlsx"}]
                                destinatarios = [e.strip() for e in email_dest_especial.split(',') if e.strip()]
                                if destinatarios:
                                    enviado, msg_envio = enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo, adjuntos)
                                    if enviado: st.success(msg_envio)
                                    else: st.error(msg_envio)
                                
                                if celular_contacto_especial:
                                    df_solicitud_final['Peso Total (kg)'] = pd.to_numeric(df_solicitud_final['Uds a Enviar'], errors='coerce') * pd.to_numeric(df_solicitud_final['Peso Individual (kg)'], errors='coerce')
                                    peso_total_solicitud = df_solicitud_final['Peso Total (kg)'].sum()
                                    mensaje_wpp = f"Hola {nombre_contacto_especial or tienda_destino_especial}, se ha generado una solicitud especial de traslado a su tienda (Grupo ID: {id_grupo_reg}). El peso total de la carga es de *{peso_total_solicitud:,.2f} kg*. ¡Gracias!"
                                    st.session_state.notificaciones_pendientes.append({
                                        "label": f"📲 Notificar a {tienda_destino_especial}", "url": generar_link_whatsapp(celular_contacto_especial, mensaje_wpp), "key": "wpp_traslado_esp"
                                    })
                                st.session_state.solicitud_traslado_especial = []
                                st.rerun()
                            else:
                                st.error(f"❌ Error al registrar: {msg}")

                if cleared_special:
                    st.session_state.solicitud_traslado_especial = []
                    st.rerun()
    # --- FIN BLOQUE MODIFICADO ---


# --- PESTAÑA 3: PLAN DE COMPRAS ---
if active_tab == tab_titles[2]:
    st.header("🛒 Plan de Compras")
    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras_base = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        st.markdown("##### Filtros Avanzados de Compras")
        f_c1, f_c2, f_c3 = st.columns(3)

        tiendas_con_sugerencia = ["Todas"] + sorted(df_plan_compras_base['Almacen_Nombre'].unique().tolist())
        filtro_tienda_compra = f_c1.selectbox("Filtrar por Tienda:", tiendas_con_sugerencia, key="filtro_tienda_compra")

        df_plan_compras_base['Proveedor'] = df_plan_compras_base['Proveedor'].astype(str).str.upper()
        proveedores_disponibles = ["Todos"] + sorted([p for p in df_plan_compras_base['Proveedor'].unique() if p and p != 'NAN'])
        selected_proveedor = f_c2.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores")
        
        # --- INICIO DE MODIFICACIÓN: FILTRO DE MARCA A MULTISELECT ---
        marcas_con_sugerencia = sorted([m for m in df_plan_compras_base['Marca_Nombre'].unique() if m and pd.notna(m)])
        filtro_marca_compra = f_c3.multiselect("Filtrar por Marca(s):", marcas_con_sugerencia, default=marcas_con_sugerencia, key="filtro_marca_compra_multi")
        # --- FIN DE MODIFICACIÓN ---
        
        current_filters = f"{filtro_tienda_compra}-{selected_proveedor}-{filtro_marca_compra}"
        if st.session_state.last_filters_compras != current_filters:
            df_temp = df_plan_compras_base.copy()
            if filtro_tienda_compra != "Todas":
                df_temp = df_temp[df_temp['Almacen_Nombre'] == filtro_tienda_compra]
            if selected_proveedor != 'Todos':
                df_temp = df_temp[df_temp['Proveedor'] == selected_proveedor]
            
            # --- INICIO DE MODIFICACIÓN: LÓGICA DE FILTRADO PARA MULTISELECT ---
            if filtro_marca_compra:
                df_temp = df_temp[df_temp['Marca_Nombre'].isin(filtro_marca_compra)]
            # --- FIN DE MODIFICACIÓN ---
            
            df_a_mostrar = df_temp.copy()
            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].apply(np.ceil).astype(int)
            df_a_mostrar['Seleccionar'] = False 
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            st.session_state.df_compras_editor = df_a_mostrar_final.copy()
            st.session_state.last_filters_compras = current_filters
            # No rerun here

        if st.session_state.df_compras_editor.empty:
            st.info("No hay sugerencias de compra con los filtros actuales.")
        else:
            with st.form(key="compras_sugerencia_form"):
                st.markdown("Marque los artículos y ajuste las cantidades. **Haga clic en 'Confirmar Cambios' para procesar.**")
                
                cols = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock', 'Stock_En_Transito', 'Uds a Comprar', 'Costo_Promedio_UND', 'Peso_Articulo']
                cols_existentes = [c for c in cols if c in st.session_state.df_compras_editor.columns]

                edited_df = st.data_editor(st.session_state.df_compras_editor[cols_existentes], hide_index=True, use_container_width=True,
                    column_config={
                        "Uds a Comprar": st.column_config.NumberColumn(min_value=0), 
                        "Seleccionar": st.column_config.CheckboxColumn(required=True),
                        "Peso_Articulo": st.column_config.NumberColumn(label="Peso Unit. (kg)", format="%.2f kg"),
                        "Stock": st.column_config.NumberColumn(label="Stock Actual", format="%d")
                        },
                    disabled=[c for c in cols_existentes if c not in ['Seleccionar', 'Uds a Comprar']], key="editor_principal")
                
                form_c1, form_c2, form_c3 = st.columns([1,1.2,4])
                select_all = form_c1.form_submit_button("Seleccionar Todos")
                deselect_all = form_c2.form_submit_button("Deseleccionar Todos")
                confirm_changes = form_c3.form_submit_button("⚙️ Confirmar Cambios en la Selección", type="primary")

                if select_all:
                    edited_df['Seleccionar'] = True
                    st.session_state.df_compras_editor = edited_df.copy()
                    st.rerun()
                if deselect_all:
                    edited_df['Seleccionar'] = False
                    st.session_state.df_compras_editor = edited_df.copy()
                    st.rerun()
                
                if confirm_changes:
                    st.session_state.df_compras_editor = edited_df
                    st.success("Cambios confirmados. Proceda a generar las órdenes a continuación.")

            df_seleccionados = st.session_state.df_compras_editor[
                (st.session_state.df_compras_editor['Seleccionar']) & 
                (st.session_state.df_compras_editor['Uds a Comprar'] > 0)
            ].copy()

            if not df_seleccionados.empty:
                st.markdown("---")
                st.subheader("🔬 Análisis de Stock Global para SKUs Seleccionados")
                selected_skus = df_seleccionados['SKU'].unique()
                
                df_stock_global = df_maestro[df_maestro['SKU'].isin(selected_skus)].copy()
                
                df_display_stock = df_stock_global[['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Stock_En_Transito', 'Estado_Inventario']]
                
                st.dataframe(
                    df_display_stock,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Almacen_Nombre": "Tienda",
                        "Stock": st.column_config.NumberColumn(format="%d"),
                        "Stock_En_Transito": st.column_config.NumberColumn(format="%d")
                    }
                )

            if not df_seleccionados.empty:
                df_seleccionados['Uds a Comprar'] = pd.to_numeric(df_seleccionados['Uds a Comprar'], errors='coerce').fillna(0)
                df_seleccionados['Costo_Promedio_UND'] = pd.to_numeric(df_seleccionados['Costo_Promedio_UND'], errors='coerce').fillna(0)
                df_seleccionados['Peso_Articulo'] = pd.to_numeric(df_seleccionados['Peso_Articulo'], errors='coerce').fillna(0)
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']
                df_seleccionados['Peso Total (kg)'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Peso_Articulo']
                
                valor_total = df_seleccionados['Valor de la Compra'].sum()
                peso_total_compra = df_seleccionados['Peso Total (kg)'].sum()
                st.markdown("---")

                col1, col2 = st.columns([3, 1])
                col1.subheader(f"Resumen de la Selección: ${valor_total:,.2f} | Peso Total: {peso_total_compra:,.2f} kg")
                
                excel_bytes = generar_excel_dinamico(df_seleccionados, "Seleccion_de_Compra", "Compra Sugerencia")
                col2.download_button("📥 Descargar Selección en Excel", data=excel_bytes, file_name="seleccion_compra.xlsx", use_container_width=True)

                st.markdown("---")
                st.subheader("Generar Órdenes de Compra por Proveedor/Tienda")
                grouped = df_seleccionados.groupby(['Proveedor', 'Tienda'])

                for (proveedor, tienda), df_grupo in grouped:
                    with st.container(border=True):
                        st.markdown(f"#### Orden para **{proveedor}** ➡️ Destino: **{tienda}**")
                        st.dataframe(df_grupo[['SKU', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND', 'Valor de la Compra', 'Peso Total (kg)']], use_container_width=True)

                        with st.form(key=f"form_{proveedor.replace(' ', '_')}_{tienda.replace(' ', '_')}"):
                            contacto_info = CONTACTOS_PROVEEDOR.get(proveedor, {})
                            contacto_tienda = CONTACTOS_TIENDAS.get(tienda, {})
                            
                            email_proveedor = contacto_info.get('email', '')
                            email_tienda = contacto_tienda.get('email', '')
                            emails_predefinidos_compra = list(set(filter(None, [email_proveedor, email_tienda])))

                            email_dest = st.text_input("📧 Correos del destinatario (separar con coma o punto y coma):", value=", ".join(emails_predefinidos_compra), key=f"email_{proveedor}_{tienda}")
                            nombre_contacto = st.text_input("Nombre contacto:", value=contacto_info.get('nombre', ''), key=f"nombre_{proveedor}_{tienda}")
                            celular_proveedor = st.text_input("Celular contacto:", value=contacto_info.get('celular', ''), key=f"celular_{proveedor}_{tienda}")

                            submitted = st.form_submit_button("✅ Enviar y Registrar Esta Orden", type="primary", use_container_width=True)
                            if submitted:
                                if not email_dest: st.warning("Se necesita un correo para enviar la orden.")
                                else:
                                    with st.spinner(f"Procesando orden para {proveedor}..."):
                                        df_para_notificar_compra = df_grupo.copy()
                                        exito, msg, df_reg = registrar_ordenes_en_sheets(client, df_grupo, "Compra Sugerencia")
                                        if exito:
                                            st.success(f"¡Orden registrada! {msg}")
                                            orden_id_grupo = df_reg['ID_Grupo'].iloc[0] if not df_reg.empty else f"OC-{datetime.now().strftime('%f')}"
                                            direccion_entrega = DIRECCIONES_TIENDAS.get(tienda, "N/A")
                                            pdf_bytes = generar_pdf_orden_compra(df_para_notificar_compra, proveedor, tienda, direccion_entrega, nombre_contacto, orden_id_grupo)
                                            excel_bytes_oc = generar_excel_dinamico(df_para_notificar_compra, f"Compra_{proveedor}", "Compra Sugerencia")

                                            asunto = f"Nueva Orden de Compra {orden_id_grupo} de Ferreinox SAS BIC - {proveedor}"
                                            cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra N° {orden_id_grupo}</b> en formatos PDF y Excel.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                            adjuntos = [ {'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_grupo}.pdf"}, {'datos': excel_bytes_oc, 'nombre_archivo': f"Detalle_OC_{orden_id_grupo}.xlsx"} ]
                                            destinatarios_finales = [e.strip() for e in email_dest.replace(';', ',').split(',') if e.strip()]
                                            enviado, msg_envio = enviar_correo_con_adjuntos(destinatarios_finales, asunto, cuerpo_html, adjuntos)
                                            if enviado: st.success(msg_envio)
                                            else: st.error(msg_envio)

                                            if celular_proveedor:
                                                peso_total_orden = pd.to_numeric(df_para_notificar_compra['Peso Total (kg)'], errors='coerce').sum()
                                                msg_wpp = f"Hola {nombre_contacto}, te acabamos de enviar la Orden de Compra N° {orden_id_grupo} al correo. Peso total: {peso_total_orden:,.2f} kg. Quedamos atentos. ¡Gracias!"
                                                st.session_state.notificaciones_pendientes.append({
                                                    "label": f"📲 Notificar a {proveedor}", "url": generar_link_whatsapp(celular_proveedor, msg_wpp), "key": f"wpp_compra_{proveedor}_{tienda}"
                                                })
                                            st.rerun()
                                        else:
                                            st.error(f"Error al registrar: {msg}")

    # --- INICIO BLOQUE MODIFICADO Y MEJORADO: COMPRAS ESPECIALES ---
    with st.expander("🆕 **Compras Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        st.markdown("##### 1. Seleccione las tiendas para consolidar stock")
        
        # Guardar la selección de la tienda en session_state para persistencia
        if 'tiendas_compra_especial_seleccionadas' not in st.session_state:
            st.session_state.tiendas_compra_especial_seleccionadas = []

        tiendas_seleccionadas = st.multiselect(
            "Seleccione una o más tiendas para consolidar el stock y buscar productos:",
            options=almacenes_disponibles,
            default=st.session_state.tiendas_compra_especial_seleccionadas,
            key="ms_tiendas_compra_especial"
        )
        
        # Si la selección cambia, actualizar el estado de sesión y limpiar la lista de items.
        if set(tiendas_seleccionadas) != set(st.session_state.tiendas_compra_especial_seleccionadas):
            st.session_state.tiendas_compra_especial_seleccionadas = tiendas_seleccionadas
            st.session_state.compra_especial_items = [] # Resetear la lista si la tienda cambia
            st.rerun()

        if st.session_state.tiendas_compra_especial_seleccionadas:
            st.markdown(f"##### 2. Buscar productos para añadir (Stock consolidado de: **{', '.join(st.session_state.tiendas_compra_especial_seleccionadas)}**)")
            
            search_term_compra_esp = st.text_input("Buscar por SKU o Descripción:", key="search_compra_especial")

            if search_term_compra_esp:
                df_maestro_tiendas = df_maestro[df_maestro['Almacen_Nombre'].isin(st.session_state.tiendas_compra_especial_seleccionadas)]
                
                # Consolidar stock
                df_consolidado = df_maestro_tiendas.groupby(['SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND', 'Peso_Articulo']).agg(
                    Stock=('Stock', 'sum'),
                    Stock_En_Transito=('Stock_En_Transito', 'sum'),
                    Tiendas_Consolidadas=('Almacen_Nombre', lambda x: ', '.join(x))
                ).reset_index()

                mask_compra_esp = (
                    df_consolidado['SKU'].str.contains(search_term_compra_esp, case=False, na=False) | 
                    df_consolidado['Descripcion'].str.contains(search_term_compra_esp, case=False, na=False)
                )
                df_resultados_busqueda = df_consolidado[mask_compra_esp].copy()

                if not df_resultados_busqueda.empty:
                    df_resultados_busqueda['Uds a Comprar'] = 1
                    df_resultados_busqueda['Seleccionar'] = False
                    
                    cols_para_mostrar = ['Seleccionar', 'SKU', 'Descripcion', 'Stock', 'Stock_En_Transito', 'Tiendas_Consolidadas', 'Proveedor', 'Costo_Promedio_UND', 'Peso_Articulo', 'Uds a Comprar']
                    
                    with st.form("form_add_special_items"):
                        c1, c2, c3 = st.columns([1,1,4])
                        select_all_sp = c1.form_submit_button("Seleccionar Todos")
                        deselect_all_sp = c2.form_submit_button("Deseleccionar Todos")

                        edited_df_busqueda = st.data_editor(
                            df_resultados_busqueda[cols_para_mostrar], 
                            key="editor_busqueda_compra_esp", 
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Uds a Comprar": st.column_config.NumberColumn(min_value=1),
                                "Seleccionar": st.column_config.CheckboxColumn(required=True),
                                "Stock": st.column_config.NumberColumn(label="Stock Consolidado")
                            },
                            disabled=['SKU', 'Descripcion', 'Stock', 'Stock_En_Transito', 'Tiendas_Consolidadas', 'Proveedor', 'Costo_Promedio_UND', 'Peso_Articulo']
                        )

                        if select_all_sp:
                            edited_df_busqueda['Seleccionar'] = True
                            st.session_state.df_resultados_busqueda_compra_esp = edited_df_busqueda.copy() # Save state
                            st.rerun()
                        if deselect_all_sp:
                            edited_df_busqueda['Seleccionar'] = False
                            st.session_state.df_resultados_busqueda_compra_esp = edited_df_busqueda.copy() # Save state
                            st.rerun()
                        
                        if st.form_submit_button("➕ Añadir Seleccionados a la Lista de Compra"):
                            items_a_anadir = edited_df_busqueda[edited_df_busqueda['Seleccionar']].to_dict('records')
                            
                            for row in items_a_anadir:
                                if not any(item['SKU'] == row['SKU'] for item in st.session_state.compra_especial_items):
                                    new_item = row.copy()
                                    new_item['Borrar'] = False
                                    st.session_state.compra_especial_items.append(new_item)
                            
                            st.success(f"{len(items_a_anadir)} producto(s) añadidos a la lista.")
                            # No st.rerun() here to avoid jumping. The page will update naturally.

                else:
                    st.warning("No se encontraron productos para las tiendas seleccionadas con ese criterio de búsqueda.")

            if st.session_state.compra_especial_items:
                st.markdown("---")
                st.markdown("##### 3. Revisar y generar la Orden de Compra Especial")

                with st.form("form_generate_special_order"):
                    df_compra_especial_actual = pd.DataFrame(st.session_state.compra_especial_items)
                    
                    edited_df_final_compra_esp = st.data_editor(
                        df_compra_especial_actual,
                        key="editor_lista_final_compra_esp",
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            'Uds a Comprar': st.column_config.NumberColumn(min_value=0, step=1, required=True),
                            'Costo_Promedio_UND': st.column_config.NumberColumn(format="$%.2f", required=True),
                            'Peso_Articulo': st.column_config.NumberColumn(label="Peso Unit. (kg)", format="%.2f kg", required=True),
                            'Borrar': st.column_config.CheckboxColumn(required=True)
                        },
                        disabled=['SKU', 'Descripcion', 'Proveedor', 'Stock', 'Stock_En_Transito', 'Seleccionar', 'Tiendas_Consolidadas']
                    )

                    st.markdown("---")
                    st.markdown("##### 4. Información del Proveedor y Destino Final del Pedido")
                    
                    # El usuario debe elegir un destino final para la entrega consolidada
                    tienda_destino_final = st.selectbox(
                        "Seleccione la TIENDA DE DESTINO FINAL a la que se debe enviar este pedido:",
                        options=[""] + almacenes_disponibles,
                        key="sb_tienda_destino_final_especial"
                    )

                    proveedor_especial = st.text_input("Nombre del Proveedor:", key="proveedor_especial_nombre")
                    
                    contacto_info_esp = CONTACTOS_PROVEEDOR.get(proveedor_especial.upper(), {})
                    
                    email_dest_esp = st.text_input("📧 Correo del proveedor:", value=contacto_info_esp.get('email', ''), key="email_compra_esp")
                    nombre_contacto_esp = st.text_input("Nombre contacto proveedor:", value=contacto_info_esp.get('nombre', ''), key="nombre_compra_esp")
                    celular_proveedor_esp = st.text_input("Celular proveedor:", value=contacto_info_esp.get('celular', ''), key="celular_compra_esp")

                    submit_col, clear_col = st.columns([2, 1])
                    submitted_special_compra = submit_col.form_submit_button("✅ Enviar y Registrar Compra Especial", use_container_width=True, type="primary")
                    cleared_special_compra = clear_col.form_submit_button("🗑️ Limpiar Toda la Lista", use_container_width=True)

                    if submitted_special_compra:
                        st.session_state.compra_especial_items = edited_df_final_compra_esp.to_dict('records')
                        df_compra_especial_final = edited_df_final_compra_esp[edited_df_final_compra_esp['Borrar'] == False].copy()

                        if proveedor_especial and not df_compra_especial_final.empty and tienda_destino_final:
                            with st.spinner("Procesando compra especial..."):
                                exito, msg, df_reg = registrar_ordenes_en_sheets(
                                    client, df_compra_especial_final, "Compra Especial", 
                                    proveedor_nombre=proveedor_especial, 
                                    tienda_destino=tienda_destino_final
                                )
                                if exito:
                                    st.success(f"✅ Compra especial registrada. {msg}")
                                    st.session_state.notificaciones_pendientes = []
                                    orden_id_grupo = df_reg['ID_Grupo'].iloc[0]
                                    direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_destino_final, "N/A")
                                    
                                    pdf_bytes = generar_pdf_orden_compra(df_compra_especial_final, proveedor_especial, tienda_destino_final, direccion_entrega, nombre_contacto_esp, orden_id_grupo)
                                    excel_bytes_oc_esp = generar_excel_dinamico(df_compra_especial_final, f"Compra_Especial_{proveedor_especial}", "Compra Especial")
                                    
                                    asunto = f"Nueva Orden de Compra Especial {orden_id_grupo} de Ferreinox SAS BIC - {proveedor_especial}"
                                    cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor_especial},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra especial N° {orden_id_grupo}</b>.</p><p><b>Sede de Entrega:</b> {tienda_destino_final}<br><b>Dirección:</b> {direccion_entrega}</p><p>Agradecemos su gestión.</p><p>Cordialmente,<br><b>Departamento de Compras</b></p></body></html>"
                                    
                                    adjuntos = [ {'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_grupo}.pdf"}, {'datos': excel_bytes_oc_esp, 'nombre_archivo': f"Detalle_OC_Especial_{orden_id_grupo}.xlsx"} ]
                                    
                                    if email_dest_esp:
                                        destinatarios_finales = [e.strip() for e in email_dest_esp.replace(';', ',').split(',') if e.strip()]
                                        enviado, msg_envio = enviar_correo_con_adjuntos(destinatarios_finales, asunto, cuerpo_html, adjuntos)
                                        if enviado: st.success(msg_envio)
                                        else: st.error(msg_envio)

                                    if celular_proveedor_esp:
                                        df_compra_especial_final['Peso Total (kg)'] = pd.to_numeric(df_compra_especial_final['Uds a Comprar'], errors='coerce') * pd.to_numeric(df_compra_especial_final['Peso_Articulo'], errors='coerce')
                                        peso_total_orden_esp = df_compra_especial_final['Peso Total (kg)'].sum()
                                        msg_wpp = f"Hola {nombre_contacto_esp}, te acabamos de enviar la Orden de Compra Especial N° {orden_id_grupo} al correo. Peso total: {peso_total_orden_esp:,.2f} kg. ¡Gracias!"
                                        st.session_state.notificaciones_pendientes.append({ "label": f"📲 Notificar a {proveedor_especial}", "url": generar_link_whatsapp(celular_proveedor_esp, msg_wpp), "key": f"wpp_compra_esp_{proveedor_especial}"})
                                    
                                    st.session_state.compra_especial_items = []
                                    st.session_state.tiendas_compra_especial_seleccionadas = []
                                    st.rerun()
                                else:
                                    st.error(f"❌ Error al registrar: {msg}")
                        else:
                            st.warning("Debe especificar un proveedor, un destino final y tener al menos un artículo en la lista.")
                        
                    if cleared_special_compra:
                        st.session_state.compra_especial_items = []
                        st.rerun()
    # --- FIN BLOQUE MODIFICADO ---


# --- INICIO MODIFICACIÓN COMPLETA: PESTAÑA DE SEGUIMIENTO ---
if active_tab == tab_titles[3]:
    st.subheader("✅ Seguimiento y Gestión de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        df_ordenes_vista_original['Proveedor'] = df_ordenes_vista_original['Proveedor'].astype(str).fillna('N/A')
        
        # Convertir a numérico las columnas de costo y peso
        for col in ['Costo_Total', 'Cantidad_Solicitada', 'Costo_Unitario', 'Peso_Unitario_kg', 'Peso_Total_kg']:
            if col in df_ordenes_vista_original.columns:
                df_ordenes_vista_original[col] = pd.to_numeric(df_ordenes_vista_original[col], errors='coerce').fillna(0)
        
        # Recalcular explícitamente el peso total para asegurar consistencia
        if 'Cantidad_Solicitada' in df_ordenes_vista_original.columns and 'Peso_Unitario_kg' in df_ordenes_vista_original.columns:
            df_ordenes_vista_original['Peso_Total_kg'] = df_ordenes_vista_original['Cantidad_Solicitada'] * df_ordenes_vista_original['Peso_Unitario_kg']


        # --- 1. FILTROS Y VISTA RESUMIDA ---
        st.markdown("##### 1. Filtrar y Visualizar Grupos de Órdenes")
        track_c1, track_c2, track_c3 = st.columns(3)
        
        estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
        default_estado_idx = estados_disponibles.index('Pendiente') if 'Pendiente' in estados_disponibles else 0
        filtro_estado = track_c1.selectbox("Filtrar por Estado:", estados_disponibles, index=default_estado_idx, key="filtro_estado_seguimiento")

        proveedores_ordenes = ["Todos"] + sorted(df_ordenes_vista_original['Proveedor'].unique().tolist())
        filtro_proveedor_orden = track_c2.selectbox("Filtrar por Proveedor/Origen:", proveedores_ordenes, key="filtro_proveedor_seguimiento")

        tiendas_ordenes = ["Todos"] + sorted(df_ordenes_vista_original['Tienda_Destino'].unique().tolist())
        filtro_tienda_orden = track_c3.selectbox("Filtrar por Tienda Destino:", tiendas_ordenes, key="filtro_tienda_orden")

        # Aplicar filtros
        df_ordenes_filtradas = df_ordenes_vista_original.copy()
        if filtro_estado != "Todos": df_ordenes_filtradas = df_ordenes_filtradas[df_ordenes_filtradas['Estado'] == filtro_estado]
        if filtro_proveedor_orden != "Todos": df_ordenes_filtradas = df_ordenes_filtradas[df_ordenes_filtradas['Proveedor'] == filtro_proveedor_orden]
        if filtro_tienda_orden != "Todos": df_ordenes_filtradas = df_ordenes_filtradas[df_ordenes_filtradas['Tienda_Destino'] == filtro_tienda_orden]

        # Vista resumida ahora incluye Peso Total
        if not df_ordenes_filtradas.empty:
            df_summary = df_ordenes_filtradas.groupby('ID_Grupo').agg(
                Fecha_Emision=('Fecha_Emision', 'first'),
                Proveedor=('Proveedor', 'first'),
                Tienda_Destino=('Tienda_Destino', 'first'),
                Estado=('Estado', 'first'),
                Items=('SKU', 'nunique'),
                Valor_Total=('Costo_Total', 'sum'),
                Peso_Total_kg=('Peso_Total_kg', 'sum') # <-- NUEVA AGREGACIÓN
            ).reset_index().sort_values(by="Fecha_Emision", ascending=False)
            
            st.dataframe(df_summary, use_container_width=True, hide_index=True,
                         column_config={
                             "Valor_Total": st.column_config.NumberColumn(format="$ {:,.0f}"),
                             "Peso_Total_kg": st.column_config.NumberColumn(label="Peso Total", format="%.2f kg") # <-- NUEVA COLUMNA EN VISTA
                         })
        else:
            st.info("No hay órdenes que coincidan con los filtros seleccionados.")
            df_summary = pd.DataFrame() 

        st.markdown("---")
        
        # --- 2. GESTIÓN DE ORDEN ESPECÍFICA ---
        st.markdown("##### 2. Gestionar una Orden Específica")
        ordenes_id_unicas = sorted(df_summary['ID_Grupo'].unique().tolist(), reverse=True) if not df_summary.empty else []
        id_grupo_elegido = st.selectbox("Seleccione el GRUPO de la Orden para gestionar:", [""] + ordenes_id_unicas, key="select_grupo_id_to_edit")

        if id_grupo_elegido:
            st.markdown(f"### Gestionando Grupo de Orden: {id_grupo_elegido}")

            # --- ACCIÓN RÁPIDA PARA CAMBIAR ESTADO ---
            with st.container(border=True):
                st.markdown("#### Acción Rápida: Cambiar Estado del Grupo Completo")
                
                current_status = df_ordenes_vista_original[df_ordenes_vista_original['ID_Grupo'] == id_grupo_elegido]['Estado'].iloc[0]
                status_options = ['Pendiente', 'En Tránsito', 'Recibido', 'Cancelado']
                try:
                    current_status_index = status_options.index(current_status)
                except ValueError:
                    current_status_index = 0

                with st.form("status_change_form"):
                    nuevo_estado = st.selectbox(
                        "Seleccione el nuevo estado para TODOS los ítems de esta orden:",
                        options=status_options,
                        index=current_status_index,
                        key="sb_nuevo_estado"
                    )
                    submitted_status_change = st.form_submit_button("Aplicar Cambio de Estado al Grupo", type="primary", use_container_width=True)

                    if submitted_status_change:
                        if nuevo_estado == current_status:
                            st.warning("El estado seleccionado es el mismo que el actual. No se realizaron cambios.")
                        else:
                            with st.spinner(f"Actualizando estado del grupo '{id_grupo_elegido}' a '{nuevo_estado}'..."):
                                df_historico_modificado = df_ordenes_historico.copy()
                                df_historico_modificado.loc[df_historico_modificado['ID_Grupo'] == id_grupo_elegido, 'Estado'] = nuevo_estado
                                
                                exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                                
                                if exito:
                                    st.success(f"✅ ¡Éxito! El estado del grupo de orden '{id_grupo_elegido}' ha sido cambiado a '{nuevo_estado}'. La página se recargará.")
                                    st.cache_data.clear()
                                    st.cache_resource.clear()
                                    st.session_state.order_to_edit = None
                                    st.rerun()
                                else:
                                    st.error(f"❌ Error al actualizar la hoja de Google: {msg}")

            # --- MODIFICACIÓN DETALLADA (EN EXPANDER) ---
            with st.expander("Modificación Detallada: Editar, Añadir o Eliminar Ítems", expanded=True):
                if st.session_state.order_to_edit != id_grupo_elegido:
                    df_orden_completa = df_ordenes_vista_original[df_ordenes_vista_original['ID_Grupo'] == id_grupo_elegido].copy()
                    df_orden_completa['Borrar'] = False
                    st.session_state.orden_a_editar_df = df_orden_completa
                    st.session_state.order_to_edit = id_grupo_elegido
                    st.session_state.items_to_add_to_order = pd.DataFrame()

                # Editor para items existentes
                with st.container(border=True):
                    st.markdown("**Ítems Actuales en la Orden:** (Puede editar cantidades o marcar para borrar)")
                    edited_orden_df = st.data_editor(
                        st.session_state.orden_a_editar_df,
                        key="editor_modificar_orden", use_container_width=True, hide_index=True,
                        column_config={
                            "Cantidad_Solicitada": st.column_config.NumberColumn(label="Cantidad", min_value=0, step=1, format="%d"),
                            "Costo_Unitario": st.column_config.NumberColumn(label="Costo Unit.", format="$%.2f"),
                            "Peso_Unitario_kg": st.column_config.NumberColumn(label="Peso Unit.", format="%.2f kg"),
                            "Borrar": st.column_config.CheckboxColumn(required=True)
                        },
                        disabled=[c for c in st.session_state.orden_a_editar_df.columns if c not in ['Cantidad_Solicitada', 'Costo_Unitario', 'Peso_Unitario_kg', 'Borrar']]
                    )
                    st.session_state.orden_a_editar_df = edited_orden_df

                # Panel para añadir nuevos items
                with st.container(border=True):
                    st.markdown("**Añadir Nuevos Ítems a la Orden:**")
                    search_term_add = st.text_input("Buscar producto por SKU o Descripción para añadir:", key="search_add_item_seguimiento")
                    
                    if search_term_add:
                        mask_add = (df_maestro['SKU'].str.contains(search_term_add, case=False, na=False) | 
                                    df_maestro['Descripcion'].str.contains(search_term_add, case=False, na=False))
                        df_resultados_add = df_maestro[mask_add].drop_duplicates(subset=['SKU']).copy()

                        if not df_resultados_add.empty:
                            df_resultados_add['Cantidad_Solicitada'] = 1
                            df_resultados_add['Seleccionar'] = False
                            cols_add = ['Seleccionar', 'SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND', 'Peso_Articulo', 'Cantidad_Solicitada']
                            
                            df_add_editor = st.data_editor(
                                df_resultados_add[cols_add], key="editor_add_seguimiento", use_container_width=True, hide_index=True,
                                column_config={
                                    "Cantidad_Solicitada": st.column_config.NumberColumn(min_value=1), 
                                    "Seleccionar": st.column_config.CheckboxColumn(required=True)
                                },
                                disabled=['SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND', 'Peso_Articulo']
                            )
                            
                            if st.button("➕ Añadir Ítems Seleccionados a la Orden"):
                                items_a_anadir = df_add_editor[df_add_editor['Seleccionar']].copy()
                                if not items_a_anadir.empty:
                                    current_order = st.session_state.orden_a_editar_df
                                    new_items_list = []
                                    max_suffix = max([int(i.split('-')[-1]) for i in current_order['ID_Orden'] if '-' in i]) if not current_order.empty and any('-' in s for s in current_order['ID_Orden']) else 0

                                    for i, row in items_a_anadir.iterrows():
                                        new_item = {
                                            'ID_Grupo': id_grupo_elegido,
                                            'ID_Orden': f"{id_grupo_elegido}-{max_suffix + i + 1}",
                                            'Fecha_Emision': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                            'Proveedor': current_order['Proveedor'].iloc[0],
                                            'SKU': row['SKU'],
                                            'Descripcion': row['Descripcion'],
                                            'Cantidad_Solicitada': row['Cantidad_Solicitada'],
                                            'Tienda_Destino': current_order['Tienda_Destino'].iloc[0],
                                            'Estado': 'Pendiente',
                                            'Costo_Unitario': row['Costo_Promedio_UND'],
                                            'Costo_Total': row['Cantidad_Solicitada'] * row['Costo_Promedio_UND'],
                                            'Peso_Unitario_kg': row['Peso_Articulo'],
                                            'Peso_Total_kg': row['Cantidad_Solicitada'] * row['Peso_Articulo'],
                                            'Borrar': False
                                        }
                                        new_items_list.append(new_item)
                                    
                                    df_new_items = pd.DataFrame(new_items_list)
                                    st.session_state.orden_a_editar_df = pd.concat([current_order, df_new_items], ignore_index=True)
                                    st.success(f"{len(df_new_items)} ítem(s) añadidos. Haga clic en 'Guardar Cambios' para finalizar.")
                                    st.rerun()

                # Botón para guardar cambios detallados
                if st.button("💾 Guardar Cambios Detallados (cantidades, ítems añadidos/borrados)", use_container_width=True):
                    with st.spinner("Guardando cambios detallados en Google Sheets..."):
                        df_final_orden = st.session_state.orden_a_editar_df[st.session_state.orden_a_editar_df['Borrar'] == False].copy()
                        df_final_orden.drop(columns=['Borrar'], inplace=True, errors='ignore')
                        # Recalcular totales antes de guardar
                        df_final_orden['Costo_Total'] = pd.to_numeric(df_final_orden['Cantidad_Solicitada'], errors='coerce') * pd.to_numeric(df_final_orden['Costo_Unitario'], errors='coerce')
                        df_final_orden['Peso_Total_kg'] = pd.to_numeric(df_final_orden['Cantidad_Solicitada'], errors='coerce') * pd.to_numeric(df_final_orden['Peso_Unitario_kg'], errors='coerce')

                        df_historico_actualizado = df_ordenes_historico[df_ordenes_historico['ID_Grupo'] != id_grupo_elegido].copy()
                        df_historico_final = pd.concat([df_historico_actualizado, df_final_orden], ignore_index=True)
                        
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_final)
                        if exito:
                            st.success(f"✅ Orden {id_grupo_elegido} actualizada correctamente. La página se recargará.")
                            st.session_state.order_to_edit = None
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Error al guardar los cambios: {msg}")
                
                # --- NOTIFICACIONES Y DESCARGA (EN EXPANDER) ---
                with st.expander("Descargar y Notificar Orden", expanded=True):
                    df_para_notificar = st.session_state.orden_a_editar_df.copy()
                    df_para_notificar = df_para_notificar[df_para_notificar['Borrar'] == False]
                    
                    # --- Botón de descarga de Excel ---
                    st.markdown("##### Descargar Orden en Formato Excel")
                    excel_bytes_seguimiento = generar_excel_dinamico(df_para_notificar, f"Orden_{id_grupo_elegido}", "Seguimiento")
                    st.download_button(
                        label=f"📥 Descargar Excel de la Orden {id_grupo_elegido}",
                        data=excel_bytes_seguimiento,
                        file_name=f"Orden_{id_grupo_elegido}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.ms-excel",
                        use_container_width=True
                    )
                    st.markdown("---")

                    with st.form(key=f"form_notify_{id_grupo_elegido}"):
                        st.markdown("##### Reenviar Notificación de la Orden")
                        st.info("Esta acción reenviará la orden con los últimos datos guardados. Asegúrese de haber guardado cualquier cambio detallado primero.")
                        
                        proveedor_orden = df_para_notificar['Proveedor'].iloc[0]
                        tienda_orden = df_para_notificar['Tienda_Destino'].iloc[0]
                        
                        is_traslado = "TRASLADO INTERNO" in proveedor_orden
                        if is_traslado:
                            tienda_origen_nombre = proveedor_orden.replace("TRASLADO INTERNO: ", "").strip()
                            # Para traslados, el contacto es la tienda de origen y el celular es de la tienda de destino
                            contacto_info_origen = CONTACTOS_TIENDAS.get(tienda_origen_nombre, {})
                            contacto_info_destino = CONTACTOS_TIENDAS.get(tienda_orden, {})
                            email_val = f"{contacto_info_origen.get('email', '')},{contacto_info_destino.get('email', '')}"
                            nombre_val = contacto_info_origen.get('nombre', '')
                            celular_val = contacto_info_destino.get('celular', '') # Notificar al que recibe
                        else: # Es Compra
                            contacto_info = CONTACTOS_PROVEEDOR.get(proveedor_orden.upper(), {})
                            email_val = contacto_info.get('email', '')
                            nombre_val = contacto_info.get('nombre', '')
                            celular_val = contacto_info.get('celular', '')

                        email_dest = st.text_input("Email(s) para notificación:", value=email_val, key=f"email_notify_{id_grupo_elegido}")
                        nombre_contacto = st.text_input("Nombre de contacto para notificación:", value=nombre_val, key=f"nombre_notify_{id_grupo_elegido}")
                        celular_contacto = st.text_input("Celular para notificación WhatsApp:", value=celular_val, key=f"celular_notify_{id_grupo_elegido}")

                        submitted_notify = st.form_submit_button("📩 Reenviar Notificaciones", use_container_width=True)

                        if submitted_notify:
                            if df_para_notificar.empty:
                                st.error("La orden está vacía. No se puede notificar.")
                            else:
                                with st.spinner("Enviando notificaciones..."):
                                    excel_bytes_notif = generar_excel_dinamico(df_para_notificar, f"Orden_ACT_{id_grupo_elegido}", "Seguimiento")
                                    adjuntos = [{'datos': excel_bytes_notif, 'nombre_archivo': f"Detalle_Orden_ACT_{id_grupo_elegido}.xlsx"}]
                                    
                                    if is_traslado:
                                        asunto = f"**RECORDATORIO/ACTUALIZACIÓN TRASLADO** {id_grupo_elegido}"
                                        cuerpo_html = f"Hola equipo, se reenvía información sobre el plan de traslado N° {id_grupo_elegido}. Por favor, ver detalles en el archivo adjunto. Gracias."
                                        peso_total_notif = pd.to_numeric(df_para_notificar['Peso_Total_kg'], errors='coerce').sum()
                                        msg_wpp = f"Hola, te reenviamos la información del traslado N° {id_grupo_elegido}. Peso total: {peso_total_notif:,.2f} kg."
                                        notif_label = f"📲 Notificar a {tienda_orden} (Destino)"
                                    else: # Es Compra
                                        direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_orden, "N/A")
                                        pdf_bytes = generar_pdf_orden_compra(df_para_notificar, proveedor_orden, tienda_orden, direccion_entrega, nombre_contacto, id_grupo_elegido)
                                        adjuntos.insert(0, {'datos': pdf_bytes, 'nombre_archivo': f"OC_ACT_{id_grupo_elegido}.pdf"}) # Añadir PDF para compras
                                        asunto = f"**RECORDATORIO/ACTUALIZACIÓN ORDEN DE COMPRA** {id_grupo_elegido}"
                                        cuerpo_html = f"Estimados Sres. {proveedor_orden}, adjunto reenviamos la versión actualizada de la orden de compra N° {id_grupo_elegido}. Agradecemos su gestión."
                                        peso_total_notif = pd.to_numeric(df_para_notificar['Peso_Total_kg'], errors='coerce').sum()
                                        msg_wpp = f"Hola {nombre_contacto}, te reenviamos la OC ACTUALIZADA N° {id_grupo_elegido}. Peso total: {peso_total_notif:,.2f} kg."
                                        notif_label = f"📲 Notificar a {proveedor_orden}"
                                    
                                    if email_dest:
                                        destinatarios = [e.strip() for e in email_dest.replace(';',',').split(',') if e.strip()]
                                        enviado, msg_envio = enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo_html, adjuntos)
                                        if enviado: st.success(f"Correo reenviado: {msg_envio}")
                                        else: st.error(f"Error al reenviar correo: {msg_envio}")
                                    
                                    if celular_contacto:
                                        st.session_state.notificaciones_pendientes.append({
                                            "label": notif_label, 
                                            "url": generar_link_whatsapp(celular_contacto, msg_wpp), 
                                            "key": f"wpp_update_{id_grupo_elegido}"
                                        })
                                    st.rerun()

# --- BLOQUE FINAL PARA MOSTRAR NOTIFICACIONES PENDIENTES ---
if st.session_state.notificaciones_pendientes:
    st.markdown("---")
    st.subheader("🔔 Notificaciones Pendientes de Envío")
    st.info("La orden ha sido registrada/actualizada. Haz clic en los botones para enviar las notificaciones por WhatsApp.")

    for notif in st.session_state.notificaciones_pendientes:
        whatsapp_button(notif["label"], notif["url"], notif["key"])

    if st.button("✅ Hecho, Limpiar Notificaciones", key="finalizar_proceso_completo", type="primary"):
        st.session_state.notificaciones_pendientes = []
        st.success("Notificaciones limpiadas. La app se recargará.")
        st.rerun()
