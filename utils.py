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

# --- CONSTANTES Y CONFIGURACIONES ---
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

def validate_dataframe(df, required_columns, df_name="DataFrame"):
    if df is None or df.empty:
        st.error(f"Error: El {df_name} está vacío o no se pudo cargar.")
        return False
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        st.error(f"Error en {df_name}: Faltan las siguientes columnas requeridas: {', '.join(missing_cols)}")
        return False
    return True

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
    marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
    df['Marca_Nombre'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str).map(marca_map).fillna('Complementarios')
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True)

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

    if dias_objetivo is None:
        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}
    df['dias_objetivo_map'] = df['Segmento_ABC'].map(dias_objetivo)
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * df['dias_objetivo_map']

    conditions = [
        (df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),
        (df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0),
        (df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']),
        (df['Stock'] > df['Stock_Objetivo']),
    ]
    choices_estado = ['Quiebre de Stock', 'Baja Rotación / Obsoleto', 'Bajo Stock (Riesgo)', 'Excedente']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    df['Excedente_Trasladable'] = np.where(
        df['Estado_Inventario'] == 'Excedente',
        np.maximum(0, df['Stock'] - df['Stock_Objetivo']), 0
    )
    
    if _df_proveedores is not None and not _df_proveedores.empty and validate_dataframe(_df_proveedores, ['SKU'], "archivo de proveedores"):
        df = pd.merge(df, _df_proveedores, on='SKU', how='left')

    df['Proveedor'] = df.get('Proveedor', 'No Asignado').fillna('No Asignado')
    df['SKU_Proveedor'] = df.get('SKU_Proveedor', 'N/A').fillna('N/A')

    return df.set_index('index')

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
        st.error(f"Error: La hoja de Google '{sheet_name}' no fue encontrada.")
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
        return True, f"Hoja '{sheet_name}' actualizada exitosamente."
    except Exception as e:
        return False, f"Error al actualizar la hoja '{sheet_name}': {e}"

def append_to_sheet(client, sheet_name, df_to_append):
    try:
        spreadsheet = client.open_by_key(st.secrets["gsheets"]["spreadsheet_key"])
        worksheet = spreadsheet.worksheet(sheet_name)
        headers = worksheet.row_values(1)
        df_to_append_str = df_to_append.astype(str).replace(np.nan, '')
        
        if not headers:
            worksheet.update([df_to_append_str.columns.values.tolist()] + df_to_append_str.values.tolist())
            return True, "Hoja creada y registros añadidos.", df_to_append
            
        df_to_append_ordered = df_to_append_str.reindex(columns=headers).fillna('')
        worksheet.append_rows(df_to_append_ordered.values.tolist(), value_input_option='USER_ENTERED')
        
        return True, f"Nuevos registros añadidos a '{sheet_name}'.", df_to_append
    except Exception as e:
        return False, f"Error al añadir registros en '{sheet_name}': {e}", pd.DataFrame()

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis):
    required_cols = ['Excedente_Trasladable', 'Necesidad_Ajustada_Por_Transito', 'SKU', 'Almacen_Nombre']
    if not validate_dataframe(_df_analisis, required_cols, "análisis para traslados"):
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
                    'Marca_Nombre': origin_row.get('Marca_Nombre', 'N/A'),
                    'Proveedor': origin_row.get('Proveedor', 'N/A'), 
                    'Segmento_ABC': need_row.get('Segmento_ABC', 'C'),
                    'Tienda Origen': tienda_origen, 'Stock en Origen': origin_row.get('Stock', 0),
                    'Tienda Destino': tienda_necesitada, 'Stock en Destino': need_row.get('Stock', 0),
                    'Necesidad en Destino': need_row.get('Necesidad_Ajustada_Por_Transito', 0),
                    'Uds a Enviar': np.floor(unidades_a_enviar),
                    'Peso Individual (kg)': need_row.get('Peso_Articulo', 0),
                    'Costo_Promedio_UND': need_row.get('Costo_Promedio_UND', 0)
                })
                
                necesidad -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
                if necesidad <= 0: break

    if not plan_final: return pd.DataFrame()
    
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Uds a Enviar'] = df_resultado['Uds a Enviar'].astype(int)
    df_resultado['Peso del Traslado (kg)'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Peso Individual (kg)'])
    df_resultado['Valor del Traslado'] = pd.to_numeric(df_resultado['Uds a Enviar']) * pd.to_numeric(df_resultado['Costo_Promedio_UND'])
    
    return df_resultado[df_resultado['Uds a Enviar'] > 0].sort_values(by=['Valor del Traslado'], ascending=False)

@st.cache_data
def calcular_sugerencias_finales(_df_base, _df_ordenes):
    df_maestro = _df_base.copy()
    
    df_maestro['Stock_En_Transito'] = 0

    if not _df_ordenes.empty and 'Estado' in _df_ordenes.columns:
        df_pendientes = _df_ordenes[_df_ordenes['Estado'] == 'Pendiente'].copy()
        if not df_pendientes.empty and 'Cantidad_Solicitada' in df_pendientes.columns:
            df_pendientes['Cantidad_Solicitada'] = pd.to_numeric(df_pendientes['Cantidad_Solicitada'], errors='coerce').fillna(0)
            stock_en_transito_agg = df_pendientes.groupby(['SKU', 'Tienda_Destino'])['Cantidad_Solicitada'].sum().reset_index()
            stock_en_transito_agg = stock_en_transito_agg.rename(columns={'Cantidad_Solicitada': 'Stock_En_Transito_Nuevas', 'Tienda_Destino': 'Almacen_Nombre'})
            
            df_maestro = pd.merge(df_maestro, stock_en_transito_agg, on=['SKU', 'Almacen_Nombre'], how='left')
            df_maestro['Stock_En_Transito'] = df_maestro['Stock_En_Transito'].add(df_maestro['Stock_En_Transito_Nuevas'], fill_value=0)
            df_maestro.drop(columns=['Stock_En_Transito_Nuevas'], inplace=True)

    df_maestro['Necesidad_Ajustada_Por_Transito'] = (df_maestro['Necesidad_Total'] - df_maestro['Stock_En_Transito']).clip(lower=0)
    
    df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)
    
    # --- INICIO DE LA LÓGICA CORREGIDA PARA 'Cubierto_Por_Traslado' ---
    # Se inicializa la columna para evitar el KeyError
    df_maestro['Cubierto_Por_Traslado'] = 0
    
    if not df_plan_maestro.empty:
        unidades_cubiertas = df_plan_maestro.groupby(['SKU', 'Tienda Destino'])['Uds a Enviar'].sum().reset_index()
        unidades_cubiertas = unidades_cubiertas.rename(columns={'Tienda Destino': 'Almacen_Nombre', 'Uds a Enviar': 'Cubierto_Por_Traslado_Nuevas'})
        
        df_maestro = pd.merge(df_maestro, unidades_cubiertas, on=['SKU', 'Almacen_Nombre'], how='left')
        df_maestro['Cubierto_Por_Traslado'] = df_maestro['Cubierto_Por_Traslado'].add(df_maestro['Cubierto_Por_Traslado_Nuevas'], fill_value=0)
        df_maestro.drop(columns=['Cubierto_Por_Traslado_Nuevas'], inplace=True)
    # --- FIN DE LA LÓGICA CORREGIDA ---

    df_maestro['Sugerencia_Compra'] = np.ceil(df_maestro['Necesidad_Ajustada_Por_Transito'] - df_maestro['Cubierto_Por_Traslado']).clip(lower=0)
    df_maestro['Sugerencia_Compra'] = df_maestro['Sugerencia_Compra'].astype(int)

    return df_maestro, df_plan_maestro

