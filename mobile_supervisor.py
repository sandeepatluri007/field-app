import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import uuid
import time
import os
import urllib.parse

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
LOGO_FILE  = "logodesign4.jpg"

# =============================================================================
# CONNECTION & DATA HELPERS
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

def clear_cache():
    st.cache_data.clear()

@st.cache_data(ttl=60, show_spinner=False)
def get_data(worksheet):
    client = get_connection()
    try:
        ws = client.open(SHEET_NAME).worksheet(worksheet)
        return pd.DataFrame(ws.get_all_records())
    except:
        return pd.DataFrame()

def save_batch_rows(worksheet, rows_list):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    ws.append_rows(rows_list)
    clear_cache()

def save_row(worksheet, row_dict):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    headers    = ws.row_values(1)
    row_values = [row_dict.get(h, "") for h in headers]
    ws.append_row(row_values)
    clear_cache()

def bulk_delete_rows(worksheet, id_list):
    if not id_list:
        return False
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell_list = []
        for rid in id_list:
            found = ws.findall(str(rid))
            cell_list.extend(found)
        rows_to_delete = sorted(list(set(c.row for c in cell_list)), reverse=True)
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
        cell    = ws.find(str(row_id))
        r       = cell.row
        headers = ws.row_values(1)
        updates = []
        for col_name, value in updated_data.items():
            if col_name in headers:
                col_idx = headers.index(col_name) + 1
                updates.append({
                    'range':  gspread.utils.rowcol_to_a1(r, col_idx),
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
    client  = get_connection()
    ws      = client.open(SHEET_NAME).worksheet("Workers")
    headers = ws.row_values(1)
    if 'Synced' not in edited_df.columns:
        edited_df['Synced'] = "FALSE"
    ws.clear()
    ws.update([headers] + edited_df.values.tolist())
    clear_cache()

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

def generate_survey_pdf(df_export):
    if FPDF is None:
        return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Survey Logs Export", ln=True, align='C')
    pdf.ln(5)
    for _, row in df_export.iterrows():
        dtr_name = str(row.get('DTR Name', 'N/A'))
        dtr_code = str(row.get('DTR Code', 'N/A'))
        lat      = str(row.get('Latitude',  ''))
        lon      = str(row.get('Longitude', ''))
        date_val = str(row.get('Date', ''))
        lc_val   = str(row.get('LC/AB Switch', 'None'))
        lm_val   = str(row.get('Lineman Name', 'N/A'))
        loc_link = (f"https://maps.google.com/?q={lat},{lon}"
                    if lat and lon else "No Location Provided")
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(200, 8,
                 txt=f"DTR SS No: {dtr_name} (Code: {dtr_code}) | Date: {date_val}",
                 ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(200, 8, txt=f"Switch: {lc_val} | Lineman: {lm_val}", ln=True)
        pdf.cell(200, 8, txt=f"Location: {loc_link}", ln=True)
        pdf.ln(5)
    return pdf.output(dest='S').encode('latin-1')

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
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save Failed: {e}")

# =============================================================================
# TAB 1 — LOG WORK
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
        c1, c2, c3 = st.columns([1, 1, 1])
        w_date   = c1.date_input("Date",   datetime.today())
        w_site   = c2.selectbox("Site",    sites_list)
        w_worker = c3.selectbox("Worker",  workers)
        c4, c5       = st.columns(2)
        w_main_id    = c4.text_input(id_label)
        w_dtr_box = w_ss_no = w_capacity = ""
        if is_dtr:
            w_dtr_box  = c5.text_input("DTR Box No")
            c6, c7     = st.columns(2)
            w_ss_no    = c6.text_input("DTR SS No")
            w_capacity = c7.text_input("Transformer Capacity (KVA)")
        else:
            c5.write("")

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
        qty_lugs  = c_m2.number_input("Lugs (Qty)",   min_value=0.0, step=1.0)
        st.caption("Coordinates (Auto-filled by Checkbox or Survey Database)")
        c_lt, c_lg = st.columns(2)
        w_lat  = c_lt.text_input("Latitude",  value=(auto_lat  or surv_lat))
        w_long = c_lg.text_input("Longitude", value=(auto_long or surv_lon))

        if st.form_submit_button("🚀 Submit Log", type="primary",
                                 use_container_width=True):
            batch_rows    = []
            meta_data     = [str(w_date), w_main_id, w_dtr_box, w_ss_no,
                             w_capacity, w_site, w_worker]
            gps_data      = [w_lat, w_long]
            box_item      = f"{w_meter_type} Box"
            batch_rows.append([str(uuid.uuid4())] + meta_data +
                              [box_item, 1] + gps_data + ["FALSE"])
            if qty_cable > 0:
                batch_rows.append([str(uuid.uuid4())] + meta_data +
                                  ["Cable", qty_cable] + gps_data + ["FALSE"])
            if qty_lugs > 0:
                batch_rows.append([str(uuid.uuid4())] + meta_data +
                                  ["Lugs", qty_lugs] + gps_data + ["FALSE"])
            try:
                save_batch_rows("WorkLogs", batch_rows)
                st.toast("✅ Log Saved!")
                time.sleep(1)
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
    # VIEW & MANAGE > SURVEY LOGS
    #
    # Tile layout (top→bottom):
    #   📅 Date
    #   🔌 DTR Code: X  ·  📡 DTR SS No: Y   ← always both labels
    #   🔘 Switch  ·  👤 Lineman
    #   📍 GPS  ·  Sync badge
    #
    # ✏️ on tile  → inline edit form
    # 🗑️ section  → multiselect + confirm dialog
    # ─────────────────────────────────────────────────────────────────────────
    with t_survey_view:
        if st.button("🔄 Refresh Data", key="ref_surv"):
            clear_cache()
            st.rerun()

        if not survey_data.empty:
            if 'Date' in survey_data.columns:
                survey_data['Date'] = pd.to_datetime(survey_data['Date'], errors='coerce')

            st.markdown("###### Filters")
            cf1, cf2, cf3 = st.columns(3)
            surv_search = cf1.text_input("Search DTR Code / DTR SS No")
            surv_switch = cf2.selectbox("Switch Type",
                                        ["All", "LC", "AB Switch", "None"])
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
                st.markdown(f"**{len(fs)} record(s)**")

                surv_delete_map = {}  # label → row_id

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

                    surv_delete_map[
                        f"[{i+1}] {date_val}  ·  "
                        f"DTR: {dtr_code or '—'}  ·  SS: {dtr_ss or '—'}"
                    ] = row_id

                    # ── Tile ─────────────────────────────────────────────────
                    with st.container(border=True):
                        col_c, col_btn = st.columns([7, 1])

                        with col_c:
                            # Line 1: Date
                            st.markdown(f"**📅 {date_val}**")
                            # Line 2: DTR Code · DTR SS No — always both labels
                            st.markdown(
                                f"🔌 DTR Code: **{dtr_code or '—'}**  ·  "
                                f"📡 DTR SS No: **{dtr_ss or '—'}**"
                            )
                            # Line 3: Switch · Lineman
                            meta = []
                            if switch and switch != "None":
                                meta.append(f"🔘 {switch}")
                            if lineman:
                                meta.append(f"👤 {lineman}")
                            if meta:
                                st.caption("  ·  ".join(meta))
                            # Line 4: GPS · Synced
                            badge = []
                            if lat and lon:
                                badge.append(f"📍 {lat[:9]}, {lon[:9]}")
                            badge.append("✅ Synced" if synced == "TRUE" else "🔄 Pending")
                            st.caption("  ·  ".join(badge))

                        with col_btn:
                            is_open = st.session_state.get(f'eo_surv_{i}', False)
                            if st.button(
                                "✖" if is_open else "✏️",
                                key=f"eb_surv_{i}",
                                help="Close" if is_open else "Edit"
                            ):
                                st.session_state[f'eo_surv_{i}'] = not is_open
                                st.rerun()

                        # ── Inline edit (inside same container) ──────────────
                        if st.session_state.get(f'eo_surv_{i}', False):
                            st.markdown("---")
                            with st.form(f"ef_surv_{i}"):
                                st.caption(f"Editing ID: {row_id}")
                                n_date    = st.text_input("Date",       value=date_val)
                                n_name    = st.text_input("DTR SS No",  value=dtr_ss)
                                n_code    = st.text_input("DTR Code",   value=dtr_code)
                                st.markdown("###### Switch Present")
                                ec1, ec2  = st.columns(2)
                                n_lc = ec1.checkbox("LC",
                                                    value=(switch == 'LC'))
                                n_ab = ec2.checkbox("AB Switch",
                                                    value=(switch == 'AB Switch'))
                                n_lineman = st.text_input("Lineman Name", value=lineman)
                                n_lat     = st.text_input("Latitude",     value=lat)
                                n_lon     = st.text_input("Longitude",    value=lon)
                                sc1, sc2  = st.columns(2)
                                saved     = sc1.form_submit_button(
                                    "💾 Save", type="primary",
                                    use_container_width=True)
                                cancelled = sc2.form_submit_button(
                                    "✖ Cancel", use_container_width=True)

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
                                        time.sleep(0.8)
                                        st.rerun()
                            if cancelled:
                                st.session_state[f'eo_surv_{i}'] = False
                                st.rerun()

                # ── DELETE SECTION (bottom of tab) ────────────────────────────
                st.markdown("---")
                st.markdown("### 🗑️ Delete Survey Logs")
                st.caption(
                    "Select records from the list, then press Delete. "
                    "A confirmation prompt will appear before anything is removed."
                )

                del_sel_surv = st.multiselect(
                    "Records to delete",
                    list(surv_delete_map.keys()),
                    key="del_sel_surv",
                    label_visibility="collapsed",
                )

                if del_sel_surv:
                    if st.button(
                        f"🗑️ Delete {len(del_sel_surv)} record(s)",
                        key="del_btn_surv",
                    ):
                        st.session_state['confirm_del_surv'] = True
                        st.session_state['del_ids_surv'] = [
                            surv_delete_map[lbl] for lbl in del_sel_surv
                        ]

                if st.session_state.get('confirm_del_surv', False):
                    n_del = len(st.session_state.get('del_ids_surv', []))
                    st.warning(
                        f"⚠️ **Permanently delete {n_del} survey record(s)?**  \n"
                        f"This action cannot be undone."
                    )
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ Yes, Delete", key="conf_del_surv",
                                     type="primary", use_container_width=True):
                            if bulk_delete_rows(
                                "SurveyLogs",
                                st.session_state['del_ids_surv']
                            ):
                                st.session_state['confirm_del_surv'] = False
                                st.session_state['del_ids_surv']     = []
                                st.success("Deleted.")
                                time.sleep(0.8)
                                st.rerun()
                    with dc2:
                        if st.button("❌ Cancel", key="cancel_del_surv",
                                     use_container_width=True):
                            st.session_state['confirm_del_surv'] = False
                            st.session_state['del_ids_surv']     = []
                            st.rerun()

            else:
                st.info("No logs match filters.")
        else:
            st.info("No Survey Logs available.")

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE > INSTALLATION LOGS
    #
    # Tile layout (top→bottom):
    #   📅 Date  ·  👷 Worker
    #   🔌 DTR Code: X  ·  📡 DTR SS No: Y  [·  📦 Box: Z]
    #   🔧 Materials
    #
    # GROUPING RULE:
    #   Rows that share the same Date + Worker + DTR Code + SS No are merged
    #   into one tile (multiple materials listed on line 3).
    #   Rows where BOTH DTR Code AND SS No are blank each receive a unique
    #   _grp_uid before groupby → they are NEVER merged, each gets its own tile.
    #
    # ✏️ on tile  → inline edit form (edits shared metadata for all raw rows)
    # 🗑️ section  → multiselect + confirm dialog
    # ─────────────────────────────────────────────────────────────────────────
    with t_view_logs:
        df = get_data("WorkLogs")
        if not df.empty:
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

            st.markdown("###### Filters")
            c_f1, c_f2, c_f3, c_f4 = st.columns(4)
            avail_sites   = ["All"] + sorted(df['Site'].dropna().unique().tolist())
            sel_loc       = c_f1.selectbox("Location (Site)", avail_sites, key="wl_loc")
            sel_mat       = c_f2.text_input("Type / Material",
                                            placeholder="e.g. Cable, Box")
            avail_workers = ["All"] + sorted(df['Worker'].dropna().unique().tolist())
            sel_worker    = c_f3.selectbox("Worker", avail_workers, key="wl_worker")
            sel_date      = c_f4.date_input("Date Range", [], key="wl_date")
            c_f5, c_f6, c_f7 = st.columns(3)
            sel_dtr = c_f5.text_input("DTR Code",   key="wl_dtr")
            sel_box = c_f6.text_input("DTR Box No", key="wl_box")
            sel_ss  = c_f7.text_input("DTR SS No",  key="wl_ss")

            fdf = df.copy()
            if sel_loc != "All":
                fdf = fdf[fdf['Site'] == sel_loc]
            if sel_worker != "All":
                fdf = fdf[fdf['Worker'] == sel_worker]
            if len(sel_date) == 2:
                mask = (
                    (fdf['Date'].dt.date >= sel_date[0]) &
                    (fdf['Date'].dt.date <= sel_date[1])
                )
                fdf = fdf[mask]
            if sel_mat:
                fdf = fdf[
                    fdf['Material'].astype(str).str.contains(
                        sel_mat, case=False, na=False)
                ]

            id_col  = ('SC No/ DTR Code'
                       if 'SC No/ DTR Code' in fdf.columns
                       else fdf.columns[2])
            ss_col  = 'Transformer_SS_No' if 'Transformer_SS_No' in fdf.columns else None
            box_col = 'DTR_Box_No'         if 'DTR_Box_No'         in fdf.columns else None

            if sel_dtr:
                fdf = fdf[
                    fdf[id_col].astype(str).str.contains(sel_dtr, case=False, na=False)
                ]
            if sel_box and box_col:
                fdf = fdf[
                    fdf[box_col].astype(str).str.contains(sel_box, case=False, na=False)
                ]
            if sel_ss and ss_col:
                fdf = fdf[
                    fdf[ss_col].astype(str).str.contains(sel_ss, case=False, na=False)
                ]

            if not fdf.empty:
                fdf = fdf.copy()
                fdf['DateStr']  = fdf['Date'].dt.strftime('%Y-%m-%d')
                fdf['ItemDesc'] = (
                    fdf['Material'].astype(str) +
                    " (" + fdf['Qty'].astype(str) + ")"
                )

                # ── Unique key for blank-ID rows (prevents accidental merging)
                id_vals = fdf[id_col].astype(str).str.strip()
                ss_vals = (fdf[ss_col].astype(str).str.strip()
                           if ss_col else pd.Series('', index=fdf.index))
                empty_mask = id_vals.eq('') & ss_vals.eq('')
                fdf['_grp_uid'] = ''
                if empty_mask.any():
                    fdf.loc[empty_mask, '_grp_uid'] = [
                        str(uuid.uuid4()) for _ in range(int(empty_mask.sum()))
                    ]

                group_cols = ['DateStr', id_col, 'Worker', '_grp_uid']
                if ss_col:  group_cols.append(ss_col)
                if box_col: group_cols.append(box_col)
                fdf[group_cols] = fdf[group_cols].fillna('')

                grouped = (
                    fdf.groupby(group_cols, sort=False)
                    .agg(ItemDesc=('ItemDesc', lambda x: ', '.join(x)),
                         IDs=('ID', list))
                    .reset_index()
                )

                # Rename SS col for display
                if ss_col and ss_col in grouped.columns:
                    grouped.rename(columns={ss_col: '_ss_disp'}, inplace=True)
                    ss_disp = '_ss_disp'
                else:
                    ss_disp = None

                st.markdown(f"**{len(grouped)} installation tile(s)**")

                wl_delete_map = {}  # label → list of raw row IDs

                for i, (_, row) in enumerate(grouped.iterrows()):
                    date_val  = str(row.get('DateStr',   '')).strip()
                    worker    = str(row.get('Worker',     '')).strip()
                    dtr_code  = str(row.get(id_col,       '')).strip()
                    dtr_ss    = str(row.get(ss_disp, '') if ss_disp else '').strip()
                    box_no    = (str(row.get(box_col, '')).strip()
                                 if box_col and box_col in row.index else '')
                    materials = str(row.get('ItemDesc',   '')).strip()
                    row_ids   = row['IDs']

                    wl_delete_map[
                        f"[{i+1}] {date_val}  ·  {worker}  ·  "
                        f"DTR: {dtr_code or '—'}  ·  SS: {dtr_ss or '—'}  ·  "
                        f"{materials[:35]}"
                    ] = row_ids

                    # ── Tile ─────────────────────────────────────────────────
                    with st.container(border=True):
                        col_c, col_btn = st.columns([7, 1])

                        with col_c:
                            # Line 1: Date · Worker
                            st.markdown(f"**📅 {date_val}**  ·  👷 {worker}")
                            # Line 2: DTR Code · DTR SS No — always both labels
                            line2 = [
                                f"🔌 DTR Code: **{dtr_code or '—'}**",
                                f"📡 DTR SS No: **{dtr_ss or '—'}**",
                            ]
                            if box_no:
                                line2.append(f"📦 Box: {box_no}")
                            st.markdown("  ·  ".join(line2))
                            # Line 3: Materials
                            st.caption(f"🔧 {materials}")

                        with col_btn:
                            is_open = st.session_state.get(f'eo_wl_{i}', False)
                            if st.button(
                                "✖" if is_open else "✏️",
                                key=f"eb_wl_{i}",
                                help="Close" if is_open else "Edit"
                            ):
                                st.session_state[f'eo_wl_{i}'] = not is_open
                                st.rerun()

                        # ── Inline edit ───────────────────────────────────────
                        # Updates shared metadata for ALL raw rows in this group
                        if st.session_state.get(f'eo_wl_{i}', False):
                            st.markdown("---")
                            with st.form(f"ef_wl_{i}"):
                                st.caption(
                                    f"Editing {len(row_ids)} material row(s) "
                                    f"in this installation"
                                )
                                n_date   = st.text_input("Date",       value=date_val)
                                n_dtr    = st.text_input("DTR Code",   value=dtr_code)
                                n_ss     = st.text_input("DTR SS No",  value=dtr_ss)
                                n_box    = st.text_input("DTR Box No", value=box_no)
                                w_idx    = (workers.index(worker)
                                            if worker in workers else 0)
                                n_worker = st.selectbox("Worker",
                                                        workers, index=w_idx)
                                sc1, sc2 = st.columns(2)
                                saved    = sc1.form_submit_button(
                                    "💾 Save", type="primary",
                                    use_container_width=True)
                                cancelled = sc2.form_submit_button(
                                    "✖ Cancel", use_container_width=True)

                            if saved:
                                u = {
                                    "Date":    n_date,
                                    id_col:    n_dtr,
                                    "Worker":  n_worker,
                                    "Synced":  "FALSE",
                                }
                                if ss_col:  u[ss_col]  = n_ss
                                if box_col: u[box_col] = n_box
                                ok = all(
                                    update_row_data("WorkLogs", rid, u)
                                    for rid in row_ids
                                )
                                if ok:
                                    st.session_state[f'eo_wl_{i}'] = False
                                    st.success("Saved!")
                                    time.sleep(0.8)
                                    st.rerun()
                            if cancelled:
                                st.session_state[f'eo_wl_{i}'] = False
                                st.rerun()

                # ── DELETE SECTION (bottom of tab) ────────────────────────────
                st.markdown("---")
                st.markdown("### 🗑️ Delete Installation Logs")
                st.caption(
                    "Select tiles from the list, then press Delete. "
                    "A confirmation prompt will appear before anything is removed."
                )

                del_sel_wl = st.multiselect(
                    "Tiles to delete",
                    list(wl_delete_map.keys()),
                    key="del_sel_wl",
                    label_visibility="collapsed",
                )

                if del_sel_wl:
                    flat_ids = [
                        rid
                        for lbl in del_sel_wl
                        for rid in wl_delete_map[lbl]
                    ]
                    if st.button(
                        f"🗑️ Delete {len(del_sel_wl)} tile(s) "
                        f"({len(flat_ids)} row(s))",
                        key="del_btn_wl",
                    ):
                        st.session_state['confirm_del_wl'] = True
                        st.session_state['del_ids_wl']     = flat_ids
                        st.session_state['del_n_tiles_wl'] = len(del_sel_wl)

                if st.session_state.get('confirm_del_wl', False):
                    n_rows  = len(st.session_state.get('del_ids_wl', []))
                    n_tiles = st.session_state.get('del_n_tiles_wl', '?')
                    st.warning(
                        f"⚠️ **Permanently delete {n_tiles} installation tile(s) "
                        f"({n_rows} material row(s) in total)?**  \n"
                        f"This action cannot be undone."
                    )
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ Yes, Delete", key="conf_del_wl",
                                     type="primary", use_container_width=True):
                            if bulk_delete_rows(
                                "WorkLogs",
                                st.session_state['del_ids_wl']
                            ):
                                st.session_state['confirm_del_wl']  = False
                                st.session_state['del_ids_wl']      = []
                                st.session_state['del_n_tiles_wl']  = 0
                                st.success("Deleted.")
                                time.sleep(0.8)
                                st.rerun()
                    with dc2:
                        if st.button("❌ Cancel", key="cancel_del_wl",
                                     use_container_width=True):
                            st.session_state['confirm_del_wl']  = False
                            st.session_state['del_ids_wl']      = []
                            st.session_state['del_n_tiles_wl']  = 0
                            st.rerun()

            else:
                st.info("No logs found matching filters.")
        else:
            st.info("No work logs available.")

    # ─────────────────────────────────────────────────────────────────────────
    # VIEW & MANAGE > GPS DATA  (unchanged)
    # ─────────────────────────────────────────────────────────────────────────
    with t_gps:
        st.caption("View and export captured location data.")
        df_gps = get_data("WorkLogs")
        if not df_gps.empty and 'Latitude' in df_gps.columns:
            gps_valid = df_gps[
                df_gps['Latitude'].astype(str).str.strip() != ''
            ].copy()
            if not gps_valid.empty:
                id_col_g   = ('SC No/ DTR Code'
                              if 'SC No/ DTR Code' in gps_valid.columns
                              else gps_valid.columns[2])
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
    # VIEW & MANAGE > INVENTORY LOGS
    #
    # Tile layout (top→bottom):
    #   📅 Date  ·  ⬆️ Inward / ⬇️ Outward
    #   📦 Material: X  ·  🔢 Qty: Y   ← always both labels
    #   🔄 Pending / ✅ Synced
    #
    # ✏️ on tile  → inline edit form
    # 🗑️ section  → multiselect + confirm dialog
    # ─────────────────────────────────────────────────────────────────────────
    with t_inv_view:
        df_inv = get_data("Inventory")
        if not df_inv.empty:
            st.markdown(f"**{len(df_inv)} record(s)**")

            inv_delete_map = {}  # label → row_id

            for i, (_, row) in enumerate(df_inv.iterrows()):
                date_val = str(row.get('Date',     '')).strip()
                material = str(row.get('Material', '')).strip()
                qty      = str(row.get('Qty',      '')).strip()
                inv_type = str(row.get('Type',     'Inward')).strip()
                synced   = str(row.get('Synced',   '')).strip().upper()
                row_id   = str(row['ID'])

                inv_delete_map[
                    f"[{i+1}] {date_val}  ·  "
                    f"{material or '—'} ({qty or '—'})  ·  {inv_type}"
                ] = row_id

                # ── Tile ─────────────────────────────────────────────────────
                with st.container(border=True):
                    col_c, col_btn = st.columns([7, 1])

                    with col_c:
                        # Line 1: Date · Type
                        type_icon = "⬆️" if inv_type.lower() == "inward" else "⬇️"
                        st.markdown(f"**📅 {date_val}**  ·  {type_icon} {inv_type}")
                        # Line 2: Material · Qty — always both labels
                        st.markdown(
                            f"📦 Material: **{material or '—'}**  ·  "
                            f"🔢 Qty: **{qty or '—'}**"
                        )
                        # Line 3: Sync badge
                        st.caption(
                            "✅ Synced" if synced == "TRUE" else "🔄 Pending sync"
                        )

                    with col_btn:
                        is_open = st.session_state.get(f'eo_inv_{i}', False)
                        if st.button(
                            "✖" if is_open else "✏️",
                            key=f"eb_inv_{i}",
                            help="Close" if is_open else "Edit"
                        ):
                            st.session_state[f'eo_inv_{i}'] = not is_open
                            st.rerun()

                    # ── Inline edit ───────────────────────────────────────────
                    if st.session_state.get(f'eo_inv_{i}', False):
                        st.markdown("---")
                        with st.form(f"ef_inv_{i}"):
                            st.caption(f"Editing record ID: {row_id}")
                            n_date = st.text_input("Date", value=date_val)
                            n_mat  = st.selectbox(
                                "Material", materials_list,
                                index=(materials_list.index(material)
                                       if material in materials_list else 0),
                            )
                            n_qty  = st.number_input(
                                "Qty",
                                value=(float(qty) if qty else 0.0),
                            )
                            ic1, ic2  = st.columns(2)
                            saved     = ic1.form_submit_button(
                                "💾 Save", type="primary",
                                use_container_width=True)
                            cancelled = ic2.form_submit_button(
                                "✖ Cancel", use_container_width=True)

                        if saved:
                            u = {
                                "Date": n_date, "Material": n_mat,
                                "Qty": n_qty, "Synced": "FALSE",
                            }
                            if update_row_data("Inventory", row_id, u):
                                st.session_state[f'eo_inv_{i}'] = False
                                st.success("Saved!")
                                time.sleep(0.8)
                                st.rerun()
                        if cancelled:
                            st.session_state[f'eo_inv_{i}'] = False
                            st.rerun()

            # ── DELETE SECTION (bottom of tab) ────────────────────────────────
            st.markdown("---")
            st.markdown("### 🗑️ Delete Inventory Records")
            st.caption(
                "Select records from the list, then press Delete. "
                "A confirmation prompt will appear before anything is removed."
            )

            del_sel_inv = st.multiselect(
                "Records to delete",
                list(inv_delete_map.keys()),
                key="del_sel_inv",
                label_visibility="collapsed",
            )

            if del_sel_inv:
                if st.button(
                    f"🗑️ Delete {len(del_sel_inv)} record(s)",
                    key="del_btn_inv",
                ):
                    st.session_state['confirm_del_inv'] = True
                    st.session_state['del_ids_inv'] = [
                        inv_delete_map[lbl] for lbl in del_sel_inv
                    ]

            if st.session_state.get('confirm_del_inv', False):
                n_del = len(st.session_state.get('del_ids_inv', []))
                st.warning(
                    f"⚠️ **Permanently delete {n_del} inventory record(s)?**  \n"
                    f"This action cannot be undone."
                )
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("✅ Yes, Delete", key="conf_del_inv",
                                 type="primary", use_container_width=True):
                        if bulk_delete_rows(
                            "Inventory",
                            st.session_state['del_ids_inv']
                        ):
                            st.session_state['confirm_del_inv'] = False
                            st.session_state['del_ids_inv']     = []
                            st.success("Deleted.")
                            time.sleep(0.8)
                            st.rerun()
                with dc2:
                    if st.button("❌ Cancel", key="cancel_del_inv",
                                 use_container_width=True):
                        st.session_state['confirm_del_inv'] = False
                        st.session_state['del_ids_inv']     = []
                        st.rerun()

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
            time.sleep(1)
            st.rerun()

# =============================================================================
# TAB 4 — WORKERS
# =============================================================================
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
        edited = st.data_editor(
            df_workers,
            use_container_width=True,
            num_rows="dynamic",
            key="w_edit",
            column_config={"Synced": st.column_config.Column(disabled=True)},
        )
        if st.button("💾 Save List"):
            update_worker_registry(edited)
            st.rerun()
