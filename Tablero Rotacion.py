import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import dropbox
import io
from datetime import datetime

# --- 1. CONFIGURACIÓN INICIAL DE LA PÁGINA ---
st.set_page_config(
    page_title="Plan de Acción de Inventario",
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

# --- 2. LÓGICA DE CARGA Y ANÁLISIS ---
@st.cache_data(ttl=600)
def cargar_datos_desde_dropbox():
    info_message = st.empty()
    info_message.info("Conectando a Dropbox para obtener los datos más recientes...", icon="☁️")
    try:
        dbx_creds = st.secrets["dropbox"]
        with dropbox.Dropbox(app_key=dbx_creds["app_key"], app_secret=dbx_creds["app_secret"], oauth2_refresh_token=dbx_creds["refresh_token"]) as dbx:
            metadata, res = dbx.files_download(path=dbx_creds["file_path"])
            with io.BytesIO(res.content) as stream:
                df_crudo = pd.read_csv(stream, encoding='latin1', sep='|', engine='python')
        info_message.empty()
        return df_crudo
    except Exception as e:
        info_message.error(f"Ocurrió un error al cargar los datos: {e}", icon="🔥")
        return None

@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155', lead_time_dias=10, dias_seguridad=7):
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()
    
    df = _df_crudo.copy()
    df.columns = df.columns.str.strip().str.upper()
    
    column_mapping = {
        'CODALMACEN': 'Almacen', 'DEPARTAMENTO': 'Departamento', 'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias', 'STOCK': 'Stock', 'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo' # <-- MEJORA: Incluir peso
    }
    df.rename(columns=column_mapping, inplace=True)
    
    essential_cols = ['Almacen', 'SKU', 'Stock', 'Ventas_60_Dias']
    if not all(col in df.columns for col in essential_cols):
        st.error("Faltan columnas esenciales en el archivo de origen.", icon="🚨")
        return pd.DataFrame()

    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo'] # <-- MEJORA: Incluir peso
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
        else:
            df[col] = 0 # Si la columna de peso no existe, se crea con ceros
    
    df['Stock'] = df['Stock'].apply(lambda x: max(0, x))
    df['Almacen'] = df['Almacen'].astype(str)
    df['Demanda_Diaria_Promedio'] = df['Ventas_60_Dias'] / 60
    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * lead_time_dias) + df['Stock_Seguridad']

    df_ventas_total = df.copy()
    df_ventas_total['Valor_Venta_60_Dias'] = df_ventas_total['Ventas_60_Dias'] * df_ventas_total['Costo_Promedio_UND']
    ventas_sku = df_ventas_total.groupby('SKU')['Valor_Venta_60_Dias'].sum()
    total_ventas_valor = ventas_sku.sum()
    
    if total_ventas_valor > 0:
        sku_to_percent = ventas_sku.sort_values(ascending=False).cumsum() / total_ventas_valor
    else:
        sku_to_percent = pd.Series(0, index=ventas_sku.index)
    
    def segmentar_abc(p):
        if p <= 0.8: return 'A'
        if p <= 0.95: return 'B'
        return 'C'
    df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(segmentar_abc).fillna('C')

    def definir_estado_y_accion(row):
        if row['Stock'] <= 0 and row['Demanda_Diaria_Promedio'] > 0:
            return 'Quiebre de Stock', 'ABASTECIMIENTO URGENTE'
        if row['Stock'] > 0 and row['Stock'] < row['Punto_Reorden']:
            return 'Bajo Stock (Riesgo)', 'REVISAR ABASTECIMIENTO'
        if row['Demanda_Diaria_Promedio'] > 0 and (row['Stock'] / row['Demanda_Diaria_Promedio']) > 90:
             return 'Excedente', 'LIQUIDAR / PROMOCIONAR'
        if row['Stock'] > 0 and row['Demanda_Diaria_Promedio'] <= 0:
            return 'Baja Rotación / Obsoleto', 'LIQUIDAR / DESCONTINUAR'
        return 'Normal', 'MONITOREAR'
    df[['Estado_Inventario', 'Accion_Requerida']] = df.apply(definir_estado_y_accion, axis=1, result_type='expand')

    # --- LÓGICA DE SUGERENCIAS Y PESO (CORREGIDA Y MEJORADA) ---
    df['Sugerencia_Traslado'] = ''
    df['Unidades_Traslado_Sugeridas'] = 0
    df['Sugerencia_Compra'] = 0
    
    df_analisis = df.copy()
    skus_necesitados = df_analisis[df_analisis['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO'])]['SKU'].unique()

    for sku in skus_necesitados:
        necesidad_mask = (df_analisis['SKU'] == sku) & (df_analisis['Accion_Requerida'].isin(['ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO']))
        excedente_df = df_analisis[(df_analisis['SKU'] == sku) & (df_analisis['Stock'] > df_analisis['Punto_Reorden'])].copy()
        excedente_df['Stock_Disponible_Traslado'] = excedente_df['Stock'] - excedente_df['Punto_Reorden']
        
        almacenes_con_excedente = excedente_df[excedente_df['Stock_Disponible_Traslado'] > 0]
        
        for idx_necesidad in df_analisis[necesidad_mask].index:
            almacen_necesitado = df_analisis.loc[idx_necesidad, 'Almacen']
            origenes_disponibles = almacenes_con_excedente[almacenes_con_excedente['Almacen'] != almacen_necesitado]
            
            if not origenes_disponibles.empty:
                sugerencias = []
                for _, origen in origenes_disponibles.iterrows():
                    unidades_disponibles = int(origen['Stock_Disponible_Traslado'])
                    sugerencias.append(f"Alm. {origen['Almacen']} ({unidades_disponibles} u.)")
                
                # *** CORRECCIÓN DEL BUG: Asignar la sugerencia detallada ***
                df.loc[idx_necesidad, 'Sugerencia_Traslado'] = ", ".join(sugerencias)
                
                stock_objetivo = df_analisis.loc[idx_necesidad, 'Punto_Reorden'] * 1.5
                cantidad_necesaria = max(0, stock_objetivo - df_analisis.loc[idx_necesidad, 'Stock'])
                df.loc[idx_necesidad, 'Unidades_Traslado_Sugeridas'] = int(np.ceil(cantidad_necesaria))
            else:
                stock_objetivo = df_analisis.loc[idx_necesidad, 'Punto_Reorden'] * 1.5
                cantidad_necesaria = max(0, stock_objetivo - df_analisis.loc[idx_necesidad, 'Stock'])
                if cantidad_necesaria > 0:
                    df.loc[idx_necesidad, 'Sugerencia_Compra'] = int(np.ceil(cantidad_necesaria))
                    df.loc[idx_necesidad, 'Accion_Requerida'] = 'COMPRA NECESARIA'

    # *** MEJORA: Cálculo del peso sugerido ***
    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']
    
    return df

