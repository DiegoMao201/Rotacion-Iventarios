import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import datetime

st.set_page_config(page_title="Análisis de Marca", layout="wide", page_icon="📊")
st.title("📊 Análisis de Salud por Marca")
st.markdown("Selecciona una marca para analizar su rendimiento y estado de inventario en profundidad.")

# Función para parsear el historial y devolver un DataFrame para el gráfico
def parse_history_to_df(historial_str):
    if not isinstance(historial_str, str) or historial_str == '':
        return pd.DataFrame(columns=['Fecha', 'Unidades'])
    
    records = []
    ventas = historial_str.split(',')
    for venta in ventas:
        try:
            fecha_str, cantidad_str = venta.split(':')
            records.append({'Fecha': datetime.strptime(fecha_str, '%Y-%m-%d'), 'Unidades': float(cantidad_str)})
        except (ValueError, IndexError):
            continue
    
    return pd.DataFrame(records)


if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        lista_marcas = sorted(df_analisis_completo['Marca_Nombre'].unique())
        selected_marca = st.selectbox("Selecciona una Marca para Analizar:", lista_marcas)

        st.header(f"Análisis Detallado de: {selected_marca}", divider='blue')

        df_marca = df_analisis_completo[df_analisis_completo['Marca_Nombre'] == selected_marca].copy()

        valor_inv_marca = df_marca['Valor_Inventario'].sum()
        unidades_stock_marca = df_marca['Stock'].sum()
        unidades_venta_marca = df_marca['Ventas_60_Dias'].sum()
        rotacion_marca = unidades_venta_marca / unidades_stock_marca if unidades_stock_marca > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Inventario de la Marca", f"${valor_inv_marca:,.0f}")
        col2.metric("📦 Unidades en Stock", f"{unidades_stock_marca:,.0f}")
        col3.metric("🔄 Rotación de la Marca (60 Días)", f"{rotacion_marca:.2f}")

        st.markdown("---")
        
        # --- MEJORA: Sección de Análisis por Producto Individual ---
        st.subheader("Análisis de Tendencia por Producto")
        
        # Agrupamos por SKU para el selector, mostrando el stock total
        sku_info = df_marca.groupby('SKU').agg(
            Descripcion=('Descripcion', 'first'),
            Stock_Total=('Stock', 'sum')
        ).reset_index()
        sku_info['Selector_SKU'] = sku_info['SKU'] + " - " + sku_info['Descripcion'] + " (" + sku_info['Stock_Total'].astype(int).astype(str) + " u.)"

        selected_sku_info = st.selectbox("Selecciona un Producto para ver su tendencia:", sku_info['Selector_SKU'])
        
        if selected_sku_info:
            selected_sku = selected_sku_info.split(' - ')[0]
            
            # Sumamos el historial de ventas de un SKU a través de todos los almacenes
            historial_agregado = df_marca[df_marca['SKU'] == selected_sku]['Historial_Ventas'].dropna().str.cat(sep=',')
            
            df_tendencia = parse_history_to_df(historial_agregado)

            if not df_tendencia.empty:
                # Agrupamos por si hay ventas el mismo día en diferentes almacenes
                df_tendencia_diaria = df_tendencia.groupby('Fecha')['Unidades'].sum().reset_index()
                
                fig = px.bar(df_tendencia_diaria, x='Fecha', y='Unidades', 
                             title=f"Tendencia de Ventas Diarias para SKU: {selected_sku}",
                             labels={'Fecha': 'Fecha de Venta', 'Unidades': 'Unidades Vendidas'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Este producto no registra ventas en los últimos 60 días.")

        st.markdown("---")
        st.subheader("Detalle Completo de Productos de la Marca")
        st.dataframe(df_marca, hide_index=True)

else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Resumen Ejecutivo de Inventario' primero.")
