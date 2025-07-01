import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIÓN DE EXCEL PROFESIONAL Y DINÁMICA ---
@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    """
    Función mejorada que crea un Excel con formato de Tabla, fórmulas
    y columnas adicionales para un análisis dinámico.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            df_vacio = pd.DataFrame([{'Notificación': f"No se encontraron datos para '{nombre_hoja}' con los filtros actuales."}])
            df_vacio.to_excel(writer, index=False, sheet_name=nombre_hoja)
            worksheet = writer.sheets[nombre_hoja]
            worksheet.set_column('A:A', 70)
            return output.getvalue() # Salir si no hay datos

        # Redondear unidades a enteros
        if 'Uds a Enviar' in df.columns:
            df['Uds a Enviar'] = df['Uds a Enviar'].astype(int)
        if 'Uds a Comprar' in df.columns:
            df['Uds a Comprar'] = df['Uds a Comprar'].astype(int)

        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1) # Dejar espacio para el título
        
        workbook = writer.book
        worksheet = writer.sheets[nombre_hoja]

        # Formatos
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        number_format = workbook.add_format({'num_format': '#,##0', 'border': 1})
        weight_format = workbook.add_format({'num_format': '#,##0.00 "kg"', 'border': 1})
        
        # Escribir cabeceras con formato
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(1, col_num, value, header_format)
        
        # ✅ LÓGICA PARA ESCRIBIR FÓRMULAS EN LUGAR DE VALORES
        # Solo se aplica si es la hoja de traslados y tiene las columnas necesarias
        if nombre_hoja == "Plan de Traslados" and all(c in df.columns for c in ['Uds a Enviar', 'Peso Individual (kg)', 'Valor Individual']):
            # Obtener las letras de las columnas para las fórmulas
            col_uds = chr(ord('A') + df.columns.get_loc('Uds a Enviar'))
            col_peso_ind = chr(ord('A') + df.columns.get_loc('Peso Individual (kg)'))
            col_valor_ind = chr(ord('A') + df.columns.get_loc('Valor Individual'))
            
            # Escribir los datos fila por fila, aplicando fórmulas
            for row_num in range(2, len(df) + 2):
                # Fórmula para Peso del Traslado
                worksheet.write_formula(row_num, df.columns.get_loc('Peso del Traslado (kg)'), f'={col_uds}{row_num+1}*{col_peso_ind}{row_num+1}', weight_format)
                # Fórmula para Valor del Traslado
                worksheet.write_formula(row_num, df.columns.get_loc('Valor del Traslado'), f'={col_uds}{row_num+1}*{col_valor_ind}{row_num+1}', money_format)

        # Crear una tabla de Excel para profesionalismo y funcionalidad
        num_rows, num_cols = df.shape
        worksheet.add_table(1, 0, num_rows + 1, num_cols - 1, {
            'columns': [{'header': col} for col in df.columns],
            'total_row': True,
            'style': 'Table Style Medium 9'
        })

        # Ajustar anchos de columna
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(width, 45))
            
    return output.getvalue()

# --- LÓGICA DE ASIGNACIÓN SECUENCIAL DE TRASLADOS ---
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
            tienda_necesitada = necesidad_row['Almacen_Nombre']
            necesidad_actual = necesidad_row['Necesidad_Total']
            for tienda_origen, excedente_disponible in sorted(excedentes_dict.items(), key=lambda item: item[1], reverse=True):
                if necesidad_actual <= 0: break
                if tienda_origen == tienda_necesitada: continue
                if excedente_disponible > 0:
                    unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                    if unidades_a_enviar < 1: continue
                    info_origen = grupo_origen_sku[grupo_origen_sku['Almacen_Nombre'] == tienda_origen].iloc[0]
                    # ✅ AÑADIR NUEVAS COLUMNAS
                    plan_final.append({
                        'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': info_origen['Marca_Nombre'],
                        'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,
                        'Stock en Origen': info_origen['Stock'], 'Tienda Destino': tienda_necesitada,
                        'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],
                        'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row['Peso_Articulo'],
                        'Valor Individual': necesidad_row['Costo_Promedio_UND'], 'Peso del Traslado (kg)': 0, 'Valor del Traslado': 0
                    })
                    necesidad_actual -= unidades_a_enviar
                    excedentes_dict[tienda_origen] -= unidades_a_enviar
    
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    # Calcular valores totales después de crear el DF
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])


# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']
    MARGEN_ESTIMADO = 1.30 
    if 'Precio_Venta_Estimado' not in df_analisis_completo.columns:
        df_analisis_completo['Precio_Venta_Estimado'] = df_analisis_completo['Costo_Promedio_UND'] * MARGEN_ESTIMADO

    # (El código de filtros y Pestaña 1 no cambia, se mantiene como estaba)
    st.sidebar.header("Filtros de Gestión")
    opcion_consolidado, nombres_almacen = "-- Consolidado (Todas las Tiendas) --", sorted([str(n) for n in df_analisis_completo['Almacen_Nombre'].unique() if pd.notna(n)])
    selected_almacen_nombre = st.sidebar.selectbox("Vista General por Tienda:", [opcion_consolidado] + nombres_almacen, key="sb_almacen_abastecimiento")
    df_vista_filtros = df_analisis_completo[df_analisis_completo['Almacen_Nombre'] == selected_almacen_nombre] if selected_almacen_nombre != opcion_consolidado else df_analisis_completo
    lista_marcas = sorted(df_vista_filtros['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    df_filtered = df_vista_filtros[df_vista_filtros['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])
    with tab_diagnostico:
        st.subheader("Indicadores Clave de Rendimiento (KPIs)")
        necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
        df_origen_kpi, df_destino_kpi = df_analisis_completo[df_analisis_completo['Excedente_Trasladable'] > 0], df_filtered[df_filtered['Necesidad_Total'] > 0]
        oportunidad_ahorro = 0
        if not df_origen_kpi.empty and not df_destino_kpi.empty:
            df_sugerencias_kpi = pd.merge(df_origen_kpi[['SKU', 'Excedente_Trasladable', 'Costo_Promedio_UND']], df_destino_kpi[['SKU', 'Necesidad_Total']], on='SKU')
            df_sugerencias_kpi['Uds_a_Mover'] = np.minimum(df_sugerencias_kpi['Excedente_Trasladable'], df_sugerencias_kpi['Necesidad_Total'])
            oportunidad_ahorro = (df_sugerencias_kpi['Uds_a_Mover'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()
        df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
        venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
        kpi1, kpi2, kpi3 = st.columns(3); kpi1.metric("💰 Valor Compra Requerida", f"${necesidad_compra_total:,.0f}"); kpi2.metric("💸 Ahorro Potencial por Traslados", f"${oportunidad_ahorro:,.0f}"); kpi3.metric("📉 Venta Potencial Perdida (30 días)", f"${venta_perdida:,.0f}")
        st.markdown("---")
        # ... (código de gráficos sin cambios)

    with tab_traslados:
        st.info("Prioridad 1: Mover inventario existente para cubrir necesidades sin comprar. Este plan asigna desde la tienda con más excedente.")
        df_plan_maestro = generar_plan_traslados_inteligente(df_analisis_completo)
        df_plan_filtrado = df_plan_maestro.copy()
        st.sidebar.markdown("---"); st.sidebar.subheader("Filtros del Plan de Traslados"); opcion_todas = "Todas"
        lista_origenes = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Origen'].unique() if pd.notna(x)])
        filtro_origen = st.sidebar.selectbox("Seleccionar Tienda Origen:", lista_origenes)
        if filtro_origen != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Origen'] == filtro_origen]
        lista_destinos = [opcion_todas] + sorted([str(x) for x in df_plan_filtrado['Tienda Destino'].unique() if pd.notna(x)])
        filtro_destino = st.sidebar.selectbox("Seleccionar Tienda Destino:", lista_destinos)
        if filtro_destino != opcion_todas: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Tienda Destino'] == filtro_destino]
        if selected_marcas and not df_plan_filtrado.empty: df_plan_filtrado = df_plan_filtrado[df_plan_filtrado['Marca_Nombre'].isin(selected_marcas)]
        
        # DataFrame a mostrar y exportar
        if not df_plan_filtrado.empty:
            df_plan_display = df_plan_filtrado[[
                'SKU', 'Descripcion', 'Marca_Nombre', 'Segmento_ABC', 'Tienda Origen', 'Stock en Origen', 
                'Tienda Destino', 'Stock en Destino', 'Necesidad en Destino', 'Uds a Enviar', 'Peso del Traslado (kg)', 'Valor del Traslado'
            ]].copy()
            df_plan_exportar = df_plan_filtrado[[
                'SKU', 'Descripcion', 'Marca_Nombre', 'Segmento_ABC', 'Tienda Origen', 'Stock en Origen', 
                'Tienda Destino', 'Stock en Destino', 'Necesidad en Destino', 'Uds a Enviar', 'Peso Individual (kg)', 'Valor Individual',
                'Peso del Traslado (kg)', 'Valor del Traslado'
            ]].copy()
        else:
            df_plan_display, df_plan_exportar = pd.DataFrame(), pd.DataFrame()

        excel_traslados = generar_excel_dinamico(df_plan_exportar, "Plan de Traslados")
        st.download_button("📥 Descargar Plan de Traslados Dinámico", excel_traslados, "Plan_de_Traslados_Dinamico.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if df_plan_display.empty: st.success("¡No se sugieren traslados con los filtros actuales!")
        else: 
            st.dataframe(df_plan_display, hide_index=True, use_container_width=True, column_config={"Valor del Traslado": st.column_config.NumberColumn(format="$ %d"), "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")})
            st.markdown("---")
            total_valor_traslado, total_peso_traslado = df_plan_display['Valor del Traslado'].sum(), df_plan_display['Peso del Traslado (kg)'].sum()
            st.subheader("Resumen de la Carga Filtrada"); col_kpi1, col_kpi2 = st.columns(2)
            col_kpi1.metric("Valor Total del Traslado", f"${total_valor_traslado:,.0f}"); col_kpi2.metric("Peso Total del Traslado", f"{total_peso_traslado:,.2f} kg")

    with tab_compras:
        # (El código de esta pestaña no cambia)
        st.info("Prioridad 2: Comprar únicamente lo necesario después de haber agotado los traslados internos.")
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            df_plan_compras['Uds a Comprar'] = df_plan_compras['Sugerencia_Compra'].astype(int)
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Peso de la Compra (kg)'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Peso_Articulo']
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Comprar para Tienda'})[['Comprar para Tienda', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Uds a Comprar', 'Peso de la Compra (kg)', 'Valor de la Compra']].sort_values(by=['Valor de la Compra', 'Segmento_ABC'], ascending=[False, True])
        excel_compras = generar_excel_dinamico(df_plan_compras_final, "Plan de Compras")
        st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if df_plan_compras_final.empty: st.success("¡No se requieren compras con los filtros actuales!")
        else: st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True, column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")})

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
