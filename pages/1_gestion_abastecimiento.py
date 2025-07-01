import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")

st.title("🚚 Gestión de Abastecimiento")
st.markdown("Coordina los **traslados** para optimizar el inventario existente y define el **plan de compras** final.")

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
            workbook = writer.book
            worksheet = writer.sheets[nombre_hoja]
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

    # --- FILTROS EN LA BARRA LATERAL ---
    st.sidebar.header("Filtros de Gestión")
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
    map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
    lista_nombres_unicos = sorted([str(nombre) for nombre in nombres_almacen['Almacen_Nombre'].unique() if pd.notna(nombre)])
    lista_seleccion_nombres = [opcion_consolidado] + lista_nombres_unicos
    
    selected_almacen_nombre = st.sidebar.selectbox("Filtrar por Tienda:", lista_seleccion_nombres, key="sb_almacen_abastecimiento")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_analisis_completo
    else:
        codigo_almacen_seleccionado = map_nombre_a_codigo.get(selected_almacen_nombre)
        df_vista = df_analisis_completo[
            (df_analisis_completo['Almacen'] == codigo_almacen_seleccionado) |
            (df_analisis_completo['SKU'].isin(
                df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]['SKU']
            ))
        ]

    lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_abastecimiento")
    
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else pd.DataFrame()

    # --- SECCIÓN 1: PLAN DE TRASLADOS ---
    st.header("🔄 Plan de Traslados para Optimización", divider='blue')
    st.info("Prioridad 1: Mover inventario existente entre tiendas para cubrir necesidades sin comprar.")

    df_origen = df_filtered[df_filtered['Excedente_Trasladable'] > 0].copy()
    df_destino = df_filtered[df_filtered['Necesidad_Total'] > 0].copy()
    
    df_plan_traslados = pd.DataFrame()

    if not df_origen.empty and not df_destino.empty:
        df_sugerencias = pd.merge(
            df_origen[['SKU', 'Descripcion', 'Marca_Nombre', 'Almacen_Nombre', 'Stock', 'Excedente_Trasladable', 'Costo_Promedio_UND', 'Segmento_ABC', 'Peso_Articulo']],
            df_destino[['SKU', 'Almacen_Nombre', 'Necesidad_Total']],
            on='SKU',
            suffixes=('_Origen', '_Destino')
        )
        df_sugerencias = df_sugerencias[df_sugerencias['Almacen_Nombre_Origen'] != df_sugerencias['Almacen_Nombre_Destino']]
        
        # ✅ **CORRECCIÓN**: Toda la lógica de creación del DataFrame final va DENTRO del IF.
        if not df_sugerencias.empty:
            df_sugerencias['Unidades_a_Enviar'] = np.minimum(df_sugerencias['Excedente_Trasladable'], df_sugerencias['Necesidad_Total']).astype(int)
            df_sugerencias['Valor_Traslado'] = df_sugerencias['Unidades_a_Enviar'] * df_sugerencias['Costo_Promedio_UND']
            df_sugerencias['Peso_Traslado'] = df_sugerencias['Unidades_a_Enviar'] * df_sugerencias['Peso_Articulo']
            
            if selected_almacen_nombre != opcion_consolidado:
                df_sugerencias = df_sugerencias[
                    (df_sugerencias['Almacen_Nombre_Origen'] == selected_almacen_nombre) |
                    (df_sugerencias['Almacen_Nombre_Destino'] == selected_almacen_nombre)
                ]

            df_plan_traslados = df_sugerencias[[
                'SKU', 'Descripcion', 'Segmento_ABC', 'Almacen_Nombre_Origen', 'Stock', 
                'Almacen_Nombre_Destino', 'Necesidad_Total', 'Unidades_a_Enviar', 'Peso_Traslado', 'Valor_Traslado'
            ]].rename(columns={
                'Almacen_Nombre_Origen': 'Tienda Origen',
                'Stock': 'Stock en Origen',
                'Almacen_Nombre_Destino': 'Tienda Destino',
                'Necesidad_Total': 'Necesidad en Destino',
                'Unidades_a_Enviar': 'Uds a Enviar',
                'Peso_Traslado': 'Peso del Traslado (kg)',
                'Valor_Traslado': 'Valor del Traslado'
            }).sort_values(by=['Valor_Traslado', 'Segmento_ABC'], ascending=[False, True])

    excel_traslados = generar_excel(df_plan_traslados, "Plan de Traslados")
    st.download_button("📥 Descargar Plan de Traslados", excel_traslados, "Plan_de_Traslados.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if df_plan_traslados.empty:
        st.success("¡No se sugieren traslados con los filtros actuales!")
    else:
        st.dataframe(df_plan_traslados, hide_index=True, use_container_width=True,
            column_config={
                "Valor del Traslado": st.column_config.NumberColumn(format="$ %d"),
                "Peso del Traslado (kg)": st.column_config.NumberColumn(format="%.2f kg")
            })

    # --- SECCIÓN 2: PLAN DE COMPRAS ---
    st.header("🛒 Plan de Compras Sugerido", divider='blue')
    st.info("Prioridad 2: Comprar únicamente lo necesario después de haber agotado los traslados internos.")

    df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
    
    df_plan_compras_final = pd.DataFrame()
    if not df_plan_compras.empty:
        df_plan_compras['Valor_Compra'] = df_plan_compras['Sugerencia_Compra'] * df_plan_compras['Costo_Promedio_UND']
        df_plan_compras['Peso_Compra'] = df_plan_compras['Sugerencia_Compra'] * df_plan_compras['Peso_Articulo']
        
        df_plan_compras_final = df_plan_compras[[
            'Almacen_Nombre', 'SKU', 'Descripcion', 'Segmento_ABC', 'Stock', 'Punto_Reorden', 'Sugerencia_Compra', 'Peso_Compra', 'Valor_Compra'
        ]].rename(columns={
            'Almacen_Nombre': 'Comprar para Tienda',
            'Sugerencia_Compra': 'Uds a Comprar',
            'Peso_Compra': 'Peso de la Compra (kg)',
            'Valor_Compra': 'Valor de la Compra'
        }).sort_values(by=['Valor_Compra', 'Segmento_ABC'], ascending=[False, True])

    excel_compras = generar_excel(df_plan_compras_final, "Plan de Compras")
    st.download_button("📥 Descargar Plan de Compras", excel_compras, "Plan_de_Compras.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if df_plan_compras_final.empty:
        st.success("¡No se requieren compras con los filtros actuales!")
    else:
        st.dataframe(df_plan_compras_final, hide_index=True, use_container_width=True,
            column_config={
                "Valor de la Compra": st.column_config.NumberColumn(format="$ %d"),
                "Peso de la Compra (kg)": st.column_config.NumberColumn(format="%.2f kg")
            })

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
