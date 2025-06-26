import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np

st.set_page_config(page_title="Análisis de Excedentes", layout="wide", page_icon="📉")

st.title("📉 Análisis de Excedentes y Baja Rotación")
st.markdown("Identifica y gestiona el inventario que está inmovilizando capital en tu tienda.")

if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        lista_almacenes = sorted(df_analisis_completo['Almacen'].unique())
        selected_almacen = st.sidebar.selectbox("Selecciona tu Almacén:", lista_almacenes, key="sb_almacen_excedentes")
        
        df_tienda = df_analisis_completo[df_analisis_completo['Almacen'] == selected_almacen]
        
        df_excedentes = df_tienda[df_tienda['Accion_Requerida'].str.contains('LIQUIDAR')].copy()
        df_excedentes['Dias_Inventario'] = (df_excedentes['Stock'] / df_excedentes['Demanda_Diaria_Promedio']).replace([np.inf, -np.inf], 9999)

        valor_excedente = df_excedentes['Valor_Inventario'].sum()
        valor_total = df_tienda['Valor_Inventario'].sum()
        porc_excedente = (valor_excedente / valor_total * 100) if valor_total > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Total en Excedente", f"${valor_excedente:,.0f}")
        col2.metric("📦 SKUs en esta categoría", f"{df_excedentes['SKU'].nunique()}")
        col3.metric("% del Inventario", f"{porc_excedente:.1f}%")

        st.markdown("---")

        col_viz, col_tabla = st.columns([1, 2])
        with col_viz:
            st.subheader("Excedente por Departamento")
            df_excedente_dpto = df_excedentes.groupby('Departamento')['Valor_Inventario'].sum().nlargest(10).reset_index()
            fig = px.bar(df_excedente_dpto, x='Valor_Inventario', y='Departamento', orientation='h', text_auto='.2s', title="Top 10 Departamentos")
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig, use_container_width=True)
        with col_tabla:
            st.subheader("Detalle de Productos para Liquidar")
            st.dataframe(
                df_excedentes.sort_values('Valor_Inventario', ascending=False),
                column_config={
                    "Valor_Inventario": st.column_config.NumberColumn("Valor Inmovilizado", format="$ %d"),
                    "Dias_Inventario": st.column_config.ProgressColumn("Días de Inventario", min_value=0, max_value=365, format="%d días"),
                    "Stock": st.column_config.NumberColumn("Unidades"),
                    "Accion_Requerida": st.column_config.TextColumn("Acción Sugerida")
                },
                hide_index=True,
                use_container_width=True,
                height=400
            )
    else:
        st.warning("No se pudo realizar el análisis. Datos no disponibles.")
else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Plan de Acción de Inventario' primero.")
