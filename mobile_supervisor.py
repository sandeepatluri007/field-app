import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time

# --- CONFIGURATION ---
SHEET_NAME = "Smart_Infra_DB"

# --- GOOGLE SHEETS CONNECTION ---
def get_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Secret Error: {e}")
        st.stop()

# --- DATA HELPERS ---
def get_data(worksheet):
    client = get_connection()
    try:
        ws = client.open(SHEET_NAME).worksheet(worksheet)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except: return pd.DataFrame()

def save_batch_rows(worksheet, rows_list):
    """Saves multiple rows at once"""
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    ws.append_rows(rows_list)

def save_row(worksheet, row_dict):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    headers = ws.row_values(1)
    row_values = [row_dict.get(h, "") for h in headers]
    ws.append_row(row_values)

def delete_row_by_id(worksheet, row_id):
    """Finds row by ID and deletes it"""
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        ws.delete_rows(cell.row)
        return True
    except: return False

def update_row_by_id(worksheet, row_id, updated_data_dict):
    """Finds row by ID and updates it (Delete + Re-insert method for safety or In-place update)"""
    # For stability with gspread, we will use Find -> Update Range
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        r = cell.row
        headers = ws.row_values(1)
        
        # Prepare the row to update
        # We need to preserve the original order of columns
        row_values = []
        for h in headers:
            if h in updated_data_dict:
                row_values.append(updated_data_dict[h])
            else:
                # Fetch existing value if not in update dict (Optional, but here we assume full row update usually)
                # For simplicity in this app, we will overwrite the specific cells
                pass
        
        # Updating cell by cell or range. Range is faster.
        # Construct range
        cell_list = ws.range(r, 1, r, len(headers))
        for i, cell in enumerate(cell_list):
            header_name = headers[i]
            if header_name in updated_data_dict:
                cell.value = updated_data_dict[header_name]
        ws.update_cells(cell_list)
        return True
    except Exception as e:
        st.error(f"Update Error: {e}")
        return False

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
    
    if not df_in.empty:
        for _, row in df_in.iterrows():
            mat = row['Material']
            qty = float(row['Qty']) if row['Qty'] else 0.0
            stock[mat] = stock.get(mat, 0.0) + qty
            
    if not df_out.empty:
        for _, row in df_out.iterrows():
            mat = row['Material']
            qty = float(row['Qty']) if row['Qty'] else 0.0
            stock[mat] = stock.get(mat, 0.0) - qty
    return stock

# --- UI SETUP ---
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")
st.title("👷 Site Supervisor App")

tabs = st.tabs(["📝 Work Logs", "📦 Inventory", "👥 Workers", "📊 View & Manage"])

sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TAB 1: WORK LOGS (CLEANED UP) ---
with tabs[0]:
    st.subheader("Log Daily Work")
    # Stock moved to Tab 2

    with st.form("work_log"):
        c_top1, c_top2 = st.columns(2)
        w_meter_type = c_top1.selectbox("Meter Type", meter_types_list)
        w_date = c_top2.date_input("Date", datetime.today())
        
        w_site = st.selectbox("Site Name", sites_list)
        w_dtr = st.text_input("DTR Code / ID")
        w_worker = st.selectbox("Worker", workers)
        
        st.divider()
        st.caption(f"✅ {w_meter_type} Box (1 Qty) will be auto-deducted.")
        
        c1, c2 = st.columns(2)
        qty_cable = c1.number_input("Cable Used (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs = c2.number_input("Lugs Used (Qty)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("🚀 Submit Log"):
            batch_rows = []
            base_row = [str(w_date), w_dtr, w_site, w_worker]
            
            # Auto-Deduct Meter Box
            box_name = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + base_row + [box_name, 1, "FALSE"])
            
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Cable", qty_cable, "FALSE"])
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Lugs", qty_lugs, "FALSE"])
            
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.success("Log Saved Successfully!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Save Failed: {e}")

# --- TAB 2: INVENTORY (STOCK MOVED HERE) ---
with tabs[1]:
    st.subheader("Current Stock Levels")
    
    # --- MOVED STOCK TICKER HERE ---
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Cable", f"{current_stock.get('Cable', 0):,.0f}")
    sc2.metric("Lugs", f"{current_stock.get('Lugs', 0):,.0f}")
    first_box = next((k for k in current_stock if 'Box' in k), 'Meter Box')
    sc3.metric(first_box, f"{current_stock.get(first_box, 0):,.0f}")
    st.divider()

    st.subheader("Inward Material")
    with st.form("inv_form"):
        i_date = st.date_input("Inward Date", datetime.today())
        i_mat = st.selectbox("Material Type", materials_list)
        i_qty = st.number_input("Quantity Received", min_value=0.0, step=1.0)
        
        if st.form_submit_button("📥 Add Stock"):
            payload = {
                "ID": str(uuid.uuid4()),
                "Date": str(i_date),
                "Material": i_mat,
                "Qty": i_qty,
                "Type": "Inward",
                "Synced": "FALSE"
            }
            save_row("Inventory", payload)
            st.success("Stock Added!")
            time.sleep(1)
            st.rerun()

