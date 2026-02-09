import streamlit as st
import pandas as pd
import re
import math
from src.utils.export import generate_excel_bom

# --- 1. CONFIG & STYLING (DARK MODE ENGINEERING) ---
st.set_page_config(page_title="IronCAL Commander", layout="wide", page_icon="assets/favicon.png")

# CSS Styling for Modern Dark Theme
st.markdown("""
<style>
    /* Global Dark Theme */
    .stApp {
        background-color: #1E1E1E;
        color: #FFFFFF;
    }
    
    /* Input Text Area Styling */
    .stTextArea textarea {
        background-color: #252525 !important;
        color: #FFFFFF !important;
        font-family: 'Courier New', Courier, monospace !important;
        border: 1px solid #444;
    }
    
    /* Custom Buttons (Toolbar) */
    div.stButton > button {
        background-color: #2D2D2D;
        color: white;
        border-radius: 50%;
        height: 50px;
        width: 50px;
        border: 1px solid #444;
        font-weight: bold;
        transition: all 0.3s;
    }
    div.stButton > button:hover {
        background-color: #2D8CFF; /* Electric Blue */
        border-color: #2D8CFF;
        box-shadow: 0 0 10px rgba(45, 140, 255, 0.5);
    }
    
    /* Metrics Cards */
    div[data-testid="stMetricValue"] {
        color: #2D8CFF !important;
    }
    
    /* Table Styling */
    div[data-testid="stDataFrame"] {
        background-color: #2D2D2D;
    }
    
    /* Remove default header/footer */
    header {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- 2. CONSTANTS (ISRAELI STANDARD 4466) ---
BAR_WEIGHTS = {
    6: 0.222, 8: 0.395, 10: 0.617, 12: 0.888, 
    14: 1.210, 16: 1.580, 18: 2.000, 20: 2.470, 25: 3.850, 32: 6.310
}

MESH_CATALOG = {
    # Common mappings (User input -> Weight per sheet)
    'Q131': 33.5, 'w6@20': 33.5, '#6@20': 33.5,
    'Q188': 48.0, 'w6@15': 48.0, '#6@15': 48.0,
    'Q257': 65.5, 'w8@20': 65.5, '#8@20': 65.5,
    'Q335': 85.5, 'w8@15': 85.5, '#8@15': 85.5,
    'Q503': 128.0,'w8@10': 128.0,'#8@10': 128.0
}

# --- 3. PARSING LOGIC (THE BRAIN) ---
def parse_line(line):
    line = line.strip().upper()
    if not line:
        return None

    # Logic 1: MESH / NET (Starts with # or w/W)
    # Regex looks for patterns like #8@20 or w8@20
    mesh_match = re.search(r'^[#Ww].*', line)
    if mesh_match:
        # Try to match spacing logic like w8@20
        clean_key = line.replace(' ', '') # remove spaces
        # Try to find mapped weight
        # 1. Direct match
        if clean_key in MESH_CATALOG:
             return {'Type': 'Mesh', 'Desc': clean_key, 'Qty': 1, 'Total Weight': MESH_CATALOG[clean_key]}
        
        # 2. Extract dia and spacing manually for custom mesh (fallback)
        mesh_parse = re.search(r'[Ww#](\d+)@(\d+)', clean_key)
        if mesh_parse:
            dia, space = mesh_parse.groups()
            key_recon = f"w{dia}@{space}"
            if key_recon in MESH_CATALOG:
                return {'Type': 'Mesh', 'Desc': key_recon, 'Qty': 1, 'Total Weight': MESH_CATALOG[key_recon]}
        return None

    # Logic 2: COMPLEX REBAR (Spacing & Multipliers)
    # Pattern: [Multiplier] [Phi/d] [w-noise] [Dia] @ [Spacing] L=[Length]
    # Example: 2Φw8@20 L=500
    
    # Pre-processing cleanup
    clean_line = line.replace('PH', 'Φ').replace('D', 'Φ')
    
    # Regex breakdown:
    # (^|\s)(\d+)? -> Optional Multiplier at start
    # .*? -> Skip garbage
    # [Φφd] -> Diameter Symbol
    # w? -> Optional 'w' noise
    # (\d+) -> Diameter Value
    # @(\d+) -> Spacing Value
    # .*?L=(\d+) -> Length Value
    
    spacing_pattern = re.search(r'(?:^|\s)(\d+)?.*?[\Φ\φd]w?(\d+)@(\d+).*?L=(\d+)', clean_line, re.IGNORECASE)
    
    if spacing_pattern:
        mult_str, dia_str, space_str, len_str = spacing_pattern.groups()
        
        multiplier = int(mult_str) if mult_str else 1
        dia = int(dia_str)
        spacing = int(space_str)
        length_cm = int(len_str)
        
        if dia not in BAR_WEIGHTS: return None # Invalid diameter
        
        # Calculation: Qty = (Length / Spacing) + 1
        elements_per_row = math.ceil(length_cm / spacing) + 1
        total_qty = elements_per_row * multiplier
        
        weight_per_meter = BAR_WEIGHTS[dia]
        total_weight = total_qty * (length_cm / 100) * weight_per_meter
        
        return {
            'Type': 'Rebar (Spacing)',
            'Desc': f"{multiplier}x Φ{dia}@{spacing}",
            'Diameter': dia,
            'Length (cm)': length_cm,
            'Qty': total_qty,
            'Total Weight': round(total_weight, 2)
        }

    # Logic 3: SIMPLE REBAR (Direct Quantity)
    # Pattern: [Qty] [Phi] [Dia] L=[Length]
    # Example: 5Φ16 L=600
    simple_pattern = re.search(r'(?:^|\s)(\d+)?.*?[\Φ\φd]w?(\d+).*?L=(\d+)', clean_line, re.IGNORECASE)
    
    if simple_pattern:
        qty_str, dia_str, len_str = simple_pattern.groups()
        
        qty = int(qty_str) if qty_str else 1
        dia = int(dia_str)
        length_cm = int(len_str)
        
        if dia not in BAR_WEIGHTS: return None
        
        # Overlap Logic for L > 1200
        overlap_add = 0
        if length_cm > 1200:
            overlap_add = 50 * dia # 50d overlap in mm -> convert logic if needed
            # For simplicity here we assume raw weight calculation, 
            # but user can split lines. Let's keep it simple.
            
        weight = qty * (length_cm / 100) * BAR_WEIGHTS[dia]
        
        return {
            'Type': 'Rebar (Direct)',
            'Desc': f"Φ{dia}",
            'Diameter': dia,
            'Length (cm)': length_cm,
            'Qty': qty,
            'Total Weight': round(weight, 2)
        }
        
    return None

# --- 4. UI LAYOUT ---

# Top Header
c1, c2 = st.columns([8,1])
with c1:
    st.markdown("<h1 style='color: white; margin-top: -20px;'>Iron<span style='color:#bbb; font-weight:lighter'>CAL</span> <span style='font-size: 0.5em; color: #2D8CFF'>Commander</span></h1>", unsafe_allow_html=True)
with c2:
    st.markdown("<h1 style='text-align: right;'>☰</h1>", unsafe_allow_html=True)

# Split Layout
col_dashboard, col_editor = st.columns([1.5, 1])

# --- RIGHT COLUMN: EDITOR ---
with col_editor:
    st.markdown("### 📝 Input Editor")
    
    # Session state for text area
    if 'input_text' not in st.session_state:
        st.session_state.input_text = ""

    # Toolbar Functions
    def add_symbol(sym):
        st.session_state.input_text += sym
        
    # Toolbar UI
    b1, b2, b3, b4, b5 = st.columns(5)
    if b1.button("Φ"): add_symbol("Φ")
    if b2.button("@"): add_symbol("@")
    if b3.button("L="): add_symbol(" L=")
    if b4.button("#"): add_symbol("#")
    if b5.button("CLR"): st.session_state.input_text = ""

    # Text Area
    text_input = st.text_area(
        "Enter Code:", 
        value=st.session_state.input_text,
        height=400,
        placeholder="Example:\n2Φw8@20 L=500\n5Φ16 L=600",
        key="main_input",
        label_visibility="collapsed"
    )
    
    # Sync back to session state if user types manually
    st.session_state.input_text = text_input
    
    st.info("💡 Syntax: QtyΦDia L=Length | OR | MultΦDia@Space L=Length")

# --- LEFT COLUMN: DASHBOARD ---
with col_dashboard:
    st.markdown("### 📊 Live Dashboard")
    
    # Parse Logic Execution
    lines = st.session_state.input_text.split('\n')
    data = []
    for line in lines:
        res = parse_line(line)
        if res:
            data.append(res)
            
    df = pd.DataFrame(data)
    
    # Metrics
    if not df.empty:
        total_w = df['Total Weight'].sum()
        est_cost = (total_w / 1000) * 3500 # 3500 NIS per ton
        count = int(df['Qty'].sum())
    else:
        total_w = 0
        est_cost = 0
        count = 0
        
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Weight", f"{total_w:,.1f} kg")
    m2.metric("Est. Cost", f"₪ {est_cost:,.0f}")
    m3.metric("Elements", count)
    
    st.divider()
    
    # Data Table
    if not df.empty:
        st.dataframe(
            df[['Desc', 'Length (cm)', 'Qty', 'Total Weight']], 
            use_container_width=True,
            hide_index=True
        )
        
        # Download Button
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download BOM (CSV)",
            csv,
            "ironcal_bom.csv",
            "text/csv",
            key='download-csv'
        )
        
        # Excel Export
        excel_data = generate_excel_bom(data)
        st.download_button(
            "📥 Download BOM (Excel)",
            excel_data,
            "ironcal_bom.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key='download-excel'
        )
    else:
        st.caption("Waiting for input...")