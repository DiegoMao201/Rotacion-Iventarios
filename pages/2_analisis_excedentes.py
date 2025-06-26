import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go

st.set_page_config(page_title="Análisis de Excedentes", layout="wide", page_icon="📉")
st.title("📉 Análisis de Excedentes y Baja Rotación")
st.markdown("Identifica y gestiona el inventario que está inmovilizando capital en tu tienda.")

if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
        lista_almacenes = sorted(df_analisis_completo['Almacen'].unique())
        lista_seleccion = [opcion_consolidado] + lista_almacenes
        selected_almacen = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion, key="sb_almacen_excedentes")
        
        if selected_almacen == opcion_consolidado:
            df_vista = df_analisis_completo
        else:
            df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == selected_almacen]

        lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_excedentes")
        
        if not selected_marcas:
            df_filtered = df_vista
        else:
            df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]

        df_excedentes = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])].copy()
        df_excedentes['Dias_Inventario'] = (df_excedentes['Stock'] / df_excedentes['Demanda_Diaria_Promedio']).replace([np.inf, -np.inf], 9999)

        st.header(f"Análisis de Excedentes para: {selected_almacen}", divider='blue')
        valor_excedente = df_excedentes['Valor_Inventario'].sum()
        valor_total = df_filtered['Valor_Inventario'].sum()
        porc_excedente = (valor_excedente / valor_total * 100) if valor_total > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Total en Excedente", f"${valor_excedente:,.0f}")
        col2.metric("📦 SKUs en esta categoría", f"{df_excedentes['SKU'].nunique()}")
        col3.metric("% del Inventario", f"{porc_excedente:.1f}%")

        st.markdown("---")

        # --- MEJORA: Gráfico de Pareto ---
        st.subheader("Análisis de Pareto: ¿Dónde se concentra el problema?")
        if not df_excedentes.empty:
            pareto_data = df_excedentes.groupby('SKU').agg(
                Valor_Inventario=('Valor_Inventario', 'sum'),
                Marca_Nombre=('Marca_Nombre', 'first')
            ).sort_values(by='Valor_Inventario', ascending=False).reset_index()

            pareto_data['Porcentaje_Acumulado'] = pareto_data['Valor_Inventario'].cumsum() / pareto_data['Valor_Inventario'].sum() * 100
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=pareto_data['SKU'], y=pareto_data['Valor_Inventario'], name='Valor del Excedente por SKU', marker_color='#7792E3'), secondary_y=False)
            fig.add_trace(go.Scatter(x=pareto_data['SKU'], y=pareto_data['Porcentaje_Acumulado'], name='Porcentaje Acumulado', mode='lines+markers', line_color='#FF4B4B'), secondary_y=True)
            
            fig.update_layout(title_text="Principio 80/20 del Inventario Excedente", xaxis_tickangle=-45)
            fig.update_xaxes(title_text="SKUs (Ordenados por Valor de Excedente)")
            fig.update_yaxes(title_text="<b>Valor del Excedente ($)</b>", secondary_y=False)
            fig.update_yaxes(title_text="<b>Porcentaje Acumulado (%)</b>", secondary_y=True, range=[0, 105])
            st.plotly_chart(fig, use_container_width=True)
            st.info("Este gráfico muestra cómo unos pocos SKUs (a la izquierda) son responsables de la mayor parte del valor de tu inventario excedente. ¡Atácalos primero!")
        else:
            st.success("No hay inventario excedente para analizar con los filtros actuales.")

        st.markdown("---")
        st.subheader("Detalle de Productos para Liquidar")
        st.dataframe(df_excedentes.sort_values('Valor_Inventario', ascending=False), column_config={"Valor_Inventario": st.column_config.NumberColumn("Valor Inmovilizado", format="$ %d"),"Dias_Inventario": st.column_config.ProgressColumn("Días de Inventario",min_value=0,max_value=365), "Marca_Nombre": "Marca"}, hide_index=True)
else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Resumen Ejecutivo de Inventario' primero.")
