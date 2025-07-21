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
st.set_page_config(page_title="Gestión de Abastecimiento v2.3", layout="wide", page_icon="🚀")

st.title("🚀 Tablero de Control de Abastecimiento v2.3")
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
    except Exception as e:
        st.error(f"Ocurrió un error al cargar la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    """Sobrescribe una hoja completa con un DataFrame de Pandas."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        worksheet.update([df_to_write.columns.values.tolist()] + df_to_write.astype(str).values.tolist())
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Añade filas a una hoja sin sobreescribir."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        # Asegurarse que las columnas del DF coinciden con las de la hoja
        headers = worksheet.row_values(1)
        df_to_append_ordered = df_to_append[headers]
        worksheet.append_rows(df_to_append_ordered.astype(str).values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Nuevos registros añadidos a '{sheet_name}'."
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}"

def registrar_ordenes_en_sheets(client, df_orden, tipo_orden="Compra"):
    """Prepara y registra un DataFrame de órdenes (compra o traslado) en la hoja 'Registro_Ordenes'."""
    if df_orden.empty or client is None:
        return False, "No hay datos para registrar."

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    df_registro = pd.DataFrame()

    if tipo_orden == "Compra":
        df_registro['ID_Orden'] = [f"OC-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = df_orden['Proveedor']
        df_registro['Tienda_Destino'] = df_orden['Tienda']
    elif tipo_orden == "Traslado":
        df_registro['ID_Orden'] = [f"TR-{timestamp}-{i}" for i in range(len(df_orden))]
        df_registro['Proveedor'] = "TRASLADO INTERNO: " + df_orden['Tienda Origen']
        df_registro['Tienda_Destino'] = df_orden['Tienda Destino']
    else:
        return False, "Tipo de orden no reconocido."

    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    df_registro['SKU'] = df_orden['SKU']
    df_registro['Descripcion'] = df_orden['Descripcion']
    df_registro['Cantidad_Solicitada'] = df_orden['Uds a Enviar'] if tipo_orden == "Traslado" else df_orden['Uds a Comprar']
    df_registro['Estado'] = 'Pendiente'
    df_registro['Costo_Unitario'] = df_orden.get('Costo_Promedio_UND', 0)
    df_registro['Costo_Total'] = df_registro['Cantidad_Solicitada'] * df_registro['Costo_Unitario']

    # Asegurar que todas las columnas de la hoja de destino existan
    columnas_destino = ['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado', 'Costo_Unitario', 'Costo_Total']
    for col in columnas_destino:
        if col not in df_registro:
            df_registro[col] = '' # o un valor por defecto apropiado

    return append_to_sheet(client, "Registro_Ordenes", df_registro)


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
def generar_plan_traslados_inteligente(_df_analisis_maestro):
    """Genera un plan de traslados óptimo incluyendo la información del proveedor."""
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
                    'Valor Individual': necesidad_row['Costo_Promedio_UND'],
                    'Costo_Promedio_UND': necesidad_row['Costo_Promedio_UND']
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
            # Asegúrate de tener estos archivos en una carpeta 'fonts' en el mismo nivel que tu script
            self.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf', uni=True)
            self.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf', uni=True)
        except RuntimeError: 
            st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica. Algunos caracteres pueden no mostrarse.")
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
        footer_text = f"{self.empresa_nombre}      |       {self.empresa_web}       |       {self.empresa_email}       |       {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font("DejaVu", 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1); pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 9)
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
    pdf.set_font("DejaVu", 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {datetime.now().strftime('%Y%m%d-%H%M')}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1); pdf.ln(10)
    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font("DejaVu", 'B', 9)
    pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
    pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
    pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 8); pdf.set_text_color(0, 0, 0)
    subtotal = 0
    uds_a_comprar_col = 'Uds a Comprar' if 'Uds a Comprar' in df_seleccion.columns else 'Uds a Enviar'
    for _, row in df_seleccion.iterrows():
        costo_total_item = row[uds_a_comprar_col] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
        y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
        pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
        y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
        pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L')
        y3 = pdf.get_y()
        row_height = max(y1, y2, y3) - y_start
        pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(row[uds_a_comprar_col])), 1, 'C')
        pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${row['Costo_Promedio_UND']:,.2f}", 1, 'R')
        pdf.set_xy(x_start + 165, y_start); pdf.multi_cell(25, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        pdf.set_y(y_start + row_height)
    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font("DejaVu", '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font("DejaVu", 'B', 11)
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
            column_len = df[col].astype(str).map(len)
            max_len = max(column_len.max(), len(col)) + 2
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

# PASO 4: Recalcular las necesidades y excedentes con la nueva información
numeric_cols = ['Stock', 'Stock_En_Transito', 'Sugerencia_Compra', 'Costo_Promedio_UND', 'Necesidad_Total', 'Excedente_Trasladable']
for col in numeric_cols:
    if col in df_maestro.columns:
        df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)

# El cálculo final que potencia la app
df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
# Ajustamos la necesidad inicial restando lo que ya está en tránsito
df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)

