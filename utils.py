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

# --- CONSTANTS AND CONFIGURATIONS (CONSOLIDATED & ENHANCED) ---
EXPECTED_INVENTORY_COLS = [
    'DEPARTAMENTO', 'REFERENCIA', 'DESCRIPCION', 'MARCA', 'PESO_ARTICULO',
    'UNIDADES_VENDIDAS', 'STOCK', 'COSTO_PROMEDIO_UND', 'CODALMACEN',
    'LEAD_TIME_PROVEEDOR', 'HISTORIAL_VENTAS'
]
EXPECTED_PROVIDERS_COLS = ['REFERENCIA', 'PROVEEDOR', 'COD PROVEEDOR']
GSHEETS_FINAL_COLS = [
    'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion',
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

# --- DATA VALIDATION ---
def validate_dataframe(df, required_columns, df_name="DataFrame"):
    """Validates if a DataFrame contains all required columns."""
    if df is None or df.empty:
        st.error(f"Error: The {df_name} is empty or could not be loaded.")
        return False
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        st.error(f"Error in {df_name}: The following required columns are missing: {', '.join(missing_cols)}")
        return False
    return True

# --- CORE ANALYSIS LOGIC (ROBUST VERSION) ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, _df_proveedores, dias_seguridad=7, dias_objetivo=None):
    """Analyzes the complete inventory to calculate key metrics and segments."""
    if not validate_dataframe(_df_crudo, EXPECTED_INVENTORY_COLS, "inventory file"):
        return pd.DataFrame()
    
    df = _df_crudo.copy()
    
    # Standardize column names
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
    
    # Clean and convert numeric columns
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True)

    # Calculate average daily demand from sales history
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
            st.warning(f"A problem was encountered while processing sales history. Some demands may be 0. Error: {e}")
            df['Demanda_Diaria_Promedio'] = 0
    else:
        df['Demanda_Diaria_Promedio'] = 0

    df['Demanda_Diaria_Promedio'].fillna(0, inplace=True)

    # Inventory Metrics Calculations
    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * df['Lead_Time_Proveedor']) + df['Stock_Seguridad']
    
    # ABC Segmentation
    df['Valor_Venta_60_Dias'] = df['Ventas_60_Dias'] * df['Costo_Promedio_UND']
    total_ventas_valor = df['Valor_Venta_60_Dias'].sum()
    if total_ventas_valor > 0:
        ventas_sku_valor = df.groupby('SKU')['Valor_Venta_60_Dias'].sum()
        sku_to_percent = ventas_sku_valor.sort_values(ascending=False).cumsum() / total_ventas_valor
        df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(lambda p: 'A' if p <= 0.8 else ('B' if p <= 0.95 else 'C')).fillna('C')
    else:
        df['Segmento_ABC'] = 'C'

    if dias_objetivo is None:
        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}
    df['dias_objetivo_map'] = df['Segmento_ABC'].map(dias_objetivo)
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * df['dias_objetivo_map']

    # Inventory Status
    conditions = [
        (df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),
        (df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0),
        (df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']),
        (df['Stock'] > df['Stock_Objetivo']),
    ]
    choices_estado = ['Stockout', 'Low Turnover / Obsolete', 'Low Stock (Risk)', 'Surplus']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    df['Excedente_Trasladable'] = np.where(
        df['Estado_Inventario'] == 'Surplus',
        np.maximum(0, df['Stock'] - df['Stock_Objetivo']), 0
    )
    
    # Merge with provider data
    if _df_proveedores is not None and not _df_proveedores.empty and validate_dataframe(_df_proveedores, EXPECTED_PROVIDERS_COLS, "provider file"):
        _df_proveedores['SKU'] = _df_proveedores['REFERENCIA'].astype(str)
        df = pd.merge(df, _df_proveedores[['SKU', 'PROVEEDOR', 'COD PROVEEDOR']], on='SKU', how='left')
        df.rename(columns={'PROVEEDOR': 'Proveedor', 'COD PROVEEDOR': 'SKU_Proveedor'}, inplace=True)


    df['Proveedor'] = df.get('Proveedor', 'Unassigned').fillna('Unassigned').str.upper()
    df['SKU_Proveedor'] = df.get('SKU_Proveedor', 'N/A').fillna('N/A')

    return df.set_index('index')


# --- GOOGLE SHEETS CONNECTION (IMPROVED CACHING & ERROR HANDLING) ---
@st.cache_resource(ttl=3600)
def connect_to_gsheets():
    """Connects to Google Sheets using service account credentials."""
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google Sheets connection error: {e}. Check your 'secrets'.")
        return None

@st.cache_data(ttl=60)
def load_data_from_sheets(_client, sheet_name):
    """Loads data from a specified Google Sheet into a DataFrame."""
    if _client is None: return pd.DataFrame()
    try:
        spreadsheet = _client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        df = pd.DataFrame(worksheet.get_all_records())
        # Ensure key columns are treated as strings to avoid data type issues
        for col in ['SKU', 'ID_Orden', 'Proveedor']:
            if col in df.columns:
                df[col] = df[col].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Error: Google Sheet '{sheet_name}' was not found.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"An error occurred while loading sheet '{sheet_name}': {e}")
        return pd.DataFrame()

