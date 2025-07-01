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

# --- 1. FUNCIÓN PARA CREAR EXCEL CON ESTILO ---
@st.cache_data
def generar_excel_promocional(df):
    """
    Crea un archivo de Excel con formato profesional para compartir con clientes.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Seleccionar y renombrar columnas para el cliente
        df_cliente = df[['SKU', 'Descripcion', 'Marca_Nombre', 'Stock', 'Precio_Oferta']].copy()
        df_cliente.rename(columns={
            'SKU': 'Referencia',
            'Descripcion': 'Descripción del Producto',
            'Marca_Nombre': 'Marca',
            'Stock': 'Unidades Disponibles',
            'Precio_Oferta': 'Precio de Oferta (IVA Incluido)'
        }, inplace=True)

        df_cliente.to_excel(writer, index=False, sheet_name='Promocion_Liquidacion')
        
        # Obtener objetos de xlsxwriter para dar formato
        workbook = writer.book
        worksheet = writer.sheets['Promocion_Liquidacion']

        # Definir formatos
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#7792E3',
            'font_color': 'white',
            'border': 1
        })
        money_format = workbook.add_format({'num_format': '$#,##0'})
        
        # Aplicar formato a la cabecera
        for col_num, value in enumerate(df_cliente.columns.values):
            worksheet.write(0, col_num, value, header_format)
            
        # Aplicar formato de moneda a la columna de precio
        worksheet.set_column('E:E', 18, money_format)
        
        # Ajustar ancho de columnas
        worksheet.set_column('A:A', 15) # Referencia
        worksheet.set_column('B:B', 45) # Descripción
        worksheet.set_column('C:C', 20) # Marca
        worksheet.set_column('D:D', 20) # Unidades

    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']

    if not df_analisis_completo.empty:
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

        # --- FILTRO PARA TIPO DE EXCEDENTE ---
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
        # --- CÁLCULO DE PRECIO DE OFERTA ---
        df_excedentes['Precio_Oferta'] = df_excedentes['Costo_Promedio_UND'] * 1.10

        # --- MÉTRICAS PRINCIPALES ---
        st.header(f"Análisis de Excedentes para: {selected_almacen_nombre}", divider='blue')
        valor_excedente = df_excedentes['Valor_Inventario'].sum()
        valor_total = df_filtered['Valor_Inventario'].sum()
        porc_excedente = (valor_excedente / valor_total * 100) if valor_total > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Valor Total en Categoría", f"${valor_excedente:,.0f}")
        col2.metric("📦 SKUs en esta categoría", f"{df_excedentes['SKU'].nunique()}")
        col3.metric("% del Inventario", f"{porc_excedente:.1f}%")

        st.markdown("---")

        # --- GRÁFICO DE PARETO ---
        st.subheader("Análisis de Pareto: ¿Dónde se concentra el problema?")
        if not df_excedentes.empty:
            pareto_data = df_excedentes.groupby('SKU').agg(
                Valor_Inventario=('Valor_Inventario', 'sum')
            ).sort_values(by='Valor_Inventario', ascending=False).reset_index()

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
                    "Descripcion": "Descripción",
                    "Valor_Inventario": st.column_config.NumberColumn("Valor Inmovilizado", format="$ %d"),
                    # --- ✅ COLUMNA DE TRASLADO INTEGRADA ---
                    "Unidades_Traslado_Sugeridas": st.column_config.NumberColumn(
                        "Sugerencia Traslado (Uds)",
                        help="Unidades de este excedente que podrían ser trasladadas a otra tienda con necesidad.",
                        format="%d"
                    ),
                    "Stock": "Stock Actual",
                    "Dias_Inventario": st.column_config.ProgressColumn("Días de Inventario", min_value=0, max_value=365, help="Estimación de cuántos días cubrirá el stock actual."),
                    "Marca_Nombre": "Marca",
                    "Precio_Oferta": st.column_config.NumberColumn("Precio de Oferta", help="Costo + 10% de margen", format="$ %d"),
                },
                # Columnas que quieres mostrar y en qué orden
                column_order=[
                    "SKU", "Descripcion", "Marca_Nombre", "Stock", 
                    "Valor_Inventario", "Unidades_Traslado_Sugeridas", "Dias_Inventario", "Precio_Oferta"
                ],
                hide_index=True,
                use_container_width=True
            )

            # --- BOTÓN DE DESCARGA ---
            excel_data = generar_excel_promocional(df_excedentes)
            st.download_button(
                label="📥 Descargar Excel para Clientes",
                data=excel_data,
                file_name=f"promocion_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No hay productos que mostrar en esta categoría.")

        # --- ANÁLISIS DE OPORTUNIDADES DE TRASLADO ---
        st.markdown("---")
        st.header("🚚 Oportunidades de Traslado entre Tiendas")

        if selected_almacen_nombre == opcion_consolidado and not df_filtered.empty:
            
            skus_excedente = df_filtered[df_filtered['Estado_Inventario'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]['SKU'].unique()
            # Asumimos que estados 'Normal' o 'Bajo Stock' indican necesidad
            skus_necesidad = df_filtered[df_filtered['Estado_Inventario'].isin(['Normal', 'Bajo Stock (Riesgo)', 'Quiebre de Stock'])]['SKU'].unique()
            
            skus_traslado = list(set(skus_excedente) & set(skus_necesidad))
            
            if skus_traslado:
                df_traslados_candidatos = df_filtered[df_filtered['SKU'].isin(skus_traslado)].copy()
                
                df_origen = df_traslados_candidatos[df_traslados_candidatos['Unidades_Traslado_Sugeridas'] > 0]
                df_destino = df_traslados_candidatos[df_traslados_candidatos['Necesidad_Total'] > 0]
                
                if not df_origen.empty and not df_destino.empty:
                    df_sugerencia_traslado = pd.merge(
                        df_origen[['SKU', 'Descripcion', 'Marca_Nombre', 'Almacen_Nombre', 'Unidades_Traslado_Sugeridas']],
                        df_destino[['SKU', 'Almacen_Nombre', 'Necesidad_Total']],
                        on='SKU',
                        suffixes=('_Origen', '_Destino')
                    ).rename(columns={
                        'Almacen_Nombre_Origen': 'Tienda Origen (con Excedente)',
                        'Unidades_Traslado_Sugeridas': 'Unidades a Enviar',
                        'Almacen_Nombre_Destino': 'Tienda Destino (con Necesidad)',
                        'Necesidad_Total': 'Unidades Requeridas'
                    })
                    
                    df_sugerencia_traslado = df_sugerencia_traslado[df_sugerencia_traslado['Tienda Origen (con Excedente)'] != df_sugerencia_traslado['Tienda Destino (con Necesidad)']]
                    df_sugerencia_traslado['Unidades a Enviar'] = df_sugerencia_traslado[['Unidades a Enviar', 'Unidades Requeridas']].min(axis=1).astype(int)

                    if not df_sugerencia_traslado.empty:
                        st.info("Productos con exceso de stock en una tienda y necesidad en otra. Considera un traslado para balancear el inventario.")
                        st.dataframe(
                            df_sugerencia_traslado[[
                                'SKU', 'Descripcion', 'Marca_Nombre', 
                                'Tienda Origen (con Excedente)', 'Tienda Destino (con Necesidad)', 'Unidades a Enviar'
                            ]].sort_values(by=['SKU', 'Tienda Origen (con Excedente)']).drop_duplicates(),
                            hide_index=True,
                            use_container_width=True
                        )
                    else:
                         st.success("🎉 ¡No se encontraron oportunidades claras de traslado! El inventario parece estar bien distribuido.")
                else:
                    st.success("🎉 ¡No se encontraron oportunidades claras de traslado! El inventario parece estar bien distribuido.")
            else:
                st.success("🎉 ¡No se encontraron oportunidades claras de traslado! El inventario parece estar bien distribuido.")

        else:
            st.warning("Selecciona la vista '-- Consolidado (Todas las Tiendas) --' para ver las oportunidades de traslado entre ellas.")

    else:
         st.warning("No hay datos cargados para analizar.")
else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' y espera a que los datos se procesen.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
