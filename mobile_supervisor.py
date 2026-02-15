import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
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
        st.error(f"🚨 Connection Error: {e}")
        st.stop()

# --- DATA HELPERS ---
@st.cache_data(ttl=60)
def get_data(worksheet):
    """Cached data fetching with 60 second TTL"""
    client = get_connection()
    try:
        ws = client.open(SHEET_NAME).worksheet(worksheet)
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except: 
        return pd.DataFrame()

def save_batch_rows(worksheet, rows_list):
    """Saves multiple rows at once"""
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    ws.append_rows(rows_list)
    get_data.clear()  # Clear cache

def save_row(worksheet, row_dict):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    headers = ws.row_values(1)
    row_values = [row_dict.get(h, "") for h in headers]
    ws.append_row(row_values)
    get_data.clear()  # Clear cache

def delete_row(worksheet, row_id):
    client = get_connection()
    ws = client.open(SHEET_NAME).worksheet(worksheet)
    try:
        cell = ws.find(str(row_id))
        ws.delete_rows(cell.row)
        get_data.clear()  # Clear cache
        return True
    except: 
        return False

@st.cache_data(ttl=300)
def get_settings_lists():
    """Fetches Sites, Meter Types, and Materials from Settings Tab"""
    df = get_data("Settings")
    if not df.empty:
        sites = df['Site_List'].dropna().unique().tolist()
        meter_types = df['Meter_Type_List'].dropna().unique().tolist()
        materials = df['Material_Master'].dropna().unique().tolist()
        return [x for x in sites if x], [x for x in meter_types if x], [x for x in materials if x]
    return ["Default Site"], ["1 Phase", "3 Phase"], ["Cable", "Lugs"]

@st.cache_data(ttl=300)
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

def get_summary_stats():
    """Calculate dashboard statistics"""
    df_work = get_data("WorkLogs")
    
    stats = {
        "today_installations": 0,
        "week_installations": 0,
        "month_installations": 0,
        "total_installations": 0,
        "today_workers": set(),
        "active_sites": set()
    }
    
    if not df_work.empty:
        df_work['Date'] = pd.to_datetime(df_work['Date'], errors='coerce')
        today = pd.Timestamp(datetime.today().date())
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        # Count unique DTR installations
        installations = df_work.groupby(['Date', 'DTR Code']).first().reset_index()
        
        stats["today_installations"] = len(installations[installations['Date'] == today])
        stats["week_installations"] = len(installations[installations['Date'] >= week_ago])
        stats["month_installations"] = len(installations[installations['Date'] >= month_ago])
        stats["total_installations"] = len(installations)
        
        # Worker stats
        today_work = df_work[df_work['Date'] == today]
        stats["today_workers"] = set(today_work['Worker'].unique()) if not today_work.empty else set()
        stats["active_sites"] = set(df_work['Site'].unique()) if 'Site' in df_work.columns else set()
    
    return stats

def get_low_stock_alerts(stock, thresholds={'Cable': 100, 'Lugs': 50, 'Box': 5}):
    """Generate low stock alerts"""
    alerts = []
    for material, qty in stock.items():
        for key, threshold in thresholds.items():
            if key in material and qty < threshold:
                alerts.append(f"⚠️ **{material}** is low: {qty:.0f} units (threshold: {threshold})")
    return alerts

