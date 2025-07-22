# utils.py

import streamlit as st
import pandas as pd
import numpy as np
import io
import os  # <-- Importante para manejar rutas de archivos
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

# --- CONSTANTES Y CONFIGURACIONES ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
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

# --- FUNCIONES DE CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource(ttl=3600)
def connect_to_gsheets():
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}. Revisa tus 'secrets'.")
        return None

@st.cache_data(ttl=60)
def load_data_from_sheets(_client, sheet_name):
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        df = pd.DataFrame(worksheet.get_all_records())
        if not df.empty and 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Error: La hoja '{sheet_name}' no fue encontrada.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ocurrió un error al cargar la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        df_str = df_to_write.astype(str).replace(np.nan, '')
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
        return True, f"Hoja '{sheet_name}' actualizada."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        headers = worksheet.row_values(1)
        df_to_append_str = df_to_append.astype(str).replace(np.nan, '')
        if headers:
            df_to_append_ordered = df_to_append_str.reindex(columns=headers).fillna('')
        else:
            worksheet.update([df_to_append_str.columns.values.tolist()] + df_to_append_str.values.tolist())
            return True, "Nuevos registros y cabeceras añadidos.", df_to_append
        worksheet.append_rows(df_to_append_ordered.values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Nuevos registros añadidos a '{sheet_name}'.", df_to_append
    except Exception as e:
        return False, f"Error al añadir registros en '{sheet_name}': {e}", pd.DataFrame()

# --- LÓGICA DE ÓRDENES Y CÁLCULOS AVANZADOS ---
@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    if _df_analisis is None or _df_analisis.empty: return pd.DataFrame()
    df_origen = _df_analisis[_df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis[_df_analisis['Necesidad_Ajustada_Por_Transito'] > 0].sort_values(by='Necesidad_Ajustada_Por_Transito', ascending=False).copy()
    if df_origen.empty or df_destino.empty: return pd.DataFrame()
    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()
    for _, need_row in df_destino.iterrows():
        sku, tienda_necesitada, necesidad = need_row['SKU'], need_row['Almacen_Nombre'], need_row['Necesidad_Ajustada_Por_Transito']
        if necesidad <= 0: continue
        posibles_origenes = df_origen[(df_origen['SKU'] == sku) & (df_origen['Almacen_Nombre'] != tienda_necesitada)]
        for _, origin_row in posibles_origenes.iterrows():
            tienda_origen = origin_row['Almacen_Nombre']
            excedente_disp = excedentes_mutables.get((sku, tienda_origen), 0)
            if excedente_disp > 0:
                unidades_a_enviar = min(necesidad, excedente_disp)
                if unidades_a_enviar < 1: continue
                plan_final.append({
                    'SKU': sku, 'Descripcion': need_row['Descripcion'], 'Marca_Nombre': origin_row['Marca_Nombre'],
                    'Proveedor': origin_row['Proveedor'], 'Segmento_ABC': need_row['Segmento_ABC'],
                    'Tienda Origen': tienda_origen, 'Stock en Origen': origin_row['Stock'],
                    'Tienda Destino': tienda_necesitada, 'Stock en Destino': need_row['Stock'],
                    'Necesidad en Destino': need_row['Necesidad_Ajustada_Por_Transito'],
                    'Uds a Enviar': np.floor(unidades_a_enviar),
                    'Peso Individual (kg)': need_row.get('Peso_Articulo', 0),
                    'Costo_Promedio_UND': need_row['Costo_Promedio_UND']
                })
                necesidad -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
                if necesidad <= 0: break
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Uds a Enviar'] = df_resultado['Uds a Enviar'].astype(int)
    df_resultado['Peso del Traslado (kg)'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado.get('Peso Individual (kg)', 0))
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Costo_Promedio_UND'])
    return df_resultado[df_resultado['Uds a Enviar'] > 0].sort_values(by=['Valor del Traslado'], ascending=False)

@st.cache_data
def calcular_sugerencias_finales(_df_base, _df_ordenes):
    df_maestro = _df_base.copy()
    if not _df_ordenes.empty and 'Estado' in _df_ordenes.columns:
        df_pendientes = _df_ordenes[_df_ordenes['Estado'] == 'Pendiente'].copy()
        if not df_pendientes.empty:
            df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
            stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
            stock_en_transito_agg = stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito', 'Tienda_Destino': 'Almacen_Nombre'})
            df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
            df_maestro['Stock_En_Transito'].fillna(0, inplace=True)
        else:
            df_maestro['Stock_En_Transito'] = 0
    else:
        df_maestro['Stock_En_Transito'] = 0
    df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)
    df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)
    if not df_plan_maestro.empty:
        unidades_cubiertas = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
        unidades_cubiertas = unidades_cubiertas.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado'})
        df_maestro = pd.merge(df_maestro, unidades_cubiertas, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Cubierto_Por_Traslado'].fillna(0, inplace=True)
    else:
        df_maestro['Cubierto_Por_Traslado'] = 0
    df_maestro['Sugerencia_Compra'] = np.ceil(df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
    df_maestro['Sugerencia_Compra'] = df_maestro['Sugerencia_Compra'].astype(int)
    return df_maestro, df_plan_maestro

# --- REGISTRO DE ÓRDENES Y NOTIFICACIONES ---
def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    if df_orden.empty or client is None:
        return False, "No hay datos para registrar.", pd.DataFrame()
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = df_orden.copy()
    if 'Uds a Comprar' in df_orden.columns: cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_orden.columns: cantidad_col = 'Uds a Enviar'
    elif 'Cantidad_Solicitada' in df_orden.columns: cantidad_col = 'Cantidad_Solicitada'
    else: return False, "No se encontró columna de cantidad.", pd.DataFrame()
    if 'Costo_Promedio_UND' in df_orden.columns: costo_col = 'Costo_Promedio_UND'
    elif 'Costo_Unitario' in df_orden.columns: costo_col = 'Costo_Unitario'
    else: return False, "No se encontró columna de costo.", pd.DataFrame()
    df_registro['Cantidad_Solicitada'] = df_registro[cantidad_col]
    df_registro['Costo_Unitario'] = df_registro.get(costo_col, 0)
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
    df_registro['ID_Orden'] = [f"{base_id}-{i+1}" for i in range(len(df_registro))]
    columnas_finales = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')
    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

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

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"
        self.empresa_nit = "NIT 800.224.617"
        self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"
        self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39)
        self.color_gris_oscuro = (68, 68, 68)
        self.color_azul_oscuro = (79, 129, 189)
        self.font_family = 'Helvetica'
        
        # --- ✅ MEJORA IMPORTANTE: RUTA ROBUSTA A LAS FUENTES Y FALLBACK ---
        try:
            # Construye una ruta absoluta al archivo de fuentes
            base_path = os.path.dirname(__file__)
            font_path = os.path.join(base_path, 'fonts', 'DejaVuSans.ttf')
            font_path_bold = os.path.join(base_path, 'fonts', 'DejaVuSans-Bold.ttf')
            
            self.add_font('DejaVu', '', font_path, uni=True)
            self.add_font('DejaVu', 'B', font_path_bold, uni=True)
            self.font_family = 'DejaVu'
        except FileNotFoundError:
            # Si no encuentra las fuentes, no detiene la app, usa la fuente por defecto.
            st.warning("Archivos de fuente personalizados no encontrados. Se usará la fuente por defecto.")
            self.font_family = 'Helvetica'
        except Exception as e:
            st.warning(f"Ocurrió un error al cargar las fuentes: {e}. Se usará la fuente por defecto.")
            self.font_family = 'Helvetica'

    def header(self):
        font_name = self.font_family
        try:
            self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError:
            self.set_xy(10, 8); self.set_font(font_name, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font(font_name, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R')
        self.set_x(80); self.set_font(font_name, '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R')
        self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        font_name = self.font_family
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1)
        self.line(10, self.get_y(), 200, self.get_y()); self.ln(2)
        self.set_font(font_name, '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}     |     {self.empresa_web}     |     {self.empresa_email}     |     {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C')
        self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num, is_consolidated=False):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    font_name = pdf.font_family
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font(font_name, 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1)
    pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font(font_name, '', 9)
    y_start_prov = pdf.get_y()
    proveedor_info = f"Razón Social: {proveedor_nombre}\nContacto: {contacto_proveedor if contacto_proveedor else 'No especificado'}"
    pdf.multi_cell(95, 7, proveedor_info, 1, 'L')
    y_end_prov = pdf.get_y()
    pdf.set_y(y_start_prov); pdf.set_x(105)
    if is_consolidated:
        envio_info = "Ferreinox SAS BIC\nDirección: Múltiples destinos según detalle\nRecibe: Coordinar con cada tienda"
    else:
        envio_info = f"{pdf.empresa_nombre} - Sede {tienda_nombre}\nDirección: {direccion_entrega}\nRecibe: Leivyn Gabriel Garcia"
    pdf.multi_cell(95, 7, envio_info, 1, 'L')
    y_end_envio = pdf.get_y()
    pdf.set_y(max(y_end_prov, y_end_envio)); pdf.ln(5)
    pdf.set_font(font_name, 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {orden_num}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1)
    pdf.ln(10); pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font(font_name, 'B', 9)
    if is_consolidated:
        pdf.cell(20, 8, 'SKU', 1, 0, 'C', 1); pdf.cell(65, 8, 'Descripción', 1, 0, 'C', 1)
        pdf.cell(35, 8, 'Proveedor', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
        pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(30, 8, 'Costo Total', 1, 1, 'C', 1)
    else:
        pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
        pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
        pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)
    pdf.set_font(font_name, '', 8); pdf.set_text_color(0, 0, 0); subtotal = 0
    if 'Uds a Comprar' in df_seleccion.columns: cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_seleccion.columns: cantidad_col = 'Uds a Enviar'
    else: cantidad_col = 'Cantidad_Solicitada'
    if 'Costo_Promedio_UND' in df_seleccion.columns: costo_col = 'Costo_Promedio_UND'
    else: costo_col = 'Costo_Unitario'
    temp_df = df_seleccion.copy()
    temp_df[cantidad_col] = pd.to_numeric(temp_df[cantidad_col], errors='coerce').fillna(0)
    temp_df[costo_col] = pd.to_numeric(temp_df[costo_col], errors='coerce').fillna(0)
    for _, row in temp_df.iterrows():
        cantidad = row[cantidad_col]; costo_unitario = row[costo_col]
        costo_total_item = cantidad * costo_unitario; subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        if is_consolidated:
            pdf.multi_cell(20, 5, str(row['SKU']), 1, 'L'); y1 = pdf.get_y(); pdf.set_xy(x_start + 20, y_start)
            pdf.multi_cell(65, 5, row['Descripcion'], 1, 'L'); y2 = pdf.get_y(); pdf.set_xy(x_start + 85, y_start)
            pdf.multi_cell(35, 5, str(row.get('Proveedor', 'N/A')), 1, 'L'); y3 = pdf.get_y()
            row_height = max(y1, y2, y3) - y_start
            pdf.set_xy(x_start + 120, y_start); pdf.multi_cell(15, row_height, str(int(cantidad)), 1, 'C')
            pdf.set_xy(x_start + 135, y_start); pdf.multi_cell(25, row_height, f"${costo_unitario:,.2f}", 1, 'R')
            pdf.set_xy(x_start + 160, y_start); pdf.multi_cell(30, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        else:
            pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L'); y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
            pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L'); y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
            pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L'); y3 = pdf.get_y()
            row_height = max(y1, y2, y3) - y_start
            pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(cantidad)), 1, 'C')
            pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${costo_unitario:,.2f}", 1, 'R')
            pdf.set_xy(x_start + 165, y_start); pdf.multi_cell(25, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        pdf.set_y(y_start + row_height)
    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19; total_general = subtotal + iva_valor
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
            try:
                column_len = df[col].astype(str).map(len).max()
                max_len = max(column_len if pd.notna(column_len) else 0, len(col)) + 2
                worksheet.set_column(i, i, min(max_len, 45))
            except Exception:
                worksheet.set_column(i, i, 15)
    return output.getvalue()
