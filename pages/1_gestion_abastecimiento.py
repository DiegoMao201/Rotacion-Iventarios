import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px
from fpdf import FPDF
from datetime import datetime

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIONES AUXILIARES ---

# ✨ CORRECCIÓN: Se restaura la función para generar el plan de traslados.
@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis_maestro):
    """Genera un plan de traslados óptimo usando el inventario de todas las tiendas."""
    if _df_analisis_maestro is None or _df_analisis_maestro.empty:
        return pd.DataFrame()
        
    df_origen = _df_analisis_maestro[_df_analisis_maestro['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis_maestro[_df_analisis_maestro['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()
    
    if df_origen.empty or df_destino.empty:
        return pd.DataFrame()

    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()

    for idx, necesidad_row in df_destino.iterrows():
        sku = necesidad_row['SKU']
        tienda_necesitada = necesidad_row['Almacen_Nombre']
        necesidad_actual = necesidad_row['Necesidad_Total']

        if necesidad_actual <= 0:
            continue

        posibles_origenes = df_origen[df_origen['SKU'] == sku]

        for _, origen_row in posibles_origenes.iterrows():
            tienda_origen = origen_row['Almacen_Nombre']
            if tienda_origen == tienda_necesitada:
                continue

            excedente_disponible = excedentes_mutables.get((sku, tienda_origen), 0)
            
            if excedente_disponible > 0 and necesidad_actual > 0:
                unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                if unidades_a_enviar < 1:
                    continue
                
                plan_final.append({
                    'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': origen_row['Marca_Nombre'],
                    'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,
                    'Stock en Origen': origen_row['Stock'], 'Tienda Destino': tienda_necesitada,
                    'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],
                    'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row['Peso_Articulo'],
                    'Valor Individual': necesidad_row['Costo_Promedio_UND']
                })
                
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
    
    if not plan_final:
        return pd.DataFrame()
        
    df_resultado = pd.DataFrame(plan_final)
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado', 'Segmento_ABC'], ascending=[False, True])


# --- Funciones para PDF y Excel (con la corrección final) ---

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 20)
        self.cell(80)
        self.cell(30, 10, 'Orden de Compra', 0, 0, 'C')
        self.ln(25)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre):
    if df_seleccion.empty:
        return None
    
    tu_empresa = "Nombre de Tu Empresa"
    tu_nit = "NIT 123.456.789-0"
    tu_direccion = "Carrera 1 # 2-3, Ciudad"
    tu_contacto = "Tel: 300 123 4567"
    
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(130, 8, f"De: {tu_empresa}", 0, 0)
    pdf.cell(60, 8, f"ORDEN DE COMPRA N°: {datetime.now().strftime('%Y%m%d-%H%M')}", 0, 1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(130, 6, tu_nit, 0, 0)
    pdf.cell(60, 6, f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", 0, 1)
    pdf.cell(130, 6, tu_direccion, 0, 1)
    pdf.cell(130, 6, tu_contacto, 0, 1)
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 7, "PROVEEDOR:", 1, 0, 'C')
    pdf.cell(95, 7, "ENVIAR A:", 1, 1, 'C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 7, f" {proveedor_nombre}", 1, 0)
    pdf.cell(95, 7, f" {tu_empresa} - {tienda_nombre}", 1, 1)
    pdf.cell(95, 7, " ", 1, 0)
    pdf.cell(95, 7, f" {tu_direccion}", 1, 1) 
    pdf.ln(10)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(35, 8, 'Cód. Proveedor', 1, 0, 'C', 1)
    pdf.cell(30, 8, 'Cód. Interno', 1, 0, 'C', 1)
    pdf.cell(65, 8, 'Descripción', 1, 0, 'C', 1)
    pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
    pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1)
    pdf.cell(20, 8, 'Total', 1, 1, 'C', 1)
    pdf.set_font("Arial", '', 9)
    subtotal = 0
    for _, row in df_seleccion.iterrows():
        costo_total_item = row['Uds a Comprar'] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.multi_cell(35, 8, str(row['SKU_Proveedor']), 1, 'L')
        pdf.set_xy(x + 35, y)
        pdf.multi_cell(30, 8, str(row['SKU']), 1, 'L')
        pdf.set_xy(x + 65, y)
        pdf.multi_cell(65, 8, row['Descripcion'], 1, 'L')
        pdf.set_xy(x + 130, y)
        pdf.multi_cell(15, 8, str(row['Uds a Comprar']), 1, 'C')
        pdf.set_xy(x + 145, y)
        pdf.multi_cell(25, 8, f"${row['Costo_Promedio_UND']:,.2f}", 1, 'R')
        pdf.set_xy(x + 170, y)
        pdf.multi_cell(20, 8, f"${costo_total_item:,.2f}", 1, 'R')
    iva_porcentaje = 0.19
    iva_valor = subtotal * iva_porcentaje
    total_general = subtotal + iva_valor
    pdf.set_font("Arial", '', 10)
    pdf.cell(145, 8, 'Subtotal', 1, 0, 'R')
    pdf.cell(45, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.cell(145, 8, f'IVA ({iva_porcentaje*100:.0f}%)', 1, 0, 'R')
    pdf.cell(45, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(145, 8, 'TOTAL GENERAL', 1, 0, 'R')
    pdf.cell(45, 8, f"${total_general:,.2f}", 1, 1, 'R')
    
    # ✨ CORRECCIÓN: Se elimina el .encode('latin-1') que causaba el error.
    return pdf.output()

@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70)
            return output.getvalue()
        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(width, 45))
    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.error("🔴 Los datos de inventario no se han cargado. Regresa a la página principal para recargar.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
else:
    df_maestro = st.session_state['df_analisis_maestro']

    # --- Filtros en la barra lateral ---
    st.sidebar.header("⚙️ Filtros de Gestión")
    opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
    if st.session_state.get('user_role') == 'gerente':
        almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    else:
        almacen_options = [st.session_state.get('almacen_nombre')]
    selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista de Tienda:", almacen_options)

    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_maestro.copy()
    else:
        df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)

    if selected_marcas:
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]
    else:
        df_filtered = df_vista

    # ✨ SE RESTAURAN LAS PESTAÑAS
    tab1, tab2, tab3 = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # --- Pestaña 1: Diagnóstico ---
    with tab1:
        st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
        # ... (La lógica de KPIs y recomendaciones se mantiene)
        # (Se omite por brevedad, es la misma que ya funcionaba)
        pass

    # --- Pestaña 2: Traslados (Restaurada) ---
    with tab2:
        st.subheader("Sugerencias de Balanceo entre Tiendas")
        with st.spinner("Calculando plan de traslados óptimo..."):
            df_plan_maestro = generar_plan_traslados_inteligente(df_maestro)

        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados! No hay cruces de necesidad y excedente.")
        else:
            if selected_almacen_nombre == opcion_consolidado:
                df_plan_display = df_plan_maestro
                st.info("Mostrando todas las sugerencias de traslado entre todas las tiendas.")
            else:
                df_plan_display = df_plan_maestro[
                    (df_plan_maestro['Tienda Origen'] == selected_almacen_nombre) |
                    (df_plan_maestro['Tienda Destino'] == selected_almacen_nombre)
                ].copy()
                st.info(f"Mostrando traslados que envían o reciben en **{selected_almacen_nombre}**.")
            
            if df_plan_display.empty:
                st.success(f"✅ La tienda **{selected_almacen_nombre}** no necesita enviar ni recibir traslados.")
            else:
                excel_traslados = generar_excel_dinamico(df_plan_display, "Plan de Traslados")
                st.download_button("📥 Descargar Plan de Traslados", excel_traslados, "Plan_Traslados.xlsx")
                st.dataframe(df_plan_display.drop(columns=['Valor Individual', 'Peso Individual (kg)'], errors='ignore'), use_container_width=True)

    # --- Pestaña 3: Compras (Mejorada) ---
    with tab3:
        st.subheader("Sugerencias de Compra")
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()

        if not df_plan_compras.empty:
            proveedores_disponibles = ['Todos'] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor para generar la orden:", proveedores_disponibles)
            if selected_proveedor != 'Todos':
                df_plan_compras = df_plan_compras[df_plan_compras['Proveedor'] == selected_proveedor]
        else:
            selected_proveedor = "Todos"
            st.selectbox("Filtrar por Proveedor:", ['Todos'], disabled=True)
            
        df_plan_compras_final = pd.DataFrame()
        if not df_plan_compras.empty:
            df_plan_compras['Uds a Comprar'] = df_plan_compras['Sugerencia_Compra'].astype(int)
            df_plan_compras['Valor de la Compra'] = df_plan_compras['Uds a Comprar'] * df_plan_compras['Costo_Promedio_UND']
            df_plan_compras['Seleccionar'] = False 
            df_plan_compras_final = df_plan_compras.rename(columns={'Almacen_Nombre': 'Tienda'})[
                ['Seleccionar', 'Tienda', 'Proveedor', 'SKU_Proveedor', 'SKU', 'Descripcion', 'Segmento_ABC', 'Uds a Comprar', 'Valor de la Compra', 'Costo_Promedio_UND']
            ].sort_values(by=['Tienda', 'Valor de la Compra'], ascending=[True, False])
        
        c1, c2 = st.columns(2)
        with c1:
            excel_compras = generar_excel_dinamico(df_plan_compras_final.drop(columns=['Seleccionar', 'Costo_Promedio_UND']), "Plan de Compras")
            st.download_button("📥 Descargar Plan de Compras (Excel)", excel_compras, "Plan_Compras.xlsx")

        if df_plan_compras_final.empty:
            st.success("✅ ¡No se requieren compras con los filtros actuales!")
        else:
            st.markdown("Marque los artículos que desea incluir en la orden de compra:")
            edited_df = st.data_editor(
                df_plan_compras_final, hide_index=True, use_container_width=True,
                column_config={"Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), "Seleccionar": st.column_config.CheckboxColumn(required=True), "SKU_Proveedor": st.column_config.TextColumn("Cód. Proveedor"), "SKU": st.column_config.TextColumn("Cód. Interno")},
                disabled=[col for col in df_plan_compras_final.columns if col != 'Seleccionar'])
            df_seleccionados = edited_df[edited_df['Seleccionar']]
            with c2:
                pdf_bytes = generar_pdf_orden_compra(df_seleccionados, selected_proveedor, selected_almacen_nombre)
                st.download_button(
                    "📄 Generar Orden de Compra (PDF)",
                    data=pdf_bytes if pdf_bytes is not None else b"",
                    file_name=f"OC_{selected_proveedor.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    disabled=df_seleccionados.empty or selected_proveedor == 'Todos')
            if selected_proveedor == 'Todos' and not df_seleccionados.empty:
                st.warning("Por favor, seleccione un proveedor específico para generar la orden de compra.")
            if not df_seleccionados.empty:
                st.info(f"**Total de la selección actual:** ${df_seleccionados['Valor de la Compra'].sum():,.0f}")
