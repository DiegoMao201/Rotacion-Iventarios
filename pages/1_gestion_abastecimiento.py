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
st.set_page_config(page_title="Gestión de Abastecimiento v5.2", layout="wide", page_icon="⚙️")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
# Claves para gestionar el estado de la aplicación de forma persistente entre interacciones.
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
    'df_compras_editor': pd.DataFrame(), # DF persistente para el editor de compras
    'df_traslados_editor': pd.DataFrame(), # DF persistente para el editor de traslados
    'last_filters_compras': None, # Guarda el estado de los filtros de compras para saber cuándo refrescar
    'last_filters_traslados': None, # Guarda el estado de los filtros de traslados para saber cuándo refrescar
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
        # **MEJORA**: Asegurar que ID_Grupo exista para la lógica de seguimiento
        if 'ID_Orden' in df.columns and 'ID_Grupo' not in df.columns:
            df['ID_Grupo'] = df['ID_Orden'].apply(lambda x: '-'.join(str(x).split('-')[:-1]))
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
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
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
        return True, f"Nuevos registros añadidos a '{sheet_name}'.", df_to_append_ordered
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}", pd.DataFrame()

def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    """Prepara y registra un DataFrame de órdenes en la hoja 'Registro_Ordenes' con IDs de grupo."""
    if df_orden.empty or client is None: return False, "No hay datos para registrar.", pd.DataFrame()

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = df_orden.copy()

    cantidad_col = next((col for col in ['Uds a Comprar', 'Uds a Enviar', 'Cantidad_Solicitada'] if col in df_orden.columns), None)
    if not cantidad_col: return False, "No se encontró la columna de cantidad.", pd.DataFrame()

    df_registro['Cantidad_Solicitada'] = df_registro[cantidad_col]
    df_registro['Costo_Unitario'] = df_registro.get('Costo_Promedio_UND', df_registro.get('Costo_Unitario', 0))
    df_registro['Costo_Total'] = pd.to_numeric(df_registro['Cantidad_Solicitada'], errors='coerce').fillna(0) * pd.to_numeric(df_registro['Costo_Unitario'], errors='coerce').fillna(0)
    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # **MEJORA**: Generación de ID de Grupo claro y consistente
    id_grupo = ""
    if tipo_orden == "Compra Sugerencia":
        id_grupo = f"OC-{timestamp}"
        df_registro['Proveedor'] = df_registro['Proveedor']
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    elif tipo_orden == "Compra Especial":
        id_grupo = f"OC-SP-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        id_grupo = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
    elif tipo_orden == "Traslado Especial":
        id_grupo = f"TR-SP-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino

    df_registro['ID_Grupo'] = id_grupo
    # ID de Orden es ahora el ID de línea, único para cada artículo
    df_registro['ID_Orden'] = [f"{id_grupo}-{i+1}" for i in range(len(df_registro))]

    columnas_finales = ['ID_Grupo', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')

    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

# --- 2. FUNCIONES AUXILIARES Y DE UI ---
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
    df_resultado['Peso del Traslado (kg)'] = pd.to_numeric(df_resultado['Uds a Enviar'], errors='coerce').fillna(0) * pd.to_numeric(df_resultado['Peso Individual (kg)'], errors='coerce').fillna(0)
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar'], errors='coerce').fillna(0) * pd.to_numeric(df_resultado['Costo_Promedio_UND'], errors='coerce').fillna(0)

    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)

