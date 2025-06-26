import streamlit as st
import pandas as pd
import io
import numpy as np

st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")
st.title("🚚 Gestión de Traslados y Compras")
st.markdown("Selecciona, planifica y ejecuta las acciones de abastecimiento para tu tienda.")

@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Plan')
    processed_data = output.getvalue()
    return processed_data

if 'df_analisis' in st.session_state:
    df_analisis_completo = st.session_state['df_analisis']
    
    if not df_analisis_completo.empty:
        lista_almacenes = sorted(df_analisis_completo['Almacen'].unique())
        selected_almacen = st.sidebar.selectbox("Selecciona tu Almacén:", lista_almacenes, key="sb_almacen_traslados")
        df_tienda = df_analisis_completo[df_analisis_completo['Almacen'] == selected_almacen]

        # --- MEJORA: Filtro por Marca también en esta página ---
        lista_marcas = sorted(df_tienda['Marca_Nombre'].unique())
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_gestion")
        
        if not selected_marcas:
            df_filtered = df_tienda
        else:
            df_filtered = df_tienda[df_tienda['Marca_Nombre'].isin(selected_marcas)]

        st.header("🔄 Plan de Traslados entre Tiendas", divider='blue')
        df_traslados = df_filtered[df_filtered['Unidades_Traslado_Sugeridas'] > 0].copy()
        
        if not df_traslados.empty:
            select_all_traslados = st.checkbox("Seleccionar Todos los Traslados", value=False, key="select_all_traslados")
            df_traslados['Ejecutar ✅'] = select_all_traslados
            columnas_traslado = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Marca_Nombre', 'Unidades_Traslado_Sugeridas', 'Peso_Traslado_Sugerido', 'Sugerencia_Traslado', 'Segmento_ABC']
            df_editado_traslados = st.data_editor(df_traslados[columnas_traslado], column_config={"Peso_Traslado_Sugerido": st.column_config.NumberColumn("Peso Total (kg)", format="%.2f kg")}, hide_index=True, use_container_width=True, key="editor_traslados")
            df_plan_traslado = df_editado_traslados[df_editado_traslados['Ejecutar ✅'] == True]
            if not df_plan_traslado.empty:
                st.subheader("Resumen del Plan de Traslado Seleccionado")
                total_unidades = df_plan_traslado['Unidades_Traslado_Sugeridas'].sum()
                total_peso = df_plan_traslado['Peso_Traslado_Sugerido'].sum()
                col1, col2 = st.columns(2)
                col1.metric(label="Total Unidades a Mover", value=f"{total_unidades}")
                col2.metric(label="⚖️ Peso Total Estimado", value=f"{total_peso:,.2f} kg")
                excel_traslados = to_excel(df_plan_traslado.drop(columns=['Ejecutar ✅']))
                st.download_button(label="📥 Descargar Plan de Traslado", data=excel_traslados, file_name=f"plan_traslado_{selected_almacen}.xlsx")
        else:
            st.success("¡Buenas noticias! No se sugieren traslados internos para tu tienda con los filtros actuales.", icon="🎉")

        st.header("🛒 Plan de Compras a Proveedor", divider='blue')
        df_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        if not df_compras.empty:
            select_all_compras = st.checkbox("Seleccionar Todas las Compras", value=False, key="select_all_compras")
            df_compras['Ejecutar ✅'] = select_all_compras
            columnas_compra = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Marca_Nombre', 'Sugerencia_Compra', 'Peso_Compra_Sugerida', 'Segmento_ABC']
            df_editado_compras = st.data_editor(df_compras[columnas_compra], column_config={"Peso_Compra_Sugerida": st.column_config.NumberColumn("Peso Total (kg)", format="%.2f kg")}, hide_index=True, use_container_width=True, key="editor_compras")
            df_plan_compra = df_editado_compras[df_editado_compras['Ejecutar ✅'] == True]
            if not df_plan_compra.empty:
                st.subheader("Resumen del Plan de Compra Seleccionado")
                total_unidades_compra = df_plan_compra['Sugerencia_Compra'].sum()
                valor_compra = (df_plan_compra['Sugerencia_Compra'] * df_plan_compra['Costo_Promedio_UND']).sum()
                total_peso_compra = df_plan_compra['Peso_Compra_Sugerida'].sum()
                col1, col2, col3 = st.columns(3)
                col1.metric(label="Total Unidades a Comprar", value=f"{total_unidades_compra}")
                col2.metric(label="Valor Estimado de la Compra", value=f"${valor_compra:,.0f}")
                col3.metric(label="⚖️ Peso Total Estimado", value=f"{total_peso_compra:,.2f} kg")
                excel_compras = to_excel(df_plan_compra.drop(columns=['Ejecutar ✅']))
                st.download_button(label="📥 Descargar Plan de Compra", data=excel_compras, file_name=f"plan_compra_{selected_almacen}.xlsx")
        else:
            st.success("No hay sugerencias de compra externa con los filtros actuales.", icon="🎉")
else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Plan de Acción de Inventario' primero.")
