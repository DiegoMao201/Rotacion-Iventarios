import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import dropbox
import io
from datetime import datetime, timedelta

# --- 1. CONFIGURACIÓN INICIAL DE LA PÁGINA ---
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


# --- FUNCIONES DE CÁLCULO DE DEMANDA ---
def parse_historial_para_analisis(historial_str):
    """Parsea el string de historial de ventas a un DataFrame."""
    if not isinstance(historial_str, str) or historial_str == '':
        return pd.DataFrame({'Fecha': pd.Series(dtype='datetime64[ns]'), 'Unidades': pd.Series(dtype='float64')})
    
    records = []
    ventas = historial_str.split(',')
    for venta in ventas:
        try:
            fecha_str, cantidad_str = venta.split(':')
            records.append({'Fecha': datetime.strptime(fecha_str, '%Y-%m-%d'), 'Unidades': float(cantidad_str)})
        except (ValueError, IndexError):
            continue
    
    df = pd.DataFrame(records)
    if not df.empty:
        df['Fecha'] = pd.to_datetime(df['Fecha'])
    return df


def calcular_demanda_y_tendencia(historial_str, dias_periodo=60):
    """Calcula la demanda diaria ponderada, tendencia y estacionalidad."""
    df_ventas = parse_historial_para_analisis(historial_str)
    
    if df_ventas.empty or len(df_ventas) < 2:
        return 0, 0, 0

    fecha_hoy = datetime.now()
    df_ventas['dias_atras'] = (fecha_hoy - df_ventas['Fecha']).dt.days
    
    # Demanda ponderada: las ventas más recientes tienen más peso
    df_ventas['peso'] = np.maximum(0, dias_periodo - df_ventas['dias_atras'])
    demanda_ponderada = (df_ventas['Unidades'] * df_ventas['peso']).sum() / df_ventas['peso'].sum() if df_ventas['peso'].sum() > 0 else 0

    # Tendencia lineal de los últimos 30 días
    ventas_30d = df_ventas[df_ventas['dias_atras'] <= 30]
    tendencia = 0
    if len(ventas_30d) > 2:
        x = ventas_30d['dias_atras'].values
        y = ventas_30d['Unidades'].values
        slope, _ = np.polyfit(x, y, 1)
        tendencia = -slope 

    ventas_ultimos_30d = df_ventas[df_ventas['dias_atras'] <= 30]['Unidades'].sum()
    ventas_previos_30d = df_ventas[(df_ventas['dias_atras'] > 30) & (df_ventas['dias_atras'] <= 60)]['Unidades'].sum()
    estacionalidad = ventas_ultimos_30d - ventas_previos_30d
    
    return demanda_ponderada, tendencia, estacionalidad


# --- 2. LÓGICA DE CARGA Y ANÁLISIS ---
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

