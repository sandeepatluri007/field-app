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
LOGO_FILE = "logodesign4.jpg"

# --- GLOBAL MOBILE CSS ---
st.markdown("""
<style>
/* Installation log cards */
.install-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 12px 14px 8px 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
}
.install-card:hover { box-shadow: 0 3px 10px rgba(0,0,0,0.12); }

.type-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #fff;
    margin-right: 6px;
}
.badge-dtr   { background: #1d4ed8; }
.badge-1ph   { background: #15803d; }
.badge-3ph   { background: #b45309; }
.badge-other { background: #6b7280; }

.card-meta {
    font-size: 0.78rem;
    color: #6b7280;
    margin-bottom: 6px;
}
.card-id {
    font-size: 1rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 2px;
}
.card-sub {
    font-size: 0.78rem;
    color: #6b7280;
    margin-bottom: 8px;
}
.mat-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 4px;
}
.mat-chip {
    background: #f3f4f6;
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 0.8rem;
    color: #374151;
    font-weight: 500;
}
.mat-chip span { color: #1d4ed8; font-weight: 700; }

/* Tighten st.metric on mobile */
div[data-testid="metric-container"] {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 6px 10px;
}
/* Edit form inside expander */
.edit-panel {
    background: #f0f9ff;
    border-radius: 8px;
    padding: 10px;
    margin-top: 6px;
}
</style>
""", unsafe_allow_html=True)

# --- CACHED CONNECTION ---
@st.cache_resource(show_spinner=False)
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

@st.cache_data(ttl=60, show_spinner=False)
def get_settings_lists():
    df = get_data("Settings")
    if not df.empty:
        sites = df['Site_List'].dropna().unique().tolist()
        m_types = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        return [x for x in sites if x], [x for x in m_types if x], [x for x in materials if x]
    return ["Default Site"], ["1 Phase", "3 Phase", "DTR"], ["Cable", "Lugs"]

