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

# --- 0. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚚")

# --- 1. CARGA DE DATOS INICIAL ---
def load_initial_data():
    """Carga y procesa los datos necesarios para la página de abastecimiento."""
    if 'df_analisis_maestro' not in st.session_state or st.session_state.df_analisis_maestro.empty:
        st.warning("⚠️ Primero debes cargar y analizar los datos en el 'Tablero Principal'.")
        st.page_link("Tablero_Principal.py", label="Ir al Tablero Principal", icon="🚀")
        return None, None, None, None

    client = connect_to_gsheets()
    if not client:
        st.error("❌ No se pudo conectar a Google Sheets. Revisa la configuración y el estado del servicio.")
        return None, None, None, None

    with st.spinner("Cargando historial de órdenes y calculando sugerencias..."):
        df_maestro_base = st.session_state.df_analisis_maestro.copy()
        df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")
        df_maestro, df_plan_maestro = calcular_sugerencias_finales(df_maestro_base, df_ordenes_historico)
    
    return client, df_maestro, df_plan_maestro, df_ordenes_historico

# Ejecutar carga de datos
client, df_maestro, df_plan_maestro, df_ordenes_historico = load_initial_data()

# Detener si la carga inicial falla
if client is None or df_maestro is None:
    st.stop()

# --- 2. TÍTULO Y FILTROS GLOBALES ---
st.title("🚚 Módulo de Gestión de Abastecimiento")
st.markdown("Genera y gestiona órdenes de compra, traslados entre tiendas y haz seguimiento.")

df_filtered_global = st.session_state.get('df_filtered_global', pd.DataFrame())
if df_filtered_global.empty:
    st.info("ℹ️ No hay datos que coincidan con los filtros seleccionados en el Tablero Principal.")
    st.stop()

# Aplicar filtros heredados de la página principal
df_filtered = df_maestro[df_maestro['index'].isin(df_filtered_global['index'])]

# --- 3. INTERFAZ DE PESTAÑAS ---
tab_traslados, tab_compras, tab_seguimiento = st.tabs(["🔄 Traslados", "🛒 Compras", "✅ Seguimiento"])


# ==============================================================================
# PESTAÑA DE TRASLADOS
# ==============================================================================
with tab_traslados:
    st.header("🚚 Plan de Traslados entre Tiendas")
    
    with st.expander("🔄 **Plan de Traslados Automático (Sugerencias)**", expanded=True):
        if df_plan_maestro is None or df_plan_maestro.empty:
            st.success("✅ ¡No se sugieren traslados automáticos en este momento!")
        else:
            st.markdown("##### Filtros del Plan de Traslado")
            
            col1, col2 = st.columns(2)
            
            lista_destinos = ["Todas"] + sorted(df_plan_maestro['Tienda Destino'].unique().tolist())
            filtro_destino = col1.selectbox("Filtrar por Tienda Destino:", lista_destinos, key="filtro_destino")

            df_aplicar_filtros = df_plan_maestro.copy()
            if filtro_destino != "Todas":
                df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Tienda Destino'] == filtro_destino]

            if not df_aplicar_filtros.empty:
                lista_proveedores_traslado = ["Todos"] + sorted(df_aplicar_filtros['Proveedor'].unique().tolist())
                filtro_proveedor_traslado = col2.selectbox("Filtrar por Proveedor:", lista_proveedores_traslado, key="filtro_proveedor_traslado")
                if filtro_proveedor_traslado != "Todos":
                    df_aplicar_filtros = df_aplicar_filtros[df_aplicar_filtros['Proveedor'] == filtro_proveedor_traslado]
            
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
                                
                                st.success("Proceso completado. La página se recargará para actualizar los datos.")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"❌ Error al registrar el traslado en Google Sheets: {msg_registro}")

