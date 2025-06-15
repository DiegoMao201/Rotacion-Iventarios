import pandas as pd
import streamlit as st
import io
import numpy as np

# --- Configuración de Columnas (SIN CAMBIOS) ---
COL_CONFIG = {
    'ESTADO_DE_RESULTADOS': {
        'NIVEL_LINEA': 'Grupo', 'CUENTA': 'Cuenta', 'NOMBRE_CUENTA': 'Título',
        'CENTROS_COSTO_COLS': { 'Sin centro de coste': 'Sin centro de coste', 156: 'Armenia', 157: 'San antonio', 158: 'Opalo', 189: 'Olaya', 238: 'Laureles', 'Total': 'Total_Consolidado_ER' }
    },
    'BALANCE_GENERAL': {
        'NIVEL_LINEA': 'Grupo', 'CUENTA': 'Cuenta', 'NOMBRE_CUENTA': 'Título', 'SALDO_INICIAL': 'Saldo inicial', 'DEBE': 'Debe', 'HABER': 'Haber', 'SALDO_FINAL': 'Saldo Final'
    }
}

# --- Funciones de Utilidad (SIN CAMBIOS) ---
def clean_numeric_value(value):
    if pd.isna(value) or value == '': return 0.0
    s_value = str(value).strip().replace('.', '').replace(',', '.')
    try: return float(s_value)
    except ValueError: return 0.0

def classify_account(cuenta_str: str) -> str:
    if not isinstance(cuenta_str, str): cuenta_str = str(cuenta_str)
    cuenta_str = cuenta_str.strip()
    if not cuenta_str: return 'No Clasificado'
    if cuenta_str.startswith('1'): return 'Balance General - Activos'
    elif cuenta_str.startswith('2'): return 'Balance General - Pasivos'
    elif cuenta_str.startswith('3'): return 'Balance General - Patrimonio'
    elif cuenta_str.startswith('4'): return 'Estado de Resultados - Ingresos'
    elif cuenta_str.startswith('5'): return 'Estado de Resultados - Gastos' 
    elif cuenta_str.startswith('6'): return 'Estado de Resultados - Costos de Ventas'
    elif cuenta_str.startswith('7'): return 'Estado de Resultados - Costos de Produccion o de Operacion'
    else: return 'No Clasificado'

def get_principal_account_value(df: pd.DataFrame, principal_account_code: str, value_column: str, cuenta_column_name: str):
    if cuenta_column_name not in df.columns or value_column not in df.columns: return 0.0
    principal_row = df[df[cuenta_column_name].astype(str) == str(principal_account_code)] 
    if not principal_row.empty:
        raw_value = principal_row[value_column].iloc[0]
        numeric_value = pd.to_numeric(raw_value, errors='coerce')
        return 0.0 if pd.isna(numeric_value) else float(numeric_value)
    return 0.0

# --- generate_financial_statement y resto de funciones (SIN CAMBIOS) ---
# Todas las funciones de generación y formato se mantienen idénticas al original que me pasaste.
def get_top_level_accounts_for_display(df_raw: pd.DataFrame, value_col_name: str, statement_type: str) -> pd.DataFrame:
    # (Código de la función sin cambios)
    config_key = statement_type.replace(' ', '_').upper()
    if config_key not in COL_CONFIG: return pd.DataFrame()
    config_specific = COL_CONFIG[config_key]
    default_cols = {'CUENTA': 'Cuenta', 'NOMBRE_CUENTA': 'Título', 'NIVEL_LINEA': 'Grupo'} 
    
    cuenta_col = config_specific.get('CUENTA', default_cols['CUENTA'])
    nombre_cuenta_col = config_specific.get('NOMBRE_CUENTA', default_cols['NOMBRE_CUENTA'])
    nivel_linea_col = config_specific.get('NIVEL_LINEA', default_cols['NIVEL_LINEA'])

    if value_col_name not in df_raw.columns: df_raw[value_col_name] = 0.0
    required_cols = [cuenta_col, nombre_cuenta_col, nivel_linea_col, value_col_name]
    if not all(col in df_raw.columns for col in required_cols): return pd.DataFrame()

    df_processed = df_raw.copy()
    df_processed[cuenta_col] = df_processed[cuenta_col].astype(str).str.strip()
    df_processed['Cuenta_Str'] = df_processed[cuenta_col] 

    df_sorted = df_processed.sort_values(by='Cuenta_Str').reset_index(drop=True)
    df_sorted = df_sorted.dropna(subset=['Cuenta_Str', nombre_cuenta_col, value_col_name])
    df_sorted = df_sorted[df_sorted['Cuenta_Str'] != ''].reset_index(drop=True)
    df_sorted = df_sorted[df_sorted[nombre_cuenta_col].astype(str).str.strip() != ''].reset_index(drop=True)
    df_sorted[value_col_name] = pd.to_numeric(df_sorted[value_col_name], errors='coerce').fillna(0.0)
    
    df_significant_values = df_sorted[df_sorted[value_col_name].abs() > 0.001].copy()
    unique_values_for_filter = df_significant_values[value_col_name].unique() if not df_significant_values.empty else []
    selected_rows_list = [] 
    for val_filter in unique_values_for_filter:
        group = df_significant_values[df_significant_values[value_col_name] == val_filter]
        if not group.empty: 
            if 'Cuenta_Str' in group.columns:
                    selected_rows_list.append(group.loc[group['Cuenta_Str'].str.len().idxmin()])
            elif cuenta_col in group.columns: 
                    selected_rows_list.append(group.loc[group[cuenta_col].astype(str).str.len().idxmin()])

    df_result = pd.DataFrame(selected_rows_list).drop_duplicates(subset=['Cuenta_Str']).reset_index(drop=True) if selected_rows_list else pd.DataFrame(columns=df_sorted.columns)
    
    principal_levels_for_zero_values = [1] 
    df_sorted[nivel_linea_col] = pd.to_numeric(df_sorted[nivel_linea_col], errors='coerce')
    df_zero_sig = df_sorted[
        (df_sorted[value_col_name].abs() < 0.001) & 
        (df_sorted[nivel_linea_col].notna()) &
        (df_sorted[nivel_linea_col].isin(principal_levels_for_zero_values))
    ].copy()
    
    df_final = pd.concat([df_result, df_zero_sig]).drop_duplicates(subset=['Cuenta_Str']).reset_index(drop=True)
    if df_final.empty: return df_final
    df_final[nivel_linea_col] = pd.to_numeric(df_final[nivel_linea_col], errors='coerce').fillna(99)
    return df_final.sort_values(by=[nivel_linea_col, 'Cuenta_Str'])