# --- INTERFAZ DE USUARIO ---
# La UI se mantiene igual, ya que los cambios de lógica se reflejarán en los datos.
st.title("🚀 Plan de Acción de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Filtros del Análisis")
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    
    df_analisis_completo = analizar_inventario_completo(df_crudo, almacen_principal_input)
    st.session_state['df_analisis'] = df_analisis_completo

    if not df_analisis_completo.empty:
        lista_almacenes = sorted(df_analisis_completo['Almacen'].unique())
        selected_almacen = st.sidebar.selectbox("Selecciona tu Almacén:", lista_almacenes)
        
        df_filtered = df_analisis_completo[df_analisis_completo['Almacen'] == selected_almacen]

        st.markdown('<p class="section-header">Métricas Clave de tu Tienda</p>', unsafe_allow_html=True)
        valor_total_inv = df_filtered['Valor_Inventario'].sum()
        valor_excedente = df_filtered[df_filtered['Estado_Inventario'] == 'Excedente']['Valor_Inventario'].sum()
        skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        perdida_potencial = (df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['Demanda_Diaria_Promedio'] * df_filtered['Costo_Promedio_UND']).sum()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(label="💰 Valor Total del Inventario", value=f"${valor_total_inv:,.0f}")
        with col2:
            st.metric(label="📉 Valor en Excedente", value=f"${valor_excedente:,.0f}")
        with col3:
            st.metric(label="📦 SKUs en Quiebre de Stock", value=f"{skus_quiebre}", delta_color="inverse")
        with col4:
            st.metric(label="💸 Pérdida Diaria Potencial", value=f"${perdida_potencial:,.0f}", delta="Por quiebres", delta_color="inverse")

        st.markdown("---")
        
        col_accion1, col_accion2 = st.columns(2)
        with col_accion1:
            st.markdown('<p class="section-header">🚨 Acciones de Abastecimiento</p>', unsafe_allow_html=True)
            df_abastecimiento = df_filtered[df_filtered['Accion_Requerida'].isin(['COMPRA NECESARIA', 'ABASTECIMIENTO URGENTE', 'REVISAR ABASTECIMIENTO'])].sort_values(by='Segmento_ABC')
            st.info(f"Tienes **{df_abastecimiento.shape[0]} SKUs** que requieren tu atención inmediata.", icon="💡")
            st.dataframe(df_abastecimiento[['SKU', 'Descripcion', 'Stock', 'Punto_Reorden', 'Accion_Requerida']].head(5), hide_index=True, use_container_width=True)
            st.page_link("pages/1_gestion_abastecimiento.py", label="Ir a Gestión de Abastecimiento", icon="🚚")
        with col_accion2:
            st.markdown('<p class="section-header">💸 Acciones de Optimización</p>', unsafe_allow_html=True)
            df_optimizacion = df_filtered[df_filtered['Accion_Requerida'].str.contains('LIQUIDAR')].sort_values(by='Valor_Inventario', ascending=False)
            st.warning(f"Tienes **{df_optimizacion.shape[0]} SKUs** con baja rotación o excedente.", icon="💰")
            st.dataframe(df_optimizacion[['SKU', 'Descripcion', 'Stock', 'Valor_Inventario', 'Estado_Inventario']].head(5), hide_index=True, use_container_width=True, column_config={"Valor_Inventario": st.column_config.NumberColumn(format="$ %d")})
            st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")

        st.markdown("---")
        
        st.markdown('<p class="section-header">Distribución del Inventario</p>', unsafe_allow_html=True)
        col_viz1, col_viz2 = st.columns(2)
        with col_viz1:
            df_distribucion = df_filtered.groupby('Estado_Inventario')['Valor_Inventario'].sum().reset_index()
            fig = px.pie(df_distribucion, values='Valor_Inventario', names='Estado_Inventario', title='Distribución del Valor por Estado', hole=0.4, color_discrete_map={'Excedente':'#FF7F0E', 'Quiebre de Stock':'#D62728', 'Bajo Stock (Riesgo)':'#FFD700', 'Normal':'#2CA02C', 'Baja Rotación / Obsoleto': '#8C564B'})
            fig.update_layout(legend_title_text='Estado')
            st.plotly_chart(fig, use_container_width=True)
        with col_viz2:
            df_abc = df_filtered.groupby('Segmento_ABC')['Valor_Inventario'].sum().reset_index()
            fig2 = px.bar(df_abc, x='Segmento_ABC', y='Valor_Inventario', title='Valor de Inventario por Segmento ABC', text_auto='.2s', labels={'Segmento_ABC': 'Segmento', 'Valor_Inventario': 'Valor del Inventario ($)'})
            fig2.update_traces(textposition='outside')
            st.plotly_chart(fig2, use_container_width=True)
            
    else:
        st.warning("El análisis no produjo resultados. Revisa el archivo de origen.")
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
