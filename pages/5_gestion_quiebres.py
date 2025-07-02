import streamlit as st
import pandas as pd
import numpy as np
import io

st.set_page_config(page_title="Gestión de Quiebres de Stock", layout="wide", page_icon="🩹")

st.title("🩹 Plan de Acción para Quiebres de Stock")
st.markdown("Identifica los productos agotados y obtén un plan claro para reabastecerlos, priorizando traslados sobre compras.")

# --- Funciones Auxiliares ---

def generar_excel_quiebres(df):
    """Crea un archivo Excel profesional y formateado para el plan de acción de quiebres."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Plan_Accion_Quiebres', startrow=1)
        
        workbook = writer.book
        worksheet = writer.sheets['Plan_Accion_Quiebres']

        # Formatos
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#C00000', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        traslado_format = workbook.add_format({'bg_color': '#E2EFDA', 'border': 1}) # Verde para Traslado
        compra_format = workbook.add_format({'bg_color': '#DEEBF7', 'border': 1}) # Azul para Compra

        # Escribir cabeceras con formato
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Aplicar formato condicional
        worksheet.conditional_format('D2:D{}'.format(len(df) + 1), {'type': 'text', 'criteria': 'containing', 'value': 'Traslado', 'format': traslado_format})
        worksheet.conditional_format('D2:D{}'.format(len(df) + 1), {'type': 'text', 'criteria': 'containing', 'value': 'Compra', 'format': compra_format})

        # Aplicar formato a columnas de valor
        col_idx = df.columns.get_loc('Valor Requerido')
        worksheet.set_column(col_idx, col_idx, 15, money_format)

        # Ajustar ancho de columnas
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 3
            worksheet.set_column(i, i, min(width, 40))

    return output.getvalue()

def preparar_plan_quiebres(df_maestro, almacen_seleccionado):
    """Analiza los quiebres y genera un plan de acción con sugerencias de traslado o compra."""
    if df_maestro is None or df_maestro.empty:
        return pd.DataFrame()

    # 1. Filtrar los productos en quiebre para la tienda(s) seleccionada(s)
    if almacen_seleccionado != "Consolidado":
        df_quiebres = df_maestro[(df_maestro['Almacen_Nombre'] == almacen_seleccionado) & (df_maestro['Estado_Inventario'] == 'Quiebre de Stock')].copy()
    else:
        df_quiebres = df_maestro[df_maestro['Estado_Inventario'] == 'Quiebre de Stock'].copy()

    if df_quiebres.empty:
        return pd.DataFrame()

    # 2. Encontrar todos los excedentes trasladables en TODAS las tiendas
    df_excedentes = df_maestro[df_maestro['Excedente_Trasladable'] > 0].copy()
    
    # Mapa para encontrar la mejor tienda de origen (la que más excedente tiene de un SKU)
    mejor_origen_map = df_excedentes.sort_values('Excedente_Trasladable', ascending=False).drop_duplicates('SKU').set_index('SKU')
    
    # 3. Generar el plan de acción
    plan_list = []
    for _, row in df_quiebres.iterrows():
        sku = row['SKU']
        necesidad = np.ceil(row['Necesidad_Total'])
        
        accion = "Generar Orden de Compra"
        origen = "-"
        
        if sku in mejor_origen_map.index:
            # Si hay excedente en alguna tienda, la acción es trasladar
            excedente_info = mejor_origen_map.loc[sku]
            accion = "Solicitar Traslado"
            origen = excedente_info['Almacen_Nombre']
        
        plan_list.append({
            "Tienda Afectada": row['Almacen_Nombre'],
            "SKU": sku,
            "Descripción": row['Descripcion'],
            "Acción Sugerida": accion,
            "Tienda Origen Sugerida": origen,
            "Uds. a Solicitar": necesidad,
            "Valor Requerido": necesidad * row['Costo_Promedio_UND'],
            "Clase ABC": row['Segmento_ABC'],
            "Marca": row['Marca_Nombre']
        })

    if not plan_list:
        return pd.DataFrame()

    df_plan = pd.DataFrame(plan_list)
    return df_plan.sort_values(by=['Valor Requerido', 'Clase ABC'], ascending=[False, True])


# --- Lógica Principal de la Página ---

if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.error("🔴 Los datos no se han cargado. Por favor, vuelve a la página principal.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop()

df_maestro = st.session_state['df_analisis_maestro']

# --- Filtros en la Barra Lateral ---
st.sidebar.header("Filtros del Plan de Acción")

if st.session_state.get('user_role') == 'gerente':
    opciones_almacen = ["Consolidado"] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    almacen_sel = st.sidebar.selectbox("Seleccionar Vista de Tienda", opciones_almacen)
else:
    almacen_sel = st.session_state.get('almacen_nombre')
    st.sidebar.info(f"Mostrando quiebres para tu tienda: **{almacen_sel}**")

# Preparar el plan basado en la selección
df_plan = preparar_plan_quiebres(df_maestro, almacen_sel)

# Filtrado adicional por Clase y Marca
if not df_plan.empty:
    clases_abc = sorted(df_plan['Clase ABC'].unique().tolist())
    marcas = sorted(df_plan['Marca'].unique().tolist())
    
    clase_sel = st.sidebar.multiselect("Filtrar por Clase ABC", clases_abc, default=clases_abc)
    marca_sel = st.sidebar.multiselect("Filtrar por Marca", marcas, default=marcas)
    
    df_plan_filtrado = df_plan[df_plan['Clase ABC'].isin(clase_sel) & df_plan['Marca'].isin(marca_sel)]
else:
    df_plan_filtrado = pd.DataFrame()


# --- Mostrar Resultados en la UI ---

if df_plan_filtrado.empty:
    st.success(f"🎉 ¡Felicidades! No hay quiebres de stock para la selección actual: **{almacen_sel}**.")
else:
    # KPIs del plan de acción
    st.markdown("### Resumen del Plan de Acción")
    total_skus = df_plan_filtrado['SKU'].nunique()
    valor_total_requerido = df_plan_filtrado['Valor Requerido'].sum()
    valor_compra = df_plan_filtrado[df_plan_filtrado['Acción Sugerida'] == 'Generar Orden de Compra']['Valor Requerido'].sum()
    valor_traslado = df_plan_filtrado[df_plan_filtrado['Acción Sugerida'] == 'Solicitar Traslado']['Valor Requerido'].sum()

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("SKUs en Quiebre", f"{total_skus}")
    kpi2.metric("Valor Total Requerido", f"${valor_total_requerido:,.0f}")
    kpi3.metric("Valor a Comprar", f"${valor_compra:,.0f}")
    kpi4.metric("Valor a Trasladar", f"${valor_traslado:,.0f}", help="Ahorro potencial al evitar compras y usar stock existente.")

    st.markdown("---")
    
    # Botón de descarga del Excel
    excel_data = generar_excel_quiebres(df_plan_filtrado)
    st.download_button(
        label="📥 Descargar Plan de Acción en Excel",
        data=excel_data,
        file_name=f"Plan_Accion_Quiebres_{almacen_sel.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Mostrar tabla del plan
    st.dataframe(
        df_plan_filtrado,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Valor Requerido": st.column_config.NumberColumn(format="$ %d"),
            "Uds. a Solicitar": st.column_config.NumberColumn(format="%d Uds.")
        }
    )
