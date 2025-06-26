import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np

st.set_page_config(page_title="Análisis de Marca", layout="wide", page_icon="📊")
st.title("📊 Análisis de Salud por Marca")
st.markdown("Selecciona una marca para analizar su rendimiento y estado de inventario en profundidad.")

if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        lista_marcas = sorted(df_analisis_completo['Marca_Nombre'].unique())
        selected_marca = st.selectbox("Selecciona una Marca para Analizar:", lista_marcas)

        st.header(f"Análisis Detallado de: {selected_marca}", divider='blue')

        df_marca = df_analisis_completo[df_analisis_completo['Marca_Nombre'] == selected_marca]

        # KPIs para la marca seleccionada
        valor_inv_marca = df_marca['Valor_Inventario'].sum()
        unidades_stock_marca = df_marca['Stock'].sum()
        unidades_venta_marca = df_marca['Ventas_60_Dias'].sum()
        rotacion_marca = unidades_venta_marca / unidades_stock_marca if unidades_stock_marca > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Inventario de la Marca", f"${valor_inv_marca:,.0f}")
        col2.metric("📦 Unidades en Stock", f"{unidades_stock_marca:,.0f}")
        col3.metric("🔄 Rotación de la Marca (60 Días)", f"{rotacion_marca:.2f}")

        st.markdown("---")
        
        col_viz1, col_viz2 = st.columns(2)
        
        with col_viz1:
            st.subheader("Estado del Inventario de la Marca")
            df_dist = df_marca.groupby('Estado_Inventario')['Valor_Inventario'].sum().reset_index()
            fig = px.pie(df_dist, values='Valor_Inventario', names='Estado_Inventario', title='Distribución por Estado',
                         color_discrete_map={'Excedente':'#FF7F0E', 'Quiebre de Stock':'#D62728', 'Bajo Stock (Riesgo)':'#FFD700', 'Normal':'#2CA02C', 'Baja Rotación / Obsoleto': '#8C564B'})
            st.plotly_chart(fig, use_container_width=True)

        with col_viz2:
            st.subheader("Top 5 SKUs con Mayor Stock")
            top_stock = df_marca.groupby('SKU')['Stock'].sum().nlargest(5).reset_index()
            fig2 = px.bar(top_stock, x='SKU', y='Stock', title='Top 5 Productos por Unidades en Stock', text_auto=True)
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")
        st.subheader("Detalle Completo de Productos de la Marca")
        st.dataframe(df_marca, hide_index=True)

else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Resumen Ejecutivo de Inventario' primero.")
