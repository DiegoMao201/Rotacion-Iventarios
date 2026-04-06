import streamlit as st
import pandas as pd
import numpy as np
import dropbox
import io
from datetime import datetime
import time

# --- 0. CONFIGURACIÓN INICIAL ---
FERREINOX_LOGO_URL = "https://www.ferreinox.co/cdn-cgi/image/w=200/upload/logo/logo_header_ferreinox_1723217791.webp"
FERREINOX_FAVICON = "https://www.ferreinox.co/favicon.ico"

st.set_page_config(
    page_title="Ferreinox | Control de Inventarios",
    page_icon="🔴",
    layout="wide",
)

# --- ✅ 1. LÓGICA DE USUARIOS Y AUTENTICACIÓN (Sin cambios) ---
USUARIOS = {
    "gerente": {"password": "1234", "almacen": "Todas"},
    "opalo": {"password": "2345", "almacen": "Opalo"},
    "armenia": {"password": "3456", "almacen": "Armenia"},
    "cedi": {"password": "4567", "almacen": "Cedi"},
    "manizales": {"password": "5678", "almacen": "Manizales"},
    "olaya": {"password": "6789", "almacen": "Olaya"},
    "laureles": {"password": "7890", "almacen": "Laureles"},
    "ferrebox": {"password": "8901", "almacen": "FerreBox"},
    "cerritos": {"password": "9012", "almacen": "Cerritos"},
}

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.almacen_nombre = None

def login():
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <img src="https://www.ferreinox.co/cdn-cgi/image/w=280/upload/logo/logo_header_ferreinox_1723217791.webp" style="max-width: 280px; margin-bottom: 1rem;">
        <h2 style="color: #D42027; margin-bottom: 0;">Sistema de Control de Inventarios</h2>
        <p style="color: #666; font-size: 1.1rem;">Más Allá del Color — Gestión Inteligente</p>
    </div>
    """, unsafe_allow_html=True)
    col_login_l, col_login_c, col_login_r = st.columns([1, 2, 1])
    with col_login_c:
        with st.form("login_form"):
            username = st.text_input("Usuario").lower()
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Iniciar Sesión", use_container_width=True)
            if submitted:
                user_data = USUARIOS.get(username)
                if user_data and user_data["password"] == password:
                    st.session_state.logged_in = True
                    st.session_state.almacen_nombre = user_data["almacen"]
                    st.session_state.user_role = "gerente" if user_data["almacen"] == "Todas" else "tienda"
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")

def logout():
    st.session_state.clear()
    st.rerun()

if not st.session_state.get('logged_in', False):
    login()
    st.stop()

# --- ESTILOS VISUALES Y CSS — IDENTIDAD FERREINOX ---
st.markdown("""
<style>
    /* === PALETA FERREINOX === */
    :root {
        --ferreinox-rojo: #D42027;
        --ferreinox-gris: #444444;
        --ferreinox-azul: #4F81BD;
        --ferreinox-bg-light: #FDF6F6;
    }

    /* Header con línea roja corporativa */
    header[data-testid="stHeader"] {
        border-bottom: 3px solid var(--ferreinox-rojo);
    }

    /* Sidebar branding */
    section[data-testid="stSidebar"] {
        border-right: 3px solid var(--ferreinox-rojo) !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0.5rem;
    }

    /* Textos de sección */
    .section-header {
        color: var(--ferreinox-rojo);
        font-weight: 700;
        font-size: 1.15rem;
        border-bottom: 2px solid var(--ferreinox-rojo);
        padding-bottom: 6px;
        margin-bottom: 16px;
        letter-spacing: 0.3px;
    }

    .stAlert { border-radius: 10px; }

    /* Botón primario rojo Ferreinox */
    div[data-testid="stButton"] > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
        background-color: var(--ferreinox-rojo) !important;
        color: white !important;
        font-weight: 700;
        border-radius: 8px;
        border: none !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover,
    div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
        background-color: #B01A20 !important;
    }

    /* Botones secundarios */
    div[data-testid="stButton"] > button {
        border-radius: 8px;
        font-weight: 600;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        border-bottom-color: var(--ferreinox-rojo) !important;
        color: var(--ferreinox-rojo) !important;
    }

    /* Métricas */
    div[data-testid="stMetric"] {
        background-color: #FAFAFA;
        border: 1px solid #E8E8E8;
        border-left: 4px solid var(--ferreinox-rojo);
        border-radius: 8px;
        padding: 12px 16px;
    }
    div[data-testid="stMetric"] label {
        font-weight: 600;
        color: var(--ferreinox-gris);
    }

    /* Download buttons */
    div[data-testid="stDownloadButton"] > button {
        background-color: var(--ferreinox-azul) !important;
        color: white !important;
        border-radius: 8px;
        font-weight: 600;
    }

    /* Footer discreto */
    .ferreinox-footer {
        text-align: center;
        color: #999;
        font-size: 0.78rem;
        padding: 2rem 0 1rem 0;
        border-top: 1px solid #eee;
        margin-top: 3rem;
    }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE CARGA DE DATOS ---
