import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIONES PARA GENERAR ARCHIVOS EXCEL Y LÓGICA DE TRASLADOS ---
@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No se encontraron datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70)
            return output.getvalue()
        for col in ['Uds a Enviar', 'Uds a Comprar']:
            if col in df.columns:
                df[col] = df[col].astype(int)
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        weight_format = workbook.add_format({'num_format': '#,##0.00 "kg"', 'border': 1})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        if nombre_hoja == "Plan de Traslados" and all(c in df.columns for c in ['Uds a Enviar', 'Peso Individual (kg)', 'Valor Individual']):
            idx_uds = df.columns.get_loc('Uds a Enviar'); idx_peso_ind = df.columns.get_loc('Peso Individual (kg)'); idx_valor_ind = df.columns.get_loc('Valor Individual'); idx_peso_total = df.columns.get_loc('Peso del Traslado (kg)'); idx_valor_total = df.columns.get_loc('Valor del Traslado')
            for row_num in range(1, len(df) + 1):
                worksheet.write_formula(row_num, idx_peso_total, f'={chr(ord("A")+idx_uds)}{row_num+1}*{chr(ord("A")+idx_peso_ind)}{row_num+1}', weight_format)
                worksheet.write_formula(row_num, idx_valor_total, f'={chr(ord("A")+idx_uds)}{row_num+1}*{chr(ord("A")+idx_valor_ind)}{row_num+1}', money_format)
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(width, 45))
    return output.getvalue()

