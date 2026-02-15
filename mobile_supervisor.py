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
    """Establishes a cached connection to Google Sheets."""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        # Load from Streamlit Secrets
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            st.error("⚠️ Secrets not found. Please configure .streamlit/secrets.toml")
            st.stop()
            
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

# --- DATA HELPERS WITH CACHING ---
def clear_cache():
    """Clears data cache to force a reload."""
    st.cache_data.clear()

@st.cache_data(ttl=60)
def get_data(worksheet):
    client = get_connection()
    try:
        ws = client.open(SHEET_NAME).worksheet(worksheet)
        data = ws.get_all_records()
        return pd.DataFrame(data)
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
    """Deletes multiple rows by ID."""
    if not id_list: return
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    
    try:
        cell_list = []
        for rid in id_list:
            found = ws.findall(str(rid))
            cell_list.extend(found)
        
        # Sort rows descending to delete safely
        rows_to_delete = sorted(list(set([c.row for c in cell_list])), reverse=True)
        
        for r in rows_to_delete:
            ws.delete_rows(r)
        
        clear_cache()
        return True
    except Exception as e:
        st.error(f"Delete Error: {e}")
        return False

def update_row_data(worksheet, row_id, updated_data):
    """Finds a row by ID and updates specific columns."""
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        r = cell.row
        headers = ws.row_values(1)
        
        # Update cells based on header mapping
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
    """Updates workers from the data editor."""
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet("Workers")
    headers = ws.row_values(1)
    if 'Synced' not in edited_df.columns:
        edited_df['Synced'] = "FALSE"
    
    data_to_write = [headers] + edited_df.values.tolist()
    ws.clear()
    ws.update(data_to_write)
    clear_cache()

def get_settings_lists():
    df = get_data("Settings")
    if not df.empty:
        sites = df['Site_List'].dropna().unique().tolist()
        meter_types = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        return [x for x in sites if x], [x for x in meter_types if x], [x for x in materials if x]
    return ["Default Site"], ["1 Phase", "3 Phase"], ["Cable", "Lugs"]

def get_worker_list():
    df = get_data("Workers")
    if not df.empty:
        return df['Name'].tolist()
    return ["General"]

def calculate_stock():
    df_in = get_data("Inventory")
    df_out = get_data("WorkLogs")
    stock = {}
    
    # Sum Inwards
    if not df_in.empty:
        for _, row in df_in.iterrows():
            mat = str(row['Material']).strip()
            qty = float(row['Qty']) if row['Qty'] else 0.0
            stock[mat] = stock.get(mat, 0.0) + qty
            
    # Subtract Outwards
    if not df_out.empty:
        for _, row in df_out.iterrows():
            mat = str(row['Material']).strip()
            qty = float(row['Qty']) if row['Qty'] else 0.0
            stock[mat] = stock.get(mat, 0.0) - qty
    return stock

# --- UI SETUP ---
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")

# --- HEADER WITH LOGO ---
c_head1, c_head2 = st.columns([1, 4])
with c_head1:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=70)
    else:
        st.write("🏢")
with c_head2:
    st.title("Site Supervisor")

# --- TABS ---
tabs = st.tabs(["📝 Work Logs", "📦 Inventory", "👥 Workers", "📊 View & Manage"])