def registrar_ordenes_en_sheets(client, df_orden, tipo_orden, proveedor_nombre=None, tienda_destino=None):
    if df_orden.empty or client is None:
        return False, "No hay datos válidos para registrar.", pd.DataFrame()
    df_registro = df_orden.copy()
    if 'Uds a Comprar' in df_registro.columns: cantidad_col = 'Uds a Comprar'
    elif 'Uds a Enviar' in df_registro.columns: cantidad_col = 'Uds a Enviar'
    elif 'Cantidad_Solicitada' in df_registro.columns: cantidad_col = 'Cantidad_Solicitada'
    else: return False, "No se encontró columna de cantidad.", pd.DataFrame()
    if 'Costo_Promedio_UND' in df_registro.columns: costo_col = 'Costo_Promedio_UND'
    elif 'Costo_Unitario' in df_registro.columns: costo_col = 'Costo_Unitario'
    else: return False, "No se encontró columna de costo.", pd.DataFrame()
    df_registro['Cantidad_Solicitada'] = df_registro[cantidad_col]
    df_registro['Costo_Unitario'] = df_registro.get(costo_col, 0)
    df_registro['Costo_Total'] = pd.to_numeric(df_registro['Cantidad_Solicitada'], errors='coerce').fillna(0) * pd.to_numeric(df_registro['Costo_Unitario'], errors='coerce').fillna(0)
    df_registro['Estado'] = 'Pendiente'
    df_registro['Fecha_Emision'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base_id = ""
    if tipo_orden == "Compra Sugerencia":
        base_id = f"OC-{timestamp}"
        df_registro['Tienda_Destino'] = df_registro['Tienda']
    elif tipo_orden == "Compra Especial":
        base_id = f"OC-SP-{timestamp}"
        df_registro['Proveedor'] = proveedor_nombre
        df_registro['Tienda_Destino'] = tienda_destino
    elif tipo_orden == "Traslado Automático":
        base_id = f"TR-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = df_registro['Tienda Destino']
    elif tipo_orden == "Traslado Especial":
        base_id = f"TR-SP-{timestamp}"
        df_registro['Proveedor'] = "TRASLADO: " + df_registro['Tienda Origen']
        df_registro['Tienda_Destino'] = tienda_destino
    else:
        return False, f"Tipo de orden no reconocido: '{tipo_orden}'.", pd.DataFrame()
    df_registro['ID_Orden'] = [f"{base_id}-{i+1}" for i in range(len(df_registro))]
    df_final_para_gsheets = df_registro.reindex(columns=GSHEETS_FINAL_COLS).fillna('')
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
            part = MIMEBase(adj_info.get('tipo_mime', 'application'), adj_info.get('subtipo_mime', 'octet-stream'))
            part.set_payload(adj_info['datos'])
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename={adj_info['nombre_archivo']}")
            msg.attach(part)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(remitente, password)
            server.sendmail(remitente, destinatarios, msg.as_string())
        return True, "Correo enviado exitosamente."
    except smtplib.SMTPAuthenticationError:
        return False, "Error de autenticación con Gmail. Revisa el email y la contraseña."
    except Exception as e:
        return False, f"Error al enviar el correo: '{e}'."

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
        try:
            base_path = os.path.dirname(__file__)
            font_path = os.path.join(base_path, 'fonts', 'DejaVuSans.ttf')
            font_path_bold = os.path.join(base_path, 'fonts', 'DejaVuSans-Bold.ttf')
            if os.path.exists(font_path) and os.path.exists(font_path_bold):
                self.add_font('DejaVu', '', font_path, uni=True)
                self.add_font('DejaVu', 'B', font_path_bold, uni=True)
                self.font_family = 'DejaVu'
        except Exception:
            if 'font_warning_shown' not in st.session_state:
                st.warning("Fuentes personalizadas no encontradas. Usando fuente por defecto.")
                st.session_state.font_warning_shown = True
            self.font_family = 'Helvetica'

    def header(self):
        try:
            self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError:
            self.set_xy(10, 8); self.set_font(self.font_family, 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font(self.font_family, 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R')
        self.set_x(80); self.set_font(self.font_family, '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R')
        self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(*self.color_rojo_ferreinox)
        self.set_line_width(1)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)
        self.set_font(self.font_family, '', 8)
        self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}   |   {self.empresa_web}   |   {self.empresa_email}   |   {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C')
        self.set_y(-12)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor, orden_num, is_consolidated=False):
    if df_seleccion.empty: return None
    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font(pdf.font_family, 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1)
    pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font(pdf.font_family, '', 9)
    y_start_prov = pdf.get_y()
    proveedor_info = f"Razón Social: {proveedor_nombre}\nContacto: {contacto_proveedor if contacto_proveedor else 'No especificado'}"
    pdf.multi_cell(95, 7, proveedor_info, 1, 'L')
    y_end_prov = pdf.get_y()
    pdf.set_y(y_start_prov); pdf.set_x(105)
    envio_info = f"{pdf.empresa_nombre} - Sede {tienda_nombre}\nDirección: {direccion_entrega}\nRecibe: Leivyn Gabriel Garcia"
    if is_consolidated:
        envio_info = "Ferreinox SAS BIC\nDirección: Múltiples destinos según detalle\nRecibe: Coordinar con cada tienda"
    pdf.multi_cell(95, 7, envio_info, 1, 'L')
    y_end_envio = pdf.get_y()
    pdf.set_y(max(y_end_prov, y_end_envio)); pdf.ln(5)
    pdf.set_font(pdf.font_family, 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {orden_num}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1)
    pdf.ln(10)
    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf.font_family, 'B', 9)
    # ... (El resto de la lógica de generación de PDF se mantiene)
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
        for col_num, value in enumerate(df.columns.values): 
            worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            try:
                column_len = df[col].astype(str).map(len).max()
                max_len = max(column_len if pd.notna(column_len) else 0, len(col)) + 2
                worksheet.set_column(i, i, min(max_len, 45))
            except Exception:
                worksheet.set_column(i, i, 15)
    return output.getvalue()
