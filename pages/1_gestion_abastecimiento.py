import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIONES AUXILIARES ---
@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    """Crea un archivo Excel dinámico con formato."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No se encontraron datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70)
            return output.getvalue()

        # Asegurar que las unidades son enteros
        for col in ['Uds a Enviar', 'Uds a Comprar']:
            if col in df.columns:
                df[col] = df[col].astype(int)

        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook = writer.book
        worksheet = writer.sheets[nombre_hoja]

        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})

        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(width, 45))
            
    return output.getvalue()

def generar_plan_traslados_inteligente(df_analisis_maestro):
    """Genera un plan de traslados óptimo usando el inventario de todas las tiendas."""
    if df_analisis_maestro is None or df_analisis_maestro.empty:
        return pd.DataFrame()
        
    df_origen = df_analisis_maestro[df_analisis_maestro['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = df_analisis_maestro[df_analisis_maestro['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()
    
    if df_origen.empty or df_destino.empty:
        return pd.DataFrame()

    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()

    for idx, necesidad_row in df_destino.iterrows():
        sku = necesidad_row['SKU']
        tienda_necesitada = necesidad_row['Almacen_Nombre']
        necesidad_actual = necesidad_row['Necesidad_Total']

        if necesidad_actual <= 0:
            continue

        posibles_origenes = df_origen[df_origen['SKU'] == sku]

        for _, origen_row in posibles_origenes.iterrows():
            tienda_origen = origen_row['Almacen_Nombre']
            if tienda_origen == tienda_necesitada:
                continue

            excedente_disponible = excedentes_mutables.get((sku, tienda_origen), 0)
            
            if excedente_disponible > 0 and necesidad_actual > 0:
                unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                if unidades_a_enviar < 1:
                    continue
                
                plan_final.append({
                    'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': origen_row['Marca_Nombre'],
                    'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,
                    'Stock en Origen': origen_row['Stock'], 'Tienda Destino': tienda_necesitada,
                    'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],
                    'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row['Peso_Articulo'],
                    'Valor Individual': necesidad_row['Costo_Promedio_UND']
                })
                
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
    
    if not plan_final:
        return pd.DataFrame()
        
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])


# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
# 🎯 CORRECCIÓN CLAVE: Usar 'df_analisis_maestro' para cálculos globales y 'df_analisis' para la vista del usuario
if 'df_analisis_maestro' in st.session_state:
    df_maestro = st.session_state['df_analisis_maestro']
    df_vista_usuario = st.session_state.get('df_analisis', df_maestro) # Usar la vista del usuario o el maestro como fallback

    MARGEN_ESTIMADO = 1.30 
    if 'Precio_Venta_Estimado' not in df_maestro.columns:
        df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * MARGEN_ESTIMADO

    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("Filtros de Gestión")
    
    # El selectbox de tiendas debe mostrar todas las tiendas si es gerente, o solo la suya si es de tienda.
    if st.session_state.get('user_role') == 'gerente':
        nombres_almacen_opciones = sorted([str(n) for n in df_maestro['Almacen_Nombre'].unique() if pd.notna(n)])
    else:
        nombres_almacen_opciones = [st.session_state.get('almacen_nombre')]

    selected_almacen_nombre = st.sidebar.selectbox(
        "Seleccionar Tienda para Gestionar:", 
        nombres_almacen_opciones, 
        key="sb_almacen_abastecimiento"
    )
    
    # df_vista_tienda es el dataframe enfocado en la tienda seleccionada EN ESTA PÁGINA.
    df_vista_tienda = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]
    
    lista_marcas = sorted(df_vista_tienda['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    
    # El DataFrame final para mostrar en la UI se filtra por tienda y por marca.
    df_filtered = df_vista_tienda[df_vista_tienda['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()
    
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
    with tab_diagnostico:
        st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
        
        # --- 🎯 LÓGICA DE KPI CORREGIDA ---
        # 1. Necesidad de Compra: Se calcula sobre los datos ya filtrados para la tienda actual.
        necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()

        # 2. Oportunidad de Ahorro: Cruza la NECESIDAD de la tienda actual con el EXCEDENTE de TODAS las tiendas.
        df_origen_kpi = df_maestro[df_maestro['Excedente_Trasladable'] > 0] # Origen: Excedentes en TODO el inventario
        df_destino_kpi = df_filtered[df_filtered['Necesidad_Total'] > 0]      # Destino: Necesidades en la tienda FILTRADA
        
        oportunidad_ahorro = 0
        if not df_origen_kpi.empty and not df_destino_kpi.empty:
            # Unimos por SKU para encontrar coincidencias
            df_sugerencias_kpi = pd.merge(
                df_origen_kpi.groupby('SKU').agg(
                    Total_Excedente_Global=('Excedente_Trasladable', 'sum'),
                    Costo_Promedio_UND=('Costo_Promedio_UND', 'mean') # Usamos el costo promedio
                ),
                df_destino_kpi.groupby('SKU').agg(
                    Total_Necesidad_Tienda=('Necesidad_Total', 'sum')
                ),
                on='SKU',
                how='inner'
            )
            df_sugerencias_kpi['Ahorro_Potencial'] = np.minimum(df_sugerencias_kpi['Total_Excedente_Global'], df_sugerencias_kpi['Total_Necesidad_Tienda'])
            oportunidad_ahorro = (df_sugerencias_kpi['Ahorro_Potencial'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()

        # 3. Venta Perdida: Se calcula sobre los quiebres de la tienda actual.
        df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
        venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
        
        st.markdown("##### Indicadores Clave de Rendimiento (KPIs)")
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric(label="💰 Valor Compra Requerida", value=f"${necesidad_compra_total:,.0f}")
        kpi2.metric(label="💸 Ahorro por Traslados", value=f"${oportunidad_ahorro:,.0f}")
        kpi3.metric(label="📉 Venta Potencial Perdida", value=f"${venta_perdida:,.0f}")
        
        st.markdown("---")
        st.markdown("##### Análisis y Recomendaciones Clave")
        with st.container(border=True):
            if venta_perdida > 0: st.markdown(f"**🚨 Alerta de Ventas en Riesgo:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** en 30 días por **{len(df_quiebre)}** productos en quiebre. Es **crítico** reabastecerlos.")
            if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad de Ahorro:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña **'Plan de Traslados'** como tu **primera opción** antes de comprar.")
            if necesidad_compra_total > 0:
                df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
                df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
                if not df_compras_prioridad.empty:
                    top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                    st.markdown(f"**🎯 Enfoque de Compra:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**. Asegura su disponibilidad.")
            if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0: st.markdown("✅ **¡Inventario Optimizado!** No se detectan necesidades urgentes con los filtros actuales.")
        
        st.markdown("---")
        st.markdown("##### Visualización de Necesidades")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.write("**Inversión Requerida por Tienda (General)**")
            df_compras_chart_data = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
            if not df_compras_chart_data.empty:
                df_compras_chart_data['Valor_Compra'] = df_compras_chart_data['Sugerencia_Compra'] * df_compras_chart_data['Costo_Promedio_UND']
                data_chart = df_compras_chart_data.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
                fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Total Requerida por Tienda")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("No se requieren compras en ninguna tienda.")
        with col_g2:
            st.write("**Prioridad de Compra (General)**")
            df_compras_chart_data = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
            if not df_compras_chart_data.empty:
                df_compras_chart_data['Valor_Compra'] = df_compras_chart_data['Sugerencia_Compra'] * df_compras_chart_data['Costo_Promedio_UND']
                fig = px.sunburst(df_compras_chart_data, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("No hay prioridades de compra.")

    # --- PESTAÑA 2: PLAN DE TRASLADOS ---
    with tab_traslados:
        # El plan de traslados se genera usando SIEMPRE el dataframe maestro
        df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)
        
        st.info(f"Mostrando todos los traslados (envíos y recepciones) que involucran a **{selected_almacen_nombre}**.")
        if not df_plan_maestro.empty:
            df_plan_tienda = df_plan_maestro[
                (df_plan_maestro['Tienda Origen'] == selected_almacen_nombre) | 
                (df_plan_maestro['Tienda Destino'] == selected_almacen_nombre)
            ].copy()
        else:
            df_plan_tienda = pd.DataFrame()
        
        df_plan_filtrado = df_plan_tienda.copy() # Copia para aplicar filtros de la sidebar
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filtros del Plan de Traslados")
        opcion_todas = "Todas"
        
        if not df_plan_filtrado.empty:
            lista_origenes = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Origen'].unique() if pd.notna(x)])
            filtro_origen = st.sidebar.selectbox("Filtrar Tienda Origen:", lista_origenes)
            if filtro_origen != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Origen'] == filtro_origen]
            
            lista_destinos = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Destino'].unique() if pd.notna(x)])
            filtro_destino = st.sidebar.selectbox("Filtrar Tienda Destino:", lista_destinos)
            if filtro_destino != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Destino'] == filtro_destino]
            
            if selected_marcas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Marca_Nombre'].isin(selected_marcas)]
        else:
            st.sidebar.selectbox("Filtrar Tienda Origen:", [opcion_todas], disabled=True)
            st.sidebar.selectbox("Filtrar Tienda Destino:", [opcion_todas], disabled=True)
            
        df_plan_display = df_plan_filtrado.drop(columns=['Valor Individual', 'Peso Individual (kg)'], errors='ignore') if not df_plan_filtrado.empty else pd.DataFrame()
        excel_traslados = generar_excel_dinamico(df_plan_filtrado, "Plan de Traslados")
        st.download_button("📥 Descargar Plan de Traslados Dinámico", excel_traslados, "Plan_de_Traslados_Dinamico.xlsx")
        
        if df_plan_display.empty: 
            st.success("¡No se sugieren traslados que involucren a esta tienda con los filtros actuales!")
        else: 
            st.dataframe(df_plan_display, hide_index=True, use_container_width=True, column_config={"Valor del Traslado": st.column_config.NumberColumn(format="$ %d"), "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")})
            st.markdown("---")
            st.subheader("Resumen de la Carga Filtrada")
            total_valor, total_peso = df_plan_display['Valor del Traslado'].sum(), df_plan_display['Peso del Traslado (kg)'].sum()
            col_kpi1, col_kpi2 = st.columns(2)
            col_kpi1.metric("Valor Total del Traslado", f"${total_valor:,.0f}")
            col_kpi2.metric("Peso Total del Traslado", f"{total_peso:,.2f} kg")

    # --- PESTAÑA 3: PLAN DE COMPRAS ---
    with tab_compras:
        st.info(f"Prioridad 2: Comprar únicamente lo necesario para **{selected_almacen_nombre}** después de agotar traslados.")
        # El plan de compras se genera desde df_filtered, que ya está acotado a la tienda y marcas correctas.
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            df_plan_compras['Uds a Comprar'] = df_plan_compras['Sugerencia_Compra'].astype(int)
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Peso de la Compra (kg)'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Peso_Articulo']
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Comprar para Tienda'})[['Comprar para Tienda', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Uds a Comprar', 'Peso de la Compra (kg)', 'Valor de la Compra']].sort_values(by=['Valor de la Compra', 'Segmento_ABC'], ascending=[False, True])
        
        excel_compras = generar_excel_dinamico(df_plan_compras_final, "Plan de Compras")
        st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx")
        
        if df_plan_compras_final.empty: 
            st.success("¡No se requieren compras con los filtros actuales!")
        else: 
            st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True, column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")})

else:
    st.error("🔴 Los datos no se han cargado o no se encuentran en el estado de la sesión.")
    st.page_link("app.py", label="Ir a la página principal para recargar", icon="🏠")