@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', dias_seguridad=7):
    """
    Realiza el análisis completo del inventario, incluyendo la lógica de sugerencias
    de compra y traslado completamente reestructurada y corregida.
    """
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()
    df = _df_crudo.copy()
    
    # Mapeo y limpieza de columnas
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas',
        'LEAD_TIME_PROVEEDOR': 'Lead_Time_Proveedor'
    }
    df.rename(columns=lambda c: column_mapping.get(c.strip().upper(), c.strip().upper()), inplace=True)
    df['Almacen'] = df['Almacen'].astype(str)
    almacen_map = {'155':'Cedi','156':'Armenia','157':'Manizales','189':'Olaya','238':'Laureles','439':'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].map(almacen_map).fillna(df['Almacen'])
    if 'Marca' in df.columns:
        df['Marca_str'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str)
        marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
        df['Marca_Nombre'] = df['Marca_str'].map(marca_map).fillna('Complementarios')
    else:
        df['Marca_Nombre'] = 'No especificada'
    
    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo', 'Lead_Time_Proveedor']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Stock'] = df['Stock'].apply(lambda x: max(0, x))

    # Cálculos de demanda e inventario
    analisis_ventas = df['Historial_Ventas'].apply(lambda x: pd.Series(calcular_demanda_y_tendencia(x)))
    analisis_ventas.columns = ['Demanda_Diaria_Promedio', 'Tendencia_Ventas', 'Estacionalidad_Reciente']
    df = pd.concat([df, analisis_ventas], axis=1)
    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * df['Lead_Time_Proveedor']) + df['Stock_Seguridad']
    
    # Clasificación ABC
    df_ventas_total = df.copy()
    df_ventas_total['Valor_Venta_60_Dias'] = df_ventas_total['Ventas_60_Dias'] * df_ventas_total['Costo_Promedio_UND']
    ventas_sku = df_ventas_total.groupby('SKU')['Valor_Venta_60_Dias'].sum()
    total_ventas_valor = ventas_sku.sum()
    if total_ventas_valor > 0: sku_to_percent = ventas_sku.sort_values(ascending=False).cumsum() / total_ventas_valor
    else: sku_to_percent = pd.Series(0, index=ventas_sku.index)
    def segmentar_abc(p):
        if p <= 0.8: return 'A'
        if p <= 0.95: return 'B'
        return 'C'
    df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(segmentar_abc).fillna('C')

    # Estado de inventario
    def definir_estado_y_accion(row):
        if row['Stock'] <= 0 and row['Demanda_Diaria_Promedio'] > 0: return 'Quiebre de Stock', 'ABASTECIMIENTO URGENTE'
        if row['Stock'] > 0 and row['Stock'] < row['Punto_Reorden']: return 'Bajo Stock (Riesgo)', 'REVISAR ABASTECIMIENTO'
        if row['Demanda_Diaria_Promedio'] > 0 and (row['Stock'] / row['Demanda_Diaria_Promedio']) > 90: return 'Excedente', 'LIQUIDAR / PROMOCIONAR'
        if row['Stock'] > 0 and row['Demanda_Diaria_Promedio'] <= 0: return 'Baja Rotación / Obsoleto', 'LIQUIDAR / DESCONTINUAR'
        return 'Normal', 'MONITOREAR'
    df[['Estado_Inventario', 'Accion_Requerida']] = df.apply(definir_estado_y_accion, axis=1, result_type='expand')

    # --- LÓGICA DE SUGERENCIAS DE ABASTECIMIENTO (COMPLETAMENTE CORREGIDA) ---
    df['Sugerencia_Traslado'] = ''
    df['Unidades_Traslado_Sugeridas'] = 0
    df['Sugerencia_Compra'] = 0
    df_analisis = df.copy()

    skus_necesitados = df_analisis[df_analisis['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO'])]['SKU'].unique()

    for sku in skus_necesitados:
        necesidad_mask = (df_analisis['SKU'] == sku) & (df_analisis['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO']))
        excedente_df = df_analisis[(df_analisis['SKU'] == sku) & (df_analisis['Stock'] > df_analisis['Punto_Reorden'])].copy()
        
        if not excedente_df.empty:
            excedente_df['Stock_Disponible_Traslado'] = excedente_df.apply(lambda row: max(0, row['Stock'] - row['Punto_Reorden']), axis=1)
        
        almacenes_con_excedente = excedente_df[excedente_df['Stock_Disponible_Traslado'] > 0] if not excedente_df.empty else pd.DataFrame()

        for idx_necesidad in df_analisis[necesidad_mask].index:
            almacen_necesitado_nombre = df_analisis.loc[idx_necesidad, 'Almacen_Nombre']
            origenes_disponibles = almacenes_con_excedente[almacenes_con_excedente['Almacen_Nombre'] != almacen_necesitado_nombre]
            
            # CORRECCIÓN 1: El stock objetivo ahora depende del segmento ABC.
            segmento = df_analisis.loc[idx_necesidad, 'Segmento_ABC']
            if segmento == 'A': multiplicador_stock_objetivo = 1.2
            elif segmento == 'B': multiplicador_stock_objetivo = 1.4
            else: multiplicador_stock_objetivo = 1.6
            
            stock_objetivo = df_analisis.loc[idx_necesidad, 'Punto_Reorden'] * multiplicador_stock_objetivo
            cantidad_necesaria_total = max(0, stock_objetivo - df_analisis.loc[idx_necesidad, 'Stock'])

            if not origenes_disponibles.empty:
                total_disponible_para_traslado = origenes_disponibles['Stock_Disponible_Traslado'].sum()
                
                # CORRECCIÓN 2: La cantidad a trasladar se limita a lo realmente disponible.
                cantidad_real_a_trasladar = min(cantidad_necesaria_total, total_disponible_para_traslado)
                
                if cantidad_real_a_trasladar > 0:
                    sugerencias = [f"{origen['Almacen_Nombre']} ({int(origen['Stock_Disponible_Traslado'])} u.)" for _, origen in origenes_disponibles.iterrows()]
                    df.loc[idx_necesidad, 'Sugerencia_Traslado'] = ", ".join(sugerencias)
                    df.loc[idx_necesidad, 'Unidades_Traslado_Sugeridas'] = int(np.ceil(cantidad_real_a_trasladar))
                
                # NUEVA FUNCIONALIDAD 3: Se sugiere comprar el remanente si el traslado es insuficiente.
                necesidad_restante = cantidad_necesaria_total - cantidad_real_a_trasladar
                if necesidad_restante > 0:
                    df.loc[idx_necesidad, 'Sugerencia_Compra'] = int(np.ceil(necesidad_restante))
                    df.loc[idx_necesidad, 'Accion_Requerida'] = 'COMPRA Y/O TRASLADO'
            else:
                # Si no hay traslados, toda la necesidad se convierte en compra.
                if cantidad_necesaria_total > 0:
                    df.loc[idx_necesidad, 'Sugerencia_Compra'] = int(np.ceil(cantidad_necesaria_total))
                    df.loc[idx_necesidad, 'Accion_Requerida'] = 'COMPRA NECESARIA'

    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']
    
    return df