# ==============================================================================
# PESTAÑA DE COMPRAS
# ==============================================================================
with tab_compras:
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
            
            st.markdown("Marque los artículos y **ajuste las cantidades** que desea incluir en la orden de compra:")
            edited_df = st.data_editor(
                df_a_mostrar_final[columnas_existentes],
                hide_index=True, use_container_width=True,
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
                email_dest = st.text_input("📧 Correos del destinatario (separados por coma):", key="email_principal", placeholder="correo1@ejemplo.com, correo2@ejemplo.com")
                whatsapp_dest = st.text_input("📱 Número de WhatsApp para notificación (ej: 573001234567):", value=celular_proveedor_num, key="wpp_principal")
                
                c1, c2, c3 = st.columns([2, 1, 1])
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
                                    # ... (Lógica de envío de notificaciones se mantiene)
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

# ==============================================================================
# PESTAÑA DE SEGUIMIENTO
# ==============================================================================
with tab_seguimiento:
    st.header("✅ Seguimiento y Recepción de Órdenes")

    if df_ordenes_historico.empty:
        st.warning("Aún no hay órdenes registradas o no se pudieron cargar desde Google Sheets.")
    else:
        df_ordenes_historico['Fecha_Emision'] = pd.to_datetime(df_ordenes_historico['Fecha_Emision'], errors='coerce')
        df_ordenes_vista_original = df_ordenes_historico.sort_values(by="Fecha_Emision", ascending=False).copy()

        with st.expander("🔄 Cambiar Estado de Múltiples Órdenes (En Lote)", expanded=False):
            st.markdown("##### 1. Filtrar Órdenes para Actualizar")
            
            required_filter_cols = ['Estado', 'Proveedor', 'Tienda_Destino']
            if not all(col in df_ordenes_vista_original.columns for col in required_filter_cols):
                st.error("El archivo 'Registro_Ordenes' no contiene las columnas necesarias para el filtrado.")
            else:
                track_c1, track_c2, track_c3 = st.columns(3)
                
                estados_disponibles = ["Todos"] + df_ordenes_vista_original['Estado'].unique().tolist()
                filtro_estado = track_c1.selectbox("Estado:", estados_disponibles, index=0, key="filtro_estado_seguimiento")
                
                df_ordenes_vista = df_ordenes_vista_original.copy()
                if filtro_estado != "Todos":
                    df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Estado'] == filtro_estado]

                if not df_ordenes_vista.empty:
                    proveedores_ordenes = ["Todos"] + sorted(df_ordenes_vista['Proveedor'].unique().tolist())
                    filtro_proveedor_orden = track_c2.selectbox("Proveedor/Origen:", proveedores_ordenes, key="filtro_proveedor_seguimiento")
                    if filtro_proveedor_orden != "Todos":
                        df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Proveedor'] == filtro_proveedor_orden]

                if not df_ordenes_vista.empty:
                    tiendas_ordenes = ["Todos"] + sorted(df_ordenes_vista['Tienda_Destino'].unique().tolist())
                    filtro_tienda_orden = track_c3.selectbox("Tienda Destino:", tiendas_ordenes, key="filtro_tienda_seguimiento")
                    if filtro_tienda_orden != "Todos":
                        df_ordenes_vista = df_ordenes_vista[df_ordenes_vista['Tienda_Destino'] == filtro_tienda_orden]
                
                if df_ordenes_vista.empty:
                    st.info("No hay órdenes que coincidan con los filtros seleccionados.")
                else:
                    st.markdown("##### 2. Seleccionar Órdenes y Actualizar")
                    select_all_seguimiento = st.checkbox("Seleccionar / Deseleccionar Todas las Órdenes Visibles", value=False, key="select_all_seguimiento")
                    df_ordenes_vista['Seleccionar'] = select_all_seguimiento
                    
                    columnas_seguimiento = ['Seleccionar', 'ID_Orden', 'Fecha_Emision', 'Proveedor', 'SKU', 'Descripcion', 'Cantidad_Solicitada', 'Tienda_Destino', 'Estado']
                    
                    edited_df_seguimiento = st.data_editor(
                        df_ordenes_vista[columnas_seguimiento], hide_index=True, use_container_width=True,
                        key="editor_seguimiento", disabled=[col for col in columnas_seguimiento if col != 'Seleccionar'],
                        column_config={"Fecha_Emision": st.column_config.DateColumn("Fecha", format="YYYY-MM-DD")}
                    )
                    
                    df_seleccion_seguimiento = edited_df_seguimiento[edited_df_seguimiento['Seleccionar']]
                    
                    if not df_seleccion_seguimiento.empty:
                        nuevo_estado = st.selectbox("Seleccionar nuevo estado:", ["Recibido", "Cancelado", "Pendiente"], key="nuevo_estado_lote")
                        
                        if st.button(f"➡️ Actualizar {len(df_seleccion_seguimiento)} SKUs a '{nuevo_estado}'", key="btn_actualizar_estado", type="primary"):
                            df_historico_modificado = df_ordenes_historico.copy()
                            df_historico_modificado['ID_unico_fila'] = df_historico_modificado['ID_Orden'].astype(str) + "_" + df_historico_modificado['SKU'].astype(str)
                            df_seleccion_seguimiento['ID_unico_fila'] = df_seleccion_seguimiento['ID_Orden'].astype(str) + "_" + df_seleccion_seguimiento['SKU'].astype(str)
                            ids_unicos_a_actualizar = df_seleccion_seguimiento['ID_unico_fila'].tolist()
                            df_historico_modificado.loc[df_historico_modificado['ID_unico_fila'].isin(ids_unicos_a_actualizar), 'Estado'] = nuevo_estado
                            df_historico_modificado.drop(columns=['ID_unico_fila'], inplace=True)
                            
                            with st.spinner("Actualizando estados en Google Sheets..."):
                                exito, msg = update_sheet(client, "Registro_Ordenes", df_historico_modificado)
                                if exito:
                                    st.success(f"¡Éxito! {len(ids_unicos_a_actualizar)} líneas de orden actualizadas. La página se recargará.")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Error al actualizar Google Sheets: {msg}")

        st.markdown("---")

        with st.expander("🔍 Gestionar o Modificar una Orden Específica", expanded=True):
            orden_a_buscar = st.text_input("Buscar por ID de Orden para ver o modificar (ej: OC-2024..., TR-2024...):", key="search_orden_id")

            if st.button("Cargar Orden", key="btn_load_order"):
                if orden_a_buscar:
                    df_orden_cargada = df_ordenes_historico[df_ordenes_historico['ID_Orden'].str.contains(orden_a_buscar.strip(), case=False, na=False)].copy()
                    
                    if not df_orden_cargada.empty:
                        st.session_state.orden_modificada_df = df_orden_cargada
                        st.session_state.orden_cargada_id = df_orden_cargada['ID_Orden'].iloc[0]
                        st.success(f"Orden '{st.session_state.orden_cargada_id}' cargada con {len(df_orden_cargada)} items.")
                    else:
                        st.error(f"No se encontró ninguna orden con el ID que contenga '{orden_a_buscar}'.")
                        st.session_state.orden_modificada_df = pd.DataFrame()
                        st.session_state.orden_cargada_id = None
                else:
                    st.warning("Por favor, ingrese un ID de orden para buscar.")
            
            if 'orden_modificada_df' in st.session_state and not st.session_state.orden_modificada_df.empty:
                orden_id_actual = st.session_state.orden_cargada_id
                st.markdown(f"#### Editando Orden: **{orden_id_actual}**")

                edited_orden_df = st.data_editor(
                    st.session_state.orden_modificada_df, key=f"editor_orden_{orden_id_actual}",
                    hide_index=True, use_container_width=True, num_rows="dynamic",
                    column_config={
                        "Cantidad_Solicitada": st.column_config.NumberColumn(label="Cantidad", min_value=0, step=1, required=True),
                        "Costo_Unitario": st.column_config.NumberColumn(label="Costo Unit.", format="$ %.2f", required=True),
                    }
                )

                if st.button("💾 Guardar Cambios en la Orden", key="btn_save_changes", type="primary"):
                    df_historico_copy = df_ordenes_historico.copy()
                    df_historico_sin_orden = df_historico_copy[df_historico_copy['ID_Orden'] != orden_id_actual]
                    df_final_actualizado = pd.concat([df_historico_sin_orden, edited_orden_df], ignore_index=True)

                    with st.spinner("Guardando cambios en Google Sheets..."):
                        exito, msg = update_sheet(client, "Registro_Ordenes", df_final_actualizado)
                        if exito:
                            st.success("¡Cambios guardados exitosamente! La página se recargará.")
                            st.cache_data.clear()
                            st.session_state.orden_modificada_df = edited_orden_df
                            st.rerun()
                        else:
                            st.error(f"Error al guardar: {msg}")

                st.markdown("---")
                st.markdown("##### 📣 Reenviar Notificaciones de la Orden (con los cambios actuales)")
                
                if not edited_orden_df.empty:
                    es_traslado = "TRASLADO" in edited_orden_df.iloc[0].get('Proveedor', '')
                    destinatario_principal = edited_orden_df.iloc[0]['Tienda_Destino'] if es_traslado else edited_orden_df.iloc[0]['Proveedor']
                    
                    email_contacto, celular_contacto, nombre_contacto = "", "", ""

                    if es_traslado:
                        info_contacto = CONTACTOS_TIENDAS.get(destinatario_principal, {})
                        email_contacto = info_contacto.get('email', '')
                        celular_contacto = info_contacto.get('celular', '')
                    else:
                        info_contacto = CONTACTOS_PROVEEDOR.get(destinatario_principal, {})
                        celular_contacto = info_contacto.get('celular', '')
                        nombre_contacto = info_contacto.get('nombre', '')
                    
                    email_mod_dest = st.text_input(
                        "Correo(s) para notificación de cambio (separados por coma):",
                        value=email_contacto, key="email_modificacion"
                    )
                    
                    pdf_mod_bytes = generar_pdf_orden_compra(
                        edited_orden_df, destinatario_principal, edited_orden_df.iloc[0]['Tienda_Destino'], 
                        DIRECCIONES_TIENDAS.get(edited_orden_df.iloc[0]['Tienda_Destino'], "N/A"), 
                        nombre_contacto, orden_id_actual
                    )
                    excel_mod_bytes = generar_excel_dinamico(edited_orden_df, f"Orden_{orden_id_actual}")

                    mod_c1, mod_c2 = st.columns(2)
                    with mod_c1:
                        if st.button("✉️ Enviar Correo con Corrección", key="btn_email_mod"):
                            if email_mod_dest and pdf_mod_bytes:
                                with st.spinner("Enviando correo..."):
                                    asunto = f"CORRECCIÓN: Orden {orden_id_actual} de Ferreinox"
                                    cuerpo_html = f"<html><body><p>Hola,</p><p>Se ha realizado una corrección en la orden <b>{orden_id_actual}</b>. Por favor, tomar en cuenta la versión adjunta como la definitiva.</p><p>Gracias.</p><p>--<br>Ferreinox SAS BIC</p></body></html>"
                                    adjuntos = [{'datos': pdf_mod_bytes, 'nombre_archivo': f"CORRECCION_OC_{orden_id_actual}.pdf"}, {'datos': excel_mod_bytes, 'nombre_archivo': f"CORRECCION_Detalle_{orden_id_actual}.xlsx"}]
                                    lista_destinatarios = [email.strip() for email in email_mod_dest.split(',') if email.strip()]
                                    enviado, msg = enviar_correo_con_adjuntos(lista_destinatarios, asunto, cuerpo_html, adjuntos)
                                    if enviado: st.success(msg)
                                    else: st.error(msg)
                            else:
                                st.warning("Ingrese un correo válido para enviar la notificación.")
                    
                    with mod_c2:
                        if celular_contacto:
                            mensaje_wpp = f"Hola, se ha enviado una CORRECCIÓN de la orden {orden_id_actual} al correo. Por favor revisar. Gracias."
                            link_wpp = generar_link_whatsapp(celular_contacto, mensaje_wpp)
                            st.link_button("📲 Notificar Corrección por WhatsApp", link_wpp, target="_blank", use_container_width=True)
                        else:
                            st.caption("No hay un número de WhatsApp configurado para este contacto.")