# *** NUEVA LÓGICA DE OPTIMIZACIÓN ***
# 1. Generar plan de traslados basado en la necesidad ajustada por tránsito
df_maestro_para_traslados = df_maestro.copy()
df_maestro_para_traslados['Necesidad_Total'] = df_maestro_para_traslados['Necesidad_Ajustada_Por_Transito']
df_plan_maestro = generar_plan_traslados_inteligente(df_maestro_para_traslados)

# 2. Calcular las unidades que se cubrirán con traslados por SKU y Tienda Destino
if not df_plan_maestro.empty:
    unidades_cubiertas_por_traslado = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
    unidades_cubiertas_por_traslado.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado'}, inplace=True)

    # 3. Fusionar esta información de vuelta al DataFrame maestro
    df_maestro = pd.merge(df_maestro, unidades_cubiertas_por_traslado, on=['SKU', 'Almacen_Nombre'], how='left')
    df_maestro['Cubierto_Por_Traslado'].fillna(0, inplace=True)
else:
    df_maestro['Cubierto_Por_Traslado'] = 0

# 4. Calcular la Sugerencia de Compra FINAL
df_maestro['Sugerencia_Compra'] = (df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
# *** FIN DE LA NUEVA LÓGICA ***

if 'Precio_Venta_Estimado' not in df_maestro.columns:
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
        # Seleccionar solo las columnas relevantes de tu análisis base
        columnas_a_sincronizar = [
            'SKU', 'Almacen_Nombre', 'Stock', 'Costo_Promedio_UND', 'Sugerencia_Compra', 
            'Necesidad_Total', 'Excedente_Trasladable', 'Estado_Inventario'
            # Añade aquí cualquier otra columna de tu archivo base que quieras tener en la hoja
        ]
        df_para_sincronizar = df_maestro_base[columnas_a_sincronizar].copy()
        exito, msg = update_sheet(client, "Estado_Inventario", df_para_sincronizar)
        if exito:
            st.sidebar.success(msg)
        else:
            st.sidebar.error(msg)

DIRECCIONES_TIENDAS = {'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32'}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893'},
}

# --- 4. INTERFAZ DE USUARIO CON PESTAÑAS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Diagnóstico", "🔄 Traslados", "🛒 Compras", "✅ Seguimiento"])

# --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
with tab1:
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
    
    oportunidad_ahorro = 0
    if not df_plan_maestro.empty:
        if selected_almacen_nombre == opcion_consolidado:
            oportunidad_ahorro = (df_plan_maestro['Uds a Enviar'] * df_plan_maestro['Valor Individual']).sum()
        else:
            oportunidad_ahorro = (df_plan_maestro[df_plan_maestro['Tienda Destino'] == selected_almacen_nombre]['Uds a Enviar'] * df_plan_maestro['Valor Individual']).sum()
            
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
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Requerida por Tienda (Post-Traslados)")
            st.plotly_chart(fig, use_container_width=True)
    with col_g2:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
            st.plotly_chart(fig, use_container_width=True)

