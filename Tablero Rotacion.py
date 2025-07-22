# Tablero_Principal.py

import streamlit as st
import pandas as pd
import numpy as np
import dropbox
import io
from datetime import datetime
import time

# --- 0. CONFIGURACIÓN INICIAL ---
st.set_page_config(
    page_title="Resumen Ejecutivo de Inventario",
    page_icon="🚀",
    layout="wide",
)

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.almacen_nombre = None
    st.session_state.df_analisis_maestro = pd.DataFrame()

# --- 1. LÓGICA DE USUARIOS Y AUTENTICACIÓN ---
USUARIOS = {
    "gerente": {"password": "1234", "almacen": "Todas"},
    "opalo": {"password": "2345", "almacen": "Opalo"},
    "armenia": {"password": "3456", "almacen": "Armenia"},
    "cedi": {"password": "4567", "almacen": "Cedi"},
    "manizales": {"password": "5678", "almacen": "Manizales"},
    "olaya": {"password": "6789", "almacen": "Olaya"},
    "laureles": {"password": "7890", "almacen": "Laureles"},
    "ferrebox": {"password": "8901", "almacen": "FerreBox"}
}

def login():
    st.title("🚀 Panel de Control de Inventarios")
    st.subheader("Por favor, inicia sesión para continuar")
    with st.form("login_form"):
        username = st.text_input("Usuario").lower()
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Iniciar Sesión")
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
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if not st.session_state.get('logged_in', False):
    login()
    st.stop()

