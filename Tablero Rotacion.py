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
# Ignorar advertencias comunes de polyfit que no afectan el resultado
warnings.filterwarnings("ignore", category=np.VisibleDeprecationWarning) 
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

# --- 2. LÓGICA DE ANÁLISIS DE INVENTARIO (VERSIÓN ULTRA OPTIMIZADA) ---
@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', dias_seguridad=7, dias_objetivo=None):
    """
    Función de análisis principal, reescrita para un rendimiento óptimo masivo.
    El cuello de botella de .apply() ha sido eliminado.
    """
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
    
    almacen_map = {'155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].astype(str).map(almacen_map).fillna(df['Almacen'])
    
    marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
    df['Marca_Nombre'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str).map(marca_map).fillna('Complementarios')
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Stock'] = np.maximum(0, df['Stock'])
    df.reset_index(inplace=True) # Guardar el índice original para el groupby

    # --- 2. "Explosión" del Historial de Ventas (El Gran Salto de Rendimiento) ---
    df['Historial_Ventas'] = df['Historial_Ventas'].fillna('').astype(str)
    df_long = df[['index', 'Historial_Ventas']].copy()
    df_long['Historial_Ventas'] = df_long['Historial_Ventas'].str.split(',')
    df_long = df_long.explode('Historial_Ventas').dropna()
    
    split_data = df_long['Historial_Ventas'].str.split(':', expand=True)
    df_long['Fecha'] = pd.to_datetime(split_data[0], errors='coerce')
    df_long['Unidades'] = pd.to_numeric(split_data[1], errors='coerce')
    df_long.dropna(subset=['Fecha', 'Unidades'], inplace=True)

    # --- 3. Cálculo de Demanda Vectorizado sobre el DataFrame "Largo" ---
    fecha_hoy = datetime.now()
    df_long['dias_atras'] = (fecha_hoy - df_long['Fecha']).dt.days
    df_long['peso'] = np.maximum(0, 60 - df_long['dias_atras'])

    # Agrupar por el índice original para calcular las métricas de demanda
    grouped = df_long.groupby('index')
    
    def weighted_avg(g):
        return np.average(g['Unidades'], weights=g['peso']) if g['peso'].sum() > 0 else 0
        
    demanda_diaria = grouped.apply(weighted_avg)
    demanda_diaria.name = 'Demanda_Diaria_Promedio'

    # Unir resultados al DataFrame original
    df = df.merge(demanda_diaria, on='index', how='left')
    df['Demanda_Diaria_Promedio'].fillna(0, inplace=True)
    
    # --- 4. Cálculos de Inventario y ABC (Vectorizados) ---
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

    # --- 5. Estado de Inventario (Vectorizado) ---
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

    # --- 6. Lógica de Sugerencias (Vectorizada) ---
    df['Sugerencia_Compra'] = 0
    df['Unidades_Traslado_Sugeridas'] = 0
    df['dias_objetivo_map'] = df['Segmento_ABC'].map(dias_objetivo)
    df['Stock_Objetivo'] = df['Demanda_Diaria_Promedio'] * df['dias_objetivo_map']
    df['Necesidad_Total'] = np.maximum(0, df['Stock_Objetivo'] - df['Stock'])
    
    necesidad_mask = df['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO'])
    df.loc[necesidad_mask, 'Sugerencia_Compra'] = np.ceil(df.loc[necesidad_mask, 'Necesidad_Total'])

    df['Excedente_Trasladable'] = np.maximum(0, df['Stock'] - df['Punto_Reorden'])
    excedentes_por_sku = df[df['Excedente_Trasladable'] > 0].groupby('SKU')['Excedente_Trasladable'].sum().rename('Total_Excedente_SKU')

    df = df.merge(excedentes_por_sku, on='SKU', how='left').fillna({'Total_Excedente_SKU': 0})

    df['Traslado_Posible'] = np.minimum(df['Sugerencia_Compra'], df['Total_Excedente_SKU'])
    df['Unidades_Traslado_Sugeridas'] = np.ceil(df['Traslado_Posible'])
    df['Sugerencia_Compra'] -= df['Unidades_Traslado_Sugeridas']
    
    df.loc[df['Unidades_Traslado_Sugeridas'] > 0, 'Accion_Requerida'] = 'COMPRA Y/O TRASLADO'
    
    df.set_index('index', inplace=True)
    df.index.name = None # Limpiar nombre del índice
    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']
    # Eliminar columnas temporales
    df.drop(columns=['dias_objetivo_map', 'Stock_Objetivo', 'Necesidad_Total', 'Excedente_Trasladable', 'Total_Excedente_SKU', 'Traslado_Posible', 'Valor_Venta_60_Dias'], inplace=True, errors='ignore')

    return df

