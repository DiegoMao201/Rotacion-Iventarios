import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import dropbox
import io
from datetime import datetime, timedelta
import warnings

# --- 0. CONFIGURACIÓN INICIAL Y ADVERTENCIAS ---
# CORRECCIÓN: La advertencia es estándar, no de numpy.
warnings.filterwarnings("ignore", category=VisibleDeprecationWarning) 
st.set_page_config(
    page_title="Resumen Ejecutivo de Inventario",
    page_icon="🚀",
    layout="wide",
)

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
</style>
""", unsafe_allow_html=True)

# --- 1. LÓGICA DE CARGA DE DATOS ---
@st.cache_data(ttl=600)
def cargar_datos_desde_dropbox():
    """Carga el archivo de datos crudos desde Dropbox."""
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

# --- 2. LÓGICA DE ANÁLISIS DE INVENTARIO (VERSIÓN FINAL OPTIMIZADA) ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', dias_seguridad=5, dias_objetivo=30):
    """
    Función de análisis final, con el motor de cálculo de demanda reescrito para máxima velocidad.
    """
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()

    df = _df_crudo.copy()
    
    # --- 1. Limpieza y Preparación de Datos ---
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas',
        'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
    }
    df.rename(columns=lambda c: column_mapping.get(c.strip().upper(), c.strip().upper()), inplace=True)
    
    almacen_map = {'155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].astype(str).map(almacen_map).fillna(df['Almacen'])
    
    marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
    df['Marca_Nombre'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str).map(marca_map).fillna('Complementarios')
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Stock'] = np.maximum(0, df['Stock'])

    # --- 2. Cálculo de Demanda (Motor Optimizado) ---
    fecha_hoy_dt = pd.Timestamp(datetime.now())

    def calcular_demanda_rapido(historial_str):
        if not isinstance(historial_str, str) or ':' not in historial_str:
            return 0.0
        try:
            parts = [item.split(':') for item in historial_str.split(',')]
            fechas_str = [p[0] for p in parts if len(p) == 2]
            unidades_str = [p[1] for p in parts if len(p) == 2]
            
            if not fechas_str: return 0.0

            fechas = pd.to_datetime(fechas_str, errors='coerce').to_numpy()
            unidades = pd.to_numeric(unidades_str, errors='coerce').to_numpy()
            
            valid_mask = ~pd.isnull(fechas) & ~pd.isnull(unidades)
            if not np.any(valid_mask): return 0.0

            fechas, unidades = fechas[valid_mask], unidades[valid_mask].astype(float)
            
            dias_atras = (fecha_hoy_dt - fechas).astype('timedelta64[D]').astype(int)
            pesos = np.maximum(0, 60 - dias_atras)
            
            sum_pesos = np.sum(pesos)
            return np.sum(unidades * pesos) / sum_pesos if sum_pesos > 0 else 0.0
        except:
            return 0.0

    df['Demanda_Diaria_Promedio'] = df['Historial_Ventas'].apply(calcular_demanda_rapido)

    # --- 3. Cálculos de Inventario y ABC (Vectorizados) ---
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

    # --- 4. Estado de Inventario (Vectorizado) ---
    conditions = [
        (df['Stock'] <= 0) & (df['Demanda_Diaria_Promedio'] > 0),
        (df['Stock'] > 0) & (df['Stock'] < df['Punto_Reorden']),
        (df['Demanda_Diaria_Promedio'] > 0) & (df['Stock'] / df['Demanda_Diaria_Promedio'].replace(0, np.nan) > 90),
        (df['Stock'] > 0) & (df['Demanda_Diaria_Promedio'] <= 0)
    ]
    choices_estado = ['Quiebre de Stock', 'Bajo Stock (Riesgo)', 'Excedente', 'Baja Rotación / Obsoleto']
    choices_accion = ['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO', 'LIQUIDAR / PROMOCIONAR', 'LIQUIDAR / DESCONTINUAR']
    df['Estado_Inventario'] = np.select(conditions, choices_estado, default='Normal')
    df['Accion_Requerida'] = np.select(conditions, choices_accion, default='MONITOREAR')

    # --- 5. Lógica de Sugerencias (Vectorizada) ---
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * dias_objetivo
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    
    df['Sugerencia_Compra'] = 0
    necesidad_mask = df['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO'])
    df.loc[necesidad_mask, 'Sugerencia_Compra'] = np.ceil(df.loc[necesidad_mask, 'Necesidad_Total'])

    df['Excedente_Trasladable'] = np.maximum(0, df['Stock'] - df['Punto_Reorden'])
    excedentes_por_sku = df.groupby('SKU')['Excedente_Trasladable'].sum().rename('Total_Excedente_SKU')

    df = df.merge(excedentes_por_sku, on='SKU', how='left').fillna({'Total_Excedente_SKU': 0})

    df['Traslado_Posible'] = np.minimum(df['Sugerencia_Compra'], df['Total_Excedente_SKU'])
    df['Unidades_Traslado_Sugeridas'] = np.ceil(df['Traslado_Posible'])
    df['Sugerencia_Compra'] -= df['Unidades_Traslado_Sugeridas']
    
    df.loc[df['Unidades_Traslado_Sugeridas'] > 0, 'Accion_Requerida'] = 'COMPRA Y/O TRASLADO'
    
    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']
    
    return df

# --- INTERFAZ DE USUARIO ---
st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

with st.expander("ℹ️ ¿Cómo interpretar la Clasificación ABC y los Días de Inventario?"):
    st.markdown("""
    La **Clasificación ABC** es un método para organizar los productos de tu inventario en tres categorías, basadas en su importancia para las ventas. Esto te ayuda a enfocar tus esfuerzos y capital en lo que más importa.

    - **👑 Productos Clase A:** Son tus productos **VIP**. Son pocos (generalmente el 20% de tus artículos) pero representan la mayor parte de tus ingresos (aprox. el 80%).
    - **👍 Productos Clase B:** Son importantes, pero no tan críticos como los A.
    - **📦 Productos Clase C:** Es la gran mayoría de tus productos, pero individualmente aportan muy poco a las ventas.

    Los **"Días de Inventario Objetivo"** que configuras en la barra lateral le dicen al sistema cuál es el **nivel máximo de stock** que deseas tener para cada clase de producto, medido en días de venta.
    """)

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Parámetros del Análisis")
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    
    # --- PARÁMETROS SIMPLIFICADOS ---
    dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad:", min_value=1, max_value=30, value=5, step=1,
                                             help="Define el colchón de seguridad mínimo para todos los productos.")
    
    dias_objetivo_input = st.sidebar.slider("Días de Inventario Objetivo:", min_value=15, max_value=90, value=30, step=5,
                                             help="Define el nivel máximo de stock (en días de venta) al que se debe reabastecer.")

    with st.spinner("Procesando datos... Por favor espera, esto debería ser rápido."):
        df_analisis_completo = analizar_inventario_completo(df_crudo, 
                                                            almacen_principal=almacen_principal_input, 
                                                            dias_seguridad=dias_seguridad_input,
                                                            dias_objetivo=dias_objetivo_input)
    
    st.session_state['df_analisis'] = df_analisis_completo

    if not df_analisis_completo.empty:
        st.sidebar.header("Filtros de Vista")
        opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
        nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
        map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
        lista_seleccion_nombres = [opcion_consolidado] + sorted(nombres_almacen['Almacen_Nombre'].unique())
        selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres)
        
        if selected_almacen_nombre == opcion_consolidado:
            df_vista = df_analisis_completo
        else:
            codigo_almacen_seleccionado = map_nombre_a_codigo[selected_almacen_nombre]
            df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]

        lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas)
        
        if not selected_marcas: df_filtered = pd.DataFrame(columns=df_vista.columns)
        else: df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]

        st.markdown(f'<p class="section-header">Métricas Clave: {selected_almacen_nombre}</p>', unsafe_allow_html=True)
        if not df_filtered.empty:
            valor_total_inv = df_filtered['Valor_Inventario'].sum()
            df_excedente_kpi = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]
            valor_excedente = df_excedente_kpi['Valor_Inventario'].sum()
            skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
            total_ventas_unidades = df_filtered['Ventas_60_Dias'].sum()
            total_stock_unidades = df_filtered['Stock'].sum()
            rotacion_general = total_ventas_unidades / total_stock_unidades if total_stock_unidades > 0 else 0
        else:
            valor_total_inv, valor_excedente, skus_quiebre, rotacion_general = 0, 0, 0, 0
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
        col2.metric(label="📉 Valor en Excedente", value=f"${valor_excedente:,.0f}")
        col3.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")
        col4.metric(label="🔄 Rotación General (60 Días)", value=f"{rotacion_general:.2f}")

        st.markdown("---")
        
        # El resto de la UI se mantiene igual
        st.markdown('<p class="section-header">💡 Consejos Automáticos</p>', unsafe_allow_html=True)
        with st.container(border=True):
            if not df_filtered.empty:
                productos_tendencia_fuerte = df_filtered[df_filtered['Demanda_Diaria_Promedio'] > 0.5] # Asumiendo tendencia por demanda
                if not productos_tendencia_fuerte.empty:
                    st.info(f"**Oportunidad de Crecimiento:** Productos como **{productos_tendencia_fuerte.iloc[0]['SKU']}** están acelerando sus ventas. Asegúrate de tener suficiente stock de seguridad para ellos.")
                if skus_quiebre > 5:
                    st.warning(f"**Prioridad Alta:** Tienes **{skus_quiebre} SKUs en quiebre de stock**. Visita 'Gestión de Abastecimiento' para evitar pérdidas de venta.")
                if valor_total_inv > 0 and (valor_excedente / valor_total_inv > 0.25):
                    st.error(f"**Alerta de Capital:** Más del 25% de tu inventario es excedente. Visita 'Análisis de Excedentes' para crear un plan de liquidación.")

        st.markdown("---")
        st.markdown('<p class="section-header">Navegación a Módulos de Análisis</p>', unsafe_allow_html=True)
        col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)
        with col_nav1:
            st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Abastecimiento", icon="🚚")
        with col_nav2:
            st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")
        with col_nav3:
            st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="�")
        with col_nav4:
            st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
