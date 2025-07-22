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
st.set_page_config(page_title="Gestión de Abastecimiento v3.0", layout="wide", page_icon="🚀")

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
# Es una buena práctica inicializar todas las claves que usarás en la sesión.
# Esto previene errores y hace el código más predecible.
keys_to_initialize = {
    'df_analisis_maestro': pd.DataFrame(),
    'user_role': None,
    'almacen_nombre': None,
    'solicitud_traslado_especial': [],
    'compra_especial_items': [],
    'orden_modificada_df': pd.DataFrame(),
    'orden_cargada_id': None,
    'active_tab': "📊 Diagnóstico"
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
        df_str = df_to_write.astype(str)
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

    # Identificar la columna de cantidad correcta
    if 'Uds a Comprar' in df_orden.columns:
        cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_orden.columns:
        cantidad_col = 'Uds a Enviar'
    elif 'Cantidad_Solicitada' in df_orden.columns:
         cantidad_col = 'Cantidad_Solicitada'
    else:
        return False, "No se encontró una columna de cantidad válida.", pd.DataFrame()

    # Identificar la columna de costo correcta
    if 'Costo_Promedio_UND' in df_orden.columns:
        costo_col = 'Costo_Promedio_UND'
    elif 'Costo_Unitario' in df_orden.columns:
        costo_col = 'Costo_Unitario'
    else:
        return False, "No se encontró una columna de costo válida.", pd.DataFrame()


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

    df_registro['ID_Orden'] = [f"{base_id}-{i}" for i in range(len(df_registro))]

    columnas_finales = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    df_final_para_gsheets = df_registro.reindex(columns=columnas_finales).fillna('')

    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

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
        footer_text = f"{self.empresa_nombre}      |       {self.empresa_web}       |       {self.empresa_email}       |       {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

## MEJORA: La función ahora es más robusta y no fallará por el nombre de la columna de costo o cantidad.
def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num, is_consolidated=False):
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

    if is_consolidated:
        envio_info = "Ferreinox SAS BIC\nDirección: Múltiples destinos según detalle\nRecibe: Coordinar con cada tienda"
    else:
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

    if is_consolidated:
        pdf.cell(20, 8, 'SKU', 1, 0, 'C', 1)
        pdf.cell(65, 8, 'Descripción', 1, 0, 'C', 1)
        pdf.cell(35, 8, 'Proveedor', 1, 0, 'C', 1)
        pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
        pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1)
        pdf.cell(30, 8, 'Costo Total', 1, 1, 'C', 1)
    else:
        pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
        pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
        pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)

    pdf.set_font(font_name, '', 8); pdf.set_text_color(0, 0, 0)
    subtotal = 0

    ## INICIO DE LA MEJORA ANTI-CRASH
    # Identificar dinámicamente los nombres de columna correctos para evitar KeyError
    if 'Uds a Comprar' in df_seleccion.columns:
        cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_seleccion.columns:
        cantidad_col = 'Uds a Enviar'
    else: # Fallback para la pestaña de seguimiento
        cantidad_col = 'Cantidad_Solicitada'

    if 'Costo_Promedio_UND' in df_seleccion.columns:
        costo_col = 'Costo_Promedio_UND'
    else: # Fallback para la pestaña de seguimiento
        costo_col = 'Costo_Unitario'
    ## FIN DE LA MEJORA ANTI-CRASH

    temp_df = df_seleccion.copy()
    temp_df[cantidad_col] = pd.to_numeric(temp_df[cantidad_col], errors='coerce').fillna(0)
    temp_df[costo_col] = pd.to_numeric(temp_df[costo_col], errors='coerce').fillna(0)

    for _, row in temp_df.iterrows():
        cantidad = row[cantidad_col]
        costo_unitario = row[costo_col]
        costo_total_item = cantidad * costo_unitario
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()

        if is_consolidated:
            pdf.multi_cell(20, 5, str(row['SKU']), 1, 'L')
            y1 = pdf.get_y(); pdf.set_xy(x_start + 20, y_start)
            pdf.multi_cell(65, 5, row['Descripcion'], 1, 'L')
            y2 = pdf.get_y(); pdf.set_xy(x_start + 85, y_start)
            pdf.multi_cell(35, 5, str(row.get('Proveedor', 'N/A')), 1, 'L')
            y3 = pdf.get_y()
            row_height = max(y1, y2, y3) - y_start
            pdf.set_xy(x_start + 120, y_start); pdf.multi_cell(15, row_height, str(int(cantidad)), 1, 'C')
            pdf.set_xy(x_start + 135, y_start); pdf.multi_cell(25, row_height, f"${costo_unitario:,.2f}", 1, 'R')
            pdf.set_xy(x_start + 160, y_start); pdf.multi_cell(30, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        else:
            pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
            y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
            pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
            y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
            pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L')
            y3 = pdf.get_y()
            row_height = max(y1, y2, y3) - y_start
            pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(cantidad)), 1, 'C')
            pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${costo_unitario:,.2f}", 1, 'R')
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
st.title("🚀 Tablero de Control de Abastecimiento v3.0")
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
    st.markdown("---")
    st.subheader("Sincronización Manual")
    if st.button("🔄 Actualizar 'Estado_Inventario' en GSheets"):
        with st.spinner("Sincronizando..."):
            columnas_a_sincronizar = ['SKU', 'Almacen_Nombre', 'Stock', 'Costo_Promedio_UND', 'Sugerencia_Compra', 'Necesidad_Total', 'Excedente_Trasladable', 'Estado_Inventario']
            df_para_sincronizar = df_maestro_base[[col for col in columnas_a_sincronizar if col in df_maestro_base.columns]].copy()
            exito, msg = update_sheet(client, "Estado_Inventario", df_para_sincronizar)
            if exito: st.success(msg)
            else: st.error(msg)

