# pages/1_gestion_abastecimiento.py

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from utils import (
    connect_to_gsheets, load_data_from_sheets, calcular_sugerencias_finales,
    registrar_ordenes_en_sheets, enviar_correo_con_adjuntos, generar_link_whatsapp,
    generar_pdf_orden_compra, generar_excel_dinamico, update_sheet,
    CONTACTOS_TIENDAS, CONTACTOS_PROVEEDOR, DIRECCIONES_TIENDAS
)

st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")

# --- 1. VERIFICACIÓN Y CARGA DE DATOS ---
if 'df_analisis_maestro' not in st.session_state or st.session_state.df_analisis_maestro.empty:
    st.warning("⚠️ Primero debes cargar los datos en el 'Tablero Principal'.")
    st.page_link("Tablero_Principal.py", label="Ir al Tablero Principal", icon="🚀")
    st.stop()

client = connect_to_gsheets()
if client:
    with st.spinner("Cargando órdenes y calculando sugerencias finales..."):
        df_maestro_base = st.session_state.df_analisis_maestro.copy()
        df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")
        df_maestro, df_plan_maestro = calcular_sugerencias_finales(df_maestro_base, df_ordenes_historico)
else:
    st.error("No se pudo conectar a Google Sheets para cargar las órdenes.")
    st.stop()

st.title("🚚 Módulo de Gestión de Abastecimiento")
st.markdown("Genera y gestiona órdenes de compra, traslados entre tiendas y haz seguimiento.")

# --- 2. FILTRADO DE DATOS (HEREDA DE LA PÁGINA PRINCIPAL) ---
df_filtered_global = st.session_state.get('df_filtered_global', pd.DataFrame())
if df_filtered_global.empty:
    st.info("No hay datos para los filtros seleccionados en el Tablero Principal.")
    st.stop()

# Usamos 'index' que viene del reset_index() en la página principal para un cruce seguro
df_filtered = df_maestro[df_maestro['index'].isin(df_filtered_global['index'])]


# --- 3. INTERFAZ DE PESTAÑAS ---
tab2, tab3, tab4 = st.tabs(["🔄 Traslados", "🛒 Compras", "✅ Seguimiento"])

