import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime, timedelta
import io

# --- 0. Configuración de la Página ---
st.set_page_config(page_title="Análisis de Tendencias", layout="wide", page_icon="🎯")
st.title("🎯 Panel Estratégico de Tendencias")
st.markdown("De los datos a las decisiones. Identifica, clasifica y actúa sobre las tendencias de tus productos para maximizar la rentabilidad y minimizar los riesgos.")

# --- 1. Funciones de Ayuda ---

@st.cache_data
def convert_df_to_excel(df):
    """Convierte un DataFrame a un archivo Excel en memoria para descarga."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Analisis_Tendencias')
        # Auto-ajustar columnas
        for column in df:
            column_length = max(df[column].astype(str).map(len).max(), len(column))
            col_idx = df.columns.get_loc(column)
            writer.sheets['Analisis_Tendencias'].set_column(col_idx, col_idx, column_length + 2)
    processed_data = output.getvalue()
    return processed_data

def parse_historial_ventas(historial_str):
    """Parsea el string de historial de ventas y devuelve un DataFrame limpio y ordenado."""
    if not isinstance(historial_str, str) or ':' not in historial_str:
        return pd.DataFrame(columns=['Fecha', 'Unidades'])
    
    records = []
    for venta in historial_str.split(','):
        try:
            fecha_str, cantidad_str = venta.split(':')
            records.append({
                'Fecha': datetime.strptime(fecha_str, '%Y-%m-%d'),
                'Unidades': float(cantidad_str)
            })
        except (ValueError, IndexError):
            continue
    
    if not records:
        return pd.DataFrame(columns=['Fecha', 'Unidades'])
        
    df = pd.DataFrame(records)
    return df.sort_values('Fecha').reset_index(drop=True)

@st.cache_data
def calcular_tendencia_y_volumen(historial_str):
    """Calcula la pendiente (tendencia) y el volumen total de ventas en los últimos 90 días."""
    df_ventas = parse_historial_ventas(historial_str)
    if len(df_ventas) < 2:
        return 0.0, 0.0

    # Filtrar ventas de los últimos 90 días para el cálculo de volumen
    fecha_limite = datetime.now() - timedelta(days=90)
    ventas_recientes = df_ventas[df_ventas['Fecha'] >= fecha_limite]
    volumen_90d = ventas_recientes['Unidades'].sum()

    df_ventas['Dias'] = (df_ventas['Fecha'] - df_ventas['Fecha'].min()).dt.days
    try:
        pendiente, _ = np.polyfit(df_ventas['Dias'], df_ventas['Unidades'], 1)
        return pendiente, volumen_90d
    except Exception:
        return 0.0, volumen_90d

# ✅ FUNCIÓN NUEVA PARA CORREGIR EL ERROR Y CALCULAR ESTACIONALIDAD
@st.cache_data
def calcular_estacionalidad_reciente(historial_str):
    """Compara ventas de últimos 30 días vs 30 días anteriores (31-60)."""
    df_ventas = parse_historial_ventas(historial_str)
    if df_ventas.empty:
        return 0.0

    hoy = datetime.now()
    hace_30_dias = hoy - timedelta(days=30)
    hace_60_dias = hoy - timedelta(days=60)

    ventas_ultimos_30 = df_ventas[(df_ventas['Fecha'] > hace_30_dias) & (df_ventas['Fecha'] <= hoy)]['Unidades'].sum()
    ventas_31_60 = df_ventas[(df_ventas['Fecha'] > hace_60_dias) & (df_ventas['Fecha'] <= hace_30_dias)]['Unidades'].sum()

    return ventas_ultimos_30 - ventas_31_60

# ✅ FUNCIÓN NUEVA PARA EL ANÁLISIS ESTRATÉGICO
def clasificar_producto(row):
    """Clasifica el producto en categorías estratégicas basadas en tendencia y volumen de ventas."""
    tendencia = row['Tendencia_Ventas']
    volumen = row['Volumen_Ventas_90d']
    
    # Umbrales (pueden ser ajustados)
    umbral_tendencia_alta = 0.05
    umbral_tendencia_baja = -0.05
    percentil_volumen = 75 # Consideramos "alto volumen" si está en el 25% superior de ventas
    
    try:
        umbral_volumen = np.percentile(row['all_volumes'], percentil_volumen)
    except: # Si falla el cálculo del percentil, usar un valor por defecto.
        umbral_volumen = 10 

    if tendencia > umbral_tendencia_alta and volumen > umbral_volumen:
        return "Producto Estrella 🌟"
    elif tendencia > umbral_tendencia_alta and volumen <= umbral_volumen:
        return "Joya Oculta 💎"
    elif tendencia < umbral_tendencia_baja and volumen > umbral_volumen:
        return "En Riesgo 💔"
    elif tendencia < umbral_tendencia_baja and volumen <= umbral_volumen:
        return "Problema Potencial 🐌"
    elif volumen > umbral_volumen:
        return "Gigante Dormido 💤"
    else:
        return "Producto Estable 😐"

# --- Lógica Principal de la Página ---

if 'df_analisis' not in st.session_state or st.session_state['df_analisis'].empty:
    st.error("Los datos no se han cargado. Por favor, ve a la página principal '🚀 Resumen Ejecutivo de Inventario' primero.")
    st.page_link("app.py", label="Ir a la Página Principal", icon="🏠")
else:
    df_analisis_completo = st.session_state['df_analisis'].reset_index()

    st.sidebar.header("Filtros de Vista")
    opcion_consolidado = "-- Consolidado (Todas las Tiendas) --"
    nombres_almacen = df_analisis_completo[['Almacen_Nombre', 'Almacen']].drop_duplicates()
    map_nombre_a_codigo = pd.Series(nombres_almacen.Almacen.values, index=nombres_almacen.Almacen_Nombre).to_dict()
    lista_nombres_unicos = sorted([str(nombre) for nombre in nombres_almacen['Almacen_Nombre'].unique() if pd.notna(nombre)])
    lista_seleccion_nombres = [opcion_consolidado] + lista_nombres_unicos
    selected_almacen_nombre = st.sidebar.selectbox("Selecciona la Vista:", lista_seleccion_nombres, key="sb_tendencias")
    
    if selected_almacen_nombre == opcion_consolidado:
        df_vista = df_analisis_completo
    else:
        codigo_almacen_seleccionado = map_nombre_a_codigo.get(selected_almacen_nombre)
        df_vista = df_analisis_completo[df_analisis_completo['Almacen'] == codigo_almacen_seleccionado] if codigo_almacen_seleccionado else pd.DataFrame()

    lista_marcas_unicas = sorted([str(m) for m in df_vista['Marca_Nombre'].unique() if pd.notna(m)])
    selected_marcas = st.sidebar.multiselect("Filtrar por Marca:", lista_marcas_unicas, default=lista_marcas_unicas, key="filtro_marca_tendencias")
    
    df_filtered = df_vista[df_vista['Marca_Nombre'].isin(selected_marcas)].copy() if selected_marcas else pd.DataFrame()

    st.header(f"Análisis para: {selected_almacen_nombre}", divider='rainbow')

    if df_filtered.empty:
        st.warning("No hay datos para mostrar con los filtros seleccionados.")
    else:
        with st.spinner("Realizando análisis estratégico de tendencias..."):
            # --- CÁLCULOS AVANZADOS ---
            # 1. Calcular Tendencia y Volumen de Ventas
            tendencias_volumenes = df_filtered['Historial_Ventas'].apply(calcular_tendencia_y_volumen)
            df_filtered['Tendencia_Ventas'] = tendencias_volumenes.apply(lambda x: x[0])
            df_filtered['Volumen_Ventas_90d'] = tendencias_volumenes.apply(lambda x: x[1])
            
            # 2. Calcular Estacionalidad Reciente (Corrige el KeyError)
            df_filtered['Estacionalidad_Reciente'] = df_filtered['Historial_Ventas'].apply(calcular_estacionalidad_reciente)
            
            # 3. Calcular Impacto Financiero de la Tendencia
            df_filtered['Impacto_Potencial'] = df_filtered['Tendencia_Ventas'] * df_filtered['Costo_Promedio_UND']
            
            # 4. Clasificación Estratégica
            df_filtered['all_volumes'] = df_filtered['Volumen_Ventas_90d'].sum() # Ayuda para el cálculo de percentil
            df_filtered['Clasificacion'] = df_filtered.apply(clasificar_producto, axis=1)

        # --- KPIs Y MÉTRICAS PRINCIPALES ---
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Productos Acelerando 📈", len(df_filtered[df_filtered['Tendencia_Ventas'] > 0.05]))
        kpi2.metric("Productos Estables 😐", len(df_filtered[(df_filtered['Tendencia_Ventas'] >= -0.05) & (df_filtered['Tendencia_Ventas'] <= 0.05)]))
        kpi3.metric("Productos Desacelerando 📉", len(df_filtered[df_filtered['Tendencia_Ventas'] < -0.05]))
        kpi4.metric("Total Productos Analizados", len(df_filtered))

        # --- PESTAÑAS CON EL NUEVO ANÁLISIS ---
        tab1, tab2, tab3 = st.tabs(["🎯 Panel de Acción", "🚀 Oportunidades (Crecimiento)", "🐌 Riesgos (Decremento)"])

        with tab1:
            st.subheader("Matriz de Acción de Tendencias")
            st.info("""
            Este cuadrante clasifica tus productos para una acción inmediata:
            - **Productos Estrella (Arriba-Derecha):** Tu motor de crecimiento. ¡Proteger y potenciar!
            - **Joyas Ocultas (Abajo-Derecha):** Potencial sin explotar. ¡Impulsar!
            - **En Riesgo (Arriba-Izquierda):** Venden bien, pero caen. ¡Requieren atención urgente!
            - **Problemas Potenciales (Abajo-Izquierda):** Bajas ventas y en caída. ¡Evaluar y decidir!
            """)
            
            fig = px.scatter(
                df_filtered,
                x="Tendencia_Ventas",
                y="Volumen_Ventas_90d",
                size="Impacto_Potencial",
                color="Clasificacion",
                hover_name="Descripcion",
                hover_data=['SKU', 'Marca_Nombre'],
                log_y=True,  # Escala logarítmica para manejar grandes diferencias de volumen
                size_max=60,
                title="Matriz Estratégica de Productos",
                color_discrete_map={
                    "Producto Estrella 🌟": "#28a745",
                    "Joya Oculta 💎": "#17a2b8",
                    "En Riesgo 💔": "#ffc107",
                    "Gigante Dormido 💤": "#6c757d",
                    "Problema Potencial 🐌": "#dc3545",
                    "Producto Estable 😐": "#007bff"
                }
            )
            fig.update_layout(
                xaxis_title="Tendencia de Ventas (Crecimiento ➔)",
                yaxis_title="Volumen de Ventas (Últimos 90 días)",
                legend_title="Clasificación Estratégica"
            )
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            st.subheader("🚀 Oportunidades: Productos en Crecimiento")
            st.markdown("Estos productos están ganando tracción. La clave es capitalizar el momento.")
            
            df_crecimiento = df_filtered[df_filtered['Tendencia_Ventas'] > 0].sort_values(by='Impacto_Potencial', ascending=False).copy()
            
            if df_crecimiento.empty:
                st.info("No se encontraron productos con una tendencia clara de crecimiento.")
            else:
                df_crecimiento['Accion_Sugerida'] = df_crecimiento['Clasificacion'].apply(
                    lambda x: "Prioridad MÁXIMA. Asegurar stock y visibilidad." if x == "Producto Estrella 🌟" 
                    else "Impulsar con marketing. Analizar si puede ser una estrella." if x == "Joya Oculta 💎"
                    else "Vigilar de cerca. Base de ventas sólida."
                )
                
                st.dataframe(
                    df_crecimiento[['SKU', 'Descripcion', 'Marca_Nombre', 'Clasificacion', 'Tendencia_Ventas', 'Impacto_Potencial', 'Accion_Sugerida']],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Tendencia_Ventas": st.column_config.BarChartColumn("Tendencia", y_min=0, y_max=df_crecimiento['Tendencia_Ventas'].max()),
                        "Impacto_Potencial": st.column_config.NumberColumn("Impacto Potencial ($)", help="Tendencia x Costo. Mide el impacto financiero del crecimiento.", format="$%.2f")
                    }
                )
                st.download_button(
                    label="📥 Descargar Oportunidades en Excel",
                    data=convert_df_to_excel(df_crecimiento),
                    file_name=f"oportunidades_crecimiento_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                    mime="application/vnd.ms-excel"
                )
        
        with tab3:
            st.subheader("🐌 Riesgos: Productos en Decremento")
            st.markdown("Estos productos están perdiendo relevancia. Una gestión proactiva puede evitar pérdidas por obsolescencia.")

            df_decremento = df_filtered[df_filtered['Tendencia_Ventas'] < 0].sort_values(by='Impacto_Potencial', ascending=True).copy()

            if df_decremento.empty:
                st.info("No se encontraron productos con una tendencia clara de decremento.")
            else:
                df_decremento['Accion_Sugerida'] = df_decremento['Clasificacion'].apply(
                    lambda x: "¡ACCIÓN URGENTE! Analizar causa y considerar liquidación." if x == "En Riesgo 💔" 
                    else "Evaluar si vale la pena mantenerlo. Posible descontinuación." if x == "Problema Potencial 🐌"
                    else "Monitorear. Puede ser un cambio estacional."
                )
                
                st.dataframe(
                    df_decremento[['SKU', 'Descripcion', 'Marca_Nombre', 'Clasificacion', 'Tendencia_Ventas', 'Impacto_Potencial', 'Accion_Sugerida']],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Tendencia_Ventas": st.column_config.BarChartColumn("Tendencia", y_min=df_decremento['Tendencia_Ventas'].min(), y_max=0),
                        "Impacto_Potencial": st.column_config.NumberColumn("Impacto Potencial ($)", help="Tendencia x Costo. Mide el impacto financiero del decremento.", format="$%.2f")
                    }
                )
                st.download_button(
                    label="📥 Descargar Riesgos en Excel",
                    data=convert_df_to_excel(df_decremento),
                    file_name=f"riesgos_decremento_{selected_almacen_nombre.replace(' ', '_')}.xlsx",
                    mime="application/vnd.ms-excel"
                )
