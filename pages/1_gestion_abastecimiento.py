# app.py

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# Importa las funciones y componentes desde tu nuevo archivo utils
from utils import (
    initialize_session_state,
    connect_to_gsheets,
    load_data_from_sheets,
    update_sheet,
    calcular_estado_inventario_completo,
    generar_plan_traslados_inteligente,
    registrar_ordenes_en_sheets,
    enviar_correo_con_adjuntos,
    generar_link_whatsapp,
    generar_excel_dinamico,
    display_seguimiento_tab, # <-- Importante: el componente de la pestaña
    CONTACTOS_TIENDAS
)

# --- 0. CONFIGURACIÓN DE PÁGINA Y ESTADO ---
st.set_page_config(page_title="Gestión de Abastecimiento", layout="wide", page_icon="🚀")
initialize_session_state()

# --- 1. CARGA DE DATOS ---
st.title("🚀 Tablero de Control de Abastecimiento")
st.markdown("Analiza, prioriza y actúa. Tu sistema de gestión en tiempo real.")

client = connect_to_gsheets()
if client:
    # Carga de datos base (si es necesario desde una página de login previa, este patrón funciona)
    if 'df_analisis_maestro' not in st.session_state or st.session_state.df_analisis_maestro.empty:
        df_maestro_base = load_data_from_sheets(client, "Consolidado_Inventario") # Ajusta el nombre de tu hoja base
        if not df_maestro_base.empty:
            st.session_state.df_analisis_maestro = df_maestro_base
        else:
            st.warning("⚠️ No se pudieron cargar los datos base de inventario. Algunas funciones pueden no estar disponibles.")
            st.stop()
    else:
        df_maestro_base = st.session_state.df_analisis_maestro.copy()

    df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")
    
    # --- 2. PROCESAMIENTO DE DATOS ---
    df_maestro, df_plan_maestro = calcular_estado_inventario_completo(df_maestro_base, df_ordenes_historico)
else:
    st.error("No se pudo establecer conexión con Google Sheets. La aplicación no puede continuar.")
    st.stop()


# --- 3. SIDEBAR Y FILTROS ---
with st.sidebar:
    st.header("⚙️ Filtros de Gestión")
    opcion_consolidado = '-- Consolidado (Todas las Tiendas) --'
    
    # Asumiendo que el rol y almacén se establecen en un login anterior y se guardan en session_state
    if st.session_state.get('user_role') == 'gerente':
        almacen_options = [opcion_consolidado] + sorted(df_maestro['Almacen_Nombre'].unique().tolist())
    else:
        almacen_options = [st.session_state.get('almacen_nombre')] if st.session_state.get('almacen_nombre') else []
        
    selected_almacen_nombre = st.selectbox("Selecciona la Vista de Tienda:", almacen_options)
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_maestro.copy()
    else:
        df_vista = df_maestro[df_maestro['Almacen_Nombre'] == selected_almacen_nombre]
        
    marcas_unicas = sorted(df_vista['Marca_Nombre'].unique().tolist())
    selected_marcas = st.multiselect("Filtrar por Marca:", marcas_unicas, default=marcas_unicas)
    
    if selected_marcas:
        df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)]
    else:
        df_filtered = df_vista

    st.markdown("---")
    st.info("Utiliza el menú de la izquierda para navegar a la sección de Compras.")


# --- 4. INTERFAZ DE PESTAÑAS ---
tab1, tab2, tab_seguimiento = st.tabs(["📊 Diagnóstico", "🔄 Traslados", "✅ Seguimiento"])

with tab1:
    # Pega aquí todo el código que tenías dentro de `with tab1:`
    st.subheader(f"Diagnóstico para: {selected_almacen_nombre}")
    # ... (el resto del código de la pestaña de diagnóstico) ...
    pass # Placeholder

with tab2:
    # Pega aquí todo el código que tenías dentro de `with tab2:`
    st.subheader("🚚 Plan de Traslados entre Tiendas")
    # ... (el resto del código de la pestaña de traslados) ...
    pass # Placeholder

with tab_seguimiento:
    # ¡Mágia! Simplemente llamamos a la función compartida.
    display_seguimiento_tab(client, df_ordenes_historico)
