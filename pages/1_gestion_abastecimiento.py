import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.express as px
from fpdf import FPDF
from datetime import datetime
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email import encoders

# --- 0. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="💡")

st.title("💡 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Optimiza tus traslados y compras para maximizar la rentabilidad.")

# --- 1. FUNCIONES AUXILIARES ---

# ✅ MEJORA: Función de correo ahora maneja diferentes tipos de adjuntos (PDF y Excel)
def enviar_correo_con_adjunto(destinatarios, asunto, cuerpo_html, nombre_adjunto, datos_adjuntos, tipo_mime='application', subtipo_mime='octet-stream'):
    """Envía un correo a una LISTA de destinatarios con un archivo adjunto."""
    try:
        remitente = st.secrets["gmail"]["email"]
        password = st.secrets["gmail"]["password"]
        msg = MIMEMultipart()
        msg['From'] = f"Compras Ferreinox <{remitente}>"
        msg['To'] = ", ".join(destinatarios)
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo_html, 'html'))
        
        with io.BytesIO(datos_adjuntos) as attachment_stream:
            adjunto = MIMEBase(tipo_mime, subtipo_mime)
            adjunto.set_payload(attachment_stream.read())
        
        encoders.encode_base64(adjunto)
        adjunto.add_header('Content-Disposition', 'attachment', filename=nombre_adjunto)
        msg.attach(adjunto)

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(remitente, password)
            server.sendmail(remitente, destinatarios, msg.as_string())
        return True, "Correo enviado exitosamente."
    except Exception as e:
        return False, f"Error al enviar el correo: '{e}'. Revisa la configuración de 'secrets'."


def generar_link_whatsapp(numero, mensaje):
    """Genera un link de WhatsApp pre-llenado y codificado."""
    mensaje_codificado = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero}?text={mensaje_codificado}"