# --- ESTILOS VISUALES Y CSS ---
st.markdown("""
<style>
    .section-header { color: #4F8BF9; font-weight: bold; border-bottom: 2px solid #4F8BF9; padding-bottom: 5px; margin-bottom: 15px; }
    .stAlert { border-radius: 10px; }
    div[data-testid="stButton"] > button { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE CARGA DE DATOS DESDE DROPBOX ---
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
    info_message = st.empty()
    info_message.info("Cargando archivo de proveedores desde Dropbox...", icon="🤝")
    try:
        dbx_creds = st.secrets["dropbox"]
        proveedores_path = dbx_creds["proveedores_file_path"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            metadata, res = dbx.files_download(path=proveedores_path)
            with io.BytesIO(res.content) as stream:
                df_proveedores = pd.read_excel(stream, dtype={'REFERENCIA': str, 'COD PROVEEDOR': str})
        df_proveedores.rename(columns={'REFERENCIA': 'SKU', 'PROVEEDOR': 'Proveedor', 'COD PROVEEDOR': 'SKU_Proveedor'}, inplace=True)
        df_proveedores.dropna(subset=['SKU_Proveedor'], inplace=True)
        df_proveedores = df_proveedores[['SKU', 'Proveedor', 'SKU_Proveedor']]
        info_message.success("Archivo de proveedores cargado exitosamente!", icon="👍")
        return df_proveedores
    except Exception as e:
        info_message.error(f"No se pudo cargar '{proveedores_path}'. La info de proveedores no estará disponible.", icon="🔥")
        return pd.DataFrame(columns=['SKU', 'Proveedor', 'SKU_Proveedor'])

# --- LÓGICA DE ANÁLISIS DE INVENTARIO ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, _df_proveedores, dias_seguridad=7, dias_objetivo=None):
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()
    if dias_objetivo is None:
        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}
    df = _df_crudo.copy()
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas',
        'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
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
    df_ventas = df_ventas.assign(Historial_Ventas=df_ventas['Historial_Ventas'].str.split(',')).explode('Historial_Ventas')
    if not df_ventas.empty:
        df_ventas[['Fecha_Venta', 'Unidades']] = df_ventas['Historial_Ventas'].str.split(':', expand=True)
        df_ventas['Fecha_Venta'] = pd.to_datetime(df_ventas['Fecha_Venta'], errors='coerce')
        df_ventas['Unidades'] = pd.to_numeric(df_ventas['Unidades'], errors='coerce')
        df_ventas.dropna(subset=['Fecha_Venta', 'Unidades'], inplace=True)
        df_ventas = df_ventas[(pd.Timestamp.now() - df_ventas['Fecha_Venta']).dt.days <= 60]
        demanda_diaria = df_ventas.groupby('index')['Unidades'].sum() / 60
        df = df.merge(demanda_diaria.rename('Demanda_Diaria_Promedio'), on='index', how='left')
    df['Demanda_Diaria_Promedio'] = df.get('Demanda_Diaria_Promedio', 0).fillna(0)
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
    conditions = [(df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),(df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0),(df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']),(df['Stock'] > df['Stock_Objetivo']),]
    choices_estado = ['Quiebre de Stock', 'Baja Rotación / Obsoleto', 'Bajo Stock (Riesgo)', 'Excedente']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    df['Excedente_Trasladable'] = np.where(df['Estado_Inventario'] == 'Excedente', np.maximum(0, df['Stock'] - df['Stock_Objetivo']), 0)
    if _df_proveedores is not None and not _df_proveedores.empty:
        df = pd.merge(df, _df_proveedores, on='SKU', how='left')
    df['Proveedor'] = df.get('Proveedor', 'No Asignado').fillna('No Asignado')
    df['SKU_Proveedor'] = df.get('SKU_Proveedor', 'N/A').fillna('N/A')
    return df.set_index('index')

# --- INICIO DE LA INTERFAZ DE USUARIO ---
st.sidebar.title(f"Usuario: {st.session_state.almacen_nombre}")
st.sidebar.button("Cerrar Sesión", on_click=logout)
st.sidebar.markdown("---")

st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

if st.button("🔄 Actualizar Datos de Inventario", help="Vuelve a cargar los archivos más recientes desde Dropbox."):
    st.cache_data.clear()
    st.toast('Borrando caché y recargando datos...', icon='⏳')
    time.sleep(2)
    st.toast('¡Datos actualizados! Recargando panel...', icon='✅')
    time.sleep(1)
    st.rerun()

st.markdown("---")

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

    with st.spinner("Analizando inventario..."):
        dias_objetivo_dict = {'A': dias_obj_a, 'B': dias_obj_b, 'C': dias_obj_c}
        df_analisis_completo = analizar_inventario_completo(
            df_crudo, df_proveedores,
            dias_seguridad=dias_seguridad_input,
            dias_objetivo=dias_objetivo_dict
        ).reset_index()

    st.session_state['df_analisis_maestro'] = df_analisis_completo.copy()

    # --- INICIO: NUEVOS FILTROS GLOBALES MEJORADOS ---
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 Filtros Globales de Gestión")
    
    # Filtro de Tienda
    if st.session_state.user_role == 'gerente':
        all_stores = sorted(df_analisis_completo['Almacen_Nombre'].unique().tolist())
        selected_stores = st.sidebar.multiselect("Filtrar por Tienda(s):", all_stores, default=all_stores)
    else:
        selected_stores = [st.session_state.almacen_nombre]
        st.sidebar.markdown(f"**Vista de Tienda:** `{selected_stores[0]}`")

    df_vista = df_analisis_completo[df_analisis_completo['Almacen_Nombre'].isin(selected_stores)]

    # Filtros Jerárquicos
    all_departments = sorted(df_vista['Departamento'].unique().tolist())
    selected_departments = st.sidebar.multiselect("Filtrar por Departamento(s):", all_departments, default=all_departments)
    df_vista_dep = df_vista[df_vista['Departamento'].isin(selected_departments)]

    all_brands = sorted(df_vista_dep['Marca_Nombre'].unique().tolist())
    selected_brands = st.sidebar.multiselect("Filtrar por Marca(s):", all_brands, default=all_brands)
    df_vista_brand = df_vista_dep[df_vista_dep['Marca_Nombre'].isin(selected_brands)]

    all_providers = sorted(df_vista_brand['Proveedor'].unique().tolist())
    selected_providers = st.sidebar.multiselect("Filtrar por Proveedor(es):", all_providers, default=all_providers)
    
    df_filtered = df_vista_brand[df_vista_brand['Proveedor'].isin(selected_providers)]
    
    # Guardar estado para las otras páginas
    st.session_state['df_filtered_global'] = df_filtered.copy()
    st.session_state['selected_almacen_global'] = "Varias Tiendas" if len(selected_stores) > 1 else selected_stores[0]
    # --- FIN: NUEVOS FILTROS GLOBALES MEJORADOS ---
    
    # --- INICIO: NUEVOS KPIs DINÁMICOS EN SIDEBAR ---
    st.sidebar.markdown("---")
    st.sidebar.header("📊 Resumen del Filtro")
    if not df_filtered.empty:
        valor_filtrado = df_filtered['Valor_Inventario'].sum()
        quiebres_filtrado = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        excedente_filtrado = df_filtered[df_filtered['Estado_Inventario'] == 'Excedente']['Valor_Inventario'].sum()
        st.sidebar.metric("Valor Inventario Filtrado", f"${valor_filtrado:,.0f}")
        st.sidebar.metric("SKUs en Quiebre", f"{quiebres_filtrado}")
        st.sidebar.metric("Valor en Excedente", f"${excedente_filtrado:,.0f}")
    else:
        st.sidebar.info("No hay datos para los filtros seleccionados.")
    # --- FIN: NUEVOS KPIs DINÁMICOS EN SIDEBAR ---


    # --- Visualización del Dashboard (Usa el df_filtered) ---
    st.markdown(f'<p class="section-header">Métricas Clave: {st.session_state.selected_almacen_global}</p>', unsafe_allow_html=True)
    if not df_filtered.empty:
        valor_total_inv = df_filtered['Valor_Inventario'].sum()
        skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        valor_sobrestock = df_filtered[df_filtered['Estado_Inventario'] == 'Excedente']['Valor_Inventario'].sum()
        valor_baja_rotacion = df_filtered[df_filtered['Estado_Inventario'] == 'Baja Rotación / Obsoleto']['Valor_Inventario'].sum()
    else:
        valor_total_inv, skus_quiebre, valor_sobrestock, valor_baja_rotacion = 0, 0, 0, 0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
    col2.metric(label="📉 Excedente (Sobre-stock)", value=f"${valor_sobrestock:,.0f}", help="Valor de productos que rotan, pero cuyo stock supera los días de inventario objetivo.")
    col3.metric(label="💀 Excedente (Baja Rotación)", value=f"${valor_baja_rotacion:,.0f}", help="Valor de productos sin ventas registradas en los últimos 60 días (stock muerto).")
    col4.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")
    
    st.markdown("---")
    st.markdown('<p class="section-header">Navegación a Módulos de Gestión</p>', unsafe_allow_html=True)
    st.warning("🚨 **ACCIÓN CRÍTICA**")
    st.page_link("pages/5_gestion_quiebres.py", label="Atender Quiebres de Stock", icon="🩹")
    st.markdown("---")
    st.info("✅ **GESTIÓN OPERATIVA**")
    st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Compras y Traslados", icon="🚚")
    st.markdown("---")
    st.info("📊 **ANÁLISIS ESTRATÉGICO**")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")
        st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="📊")
    with col_nav2:
        st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")
        
    st.markdown('<p class="section-header" style="margin-top: 20px;">Diagnóstico de la Tienda</p>', unsafe_allow_html=True)
    with st.container(border=True):
        if not df_filtered.empty:
            valor_excedente_total = valor_sobrestock + valor_baja_rotacion
            porc_excedente = (valor_excedente_total / valor_total_inv) * 100 if valor_total_inv > 0 else 0
            if skus_quiebre > 10:
                st.error(f"🚨 **Alerta de Abastecimiento:** ¡Atención! La selección actual tiene **{skus_quiebre} productos en quiebre de stock**. Usa el módulo 'Atender Quiebres' para actuar.", icon="🚨")
            elif porc_excedente > 30:
                st.warning(f"💸 **Oportunidad de Capital:** En la selección actual, más del **{porc_excedente:.1f}%** del inventario es excedente.", icon="💸")
            else:
                st.success(f"✅ **Inventario Saludable:** La selección actual mantiene un buen balance.", icon="✅")
        else:
            st.info("No hay datos para los filtros seleccionados.")
    
    st.markdown("---")
    st.markdown('<p class="section-header">🔍 Consulta de Inventario por Producto (Solo con Stock)</p>', unsafe_allow_html=True)
    search_term = st.text_input("Buscar producto por SKU, Descripción o cualquier palabra clave:", placeholder="Ej: 'ESTUCO', '102030', 'ACRILICO BLANCO'")
    if search_term:
        df_search_initial = df_analisis_completo[df_analisis_completo['SKU'].astype(str).str.contains(search_term, case=False, na=False) | df_analisis_completo['Descripcion'].astype(str).str.contains(search_term, case=False, na=False)]
        df_search_with_stock = df_search_initial[df_search_initial['Stock'] > 0]
        if df_search_with_stock.empty:
            st.warning("No se encontraron productos en stock que coincidan con la búsqueda.")
        else:
            found_skus = df_search_with_stock['SKU'].unique()
            df_stock_completo = df_analisis_completo[df_analisis_completo['SKU'].isin(found_skus)]
            pivot_stock = df_stock_completo.pivot_table(index=['SKU', 'Descripcion', 'Marca_Nombre'], columns='Almacen_Nombre', values='Stock', fill_value=0)
            st.dataframe(pivot_stock.drop(columns=[col for col in pivot_stock.columns if pivot_stock[col].sum() == 0]), use_container_width=True)

else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error, el archivo en Dropbox o intenta actualizar los datos.")
