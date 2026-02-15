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

def delete_row(worksheet, row_id):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        ws.delete_rows(cell.row)
        return True
    except: return False

def get_settings_lists():
    """Fetches Sites, Meter Types, and Materials from Settings Tab"""
    df = get_data("Settings")
    if not df.empty:
        sites = df['Site_List'].dropna().unique().tolist()
        meter_types = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        # Clean out empty strings if any
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

tabs = st.tabs(["📝 Work Logs", "📦 Inventory", "👥 Workers", "📊 View Data"])

# Load Settings
sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TAB 1: WORK LOGS (UPDATED LOGIC) ---
with tabs[0]:
    st.subheader("Log Daily Work")
    
    # Live Stock Ticker
    st.info("📦 Current Stock Levels")
    sc1, sc2, sc3 = st.columns(3)
    # Display common items for quick ref
    sc1.metric("Cable", f"{current_stock.get('Cable', 0):,.0f}")
    sc2.metric("Lugs", f"{current_stock.get('Lugs', 0):,.0f}")
    # Display first meter box type found
    first_box = next((k for k in current_stock if 'Box' in k), 'Meter Box')
    sc3.metric(first_box, f"{current_stock.get(first_box, 0):,.0f}")

    with st.form("work_log"):
        # 1. Meter Type (Top) & Date
        c_top1, c_top2 = st.columns(2)
        w_meter_type = c_top1.selectbox("Meter Type", meter_types_list)
        w_date = c_top2.date_input("Date", datetime.today())
        
        # 2. Site (Dropdown) & DTR
        w_site = st.selectbox("Site Name", sites_list)
        w_dtr = st.text_input("DTR Code / ID")
        w_worker = st.selectbox("Worker", workers)
        
        st.divider()
        st.markdown(f"**Materials for {w_meter_type} Installation:**")
        
        # 3. Separate Inputs
        # Logic: Selecting Meter Type implies 1 Box
        st.caption(f"✅ {w_meter_type} Box (1 Qty) will be auto-deducted.")
        
        c1, c2 = st.columns(2)
        qty_cable = c1.number_input("Cable Used (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs = c2.number_input("Lugs Used (Qty)", min_value=0.0, step=1.0)
        
        if st.form_submit_button("🚀 Submit Log"):
            # Prepare Batch Data
            batch_rows = []
            base_row = [str(w_date), w_dtr, w_site, w_worker] # Common fields
            
            # A. Auto-Deduct Meter Box
            box_name = f"{w_meter_type} Box" # Convention: "1 Phase" -> "1 Phase Box"
            batch_rows.append([str(uuid.uuid4())] + base_row + [box_name, 1, "FALSE"])
            
            # B. Deduct Cable
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Cable", qty_cable, "FALSE"])
                
            # C. Deduct Lugs
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + base_row + ["Lugs", qty_lugs, "FALSE"])
            
            # Save to Sheet
            # Headers map: ID, Date, DTR Code, Site, Worker, Material, Qty, Synced
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.success(f"Saved! deducted: 1 {box_name}, {qty_cable}m Cable, {qty_lugs} Lugs.")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                st.error(f"Save Failed: {e}")

# --- TAB 2: INVENTORY ---
with tabs[1]:
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

# --- TAB 4: VIEW / EDIT / DELETE ---
with tabs[3]:
    st.subheader("Data Management")
    view_mode = st.radio("Select Data to View", ["Work Logs", "Inventory Logs"], horizontal=True)
    
    if st.button("🔄 Refresh Data"):
        st.rerun()

    if view_mode == "Work Logs":
        df = get_data("WorkLogs")
        if not df.empty:
            with st.expander("🔎 Filter Options"):
                f1, f2, f3, f4 = st.columns(4)
                f_w = f1.multiselect("Worker", df['Worker'].unique())
                f_m = f2.multiselect("Material", df['Material'].unique())
                f_s = f3.text_input("Search Site/DTR")
                f_site = f4.multiselect("Site", df['Site'].unique())
                
                if f_w: df = df[df['Worker'].isin(f_w)]
                if f_m: df = df[df['Material'].isin(f_m)]
                if f_site: df = df[df['Site'].isin(f_site)]
                if f_s: df = df[df['DTR Code'].astype(str).str.contains(f_s, case=False) | df['Site'].astype(str).str.contains(f_s, case=False)]
            
            st.dataframe(df)
            
            # Simple Delete Interface
            st.caption("To delete, enter ID below (Copy from table)")
            del_id = st.text_input("ID to Delete")
            if st.button("🗑️ Delete Log"):
                if delete_row("WorkLogs", del_id):
                    st.success("Deleted!")
                    time.sleep(1)
                    st.rerun()
        else:
            st.info("No work logs found.")

    elif view_mode == "Inventory Logs":
        df = get_data("Inventory")
        if not df.empty:
            st.dataframe(df)
            del_id_i = st.text_input("Inventory ID to Delete")
            if st.button("🗑️ Delete Inventory Log"):
                if delete_row("Inventory", del_id_i):
                    st.success("Deleted!")
                    time.sleep(1)
                    st.rerun()
        else:
            st.info("No inventory logs found.")