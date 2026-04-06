import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import io

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Ferreinox | Marcas", layout="wide", page_icon="🔴")

# --- IDENTIDAD VISUAL FERREINOX ---
try:
    from utils import aplicar_estilo_ferreinox, mostrar_footer_ferreinox
    aplicar_estilo_ferreinox()
except ImportError:
    pass

st.title("🎯 Análisis Estratégico de Marca y Categoría")
st.markdown("Una herramienta poderosa para evaluar el rendimiento y tomar decisiones informadas con tus proveedores.")

# --- 1. FUNCIÓN PARA DESCARGAR EXCEL ---
@st.cache_data
def convert_df_to_excel(df):
    """Convierte un DataFrame a un archivo Excel en memoria para descarga."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Analisis_Detallado')
        # Formato básico para legibilidad
        worksheet = writer.sheets['Analisis_Detallado']
        worksheet.autofit()
    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' not in st.session_state or st.session_state['df_analisis'].empty:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal primero.")
    st.page_link("Tablero Rotacion.py", label="Ir a la Página Principal", icon="🏠")
else:
    df_analisis_completo = st.session_state['df_analisis']
    
    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("⚙️ Filtros de Análisis")
    
    # Filtro para elegir entre Marca o Departamento
    tipo_analisis = st.sidebar.radio(
        "Selecciona el tipo de análisis:",
        ('Por Marca', 'Por Categoría/Departamento'),
        key="radio_tipo_analisis"
    )

    # Lógica para filtrar por la selección del usuario
    if tipo_analisis == 'Por Marca':
        columna_filtro = 'Marca_Nombre'
        lista_items = sorted([str(item) for item in df_analisis_completo[columna_filtro].dropna().unique()])
        selected_item = st.sidebar.selectbox("Selecciona una Marca:", lista_items)
    else: # Por Categoría/Departamento
        columna_filtro = 'Departamento'
        lista_items = sorted([str(item) for item in df_analisis_completo[columna_filtro].dropna().unique()])
        selected_item = st.sidebar.selectbox("Selecciona una Categoría:", lista_items)

    # Filtro de Almacén/Tienda
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    # CORRECCIÓN DEL ERROR: Convertir todos los nombres a string antes de ordenar
    lista_almacenes = sorted([str(nombre) for nombre in df_analisis_completo['Almacen_Nombre'].dropna().unique()])
    lista_seleccion_almacen = [opcion_consolidado] + lista_almacenes
    selected_almacen = st.sidebar.selectbox("Selecciona la Vista de Tienda:", lista_seleccion_almacen)

    st.header(f"Análisis para: {selected_item}", divider='rainbow')
    st.caption(f"Mostrando datos para: **{selected_almacen}**")

    # --- Aplicación de Filtros ---
    # 1. Filtrar por Marca/Categoría seleccionada
    df_item_filtrado = df_analisis_completo[df_analisis_completo[columna_filtro] == selected_item].copy()
    
    # 2. Filtrar por tienda (si no es consolidado)
    if selected_almacen != opcion_consolidado:
        df_vista = df_item_filtrado[df_item_filtrado['Almacen_Nombre'] == selected_almacen].copy()
    else:
        df_vista = df_item_filtrado.copy()

    # 3. ENFOCARSE SOLO EN PRODUCTOS CON STOCK
    df_con_stock = df_vista[df_vista['Stock'] > 0].copy()

    if df_con_stock.empty:
        st.warning(f"No se encontró inventario activo para '{selected_item}' en '{selected_almacen}'.")
    else:
        # --- Pestañas de Análisis Detallado ---
        tab1, tab2, tab3 = st.tabs(["📊 Visión General", "🏪 Análisis por Tienda", "📋 Detalle de Productos y Acciones"])

        with tab1:
            st.subheader(f"Salud de la Marca/Categoría: {selected_item}")
            
            # --- KPIs Principales ---
            valor_inv_total_general = df_analisis_completo['Valor_Inventario'].sum()
            valor_inv_item = df_con_stock['Valor_Inventario'].sum()
            participacion_inv = (valor_inv_item / valor_inv_total_general * 100) if valor_inv_total_general > 0 else 0
            skus_activos = df_con_stock['SKU'].nunique()
            df_excedente_item = df_con_stock[df_con_stock['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]
            valor_excedente_item = df_excedente_item['Valor_Inventario'].sum()
            skus_quiebre_item = df_analisis_completo[
                (df_analisis_completo[columna_filtro] == selected_item) & 
                (df_analisis_completo['Estado_Inventario'] == 'Quiebre de Stock')
            ]['SKU'].nunique()

            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            kpi_col1.metric("💰 Valor Inventario Actual", f"${valor_inv_item:,.0f}")
            kpi_col2.metric("% Participación en Inventario Total", f"{participacion_inv:.1f}%")
            kpi_col3.metric("📦 SKUs Activos (con stock)", f"{skus_activos}")
            
            kpi_col4, kpi_col5, _ = st.columns(3)
            kpi_col4.metric("📉 Valor en Excedente", f"${valor_excedente_item:,.0f}")
            kpi_col5.metric("🚨 SKUs en Quiebre de Stock", f"{skus_quiebre_item}")

            st.markdown("---")
            
            # --- Gráficos de Visión General ---
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.markdown("##### Distribución del Inventario por Estado")
                estado_counts = df_con_stock['Estado_Inventario'].value_counts()
                fig_donut = px.pie(
                    values=estado_counts.values, 
                    names=estado_counts.index, 
                    title="Proporción por Valor de Inventario",
                    hole=.4,
                    color_discrete_map={
                        'Normal': 'green', 'Bajo Stock (Riesgo)': 'orange', 
                        'Excedente': 'red', 'Baja Rotación / Obsoleto': 'darkred'
                    }
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            with col_g2:
                st.markdown("##### Top 5 Productos por Valor de Inventario")
                top_5_prods = df_con_stock.groupby('SKU')['Valor_Inventario'].sum().nlargest(5).reset_index()
                fig_bar = px.bar(
                    top_5_prods, x='SKU', y='Valor_Inventario',
                    title="Productos más valiosos en stock",
                    text_auto='.2s',
                    labels={'Valor_Inventario': 'Valor Inventario ($)', 'SKU': 'Referencia'}
                )
                fig_bar.update_traces(textangle=0, textposition="outside")
                st.plotly_chart(fig_bar, use_container_width=True)

        with tab2:
            st.subheader("Rendimiento Comparativo por Tienda")
            st.info("Analiza en qué tiendas la marca o categoría tiene mejor desempeño, mayor inversión o más problemas de quiebre.")

            # Agrupar datos a nivel de tienda para la marca/categoría seleccionada
            df_tienda_summary = df_item_filtrado.groupby('Almacen_Nombre').agg(
                Valor_Inventario=('Valor_Inventario', 'sum'),
                Unidades_Stock=('Stock', 'sum')
            ).reset_index()

            # Calcular quiebres por tienda para esta marca/categoría
            quiebres_por_tienda = df_item_filtrado[df_item_filtrado['Estado_Inventario'] == 'Quiebre de Stock'].groupby('Almacen_Nombre')['SKU'].nunique().rename('SKUs_en_Quiebre')
            df_tienda_summary = df_tienda_summary.merge(quiebres_por_tienda, on='Almacen_Nombre', how='left').fillna(0)

            st.dataframe(
                df_tienda_summary.sort_values('Valor_Inventario', ascending=False),
                column_config={
                    "Almacen_Nombre": "Tienda",
                    "Valor_Inventario": st.column_config.NumberColumn("Valor Inventario ($)", format="$ %d"),
                    "Unidades_Stock": "Unidades Totales",
                    "SKUs_en_Quiebre": "Productos en Quiebre"
                },
                use_container_width=True, hide_index=True
            )

        with tab3:
            st.subheader("Detalle de Productos y Planes de Acción")
            
            # --- Plan de Acción Sugerido ---
            conditions = [
                (df_con_stock['Estado_Inventario'] == 'Quiebre de Stock'),
                (df_con_stock['Estado_Inventario'] == 'Bajo Stock (Riesgo)'),
                (df_con_stock['Estado_Inventario'] == 'Excedente'),
                (df_con_stock['Estado_Inventario'] == 'Baja Rotación / Obsoleto')
            ]
            choices = [
                'ABASTECIMIENTO URGENTE', 'REVISAR PUNTO DE REORDEN',
                'PLAN DE LIQUIDACIÓN', 'LIQUIDAR / DESCONTINUAR'
            ]
            df_con_stock['Plan_Accion'] = np.select(conditions, choices, default='MONITOREAR')

            df_display = df_con_stock[[
                'SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Valor_Inventario', 'Estado_Inventario', 'Plan_Accion'
            ]].sort_values('Valor_Inventario', ascending=False)

            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # Botón de descarga
            excel_data = convert_df_to_excel(df_display)
            st.download_button(
                label="📥 Descargar Detalle en Excel",
                data=excel_data,
                file_name=f"analisis_{selected_item.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# --- FOOTER ---
try:
    mostrar_footer_ferreinox()
except NameError:
    pass