def generar_plan_traslados_inteligente(df_analisis):
    df_origen = df_analisis[df_analisis['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = df_analisis[df_analisis['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()
    if df_origen.empty or df_destino.empty: return pd.DataFrame()
    plan_final = []
    for sku, grupo_destino in df_destino.groupby('SKU'):
        grupo_origen_sku = df_origen[df_origen['SKU'] == sku].copy()
        if grupo_origen_sku.empty: continue
        excedentes_dict = pd.Series(grupo_origen_sku['Excedente_Trasladable'].values, index=grupo_origen_sku['Almacen_Nombre']).to_dict()
        for idx, necesidad_row in grupo_destino.iterrows():
            tienda_necesitada = necesidad_row['Almacen_Nombre']; necesidad_actual = necesidad_row['Necesidad_Total']
            for tienda_origen, excedente_disponible in sorted(excedentes_dict.items(), key=lambda item: item[1], reverse=True):
                if necesidad_actual <= 0: break
                if tienda_origen == tienda_necesitada: continue
                if excedente_disponible > 0:
                    unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                    if unidades_a_enviar < 1: continue
                    info_origen = grupo_origen_sku[grupo_origen_sku['Almacen_Nombre'] == tienda_origen].iloc[0]
                    plan_final.append({'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': info_origen['Marca_Nombre'], 'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen, 'Stock en Origen': info_origen['Stock'], 'Tienda Destino': tienda_necesitada, 'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'], 'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row['Peso_Articulo'], 'Valor Individual': necesidad_row['Costo_Promedio_UND'], 'Peso del Traslado (kg)': 0, 'Valor del Traslado': 0})
                    necesidad_actual -= unidades_a_enviar; excedentes_dict[tienda_origen] -= unidades_a_enviar
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']
    MARGEN_ESTIMADO = 1.30 
    if 'Precio_Venta_Estimado' not in df_analisis_completo.columns:
        df_analisis_completo['Precio_Venta_Estimado'] = df_analisis_completo['Costo_Promedio_UND'] * MARGEN_ESTIMADO

    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("Filtros de Gestión"); opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = sorted([str(n) for n in df_analisis_completo['Almacen_Nombre'].unique() if pd.notna(n)])
    selected_almacen_nombre = st.sidebar.selectbox("Vista por Tienda (Diagnóstico y Compras):", [opcion_consolidado] + nombres_almacen, key="sb_almacen_abastecimiento")
    df_vista_filtros = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == selected_almacen_nombre] if selected_almacen_nombre != opcion_consolidado else df_analisis_completo
    lista_marcas = sorted(df_vista_filtros['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    df_filtered = df_vista_filtros[df_vista_filtros['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()
    
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # --- PESTAÑA 1: DIAGNÓSTICO GENERAL ---
    with tab_diagnostico:
        st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
        # ... (Cálculos y visualizaciones de Diagnóstico se mantienen igual, son correctos)
        necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
        df_origen_kpi, df_destino_kpi = df_analisis_completo[df_analisis_completo['Excedente_Trasladable'] > 0], df_filtered[df_filtered['Necesidad_Total'] > 0]
        oportunidad_ahorro = 0
        if not df_origen_kpi.empty and not df_destino_kpi.empty:
            df_sugerencias_kpi = pd.merge(df_origen_kpi[['SKU', 'Excedente_Trasladable', 'Costo_Promedio_UND']], df_destino_kpi[['SKU', 'Necesidad_Total']], on='SKU')
            df_sugerencias_kpi['Uds_a_Mover'] = np.minimum(df_sugerencias_kpi['Excedente_Trasladable'], df_sugerencias_kpi['Necesidad_Total'])
            oportunidad_ahorro = (df_sugerencias_kpi['Uds_a_Mover'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()
        df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
        venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
        st.markdown("##### Indicadores Clave de Rendimiento (KPIs)")
        kpi1, kpi2, kpi3 = st.columns(3); kpi1.metric("💰 Valor Compra Requerida", f"${necesidad_compra_total:,.0f}"); kpi2.metric("💸 Ahorro por Traslados", f"${oportunidad_ahorro:,.0f}"); kpi3.metric("📉 Venta Potencial Perdida", f"${venta_perdida:,.0f}")
        st.markdown("---"); st.markdown("##### Análisis y Recomendaciones Clave")
        with st.container(border=True):
            if venta_perdida > 0: st.markdown(f"**🚨 Alerta de Ventas en Riesgo:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** en 30 días por **{len(df_quiebre)}** productos en quiebre. Es **crítico** reabastecerlos.")
            if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad de Ahorro:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña **'Plan de Traslados'** como tu **primera opción** antes de comprar.")
            if necesidad_compra_total > 0:
                df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0]
                df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
                top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                st.markdown(f"**🎯 Enfoque de Compra:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**. Asegura su disponibilidad.")
            if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0: st.markdown("✅ **¡Inventario Optimizado!** No se detectan necesidades urgentes con los filtros actuales.")
        st.markdown("---"); st.markdown("##### Visualización de Necesidades")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            # (Gráfico de barras de Inversión Requerida)
            ...
        with col_g2:
            # (Gráfico sunburst de Prioridad de Compra)
            ...

    # --- PESTAÑA 2: PLAN DE TRASLADOS ---
    with tab_traslados:
        df_plan_maestro = generar_plan_traslados_inteligente(df_analisis_completo)
        
        # ✅ Filtro principal: si se selecciona una tienda, solo mostrar lo que necesita recibir.
        if selected_almacen_nombre != opcion_consolidado:
            st.info(f"Mostrando únicamente los traslados que la tienda **{selected_almacen_nombre}** necesita recibir.")
            df_plan_filtrado = df_plan_maestro[df_plan_maestro['Tienda Destino'] == selected_almacen_nombre].copy()
        else:
            st.info("Mostrando todas las oportunidades de traslado entre tiendas (vista consolidada).")
            df_plan_filtrado = df_plan_maestro.copy()
            
        st.sidebar.markdown("---"); st.sidebar.subheader("Filtros del Plan de Traslados"); opcion_todas = "Todas"
        
        # ✅ CORRECCIÓN TypeError: Se verifica si el df no está vacío ANTES de crear los filtros.
        if not df_plan_filtrado.empty:
            lista_origenes = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Origen'].unique() if pd.notna(x)])
            filtro_origen = st.sidebar.selectbox("Filtrar Tienda Origen:", lista_origenes)
            if filtro_origen != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Origen'] == filtro_origen]
            
            lista_destinos = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Destino'].unique() if pd.notna(x)])
            filtro_destino = st.sidebar.selectbox("Filtrar Tienda Destino:", lista_destinos)
            if filtro_destino != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Destino'] == filtro_destino]
            
            if selected_marcas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Marca_Nombre'].isin(selected_marcas)]
        else:
            # Si el df está vacío, se muestran los selectbox deshabilitados para consistencia visual
            st.sidebar.selectbox("Filtrar Tienda Origen:", [opcion_todas], disabled=True)
            st.sidebar.selectbox("Filtrar Tienda Destino:", [opcion_todas], disabled=True)
            
        df_plan_display, df_plan_exportar = (df_plan_filtrado, df_plan_filtrado) if df_plan_filtrado.empty else (df_plan_filtrado.drop(columns=['Valor Individual', 'Peso Individual (kg)']), df_plan_filtrado)
        excel_traslados = generar_excel_dinamico(df_plan_exportar, "Plan de Traslados"); st.download_button("📥 Descargar Plan de Traslados Dinámico", excel_traslados, "Plan_de_Traslados_Dinamico.xlsx")
        
        if df_plan_display.empty: st.success("¡No se sugieren traslados con los filtros actuales!")
        else: 
            st.dataframe(df_plan_display, hide_index=True, use_container_width=True, column_config={"Valor del Traslado": st.column_config.NumberColumn(format="$ %d"), "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")})
            st.markdown("---"); st.subheader("Resumen de la Carga Filtrada")
            total_valor, total_peso = df_plan_display['Valor del Traslado'].sum(), df_plan_display['Peso del Traslado (kg)'].sum()
            col_kpi1, col_kpi2 = st.columns(2); col_kpi1.metric("Valor Total del Traslado", f"${total_valor:,.0f}"); col_kpi2.metric("Peso Total del Traslado", f"{total_peso:,.2f} kg")

    # --- PESTAÑA 3: PLAN DE COMPRAS ---
    with tab_compras:
        st.info("Prioridad 2: Comprar únicamente lo necesario después de haber agotado los traslados internos.")
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            df_plan_compras['Uds a Comprar'] = df_plan_compras['Sugerencia_Compra'].astype(int)
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Peso de la Compra (kg)'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Peso_Articulo']
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Comprar para Tienda'})[['Comprar para Tienda', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Uds a Comprar', 'Peso de la Compra (kg)', 'Valor de la Compra']].sort_values(by=['Valor de la Compra', 'Segmento_ABC'], ascending=[False, True])
        
        excel_compras = generar_excel_dinamico(df_plan_compras_final, "Plan de Compras"); st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx")
        
        if df_plan_compras_final.empty: st.success("¡No se requieren compras con los filtros actuales!")
        else: st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True, column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")})

else:
    st.error("🔴 Los datos no se han cargado."); st.page_link("app.py", label="Ir a la página principal", icon="🏠")