@st.cache_data
def generar_plan_traslados_inteligente(_df_analisis_maestro):
    if _df_analisis_maestro is None or _df_analisis_maestro.empty: return pd.DataFrame()
    df_origen = _df_analisis_maestro[_df_analisis_maestro['Excedente_Trasladable'] > 0].sort_values(by='Excedente_Trasladable', ascending=False).copy()
    df_destino = _df_analisis_maestro[_df_analisis_maestro['Necesidad_Total'] > 0].sort_values(by='Necesidad_Total', ascending=False).copy()
    if df_origen.empty or df_destino.empty: return pd.DataFrame()
    plan_final = []
    excedentes_mutables = df_origen.set_index(['SKU', 'Almacen_Nombre'])['Excedente_Trasladable'].to_dict()
    for _, necesidad_row in df_destino.iterrows():
        sku, tienda_necesitada, necesidad_actual = necesidad_row['SKU'], necesidad_row['Almacen_Nombre'], necesidad_row['Necesidad_Total']
        if necesidad_actual <= 0: continue
        posibles_origenes = df_origen[df_origen['SKU'] == sku]
        for _, origen_row in posibles_origenes.iterrows():
            tienda_origen = origen_row['Almacen_Nombre']
            if tienda_origen == tienda_necesitada: continue
            excedente_disponible = excedentes_mutables.get((sku, tienda_origen), 0)
            if excedente_disponible > 0 and necesidad_actual > 0:
                unidades_a_enviar = np.floor(min(necesidad_actual, excedente_disponible))
                if unidades_a_enviar < 1: continue
                plan_final.append({'SKU': sku, 'Descripcion': necesidad_row['Descripcion'], 'Marca_Nombre': origen_row['Marca_Nombre'],'Segmento_ABC': necesidad_row['Segmento_ABC'], 'Tienda Origen': tienda_origen,'Stock en Origen': origen_row['Stock'], 'Tienda Destino': tienda_necesitada,'Stock en Destino': necesidad_row['Stock'], 'Necesidad en Destino': necesidad_row['Necesidad_Total'],'Uds a Enviar': unidades_a_enviar, 'Peso Individual (kg)': necesidad_row['Peso_Articulo'],'Valor Individual': necesidad_row['Costo_Promedio_UND']})
                necesidad_actual -= unidades_a_enviar
                excedentes_mutables[(sku, tienda_origen)] -= unidades_a_enviar
    if not plan_final: return pd.DataFrame()
    df_resultado = pd.DataFrame(plan_final)
    # Se calcula el peso, pero el valor se deja fuera de la vista principal según solicitado
    df_resultado['Peso del Traslado (kg)'] = df_resultado['Uds a Enviar'] * df_resultado['Peso Individual (kg)']
    df_resultado['Valor del Traslado'] = df_resultado['Uds a Enviar'] * df_resultado['Valor Individual']
    return df_resultado.sort_values(by=['Valor del Traslado'], ascending=False)

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa_nombre = "Ferreinox SAS BIC"; self.empresa_nit = "NIT 800.224.617"; self.empresa_tel = "Tel: 312 7574279"
        self.empresa_web = "www.ferreinox.co"; self.empresa_email = "compras@ferreinox.co"
        self.color_rojo_ferreinox = (212, 32, 39); self.color_gris_oscuro = (68, 68, 68); self.color_azul_oscuro = (79, 129, 189)
        try:
            self.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf'); self.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf')
            self.add_font('DejaVu', 'I', 'fonts/DejaVuSans-Oblique.ttf'); self.add_font('DejaVu', 'BI', 'fonts/DejaVuSans-BoldOblique.ttf')
        except RuntimeError: st.error("Error al cargar la fuente. Asegúrate de que los archivos .ttf están en la carpeta 'fonts'.")
    def header(self):
        try: self.image('LOGO FERREINOX SAS BIC 2024.png', x=10, y=8, w=65)
        except RuntimeError: self.set_xy(10, 8); self.set_font('DejaVu', 'B', 12); self.cell(65, 25, '[LOGO]', 1, 0, 'C')
        self.set_y(12); self.set_x(80); self.set_font('DejaVu', 'B', 22); self.set_text_color(*self.color_gris_oscuro)
        self.cell(120, 10, 'ORDEN DE COMPRA', 0, 1, 'R'); self.set_x(80); self.set_font('DejaVu', '', 10); self.set_text_color(100, 100, 100)
        self.cell(120, 7, self.empresa_nombre, 0, 1, 'R'); self.set_x(80); self.cell(120, 7, f"{self.empresa_nit} - {self.empresa_tel}", 0, 1, 'R')
        self.ln(15)
    def footer(self):
        self.set_y(-20); self.set_draw_color(*self.color_rojo_ferreinox); self.set_line_width(1); self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2); self.set_font('DejaVu', '', 8); self.set_text_color(128, 128, 128)
        footer_text = f"{self.empresa_nombre}   |   {self.empresa_web}   |   {self.empresa_email}   |   {self.empresa_tel}"
        self.cell(0, 10, footer_text, 0, 0, 'C'); self.set_y(-12); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_orden_compra(df_seleccion, proveedor_nombre, tienda_nombre, direccion_entrega, contacto_proveedor):
    if df_seleccion.empty: return None
    pdf = PDF()
    pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_font("DejaVu", 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 7, "PROVEEDOR", 1, 0, 'C', 1); pdf.cell(95, 7, "ENVIAR A", 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 9)
    y_start = pdf.get_y()
    proveedor_info = f"Razón Social: {proveedor_nombre}\nContacto: {contacto_proveedor if contacto_proveedor else 'No especificado'}"
    pdf.multi_cell(95, 7, proveedor_info, 1, 'L')
    pdf.set_y(y_start); pdf.set_x(105)
    envio_info = f"{pdf.empresa_nombre} - Sede {tienda_nombre}\nDirección: {direccion_entrega}\nRecibe: Leivyn Gabriel Garcia"
    pdf.multi_cell(95, 7, envio_info, 1, 'L'); pdf.ln(5)
    pdf.set_font("DejaVu", 'B', 10)
    pdf.cell(63, 7, f"ORDEN N°: {datetime.now().strftime('%Y%m%d-%H%M')}", 1, 0, 'C', 1)
    pdf.cell(64, 7, f"FECHA EMISIÓN: {datetime.now().strftime('%d/%m/%Y')}", 1, 0, 'C', 1)
    pdf.cell(63, 7, "CONDICIONES: NETO 30 DÍAS", 1, 1, 'C', 1); pdf.ln(10)
    pdf.set_fill_color(*pdf.color_azul_oscuro); pdf.set_text_color(255, 255, 255); pdf.set_font("DejaVu", 'B', 9)
    pdf.cell(25, 8, 'Cód. Interno', 1, 0, 'C', 1); pdf.cell(30, 8, 'Cód. Prov.', 1, 0, 'C', 1)
    pdf.cell(70, 8, 'Descripción del Producto', 1, 0, 'C', 1); pdf.cell(15, 8, 'Cant.', 1, 0, 'C', 1)
    pdf.cell(25, 8, 'Costo Unit.', 1, 0, 'C', 1); pdf.cell(25, 8, 'Costo Total', 1, 1, 'C', 1)
    pdf.set_font("DejaVu", '', 9); pdf.set_text_color(0, 0, 0)
    subtotal = 0
    for _, row in df_seleccion.iterrows():
        costo_total_item = row['Uds a Comprar'] * row['Costo_Promedio_UND']
        subtotal += costo_total_item
        x_start, y_start = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(25, 8, str(row['SKU']), 1, 'L'); pdf.set_xy(x_start + 25, y_start)
        pdf.multi_cell(30, 8, str(row['SKU_Proveedor']), 1, 'L'); pdf.set_xy(x_start + 55, y_start)
        pdf.multi_cell(70, 8, row['Descripcion'], 1, 'L')
        y_end_desc = pdf.get_y(); row_height = y_end_desc - y_start
        pdf.set_xy(x_start + 125, y_start); pdf.multi_cell(15, row_height, str(row['Uds a Comprar']), 1, 'C')
        pdf.set_xy(x_start + 140, y_start); pdf.multi_cell(25, row_height, f"${row['Costo_Promedio_UND']:,.2f}", 1, 'R')
        pdf.set_xy(x_start + 165, y_start); pdf.multi_cell(25, row_height, f"${costo_total_item:,.2f}", 1, 'R')
        pdf.set_y(y_end_desc)
    iva_porcentaje, iva_valor = 0.19, subtotal * 0.19
    total_general = subtotal + iva_valor
    pdf.set_x(110); pdf.set_font("DejaVu", '', 10)
    pdf.cell(55, 8, 'Subtotal:', 1, 0, 'R'); pdf.cell(35, 8, f"${subtotal:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.cell(55, 8, f'IVA ({iva_porcentaje*100:.0f}%):', 1, 0, 'R'); pdf.cell(35, 8, f"${iva_valor:,.2f}", 1, 1, 'R')
    pdf.set_x(110); pdf.set_font("DejaVu", 'B', 11)
    pdf.cell(55, 10, 'TOTAL A PAGAR', 1, 0, 'R'); pdf.cell(35, 10, f"${total_general:,.2f}", 1, 1, 'R')
    return bytes(pdf.output())

@st.cache_data
def generar_excel_dinamico(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df.empty:
            pd.DataFrame([{'Notificación': f"No hay datos para '{nombre_hoja}'."}]).to_excel(writer, index=False, sheet_name=nombre_hoja)
            writer.sheets[nombre_hoja].set_column('A:A', 70); return output.getvalue()
        df.to_excel(writer, index=False, sheet_name=nombre_hoja, startrow=1)
        workbook, worksheet = writer.book, writer.sheets[nombre_hoja]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'align': 'center'})
        for col_num, value in enumerate(df.columns.values): worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 4; worksheet.set_column(i, i, min(width, 45))
    return output.getvalue()

