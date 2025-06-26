# app_inventario_consolidado.py
# -----------------------------
# Este script unifica el análisis de inventario y la visualización en Streamlit.
# Se conecta a Dropbox para leer los datos, los procesa en memoria y muestra
# un tablero interactivo con filtros, KPIs, gráficos y tablas descargables.

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import dropbox
import io

# --- 1. CONFIGURACIÓN INICIAL DE LA PÁGINA ---
st.set_page_config(
    page_title="Tablero de Control de Inventario",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. LÓGICA DE CARGA DE DATOS DESDE DROPBOX ---
# Esta función reemplaza la lectura de archivos locales.
# Se cachea para no descargar el archivo en cada interacción del usuario.
@st.cache_data(ttl=600) # Cache expira cada 10 minutos
def cargar_datos_desde_dropbox():
    """
    Se conecta a Dropbox usando credenciales de st.secrets, descarga el archivo CSV
    de inventario y lo carga en un DataFrame de Pandas.
    """
    # Usamos un placeholder para el mensaje de carga
    info_message = st.empty()
    info_message.info("Conectando a Dropbox para obtener los datos más recientes...")
    try:
        # Lee las credenciales y la ruta del archivo desde secrets.toml
        dbx_creds = st.secrets["dropbox"]
        
        # Se conecta usando el método robusto con refresh token
        with dropbox.Dropbox(
            app_key=dbx_creds["app_key"],
            app_secret=dbx_creds["app_secret"],
            oauth2_refresh_token=dbx_creds["refresh_token"]
        ) as dbx:
            metadata, res = dbx.files_download(path=dbx_creds["file_path"])
            
            with io.BytesIO(res.content) as stream:
                # *** CORRECCIÓN FINAL Y MÁS ROBUSTA ***
                # Se añaden los parámetros quotechar y quoting para manejar correctamente
                # las comas dentro de los campos de texto (ej. en las descripciones).
                df_crudo = pd.read_csv(
                    stream, 
                    encoding='latin1', 
                    sep=',', 
                    engine='python',
                    quotechar='"', # Define el caracter para encerrar texto.
                    quoting=1      # QUOTE_MINIMAL: respeta las comillas en el archivo.
                )
            
            # Limpiamos el mensaje de "cargando" y mostramos éxito
            info_message.empty()
            st.success("¡Datos cargados exitosamente desde Dropbox!")
            return df_crudo

    except dropbox.exceptions.AuthError as err:
        info_message.error(f"Error de autenticación con Dropbox: {err}. Verifica tus credenciales en los 'secrets' de Streamlit.")
        return None
    except dropbox.exceptions.ApiError as err:
        info_message.error(f"Error de API con Dropbox: {err}. Asegúrate que la ruta del archivo en tus 'secrets' sea correcta: '{st.secrets.get('dropbox', {}).get('file_path', 'No configurado')}'.")
        return None
    except Exception as e:
        info_message.error(f"Ocurrió un error inesperado al cargar los datos: {e}")
        return None

# --- 3. LÓGICA DE ANÁLISIS DE INVENTARIO (ADAPTADA DE TU .QMD) ---
# Esta es la función principal que contiene toda tu lógica de negocio.
# También se cachea para que el análisis pesado se haga solo una vez por carga de datos.
@st.cache_data
def analizar_inventario_completo(_df_crudo, almacen_principal='155'):
    """
    Aplica toda la lógica de análisis del QMD a un DataFrame.
    El guion bajo en _df_crudo es una convención para indicar que el DataFrame
    no debe ser modificado directamente.
    """
    if _df_crudo is None or _df_crudo.empty:
        return pd.DataFrame()
        
    df = _df_crudo.copy()

    # Limpieza y renombrado de columnas para que coincidan con la consulta SQL
    df.columns = df.columns.str.strip().str.upper() # Convertir a mayúsculas para consistencia
    
    # El mapeo ahora usa los nombres de columna EXACTOS de tu consulta SQL.
    column_mapping = {
        'CODALMACEN': 'Almacen',
        'DEPARTAMENTO': 'Departamento',
        'DESCRIPCION': 'Descripcion',
        'UNIDADES_VENDIDAS': 'Ventas_60_Dias',
        'STOCK': 'Stock',
        'PRECIO_PROMOCION': 'Precio_Promocion', # Asumiendo que esta columna existe
        'COSTO_PROMEDIO_UND': 'Costo_Promedio_UND',
        'REFERENCIA': 'SKU',
        'PESO_ARTICULO': 'PESO_ARTICULO'
    }
    df.rename(columns=column_mapping, inplace=True)

    # Validación de Columnas Esenciales
    essential_cols_map = {
        'Almacen': "'CODALMACEN'",
        'SKU': "'REFERENCIA'",
        'Stock': "'STOCK'",
        'Ventas_60_Dias': "'UNIDADES_VENDIDAS'"
    }
    missing_cols = [original_name for col, original_name in essential_cols_map.items() if col not in df.columns]

    if missing_cols:
        st.error(f"**Error Crítico de Datos:**\n\nNo se encontraron las siguientes columnas esenciales en tu archivo `Rotacion.csv`:\n\n* **{', '.join(missing_cols)}**\n\nPor favor, asegúrate de que tu consulta SQL genere estas columnas para que el análisis pueda continuar.")
        return pd.DataFrame() # Devuelve un DF vacío para detener el proceso de forma segura.


    # Preprocesamiento y conversión de tipos
    for col in ['Ventas_60_Dias', 'Precio_Promocion', 'Costo_Promedio_UND']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        else:
            df[col] = 0

    for col in ['Stock', 'PESO_ARTICULO']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        else:
            df[col] = 0

    df['Stock'] = df['Stock'].apply(lambda x: max(0, x))
    df['Almacen'] = df['Almacen'].astype(str)
    
    if 'Departamento' not in df.columns:
        df['Departamento'] = 'No especificado'
    else:
        df['Departamento'] = df['Departamento'].astype(str).fillna('No especificado')


    # Cálculo de Métricas Clave
    df['Demanda_Diaria_Promedio'] = df['Ventas_60_Dias'] / 60
    df['Rotacion_60_Dias'] = df.apply(lambda r: r['Ventas_60_Dias'] / r['Stock'] if r['Stock'] > 0 else 0, axis=1)
    df['Dias_Inventario'] = df.apply(lambda r: (r['Stock'] / r['Demanda_Diaria_Promedio']) if r['Demanda_Diaria_Promedio'] > 0 else np.inf, axis=1)
    
    # Segmentación ABC
    ventas_sku = df.groupby('SKU')['Ventas_60_Dias'].sum()
    total_ventas = ventas_sku.sum()
    
    if total_ventas > 0:
        sku_to_percent = ventas_sku.sort_values(ascending=False).cumsum() / total_ventas
    else:
        sku_to_percent = pd.Series(0, index=ventas_sku.index)

    def segmentar_abc(p):
        if p <= 0.8: return 'A'
        if p <= 0.95: return 'B'
        return 'C'

    df['Segmento_ABC'] = df['SKU'].map(sku_to_percent).apply(segmentar_abc).fillna('C')

    # Segmentación por Estado de Inventario Local
    def segmentar_estado(row):
        if row['Stock'] <= 0 and row['Demanda_Diaria_Promedio'] > 0: return 'Quiebre de Stock'
        if row['Stock'] > 0 and row['Demanda_Diaria_Promedio'] <= 0: return 'Baja Rotación / Obsoleto'
        if row['Dias_Inventario'] < 15 and row['Demanda_Diaria_Promedio'] > 0: return 'Bajo Stock / Reordenar'
        if row['Dias_Inventario'] > 45: return 'Excedente'
        return 'Normal'
    df['Estado_Inventario_Local'] = df.apply(segmentar_estado, axis=1)

    # Lógica de Reparto de Inventario
    df['Sugerencia_Traslado'] = 'No aplica traslado.'
    df['Unidades_Traslado_Sugeridas'] = 0
    
    df_reparto = df.copy()

    for sku in df_reparto['SKU'].unique():
        necesidad_mask = (df_reparto['SKU'] == sku) & (df_reparto['Estado_Inventario_Local'].isin(['Quiebre de Stock', 'Bajo Stock / Reordenar']))
        if not necesidad_mask.any():
            continue

        excedente_df = df_reparto[(df_reparto['SKU'] == sku) & (df_reparto['Stock'] > 0) & (df_reparto['Almacen'] != almacen_principal)].copy()
        
        for idx_necesidad in df_reparto[necesidad_mask].index:
            demanda_diaria_destino = df_reparto.loc[idx_necesidad, 'Demanda_Diaria_Promedio']
            stock_actual_destino = df_reparto.loc[idx_necesidad, 'Stock']
            stock_objetivo = demanda_diaria_destino * 30
            cantidad_necesaria = max(0, stock_objetivo - stock_actual_destino)
            
            if cantidad_necesaria <= 0:
                continue

            origenes_sugeridos = []
            unidades_acumuladas = 0

            for idx_excedente, row_excedente in excedente_df.iterrows():
                if row_excedente['Stock'] > 0:
                    cantidad_a_mover = min(cantidad_necesaria, row_excedente['Stock'])
                    origenes_sugeridos.append(f"Almacén {row_excedente['Almacen']} ({int(cantidad_a_mover)} u.)")
                    excedente_df.loc[idx_excedente, 'Stock'] -= cantidad_a_mover
                    cantidad_necesaria -= cantidad_a_mover
                    unidades_acumuladas += cantidad_a_mover
                    if cantidad_necesaria <= 0:
                        break
            
            if origenes_sugeridos:
                df.loc[idx_necesidad, 'Sugerencia_Traslado'] = f"Desde: {', '.join(origenes_sugeridos)}"
                df.loc[idx_necesidad, 'Unidades_Traslado_Sugeridas'] = int(unidades_acumuladas)
    
    # Recomendaciones finales
    df['Recomendacion'] = 'Mantener monitoreo.'
    df.loc[df['Estado_Inventario_Local'] == 'Quiebre de Stock', 'Recomendacion'] = '¡Prioridad máxima! Reabastecer inmediatamente.'
    df.loc[df['Estado_Inventario_Local'] == 'Baja Rotación / Obsoleto', 'Recomendacion'] = 'Considerar liquidación o descontinuación.'
    df.loc[df['Estado_Inventario_Local'] == 'Bajo Stock / Reordenar', 'Recomendacion'] = 'Revisar urgencia de reabastecimiento.'
    df.loc[df['Estado_Inventario_Local'] == 'Excedente', 'Recomendacion'] = 'Alto excedente. Evaluar promociones.'
    df.loc[(df['Segmento_ABC'] == 'A') & (df['Dias_Inventario'] < 30) & (df['Demanda_Diaria_Promedio'] > 0), 'Recomendacion'] += ' Producto "A" crítico, asegurar stock.'

    if 'PESO_ARTICULO' in df.columns:
        df['PESO_TOTAL'] = df['Unidades_Traslado_Sugeridas'] * df['PESO_ARTICULO']
    else:
        df['PESO_TOTAL'] = 0

    return df


# --- FUNCIÓN AUXILIAR PARA DESCARGA DE EXCEL ---
@st.cache_data
def convert_df_to_excel(_df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        _df.to_excel(writer, index=False, sheet_name='Análisis Inventario')
    processed_data = output.getvalue()
    return processed_data


# --- 4. CONSTRUCCIÓN DE LA INTERFAZ DE USUARIO DE STREAMLIT ---

st.title("📦 Tablero de Control y Optimización de Inventario")
st.markdown("Análisis automatizado a partir de los datos más recientes en Dropbox.")

# Cargar los datos crudos
df_crudo = cargar_datos_desde_dropbox()

# --- ESTRUCTURA PRINCIPAL DE LA APLICACIÓN ---
if df_crudo is not None and not df_crudo.empty:

    # --- BARRA LATERAL CON FILTROS Y OPCIONES ---
    st.sidebar.header("⚙️ Opciones de Análisis y Filtrado")
    
    almacen_principal_input = st.sidebar.text_input(
        "Código del Almacén Principal/Bodega:",
        value='155',
        help="Este almacén se considera como la fuente principal en las sugerencias de reparto."
    )

    # Ejecutar el análisis completo con el DataFrame cargado
    df_analisis = analizar_inventario_completo(df_crudo, almacen_principal_input)

    # --- Continuar solo si el análisis fue exitoso ---
    if not df_analisis.empty:
        # Filtros basados en el DataFrame analizado
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filtros del Tablero")

        opciones_almacen = sorted(df_analisis['Almacen'].unique())
        opciones_departamento = sorted(df_analisis['Departamento'].unique())
        opciones_estado = sorted(df_analisis['Estado_Inventario_Local'].unique())

        selected_almacenes = st.sidebar.multiselect("Almacén(es):", opciones_almacen, default=opciones_almacen)
        selected_departamentos = st.sidebar.multiselect("Departamento(s):", opciones_departamento)
        search_sku = st.sidebar.text_input("Buscar por SKU (Referencia):")
        selected_estados = st.sidebar.multiselect("Estado de Inventario:", opciones_estado)

        # Aplicar filtros
        df_filtered = df_analisis.copy()
        if selected_almacenes:
            df_filtered = df_filtered[df_filtered['Almacen'].isin(selected_almacenes)]
        if selected_departamentos:
            df_filtered = df_filtered[df_filtered['Departamento'].isin(selected_departamentos)]
        if search_sku:
            df_filtered = df_filtered[df_filtered['SKU'].str.contains(search_sku, case=False, na=False)]
        if selected_estados:
            df_filtered = df_filtered[df_filtered['Estado_Inventario_Local'].isin(selected_estados)]

        # --- CUERPO PRINCIPAL DEL TABLERO ---
        if not df_filtered.empty:
            # KPIs
            st.header("📊 Métricas Clave (Inventario Filtrado)")
            costo_col = 'Costo_Promedio_UND' if 'Costo_Promedio_UND' in df_filtered.columns and df_filtered['Costo_Promedio_UND'].sum() > 0 else 'Precio_Promocion'
            total_inventario_valor = (df_filtered['Stock'] * df_filtered[costo_col]).sum()
            quiebre_count = df_filtered[df_filtered['Estado_Inventario_Local'] == 'Quiebre de Stock']['SKU'].nunique()
            unidades_excedente = df_filtered[df_filtered['Estado_Inventario_Local'].isin(['Excedente', 'Baja Rotación / Obsoleto'])]['Stock'].sum()
            unidades_sugeridas_traslado = df_filtered['Unidades_Traslado_Sugeridas'].sum()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Valor Total Inventario", f"${total_inventario_valor:,.2f}", help=f"Calculado con la columna '{costo_col}'")
            col2.metric("SKUs en Quiebre de Stock", f"{quiebre_count:,.0f}")
            col3.metric("Unidades en Excedente", f"{unidades_excedente:,.0f}")
            col4.metric("Unidades para Traslado", f"{unidades_sugeridas_traslado:,.0f}")
            st.markdown("---")

            # Gráficos
            st.header("📈 Visualización del Inventario")
            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                estado_counts = df_filtered['Estado_Inventario_Local'].value_counts()
                fig_estado = px.pie(estado_counts, values=estado_counts.values, names=estado_counts.index,
                                    title='Distribución de SKUs por Estado', hole=0.3)
                fig_estado.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='#FFFFFF', width=2)))
                st.plotly_chart(fig_estado, use_container_width=True)
            with col_graph2:
                df_rotacion_dept = df_filtered[df_filtered['Stock'] > 0].groupby('Departamento')['Rotacion_60_Dias'].mean().nlargest(15)
                fig_rotacion = px.bar(df_rotacion_dept, y=df_rotacion_dept.index, x='Rotacion_60_Dias',
                                      title='Top 15 Departamentos por Rotación Promedio',
                                      labels={'Rotacion_60_Dias': 'Rotación (Ventas/Stock)', 'index': 'Departamento'},
                                      orientation='h')
                st.plotly_chart(fig_rotacion, use_container_width=True)
            st.markdown("---")

            # Tablas de detalle
            st.header("📋 Tablas de Acción Prioritaria")
            col_table1, col_table2 = st.columns(2)
            with col_table1:
                st.subheader("🚨 Oportunidades de Reparto (Quiebre/Bajo Stock)")
                df_criticos = df_filtered[df_filtered['Unidades_Traslado_Sugeridas'] > 0].sort_values(by='Dias_Inventario')
                if not df_criticos.empty:
                    st.dataframe(df_criticos[['SKU', 'Almacen', 'Stock', 'Estado_Inventario_Local', 'Unidades_Traslado_Sugeridas', 'Sugerencia_Traslado']].head(20),
                                   hide_index=True, use_container_width=True, height=300)
                else:
                    st.info("No se encontraron oportunidades de reparto con los filtros actuales.")
            with col_table2:
                st.subheader("🟢 Mayor Excedente / Baja Rotación")
                df_excedente = df_filtered[df_filtered['Estado_Inventario_Local'].isin(['Excedente', 'Baja Rotación / Obsoleto'])].sort_values(by='Dias_Inventario', ascending=False)
                if not df_excedente.empty:
                    st.dataframe(df_excedente[['SKU', 'Almacen', 'Stock', 'Dias_Inventario', 'Segmento_ABC', 'Recomendacion']].head(20),
                                   hide_index=True, use_container_width=True, height=300)
                else:
                    st.info("No hay SKUs en excedente o baja rotación con los filtros actuales.")
            st.markdown("---")

            # Tabla de datos completa y botón de descarga
            st.header("📦 Detalle Completo del Inventario (Filtrado)")
            columnas_mostrar = [
                'SKU', 'Descripcion', 'Almacen', 'Stock', 'Estado_Inventario_Local',
                'Unidades_Traslado_Sugeridas', 'Sugerencia_Traslado', 'Recomendacion',
                'Ventas_60_Dias', 'Dias_Inventario', 'Segmento_ABC', 'PESO_TOTAL'
            ]
            columnas_existentes = [col for col in columnas_mostrar if col in df_filtered.columns]
            st.dataframe(df_filtered[columnas_existentes], hide_index=True, use_container_width=True, height=500)

            excel_data = convert_df_to_excel(df_filtered[columnas_existentes])
            st.download_button(
                label="📥 Descargar Datos Filtrados a Excel",
                data=excel_data,
                file_name=f"analisis_inventario_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Descarga la tabla de datos actual con todos los filtros aplicados."
            )
        else:
            # Mensaje que se muestra si los filtros no arrojan resultados.
            st.warning("No se encontraron datos con los filtros seleccionados. Por favor, ajusta tus filtros en la barra lateral.")

else:
    # Mensaje final si la carga inicial de datos falla.
    st.warning("La carga de datos inicial ha fallado o el archivo está vacío. Por favor, revisa los mensajes de error de arriba.")
