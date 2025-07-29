import streamlit as st
import pandas as pd
import numpy as np
import io
import math

# --- Configuración de la Página ---
st.set_page_config(page_title="Gestión de Quiebres de Stock", layout="wide", page_icon="🚀")

# --- Título y Descripción ---
st.title("🚀 Tablero de Control y Acción para Quiebres de Stock")
st.markdown("""
Esta herramienta te permite no solo identificar productos agotados, sino también **gestionar activamente el plan de reabastecimiento**.
Prioriza traslados internos para ahorrar costos y utiliza una lógica de pedido inteligente para optimizar las compras a proveedores.
**¡Gestiona, edita y exporta tu plan de acción directamente desde este tablero!**
""")

# --- Funciones Auxiliares ---

def determinar_uem_y_ajustar_cantidad(row):
    """
    Determina la Unidad de Empaque (UEM) basada en la descripción y ajusta la cantidad a solicitar.
    - Contiene '0.94' o hasta '3.0' en descripción -> UEM = 9
    - Contiene '3.7' en descripción -> UEM = 4
    - Contiene '9.4' o superior, o no aplica -> UEM = 1 (se pide la cantidad exacta)
    """
    descripcion = row['Descripcion'].lower()
    necesidad = row['Necesidad_Total']
    uem = 1 # Unidad de empaque por defecto

    # Lógica para determinar la UEM
    if any(s in descripcion for s in ['0.94', ' 1.', ' 2.']): # Asumiendo formatos como "GALON 0.94L"
        uem = 9
    elif '3.7' in descripcion: # Asumiendo formatos como "GALON 3.7L"
        uem = 4
    # Para los demás casos, la UEM es 1 (se pide la cantidad exacta o ya viene en unidad)

    if uem > 1:
        # Si se necesita más que 0, calcular el siguiente múltiplo de la UEM
        # math.ceil(necesidad / uem) calcula cuántos "paquetes" se necesitan
        # Luego, se multiplica por la UEM para obtener la cantidad total de unidades
        return math.ceil(necesidad / uem) * uem
    else:
        # Si la UEM es 1, simplemente se redondea hacia arriba la necesidad
        return math.ceil(necesidad)

