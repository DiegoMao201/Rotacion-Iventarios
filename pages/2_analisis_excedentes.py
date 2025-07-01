import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import io

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Análisis de Excedentes", layout="wide", page_icon="📉")
st.title("📉 Análisis de Excedentes y Baja Rotación")
st.markdown("Identifica, gestiona y crea planes de acción para el inventario que está inmovilizando capital.")

# --- 1. FUNCIONES PARA CREAR ARCHIVOS EXCEL ---

@st.cache_data
def generar_excel_promocional(df):
    """Crea un archivo de Excel con formato profesional para compartir con clientes."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_cliente = df[['SKU', 'Descripcion', 'Marca_Nombre', 'Stock', 'Precio_Oferta']].copy()
        df_cliente.rename(columns={
            'SKU': 'Referencia',
            'Descripcion': 'Descripción del Producto',
            'Marca_Nombre': 'Marca',
            'Stock': 'Unidades Disponibles',
            'Precio_Oferta': 'Precio de Oferta (IVA Incluido)'
        }, inplace=True)
        df_cliente.to_excel(writer, index=False, sheet_name='Promocion_Liquidacion')
        
        workbook = writer.book
        worksheet = writer.sheets['Promocion_Liquidacion']
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#7792E3', 'font_color': 'white', 'border': 1})
        money_format = workbook.add_format({'num_format': '$#,##0'})
        
        for col_num, value in enumerate(df_cliente.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        worksheet.set_column('E:E', 18, money_format)
        worksheet.set_column('A:A', 15)
        worksheet.set_column('B:B', 45)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:D', 20)
    return output.getvalue()

@st.cache_data
def generar_excel_plan_traslados(df):
    """Crea un Excel interno con el plan de acción de traslados."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Seleccionar, renombrar y ordenar columnas para el plan interno
        df_interno = df[[
            'SKU', 'Descripcion', 'Marca_Nombre', 'Almacen_Nombre', 'Stock',
            'Unidades_Traslado_Sugeridas', 'Tienda_Destino_Sugerida', 'Valor_Inventario'
        ]].copy()
        
        df_interno.rename(columns={
            'SKU': 'SKU',
            'Descripcion': 'Descripción Producto',
            'Marca_Nombre': 'Marca',
            'Almacen_Nombre': 'Tienda Origen (con Excedente)',
            'Stock': 'Stock Actual en Origen',
            'Unidades_Traslado_Sugeridas': 'Unidades a Enviar',
            'Tienda_Destino_Sugerida': 'Sugerencia Tienda Destino',
            'Valor_Inventario': 'Valor Inmovilizado'
        }, inplace=True)
        
        # Filtrar solo las filas donde hay una sugerencia de traslado válida
        df_interno = df_interno[df_interno['Unidades a Enviar'] > 0].sort_values(by='Valor Inmovilizado', ascending=False)
        
        df_interno.to_excel(writer, index=False, sheet_name='Plan_de_Traslados')
        
        workbook = writer.book
        worksheet = writer.sheets['Plan_de_Traslados']
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        default_format = workbook.add_format({'border': 1})
        
        for col_num, value in enumerate(df_interno.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Aplicar formatos a las columnas de datos
        worksheet.conditional_format('A1:H' + str(len(df_interno) + 1), {'type': 'no_blanks', 'format': default_format})
        worksheet.set_column('H:H', 20, money_format) # Valor Inmovilizado
        
        # Ajustar ancho de columnas
        worksheet.set_column('A:A', 15) # SKU
        worksheet.set_column('B:B', 45) # Descripcion
        worksheet.set_column('C:C', 20) # Marca
        worksheet.set_column('D:E', 25) # Tienda Origen y Stock
        worksheet.set_column('F:G', 25) # Unidades a enviar y Tienda Destino

    return output.getvalue()


# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
        # --- LÓGICA AÑADIDA: CALCULAR LA MEJOR TIENDA DE DESTINO ---
        # 1. Identificar todas las necesidades
        df_necesidades = df_analisis_completo[df_analisis_completo['Necesidad_Total'] > 0].copy()
        # 2. Para cada SKU, encontrar la tienda con la MÁXIMA necesidad
        idx_max_necesidad = df_necesidades.groupby('SKU')['Necesidad_Total'].idxmax()
        df_mejor_destino = df_necesidades.loc[idx_max_necesidad][['SKU', 'Almacen_Nombre']]
        df_mejor_destino.rename(columns={'Almacen_Nombre': 'Tienda_Destino_Sugerida'}, inplace=True)
        # 3. Unir esta sugerencia al dataframe principal
        df_analisis_completo = pd.merge(df_analisis_completo, df_mejor_destino, on='SKU', how='left')
        # 4. Limpieza: Si el destino es la misma tienda de origen, no es un traslado válido
        df_analisis_completo.loc[
            df_analisis_completo['Almacen_Nombre'] == df_analisis_completo['Tienda_Destino_Sugerida'],
            'Tienda_Destino_Sugerida'
        ] = np.nan
        df_analisis_completo['Tienda_Destino_Sugerida'].fillna("Sin necesidad en otra tienda", inplace=True)


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

        st.sidebar.markdown("---")
        tipo_excedente = st.sidebar.radio(
            "Selecciona el tipo de producto a analizar:",
            ('Todos los Excedentes y Bajas Ventas', 'Solo Excedentes (Sobre-stock)', 'Solo Baja Rotación / Obsoleto'),
            key="radio_tipo_excedente"
        )

        if tipo_excedente == 'Solo Excedentes (Sobre-stock)':
            estados_filtrar = ['Excedente']
            titulo_detalle = "Detalle de Productos con Excedente (Sobre-stock)"
        elif tipo_excedente == 'Solo Baja Rotación / Obsoleto':
            estados_filtrar = ['Baja Rotación / Obsoleto']
            titulo_detalle = "Detalle de Productos de Baja Rotación para Liquidar"
        else:
            estados_filtrar = ['Excedente', 'Baja Rotación / Obsoleto']
            titulo_detalle = "Detalle de Todos los Productos Críticos"

        df_excedentes = df_filtered[df_filtered['Estado_Inventario'].isin(estados_filtrar)].copy()
        df_excedentes['Dias_Inventario'] = (df_excedentes['Stock'] / df_excedentes['Demanda_Diaria_Promedio']).replace([np.inf, -np.inf], 9999)
        df_excedentes['Precio_Oferta'] = df_excedentes['Costo_Promedio_UND'] * 1.10

        # --- MÉTRICAS PRINCIPALES ---
        st.header(f"Análisis de Excedentes para: {selected_almacen_nombre}", divider='blue')
        # ... (el resto de las métricas y el gráfico de Pareto no cambian) ...
        valor_excedente = df_excedentes['Valor_Inventario'].sum()
        valor_total = df_filtered['Valor_Inventario'].sum()
        porc_excedente = (valor_excedente / valor_total * 100) if valor_total > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Total en Categoría", f"${valor_excedente:,.0f}")
        col2.metric("📦 SKUs en esta categoría", f"{df_excedentes['SKU'].nunique()}")
        col3.metric("% del Inventario", f"{porc_excedente:.1f}%")
        st.markdown("---")
        st.subheader("Análisis de Pareto: ¿Dónde se concentra el problema?")
        if not df_excedentes.empty:
            pareto_data = df_excedentes.groupby('SKU').agg(Valor_Inventario=('Valor_Inventario', 'sum')).sort_values(by='Valor_Inventario', ascending=False).reset_index()
            pareto_data['Porcentaje_Acumulado'] = pareto_data['Valor_Inventario'].cumsum() / pareto_data['Valor_Inventario'].sum() * 100
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=pareto_data['SKU'], y=pareto_data['Valor_Inventario'], name='Valor del Excedente por SKU', marker_color='#7792E3'), secondary_y=False)
            fig.add_trace(go.Scatter(x=pareto_data['SKU'], y=pareto_data['Porcentaje_Acumulado'], name='Porcentaje Acumulado', mode='lines+markers', line_color='#FF4B4B'), secondary_y=True)
            fig.update_layout(title_text="Principio 80/20 del Inventario en la Categoría Seleccionada", xaxis_tickangle=-45)
            fig.update_xaxes(title_text="SKUs (Ordenados por Valor de Excedente)")
            fig.update_yaxes(title_text="<b>Valor del Excedente ($)</b>", secondary_y=False)
            fig.update_yaxes(title_text="<b>Porcentaje Acumulado (%)</b>", secondary_y=True, range=[0, 105])
            st.plotly_chart(fig, use_container_width=True)
            st.info("Este gráfico muestra cómo unos pocos SKUs (a la izquierda) son responsables de la mayor parte del valor de tu inventario en esta categoría. ¡Atácalos primero!")
        else:
            st.success("No hay inventario para analizar con los filtros actuales.")


        # --- TABLA DE DETALLE Y DESCARGA DE EXCEL ---
        st.markdown("---")
        st.subheader(titulo_detalle)
        
        if not df_excedentes.empty:
            st.dataframe(
                df_excedentes.sort_values('Valor_Inventario', ascending=False),
                column_config={
                    "SKU": "SKU",
                    "Descripcion": st.column_config.TextColumn("Descripción", width="large"),
                    "Valor_Inventario": st.column_config.NumberColumn("Valor Inmovilizado", format="$ %d"),
                    "Unidades_Traslado_Sugeridas": st.column_config.NumberColumn("Uds. a Enviar", help="Unidades sugeridas para enviar a la tienda destino."),
                    # --- ✅ COLUMNA DE DESTINO INTEGRADA ---
                    "Tienda_Destino_Sugerida": st.column_config.TextColumn("Enviar Traslado a:", help="Tienda con mayor necesidad para este producto."),
                    "Stock": "Stock Actual",
                    "Dias_Inventario": st.column_config.ProgressColumn("Días de Inventario", min_value=0, max_value=365),
                },
                column_order=[
                    "SKU", "Descripcion", "Stock", "Valor_Inventario", 
                    "Unidades_Traslado_Sugeridas", "Tienda_Destino_Sugerida", "Dias_Inventario"
                ],
                hide_index=True,
                use_container_width=True
            )

            # --- BOTONES DE DESCARGA ---
            st.markdown("##### ⬇️ Descargar Reportes")
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                # Botón para el plan de acción interno
                excel_traslados = generar_excel_plan_traslados(df_excedentes)
                st.download_button(
                    label="📥 Descargar Plan de Traslados (Interno)",
                    data=excel_traslados,
                    file_name=f"Plan_Traslados_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            with col_btn2:
                 # Botón para la promoción a clientes
                excel_promo = generar_excel_promocional(df_excedentes)
                st.download_button(
                    label="📥 Descargar Promoción para Clientes",
                    data=excel_promo,
                    file_name=f"Promocion_Liquidacion_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        else:
            st.info("No hay productos que mostrar en esta categoría.")

    else:
         st.warning("No hay datos cargados para analizar.")
else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' y espera a que los datos se procesen.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
