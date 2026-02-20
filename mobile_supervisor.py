import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time
import os
import urllib.parse  # Added for safe WhatsApp link encoding

# --- NEW IMPORTS ---
try:
    from streamlit_js_eval import get_geolocation
except ImportError:
    st.error("⚠️ Please run: pip install streamlit_js_eval")
    get_geolocation = None

try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Please run: pip install fpdf")
    FPDF = None

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

def generate_survey_pdf(df_export):
    """Generates PDF for Survey Logs export"""
    if FPDF is None: return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Survey Logs Export", ln=True, align='C')
    pdf.ln(5)
    
    for _, row in df_export.iterrows():
        dtr_name = str(row.get('DTR Name', 'N/A'))
        dtr_code = str(row.get('DTR Code', 'N/A'))
        lat = str(row.get('Latitude', ''))
        lon = str(row.get('Longitude', ''))
        date_val = str(row.get('Date', ''))
        loc_link = f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "No Location Provided"
        
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(200, 8, txt=f"DTR: {dtr_name} (Code: {dtr_code}) | Date: {date_val}", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(200, 8, txt=f"Location: {loc_link}", ln=True)
        pdf.ln(5)
        
    return pdf.output(dest='S').encode('latin-1')

# --- UI SETUP ---
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")

c_head1, c_head2 = st.columns([1, 4])
with c_head1:
    if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, width=70)
    else: st.write("🏢")
with c_head2:
    st.title("Site Supervisor")

# --- TAB NAVIGATION (Survey Tab Added) ---
tabs = st.tabs(["📋 Survey", "📝 Work Logs", "📊 View & Manage", "📦 Inventory", "👥 Workers"])

sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# Fetch Survey Data globally so it can be used for auto-filling Work Logs
survey_data = get_data("SurveyLogs")

# --- TAB 0: SURVEY ---
with tabs[0]:
    st.markdown("##### 📍 Site Survey Entry")
    auto_lat_surv, auto_long_surv = "", ""
    
    # GPS Auto-capture (Outside form)
    if get_geolocation:
        if st.checkbox("📍 Capture GPS Automatically", key="gps_survey_check", help="Check this to fetch current location"):
            geo_data = get_geolocation(component_key='gps_capture_survey')
            if geo_data:
                auto_lat_surv = str(geo_data['coords']['latitude'])
                auto_long_surv = str(geo_data['coords']['longitude'])
                st.success(f"Captured: {auto_lat_surv}, {auto_long_surv}")
                
    with st.form("survey_log", clear_on_submit=True):
        s_date = st.date_input("Date", datetime.today())
        c1, c2 = st.columns(2)
        s_name = c1.text_input("DTR Name", placeholder="e.g. Main Street Transformer")
        s_code = c2.text_input("DTR Code", placeholder="e.g. DTR-101")
        
        st.caption("Location Coordinates (Auto-filled if 'Capture GPS' is checked)")
        c_lat, c_long = st.columns(2)
        s_lat = c_lat.text_input("Latitude", value=auto_lat_surv)
        s_long = c_long.text_input("Longitude", value=auto_long_surv)
        
        if st.form_submit_button("🚀 Submit Survey", type="primary", use_container_width=True):
            if not s_name or not s_code:
                st.error("⚠️ DTR Name and DTR Code are required.")
            else:
                payload = {
                    "ID": str(uuid.uuid4()),
                    "Date": str(s_date),
                    "DTR Name": s_name,
                    "DTR Code": s_code,
                    "Latitude": s_lat,
                    "Longitude": s_long,
                    "Synced": "FALSE"
                }
                try:
                    save_row("SurveyLogs", payload)
                    st.toast("✅ Survey Log Saved!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save Failed: {e}")