def update_sheet(client, sheet_name, df_to_write):
    """Clears and overwrites a Google Sheet with a DataFrame."""
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        # Convert all data to string to prevent gspread errors with mixed types
        df_str = df_to_write.astype(str).replace(np.nan, '')
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist(), value_input_option='USER_ENTERED')
        return True, f"Sheet '{sheet_name}' updated successfully."
    except Exception as e:
        return False, f"Error updating sheet '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    """Appends DataFrame rows to a Google Sheet."""
    if df_to_append.empty:
        return False, "No data to append.", pd.DataFrame()
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        headers = worksheet.row_values(1)
        
        # Ensure columns match the sheet's headers
        df_to_append_ordered = df_to_append.reindex(columns=headers).fillna('')
        df_str = df_to_append_ordered.astype(str).replace(np.nan, '')

        if not headers: # If sheet is empty, write headers first
            worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())
            return True, "Sheet created and records added.", df_to_append
            
        worksheet.append_rows(df_str.values.tolist(), value_input_option='USER_ENTERED')
        return True, f"{len(df_to_append)} new records added to '{sheet_name}'.", df_to_append
    except Exception as e:
        return False, f"Error appending records to '{sheet_name}': {e}", pd.DataFrame()

# --- SUGGESTION & PLANNING LOGIC ---
@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    """Generates an intelligent transfer plan based on surplus and needs."""
    required_cols = ['Excedente_Trasladable', 'Necesidad_Ajustada_Por_Transito', 'SKU', 'Almacen_Nombre']
    if not validate_dataframe(_df_analisis, required_cols, "analysis for transfers"):
        return pd.DataFrame()

    df_origen = _df_analisis[_df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis[_df_analisis['Necesidad_Ajustada_Por_Transito'] > 0].sort_values(by='Necesidad_Ajustada_Por_Transito', ascending=False).copy()

    if df_origen.empty or df_destino.empty:
        return pd.DataFrame()

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
                    'SKU': sku, 'Descripcion': need_row.get('Descripcion', 'N/A'), 
                    'Proveedor': origin_row.get('Proveedor', 'N/A'), 
                    'Tienda Origen': tienda_origen, 'Stock en Origen': origin_row.get('Stock', 0),
                    'Tienda Destino': tienda_necesitada, 'Stock en Destino': need_row.get('Stock', 0),
                    'Uds a Enviar': np.floor(unidades_a_enviar),
                    'Costo_Promedio_UND': need_row.get('Costo_Promedio_UND', 0)
                })
                
                necesidad -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
                if necesidad <= 0: break

    if not plan_final: return pd.DataFrame()
    
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Uds a Enviar'] = df_resultado['Uds a Enviar'].astype(int)
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Costo_Promedio_UND'])
    
    return df_resultado[df_resultado['Uds a Enviar'] > 0].sort_values(by=['Valor del Traslado'], ascending=False).reset_index(drop=True)

@st.cache_data
def calcular_sugerencias_finales(_df_base, _df_ordenes):
    """Adjusts inventory needs considering in-transit stock and potential transfers."""
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

def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    """Prepares and registers orders (purchases/transfers) in Google Sheets."""
    if df_orden.empty or client is None:
        return False, "No valid data to register.", pd.DataFrame()
    
    df_registro = df_orden.copy()
    
    # Determine quantity and cost columns from different possible inputs
    if 'Uds a Comprar' in df_registro.columns: cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_registro.columns: cantidad_col = 'Uds a Enviar'
    else: return False, "Quantity column not found.", pd.DataFrame()
    
    if 'Costo_Promedio_UND' in df_registro.columns: costo_col = 'Costo_Promedio_UND'
    elif 'Costo_Unitario' in df_registro.columns: costo_col = 'Costo_Unitario'
    else: return False, "Cost column not found.", pd.DataFrame()
    
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
    elif tipo_orden == "Compra Especial":
        base_id = f"OCS-{proveedor_nombre[:3]}-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        base_id = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
    elif tipo_orden == "Traslado Especial":
        base_id = f"TRS-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino
    else:
        return False, f"Unrecognized order type: '{tipo_orden}'.", pd.DataFrame()
        
    df_registro['ID_Orden'] = [f"{base_id}-{i+1:02}" for i in range(len(df_registro))]
    
    df_final_para_gsheets = df_registro.reindex(columns=GSHEETS_FINAL_COLS).fillna('')
    return append_to_sheet(client, "Registro_Ordenes", df_final_para_gsheets)

# --- NOTIFICATION & FILE GENERATION ---
def generar_cuerpo_correo(proveedor_nombre, orden_num, tiendas_destino_df, contacto_bodega="Leivyn Gabriel Garcia"):
    """Generates a dynamic HTML email body."""
    tiendas_unicas = tiendas_destino_df['Tienda_Destino'].unique()
    
    if len(tiendas_unicas) > 1:
        sede_entrega_txt = "Multi-Store Delivery"
        direcciones_html = "<ul>"
        for tienda in tiendas_unicas:
            direccion = DIRECCIONES_TIENDAS.get(tienda, "Address not specified")
            direcciones_html += f"<li><strong>{tienda}:</strong> {direccion}</li>"
        direcciones_html += "</ul><p>Please check the attached Excel for item-specific store destinations.</p>"
    else:
        sede_entrega_txt = tiendas_unicas[0]
        direcciones_html = f"<p><strong>Address:</strong> {DIRECCIONES_TIENDAS.get(sede_entrega_txt, 'Address not specified')}</p>"

    cuerpo_html = f"""
    <html>
    <body>
        <p>Dear <strong>{proveedor_nombre.upper()}</strong> team,</p>
        <p>Attached to this email, you will find our <strong>purchase order No. {orden_num}</strong> in PDF and Excel formats.</p>
        <p>Please arrange for dispatch to the following location(s):</p>
        <p><strong>Delivery Site:</strong> {sede_entrega_txt}</p>
        {direcciones_html}
        <p><strong>Warehouse Contact:</strong> {contacto_bodega}</p>
        <p>We appreciate your prompt attention to this matter.</p>
        <p>Sincerely,</p>
        <br>
        <p>
            --<br>
            <strong>Purchasing Department</strong><br>
            Ferreinox SAS BIC
        </p>
    </body>
    </html>
    """
    return cuerpo_html

def enviar_correo_con_adjuntos(destinatarios, asunto, cuerpo_html, lista_de_adjuntos):
    """Sends an email with attachments using Gmail's SMTP server."""
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
        return True, "Email sent successfully."
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail authentication error. Check your email and password in secrets."
    except Exception as e:
        return False, f"Error sending email: '{e}'."