# --- PESTAÑA 2: PLAN DE TRASLADOS ---
with tab2:
    st.subheader("🚚 Plan de Traslados entre Tiendas")

    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        # El df_plan_maestro ya fue calculado al inicio
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
                df_para_editar = df_traslados_filtrado.copy()
                df_para_editar['Seleccionar'] = False

                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Marca_Nombre', 'Tienda Origen',
                                     'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Necesidad en Destino', 'Uds a Enviar']

                edited_df_traslados = st.data_editor(
                    df_para_editar[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={
                        "Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                        "Seleccionar": st.column_config.CheckboxColumn(required=True),
                        "Stock en Origen": st.column_config.NumberColumn(format="%d"),
                        "Stock en Destino": st.column_config.NumberColumn(format="%d"),
                        "Necesidad en Destino": st.column_config.NumberColumn(format="%d")
                    },
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']],
                    key="editor_traslados"
                )

                df_seleccionados_traslado = edited_df_traslados[edited_df_traslados['Seleccionar']]

                if not df_seleccionados_traslado.empty:
                    df_seleccionados_traslado = df_seleccionados_traslado.copy()
                    # Merge para traer info de peso y valor que no está en la tabla editable
                    df_seleccionados_traslado = pd.merge(
                        df_seleccionados_traslado,
                        df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND']],
                        on=['SKU', 'Tienda Origen', 'Tienda Destino'],
                        how='left'
                    )
                    df_seleccionados_traslado['Peso del Traslado (kg)'] = df_seleccionados_traslado['Uds a Enviar'] * df_seleccionados_traslado['Peso Individual (kg)']
                    
                    st.markdown("---")
                    
                    total_unidades = df_seleccionados_traslado['Uds a Enviar'].sum()
                    total_peso = df_seleccionados_traslado['Peso del Traslado (kg)'].sum()
                    st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")
                    
                    email_dest_traslado = st.text_input("📧 Correo del destinatario para el plan de traslado:", key="email_traslado", help="Puede ser uno o varios correos separados por coma o punto y coma.")

                    if st.button("✅ Confirmar y Registrar Traslado", use_container_width=True, key="btn_registrar_traslado", type="primary"):
                        if not df_seleccionados_traslado.empty:
                            with st.spinner("Registrando traslado en Google Sheets y enviando notificaciones..."):
                                # 1. Registrar en Google Sheets
                                exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_seleccionados_traslado, tipo_orden="Traslado")
                                
                                if exito_registro:
                                    st.success(f"✅ ¡Traslado registrado exitosamente en Google Sheets! ({msg_registro})")
                                    
                                    # 2. Enviar correo si se proporcionó un destinatario
                                    if email_dest_traslado:
                                        excel_bytes = generar_excel_dinamico(df_seleccionados_traslado.drop(columns=['Peso Individual (kg)', 'Costo_Promedio_UND']), "Plan_de_Traslados")
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

