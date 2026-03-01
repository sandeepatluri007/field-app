import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time
import os
import urllib.parse
import io

# --- IMPORTS ---
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
SHEET_NAME       = "Smart_Infra_DB"
LOGO_FILE        = "logodesign4.jpg"
DEFAULT_LUGS_QTY = 8   # auto-filled whenever cable is entered without lugs

# =============================================================================
# CONNECTION & DATA HELPERS (Optimized for Speed & Rate Limits)
# =============================================================================
@st.cache_resource(show_spinner=False)
def get_connection():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
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

@st.cache_resource(show_spinner=False, ttl=3600)
def get_spreadsheet():
    client = get_connection()
    return client.open(SHEET_NAME)

@st.cache_data(ttl=60, show_spinner=False)
def get_data(worksheet_name):
    try:
        ws = get_spreadsheet().worksheet(worksheet_name)
        return pd.DataFrame(ws.get_all_records())
    except Exception as e:
        time.sleep(1.5)
        try:
            ws = get_spreadsheet().worksheet(worksheet_name)
            return pd.DataFrame(ws.get_all_records())
        except Exception as ex:
            st.error(f"Failed to fetch {worksheet_name}. Please refresh.")
            return pd.DataFrame()

def save_batch_rows(worksheet_name, rows_list):
    ws = get_spreadsheet().worksheet(worksheet_name)
    ws.append_rows(rows_list)
    get_data.clear(worksheet_name)

def save_row(worksheet_name, row_dict):
    ws = get_spreadsheet().worksheet(worksheet_name)
    headers = ws.row_values(1)
    row_values = [row_dict.get(h, "") for h in headers]
    ws.append_row(row_values)
    get_data.clear(worksheet_name)

def bulk_delete_rows(worksheet_name, id_list):
    if not id_list:
        return False
    ws = get_spreadsheet().worksheet(worksheet_name)
    try:
        cell_list = []
        for rid in id_list:
            found = ws.findall(str(rid))
            cell_list.extend(found)
        rows_to_delete = sorted(list(set(c.row for c in cell_list)), reverse=True)
        for r in rows_to_delete:
            ws.delete_rows(r)
        get_data.clear(worksheet_name)
        return True
    except Exception as e:
        st.error(f"Delete Error: {e}")
        return False

def update_row_data(worksheet_name, row_id, updated_data):
    ws = get_spreadsheet().worksheet(worksheet_name)
    try:
        cell           = ws.find(str(row_id))
        r              = cell.row
        raw_headers    = ws.row_values(1)
        headers        = [h.strip() for h in raw_headers]
        updates        = []
        skipped        = []

        for col_name, value in updated_data.items():
            col_name_s = col_name.strip()
            if col_name_s in headers:
                col_idx = headers.index(col_name_s) + 1
                updates.append({
                    'range':  gspread.utils.rowcol_to_a1(r, col_idx),
                    'values': [[value]]
                })
            else:
                skipped.append(col_name_s)

        if updates:
            ws.batch_update(updates)
            get_data.clear(worksheet_name)
            return True

        st.error("Update failed: none of the target columns were found in the sheet.")
        return False

    except Exception as e:
        st.error(f"Update Error: {e}")
        return False

def update_worker_registry(edited_df):
    ws = get_spreadsheet().worksheet("Workers")
    headers = ws.row_values(1)
    if 'Synced' not in edited_df.columns:
        edited_df['Synced'] = "FALSE"
    ws.clear()
    ws.update([headers] + edited_df.values.tolist())
    get_data.clear("Workers")

@st.cache_data(ttl=60, show_spinner=False)
def get_settings_lists():
    df = get_data("Settings")
    if not df.empty:
        sites     = df['Site_List'].dropna().unique().tolist()
        m_types   = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        return (
            [x for x in sites     if x],
            [x for x in m_types   if x],
            [x for x in materials if x],
        )
    return ["Default Site"], ["1 Phase", "3 Phase", "DTR"], ["Cable", "Lugs"]

@st.cache_data(ttl=60, show_spinner=False)
def get_worker_list():
    df = get_data("Workers")
    return df['Name'].tolist() if not df.empty else ["General"]

def calculate_stock():
    df_in  = get_data("Inventory")
    df_out = get_data("WorkLogs")
    stock  = {}
    if not df_in.empty:
        for _, row in df_in.iterrows():
            mat = str(row['Material']).strip()
            qty = float(row['Qty'] or 0)
            stock[mat] = stock.get(mat, 0.0) + qty
    if not df_out.empty:
        for _, row in df_out.iterrows():
            mat = str(row['Material']).strip()
            qty = float(row['Qty'] or 0)
            stock[mat] = stock.get(mat, 0.0) - qty
    return stock

# --- EXPORT HELPERS ---
def clean_text(text):
    """Sanitizes text to prevent FPDF UnicodeEncodeError by safely removing non-Latin-1 characters (e.g., Emojis)."""
    if pd.isna(text) or text is None:
        return ""
    return str(text).encode('latin-1', 'ignore').decode('latin-1')

def convert_df_to_excel(df):
    output = io.BytesIO()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Exported Data')
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    except ImportError:
        # Fallback to CSV if xlsxwriter is missing
        return df.to_csv(index=False).encode('utf-8'), "text/csv", "csv"