@st.cache_data(ttl=60, show_spinner=False)
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
        lc_val = str(row.get('LC/AB Switch', 'None'))
        lm_val = str(row.get('Lineman Name', 'N/A'))

        loc_link = f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "No Location Provided"

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(200, 8, txt=f"DTR SS No: {dtr_name} (Code: {dtr_code}) | Date: {date_val}", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(200, 8, txt=f"Switch: {lc_val} | Lineman: {lm_val}", ln=True)
        pdf.cell(200, 8, txt=f"Location: {loc_link}", ln=True)
        pdf.ln(5)

    return pdf.output(dest='S').encode('latin-1')

# ─────────────────────────────────────────────
# HELPER: Extract installation type from materials
# Each installation's box row is stored as e.g. "DTR Box", "1 Phase Box", "3 Phase Box"
# We read that to tag the whole installation group.
# ─────────────────────────────────────────────
def extract_install_type(material_series):
    """Given a series of materials for one group, find the Box entry and derive type."""
    for m in material_series.astype(str):
        if 'Box' in m:
            return m.replace(' Box', '').strip()
    return 'Unknown'

def badge_class(install_type):
    t = install_type.upper()
    if 'DTR' in t: return 'badge-dtr'
    if '1' in t: return 'badge-1ph'
    if '3' in t: return 'badge-3ph'
    return 'badge-other'

# ─────────────────────────────────────────────
# HELPER: Build installation-level grouped dataframe
# KEY FIX: include InstallType in group key so DTR vs 1PH vs 3PH never collapse together.
# ─────────────────────────────────────────────
def build_install_groups(filtered_df, id_col, ss_col, box_col):
    """
    Returns a dataframe where each row = one complete installation.
    Columns: DateStr, id_col, Worker, InstallType, Cable_m, Lugs_qty, HasBox,
             [ss_col], [box_col], IDs (list of raw row IDs for delete/edit)
    """
    base_group_cols = ['DateStr', id_col, 'Worker']
    if ss_col: base_group_cols.append(ss_col)
    if box_col: base_group_cols.append(box_col)

    # Step 1 – derive InstallType per raw row from its Material field
    def row_install_type(mat):
        m = str(mat)
        if 'Box' in m:
            return m.replace(' Box', '').strip()
        return None  # Cable/Lugs rows don't carry the type — we'll forward-fill below

    # For each group, figure out type from the box row
    def agg_install(grp):
        mats = grp['Material'].astype(str)
        qty_map = {}
        for _, r in grp.iterrows():
            qty_map[str(r['Material']).strip()] = float(r['Qty']) if r['Qty'] != '' else 0.0

        install_type = extract_install_type(mats)
        cable = 0.0
        lugs = 0.0
        for mat, qty in qty_map.items():
            if mat.lower() == 'cable':
                cable = qty
            elif mat.lower() == 'lugs':
                lugs = qty

        return pd.Series({
            'InstallType': install_type,
            'Cable_m': cable,
            'Lugs_qty': lugs,
            'HasBox': any('Box' in m for m in mats),
            'IDs': grp['ID'].tolist(),
            # Store one representative row ID for single-record edits
            'BoxRowID': grp.loc[grp['Material'].astype(str).str.contains('Box'), 'ID'].iloc[0]
                        if any(grp['Material'].astype(str).str.contains('Box')) else grp['ID'].iloc[0],
        })

    grouped = (
        filtered_df
        .groupby(base_group_cols, sort=False)
        .apply(agg_install)
        .reset_index()
    )
    return grouped


# ─────────────────────────────────────────────
# RENDER: A single installation card (HTML)
# ─────────────────────────────────────────────
def render_install_card(row, id_col, ss_col, box_col):
    install_type = str(row['InstallType'])
    bc = badge_class(install_type)
    date_str = str(row['DateStr'])
    worker = str(row['Worker'])
    dtr_id = str(row[id_col])
    ss_val = str(row[ss_col]) if ss_col and ss_col in row.index and row[ss_col] else ""
    box_val = str(row[box_col]) if box_col and box_col in row.index and row[box_col] else ""
    cable = row['Cable_m']
    lugs = row['Lugs_qty']
    has_box = row['HasBox']

    sub_parts = []
    if ss_val: sub_parts.append(f"SS: {ss_val}")
    if box_val: sub_parts.append(f"Box: {box_val}")
    sub_line = "  ·  ".join(sub_parts) if sub_parts else ""

    cable_chip = f'<div class="mat-chip">🔌 Cable <span>{cable:.0f} m</span></div>' if cable > 0 else ''
    lugs_chip = f'<div class="mat-chip">🔩 Lugs <span>{lugs:.0f}</span></div>' if lugs > 0 else ''
    box_chip = f'<div class="mat-chip">📦 Box <span>✓</span></div>' if has_box else ''

    html = f"""
    <div class="install-card">
      <div class="card-meta">
        <span class="type-badge {bc}">{install_type}</span>
        📅 {date_str} &nbsp;·&nbsp; 👷 {worker}
      </div>
      <div class="card-id">{dtr_id}</div>
      {"<div class='card-sub'>" + sub_line + "</div>" if sub_line else ""}
      <div class="mat-row">
        {cable_chip}{lugs_chip}{box_chip}
      </div>
    </div>
    """
    return html


# ─────────────────────────────────────────────
# UI SETUP
# ─────────────────────────────────────────────
st.set_page_config(page_title="Site Supervisor", page_icon="👷", layout="centered")

c_head1, c_head2 = st.columns([1, 4])
with c_head1:
    if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, width=70)
    else: st.write("🏢")
with c_head2:
    st.title("Site Supervisor")