# --- PESTAÑA 3: PLAN DE COMPRAS ---
with tab3:
    st.header("🛒 Plan de Compras")

    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        if df_plan_compras.empty:
            st.info("¡Excelente! No hay sugerencias de compra con los filtros actuales. El inventario está optimizado con los traslados.")
        else:
            df_plan_compras['Proveedor'] = df_plan_compras['Proveedor'].str.upper()
            proveedores_disponibles = ["Todos"] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores")

            df_a_mostrar = df_plan_compras.copy()
            if selected_proveedor != 'Todos':
                df_a_mostrar = df_a_mostrar[df_a_mostrar['Proveedor'] == selected_proveedor]

            select_all = st.checkbox("Seleccionar / Deseleccionar Todos los Productos Visibles", key="select_all_suggested")

            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].astype(int)
            df_a_mostrar['Seleccionar'] = select_all
            
            columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})[columnas]

            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df = st.data_editor(df_a_mostrar_final, hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']],
                key="editor_principal")

            df_seleccionados = edited_df[edited_df['Seleccionar']]

            if not df_seleccionados.empty:
                df_seleccionados = df_seleccionados.copy()
                df_seleccionados['Valor de la Compra'] = df_seleccionados['Uds a Comprar'] * df_seleccionados['Costo_Promedio_UND']

                st.markdown("---")

                es_proveedor_unico = selected_proveedor != 'Todos' and selected_proveedor != 'NO ASIGNADO'

                if es_proveedor_unico:
                    email_dest = st.text_input("📧 Correos del destinatario (separados por coma o punto y coma):", key="email_principal", help="Ej: correo1@ejemplo.com, correo2@ejemplo.com")
                else:
                    st.info("Para generar un PDF o enviar una orden por correo, por favor seleccione un proveedor específico desde el filtro superior.")
                    email_dest = ""

                c1, c2, c3 = st.columns(3)

                with c1:
                    excel_data = generar_excel_dinamico(df_seleccionados, "compra")
                    file_name_excel = f"Compra_{selected_proveedor if es_proveedor_unico else 'Consolidado'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    st.download_button("📥 Descargar Excel", data=excel_data, file_name=file_name_excel, use_container_width=True)

                pdf_bytes = None
                if es_proveedor_unico:
                    tienda_entrega = df_seleccionados['Tienda'].iloc[0] # Asumimos misma tienda para un proveedor
                    direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_entrega, "N/A")
                    info_proveedor = CONTACTOS_PROVEEDOR.get(selected_proveedor, {})
                    contacto_proveedor = info_proveedor.get('nombre', '')
                    celular_proveedor = info_proveedor.get('celular', '')
                    pdf_bytes = generar_pdf_orden_compra(df_seleccionados, selected_proveedor, tienda_entrega, direccion_entrega, contacto_proveedor)

                with c2:
                    if st.button("✉️ Enviar y Registrar Orden", disabled=(not es_proveedor_unico or pdf_bytes is None), use_container_width=True, key="btn_enviar_principal", type="primary"):
                        if email_dest:
                            with st.spinner("Enviando correo y registrando orden en Google Sheets..."):
                                # 1. Enviar Correo
                                email_string = email_dest.replace(';', ',')
                                lista_destinatarios = [email.strip() for email in email_string.split(',') if email.strip()]
                                asunto = f"Nueva Orden de Compra de Ferreinox SAS BIC - {selected_proveedor}"
                                cuerpo_html = f"<html><body><p>Estimados Sres. {selected_proveedor},</p><p>Adjunto a este correo encontrarán nuestra orden de compra N° {datetime.now().strftime('%Y%m%d-%H%M')}.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_entrega}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión y quedamos atentos a la confirmación.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC<br>Tel: 312 7574279<br>compras@ferreinox.co</p></body></html>"
                                adjunto_sugerencia = [{'datos': pdf_bytes, 'nombre_archivo': f"OC_Ferreinox_{selected_proveedor.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'}]
                                enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_sugerencia)
                                
                                if enviado:
                                    st.success(mensaje)
                                    # 2. Registrar en Google Sheets
                                    exito_registro, msg_registro = registrar_ordenes_en_sheets(client, df_seleccionados, tipo_orden="Compra")
                                    if exito_registro:
                                        st.success(f"¡Orden registrada en Google Sheets! {msg_registro}")
                                        # 3. Notificar por WhatsApp
                                        if celular_proveedor:
                                            numero_completo = celular_proveedor.strip()
                                            if not numero_completo.startswith('57'): numero_completo = '57' + numero_completo
                                            mensaje_wpp = f"Hola {contacto_proveedor}, te acabamos de enviar la Orden de Compra N° {datetime.now().strftime('%Y%m%d-%H%M')} al correo. Quedamos atentos. ¡Gracias!"
                                            link_wpp = generar_link_whatsapp(numero_completo, mensaje_wpp)
                                            st.link_button("📲 Enviar Confirmación por WhatsApp", link_wpp)
                                        
                                        st.info("Recargando la página para reflejar los cambios...")
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error(f"La orden fue enviada por correo, pero falló el registro en Google Sheets: {msg_registro}")
                                else:
                                    st.error(mensaje)
                        else:
                            st.warning("Por favor, ingresa al menos un correo electrónico de destinatario.")

                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes or b"", file_name=f"OC_{selected_proveedor}.pdf", use_container_width=True, disabled=(not es_proveedor_unico or pdf_bytes is None))

                st.info(f"Total de la selección para **{selected_proveedor}**: ${df_seleccionados['Valor de la Compra'].sum():,.0f}")

