import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time
import os

# --- CONFIGURATION ---
SHEET_NAME = "Smart_Infra_DB"
LOGO_FILE = "logodesign4.jpg"

# --- CACHED CONNECTION ---
@st.cache_resource
def get_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            st.error("⚠️ Secrets not found.")
            st.stop()
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

# --- DATA HELPERS ---
def clear_cache():
    st.cache_data.clear()

@st.cache_data(ttl=60)
def get_data(worksheet):
    client = get_connection()
    try:
        ws = client.open(SHEET_NAME).worksheet(worksheet)
        return pd.DataFrame(ws.get_all_records())
    except: return pd.DataFrame()

def save_batch_rows(worksheet, rows_list):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    ws.append_rows(rows_list)
    clear_cache()

def save_row(worksheet, row_dict):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    headers = ws.row_values(1)
    row_values = [row_dict.get(h, "") for h in headers]
    ws.append_row(row_values)
    clear_cache()

def bulk_delete_rows(worksheet, id_list):
    if not id_list: return
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell_list = []
        for rid in id_list:
            found = ws.findall(str(rid))
            cell_list.extend(found)
        rows_to_delete = sorted(list(set([c.row for c in cell_list])), reverse=True)
        for r in rows_to_delete:
            ws.delete_rows(r)
        clear_cache()
        return True
    except Exception as e:
        st.error(f"Delete Error: {e}")
        return False

def update_row_data(worksheet, row_id, updated_data):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        r = cell.row
        headers = ws.row_values(1)
        updates = []
        for col_name, value in updated_data.items():
            if col_name in headers:
                col_idx = headers.index(col_name) + 1
                updates.append({
                    'range': gspread.utils.rowcol_to_a1(r, col_idx),
                    'values': [[value]]
                })
        if updates:
            ws.batch_update(updates)
            clear_cache()
            return True
        return False
    except Exception as e:
        st.error(f"Update Error: {e}")
        return False

def update_worker_registry(edited_df):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet("Workers")
    headers = ws.row_values(1)
    if 'Synced' not in edited_df.columns:
        edited_df['Synced'] = "FALSE"
    ws.clear()
    ws.update([headers] + edited_df.values.tolist())
    clear_cache()

def get_settings_lists():
    df = get_data("Settings")
    if not df.empty:
        sites = df['Site_List'].dropna().unique().tolist()
        m_types = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        return [x for x in sites if x], [x for x in m_types if x], [x for x in materials if x]
    return ["Default Site"], ["1 Phase", "3 Phase", "DTR"], ["Cable", "Lugs"]

def get_worker_list():
    df = get_data("Workers")
    return df['Name'].tolist() if not df.empty else ["General"]

def calculate_stock():
    df_in = get_data("Inventory")
    df_out = get_data("WorkLogs")
    stock = {}
    if not df_in.empty:
        for _, row in df_in.iterrows():
            mat, qty = str(row['Material']).strip(), float(row['Qty'] or 0)
            stock[mat] = stock.get(mat, 0.0) + qty
    if not df_out.empty:
        for _, row in df_out.iterrows():
            mat, qty = str(row['Material']).strip(), float(row['Qty'] or 0)
            stock[mat] = stock.get(mat, 0.0) - qty
    return stock

# --- UI SETUP ---
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")

c_head1, c_head2 = st.columns([1, 4])
with c_head1:
    if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, width=70)
    else: st.write("🏢")
with c_head2:
    st.title("Site Supervisor")

tabs = st.tabs(["📝 Work Logs", "📦 Inventory", "👥 Workers", "📊 View & Manage"])

sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TAB 1: LOG WORK ---
with tabs[0]:
    st.markdown("##### 1. Asset Type")
    w_meter_type = st.selectbox("Select Installation Type:", meter_types_list)

    # Logic: Check if DTR is selected
    is_dtr = "DTR" in w_meter_type.upper()
    
    # Label changes dynamically for the User
    id_label = "DTR Code" if is_dtr else "Service Number"
    
    with st.form("work_log", clear_on_submit=True):
        st.markdown("##### 2. Installation Details")
        
        c1, c2, c3 = st.columns([1,1,1])
        w_date = c1.date_input("Date", datetime.today())
        w_site = c2.selectbox("Site", sites_list)
        w_worker = c3.selectbox("Worker", workers)
        
        c4, c5 = st.columns(2)
        # This input captures the Main ID (Service No OR DTR Code)
        w_main_id = c4.text_input(id_label) 
        
        # Optional Fields
        w_dtr_box = ""
        w_ss_no = ""
        w_capacity = ""
        
        if is_dtr:
            w_dtr_box = c5.text_input("DTR Box No")
            c6, c7 = st.columns(2)
            w_ss_no = c6.text_input("Transformer SS No")
            w_capacity = c7.text_input("Transformer Capacity (KVA)")
        else:
            c5.write("")
        
        st.markdown("##### 3. Materials")
        c_mat1, c_mat2 = st.columns(2)
        qty_cable = c_mat1.number_input("Cable (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs = c_mat2.number_input("Lugs (Qty)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("🚀 Submit Log", type="primary", use_container_width=True):
            batch_rows = []
            
            # --- ROW STRUCTURE UPDATE ---
            # Column 3 is now "SC No/ DTR Code"
            base_row = [
                str(w_date),
                w_main_id,    # Goes into "SC No/ DTR Code"
                w_dtr_box,
                w_ss_no,
                w_capacity,
                w_site,
                w_worker
            ]
            
            box_item_name = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + base_row + [box_item_name, 1, "FALSE"])
            
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Cable", qty_cable, "FALSE"])
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Lugs", qty_lugs, "FALSE"])
            
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.toast("✅ Log Saved!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Save Failed: {e}")

# --- TAB 2: INVENTORY ---
with tabs[1]:
    st.subheader("📊 Stock Overview")
    if current_stock:
        sorted_stock = sorted(current_stock.items(), key=lambda x: x[1])
        cols = st.columns(3)
        for i, (item, qty) in enumerate(sorted_stock):
            color = "normal" if qty >= 10 else "inverse"
            with cols[i % 3]:
                st.metric(label=item, value=f"{qty:,.0f}", delta="Low" if qty<10 else None, delta_color=color)
    else:
        st.info("No stock data.")

    st.markdown("---")
    with st.form("inv_form", clear_on_submit=True):
        st.caption("📥 Add New Stock")
        c1, c2, c3 = st.columns([1, 1, 1])
        i_date = c1.date_input("Date", datetime.today())
        i_mat = c2.selectbox("Material", materials_list)
        i_qty = c3.number_input("Qty", min_value=0.0, step=1.0)
        
        if st.form_submit_button("Add Stock", use_container_width=True):
            payload = {"ID": str(uuid.uuid4()), "Date": str(i_date), "Material": i_mat, "Qty": i_qty, "Type": "Inward", "Synced": "FALSE"}
            save_row("Inventory", payload)
            st.toast(f"✅ Added {i_qty} {i_mat}")
            time.sleep(1)
            st.rerun()

# --- TAB 3: WORKERS ---
with tabs[2]:
    st.subheader("👥 Workers")
    with st.expander("➕ Add Worker"):
        with st.form("add_worker"):
            new_w = st.text_input("Name")
            if st.form_submit_button("Add"):
                if new_w and new_w not in workers:
                    save_row("Workers", {"Name": new_w, "Synced": "FALSE"})
                    st.rerun()
    
    df_workers = get_data("Workers")
    if not df_workers.empty:
        edited = st.data_editor(df_workers, use_container_width=True, num_rows="dynamic", key="w_edit", column_config={"Synced": st.column_config.Column(disabled=True)})
        if st.button("💾 Save List"):
            update_worker_registry(edited)
            st.rerun()