# --- 2. LÓGICA PRINCIPAL DE LA PÁGINA ---

if 'df_analisis_maestro' not in st.session_state or st.session_state['df_analisis_maestro'].empty:
    st.warning("⚠️ Por favor, inicia sesión en la página principal para cargar los datos.")
    st.page_link("app.py", label="Ir a la página principal", icon="🏠")
    st.stop() 

df_maestro = st.session_state['df_analisis_maestro']
if 'Precio_Venta_Estimado' not in df_maestro.columns:
    df_maestro['Precio_Venta_Estimado'] = df_maestro['Costo_Promedio_UND'] * 1.30

st.sidebar.header("⚙️ Filtros de Gestión")
opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
if st.session_state.get('user_role') == 'gerente':
    almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
else:
    almacen_options = [st.session_state.get('almacen_nombre')]
selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista de Tienda:", almacen_options)

if selected_almacen_nombre == opcion_consolidado: df_vista = df_maestro.copy()
else: df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]

marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)] if selected_marcas else df_vista

DIRECCIONES_TIENDAS = {'Armenia': 'Carrera 19 11 05', 'Olaya': 'Carrera 13 19 26', 'Manizales': 'Calle 16 21 32', 'FerreBox': 'Calle 20 12 32'}
CONTACTOS_PROVEEDOR = {
    'ABRACOL': {'nombre': 'JHON JAIRO DUQUE', 'celular': '573113032448'},
    'SAINT GOBAIN': {'nombre': 'SARA LARA', 'celular': '573165257917'},
    'GOYA': {'nombre': 'JULIAN NAÑES', 'celular': '573208334589'},
    'YALE': {'nombre': 'JUAN CARLOS MARTINEZ', 'celular': '573208130893'},
}

