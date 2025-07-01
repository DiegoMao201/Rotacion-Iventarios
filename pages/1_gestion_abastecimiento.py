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
            # ✅ Redondear unidades antes de exportar
            if 'Uds a Enviar' in df.columns:
                df['Uds a Enviar'] = df['Uds a Enviar'].astype(int)
            if 'Uds a Comprar' in df.columns:
                df['Uds a Comprar'] = df['Uds a Comprar'].astype(int)
            
            df.to_excel(writer, index=False, sheet_name=nombre_hoja)
            workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
            header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for i, col in enumerate(df.columns):
                width = max(df[col].astype(str).map(len).max(), len(col)) + 3
                worksheet.set_column(i, i, min(width, 50))
    return output.getvalue()

# --- LÓGICA DE ASIGNACIÓN SECUENCIAL DE TRASLADOS ---
def generar_plan_traslados_inteligente(df_analisis):
    """
    Genera un plan de traslados que asigna desde la tienda con más excedente
    hacia la que tiene más necesidad, de forma secuencial y sin duplicar.
    """
    df_origen = df_analisis[df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = df_analisis[df_analisis['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()

    if df_origen.empty or df_destino.empty:
        return pd.DataFrame()

    plan_final = []
    
    for sku, grupo_destino in df_destino.groupby('SKU'):
        grupo_origen_sku = df_origen[df_origen['SKU'] == sku].copy()
        if grupo_origen_sku.empty:
            continue

        excedentes_dict = pd.Series(grupo_origen_sku['Excedente_Trasladable'].values, index=grupo_origen_sku['Almacen_Nombre']).to_dict()

        for idx, necesidad_row in grupo_destino.iterrows():
            tienda_necesitada = necesidad_row['Almacen_Nombre']
            necesidad_actual = necesidad_row['Necesidad_Total']

            for tienda_origen, excedente_disponible in sorted(excedentes_dict.items(), key=lambda item: item[1], reverse=True):
                if necesidad_actual <= 0: break
                if tienda_origen == tienda_necesitada: continue

                if excedente_disponible > 0:
                    # ✅ Redondear unidades a enteros (no se pueden enviar fracciones)
                    unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                    if unidades_a_enviar < 1: continue

                    info_origen = grupo_origen_sku[grupo_origen_sku['Almacen_Nombre'] == tienda_origen].iloc[0]
                    plan_final.append({
                        'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': info_origen['Marca_Nombre'],
                        'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,
                        'Stock en Origen': info_origen['Stock'], 'Tienda Destino': tienda_necesitada,
                        'Necesidad en Destino': necesidad_row['Necesidad_Total'], 'Uds a Enviar': unidades_a_enviar,
                        'Peso del Traslado (kg)': unidades_a_enviar * necesidad_row['Peso_Articulo'],
                        'Valor del Traslado': unidades_a_enviar * necesidad_row['Costo_Promedio_UND']
                    })
                    necesidad_actual -= unidades_a_enviar
                    excedentes_dict[tienda_origen] -= unidades_a_enviar
    
    if not plan_final: return pd.DataFrame()
    return pd.DataFrame(plan_final).sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])


# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']
    
    MARGEN_ESTIMADO = 1.30 
    if 'Precio_Venta_Estimado' not in df_analisis_completo.columns:
        df_analisis_completo['Precio_Venta_Estimado'] = df_analisis_completo['Costo_Promedio_UND'] * MARGEN_ESTIMADO

    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("Filtros de Gestión")
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = sorted([str(nombre) for nombre in df_analisis_completo['Almacen_Nombre'].unique() if pd.notna(nombre)])
    
    selected_almacen_nombre = st.sidebar.selectbox("Vista General por Tienda (Diagnóstico y Compras):", [opcion_consolidado] + nombres_almacen, key="sb_almacen_abastecimiento")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista_filtros = df_analisis_completo
    else:
        df_vista_filtros = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == selected_almacen_nombre]

    lista_marcas = sorted(df_vista_filtros['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    df_filtered = df_vista_filtros[df_vista_filtros['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()

    # --- PESTAÑAS DE NAVEGACIÓN ---
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
    with tab_diagnostico:
        # (El contenido de esta pestaña no cambia)
        st.subheader("Indicadores Clave de Rendimiento (KPIs)")
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
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric(label="💰 Valor Compra Requerida", value=f"${necesidad_compra_total:,.0f}", help="Costo total de los productos que se sugiere comprar a proveedores.")
        kpi2.metric(label="💸 Ahorro Potencial por Traslados", value=f"${oportunidad_ahorro:,.0f}", help="Valor (a costo) de los productos que puedes conseguir de otras tiendas en lugar de comprar.")
        kpi3.metric(label="📉 Venta Potencial Perdida (30 días)", value=f"${venta_perdida:,.0f}", help=f"Estimación de ingresos no percibidos por productos en quiebre de stock.")
        st.markdown("---")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.write("**Necesidad de Compra por Tienda**")
            df_compras_chart_data = df_analisis_completo[df_analisis_completo['Sugerencia_Compra'] > 0]
            if not df_compras_chart_data.empty:
                df_compras_chart_data['Valor_Compra'] = df_compras_chart_data['Sugerencia_Compra'] * df_compras_chart_data['Costo_Promedio_UND']
                data_chart = df_compras_chart_data.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
                fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Requerida por Tienda")
                st.plotly_chart(fig, use_container_width=True)
            else: st.success("No se requieren compras.")
        with col_g2:
            st.write("**Prioridad de Compra por Categoría**")
            df_compras_chart_data = df_analisis_completo[df_analisis_completo['Sugerencia_Compra'] > 0]
            if not df_compras_chart_data.empty:
                df_compras_chart_data['Valor_Compra'] = df_compras_chart_data['Sugerencia_Compra'] * df_compras_chart_data['Costo_Promedio_UND']
                fig = px.sunburst(df_compras_chart_data, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
                st.plotly_chart(fig, use_container_width=True)
            else: st.success("No hay prioridades de compra.")

    # --- PESTAÑA 2: PLAN DE TRASLADOS ---
    with tab_traslados:
        st.info("Prioridad 1: Mover inventario existente para cubrir necesidades sin comprar. Este plan asigna desde la tienda con más excedente.")
        
        df_plan_maestro = generar_plan_traslados_inteligente(df_analisis_completo)
        df_plan_filtrado = df_plan_maestro.copy()

        # --- ✅ NUEVOS FILTROS DE RUTA ---
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filtros del Plan de Traslados")
        opcion_todas = "Todas"

        lista_origenes = [opcion_todas] + sorted(df_plan_filtrado['Tienda Origen'].unique())
        filtro_origen = st.sidebar.selectbox("Seleccionar Tienda Origen:", lista_origenes)
        if filtro_origen != opcion_todas:
            df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Origen'] == filtro_origen]

        lista_destinos = [opcion_todas] + sorted(df_plan_filtrado['Tienda Destino'].unique())
        filtro_destino = st.sidebar.selectbox("Seleccionar Tienda Destino:", lista_destinos)
        if filtro_destino != opcion_todas:
            df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Destino'] == filtro_destino]

        # Aplicar filtro de marca al final
        if selected_marcas and not df_plan_filtrado.empty:
             df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Marca_Nombre'].isin(selected_marcas)]
        
        # Redondear unidades a enteros en el DataFrame final
        if not df_plan_filtrado.empty:
            df_plan_filtrado['Uds a Enviar'] = df_plan_filtrado['Uds a Enviar'].astype(int)

        excel_traslados = generar_excel(df_plan_filtrado, "Plan de Traslados")
        st.download_button("📥 Descargar Plan de Traslados", excel_traslados, "Plan_de_Traslados.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if df_plan_filtrado.empty: 
            st.success("¡No se sugieren traslados con los filtros actuales!")
        else: 
            st.dataframe(df_plan_filtrado, hide_index=True, use_container_width=True, column_config={"Valor del Traslado": st.column_config.NumberColumn(format="$ %d"), "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")})
            
            st.markdown("---")
            # --- ✅ NUEVOS INDICADORES DE CARGA TOTAL ---
            total_valor_traslado = df_plan_filtrado['Valor del Traslado'].sum()
            total_peso_traslado = df_plan_filtrado['Peso del Traslado (kg)'].sum()
            st.subheader("Resumen de la Carga Filtrada")
            col_kpi1, col_kpi2 = st.columns(2)
            col_kpi1.metric("Valor Total del Traslado", f"${total_valor_traslado:,.0f}")
            col_kpi2.metric("Peso Total del Traslado", f"{total_peso_traslado:,.2f} kg")

    # --- PESTAÑA 3: PLAN DE COMPRAS ---
    with tab_compras:
        st.info("Prioridad 2: Comprar únicamente lo necesario después de haber agotado los traslados internos.")
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            # ✅ Redondear unidades a enteros
            df_plan_compras['Uds a Comprar'] = df_plan_compras['Sugerencia_Compra'].astype(int)
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Peso de la Compra (kg)'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Peso_Articulo']
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Comprar para Tienda'})[['Comprar para Tienda', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Uds a Comprar', 'Peso de la Compra (kg)', 'Valor de la Compra']].sort_values(by=['Valor de la Compra', 'Segmento_ABC'], ascending=[False, True])

        excel_compras = generar_excel(df_plan_compras_final, "Plan de Compras")
        st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if df_plan_compras_final.empty: 
            st.success("¡No se requieren compras con los filtros actuales!")
        else: 
            st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True, column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")})

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
