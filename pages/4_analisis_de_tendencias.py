import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime
import io

# --- Configuración de la Página ---
st.set_page_config(page_title="Análisis de Tendencias", layout="wide", page_icon="📈")
st.title("📈 Análisis de Tendencias y Estacionalidad")
st.markdown("Identifica los productos que están acelerando o desacelerando sus ventas para tomar acciones proactivas.")

# --- Funciones de Ayuda ---

@st.cache_data
def convert_df_to_excel(df):
    """Convierte un DataFrame a un archivo Excel en memoria para descarga."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Tendencias')
    processed_data = output.getvalue()
    return processed_data

@st.cache_data
def calcular_tendencia(historial_str):
    """
    Calcula la pendiente de la línea de regresión lineal para las ventas.
    Una pendiente positiva indica crecimiento; negativa, decremento.
    """
    if not isinstance(historial_str, str) or ':' not in historial_str:
        return 0.0

    records = []
    for venta in historial_str.split(','):
        try:
            fecha_str, cantidad_str = venta.split(':')
            records.append({
                'Fecha': datetime.strptime(fecha_str, '%Y-%m-%d'),
                'Unidades': float(cantidad_str)
            })
        except (ValueError, IndexError):
            continue
    
    if len(records) < 2:
        return 0.0

    df_ventas = pd.DataFrame(records)
    df_ventas = df_ventas.sort_values('Fecha').reset_index(drop=True)
    
    # Convertir fechas a un valor numérico (días desde la primera venta) para la regresión
    df_ventas['Dias'] = (df_ventas['Fecha'] - df_ventas['Fecha'].min()).dt.days
    
    # Calcular regresión lineal (y = mx + b), donde 'm' (la pendiente) es nuestra tendencia
    try:
        # polyfit(x, y, grado_del_polinomio) -> para lineal, grado es 1
        pendiente, _ = np.polyfit(df_ventas['Dias'], df_ventas['Unidades'], 1)
        return pendiente
    except Exception:
        return 0.0

# --- Lógica Principal de la Página ---

# Verificar si los datos del análisis principal están disponibles en la sesión
if 'df_analisis' not in st.session_state or st.session_state['df_analisis'].empty:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la Página Principal", icon="🏠")
else:
    df_analisis_completo = st.session_state['df_analisis'].reset_index()

    # --- Barra Lateral de Filtros ---
    st.sidebar.header("Filtros de Vista")
    
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
    map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
    
    # CORRECCIÓN DEL ERROR: Manejar posibles valores nulos o no-string antes de ordenar
    lista_nombres_unicos = sorted([str(nombre) for nombre in nombres_almacen['Almacen_Nombre'].unique() if pd.notna(nombre)])
    lista_seleccion_nombres = [opcion_consolidado] + lista_nombres_unicos
    
    selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres, key="sb_tendencias")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_analisis_completo
    else:
        codigo_almacen_seleccionado = map_nombre_a_codigo.get(selected_almacen_nombre)
        df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado] if codigo_almacen_seleccionado else pd.DataFrame()

    lista_marcas_unicas = sorted([str(m) for m in df_vista['Marca_Nombre'].unique() if pd.notna(m)])
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas_unicas, default=lista_marcas_unicas, key="filtro_marca_tendencias")
    
    if not selected_marcas:
        df_filtered = pd.DataFrame() # Si no se selecciona marca, no mostrar nada
    else:
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)].copy()

    st.header(f"Análisis para: {selected_almacen_nombre}", divider='rainbow')

    if df_filtered.empty:
        st.warning("No hay datos para mostrar con los filtros seleccionados.")
    else:
        # --- Cálculo de la Tendencia (la parte más importante) ---
        with st.spinner("Calculando tendencias de venta para cada producto..."):
            df_filtered['Tendencia_Ventas'] = df_filtered['Historial_Ventas'].apply(calcular_tendencia)

        # --- Interfaz de Pestañas ---
        tab1, tab2 = st.tabs(["📈 Tendencias de Venta (Regresión Lineal)", "📊 Estacionalidad Reciente (Últimos 60 Días)"])

        with tab1:
            st.markdown("#### ¿Qué es la Tendencia?")
            st.caption("""
            La tendencia se calcula usando una regresión lineal sobre el historial de ventas de cada producto. El valor representa la **pendiente de la línea de ventas**.
            - **Valor Positivo (> 0):** Las ventas del producto están **creciendo** a lo largo del tiempo.
            - **Valor Negativo (< 0):** Las ventas del producto están **decreciendo**.
            - **Valor cercano a 0:** Las ventas son estables o no tienen una tendencia clara.
            """)
            
            col1, col2 = st.columns(2)
            
            # Productos con Crecimiento
            with col1:
                st.subheader("🚀 Productos con Mayor Crecimiento")
                st.info("Estos productos están acelerando sus ventas. Considera aumentar su stock o revisar su visibilidad.")
                top_crecimiento = df_filtered[df_filtered['Tendencia_Ventas'] > 0].sort_values(by='Tendencia_Ventas', ascending=False)
                
                st.dataframe(
                    top_crecimiento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']],
                    column_config={"Tendencia_Ventas": st.column_config.ProgressColumn(
                        "Tendencia (Pendiente)",
                        help="La pendiente de la línea de regresión de ventas. Un valor positivo indica crecimiento.",
                        format="%.3f",
                        min_value=0,
                        max_value=max(1, top_crecimiento['Tendencia_Ventas'].max() if not top_crecimiento.empty else 1),
                    )},
                    hide_index=True, use_container_width=True
                )
                
                if not top_crecimiento.empty:
                    excel_crecimiento = convert_df_to_excel(top_crecimiento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']])
                    st.download_button(
                        label="📥 Descargar lista en Excel",
                        data=excel_crecimiento,
                        file_name=f"productos_en_crecimiento_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                        mime="application/vnd.ms-excel"
                    )

            # Productos con Decremento
            with col2:
                st.subheader("🐌 Productos con Mayor Decremento")
                st.warning("Las ventas de estos productos están desacelerando. Evita reabastecer en exceso y considera promociones.")
                top_decremento = df_filtered[df_filtered['Tendencia_Ventas'] < 0].sort_values(by='Tendencia_Ventas', ascending=True)

                st.dataframe(
                    top_decremento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']],
                    column_config={"Tendencia_Ventas": st.column_config.ProgressColumn(
                        "Tendencia (Pendiente)",
                        help="La pendiente de la línea de regresión de ventas. Un valor negativo indica decremento.",
                        format="%.3f",
                        min_value=min(-1, top_decremento['Tendencia_Ventas'].min() if not top_decremento.empty else -1),
                        max_value=0,
                    )},
                    hide_index=True, use_container_width=True
                )
                
                if not top_decremento.empty:
                    excel_decremento = convert_df_to_excel(top_decremento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']])
                    st.download_button(
                        label="📥 Descargar lista en Excel",
                        data=excel_decremento,
                        file_name=f"productos_en_decremento_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                        mime="application/vnd.ms-excel"
                    )

        with tab2:
            st.subheader("🔍 Análisis de Estacionalidad Reciente")
            st.info("La gráfica compara las ventas totales de los últimos 30 días con las de los 30 días anteriores (días 31-60). Es útil para detectar cambios de demanda a corto plazo.")

            productos_estacionales = df_filtered[df_filtered['Estacionalidad_Reciente'] != 0].copy()
            
            if productos_estacionales.empty:
                st.info("No se encontraron productos con cambios significativos en ventas en los últimos 60 días.")
            else:
                productos_estacionales['Tipo_Estacionalidad'] = np.where(productos_estacionales['Estacionalidad_Reciente'] > 0, 'Crecimiento Reciente', 'Decremento Reciente')
                
                fig = px.bar(
                    productos_estacionales.sort_values('Estacionalidad_Reciente', ascending=False).head(50), # Mostrar los 50 más relevantes
                    x='SKU', 
                    y='Estacionalidad_Reciente', 
                    color='Tipo_Estacionalidad',
                    title="Top 50 - Comparación de Ventas: Últimos 30 vs. 30 Anteriores",
                    labels={'Estacionalidad_Reciente': 'Diferencia de Unidades Vendidas', 'SKU': 'Producto'},
                    color_discrete_map={'Crecimiento Reciente':'#28a745', 'Decremento Reciente':'#dc3545'},
                    template="streamlit"
                )
                fig.update_layout(xaxis_title="Producto (SKU)", yaxis_title="Diferencia en Unidades Vendidas")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("La gráfica muestra la diferencia de unidades vendidas. Barras positivas indican que el producto se vendió más en los últimos 30 días. Barras negativas, lo contrario.")
