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

# --- ESTILOS VISUALES Y CSS PERSONALIZADO ---
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
        info_message.success("Datos cargados exitosamente desde Dropbox!", icon="✅")
        return df_crudo
    except Exception as e:
        info_message.error(f"Ocurrió un error al cargar los datos: {e}", icon="🔥")
        return None

# --- ✅ FUNCIÓN DE ANÁLISIS DE INVENTARIO (CÓDIGO COMPLETO) ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', dias_seguridad=7, dias_objetivo=None):
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()

    if dias_objetivo is None:
        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}
        
    df = _df_crudo.copy()
    
    # --- 1. Limpieza y Preparación de Datos ---
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas',
        'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
    }
    df.rename(columns=lambda c: column_mapping.get(c.strip().upper(), c.strip().upper()), inplace=True)
    
    almacen_map = {'158':'Opalo', '155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].astype(str).map(almacen_map).fillna(df['Almacen'])
    
    marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
    df['Marca_Nombre'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str).map(marca_map).fillna('Complementarios')
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True)

    # --- 2. Cálculo de Demanda y Estacionalidad ---
    fecha_hoy_dt = pd.Timestamp(datetime.now())
    df['Historial_Ventas'] = df['Historial_Ventas'].fillna('').astype(str)
    
    df_long = df[['index', 'Historial_Ventas']].copy()
    df_long = df_long[df_long['Historial_Ventas'].str.contains(':')]
    df_long['Historial_Ventas'] = df_long['Historial_Ventas'].str.split(',')
    df_long = df_long.explode('Historial_Ventas').dropna()
    
    split_data = df_long['Historial_Ventas'].str.split(':', expand=True)
    df_long['Fecha'] = pd.to_datetime(split_data[0], errors='coerce')
    df_long['Unidades'] = pd.to_numeric(split_data[1], errors='coerce')
    df_long.dropna(subset=['Fecha', 'Unidades'], inplace=True)
    
    df_long['dias_atras'] = (fecha_hoy_dt - df_long['Fecha']).dt.days
    ventas_recientes = df_long[df_long['dias_atras'] <= 60]
    total_ventas_periodo = ventas_recientes.groupby('index')['Unidades'].sum()
    demanda_diaria = (total_ventas_periodo / 60).rename('Demanda_Diaria_Promedio')
    
    df_long['periodo'] = np.select([(df_long['dias_atras'] <= 30), (df_long['dias_atras'] > 30) & (df_long['dias_atras'] <= 60)], ['ultimos_30', 'previos_30'], default='otro')
    ventas_periodo = pd.crosstab(index=df_long['index'], columns=df_long['periodo'], values=df_long['Unidades'], aggfunc='sum').fillna(0)
    if 'ultimos_30' not in ventas_periodo: ventas_periodo['ultimos_30'] = 0
    if 'previos_30' not in ventas_periodo: ventas_periodo['previos_30'] = 0
    ventas_periodo['Estacionalidad_Reciente'] = ventas_periodo['ultimos_30'] - ventas_periodo['previos_30']
    
    df = df.merge(demanda_diaria, on='index', how='left').fillna({'Demanda_Diaria_Promedio': 0})
    df = df.merge(ventas_periodo[['Estacionalidad_Reciente']], on='index', how='left').fillna({'Estacionalidad_Reciente': 0})

    # --- 3. Cálculos Base de Inventario y ABC ---
    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * df['Lead_Time_Proveedor']) + df['Stock_Seguridad']
    
    df['Valor_Venta_60_Dias'] = df['Ventas_60_Dias'] * df['Costo_Promedio_UND']
    ventas_sku_valor = df.groupby('SKU')['Valor_Venta_60_Dias'].sum()
    total_ventas_valor = ventas_sku_valor.sum()
    if total_ventas_valor > 0:
        sku_to_percent = ventas_sku_valor.sort_values(ascending=False).cumsum() / total_ventas_valor
        df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(lambda p: 'A' if p <= 0.8 else ('B' if p <= 0.95 else 'C')).fillna('C')
    else:
        df['Segmento_ABC'] = 'C'

    # --- 4. Estado de Inventario ---
    df['dias_objetivo_map'] = df['Segmento_ABC'].map(dias_objetivo)
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * df['dias_objetivo_map']
    conditions = [
        (df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),
        (df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']),
        (df['Stock'] > df['Stock_Objetivo']),
        (df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0)
    ]
    choices_estado = ['Quiebre de Stock', 'Bajo Stock (Riesgo)', 'Excedente', 'Baja Rotación / Obsoleto']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    
    # --- 5. LÓGICA DE SUGERENCIAS (PRIORIZA TRASLADOS) ---
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    df['Excedente_Trasladable'] = np.maximum(0, df['Stock'] - df['Stock_Objetivo'])

    sku_summary = df.groupby('SKU').agg(
        Total_Necesidad_SKU=('Necesidad_Total', 'sum'),
        Total_Excedente_SKU=('Excedente_Trasladable', 'sum')
    ).reset_index()
    sku_summary['Total_Traslados_Posibles_SKU'] = np.minimum(sku_summary['Total_Necesidad_SKU'], sku_summary['Total_Excedente_SKU'])
    df = df.merge(sku_summary[['SKU', 'Total_Necesidad_SKU', 'Total_Traslados_Posibles_SKU']], on='SKU', how='left')
    
    df['Unidades_Traslado_Sugeridas'] = 0
    df['Sugerencia_Compra'] = 0
    mask_necesidad = df['Total_Necesidad_SKU'] > 0
    df.loc[mask_necesidad, 'Unidades_Traslado_Sugeridas'] = (df['Necesidad_Total'] / df['Total_Necesidad_SKU']) * df['Total_Traslados_Posibles_SKU']
    df['Sugerencia_Compra'] = df['Necesidad_Total'] - df['Unidades_Traslado_Sugeridas']
    df['Unidades_Traslado_Sugeridas'] = np.ceil(df['Unidades_Traslado_Sugeridas'])
    df['Sugerencia_Compra'] = np.ceil(df['Sugerencia_Compra'])
    
    # --- 6. CÁLCULOS FINALES ---
    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']
    df.drop(columns=['Total_Necesidad_SKU', 'Total_Traslados_Posibles_SKU'], inplace=True, errors='ignore')

    return df.set_index('index')


# --- INICIO DE LA INTERFAZ DE USUARIO (SOLO PARA USUARIOS LOGUEADOS) ---

st.sidebar.title(f"Usuario: {st.session_state.almacen_nombre}")
st.sidebar.button("Cerrar Sesión", on_click=logout)
st.sidebar.markdown("---")

st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
with st.expander("ℹ️ ¿Cómo interpretar la Clasificación ABC y los Días de Inventario?"):
    st.markdown("""
    La **Clasificación ABC** es un método para organizar los productos... (etc)
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
    
    # --- ✅ LÓGICA DE DATOS CORREGIDA ---
# 1. Guardamos una copia maestra con TODOS los datos para la lógica de traslados.
st.session_state['df_analisis_maestro'] = df_analisis_completo.copy()

# 2. Filtramos los datos para la vista normal del usuario.
if st.session_state.user_role == 'tienda':
    df_vista_usuario = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == st.session_state.almacen_nombre]
    st.session_state['df_analisis'] = df_vista_usuario
else:
    # El gerente trabaja con la vista completa por defecto.
    st.session_state['df_analisis'] = df_analisis_completo

    if not df_analisis_completo.empty:
        st.sidebar.header("Filtros de Vista")
        
        # --- VISTA CONDICIONAL DEL FILTRO DE TIENDA ---
        if st.session_state.user_role == 'gerente':
            opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
            nombres_almacen = sorted([str(nombre) for nombre in df_analisis_completo['Almacen_Nombre'].unique() if pd.notna(nombre)])
            lista_seleccion_nombres = [opcion_consolidado] + nombres_almacen
            selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres)
        else:
            selected_almacen_nombre = st.session_state.almacen_nombre
            st.sidebar.markdown(f"**Vista actual:** `{selected_almacen_nombre}`")
            opcion_consolidado = "" 

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

        st.markdown('<p class="section-header">Diagnóstico de la Tienda</p>', unsafe_allow_html=True)
        with st.container(border=True):
            if selected_almacen_nombre != opcion_consolidado and not df_filtered.empty:
                porc_excedente = (valor_excedente / valor_total_inv) * 100 if valor_total_inv > 0 else 0
                if skus_quiebre > 10:
                    st.error(f"🚨 **Alerta de Abastecimiento:** ¡Atención! La tienda **{selected_almacen_nombre}** tiene **{skus_quiebre} productos en quiebre de stock**.", icon="🚨")
                elif porc_excedente > 30:
                    st.warning(f"💸 **Oportunidad de Capital:** En **{selected_almacen_nombre}**, más del **{porc_excedente:.1f}%** del inventario es excedente.", icon="💸")
                else:
                    st.success(f"✅ **Inventario Saludable:** La tienda **{selected_almacen_nombre}** mantiene un buen balance.", icon="✅")
            else:
                st.info("Selecciona una tienda específica en el filtro para ver su diagnóstico detallado.")

      # --- SECCIÓN: Buscador de Inventario Global ---
        st.markdown("---")
        st.markdown('<p class="section-header">🔍 Consulta de Inventario por Producto (Solo con Stock)</p>', unsafe_allow_html=True)
        
        search_term = st.text_input(
            "Buscar producto por SKU, Descripción o cualquier palabra clave:",
            placeholder="Ej: 'ESTUCO', '102030', 'ACRILICO BLANCO'"
        )

        if search_term:
            df_search_initial = df_analisis_completo[
                (df_analisis_completo['SKU'].astype(str).str.contains(search_term, case=False, na=False)) |
                (df_analisis_completo['Descripcion'].astype(str).str.contains(search_term, case=False, na=False))
            ]
            df_search_with_stock = df_search_initial[df_search_initial['Stock'] > 0]
            
            if df_search_with_stock.empty:
                st.warning("No se encontraron productos en stock que coincidan con la búsqueda.")
            else:
                found_skus = df_search_with_stock['SKU'].unique()
                df_stock_completo = df_analisis_completo[df_analisis_completo['SKU'].isin(found_skus)]
                pivot_stock = df_stock_completo.pivot_table(
                    index=['SKU', 'Descripcion', 'Marca_Nombre'],
                    columns='Almacen_Nombre',
                    values='Stock',
                    fill_value=0
                ).reset_index()

                store_cols = pivot_stock.columns[3:]
                cols_to_drop = [col for col in store_cols if pivot_stock[col].sum() == 0]
                pivot_stock_filtered = pivot_stock.drop(columns=cols_to_drop)

                st.dataframe(pivot_stock_filtered, use_container_width=True, hide_index=True)

# ✅ El 'else' está completamente a la izquierda, alineado con el 'if' principal.
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