# --- TAB 4: MANAGE ---
with tabs[3]:
    st.subheader("🗂️ Manage Data")
    view_mode = st.radio("Source", ["Work Logs", "Inventory"], horizontal=True, label_visibility="collapsed")
    
    if st.button("🔄 Refresh"): clear_cache(); st.rerun()

    target_sheet = "WorkLogs" if view_mode == "Work Logs" else "Inventory"
    df = get_data(target_sheet)

    if not df.empty:
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df = df.sort_values(by='Date', ascending=False)

        # Multi-Delete
        display_cols = [c for c in df.columns if c not in ["ID", "Synced"]]
        event = st.dataframe(df[display_cols], on_select="rerun", selection_mode="multi-row", use_container_width=True, height=300)
        
        if event.selection.rows:
            ids = df.iloc[event.selection.rows]['ID'].tolist()
            if st.button(f"🗑️ Delete {len(ids)} Items"):
                if bulk_delete_rows(target_sheet, ids): st.rerun()

        # Edit Record
        st.markdown("---")
        st.write("### ✏️ Edit Record")
        
        # Create Label
        if target_sheet == "WorkLogs":
            # --- UPDATED COLUMN NAME ---
            s_col = 'SC No/ DTR Code' if 'SC No/ DTR Code' in df.columns else df.columns[2]
            df['label'] = df['Date'] + " | " + df[s_col].astype(str) + " | " + df['Material']
        else:
            df['label'] = df['Date'] + " | " + df['Material'] + " (" + df['Qty'].astype(str) + ")"

        edit_sel = st.selectbox("Select Record", [""] + df['label'].tolist())
        
        if edit_sel:
            sel_row = df[df['label'] == edit_sel].iloc[0]
            with st.form("edit_form"):
                st.caption(f"ID: {sel_row['ID']}")
                n_date = st.text_input("Date", value=sel_row['Date'])
                
                if target_sheet == "WorkLogs":
                    n_site = st.selectbox("Site", sites_list, index=sites_list.index(sel_row['Site']) if sel_row['Site'] in sites_list else 0)
                    n_worker = st.selectbox("Worker", workers, index=workers.index(sel_row['Worker']) if sel_row['Worker'] in workers else 0)
                    
                    # --- UPDATED COLUMN NAME HERE ---
                    col_name = 'SC No/ DTR Code'
                    n_id = st.text_input("SC No / DTR Code", value=sel_row.get(col_name, ''))
                    
                    n_box = st.text_input("DTR Box No", value=sel_row.get('DTR_Box_No', '')) if 'DTR_Box_No' in df.columns else ""
                    n_ss = st.text_input("SS No", value=sel_row.get('Transformer_SS_No', '')) if 'Transformer_SS_No' in df.columns else ""
                    n_cap = st.text_input("Capacity", value=sel_row.get('Transformer_Capacity', '')) if 'Transformer_Capacity' in df.columns else ""

                n_mat = st.selectbox("Material", materials_list, index=materials_list.index(sel_row['Material']) if sel_row['Material'] in materials_list else 0)
                n_qty = st.number_input("Qty", value=float(sel_row['Qty']))
                
                if st.form_submit_button("💾 Save"):
                    u_data = {"Date": n_date, "Material": n_mat, "Qty": n_qty, "Synced": "FALSE"}
                    if target_sheet == "WorkLogs":
                        # --- UPDATED MAPPING ---
                        u_data.update({
                            "Site": n_site, 
                            "Worker": n_worker, 
                            "SC No/ DTR Code": n_id, 
                            "DTR_Box_No": n_box,
                            "Transformer_SS_No": n_ss,
                            "Transformer_Capacity": n_cap
                        })
                    
                    if update_row_data(target_sheet, sel_row['ID'], u_data):
                        st.success("Updated!"); time.sleep(1); st.rerun()
