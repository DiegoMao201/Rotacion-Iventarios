# Tablero_Principal.py

import streamlit as st
import pandas as pd
import numpy as np
import dropbox
import io
import time
from datetime import datetime
from utils import (
    analizar_inventario_completo,
    validate_dataframe,
    EXPECTED_INVENTORY_COLS,
    EXPECTED_PROVIDERS_COLS
)

st.set_page_config(
    page_title="Resumen Ejecutivo de Inventario",
    page_icon="🚀",
    layout="wide",
)

def init_session_state():
    defaults = {
        'logged_in': False, 'user_role': None, 'almacen_nombre': None,
        'df_analisis_maestro': pd.DataFrame(), 'df_filtered_global': pd.DataFrame(),
        'selected_almacen_global': 'Todas'
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

USUARIOS = st.secrets.get("usuarios", {
    "gerente": {"password": "1234", "almacen": "Todas"}, "opalo": {"password": "2345", "almacen": "Opalo"},
    "armenia": {"password": "3456", "almacen": "Armenia"}, "cedi": {"password": "4567", "almacen": "Cedi"},
    "manizales": {"password": "5678", "almacen": "Manizales"}, "olaya": {"password": "6789", "almacen": "Olaya"},
    "laureles": {"password": "7890", "almacen": "Laureles"}, "ferrebox": {"password": "8901", "almacen": "FerreBox"}
})

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
    init_session_state()
    st.rerun()

if not st.session_state.logged_in:
    login()
    st.stop()

st.markdown("""
<style>
    .section-header { color: #4F8BF9; font-weight: bold; border-bottom: 2px solid #4F8BF9; padding-bottom: 5px; margin-bottom: 15px; }
    .stAlert { border-radius: 10px; }
    div[data-testid="stButton"] > button { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=600)
def cargar_datos_desde_dropbox():
    info_message = st.empty()
    info_message.info("Conectando a Dropbox por el archivo de inventario...", icon="☁️")
    try:
        dbx_creds = st.secrets["dropbox"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            _, res = dbx.files_download(path=dbx_creds["file_path"])
            with io.BytesIO(res.content) as stream:
                df_crudo = pd.read_csv(stream, encoding='latin1', sep='|', header=None, names=EXPECTED_INVENTORY_COLS)
        if not validate_dataframe(df_crudo, EXPECTED_INVENTORY_COLS, "inventario de Dropbox"):
            return pd.DataFrame()
        info_message.success("Datos de inventario cargados y validados!", icon="✅")
        return df_crudo
    except dropbox.exceptions.ApiError as e:
        info_message.error(f"Error de API de Dropbox: No se encontró el archivo. ({e})", icon="🔥")
        return pd.DataFrame()
    except Exception as e:
        info_message.error(f"Error inesperado al cargar inventario: {e}", icon="🔥")
        return pd.DataFrame()

@st.cache_data(ttl=600)
def cargar_proveedores_desde_dropbox():
    info_message = st.empty()
    info_message.info("Cargando archivo de proveedores...", icon="🤝")
    try:
        dbx_creds = st.secrets["dropbox"]
        proveedores_path = dbx_creds["proveedores_file_path"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            _, res = dbx.files_download(path=proveedores_path)
            with io.BytesIO(res.content) as stream:
                df = pd.read_excel(stream, dtype={'REFERENCIA': str, 'COD PROVEEDOR': str})
        if not validate_dataframe(df, EXPECTED_PROVIDERS_COLS, "proveedores de Dropbox"):
            return pd.DataFrame(columns=['SKU', 'Proveedor', 'SKU_Proveedor'])
        df.rename(columns={'REFERENCIA': 'SKU', 'PROVEEDOR': 'Proveedor', 'COD PROVEEDOR': 'SKU_Proveedor'}, inplace=True)
        df.dropna(subset=['SKU_Proveedor'], inplace=True)
        info_message.success("Archivo de proveedores cargado!", icon="👍")
        return df[['SKU', 'Proveedor', 'SKU_Proveedor']]
    except dropbox.exceptions.ApiError:
        info_message.warning("Archivo de proveedores no encontrado. La info de proveedores no estará disponible.", icon="⚠️")
        return pd.DataFrame(columns=['SKU', 'Proveedor', 'SKU_Proveedor'])
    except Exception as e:
        info_message.error(f"Error inesperado al cargar proveedores: {e}", icon="🔥")
        return pd.DataFrame(columns=['SKU', 'Proveedor', 'SKU_Proveedor'])

st.sidebar.title(f"Usuario: {st.session_state.almacen_nombre}")
st.sidebar.button("Cerrar Sesión", on_click=logout, use_container_width=True)
st.sidebar.markdown("---")
st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel para la toma de decisiones. Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
if st.button("🔄 Actualizar Datos", help="Vuelve a cargar los archivos desde Dropbox.", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")
df_crudo = cargar_datos_desde_dropbox()
df_proveedores = cargar_proveedores_desde_dropbox()
if df_crudo.empty:
    st.error("La carga de datos de inventario falló. Revisa el archivo en Dropbox.")
    st.stop()

st.sidebar.header("⚙️ Parámetros del Análisis")
dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad (Min):", 1, 30, 7)
st.sidebar.markdown("**Días de Inventario Objetivo (Max)**")
dias_obj_a = st.sidebar.slider("Clase A", 15, 45, 30)
dias_obj_b = st.sidebar.slider("Clase B", 30, 60, 45)
dias_obj_c = st.sidebar.slider("Clase C", 45, 90, 60)

with st.spinner("Analizando inventario..."):
    dias_objetivo_dict = {'A': dias_obj_a, 'B': dias_obj_b, 'C': dias_obj_c}
    df_analisis_completo = analizar_inventario_completo(
        df_crudo, df_proveedores, dias_seguridad=dias_seguridad_input, dias_objetivo=dias_objetivo_dict
    ).reset_index()

st.session_state.df_analisis_maestro = df_analisis_completo.copy()
st.sidebar.markdown("---")
st.sidebar.header("🎯 Filtros Globales de Gestión")

if st.session_state.user_role == 'gerente':
    all_stores = sorted(df_analisis_completo['Almacen_Nombre'].unique().tolist())
    selected_stores = st.sidebar.multiselect("Filtrar por Tienda(s):", all_stores, default=all_stores)
else:
    selected_stores = [st.session_state.almacen_nombre]
    st.sidebar.markdown(f"**Vista de Tienda:** `{selected_stores[0]}`")

df_vista = df_analisis_completo[df_analisis_completo['Almacen_Nombre'].isin(selected_stores)]
df_filtered = df_vista
if not df_vista.empty:
    all_brands = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_brands = st.sidebar.multiselect("Filtrar por Marca(s):", all_brands, default=all_brands)
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_brands)]

if not df_filtered.empty:
    all_providers = sorted(df_filtered['Proveedor'].unique().tolist())
    selected_providers = st.sidebar.multiselect("Filtrar por Proveedor(es):", all_providers, default=all_providers)
    df_filtered = df_filtered[df_filtered['Proveedor'].isin(selected_providers)]

st.session_state.df_filtered_global = df_filtered.copy()
st.session_state.selected_almacen_global = "Varias Tiendas" if len(selected_stores) > 1 else (selected_stores[0] if selected_stores else "Ninguna")

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
    st.sidebar.warning("No hay datos para los filtros.")

st.markdown(f'<p class="section-header">Métricas Clave: {st.session_state.selected_almacen_global}</p>', unsafe_allow_html=True)
if not df_filtered.empty:
    valor_total_inv = df_filtered['Valor_Inventario'].sum()
    skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
    valor_sobrestock = df_filtered[df_filtered['Estado_Inventario'] == 'Excedente']['Valor_Inventario'].sum()
    valor_baja_rotacion = df_filtered[df_filtered['Estado_Inventario'] == 'Baja Rotación / Obsoleto']['Valor_Inventario'].sum()
else:
    valor_total_inv, skus_quiebre, valor_sobrestock, valor_baja_rotacion = 0, 0, 0, 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("💰 Valor Total Inventario", f"${valor_total_inv:,.0f}")
col2.metric("📉 Excedente (Sobre-stock)", f"${valor_sobrestock:,.0f}")
col3.metric("💀 Excedente (Baja Rotación)", f"${valor_baja_rotacion:,.0f}")
col4.metric("📦 SKUs en Quiebre", f"{skus_quiebre}")

st.markdown("---")
st.markdown('<p class="section-header">Navegación a Módulos de Gestión</p>', unsafe_allow_html=True)
st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Compras y Traslados", icon="🚚")
# ... Puedes añadir otros page_links aquí si los tienes

# --- INICIO DE LA SECCIÓN CORREGIDA ---
st.markdown('<p class="section-header" style="margin-top: 20px;">Diagnóstico de la Selección Actual</p>', unsafe_allow_html=True)
with st.container(border=True):
    # Este es el bloque de código que faltaba y causaba el IndentationError
    if not df_filtered.empty:
        valor_excedente_total = valor_sobrestock + valor_baja_rotacion
        porc_excedente = (valor_excedente_total / valor_total_inv) * 100 if valor_total_inv > 0 else 0
        if skus_quiebre > 10:
            st.error(f"🚨 **Alerta de Abastecimiento:** ¡Hay **{skus_quiebre} productos en quiebre de stock!**", icon="🚨")
        elif porc_excedente > 30:
            st.warning(f"💸 **Oportunidad de Capital:** Más del **{porc_excedente:.1f}%** del valor del inventario es excedente.", icon="💸")
        else:
            st.success("✅ **Inventario Saludable:** La selección actual mantiene un buen balance.", icon="✅")
    else:
        st.info("No hay datos disponibles para mostrar un diagnóstico.")
# --- FIN DE LA SECCIÓN CORREGIDA ---

st.markdown("---")
st.markdown('<p class="section-header">🔍 Consulta Inteligente de Stock por Producto</p>', unsafe_allow_html=True)
search_term = st.text_input(
    "Buscar producto con stock por SKU o palabras clave (ej: estuco acrilico galon):",
    placeholder="Buscar solo en productos con inventario..."
)

if search_term:
    df_con_stock = df_analisis_completo[df_analisis_completo['Stock'] > 0].copy()
    df_con_stock['Campo_Busqueda'] = (
        df_con_stock['SKU'].astype(str) + ' ' +
        df_con_stock['Descripcion'].astype(str)
    ).str.lower()
    
    keywords = search_term.lower().split()

    if keywords:
        final_mask = pd.Series(True, index=df_con_stock.index)
        for keyword in keywords:
            final_mask &= df_con_stock['Campo_Busqueda'].str.contains(keyword, na=False)
        
        df_search_results = df_con_stock[final_mask]
    else:
        df_search_results = pd.DataFrame()

    if df_search_results.empty:
        st.warning("No se encontraron productos en stock que coincidan con todas las palabras clave.")
    else:
        found_skus = df_search_results['SKU'].unique()
        df_stock_completo = df_analisis_completo[df_analisis_completo['SKU'].isin(found_skus)]
        
        pivot_stock = df_stock_completo.pivot_table(
            index=['SKU', 'Descripcion', 'Marca_Nombre'],
            columns='Almacen_Nombre',
            values='Stock',
            fill_value=0
        )
        st.dataframe(pivot_stock.loc[:, pivot_stock.sum() > 0], use_container_width=True)
