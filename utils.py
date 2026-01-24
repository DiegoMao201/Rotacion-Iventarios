# utils.py

import streamlit as st
import pandas as pd
import numpy as np
import io
import os
import gspread
import smtplib
import urllib.parse
from datetime import datetime
from fpdf import FPDF
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google.oauth2.service_account import Credentials
import dropbox

# --- CONSTANTES Y CONFIGURACIONES (AJUSTADAS A TUS NECESIDADES) ---
EXPECTED_INVENTORY_COLS = [
    'DEPARTAMENTO', 'REFERENCIA', 'DESCRIPCION', 'MARCA', 'PESO_ARTICULO',
    'UNIDADES_VENDIDAS', 'STOCK', 'COSTO_PROMEDIO_UND', 'CODALMACEN',
    'LEAD_TIME_PROVEEDOR', 'HISTORIAL_VENTAS'
]
# Columnas exactas que se esperan en el archivo de proveedores
EXPECTED_PROVIDERS_COLS = ['COD PROVEEDOR', 'REFERENCIA', 'PROVEEDOR']

# Se añade 'SKU_Proveedor' a las columnas que se registran en Google Sheets
GSHEETS_FINAL_COLS = [
    'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion',
    'Cantidad_Solicitada', 'Tienda_Destino', 'Estado',
    'Costo_Unitario', 'Costo_Total'
]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

DIRECCIONES_TIENDAS = {
    'Armenia': 'Carrera 19 11 05',
    'Olaya': 'Carrera 13 19 26',
    'Manizales': 'Calle 16 21 32',
    'FerreBox': 'Calle 20 12 32',
    'Laureles': 'Av. Laureles #35-13',
    'Opalo': 'Cra. 10 #70-52',
    'Cedi': 'Bodega Principal Vía Condina'
}

CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448', 'email': 'proveedor1@example.com'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917', 'email': 'proveedor2@example.com'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589', 'email': 'proveedor3@example.com'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893', 'email': 'proveedor4@example.com'},
}

CONTACTOS_TIENDAS = {
    'Armenia': {'email': 'tiendapintucoarmenia@ferreinox.co', 'celular': '573165219904'},
    'Olaya': {'email': 'tiendapintucopereira@ferreinox.co', 'celular': '573102368346'},
    'Manizales': {'email': 'tiendapintucomanizales@ferreinox.co', 'celular': '573136086232'},
    'Laureles': {'email': 'tiendapintucolaureles@ferreinox.co', 'celular': '573104779389'},
    'Opalo': {'email': 'tiendapintucodosquebradas@ferreinox.co', 'celular': '573108561506'},
    'FerreBox': {'email': 'compras@ferreinox.co', 'celular': '573127574279'},
    'Cedi': {'email': 'bodega@ferreinox.co', 'celular': '573123456789'}
}

# --- VALIDACIÓN DE DATOS ---
def validate_dataframe(df, required_columns, df_name="DataFrame"):
    if df is None or df.empty:
        # No mostramos error si el archivo es opcional, como el de proveedores
        if df_name != "archivo de proveedores":
            st.error(f"Error: El {df_name} está vacío o no se pudo cargar.")
        return False
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        st.warning(f"Advertencia en {df_name}: Faltan las siguientes columnas requeridas: {', '.join(missing_cols)}")
        return False
    return True