def generate_financial_statement(df_full_data: pd.DataFrame, statement_type: str, selected_cc_filter: str = None, max_level: int = 999) -> pd.DataFrame:
    # (Código de la función sin cambios)
    config_key = statement_type.replace(' ', '_').upper()
    if config_key not in COL_CONFIG: return pd.DataFrame()
    config = COL_CONFIG[config_key]
    default_col_names = {'CUENTA': 'Cuenta', 'NOMBRE_CUENTA': 'Título', 'NIVEL_LINEA': 'Grupo'}
    cuenta_col = config.get('CUENTA', default_col_names['CUENTA'])
    nombre_col = config.get('NOMBRE_CUENTA', default_col_names['NOMBRE_CUENTA'])
    nivel_col = config.get('NIVEL_LINEA', default_col_names['NIVEL_LINEA'])

    final_cols = [cuenta_col, nombre_col, 'Valor']
    base_check = [cuenta_col, nombre_col, nivel_col, 'Tipo_Estado']
    if not all(col in df_full_data.columns for col in base_check):
        return pd.DataFrame(columns=final_cols)

    if statement_type == 'Estado de Resultados':
        df_statement_orig = df_full_data[df_full_data['Tipo_Estado'].str.contains('Estado de Resultados', na=False)].copy()
        if df_statement_orig.empty: return pd.DataFrame(columns=final_cols)
        
        value_col_to_use = ''
        if selected_cc_filter and selected_cc_filter != 'Todos':
            if selected_cc_filter in df_statement_orig.columns: value_col_to_use = selected_cc_filter
            else: df_statement_orig['Valor_Final_Temp_CC'] = 0.0; value_col_to_use = 'Valor_Final_Temp_CC'
        else: 
            total_er_cfg_col = config.get('CENTROS_COSTO_COLS',{}).get('Total') 
            if total_er_cfg_col and total_er_cfg_col in df_statement_orig.columns: value_col_to_use = total_er_cfg_col
            else: 
                cc_ind_cols_list = [ v for k, v in config.get('CENTROS_COSTO_COLS',{}).items() if str(k).lower() not in ['total', 'sin centro de coste'] and v in df_statement_orig.columns and v != total_er_cfg_col]
                if cc_ind_cols_list:
                    for c_col in cc_ind_cols_list: df_statement_orig[c_col] = pd.to_numeric(df_statement_orig[c_col], errors='coerce').fillna(0)
                    df_statement_orig['__temp_sum_for_gfs'] = df_statement_orig[cc_ind_cols_list].sum(axis=1)
                    value_col_to_use = '__temp_sum_for_gfs'
                else: 
                    scc_cfg_col = config.get('CENTROS_COSTO_COLS',{}).get('Sin centro de coste')
                    if scc_cfg_col and scc_cfg_col in df_statement_orig.columns: value_col_to_use = scc_cfg_col
                    else: df_statement_orig['Valor_Final_Temp_Total'] = 0.0; value_col_to_use = 'Valor_Final_Temp_Total'
        
        if value_col_to_use not in df_statement_orig.columns: df_statement_orig[value_col_to_use] = 0.0
        df_statement_orig['Valor_Final'] = pd.to_numeric(df_statement_orig[value_col_to_use], errors='coerce').fillna(0)

        df_display = get_top_level_accounts_for_display(df_statement_orig, 'Valor_Final', statement_type)
        if df_display.empty: return pd.DataFrame(columns=final_cols)
        
        if nivel_col not in df_display.columns: df_display[nivel_col] = 1
        df_display[nivel_col] = pd.to_numeric(df_display[nivel_col], errors='coerce').fillna(9999) 
        df_display = df_display[df_display[nivel_col] <= float(max_level)].copy()
        
        er_categories_ordered = ['Estado de Resultados - Ingresos', 'Estado de Resultados - Costos de Ventas', 'Estado de Resultados - Gastos', 'Estado de Resultados - Costos de Produccion o de Operacion']
        processed_final_df = pd.DataFrame(columns=final_cols)
        required_loop_cols = ['Tipo_Estado', cuenta_col, nombre_col, nivel_col, 'Valor_Final']
        if not all(col_loop in df_display.columns for col_loop in required_loop_cols): return processed_final_df 

        for tipo_estado_categoria in er_categories_ordered:
            group = df_display[df_display['Tipo_Estado'] == tipo_estado_categoria].copy()
            if not group.empty:
                group = group.sort_values(by=cuenta_col)
                group[nivel_col] = pd.to_numeric(group[nivel_col], errors='coerce').fillna(1).astype(int)
                group['Nombre_Cuenta_Display'] = group.apply(lambda r: f"{'  '*(r[nivel_col]-1)}{r[nombre_col]}", axis=1)
                processed_final_df = pd.concat([processed_final_df, group[[cuenta_col, 'Nombre_Cuenta_Display', 'Valor_Final']].rename(columns={'Nombre_Cuenta_Display': nombre_col, 'Valor_Final': 'Valor'})], ignore_index=True)
        
        df_statement_orig[cuenta_col] = df_statement_orig[cuenta_col].astype(str)

        _ing_calc_gfs = get_principal_account_value(df_statement_orig, '4', 'Valor_Final', cuenta_col)
        _cv_calc_gfs = get_principal_account_value(df_statement_orig, '6', 'Valor_Final', cuenta_col)
        _go_admin_calc_gfs = get_principal_account_value(df_statement_orig, '51', 'Valor_Final', cuenta_col)
        _go_ventas_calc_gfs = get_principal_account_value(df_statement_orig, '52', 'Valor_Final', cuenta_col)
        _cost_prod_op_calc_gfs = get_principal_account_value(df_statement_orig, '7', 'Valor_Final', cuenta_col)
        _go_total_calc_gfs = _go_admin_calc_gfs + _go_ventas_calc_gfs + _cost_prod_op_calc_gfs
        _gno_calc_gfs = get_principal_account_value(df_statement_orig, '53', 'Valor_Final', cuenta_col)
        _imp_calc_gfs = get_principal_account_value(df_statement_orig, '54', 'Valor_Final', cuenta_col)
        _uo_calc_tabla_gfs = _ing_calc_gfs + _cv_calc_gfs + _go_total_calc_gfs
        total_val_er_correct = _uo_calc_tabla_gfs + _gno_calc_gfs + _imp_calc_gfs
        
        total_row = pd.DataFrame([{cuenta_col: '', nombre_col: 'TOTAL ESTADO DE RESULTADOS', 'Valor': total_val_er_correct}])
        processed_final_df = pd.concat([processed_final_df, total_row], ignore_index=True)
        blank_row = pd.DataFrame([{cuenta_col: '', nombre_col: '', 'Valor': None}])
        processed_final_df = pd.concat([processed_final_df, blank_row], ignore_index=True)
        return processed_final_df

    elif statement_type == 'Balance General':
        df_statement_bg = df_full_data[df_full_data['Tipo_Estado'].str.contains('Balance General', na=False)].copy()
        if df_statement_bg.empty: return pd.DataFrame(columns=final_cols)
        saldo_col_bg = config.get('SALDO_FINAL', 'Saldo Final') 
        if saldo_col_bg and saldo_col_bg in df_statement_bg.columns: df_statement_bg['Valor_Final'] = pd.to_numeric(df_statement_bg[saldo_col_bg], errors='coerce').fillna(0)
        else: df_statement_bg['Valor_Final'] = 0.0
        df_statement_bg[cuenta_col] = df_statement_bg[cuenta_col].astype(str)
        t_act_bg = get_principal_account_value(df_statement_bg, '1', 'Valor_Final', cuenta_col)
        t_pas_bg = get_principal_account_value(df_statement_bg, '2', 'Valor_Final', cuenta_col)
        t_pat_bg = get_principal_account_value(df_statement_bg, '3', 'Valor_Final', cuenta_col)
        df_display_bg = get_top_level_accounts_for_display(df_statement_bg, 'Valor_Final', statement_type)
        if df_display_bg.empty:
            rows_bg_totals_only = [ {cuenta_col:'1', nombre_col:'TOTAL ACTIVOS', 'Valor':t_act_bg}, {cuenta_col:'2', nombre_col:'TOTAL PASIVOS', 'Valor':t_pas_bg}, {cuenta_col:'3', nombre_col:'TOTAL PATRIMONIO', 'Valor':t_pat_bg}, {cuenta_col:'', nombre_col:'', 'Valor':None}, {cuenta_col:'', nombre_col:'TOTAL PASIVO + PATRIMONIO', 'Valor':t_pas_bg + t_pat_bg}, {cuenta_col:'', nombre_col:'VERIFICACIÓN (A-(P+Pt))', 'Valor':t_act_bg - (t_pas_bg + t_pat_bg)} ]
            return pd.DataFrame(rows_bg_totals_only)
        if nivel_col not in df_display_bg.columns: df_display_bg[nivel_col] = 1 
        df_display_bg[nivel_col] = pd.to_numeric(df_display_bg[nivel_col], errors='coerce').fillna(9999)
        df_display_bg = df_display_bg[df_display_bg[nivel_col] <= float(max_level)].copy()
        order_categories_bg_list = ['Balance General - Activos', 'Balance General - Pasivos', 'Balance General - Patrimonio']
        final_df_bg_display = pd.DataFrame(columns=final_cols)
        required_loop_cols_bg_list = ['Tipo_Estado', cuenta_col, nombre_col, nivel_col, 'Valor_Final']
        if all(col_loop_bg_item in df_display_bg.columns for col_loop_bg_item in required_loop_cols_bg_list):
            for tipo_estado_cat_bg in order_categories_bg_list:
                group_bg_display = df_display_bg[df_display_bg['Tipo_Estado'] == tipo_estado_cat_bg].copy()
                if not group_bg_display.empty:
                    group_bg_display = group_bg_display.sort_values(by=cuenta_col)
                    group_bg_display[nivel_col] = pd.to_numeric(group_bg_display[nivel_col], errors='coerce').fillna(1).astype(int)
                    group_bg_display['Nombre_Cuenta_Display'] = group_bg_display.apply( lambda r: f"{'  '*(r[nivel_col]-1)}{r[nombre_col]}", axis=1 )
                    final_df_bg_display = pd.concat([final_df_bg_display, group_bg_display[[cuenta_col, 'Nombre_Cuenta_Display', 'Valor_Final']].rename( columns={'Nombre_Cuenta_Display': nombre_col, 'Valor_Final': 'Valor'} )], ignore_index=True)
        else:
            rows_bg_principales = [ {cuenta_col:'1', nombre_col:COL_CONFIG['BALANCE_GENERAL'].get('NOMBRE_CUENTA', 'ACTIVOS'), 'Valor':t_act_bg}, {cuenta_col:'2', nombre_col:COL_CONFIG['BALANCE_GENERAL'].get('NOMBRE_CUENTA', 'PASIVOS'), 'Valor':t_pas_bg}, {cuenta_col:'3', nombre_col:COL_CONFIG['BALANCE_GENERAL'].get('NOMBRE_CUENTA', 'PATRIMONIO'), 'Valor':t_pat_bg}, ]
            final_df_bg_display = pd.DataFrame(rows_bg_principales)
        rows_to_add_bg_final = [ {cuenta_col:'', nombre_col:'', 'Valor':None}, {cuenta_col:'', nombre_col:'TOTAL PASIVO + PATRIMONIO', 'Valor':t_pas_bg + t_pat_bg}, {cuenta_col:'', nombre_col:'VERIFICACIÓN (A-(P+Pt))', 'Valor':t_act_bg - (t_pas_bg + t_pat_bg)} ]
        final_df_bg_display = pd.concat([final_df_bg_display, pd.DataFrame(rows_to_add_bg_final)], ignore_index=True)
        return final_df_bg_display
    return pd.DataFrame(columns=final_cols)
