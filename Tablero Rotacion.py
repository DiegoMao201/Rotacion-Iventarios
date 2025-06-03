# app_inventario_streamlit.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io

# --- 1. Configuración inicial de la página de Streamlit ---
st.set_page_config(
    page_title="Tablero de Control de Inventario",
    page_icon="📦",
    layout="wide", # Usa el ancho completo de la página
    initial_sidebar_state="expanded"
)

# --- 2. Cargar los datos analizados ---
@st.cache_data # Decorador para cachear la carga de datos y mejorar el rendimiento
def load_data(file_path='Analisis_Inventario_Resultados_con_Reparto_Detallado.xlsx'):
    try:
        df = pd.read_excel(file_path)
        # Asegurar tipos de datos correctos
        df['Stock'] = df['Stock'].astype(int)
        df['Ventas_60_Dias'] = df['Ventas_60_Dias'].astype(int)
        df['Unidades_Traslado_Sugeridas'] = df['Unidades_Traslado_Sugeridas'].astype(int)
        df['Precio_Promocion'] = df['Precio_Promocion'].round(2)
        df['Almacen'] = df['Almacen'].astype(str) # Asegurar que Almacen sea string para filtros
        df['Departamento'] = df['Departamento'].astype(str) # Asegurar que Departamento sea string
        return df
    except FileNotFoundError:
        st.error(f"ERROR: El archivo '{file_path}' no fue encontrado.")
        st.warning("Por favor, asegúrate de que el script de análisis de inventario haya sido ejecutado y el archivo Excel esté en la misma carpeta.")
        st.stop() # Detiene la ejecución del script
    except Exception as e:
        st.error(f"Error al cargar o procesar los datos: {e}")
        st.stop()

df_analisis = load_data()

# Columnas de interés para la tabla principal
COLUMNAS_INTERES = [
    'SKU',
    'Descripcion',
    'Almacen',
    'Departamento',
    'Stock',
    'Ventas_60_Dias',
    'Demanda_Diaria_Promedio', # Puede ser útil
    'Dias_Inventario',
    'Estado_Inventario_Local',
    'Unidades_Traslado_Sugeridas',
    'Sugerencia_Traslado',
    'Precio_Promocion',
    'Recomendacion'
]

# Asegurarse de que todas las columnas de interés existen
for col in COLUMNAS_INTERES:
    if col not in df_analisis.columns:
        st.warning(f"ADVERTENCIA: La columna '{col}' no se encontró en el archivo de datos. Se omitirá.")
        COLUMNAS_INTERES.remove(col)

# --- 3. Título del Tablero ---
st.title("📦 Tablero de Control y Optimización de Inventario")
st.markdown("---")

# --- 4. Barra Lateral para Filtros ---
st.sidebar.header("⚙️ Opciones de Filtrado")

# Filtro por Almacén
selected_almacenes = st.sidebar.multiselect(
    "Selecciona Almacén(es):",
    options=sorted(df_analisis['Almacen'].unique()),
    default=[]
)

# Filtro por Departamento
selected_departamentos = st.sidebar.multiselect(
    "Selecciona Departamento(s):",
    options=sorted(df_analisis['Departamento'].unique()),
    default=[]
)

# Búsqueda por SKU
search_sku = st.sidebar.text_input(
    "Buscar por SKU (Referencia):",
    placeholder="Ej: SKU12345"
)

# Filtro por Estado de Inventario Local
selected_estados = st.sidebar.multiselect(
    "Filtrar por Estado de Inventario:",
    options=sorted(df_analisis['Estado_Inventario_Local'].unique()),
    default=[]
)

# --- Aplicar Filtros ---
df_filtered = df_analisis.copy()

if selected_almacenes:
    df_filtered = df_filtered[df_filtered['Almacen'].isin(selected_almacenes)]
if selected_departamentos:
    df_filtered = df_filtered[df_filtered['Departamento'].isin(selected_departamentos)]
if search_sku:
    df_filtered = df_filtered[df_filtered['SKU'].str.contains(search_sku, case=False, na=False)]
if selected_estados:
    df_filtered = df_filtered[df_filtered['Estado_Inventario_Local'].isin(selected_estados)]

if df_filtered.empty:
    st.warning("No se encontraron datos con los filtros seleccionados. Intenta ajustar tus filtros.")
    st.stop() # Detiene la ejecución si no hay datos


# --- 5. Métricas Clave (KPIs) ---
st.header("📊 Métricas Clave del Inventario")

total_inventario_valor = (df_filtered['Stock'] * df_filtered['Precio_Promocion']).sum().round(2)
unidades_en_quiebre = df_filtered[df_filtered['Estado_Inventario_Local'] == 'Quiebre de Stock']['Stock'].sum() # Stock en 0, pero se cuenta el registro
unidades_en_excedente = df_filtered[df_filtered['Estado_Inventario_Local'] == 'Excedente / Lento Movimiento']['Stock'].sum()
unidades_sugeridas_traslado = df_filtered['Unidades_Traslado_Sugeridas'].sum()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(label="Valor Total del Inventario Filtrado", value=f"${total_inventario_valor:,.2f}")
with col2:
    st.metric(label="Unidades en Quiebre de Stock", value=f"{unidades_en_quiebre:,.0f} unid.")
with col3:
    st.metric(label="Unidades en Excedente", value=f"{unidades_en_excedente:,.0f} unid.")
with col4:
    st.metric(label="Unidades Sugeridas para Traslado", value=f"{unidades_sugeridas_traslado:,.0f} unid.")

st.markdown("---")