# --- 4. INTERFAZ DE USUARIO CON PESTAÑAS ---
tab_titles = ["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"]
tabs = st.tabs(tab_titles)

with tabs[0]:
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

with tabs[1]:
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
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
                df_para_editar = pd.merge(df_traslados_filtrado, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                          left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left'
                                          ).drop(columns=['Almacen_Nombre']).fillna({'Stock_En_Transito': 0})
                df_para_editar['Seleccionar'] = False
                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Tienda Origen', 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Stock_En_Transito', 'Necesidad en Destino', 'Uds a Enviar']
                edited_df_traslados = st.data_editor(
                    df_para_editar[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                                   "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d"),
                                   "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']], key="editor_traslados")
                df_seleccionados_traslado = edited_df_traslados[(edited_df_traslados['Seleccionar']) & (edited_df_traslados['Uds a Enviar'] > 0)]
                if not df_seleccionados_traslado.empty:
                    df_seleccionados_traslado_full = pd.merge(df_seleccionados_traslado.copy(), df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND']],
                                                              on=['SKU', 'Tienda Origen', 'Tienda Destino'], how='left')
                    df_seleccionados_traslado_full['Peso del Traslado (kg)'] = df_seleccionados_traslado_full['Uds a Enviar'] * df_seleccionados_traslado_full['Peso Individual (kg)']
                    st.markdown("---")
                    total_unidades = df_seleccionados_traslado_full['Uds a Enviar'].sum()
                    total_peso = df_seleccionados_traslado_full['Peso del Traslado (kg)'].sum()
                    st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")
                    destinos_implicados = df_seleccionados_traslado_full['Tienda Destino'].unique().tolist()
                    emails_predefinidos = [CONTACTOS_TIENDAS.get(d, {}).get('email', '') for d in destinos_implicados]
                    email_dest_traslado = st.text_input("📧 Correo(s) de destinatario(s) para el plan de traslado:", value=", ".join(filter(None, emails_predefinidos)), key="email_traslado", help="Puede ser uno o varios correos separados por coma.")
                    if st.button("✅ Enviar y Registrar Traslado", use_container_width=True, key="btn_registrar_traslado", type="primary"):
                        with st.spinner("Registrando traslado y enviando notificaciones..."):
                            exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados_traslado_full, "Traslado Automático")
                            if exito_registro:
                                st.success(f"✅ ¡Traslado registrado exitosamente! {msg_registro}")
                                if email_dest_traslado:
                                    excel_bytes = generar_excel_dinamico(df_registrado, "Plan_de_Traslados")
                                    asunto = f"Nuevo Plan de Traslado Interno - {datetime.now().strftime('%d/%m/%Y')}"
                                    cuerpo_html = f"<html><body><p>Hola equipo,</p><p>Se ha registrado un nuevo plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado en el archivo adjunto.</p><p><b>IDs de Traslado generados:</b> {', '.join(df_registrado['ID_Orden'].unique())}</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"
                                    adjunto_traslado = [{'datos': excel_bytes, 'nombre_archivo': f"Plan_Traslado_{datetime.now().strftime('%Y%m%d')}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                    lista_destinatarios = [email.strip() for email in email_dest_traslado.replace(';', ',').split(',') if email.strip()]
                                    enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_traslado)
                                    if enviado: st.success(mensaje)
                                    else: st.error(mensaje)
                                for _, row in df_registrado.drop_duplicates(subset=['Tienda_Destino']).iterrows():
                                    destino = row['Tienda_Destino']
                                    info_tienda = CONTACTOS_TIENDAS.get(destino)
                                    if info_tienda and info_tienda.get('celular'):
                                        numero_wpp = info_tienda['celular']
                                        ordenes_destino = df_registrado[df_registrado['Tienda_Destino'] == destino]
                                        ids_orden_tienda = ", ".join(ordenes_destino['ID_Orden'].unique())
                                        mensaje_wpp = f"Hola equipo de {destino}, se ha generado una nueva orden de traslado hacia su tienda (ID: {ids_orden_tienda}). Por favor, estar atentos a la recepción. ¡Gracias!"
                                        link_wpp = generar_link_whatsapp(numero_wpp, mensaje_wpp)
                                        st.link_button(f"📲 Notificar a {destino} por WhatsApp", link_wpp, target="_blank")
                                st.success("Proceso completado. La página se recargará para actualizar los datos.")
                                st.cache_data.clear()
                            else:
                                st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")
    st.markdown("---")
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
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
                st.write("Resultados de la búsqueda (solo se muestran productos con stock):")
                edited_df_especial = st.data_editor(
                    df_resultados_especial[columnas_busqueda], key="editor_traslados_especiales", hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=1, step=1),
                                   "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock'])
                df_para_anadir = edited_df_especial[edited_df_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la solicitud", key="btn_anadir_especial"):
                    for _, row in df_para_anadir.iterrows():
                        item_id = f"{row['SKU']}_{row['Almacen_Nombre']}"
                        if not any(item['id'] == item_id for item in st.session_state.solicitud_traslado_especial):
                            costo_info = df_maestro.loc[(df_maestro['SKU'] == row['SKU']) & (df_maestro['Almacen_Nombre'] == row['Almacen_Nombre']), 'Costo_Promedio_UND']
                            costo = costo_info.iloc[0] if not costo_info.empty else 0
                            st.session_state.solicitud_traslado_especial.append({
                                'id': item_id, 'SKU': row['SKU'], 'Descripcion': row['Descripcion'],
                                'Tienda Origen': row['Almacen_Nombre'], 'Uds a Enviar': row['Uds a Enviar'],
                                'Costo_Promedio_UND': costo
                            })
                    st.success(f"{len(df_para_anadir)} producto(s) añadidos a la solicitud.")
            else:
                st.warning("No se encontraron productos con stock para ese criterio de búsqueda.")
        if st.session_state.solicitud_traslado_especial:
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la solicitud de traslado")
            df_solicitud = pd.DataFrame(st.session_state.solicitud_traslado_especial)
            tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
            tienda_destino_especial = st.selectbox("Seleccionar Tienda Destino para esta solicitud:", tiendas_destino_validas, key="destino_especial")
            st.dataframe(df_solicitud[['SKU', 'Descripcion', 'Tienda Origen', 'Uds a Enviar']], use_container_width=True)
            if st.button("🗑️ Limpiar Solicitud", key="btn_limpiar_especial"):
                st.session_state.solicitud_traslado_especial = []
            st.markdown("##### 3. Finalizar y enviar la solicitud")
            email_predefinido_especial = CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('email', '')
            email_dest_especial = st.text_input("📧 Correo(s) del destinatario para la solicitud especial:", value=email_predefinido_especial, key="email_traslado_especial", help="Separados por coma.")
            if st.button("✅ Enviar y Registrar Solicitud Especial", use_container_width=True, key="btn_enviar_traslado_especial", type="primary"):
                if not df_solicitud.empty:
                    with st.spinner("Registrando y enviando solicitud especial..."):
                        exito_registro, msg_registro, df_registrado_especial = registrar_ordenes_en_sheets(client, df_solicitud, "Traslado Especial", tienda_destino=tienda_destino_especial)
                        if exito_registro:
                            st.success(f"✅ Solicitud especial registrada. {msg_registro}")
                            st.session_state.solicitud_traslado_especial = []
                            st.cache_data.clear()
                        else:
                            st.error(f"❌ Error al registrar: {msg_registro}")
                else:
                    st.warning("La solicitud está vacía.")

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
            select_all_suggested = st.checkbox("Seleccionar / Deseleccionar Todos los Productos Visibles", key="select_all_suggested", value=True)
            df_a_mostrar['Seleccionar'] = select_all_suggested
            columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock_En_Transito', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            columnas_existentes = [col for col in columnas if col in df_a_mostrar_final.columns]
            df_a_mostrar_final = df_a_mostrar_final[columnas_existentes]
            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df = st.data_editor(df_a_mostrar_final, hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1),
                               "Seleccionar": st.column_config.CheckboxColumn(required=True),
                               "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d")},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']], key="editor_principal")
            df_seleccionados = edited_df[(edited_df['Seleccionar']) & (edited_df['Uds a Comprar'] > 0)]
            if not df_seleccionados.empty:
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']
                st.markdown("---")
                proveedores_seleccion = df_seleccionados['Proveedor'].unique()
                tiendas_seleccion = df_seleccionados['Tienda'].unique()
                is_single_provider = len(proveedores_seleccion) == 1 and proveedores_seleccion[0] != 'NO ASIGNADO'
                is_single_store = len(tiendas_seleccion) == 1
                proveedor_actual = proveedores_seleccion[0] if is_single_provider else "CONSOLIDADO"
                tienda_actual = tiendas_seleccion[0] if is_single_store else "Multi-Tienda"
                info_proveedor = CONTACTOS_PROVEEDOR.get(proveedor_actual, {}) if is_single_provider else {}
                contacto_proveedor_nombre = info_proveedor.get('nombre', '')
                celular_proveedor_num = info_proveedor.get('celular', '')
                st.markdown(f"#### Opciones para la Orden a **{proveedor_actual}**")
                email_dest_placeholder = "ej: correo1@ejemplo.com, correo2@ejemplo.com"
                email_dest = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_principal", help=email_dest_placeholder, placeholder=email_dest_placeholder)
                whatsapp_dest = st.text_input("📱 Número de WhatsApp para notificación (ej: 573001234567):", value=celular_proveedor_num, key="wpp_principal", placeholder="573001234567")
                c1, c2, c3 = st.columns([2,1,1])
                orden_num = f"OC-{datetime.now().strftime('%Y%m%d-%H%M')}"
                direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_actual, "Verificar con cada tienda")
                pdf_bytes = generar_pdf_orden_compra(df_seleccionados, proveedor_actual, tienda_actual, direccion_entrega, contacto_proveedor_nombre, orden_num, is_consolidated=(not is_single_provider))
                excel_bytes = generar_excel_dinamico(df_seleccionados, f"Compra_{proveedor_actual}")
                with c1:
                    if st.button("✅ Enviar y Registrar Orden", use_container_width=True, key="btn_enviar_principal", type="primary"):
                        if not email_dest:
                             st.warning("Por favor, ingrese al menos un correo electrónico de destinatario para enviar la orden.")
                        else:
                            with st.spinner("Enviando correo y registrando orden..."):
                                exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados, "Compra Sugerencia")
                                if exito_registro:
                                    st.success(f"¡Orden registrada! {msg_registro}")
                                    orden_id_real = df_registrado['ID_Orden'].iloc[0] if not df_registrado.empty else orden_num
                                    lista_destinatarios = [email.strip() for email in email_dest.replace(';', ',').split(',') if email.strip()]
                                    if is_single_provider:
                                        asunto = f"Nueva Orden de Compra {orden_id_real} de Ferreinox SAS BIC - {proveedor_actual}"
                                        cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor_actual},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra N° {orden_id_real}</b> en formatos PDF y Excel.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_actual}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                    else:
                                        asunto = f"Nuevo Requerimiento Consolidado de Compra {orden_id_real} de Ferreinox SAS BIC"
                                        cuerpo_html = f"<html><body><p>Estimados proveedores,</p><p>Adjunto a este correo encontrarán un <b>requerimiento de compra consolidado N° {orden_id_real}</b> en formatos PDF y Excel. Por favor, revisar los items que corresponden a su empresa.</p><p>Las entregas deben coordinarse con cada tienda de destino según se especifica.</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                    adjuntos = [{'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_real}_{proveedor_actual.replace(' ','_')}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                                {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_{orden_id_real}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                    enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                    if enviado: st.success(mensaje)
                                    else: st.error(mensaje)
                                    if whatsapp_dest:
                                        numero_completo = whatsapp_dest.strip().replace(" ", "")
                                        mensaje_wpp = f"Hola {contacto_proveedor_nombre or ''}, le acabamos de enviar la Orden de Compra N° {orden_id_real} al correo. Quedamos atentos. ¡Gracias!"
                                        link_wpp = generar_link_whatsapp(numero_completo, mensaje_wpp)
                                        st.link_button("📲 Enviar Confirmación por WhatsApp", link_wpp, target="_blank")
                                    st.success("Proceso completado. Los datos se actualizarán.")
                                    st.cache_data.clear()
                                else:
                                    st.error(f"Error al registrar en Google Sheets: {msg_registro}")
                with c2:
                    st.download_button("📥 Descargar Excel", data=excel_bytes, file_name=f"Compra_{proveedor_actual}.xlsx", use_container_width=True)
                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes, file_name=f"OC_{orden_num}.pdf", use_container_width=True, disabled=(pdf_bytes is None))
                st.info(f"Total de la selección: ${df_seleccionados['Valor de la Compra'].sum():,.2f}")
    st.markdown("---")
    ## MEJORA: Funcionalidad de Compras Especiales implementada
    with st.expander("🆕 **Compras Especiales (Búsqueda y Creación Manual)**", expanded=False):
        st.markdown("##### 1. Buscar y añadir productos a la compra especial")
        search_term_compra_especial = st.text_input("Buscar cualquier producto por SKU o Descripción:", key="search_compra_especial")
        if search_term_compra_especial:
            mask_compra = (df_maestro['SKU'].astype(str).str.contains(search_term_compra_especial, case=False, na=False) |
                           df_maestro['Descripcion'].astype(str).str.contains(search_term_compra_especial, case=False, na=False))
            # Buscamos en el maestro para obtener una sola línea por SKU para añadir, sin importar la tienda
            df_resultados_compra = df_maestro[mask_compra].drop_duplicates(subset=['SKU']).copy()
            if not df_resultados_compra.empty:
                df_resultados_compra['Uds a Comprar'] = 1
                df_resultados_compra['Seleccionar'] = False
                columnas_busqueda_compra = ['Seleccionar', 'SKU', 'Descripcion', 'Proveedor', 'Uds a Comprar']
                st.write("Resultados de la búsqueda:")
                edited_df_compra_especial = st.data_editor(
                    df_resultados_compra[columnas_busqueda_compra], key="editor_compra_especial", hide_index=True, use_container_width=True,
                    column_config={"Uds a Comprar": st.column_config.NumberColumn(min_value=1, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Proveedor'])
                df_para_anadir_compra = edited_df_compra_especial[edited_df_compra_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la Compra Especial", key="btn_anadir_compra_especial"):
                    for _, row in df_para_anadir_compra.iterrows():
                        if not any(item['SKU'] == row['SKU'] for item in st.session_state.compra_especial_items):
                            st.session_state.compra_especial_items.append(row.to_dict())
                    st.success(f"{len(df_para_anadir_compra)} producto(s) añadidos a la compra.")
            else:
                st.warning("No se encontraron productos para ese criterio de búsqueda.")
        if st.session_state.compra_especial_items:
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la Compra Especial")
            df_solicitud_compra = pd.DataFrame(st.session_state.compra_especial_items)
            
            col_compra1, col_compra2 = st.columns(2)
            proveedores_validos = sorted(df_maestro['Proveedor'].unique().tolist())
            proveedor_especial = col_compra1.selectbox("Seleccionar Proveedor para esta compra:", proveedores_validos, key="proveedor_especial")
            tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
            tienda_destino_especial = col_compra2.selectbox("Seleccionar Tienda Destino para esta compra:", tiendas_destino_validas, key="destino_compra_especial")
            
            st.dataframe(df_solicitud_compra[['SKU', 'Descripcion', 'Proveedor', 'Uds a Comprar']], use_container_width=True)
            if st.button("🗑️ Limpiar Compra Especial", key="btn_limpiar_compra_especial"):
                st.session_state.compra_especial_items = []
            
            st.markdown("##### 3. Finalizar y enviar la Compra Especial")
            email_dest_compra_especial = st.text_input("📧 Correo(s) del destinatario para la compra especial:", key="email_compra_especial", help="Separados por coma.")
            
            if st.button("✅ Enviar y Registrar Compra Especial", use_container_width=True, key="btn_enviar_compra_especial", type="primary"):
                if not df_solicitud_compra.empty:
                    with st.spinner("Registrando y enviando compra especial..."):
                        exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_solicitud_compra, "Compra Especial", proveedor_nombre=proveedor_especial, tienda_destino=tienda_destino_especial)
                        if exito_registro:
                            st.success(f"✅ Compra especial registrada. {msg_registro}")
                            st.session_state.compra_especial_items = []
                            st.cache_data.clear()
                        else:
                            st.error(f"❌ Error al registrar: {msg_registro}")
                else:
                    st.warning("La lista de compra está vacía.")

with tabs[3]:
    st.subheader("✅ Seguimiento y Recepción de Órdenes")
    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes desde Google Sheets o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        with st.expander("Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=False):
            st.markdown("##### Filtrar Órdenes")
            track_c1, track_c2, track_c3 = st.columns(3)
            estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
            filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, index=0, key="filtro_estado_seguimiento")
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
                select_all_seguimiento = st.checkbox("Seleccionar / Deseleccionar Todas las Órdenes Visibles", value=False, key="select_all_seguimiento")
                df_ordenes_vista['Seleccionar'] = select_all_seguimiento
                columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                st.info("Selecciona las órdenes y luego elige el nuevo estado para actualizarlas en lote.")
                edited_df_seguimiento = st.data_editor(
                    df_ordenes_vista[columnas_seguimiento], hide_index=True, use_container_width=True,
                    key="editor_seguimiento", disabled=[col for col in columnas_seguimiento if col != 'Seleccionar'])
                df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]
                if not df_seleccion_seguimiento.empty:
                    st.markdown("##### Acciones en Lote para Órdenes Seleccionadas")
                    nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                    if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} SKUs a '{nuevo_estado}'", key="btn_actualizar_estado"):
                        df_historico_modificado = df_ordenes_historico.copy()
                        df_historico_modificado['ID_unico_fila'] = df_historico_modificado['ID_Orden'] + "_" + df_historico_modificado['SKU'].astype(str)
                        df_seleccion_seguimiento['ID_unico_fila'] = df_seleccion_seguimiento['ID_Orden'] + "_" + df_seleccion_seguimiento['SKU'].astype(str)
                        ids_unicos_a_actualizar = df_seleccion_seguimiento['ID_unico_fila'].tolist()
                        df_historico_modificado.loc[df_historico_modificado['ID_unico_fila'].isin(ids_unicos_a_actualizar), 'Estado'] = nuevo_estado
                        df_historico_modificado.drop(columns=['ID_unico_fila'], inplace=True)
                        with st.spinner("Actualizando estados en Google Sheets..."):
                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                            if exito:
                                st.success(f"¡Éxito! {len(ids_unicos_a_actualizar)} líneas de orden actualizadas. Recargando...")
                                st.cache_data.clear()
                            else:
                                st.error(f"Error al actualizar Google Sheets: {msg}")
        st.markdown("---")
        with st.expander("🔍 Gestionar, Modificar o Reenviar una Orden Específica", expanded=True):
            orden_a_buscar = st.text_input("Buscar ID de Orden para modificar (ej: OC-2024..., TR-2024...):", key="search_orden_id")
            if st.button("Cargar Orden", key="btn_load_order"):
                if orden_a_buscar:
                    df_orden_cargada = df_ordenes_historico[df_ordenes_historico['ID_Orden'].str.startswith(orden_a_buscar.strip(), na=False)].copy()
                    if not df_orden_cargada.empty:
                        st.session_state.orden_modificada_df = df_orden_cargada
                        st.session_state.orden_cargada_id = orden_a_buscar.strip()
                        st.success(f"Orden '{st.session_state.orden_cargada_id}' cargada con {len(df_orden_cargada)} items.")
                    else:
                        st.error(f"No se encontró ninguna orden con el ID que comience por '{orden_a_buscar}'.")
                        st.session_state.orden_modificada_df = pd.DataFrame()
                        st.session_state.orden_cargada_id = None
                else:
                    st.warning("Por favor, ingrese un ID de orden para buscar.")
            if not st.session_state.orden_modificada_df.empty and st.session_state.orden_cargada_id:
                st.markdown(f"#### Editando Orden: **{st.session_state.orden_cargada_id}**")
                editor_key = f"editor_orden_{st.session_state.orden_cargada_id}"
                edited_orden_df = st.data_editor(
                    st.session_state.orden_modificada_df, key=editor_key, hide_index=True, use_container_width=True,
                    column_config={"Cantidad_Solicitada": st.column_config.NumberColumn(label="Cantidad", min_value=0, step=1),
                                   "Costo_Unitario": st.column_config.NumberColumn(label="Costo Unit.", format="$ %.2f")},
                    disabled=['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Tienda_Destino', 'Estado', 'Costo_Total'])
                if st.button("💾 Guardar Cambios", key="btn_save_changes"):
                    df_ordenes_historico['temp_id'] = df_ordenes_historico['ID_Orden'] + df_ordenes_historico['SKU'].astype(str)
                    edited_orden_df['temp_id'] = edited_orden_df['ID_Orden'] + edited_orden_df['SKU'].astype(str)
                    df_actualizado = df_ordenes_historico.set_index('temp_id')
                    df_cambios = edited_orden_df.set_index('temp_id')
                    df_actualizado.update(df_cambios)
                    df_actualizado.reset_index(drop=True, inplace=True)
                    with st.spinner("Guardando cambios en Google Sheets..."):
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_actualizado)
                        if exito:
                            st.success("¡Cambios guardados exitosamente!")
                            st.cache_data.clear()
                            st.session_state.orden_modificada_df = edited_orden_df
                        else:
                            st.error(f"Error al guardar: {msg}")
                st.markdown("---")
                st.markdown("##### Reenviar Notificaciones de la Orden (con cambios si los hay)")
                es_traslado = "TRASLADO" in edited_orden_df.iloc[0]['Proveedor']
                destinatario = edited_orden_df.iloc[0]['Tienda_Destino'] if es_traslado else edited_orden_df.iloc[0]['Proveedor']
                email_contacto, celular_contacto, nombre_contacto = "", "", ""
                if es_traslado:
                    info = CONTACTOS_TIENDAS.get(destinatario, {})
                    email_contacto, celular_contacto = info.get('email', ''), info.get('celular', '')
                else:
                    info = CONTACTOS_PROVEEDOR.get(destinatario, {})
                    celular_contacto, nombre_contacto = info.get('celular', ''), info.get('nombre', '')
                email_mod_dest = st.text_input("Correo(s) para notificación de cambio:", value=email_contacto, key="email_modificacion")
                pdf_mod_bytes = generar_pdf_orden_compra(edited_orden_df, destinatario, edited_orden_df.iloc[0]['Tienda_Destino'], "N/A", nombre_contacto, st.session_state.orden_cargada_id)
                excel_mod_bytes = generar_excel_dinamico(edited_orden_df, f"Orden_{st.session_state.orden_cargada_id}")
                mod_c1, mod_c2 = st.columns(2)
                with mod_c1:
                    if st.button("✉️ Enviar Correo con Corrección", key="btn_email_mod"):
                        if email_mod_dest:
                             with st.spinner("Enviando correo..."):
                                asunto = f"CORRECCIÓN: Orden {st.session_state.orden_cargada_id} de Ferreinox"
                                cuerpo_html = f"<html><body><p>Hola,</p><p>Se ha realizado una corrección en la orden <b>{st.session_state.orden_cargada_id}</b>. Por favor, tomar en cuenta la versión adjunta como la definitiva.</p><p>Gracias.</p><p>--<br>Ferreinox SAS BIC</p></body></html>"
                                adjuntos = [{'datos': pdf_mod_bytes, 'nombre_archivo': f"CORRECCION_OC_{st.session_state.orden_cargada_id}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                            {'datos': excel_mod_bytes, 'nombre_archivo': f"CORRECCION_Detalle_{st.session_state.orden_cargada_id}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                lista_destinatarios = [email.strip() for email in email_mod_dest.split(',') if email.strip()]
                                enviado, msg = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                if enviado: st.success(msg)
                                else: st.error(msg)
                        else:
                            st.warning("Ingrese un correo para enviar la notificación.")
                with mod_c2:
                     if celular_contacto:
                        mensaje_wpp = f"Hola, se ha enviado una CORRECCIÓN de la orden {st.session_state.orden_cargada_id} al correo. Por favor revisar. Gracias."
                        link_wpp = generar_link_whatsapp(celular_contacto, mensaje_wpp)
                        st.link_button("📲 Notificar Corrección por WhatsApp", link_wpp, target="_blank", use_container_width=True)