# --- LÓGICA DE ANÁLISIS CENTRAL ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, _df_proveedores, dias_seguridad=7, dias_objetivo=None):
    if not validate_dataframe(_df_crudo, EXPECTED_INVENTORY_COLS, "archivo de inventario"):
        return pd.DataFrame()
    
    df = _df_crudo.copy()
    
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 
        'HISTORIAL_VENTAS': 'Historial_Ventas', 'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
    }
    df.rename(columns=column_mapping, inplace=True)
    
    df['SKU'] = df['SKU'].astype(str)
    almacen_map = {'158':'Opalo', '155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].astype(str).map(almacen_map).fillna(df['Almacen'])
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True)

    # --- LÓGICA DE DEMANDA DIARIA Y MÉTRICAS (COMPLETA) ---
    df['Historial_Ventas'] = df['Historial_Ventas'].fillna('').astype(str)
    df_ventas = df[df['Historial_Ventas'].str.contains(':')].copy()
    if not df_ventas.empty:
        try:
            df_ventas = df_ventas.assign(Historial_Ventas=df_ventas['Historial_Ventas'].str.split(',')).explode('Historial_Ventas')
            df_ventas[['Fecha_Venta', 'Unidades']] = df_ventas['Historial_Ventas'].str.split(':', expand=True)
            df_ventas['Fecha_Venta'] = pd.to_datetime(df_ventas['Fecha_Venta'], errors='coerce')
            df_ventas['Unidades'] = pd.to_numeric(df_ventas['Unidades'], errors='coerce')
            df_ventas.dropna(subset=['Fecha_Venta', 'Unidades'], inplace=True)
            df_ventas = df_ventas[(pd.Timestamp.now() - df_ventas['Fecha_Venta']).dt.days <= 60]
            if not df_ventas.empty:
                demanda_diaria = df_ventas.groupby('index')['Unidades'].sum() / 60
                df = df.merge(demanda_diaria.rename('Demanda_Diaria_Promedio'), on='index', how='left')
            else:
                df['Demanda_Diaria_Promedio'] = 0
        except Exception as e:
            st.warning(f"Se encontró un problema al procesar el historial de ventas. Algunas demandas podrían ser 0. Error: {e}")
            df['Demanda_Diaria_Promedio'] = 0
    else:
        df['Demanda_Diaria_Promedio'] = 0
    df['Demanda_Diaria_Promedio'].fillna(0, inplace=True)
    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * df['Lead_Time_Proveedor']) + df['Stock_Seguridad']
    df['Valor_Venta_60_Dias'] = df['Ventas_60_Dias'] * df['Costo_Promedio_UND']
    total_ventas_valor = df['Valor_Venta_60_Dias'].sum()
    if total_ventas_valor > 0:
        ventas_sku_valor = df.groupby('SKU')['Valor_Venta_60_Dias'].sum()
        sku_to_percent = ventas_sku_valor.sort_values(ascending=False).cumsum() / total_ventas_valor
        df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(lambda p: 'A' if p <= 0.8 else ('B' if p <= 0.95 else 'C')).fillna('C')
    else:
        df['Segmento_ABC'] = 'C'
    if dias_objetivo is None: dias_objetivo = {'A': 30, 'B': 45, 'C': 60}
    df['dias_objetivo_map'] = df['Segmento_ABC'].map(dias_objetivo)
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * df['dias_objetivo_map']
    conditions = [(df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0), (df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0), (df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']), (df['Stock'] > df['Stock_Objetivo']),]
    choices_estado = ['Quiebre de Stock', 'Baja Rotación / Obsoleto', 'Bajo Stock (Riesgo)', 'Excedente']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    df['Excedente_Trasladable'] = np.where(df['Estado_Inventario'] == 'Excedente', np.maximum(0, df['Stock'] - df['Stock_Objetivo']), 0)
    
    # --- MANEJO ROBUSTO DE PROVEEDORES ---
    if validate_dataframe(_df_proveedores, EXPECTED_PROVIDERS_COLS, "archivo de proveedores"):
        df_proveedores_limpio = _df_proveedores[EXPECTED_PROVIDERS_COLS].copy()
        df_proveedores_limpio.rename(columns={'REFERENCIA': 'SKU', 'PROVEEDOR': 'Proveedor', 'COD PROVEEDOR': 'SKU_Proveedor'}, inplace=True)
        df_proveedores_limpio['SKU'] = df_proveedores_limpio['SKU'].astype(str)
        df = pd.merge(df, df_proveedores_limpio, on='SKU', how='left')
    
    if 'Proveedor' not in df.columns: df['Proveedor'] = 'No Asignado'
    if 'SKU_Proveedor' not in df.columns: df['SKU_Proveedor'] = 'N/A'
    
    df['Proveedor'] = df['Proveedor'].fillna('No Asignado').str.upper()
    df['SKU_Proveedor'] = df['SKU_Proveedor'].fillna('N/A')

    return df.set_index('index')

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource(ttl=3600)
def connect_to_gsheets():
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}. Revisa tus 'secrets'.")
        return None

# --- FUNCIONES DE GOOGLE SHEETS (COMPLETAS) ---
@st.cache_data(ttl=60)
def load_data_from_sheets(sheet_name):
    client = connect_to_gsheets()
    if client is None: return pd.DataFrame()
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        df = pd.DataFrame(worksheet.get_all_records())
        for col in ['SKU', 'ID_Orden', 'Proveedor', 'SKU_Proveedor']:
            if col in df.columns:
                df[col] = df[col].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Error: La hoja de Google '{sheet_name}' no fue encontrada.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ocurrió un error al cargar la hoja '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(sheet_name, df_to_write):
    client = connect_to_gsheets()
    if client is None: return False, "No se pudo conectar a Google Sheets."
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        df_str = df_to_write.astype(str).replace(np.nan, '')
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(sheet_name, df_to_append):
    client = connect_to_gsheets()
    if client is None: return False, "No se pudo conectar a Google Sheets.", pd.DataFrame()
    if df_to_append.empty: return False, "No hay datos para añadir.", pd.DataFrame()
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        # Reordenar y asegurar que todas las columnas de GSheets existan en el DF a añadir
        df_final_append = df_to_append.reindex(columns=GSHEETS_FINAL_COLS).fillna('')
        df_str = df_final_append.astype(str).replace(np.nan, '')
        
        headers = worksheet.row_values(1)
        if not headers:
            worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
            return True, "Hoja creada y registros añadidos.", df_final_append
        
        worksheet.append_rows(df_str.values.tolist(), value_input_option='USER_ENTERED')
        return True, f"{len(df_final_append)} nuevos registros añadidos a '{sheet_name}'.", df_final_append
    except Exception as e:
        return False, f"Error al añadir registros a '{sheet_name}': {e}", pd.DataFrame()

# --- LÓGICA DE CÁLCULO DE SUGERENCIAS (COMPLETA) ---
@st.cache_data
def calcular_sugerencias_finales(_df_base, _df_ordenes):
    df_maestro = _df_base.copy()
    df_maestro['Stock_En_Transito'] = 0
    if not _df_ordenes.empty and 'Estado' in _df_ordenes.columns:
        df_pendientes = _df_ordenes[_df_ordenes['Estado'].isin(['Pendiente', 'En Tránsito'])].copy()
        if not df_pendientes.empty and 'Cantidad_Solicitada' in df_pendientes.columns:
            df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
            stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
            stock_en_transito_agg = stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito_Nuevas', 'Tienda_Destino': 'Almacen_Nombre'})
            df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
            df_maestro['Stock_En_Transito'] = df_maestro['Stock_En_Transito'].add(df_maestro['Stock_En_Transito_Nuevas'].fillna(0))
            df_maestro.drop(columns=['Stock_En_Transito_Nuevas'], inplace=True)
    df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)
    df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)
    df_maestro['Cubierto_Por_Traslado'] = 0
    if not df_plan_maestro.empty:
        unidades_cubiertas = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
        unidades_cubiertas = unidades_cubiertas.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado_Nuevas'})
        df_maestro = pd.merge(df_maestro, unidades_cubiertas, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Cubierto_Por_Traslado'] = df_maestro['Cubierto_Por_Traslado'].add(df_maestro['Cubierto_Por_Traslado_Nuevas'].fillna(0))
        df_maestro.drop(columns=['Cubierto_Por_Traslado_Nuevas'], inplace=True)
    df_maestro['Sugerencia_Compra'] = np.ceil(df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
    df_maestro['Sugerencia_Compra'] = df_maestro['Sugerencia_Compra'].astype(int)
    return df_maestro, df_plan_maestro

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    required_cols = ['Excedente_Trasladable', 'Necesidad_Ajustada_Por_Transito', 'SKU', 'Almacen_Nombre']
    if not validate_dataframe(_df_analisis, required_cols, "análisis para traslados"): return pd.DataFrame()
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
                plan_final.append({'SKU': sku, 'Descripcion': need_row.get('Descripcion', 'N/A'), 'Proveedor': origin_row.get('Proveedor', 'N/A'), 'Tienda Origen': tienda_origen, 'Stock en Origen': origin_row.get('Stock', 0), 'Tienda Destino': tienda_necesitada, 'Stock en Destino': need_row.get('Stock', 0), 'Uds a Enviar': np.floor(unidades_a_enviar), 'Costo_Promedio_UND': need_row.get('Costo_Promedio_UND', 0)})
                necesidad -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
                if necesidad <= 0: break
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Uds a Enviar'] = df_resultado['Uds a Enviar'].astype(int)
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Costo_Promedio_UND'])
    return df_resultado[df_resultado['Uds a Enviar'] > 0].sort_values(by=['Valor del Traslado'], ascending=False).reset_index(drop=True)

# --- REGISTRO Y NOTIFICACIONES (COMPLETO) ---
def registrar_ordenes_en_sheets(sheet_name, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    if df_orden.empty: return False, "No hay datos válidos para registrar.", pd.DataFrame()
    df_registro = df_orden.copy()
    if 'Uds a Comprar' in df_registro.columns: cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_registro.columns: cantidad_col = 'Uds a Enviar'
    else: return False, "No se encontró columna de cantidad.", pd.DataFrame()
    if 'Costo_Promedio_UND' in df_registro.columns: costo_col = 'Costo_Promedio_UND'
    elif 'Costo_Unitario' in df_registro.columns: costo_col = 'Costo_Unitario'
    else: return False, "No se encontró columna de costo.", pd.DataFrame()
    df_registro['Cantidad_Solicitada'] = pd.to_numeric(df_registro[cantidad_col], errors='coerce').fillna(0)
    df_registro['Costo_Unitario'] = pd.to_numeric(df_registro.get(costo_col, 0), errors='coerce').fillna(0)
    df_registro['Costo_Total'] = df_registro['Cantidad_Solicitada'] * df_registro['Costo_Unitario']
    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    timestamp = datetime.now().strftime('%y%m%d%H%M')
    base_id = ""
    if tipo_orden == "Compra Sugerencia":
        base_id = f"OC-{proveedor_nombre[:3]}-{timestamp}"
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    # Lógica para otros tipos de orden...
    df_registro['ID_Orden'] = [f"{base_id}-{i+1:02}" for i in range(len(df_registro))]
    df_final_para_gsheets = df_registro.reindex(columns=GSHEETS_FINAL_COLS).fillna('')
    return append_to_sheet(sheet_name, df_final_para_gsheets)

def generar_cuerpo_correo(proveedor_nombre, orden_num, tiendas_destino_df, contacto_bodega="Leivyn Gabriel Garcia"):
    tiendas_unicas = tiendas_destino_df['Tienda_Destino'].unique()
    if len(tiendas_unicas) > 1:
        sede_entrega_txt = "Entrega Multi-Tienda"
        direcciones_html = "<ul>"
        for tienda in tiendas_unicas:
            direccion = DIRECCIONES_TIENDAS.get(tienda, "Dirección no especificada")
            direcciones_html += f"<li><strong>{tienda}:</strong> {direccion}</li>"
        direcciones_html += "</ul><p>Por favor, revise el Excel adjunto para ver los destinos específicos de cada ítem.</p>"
    else:
        sede_entrega_txt = tiendas_unicas[0]
        direcciones_html = f"<p><strong>Dirección:</strong> {DIRECCIONES_TIENDAS.get(sede_entrega_txt, 'Dirección no especificada')}</p>"
    cuerpo_html = f"""<html><body><p>Estimado equipo de <strong>{proveedor_nombre.upper()}</strong>,</p><p>Adjunto a este correo encontrarán nuestra <strong>orden de compra N° {orden_num}</strong> en formatos PDF y Excel.</p><p>Por favor, realizar el despacho a la(s) siguiente(s) dirección(es):</p><p><strong>Sede de Entrega:</strong> {sede_entrega_txt}</p>{direcciones_html}<p><strong>Contacto en Bodega:</strong> {contacto_bodega}</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><br><p>--<br><strong>Departamento de Compras</strong><br>Ferreinox SAS BIC</p></body></html>"""
    return cuerpo_html

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
            part = MIMEBase(adj_info.get('maintype', 'application'), adj_info.get('subtype', 'octet-stream'))
            part.set_payload(adj_info['data'])
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename=\"{adj_info['filename']}\"")
            msg.attach(part)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(remitente, password)
            server.sendmail(remitente, destinatarios, msg.as_string())
        return True, "Correo enviado exitosamente."
    except smtplib.SMTPAuthenticationError:
        return False, "Error de autenticación con Gmail. Revisa el email y la contraseña en los 'secrets'."
    except Exception as e:
        return False, f"Error al enviar el correo: '{e}'."

def generar_link_whatsapp(numero, mensaje):
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"

# --- GENERACIÓN DE ARCHIVOS PDF Y EXCEL (COMPLETO) ---
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
        self.font_family = 'Helvetica'

    def header(self):
        try: self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError: self.set_xy(10, 8); self.set_font(self.font_family, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font(self.font_family, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R')
        self.set_font(self.font_family, '', 10); self.set_text_color(100, 100, 100)
        self.cell(0, 7, self.empresa_nombre, 0, 1, 'R')
        self.cell(0, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font(self.font_family, '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}      |      {self.empresa_web}      |      {self.empresa_email}      |      {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C')
        self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, orden_num):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='L', unit='mm', format='A4') # Orientación a Paisaje para más columnas
    pdf.add_page()
    pdf.set_font(pdf.font_family, 'B', 11)
    pdf.cell(138, 8, 'PROVEEDOR', 1, 0, 'C')
    pdf.cell(10, 8, '', 0, 0)
    pdf.cell(130, 8, 'DIRECCIÓN DE ENTREGA', 1, 1, 'C')
    pdf.set_font(pdf.font_family, '', 10)
    pdf.cell(138, 7, f"Proveedor: {proveedor_nombre}", 'L', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(130, 7, "Entrega: Ver instrucciones en correo", 'L', 1)
    pdf.cell(138, 7, f"Fecha de Orden: {datetime.now().strftime('%Y-%m-%d')}", 'L', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(130, 7, "Contacto: Leivyn Gabriel Garcia", 'L', 1)
    pdf.cell(138, 7, f"Orden de Compra No.: {orden_num}", 'LB', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(130, 7, "", 'LR', 1)
    pdf.ln(10)
    
    # --- Cabecera de la Tabla (con SKU Proveedor) ---
    pdf.set_font(pdf.font_family, 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(25, 7, 'SKU Interno', 1, 0, 'C', 1)
    pdf.cell(25, 7, 'SKU Proveedor', 1, 0, 'C', 1) # NUEVA COLUMNA
    pdf.cell(105, 7, 'Descripción', 1, 0, 'C', 1)
    pdf.cell(25, 7, 'Tienda Destino', 1, 0, 'C', 1)
    pdf.cell(20, 7, 'Cantidad', 1, 0, 'C', 1)
    pdf.cell(25, 7, 'Costo Unit.', 1, 0, 'C', 1)
    pdf.cell(25, 7, 'Costo Total', 1, 1, 'C', 1)
    
    # --- Cuerpo de la Tabla ---
    pdf.set_font(pdf.font_family, '', 8)
    total_general = 0
    for _, row in df_seleccion.iterrows():
        costo_unit = pd.to_numeric(row.get('Costo_Unitario', 0))
        cantidad = pd.to_numeric(row.get('Cantidad_Solicitada', 0))
        total_linea = costo_unit * cantidad
        total_general += total_linea
        pdf.cell(25, 6, str(row.get('SKU', '')), 1, 0, 'L')
        pdf.cell(25, 6, str(row.get('SKU_Proveedor', '')), 1, 0, 'L') # NUEVA COLUMNA
        pdf.cell(105, 6, str(row.get('Descripcion', '')), 1, 0, 'L')
        pdf.cell(25, 6, str(row.get('Tienda_Destino', '')), 1, 0, 'C')
        pdf.cell(20, 6, str(int(cantidad)), 1, 0, 'R')
        pdf.cell(25, 6, f"${costo_unit:,.0f}", 1, 0, 'R')
        pdf.cell(25, 6, f"${total_linea:,.0f}", 1, 1, 'R')
        
    pdf.set_font(pdf.font_family, 'B', 10)
    pdf.cell(225, 8, 'Total General', 1, 0, 'R')
    pdf.cell(25, 8, f"${total_general:,.0f}", 1, 1, 'R')
    
    return bytes(pdf.output())

def generar_excel_dinamico(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        # Aquí se puede añadir formato al excel si se desea
    return output.getvalue()

def cargar_maestro_articulos_dropbox():
    """
    Carga el archivo maestro de artículos desde Dropbox y retorna un diccionario {referencia: codigo_articulo}.
    El archivo debe tener columnas 'referencia' y 'codigo' o 'código'.
    """
    dbx_creds = st.secrets["dropbox"]
    maestro_path = dbx_creds["maestro_articulos_file_path"]  # Define esto en tus secrets

    df_base = None
    try:
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            metadata, res = dbx.files_download(path=maestro_path)
            with io.BytesIO(res.content) as stream:
                if maestro_path.endswith('.xlsx'):
                    df_base = pd.read_excel(stream)
                else:
                    df_base = pd.read_csv(stream, sep=None, engine='python')
    except Exception as e:
        st.error(f"Error leyendo archivo maestro desde Dropbox: {e}")
        return {}

    # 2. Normalizar nombres de columnas (todo a minúsculas y sin espacios)
    df_base.columns = [str(col).strip().lower() for col in df_base.columns]

    # 3. Detectar columnas clave
    col_referencia = next((c for c in df_base.columns if 'referencia' in c), None)
    col_codigo = next((c for c in df_base.columns if 'código' in c or 'codigo' in c), None)

    if not col_referencia or not col_codigo:
        st.error("❌ Faltan columnas 'Referencia' o 'Código' en el archivo maestro.")
        return {}

    # 4. Limpieza de datos (Quitar espacios, poner minúsculas y quitar '.0' de los códigos)
    df_base[col_referencia] = df_base[col_referencia].astype(str).str.strip().str.lower()
    df_base[col_codigo] = df_base[col_codigo].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    # 5. Crear Diccionario { 'referencia': 'codigo_articulo' }
    mapping_dict = dict(zip(df_base[col_referencia], df_base[col_codigo]))
    
    return mapping_dict

def generar_txt_traslados(df_traslados, mapping_dict):
    """
    Genera un archivo TXT para traslados con formato SECUENCIA|CODIGO|.|.|CANTIDAD|0|0|0|
    - df_traslados: DataFrame con columna 'referencia' y 'Uds a Enviar'
    - mapping_dict: dict {referencia: codigo_articulo}
    """
    lines = []
    secuencia = 1
    for _, row in df_traslados.iterrows():
        ref = str(row['referencia']).strip().lower()
        codigo = mapping_dict.get(ref, "SIN_CODIGO")
        cantidad = int(row['Uds a Enviar'])
        linea = f"{secuencia}|{codigo}|.|.|{cantidad}|0|0|0|"
        lines.append(linea)
        secuencia += 1
    return "\n".join(lines)