# Load Data
sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TAB 1: LOG WORK (UPDATED LAYOUT) ---
with tabs[0]:
    st.subheader("Daily Activity Log")
    
    with st.form("work_log", clear_on_submit=True):
        # Row 1: Date & Site
        c_top1, c_top2 = st.columns(2)
        w_date = c_top1.date_input("Date", datetime.today())
        w_site = c_top2.selectbox("Site Name", sites_list)
        
        # Row 2: Worker
        w_worker = st.selectbox("Installer / Worker", workers)
        
        # Row 3: Asset Details (MOVED UP)
        st.markdown("---")
        st.caption("📍 Installation Details")
        c_asset1, c_asset2 = st.columns(2)
        w_meter_type = c_asset1.selectbox("Meter/Box Type", meter_types_list)
        w_dtr = c_asset2.text_input("DTR Code / ID")
        
        # Row 4: Material Consumption (MOVED DOWN)
        st.markdown("---")
        st.caption("🛠️ Material Consumption")
        c_mat1, c_mat2 = st.columns(2)
        qty_cable = c_mat1.number_input("Cable Used (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs = c_mat2.number_input("Lugs Used (Qty)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("🚀 Submit Log", type="primary", use_container_width=True):
            batch_rows = []
            base_row = [str(w_date), w_dtr, w_site, w_worker]
            
            # Logic: Auto-Deduct Box
            box_name = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + base_row + [box_name, 1, "FALSE"])
            
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Cable", qty_cable, "FALSE"])
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Lugs", qty_lugs, "FALSE"])
            
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.toast("✅ Log Saved Successfully!")
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
            color = "normal"
            if qty < 10: color = "inverse"
            with cols[i % 3]:
                st.metric(label=item, value=f"{qty:,.0f}", delta="Low" if qty<10 else None, delta_color=color)
    else:
        st.info("No stock data available.")

    st.markdown("---")
    st.subheader("📥 Inward Entry")
    with st.form("inv_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        i_date = c1.date_input("Inward Date", datetime.today())
        i_mat = c2.selectbox("Material Type", materials_list)
        i_qty = st.number_input("Quantity Received", min_value=0.0, step=1.0)
        
        if st.form_submit_button("Add Stock", use_container_width=True):
            payload = {
                "ID": str(uuid.uuid4()),
                "Date": str(i_date),
                "Material": i_mat,
                "Qty": i_qty,
                "Type": "Inward",
                "Synced": "FALSE"
            }
            save_row("Inventory", payload)
            st.toast(f"✅ Added {i_qty} {i_mat}")
            time.sleep(1)
            st.rerun()

# --- TAB 3: WORKERS ---
with tabs[2]:
    st.subheader("👥 Worker Management")
    
    with st.expander("➕ Add New Worker"):
        with st.form("add_worker"):
            new_w = st.text_input("Worker Name")
            if st.form_submit_button("Add"):
                if new_w and new_w not in workers:
                    save_row("Workers", {"Name": new_w, "Synced": "FALSE"})
                    st.success(f"Added {new_w}")
                    time.sleep(1)
                    st.rerun()
                elif new_w in workers:
                    st.warning("Worker already exists")

    st.markdown("##### Existing Workers")
    df_workers = get_data("Workers")
    
    if not df_workers.empty:
        edited_workers = st.data_editor(
            df_workers,
            num_rows="dynamic",
            use_container_width=True,
            key="worker_editor",
            column_config={"Synced": st.column_config.Column(disabled=True)}
        )
        if st.button("💾 Save Worker Changes"):
            update_worker_registry(edited_workers)
            st.success("Worker list updated!")
            time.sleep(1)
            st.rerun()
    else:
        st.info("No workers found.")

# --- TAB 4: VIEW & MANAGE (EDIT & DELETE RESTORED) ---
with tabs[3]:
    st.subheader("🗂️ Data Management")
    view_mode = st.radio("Select Data Source", ["Work Logs", "Inventory Logs"], horizontal=True, label_visibility="collapsed")
    
    if st.button("🔄 Refresh Data"):
        clear_cache()
        st.rerun()

    target_sheet = "WorkLogs" if view_mode == "Work Logs" else "Inventory"
    df = get_data(target_sheet)

    if not df.empty:
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df = df.sort_values(by='Date', ascending=False)
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')

        # --- MULTI-SELECT DELETE SECTION ---
        st.markdown("### 🗑️ Delete Records")
        display_cols = [c for c in df.columns if c not in ["ID", "Synced"]]
        event = st.dataframe(
            df[display_cols],
            on_select="rerun",
            selection_mode="multi-row",
            use_container_width=True,
            height=300
        )
        
        if event.selection.rows:
            selected_indices = event.selection.rows
            selected_ids = df.iloc[selected_indices]['ID'].tolist()
            count = len(selected_ids)
            
            if st.button(f"🗑️ Delete {count} Selected Record(s)"):
                if bulk_delete_rows(target_sheet, selected_ids):
                    st.success("Deleted successfully!")
                    time.sleep(1)
                    st.rerun()

        # --- SINGLE RECORD EDIT SECTION ---
        st.markdown("---")
        st.markdown("### ✏️ Edit Record")
        
        # Create a dropdown for record selection (easier on mobile than table clicking)
        # Label format: Date | Site | Item (Qty)
        if target_sheet == "WorkLogs":
            df['label'] = df['Date'] + " | " + df['Site'] + " | " + df['Material'] + " (" + df['Qty'].astype(str) + ")"
        else:
            df['label'] = df['Date'] + " | " + df['Material'] + " (" + df['Qty'].astype(str) + ")"
            
        edit_option = st.selectbox("Select a record to edit:", [""] + df['label'].tolist(), key="edit_sel")
        
        if edit_option:
            sel_row = df[df['label'] == edit_option].iloc[0]
            sel_id = sel_row['ID']
            
            with st.form("edit_form"):
                st.caption(f"Editing ID: {sel_id}")
                
                # Edit Fields
                new_date = st.text_input("Date (YYYY-MM-DD)", value=sel_row['Date'])
                
                if target_sheet == "WorkLogs":
                    new_site = st.selectbox("Site", sites_list, index=sites_list.index(sel_row['Site']) if sel_row['Site'] in sites_list else 0)
                    new_worker = st.selectbox("Worker", workers, index=workers.index(sel_row['Worker']) if sel_row['Worker'] in workers else 0)
                    new_dtr = st.text_input("DTR Code", value=sel_row.get('DTR Code', ''))
                
                new_mat = st.selectbox("Material", materials_list, index=materials_list.index(sel_row['Material']) if sel_row['Material'] in materials_list else 0)
                new_qty = st.number_input("Qty", value=float(sel_row['Qty']))
                
                if st.form_submit_button("💾 Save Changes"):
                    update_data = {
                        "Date": new_date,
                        "Material": new_mat,
                        "Qty": new_qty,
                        "Synced": "FALSE"
                    }
                    if target_sheet == "WorkLogs":
                        update_data.update({
                            "Site": new_site,
                            "Worker": new_worker,
                            "DTR Code": new_dtr
                        })
                    
                    if update_row_data(target_sheet, sel_id, update_data):
                        st.success("Record Updated!")
                        time.sleep(1)
                        st.rerun()
    else:
        st.info(f"No records found in {view_mode}.")
