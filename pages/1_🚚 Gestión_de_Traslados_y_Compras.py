import streamlit as st
import pandas as pd
import io
from streamlit_extras.dataframe_explorer import dataframe_explorer

# Re-importar funciones de análisis (asumiendo que están en el script principal)
from app_inventario_consolidado import analizar_inventario_completo, cargar_datos_desde_dropbox

st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")

st.title("🚚 Gestión de Traslados y Compras")
st.markdown("Selecciona, planifica y ejecuta las acciones de abastecimiento para tu tienda.")

# --- Función para convertir a Excel ---
@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Plan')
    processed_data = output.getvalue()
    return processed_data

# --- Carga y Filtrado de Datos ---
df_crudo = cargar_datos_desde_dropbox()
if df_crudo is not None and not df_crudo.empty:
    almacen_principal_input = st.sidebar.text_input("Código Almacén Principal/Bodega:", '155')
    df_analisis_completo = analizar_inventario_completo(df_crudo, almacen_principal_input)

    if not df_analisis_completo.empty:
        lista_almacenes = sorted(df_analisis_completo['Almacen'].unique())
        selected_almacen = st.sidebar.selectbox("Selecciona tu Almacén:", lista_almacenes, key="sb_almacen_traslados")
        
        df_tienda = df_analisis_completo[df_analisis_completo['Almacen'] == selected_almacen]

        # --- SECCIÓN 1: SUGERENCIAS DE TRASLADO INTERNO ---
        st.header("🔄 Plan de Traslados entre Tiendas", divider='blue')
        
        df_traslados = df_tienda[df_tienda['Unidades_Traslado_Sugeridas'] > 0].copy()
        
        if not df_traslados.empty:
            df_traslados['Ejecutar ✅'] = False
            columnas_traslado = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Stock', 'Punto_Reorden', 'Unidades_Traslado_Sugeridas', 'Segmento_ABC']
            
            st.info("Marca los traslados que deseas ejecutar. El plan se actualizará dinámicamente.", icon="✍️")
            
            df_editado_traslados = st.data_editor(
                df_traslados[columnas_traslado],
                hide_index=True,
                use_container_width=True,
                disabled=['SKU', 'Descripcion', 'Stock', 'Punto_Reorden', 'Unidades_Traslado_Sugeridas', 'Segmento_ABC']
            )

            df_plan_traslado = df_editado_traslados[df_editado_traslados['Ejecutar ✅'] == True]

            if not df_plan_traslado.empty:
                st.subheader("Resumen del Plan de Traslado Seleccionado")
                total_unidades = df_plan_traslado['Unidades_Traslado_Sugeridas'].sum()
                total_skus = df_plan_traslado['SKU'].nunique()
                st.metric(label="Total Unidades a Mover", value=f"{total_unidades}")
                
                excel_traslados = to_excel(df_plan_traslado)
                st.download_button(
                    label="📥 Descargar Plan de Traslado a Excel",
                    data=excel_traslados,
                    file_name=f"plan_traslado_{selected_almacen}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.success("¡Buenas noticias! No se sugieren traslados internos para tu tienda en este momento.", icon="🎉")

        # --- SECCIÓN 2: SUGERENCIAS DE COMPRA EXTERNA ---
        st.header("🛒 Plan de Compras a Proveedor", divider='blue')
        df_compras = df_tienda[df_tienda['Sugerencia_Compra'] > 0].copy()

        if not df_compras.empty:
            df_compras['Ejecutar ✅'] = False
            columnas_compra = ['Ejecutar ✅', 'SKU', 'Descripcion', 'Stock', 'Punto_Reorden', 'Sugerencia_Compra', 'Segmento_ABC']
            st.info("Estos SKUs no tienen stock disponible en otras tiendas. Marca los que deseas incluir en la próxima orden de compra.", icon="✍️")

            df_editado_compras = st.data_editor(
                df_compras[columnas_compra],
                hide_index=True,
                use_container_width=True,
                disabled=['SKU', 'Descripcion', 'Stock', 'Punto_Reorden', 'Sugerencia_Compra', 'Segmento_ABC']
            )

            df_plan_compra = df_editado_compras[df_editado_compras['Ejecutar ✅'] == True]

            if not df_plan_compra.empty:
                st.subheader("Resumen del Plan de Compra Seleccionado")
                total_unidades_compra = df_plan_compra['Sugerencia_Compra'].sum()
                valor_compra = (df_plan_compra['Sugerencia_Compra'] * df_plan_compra['Costo_Promedio_UND']).sum()

                col1, col2 = st.columns(2)
                col1.metric(label="Total Unidades a Comprar", value=f"{total_unidades_compra}")
                col2.metric(label="Valor Estimado de la Compra", value=f"${valor_compra:,.0f}")
                
                excel_compras = to_excel(df_plan_compra)
                st.download_button(
                    label="📥 Descargar Plan de Compra a Excel",
                    data=excel_compras,
                    file_name=f"plan_compra_{selected_almacen}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.success("No hay sugerencias de compra externa en este momento.", icon="🎉")

    else:
        st.warning("No se pudo realizar el análisis. Datos no disponibles.")
else:
    st.error("No se pudieron cargar los datos de Dropbox.")
