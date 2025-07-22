# pages/compras.py

import streamlit as st
import pandas as pd
from datetime import datetime

# Importa las funciones necesarias desde utils.py
from utils import (
    initialize_session_state,
    connect_to_gsheets,
    load_data_from_sheets,
    calcular_estado_inventario_completo,
    registrar_ordenes_en_sheets,
    enviar_correo_con_adjuntos,
    generar_link_whatsapp,
    generar_excel_dinamico,
    generar_pdf_orden_compra,
    display_seguimiento_tab, # <-- El mismo componente reutilizado
    DIRECCIONES_TIENDAS,
    CONTACTOS_PROVEEDOR
)

# --- 0. CONFIGURACIÓN Y ESTADO ---
st.set_page_config(page_title="Compras y Seguimiento", layout="wide", page_icon="🛒")
initialize_session_state()

# --- 1. CARGA Y PROCESAMIENTO DE DATOS ---
st.header("🛒 Gestión de Compras")
client = connect_to_gsheets()

if client and not st.session_state.df_analisis_maestro.empty:
    df_maestro_base = st.session_state.df_analisis_maestro.copy()
    df_ordenes_historico = load_data_from_sheets(client, "Registro_Ordenes")
    df_maestro, _ = calcular_estado_inventario_completo(df_maestro_base, df_ordenes_historico)
else:
    st.warning("⚠️ Los datos de inventario no están cargados. Por favor, ve a la página principal 'app.py' para iniciar.")
    st.stop()


# --- 2. FILTROS (si son necesarios en esta página) ---
# Puedes añadir filtros específicos para compras si lo deseas, o usar los datos completos.
df_filtered = df_maestro.copy() # Usamos el df completo por simplicidad aquí

# --- 3. INTERFAZ DE PESTAÑAS ---
tab_compras, tab_seguimiento = st.tabs(["🛒 Compras", "✅ Seguimiento"])

with tab_compras:
    # Pega aquí todo el código que tenías dentro de `with tab3:`
    st.header("🛒 Plan de Compras")
    # ... (el resto del código de la pestaña de compras) ...
    pass # Placeholder

with tab_seguimiento:
    # Reutilizamos el componente de seguimiento, ¡así de fácil!
    display_seguimiento_tab(client, df_ordenes_historico)