tab1, tab2, tab3 = st.tabs(["📊 Diagnóstico General", "🔄 Plan de Traslados", "🛒 Plan de Compras"])

with tab1:
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    necesidad_compra_total = (df_filtered['Sugerencia_Compra'] * df_filtered['Costo_Promedio_UND']).sum()
    df_origen_kpi = df_maestro[df_maestro['Excedente_Trasladable'] > 0]
    df_destino_kpi = df_filtered[df_filtered['Necesidad_Total'] > 0]
    oportunidad_ahorro = 0
    if not df_origen_kpi.empty and not df_destino_kpi.empty:
        df_sugerencias_kpi = pd.merge(df_origen_kpi.groupby('SKU').agg(Total_Excedente_Global=('Excedente_Trasladable', 'sum'),Costo_Promedio_UND=('Costo_Promedio_UND', 'mean')), df_destino_kpi.groupby('SKU').agg(Total_Necesidad_Tienda=('Necesidad_Total', 'sum')), on='SKU', how='inner')
        df_sugerencias_kpi['Ahorro_Potencial'] = np.minimum(df_sugerencias_kpi['Total_Excedente_Global'], df_sugerencias_kpi['Total_Necesidad_Tienda'])
        oportunidad_ahorro = (df_sugerencias_kpi['Ahorro_Potencial'] * df_sugerencias_kpi['Costo_Promedio_UND']).sum()
    df_quiebre = df_filtered[df_filtered['Estado_Inventario'] == 'Quiebre de Stock']
    venta_perdida = (df_quiebre['Demanda_Diaria_Promedio'] * 30 * df_quiebre['Precio_Venta_Estimado']).sum()
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric(label="💰 Valor Compra Requerida", value=f"${necesidad_compra_total:,.0f}")
    kpi2.metric(label="💸 Ahorro por Traslados", value=f"${oportunidad_ahorro:,.0f}")
    kpi3.metric(label="📉 Venta Potencial Perdida", value=f"${venta_perdida:,.0f}")
    st.markdown("##### Análisis y Recomendaciones Clave")
    with st.container(border=True):
        if venta_perdida > 0: st.markdown(f"**🚨 Alerta:** Se estima una pérdida de venta de **${venta_perdida:,.0f}** en 30 días por **{len(df_quiebre)}** productos en quiebre.")
        if oportunidad_ahorro > 0: st.markdown(f"**💸 Oportunidad:** Puedes ahorrar **${oportunidad_ahorro:,.0f}** solicitando traslados. Revisa la pestaña de 'Plan de Traslados'.")
        if necesidad_compra_total > 0:
            df_compras_prioridad = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
            df_compras_prioridad['Valor_Compra'] = df_compras_prioridad['Sugerencia_Compra'] * df_compras_prioridad['Costo_Promedio_UND']
            if not df_compras_prioridad.empty:
                top_categoria = df_compras_prioridad.groupby('Segmento_ABC')['Valor_Compra'].sum().idxmax()
                st.markdown(f"**🎯 Enfoque:** Tu principal necesidad de inversión se concentra en productos de **Clase '{top_categoria}'**.")
        if venta_perdida == 0 and oportunidad_ahorro == 0 and necesidad_compra_total == 0: st.markdown("✅ **¡Inventario Optimizado!** No se detectan necesidades urgentes.")
    st.markdown("---")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            data_chart = df_compras_chart.groupby('Almacen_Nombre')['Valor_Compra'].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(data_chart, x='Almacen_Nombre', y='Valor_Compra', text_auto='.2s', title="Inversión Total Requerida por Tienda")
            st.plotly_chart(fig, use_container_width=True)
    with col_g2:
        df_compras_chart = df_maestro[df_maestro['Sugerencia_Compra'] > 0]
        if not df_compras_chart.empty:
            df_compras_chart['Valor_Compra'] = df_compras_chart['Sugerencia_Compra'] * df_compras_chart['Costo_Promedio_UND']
            fig = px.sunburst(df_compras_chart, path=['Segmento_ABC', 'Marca_Nombre'], values='Valor_Compra', title="¿En qué categorías y marcas comprar?")
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    
    with st.spinner("Calculando plan de traslados óptimo..."):
        df_plan_maestro = generar_plan_traslados_inteligente(df_filtered)

    if df_plan_maestro.empty:
        st.success("✅ ¡No se sugieren traslados con los filtros actuales!")
    else:
        search_term_traslado = st.text_input("Buscar producto a trasladar por SKU o Descripción:", key="search_traslados")
        
        df_traslados_filtrado = df_plan_maestro
        if search_term_traslado:
            mask_traslado = (
                df_plan_maestro['SKU'].astype(str).str.contains(search_term_traslado, case=False, na=False) |
                df_plan_maestro['Descripcion'].astype(str).str.contains(search_term_traslado, case=False, na=False)
            )
            df_traslados_filtrado = df_plan_maestro[mask_traslado]

        if df_traslados_filtrado.empty:
            st.warning("No se encontraron traslados que coincidan con la búsqueda.")
        else:
            df_para_editar = df_traslados_filtrado.copy()
            df_para_editar['Seleccionar'] = False
            
            columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Tienda Origen', 'Tienda Destino', 'Uds a Enviar', 'Peso Individual (kg)']
            edited_df_traslados = st.data_editor(
                df_para_editar[columnas_traslado],
                hide_index=True, use_container_width=True,
                column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']],
                key="editor_traslados"
            )

            df_seleccionados_traslado = edited_df_traslados[edited_df_traslados['Seleccionar']]

            if not df_seleccionados_traslado.empty:
                df_seleccionados_traslado = df_seleccionados_traslado.copy()
                df_seleccionados_traslado['Peso del Traslado (kg)'] = df_seleccionados_traslado['Uds a Enviar'] * df_seleccionados_traslado['Peso Individual (kg)']
                
                st.markdown("---")
                
                email_dest_traslado = st.text_input("📧 Correo del destinatario para el plan de traslado:", key="email_traslado", help="Ej: logistica@ferreinox.co")
                
                t_c1, t_c2 = st.columns(2)
                with t_c1:
                    if st.button("✉️ Enviar Plan por Correo", use_container_width=True, key="btn_enviar_traslado"):
                        if email_dest_traslado:
                            with st.spinner("Enviando correo con el plan..."):
                                excel_bytes = generar_excel_dinamico(df_seleccionados_traslado, "Plan_de_Traslados")
                                asunto = f"Nuevo Plan de Traslado Interno - {datetime.now().strftime('%d/%m/%Y')}"
                                cuerpo_html = f"<html><body><p>Hola equipo de logística,</p><p>Adjunto se encuentra el plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado.</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"
                                nombre_archivo = f"Plan_Traslado_{datetime.now().strftime('%Y%m%d')}.xlsx"
                                
                                email_string = email_dest_traslado.replace(';', ',')
                                lista_destinatarios = [email.strip() for email in email_string.split(',') if email.strip()]

                                enviado, mensaje = enviar_correo_con_adjunto(
                                    lista_destinatarios, asunto, cuerpo_html, nombre_archivo, excel_bytes, 
                                    tipo_mime='application', subtipo_mime='vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                                
                                if enviado:
                                    st.success(mensaje)
                                else:
                                    st.error(mensaje)
                        else:
                            st.warning("Por favor, ingresa un correo de destinatario.")
                with t_c2:
                    st.download_button("📥 Descargar Plan (Excel)", data=generar_excel_dinamico(df_seleccionados_traslado, "Plan_de_Traslados"), file_name="Plan_de_Traslado.xlsx", use_container_width=True)

                st.markdown("---")
                total_unidades = df_seleccionados_traslado['Uds a Enviar'].sum()
                total_peso = df_seleccionados_traslado['Peso del Traslado (kg)'].sum()
                st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")

with tab3:
    st.header("🛒 Plan de Compras")
    
    with st.expander("✅ **Paso 1: Generar Órdenes para Proveedores Asignados**", expanded=True):
        df_asignados = df_filtered[(df_filtered['Sugerencia_Compra'] > 0) & (df_filtered['Proveedor'] != 'No Asignado')].copy()
        
        if df_asignados.empty:
            st.info("No hay sugerencias de compra para productos con proveedores ya asignados.")
        else:
            df_asignados['Proveedor'] = df_asignados['Proveedor'].str.upper()
            proveedores_asignados = sorted(df_asignados['Proveedor'].unique().tolist())
            selected_proveedor_asignado = st.selectbox("Filtrar por Proveedor:", proveedores_asignados, key="sb_proveedores_asignados")
            
            df_a_mostrar = df_asignados[df_asignados['Proveedor'] == selected_proveedor_asignado].copy()
            
            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].astype(int)
            df_a_mostrar['Seleccionar'] = False 
            columnas = ['Seleccionar', 'Tienda', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})[columnas]

            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df_asignados = st.data_editor(df_a_mostrar_final, hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']], 
                key="editor_asignados")

            df_seleccionados_asignados = edited_df_asignados[edited_df_asignados['Seleccionar']]

            if not df_seleccionados_asignados.empty:
                df_seleccionados_asignados = df_seleccionados_asignados.copy()
                df_seleccionados_asignados['Valor de la Compra'] = df_seleccionados_asignados['Uds a Comprar'] * df_seleccionados_asignados['Costo_Promedio_UND']
                
                tienda_entrega_asig = selected_almacen_nombre
                if tienda_entrega_asig == opcion_consolidado:
                    tienda_entrega_asig = 'FerreBox'
                
                direccion_entrega_asig = DIRECCIONES_TIENDAS.get(tienda_entrega_asig, "N/A")
                info_proveedor = CONTACTOS_PROVEEDOR.get(selected_proveedor_asignado, {})
                contacto_proveedor_asig = info_proveedor.get('nombre', '')
                celular_proveedor_asig = info_proveedor.get('celular', '')
                
                pdf_bytes_asignado = generar_pdf_orden_compra(df_seleccionados_asignados, selected_proveedor_asignado, tienda_entrega_asig, direccion_entrega_asig, contacto_proveedor_asig)
                
                st.markdown("---")
                email_dest_asignado = st.text_input("📧 Correos del destinatario (separados por coma o punto y coma):", key="email_asignado", help="Ej: correo1@ejemplo.com, correo2@ejemplo.com")
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.download_button("📥 Descargar Excel", data=generar_excel_dinamico(df_seleccionados_asignados, "compra"), file_name=f"Compra_{selected_proveedor_asignado}.xlsx", use_container_width=True)
                with c2:
                    if st.button("✉️ Enviar por Correo", disabled=(pdf_bytes_asignado is None), use_container_width=True, key="btn_enviar_asignado"):
                        if email_dest_asignado:
                            with st.spinner("Enviando correo..."):
                                email_string = email_dest_asignado.replace(';', ',')
                                lista_destinatarios = [email.strip() for email in email_string.split(',') if email.strip()]
                                asunto = f"Nueva Orden de Compra de Ferreinox SAS BIC - {selected_proveedor_asignado}"
                                cuerpo_html = f"<html><body><p>Estimados Sres. {selected_proveedor_asignado},</p><p>Adjunto a este correo encontrarán nuestra orden de compra N° {datetime.now().strftime('%Y%m%d-%H%M')}.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_entrega_asig}<br><b>Dirección:</b> {direccion_entrega_asig}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión y quedamos atentos a la confirmación.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC<br>Tel: 312 7574279<br>compras@ferreinox.co</p></body></html>"
                                nombre_archivo = f"OC_Ferreinox_{selected_proveedor_asignado.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                                enviado, mensaje = enviar_correo_con_adjunto(lista_destinatarios, asunto, cuerpo_html, nombre_archivo, pdf_bytes_asignado)
                                if enviado:
                                    st.success(mensaje)
                                    if celular_proveedor_asig:
                                        mensaje_wpp = f"Hola {contacto_proveedor_asig}, te acabamos de enviar la Orden de Compra N° {datetime.now().strftime('%Y%m%d-%H%M')} al correo. Quedamos atentos. ¡Gracias!"
                                        link_wpp = generar_link_whatsapp(celular_proveedor_asig, mensaje_wpp)
                                        st.link_button("📲 Enviar Confirmación por WhatsApp", link_wpp, use_container_width=True)
                                else:
                                    st.error(mensaje)
                        else:
                            st.warning("Por favor, ingresa al menos un correo electrónico de destinatario.")
                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes_asignado, file_name=f"OC_{selected_proveedor_asignado}.pdf", use_container_width=True, disabled=(pdf_bytes_asignado is None))
                st.info(f"Total de la selección para **{selected_proveedor_asignado}**: ${df_seleccionados_asignados['Valor de la Compra'].sum():,.0f}")
    
    st.markdown("---")
    
    with st.expander("🆕 **Paso 2: Compras Especiales (Productos Sin Proveedor)**"):
        df_sin_proveedor = df_filtered[(df_filtered['Sugerencia_Compra'] > 0) & (df_filtered['Proveedor'] == 'No Asignado')].copy()
        
        if df_sin_proveedor.empty:
            st.info("No hay sugerencias de compra para productos sin proveedor asignado.")
        else:
            search_term_sp = st.text_input("Buscar producto sin proveedor por SKU o Descripción:", key="search_sp")
            
            df_resultados_sp = pd.DataFrame()
            if search_term_sp:
                mask = (df_sin_proveedor['SKU'].astype(str).str.contains(search_term_sp, case=False, na=False) | df_sin_proveedor['Descripcion'].astype(str).str.contains(search_term_sp, case=False, na=False))
                df_resultados_sp = df_sin_proveedor[mask].copy()

            if not df_resultados_sp.empty:
                df_resultados_sp['Uds a Comprar'] = df_resultados_sp['Sugerencia_Compra'].astype(int)
                df_resultados_sp['Seleccionar'] = False
                columnas_sp = ['Seleccionar', 'Tienda', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Uds a Comprar', 'Costo_Promedio_UND']
                df_resultados_sp_final = df_resultados_sp.rename(columns={'Almacen_Nombre': 'Tienda'})[columnas_sp]

                st.markdown("##### Productos Encontrados")
                edited_df_sp = st.data_editor(df_resultados_sp_final, hide_index=True, use_container_width=True,
                    column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1), "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=[col for col in df_resultados_sp_final.columns if col not in ['Seleccionar', 'Uds a Comprar']], key="editor_sp")

                df_seleccionados_sp = edited_df_sp[edited_df_sp['Seleccionar']]

                if not df_seleccionados_sp.empty:
                    st.markdown("##### Asignar Proveedor para esta Compra")
                    nuevo_proveedor_nombre = st.text_input("Nombre del Nuevo Proveedor:", key="nuevo_prov_nombre")
                    
                    if nuevo_proveedor_nombre:
                        df_seleccionados_sp = df_seleccionados_sp.copy()
                        df_seleccionados_sp['Valor de la Compra'] = df_seleccionados_sp['Uds a Comprar'] * df_seleccionados_sp['Costo_Promedio_UND']
                        df_seleccionados_sp['Proveedor'] = nuevo_proveedor_nombre
                        
                        tienda_de_entrega_sp = selected_almacen_nombre
                        if tienda_de_entrega_sp == opcion_consolidado:
                            tienda_de_entrega_sp = 'FerreBox'
                        
                        direccion_entrega_sp = DIRECCIONES_TIENDAS.get(tienda_de_entrega_sp, "N/A")
                        pdf_bytes_sp = generar_pdf_orden_compra(df_seleccionados_sp, nuevo_proveedor_nombre, tienda_de_entrega_sp, direccion_entrega_sp, "")

                        email_destinatario_sp = st.text_input("📧 Correo(s) del nuevo proveedor (separados por coma):", key="email_sp")
                        celular_destinatario_sp = st.text_input("📲 Celular del nuevo proveedor (sin el 57):", key="cel_sp", help="Ej: 3001234567")

                        sp_c1, sp_c2, sp_c3 = st.columns(3)
                        with sp_c1:
                            st.download_button("📥 Descargar Excel (SP)", data=generar_excel_dinamico(df_seleccionados_sp, "compra_especial"), file_name=f"Compra_Especial_{nuevo_proveedor_nombre}.xlsx", use_container_width=True, key="btn_dl_excel_sp")
                        with sp_c2:
                            if st.button("✉️ Enviar Correo (SP)", disabled=(pdf_bytes_sp is None), use_container_width=True, key="btn_enviar_sp"):
                                if email_destinatario_sp:
                                    with st.spinner("Enviando correo..."):
                                        email_string_sp = email_destinatario_sp.replace(';', ',')
                                        lista_destinatarios_sp = [email.strip() for email in email_string_sp.split(',') if email.strip()]
                                        asunto_sp = f"Nueva Orden de Compra de Ferreinox SAS BIC - {nuevo_proveedor_nombre}"
                                        cuerpo_html_sp = f"<html><body><p>Estimados {nuevo_proveedor_nombre},</p><p>Adjunto a este correo encontrarán nuestra orden de compra N° {datetime.now().strftime('%Y%m%d-%H%M')}.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_de_entrega_sp}<br><b>Dirección:</b> {direccion_entrega_sp}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión y quedamos atentos a la confirmación.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC<br>Tel: 312 7574279<br>compras@ferreinox.co</p></body></html>"
                                        nombre_archivo_sp = f"OC_Ferreinox_{nuevo_proveedor_nombre.replace(' ','_')}.pdf"
                                        enviado_sp, mensaje_sp = enviar_correo_con_adjunto(lista_destinatarios_sp, asunto_sp, cuerpo_html_sp, nombre_archivo_sp, pdf_bytes_sp)
                                        if enviado_sp:
                                            st.success(mensaje_sp)
                                            if celular_destinatario_sp:
                                                numero_completo = celular_destinatario_sp.strip()
                                                if not numero_completo.startswith('57'):
                                                    numero_completo = '57' + numero_completo
                                                mensaje_wpp_sp = f"Hola {nuevo_proveedor_nombre}, te acabamos de enviar la Orden de Compra N° {datetime.now().strftime('%Y%m%d-%H%M')} al correo. Quedamos atentos. ¡Gracias!"
                                                link_wpp_sp = generar_link_whatsapp(numero_completo, mensaje_wpp_sp)
                                                st.link_button("📲 Notificar por WhatsApp (SP)", link_wpp_sp, use_container_width=True)
                                        else:
                                            st.error(mensaje_sp)
                                else:
                                    st.warning("Ingresa un correo para el nuevo proveedor.")
                        with sp_c3:
                            st.download_button("📄 Descargar PDF (SP)", data=pdf_bytes_sp, file_name=f"OC_Especial_{nuevo_proveedor_nombre}.pdf", use_container_width=True, key="btn_dl_pdf_sp", disabled=(pdf_bytes_sp is None))

                        st.info(f"Total de la selección para **{nuevo_proveedor_nombre}**: ${df_seleccionados_sp['Valor de la Compra'].sum():,.0f}")