def generar_link_whatsapp(numero, mensaje):
    """Generates a WhatsApp click-to-chat link."""
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"


class PDF(FPDF):
    """Custom PDF class with a standard header and footer for purchase orders."""
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
        # Optional: Add custom font if available
        # self.add_font(...)

    def header(self):
        try:
            self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError:
            self.set_xy(10, 8); self.set_font(self.font_family, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        
        self.set_y(12)
        self.set_x(80)
        self.set_font(self.font_family, 'B', 22)
        self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'PURCHASE ORDER', 0, 1, 'R')
        self.set_font(self.font_family, '', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 7, self.empresa_nombre, 0, 1, 'R')
        self.cell(0, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(*self.color_rojo_ferreinox)
        self.set_line_width(1)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)
        self.set_font(self.font_family, '', 8)
        self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}      |      {self.empresa_web}      |      {self.empresa_email}      |      {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C')
        self.set_y(-12)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, orden_num):
    """Generates a purchase order PDF from a DataFrame."""
    if df_seleccion.empty: return None

    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    # --- Order Info ---
    pdf.set_font(pdf.font_family, 'B', 11)
    pdf.cell(95, 8, 'PROVIDER', 1, 0, 'C')
    pdf.cell(10, 8, '', 0, 0) # spacer
    pdf.cell(85, 8, 'DELIVERY ADDRESS', 1, 1, 'C')

    pdf.set_font(pdf.font_family, '', 10)
    pdf.cell(95, 7, f"Provider: {proveedor_nombre}", 'L', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(85, 7, "Delivery: See instructions", 'L', 1)

    pdf.cell(95, 7, f"Order Date: {datetime.now().strftime('%Y-%m-%d')}", 'L', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(85, 7, "Contact: Leivyn Gabriel Garcia", 'L', 1)

    pdf.cell(95, 7, f"Order No.: {orden_num}", 'LB', 0)
    pdf.cell(10, 7, '', 0, 0)
    pdf.cell(85, 7, "", 'LR', 1) # Empty line to match height

    pdf.ln(10)

    # --- Table Header ---
    pdf.set_font(pdf.font_family, 'B', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(20, 7, 'SKU', 1, 0, 'C', 1)
    pdf.cell(85, 7, 'Description', 1, 0, 'C', 1)
    pdf.cell(25, 7, 'Store', 1, 0, 'C', 1)
    pdf.cell(20, 7, 'Quantity', 1, 0, 'C', 1)
    pdf.cell(20, 7, 'Unit Cost', 1, 0, 'C', 1)
    pdf.cell(20, 7, 'Total', 1, 1, 'C', 1)

    # --- Table Body ---
    pdf.set_font(pdf.font_family, '', 9)
    total_general = 0
    for _, row in df_seleccion.iterrows():
        costo_unit = pd.to_numeric(row.get('Costo_Unitario', row.get('Costo_Promedio_UND', 0)), errors='coerce')
        cantidad = pd.to_numeric(row.get('Cantidad_Solicitada', row.get('Uds a Comprar', 0)), errors='coerce')
        total_linea = costo_unit * cantidad
        total_general += total_linea
        
        pdf.cell(20, 6, str(row['SKU']), 1, 0, 'L')
        pdf.cell(85, 6, str(row['Descripcion']), 1, 0, 'L')
        pdf.cell(25, 6, str(row.get('Tienda_Destino', row.get('Tienda', ''))), 1, 0, 'C')
        pdf.cell(20, 6, str(int(cantidad)), 1, 0, 'R')
        pdf.cell(20, 6, f"${costo_unit:,.0f}", 1, 0, 'R')
        pdf.cell(20, 6, f"${total_linea:,.0f}", 1, 1, 'R')

    # --- Total ---
    pdf.set_font(pdf.font_family, 'B', 10)
    pdf.cell(170, 8, 'Grand Total', 1, 0, 'R')
    pdf.cell(20, 8, f"${total_general:,.0f}", 1, 1, 'R')
    
    return bytes(pdf.output())

def generar_excel_dinamico(df, nombre_hoja):
    """Generates a formatted Excel file from a DataFrame in memory."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        # Add formatting if needed
    return output.getvalue()
