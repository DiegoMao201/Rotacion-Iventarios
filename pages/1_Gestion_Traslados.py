# pages/1_Gestion_Traslados.py

import streamlit as st
import pandas as pd
from utils import initialize_session_state, display_traslados_ui, connect_to_gsheets

st.set_page_config(page_title="Gestión de Traslados", layout="wide", page_icon="🔄")
initialize_session_state()

# Verificar que los datos han sido cargados en la página principal
if 'df_maestro_procesado' not in st.session_state or st.session_state.df_maestro_procesado.empty:
    st.warning("⚠️ Por favor, ve primero al 'Tablero Principal' para cargar y filtrar los datos.")
    st.link_button("Ir al Tablero Principal", "/")
    st.stop()

client = connect_to_gsheets()
if client:
    # Llamamos a la función que construye toda la UI de traslados
    display_traslados_ui(client)
else:
    st.error("No se pudo establecer la conexión con Google Sheets.")