# --- 6. Visualizaciones (Gráficos) ---
st.header("📈 Gráficos de Inventario")

col_graph1, col_graph2 = st.columns(2)

with col_graph1:
    # Gráfico de Distribución por Estado de Inventario
    estado_counts = df_filtered['Estado_Inventario_Local'].value_counts().reset_index()
    estado_counts.columns = ['Estado', 'Cantidad']
    fig_estado = px.pie(estado_counts, values='Cantidad', names='Estado',
                        title='Distribución del Inventario por Estado',
                        color_discrete_sequence=px.colors.qualitative.Set3)
    fig_estado.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='#000000', width=1)))
    st.plotly_chart(fig_estado, use_container_width=True)

with col_graph2:
    # Gráfico de Rotación de Inventario por Departamento (promedio)
    # Solo incluir departamentos con stock > 0 para una rotación significativa
    df_rotacion_dept = df_filtered[df_filtered['Stock'] > 0].groupby('Departamento')['Rotacion_60_Dias'].mean().reset_index()
    df_rotacion_dept = df_rotacion_dept.sort_values(by='Rotacion_60_Dias', ascending=False)
    fig_rotacion = px.bar(df_rotacion_dept, x='Departamento', y='Rotacion_60_Dias',
                          title='Rotación Promedio de Inventario por Departamento',
                          labels={'Rotacion_60_Dias': 'Rotación (Ventas / Stock)'},
                          color_discrete_sequence=px.colors.qualitative.Pastel)
    st.plotly_chart(fig_rotacion, use_container_width=True)

st.markdown("---")

# --- 7. Tablas de Resumen (Críticos y Excedente) ---
st.header("📋 Resumen de SKUs Críticos y Excedentes")

col_table1, col_table2 = st.columns(2)

with col_table1:
    st.subheader("🚨 SKUs Críticos (Bajo Stock / Quiebre)")
    df_criticos = df_filtered[df_filtered['Estado_Inventario_Local'].isin(['Bajo Stock / Reordenar', 'Quiebre de Stock'])].copy()
    if not df_criticos.empty:
        df_criticos = df_criticos.sort_values(by=['Estado_Inventario_Local', 'Dias_Inventario'], ascending=[True, True])
        # Columnas específicas para esta tabla
        st.dataframe(df_criticos[['SKU', 'Almacen', 'Stock', 'Ventas_60_Dias', 'Dias_Inventario', 'Recomendacion']].head(20),
                     hide_index=True,
                     use_container_width=True,
                     column_config={
                         "Stock": st.column_config.NumberColumn(format="%d"),
                         "Ventas_60_Dias": st.column_config.NumberColumn(format="%d"),
                         "Dias_Inventario": st.column_config.NumberColumn(format="%.0f"),
                     })
    else:
        st.info("No hay SKUs críticos con los filtros actuales.")

with col_table2:
    st.subheader("🟢 SKUs en Excedente / Baja Rotación")
    df_excedente = df_filtered[df_filtered['Estado_Inventario_Local'].isin(['Excedente / Lento Movimiento', 'Baja Rotación / Obsoleto'])].copy()
    if not df_excedente.empty:
        df_excedente = df_excedente.sort_values(by=['Estado_Inventario_Local', 'Dias_Inventario'], ascending=[True, False])
        # Columnas específicas para esta tabla
        st.dataframe(df_excedente[['SKU', 'Almacen', 'Stock', 'Dias_Inventario', 'Unidades_Traslado_Sugeridas', 'Sugerencia_Traslado', 'Precio_Promocion']].head(20),
                     hide_index=True,
                     use_container_width=True,
                     column_config={
                         "Stock": st.column_config.NumberColumn(format="%d"),
                         "Dias_Inventario": st.column_config.NumberColumn(format="%.0f"),
                         "Unidades_Traslado_Sugeridas": st.column_config.NumberColumn(format="%d"),
                         "Precio_Promocion": st.column_config.NumberColumn(format="$%.2f"),
                     })
    else:
        st.info("No hay SKUs en excedente o baja rotación con los filtros actuales.")

st.markdown("---")

# --- 8. Tabla Detallada del Inventario ---
st.header("📦 Detalle del Inventario (Datos Filtrados)")

# Tabla principal
st.dataframe(
    df_filtered[COLUMNAS_INTERES],
    hide_index=True,
    use_container_width=True, # Ajusta al ancho del contenedor
    height=400, # Altura fija para la tabla
    column_config={
        "Stock": st.column_config.NumberColumn(format="%d"),
        "Ventas_60_Dias": st.column_config.NumberColumn(format="%d"),
        "Demanda_Diaria_Promedio": st.column_config.NumberColumn(format="%.2f"),
        "Dias_Inventario": st.column_config.NumberColumn(format="%.0f"),
        "Unidades_Traslado_Sugeridas": st.column_config.NumberColumn(format="%d"),
        "Precio_Promocion": st.column_config.NumberColumn(format="$%.2f"),
    }
)

# --- 9. Botón de Descarga ---
@st.cache_data # Cachear la función de conversión para mejorar el rendimiento
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario Filtrado')
    processed_data = output.getvalue()
    return processed_data

excel_data = convert_df_to_excel(df_filtered[COLUMNAS_INTERES])

st.download_button(
    label="Descargar Datos Filtrados a Excel",
    data=excel_data,
    file_name="inventario_filtrado_streamlit.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    help="Descarga la tabla de inventario con los filtros aplicados."
)

st.markdown("---")
st.caption("Desarrollado con ❤️ por tu Asistente de IA.")