import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time
import os

# --- NEW IMPORT FOR GPS ---
try:
    from streamlit_js_eval import get_geolocation
except ImportError:
    st.error("⚠️ Please run: pip install streamlit_js_eval")
    get_geolocation = None

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
            st.error("⚠️ Secrets not found. Please configure .streamlit/secrets.toml")
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

# --- TAB NAVIGATION ---
tabs = st.tabs(["📝 Work Logs", "📊 View & Manage", "📦 Inventory", "👥 Workers"])

sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TAB 1: LOG WORK ---
with tabs[0]:
    st.markdown("##### 1. Asset Type")
    w_meter_type = st.selectbox("Select Installation Type:", meter_types_list)

    is_dtr = "DTR" in w_meter_type.upper()
    id_label = "DTR Code" if is_dtr else "Service Number"
    
    # --- GPS AUTO-CAPTURE (OUTSIDE FORM) ---
    st.markdown("##### 📍 Location")
    auto_lat, auto_long = "", ""
    
    # Use a checkbox to trigger GPS fetch (acts like a toggle button)
    if get_geolocation:
        if st.checkbox("📍 Capture GPS Automatically", help="Check this to fetch current location"):
            geo_data = get_geolocation(component_key='gps_capture')
            if geo_data:
                auto_lat = str(geo_data['coords']['latitude'])
                auto_long = str(geo_data['coords']['longitude'])
                st.success(f"Captured: {auto_lat}, {auto_long}")
    
    with st.form("work_log", clear_on_submit=True):
        st.markdown("##### 2. Installation Details")
        
        c1, c2, c3 = st.columns([1,1,1])
        w_date = c1.date_input("Date", datetime.today())
        w_site = c2.selectbox("Site", sites_list)
        w_worker = c3.selectbox("Worker", workers)
        
        c4, c5 = st.columns(2)
        w_main_id = c4.text_input(id_label) 
        
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
        
        # Hidden inputs to capture the auto-filled GPS (user can still edit if needed)
        # We use text_input so it can be submitted with the form
        st.caption("Coordinates (Auto-filled if 'Capture GPS' is checked)")
        c_lat, c_long = st.columns(2)
        w_lat = c_lat.text_input("Latitude", value=auto_lat)
        w_long = c_long.text_input("Longitude", value=auto_long)

        if st.form_submit_button("🚀 Submit Log", type="primary", use_container_width=True):
            batch_rows = []
            
            # --- ROW STRUCTURE (Matches Google Sheet) ---
            # Order: [Date, SC No/ DTR Code, DTR_Box_No, SS No, Capacity, Site, Worker, Material, Qty, Latitude, Longitude, Synced]
            
            meta_data = [
                str(w_date),
                w_main_id,    # SC No/ DTR Code
                w_dtr_box,
                w_ss_no,
                w_capacity,
                w_site,
                w_worker
            ]
            
            gps_data = [w_lat, w_long]
            
            # 1. Box Row
            box_item_name = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + meta_data + [box_item_name, 1] + gps_data + ["FALSE"])
            
            # 2. Cable Row
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + meta_data + ["Cable", qty_cable] + gps_data + ["FALSE"])
            
            # 3. Lugs Row
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + meta_data + ["Lugs", qty_lugs] + gps_data + ["FALSE"])
            
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.toast("✅ Log Saved!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Save Failed: {e}")