# ... resto de funciones de formato y excel sin cambios

def to_excel_buffer(er_df: pd.DataFrame, bg_df: pd.DataFrame) -> io.BytesIO:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if er_df is not None and not er_df.empty: 
            df_er_export = er_df.copy()
            if 'Valor' in df_er_export.columns:
                df_er_export['Valor'] = df_er_export['Valor'].astype(str).str.replace(r'[$,]', '', regex=True)
                df_er_export['Valor'] = pd.to_numeric(df_er_export['Valor'], errors='coerce')
            df_er_export.to_excel(writer, sheet_name='Estado de Resultados', index=False)
        if bg_df is not None and not bg_df.empty: 
            df_bg_export = bg_df.copy()
            if 'Valor' in df_bg_export.columns:
                df_bg_export['Valor'] = df_bg_export['Valor'].astype(str).str.replace(r'[$,]', '', regex=True)
                df_bg_export['Valor'] = pd.to_numeric(df_bg_export['Valor'], errors='coerce')
            df_bg_export.to_excel(writer, sheet_name='Balance General', index=False)
    output.seek(0)
    return output

def generate_styled_vertical_analysis_er_table(input_df: pd.DataFrame, total_ingresos_for_cc: float, cuenta_col_original: str, nombre_col_display: str, valor_col_report: str):
    # (Código de la función sin cambios)
    va_df = pd.DataFrame()
    if not all(col in input_df.columns for col in [nombre_col_display, cuenta_col_original, valor_col_report]):
        return pd.DataFrame().style 

    va_df[nombre_col_display] = input_df[nombre_col_display]
    va_df['Cuenta_Interna_VA'] = input_df[cuenta_col_original].astype(str) 
    numeric_values = pd.to_numeric(input_df[valor_col_report], errors='coerce').fillna(0)

    if total_ingresos_for_cc != 0: 
        va_df['Valor %'] = (numeric_values / total_ingresos_for_cc)
    else:
        va_df['Valor %'] = np.nan 

    def style_row_va(row):
        cuenta_str = row['Cuenta_Interna_VA']
        percentage_val = row['Valor %'] 
        styles = ['color: black'] * len(row) 
        color = 'black' 
        if pd.isna(percentage_val): return styles
        
        if cuenta_str.startswith('4'): 
            if cuenta_str == '4' and abs(percentage_val - 1.0) < 0.005 : color = 'green'
            elif percentage_val > 0.005 : color = 'green' 
            elif percentage_val < -0.005 : color = 'red'
        elif cuenta_str.startswith('6'):
            abs_percentage = abs(percentage_val)
            if abs_percentage > 0.60: color = 'red'      
            elif abs_percentage > 0.40: color = 'orange' 
            else: color = 'green'                 
        elif cuenta_str.startswith('5') or cuenta_str.startswith('7'):
            abs_percentage = abs(percentage_val)
            if abs_percentage > 0.30: color = 'red'    
            elif abs_percentage > 0.15: color = 'orange'
            else: color = 'green'                 
        try:
            valor_pc_idx = row.index.get_loc('Valor %')
            styles[valor_pc_idx] = f'color: {color}'
        except KeyError: pass
        return styles
        
    styled_df_object = va_df.style.apply(style_row_va, axis=1).format({'Valor %': "{:.2%}"}) 
    try:
        styled_df_object = styled_df_object.hide(columns=['Cuenta_Interna_VA'])
    except (TypeError, AttributeError): 
        try:
            styled_df_object = styled_df_object.set_properties(subset=['Cuenta_Interna_VA'], **{'display': 'none', 'width': '0px'})
        except Exception: pass
    return styled_df_object

