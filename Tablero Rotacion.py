import streamlit as st
import pandas as pd
import numpy as np
import dropbox
import io
from datetime import datetime

# --- 0. CONFIGURACIÓN INICIAL ---
st.set_page_config(
    page_title="Resumen Ejecutivo de Inventario",
    page_icon="🚀",
    layout="wide",
)

# --- ✅ 1. LÓGICA DE USUARIOS Y AUTENTICACIÓN ---
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

# Inicializar session_state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.almacen_nombre = None

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
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.almacen_nombre = None
    st.rerun()

# --- GATEKEEPER PRINCIPAL ---
if not st.session_state.get('logged_in', False):
    login()
    st.stop()

# --- ESTILOS VISUALES Y CSS PERSONALIZADO (Sin cambios) ---
st.markdown("""
<style>
    .section-header {
        color: #7792E3;
        font-weight: bold;
        border-bottom: 2px solid #7792E3;
        padding-bottom: 5px;
        margin-bottom: 15px;
    }
    .stAlert {
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE CARGA DE DATOS (Sin cambios) ---
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
        info_message.success("Datos cargados exitosamente desde Dropbox!", icon="✅")
        return df_crudo
    except Exception as e:
        info_message.error(f"Ocurrió un error al cargar los datos: {e}", icon="🔥")
        return None

# --- LÓGICA DE ANÁLISIS DE INVENTARIO (Con el renombre de 'Opalo') ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', dias_seguridad=7, dias_objetivo=None):
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
    df.rename(columns=lambda c: column_mapping.get(c.strip().upper(), c.strip().upper()), inplace=True)
    
    # ✅ Se incluye el mapeo de 'Opalo'
    almacen_map = {'158':'Opalo', '155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].astype(str).map(almacen_map).fillna(df['Almacen'])
    
    marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
    df['Marca_Nombre'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str).map(marca_map).fillna('Complementarios')
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True)

    # El resto de la función de análisis permanece intacta...
    # ... (Cálculo de Demanda, ABC, Estado, Sugerencias, etc.)
    # ...
    # (Se omite por brevedad, pero es el mismo código que ya funcionaba)
    return df.set_index('index')

# --- INICIO DE LA INTERFAZ DE USUARIO (SOLO PARA USUARIOS LOGUEADOS) ---

st.sidebar.title(f"Usuario: {st.session_state.almacen_nombre}")
st.sidebar.button("Cerrar Sesión", on_click=logout)
st.sidebar.markdown("---")

st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
with st.expander("ℹ️ ¿Cómo interpretar la Clasificación ABC y los Días de Inventario?"):
    st.markdown("""
    ... (Tu texto de ayuda sin cambios) ...
    """)

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Parámetros del Análisis")
    dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad (Min):", 1, 30, 7)
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Días de Inventario Objetivo (Max)**")
    dias_obj_a = st.sidebar.slider("Clase A (VIPs)", 15, 45, 30)
    dias_obj_b = st.sidebar.slider("Clase B (Importantes)", 30, 60, 45)
    dias_obj_c = st.sidebar.slider("Clase C (Generales)", 45, 90, 60)

    with st.spinner("Procesando datos... Por favor espera, esto debería ser rápido."):
        dias_objetivo_dict = {'A': dias_obj_a, 'B': dias_obj_b, 'C': dias_obj_c}
        df_analisis_completo = analizar_inventario_completo(df_crudo, dias_seguridad=dias_seguridad_input, dias_objetivo=dias_objetivo_dict).reset_index()
    
    # --- ✅ FILTRADO GLOBAL DE DATOS SEGÚN EL ROL ---
    if st.session_state.user_role == 'tienda':
        df_analisis_completo = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == st.session_state.almacen_nombre]
    
    st.session_state['df_analisis'] = df_analisis_completo

    if not df_analisis_completo.empty:
        st.sidebar.header("Filtros de Vista")
        
        # --- ✅ VISTA CONDICIONAL DEL FILTRO DE TIENDA ---
        if st.session_state.user_role == 'gerente':
            opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
            nombres_almacen = sorted([str(nombre) for nombre in df_analisis_completo['Almacen_Nombre'].unique() if pd.notna(nombre)])
            lista_seleccion_nombres = [opcion_consolidado] + nombres_almacen
            selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres)
        else:
            selected_almacen_nombre = st.session_state.almacen_nombre
            st.sidebar.markdown(f"**Vista actual:** `{selected_almacen_nombre}`")
            opcion_consolidado = "" # Para que la lógica de abajo funcione

        if selected_almacen_nombre == opcion_consolidado:
            df_vista = df_analisis_completo
        else:
            df_vista = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == selected_almacen_nombre]

        lista_marcas_unicas = sorted([str(m) for m in df_vista['Marca_Nombre'].unique() if pd.notna(m)])
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas_unicas, default=lista_marcas_unicas)
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()

        st.markdown(f'<p class="section-header">Métricas Clave: {selected_almacen_nombre}</p>', unsafe_allow_html=True)
        if not df_filtered.empty:
            valor_total_inv = df_filtered['Valor_Inventario'].sum()
            df_excedente_kpi = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]
            valor_excedente = df_excedente_kpi['Valor_Inventario'].sum()
            skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        else:
            valor_total_inv, valor_excedente, skus_quiebre = 0, 0, 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
        col2.metric(label="📉 Valor en Excedente", value=f"${valor_excedente:,.0f}")
        col3.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")

        st.markdown("---")
        st.markdown('<p class="section-header">Navegación a Módulos de Análisis</p>', unsafe_allow_html=True)
        
        col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)
        with col_nav1:
            st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Abastecimiento", icon="🚚")
        with col_nav2:
            st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")
        with col_nav3:
            st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="📊")
            st.caption("Descubre tus marcas estrella.")
        with col_nav4:
            st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")
            st.caption("Anticípate al mercado.")

        # --- SECCIÓN: Diagnóstico de la Tienda (Sin cambios) ---
        st.markdown('<p class="section-header">Diagnóstico de la Tienda</p>', unsafe_allow_html=True)
        with st.container(border=True):
            if selected_almacen_nombre != opcion_consolidado and not df_filtered.empty:
                porc_excedente = (valor_excedente / valor_total_inv) * 100 if valor_total_inv > 0 else 0
                if skus_quiebre > 10:
                    st.error(f"🚨 **Alerta de Abastecimiento:** ¡Atención! La tienda **{selected_almacen_nombre}** tiene **{skus_quiebre} productos en quiebre de stock**. Es urgente revisar el plan de abastecimiento.", icon="🚨")
                elif porc_excedente > 30:
                    st.warning(f"💸 **Oportunidad de Capital:** En **{selected_almacen_nombre}**, más del **{porc_excedente:.1f}%** del inventario es excedente. ¡Libera capital y optimiza!", icon="💸")
                else:
                    st.success(f"✅ **Inventario Saludable:** La tienda **{selected_almacen_nombre}** mantiene un buen balance.", icon="✅")
            else:
                st.info("Selecciona una tienda específica en el filtro de la izquierda para ver su diagnóstico detallado.")

        # --- SECCIÓN: Buscador de Inventario Global (Sin cambios) ---
        st.markdown("---")
        st.markdown('<p class="section-header">🔍 Consulta de Inventario por Producto (Solo con Stock)</p>', unsafe_allow_html=True)
        
        search_term = st.text_input(
            "Buscar producto por SKU, Descripción o cualquier palabra clave:",
            placeholder="Ej: 'ESTUCO', '102030', 'ACRILICO BLANCO'"
        )

        if search_term:
            df_search_initial = df_analisis_completo[
                df_analisis_completo['SKU'].astype(str).str.contains(search_term, case=False, na=False) |
                df_analisis_completo['Descripcion'].astype(str).str.contains(search_term, case=False, na=False)
            ]
            df_search_with_stock = df_search_initial[df_search_initial['Stock'] > 0]
            if df_search_with_stock.empty:
                st.warning("No se encontraron productos en stock que coincidan con la búsqueda.")
            else:
                found_skus = df_search_with_stock['SKU'].unique()
                df_stock_completo = df_analisis_completo[df_analisis_completo['SKU'].isin(found_skus)]
                pivot_stock = df_stock_completo.pivot_table(index=['SKU', 'Descripcion', 'Marca_Nombre'], columns='Almacen_Nombre', values='Stock', fill_value=0).reset_index()
                store_cols = pivot_stock.columns[3:]
                cols_to_drop = [col for col in store_cols if pivot_stock[col].sum() == 0]
                pivot_stock_filtered = pivot_stock.drop(columns=cols_to_drop)
                st.dataframe(pivot_stock_filtered, use_container_width=True, hide_index=True)
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