@st.cache_data(ttl=600)
def cargar_datos_desde_dropbox():
    info_message = st.empty()
    info_message.info("Conectando a Dropbox para obtener los datos más recientes...", icon="☁️")
    column_names = ['DEPARTAMENTO','REFERENCIA','DESCRIPCION','MARCA','PESO_ARTICULO','UNIDADES_VENDIDAS','STOCK','COSTO_PROMEDIO_UND','CODALMACEN','LEAD_TIME_PROVEEDOR','HISTORIAL_VENTAS']
    try:
        dbx_creds = st.secrets["dropbox"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            metadata, res = dbx.files_download(path=dbx_creds["file_path"])
            with io.BytesIO(res.content) as stream:
                df_crudo = pd.read_csv(stream, encoding='latin1', sep='|', header=None, names=column_names)
        info_message.success("Datos de inventario cargados exitosamente!", icon="✅")
        return df_crudo
    except Exception as e:
        info_message.error(f"Error al cargar datos de inventario: {e}", icon="🔥")
        return None

@st.cache_data(ttl=600)
def cargar_proveedores_desde_dropbox():
    """Carga el archivo de proveedores 'Provedores.xlsx' desde Dropbox."""
    info_message = st.empty()
    info_message.info("Cargando archivo de proveedores desde Dropbox...", icon="🤝")
    try:
        dbx_creds = st.secrets["dropbox"]
        proveedores_path = dbx_creds["proveedores_file_path"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            metadata, res = dbx.files_download(path=proveedores_path)
            with io.BytesIO(res.content) as stream:
                df_proveedores = pd.read_excel(stream, dtype={'REFERENCIA': str, 'COD PROVEEDOR': str})

        df_proveedores.rename(columns={
            'REFERENCIA': 'SKU',
            'PROVEEDOR': 'Proveedor',
            'COD PROVEEDOR': 'SKU_Proveedor'
        }, inplace=True)
        df_proveedores.dropna(subset=['SKU_Proveedor'], inplace=True)
        df_proveedores = df_proveedores[['SKU', 'Proveedor', 'SKU_Proveedor']]

        info_message.success("Archivo de proveedores cargado exitosamente!", icon="👍")
        return df_proveedores
    except Exception as e:
        info_message.error(f"No se pudo cargar '{proveedores_path}' desde Dropbox: {e}. La información de proveedores no estará disponible.", icon="🔥")
        return pd.DataFrame(columns=['SKU', 'Proveedor', 'SKU_Proveedor'])

# ✨ NUEVA FUNCIÓN: Lógica para limpiar duplicados de SKU por almacén
def limpiar_duplicados_sku_por_almacen(df):
    if df is None or df.empty:
        return pd.DataFrame()

    # Agrupar por las columnas clave y sumar o tomar la primera aparición
    agg_funcs = {
        'DEPARTAMENTO': 'first',
        'DESCRIPCION': 'first',
        'MARCA': 'first',
        'PESO_ARTICULO': 'first',
        'UNIDADES_VENDIDAS': 'sum',
        'STOCK': 'sum',
        'COSTO_PROMEDIO_UND': 'first', # Asumimos que el costo promedio es el mismo
        'LEAD_TIME_PROVEEDOR': 'first',
        'HISTORIAL_VENTAS': lambda x: ','.join(x.dropna().astype(str).unique()) # Combina los historiales de ventas únicos
    }

    # Eliminar 'HISTORIAL_VENTAS' si todas sus filas son nulas, para evitar errores en la lambda
    if df['HISTORIAL_VENTAS'].isnull().all():
        del agg_funcs['HISTORIAL_VENTAS']
        
    df_agrupado = df.groupby(['REFERENCIA', 'CODALMACEN'], as_index=False).agg(agg_funcs)
    
    return df_agrupado

# --- LÓGICA DE ANÁLISIS DE INVENTARIO ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, _df_proveedores, dias_seguridad=7, dias_objetivo=None):
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()

    # Llama a la nueva función de limpieza
    df = limpiar_duplicados_sku_por_almacen(_df_crudo.copy())
    
    if dias_objetivo is None:
        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}

    # 1. Limpieza y Preparación
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas',
        'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
    }
    df.rename(columns=column_mapping, inplace=True)
    df['SKU'] = df['SKU'].astype(str)
    almacen_map = {'158':'Opalo', '155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox','463':'Cerritos'}
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
    df_ventas = df_ventas.assign(Historial_Ventas=df_ventas['Historial_Ventas'].str.split(',')).explode('Historial_Ventas')
    df_ventas[['Fecha_Venta', 'Unidades']] = df_ventas['Historial_Ventas'].str.split(':', expand=True)
    df_ventas['Fecha_Venta'] = pd.to_datetime(df_ventas['Fecha_Venta'], errors='coerce')
    df_ventas['Unidades'] = pd.to_numeric(df_ventas['Unidades'], errors='coerce')
    df_ventas.dropna(subset=['Fecha_Venta', 'Unidades'], inplace=True)
    df_ventas = df_ventas[(pd.Timestamp.now() - df_ventas['Fecha_Venta']).dt.days <= 60]
    demanda_diaria = df_ventas.groupby('index')['Unidades'].sum() / 60
    df = df.merge(demanda_diaria.rename('Demanda_Diaria_Promedio'), on='index', how='left').fillna({'Demanda_Diaria_Promedio': 0})
    # FALLBACK: Si Historial_Ventas no parsó pero hay ventas reportadas, usar ese dato
    mask_fallback = (df['Demanda_Diaria_Promedio'] == 0) & (df['Ventas_60_Dias'] > 0)
    df.loc[mask_fallback, 'Demanda_Diaria_Promedio'] = df.loc[mask_fallback, 'Ventas_60_Dias'] / 60
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
    # --- MÉTRICAS AVANZADAS DE ROTACIÓN ---
    df['Cobertura_Dias'] = np.where(
        df['Demanda_Diaria_Promedio'] > 0,
        df['Stock'] / df['Demanda_Diaria_Promedio'],
        9999  # Sin demanda = cobertura infinita
    )
    df['Rotacion_Inventario'] = np.where(
        df['Valor_Inventario'] > 0,
        (df['Valor_Venta_60_Dias'] / df['Valor_Inventario']) * 6,  # Anualizado (60d * 6 = 360d)
        0
    )
    df['Venta_Perdida_Estimada_30d'] = np.where(
        (df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),
        df['Demanda_Diaria_Promedio'] * 30 * df['Costo_Promedio_UND'] * 1.30,  # Margen estimado 30%
        0
    )
    # Velocidad de venta: cambio periodo actual vs anterior
    df['Precio_Venta_Estimado'] = df['Costo_Promedio_UND'] * 1.30

    # Objetivo real: el mayor entre stock_objetivo y punto_reorden (cubre lead times largos)
    df['Objetivo_Abastecimiento'] = np.maximum(df['Stock_Objetivo'], df['Punto_Reorden'])
    # Necesidad proactiva: anticipa el consumo durante el lead time del proveedor
    df['Necesidad_Total'] = np.maximum(0,
        df['Objetivo_Abastecimiento'] - df['Stock']
        + (df['Demanda_Diaria_Promedio'] * df['Lead_Time_Proveedor'])
    )
    # Excedente_Trasladable: stock que esta tienda puede ceder a otras
    # - Excedente: todo lo que sobra por encima del Objetivo_Abastecimiento
    # - Baja Rotación: TODO el stock (si no vende aquí, que venda en otra sede)
    # - Normal/Bajo Stock/Quiebre: no ceden stock
    df['Excedente_Trasladable'] = np.select(
        [
            df['Estado_Inventario'] == 'Excedente',
            df['Estado_Inventario'] == 'Baja Rotación / Obsoleto',
        ],
        [
            np.maximum(0, df['Stock'] - df['Objetivo_Abastecimiento']),
            df['Stock'],  # Todo el stock sin rotación es trasladable
        ],
        default=0
    )
    sku_summary = df.groupby('SKU').agg(
        Total_Necesidad_SKU=('Necesidad_Total', 'sum'),
        Total_Excedente_SKU=('Excedente_Trasladable', 'sum')
    ).reset_index()
    sku_summary['Total_Traslados_Posibles_SKU'] = np.minimum(sku_summary['Total_Necesidad_SKU'], sku_summary['Total_Excedente_SKU'])
    df = df.merge(sku_summary.drop(columns=['Total_Necesidad_SKU']), on='SKU', how='left')
    df['Unidades_Traslado_Sugeridas'] = 0.0
    mask_necesidad = (df['Necesidad_Total'] > 0) & (df.groupby('SKU')['Necesidad_Total'].transform('sum') > 0)
    df.loc[mask_necesidad, 'Unidades_Traslado_Sugeridas'] = (df['Necesidad_Total'] / df.groupby('SKU')['Necesidad_Total'].transform('sum')) * df['Total_Traslados_Posibles_SKU']
    df['Sugerencia_Compra'] = np.maximum(0, np.ceil(df['Necesidad_Total'] - df['Unidades_Traslado_Sugeridas'].fillna(0)))
    df['Unidades_Traslado_Sugeridas'] = np.ceil(df['Unidades_Traslado_Sugeridas'].fillna(0))

    if _df_proveedores is not None and not _df_proveedores.empty:
        _df_proveedores_dedup = _df_proveedores.drop_duplicates(subset=['SKU'], keep='first')
        df = pd.merge(df, _df_proveedores_dedup, on='SKU', how='left')
        df['Proveedor'] = df['Proveedor'].fillna('No Asignado')
        df['SKU_Proveedor'] = df['SKU_Proveedor'].fillna('N/A')
    else:
        df['Proveedor'] = 'No Asignado'
        df['SKU_Proveedor'] = 'N/A'

    return df.set_index('index')

