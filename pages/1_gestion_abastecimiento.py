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

# Clase para crear el PDF profesional (sin cambios)
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

# Función de generación de PDF (sin cambios)
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

    y_antes = pdf.get_y()
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 7, "PROVEEDOR:", 1, 0, 'C')
    pdf.cell(95, 7, "ENVIAR A:", 1, 1, 'C')
    
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 7, f" {proveedor_nombre}", 1, 0)
    pdf.cell(95, 7, f" {tu_empresa} - Bodega {tienda_nombre}", 1, 1)
    
    pdf.cell(95, 7, " ", 1, 0)
    pdf.cell(95, 7, f" {tu_direccion}", 1, 1) 
    pdf.ln(10)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(35, 8, 'Cód. Proveedor', 1, 0, 'C', 1)
    pdf.cell(30, 8, 'Cód. Interno', 1, 0, 'C', 1)
    pdf.cell(65, 8, 'Descripción del Producto', 1, 0, 'C', 1)
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
    
    return pdf.output(dest='S').encode('latin-1')

# ✨ CORRECCIÓN: Esta es la función completa para generar el Excel.
# Reemplaza la versión con 'pass' que tenías antes.
@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    """Crea un archivo Excel dinámico con formato."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            # Esto evita que la app se caiga si no hay datos.
            pd.DataFrame([{'Notificación': f"No se encontraron datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70)
            return output.getvalue()

        # Asegurar que las unidades son enteros
        for col in ['Uds a Enviar', 'Uds a Comprar']:
            if col in df.columns:
                df[col] = df[col].astype(int)

        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook = writer.book
        worksheet = writer.sheets[nombre_hoja]

        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})

        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(width, 45))
            
    return output.getvalue()

# Esta función no cambia
def generar_plan_traslados_inteligente(df_analisis_maestro):
    # (El código de esta función es el mismo que ya tenías)
    pass


# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---
if 'df_analisis_maestro' in st.session_state:
    df_maestro = st.session_state['df_analisis_maestro']
    
    tab_diagnostico, tab_traslados, tab_compras = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

    # Las pestañas de diagnóstico y traslados no cambian
    with tab_diagnostico:
        # (El código de esta pestaña es el mismo)
        pass

    with tab_traslados:
        # (El código de esta pestaña es el mismo)
        pass
        
    # --- PESTAÑA 3: PLAN DE COMPRAS ---
    with tab_compras:
        # Aquí la lógica es la misma que la versión final anterior
        if 'df_analisis' in st.session_state:
            df_vista_tienda = st.session_state.get('df_analisis')
            selected_almacen_nombre = df_vista_tienda['Almacen_Nombre'].iloc[0] if not df_vista_tienda.empty else "N/A"
        else:
            df_vista_tienda = df_maestro
            selected_almacen_nombre = "Consolidado"

        st.info(f"Prioridad 2: Comprar únicamente lo necesario para **{selected_almacen_nombre}** después de agotar traslados.")
        
        df_plan_compras = df_vista_tienda[df_vista_tienda['Sugerencia_Compra'] > 0].copy()

        if not df_plan_compras.empty:
            proveedores_disponibles = ['Todos'] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor:", proveedores_disponibles)
            
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
                [
                    'Seleccionar', 'Tienda', 'Proveedor', 'SKU_Proveedor', 'SKU', 'Descripcion', 
                    'Segmento_ABC', 'Uds a Comprar', 'Valor de la Compra', 'Costo_Promedio_UND'
                ]
            ].sort_values(by='Valor de la Compra', ascending=[False])
        
        col1, col2 = st.columns(2)
        with col1:
            excel_display_df = df_plan_compras_final.drop(columns=['Seleccionar', 'Costo_Promedio_UND'], errors='ignore')
            excel_bytes = generar_excel_dinamico(excel_display_df, "Plan de Compras")
            st.download_button(
                "📥 Descargar Plan de Compras (Excel)", 
                excel_bytes, 
                f"Plan_de_Compras_{selected_proveedor.replace(' ','_')}.xlsx"
            )
        
        if df_plan_compras_final.empty: 
            st.success("¡No se requieren compras con los filtros actuales!")
        else:
            st.markdown("Marque los artículos que desea incluir en la orden de compra:")
            edited_df = st.data_editor(
                df_plan_compras_final, 
                hide_index=True, 
                use_container_width=True, 
                column_config={
                    "Valor de la Compra": st.column_config.NumberColumn(format="$ %d"), 
                    "Seleccionar": st.column_config.CheckboxColumn(required=True),
                    "SKU_Proveedor": st.column_config.TextColumn("Cód. Proveedor"),
                    "SKU": st.column_config.TextColumn("Cód. Interno"),
                },
                disabled=[col for col in df_plan_compras_final.columns if col != 'Seleccionar']
            )

            df_seleccionados = edited_df[edited_df['Seleccionar']]

            with col2:
                pdf_bytes = generar_pdf_orden_compra(df_seleccionados, selected_proveedor, selected_almacen_nombre)
                st.download_button(
                    "📄 Generar Orden de Compra (PDF)",
                    data=pdf_bytes,
                    file_name=f"OC_{selected_proveedor.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    disabled=df_seleccionados.empty or selected_proveedor == 'Todos'
                )
            
            if selected_proveedor == 'Todos' and not df_seleccionados.empty:
                st.warning("Por favor, seleccione un proveedor específico para generar la orden de compra.")

            if not df_seleccionados.empty:
                total_seleccionado = df_seleccionados['Valor de la Compra'].sum()
                st.info(f"**Total de la selección actual:** ${total_seleccionado:,.0f}")

else:
    st.error("🔴 Los datos de inventario no se han cargado. Regresa a la página principal para recargar.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
