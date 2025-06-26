import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import datetime

st.set_page_config(page_title="Análisis de Tendencias", layout="wide", page_icon="📈")
st.title("📈 Análisis de Tendencias y Estacionalidad")
st.markdown("Identifica los productos que están acelerando o desacelerando sus ventas para tomar acciones proactivas.")

def parse_historial_para_analisis(historial_str, dias_periodo=60):
    if not isinstance(historial_str, str) or historial_str == '':
        return pd.DataFrame(columns=['Fecha', 'Unidades'])
    records = []
    ventas = historial_str.split(',')
    for venta in ventas:
        try:
            fecha_str, cantidad_str = venta.split(':')
            records.append({'Fecha': datetime.strptime(fecha_str, '%Y-%m-%d').date(), 'Unidades': float(cantidad_str)})
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(records)

if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
        # --- CORRECCIÓN: Usar 'Almacen' (con camel case) ---
        nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
        map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
        lista_seleccion_nombres = [opcion_consolidado] + sorted(nombres_almacen['Almacen_Nombre'].unique())
        selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres, key="sb_tendencias")
        
        if selected_almacen_nombre == opcion_consolidado:
            df_vista = df_analisis_completo
        else:
            codigo_almacen_seleccionado = map_nombre_a_codigo[selected_almacen_nombre]
            df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]

        lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_tendencias")
        
        if not selected_marcas:
            df_filtered = df_vista.copy()
        else:
            df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)].copy()
        
        st.header(f"Análisis de Tendencias para: {selected_almacen_nombre}", divider='blue')

        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🚀 Productos con Mayor Crecimiento")
            st.info("Estos productos están acelerando sus ventas. Considera aumentar su stock de seguridad.")
            top_crecimiento = df_filtered.sort_values(by='Tendencia_Ventas', ascending=False).head(10)
            st.dataframe(top_crecimiento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']], 
                         column_config={"Tendencia_Ventas": st.column_config.NumberColumn(format="%.2f")},
                         hide_index=True, use_container_width=True)

        with col2:
            st.subheader("🐌 Productos con Mayor Decremento")
            st.warning("Las ventas de estos productos están desacelerando. Evita reabastecer en exceso.")
            top_decremento = df_filtered[df_filtered['Tendencia_Ventas'] < 0].sort_values(by='Tendencia_Ventas', ascending=True).head(10)
            st.dataframe(top_decremento[['SKU', 'Descripcion', 'Marca_Nombre', 'Tendencia_Ventas']], 
                         column_config={"Tendencia_Ventas": st.column_config.NumberColumn(format="%.2f")},
                         hide_index=True, use_container_width=True)

        st.markdown("---")
        st.subheader("🔍 Análisis de Estacionalidad Reciente")
        
        productos_estacionales = df_filtered[df_filtered['Estacionalidad_Reciente'] != 0].copy()
        productos_estacionales['Tipo_Estacionalidad'] = np.where(productos_estacionales['Estacionalidad_Reciente'] > 0, 'Crecimiento', 'Decremento')
        
        fig = px.bar(productos_estacionales.sort_values('Estacionalidad_Reciente', ascending=False), 
                     x='SKU', y='Estacionalidad_Reciente', color='Tipo_Estacionalidad',
                     title="Comparación de Ventas: Últimos 30 días vs. 30 días Anteriores",
                     labels={'Estacionalidad_Reciente': 'Diferencia de Unidades Vendidas', 'SKU': 'Producto'},
                     color_discrete_map={'Crecimiento':'green', 'Decremento':'red'})
        st.plotly_chart(fig, use_container_width=True)
        st.info("La gráfica muestra la diferencia de unidades vendidas. Barras positivas indican que el producto se vendió más en los últimos 30 días. Barras negativas, lo contrario.")
        
else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Resumen Ejecutivo de Inventario' primero.")
