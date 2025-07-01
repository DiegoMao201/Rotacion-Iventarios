import streamlit as st
import pandas as pd
import numpy as np
import io

st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")

st.title("🚚 Gestión de Abastecimiento y Plan de Traslados")
st.markdown("Revisa las necesidades de compra y coordina los traslados entre tiendas para optimizar el inventario.")

# --- FUNCIÓN DE EXCEL CORREGIDA ---
@st.cache_data
def generar_excel_plan_traslados(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_interno = df.copy()
        
        # Si el dataframe está vacío, escribe un mensaje en el Excel y sal.
        if df_interno.empty:
            df_vacio = pd.DataFrame([{'Notificación': "No se encontraron sugerencias de traslado con los filtros actuales."}])
            df_vacio.to_excel(writer, index=False, sheet_name='Plan_de_Traslados')
            worksheet = writer.sheets['Plan_de_Traslados']
            worksheet.set_column('A:A', 70)
        else:
            # Procede con la lógica normal si hay datos
            df_interno.to_excel(writer, index=False, sheet_name='Plan_de_Traslados')
            workbook = writer.book
            worksheet = writer.sheets['Plan_de_Traslados']
            header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
            money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
            default_format = workbook.add_format({'border': 1})
            
            for col_num, value in enumerate(df_interno.columns.values):
                worksheet.write(0, col_num, value, header_format)
            
            worksheet.conditional_format('A1:Z' + str(len(df_interno) + 1), {'type': 'no_blanks', 'format': default_format})
            worksheet.set_column('C:C', 45) # Descripcion
            worksheet.set_column('D:F', 25) # Origen, Destino, Unidades
    
    return output.getvalue()


# --- LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis' in st.session_state and not st.session_state['df_analisis'].empty:
    df_analisis_completo = st.session_state['df_analisis']

    st.header("🔄 Plan de Traslados entre Tiendas")
    st.info("Vista consolidada. Aquí puedes ver todos los traslados sugeridos para balancear el inventario en la red de tiendas.")

    # 1. Crear el DF de sugerencias
    df_origen = df_analisis_completo[df_analisis_completo['Unidades_Traslado_Sugeridas'] > 0]
    df_destino = df_analisis_completo[df_analisis_completo['Necesidad_Total'] > 0]
    
    df_plan_traslados = pd.DataFrame() # DF vacío por si no hay traslados

    if not df_origen.empty and not df_destino.empty:
        # Usamos el mismo cálculo para encontrar el mejor destino
        idx_max_necesidad = df_destino.groupby('SKU')['Necesidad_Total'].idxmax()
        df_mejor_destino = df_destino.loc[idx_max_necesidad][['SKU', 'Almacen_Nombre']]
        df_mejor_destino.rename(columns={'Almacen_Nombre': 'Tienda_Destino_Sugerida'}, inplace=True)
        
        # Unimos esta información a los posibles orígenes
        df_plan = pd.merge(df_origen, df_mejor_destino, on='SKU', how='inner')
        
        # Limpieza final
        df_plan = df_plan[df_plan['Almacen_Nombre'] != df_plan['Tienda_Destino_Sugerida']]
        df_plan['Unidades_a_Enviar'] = np.minimum(df_plan['Unidades_Traslado_Sugeridas'], df_plan['Necesidad_Total']).astype(int)

        if not df_plan.empty:
            df_plan_traslados = df_plan[[
                'SKU', 'Descripcion', 'Marca_Nombre', 'Almacen_Nombre', 'Tienda_Destino_Sugerida', 'Unidades_a_Enviar'
            ]].rename(columns={
                'Almacen_Nombre': 'Tienda Origen (con Excedente)',
                'Tienda_Destino_Sugerida': 'Tienda Destino (con Necesidad)',
                'Unidades_a_Enviar': 'Unidades Sugeridas a Enviar'
            }).sort_values(by='SKU')

    # 2. Botón de Descarga (Siempre visible)
    excel_data = generar_excel_plan_traslados(df_plan_traslados)
    st.download_button(
        label="📥 Descargar Plan de Traslados Completo",
        data=excel_data,
        file_name="Plan_Maestro_de_Traslados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # 3. Mostrar la tabla en la App
    if df_plan_traslados.empty:
        st.success("¡Excelente! No se requieren traslados en este momento. El inventario está balanceado.")
    else:
        st.dataframe(df_plan_traslados, hide_index=True, use_container_width=True)

else:
    st.error("🔴 Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