# --- INICIO DE LA INTERFAZ DE USUARIO ---
st.sidebar.markdown("""
<div style="text-align: center; padding: 0.5rem 0 0.5rem 0;">
    <img src="https://www.ferreinox.co/cdn-cgi/image/w=200/upload/logo/logo_header_ferreinox_1723217791.webp" style="max-width: 180px;">
</div>
""", unsafe_allow_html=True)
st.sidebar.markdown(f"**🏪 {st.session_state.almacen_nombre}**")
st.sidebar.button("Cerrar Sesión", on_click=logout)
st.sidebar.markdown("---")

st.markdown("""
<div style="display: flex; align-items: center; gap: 16px; margin-bottom: 0;">
    <div>
        <h1 style="margin: 0; color: #D42027;">Control de Inventarios</h1>
        <p style="margin: 0; color: #888; font-size: 0.95rem;">Ferreinox SAS BIC — Más Allá del Color | Actualizado: """ + datetime.now().strftime('%d/%m/%Y %H:%M') + """</p>
    </div>
</div>
""", unsafe_allow_html=True)

col_upd1, col_upd2 = st.columns([1, 5])
with col_upd1:
    if st.button("🔄 Actualizar Datos", help="Borra la caché y recarga desde Dropbox.", type="primary"):
        st.cache_data.clear()
        toast_message = st.toast('Borrando caché y recargando datos...', icon='⏳')
        time.sleep(2)
        toast_message.toast('¡Datos actualizados! Recargando panel...', icon='✅')
        time.sleep(1)
        st.rerun()