# --- TAB 1: LOG WORK ---
with tabs[1]:
    st.markdown("##### 1. Asset Type")
    w_meter_type = st.selectbox("Select Installation Type:", meter_types_list)

    is_dtr = "DTR" in w_meter_type.upper()
    id_label = "DTR Code" if is_dtr else "Service Number"
    
    # --- GPS AUTO-CAPTURE (OUTSIDE FORM) ---
    st.markdown("##### 📍 Location")
    auto_lat, auto_long = "", ""
    
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
            
        # --- LOGIC: FETCH FROM SURVEY ---
        surv_lat, surv_lon = "", ""
        if w_main_id and not survey_data.empty and 'DTR Code' in survey_data.columns:
            # Case-insensitive match
            match = survey_data[survey_data['DTR Code'].astype(str).str.lower() == w_main_id.lower()]
            if not match.empty:
                surv_lat = str(match.iloc[0].get('Latitude', ''))
                surv_lon = str(match.iloc[0].get('Longitude', ''))
                if surv_lat and surv_lon:
                    st.success(f"✅ Found GPS in Survey for {w_main_id}")

        st.markdown("##### 3. Materials")
        c_mat1, c_mat2 = st.columns(2)
        qty_cable = c_mat1.number_input("Cable (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs = c_mat2.number_input("Lugs (Qty)", min_value=0.0, step=1.0)
        
        st.caption("Coordinates (Auto-filled by Checkbox or Survey Database)")
        c_lat, c_long = st.columns(2)
        
        # Priority: 1. Auto GPS 2. Survey DB 3. Empty
        final_lat_val = auto_lat if auto_lat else surv_lat
        final_lon_val = auto_long if auto_long else surv_lon
        
        w_lat = c_lat.text_input("Latitude", value=final_lat_val)
        w_long = c_long.text_input("Longitude", value=final_lon_val)

        if st.form_submit_button("🚀 Submit Log", type="primary", use_container_width=True):
            batch_rows = []
            meta_data = [
                str(w_date), w_main_id, w_dtr_box, w_ss_no, w_capacity, w_site, w_worker
            ]
            gps_data = [w_lat, w_long]
            
            box_item_name = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + meta_data + [box_item_name, 1] + gps_data + ["FALSE"])
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + meta_data + ["Cable", qty_cable] + gps_data + ["FALSE"])
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
with tabs[2]:
    st.subheader("🗂️ Data Management")
    
    # Sub-tabs for Data Views (Added Survey Logs)
    t_survey_view, t_view_logs, t_gps, t_inv_view = st.tabs(["📋 Survey Logs", "📋 Installation Logs", "📍 GPS Data", "📦 Inventory Logs"])
    
    # --- 1. SURVEY LOGS VIEW ---
    with t_survey_view:
        if st.button("🔄 Refresh Data", key="ref_surv"): clear_cache(); st.rerun()
        
        if not survey_data.empty:
            if 'Date' in survey_data.columns:
                survey_data['Date'] = pd.to_datetime(survey_data['Date'], errors='coerce')
            
            st.markdown("###### Filters")
            cf1, cf2 = st.columns(2)
            surv_search = cf1.text_input("Search DTR Code / Name")
            surv_date = cf2.date_input("Date Range", [])
            
            # Apply Filters
            filtered_surv = survey_data.copy()
            if surv_search:
                filtered_surv = filtered_surv[
                    filtered_surv['DTR Code'].astype(str).str.contains(surv_search, case=False, na=False) |
                    filtered_surv['DTR Name'].astype(str).str.contains(surv_search, case=False, na=False)
                ]
            if len(surv_date) == 2:
                mask = (filtered_surv['Date'].dt.date >= surv_date[0]) & (filtered_surv['Date'].dt.date <= surv_date[1])
                filtered_surv = filtered_surv[mask]
                
            if not filtered_surv.empty:
                filtered_surv['Date'] = filtered_surv['Date'].dt.strftime('%Y-%m-%d')
                display_cols = [c for c in filtered_surv.columns if c not in ["Synced"]]
                
                # Multi-Delete Selection
                evt_surv = st.dataframe(filtered_surv[display_cols], on_select="rerun", selection_mode="multi-row", use_container_width=True)
                
                if evt_surv.selection.rows:
                    sel_surv_ids = filtered_surv.iloc[evt_surv.selection.rows]['ID'].tolist()
                    if st.button(f"🗑️ Delete {len(sel_surv_ids)} Survey Logs", key="del_surv"):
                        if bulk_delete_rows("SurveyLogs", sel_surv_ids): st.rerun()
                        
                st.markdown("---")
                
                # Export & Edit Options
                ce1, ce2 = st.columns(2)
                with ce1:
                    st.write("### ✏️ Edit / Export Record")
                    filtered_surv['label'] = filtered_surv['Date'].astype(str) + " | " + filtered_surv['DTR Code'].astype(str) + " (" + filtered_surv['DTR Name'].astype(str) + ")"
                    edit_sel_surv = st.selectbox("Select Record", [""] + filtered_surv['label'].tolist(), key="edit_sel_surv")
                    
                    if edit_sel_surv:
                        sel_row = filtered_surv[filtered_surv['label'] == edit_sel_surv].iloc[0]
                        with st.form("edit_surv_form"):
                            st.caption(f"Editing ID: {sel_row['ID']}")
                            n_date = st.text_input("Date", value=sel_row['Date'])
                            n_name = st.text_input("DTR Name", value=sel_row['DTR Name'])
                            n_code = st.text_input("DTR Code", value=sel_row['DTR Code'])
                            n_lat = st.text_input("Latitude", value=sel_row.get('Latitude', ''))
                            n_lon = st.text_input("Longitude", value=sel_row.get('Longitude', ''))
                            
                            if st.form_submit_button("💾 Save Changes"):
                                u_data = {"Date": n_date, "DTR Name": n_name, "DTR Code": n_code, "Latitude": n_lat, "Longitude": n_lon, "Synced": "FALSE"}
                                if update_row_data("SurveyLogs", sel_row['ID'], u_data):
                                    st.success("Updated!"); time.sleep(1); st.rerun()
                                    
                with ce2:
                    st.write("### 📤 Export Selected")
                    if edit_sel_surv:
                        lat = sel_row.get('Latitude', '')
                        lon = sel_row.get('Longitude', '')
                        loc_link = f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "No GPS recorded."
                        
                        # UPDATED FORMAT & ENCODING
                        msg = f"*Survey Details*\n\nDTR Name: {sel_row['DTR Name']}\nDTR Code: {sel_row['DTR Code']}\nLocation: {loc_link}"
                        encoded_msg = urllib.parse.quote(msg)
                        
                        st.link_button("📱 Share via WhatsApp", f"https://wa.me/?text={encoded_msg}")
                        
                    # PDF Export for all filtered rows
                    st.write("### 📄 Export Full List")
                    if FPDF:
                        pdf_data = generate_survey_pdf(filtered_surv)
                        st.download_button("⬇️ Download as PDF", data=pdf_data, file_name="Survey_Logs.pdf", mime="application/pdf")
                    else:
                        st.warning("PDF generator not installed.")
            else:
                st.info("No logs match filters.")
        else:
            st.info("No Survey Logs available.")

    # --- 2. INSTALLATION LOGS VIEW ---
    with t_view_logs:
        df = get_data("WorkLogs")
        if not df.empty:
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            
            st.markdown("###### Filters")
            c_f1, c_f2, c_f3 = st.columns(3)
            avail_sites = ["All"] + sorted(df['Site'].dropna().unique().tolist())
            sel_site = c_f1.selectbox("Site", avail_sites, key="fil_site")
            avail_workers = ["All"] + sorted(df['Worker'].dropna().unique().tolist())
            sel_worker = c_f2.selectbox("Worker", avail_workers, key="fil_worker")
            sel_date = c_f3.date_input("Date", [])
            
            filtered_df = df.copy()
            if sel_site != "All": filtered_df = filtered_df[filtered_df['Site'] == sel_site]
            if sel_worker != "All": filtered_df = filtered_df[filtered_df['Worker'] == sel_worker]
            if len(sel_date) == 2:
                mask = (filtered_df['Date'].dt.date >= sel_date[0]) & (filtered_df['Date'].dt.date <= sel_date[1])
                filtered_df = filtered_df[mask]
                
            if not filtered_df.empty:
                filtered_df['DateStr'] = filtered_df['Date'].dt.strftime('%Y-%m-%d')
                id_col = 'SC No/ DTR Code' if 'SC No/ DTR Code' in filtered_df.columns else filtered_df.columns[2]
                filtered_df['ItemDesc'] = filtered_df['Material'] + " (" + filtered_df['Qty'].astype(str) + ")"
                
                grouped = filtered_df.groupby([id_col, 'DateStr', 'Site', 'Worker']).agg({
                    'ItemDesc': lambda x: ', '.join(x),
                    'ID': 'first' 
                }).reset_index()
                grouped.columns = ['ID / Code', 'Date', 'Site', 'Worker', 'Materials Consumed', 'Ref_ID']
                
                # Multi Delete (Uses grouped Dataframe visual but deletes by Ref_ID)
                evt = st.dataframe(grouped.drop(columns=['Ref_ID']), use_container_width=True, on_select="rerun", selection_mode="multi-row")
                
                if evt.selection.rows:
                    sel_group_ids = grouped.iloc[evt.selection.rows]['ID / Code'].tolist()
                    # Find all original rows tied to this ID to delete all materials associated
                    ids_to_delete = filtered_df[filtered_df[id_col].isin(sel_group_ids)]['ID'].tolist()
                    if st.button(f"🗑️ Delete {len(ids_to_delete)} linked materials"):
                        if bulk_delete_rows("WorkLogs", ids_to_delete): st.rerun()
            else:
                st.info("No logs found matching filters.")
        else:
            st.info("No work logs available.")

    # --- 3. GPS DATA LOG ---
    with t_gps:
        st.caption("View and export captured location data.")
        df_gps = get_data("WorkLogs")
        
        if not df_gps.empty and 'Latitude' in df_gps.columns:
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
                    maps_link = f"https://maps.google.com/?q={lat},{lon}"
                    
                    text = f"📍 Installation Location for {row[id_col]}: {maps_link}"
                    encoded_text = urllib.parse.quote(text)
                    st.link_button(f"📱 Share {row[id_col]} on WhatsApp", f"https://wa.me/?text={encoded_text}")
            else:
                st.info("No GPS data recorded yet.")
        else:
            st.warning("GPS columns not found in Sheet. Please update header row.")

    # --- 4. INVENTORY LOGS ---
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
with tabs[3]:
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
with tabs[4]:
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