# --- TAB 3: WORKERS ---
with tabs[2]:
    st.subheader("Manage Workers")
    new_w = st.text_input("New Worker Name")
    if st.button("Add Worker"):
        if new_w and new_w not in workers:
            save_row("Workers", {"Name": new_w, "Synced": "FALSE"})
            st.success(f"Added {new_w}")
            st.rerun()
        elif new_w in workers:
            st.warning("Worker already exists")

# --- TAB 4: VIEW / EDIT / DELETE (FIXED) ---
with tabs[3]:
    st.subheader("Data Management")
    view_mode = st.radio("Select Data Source", ["Work Logs", "Inventory Logs"], horizontal=True)
    
    if st.button("🔄 Refresh Table"):
        st.rerun()

    # --- WORK LOGS MANAGEMENT ---
    if view_mode == "Work Logs":
        df = get_data("WorkLogs")
        if not df.empty:
            # 1. DISPLAY TABLE (HIDE ID)
            # Create a view without ID for display
            display_cols = [c for c in df.columns if c != "ID"]
            st.dataframe(df[display_cols], use_container_width=True)
            
            st.divider()
            st.markdown("### 🛠️ Edit or Delete Record")
            
            # 2. SELECT RECORD TO MANAGE
            # Create a label for dropdown
            df['label'] = df['Date'] + " | " + df['Site'] + " | " + df['Material'] + " (" + df['Qty'].astype(str) + ")"
            
            # Dropdown to select record
            selected_label = st.selectbox("Select Record", options=df['label'].tolist()[::-1]) # Reverse to show newest first
            
            if selected_label:
                # Get the actual row data based on selection
                selected_row = df[df['label'] == selected_label].iloc[0]
                sel_id = selected_row['ID']
                
                c_edit, c_delete = st.columns(2)
                
                # DELETE ACTION
                if c_delete.button("🗑️ Delete Selected", type="primary"):
                    if delete_row_by_id("WorkLogs", sel_id):
                        st.success("Record Deleted!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Could not find record to delete.")

                # EDIT ACTION
                with st.expander("✏️ Edit Selected Record"):
                    with st.form(f"edit_{sel_id}"):
                        e_date = st.text_input("Date (YYYY-MM-DD)", value=selected_row['Date'])
                        e_site = st.selectbox("Site", sites_list, index=sites_list.index(selected_row['Site']) if selected_row['Site'] in sites_list else 0)
                        e_mat = st.selectbox("Material", materials_list, index=materials_list.index(selected_row['Material']) if selected_row['Material'] in materials_list else 0)
                        e_qty = st.number_input("Qty", value=float(selected_row['Qty']))
                        
                        if st.form_submit_button("💾 Save Changes"):
                            update_data = {
                                "Date": e_date,
                                "Site": e_site,
                                "Material": e_mat,
                                "Qty": e_qty,
                                "Synced": "FALSE" # Reset sync on edit
                            }
                            if update_row_by_id("WorkLogs", sel_id, update_data):
                                st.success("Updated Successfully!")
                                time.sleep(1)
                                st.rerun()
        else:
            st.info("No work logs found.")

    # --- INVENTORY MANAGEMENT ---
    elif view_mode == "Inventory Logs":
        df = get_data("Inventory")
        if not df.empty:
            # 1. DISPLAY TABLE (HIDE ID)
            display_cols = [c for c in df.columns if c != "ID"]
            st.dataframe(df[display_cols], use_container_width=True)
            
            st.divider()
            st.markdown("### 🛠️ Delete Inventory Record")
            
            # Label
            df['label'] = df['Date'] + " | " + df['Material'] + " | Qty: " + df['Qty'].astype(str)
            selected_label = st.selectbox("Select Record", options=df['label'].tolist()[::-1])
            
            if selected_label:
                selected_row = df[df['label'] == selected_label].iloc[0]
                sel_id = selected_row['ID']
                
                if st.button("🗑️ Delete Selected Inventory", type="primary"):
                    if delete_row_by_id("Inventory", sel_id):
                        st.success("Deleted!")
                        time.sleep(1)
                        st.rerun()
        else:
            st.info("No inventory logs found.")