def generar_excel_quiebres(df):
    """Crea un archivo Excel profesional y formateado para el plan de acción de quiebres."""
    output = io.BytesIO()
    # Asegurarse de que no se exporte la columna de selección
    df_export = df.drop(columns=['✔️ Seleccionar'], errors='ignore')
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Plan_Accion_Quiebres', startrow=1)
        
        workbook = writer.book
        worksheet = writer.sheets['Plan_Accion_Quiebres']

        # Formatos
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#C00000', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '$#,##0', 'border': 1})
        traslado_format = workbook.add_format({'bg_color': '#E2EFDA', 'border': 1}) # Verde
        compra_format = workbook.add_format({'bg_color': '#DEEBF7', 'border': 1}) # Azul

        # Escribir cabeceras con formato
        for col_num, value in enumerate(df_export.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Aplicar formato condicional a la columna de Acción Sugerida
        try:
            col_idx_accion = df_export.columns.get_loc('Acción Sugerida') + 1 # +1 para formato de Excel (1-based)
            worksheet.conditional_format(1, col_idx_accion - 1, len(df_export), col_idx_accion - 1,
                                         {'type': 'cell', 'criteria': '==', 'value': '"Solicitar Traslado"', 'format': traslado_format})
            worksheet.conditional_format(1, col_idx_accion - 1, len(df_export), col_idx_accion - 1,
                                         {'type': 'cell', 'criteria': '==', 'value': '"Generar Orden de Compra"', 'format': compra_format})
        except KeyError:
            pass # Si la columna no existe, no se aplica el formato.

        # Aplicar formato a columnas de valor y unidades
        try:
            col_idx_valor = df_export.columns.get_loc('Valor Requerido')
            worksheet.set_column(col_idx_valor, col_idx_valor, 15, money_format)
        except KeyError:
            pass

        # Ajustar ancho de columnas
        for i, col in enumerate(df_export.columns):
            width = max(df_export[col].astype(str).map(len).max(), len(col)) + 3
            worksheet.set_column(i, i, min(width, 40))

    return output.getvalue()


def preparar_plan_quiebres(df_maestro, almacen_seleccionado):
    """Analiza los quiebres y genera un plan de acción con sugerencias inteligentes."""
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
    mejor_origen_map = df_excedentes.sort_values('Excedente_Trasladable', ascending=False).drop_duplicates('SKU').set_index('SKU')

    # 3. Generar el plan de acción
    plan_list = []
    for _, row in df_quiebres.iterrows():
        sku = row['SKU']
        accion = "Generar Orden de Compra"
        origen = "Proveedor"

        # Aplicar la lógica de UEM para obtener la cantidad sugerida
        uds_a_solicitar = determinar_uem_y_ajustar_cantidad(row)

        if sku in mejor_origen_map.index:
            excedente_info = mejor_origen_map.loc[sku]
            # Solo sugerir traslado si la tienda de origen es DIFERENTE a la afectada
            if excedente_info['Almacen_Nombre'] != row['Almacen_Nombre']:
                accion = "Solicitar Traslado"
                origen = excedente_info['Almacen_Nombre']
        
        plan_list.append({
            "✔️ Seleccionar": True, # Columna para el checkbox, por defecto todo seleccionado
            "Tienda Afectada": row['Almacen_Nombre'],
            "SKU": sku,
            "Descripción": row['Descripcion'],
            "Acción Sugerida": accion,
            "Tienda Origen / Proveedor": origen,
            "Uds. a Solicitar": uds_a_solicitar,
            "Valor Requerido": uds_a_solicitar * row['Costo_Promedio_UND'],
            "Clase ABC": row['Segmento_ABC'],
            "Marca": row['Marca_Nombre'],
            # Se asume que 'Proveedor_Nombre' existe en el df_maestro. Si no, comentar la línea.
            "Proveedor": row.get('Proveedor_Nombre', 'No definido')
        })

    if not plan_list:
        return pd.DataFrame()

    df_plan = pd.DataFrame(plan_list)
    return df_plan.sort_values(by=['Valor Requerido', 'Clase ABC'], ascending=[False, True])


# --- Lógica Principal de la Página ---

if 'df_analisis_maestro' not in st.session_state or st.session_state.get('df_analisis_maestro', pd.DataFrame()).empty:
    st.error("🔴 Los datos no se han cargado. Por favor, vuelve a la página principal y carga el archivo maestro.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop()

df_maestro = st.session_state['df_analisis_maestro']

# --- Barra Lateral de Filtros ---
st.sidebar.header("Filtros del Plan de Acción")

if st.session_state.get('user_role') == 'gerente':
    opciones_almacen = ["Consolidado"] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    almacen_sel = st.sidebar.selectbox("Seleccionar Vista de Tienda", opciones_almacen, key="almacen_selector")
else:
    almacen_sel = st.session_state.get('almacen_nombre')
    st.sidebar.info(f"Mostrando quiebres para tu tienda: **{almacen_sel}**")

# Generar el plan base
df_plan = preparar_plan_quiebres(df_maestro, almacen_sel)

# Filtrado adicional por Clase, Marca y Proveedor
if not df_plan.empty:
    clases_abc = sorted(df_plan['Clase ABC'].unique().tolist())
    marcas = sorted(df_plan['Marca'].unique().tolist())
    proveedores = sorted(df_plan['Proveedor'].unique().tolist())

    clase_sel = st.sidebar.multiselect("Filtrar por Clase ABC", clases_abc, default=clases_abc)
    marca_sel = st.sidebar.multiselect("Filtrar por Marca", marcas, default=marcas)
    proveedor_sel = st.sidebar.multiselect("Filtrar por Proveedor", proveedores, default=proveedores)

    df_plan_filtrado = df_plan[
        df_plan['Clase ABC'].isin(clase_sel) &
        df_plan['Marca'].isin(marca_sel) &
        df_plan['Proveedor'].isin(proveedor_sel)
    ]
else:
    df_plan_filtrado = pd.DataFrame()

# --- Mostrar Resultados en la UI ---

if df_plan_filtrado.empty:
    st.success(f"🎉 ¡Felicidades! No hay quiebres de stock para la selección actual: **{almacen_sel}**.")
    st.balloons()
else:
    # Definir las pestañas de análisis
    tab1, tab2, tab3, tab4 = st.tabs([
        "📝 **Plan de Acción Interactivo**",
        "🚚 **Resumen por Proveedor**",
        "🏷️ **Resumen por Marca**",
        "🔄 **Resumen de Traslados**"
    ])

    with tab1:
        st.markdown("### Gestiona tu Plan de Acción")
        st.info("Usa los checkboxes para seleccionar filas. Edita las cantidades o acciones directamente en la tabla. Los KPIs y la descarga se actualizarán automáticamente.")

        # --- Editor de Datos Interactivo ---
        edited_df = st.data_editor(
            df_plan_filtrado,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="plan_editor",
            column_config={
                "✔️ Seleccionar": st.column_config.CheckboxColumn(required=True),
                "Valor Requerido": st.column_config.NumberColumn(format="$ {:,.0f}"),
                "Uds. a Solicitar": st.column_config.NumberColumn(format="%d Uds.", min_value=0, step=1),
                "Acción Sugerida": st.column_config.SelectboxColumn("Acción", options=["Generar Orden de Compra", "Solicitar Traslado"]),
            },
            # Deshabilitar la edición de columnas que no deben ser cambiadas
            disabled=["SKU", "Descripción", "Tienda Afectada", "Clase ABC", "Marca", "Proveedor", "Valor Requerido"]
        )
        
        # Filtrar el dataframe basado en las selecciones del usuario
        df_seleccionado = edited_df[edited_df['✔️ Seleccionar'] == True]

        st.markdown("---")
        st.markdown("### Resumen del Plan Seleccionado")

        # --- KPIs Dinámicos ---
        if not df_seleccionado.empty:
            total_skus = df_seleccionado['SKU'].nunique()
            # Recalcular el valor requerido basado en las cantidades editadas
            df_seleccionado['Valor Requerido'] = df_seleccionado['Uds. a Solicitar'] * df_seleccionado.apply(
                lambda row: df_maestro.loc[df_maestro['SKU'] == row['SKU'], 'Costo_Promedio_UND'].iloc[0], axis=1
            )
            valor_total_requerido = df_seleccionado['Valor Requerido'].sum()
            valor_compra = df_seleccionado[df_seleccionado['Acción Sugerida'] == 'Generar Orden de Compra']['Valor Requerido'].sum()
            valor_traslado = df_seleccionado[df_seleccionado['Acción Sugerida'] == 'Solicitar Traslado']['Valor Requerido'].sum()

            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("SKUs Seleccionados", f"{total_skus}")
            kpi2.metric("Valor Total Requerido", f"${valor_total_requerido:,.0f}")
            kpi3.metric("Valor a Comprar", f"${valor_compra:,.0f}", help="Valor total de los productos marcados para compra a proveedor.")
            kpi4.metric("Valor a Trasladar", f"${valor_traslado:,.0f}", delta_color="off", help="Ahorro potencial al evitar compras y usar stock existente de otras tiendas.")

            # --- Botón de Descarga ---
            excel_data = generar_excel_quiebres(df_seleccionado)
            st.download_button(
                label="📥 Descargar Plan de Acción SELECCIONADO en Excel",
                data=excel_data,
                file_name=f"Plan_Accion_Quiebres_{almacen_sel.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.warning("⚠️ No has seleccionado ningún producto para incluir en el plan de acción.")

    # --- Lógica de las Pestañas de Resumen ---
    df_resumen = edited_df[edited_df['✔️ Seleccionar'] == True]
    if not df_resumen.empty:
        # Recalcular valor por si hubo ediciones
        df_resumen['Valor Requerido'] = df_resumen['Uds. a Solicitar'] * df_resumen.apply(
            lambda row: df_maestro.loc[df_maestro['SKU'] == row['SKU'], 'Costo_Promedio_UND'].iloc[0], axis=1
        )
        
        with tab2: # Resumen por Proveedor
            st.header("🚚 Resumen para Órdenes de Compra por Proveedor")
            df_compras = df_resumen[df_resumen['Acción Sugerida'] == 'Generar Orden de Compra']
            if not df_compras.empty:
                resumen_proveedor = df_compras.groupby('Proveedor').agg(
                    Valor_Total_Compra=('Valor Requerido', 'sum'),
                    SKUs_Distintos=('SKU', 'nunique')
                ).reset_index().sort_values('Valor_Total_Compra', ascending=False)

                st.dataframe(resumen_proveedor, use_container_width=True, hide_index=True,
                             column_config={"Valor_Total_Compra": st.column_config.NumberColumn(format="$ {:,.0f}")})
                
                st.bar_chart(resumen_proveedor.set_index('Proveedor'), y='Valor_Total_Compra')
            else:
                st.info("No hay acciones de 'Generar Orden de Compra' en tu selección actual.")

        with tab3: # Resumen por Marca
            st.header("🏷️ Resumen de Requerimientos por Marca")
            resumen_marca = df_resumen.groupby('Marca').agg(
                Valor_Total_Requerido=('Valor Requerido', 'sum'),
                SKUs_Distintos=('SKU', 'nunique')
            ).reset_index().sort_values('Valor_Total_Requerido', ascending=False)
            
            st.dataframe(resumen_marca, use_container_width=True, hide_index=True,
                         column_config={"Valor_Total_Requerido": st.column_config.NumberColumn(format="$ {:,.0f}")})
            
            st.bar_chart(resumen_marca.set_index('Marca'), y='Valor_Total_Requerido')

        with tab4: # Resumen de Traslados
            st.header("🔄 Resumen para Solicitudes de Traslado entre Tiendas")
            df_traslados = df_resumen[df_resumen['Acción Sugerida'] == 'Solicitar Traslado']
            if not df_traslados.empty:
                resumen_traslados = df_traslados.groupby(['Tienda Origen / Proveedor', 'Tienda Afectada']).agg(
                    Valor_Total_Traslado=('Valor Requerido', 'sum'),
                    SKUs_A_Trasladar=('SKU', 'nunique'),
                    Uds_A_Trasladar=('Uds. a Solicitar', 'sum')
                ).reset_index().sort_values('Valor_Total_Traslado', ascending=False)
                
                st.dataframe(resumen_traslados, use_container_width=True, hide_index=True,
                             column_config={
                                 "Valor_Total_Traslado": st.column_config.NumberColumn(format="$ {:,.0f}"),
                                 "Uds_A_Trasladar": st.column_config.NumberColumn(format="%d Uds.")
                             })
            else:
                st.info("No hay acciones de 'Solicitar Traslado' en tu selección actual.")
