import streamlit as st

import pandas as pd

import numpy as np

import dropbox

import io

from datetime import datetime

import time # ✨ NUEVO: Importamos la librería time para una pequeña pausa visual



# --- 0. CONFIGURACIÓN INICIAL ---

st.set_page_config(

    page_title="Resumen Ejecutivo de Inventario",

    page_icon="🚀",

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

    "ferrebox": {"password": "8901", "almacen": "FerreBox"}

}



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

    st.session_state.clear()

    st.rerun()



if not st.session_state.get('logged_in', False):

    login()

    st.stop()



# --- ESTILOS VISUALES Y CSS (Sin cambios) ---

st.markdown("""

<style>

    .section-header { color: #7792E3; font-weight: bold; border-bottom: 2px solid #7792E3; padding-bottom: 5px; margin-bottom: 15px; }

    .stAlert { border-radius: 10px; }

    /* Estilo para que el botón de actualizar sea más prominente */

    div[data-testid="stButton"] > button {

        background-color: #4CAF50;

        color: white;

        font-weight: bold;

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





# --- LÓGICA DE ANÁLISIS DE INVENTARIO ---

@st.cache_data

def analizar_inventario_completo(_df_crudo, _df_proveedores, dias_seguridad=7, dias_objetivo=None):

    if _df_crudo is None or _df_crudo.empty:

        return pd.DataFrame()



    if dias_objetivo is None:

        dias_objetivo = {'A': 30, 'B': 45, 'C': 60}



    df = _df_crudo.copy()



    # 1. Limpieza y Preparación

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

    df_ventas[['Fecha_Venta', 'Unidades']] = df_ventas['Historial_Ventas'].str.split(':', expand=True)

    df_ventas['Fecha_Venta'] = pd.to_datetime(df_ventas['Fecha_Venta'], errors='coerce')

    df_ventas['Unidades'] = pd.to_numeric(df_ventas['Unidades'], errors='coerce')

    df_ventas.dropna(subset=['Fecha_Venta', 'Unidades'], inplace=True)

    df_ventas = df_ventas[(pd.Timestamp.now() - df_ventas['Fecha_Venta']).dt.days <= 60]

    demanda_diaria = df_ventas.groupby('index')['Unidades'].sum() / 60

    df = df.merge(demanda_diaria.rename('Demanda_Diaria_Promedio'), on='index', how='left').fillna({'Demanda_Diaria_Promedio': 0})

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

    sku_summary = df.groupby('SKU').agg(Total_Necesidad_SKU=('Necesidad_Total', 'sum'),Total_Excedente_SKU=('Excedente_Trasladable', 'sum')).reset_index()

    sku_summary['Total_Traslados_Posibles_SKU'] = np.minimum(sku_summary['Total_Necesidad_SKU'], sku_summary['Total_Excedente_SKU'])

    df = df.merge(sku_summary.drop(columns=['Total_Necesidad_SKU']), on='SKU', how='left')

    df['Unidades_Traslado_Sugeridas'] = 0

    mask_necesidad = (df['Necesidad_Total'] > 0) & (df.groupby('SKU')['Necesidad_Total'].transform('sum') > 0)

    df.loc[mask_necesidad, 'Unidades_Traslado_Sugeridas'] = (df['Necesidad_Total'] / df.groupby('SKU')['Necesidad_Total'].transform('sum')) * df['Total_Traslados_Posibles_SKU']

    df['Sugerencia_Compra'] = np.ceil(df['Necesidad_Total'] - df['Unidades_Traslado_Sugeridas'].fillna(0))

    df['Unidades_Traslado_Sugeridas'] = np.ceil(df['Unidades_Traslado_Sugeridas'].fillna(0))



    if _df_proveedores is not None and not _df_proveedores.empty:

        df = pd.merge(df, _df_proveedores, on='SKU', how='left')

        df['Proveedor'] = df['Proveedor'].fillna('No Asignado')

        df['SKU_Proveedor'] = df['SKU_Proveedor'].fillna('N/A')

    else:

        df['Proveedor'] = 'No Asignado'

        df['SKU_Proveedor'] = 'N/A'



    return df.set_index('index')



# --- INICIO DE LA INTERFAZ DE USUARIO ---

st.sidebar.title(f"Usuario: {st.session_state.almacen_nombre}")

st.sidebar.button("Cerrar Sesión", on_click=logout)

st.sidebar.markdown("---")



st.title("🚀 Resumen Ejecutivo de Inventario")

st.markdown(f"###### Panel de control para la toma de decisiones. Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")



# ✨ NUEVO: BOTÓN DE ACTUALIZACIÓN MANUAL

# Este botón limpia la caché de todas las funciones @st.cache_data y reinicia el script.

if st.button("🔄 Actualizar Datos de Inventario", help="Borra la memoria caché y vuelve a cargar los archivos más recientes desde Dropbox."):

    st.cache_data.clear()

    # Mostramos un mensaje temporal al usuario

    toast_message = st.toast('Borrando caché y recargando datos...', icon='⏳')

    time.sleep(2) # Pausa de 2 segundos para que el usuario vea el mensaje

    toast_message.toast('¡Datos actualizados! Recargando panel...', icon='✅')

    time.sleep(1)

    st.rerun() # Vuelve a ejecutar el script desde el principio



st.markdown("---") # ✨ NUEVO: Separador visual



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



    # --- EL RESTO DE LA PÁGINA ES IDÉNTICO Y NO REQUIERE CAMBIOS ---

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

    else:

        valor_total_inv, skus_quiebre, valor_sobrestock, valor_baja_rotacion = 0, 0, 0, 0

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")

    col2.metric(label="📉 Excedente (Sobre-stock)", value=f"${valor_sobrestock:,.0f}", help="Valor de productos que rotan, pero cuyo stock supera los días de inventario objetivo.")

    col3.metric(label="💀 Excedente (Baja Rotación)", value=f"${valor_baja_rotacion:,.0f}", help="Valor de productos sin ventas registradas en los últimos 60 días (stock muerto).")

    col4.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")

    st.markdown("---")

    st.markdown('<p class="section-header">Navegación a Módulos de Análisis</p>', unsafe_allow_html=True)

    st.error("🚨 **ACCIÓN CRÍTICA**")

    st.page_link("pages/5_gestion_quiebres.py", label="Atender Quiebres de Stock", icon="🩹")

    st.markdown("---")

    col_nav1, col_nav2 = st.columns(2)

    with col_nav1:

        st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Abastecimiento", icon="🚚")

        st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")

    with col_nav2:

        st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="📊")

        st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")

    st.markdown('<p class="section-header" style="margin-top: 20px;">Diagnóstico de la Tienda</p>', unsafe_allow_html=True)

    with st.container(border=True):

        if not df_filtered.empty:

            valor_excedente_total = valor_sobrestock + valor_baja_rotacion

            porc_excedente = (valor_excedente_total / valor_total_inv) * 100 if valor_total_inv > 0 else 0

            if skus_quiebre > 10: 

                st.error(f"🚨 **Alerta de Abastecimiento:** ¡Atención! La tienda **{selected_almacen_nombre}** tiene **{skus_quiebre} productos en quiebre de stock**. Usa el módulo 'Atender Quiebres' para actuar.", icon="🚨")

            elif porc_excedente > 30: 

                st.warning(f"💸 **Oportunidad de Capital:** En **{selected_almacen_nombre}**, más del **{porc_excedente:.1f}%** del inventario es excedente. El problema principal está en: {'Baja Rotación' if valor_baja_rotacion > valor_sobrestock else 'Sobre-stock'}.", icon="💸")

            else: 

                st.success(f"✅ **Inventario Saludable:** La tienda **{selected_almacen_nombre}** mantiene un buen balance.", icon="✅")

        elif st.session_state.get('user_role') == 'gerente' and selected_almacen_nombre == "-- Consolidado (Todas las Tiendas) --":

             st.info("Selecciona una tienda específica en el filtro para ver su diagnóstico detallado.")

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
