import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import io
from datetime import datetime

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Diagnóstico de Excedentes", layout="wide", page_icon="💡")
st.title("💡 Diagnóstico y Acción sobre Excedentes")
st.markdown("Un tablero inteligente que te dice dónde está tu capital inmovilizado y qué hacer para liberarlo.")

# --- 1. FUNCIONES AUXILIARES Y DE EXCEL ---

@st.cache_data
def generar_excel_analisis(df):
    """Crea un archivo de Excel con el análisis completo y plan de acción."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Preparar el dataframe para el reporte
        df_reporte = df[[
            'SKU', 'Descripcion', 'Marca_Nombre', 'Almacen_Nombre', 'Stock', 
            'Valor_Inventario', 'Dias_Desde_Ultima_Venta', 'Sugerencia_Accion'
        ]].copy()
        df_reporte.rename(columns={
            'Almacen_Nombre': 'Tienda',
            'Valor_Inventario': 'Capital Inmovilizado',
            'Dias_Desde_Ultima_Venta': 'Antigüedad (Días sin Venta)',
            'Sugerencia_Accion': 'Acción Sugerida'
        }, inplace=True)
        
        df_reporte.to_excel(writer, index=False, sheet_name='Plan de Acción Excedentes')
        
        workbook = writer.book
        worksheet = writer.sheets['Plan de Acción Excedentes']
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#E32D2D', 'font_color': 'white', 'border': 1})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        
        for col_num, value in enumerate(df_reporte.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        worksheet.set_column('F:F', 20, money_format)
        for i, col in enumerate(df_reporte.columns):
            width = max(df_reporte[col].astype(str).map(len).max(), len(col)) + 3
            worksheet.set_column(i, i, min(width, 45))
            
    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']

    # --- ENRIQUECIMIENTO DE DATOS (CÁLCULOS CLAVE) ---
    # Calcular Días desde la última venta
    @st.cache_data
    def calcular_antiguedad(df):
        df_c = df.copy()
        ultima_venta = df_c['Historial_Ventas'].str.extractall(r'(\d{4}-\d{2}-\d{2})').groupby(level=0)[0].max()
        ultima_venta = pd.to_datetime(ultima_venta, errors='coerce')
        df_c['Dias_Desde_Ultima_Venta'] = (datetime.now() - ultima_venta).dt.days.fillna(999) # Si no hay historial, es muy viejo
        return df_c
    
    df_analisis_completo = calcular_antiguedad(df_analisis_completo)

    # Calcular sugerencia de destino para traslados
    df_necesidades = df_analisis_completo[df_analisis_completo['Necesidad_Total'] > 0]
    if not df_necesidades.empty:
        idx_max_necesidad = df_necesidades.groupby('SKU')['Necesidad_Total'].idxmax()
        df_mejor_destino = df_necesidades.loc[idx_max_necesidad][['SKU', 'Almacen_Nombre']].rename(columns={'Almacen_Nombre': 'Tienda_Destino_Sugerida'})
        df_analisis_completo = pd.merge(df_analisis_completo, df_mejor_destino, on='SKU', how='left')
    else:
        df_analisis_completo['Tienda_Destino_Sugerida'] = np.nan

    # --- FILTROS EN LA BARRA LATERAL ---
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
    map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
    lista_nombres_unicos = sorted([str(nombre) for nombre in nombres_almacen['Almacen_Nombre'].unique() if pd.notna(nombre)])
    lista_seleccion_nombres = [opcion_consolidado] + lista_nombres_unicos
    
    selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres, key="sb_almacen_excedentes")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_analisis_completo
    else:
        codigo_almacen_seleccionado = map_nombre_a_codigo.get(selected_almacen_nombre)
        df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]

    lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_excedentes")
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()

    # Filtrar solo por productos críticos
    estados_filtrar = ['Excedente', 'Baja Rotación / Obsoleto']
    df_excedentes = df_filtered[df_filtered['Estado_Inventario'].isin(estados_filtrar)].copy()

    # --- ASIGNAR ACCIÓN SUGERIDA ---
    def asignar_accion(row):
        # Prioridad 1: Traslado si es posible
        if pd.notna(row['Tienda_Destino_Sugerida']) and row['Almacen_Nombre'] != row['Tienda_Destino_Sugerida'] and row['Excedente_Trasladable'] > 0:
            return "🚚 Trasladar"
        # Prioridad 2: Liquidar si es muy viejo y sin movimiento
        if row['Dias_Desde_Ultima_Venta'] > 180: # Más de 6 meses
            return "🔥 Liquidar Urgente"
        # Prioridad 3: Promocionar si es moderadamente viejo
        if row['Dias_Desde_Ultima_Venta'] > 90: # Más de 3 meses
            return "💸 Promocionar"
        # Prioridad 4: Monitorear si es un excedente reciente
        return "👁️ Monitorear"
    
    if not df_excedentes.empty:
        df_excedentes['Sugerencia_Accion'] = df_excedentes.apply(asignar_accion, axis=1)

    # --- NAVEGACIÓN POR PESTAÑAS ---
    tab_diagnostico, tab_plan_accion = st.tabs(["📊 Visión General y Diagnóstico", "📋 Plan de Acción y Detalle"])

    with tab_diagnostico:
        # --- CÁLCULO DE KPIs ---
        valor_excedente_total = df_excedentes['Valor_Inventario'].sum()
        valor_inventario_total = df_filtered['Valor_Inventario'].sum()
        porc_excedente = (valor_excedente_total / valor_inventario_total * 100) if valor_inventario_total > 0 else 0
        skus_excedente = df_excedentes['SKU'].nunique()
        antiguedad_promedio = df_excedentes['Dias_Desde_Ultima_Venta'].replace(999, np.nan).mean()

        st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")

        # --- DIAGNÓSTICO AUTOMÁTICO ---
        if porc_excedente > 25 or (antiguedad_promedio is not None and antiguedad_promedio > 120):
            st.error(f"🚨 **Alerta de Capital en Riesgo**: El **{porc_excedente:.1f}%** de tu inventario es excedente, con una antigüedad promedio de **{antiguedad_promedio:.0f} días**. Es crítico tomar acciones de liquidación y traslado para liberar capital.", icon="🚨")
        elif porc_excedente > 10:
            st.warning(f"⚠️ **Atención**: El **{porc_excedente:.1f}%** de tu inventario es excedente. Revisa el Plan de Acción para optimizar tu stock y prevenir obsolescencia.", icon="⚠️")
        else:
            st.success("✅ **¡Inventario Saludable!** Tus niveles de excedente están bajo control. ¡Excelente trabajo!", icon="✅")

        # --- KPIs ---
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("💰 Capital Inmovilizado", f"${valor_excedente_total:,.0f}", f"{porc_excedente:.1f}% del total")
        kpi2.metric("📦 SKUs con Excedente", f"{skus_excedente}")
        kpi3.metric("⏳ Antigüedad Promedio del Excedente", f"{antiguedad_promedio:.0f} días" if pd.notna(antiguedad_promedio) else "N/A")

        st.markdown("---")

        # --- VISUALIZACIONES INTELIGENTES ---
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("Concentración del Excedente")
            if not df_excedentes.empty and valor_excedente_total > 0:
                fig = px.treemap(df_excedentes, path=[px.Constant("Todo el Excedente"), 'Marca_Nombre', 'SKU'], values='Valor_Inventario',
                                 color='Marca_Nombre', title="¿Dónde se concentra el capital inmovilizado?")
                fig.update_layout(margin = dict(t=50, l=25, r=25, b=25))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No hay datos de excedente para mostrar.")
        
        with col_g2:
            st.subheader("Antigüedad del Problema")
            if not df_excedentes.empty and valor_excedente_total > 0:
                df_excedentes['Rango_Antiguedad'] = pd.cut(df_excedentes['Dias_Desde_Ultima_Venta'],
                                                          bins=[0, 30, 90, 180, 365, float('inf')],
                                                          labels=['0-30 días', '31-90 días', '91-180 días', '181-365 días', '+1 año'])
                data_chart = df_excedentes.groupby('Rango_Antiguedad')['Valor_Inventario'].sum().reset_index()
                fig = px.bar(data_chart, x='Rango_Antiguedad', y='Valor_Inventario', text_auto='.2s', title="¿Qué tan viejo es tu excedente?")
                st.plotly_chart(fig, use_container_width=True)
            else:
                 st.info("No hay datos de antigüedad para mostrar.")

    with tab_plan_accion:
        st.subheader("Plan de Acción Detallado por Producto")
        
        if not df_excedentes.empty:
            st.dataframe(
                df_excedentes.sort_values('Valor_Inventario', ascending=False),
                column_config={
                    "SKU": "SKU",
                    "Descripcion": st.column_config.TextColumn("Descripción", width="large"),
                    "Valor_Inventario": st.column_config.NumberColumn("Capital Inmovilizado", format="$ %d"),
                    "Sugerencia_Accion": st.column_config.TextColumn("⚡ Acción Sugerida"),
                    "Dias_Desde_Ultima_Venta": st.column_config.ProgressColumn("Días sin Venta", min_value=0, max_value=365),
                    "Almacen_Nombre": "Tienda",
                },
                column_order=[
                    "Sugerencia_Accion", "SKU", "Descripcion", "Almacen_Nombre", "Marca_Nombre",
                    "Stock", "Valor_Inventario", "Dias_Desde_Ultima_Venta"
                ],
                hide_index=True,
                use_container_width=True
            )
            
            # --- BOTÓN DE DESCARGA MEJORADO ---
            excel_data = generar_excel_analisis(df_excedentes)
            st.download_button(
                label="📥 Descargar Plan de Acción en Excel",
                data=excel_data,
                file_name=f"Plan_Accion_Excedentes_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.success("¡Felicidades! No se encontraron productos con excedente según los filtros aplicados.")

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
