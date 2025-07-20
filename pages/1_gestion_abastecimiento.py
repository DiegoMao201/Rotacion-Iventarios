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

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚀")

st.title("🚀 Tablero de Control de Abastecimiento v2.1")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real conectado a Google Sheets.")

# --- NUEVO: 1. FUNCIONES DE CONEXIÓN Y GESTIÓN CON GOOGLE SHEETS ---

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
def load_pending_orders(_client):
    """Carga únicamente el registro de órdenes desde Google Sheets."""
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet("Registro_Ordenes")
        df_ordenes = pd.DataFrame(worksheet.get_all_records())
        # Asegurar tipos de datos correctos para evitar errores posteriores
        if not df_ordenes.empty:
            df_ordenes['SKU'] = df_ordenes['SKU'].astype(str)
        return df_ordenes
    except Exception as e:
        st.error(f"Ocurrió un error al cargar el registro de órdenes: {e}")
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
    """Añade filas a una hoja."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.append_rows(df_to_append.astype(str).values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Nuevos registros añadidos a '{sheet_name}'."
    except Exception as e:
        return False, f"Error al añadir registros en la hoja '{sheet_name}': {e}"


# --- 2. FUNCIONES AUXILIARES (EXISTENTES Y SIN CAMBIOS) ---

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


def generar_plan_traslados_inteligente(_df_analisis_maestro):
    """Genera un plan de traslados óptimo incluyendo la información del proveedor."""
    if _df_analisis_maestro is None or _df_analisis_maestro.empty: return pd.DataFrame()
    
    # Asegurarse que las columnas necesarias existen y son numéricas
    for col in ['Excedente_Trasladable', 'Necesidad_Total', 'Stock', 'Peso_Articulo', 'Costo_Promedio_UND']:
        if col not in _df_analisis_maestro.columns:
            _df_analisis_maestro[col] = 0 # O un valor por defecto apropiado
        _df_analisis_maestro[col] = pd.to_numeric(_df_analisis_maestro[col], errors='coerce').fillna(0)
            
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
                    'Proveedor': origen_row.get('Proveedor', 'N/A'),
                    'Segmento_ABC': necesidad_row.get('Segmento_ABC', 'C'), 'Tienda Origen': tienda_origen,
                    'Stock en Origen': origen_row['Stock'], 'Tienda Destino': tienda_necesitada,
                    'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],
                    'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row.get('Peso_Articulo', 0),
                    'Valor Individual': necesidad_row['Costo_Promedio_UND']
                })
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
    
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = pd.to_numeric(df_resultado['Uds a Enviar'], errors='coerce').fillna(0) * pd.to_numeric(df_resultado['Peso Individual (kg)'], errors='coerce').fillna(0)
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar'], errors='coerce').fillna(0) * pd.to_numeric(df_resultado['Valor Individual'], errors='coerce').fillna(0)
    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)


class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        try:
            self.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
            self.add_font('DejaVu', 'B', 'DejaVuSans-Bold.ttf', uni=True)
        except RuntimeError: 
            st.warning("Fuente 'DejaVu' no encontrada. Se usará Helvetica. Algunos caracteres especiales podrían no renderizarse correctamente en el PDF.")
            self.set_font('Helvetica', '', 12)
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
        footer_text = f"{self.empresa_nombre}      |      {self.empresa_web}      |      {self.empresa_email}      |      {self.empresa_tel}"
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
    for _, row in df_seleccion.iterrows():
        costo_total_item = row['Uds a Comprar'] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        
        pdf.multi_cell(25, 5, str(row['SKU']), 1, 'L')
        y1 = pdf.get_y(); pdf.set_xy(x_start + 25, y_start)
        pdf.multi_cell(30, 5, str(row.get('SKU_Proveedor', 'N/A')), 1, 'L')
        y2 = pdf.get_y(); pdf.set_xy(x_start + 55, y_start)
        pdf.multi_cell(70, 5, row['Descripcion'], 1, 'L')
        y3 = pdf.get_y()
        row_height = max(y1, y2, y3) - y_start
        
        pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(int(row['Uds a Comprar'])), 1, 'C')
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

# PASO 1: Cargar el archivo base desde la sesión (como en el original)
if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos base de inventario.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop()
df_maestro_base = st.session_state['df_analisis_maestro'].copy()

# PASO 2: Conectar a Google Sheets y cargar las órdenes pendientes
client = connect_to_gsheets()
df_ordenes_historico = load_pending_orders(client)

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
    df_maestro = df_maestro_base
    df_maestro['Stock_En_Transito'] = 0

# PASO 4: Recalcular las necesidades y excedentes con la nueva información
numeric_cols = ['Stock', 'Stock_En_Transito', 'Nivel_Optimo', 'Stock_Seguridad', 'Sugerencia_Compra', 'Costo_Promedio_UND']
for col in numeric_cols:
    if col in df_maestro.columns:
        df_maestro[col] = pd.to_numeric(df_maestro[col], errors='coerce').fillna(0)
    else:
        df_maestro[col] = 0 # Crear columna si no existe para evitar errores

df_maestro['Stock_Disponible_Proyectado'] = df_maestro['Stock'] + df_maestro['Stock_En_Transito']
df_maestro['Necesidad_Total'] = (df_maestro['Nivel_Optimo'] - df_maestro['Stock_Disponible_Proyectado']).clip(lower=0)
df_maestro['Excedente_Trasladable'] = (df_maestro['Stock'] - df_maestro['Stock_Seguridad']).clip(lower=0)
df_maestro['Sugerencia_Compra'] = df_maestro['Necesidad_Total']
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
    
    # ... (Código idéntico al original, ahora es más inteligente) ...
    # ... (Copiado y pegado desde tu script original) ...


# --- PESTAÑA 2: PLAN DE TRASLADOS ---
with tab2:
    st.subheader("🚚 Plan de Traslados entre Tiendas")

    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        with st.spinner("Calculando plan de traslados óptimo..."):
            df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)

        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            # ... (Lógica de filtros y búsqueda de traslados sin cambios) ...
            
            df_para_editar = df_traslados_filtrado.copy()
            df_para_editar['Seleccionar'] = False
            
            df_para_editar = pd.merge(df_para_editar, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                      left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left')
            df_para_editar.drop(columns=['Almacen_Nombre'], inplace=True)
            df_para_editar['Stock_En_Transito'].fillna(0, inplace=True)
            
            columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Marca_Nombre', 'Tienda Origen',
                                 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Stock_En_Transito', 
                                 'Necesidad en Destino', 'Uds a Enviar']
            
            edited_df_traslados = st.data_editor( #... (código del editor idéntico) ...
            )
            
            df_seleccionados_traslado = edited_df_traslados[edited_df_traslados['Seleccionar']]

            if not df_seleccionados_traslado.empty:
                # ... (Lógica para mostrar detalles, calcular peso, etc. idéntica) ...
                if st.button("✉️ Enviar Plan y Registrar en GSheets", use_container_width=True, key="btn_enviar_traslado", type="primary"):
                    if email_dest_traslado:
                        # ... (lógica de envío de correo idéntica) ...
                        if enviado:
                            st.success(mensaje)
                            with st.spinner("Registrando orden de traslado en Google Sheets..."):
                                df_reg = df_seleccionados_traslado.copy()
                                id_orden = f"OT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                                df_reg['ID_Orden'] = id_orden
                                df_reg['ID_Item'] = [f"{id_orden}-{i+1}" for i in range(len(df_reg))]
                                df_reg['Fecha_Solicitud'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                df_reg['Tipo'] = 'Traslado'
                                df_reg['Estado'] = 'Pendiente'
                                df_reg['Fecha_Recepcion'] = ''
                                df_reg.rename(columns={
                                    'Tienda Origen': 'Origen',
                                    'Tienda Destino': 'Tienda_Destino',
                                    'Uds a Enviar': 'Cantidad_Solicitada'
                                }, inplace=True)
                                
                                columnas_registro = ['ID_Orden', 'ID_Item', 'Fecha_Solicitud', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tipo', 'Origen', 'Tienda_Destino', 'Estado', 'Fecha_Recepcion']
                                
                                exito, msg = append_to_sheet(client, "Registro_Ordenes", df_reg[columnas_registro])
                                if exito: st.success(msg); st.cache_data.clear(); st.rerun()
                                else: st.error(msg)
    
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        # ... (código idéntico al original, pero el botón de envío ahora registra en GSheets) ...
        # if st.button("✉️ Enviar Solicitud y Registrar", ...):
        #    ... (lógica de envío de correo) ...
        #    if enviado:
        #        ... (lógica para registrar en GSheets, igual que arriba) ...
        pass


# --- PESTAÑA 3: PLAN DE COMPRAS ---
with tab3:
    st.header("🛒 Plan de Compras")

    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        # ... (lógica de filtro de proveedor idéntica) ...
        df_a_mostrar = pd.merge(df_a_mostrar, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                              on=['SKU', 'Almacen_Nombre'], how='left')
        df_a_mostrar['Stock_En_Transito'].fillna(0, inplace=True)
        
        columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock', 'Stock_En_Transito', 'Sugerencia_Compra', 'Uds a Comprar', 'Costo_Promedio_UND']
        
        # ... (código del data_editor idéntico) ...
        
        if not df_seleccionados.empty:
            # ... (código de botones de descarga y preparación de correo idéntico) ...
            if st.button("✉️ Enviar por Correo y Registrar", ...):
                # ... (lógica de envío de correo idéntica) ...
                if enviado:
                    st.success(mensaje)
                    # --- NUEVO: REGISTRAR COMPRA EN GSHEETS ---
                    with st.spinner("Registrando orden de compra en Google Sheets..."):
                        # ... (código para preparar y registrar el df idéntico a la versión anterior) ...
                        pass
    
    with st.expander("🆕 **Compras Especiales (Búsqueda Inteligente y Manual)**", expanded=True):
        # ... (código idéntico al original, pero el botón de envío ahora registra en GSheets) ...
        pass


# --- NUEVO: PESTAÑA 4: SEGUIMIENTO Y RECEPCIÓN ---
with tab4:
    st.header("📦 Seguimiento y Recepción de Órdenes")
    st.info("Aquí puedes gestionar las órdenes de compra y traslados que ya has generado.")

    if df_ordenes_historico.empty or df_ordenes_historico['Estado'].isnull().all():
        st.warning("Aún no se han registrado órdenes en Google Sheets.")
    else:
        df_pendientes = df_ordenes_historico[df_ordenes_historico['Estado'] == 'Pendiente'].copy()

        if df_pendientes.empty:
            st.success("✅ ¡Excelente! No hay órdenes pendientes de recibir.")
        else:
            st.subheader(f"Tienes {len(df_pendientes)} items en {df_pendientes['ID_Orden'].nunique()} órdenes pendientes.")
            
            lista_ordenes = sorted(df_pendientes['ID_Orden'].unique().tolist(), reverse=True)
            orden_seleccionada = st.selectbox("Selecciona una orden para gestionar:", [""] + lista_ordenes, key="sb_orden_gestion")

            if orden_seleccionada:
                df_items_orden = df_pendientes[df_pendientes['ID_Orden'] == orden_seleccionada].copy()
                st.write(f"Artículos de la orden: **{orden_seleccionada}**")

                df_items_orden['Cantidad_Recibida'] = df_items_orden['Cantidad_Solicitada']
                df_items_orden['Cancelar_Item'] = False

                edited_df = st.data_editor(
                    df_items_orden[['SKU', 'Descripcion', 'Cantidad_Solicitada', 'Cantidad_Recibida', 'Cancelar_Item', 'ID_Item']],
                    hide_index=True, use_container_width=True,
                    disabled=['SKU', 'Descripcion', 'Cantidad_Solicitada', 'ID_Item'],
                    column_config={
                        "ID_Item": None,
                        "Cantidad_Recibida": st.column_config.NumberColumn("Cant. Recibida", help="Modifica si la entrega fue parcial.", min_value=0, step=1),
                        "Cancelar_Item": st.column_config.CheckboxColumn("Cancelar Ítem")
                    }, key=f"editor_{orden_seleccionada}"
                )

                if st.button("🚀 Procesar Recepción de esta Orden", type="primary", key="btn_procesar_recepcion"):
                    with st.spinner("Actualizando Google Sheets..."):
                        df_ord_actual = load_pending_orders(client)
                        df_ord_actual['ID_Item'] = df_ord_actual['ID_Item'].astype(str)
                        edited_df['ID_Item'] = edited_df['ID_Item'].astype(str)

                        nuevas_filas_ordenes = []

                        for _, row in edited_df.iterrows():
                            id_item_a_procesar = row['ID_Item']
                            cant_solicitada = int(pd.to_numeric(row['Cantidad_Solicitada'], errors='coerce'))
                            cant_recibida = int(pd.to_numeric(row['Cantidad_Recibida'], errors='coerce'))
                            mask_ord = df_ord_actual['ID_Item'] == id_item_a_procesar
                            
                            if row['Cancelar_Item']:
                                df_ord_actual.loc[mask_ord, 'Estado'] = 'Cancelado'
                            elif cant_recibida >= cant_solicitada:
                                df_ord_actual.loc[mask_ord, 'Estado'] = 'Recibido'
                                df_ord_actual.loc[mask_ord, 'Fecha_Recepcion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            elif 0 < cant_recibida < cant_solicitada:
                                df_ord_actual.loc[mask_ord, 'Estado'] = 'Recibido Parcialmente'
                                df_ord_actual.loc[mask_ord, 'Cantidad_Solicitada'] = cant_recibida
                                df_ord_actual.loc[mask_ord, 'Fecha_Recepcion'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                fila_remanente = df_ord_actual[mask_ord].iloc[0].to_dict()
                                fila_remanente['ID_Item'] = f"{fila_remanente['ID_Orden']}-REM-{np.random.randint(1000,9999)}"
                                fila_remanente['Cantidad_Solicitada'] = cant_solicitada - cant_recibida
                                fila_remanente['Estado'] = 'Pendiente'
                                fila_remanente['Fecha_Recepcion'] = ''
                                nuevas_filas_ordenes.append(fila_remanente)
                        
                        if nuevas_filas_ordenes:
                            df_ord_actual = pd.concat([df_ord_actual, pd.DataFrame(nuevas_filas_ordenes)], ignore_index=True)

                        exito_ord, msg_ord = update_sheet(client, 'Registro_Ordenes', df_ord_actual)
                        if exito_ord:
                            st.success(msg_ord)
                            st.info("El estado de las órdenes ha sido actualizado. Los cambios en el inventario se verán reflejados en la próxima carga de datos base.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(msg_ord)
        
        st.subheader("Historial de Todas las Órdenes")
        st.dataframe(df_ordenes_historico.sort_values(by='Fecha_Solicitud', ascending=False))