# --- TAB NAVIGATION ---
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
        s_name = c1.text_input("DTR SS No", placeholder="e.g. SS-101")
        s_code = c2.text_input("DTR Code", placeholder="e.g. DTR-101")

        s_lineman = st.text_input("Lineman Name", placeholder="e.g. Ramesh")

        st.markdown("###### Switch Present")
        c3, c4 = st.columns(2)
        s_lc = c3.checkbox("LC")
        s_ab = c4.checkbox("AB Switch")

        st.caption("Location Coordinates (Auto-filled if 'Capture GPS' is checked)")
        c_lat, c_long = st.columns(2)
        s_lat = c_lat.text_input("Latitude", value=auto_lat_surv)
        s_long = c_long.text_input("Longitude", value=auto_long_surv)

        if st.form_submit_button("🚀 Submit Survey", type="primary", use_container_width=True):
            if s_lc and s_ab:
                st.error("⚠️ Please select either LC or AB Switch, not both.")
            elif not s_name or not s_code:
                st.error("⚠️ DTR SS No and DTR Code are required.")
            else:
                switch_val = "LC" if s_lc else "AB Switch" if s_ab else "None"
                payload = {
                    "ID": str(uuid.uuid4()),
                    "Date": str(s_date),
                    "DTR Name": s_name,
                    "DTR Code": s_code,
                    "Latitude": s_lat,
                    "Longitude": s_long,
                    "LC/AB Switch": switch_val,
                    "Lineman Name": s_lineman,
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

        c1, c2, c3 = st.columns([1, 1, 1])
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
            w_ss_no = c6.text_input("DTR SS No")
            w_capacity = c7.text_input("Transformer Capacity (KVA)")
        else:
            c5.write("")

        # --- LOGIC: FETCH FROM SURVEY ---
        surv_lat, surv_lon = "", ""
        if w_main_id and not survey_data.empty and 'DTR Code' in survey_data.columns:
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

    t_survey_view, t_view_logs, t_gps, t_inv_view = st.tabs(
        ["📋 Survey Logs", "📋 Installation Logs", "📍 GPS Data", "📦 Inventory Logs"]
    )

    # ── 1. SURVEY LOGS VIEW ──
    with t_survey_view:
        if st.button("🔄 Refresh Data", key="ref_surv"): clear_cache(); st.rerun()

        if not survey_data.empty:
            if 'Date' in survey_data.columns:
                survey_data['Date'] = pd.to_datetime(survey_data['Date'], errors='coerce')

            st.markdown("###### Filters")
            cf1, cf2, cf3 = st.columns(3)
            surv_search = cf1.text_input("Search DTR Code / DTR SS No")
            surv_switch = cf2.selectbox("Switch Type", ["All", "LC", "AB Switch", "None"])
            surv_date = cf3.date_input("Date Range", [])

            filtered_surv = survey_data.copy()

            if surv_search:
                filtered_surv = filtered_surv[
                    filtered_surv['DTR Code'].astype(str).str.contains(surv_search, case=False, na=False) |
                    filtered_surv['DTR Name'].astype(str).str.contains(surv_search, case=False, na=False)
                ]
            if surv_switch != "All" and 'LC/AB Switch' in filtered_surv.columns:
                filtered_surv = filtered_surv[filtered_surv['LC/AB Switch'].astype(str).str.strip() == surv_switch]
            if len(surv_date) == 2:
                mask = (filtered_surv['Date'].dt.date >= surv_date[0]) & (filtered_surv['Date'].dt.date <= surv_date[1])
                filtered_surv = filtered_surv[mask]

            if not filtered_surv.empty:
                filtered_surv['Date'] = filtered_surv['Date'].dt.strftime('%Y-%m-%d')
                display_cols = [c for c in filtered_surv.columns if c not in ["Synced"]]

                display_df = filtered_surv[display_cols].rename(columns={'DTR Name': 'DTR SS No'})
                evt_surv = st.dataframe(display_df, on_select="rerun", selection_mode="multi-row", use_container_width=True)

                if evt_surv.selection.rows:
                    selected_surv_df = filtered_surv.iloc[evt_surv.selection.rows]

                    st.markdown("### ⚡ Actions for Selected Records")
                    ca1, ca2, ca3 = st.columns(3)
                    with ca1:
                        if st.button(f"🗑️ Delete {len(selected_surv_df)} Logs", key="del_surv"):
                            if bulk_delete_rows("SurveyLogs", selected_surv_df['ID'].tolist()): st.rerun()
                    with ca2:
                        msg = "*Survey Details*\n"
                        for _, r in selected_surv_df.iterrows():
                            lat = r.get('Latitude', '')
                            lon = r.get('Longitude', '')
                            loc_link = f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "No GPS recorded."
                            msg += f"\n➖ DTR SS No: {r['DTR Name']}\nDTR Code: {r['DTR Code']}\nSwitch Type: {r.get('LC/AB Switch', 'None')}\nLineman: {r.get('Lineman Name', 'N/A')}\nLocation: {loc_link}\n"
                        encoded_msg = urllib.parse.quote(msg)
                        st.link_button("📱 Share via WhatsApp", f"https://wa.me/?text={encoded_msg}")
                    with ca3:
                        if FPDF:
                            pdf_data = generate_survey_pdf(selected_surv_df)
                            st.download_button("⬇️ Download PDF", data=pdf_data, file_name="Selected_Survey_Logs.pdf", mime="application/pdf")
                        else:
                            st.warning("PDF generator not installed.")

                st.markdown("---")

                # SINGLE EDIT OPTION
                st.write("### ✏️ Edit Single Record")
                filtered_surv['label'] = (filtered_surv['Date'].astype(str) + " | " +
                                          filtered_surv['DTR Code'].astype(str) + " (" +
                                          filtered_surv['DTR Name'].astype(str) + ")")
                edit_sel_surv = st.selectbox("Select Record", [""] + filtered_surv['label'].tolist(), key="edit_sel_surv")

                if edit_sel_surv:
                    sel_row = filtered_surv[filtered_surv['label'] == edit_sel_surv].iloc[0]
                    with st.form("edit_surv_form"):
                        st.caption(f"Editing ID: {sel_row['ID']}")
                        n_date = st.text_input("Date", value=sel_row['Date'])
                        n_name = st.text_input("DTR SS No", value=sel_row['DTR Name'])
                        n_code = st.text_input("DTR Code", value=sel_row['DTR Code'])

                        curr_switch = str(sel_row.get('LC/AB Switch', 'None')).strip()
                        st.markdown("###### Switch Present")
                        c_edit_s1, c_edit_s2 = st.columns(2)
                        n_lc = c_edit_s1.checkbox("LC", value=(curr_switch == 'LC'))
                        n_ab = c_edit_s2.checkbox("AB Switch", value=(curr_switch == 'AB Switch'))

                        n_lineman = st.text_input("Lineman Name", value=sel_row.get('Lineman Name', ''))
                        n_lat = st.text_input("Latitude", value=sel_row.get('Latitude', ''))
                        n_lon = st.text_input("Longitude", value=sel_row.get('Longitude', ''))

                        if st.form_submit_button("💾 Save Changes"):
                            if n_lc and n_ab:
                                st.error("⚠️ Please select either LC or AB Switch, not both.")
                            else:
                                switch_val = "LC" if n_lc else "AB Switch" if n_ab else "None"
                                u_data = {
                                    "Date": n_date,
                                    "DTR Name": n_name,
                                    "DTR Code": n_code,
                                    "Latitude": n_lat,
                                    "Longitude": n_lon,
                                    "LC/AB Switch": switch_val,
                                    "Lineman Name": n_lineman,
                                    "Synced": "FALSE"
                                }
                                if update_row_data("SurveyLogs", sel_row['ID'], u_data):
                                    st.success("Updated!"); time.sleep(1); st.rerun()
            else:
                st.info("No logs match filters.")
        else:
            st.info("No Survey Logs available.")

    # ── 2. INSTALLATION LOGS VIEW ── (REDESIGNED) ──
    with t_view_logs:
        col_ref, col_title = st.columns([1, 4])
        with col_ref:
            if st.button("🔄 Refresh", key="ref_wl"): clear_cache(); st.rerun()

        df = get_data("WorkLogs")

        if not df.empty:
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

            # ── FILTERS ──
            with st.expander("🔍 Filters", expanded=False):
                fc1, fc2 = st.columns(2)
                avail_sites = ["All"] + sorted(df['Site'].dropna().unique().tolist())
                sel_loc = fc1.selectbox("Site", avail_sites, key="wl_loc")
                avail_workers = ["All"] + sorted(df['Worker'].dropna().unique().tolist())
                sel_worker = fc2.selectbox("Worker", avail_workers, key="wl_worker")

                fc3, fc4 = st.columns(2)
                sel_dtr = fc3.text_input("DTR Code / SC No", key="wl_dtr")
                sel_mat = fc4.text_input("Material / Type", placeholder="e.g. Cable, DTR", key="wl_mat")

                fc5, fc6, fc7 = st.columns(3)
                sel_box = fc5.text_input("DTR Box No", key="wl_box")
                sel_ss = fc6.text_input("DTR SS No", key="wl_ss")
                sel_date = fc7.date_input("Date Range", [], key="wl_date")

            id_col = 'SC No/ DTR Code' if 'SC No/ DTR Code' in df.columns else df.columns[2]
            ss_col = 'Transformer_SS_No' if 'Transformer_SS_No' in df.columns else None
            box_col = 'DTR_Box_No' if 'DTR_Box_No' in df.columns else None

            # Apply filters
            filtered_df = df.copy()
            if sel_loc != "All":
                filtered_df = filtered_df[filtered_df['Site'] == sel_loc]
            if sel_worker != "All":
                filtered_df = filtered_df[filtered_df['Worker'] == sel_worker]
            if len(sel_date) == 2:
                mask = (filtered_df['Date'].dt.date >= sel_date[0]) & (filtered_df['Date'].dt.date <= sel_date[1])
                filtered_df = filtered_df[mask]
            if sel_mat:
                filtered_df = filtered_df[
                    filtered_df['Material'].astype(str).str.contains(sel_mat, case=False, na=False)
                ]
            if sel_dtr:
                filtered_df = filtered_df[
                    filtered_df[id_col].astype(str).str.contains(sel_dtr, case=False, na=False)
                ]
            if sel_box and box_col and box_col in filtered_df.columns:
                filtered_df = filtered_df[
                    filtered_df[box_col].astype(str).str.contains(sel_box, case=False, na=False)
                ]
            if sel_ss and ss_col and ss_col in filtered_df.columns:
                filtered_df = filtered_df[
                    filtered_df[ss_col].astype(str).str.contains(sel_ss, case=False, na=False)
                ]

            if filtered_df.empty:
                st.info("No logs found matching filters.")
            else:
                filtered_df['DateStr'] = filtered_df['Date'].dt.strftime('%d %b %Y')
                filtered_df[id_col] = filtered_df[id_col].astype(str)
                filtered_df['Worker'] = filtered_df['Worker'].astype(str)
                if ss_col and ss_col in filtered_df.columns:
                    filtered_df[ss_col] = filtered_df[ss_col].fillna("").astype(str)
                if box_col and box_col in filtered_df.columns:
                    filtered_df[box_col] = filtered_df[box_col].fillna("").astype(str)

                # ── BUILD INSTALLATION-LEVEL GROUPS ──
                # FIX: Each (Date, DTR Code, Worker, [SS], [BoxNo]) combination that shares
                # the same installation type (from the Box material name) is ONE installation row.
                grouped = build_install_groups(filtered_df, id_col, ss_col, box_col)

                # ── SUMMARY METRICS ──
                total_inst = len(grouped)
                total_cable = grouped['Cable_m'].sum()
                total_lugs = grouped['Lugs_qty'].sum()
                type_counts = grouped['InstallType'].value_counts().to_dict()

                m1, m2, m3 = st.columns(3)
                m1.metric("📦 Installations", total_inst)
                m2.metric("🔌 Cable (m)", f"{total_cable:.0f}")
                m3.metric("🔩 Lugs", f"{total_lugs:.0f}")

                if type_counts:
                    type_pills = "  ".join(
                        f"`{t}: {c}`" for t, c in type_counts.items()
                    )
                    st.caption(f"Breakdown — {type_pills}")

                st.markdown("---")

                # ── INSTALLATION CARDS ──
                # Session state for which card's edit panel is open
                if 'wl_edit_open' not in st.session_state:
                    st.session_state['wl_edit_open'] = None
                if 'wl_delete_confirm' not in st.session_state:
                    st.session_state['wl_delete_confirm'] = None

                for idx, row in grouped.iterrows():
                    card_key = f"card_{idx}"

                    # Render the card HTML
                    st.markdown(render_install_card(row, id_col, ss_col, box_col), unsafe_allow_html=True)

                    # Action buttons under each card (outside HTML so Streamlit handles clicks)
                    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 4])

                    with btn_col1:
                        edit_label = "✏️ Edit" if st.session_state['wl_edit_open'] != card_key else "✖ Close"
                        if st.button(edit_label, key=f"edit_btn_{idx}", use_container_width=True):
                            st.session_state['wl_edit_open'] = (
                                None if st.session_state['wl_edit_open'] == card_key else card_key
                            )
                            st.session_state['wl_delete_confirm'] = None
                            st.rerun()

                    with btn_col2:
                        if st.session_state['wl_delete_confirm'] == card_key:
                            if st.button("⚠️ Confirm", key=f"del_confirm_{idx}", use_container_width=True):
                                if bulk_delete_rows("WorkLogs", row['IDs']):
                                    st.session_state['wl_delete_confirm'] = None
                                    st.rerun()
                        else:
                            if st.button("🗑️ Delete", key=f"del_btn_{idx}", use_container_width=True):
                                st.session_state['wl_delete_confirm'] = card_key
                                st.session_state['wl_edit_open'] = None
                                st.rerun()

                    # ── INLINE EDIT PANEL ──
                    if st.session_state['wl_edit_open'] == card_key:
                        # Find all raw rows belonging to this installation group
                        install_raw = filtered_df[filtered_df['ID'].isin(row['IDs'])]

                        # ── Edit the installation metadata (applies to all rows in the group) ──
                        with st.form(f"edit_install_form_{idx}"):
                            st.markdown("**✏️ Edit Installation**")
                            st.caption("Changes apply to all material rows for this installation.")

                            ei1, ei2 = st.columns(2)
                            n_date = ei1.text_input("Date", value=str(row['DateStr']))
                            n_dtr = ei2.text_input("DTR Code / SC No", value=str(row[id_col]))

                            ei3, ei4 = st.columns(2)
                            n_ss = ei3.text_input(
                                "DTR SS No",
                                value=str(row[ss_col]) if ss_col and ss_col in row.index else ""
                            )
                            n_box = ei4.text_input(
                                "DTR Box No",
                                value=str(row[box_col]) if box_col and box_col in row.index else ""
                            )

                            w_idx = workers.index(row['Worker']) if row['Worker'] in workers else 0
                            n_worker = st.selectbox("Worker", workers, index=w_idx)

                            st.markdown("**Materials**")
                            em1, em2 = st.columns(2)
                            # Pre-fill from aggregated values
                            n_cable = em1.number_input("Cable (m)", value=float(row['Cable_m']), min_value=0.0, step=1.0)
                            n_lugs = em2.number_input("Lugs (Qty)", value=float(row['Lugs_qty']), min_value=0.0, step=1.0)

                            if st.form_submit_button("💾 Save Changes", use_container_width=True):
                                success = True
                                for _, raw_row in install_raw.iterrows():
                                    mat = str(raw_row['Material']).strip()
                                    if mat == 'Cable':
                                        qty_val = n_cable
                                    elif mat == 'Lugs':
                                        qty_val = n_lugs
                                    else:
                                        qty_val = float(raw_row['Qty'])  # Box qty stays 1

                                    u_data = {
                                        id_col: n_dtr,
                                        "Transformer_SS_No": n_ss,
                                        "DTR_Box_No": n_box,
                                        "Worker": n_worker,
                                        "Qty": qty_val,
                                        "Synced": "FALSE"
                                    }
                                    if not update_row_data("WorkLogs", raw_row['ID'], u_data):
                                        success = False
                                if success:
                                    st.session_state['wl_edit_open'] = None
                                    st.success("✅ Updated!")
                                    time.sleep(0.8)
                                    st.rerun()

                    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

                # ── BULK DELETE VIA TABLE ──
                st.markdown("---")
                with st.expander("🗂️ Bulk Select & Delete"):
                    st.caption("Select multiple installations to delete together.")
                    # Show a compact table for bulk selection
                    bulk_display = grouped[[id_col, 'DateStr', 'Worker', 'InstallType', 'Cable_m', 'Lugs_qty']].copy()
                    bulk_display.columns = ['DTR/SC No', 'Date', 'Worker', 'Type', 'Cable (m)', 'Lugs']
                    evt_bulk = st.dataframe(
                        bulk_display,
                        on_select="rerun",
                        selection_mode="multi-row",
                        use_container_width=True,
                        height=300
                    )
                    if evt_bulk.selection.rows:
                        sel_ids_flat = []
                        for i in evt_bulk.selection.rows:
                            sel_ids_flat.extend(grouped.iloc[i]['IDs'])
                        n_sel = len(evt_bulk.selection.rows)
                        if st.button(f"🗑️ Delete {n_sel} Selected Installation(s)", type="primary"):
                            if bulk_delete_rows("WorkLogs", sel_ids_flat):
                                st.success(f"Deleted {n_sel} installation(s).")
                                time.sleep(0.8)
                                st.rerun()
        else:
            st.info("No work logs available.")

    # ── 3. GPS DATA LOG ──
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

    # ── 4. INVENTORY LOGS ──
    with t_inv_view:
        df_inv = get_data("Inventory")
        if not df_inv.empty:
            st.dataframe(df_inv, use_container_width=True)

            st.markdown("---")
            st.write("### ✏️ Edit or Delete Inventory Record")
            df_inv['label'] = (df_inv['Date'].astype(str) + " | " +
                               df_inv['Material'] + " (" + df_inv['Qty'].astype(str) + ")")
            edit_sel = st.selectbox("Select Record", [""] + df_inv['label'].tolist())

            if edit_sel:
                sel_row = df_inv[df_inv['label'] == edit_sel].iloc[0]

                with st.form("edit_inv_form"):
                    n_date = st.text_input("Date", value=sel_row['Date'])
                    n_mat = st.selectbox(
                        "Material",
                        materials_list,
                        index=materials_list.index(sel_row['Material']) if sel_row['Material'] in materials_list else 0
                    )
                    n_qty = st.number_input("Qty", value=float(sel_row['Qty']))

                    if st.form_submit_button("💾 Save Changes"):
                        u_data = {"Date": n_date, "Material": n_mat, "Qty": n_qty, "Synced": "FALSE"}
                        if update_row_data("Inventory", sel_row['ID'], u_data):
                            st.success("Updated!"); time.sleep(1); st.rerun()

                if st.button("🗑️ Delete Record", type="secondary"):
                    if bulk_delete_rows("Inventory", [sel_row['ID']]):
                        st.success("Deleted!"); time.sleep(1); st.rerun()

# --- TAB 3: INVENTORY (Add Stock) ---
with tabs[3]:
    st.subheader("📊 Stock Overview")
    if current_stock:
        sorted_stock = sorted(current_stock.items(), key=lambda x: x[1])
        cols = st.columns(3)
        for i, (item, qty) in enumerate(sorted_stock):
            color = "normal" if qty >= 10 else "inverse"
            with cols[i % 3]:
                st.metric(label=item, value=f"{qty:,.0f}", delta="Low" if qty < 10 else None, delta_color=color)
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
        edited = st.data_editor(
            df_workers,
            use_container_width=True,
            num_rows="dynamic",
            key="w_edit",
            column_config={"Synced": st.column_config.Column(disabled=True)}
        )
        if st.button("💾 Save List"):
            update_worker_registry(edited)
            st.rerun()