class PDF(FPDF):
    """Clase personalizada para generar PDFs de Órdenes de Compra con cabecera y pie de página de la empresa."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        self.font_family = 'Helvetica'

        # **CORRECCIÓN**: Rutas ajustadas a la carpeta 'fonts' y manejo de errores mejorado.
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # Asume que la carpeta 'fonts' está en el mismo directorio que el script
            font_path_regular = os.path.join(script_dir, 'fonts', 'DejaVuSans.ttf')
            font_path_bold = os.path.join(script_dir, 'fonts', 'DejaVuSans-Bold.ttf')
            
            if os.path.exists(font_path_regular) and os.path.exists(font_path_bold):
                self.add_font('DejaVu', '', font_path_regular, uni=True)
                self.add_font('DejaVu', 'B', font_path_bold, uni=True)
                self.font_family = 'DejaVu'
            else:
                st.warning("Archivos de fuente 'DejaVu' no encontrados en la carpeta 'fonts'. Se usará Helvetica. Algunos caracteres podrían no mostrarse.")
        except Exception as e:
            st.warning(f"No se pudo cargar la fuente 'DejaVu' (Error: {e}). Se usará Helvetica. Algunos caracteres podrían no mostrarse.")

    def header(self):
        font_name = self.font_family
        try:
            # **CORRECCIÓN**: Ruta del logo ajustada para estar en la carpeta principal.
            script_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(script_dir, 'Logo Ferreinox SAS BIC 2024.png')
            
            if os.path.exists(logo_path):
                self.image(logo_path, x=10, y=8, w=65)
            else:
                self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO NO ENCONTRADO]', 1, 0, 'C')
                #logging.warning(f"No se encontró el archivo del logo en la ruta: {logo_path}")

        except Exception as e:
            self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO ERROR]', 1, 0, 'C')
            #logging.error(f"Error al cargar el logo: {e}")

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

        x_start, y_start = pdf.get_x(), pdf.get_y()
        max_h = 0
        
        pdf.multi_cell(widths[0], 5, str(row.get('SKU', '')), 1, 'L'); max_h = max(max_h, pdf.get_y() - y_start)
        pdf.set_xy(x_start + widths[0], y_start)
        pdf.multi_cell(widths[1], 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L'); max_h = max(max_h, pdf.get_y() - y_start)
        pdf.set_xy(x_start + sum(widths[:2]), y_start)
        pdf.multi_cell(widths[2], 5, str(row.get('Descripcion', '')), 1, 'L'); max_h = max(max_h, pdf.get_y() - y_start)
        pdf.set_y(y_start)

        pdf.set_x(x_start + sum(widths[:3])); pdf.cell(widths[3], max_h, str(int(row[cantidad_col])), 1, 0, 'C')
        pdf.set_x(x_start + sum(widths[:4])); pdf.cell(widths[4], max_h, f"${row[costo_col]:,.2f}", 1, 0, 'R')
        pdf.set_x(x_start + sum(widths[:5])); pdf.cell(widths[5], max_h, f"${costo_total_item:,.2f}", 1, 0, 'R')
        pdf.ln(max_h)

    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font(font_name, '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font(font_name, 'B', 11)
    pdf.cell(55, 10, 'TOTAL A PAGAR', 1, 0, 'R'); pdf.cell(35, 10, f"${total_general:,.2f}", 1, 1, 'R')
    return bytes(pdf.output())

def generar_excel_dinamico(df, nombre_hoja):
    """Genera un archivo Excel en memoria a partir de un DataFrame, con formato automático."""
    output = io.BytesIO()
    nombre_hoja_truncado = nombre_hoja[:31]
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja_truncado}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja_truncado)
            writer.sheets[nombre_hoja_truncado].set_column('A:A', 70)
            return output.getvalue()

        df.to_excel(writer, index=False, sheet_name=nombre_hoja_truncado, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja_truncado]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        
        for col_num, value in enumerate(df.columns.values): worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            column_len = df[col].astype(str).map(len).max()
            max_len = max(column_len if pd.notna(column_len) else 0, len(col)) + 2
            worksheet.set_column(i, i, min(max_len, 45))

    return output.getvalue()

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
st.title("🚀 Tablero de Control de Abastecimiento v5.2")
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

    numeric_cols = ['Stock', 'Costo_Promedio_UND', 'Necesidad_Total', 'Excedente_Trasladable', 'Precio_Venta_Estimado', 'Demanda_Diaria_Promedio']
    for col in numeric_cols:
        if col in df_maestro.columns:
            df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)

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
            st.success("✅ ¡No se sugieren traslados automáticos en este momento! No hay necesidades que puedan ser cubiertas por excedentes de otras tiendas.")
        else:
            st.markdown("##### Filtros Avanzados de Traslados")
            f_col1, f_col2, f_col3 = st.columns(3)
            lista_origenes = ["Todas"] + sorted(df_plan_maestro['Tienda Origen'].unique().tolist())
            filtro_origen = f_col1.selectbox("Filtrar por Tienda Origen:", lista_origenes, key="filtro_origen")

            lista_destinos = ["Todas"] + sorted(df_plan_maestro['Tienda Destino'].unique().tolist())
            filtro_destino = f_col2.selectbox("Filtrar por Tienda Destino:", lista_destinos, key="filtro_destino")

            lista_proveedores_traslado = ["Todos"] + sorted(df_plan_maestro['Proveedor'].unique().tolist())
            filtro_proveedor_traslado = f_col3.selectbox("Filtrar por Proveedor:", lista_proveedores_traslado, key="filtro_proveedor_traslado")
            
            # **LÓGICA ANTI-SALTO**
            current_filters = f"{filtro_origen}-{filtro_destino}-{filtro_proveedor_traslado}"
            if st.session_state.last_filters_traslados != current_filters:
                df_aplicar_filtros = df_plan_maestro.copy()
                if filtro_origen != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Origen'] == filtro_origen]
                if filtro_destino != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Destino'] == filtro_destino]
                if filtro_proveedor_traslado != "Todos": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Proveedor'] == filtro_proveedor_traslado]

                df_para_editar = pd.merge(df_aplicar_filtros, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                          left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left'
                                          ).drop(columns=['Almacen_Nombre']).fillna({'Stock_En_Transito': 0})
                df_para_editar['Seleccionar'] = False
                st.session_state.df_traslados_editor = df_para_editar
                st.session_state.last_filters_traslados = current_filters

            if st.session_state.df_traslados_editor.empty:
                st.warning("No se encontraron traslados que coincidan con los filtros.")
            else:
                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Tienda Origen', 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Stock_En_Transito', 'Necesidad en Destino', 'Uds a Enviar']
                
                edited_df_traslados = st.data_editor(
                    st.session_state.df_traslados_editor[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={
                        "Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                        "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d"),
                        "Seleccionar": st.column_config.CheckboxColumn(required=True),
                    },
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']],
                    key="editor_traslados")
                
                # Actualiza el estado de la sesión con las ediciones del usuario para persistencia
                st.session_state.df_traslados_editor = edited_df_traslados

                df_seleccionados_traslado = edited_df_traslados[(edited_df_traslados['Seleccionar']) & (edited_df_traslados['Uds a Enviar'] > 0)]

                if not df_seleccionados_traslado.empty:
                    df_seleccionados_traslado_full = pd.merge(
                        df_seleccionados_traslado.copy(),
                        df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND', 'Proveedor']],
                        on=['SKU', 'Tienda Origen', 'Tienda Destino'], how='left'
                    )
                    df_seleccionados_traslado_full['Peso del Traslado (kg)'] = df_seleccionados_traslado_full['Uds a Enviar'] * df_seleccionados_traslado_full['Peso Individual (kg)']
                    st.markdown("---")
                    total_unidades = df_seleccionados_traslado_full['Uds a Enviar'].sum()
                    total_peso = df_seleccionados_traslado_full['Peso del Traslado (kg)'].sum()
                    st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")

                    with st.form("form_traslado_auto"):
                        destinos_implicados = df_seleccionados_traslado_full['Tienda Destino'].unique().tolist()
                        emails_predefinidos = [CONTACTOS_TIENDAS.get(d, {}).get('email', '') for d in destinos_implicados]
                        email_dest_traslado = st.text_input("📧 Correo(s) de destinatario(s) para el plan de traslado:", value=", ".join(filter(None, emails_predefinidos)), key="email_traslado")

                        st.markdown("##### Contactos para Notificación WhatsApp")
                        for dest in destinos_implicados:
                            c1, c2 = st.columns(2)
                            st.session_state.contacto_manual.setdefault(dest, CONTACTOS_TIENDAS.get(dest, {}))
                            nombre_actual = c1.text_input(f"Nombre contacto {dest}", value=st.session_state.contacto_manual[dest].get("nombre", ''), key=f"nombre_contacto_aut_{dest}")
                            celular_actual = c2.text_input(f"Celular {dest}", value=st.session_state.contacto_manual[dest].get("celular", ''), key=f"celular_contacto_aut_{dest}")
                            st.session_state.contacto_manual[dest]["nombre"] = nombre_actual
                            st.session_state.contacto_manual[dest]["celular"] = celular_actual

                        if st.form_submit_button("✅ Enviar y Registrar Traslado", use_container_width=True, type="primary"):
                            with st.spinner("Registrando traslado y enviando notificaciones..."):
                                exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados_traslado_full, "Traslado Automático")
                                if exito_registro:
                                    st.success(f"✅ ¡Traslado registrado exitosamente! {msg_registro}")
                                    if email_dest_traslado:
                                        excel_bytes = generar_excel_dinamico(df_registrado, "Plan_de_Traslados")
                                        asunto = f"Nuevo Plan de Traslado Interno - {datetime.now().strftime('%d/%m/%Y')}"
                                        cuerpo_html = f"""<html><body><p>Hola equipo,</p><p>Se ha registrado un nuevo plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado en el archivo adjunto.</p><p><b>ID de Grupo de Traslado:</b> {df_registrado['ID_Grupo'].iloc[0]}</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"""
                                        adjunto = [{'datos': excel_bytes, 'nombre_archivo': f"Plan_Traslado_{datetime.now().strftime('%Y%m%d')}.xlsx"}]
                                        enviado, msg = enviar_correo_con_adjuntos([e.strip() for e in email_dest_traslado.split(',')], asunto, cuerpo_html, adjunto)
                                        if enviado: st.success(msg)
                                        else: st.error(msg)

                                    st.session_state.notificaciones_pendientes = []
                                    for _, row in df_registrado.drop_duplicates(subset=['Tienda_Destino']).iterrows():
                                        destino = row['Tienda_Destino']
                                        info_tienda = st.session_state.contacto_manual.get(destino, {})
                                        numero_wpp = info_tienda.get("celular", "").strip()
                                        if numero_wpp:
                                            nombre_contacto = info_tienda.get("nombre", "equipo de " + destino)
                                            id_grupo_tienda = row['ID_Grupo']
                                            mensaje_wpp = f"Hola {nombre_contacto}, se ha generado una nueva orden de traslado hacia su tienda (Grupo ID: {id_grupo_tienda}). Por favor, estar atentos a la recepción. ¡Gracias!"
                                            st.session_state.notificaciones_pendientes.append({
                                                "label": f"📲 Notificar a {destino} por WhatsApp",
                                                "url": generar_link_whatsapp(numero_wpp, mensaje_wpp),
                                                "key": f"wpp_traslado_aut_{dest}"
                                            })
                                else:
                                    st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")

    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        st.markdown("##### 1. Buscar y añadir productos a la solicitud")
        search_term_especial = st.text_input("Buscar producto por SKU o Descripción para traslado especial:", key="search_traslado_especial")
        if search_term_especial:
            mask_especial = (df_maestro['Stock'] > 0) & (df_maestro['SKU'].str.contains(search_term_especial, case=False, na=False) | df_maestro['Descripcion'].str.contains(search_term_especial, case=False, na=False))
            df_resultados_especial = df_maestro[mask_especial].copy()
            if not df_resultados_especial.empty:
                df_resultados_especial['Uds a Enviar'] = 1; df_resultados_especial['Seleccionar'] = False
                cols_busqueda = ['Seleccionar', 'SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Stock_En_Transito', 'Uds a Enviar']
                edited_df_especial = st.data_editor(
                    df_resultados_especial[cols_busqueda], key="editor_traslados_especiales", use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(min_value=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Stock_En_Transito'])

                df_para_anadir = edited_df_especial[edited_df_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la solicitud", key="btn_anadir_especial"):
                    for _, row in df_para_anadir.iterrows():
                        item_id = f"{row['SKU']}_{row['Almacen_Nombre']}"
                        if not any(item['id'] == item_id for item in st.session_state.solicitud_traslado_especial):
                            costo = df_maestro.loc[(df_maestro['SKU'] == row['SKU']) & (df_maestro['Almacen_Nombre'] == row['Almacen_Nombre']), 'Costo_Promedio_UND'].iloc[0]
                            st.session_state.solicitud_traslado_especial.append({
                                'id': item_id, 'SKU': row['SKU'], 'Descripcion': row['Descripcion'],
                                'Tienda Origen': row['Almacen_Nombre'], 'Uds a Enviar': row['Uds a Enviar'], 'Costo_Promedio_UND': costo
                            })
                    st.success(f"{len(df_para_anadir)} producto(s) añadidos a la solicitud.")
            else:
                st.warning("No se encontraron productos con stock para ese criterio de búsqueda.")

        if st.session_state.solicitud_traslado_especial:
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la solicitud de traslado")
            df_solicitud = pd.DataFrame(st.session_state.solicitud_traslado_especial)

            with st.form("form_traslado_especial"):
                tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
                tienda_destino_especial = st.selectbox("Seleccionar Tienda Destino para esta solicitud:", tiendas_destino_validas, key="destino_especial")
                st.dataframe(df_solicitud[['SKU', 'Descripcion', 'Tienda Origen', 'Uds a Enviar']], use_container_width=True)

                email_dest_especial = st.text_input("📧 Correo(s) del destinatario:", value=CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('email', ''), key="email_traslado_especial")
                nombre_contacto_especial = st.text_input("Nombre contacto destino", value=CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('nombre', ''), key="nombre_especial")
                celular_contacto_especial = st.text_input("Celular destino", value=CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('celular', ''), key="celular_especial")

                c1, c2 = st.columns([1, 1])
                if c1.form_submit_button("✅ Enviar y Registrar Solicitud Especial", use_container_width=True, type="primary"):
                    with st.spinner("Procesando..."):
                        exito, msg, df_reg = registrar_ordenes_en_sheets(client, df_solicitud, "Traslado Especial", tienda_destino=tienda_destino_especial)
                        if exito:
                            st.success(f"✅ Solicitud especial registrada. {msg}")
                            st.session_state.notificaciones_pendientes = []
                            if celular_contacto_especial:
                                ids_grupo = ", ".join(df_reg['ID_Grupo'].unique())
                                mensaje_wpp = f"Hola {nombre_contacto_especial or tienda_destino_especial}, se ha generado una solicitud especial de traslado a su tienda (Grupo ID: {ids_grupo})."
                                st.session_state.notificaciones_pendientes.append({
                                    "label": f"📲 Notificar a {tienda_destino_especial}", "url": generar_link_whatsapp(celular_contacto_especial, mensaje_wpp), "key": "wpp_traslado_esp"
                                })
                            st.session_state.solicitud_traslado_especial = []
                            st.rerun()
                        else:
                            st.error(f"❌ Error al registrar: {msg}")
                if c2.form_submit_button("🗑️ Limpiar Solicitud", use_container_width=True):
                    st.session_state.solicitud_traslado_especial = []
                    st.rerun()

# --- PESTAÑA 3: PLAN DE COMPRAS ---
if active_tab == tab_titles[2]:
    st.header("🛒 Plan de Compras")
    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras_base = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        st.markdown("##### Filtros Avanzados de Compras")
        f_c1, f_c2, _ = st.columns(3)

        tiendas_con_sugerencia = ["Todas"] + sorted(df_plan_compras_base['Almacen_Nombre'].unique().tolist())
        filtro_tienda_compra = f_c1.selectbox("Filtrar por Tienda:", tiendas_con_sugerencia, key="filtro_tienda_compra")

        df_plan_compras_base['Proveedor'] = df_plan_compras_base['Proveedor'].astype(str).str.upper()
        proveedores_disponibles = ["Todos"] + sorted([p for p in df_plan_compras_base['Proveedor'].unique() if p and p != 'NAN'])
        selected_proveedor = f_c2.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores")
        
        # **LÓGICA ANTI-SALTO**
        current_filters = f"{filtro_tienda_compra}-{selected_proveedor}"
        if st.session_state.last_filters_compras != current_filters:
            df_temp = df_plan_compras_base.copy()
            if filtro_tienda_compra != "Todas":
                df_temp = df_temp[df_temp['Almacen_Nombre'] == filtro_tienda_compra]
            if selected_proveedor != 'Todos':
                df_temp = df_temp[df_temp['Proveedor'] == selected_proveedor]
            
            df_a_mostrar = df_temp.copy()
            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].apply(np.ceil).astype(int)
            df_a_mostrar['Seleccionar'] = False # Iniciar siempre deseleccionado
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            st.session_state.df_compras_editor = df_a_mostrar_final
            st.session_state.last_filters_compras = current_filters
        
        if st.session_state.df_compras_editor.empty:
            st.info("No hay sugerencias de compra con los filtros actuales. ¡El inventario parece estar optimizado!")
        else:
            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            col_b1, col_b2, _ = st.columns([1,1,5])
            if col_b1.button("Seleccionar Todos", key="select_all_compras"):
                st.session_state.df_compras_editor['Seleccionar'] = True
                st.rerun() # Forzar rerun para que el editor se actualice
            if col_b2.button("Deseleccionar Todos", key="deselect_all_compras"):
                st.session_state.df_compras_editor['Seleccionar'] = False
                st.rerun() # Forzar rerun

            cols = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock_En_Transito', 'Uds a Comprar', 'Costo_Promedio_UND']
            cols_existentes = [c for c in cols if c in st.session_state.df_compras_editor.columns]
            
            edited_df = st.data_editor(st.session_state.df_compras_editor[cols_existentes], hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(min_value=0), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[c for c in cols_existentes if c not in ['Seleccionar', 'Uds a Comprar']], key="editor_principal")
            
            # Actualiza el estado de la sesión con las ediciones para persistencia
            st.session_state.df_compras_editor = edited_df
            
            df_seleccionados = edited_df[(edited_df['Seleccionar']) & (edited_df['Uds a Comprar'] > 0)]

            if not df_seleccionados.empty:
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']
                valor_total = df_seleccionados['Valor de la Compra'].sum()
                st.markdown("---")

                col1, col2 = st.columns([3, 1])
                col1.subheader(f"Resumen de la Selección Total: ${valor_total:,.2f}")
                excel_bytes = generar_excel_dinamico(df_seleccionados, "Seleccion_de_Compra")
                col2.download_button("📥 Descargar Selección en Excel", data=excel_bytes, file_name="seleccion_compra.xlsx", use_container_width=True)

                st.markdown("---")
                st.subheader("Generar Órdenes de Compra por Proveedor/Tienda")
                grouped = df_seleccionados.groupby(['Proveedor', 'Tienda'])

                for (proveedor, tienda), df_grupo in grouped:
                    with st.container(border=True):
                        st.markdown(f"#### Orden para **{proveedor}** ➡️ Destino: **{tienda}**")
                        st.dataframe(df_grupo[['SKU', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND', 'Valor de la Compra']], use_container_width=True)

                        with st.form(key=f"form_{proveedor.replace(' ', '_')}_{tienda.replace(' ', '_')}"):
                            contacto_info = CONTACTOS_PROVEEDOR.get(proveedor, {})
                            email_dest = st.text_input("📧 Correos del destinatario:", value=contacto_info.get('email', ''), key=f"email_{proveedor}_{tienda}")
                            nombre_contacto = st.text_input("Nombre contacto:", value=contacto_info.get('nombre', ''), key=f"nombre_{proveedor}_{tienda}")
                            celular_proveedor = st.text_input("Celular contacto:", value=contacto_info.get('celular', ''), key=f"celular_{proveedor}_{tienda}")

                            submitted = st.form_submit_button("✅ Enviar y Registrar Esta Orden", type="primary", use_container_width=True)
                            if submitted:
                                if not email_dest: st.warning("Se necesita un correo para enviar la orden.")
                                else:
                                    with st.spinner(f"Procesando orden para {proveedor}..."):
                                        exito, msg, df_reg = registrar_ordenes_en_sheets(client, df_grupo, "Compra Sugerencia")
                                        if exito:
                                            st.success(f"¡Orden registrada! {msg}")
                                            orden_id_grupo = df_reg['ID_Grupo'].iloc[0] if not df_reg.empty else f"OC-{datetime.now().strftime('%f')}"
                                            direccion_entrega = DIRECCIONES_TIENDAS.get(tienda, "N/A")
                                            pdf_bytes = generar_pdf_orden_compra(df_grupo, proveedor, tienda, direccion_entrega, nombre_contacto, orden_id_grupo)
                                            excel_bytes = generar_excel_dinamico(df_grupo, f"Compra_{proveedor}")

                                            asunto = f"Nueva Orden de Compra {orden_id_grupo} de Ferreinox SAS BIC - {proveedor}"
                                            cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra N° {orden_id_grupo}</b> en formatos PDF y Excel.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                            adjuntos = [ {'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_grupo}.pdf"}, {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_{orden_id_grupo}.xlsx"} ]
                                            enviado, msg_envio = enviar_correo_con_adjuntos([e.strip() for e in email_dest.split(',')], asunto, cuerpo_html, adjuntos)
                                            if enviado: st.success(msg_envio)
                                            else: st.error(msg_envio)

                                            if celular_proveedor:
                                                msg_wpp = f"Hola {nombre_contacto}, te acabamos de enviar la Orden de Compra N° {orden_id_grupo} al correo. Quedamos atentos. ¡Gracias!"
                                                st.session_state.notificaciones_pendientes.append({
                                                    "label": f"📲 Notificar a {proveedor}", "url": generar_link_whatsapp(celular_proveedor, msg_wpp), "key": f"wpp_compra_{proveedor}_{tienda}"
                                                })
                                        else:
                                            st.error(f"Error al registrar: {msg}")

    with st.expander("🆕 **Compras Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        # La lógica de esta sección se mantiene similar ya que no utiliza un editor persistente
        st.markdown("##### 1. Buscar y añadir productos a la solicitud de compra")
        search_term_compra_esp = st.text_input("Buscar producto por SKU o Descripción para compra especial:", key="search_compra_especial")
        if search_term_compra_esp:
            mask_compra_esp = (df_maestro['SKU'].str.contains(search_term_compra_esp, case=False, na=False) | 
                             df_maestro['Descripcion'].str.contains(search_term_compra_esp, case=False, na=False))
            df_resultados_compra_esp = df_maestro[mask_compra_esp].drop_duplicates(subset=['SKU']).copy()

            if not df_resultados_compra_esp.empty:
                df_resultados_compra_esp['Uds a Comprar'] = 1; df_resultados_compra_esp['Seleccionar'] = False
                cols_compra_esp = ['Seleccionar', 'SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND', 'Uds a Comprar']
                edited_df_compra_esp = st.data_editor(
                    df_resultados_compra_esp[cols_compra_esp], key="editor_compra_especial", use_container_width=True,
                    column_config={"Uds a Comprar": st.column_config.NumberColumn(min_value=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND'])
                df_para_anadir_compra = edited_df_compra_esp[edited_df_compra_esp['Seleccionar']]
                if st.button("➕ Añadir a la Compra Especial", key="btn_anadir_compra_esp"):
                    for _, row in df_para_anadir_compra.iterrows():
                        if not any(item['SKU'] == row['SKU'] for item in st.session_state.compra_especial_items):
                            st.session_state.compra_especial_items.append(row.to_dict())
                    st.success(f"{len(df_para_anadir_compra)} producto(s) añadidos a la compra especial.")
            else:
                st.warning("No se encontraron productos con ese criterio de búsqueda.")

        if st.session_state.compra_especial_items:
            st.markdown("---")
            st.markdown("##### 2. Revisar y generar la Orden de Compra Especial")
            df_compra_especial = pd.DataFrame(st.session_state.compra_especial_items)

            with st.form("form_compra_especial"):
                st.dataframe(df_compra_especial[['SKU', 'Descripcion', 'Proveedor', 'Uds a Comprar', 'Costo_Promedio_UND']], use_container_width=True)
                proveedor_especial = st.text_input("Nombre del Proveedor:", key="proveedor_especial_nombre")
                tienda_destino_especial = st.selectbox("Tienda Destino:", almacenes_disponibles, key="tienda_destino_compra_esp")
                contacto_info_esp = CONTACTOS_PROVEEDOR.get(proveedor_especial.upper(), {})
                email_dest_esp = st.text_input("📧 Correo del proveedor:", value=contacto_info_esp.get('email', ''), key="email_compra_esp")
                nombre_contacto_esp = st.text_input("Nombre contacto proveedor:", value=contacto_info_esp.get('nombre', ''), key="nombre_compra_esp")
                celular_proveedor_esp = st.text_input("Celular proveedor:", value=contacto_info_esp.get('celular', ''), key="celular_compra_esp")

                c1_esp, c2_esp = st.columns([1, 1])
                if c1_esp.form_submit_button("✅ Enviar y Registrar Compra Especial", use_container_width=True, type="primary"):
                    if proveedor_especial and tienda_destino_especial:
                        with st.spinner("Procesando compra especial..."):
                            exito, msg, df_reg = registrar_ordenes_en_sheets(client, df_compra_especial, "Compra Especial", proveedor_nombre=proveedor_especial, tienda_destino=tienda_destino_especial)
                            if exito:
                                st.success(f"✅ Compra especial registrada. {msg}")
                                orden_id_grupo = df_reg['ID_Grupo'].iloc[0] if not df_reg.empty else f"OC-SP-{datetime.now().strftime('%f')}"
                                direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_destino_especial, "N/A")
                                pdf_bytes = generar_pdf_orden_compra(df_reg, proveedor_especial, tienda_destino_especial, direccion_entrega, nombre_contacto_esp, orden_id_grupo)
                                excel_bytes = generar_excel_dinamico(df_reg, f"Compra_Especial_{proveedor_especial}")
                                asunto = f"Nueva Orden de Compra Especial {orden_id_grupo} de Ferreinox SAS BIC - {proveedor_especial}"
                                cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor_especial},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra especial N° {orden_id_grupo}</b>.</p><p><b>Sede de Entrega:</b> {tienda_destino_especial}<br><b>Dirección:</b> {direccion_entrega}</p><p>Agradecemos su gestión.</p><p>Cordialmente,<br><b>Departamento de Compras</b></p></body></html>"
                                adjuntos = [ {'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_grupo}.pdf"}, {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_Especial_{orden_id_grupo}.xlsx"} ]
                                if email_dest_esp:
                                    enviado, msg_envio = enviar_correo_con_adjuntos([e.strip() for e in email_dest_esp.split(',')], asunto, cuerpo_html, adjuntos)
                                    if enviado: st.success(msg_envio)
                                    else: st.error(msg_envio)
                                if celular_proveedor_esp:
                                    msg_wpp = f"Hola {nombre_contacto_esp}, te acabamos de enviar la Orden de Compra Especial N° {orden_id_grupo} al correo. ¡Gracias!"
                                    st.session_state.notificaciones_pendientes.append({ "label": f"📲 Notificar a {proveedor_especial}", "url": generar_link_whatsapp(celular_proveedor_esp, msg_wpp), "key": f"wpp_compra_esp_{proveedor_especial}"})
                                st.session_state.compra_especial_items = []
                                st.rerun()
                            else:
                                st.error(f"❌ Error al registrar: {msg}")
                    else:
                        st.warning("Debe especificar un proveedor y una tienda de destino.")
                if c2_esp.form_submit_button("🗑️ Limpiar Lista", use_container_width=True):
                    st.session_state.compra_especial_items = []
                    st.rerun()

# --- PESTAÑA 4: SEGUIMIENTO Y RECEPCIÓN ---
if active_tab == tab_titles[3]:
    st.subheader("✅ Seguimiento y Recepción de Órdenes")
    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        df_ordenes_vista_original['Proveedor'] = df_ordenes_vista_original['Proveedor'].astype(str).fillna('N/A')

        with st.expander("Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=True):
            st.markdown("##### Filtrar Órdenes")
            track_c1, track_c2, track_c3 = st.columns(3)
            df_ordenes_vista = df_ordenes_vista_original.copy()

            estados_disponibles = ["Todos"] + df_ordenes_vista['Estado'].unique().tolist()
            filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, index=estados_disponibles.index('Pendiente') if 'Pendiente' in estados_disponibles else 0, key="filtro_estado_seguimiento")
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
                cols_seguimiento = ['Seleccionar', 'ID_Grupo', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                st.info("Selecciona las líneas de orden y luego elige el nuevo estado para actualizarlas en lote.")
                edited_df_seguimiento = st.data_editor(df_ordenes_vista[cols_seguimiento], hide_index=True, use_container_width=True,
                    key="editor_seguimiento", disabled=[c for c in cols_seguimiento if c != 'Seleccionar'])

                df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]
                if not df_seleccion_seguimiento.empty:
                    st.markdown("##### Acciones en Lote para Órdenes Seleccionadas")
                    nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                    if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} líneas a '{nuevo_estado}'", key="btn_actualizar_estado"):
                        df_historico_modificado = df_ordenes_historico.copy()
                        ids_a_actualizar = df_seleccion_seguimiento['ID_Orden'].tolist()
                        df_historico_modificado.loc[df_historico_modificado['ID_Orden'].isin(ids_a_actualizar), 'Estado'] = nuevo_estado
                        with st.spinner("Actualizando estados en Google Sheets..."):
                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                            if exito:
                                st.success(f"¡Éxito! {len(ids_a_actualizar)} líneas de orden actualizadas. Pulse 'Forzar Recarga' para ver los cambios.")
                            else:
                                st.error(f"Error al actualizar Google Sheets: {msg}")

        st.markdown("---")
        # **MEJORA**: Nueva sección para gestionar por ID_Grupo
        with st.expander("🔍 Gestionar, Modificar o Reenviar una Orden Específica por Grupo", expanded=False):
            ordenes_id_unicas = sorted(df_ordenes_vista_original['ID_Grupo'].unique().tolist(), reverse=True)
            id_grupo_elegido = st.selectbox("Seleccione el GRUPO de la Orden para gestionar:", [""] + ordenes_id_unicas, key="select_grupo_id_to_edit")

            if id_grupo_elegido:
                if st.session_state.order_to_edit != id_grupo_elegido:
                    df_orden_completa = df_ordenes_vista_original[df_ordenes_vista_original['ID_Grupo'] == id_grupo_elegido].copy()
                    df_orden_completa['Costo_Unitario'] = pd.to_numeric(df_orden_completa['Costo_Unitario'], errors='coerce')
                    df_orden_completa['Cantidad_Solicitada'] = pd.to_numeric(df_orden_completa['Cantidad_Solicitada'], errors='coerce')
                    st.session_state.orden_a_editar_df = df_orden_completa
                    st.session_state.order_to_edit = id_grupo_elegido

                st.write(f"#### Modificando Orden (Grupo): **{id_grupo_elegido}**")
                edited_orden_df = st.data_editor(
                    st.session_state.orden_a_editar_df, key="editor_modificar_orden", use_container_width=True, hide_index=True,
                    column_config={
                        "Cantidad_Solicitada": st.column_config.NumberColumn(label="Cantidad", min_value=0, step=1, format="%d"),
                        "Costo_Unitario": st.column_config.NumberColumn(label="Costo Unit.", format="$%.2f")
                    },
                    disabled=['ID_Grupo', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Tienda_Destino', 'Estado', 'Costo_Total']
                )

                with st.form(key=f"form_resend_{id_grupo_elegido}"):
                    st.markdown("##### Información para reenvío")
                    proveedor_orden = edited_orden_df['Proveedor'].iloc[0]
                    tienda_orden = edited_orden_df['Tienda_Destino'].iloc[0]
                    
                    is_traslado = "TRASLADO INTERNO" in proveedor_orden
                    if is_traslado:
                        contacto_info = CONTACTOS_TIENDAS.get(tienda_orden, {})
                        email_label, nombre_label, celular_label = f"📧 Correo {tienda_orden}:", f"Nombre {tienda_orden}:", f"Celular {tienda_orden}:"
                    else:
                        contacto_info = CONTACTOS_PROVEEDOR.get(proveedor_orden.upper(), {})
                        email_label, nombre_label, celular_label = f"📧 Correo ({proveedor_orden}):", "Nombre proveedor:", "Celular proveedor:"

                    email_dest = st.text_input(email_label, value=contacto_info.get('email', ''))
                    nombre_contacto = st.text_input(nombre_label, value=contacto_info.get('nombre', ''))
                    celular_contacto = st.text_input(celular_label, value=contacto_info.get('celular', ''))

                    submitted = st.form_submit_button("💾 Guardar Cambios y Reenviar Orden", type="primary", use_container_width=True)
                    if submitted:
                        with st.spinner("Guardando cambios y reenviando orden..."):
                            df_historico_actualizado = df_ordenes_historico.copy()
                            for _, row in edited_orden_df.iterrows():
                                mask = df_historico_actualizado['ID_Orden'] == row['ID_Orden']
                                df_historico_actualizado.loc[mask, 'Cantidad_Solicitada'] = row['Cantidad_Solicitada']
                                df_historico_actualizado.loc[mask, 'Costo_Unitario'] = row['Costo_Unitario']
                                costo_total_recalculado = row['Cantidad_Solicitada'] * row['Costo_Unitario']
                                df_historico_actualizado.loc[mask, 'Costo_Total'] = costo_total_recalculado
                            
                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_actualizado)
                            if exito:
                                st.success(f"✅ Orden {id_grupo_elegido} actualizada correctamente en Google Sheets.")
                                # Preparar DF para PDF/correo
                                df_reenvio = edited_orden_df[edited_orden_df['Cantidad_Solicitada'] > 0].copy()
                                if is_traslado:
                                    # Lógica específica si es un traslado (ej. no generar PDF o email diferente)
                                    st.info("La orden de traslado ha sido actualizada. Notifique manualmente si es necesario.")
                                else:
                                    # Lógica para orden de compra
                                    if df_reenvio.empty:
                                        st.warning("La orden está vacía después de los cambios. No se envió ningún correo.")
                                    else:
                                        direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_orden, "N/A")
                                        pdf_bytes = generar_pdf_orden_compra(df_reenvio, proveedor_orden, tienda_orden, direccion_entrega, nombre_contacto, id_grupo_elegido)
                                        excel_bytes = generar_excel_dinamico(df_reenvio, f"Orden_{id_grupo_elegido}")
                                        asunto = f"**ORDEN ACTUALIZADA** {id_grupo_elegido} de Ferreinox SAS BIC"
                                        cuerpo_html = f"<html><body><p>Estimados,</p><p>Adjunto encontrarán la <b>versión actualizada de la orden N° {id_grupo_elegido}</b>.</p><p>Por favor, considerar esta como la versión final y anular cualquier versión anterior.</p><p><b>Sede de Entrega:</b> {tienda_orden}<br><b>Dirección:</b> {direccion_entrega}</p><p>Gracias,</p><p>--<br><b>Departamento de Compras</b></p></body></html>"
                                        adjuntos = [ {'datos': pdf_bytes, 'nombre_archivo': f"OC_ACTUALIZADA_{id_grupo_elegido}.pdf"}, {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_ACTUALIZADA_{id_grupo_elegido}.xlsx"} ]
                                        if email_dest:
                                            enviado, msg_envio = enviar_correo_con_adjuntos([e.strip() for e in email_dest.split(',')], asunto, cuerpo_html, adjuntos)
                                            if enviado: st.success(msg_envio)
                                            else: st.error(msg_envio)
                                        else: st.warning("Orden actualizada pero no enviada (falta correo).")

                                        if celular_contacto:
                                            msg_wpp = f"Hola {nombre_contacto}, te acabamos de reenviar la Orden de Compra ACTUALIZADA N° {id_grupo_elegido} al correo. Por favor, tomar esta como la versión final. ¡Gracias!"
                                            st.session_state.notificaciones_pendientes.append({
                                                "label": f"📲 Notificar actualización a {nombre_contacto}", "url": generar_link_whatsapp(celular_contacto, msg_wpp), "key": f"wpp_update_{id_grupo_elegido}"
                                            })
                                
                                # Limpiar estado para la próxima edición
                                st.session_state.orden_a_editar_df = pd.DataFrame()
                                st.session_state.order_to_edit = None
                                st.rerun() # Recargar para reflejar cambios y limpiar la vista de edición
                            else:
                                st.error(f"Error al actualizar la orden en Google Sheets: {msg}")

# --- BLOQUE FINAL PARA MOSTRAR NOTIFICACIONES PENDIENTES ---
if st.session_state.notificaciones_pendientes:
    st.markdown("---")
    st.subheader("🔔 Notificaciones Pendientes de Envío")
    st.info("La orden ha sido registrada/actualizada y el correo enviado. Haz clic en los botones para enviar las notificaciones por WhatsApp.")

    for notif in st.session_state.notificaciones_pendientes:
        whatsapp_button(notif["label"], notif["url"], notif["key"])

    if st.button("✅ Hecho, Limpiar Notificaciones", key="finalizar_proceso_completo", type="primary"):
        st.session_state.notificaciones_pendientes = []
        st.success("Notificaciones limpiadas. La app se recargará.")
        st.rerun()