# --- TAB 2: VIEW & MANAGE ---
with tabs[1]:
    st.subheader("🗂️ Data Management")
    
    # Sub-tabs for Data Views
    t_view_logs, t_gps, t_inv_view = st.tabs(["📋 Installation Logs", "📍 GPS Data", "📦 Inventory Logs"])
    
    # --- 1. CONSOLIDATED LOGS VIEW (Single Entry Logic) ---
    with t_view_logs:
        if st.button("🔄 Refresh Data", key="ref_logs"): clear_cache(); st.rerun()
        
        df = get_data("WorkLogs")
        if not df.empty:
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            
            # --- FILTERS ---
            st.markdown("###### Filters")
            c_f1, c_f2, c_f3 = st.columns(3)
            
            # Site Filter
            avail_sites = ["All"] + sorted(df['Site'].dropna().unique().tolist())
            sel_site = c_f1.selectbox("Site", avail_sites, key="fil_site")
            
            # Worker Filter
            avail_workers = ["All"] + sorted(df['Worker'].dropna().unique().tolist())
            sel_worker = c_f2.selectbox("Worker", avail_workers, key="fil_worker")
            
            # Date Filter
            sel_date = c_f3.date_input("Date", [])
            
            # Apply Filters
            filtered_df = df.copy()
            if sel_site != "All":
                filtered_df = filtered_df[filtered_df['Site'] == sel_site]
            if sel_worker != "All":
                filtered_df = filtered_df[filtered_df['Worker'] == sel_worker]
            if len(sel_date) == 2:
                mask = (filtered_df['Date'].dt.date >= sel_date[0]) & (filtered_df['Date'].dt.date <= sel_date[1])
                filtered_df = filtered_df[mask]
                
            # --- CONSOLIDATION LOGIC ---
            if not filtered_df.empty:
                filtered_df['DateStr'] = filtered_df['Date'].dt.strftime('%Y-%m-%d')
                id_col = 'SC No/ DTR Code' if 'SC No/ DTR Code' in filtered_df.columns else filtered_df.columns[2]
                
                # Create a concise material string
                filtered_df['ItemDesc'] = filtered_df['Material'] + " (" + filtered_df['Qty'].astype(str) + ")"
                
                # Group items by ID to show as one entry
                grouped = filtered_df.groupby([id_col, 'DateStr', 'Site', 'Worker']).agg({
                    'ItemDesc': lambda x: ', '.join(x), # Merges "Box (1), Cable (10)"
                    'ID': 'first' 
                }).reset_index()
                
                grouped.columns = ['ID / Code', 'Date', 'Site', 'Worker', 'Materials Consumed', 'Ref_ID']
                
                st.dataframe(grouped.drop(columns=['Ref_ID']), use_container_width=True)
            else:
                st.info("No logs found matching filters.")
        else:
            st.info("No work logs available.")

    # --- 2. GPS DATA LOG ---
    with t_gps:
        st.caption("View and export captured location data.")
        df_gps = get_data("WorkLogs")
        
        if not df_gps.empty and 'Latitude' in df_gps.columns:
            # Filter rows with GPS data
            gps_valid = df_gps[df_gps['Latitude'].astype(str).str.strip() != ""].copy()
            
            if not gps_valid.empty:
                id_col = 'SC No/ DTR Code' if 'SC No/ DTR Code' in gps_valid.columns else gps_valid.columns[2]
                gps_unique = gps_valid.drop_duplicates(subset=[id_col])
                
                st.dataframe(gps_unique[[id_col, 'Site', 'Latitude', 'Longitude']], use_container_width=True)
                
                st.markdown("#### 📤 Export Location")
                gps_unique['label'] = gps_unique[id_col].astype(str) + " - " + gps_unique['Site']
                sel_loc = st.selectbox("Select Location to Share", gps_unique['label'].tolist())
                
                if sel_loc:
                    row = gps_unique[gps_unique['label'] == sel_loc].iloc[0]
                    lat = row['Latitude']
                    lon = row['Longitude']
                    
                    # WhatsApp Link
                    maps_link = f"http://maps.google.com/?q={lat},{lon}"
                    text = f"📍 Location for {row[id_col]}: {maps_link}"
                    
                    st.link_button(f"📱 Share {row[id_col]} on WhatsApp", f"https://wa.me/?text={text}")
            else:
                st.info("No GPS data recorded yet.")
        else:
            st.warning("GPS columns not found in Sheet. Please update header row.")

    # --- 3. INVENTORY LOGS ---
    with t_inv_view:
        df_inv = get_data("Inventory")
        if not df_inv.empty:
            st.dataframe(df_inv, use_container_width=True)
            
            st.markdown("---")
            st.write("### ✏️ Edit Inventory Record")
            df_inv['label'] = df_inv['Date'].astype(str) + " | " + df_inv['Material'] + " (" + df_inv['Qty'].astype(str) + ")"
            edit_sel = st.selectbox("Select Record", [""] + df_inv['label'].tolist())
            
            if edit_sel:
                sel_row = df_inv[df_inv['label'] == edit_sel].iloc[0]
                with st.form("edit_inv_form"):
                    n_date = st.text_input("Date", value=sel_row['Date'])
                    n_mat = st.selectbox("Material", materials_list, index=materials_list.index(sel_row['Material']) if sel_row['Material'] in materials_list else 0)
                    n_qty = st.number_input("Qty", value=float(sel_row['Qty']))
                    
                    if st.form_submit_button("💾 Save Changes"):
                        u_data = {"Date": n_date, "Material": n_mat, "Qty": n_qty, "Synced": "FALSE"}
                        if update_row_data("Inventory", sel_row['ID'], u_data):
                            st.success("Updated!"); time.sleep(1); st.rerun()

# --- TAB 3: INVENTORY (Add Stock) ---
with tabs[2]:
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
    with st.form("inv_form_add", clear_on_submit=True):
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

# --- TAB 4: WORKERS ---
with tabs[3]:
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