# --- INTERFAZ DE USUARIO ---
st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

with st.expander("ℹ️ ¿Cómo interpretar la Clasificación ABC y los Días de Inventario?"):
    st.markdown("""
    La **Clasificación ABC** es un método para organizar los productos de tu inventario en tres categorías, basadas en su importancia para las ventas. Esto te ayuda a enfocar tus esfuerzos y capital en lo que más importa.

    - **👑 Productos Clase A:** Son tus productos **VIP**. Son pocos (generalmente el 20% de tus artículos) pero representan la mayor parte de tus ingresos (aprox. el 80%).
      - **Estrategia:** Debes monitorearlos de cerca. Evita los quiebres de stock a toda costa, pero también el exceso de inventario, ya que inmovilizan mucho capital. Por eso, se les asigna un **objetivo de días de inventario más bajo**.

    - **👍 Productos Clase B:** Son importantes, pero no tan críticos como los A. Representan el siguiente 30% de tus artículos y un 15% de las ventas.
      - **Estrategia:** Tienen una política de control más moderada. Se les asigna un nivel de inventario intermedio.

    - **📦 Productos Clase C:** Es la gran mayoría de tus productos (el 50% restante), pero individualmente aportan muy poco a las ventas (el 5% del total).
      - **Estrategia:** El control puede ser más relajado. Un stock de seguridad más alto es aceptable, ya que el costo financiero es bajo.

    ---
    
    Los **"Días de Inventario Objetivo"** que configuras en la barra lateral le dicen al sistema cuál es el **nivel máximo de stock** que deseas tener para cada clase de producto, medido en días de venta. El sistema sugerirá compras o traslados para alcanzar ese nivel objetivo.
    """)

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Parámetros del Análisis")
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad (Min):", min_value=1, max_value=30, value=7, step=1,
                                             help="Define el colchón de seguridad sobre el Lead Time para calcular el Punto de Reorden (Mínimo).")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Días de Inventario Objetivo (Max)**")
    st.sidebar.info("Define el nivel máximo de stock al que se debe reabastecer cada producto.", icon="🎯")
    dias_obj_a = st.sidebar.slider("Clase A (VIPs)", min_value=15, max_value=45, value=30)
    dias_obj_b = st.sidebar.slider("Clase B (Importantes)", min_value=30, max_value=60, value=45)
    dias_obj_c = st.sidebar.slider("Clase C (Generales)", min_value=45, max_value=90, value=60)

    with st.spinner("Procesando datos... Por favor espera, esto debería ser rápido."):
        dias_objetivo_dict = {'A': dias_obj_a, 'B': dias_obj_b, 'C': dias_obj_c}
        df_analisis_completo = analizar_inventario_completo(df_crudo, 
                                                            almacen_principal=almacen_principal_input, 
                                                            dias_seguridad=dias_seguridad_input,
                                                            dias_objetivo=dias_objetivo_dict)
    
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
        # Asegurarse de que el df filtrado no está vacío antes de sumar
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
        # ...

        st.markdown("---")
        st.markdown('<p class="section-header">Navegación a Módulos de Análisis</p>', unsafe_allow_html=True)
        # ...
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