# --- Aplicación Streamlit ---
st.set_page_config(layout="wide", page_title="Análisis Financiero Avanzado")
st.title("💰 Análisis Financiero y Tablero Gerencial")

# --- CAMBIO #1: Inicialización de session_state para los dataframes MAESTROS ---
for key in ['df_er_master', 'df_bg_master', 'final_er_display', 'final_bg_display', 'uploaded_file_name', 'current_selected_cc']:
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame() if 'df' in key else None

uploaded_file = st.file_uploader("Sube tu archivo Excel (hojas 'EDO RESULTADO' y 'BALANCE')", type=["xlsx"])

if uploaded_file is not None:
    # --- CAMBIO #2: Cargar y procesar los datos en los dataframes MAESTROS ---
    if st.session_state.uploaded_file_name != uploaded_file.name or st.session_state.df_er_master.empty:
        st.session_state.uploaded_file_name = uploaded_file.name
        try:
            xls = pd.ExcelFile(uploaded_file)
            if 'EDO RESULTADO' not in xls.sheet_names or 'BALANCE' not in xls.sheet_names:
                st.error("Asegúrate que el archivo Excel contenga las hojas 'EDO RESULTADO' y 'BALANCE'."); st.stop()
            
            df_er_raw, df_bg_raw = pd.read_excel(xls, 'EDO RESULTADO'), pd.read_excel(xls, 'BALANCE')
            st.success("Archivo cargado y procesando...")
            
            # --- Procesamiento ER (Sin cambios, pero carga en df_er_master) ---
            er_conf = COL_CONFIG['ESTADO_DE_RESULTADOS']
            bg_conf = COL_CONFIG['BALANCE_GENERAL']
            cuenta_col_er_config = er_conf.get('CUENTA', 'Cuenta') 
            er_map_config_keys_as_str = {str(k): v for k, v in er_conf.get('CENTROS_COSTO_COLS', {}).items()}
            df_er_raw.columns = [str(col).strip() for col in df_er_raw.columns]
            er_rename_mapping = {excel_col: logic_name for excel_col, logic_name in er_map_config_keys_as_str.items() if excel_col in df_er_raw.columns}
            current_df_er = df_er_raw.rename(columns=er_rename_mapping).copy()
            for logical_cc_name in er_conf.get('CENTROS_COSTO_COLS', {}).values():
                if logical_cc_name in current_df_er.columns: current_df_er[logical_cc_name] = current_df_er[logical_cc_name].apply(clean_numeric_value)
            for col_key in ['CUENTA', 'NOMBRE_CUENTA', 'NIVEL_LINEA']:
                col_config_name = er_conf.get(col_key, col_key) 
                if col_config_name not in current_df_er.columns:
                    found_original = False
                    for excel_key_cfg, logic_val_cfg in er_conf.items():
                        if isinstance(logic_val_cfg, str) and logic_val_cfg == col_config_name and str(excel_key_cfg) in df_er_raw.columns:
                            current_df_er[col_config_name] = df_er_raw[str(excel_key_cfg)]; found_original = True; break
                    if not found_original and col_config_name in df_er_raw.columns: current_df_er[col_config_name] = df_er_raw[col_config_name]
                    elif not found_original and col_key not in er_conf.get('CENTROS_COSTO_COLS', {}):
                        st.error(f"Columna '{col_config_name}' para '{col_key}' (ER) no encontrada."); st.stop()
                if col_key == 'NIVEL_LINEA': current_df_er[col_config_name] = pd.to_numeric(current_df_er[col_config_name], errors='coerce').fillna(0).astype(int)
                else: current_df_er[col_config_name] = current_df_er[col_config_name].astype(str).str.strip()
            if cuenta_col_er_config not in current_df_er.columns: st.error(f"Col. cuenta '{cuenta_col_er_config}' (ER) no encontrada para clasificación."); st.stop()
            current_df_er[cuenta_col_er_config] = current_df_er[cuenta_col_er_config].astype(str) 
            current_df_er['Tipo_Estado'] = current_df_er[cuenta_col_er_config].apply(classify_account)
            for cc_log_name_sign in er_conf.get('CENTROS_COSTO_COLS', {}).values():
                if cc_log_name_sign in current_df_er.columns:
                    current_df_er[cc_log_name_sign] = pd.to_numeric(current_df_er[cc_log_name_sign], errors='coerce').fillna(0)
                    ingresos_m = current_df_er['Tipo_Estado'] == 'Estado de Resultados - Ingresos'
                    current_df_er.loc[ingresos_m, cc_log_name_sign] = current_df_er.loc[ingresos_m, cc_log_name_sign].abs()
                    egresos_m = current_df_er['Tipo_Estado'].str.contains('Estado de Resultados', na=False) & ~ingresos_m
                    current_df_er.loc[egresos_m, cc_log_name_sign] = current_df_er.loc[egresos_m, cc_log_name_sign].abs() * -1
            st.session_state.df_er_master = current_df_er # Guardado en el maestro

            # --- Procesamiento BG (Sin cambios, pero carga en df_bg_master) ---
            current_df_bg = df_bg_raw.copy()
            cuenta_col_bg_config = bg_conf.get('CUENTA', 'Cuenta')
            for col_key_bg_base in ['SALDO_INICIAL', 'DEBE', 'HABER', 'SALDO_FINAL', 'CUENTA', 'NOMBRE_CUENTA', 'NIVEL_LINEA']:
                col_cfg_name_bg = bg_conf.get(col_key_bg_base, col_key_bg_base)
                if col_cfg_name_bg not in current_df_bg.columns: st.error(f"Columna '{col_cfg_name_bg}' (BG) no encontrada."); st.stop()
                if col_key_bg_base not in ['CUENTA', 'NOMBRE_CUENTA', 'NIVEL_LINEA']: current_df_bg[col_cfg_name_bg] = current_df_bg[col_cfg_name_bg].apply(clean_numeric_value)
                elif col_key_bg_base == 'NIVEL_LINEA': current_df_bg[col_cfg_name_bg] = pd.to_numeric(current_df_bg[col_cfg_name_bg], errors='coerce').fillna(0).astype(int)
                else: current_df_bg[col_cfg_name_bg] = current_df_bg[col_cfg_name_bg].astype(str).str.strip()
            if cuenta_col_bg_config not in current_df_bg.columns: st.error(f"Col. cuenta '{cuenta_col_bg_config}' (BG) no encontrada."); st.stop()
            current_df_bg[cuenta_col_bg_config] = current_df_bg[cuenta_col_bg_config].astype(str) 
            current_df_bg['Tipo_Estado'] = current_df_bg[cuenta_col_bg_config].apply(classify_account)
            st.session_state.df_bg_master = current_df_bg # Guardado en el maestro
            st.rerun() # Forzar un rerun para que la UI se actualice con los datos ya cargados
        except Exception as e:
            st.error(f"Error al procesar archivo: {e}"); st.exception(e)
            st.session_state.df_er_master = pd.DataFrame(); st.session_state.df_bg_master = pd.DataFrame()