# --- UI SETUP ---
st.set_page_config(
    page_title="Site Supervisor", 
    page_icon="👷", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS for mobile optimization
st.markdown("""
<style>
    /* Mobile-first responsive design */
    .stButton>button {
        width: 100%;
        height: 55px;
        font-size: 18px;
        font-weight: 600;
        border-radius: 10px;
        margin: 8px 0;
    }
    
    /* Form inputs - larger touch targets */
    .stTextInput>div>div>input, 
    .stNumberInput>div>div>input {
        height: 55px;
        font-size: 18px;
        border-radius: 8px;
    }
    
    .stSelectbox>div>div>select,
    .stDateInput>div>div>input {
        height: 55px;
        font-size: 18px;
        border-radius: 8px;
    }
    
    /* Better spacing for mobile */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 3rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* Larger metrics for dashboard */
    [data-testid="stMetricValue"] {
        font-size: 32px;
        font-weight: 700;
    }
    
    [data-testid="stMetricLabel"] {
        font-size: 14px;
        font-weight: 500;
    }
    
    /* Touch-friendly tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 55px;
        padding-top: 12px;
        font-size: 15px;
        font-weight: 600;
    }
    
    /* Compact dataframes */
    .dataframe {
        font-size: 13px;
    }
    
    /* Alert styling */
    .stAlert {
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
    }
    
    /* Divider styling */
    hr {
        margin: 20px 0;
    }
    
    /* Expander headers */
    .streamlit-expanderHeader {
        font-size: 16px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state for confirmations
if 'confirm_delete' not in st.session_state:
    st.session_state.confirm_delete = None
if 'delete_type' not in st.session_state:
    st.session_state.delete_type = None

# Header with refresh
col1, col2 = st.columns([4, 1])
with col1:
    st.title("👷 Site Supervisor")
with col2:
    if st.button("🔄"):
        get_data.clear()
        get_settings_lists.clear()
        get_worker_list.clear()
        st.rerun()

# Load Settings
sites_list, meter_types_list, materials_list = get_settings_lists()
workers = get_worker_list()
current_stock = calculate_stock()

# --- TABS ---
tabs = st.tabs(["📊 Home", "⚡ Log Work", "📦 Stock", "👥 Team", "📋 Records"])

# ==================== TAB 1: DASHBOARD ====================
with tabs[0]:
    st.subheader("📊 Today's Overview")
    
    stats = get_summary_stats()
    
    # Installation Stats - 2 column layout only
    col1, col2 = st.columns(2)
    col1.metric("Today", stats["today_installations"], help="Installations completed today")
    col2.metric("This Week", stats["week_installations"], help="Last 7 days")
    
    col3, col4 = st.columns(2)
    col3.metric("This Month", stats["month_installations"], help="Last 30 days")
    col4.metric("Total Jobs", stats["total_installations"], help="All time")
    
    # Active workers today
    if stats["today_workers"]:
        st.info(f"👷 **Active Today:** {', '.join(stats['today_workers'])}")
    
    st.divider()
    
    # Stock Status with Alerts
    st.subheader("📦 Stock Status")
    
    # Check for low stock
    alerts = get_low_stock_alerts(current_stock)
    if alerts:
        st.warning("**Low Stock Alerts**")
        for alert in alerts:
            st.markdown(alert)
        st.divider()
    
    # Display stock in organized manner (single column for mobile)
    if current_stock:
        # Group materials
        cables = {k: v for k, v in current_stock.items() if 'Cable' in k or 'Wire' in k}
        boxes = {k: v for k, v in current_stock.items() if 'Box' in k}
        other = {k: v for k, v in current_stock.items() if k not in cables and k not in boxes}
        
        if cables:
            st.markdown("**🔌 Cables & Wires**")
            for material, qty in cables.items():
                color = "🟢" if qty > 50 else "🟡" if qty > 20 else "🔴"
                st.markdown(f"{color} **{material}:** {qty:,.1f} units")
            st.write("")
        
        if boxes:
            st.markdown("**📦 Meter Boxes**")
            for material, qty in boxes.items():
                color = "🟢" if qty > 10 else "🟡" if qty > 5 else "🔴"
                st.markdown(f"{color} **{material}:** {qty:,.0f} units")
            st.write("")
        
        if other:
            st.markdown("**🔧 Other Materials**")
            for material, qty in other.items():
                color = "🟢" if qty > 20 else "🟡" if qty > 10 else "🔴"
                st.markdown(f"{color} **{material}:** {qty:,.1f} units")
    else:
        st.info("No stock data available")
    
    st.divider()
    
    # Recent Activity
    st.subheader("📝 Recent Installations")
    df_work = get_data("WorkLogs")
    if not df_work.empty:
        df_work['Date'] = pd.to_datetime(df_work['Date'], errors='coerce')
        # Group by DTR to get unique installations
        recent = df_work.sort_values('Date', ascending=False).groupby('DTR Code').first().reset_index()
        recent = recent.head(5)[['Date', 'DTR Code', 'Site', 'Worker']]
        recent['Date'] = recent['Date'].dt.strftime('%d-%b-%y')
        st.dataframe(recent, hide_index=True, use_container_width=True)
    else:
        st.info("No work logs yet")

# ==================== TAB 2: WORK LOG (MOBILE OPTIMIZED) ====================
with tabs[1]:
    st.subheader("⚡ Log Installation")
    
    # Collapsible stock check
    with st.expander("📦 Quick Stock Check", expanded=False):
        for material, qty in sorted(current_stock.items()):
            color = "🟢" if qty > 20 else "🟡" if qty > 10 else "🔴"
            st.markdown(f"{color} **{material}:** {qty:,.1f}")
    
    with st.form("work_log", clear_on_submit=True):
        st.markdown("### 📅 Basic Info")
        
        # Single column layout for mobile
        w_date = st.date_input("Date", datetime.today(), key="wl_date")
        w_site = st.selectbox("Site Name", sites_list, key="wl_site", help="Select site location")
        w_dtr = st.text_input("DTR Code / ID", key="wl_dtr", placeholder="e.g., DTR-001", help="Unique DTR identifier")
        w_worker = st.selectbox("Worker Assigned", workers, key="wl_worker")
        
        st.divider()
        st.markdown("### ⚡ Meter Installation")
        
        w_meter_type = st.selectbox("Meter Type", meter_types_list, key="wl_meter", help="Meter box type will be auto-deducted")
        
        # Show what will be deducted
        box_name = f"{w_meter_type} Box"
        st.info(f"✅ **Auto-Deduct:** 1x {box_name}")
        
        st.divider()
        st.markdown("### 🔧 Additional Materials")
        
        # Single column for mobile
        qty_cable = st.number_input("Cable Used (Meters)", min_value=0.0, step=1.0, key="wl_cable")
        qty_lugs = st.number_input("Lugs Used (Qty)", min_value=0.0, step=1.0, key="wl_lugs")
        
        # Large submit button
        submitted = st.form_submit_button("🚀 Submit Installation Log", use_container_width=True)
        
        if submitted:
            if not w_dtr:
                st.error("⚠️ Please enter DTR Code")
            else:
                # Prepare batch data
                batch_rows = []
                base_row = [str(w_date), w_dtr, w_site, w_worker]
                
                # Auto-deduct meter box
                batch_rows.append([str(uuid.uuid4())] + base_row + [box_name, 1, "FALSE"])
                
                # Deduct cable if used
                if qty_cable > 0:
                    batch_rows.append([str(uuid.uuid4())] + base_row + ["Cable", qty_cable, "FALSE"])
                
                # Deduct lugs if used
                if qty_lugs > 0:
                    batch_rows.append([str(uuid.uuid4())] + base_row + ["Lugs", qty_lugs, "FALSE"])
                
                # Save to sheet
                try:
                    save_batch_rows("WorkLogs", batch_rows)
                    st.success(f"✅ Saved! Deducted: 1x {box_name}, {qty_cable}m Cable, {qty_lugs} Lugs")
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Save Failed: {e}")

# ==================== TAB 3: INVENTORY ====================
with tabs[2]:
    st.subheader("📦 Add New Stock")
    
    # Show current stock summary
    with st.expander("📊 Current Stock Levels", expanded=False):
        for material, qty in sorted(current_stock.items()):
            st.markdown(f"**{material}:** {qty:,.1f} units")
    
    with st.form("inv_form", clear_on_submit=True):
        st.markdown("### 📥 Inward Material Entry")
        
        i_date = st.date_input("Received Date", datetime.today(), key="inv_date")
        i_mat = st.selectbox("Material Type", materials_list, key="inv_mat")
        i_qty = st.number_input("Quantity Received", min_value=0.0, step=1.0, key="inv_qty", help="Enter quantity in standard units")
        
        submitted = st.form_submit_button("📥 Add to Stock", use_container_width=True)
        
        if submitted:
            if i_qty <= 0:
                st.error("⚠️ Please enter a valid quantity")
            else:
                payload = {
                    "ID": str(uuid.uuid4()),
                    "Date": str(i_date),
                    "Material": i_mat,
                    "Qty": i_qty,
                    "Type": "Inward",
                    "Synced": "FALSE"
                }
                try:
                    save_row("Inventory", payload)
                    st.success(f"✅ Added {i_qty} units of {i_mat}")
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed: {e}")

# ==================== TAB 4: WORKERS ====================
with tabs[3]:
    st.subheader("👥 Team Management")
    
    # Show current workers
    st.markdown("### Current Team Members")
    if workers:
        for i, worker in enumerate(workers, 1):
            st.markdown(f"{i}. **{worker}**")
    else:
        st.info("No workers added yet")
    
    st.divider()
    
    # Add new worker
    st.markdown("### ➕ Add New Worker")
    new_w = st.text_input("Worker Name", placeholder="Enter full name", key="new_worker")
    
    if st.button("➕ Add Worker", use_container_width=True):
        if not new_w:
            st.error("⚠️ Please enter a name")
        elif new_w in workers:
            st.warning("⚠️ Worker already exists")
        else:
            try:
                save_row("Workers", {"Name": new_w, "Synced": "FALSE"})
                st.success(f"✅ Added {new_w} to team")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Failed: {e}")

# ==================== TAB 5: VIEW RECORDS ====================
with tabs[4]:
    st.subheader("📋 Data Records")
    
    view_mode = st.radio(
        "Select Records", 
        ["Work Logs", "Inventory Logs"], 
        horizontal=True,
        label_visibility="collapsed"
    )
    
    st.divider()
    
    # ===== WORK LOGS =====
    if view_mode == "Work Logs":
        df = get_data("WorkLogs")
        
        if not df.empty:
            # Filters in expander (mobile-friendly)
            with st.expander("🔍 Filter Options", expanded=False):
                f_worker = st.multiselect("Worker", df['Worker'].unique(), key="f_worker")
                f_site = st.multiselect("Site", df['Site'].unique(), key="f_site")
                f_material = st.multiselect("Material", df['Material'].unique(), key="f_material")
                f_search = st.text_input("Search DTR Code", key="f_search")
                
                # Apply filters
                if f_worker:
                    df = df[df['Worker'].isin(f_worker)]
                if f_site:
                    df = df[df['Site'].isin(f_site)]
                if f_material:
                    df = df[df['Material'].isin(f_material)]
                if f_search:
                    df = df[df['DTR Code'].astype(str).str.contains(f_search, case=False, na=False)]
            
            st.caption(f"Showing {len(df)} records")
            
            # Display table with horizontal scroll
            st.dataframe(
                df[['Date', 'DTR Code', 'Site', 'Worker', 'Material', 'Qty']], 
                hide_index=True, 
                use_container_width=True
            )
            
            st.divider()
            
            # IMPROVED DELETE - Select from dropdown instead of copy-paste
            st.markdown("### 🗑️ Delete Record")
            
            if len(df) > 0:
                # Create readable options
                df['display'] = df.apply(
                    lambda x: f"{x['Date']} | {x['DTR Code']} | {x['Material']} | {x['Qty']}", 
                    axis=1
                )
                
                selected_display = st.selectbox(
                    "Select record to delete",
                    options=df['display'].tolist(),
                    key="del_select_work"
                )
                
                if selected_display:
                    # Get the ID for selected record
                    selected_id = df[df['display'] == selected_display]['ID'].iloc[0]
                    
                    col1, col2 = st.columns([1, 1])
                    
                    with col1:
                        if st.button("🗑️ Delete", use_container_width=True, type="secondary"):
                            st.session_state.confirm_delete = selected_id
                            st.session_state.delete_type = "WorkLogs"
                    
                    with col2:
                        if st.session_state.confirm_delete == selected_id:
                            if st.button("✅ Confirm", use_container_width=True, type="primary"):
                                if delete_row("WorkLogs", selected_id):
                                    st.success("✅ Deleted!")
                                    st.session_state.confirm_delete = None
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Delete failed")
        else:
            st.info("📭 No work logs found")
    
    # ===== INVENTORY LOGS =====
    elif view_mode == "Inventory Logs":
        df = get_data("Inventory")
        
        if not df.empty:
            with st.expander("🔍 Filter Options", expanded=False):
                f_mat_inv = st.multiselect("Material", df['Material'].unique(), key="f_mat_inv")
                
                if f_mat_inv:
                    df = df[df['Material'].isin(f_mat_inv)]
            
            st.caption(f"Showing {len(df)} records")
            
            st.dataframe(
                df[['Date', 'Material', 'Qty', 'Type']], 
                hide_index=True, 
                use_container_width=True
            )
            
            st.divider()
            
            # IMPROVED DELETE for Inventory
            st.markdown("### 🗑️ Delete Record")
            
            if len(df) > 0:
                df['display'] = df.apply(
                    lambda x: f"{x['Date']} | {x['Material']} | {x['Qty']} | {x['Type']}", 
                    axis=1
                )
                
                selected_display_inv = st.selectbox(
                    "Select record to delete",
                    options=df['display'].tolist(),
                    key="del_select_inv"
                )
                
                if selected_display_inv:
                    selected_id_inv = df[df['display'] == selected_display_inv]['ID'].iloc[0]
                    
                    col1, col2 = st.columns([1, 1])
                    
                    with col1:
                        if st.button("🗑️ Delete", use_container_width=True, type="secondary", key="del_inv_btn"):
                            st.session_state.confirm_delete = selected_id_inv
                            st.session_state.delete_type = "Inventory"
                    
                    with col2:
                        if st.session_state.confirm_delete == selected_id_inv:
                            if st.button("✅ Confirm", use_container_width=True, type="primary", key="confirm_inv_btn"):
                                if delete_row("Inventory", selected_id_inv):
                                    st.success("✅ Deleted!")
                                    st.session_state.confirm_delete = None
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Delete failed")
        else:
            st.info("📭 No inventory logs found")

# Footer
st.divider()
st.caption("👷 Site Supervisor App v2.0 | Mobile Optimized")