def generate_survey_pdf(df_export):
    if FPDF is None: return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Survey Logs Export", ln=True, align='C')
    pdf.ln(5)
    for _, row in df_export.iterrows():
        dtr_name = row.get('DTR Name', 'N/A')
        dtr_code = row.get('DTR Code', 'N/A')
        lat      = row.get('Latitude',  '')
        lon      = row.get('Longitude', '')
        date_val = row.get('Date', '')
        lc_val   = row.get('LC/AB Switch', 'None')
        lm_val   = row.get('Lineman Name', 'N/A')
        loc_link = (f"https://maps.google.com/?q={lat},{lon}"
                    if lat and lon else "No Location Provided")
        
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(200, 8, txt=clean_text(f"DTR SS No: {dtr_name} (Code: {dtr_code}) | Date: {date_val}"), ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(200, 8, txt=clean_text(f"Switch: {lc_val} | Lineman: {lm_val}"), ln=True)
        pdf.cell(200, 8, txt=clean_text(f"Location: {loc_link}"), ln=True)
        pdf.ln(5)
    return pdf.output(dest='S').encode('latin-1')

def generate_worklog_pdf(df_export, id_col, ss_col, box_col):
    if FPDF is None: return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Installation Logs Export", ln=True, align='C')
    pdf.ln(5)
    for _, row in df_export.iterrows():
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(200, 8, txt=clean_text(f"Date: {row['Date']} | Worker: {row['Worker']}"), ln=True)
        pdf.set_font("Arial", '', 10)
        
        info_line = []
        if id_col and row.get(id_col): info_line.append(f"DTR Code: {row[id_col]}")
        if ss_col and row.get('DTR SS No'): info_line.append(f"SS No: {row['DTR SS No']}")
        if box_col and row.get(box_col): info_line.append(f"Box: {row[box_col]}")
        
        pdf.cell(200, 8, txt=clean_text(" | ".join(info_line)), ln=True)
        pdf.cell(200, 8, txt=clean_text(f"Materials: {row['Materials Consumed']}"), ln=True)
        pdf.ln(5)
    return pdf.output(dest='S').encode('latin-1')

def generate_inventory_pdf(df_export):
    if FPDF is None: return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Inventory Logs Export", ln=True, align='C')
    pdf.ln(5)
    for _, row in df_export.iterrows():
        pdf.set_font("Arial", 'B', 10)
        type_str = row.get('Type', 'Inward')
        pdf.cell(200, 8, txt=clean_text(f"Date: {row['Date']} | Type: {type_str}"), ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(200, 8, txt=clean_text(f"Material: {row['Material']} | Qty: {row['Qty']}"), ln=True)
        pdf.ln(3)
    return pdf.output(dest='S').encode('latin-1')

# --- Robust Column Matcher ---
def resolve_col(columns, candidates):
    columns_lower = {str(col).strip().lower(): col for col in columns}
    for cand in candidates:
        if cand.lower() in columns_lower:
            return columns_lower[cand.lower()]
    return None

# =============================================================================
# MATERIAL DISPLAY HELPERS
# =============================================================================
def _qty_str(qty, unit=""):
    try:
        q = float(qty)
        s = str(int(q)) if q == int(q) else str(round(q, 2))
    except:
        s = str(qty)
    return f"{s}{unit}"

def format_mat_line(mat_dict):
    parts   = []
    handled = set()
    for mat, qty in mat_dict.items():
        if 'box' in mat.lower():
            parts.append(f"📦 {mat}: {_qty_str(qty)}")
            handled.add(mat)
    for mat, qty in mat_dict.items():
        if mat.lower() == 'cable' and mat not in handled:
            parts.append(f"🔌 Cable: {_qty_str(qty, 'm')}")
            handled.add(mat)
    for mat, qty in mat_dict.items():
        if mat.lower() == 'lugs' and mat not in handled:
            parts.append(f"🔧 Lugs: {_qty_str(qty)}")
            handled.add(mat)
    for mat, qty in mat_dict.items():
        if mat not in handled:
            parts.append(f"• {mat}: {_qty_str(qty)}")

    return "  ·  ".join(parts) if parts else "—"

def tile_needs_lugs_fix(mat_dict):
    cable_qty = sum(v for k, v in mat_dict.items() if k.lower() == 'cable')
    lugs_qty  = sum(v for k, v in mat_dict.items() if k.lower() == 'lugs')
    return cable_qty > 0 and lugs_qty == 0

# =============================================================================
# UI SETUP
# =============================================================================
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")

c_head1, c_head2 = st.columns([1, 4])
with c_head1:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=70)
    else:
        st.write("🏢")
with c_head2:
    st.title("Site Supervisor")

tabs = st.tabs([
    "📋 Survey", "📝 Work Logs",
    "📊 View & Manage", "📦 Inventory", "👥 Workers"
])

sites_list, meter_types_list, materials_list = get_settings_lists()
workers       = get_worker_list()
current_stock = calculate_stock()
survey_data   = get_data("SurveyLogs")

# =============================================================================
# TAB 0 — SURVEY ENTRY
# =============================================================================
with tabs[0]:
    st.markdown("##### 📍 Site Survey Entry")
    auto_lat_surv, auto_long_surv = "", ""

    if get_geolocation:
        if st.checkbox("📍 Capture GPS Automatically", key="gps_survey_check",
                       help="Check this to fetch current location"):
            geo_data = get_geolocation(component_key='gps_capture_survey')
            if geo_data:
                auto_lat_surv  = str(geo_data['coords']['latitude'])
                auto_long_surv = str(geo_data['coords']['longitude'])
                st.success(f"Captured: {auto_lat_surv}, {auto_long_surv}")

    with st.form("survey_log", clear_on_submit=True):
        s_date = st.date_input("Date", datetime.today())
        c1, c2 = st.columns(2)
        s_name = c1.text_input("DTR SS No", placeholder="e.g. SS-101")
        s_code = c2.text_input("DTR Code",  placeholder="e.g. DTR-101")
        s_lineman = st.text_input("Lineman Name", placeholder="e.g. Ramesh")
        st.markdown("###### Switch Present")
        c3, c4 = st.columns(2)
        s_lc = c3.checkbox("LC")
        s_ab = c4.checkbox("AB Switch")
        st.caption("Location Coordinates (Auto-filled if 'Capture GPS' is checked)")
        c_lat, c_long = st.columns(2)
        s_lat  = c_lat.text_input("Latitude",  value=auto_lat_surv)
        s_long = c_long.text_input("Longitude", value=auto_long_surv)

        if st.form_submit_button("🚀 Submit Survey", type="primary",
                                 use_container_width=True):
            if s_lc and s_ab:
                st.error("⚠️ Please select either LC or AB Switch, not both.")
            elif not s_name or not s_code:
                st.error("⚠️ DTR SS No and DTR Code are required.")
            else:
                switch_val = "LC" if s_lc else "AB Switch" if s_ab else "None"
                payload = {
                    "ID": str(uuid.uuid4()), "Date": str(s_date),
                    "DTR Name": s_name, "DTR Code": s_code,
                    "Latitude": s_lat, "Longitude": s_long,
                    "LC/AB Switch": switch_val, "Lineman Name": s_lineman,
                    "Synced": "FALSE",
                }
                try:
                    save_row("SurveyLogs", payload)
                    st.toast("✅ Survey Log Saved!")
                    time.sleep(0.3)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save Failed: {e}")

# =============================================================================
# TAB 1 — LOG WORK (Rearranged Layout)
# =============================================================================
with tabs[1]:
    st.markdown("##### 1. Asset Type")
    w_meter_type = st.selectbox("Select Installation Type:", meter_types_list)
    is_dtr   = "DTR" in w_meter_type.upper()
    id_label = "DTR Code" if is_dtr else "Service Number"

    st.markdown("##### 📍 Location")
    auto_lat, auto_long = "", ""
    if get_geolocation:
        if st.checkbox("📍 Capture GPS Automatically",
                       help="Check this to fetch current location"):
            geo_data = get_geolocation(component_key='gps_capture')
            if geo_data:
                auto_lat  = str(geo_data['coords']['latitude'])
                auto_long = str(geo_data['coords']['longitude'])
                st.success(f"Captured: {auto_lat}, {auto_long}")

    with st.form("work_log", clear_on_submit=True):
        st.markdown("##### 2. Installation Details")
        
        # New Layout Order: Date, Site, Worker -> Box No, SS No -> DTR Code, Capacity
        c1, c2, c3 = st.columns([1, 1, 1])
        w_date   = c1.date_input("Date",   datetime.today())
        w_site   = c2.selectbox("Site",    sites_list)
        w_worker = c3.selectbox("Worker",  workers)

        w_dtr_box = w_ss_no = w_capacity = w_main_id = ""

        if is_dtr:
            c4, c5 = st.columns(2)
            w_dtr_box = c4.text_input("DTR Box No", help="Box serial / reference number")
            w_ss_no   = c5.text_input("DTR SS No", help="Sub-station number")

            c6, c7 = st.columns(2)
            w_main_id  = c6.text_input("DTR Code", help="DTR Code for this installation")
            w_capacity = c7.text_input("Transformer Capacity (KVA)")

            if not w_main_id.strip() and not w_ss_no.strip():
                st.caption("⚠️ Enter at least **DTR Code** or **DTR SS No** to submit this log.")
        else:
            w_main_id = st.text_input("Service Number", help="Service Number is required.")

        surv_lat = surv_lon = ""
        if w_main_id and not survey_data.empty and 'DTR Code' in survey_data.columns:
            match = survey_data[
                survey_data['DTR Code'].astype(str).str.lower() == w_main_id.lower()
            ]
            if not match.empty:
                surv_lat = str(match.iloc[0].get('Latitude',  ''))
                surv_lon = str(match.iloc[0].get('Longitude', ''))
                if surv_lat and surv_lon:
                    st.success(f"✅ Found GPS in Survey for {w_main_id}")

        st.markdown("##### 3. Materials")
        c_m1, c_m2 = st.columns(2)
        qty_cable = c_m1.number_input("Cable (Mtrs)", min_value=0.0, step=1.0)
        qty_lugs  = c_m2.number_input(
            f"Lugs (Qty)  —  leave 0 to auto-fill {DEFAULT_LUGS_QTY} when cable > 0",
            min_value=0.0, step=1.0,
            help=f"Default {DEFAULT_LUGS_QTY} Lugs are added automatically "
                 f"whenever cable is entered and this field is left at 0."
        )
        st.caption("Coordinates (Auto-filled by GPS checkbox or Survey Database)")
        c_lt, c_lg = st.columns(2)
        w_lat  = c_lt.text_input("Latitude",  value=(auto_lat  or surv_lat))
        w_long = c_lg.text_input("Longitude", value=(auto_long or surv_lon))

        submitted = st.form_submit_button(
            "🚀 Submit Log", type="primary", use_container_width=True
        )

    if submitted:
        validation_ok = True

        if is_dtr:
            if not w_main_id.strip() and not w_ss_no.strip():
                st.error("⚠️ **DTR installation requires at least one identifier.** \nPlease enter either **DTR Code** or **DTR SS No** (or both).")
                validation_ok = False
        else:
            if not w_main_id.strip():
                st.error("⚠️ **Service Number is required.**")
                validation_ok = False

        if validation_ok:
            effective_lugs = qty_lugs
            lugs_auto_added = False
            if qty_cable > 0 and qty_lugs == 0:
                effective_lugs  = float(DEFAULT_LUGS_QTY)
                lugs_auto_added = True

            batch_rows = []
            meta_data  = [
                str(w_date), w_main_id, w_dtr_box, w_ss_no,
                w_capacity, w_site, w_worker
            ]
            gps_data   = [w_lat, w_long]
            box_item   = f"{w_meter_type} Box"

            batch_rows.append(
                [str(uuid.uuid4())] + meta_data +
                [box_item, 1] + gps_data + ["FALSE"]
            )
            if qty_cable > 0:
                batch_rows.append(
                    [str(uuid.uuid4())] + meta_data +
                    ["Cable", qty_cable] + gps_data + ["FALSE"]
                )
            if effective_lugs > 0:
                batch_rows.append(
                    [str(uuid.uuid4())] + meta_data +
                    ["Lugs", effective_lugs] + gps_data + ["FALSE"]
                )

            try:
                save_batch_rows("WorkLogs", batch_rows)
                if lugs_auto_added:
                    st.toast(f"✅ Log Saved! Auto-added {DEFAULT_LUGS_QTY} Lugs.", icon="ℹ️")
                else:
                    st.toast("✅ Log Saved!")
                time.sleep(0.3)
                st.rerun()
            except Exception as e:
                st.error(f"Save Failed: {e}")

# =============================================================================
# TAB 2 — VIEW & MANAGE
# =============================================================================
with tabs[2]:
    st.subheader("🗂️ Data Management")

    t_survey_view, t_view_logs, t_gps, t_inv_view = st.tabs([
        "📋 Survey Logs", "📋 Installation Logs", "📍 GPS Data", "📦 Inventory Logs"
    ])

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE › SURVEY LOGS
    # ─────────────────────────────────────────────────────────────────────────
    with t_survey_view:
        if st.button("🔄 Refresh Data", key="ref_surv"):
            get_data.clear("SurveyLogs")
            st.rerun()

        if not survey_data.empty:
            if 'Date' in survey_data.columns:
                survey_data['Date'] = pd.to_datetime(survey_data['Date'], errors='coerce')
                survey_data['RowIndex'] = range(len(survey_data))
                survey_data = survey_data.sort_values(by=['Date', 'RowIndex'], ascending=[False, True])

            st.markdown("###### Filters")
            cf1, cf2, cf3 = st.columns(3)
            surv_search = cf1.text_input("Search DTR Code / DTR SS No")
            surv_switch = cf2.selectbox("Switch Type", ["All", "LC", "AB Switch", "None"])
            surv_date   = cf3.date_input("Date Range", [])

            fs = survey_data.copy()
            if surv_search:
                fs = fs[
                    fs['DTR Code'].astype(str).str.contains(surv_search, case=False, na=False) |
                    fs['DTR Name'].astype(str).str.contains(surv_search, case=False, na=False)
                ]
            if surv_switch != "All" and 'LC/AB Switch' in fs.columns:
                fs = fs[fs['LC/AB Switch'].astype(str).str.strip() == surv_switch]
            if len(surv_date) == 2:
                mask = (
                    (fs['Date'].dt.date >= surv_date[0]) &
                    (fs['Date'].dt.date <= surv_date[1])
                )
                fs = fs[mask]

            if not fs.empty:
                fs = fs.copy()
                fs['Date'] = fs['Date'].dt.strftime('%Y-%m-%d')
                
                # Excel & PDF Export (Survey Logs)
                st.write("### 📤 Export Filtered Logs")
                ce_s1, ce_s2 = st.columns(2)
                display_cols = [c for c in fs.columns if c not in ["Synced", "RowIndex", "ID"]]
                display_df = fs[display_cols].rename(columns={'DTR Name': 'DTR SS No'})
                
                with ce_s1:
                    if FPDF:
                        pdf_data = generate_survey_pdf(fs)
                        st.download_button("⬇️ Download PDF", data=pdf_data, file_name="Survey_Logs.pdf", mime="application/pdf")
                with ce_s2:
                    excel_data, mime_type, ext = convert_df_to_excel(display_df)
                    st.download_button(f"⬇️ Download Excel (.{ext})", data=excel_data, file_name=f"Survey_Logs.{ext}", mime=mime_type)

                st.markdown("---")
                st.markdown(f"**{len(fs)} record(s)**")
                surv_delete_map = {}

                for i, (_, row) in enumerate(fs.iterrows()):
                    dtr_code = str(row.get('DTR Code',     '')).strip()
                    dtr_ss   = str(row.get('DTR Name',     '')).strip()
                    date_val = str(row.get('Date',         '')).strip()
                    switch   = str(row.get('LC/AB Switch', 'None')).strip()
                    lineman  = str(row.get('Lineman Name', '')).strip()
                    lat      = str(row.get('Latitude',     '')).strip()
                    lon      = str(row.get('Longitude',    '')).strip()
                    synced   = str(row.get('Synced',       '')).strip().upper()
                    row_id   = str(row['ID'])

                    surv_delete_map[f"[{i+1}] {date_val}  ·  DTR: {dtr_code or '—'}  ·  SS: {dtr_ss or '—'}"] = row_id

                    with st.container(border=True):
                        col_c, col_btn = st.columns([7, 1])

                        with col_c:
                            st.markdown(f"**📅 {date_val}**")
                            st.markdown(f"🔌 DTR Code: **{dtr_code or '—'}** ·  📡 DTR SS No: **{dtr_ss or '—'}**")
                            meta = []
                            if switch and switch != "None": meta.append(f"🔘 {switch}")
                            if lineman: meta.append(f"👤 {lineman}")
                            if meta: st.caption("  ·  ".join(meta))
                            badge = []
                            if lat and lon: badge.append(f"📍 {lat[:9]}, {lon[:9]}")
                            badge.append("✅ Synced" if synced == "TRUE" else "🔄 Pending")
                            st.caption("  ·  ".join(badge))

                        with col_btn:
                            is_open = st.session_state.get(f'eo_surv_{i}', False)
                            if st.button("✖" if is_open else "✏️", key=f"eb_surv_{i}", help="Close" if is_open else "Edit"):
                                st.session_state[f'eo_surv_{i}'] = not is_open
                                st.rerun()

                        if st.session_state.get(f'eo_surv_{i}', False):
                            st.markdown("---")
                            with st.form(f"ef_surv_{i}"):
                                st.caption(f"Editing ID: {row_id}")
                                n_date    = st.text_input("Date",       value=date_val)
                                n_name    = st.text_input("DTR SS No",  value=dtr_ss)
                                n_code    = st.text_input("DTR Code",   value=dtr_code)
                                st.markdown("###### Switch Present")
                                ec1, ec2  = st.columns(2)
                                n_lc = ec1.checkbox("LC",        value=(switch == 'LC'))
                                n_ab = ec2.checkbox("AB Switch", value=(switch == 'AB Switch'))
                                n_lineman = st.text_input("Lineman Name", value=lineman)
                                n_lat     = st.text_input("Latitude",     value=lat)
                                n_lon     = st.text_input("Longitude",    value=lon)
                                sc1, sc2  = st.columns(2)
                                saved     = sc1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                cancelled = sc2.form_submit_button("✖ Cancel", use_container_width=True)
                            if saved:
                                if n_lc and n_ab:
                                    st.error("⚠️ Select either LC or AB Switch, not both.")
                                else:
                                    sw = "LC" if n_lc else "AB Switch" if n_ab else "None"
                                    u  = {
                                        "Date": n_date, "DTR Name": n_name,
                                        "DTR Code": n_code, "Latitude": n_lat,
                                        "Longitude": n_lon, "LC/AB Switch": sw,
                                        "Lineman Name": n_lineman, "Synced": "FALSE",
                                    }
                                    if update_row_data("SurveyLogs", row_id, u):
                                        st.session_state[f'eo_surv_{i}'] = False
                                        st.success("Saved!")
                                        time.sleep(0.3)
                                        st.rerun()
                            if cancelled:
                                st.session_state[f'eo_surv_{i}'] = False
                                st.rerun()

                st.markdown("---")
                st.markdown("### 🗑️ Delete Survey Logs")
                st.caption("Select records, then press Delete.")

                del_sel_surv = st.multiselect("Records to delete", list(surv_delete_map.keys()), key="del_sel_surv", label_visibility="collapsed")
                if del_sel_surv:
                    if st.button(f"🗑️ Delete {len(del_sel_surv)} record(s)", key="del_btn_surv"):
                        st.session_state['confirm_del_surv'] = True
                        st.session_state['del_ids_surv'] = [surv_delete_map[lbl] for lbl in del_sel_surv]

                if st.session_state.get('confirm_del_surv', False):
                    n_del = len(st.session_state.get('del_ids_surv', []))
                    st.warning(f"⚠️ **Permanently delete {n_del} survey record(s)?** \nThis action cannot be undone.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ Yes, Delete", key="conf_del_surv", type="primary", use_container_width=True):
                            if bulk_delete_rows("SurveyLogs", st.session_state['del_ids_surv']):
                                st.session_state['confirm_del_surv'] = False
                                st.session_state['del_ids_surv']     = []
                                st.success("Deleted.")
                                time.sleep(0.3)
                                st.rerun()
                    with dc2:
                        if st.button("❌ Cancel", key="cancel_del_surv", use_container_width=True):
                            st.session_state['confirm_del_surv'] = False
                            st.session_state['del_ids_surv']     = []
                            st.rerun()
            else:
                st.info("No logs match filters.")
        else:
            st.info("No Survey Logs available.")

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE › INSTALLATION LOGS
    # ─────────────────────────────────────────────────────────────────────────
    with t_view_logs:
        if st.button("🔄 Refresh Data", key="ref_wl"):
            get_data.clear("WorkLogs")
            st.rerun()

        df = get_data("WorkLogs")
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

            id_col  = resolve_col(df.columns, ['SC No/ DTR Code', 'DTR Code', 'Service Number'])
            if not id_col and len(df.columns) > 2: id_col = df.columns[2]

            ss_col  = resolve_col(df.columns, ['Transformer_SS_No', 'Transformer SS No', 'DTR SS No', 'SS No'])
            box_col = resolve_col(df.columns, ['DTR_Box_No', 'DTR Box No', 'Box No'])
            cap_col = resolve_col(df.columns, ['Capacity', 'Transformer Capacity (KVA)', 'Transformer Capacity', 'Transformer_Capacity'])

            # ── TILE GROUPING & CHRONOLOGICAL SORTING LOGIC ──
            df['DateStr'] = df['Date'].dt.strftime('%Y-%m-%d')
            meta_cols = ['DateStr', 'Site', 'Worker']
            if id_col: meta_cols.append(id_col)
            if ss_col: meta_cols.append(ss_col)
            if box_col: meta_cols.append(box_col)

            df[meta_cols] = df[meta_cols].fillna('')
            
            df['OriginalIndex'] = range(len(df))
            sort_cols = meta_cols + ['OriginalIndex']
            df = df.sort_values(by=sort_cols)

            metadata_changed = (df[meta_cols] != df[meta_cols].shift()).any(axis=1)
            is_box = df['Material'].astype(str).str.contains('Box', case=False, na=False)
            df['_sub_grp'] = (metadata_changed | is_box).cumsum()
            
            df = df.sort_values(by=['Date', '_sub_grp', 'OriginalIndex'], ascending=[False, False, True])

            st.markdown("###### Filters")
            c_f1, c_f2, c_f3 = st.columns(3)
            avail_workers = ["All"] + sorted(df['Worker'].dropna().unique().tolist())
            sel_worker    = c_f1.selectbox("Worker", avail_workers, key="wl_worker")
            sel_date      = c_f2.date_input("Date Range", [], key="wl_date")
            sel_dtr       = c_f3.text_input("DTR Code",   key="wl_dtr")
            
            c_f4, c_f5 = st.columns(2)
            sel_box = c_f4.text_input("DTR Box No", key="wl_box")
            sel_ss  = c_f5.text_input("DTR SS No",  key="wl_ss")

            fdf = df.copy()
            if sel_worker != "All":
                fdf = fdf[fdf['Worker'] == sel_worker]
            if len(sel_date) == 2:
                mask = (
                    (fdf['Date'].dt.date >= sel_date[0]) &
                    (fdf['Date'].dt.date <= sel_date[1])
                )
                fdf = fdf[mask]

            if sel_dtr and id_col:
                fdf = fdf[fdf[id_col].astype(str).str.contains(sel_dtr, case=False, na=False)]
            if sel_box and box_col:
                fdf = fdf[fdf[box_col].astype(str).str.contains(sel_box, case=False, na=False)]
            if sel_ss and ss_col:
                fdf = fdf[fdf[ss_col].astype(str).str.contains(sel_ss, case=False, na=False)]

            if not fdf.empty:
                group_cols_to_agg = ['_sub_grp', 'DateStr', 'Worker']
                if id_col: group_cols_to_agg.append(id_col)
                if ss_col: group_cols_to_agg.append(ss_col)
                if box_col: group_cols_to_agg.append(box_col)

                grouped = (
                    fdf.groupby(group_cols_to_agg, sort=False)
                    .agg(IDs=('ID', list))
                    .reset_index()
                )
                
                # Fetch formatted string for export & UI
                grouped['Materials Consumed'] = grouped['IDs'].apply(lambda ids: format_mat_line({
                    str(rr['Material']).strip(): float(rr['Qty']) if str(rr['Qty']).replace('.','').isdigit() else 0.0
                    for _, rr in fdf[fdf['ID'].isin(ids)].iterrows()
                }))
                
                grouped.rename(columns={'DateStr': 'Date'}, inplace=True)
                if ss_col: grouped.rename(columns={ss_col: 'DTR SS No'}, inplace=True)

                # Excel & PDF Export (Installation Logs)
                st.write("### 📤 Export Filtered Logs")
                ce_w1, ce_w2 = st.columns(2)
                
                exp_cols = ['Date', 'Worker']
                if id_col: exp_cols.append(id_col)
                if ss_col: exp_cols.append('DTR SS No')
                if box_col: exp_cols.append(box_col)
                exp_cols.append('Materials Consumed')
                
                with ce_w1:
                    if FPDF:
                        pdf_data = generate_worklog_pdf(grouped, id_col, ss_col, box_col)
                        st.download_button("⬇️ Download PDF", data=pdf_data, file_name="Installation_Logs.pdf", mime="application/pdf")
                with ce_w2:
                    excel_data, mime_type, ext = convert_df_to_excel(grouped[exp_cols])
                    st.download_button(f"⬇️ Download Excel (.{ext})", data=excel_data, file_name=f"Installation_Logs.{ext}", mime=mime_type)
                    
                st.markdown("---")

                st.markdown(f"**{len(grouped)} installation tile(s)**")

                wl_delete_map = {}   

                for i, (_, grow) in enumerate(grouped.iterrows()):
                    date_val = str(grow.get('Date', '')).strip()
                    worker   = str(grow.get('Worker',  '')).strip()
                    dtr_code = str(grow.get(id_col,    '')).strip() if id_col else ''
                    dtr_ss   = str(grow.get('DTR SS No',    '')).strip() if ss_col else ''
                    box_no   = str(grow.get(box_col,   '')).strip() if box_col and box_col in grow.index else ''
                    row_ids  = grow['IDs']
                    mat_line = grow['Materials Consumed']

                    raw_rows = fdf[fdf['ID'].isin(row_ids)]
                    raw_first = raw_rows.iloc[0]
                    cap_val   = str(raw_first.get(cap_col, '')).strip() if cap_col else ''
                    
                    mat_dict = {str(rr['Material']).strip(): (float(rr['Qty']) if str(rr['Qty']).replace('.','').isdigit() else 0.0) for _, rr in raw_rows.iterrows()}
                    needs_fix  = tile_needs_lugs_fix(mat_dict)

                    del_label = (
                        f"[{i+1}] {date_val}  ·  {worker}  ·  "
                        f"DTR: {dtr_code or '—'}  ·  SS: {dtr_ss or '—'}  ·  "
                        f"{mat_line[:40]}"
                    )
                    wl_delete_map[del_label] = row_ids

                    with st.container(border=True):
                        col_c, col_btn = st.columns([7, 1])

                        with col_c:
                            st.markdown(f"**📅 {date_val}** ·  👷 {worker}")
                            line2 = [
                                f"🔌 DTR Code: **{dtr_code or '—'}**",
                                f"📡 DTR SS No: **{dtr_ss or '—'}**",
                            ]
                            if box_no: line2.append(f"📦 Box No: {box_no}")
                            st.markdown("  ·  ".join(line2))
                            st.caption(mat_line)

                            if needs_fix:
                                lc1, lc2 = st.columns([3, 2])
                                lc1.warning("⚠️ Lugs missing for this cable entry")
                                if lc2.button(
                                    f"➕ Add {DEFAULT_LUGS_QTY} Lugs",
                                    key=f"fix_lugs_{i}",
                                    use_container_width=True,
                                ):
                                    lugs_row = {
                                        "ID":               str(uuid.uuid4()),
                                        "Date":             date_val,
                                        "Site":             str(raw_first.get('Site', '')),
                                        "Worker":           worker,
                                        "Material":         "Lugs",
                                        "Qty":              DEFAULT_LUGS_QTY,
                                        "Latitude":         str(raw_first.get('Latitude',  '')),
                                        "Longitude":        str(raw_first.get('Longitude', '')),
                                        "Synced":           "FALSE",
                                    }
                                    if id_col: lugs_row[id_col] = dtr_code
                                    if box_col: lugs_row[box_col] = box_no
                                    if ss_col: lugs_row[ss_col] = dtr_ss
                                    if cap_col: lugs_row[cap_col] = cap_val

                                    try:
                                        save_row("WorkLogs", lugs_row)
                                        st.toast(f"✅ Added {DEFAULT_LUGS_QTY} Lugs to this entry.")
                                        time.sleep(0.3)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Could not add Lugs: {e}")

                        with col_btn:
                            is_open = st.session_state.get(f'eo_wl_{i}', False)
                            if st.button("✖" if is_open else "✏️", key=f"eb_wl_{i}", help="Close" if is_open else "Edit"):
                                st.session_state[f'eo_wl_{i}'] = not is_open
                                st.rerun()

                        if st.session_state.get(f'eo_wl_{i}', False):
                            st.markdown("---")

                            mat_to_row = {}
                            for _, rr in raw_rows.iterrows():
                                mat = str(rr['Material']).strip()
                                try: qty_r = float(rr['Qty'])
                                except: qty_r = 0.0
                                mat_to_row[mat] = {'row_id': str(rr['ID']), 'qty': qty_r}

                            if not any('cable' in k.lower() for k in mat_to_row.keys()):
                                mat_to_row['Cable'] = {'row_id': 'NEW_CABLE', 'qty': 0.0}
                            if not any('lugs' in k.lower() for k in mat_to_row.keys()):
                                mat_to_row['Lugs'] = {'row_id': 'NEW_LUGS', 'qty': 0.0}

                            with st.form(f"ef_wl_{i}"):
                                st.caption("Edit existing materials or add missing ones by entering a quantity > 0")

                                st.markdown("###### Installation Details")
                                n_date   = st.text_input("Date", value=date_val)
                                
                                mc1, mc2, mc3 = st.columns(3)
                                n_dtr    = mc1.text_input("DTR Code",   value=dtr_code)
                                n_ss     = mc2.text_input("DTR SS No",  value=dtr_ss)
                                n_box    = mc3.text_input("DTR Box No", value=box_no)

                                mc4, mc5 = st.columns(2)
                                n_cap    = mc4.text_input("Capacity", value=cap_val)
                                w_idx    = (workers.index(worker) if worker in workers else 0)
                                n_worker = mc5.selectbox("Worker", workers, index=w_idx)

                                st.markdown("###### Materials")
                                mat_qty_inputs = {}
                                for mat_name, mat_info in mat_to_row.items():
                                    label = f"{mat_name} (Mtrs)" if mat_name.lower() == 'cable' else f"{mat_name} (Qty)"
                                    mat_qty_inputs[mat_name] = st.number_input(
                                        label, value=mat_info['qty'], min_value=0.0, step=1.0, key=f"mat_qty_{i}_{mat_name}"
                                    )

                                sc1, sc2 = st.columns(2)
                                saved    = sc1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                cancelled = sc2.form_submit_button("✖ Cancel", use_container_width=True)

                            if saved:
                                meta_update = {"Date": n_date, "Worker": n_worker, "Synced": "FALSE"}
                                if id_col:  meta_update[id_col]  = n_dtr
                                if ss_col:  meta_update[ss_col]  = n_ss
                                if box_col: meta_update[box_col] = n_box
                                if cap_col: meta_update[cap_col] = n_cap

                                meta_ok = all(update_row_data("WorkLogs", rid, meta_update) for rid in row_ids)
                                
                                qty_ok = True
                                new_rows_to_save = []

                                for mat_name, new_qty in mat_qty_inputs.items():
                                    rid = mat_to_row[mat_name]['row_id']
                                    if rid.startswith("NEW_"):
                                        if new_qty > 0:
                                            new_row = {
                                                "ID": str(uuid.uuid4()), "Date": n_date,
                                                "Site": str(raw_first.get('Site', '')),
                                                "Worker": n_worker, "Material": mat_name,
                                                "Qty": new_qty, "Latitude": str(raw_first.get('Latitude', '')),
                                                "Longitude": str(raw_first.get('Longitude', '')), "Synced": "FALSE"
                                            }
                                            if id_col: new_row[id_col] = n_dtr
                                            if ss_col: new_row[ss_col] = n_ss
                                            if box_col: new_row[box_col] = n_box
                                            if cap_col: new_row[cap_col] = n_cap
                                            new_rows_to_save.append(new_row)
                                    else:
                                        if not update_row_data("WorkLogs", rid, {"Qty": new_qty}):
                                            qty_ok = False

                                for new_r in new_rows_to_save:
                                    save_row("WorkLogs", new_r)

                                if meta_ok and qty_ok:
                                    st.session_state[f'eo_wl_{i}'] = False
                                    st.success("Saved!")
                                    time.sleep(0.3)
                                    st.rerun()
                                else:
                                    st.error("Some fields may not have saved. Check the warnings above.")

                            if cancelled:
                                st.session_state[f'eo_wl_{i}'] = False
                                st.rerun()

                st.markdown("---")
                st.markdown("### 🗑️ Delete Installation Logs")
                st.caption("Select tiles from the list, then press Delete.")

                del_sel_wl = st.multiselect("Tiles to delete", list(wl_delete_map.keys()), key="del_sel_wl", label_visibility="collapsed")

                if del_sel_wl:
                    flat_ids = [rid for lbl in del_sel_wl for rid in wl_delete_map[lbl]]
                    if st.button(f"🗑️ Delete {len(del_sel_wl)} tile(s) ({len(flat_ids)} row(s))", key="del_btn_wl"):
                        st.session_state['confirm_del_wl']  = True
                        st.session_state['del_ids_wl']      = flat_ids
                        st.session_state['del_n_tiles_wl']  = len(del_sel_wl)

                if st.session_state.get('confirm_del_wl', False):
                    n_rows  = len(st.session_state.get('del_ids_wl', []))
                    n_tiles = st.session_state.get('del_n_tiles_wl', '?')
                    st.warning(f"⚠️ **Permanently delete {n_tiles} installation tile(s) ({n_rows} material row(s) in total)?** \nThis action cannot be undone.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ Yes, Delete", key="conf_del_wl", type="primary", use_container_width=True):
                            if bulk_delete_rows("WorkLogs", st.session_state['del_ids_wl']):
                                st.session_state['confirm_del_wl']  = False
                                st.session_state['del_ids_wl']      = []
                                st.session_state['del_n_tiles_wl']  = 0
                                st.success("Deleted.")
                                time.sleep(0.3)
                                st.rerun()
                    with dc2:
                        if st.button("❌ Cancel", key="cancel_del_wl", use_container_width=True):
                            st.session_state['confirm_del_wl']  = False
                            st.session_state['del_ids_wl']      = []
                            st.session_state['del_n_tiles_wl']  = 0
                            st.rerun()

            else:
                st.info("No logs found matching filters.")
        else:
            st.info("No work logs available.")

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE › GPS DATA 
    # ─────────────────────────────────────────────────────────────────────────
    with t_gps:
        st.caption("View and export captured location data.")
        df_gps = get_data("WorkLogs")
        if not df_gps.empty and 'Latitude' in df_gps.columns:
            if 'Date' in df_gps.columns:
                df_gps['Date'] = pd.to_datetime(df_gps['Date'], errors='coerce')
                df_gps['OriginalIndex'] = range(len(df_gps))
                df_gps = df_gps.sort_values(by=['Date', 'OriginalIndex'], ascending=[False, True])

            gps_valid = df_gps[
                df_gps['Latitude'].astype(str).str.strip() != ''
            ].copy()
            if not gps_valid.empty:
                id_col_g = resolve_col(gps_valid.columns, ['SC No/ DTR Code', 'DTR Code', 'Service Number'])
                if not id_col_g: id_col_g = gps_valid.columns[2]

                gps_unique = gps_valid.drop_duplicates(subset=[id_col_g])
                st.dataframe(
                    gps_unique[[id_col_g, 'Site', 'Latitude', 'Longitude']],
                    use_container_width=True,
                )
                st.markdown("#### 📤 Export Location")
                gps_unique['label'] = (
                    gps_unique[id_col_g].astype(str) + " - " + gps_unique['Site']
                )
                sel_loc_g = st.selectbox(
                    "Select Location to Share", gps_unique['label'].tolist()
                )
                if sel_loc_g:
                    grow      = gps_unique[gps_unique['label'] == sel_loc_g].iloc[0]
                    maps_link = (f"https://maps.google.com/?"
                                 f"q={grow['Latitude']},{grow['Longitude']}")
                    text      = (f"📍 Installation Location for "
                                 f"{grow[id_col_g]}: {maps_link}")
                    st.link_button(
                        f"📱 Share {grow[id_col_g]} on WhatsApp",
                        f"https://wa.me/?text={urllib.parse.quote(text)}",
                    )
            else:
                st.info("No GPS data recorded yet.")
        else:
            st.warning("GPS columns not found in Sheet. Please update header row.")

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE › INVENTORY LOGS 
    # ─────────────────────────────────────────────────────────────────────────
    with t_inv_view:
        if st.button("🔄 Refresh Data", key="ref_inv"):
            get_data.clear("Inventory")
            st.rerun()

        df_inv = get_data("Inventory")
        if not df_inv.empty:
            if 'Date' in df_inv.columns:
                df_inv['Date'] = pd.to_datetime(df_inv['Date'], errors='coerce')
                df_inv['OriginalIndex'] = range(len(df_inv))
                df_inv = df_inv.sort_values(by=['Date', 'OriginalIndex'], ascending=[False, True])

            st.markdown("###### Filters")
            ic1, ic2 = st.columns(2)
            avail_mats = ["All"] + sorted(df_inv['Material'].dropna().unique().tolist())
            inv_mat = ic1.selectbox("Material Type", avail_mats, key="inv_mat_filt")
            inv_date = ic2.date_input("Date Range", [], key="inv_date_filt")

            fs_inv = df_inv.copy()
            if inv_mat != "All":
                fs_inv = fs_inv[fs_inv['Material'] == inv_mat]
            if len(inv_date) == 2:
                mask = (
                    (fs_inv['Date'].dt.date >= inv_date[0]) &
                    (fs_inv['Date'].dt.date <= inv_date[1])
                )
                fs_inv = fs_inv[mask]

            if not fs_inv.empty:
                fs_inv['Date'] = fs_inv['Date'].dt.strftime('%Y-%m-%d')
                
                # Excel & PDF Export (Inventory Logs)
                st.write("### 📤 Export Filtered Logs")
                ce_i1, ce_i2 = st.columns(2)
                display_cols = [c for c in fs_inv.columns if c not in ["Synced", "RowIndex", "OriginalIndex", "ID"]]
                
                with ce_i1:
                    if FPDF:
                        pdf_data = generate_inventory_pdf(fs_inv)
                        st.download_button("⬇️ Download PDF", data=pdf_data, file_name="Inventory_Logs.pdf", mime="application/pdf")
                with ce_i2:
                    excel_data, mime_type, ext = convert_df_to_excel(fs_inv[display_cols])
                    st.download_button(f"⬇️ Download Excel (.{ext})", data=excel_data, file_name=f"Inventory_Logs.{ext}", mime=mime_type)

                st.markdown("---")
                st.markdown(f"**{len(fs_inv)} record(s)**")

                inv_delete_map = {}

                for i, (_, row) in enumerate(fs_inv.iterrows()):
                    date_val = str(row.get('Date',     '')).strip()
                    material = str(row.get('Material', '')).strip()
                    qty      = str(row.get('Qty',      '')).strip()
                    inv_type = str(row.get('Type',     'Inward')).strip()
                    synced   = str(row.get('Synced',   '')).strip().upper()
                    row_id   = str(row['ID'])

                    inv_delete_map[f"[{i+1}] {date_val}  ·  {material or '—'} ({qty or '—'})  ·  {inv_type}"] = row_id

                    with st.container(border=True):
                        col_c, col_btn = st.columns([7, 1])

                        with col_c:
                            type_icon = "⬆️" if inv_type.lower() == "inward" else "⬇️"
                            st.markdown(f"**📅 {date_val}** ·  {type_icon} {inv_type}")
                            st.markdown(f"📦 Material: **{material or '—'}** ·  🔢 Qty: **{qty or '—'}**")
                            st.caption("✅ Synced" if synced == "TRUE" else "🔄 Pending sync")

                        with col_btn:
                            is_open = st.session_state.get(f'eo_inv_{i}', False)
                            if st.button("✖" if is_open else "✏️", key=f"eb_inv_{i}", help="Close" if is_open else "Edit"):
                                st.session_state[f'eo_inv_{i}'] = not is_open
                                st.rerun()

                        if st.session_state.get(f'eo_inv_{i}', False):
                            st.markdown("---")
                            with st.form(f"ef_inv_{i}"):
                                st.caption(f"Editing record ID: {row_id}")
                                n_date = st.text_input("Date", value=date_val)
                                n_mat  = st.selectbox("Material", materials_list, index=(materials_list.index(material) if material in materials_list else 0))
                                n_qty  = st.number_input("Qty", value=(float(qty) if qty else 0.0))
                                ic1, ic2  = st.columns(2)
                                saved     = ic1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                cancelled = ic2.form_submit_button("✖ Cancel", use_container_width=True)
                            if saved:
                                u = {"Date": n_date, "Material": n_mat, "Qty": n_qty, "Synced": "FALSE"}
                                if update_row_data("Inventory", row_id, u):
                                    st.session_state[f'eo_inv_{i}'] = False
                                    st.success("Saved!")
                                    time.sleep(0.3)
                                    st.rerun()
                            if cancelled:
                                st.session_state[f'eo_inv_{i}'] = False
                                st.rerun()

                st.markdown("---")
                st.markdown("### 🗑️ Delete Inventory Records")
                st.caption("Select records, then press Delete. A confirmation prompt will appear.")

                del_sel_inv = st.multiselect("Records to delete", list(inv_delete_map.keys()), key="del_sel_inv", label_visibility="collapsed")
                if del_sel_inv:
                    if st.button(f"🗑️ Delete {len(del_sel_inv)} record(s)", key="del_btn_inv"):
                        st.session_state['confirm_del_inv'] = True
                        st.session_state['del_ids_inv'] = [inv_delete_map[lbl] for lbl in del_sel_inv]

                if st.session_state.get('confirm_del_inv', False):
                    n_del = len(st.session_state.get('del_ids_inv', []))
                    st.warning(f"⚠️ **Permanently delete {n_del} inventory record(s)?** \nThis action cannot be undone.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ Yes, Delete", key="conf_del_inv", type="primary", use_container_width=True):
                            if bulk_delete_rows("Inventory", st.session_state['del_ids_inv']):
                                st.session_state['confirm_del_inv'] = False
                                st.session_state['del_ids_inv']     = []
                                st.success("Deleted.")
                                time.sleep(0.3)
                                st.rerun()
                    with dc2:
                        if st.button("❌ Cancel", key="cancel_del_inv", use_container_width=True):
                            st.session_state['confirm_del_inv'] = False
                            st.session_state['del_ids_inv']     = []
                            st.rerun()
            else:
                st.info("No inventory logs match filters.")
        else:
            st.info("No inventory logs available.")

# =============================================================================
# TAB 3 — INVENTORY (Add Stock)
# =============================================================================
with tabs[3]:
    st.subheader("📊 Stock Overview")
    if current_stock:
        sorted_stock = sorted(current_stock.items(), key=lambda x: x[1])
        cols = st.columns(3)
        for i, (item, qty) in enumerate(sorted_stock):
            color = "normal" if qty >= 10 else "inverse"
            with cols[i % 3]:
                st.metric(
                    label=item,
                    value=f"{qty:,.0f}",
                    delta="Low" if qty < 10 else None,
                    delta_color=color,
                )
    else:
        st.info("No stock data.")

    st.markdown("---")
    with st.form("inv_form_add", clear_on_submit=True):
        st.caption("📥 Add New Stock")
        c1, c2, c3 = st.columns([1, 1, 1])
        i_date = c1.date_input("Date", datetime.today())
        i_mat  = c2.selectbox("Material", materials_list)
        i_qty  = c3.number_input("Qty", min_value=0.0, step=1.0)
        if st.form_submit_button("Add Stock", use_container_width=True):
            payload = {
                "ID": str(uuid.uuid4()), "Date": str(i_date),
                "Material": i_mat, "Qty": i_qty,
                "Type": "Inward", "Synced": "FALSE",
            }
            save_row("Inventory", payload)
            st.toast(f"✅ Added {i_qty} {i_mat}")
            time.sleep(0.3)
            st.rerun()

# =============================================================================
# TAB 4 — WORKERS
# =============================================================================
with tabs[4]:
    st.subheader("👥 Workers")
    if st.button("🔄 Refresh Data", key="ref_work"):
        get_data.clear("Workers")
        st.rerun()

    with st.expander("➕ Add Worker"):
        with st.form("add_worker"):
            new_w = st.text_input("Name")
            if st.form_submit_button("Add"):
                if new_w and new_w not in workers:
                    save_row("Workers", {"Name": new_w, "Synced": "FALSE"})
                    st.rerun()

    df_workers = get_data("Workers")
    if not df_workers.empty:
        edited = st.data_editor(
            df_workers,
            use_container_width=True,
            num_rows="dynamic",
            key="w_edit",
            column_config={"Synced": st.column_config.Column(disabled=True)},
        )
        if st.button("💾 Save List"):
            update_worker_registry(edited)
            st.toast("✅ Workers updated")
            time.sleep(0.3)
            st.rerun()