# --- Interfaz de Usuario y Lógica de Reportes ---
st.sidebar.header("Opciones de Reporte")
df_er_exists = not st.session_state.get('df_er_master', pd.DataFrame()).empty
df_bg_exists = not st.session_state.get('df_bg_master', pd.DataFrame()).empty
report_type_disabled = not (df_er_exists or df_bg_exists)
report_type = st.sidebar.radio("Selecciona el reporte:", ["Estado de Resultados", "Balance General"], key="report_type_selector", disabled=report_type_disabled)

# --- Filtro CC se construye desde el DataFrame maestro, asegurando que siempre esté disponible ---
_selected_cc_report_from_ui = "Todos"
if report_type == "Estado de Resultados" and df_er_exists:
    er_conf_sidebar = COL_CONFIG['ESTADO_DE_RESULTADOS']
    # Se usa df_er_master para poblar el filtro.
    cc_options_ui_list = [name for name in er_conf_sidebar.get('CENTROS_COSTO_COLS', {}).values() if name in st.session_state.df_er_master.columns and name not in [er_conf_sidebar.get('CENTROS_COSTO_COLS', {}).get('Total'), er_conf_sidebar.get('CENTROS_COSTO_COLS', {}).get('Sin centro de coste')]]
    cc_options_ui_list = sorted(list(set(cc_options_ui_list)))
    if cc_options_ui_list:
        idx_cc = 0
        if "cc_filter_er_sidebar_main" in st.session_state:
            try: idx_cc = (['Todos'] + cc_options_ui_list).index(st.session_state.cc_filter_er_sidebar_main)
            except ValueError: idx_cc = 0
        _selected_cc_report_from_ui = st.sidebar.selectbox("Filtrar por Centro de Costo (ER):", ['Todos'] + cc_options_ui_list, index=idx_cc, key="cc_filter_er_sidebar_main")

