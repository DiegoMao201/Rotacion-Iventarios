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

# --- NUEVO: LIBRERÍAS PARA GOOGLE SHEETS ---
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento v2.3", layout="wide", page_icon="🚀")

st.title("🚀 Tablero de Control de Abastecimiento v2.3")
st.markdown("Analiza, prioriza, actúa y registra. Tu sistema de gestión en tiempo real.")

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

def check_or_create_worksheet(client, spreadsheet_key, sheet_name, headers):
    """Verifica si una hoja existe, si no, la crea con las cabeceras dadas."""
    try:
        spreadsheet = client.open_by_key(spreadsheet_key)
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except WorksheetNotFound:
            st.warning(f"No se encontró la hoja '{sheet_name}'. Creando una nueva...")
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="1", cols=len(headers))
            worksheet.append_row(headers, value_input_option='USER_ENTERED')
            st.success(f"Hoja '{sheet_name}' creada exitosamente.")
        return worksheet
    except Exception as e:
        st.error(f"Error al verificar/crear la hoja '{sheet_name}': {e}")
        return None

@st.cache_data(ttl=60)
def load_data_from_sheet(_client, sheet_name):
    """Carga datos desde una hoja de Google Sheets, manejando si está vacía."""
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        data = worksheet.get_all_records()
        if not data:
            return pd.DataFrame() # Retorna DF vacío si no hay registros
        df = pd.DataFrame(data)
        if 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str)
        return df
    except Exception as e:
        st.error(f"Ocurrió un error al cargar datos de la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    """Sobrescribe una hoja completa con un DataFrame."""
    if client is None: return False, "Cliente de Google Sheets no está disponible."
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        worksheet.update([df_to_write.columns.values.tolist()] + df_to_write.astype(str).values.tolist())
        return True, f"Hoja '{sheet_name}' actualizada."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Añade filas a una hoja."""
    if client is None: return False, "Cliente de Google Sheets no está disponible."
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.append_rows(df_to_append.astype(str).values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Registros añadidos a '{sheet_name}'."
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}"


# --- 2. FUNCIONES AUXILIARES (LÓGICA ORIGINAL) ---

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
def generar_plan_traslados_inteligente(_df_analisis_maestro):
    if _df_analisis_maestro is None or _df_analisis_maestro.empty: return pd.DataFrame()
    df_origen = _df_analisis_maestro[_df_analisis_maestro['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis_maestro[_df_analisis_maestro['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()
    if df_origen.empty or df_destino.empty: return pd.DataFrame()
    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()
    for _, necesidad_row in df_destino.iterrows():
        sku, tienda_necesitada, necesidad_actual = necesidad_row['SKU'], necesidad_row['Almacen_Nombre'], necesidad_row['Necesidad_Total']
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
                    'Proveedor': origen_row['Proveedor'],
                    'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,
                    'Stock en Origen': origen_row['Stock'], 'Tienda Destino': tienda_necesitada,
                    'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],
                    'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row.get('Peso_Articulo', 0),
                    'Valor Individual': necesidad_row['Costo_Promedio_UND']
                })
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        try:
            self.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf', uni=True)
            self.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf', uni=True)
        except RuntimeError: st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica.")
    def header(self):
        try: self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError: self.set_xy(10, 8); self.set_font('Helvetica', 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font('DejaVu', 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R'); self.set_x(80); self.set_font('DejaVu', '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R'); self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)
    def footer(self):
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1); self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font('DejaVu', '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}      |       {self.empresa_web}      |       {self.empresa_email}      |       {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor):
    # (El código de esta función es idéntico al original, no se necesita modificar)
    if df_seleccion.empty: return None
    pdf = PDF()
    pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font("DejaVu", 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1); pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 9)
    y_start = pdf.get_y()
    proveedor_info = f"Razón Social: {proveedor_nombre}\nContacto: {contacto_proveedor if contacto_proveedor else 'No especificado'}"
    pdf.multi_cell(95, 7, proveedor_info, 1, 'L')
    y_end_prov = pdf.get_y()
    pdf.set_y(y_start); pdf.set_x(105)
    envio_info = f"{pdf.empresa_nombre} - Sede {tienda_nombre}\nDirección: {direccion_entrega}\nRecibe: Leivyn Gabriel Garcia"
    pdf.multi_cell(95, 7, envio_info, 1, 'L')
    y_end_envio = pdf.get_y()
    pdf.set_y(max(y_end_prov, y_end_envio))
    pdf.ln(5)
    pdf.set_font("DejaVu", 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {st.session_state.get('current_order_id', 'N/A')}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1); pdf.ln(10)
    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font("DejaVu", 'B', 9)
    pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
    pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
    pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 8); pdf.set_text_color(0, 0, 0)
    subtotal = 0
    for _, row in df_seleccion.iterrows():
        costo_total_item = row['Uds a Comprar'] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x_start_cell, y_start_cell = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
        y1 = pdf.get_y(); pdf.set_xy(x_start_cell + 25, y_start_cell)
        pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
        y2 = pdf.get_y(); pdf.set_xy(x_start_cell + 55, y_start_cell)
        pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L')
        y3 = pdf.get_y()
        row_height = max(y1, y2, y3) - y_start_cell
        pdf.set_xy(x_start_cell + 125, y_start_cell); pdf.multi_cell(15, row_height, str(int(row['Uds a Comprar'])), 1, 'C')
        pdf.set_xy(x_start_cell + 140, y_start_cell); pdf.multi_cell(25, row_height, f"${row['Costo_Promedio_UND']:,.2f}", 1, 'R')
        pdf.set_xy(x_start_cell + 165, y_start_cell); pdf.multi_cell(25, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        pdf.set_y(y_start_cell + row_height)
    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font("DejaVu", '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font("DejaVu", 'B', 11)
    pdf.cell(55, 10, 'TOTAL A PAGAR', 1, 0, 'R'); pdf.cell(35, 10, f"${total_general:,.2f}", 1, 1, 'R')
    return bytes(pdf.output())

@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    # (El código de esta función es idéntico al original, no se necesita modificar)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70); return output.getvalue()
        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        for col_num, value in enumerate(df.columns.values): worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4; worksheet.set_column(i, i, min(width, 45))
    return output.getvalue()

# --- 3. LÓGICA PRINCIPAL DE LA APLICACIÓN ---

# PASO 1: Cargar datos locales y verificar estado de sesión
if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop()

# PASO 2: Conectar a GSheets y preparar las hojas de trabajo
client = connect_to_gsheets()
if client:
    spreadsheet_key = st.secrets["gsheets"]["spreadsheet_key"]
    # Asegurar que las hojas existan
    check_or_create_worksheet(client, spreadsheet_key, "Estado_Inventario", st.session_state['df_analisis_maestro'].columns.tolist())
    check_or_create_worksheet(client, spreadsheet_key, "Registro_Ordenes", ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado'])
    
    # Sincronizar el inventario base al iniciar
    with st.spinner("Sincronizando estado de inventario inicial con Google Sheets..."):
        update_sheet(client, "Estado_Inventario", st.session_state['df_analisis_maestro'])

# PASO 3: Cargar órdenes y calcular stock en tránsito
df_ordenes_historico = load_data_from_sheet(client, "Registro_Ordenes")

df_maestro = st.session_state['df_analisis_maestro'].copy()

if not df_ordenes_historico.empty and 'Estado' in df_ordenes_historico.columns:
    df_pendientes = df_ordenes_historico[df_ordenes_historico['Estado'] == 'Pendiente'].copy()
    if not df_pendientes.empty:
        df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
        stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
        stock_en_transito_agg = stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito', 'Tienda_Destino': 'Almacen_Nombre'})
        stock_en_transito_agg['SKU'] = stock_en_transito_agg['SKU'].astype(str)
        df_maestro['SKU'] = df_maestro['SKU'].astype(str)
        
        df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Stock_En_Transito'].fillna(0, inplace=True)
    else:
        df_maestro['Stock_En_Transito'] = 0
else:
    df_maestro['Stock_En_Transito'] = 0

# PASO 4: Recalcular necesidades
df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
df_maestro['Necesidad_Total'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)
df_maestro['Sugerencia_Compra'] = df_maestro['Necesidad_Total']
if 'Precio_Venta_Estimado' not in df_maestro.columns:
    df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * 1.30


# --- LÓGICA DE FILTROS Y UI (Original) ---
st.sidebar.header("⚙️ Filtros de Gestión")
opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
if st.session_state.get('user_role') == 'gerente':
    almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
else:
    almacen_options = [st.session_state.get('almacen_nombre')]
selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista de Tienda:", almacen_options)

if selected_almacen_nombre == opcion_consolidado: df_vista = df_maestro.copy()
else: df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else df_vista

DIRECCIONES_TIENDAS = {'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32'}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893'},
}

# --- PESTAÑAS DE LA APLICACIÓN ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"])

with tab1:
    # (El código de esta pestaña es idéntico al original, no se necesita modificar)
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
    df_origen_kpi = df_maestro[df_maestro['Excedente_Trasladable'] > 0]
    df_destino_kpi = df_filtered[df_filtered['Necesidad_Total'] > 0]
    oportunidad_ahorro = 0
    if not df_origen_kpi.empty and not df_destino_kpi.empty:
        df_sugerencias_kpi = pd.merge(df_origen_kpi.groupby('SKU').agg(Total_Excedente_Global=('Excedente_Trasladable', 'sum'),Costo_Promedio_UND=('Costo_Promedio_UND', 'mean')), df_destino_kpi.groupby('SKU').agg(Total_Necesidad_Tienda=('Necesidad_Total', 'sum')), on='SKU', how='inner')
        df_sugerencias_kpi['Ahorro_Potencial'] = np.minimum(df_sugerencias_kpi['Total_Excedente_Global'], df_sugerencias_kpi['Total_Necesidad_Tienda'])
        oportunidad_ahorro = (df_sugerencias_kpi['Ahorro_Potencial'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()
    df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
    venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label="💰 Valor Compra Requerida", value=f"${necesidad_compra_total:,.0f}")
    kpi2.metric(label="💸 Ahorro por Traslados", value=f"${oportunidad_ahorro:,.0f}")
    kpi3.metric(label="📉 Venta Potencial Perdida", value=f"${venta_perdida:,.0f}")
    st.markdown("##### Análisis y Recomendaciones Clave")
    with st.container(border=True):
        if venta_perdida > 0: st.markdown(f"**🚨 Alerta:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** en 30 días por **{len(df_quiebre)}** productos en quiebre.")
        if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña de 'Plan de Traslados'.")
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
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Total Requerida por Tienda")
            st.plotly_chart(fig, use_container_width=True)
    with col_g2:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    # (El código de esta pestaña es idéntico al original, no se necesita modificar)
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        with st.spinner("Calculando plan de traslados óptimo..."):
            df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            # (Resto del código de la pestaña de traslados idéntico al original)
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
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"), "Seleccionar": st.column_config.CheckboxColumn(required=True), "Stock en Origen": st.column_config.NumberColumn(format="%d"), "Stock en Destino": st.column_config.NumberColumn(format="%d"), "Necesidad en Destino": st.column_config.NumberColumn(format="%d")},
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']], key="editor_traslados"
                )
                df_seleccionados_traslado = edited_df_traslados[edited_df_traslados['Seleccionar']]
                if not df_seleccionados_traslado.empty:
                    st.markdown("---")
                    email_dest_traslado = st.text_input("📧 Correo del destinatario para el plan de traslado:", key="email_traslado", help="Puede ser uno o varios correos separados por coma o punto y coma.")
                    t_c1, t_c2 = st.columns(2)
                    with t_c1:
                        if st.button("✉️ Enviar Plan por Correo", use_container_width=True, key="btn_enviar_traslado"):
                           # Lógica de envío de correo... (idéntica)
                           pass
                    with t_c2:
                        st.download_button("📥 Descargar Plan (Excel)", data=generar_excel_dinamico(df_seleccionados_traslado, "Plan_de_Traslados"), file_name="Plan_de_Traslado.xlsx", use_container_width=True)

with tab3:
    st.header("🛒 Plan de Compras")

    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        # ... (código original sin cambios) ...
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        if not df_plan_compras.empty:
            # ... (código original sin cambios) ...
            df_seleccionados = ... # Lógica del data editor
            if not df_seleccionados.empty:
                # ...
                if st.button("✉️ Enviar por Correo", ...):
                    # ...
                    enviado, mensaje = enviar_correo_con_adjuntos(...)
                    if enviado:
                        st.success(mensaje)
                        # --- NUEVO: REGISTRAR ORDEN EN GSHEETS ---
                        order_id = f"OC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                        df_para_registrar = df_seleccionados.copy()
                        df_para_registrar['ID_Orden'] = order_id
                        df_para_registrar['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d')
                        df_para_registrar['Estado'] = 'Pendiente'
                        df_para_registrar.rename(columns={
                            'Uds a Comprar': 'Cantidad_Solicitada',
                            'Tienda': 'Tienda_Destino'
                        }, inplace=True)
                        columnas_registro = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                        
                        exito_registro, msg_registro = append_to_sheet(client, "Registro_Ordenes", df_para_registrar[columnas_registro])
                        if exito_registro:
                            st.info(f"Orden de compra registrada en Google Sheets con ID: {order_id}")
                        else:
                            st.error(f"No se pudo registrar la orden en Google Sheets: {msg_registro}")
                        # --- FIN DEL NUEVO BLOQUE ---

    with st.expander("🆕 **Compras Especiales (Búsqueda Inteligente y Manual)**", expanded=True):
        # ... (código original sin cambios) ...
        if st.session_state.compra_especial_items:
            # ... (código original sin cambios) ...
            if st.button("✉️ Enviar Correo", ...):
                # ...
                enviado_sp, mensaje_sp = enviar_correo_con_adjuntos(...)
                if enviado_sp:
                    st.success(mensaje_sp)
                    # --- NUEVO: REGISTRAR ORDEN ESPECIAL EN GSHEETS ---
                    order_id_sp = f"OC-SP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    df_seleccionados_sp = pd.DataFrame(st.session_state.compra_especial_items)
                    df_para_registrar_sp = df_seleccionados_sp.copy()
                    df_para_registrar_sp['ID_Orden'] = order_id_sp
                    df_para_registrar_sp['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d')
                    df_para_registrar_sp['Estado'] = 'Pendiente'
                    df_para_registrar_sp['Proveedor'] = nuevo_proveedor_nombre # El proveedor ingresado manualmente
                    df_para_registrar_sp.rename(columns={
                        'Uds a Comprar': 'Cantidad_Solicitada',
                        'Tienda': 'Tienda_Destino'
                    }, inplace=True)
                    columnas_registro = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']

                    exito_registro, msg_registro = append_to_sheet(client, "Registro_Ordenes", df_para_registrar_sp[columnas_registro])
                    if exito_registro:
                        st.info(f"Orden especial registrada en Google Sheets con ID: {order_id_sp}")
                    else:
                        st.error(f"No se pudo registrar la orden especial en Google Sheets: {msg_registro}")
                    # --- FIN DEL NUEVO BLOQUE ---

with tab4:
    st.subheader("✅ Seguimiento y Recepción de Órdenes")

    if df_ordenes_historico.empty:
        st.info("Aún no hay órdenes registradas en Google Sheets. Genere una desde la pestaña 'Compras'.")
    else:
        df_ordenes_vista = df_ordenes_historico.copy()
        
        st.markdown("##### Filtrar Órdenes")
        track_c1, track_c2, track_c3 = st.columns(3)
        
        estados_disponibles = ["Todos"] + df_ordenes_vista['Estado'].unique().tolist()
        filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, index=estados_disponibles.index("Pendiente") if "Pendiente" in estados_disponibles else 0)
        
        if filtro_estado != "Todos":
            df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Estado'] == filtro_estado]

        # (Resto de los filtros igual que en el código de fusión anterior)

        if df_ordenes_vista.empty:
            st.info("No hay órdenes que coincidan con los filtros seleccionados.")
        else:
            df_ordenes_vista['Seleccionar'] = False
            columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
            
            edited_df_seguimiento = st.data_editor(
                df_ordenes_vista[columnas_seguimiento],
                hide_index=True, use_container_width=True, key="editor_seguimiento",
                disabled=[col for col in columnas_seguimiento if col != 'Seleccionar']
            )

            df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]

            if not df_seleccion_seguimiento.empty:
                st.markdown("---")
                st.markdown("##### Acciones para Órdenes Seleccionadas")
                
                nuevo_estado = st.selectbox("Cambiar estado a:", ["Recibido", "Cancelado"], key="nuevo_estado_lote")
                
                if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} órdenes a '{nuevo_estado}'"):
                    # Identificar filas a actualizar por un identificador único. SKU + ID_Orden es más seguro.
                    ids_a_actualizar = df_seleccion_seguimiento[['ID_Orden', 'SKU']].to_records(index=False)
                    set_ids_a_actualizar = set(ids_a_actualizar)
                    
                    df_historico_modificado = df_ordenes_historico.copy()
                    
                    # Crear una columna temporal para la comparación
                    df_historico_modificado['temp_id'] = list(zip(df_historico_modificado['ID_Orden'], df_historico_modificado['SKU'].astype(str)))
                    
                    # Actualizar estado
                    df_historico_modificado.loc[df_historico_modificado['temp_id'].isin(set_ids_a_actualizar), 'Estado'] = nuevo_estado
                    
                    df_historico_modificado.drop(columns=['temp_id'], inplace=True)
                    
                    with st.spinner("Actualizando estados en Google Sheets..."):
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                        
                        if exito:
                            st.success(f"¡Éxito! Se actualizaron los estados. La página se recargará para reflejar los cambios.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Error al actualizar Google Sheets: {msg}")