# --- PESTAÑA 4: SEGUIMIENTO Y RECEPCIÓN ---
with tab4:
    st.subheader("✅ Seguimiento y Recepción de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes desde Google Sheets o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        
        # Filtros para el seguimiento
        st.markdown("##### Filtrar Órdenes")
        track_c1, track_c2, track_c3 = st.columns(3)
        
        # Filtro por estado
        estados_disponibles = ["Todos"] + df_ordenes_vista['Estado'].unique().tolist()
        filtro_estado = track_c1.selectbox("Estado de la Orden:", estados_disponibles, key="filtro_estado_seguimiento")
        if filtro_estado != "Todos":
            df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Estado'] == filtro_estado]

        # Filtro por proveedor
        proveedores_ordenes = ["Todos"] + sorted(df_ordenes_vista['Proveedor'].unique().tolist())
        filtro_proveedor_orden = track_c2.selectbox("Proveedor/Origen:", proveedores_ordenes, key="filtro_proveedor_seguimiento")
        if filtro_proveedor_orden != "Todos":
            df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Proveedor'] == filtro_proveedor_orden]

        # Filtro por tienda destino
        tiendas_ordenes = ["Todos"] + sorted(df_ordenes_vista['Tienda_Destino'].unique().tolist())
        filtro_tienda_orden = track_c3.selectbox("Tienda Destino:", tiendas_ordenes, key="filtro_tienda_seguimiento")
        if filtro_tienda_orden != "Todos":
            df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Tienda_Destino'] == filtro_tienda_orden]


        if df_ordenes_vista.empty:
            st.info("No hay órdenes que coincidan con los filtros seleccionados.")
        else:
            # Añadir una columna de selección para actualizar el estado
            df_ordenes_vista['Seleccionar'] = False
            
            columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
            
            st.markdown("##### Gestionar Estado de Órdenes")
            st.info("Selecciona las órdenes y luego elige el nuevo estado para actualizarlas en lote.")
            
            edited_df_seguimiento = st.data_editor(
                df_ordenes_vista[columnas_seguimiento],
                hide_index=True,
                use_container_width=True,
                key="editor_seguimiento",
                disabled=[col for col in columnas_seguimiento if col != 'Seleccionar']
            )

            df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]

            if not df_seleccion_seguimiento.empty:
                st.markdown("---")
                st.markdown("##### Acciones en Lote para Órdenes Seleccionadas")
                
                nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                
                if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} órdenes a '{nuevo_estado}'", key="btn_actualizar_estado"):
                    ids_a_actualizar = df_seleccion_seguimiento['ID_Orden'].tolist()
                    
                    # Copia del dataframe histórico para modificar
                    df_historico_modificado = df_ordenes_historico.copy()
                    
                    # Actualizar el estado en el DataFrame
                    df_historico_modificado.loc[df_historico_modificado['ID_Orden'].isin(ids_a_actualizar), 'Estado'] = nuevo_estado
                    
                    with st.spinner("Actualizando estados en Google Sheets..."):
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                        
                        if exito:
                            st.success(f"¡Éxito! {len(ids_a_actualizar)} órdenes han sido actualizadas a '{nuevo_estado}'. La página se recargará.")
                            # Limpiar cache y recargar para reflejar los cambios
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Error al actualizar Google Sheets: {msg}")