st.session_state.current_selected_cc = _selected_cc_report_from_ui
st.sidebar.header("Buscar Cuenta Específica")
search_account_input = st.sidebar.text_input("Número de Cuenta a detallar:", key="search_account_input_main")

if report_type == "Estado de Resultados" and df_er_exists:
    # --- CAMBIO #3: Usar la copia de trabajo para todas las operaciones de ER ---
    df_er_actual = st.session_state.df_er_master.copy()
    active_cc = st.session_state.current_selected_cc 
    st.header(f"📈 Estado de Resultados ({active_cc})")
    er_config = COL_CONFIG['ESTADO_DE_RESULTADOS']
    cuenta_col_name_er = er_config.get('CUENTA', 'Cuenta')
    val_col_kpi = ''
    if active_cc and active_cc != 'Todos':
        if active_cc in df_er_actual.columns: val_col_kpi = active_cc
    else:
        total_col_name = er_config.get('CENTROS_COSTO_COLS',{}).get('Total')
        if total_col_name and total_col_name in df_er_actual.columns: val_col_kpi = total_col_name
        else:
            ind_cc_cols = [v for k, v in er_config.get('CENTROS_COSTO_COLS',{}).items() if str(k).lower() not in ['total', 'sin centro de coste'] and v in df_er_actual.columns]
            if ind_cc_cols:
                for c_col_sum in ind_cc_cols: df_er_actual[c_col_sum] = pd.to_numeric(df_er_actual[c_col_sum], errors='coerce').fillna(0)
                df_er_actual['__temp_sum_kpi'] = df_er_actual[ind_cc_cols].sum(axis=1)
                val_col_kpi = '__temp_sum_kpi'
            else:
                scc_name = er_config.get('CENTROS_COSTO_COLS',{}).get('Sin centro de coste')
                if scc_name and scc_name in df_er_actual.columns: val_col_kpi = scc_name
    kpi_ing, kpi_cv, kpi_go, kpi_gno, kpi_imp, kpi_uo_calc, kpi_un_calc = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    if val_col_kpi and val_col_kpi in df_er_actual.columns:
        df_er_actual[val_col_kpi] = pd.to_numeric(df_er_actual[val_col_kpi], errors='coerce').fillna(0)
        kpi_ing = get_principal_account_value(df_er_actual, '4', val_col_kpi, cuenta_col_name_er)
        kpi_cv = get_principal_account_value(df_er_actual, '6', val_col_kpi, cuenta_col_name_er)
        go_51 = get_principal_account_value(df_er_actual, '51', val_col_kpi, cuenta_col_name_er)
        go_52 = get_principal_account_value(df_er_actual, '52', val_col_kpi, cuenta_col_name_er)
        cost_7 = get_principal_account_value(df_er_actual, '7', val_col_kpi, cuenta_col_name_er)
        kpi_go = go_51 + go_52 + cost_7
        kpi_gno = get_principal_account_value(df_er_actual, '53', val_col_kpi, cuenta_col_name_er)
        kpi_imp = get_principal_account_value(df_er_actual, '54', val_col_kpi, cuenta_col_name_er)
        kpi_uo_calc = kpi_ing + kpi_cv + kpi_go
        kpi_un_calc = kpi_uo_calc + kpi_gno + kpi_imp
    margen_op_calc = (kpi_uo_calc / kpi_ing) * 100 if kpi_ing != 0 else 0.0
    margen_neto_calc = (kpi_un_calc / kpi_ing) * 100 if kpi_ing != 0 else 0.0
    cols_kpi_er_disp = st.columns(2)
    cols_kpi_er_disp[0].metric("Utilidad Operativa", f"${kpi_uo_calc:,.0f}", f"{margen_op_calc:.1f}% Margen Op.")
    cols_kpi_er_disp[1].metric("Utilidad Neta", f"${kpi_un_calc:,.0f}", f"{margen_neto_calc:.1f}% Margen Neto")
    er_niv_col_slider_disp = er_config.get('NIVEL_LINEA', 'Grupo')
    if er_niv_col_slider_disp in df_er_actual.columns:
        niveles_er_s = df_er_actual[er_niv_col_slider_disp].dropna()
        num_levels_er_s = pd.to_numeric(niveles_er_s, errors='coerce')
        valid_levels_er_s = num_levels_er_s[~np.isnan(num_levels_er_s)]
        lvls_er_slider_list = sorted(np.unique(valid_levels_er_s.astype(int)).tolist()) if valid_levels_er_s.size > 0 else []
        max_lvl_er_val = 1
        if lvls_er_slider_list:
            min_l_er_val, max_l_er_val = (min(lvls_er_slider_list), max(lvls_er_slider_list))
            default_lvl_er_val = min_l_er_val
            slider_key_er_val_name = "slider_er_level_main_display_final"
            if slider_key_er_val_name in st.session_state:
                default_lvl_er_val = st.session_state[slider_key_er_val_name]
            if default_lvl_er_val < min_l_er_val or default_lvl_er_val > max_l_er_val:
                default_lvl_er_val = min_l_er_val
            max_lvl_er_val = st.sidebar.slider(
                "Nivel Detalle (ER):",
                min_l_er_val,
                max_l_er_val,
                default_lvl_er_val,
                key=slider_key_er_val_name,
                disabled=(min_l_er_val == max_l_er_val and len(lvls_er_slider_list) > 0) or not lvls_er_slider_list
            )
        st.session_state.final_er_display = generate_financial_statement(df_er_actual, 'Estado de Resultados', active_cc, max_lvl_er_val)
        # Mostrar tabla de Estado de Resultados
        if not st.session_state.final_er_display.empty:
            df_er_display_fmt = st.session_state.final_er_display.copy()
            if 'Valor' in df_er_display_fmt.columns:
                df_er_display_fmt['Valor'] = pd.to_numeric(df_er_display_fmt['Valor'], errors='coerce').apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "")
            st.dataframe(df_er_display_fmt, use_container_width=True, hide_index=True)
        else:
            st.info("No se generaron datos para ER con filtros actuales.")

    # --- Mostrar Balance General debajo del Estado de Resultados ---
    st.markdown("---")
    st.header("⚖️ Balance General (Vista Rápida)")
    df_bg_actual = st.session_state.df_bg_master.copy() if df_bg_exists else pd.DataFrame()
    bg_config = COL_CONFIG['BALANCE_GENERAL']
    saldo_final_col_bg = bg_config.get('SALDO_FINAL', 'Saldo Final')
    cuenta_col_bg = bg_config.get('CUENTA', 'Cuenta')
    max_lvl_bg_val = 999
    bg_niv_col_slider_disp = bg_config.get('NIVEL_LINEA', 'Grupo')
    if not df_bg_actual.empty and bg_niv_col_slider_disp in df_bg_actual.columns:
        min_level_bg = int(df_bg_actual[bg_niv_col_slider_disp].min()) if not df_bg_actual[bg_niv_col_slider_disp].empty else 1
        max_level_bg_data = int(df_bg_actual[bg_niv_col_slider_disp].max()) if not df_bg_actual[bg_niv_col_slider_disp].empty else 5
        max_lvl_bg_val = st.sidebar.slider(
            f"Profundidad Máxima de Cuentas (BG - {bg_niv_col_slider_disp}):",
            min_value=min_level_bg,
            max_value=max_level_bg_data,
            value=min(max_level_bg_data, 5),
            key="max_level_slider_bg"
        )
        # --- KPIs del Balance General y Financieros con mejor visual ---
        t_act_bg = get_principal_account_value(df_bg_actual, '1', saldo_final_col_bg, cuenta_col_bg)
        t_pas_bg = get_principal_account_value(df_bg_actual, '2', saldo_final_col_bg, cuenta_col_bg)
        t_pat_bg = get_principal_account_value(df_bg_actual, '3', saldo_final_col_bg, cuenta_col_bg)
        act_corr = get_principal_account_value(df_bg_actual, '11', saldo_final_col_bg, cuenta_col_bg) + \
                   get_principal_account_value(df_bg_actual, '12', saldo_final_col_bg, cuenta_col_bg) + \
                   get_principal_account_value(df_bg_actual, '13', saldo_final_col_bg, cuenta_col_bg)
        pas_corr = get_principal_account_value(df_bg_actual, '21', saldo_final_col_bg, cuenta_col_bg) + \
                   get_principal_account_value(df_bg_actual, '22', saldo_final_col_bg, cuenta_col_bg)
        razon_corriente = act_corr / pas_corr if pas_corr != 0 else 0.0
        indicador_liquidez = razon_corriente
        cuentas_por_cobrar = get_principal_account_value(df_bg_actual, '13', saldo_final_col_bg, cuenta_col_bg)
        indicador_cartera = cuentas_por_cobrar / act_corr if act_corr != 0 else 0.0

        # --- Visualización compacta y colorida de KPIs ---
        kpi_data = [
            {"label": "Activos", "value": f"${t_act_bg:,.0f}", "color": "#4CAF50"},
            {"label": "Pasivos", "value": f"${t_pas_bg:,.0f}", "color": "#F44336"},
            {"label": "Patrimonio", "value": f"${t_pat_bg:,.0f}", "color": "#2196F3"},
            {"label": "Pasivo + Patrimonio", "value": f"${(t_pas_bg + t_pat_bg):,.0f}", "color": "#FF9800"},
            {"label": "Verificación (A+(P+Pt))", "value": f"${(t_act_bg + t_pas_bg + t_pat_bg):,.0f}", "color": "#9C27B0"},
            {"label": "Razón Corriente", "value": f"{razon_corriente:.2f}", "color": "#00BCD4"},
            {"label": "Liquidez", "value": f"{indicador_liquidez:.2f}", "color": "#009688"},
            {"label": "Cartera / Activo Corriente", "value": f"{indicador_cartera:.2%}", "color": "#FFC107"},
        ]
        kpi_html = '<div style="display: flex; flex-wrap: wrap; gap: 16px 10px; justify-content: flex-start; align-items: flex-start; margin-bottom: 0;">'
        for kpi in kpi_data:
            kpi_html += (
                f"<div style='background: {kpi['color']}; color: white; border-radius: 10px; padding: 7px 10px; min-width: 90px; margin-bottom: 0; text-align: center; font-size: 0.85em; box-shadow: 1px 2px 8px #0001;'>"
                f"<div style='font-weight: bold; font-size: 1em;'>{kpi['value']}</div>"
                f"<div style='font-size: 0.78em; opacity: 0.85;'>{kpi['label']}</div>"
                "</div>"
            )
        kpi_html += "</div>"
        st.markdown(kpi_html, unsafe_allow_html=True)

        # --- Tabla Balance General con estilo visual ---
        st.session_state.final_bg_display = generate_financial_statement(df_bg_actual, 'Balance General', max_level=max_lvl_bg_val)
        if not st.session_state.final_bg_display.empty:
            def highlight_rows(row):
                if isinstance(row['Valor'], (int, float)) and abs(row['Valor']) < 1e-2:
                    return ['background-color: #f5f5f5']*len(row)
                if 'TOTAL' in str(row.get('Título', '')).upper():
                    return ['background-color: #e3f2fd; font-weight: bold']*len(row)
                return ['']*len(row)
            st.dataframe(
                st.session_state.final_bg_display.style.format({'Valor': "${:,.0f}"}).apply(highlight_rows, axis=1),
                use_container_width=True,
                height=(len(st.session_state.final_bg_display) + 1) * 35 + 3
            )
        else:
            st.info("No hay datos para mostrar en el Balance General con los filtros actuales.")