st.markdown("---")

# Cargar ambos dataframes desde Dropbox
df_crudo = cargar_datos_desde_dropbox()
df_proveedores = cargar_proveedores_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Parámetros del Análisis")
    dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad (Min):", 1, 30, 7)
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Días de Inventario Objetivo (Max)**")
    dias_obj_a = st.sidebar.slider("Clase A (VIPs)", 15, 45, 30)
    dias_obj_b = st.sidebar.slider("Clase B (Importantes)", 30, 60, 45)
    dias_obj_c = st.sidebar.slider("Clase C (Generales)", 45, 90, 60)

    with st.spinner("Analizando inventario y asignando proveedores..."):
        dias_objetivo_dict = {'A': dias_obj_a, 'B': dias_obj_b, 'C': dias_obj_c}
        df_analisis_completo = analizar_inventario_completo(
            df_crudo,
            df_proveedores,
            dias_seguridad=dias_seguridad_input,
            dias_objetivo=dias_objetivo_dict
        ).reset_index()

    st.session_state['df_analisis_maestro'] = df_analisis_completo.copy()

    if st.session_state.user_role == 'tienda':
        st.session_state['df_analisis'] = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == st.session_state.almacen_nombre]
    else:
        st.session_state['df_analisis'] = df_analisis_completo.copy()

    if st.session_state.user_role == 'gerente':
        opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
        nombres_almacen = [opcion_consolidado] + sorted(df_analisis_completo['Almacen_Nombre'].unique().tolist())
        selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", nombres_almacen)
        df_vista = df_analisis_completo if selected_almacen_nombre == opcion_consolidado else df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == selected_almacen_nombre]
    else:
        selected_almacen_nombre = st.session_state.almacen_nombre
        st.sidebar.markdown(f"**Vista actual:** `{selected_almacen_nombre}`")
        df_vista = st.session_state['df_analisis']

    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else df_vista

    st.markdown(f'<p class="section-header">Métricas Clave: {selected_almacen_nombre}</p>', unsafe_allow_html=True)
    if not df_filtered.empty:
        valor_total_inv = df_filtered['Valor_Inventario'].sum()
        skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        valor_sobrestock = df_filtered[df_filtered['Estado_Inventario'] == 'Excedente']['Valor_Inventario'].sum()
        valor_baja_rotacion = df_filtered[df_filtered['Estado_Inventario'] == 'Baja Rotación / Obsoleto']['Valor_Inventario'].sum()
        venta_perdida_30d = df_filtered['Venta_Perdida_Estimada_30d'].sum()
        # Rotación promedio ponderada por valor
        rotacion_promedio = (df_filtered['Rotacion_Inventario'] * df_filtered['Valor_Inventario']).sum() / valor_total_inv if valor_total_inv > 0 else 0
        # Fill rate: % SKUs con stock vs total SKUs activos (con demanda)
        skus_con_demanda = df_filtered[df_filtered['Demanda_Diaria_Promedio'] > 0]['SKU'].nunique()
        skus_con_stock_y_demanda = df_filtered[(df_filtered['Stock'] > 0) & (df_filtered['Demanda_Diaria_Promedio'] > 0)]['SKU'].nunique()
        fill_rate = (skus_con_stock_y_demanda / skus_con_demanda * 100) if skus_con_demanda > 0 else 100
    else:
        valor_total_inv, skus_quiebre, valor_sobrestock, valor_baja_rotacion = 0, 0, 0, 0
        venta_perdida_30d, rotacion_promedio, fill_rate = 0, 0, 100

    # --- FILA 1: KPIs PRINCIPALES ---
    col1, col2, col3 = st.columns(3)
    col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
    col2.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}", delta=f"-${venta_perdida_30d:,.0f} venta perdida/mes" if venta_perdida_30d > 0 else None, delta_color="inverse")
    col3.metric(label="✅ Fill Rate (Disponibilidad)", value=f"{fill_rate:.1f}%", help="% de productos con demanda que tienen stock disponible. Meta: >95%")

    # --- FILA 2: KPIs DE EFICIENCIA ---
    col4, col5, col6 = st.columns(3)
    col4.metric(label="📉 Capital en Excedente", value=f"${valor_sobrestock + valor_baja_rotacion:,.0f}", help="Sobre-stock + Baja Rotación")
    col5.metric(label="🔄 Rotación Anualizada", value=f"{rotacion_promedio:.1f}x", help="Veces que rota el inventario al año. Ideal: >4x")
    col6.metric(label="💀 Stock Muerto (Sin Rotación)", value=f"${valor_baja_rotacion:,.0f}", help="Sin ventas en 60 días")

    st.markdown("---")

    # --- NAVEGACIÓN RÁPIDA A MÓDULOS ---
    st.markdown('<p class="section-header">Centro de Comando</p>', unsafe_allow_html=True)
    
    if skus_quiebre > 0:
        st.error(f"🚨 **{skus_quiebre} productos en quiebre** generan una pérdida estimada de **${venta_perdida_30d:,.0f}/mes**. ¡Actúa ahora!")
        st.page_link("pages/5_gestion_quiebres.py", label="⚡ Atender Quiebres de Stock", icon="🩹")
    st.markdown("---")

    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Abastecimiento", icon="🚚")
        st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")
    with col_nav2:
        st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="📊")
        st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")

    st.markdown('<p class="section-header" style="margin-top: 20px;">Diagnóstico Inteligente</p>', unsafe_allow_html=True)
    with st.container(border=True):
        if not df_filtered.empty:
            valor_excedente_total = valor_sobrestock + valor_baja_rotacion
            porc_excedente = (valor_excedente_total / valor_total_inv) * 100 if valor_total_inv > 0 else 0
            
            # Diagnóstico multi-factor
            alertas = []
            if skus_quiebre > 10:
                alertas.append(f"🚨 **Quiebres Críticos:** {skus_quiebre} productos agotados. Pérdida estimada: **${venta_perdida_30d:,.0f}/mes**.")
            if fill_rate < 90:
                alertas.append(f"📉 **Disponibilidad Baja:** Solo el {fill_rate:.0f}% de productos con demanda tienen stock. Meta: >95%.")
            if porc_excedente > 30:
                alertas.append(f"💸 **Capital Inmovilizado:** {porc_excedente:.1f}% del inventario es excedente (${valor_excedente_total:,.0f}).")
            if rotacion_promedio < 3 and rotacion_promedio > 0:
                alertas.append(f"🔄 **Rotación Lenta:** {rotacion_promedio:.1f}x anual. Tu inventario tarda en promedio **{int(365/rotacion_promedio) if rotacion_promedio > 0 else 999} días** en venderse.")
            
            if alertas:
                for alerta in alertas:
                    st.warning(alerta)
                # Recomendación priorizada
                if skus_quiebre > 10:
                    st.info("🎯 **Prioridad #1:** Resolver quiebres de clase A y B para recuperar ventas inmediatamente.")
                elif fill_rate < 90:
                    st.info("🎯 **Prioridad #1:** Mejorar abastecimiento para subir el Fill Rate a >95%.")
                elif porc_excedente > 30:
                    st.info("🎯 **Prioridad #1:** Ejecutar traslados y liquidaciones para liberar capital.")
            else:
                st.success(f"✅ **Inventario Saludable:** {selected_almacen_nombre} — Fill Rate {fill_rate:.0f}% | Rotación {rotacion_promedio:.1f}x | Sin alertas críticas.", icon="✅")
        elif st.session_state.get('user_role') == 'gerente' and selected_almacen_nombre == "-- Consolidado (Todas las Tiendas) --":
            st.info("Selecciona una tienda específica en el filtro para ver su diagnóstico detallado.")
        else:
            st.info("No hay datos para los filtros seleccionados.")

    st.markdown("---")
    st.markdown('<p class="section-header">🔍 Consulta de Inventario por Producto</p>', unsafe_allow_html=True)
    search_term = st.text_input("Buscar producto por SKU, Descripción o cualquier palabra clave:", placeholder="Ej: 'ESTUCO', '102030', 'ACRILICO BLANCO'")
    if search_term:
        df_search_initial = df_analisis_completo[
            df_analisis_completo['SKU'].astype(str).str.contains(search_term, case=False, na=False) |
            df_analisis_completo['Descripcion'].astype(str).str.contains(search_term, case=False, na=False)
        ]
        if df_search_initial.empty:
            st.warning("No se encontraron productos que coincidan con la búsqueda.")
        else:
            found_skus = df_search_initial['SKU'].unique()
            df_stock_completo = df_analisis_completo[df_analisis_completo['SKU'].isin(found_skus)]

            tab_stock, tab_detalle = st.tabs(["📊 Matriz de Stock por Tienda", "📋 Detalle Completo"])

            with tab_stock:
                pivot_stock = df_stock_completo.pivot_table(
                    index=['SKU', 'Descripcion', 'Marca_Nombre'],
                    columns='Almacen_Nombre',
                    values='Stock',
                    fill_value=0
                )
                st.dataframe(pivot_stock, use_container_width=True)

            with tab_detalle:
                cols_detalle = ['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Demanda_Diaria_Promedio',
                                'Cobertura_Dias', 'Estado_Inventario', 'Segmento_ABC', 'Sugerencia_Compra',
                                'Excedente_Trasladable', 'Costo_Promedio_UND', 'Proveedor']
                cols_existentes = [c for c in cols_detalle if c in df_stock_completo.columns]
                df_detalle_display = df_stock_completo[cols_existentes].copy()
                df_detalle_display['Cobertura_Dias'] = df_detalle_display['Cobertura_Dias'].clip(upper=999).astype(int)
                st.dataframe(
                    df_detalle_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'Almacen_Nombre': 'Tienda',
                        'Demanda_Diaria_Promedio': st.column_config.NumberColumn('Demanda/Día', format='%.2f'),
                        'Cobertura_Dias': st.column_config.ProgressColumn('Cobertura (Días)', min_value=0, max_value=120),
                        'Costo_Promedio_UND': st.column_config.NumberColumn('Costo UND', format='$%d'),
                        'Sugerencia_Compra': st.column_config.NumberColumn('Sug. Compra', format='%d'),
                        'Excedente_Trasladable': st.column_config.NumberColumn('Excedente', format='%d'),
                    }
                )

    # --- FOOTER ---
    st.markdown('<div class="ferreinox-footer">Ferreinox SAS BIC — NIT 800.224.617 | Sistema de Control de Inventarios | www.ferreinox.co</div>', unsafe_allow_html=True)
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error, el archivo en Dropbox o intenta actualizar los datos.")
