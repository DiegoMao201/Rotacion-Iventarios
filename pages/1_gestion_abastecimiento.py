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
        opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
        nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
        map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
        lista_seleccion_nombres = [opcion_consolidado] + sorted(nombres_almacen['Almacen_Nombre'].unique())
        selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres, key="sb_almacen_gestion")
        
        if selected_almacen_nombre == opcion_consolidado:
            df_vista = df_analisis_completo
        else:
            codigo_almacen_seleccionado = map_nombre_a_codigo[selected_almacen_nombre]
            df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado]

        lista_marcas = sorted(df_vista['Marca_Nombre'].unique())
        selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas, default=lista_marcas, key="filtro_marca_gestion")
        
        if not selected_marcas:
            df_filtered = df_vista
        else:
            df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]

        st.header(f"Plan de Acción para: {selected_almacen_nombre}", divider='blue')

        st.subheader("🔄 Plan de Traslados entre Tiendas")
        df_traslados = df_filtered[df_filtered['Unidades_Traslado_Sugeridas'] > 0].copy()
        
        if not df_traslados.empty:
            # El resto de la lógica de esta página se mantiene, ya que los nombres se reflejarán automáticamente
            select_all_traslados = st.checkbox("Seleccionar Todos los Traslados", value=False, key="select_all_traslados")
            df_traslados['Ejecutar ✅'] = select_all_traslados
            columnas_traslado = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Marca_Nombre', 'Unidades_Traslado_Sugeridas', 'Peso_Traslado_Sugerido', 'Sugerencia_Traslado', 'Segmento_ABC']
            df_editado_traslados = st.data_editor(df_traslados[columnas_traslado], column_config={"Peso_Traslado_Sugerido": st.column_config.NumberColumn("Peso Total (kg)", format="%.2f kg")}, hide_index=True, use_container_width=True, key="editor_traslados")
            df_plan_traslado = df_editado_traslados[df_editado_traslados['Ejecutar ✅'] == True]
            if not df_plan_traslado.empty:
                st.text("Resumen del Plan de Traslado Seleccionado")
                total_unidades = df_plan_traslado['Unidades_Traslado_Sugeridas'].sum()
                total_peso = df_plan_traslado['Peso_Traslado_Sugerido'].sum()
                col1, col2 = st.columns(2)
                col1.metric(label="Total Unidades a Mover", value=f"{total_unidades}")
                col2.metric(label="⚖️ Peso Total Estimado", value=f"{total_peso:,.2f} kg")
                excel_traslados = to_excel(df_plan_traslado.drop(columns=['Ejecutar ✅']))
                st.download_button(label="📥 Descargar Plan de Traslado", data=excel_traslados, file_name=f"plan_traslado_{selected_almacen_nombre}.xlsx")
        else:
            st.success("¡Buenas noticias! No se sugieren traslados internos con los filtros actuales.", icon="🎉")

        st.subheader("🛒 Plan de Compras a Proveedor")
        # (El resto de la página de compras se mantiene igual)
        df_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        if not df_compras.empty:
            select_all_compras = st.checkbox("Seleccionar Todas las Compras", value=False, key="select_all_compras")
            df_compras['Ejecutar ✅'] = select_all_compras
            columnas_compra = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Marca_Nombre', 'Sugerencia_Compra', 'Peso_Compra_Sugerida', 'Segmento_ABC']
            df_editado_compras = st.data_editor(df_compras[columnas_compra], column_config={"Peso_Compra_Sugerida": st.column_config.NumberColumn("Peso Total (kg)", format="%.2f kg")}, hide_index=True, use_container_width=True, key="editor_compras")
            df_plan_compra = df_editado_compras[df_editado_compras['Ejecutar ✅'] == True]
            if not df_plan_compra.empty:
                st.text("Resumen del Plan de Compra Seleccionado")
                total_unidades_compra = df_plan_compra['Sugerencia_Compra'].sum()
                valor_compra = (df_plan_compra['Sugerencia_Compra'] * df_plan_compra['Costo_Promedio_UND']).sum()
                total_peso_compra = df_plan_compra['Peso_Compra_Sugerida'].sum()
                col1, col2, col3 = st.columns(3)
                col1.metric(label="Total Unidades a Comprar", value=f"{total_unidades_compra}")
                col2.metric(label="Valor Estimado de la Compra", value=f"${valor_compra:,.0f}")
                col3.metric(label="⚖️ Peso Total Estimado", value=f"{total_peso_compra:,.2f} kg")
                excel_compras = to_excel(df_plan_compra.drop(columns=['Ejecutar ✅']))
                st.download_button(label="📥 Descargar Plan de Compra", data=excel_compras, file_name=f"plan_compra_{selected_almacen_nombre}.xlsx")
        else:
            st.success("No hay sugerencias de compra externa con los filtros actuales.", icon="🎉")
else:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal 'Resumen Ejecutivo de Inventario' primero.")