# --- INTERFAZ DE USUARIO ---
st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Parámetros del Análisis")
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    dias_seguridad_input = st.sidebar.slider("Días de Stock de Seguridad:", min_value=1, max_value=30, value=7, step=1)
    
    df_analisis_completo = analizar_inventario_completo(df_crudo, almacen_principal=almacen_principal_input, dias_seguridad=dias_seguridad_input)
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
        valor_total_inv = df_filtered['Valor_Inventario'].sum()
        df_excedente_kpi = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]
        valor_excedente = df_excedente_kpi['Valor_Inventario'].sum()
        skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        total_ventas_unidades = df_filtered['Ventas_60_Dias'].sum()
        total_stock_unidades = df_filtered['Stock'].sum()
        rotacion_general = total_ventas_unidades / total_stock_unidades if total_stock_unidades > 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
        col2.metric(label="📉 Valor en Excedente", value=f"${valor_excedente:,.0f}")
        col3.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")
        # CORRECCIÓN DE SINTAXIS: Se arregló el paréntesis y el argumento 'label'.
        col4.metric(label="🔄 Rotación General (60 Días)", value=f"{rotacion_general:.2f}")

        st.markdown("---")
        
        st.markdown('<p class="section-header">💡 Consejos Automáticos</p>', unsafe_allow_html=True)
        with st.container(border=True):
            productos_tendencia_fuerte = df_filtered[df_filtered['Tendencia_Ventas'] > 0.5]
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
            st.page_link("pages/3_analisis_de_marca.py", label="Analizar Marcas", icon="📊")
        with col_nav4:
            st.page_link("pages/4_analisis_de_tendencias.py", label="Analizar Tendencias", icon="📈")
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")