# ==============================================================================
# INICIO DE LA PESTAÑA DE TRASLADOS (CÓDIGO ORIGINAL DE tab2)
# ==============================================================================
with tab2:
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    with st.expander("🔄 **Plan de Traslados Automático**", expanded=True):
        if df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            st.markdown("##### Filtros Avanzados de Traslados")
            f_col1, f_col2, f_col3 = st.columns(3)
            lista_origenes = ["Todas"] + sorted(df_plan_maestro['Tienda Origen'].unique().tolist())
            filtro_origen = f_col1.selectbox("Filtrar por Tienda Origen:", lista_origenes, key="filtro_origen")
            lista_destinos = ["Todas"] + sorted(df_plan_maestro['Tienda Destino'].unique().tolist())
            filtro_destino = f_col2.selectbox("Filtrar por Tienda Destino:", lista_destinos, key="filtro_destino")
            lista_proveedores_traslado = ["Todos"] + sorted(df_plan_maestro['Proveedor'].unique().tolist())
            filtro_proveedor_traslado = f_col3.selectbox("Filtrar por Proveedor:", lista_proveedores_traslado, key="filtro_proveedor_traslado")
            
            df_aplicar_filtros = df_plan_maestro.copy()
            if filtro_origen != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Origen'] == filtro_origen]
            if filtro_destino != "Todas": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Destino'] == filtro_destino]
            if filtro_proveedor_traslado != "Todos": df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Proveedor'] == filtro_proveedor_traslado]
            
            search_term_traslado = st.text_input("Buscar producto a trasladar por SKU o Descripción:", key="search_traslados")
            df_traslados_filtrado = df_aplicar_filtros
            if search_term_traslado:
                mask_traslado = (df_traslados_filtrado['SKU'].astype(str).str.contains(search_term_traslado, case=False, na=False) |
                                 df_traslados_filtrado['Descripcion'].astype(str).str.contains(search_term_traslado, case=False, na=False))
                df_traslados_filtrado = df_traslados_filtrado[mask_traslado]

            if df_traslados_filtrado.empty:
                st.warning("No se encontraron traslados que coincidan con los filtros y la búsqueda.")
            else:
                df_para_editar = pd.merge(df_traslados_filtrado, df_maestro[['SKU', 'Almacen_Nombre', 'Stock_En_Transito']],
                                          left_on=['SKU', 'Tienda Destino'], right_on=['SKU', 'Almacen_Nombre'], how='left'
                                          ).drop(columns=['Almacen_Nombre']).fillna({'Stock_En_Transito': 0})
                df_para_editar['Seleccionar'] = False
                columnas_traslado = ['Seleccionar', 'SKU', 'Descripcion', 'Tienda Origen', 'Stock en Origen', 'Tienda Destino', 'Stock en Destino', 'Stock_En_Transito', 'Necesidad en Destino', 'Uds a Enviar']
                edited_df_traslados = st.data_editor(
                    df_para_editar[columnas_traslado], hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=0, step=1, format="%d"),
                                   "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d"),
                                   "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=[col for col in columnas_traslado if col not in ['Seleccionar', 'Uds a Enviar']], key="editor_traslados")
                
                df_seleccionados_traslado = edited_df_traslados[(edited_df_traslados['Seleccionar']) & (pd.to_numeric(edited_df_traslados['Uds a Enviar'], errors='coerce').fillna(0) > 0)]
                
                if not df_seleccionados_traslado.empty:
                    df_seleccionados_traslado_full = pd.merge(df_seleccionados_traslado.copy(), df_plan_maestro[['SKU', 'Tienda Origen', 'Tienda Destino', 'Peso Individual (kg)', 'Costo_Promedio_UND']],
                                                              on=['SKU', 'Tienda Origen', 'Tienda Destino'], how='left')
                    df_seleccionados_traslado_full['Peso del Traslado (kg)'] = pd.to_numeric(df_seleccionados_traslado_full['Uds a Enviar']) * pd.to_numeric(df_seleccionados_traslado_full.get('Peso Individual (kg)', 0))
                    
                    st.markdown("---")
                    total_unidades = pd.to_numeric(df_seleccionados_traslado_full['Uds a Enviar']).sum()
                    total_peso = df_seleccionados_traslado_full['Peso del Traslado (kg)'].sum()
                    st.info(f"**Resumen de la Carga Seleccionada:** {total_unidades} Unidades Totales | **{total_peso:,.2f} kg** de Peso Total")
                    
                    destinos_implicados = df_seleccionados_traslado_full['Tienda Destino'].unique().tolist()
                    emails_predefinidos = [CONTACTOS_TIENDAS.get(d, {}).get('email', '') for d in destinos_implicados]
                    email_dest_traslado = st.text_input("📧 Correo(s) de destinatario(s) para el plan de traslado:", value=", ".join(filter(None, emails_predefinidos)), key="email_traslado", help="Puede ser uno o varios correos separados por coma.")
                    
                    if st.button("✅ Enviar y Registrar Traslado", use_container_width=True, key="btn_registrar_traslado", type="primary"):
                        with st.spinner("Registrando traslado y enviando notificaciones..."):
                            exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados_traslado_full, "Traslado Automático")
                            if exito_registro:
                                st.success(f"✅ ¡Traslado registrado exitosamente! {msg_registro}")
                                if email_dest_traslado:
                                    excel_bytes = generar_excel_dinamico(df_registrado, "Plan_de_Traslados")
                                    asunto = f"Nuevo Plan de Traslado Interno - {datetime.now().strftime('%d/%m/%Y')}"
                                    cuerpo_html = f"<html><body><p>Hola equipo,</p><p>Se ha registrado un nuevo plan de traslados para ser ejecutado. Por favor, coordinar el movimiento de la mercancía según lo especificado en el archivo adjunto.</p><p><b>IDs de Traslado generados:</b> {', '.join(df_registrado['ID_Orden'].unique())}</p><p>Gracias por su gestión.</p><p>--<br><b>Sistema de Gestión de Inventarios</b></p></body></html>"
                                    adjunto_traslado = [{'datos': excel_bytes, 'nombre_archivo': f"Plan_Traslado_{datetime.now().strftime('%Y%m%d')}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                    lista_destinatarios = [email.strip() for email in email_dest_traslado.replace(';', ',').split(',') if email.strip()]
                                    enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjunto_traslado)
                                    if enviado: st.success(mensaje)
                                    else: st.error(mensaje)
                                for _, row in df_registrado.drop_duplicates(subset=['Tienda_Destino']).iterrows():
                                    destino = row['Tienda_Destino']
                                    info_tienda = CONTACTOS_TIENDAS.get(destino)
                                    if info_tienda and info_tienda.get('celular'):
                                        numero_wpp = info_tienda['celular']
                                        ordenes_destino = df_registrado[df_registrado['Tienda_Destino'] == destino]
                                        ids_orden_tienda = ", ".join(ordenes_destino['ID_Orden'].unique())
                                        mensaje_wpp = f"Hola equipo de {destino}, se ha generado una nueva orden de traslado hacia su tienda (ID: {ids_orden_tienda}). Por favor, estar atentos a la recepción. ¡Gracias!"
                                        link_wpp = generar_link_whatsapp(numero_wpp, mensaje_wpp)
                                        st.link_button(f"📲 Notificar a {destino} por WhatsApp", link_wpp, target="_blank")
                                st.success("Proceso completado. La página se recargará para actualizar los datos.")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")

    st.markdown("---")
    
    with st.expander("🚚 **Traslados Especiales (Búsqueda y Solicitud Manual)**", expanded=False):
        st.markdown("##### 1. Buscar y añadir productos a la solicitud")
        search_term_especial = st.text_input("Buscar producto por SKU o Descripción para traslado especial:", key="search_traslado_especial")
        if search_term_especial:
            mask_especial = (df_maestro['Stock'] > 0) & \
                            (df_maestro['SKU'].astype(str).str.contains(search_term_especial, case=False, na=False) |
                             df_maestro['Descripcion'].astype(str).str.contains(search_term_especial, case=False, na=False))
            df_resultados_especial = df_maestro[mask_especial].copy()
            if not df_resultados_especial.empty:
                df_resultados_especial['Uds a Enviar'] = 1
                df_resultados_especial['Seleccionar'] = False
                columnas_busqueda = ['Seleccionar', 'SKU', 'Descripcion', 'Almacen_Nombre', 'Stock', 'Uds a Enviar']
                st.write("Resultados de la búsqueda (solo se muestran productos con stock):")
                edited_df_especial = st.data_editor(
                    df_resultados_especial[columnas_busqueda], key="editor_traslados_especiales", hide_index=True, use_container_width=True,
                    column_config={"Uds a Enviar": st.column_config.NumberColumn(label="Cant. a Enviar", min_value=1, step=1),
                                   "Seleccionar": st.column_config.CheckboxColumn(required=True)},
                    disabled=['SKU', 'Descripcion', 'Almacen_Nombre', 'Stock'])
                df_para_anadir = edited_df_especial[edited_df_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la solicitud", key="btn_anadir_especial"):
                    for _, row in df_para_anadir.iterrows():
                        item_id = f"{row['SKU']}_{row['Almacen_Nombre']}"
                        if not any(item['id'] == item_id for item in st.session_state.get('solicitud_traslado_especial', [])):
                            costo_info = df_maestro.loc[(df_maestro['SKU'] == row['SKU']) & (df_maestro['Almacen_Nombre'] == row['Almacen_Nombre']), 'Costo_Promedio_UND']
                            costo = costo_info.iloc[0] if not costo_info.empty else 0
                            if 'solicitud_traslado_especial' not in st.session_state: st.session_state.solicitud_traslado_especial = []
                            st.session_state.solicitud_traslado_especial.append({
                                'id': item_id, 'SKU': row['SKU'], 'Descripcion': row['Descripcion'],
                                'Tienda Origen': row['Almacen_Nombre'], 'Uds a Enviar': row['Uds a Enviar'],
                                'Costo_Promedio_UND': costo
                            })
                    st.success(f"{len(df_para_anadir)} producto(s) añadidos a la solicitud.")
                    st.rerun()
            else:
                st.warning("No se encontraron productos con stock para ese criterio de búsqueda.")
        
        if st.session_state.get('solicitud_traslado_especial'):
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la solicitud de traslado")
            df_solicitud = pd.DataFrame(st.session_state.solicitud_traslado_especial)
            tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
            tienda_destino_especial = st.selectbox("Seleccionar Tienda Destino para esta solicitud:", tiendas_destino_validas, key="destino_especial")
            st.dataframe(df_solicitud[['SKU', 'Descripcion', 'Tienda Origen', 'Uds a Enviar']], use_container_width=True)
            if st.button("🗑️ Limpiar Solicitud", key="btn_limpiar_especial"):
                st.session_state.solicitud_traslado_especial = []
                st.rerun()
            st.markdown("##### 3. Finalizar y enviar la solicitud")
            email_predefinido_especial = CONTACTOS_TIENDAS.get(tienda_destino_especial, {}).get('email', '')
            email_dest_especial = st.text_input("📧 Correo(s) del destinatario para la solicitud especial:", value=email_predefinido_especial, key="email_traslado_especial", help="Separados por coma.")
            if st.button("✅ Enviar y Registrar Solicitud Especial", use_container_width=True, key="btn_enviar_traslado_especial", type="primary"):
                if not df_solicitud.empty:
                    with st.spinner("Registrando y enviando solicitud especial..."):
                        exito_registro, msg_registro, df_registrado_especial = registrar_ordenes_en_sheets(client, df_solicitud, "Traslado Especial", tienda_destino=tienda_destino_especial)
                        if exito_registro:
                            st.success(f"✅ Solicitud especial registrada. {msg_registro}")
                            st.session_state.solicitud_traslado_especial = []
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"❌ Error al registrar: {msg_registro}")
                else:
                    st.warning("La solicitud está vacía.")

# ==============================================================================
# INICIO DE LA PESTAÑA DE COMPRAS (CÓDIGO ORIGINAL DE tab3)
# ==============================================================================
with tab3:
    st.header("🛒 Plan de Compras")
    with st.expander("✅ **Generar Órdenes de Compra por Sugerencia**", expanded=True):
        df_plan_compras = df_filtered[df_filtered['Sugerencia_Compra'] > 0].copy()
        if df_plan_compras.empty:
            st.info("No hay sugerencias de compra con los filtros actuales. ¡El inventario parece estar optimizado!")
        else:
            df_plan_compras['Proveedor'] = df_plan_compras['Proveedor'].astype(str).str.upper()
            proveedores_disponibles = ["Todos"] + sorted(df_plan_compras['Proveedor'].unique().tolist())
            selected_proveedor = st.selectbox("Filtrar por Proveedor:", proveedores_disponibles, key="sb_proveedores")
            df_a_mostrar = df_plan_compras.copy()
            if selected_proveedor != 'Todos':
                df_a_mostrar = df_a_mostrar[df_a_mostrar['Proveedor'] == selected_proveedor]
            df_a_mostrar['Uds a Comprar'] = df_a_mostrar['Sugerencia_Compra'].astype(int)
            select_all_suggested = st.checkbox("Seleccionar / Deseleccionar Todos los Productos Visibles", key="select_all_suggested", value=True)
            df_a_mostrar['Seleccionar'] = select_all_suggested
            columnas = ['Seleccionar', 'Tienda', 'Proveedor', 'SKU', 'SKU_Proveedor', 'Descripcion', 'Stock_En_Transito', 'Uds a Comprar', 'Costo_Promedio_UND']
            df_a_mostrar_final = df_a_mostrar.rename(columns={'Almacen_Nombre': 'Tienda'})
            columnas_existentes = [col for col in columnas if col in df_a_mostrar_final.columns]
            df_a_mostrar_final = df_a_mostrar_final[columnas_existentes]
            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df = st.data_editor(df_a_mostrar_final, hide_index=True, use_container_width=True,
                column_config={"Uds a Comprar": st.column_config.NumberColumn(label="Cant. a Comprar", min_value=0, step=1),
                               "Seleccionar": st.column_config.CheckboxColumn(required=True),
                               "Stock_En_Transito": st.column_config.NumberColumn(label="En Tránsito", format="%d")},
                disabled=[col for col in df_a_mostrar_final.columns if col not in ['Seleccionar', 'Uds a Comprar']], key="editor_principal")
            df_seleccionados = edited_df[(edited_df['Seleccionar']) & (pd.to_numeric(edited_df['Uds a Comprar'], errors='coerce').fillna(0) > 0)]
            if not df_seleccionados.empty:
                df_seleccionados['Valor de la Compra'] = pd.to_numeric(df_seleccionados['Uds a Comprar']) * pd.to_numeric(df_seleccionados['Costo_Promedio_UND'])
                st.markdown("---")
                proveedores_seleccion = df_seleccionados['Proveedor'].unique()
                tiendas_seleccion = df_seleccionados['Tienda'].unique()
                is_single_provider = len(proveedores_seleccion) == 1 and proveedores_seleccion[0] != 'NO ASIGNADO'
                is_single_store = len(tiendas_seleccion) == 1
                proveedor_actual = proveedores_seleccion[0] if is_single_provider else "CONSOLIDADO"
                tienda_actual = tiendas_seleccion[0] if is_single_store else "Multi-Tienda"
                info_proveedor = CONTACTOS_PROVEEDOR.get(proveedor_actual, {}) if is_single_provider else {}
                contacto_proveedor_nombre = info_proveedor.get('nombre', '')
                celular_proveedor_num = info_proveedor.get('celular', '')
                st.markdown(f"#### Opciones para la Orden a **{proveedor_actual}**")
                email_dest_placeholder = "ej: correo1@ejemplo.com, correo2@ejemplo.com"
                email_dest = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_principal", help=email_dest_placeholder, placeholder=email_dest_placeholder)
                whatsapp_dest = st.text_input("📱 Número de WhatsApp para notificación (ej: 573001234567):", value=celular_proveedor_num, key="wpp_principal", placeholder="573001234567")
                c1, c2, c3 = st.columns([2,1,1])
                orden_num = f"OC-{datetime.now().strftime('%Y%m%d-%H%M')}"
                direccion_entrega = DIRECCIONES_TIENDAS.get(tienda_actual, "Verificar con cada tienda")
                pdf_bytes = generar_pdf_orden_compra(df_seleccionados, proveedor_actual, tienda_actual, direccion_entrega, contacto_proveedor_nombre, orden_num, is_consolidated=(not is_single_provider))
                excel_bytes = generar_excel_dinamico(df_seleccionados, f"Compra_{proveedor_actual}")
                with c1:
                    if st.button("✅ Enviar y Registrar Orden", use_container_width=True, key="btn_enviar_principal", type="primary"):
                        if not email_dest:
                            st.warning("Por favor, ingrese al menos un correo electrónico de destinatario para enviar la orden.")
                        else:
                            with st.spinner("Enviando correo y registrando orden..."):
                                exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_seleccionados, "Compra Sugerencia")
                                if exito_registro:
                                    st.success(f"¡Orden registrada! {msg_registro}")
                                    orden_id_real = df_registrado['ID_Orden'].iloc[0] if not df_registrado.empty else orden_num
                                    lista_destinatarios = [email.strip() for email in email_dest.replace(';', ',').split(',') if email.strip()]
                                    if is_single_provider:
                                        asunto = f"Nueva Orden de Compra {orden_id_real} de Ferreinox SAS BIC - {proveedor_actual}"
                                        cuerpo_html = f"<html><body><p>Estimados Sres. {proveedor_actual},</p><p>Adjunto a este correo encontrarán nuestra <b>orden de compra N° {orden_id_real}</b> en formatos PDF y Excel.</p><p>Por favor, realizar el despacho a la siguiente dirección:</p><p><b>Sede de Entrega:</b> {tienda_actual}<br><b>Dirección:</b> {direccion_entrega}<br><b>Contacto en Bodega:</b> Leivyn Gabriel Garcia</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                    else:
                                        asunto = f"Nuevo Requerimiento Consolidado de Compra {orden_id_real} de Ferreinox SAS BIC"
                                        cuerpo_html = f"<html><body><p>Estimados proveedores,</p><p>Adjunto a este correo encontrarán un <b>requerimiento de compra consolidado N° {orden_id_real}</b> en formatos PDF y Excel. Por favor, revisar los items que corresponden a su empresa.</p><p>Las entregas deben coordinarse con cada tienda de destino según se especifica.</p><p>Agradecemos su pronta gestión.</p><p>Cordialmente,</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                    adjuntos = [{'datos': pdf_bytes, 'nombre_archivo': f"OC_{orden_id_real}_{proveedor_actual.replace(' ','_')}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                                {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_{orden_id_real}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                    enviado, mensaje = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                    if enviado: st.success(mensaje)
                                    else: st.error(mensaje)
                                    if whatsapp_dest:
                                        numero_completo = whatsapp_dest.strip().replace(" ", "")
                                        mensaje_wpp = f"Hola {contacto_proveedor_nombre or ''}, le acabamos de enviar la Orden de Compra N° {orden_id_real} al correo. Quedamos atentos. ¡Gracias!"
                                        link_wpp = generar_link_whatsapp(numero_completo, mensaje_wpp)
                                        st.link_button("📲 Enviar Confirmación por WhatsApp", link_wpp, target="_blank")
                                    st.success("Proceso completado. Los datos se actualizarán.")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Error al registrar en Google Sheets: {msg_registro}")
                with c2:
                    st.download_button("📥 Descargar Excel", data=excel_bytes, file_name=f"Compra_{proveedor_actual}.xlsx", use_container_width=True)
                with c3:
                    st.download_button("📄 Descargar PDF", data=pdf_bytes, file_name=f"OC_{orden_num}.pdf", use_container_width=True, disabled=(pdf_bytes is None))
                st.info(f"Total de la selección: ${df_seleccionados['Valor de la Compra'].sum():,.2f}")

    st.markdown("---")
    
    with st.expander("🆕 **Compras Especiales (Búsqueda y Creación Manual)**", expanded=False):
        st.markdown("##### 1. Buscar y añadir productos a la compra especial")
        search_term_compra_especial = st.text_input("Buscar cualquier producto por SKU o Descripción:", key="search_compra_especial")
        if search_term_compra_especial:
            mask_compra = (df_maestro['SKU'].astype(str).str.contains(search_term_compra_especial, case=False, na=False) |
                           df_maestro['Descripcion'].astype(str).str.contains(search_term_compra_especial, case=False, na=False))
            df_resultados_compra = df_maestro[mask_compra].drop_duplicates(subset=['SKU']).copy()
            if not df_resultados_compra.empty:
                df_resultados_compra['Uds a Comprar'] = 1
                df_resultados_compra['Seleccionar'] = False
                columnas_busqueda_compra = ['Seleccionar', 'SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND', 'Uds a Comprar']
                columnas_existentes_compra = [col for col in columnas_busqueda_compra if col in df_resultados_compra.columns]
                st.write("Resultados de la búsqueda:")
                edited_df_compra_especial = st.data_editor(
                    df_resultados_compra[columnas_existentes_compra], key="editor_compra_especial", hide_index=True, use_container_width=True,
                    column_config={
                        "Uds a Comprar": st.column_config.NumberColumn(min_value=1, step=1, required=True),
                        "Seleccionar": st.column_config.CheckboxColumn(required=True),
                        "Costo_Promedio_UND": st.column_config.NumberColumn(label="Costo Unitario", disabled=True, format="$%.2f")
                    },
                    disabled=['SKU', 'Descripcion', 'Proveedor', 'Costo_Promedio_UND'])
                df_para_anadir_compra = edited_df_compra_especial[edited_df_compra_especial['Seleccionar']]
                if st.button("➕ Añadir seleccionados a la Compra Especial", key="btn_anadir_compra_especial"):
                    if 'compra_especial_items' not in st.session_state: st.session_state.compra_especial_items = []
                    for _, row in df_para_anadir_compra.iterrows():
                        if not any(item['SKU'] == row['SKU'] for item in st.session_state.compra_especial_items):
                            st.session_state.compra_especial_items.append(row.to_dict())
                    st.success(f"{len(df_para_anadir_compra)} producto(s) añadidos a la compra.")
                    st.rerun()
            else:
                st.warning("No se encontraron productos para ese criterio de búsqueda.")
        
        if st.session_state.get('compra_especial_items'):
            st.markdown("---")
            st.markdown("##### 2. Revisar y gestionar la Compra Especial")
            df_solicitud_compra = pd.DataFrame(st.session_state.compra_especial_items)
            col_compra1, col_compra2 = st.columns(2)
            proveedor_especial = col_compra1.text_input("Ingrese el nombre del proveedor:", key="proveedor_especial_nombre")
            contacto_proveedor_especial = col_compra2.text_input("Ingrese el contacto del proveedor (opcional):", key="proveedor_especial_contacto")
            tiendas_destino_validas = sorted(df_maestro['Almacen_Nombre'].unique().tolist())
            tienda_destino_especial = st.selectbox("Seleccionar Tienda Destino para esta compra:", tiendas_destino_validas, key="destino_compra_especial")
            if 'Costo_Promedio_UND' in df_solicitud_compra.columns:
                df_solicitud_compra.rename(columns={'Costo_Promedio_UND': 'Costo_Unitario'}, inplace=True)
            st.dataframe(df_solicitud_compra[['SKU', 'Descripcion', 'Proveedor', 'Uds a Comprar', 'Costo_Unitario']], use_container_width=True)
            if st.button("🗑️ Limpiar Compra Especial", key="btn_limpiar_compra_especial"):
                st.session_state.compra_especial_items = []
                st.rerun()
            st.markdown("##### 3. Finalizar y enviar la Compra Especial")
            email_dest_compra_especial = st.text_input("📧 Correo(s) del destinatario para la compra especial:", key="email_compra_especial", help="Separados por coma.")
            if st.button("✅ Enviar y Registrar Compra Especial", use_container_width=True, key="btn_enviar_compra_especial", type="primary"):
                if not df_solicitud_compra.empty and proveedor_especial:
                    with st.spinner("Registrando y enviando compra especial..."):
                        exito_registro, msg_registro, df_registrado = registrar_ordenes_en_sheets(client, df_solicitud_compra, "Compra Especial", proveedor_nombre=proveedor_especial, tienda_destino=tienda_destino_especial)
                        if exito_registro:
                            st.success(f"✅ Compra especial registrada. {msg_registro}")
                            if email_dest_compra_especial:
                                orden_id_real = df_registrado['ID_Orden'].iloc[0] if not df_registrado.empty else f"OC-SP-{datetime.now().strftime('%Y%m%d')}"
                                pdf_bytes = generar_pdf_orden_compra(df_registrado, proveedor_especial, tienda_destino_especial, DIRECCIONES_TIENDAS.get(tienda_destino_especial, ""), contacto_proveedor_especial, orden_id_real)
                                excel_bytes = generar_excel_dinamico(df_registrado, f"CompraEspecial_{proveedor_especial}")
                                asunto = f"Nueva Orden de Compra Especial {orden_id_real} de Ferreinox"
                                cuerpo_html = f"<html><body><p>Estimado(a) {proveedor_especial},</p><p>Adjuntamos una orden de compra especial con ID <b>{orden_id_real}</b>. Por favor, revise los detalles en los archivos adjuntos.</p><p>Gracias.</p><p>--<br><b>Departamento de Compras</b><br>Ferreinox SAS BIC</p></body></html>"
                                adjuntos = [
                                    {'datos': pdf_bytes, 'nombre_archivo': f"OC_Especial_{orden_id_real}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                    {'datos': excel_bytes, 'nombre_archivo': f"Detalle_OC_Especial_{orden_id_real}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
                                ]
                                lista_destinatarios = [email.strip() for email in email_dest_compra_especial.split(',') if email.strip()]
                                enviado, msg = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                if enviado: st.success(msg)
                                else: st.error(msg)
                            st.session_state.compra_especial_items = []
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"❌ Error al registrar: {msg_registro}")
                else:
                    st.warning("La lista de compra está vacía o falta el nombre del proveedor.")

# ==============================================================================
# INICIO DE LA PESTAÑA DE SEGUIMIENTO (CÓDIGO ORIGINAL DE tab4)
# ==============================================================================
with tab4:
    st.subheader("✅ Seguimiento y Recepción de Órdenes")
    if df_ordenes_historico.empty:
        st.warning("No se pudo cargar el historial de órdenes desde Google Sheets o aún no hay órdenes registradas.")
    else:
        df_ordenes_vista_original = df_ordenes_historico.copy().sort_values(by="Fecha_Emision", ascending=False)
        with st.expander("Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=False):
            st.markdown("##### Filtrar Órdenes")
            track_c1, track_c2, track_c3 = st.columns(3)
            estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
            filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, index=0, key="filtro_estado_seguimiento")
            df_ordenes_vista = df_ordenes_vista_original.copy()
            if filtro_estado != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Estado'] == filtro_estado]
            proveedores_ordenes = ["Todos"] + sorted(df_ordenes_vista['Proveedor'].unique().tolist())
            filtro_proveedor_orden = track_c2.selectbox("Proveedor/Origen:", proveedores_ordenes, key="filtro_proveedor_seguimiento")
            if filtro_proveedor_orden != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Proveedor'] == filtro_proveedor_orden]
            tiendas_ordenes = ["Todos"] + sorted(df_ordenes_vista['Tienda_Destino'].unique().tolist())
            filtro_tienda_orden = track_c3.selectbox("Tienda Destino:", tiendas_ordenes, key="filtro_tienda_seguimiento")
            if filtro_tienda_orden != "Todos": df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Tienda_Destino'] == filtro_tienda_orden]
            if df_ordenes_vista.empty:
                st.info("No hay órdenes que coincidan con los filtros seleccionados.")
            else:
                select_all_seguimiento = st.checkbox("Seleccionar / Deseleccionar Todas las Órdenes Visibles", value=False, key="select_all_seguimiento")
                df_ordenes_vista['Seleccionar'] = select_all_seguimiento
                columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                st.info("Selecciona las órdenes y luego elige el nuevo estado para actualizarlas en lote.")
                edited_df_seguimiento = st.data_editor(
                    df_ordenes_vista[columnas_seguimiento], hide_index=True, use_container_width=True,
                    key="editor_seguimiento", disabled=[col for col in columnas_seguimiento if col != 'Seleccionar'])
                df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]
                if not df_seleccion_seguimiento.empty:
                    st.markdown("##### Acciones en Lote para Órdenes Seleccionadas")
                    nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                    if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} SKUs a '{nuevo_estado}'", key="btn_actualizar_estado"):
                        df_historico_modificado = df_ordenes_historico.copy()
                        df_historico_modificado['ID_unico_fila'] = df_historico_modificado['ID_Orden'] + "_" + df_historico_modificado['SKU'].astype(str)
                        df_seleccion_seguimiento['ID_unico_fila'] = df_seleccion_seguimiento['ID_Orden'] + "_" + df_seleccion_seguimiento['SKU'].astype(str)
                        ids_unicos_a_actualizar = df_seleccion_seguimiento['ID_unico_fila'].tolist()
                        df_historico_modificado.loc[df_historico_modificado['ID_unico_fila'].isin(ids_unicos_a_actualizar), 'Estado'] = nuevo_estado
                        df_historico_modificado.drop(columns=['ID_unico_fila'], inplace=True)
                        with st.spinner("Actualizando estados en Google Sheets..."):
                            exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                            if exito:
                                st.success(f"¡Éxito! {len(ids_unicos_a_actualizar)} líneas de orden actualizadas. Recargando...")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"Error al actualizar Google Sheets: {msg}")
        
        st.markdown("---")
        
        with st.expander("🔍 Gestionar, Modificar o Reenviar una Orden Específica", expanded=True):
            orden_a_buscar = st.text_input("Buscar ID de Orden para modificar (ej: OC-2024..., TR-2024...):", key="search_orden_id")
            if st.button("Cargar Orden", key="btn_load_order"):
                if orden_a_buscar:
                    df_orden_cargada = df_ordenes_historico[df_ordenes_historico['ID_Orden'].str.startswith(orden_a_buscar.strip(), na=False)].copy()
                    if not df_orden_cargada.empty:
                        st.session_state.orden_modificada_df = df_orden_cargada
                        st.session_state.orden_cargada_id = orden_a_buscar.strip()
                        st.success(f"Orden '{st.session_state.orden_cargada_id}' cargada con {len(df_orden_cargada)} items.")
                    else:
                        st.error(f"No se encontró ninguna orden con el ID que comience por '{orden_a_buscar}'.")
                        st.session_state.orden_modificada_df = pd.DataFrame()
                        st.session_state.orden_cargada_id = None
                else:
                    st.warning("Por favor, ingrese un ID de orden para buscar.")
            
            if 'orden_modificada_df' in st.session_state and not st.session_state.orden_modificada_df.empty and st.session_state.orden_cargada_id:
                st.markdown(f"#### Editando Orden: **{st.session_state.orden_cargada_id}**")
                editor_key = f"editor_orden_{st.session_state.orden_cargada_id}"
                edited_orden_df = st.data_editor(
                    st.session_state.orden_modificada_df, key=editor_key, hide_index=True, use_container_width=True,
                    column_config={"Cantidad_Solicitada": st.column_config.NumberColumn(label="Cantidad", min_value=0, step=1),
                                   "Costo_Unitario": st.column_config.NumberColumn(label="Costo Unit.", format="$ %.2f")},
                    disabled=['ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Tienda_Destino', 'Estado', 'Costo_Total'])
                if st.button("💾 Guardar Cambios", key="btn_save_changes"):
                    df_historico_copy = df_ordenes_historico.copy()
                    df_historico_copy['temp_id'] = df_historico_copy['ID_Orden'] + df_historico_copy['SKU'].astype(str)
                    edited_orden_df['temp_id'] = edited_orden_df['ID_Orden'] + edited_orden_df['SKU'].astype(str)
                    
                    df_actualizado = df_historico_copy.set_index('temp_id')
                    df_cambios = edited_orden_df.set_index('temp_id')
                    df_actualizado.update(df_cambios)
                    df_actualizado.reset_index(drop=True, inplace=True)
                    
                    with st.spinner("Guardando cambios en Google Sheets..."):
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_actualizado)
                        if exito:
                            st.success("¡Cambios guardados exitosamente!")
                            st.cache_data.clear()
                            st.session_state.orden_modificada_df = edited_orden_df.drop(columns=['temp_id'])
                            st.rerun()
                        else:
                            st.error(f"Error al guardar: {msg}")
                st.markdown("---")
                st.markdown("##### Reenviar Notificaciones de la Orden (con cambios si los hay)")
                es_traslado = "TRASLADO" in edited_orden_df.iloc[0]['Proveedor']
                destinatario = edited_orden_df.iloc[0]['Tienda_Destino'] if es_traslado else edited_orden_df.iloc[0]['Proveedor']
                email_contacto, celular_contacto, nombre_contacto = "", "", ""
                if es_traslado:
                    info = CONTACTOS_TIENDAS.get(destinatario, {})
                    email_contacto, celular_contacto = info.get('email', ''), info.get('celular', '')
                else:
                    info = CONTACTOS_PROVEEDOR.get(destinatario, {})
                    celular_contacto, nombre_contacto = info.get('celular', ''), info.get('nombre', '')
                email_mod_dest = st.text_input("Correo(s) para notificación de cambio:", value=email_contacto, key="email_modificacion")
                pdf_mod_bytes = generar_pdf_orden_compra(edited_orden_df, destinatario, edited_orden_df.iloc[0]['Tienda_Destino'], "N/A", nombre_contacto, st.session_state.orden_cargada_id)
                excel_mod_bytes = generar_excel_dinamico(edited_orden_df, f"Orden_{st.session_state.orden_cargada_id}")
                mod_c1, mod_c2 = st.columns(2)
                with mod_c1:
                    if st.button("✉️ Enviar Correo con Corrección", key="btn_email_mod"):
                        if email_mod_dest:
                            with st.spinner("Enviando correo..."):
                                asunto = f"CORRECCIÓN: Orden {st.session_state.orden_cargada_id} de Ferreinox"
                                cuerpo_html = f"<html><body><p>Hola,</p><p>Se ha realizado una corrección en la orden <b>{st.session_state.orden_cargada_id}</b>. Por favor, tomar en cuenta la versión adjunta como la definitiva.</p><p>Gracias.</p><p>--<br>Ferreinox SAS BIC</p></body></html>"
                                adjuntos = [{'datos': pdf_mod_bytes, 'nombre_archivo': f"CORRECCION_OC_{st.session_state.orden_cargada_id}.pdf", 'tipo_mime': 'application', 'subtipo_mime': 'pdf'},
                                            {'datos': excel_mod_bytes, 'nombre_archivo': f"CORRECCION_Detalle_{st.session_state.orden_cargada_id}.xlsx", 'tipo_mime': 'application', 'subtipo_mime': 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'}]
                                lista_destinatarios = [email.strip() for email in email_mod_dest.split(',') if email.strip()]
                                enviado, msg = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                if enviado: st.success(msg)
                                else: st.error(msg)
                        else:
                            st.warning("Ingrese un correo para enviar la notificación.")
                with mod_c2:
                    if celular_contacto:
                        mensaje_wpp = f"Hola, se ha enviado una CORRECCIÓN de la orden {st.session_state.orden_cargada_id} al correo. Por favor revisar. Gracias."
                        link_wpp = generar_link_whatsapp(celular_contacto, mensaje_wpp)
                        st.link_button("📲 Notificar Corrección por WhatsApp", link_wpp, target="_blank", use_container_width=True)
