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


# --- NUEVA FUNCIÓN PARA CÁLCULO DE DEMANDA PONDERADA (CORREGIDA) ---
def calcular_demanda_ponderada(historial_str, dias_periodo=60):
    """
    Calcula la demanda diaria ponderada. Las ventas más recientes tienen más peso.
    Devuelve un promedio diario.
    """
    if not isinstance(historial_str, str) or historial_str == '':
        return 0

    total_unidades_ponderadas = 0
    total_pesos = 0
    
    ventas = historial_str.split(',')
    fecha_hoy = datetime.now().date()

    for venta in ventas:
        try:
            fecha_str, cantidad_str = venta.split(':')
            fecha_venta = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            cantidad = float(cantidad_str)
            
            dias_atras = (fecha_hoy - fecha_venta).days
            peso = max(0, dias_periodo - dias_atras)
            
            # *** CORRECCIÓN: Se eliminó el espacio en el nombre de la variable ***
            total_unidades_ponderadas += cantidad * peso
            total_pesos += peso
        except (ValueError, IndexError):
            continue

    if total_pesos == 0:
        return 0
    
    demanda_diaria = total_unidades_ponderadas / total_pesos
    return demanda_diaria


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
                df_crudo = pd.read_csv(stream, encoding='latin1', sep='|')
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
        'REFERENCIA': 'SKU', 'MARCA': 'Marca', 'PESO_ARTICULO': 'Peso_Articulo', 'HISTORIAL_VENTAS': 'Historial_Ventas'
    }
    df.rename(columns=column_mapping, inplace=True)
    
    df['Almacen'] = df['Almacen'].astype(str)
    almacen_map = {'155': 'Cedi', '156': 'Armenia', '157': 'Manizales', '189': 'Olaya', '238': 'Laureles', '439': 'FerreBox'}
    df['Almacen_Nombre'] = df['Almacen'].map(almacen_map).fillna(df['Almacen'])
    
    if 'Marca' in df.columns:
        df['Marca_str'] = pd.to_numeric(df['Marca'], errors='coerce').fillna(0).astype(int).astype(str)
        marca_map = {'41':'TERINSA','50':'P8-ASC-MEGA','54':'MPY-International','55':'DPP-AN COLORANTS LATAM','56':'DPP-Pintuco Profesional','57':'ASC-Mega','58':'DPP-Pintuco','59':'DPP-Madetec','60':'POW-Interpon','61':'various','62':'DPP-ICO','63':'DPP-Terinsa','64':'MPY-Pintuco','65':'non-AN Third Party','66':'ICO-AN Packaging','67':'ASC-Automotive OEM','68':'POW-Resicoat'}
        df['Marca_Nombre'] = df['Marca_str'].map(marca_map).fillna('Complementarios')
    else:
        df['Marca_Nombre'] = 'No especificada'

    numeric_cols = ['Ventas_60_Dias', 'Costo_Promedio_UND', 'Stock', 'Peso_Articulo']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
        else:
            df[col] = 0
    
    df['Stock'] = df['Stock'].apply(lambda x: max(0, x))
    
    df['Demanda_Diaria_Promedio'] = df['Historial_Ventas'].apply(calcular_demanda_ponderada)

    df['Valor_Inventario'] = df['Stock'] * df['Costo_Promedio_UND']
    df['Stock_Seguridad'] = df['Demanda_Diaria_Promedio'] * dias_seguridad
    df['Punto_Reorden'] = (df['Demanda_Diaria_Promedio'] * lead_time_dias) + df['Stock_Seguridad']
    df['Rotacion_60_Dias'] = df.apply(lambda r: r['Ventas_60_Dias'] / r['Stock'] if r['Stock'] > 0 else 0, axis=1)
    
    df_ventas_total = df.copy()
    df_ventas_total['Valor_Venta_60_Dias'] = df_ventas_total['Ventas_60_Dias'] * df_ventas_total['Costo_Promedio_UND']
    ventas_sku = df_ventas_total.groupby('SKU')['Valor_Venta_60_Dias'].sum()
    total_ventas_valor = ventas_sku.sum()
    if total_ventas_valor > 0: sku_to_percent = ventas_sku.sort_values(ascending=False).cumsum() / total_ventas_valor
    else: sku_to_percent = pd.Series(0, index=ventas_sku.index)
    def segmentar_abc(p):
        if p <= 0.8: return 'A';
        if p <= 0.95: return 'B';
        return 'C'
    df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(segmentar_abc).fillna('C')
    def definir_estado_y_accion(row):
        if row['Stock'] <= 0 and row['Demanda_Diaria_Promedio'] > 0: return 'Quiebre de Stock', 'ABASTECIMIENTO URGENTE'
        if row['Stock'] > 0 and row['Stock'] < row['Punto_Reorden']: return 'Bajo Stock (Riesgo)', 'REVISAR ABASTECIMIENTO'
        if row['Demanda_Diaria_Promedio'] > 0 and (row['Stock'] / row['Demanda_Diaria_Promedio']) > 90: return 'Excedente', 'LIQUIDAR / PROMOCIONAR'
        if row['Stock'] > 0 and row['Demanda_Diaria_Promedio'] <= 0: return 'Baja Rotación / Obsoleto', 'LIQUIDAR / DESCONTINUAR'
        return 'Normal', 'MONITOREAR'
    df[['Estado_Inventario', 'Accion_Requerida']] = df.apply(definir_estado_y_accion, axis=1, result_type='expand')
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
            almacen_necesitado_nombre = df_analisis.loc[idx_necesidad, 'Almacen_Nombre']
            origenes_disponibles = almacenes_con_excedente[almacenes_con_excedente['Almacen_Nombre'] != almacen_necesitado_nombre]
            if not origenes_disponibles.empty:
                sugerencias = [f"{origen['Almacen_Nombre']} ({int(origen['Stock_Disponible_Traslado'])} u.)" for _, origen in origenes_disponibles.iterrows()]
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
    df['Peso_Traslado_Sugerido'] = df['Unidades_Traslado_Sugeridas'] * df['Peso_Articulo']
    df['Peso_Compra_Sugerida'] = df['Sugerencia_Compra'] * df['Peso_Articulo']

    return df


