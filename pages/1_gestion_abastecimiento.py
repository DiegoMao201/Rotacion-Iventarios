import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIONES PARA GENERAR ARCHIVOS EXCEL ---
@st.cache_data
def generar_excel(df, nombre_hoja):
    """Función genérica para crear un archivo Excel con formato."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            df_vacio = pd.DataFrame([{'Notificación': f"No se encontraron datos para '{nombre_hoja}' con los filtros actuales."}])
            df_vacio.to_excel(writer, index=False, sheet_name=nombre_hoja)
            worksheet = writer.sheets[nombre_hoja]
            worksheet.set_column('A:A', 70)
        else:
            df.to_excel(writer, index=False, sheet_name=nombre_hoja)
            workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
            header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for i, col in enumerate(df.columns):
                width = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, min(width, 50))
    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']
    
    # --- Añadir precio de venta estimado para KPIs ---
    MARGEN_ESTIMADO = 1.30 
    df_analisis_completo['Precio_Venta_Estimado'] = df_analisis_completo['Costo_Promedio_UND'] * MARGEN_ESTIMADO

    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("Filtros de Gestión")
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
    map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
    lista_nombres_unicos = sorted([str(nombre) for nombre in nombres_almacen['Almacen_Nombre'].unique() if pd.notna(nombre)])
    lista_seleccion_nombres = [opcion_consolidado] + lista_nombres_unicos
    
    selected_almacen_nombre = st.sidebar.selectbox("Selecciona una Tienda para gestionar:", lista_seleccion_nombres, key="sb_almacen_abastecimiento")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista_filtros = df_analisis_completo
    else:
        codigo_almacen_seleccionado = map_nombre_a_codigo.get(selected_almacen_nombre)
        df_vista_filtros = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]

    lista_marcas = sorted(df_vista_filtros['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    
    df_filtered = df_vista_filtros[df_vista_filtros['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()

    # --- PESTAÑAS DE NAVEGACIÓN ---
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
    with tab_diagnostico:
        st.subheader("Indicadores Clave de Rendimiento (KPIs)")

        # --- CÁLCULO DE KPIs ---
        necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
        
        df_origen_kpi = df_analisis_completo[df_analisis_completo['Excedente_Trasladable'] > 0]
        df_destino_kpi = df_filtered[df_filtered['Necesidad_Total'] > 0]
        oportunidad_ahorro = 0
        if not df_origen_kpi.empty and not df_destino_kpi.empty:
            df_sugerencias_kpi = pd.merge(df_origen_kpi[['SKU', 'Excedente_Trasladable', 'Costo_Promedio_UND']], df_destino_kpi[['SKU', 'Necesidad_Total']], on='SKU')
            df_sugerencias_kpi['Uds_a_Mover'] = np.minimum(df_sugerencias_kpi['Excedente_Trasladable'], df_sugerencias_kpi['Necesidad_Total'])
            oportunidad_ahorro = (df_sugerencias_kpi['Uds_a_Mover'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()

        df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
        venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()

        # --- MOSTRAR KPIs ---
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric(label="💰 Valor Compra Requerida", value=f"${necesidad_compra_total:,.0f}", help="Costo total de los productos que se sugiere comprar a proveedores.")
        kpi2.metric(label="💸 Ahorro Potencial por Traslados", value=f"${oportunidad_ahorro:,.0f}", help="Valor (a costo) de los productos que puedes conseguir de otras tiendas en lugar de comprar.")
        kpi3.metric(label="📉 Venta Potencial Perdida (30 días)", value=f"${venta_perdida:,.0f}", help=f"Estimación de ingresos no percibidos por productos en quiebre de stock, basado en un margen del {int((MARGEN_ESTIMADO-1)*100)}%.")

        st.markdown("---")

        # --- GRÁFICOS INTERACTIVOS ---
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.write("**Necesidad de Compra por Tienda**")
            if necesidad_compra_total > 0:
                df_compras_chart = df_analisis_completo[df_analisis_completo['Sugerencia_Compra'] > 0]
                df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
                data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
                fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Requerida por Tienda")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("No se requieren compras.")

        with col_g2:
            st.write("**Prioridad de Compra por Categoría**")
            if necesidad_compra_total > 0:
                df_compras_chart = df_analisis_completo[df_analisis_completo['Sugerencia_Compra'] > 0]
                df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
                fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("No hay prioridades de compra.")

    # --- PESTAÑA 2: PLAN DE TRASLADOS ---
    with tab_traslados:
        df_origen = df_analisis_completo[df_analisis_completo['Excedente_Trasladable'] > 0].copy()
        df_destino = df_analisis_completo[df_analisis_completo['Necesidad_Total'] > 0].copy()
        df_plan_traslados = pd.DataFrame()

        if not df_origen.empty and not df_destino.empty:
            # ✅ **CORRECCIÓN DEFINITIVA**: Se unen los dataframes completos. Pandas manejará los sufijos.
            df_sugerencias = pd.merge(
                df_origen,
                df_destino,
                on='SKU',
                suffixes=('_Origen', '_Destino')
            )
            df_sugerencias = df_sugerencias[df_sugerencias['Almacen_Nombre_Origen'] != df_sugerencias['Almacen_Nombre_Destino']]

            if selected_almacen_nombre != opcion_consolidado: 
                df_sugerencias = df_sugerencias[df_sugerencias['Almacen_Nombre_Destino'] == selected_almacen_nombre]
            
            if selected_marcas:
                # Usamos la columna de marca del origen para el filtro
                df_sugerencias = df_sugerencias[df_sugerencias['Marca_Nombre_Origen'].isin(selected_marcas)]

            if not df_sugerencias.empty:
                # Se usan los nombres con sufijo correctos que Pandas crea automáticamente
                df_sugerencias['Uds a Enviar'] = np.minimum(df_sugerencias['Excedente_Trasladable_Origen'], df_sugerencias['Necesidad_Total_Destino']).astype(int)
                df_sugerencias['Valor del Traslado'] = df_sugerencias['Uds a Enviar'] * df_sugerencias['Costo_Promedio_UND_Origen']
                df_sugerencias['Peso del Traslado (kg)'] = df_sugerencias['Uds a Enviar'] * df_sugerencias['Peso_Articulo_Origen']
                
                df_plan_traslados = df_sugerencias.rename(columns={
                    'Descripcion_Origen': 'Descripcion',
                    'Segmento_ABC_Origen': 'Segmento_ABC',
                    'Almacen_Nombre_Origen': 'Tienda Origen', 
                    'Stock_Origen': 'Stock en Origen',
                    'Almacen_Nombre_Destino': 'Tienda Destino', 
                    'Necesidad_Total_Destino': 'Necesidad en Destino'
                })[[
                    'SKU', 'Descripcion', 'Segmento_ABC', 'Tienda Origen', 'Stock en Origen', 
                    'Tienda Destino', 'Necesidad en Destino', 'Uds a Enviar', 'Peso del Traslado (kg)', 'Valor del Traslado'
                ]].sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])
        
        st.info("Prioridad 1: Mover inventario existente para cubrir necesidades sin comprar.")
        excel_traslados = generar_excel(df_plan_traslados, "Plan de Traslados")
        st.download_button("📥 Descargar Plan de Traslados", excel_traslados, "Plan_de_Traslados.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if df_plan_traslados.empty: 
            st.success("¡No se sugieren traslados con los filtros actuales!")
        else: 
            st.dataframe(df_plan_traslados, hide_index=True, use_container_width=True, column_config={"Valor del Traslado": st.column_config.NumberColumn(format="$ %d"), "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")})

    # --- PESTAÑA 3: PLAN DE COMPRAS ---
    with tab_compras:
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Sugerencia_Compra'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Peso de la Compra (kg)'] = df_plan_compras['Sugerencia_Compra'] * df_plan_compras['Peso_Articulo']
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Comprar para Tienda', 'Sugerencia_Compra': 'Uds a Comprar'})[['Comprar para Tienda', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Uds a Comprar', 'Peso de la Compra (kg)', 'Valor de la Compra']].sort_values(by=['Valor de la Compra', 'Segmento_ABC'], ascending=[False, True])

        st.info("Prioridad 2: Comprar únicamente lo necesario después de haber agotado los traslados internos.")
        excel_compras = generar_excel(df_plan_compras_final, "Plan de Compras")
        st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if df_plan_compras_final.empty: 
            st.success("¡No se requieren compras con los filtros actuales!")
        else: 
            st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True, column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")})

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