# --- Detalle de Cuenta Buscada ---
if search_account_input:
    with st.expander(f"Detalle y Subcuentas para la Cuenta '{search_account_input}'", expanded=True):
        for report_label, active_df_key_search, active_config_key_search in [
            ("Estado de Resultados", 'df_er_master', 'ESTADO_DE_RESULTADOS'),
            ("Balance General", 'df_bg_master', 'BALANCE_GENERAL')
        ]:
            if not st.session_state.get(active_df_key_search, pd.DataFrame()).empty:
                df_search = st.session_state[active_df_key_search].copy()
                config_search = COL_CONFIG[active_config_key_search]
                cuenta_col_search = config_search.get('CUENTA', 'Cuenta')
                nombre_col_search = config_search.get('NOMBRE_CUENTA', 'Título')
                if cuenta_col_search in df_search.columns:
                    df_search[cuenta_col_search] = df_search[cuenta_col_search].astype(str)
                    sub_accounts_df_search = df_search[df_search[cuenta_col_search].str.startswith(search_account_input)].copy()
                else:
                    sub_accounts_df_search = pd.DataFrame()
                if not sub_accounts_df_search.empty:
                    display_cols_search = []
                    if report_label == "Estado de Resultados":
                        cc_cols_cfg_search = config_search.get('CENTROS_COSTO_COLS', {})
                        cc_cols_to_show_search = [val for val in cc_cols_cfg_search.values() if val in sub_accounts_df_search.columns]
                        base_cols_er_search = [col for col in [cuenta_col_search, nombre_col_search] if col in sub_accounts_df_search.columns]
                        display_cols_search = base_cols_er_search + cc_cols_to_show_search
                    else:
                        base_cols_bg_search = [col for col in [cuenta_col_search, nombre_col_search] if col in sub_accounts_df_search.columns]
                        data_cols_bg_search = [config_search.get('SALDO_INICIAL'), config_search.get('DEBE'), config_search.get('HABER'), config_search.get('SALDO_FINAL')]
                        data_cols_bg_existing_search = [col for col in data_cols_bg_search if col and col in sub_accounts_df_search.columns]
                        display_cols_search = base_cols_bg_search + data_cols_bg_existing_search
                    display_cols_search = sorted(list(set(display_cols_search)), key=lambda x: (x != cuenta_col_search, x != nombre_col_search, x))
                    df_display_detalle_search_fmt = sub_accounts_df_search[display_cols_search].copy()
                    for col_fmt_det_search in df_display_detalle_search_fmt.columns:
                        if col_fmt_det_search not in [cuenta_col_search, nombre_col_search]:
                            try:
                                df_display_detalle_search_fmt[col_fmt_det_search] = pd.to_numeric(df_display_detalle_search_fmt[col_fmt_det_search], errors='coerce').apply(lambda x: f"{x:,.0f}" if pd.notna(x) and isinstance(x, (int, float)) else ("" if pd.isna(x) else x))
                            except: pass
                    st.dataframe(df_display_detalle_search_fmt, use_container_width=True, hide_index=True)