# --- INTERFAZ DE USUARIO ---
# (Sin cambios en esta sección)
st.title("🚀 Resumen Ejecutivo de Inventario")
st.markdown(f"###### Panel de control para la toma de decisiones. Actualizado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

df_crudo = cargar_datos_desde_dropbox()

if df_crudo is not None and not df_crudo.empty:
    st.sidebar.header("⚙️ Filtros del Análisis")
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    
    df_analisis_completo = analizar_inventario_completo(df_crudo, almacen_principal=almacen_principal_input)
    st.session_state['df_analisis'] = df_analisis_completo

    if not df_analisis_completo.empty:
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
        
        if not selected_marcas: df_filtered = df_vista
        else: df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]

        st.markdown(f'<p class="section-header">Métricas Clave: {selected_almacen_nombre}</p>', unsafe_allow_html=True)
        valor_total_inv = df_filtered['Valor_Inventario'].sum()
        df_excedente_kpi = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]
        valor_excedente = df_excedente_kpi['Valor_Inventario'].sum()
        skus_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['SKU'].nunique()
        perdida_potencial = (df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']['Demanda_Diaria_Promedio'] * df_filtered['Costo_Promedio_UND']).sum()
        total_ventas_unidades = df_filtered['Ventas_60_Dias'].sum()
        total_stock_unidades = df_filtered['Stock'].sum()
        rotacion_general = total_ventas_unidades / total_stock_unidades if total_stock_unidades > 0 else 0
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric(label="💰 Valor Total Inventario", value=f"${valor_total_inv:,.0f}")
        col2.metric(label="📉 Valor en Excedente", value=f"${valor_excedente:,.0f}")
        col3.metric(label="📦 SKUs en Quiebre", value=f"{skus_quiebre}")
        col4.metric(label="💸 Pérdida Diaria Potencial", value=f"${perdida_potencial:,.0f}")
        col5.metric(label="🔄 Rotación General (60 Días)", value=f"{rotacion_general:.2f}")

        st.markdown("---")
        
        st.markdown('<p class="section-header">💡 Consejos Automáticos</p>', unsafe_allow_html=True)
        with st.container(border=True):
            if skus_quiebre > 5:
                st.warning(f"**Prioridad Alta:** Tienes **{skus_quiebre} SKUs en quiebre de stock**. Es crucial que visites la página de 'Gestión de Abastecimiento' para evitar pérdidas de venta.")
            if valor_total_inv > 0 and (valor_excedente / valor_total_inv > 0.25):
                st.error(f"**Alerta de Capital:** Más del 25% de tu inventario (${valor_excedente:,.0f}) es excedente. Enfócate en liquidar estos productos visitando la página de 'Análisis de Excedentes'.")
            if rotacion_general < 0.5 and rotacion_general > 0:
                st.info("**Oportunidad de Mejora:** La rotación general es baja. Explora el 'Análisis de Marca' para identificar las marcas de menor movimiento y planificar acciones comerciales.")
            if skus_quiebre == 0 and (valor_total_inv == 0 or (valor_excedente / valor_total_inv < 0.1)):
                st.success("**¡Excelente Gestión!** Tus niveles de inventario están saludables, con pocos quiebres y bajo excedente. ¡Sigue así!")

        st.markdown("---")
        st.markdown('<p class="section-header">Navegación a Módulos de Análisis</p>', unsafe_allow_html=True)
        
        col_nav1, col_nav2, col_nav3 = st.columns(3)
        with col_nav1:
            st.page_link("pages/1_gestion_abastecimiento.py", label="Gestionar Traslados y Compras", icon="🚚")
            st.caption("Planifica y ejecuta los movimientos de inventario necesarios para tu tienda o para toda la red.")
        with col_nav2:
            st.page_link("pages/2_analisis_excedentes.py", label="Analizar Excedentes", icon="📉")
            st.caption("Identifica los productos que inmovilizan tu capital y crea planes de acción para liquidarlos.")
        with col_nav3:
            st.page_link("pages/3_analisis_de_marca.py", label="Analizar Salud de Marcas", icon="📊")
            st.caption("Profundiza en el rendimiento de cada marca para tomar decisiones comerciales estratégicas.")
else:
    st.error("La carga de datos inicial falló. Revisa los mensajes de error o el archivo en Dropbox.")
