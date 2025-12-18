import streamlit as st
import pandas as pd
import pdfplumber
import re
import os

st.set_page_config(page_title="Salary Scale Comparator", layout="wide")

st.title("📊 Salary Scale Comparator")
st.markdown("Upload your **Salary Scale PDF** and the corresponding **Excel Sheet** to compare values.")

# --- Parsing Logic ---

def parse_pdf_with_geometry(pdf_file):
    data = {} # (period, scale) -> value
    
    with pdfplumber.open(pdf_file) as pdf:
        if len(pdf.pages) == 0:
            return data
        page = pdf.pages[0]
        # Cluster words into lines based on 'top' coordinate with tolerance
        # Standard clustering can be brittle. We group words that are vertically close.
        words = sorted(page.extract_words(), key=lambda w: (w['top'], w['x0']))
        
    lines = []
    if words:
        current_line = [words[0]]
        for w in words[1:]:
            # Tolerance of 5 points to group words on roughly same line
            if abs(w['top'] - current_line[0]['top']) < 5:
                current_line.append(w)
            else:
                lines.append(current_line)
                current_line = [w]
        lines.append(current_line)
    
    scale_columns = {}
    table_active = False
    
    for row_words in lines:
        # Sort words in line by x0
        row_words.sort(key=lambda w: w['x0'])
        text_line = " ".join([w['text'] for w in row_words])
        
        # Stop processing if we hit the July table
        if "juli" in text_line.lower() and "2026" in text_line:
            break

        # Heuristic to look for the table start
        if "De salaristabel is per" in text_line:
            if "januari" in text_line.lower():
                table_active = True
            continue 
            
        # Header detection
        if "Periodiek" in text_line:
            # If we are active (or fallback if we missed the title but see Periodiek before July)
            # We assume first Periodiek encountered before July is the one we want if active wasn't set 
            # (but safer to rely on 'table_active' from date)
            if table_active:
                scale_columns = {} 
                seen_periodiek = False
                for w in row_words:
                    if "Periodiek" in w['text']:
                        seen_periodiek = True
                        continue
                    if seen_periodiek:
                        scale_name = w['text']
                        x_center = (w['x0'] + w['x1']) / 2
                        scale_columns[scale_name] = x_center
            elif "1" in text_line and "2" in text_line: # Heuristic: if we see Periodiek and numbers, maybe it's the header
                 # Only activate if we haven't started. 
                 # But sticking to strict 'table_active' is safer to avoid confusing block headers.
                 pass
            continue
            
        if not table_active:
            continue
            
        # Data Row
        if not row_words: continue
        
        first_word = row_words[0]
        # Period should be a number
        if re.match(r'^\d+$', first_word['text']):
            period = first_word['text']
            
            if not scale_columns:
                continue
                
            for w in row_words[1:]:
                val_text = w['text']
                clean_val_str = val_text.replace('.', '').replace(',', '')
                if not clean_val_str.isdigit():
                    continue
                
                val = int(clean_val_str)
                
                w_center = (w['x0'] + w['x1']) / 2
                
                closest_scale = None
                min_dist = 50 # Threshold
                
                for scale, col_x in scale_columns.items():
                    dist = abs(w_center - col_x)
                    if dist < min_dist:
                        min_dist = dist
                        closest_scale = scale
                
                if closest_scale:
                    data[(period, closest_scale)] = val

    return data

def parse_excel_sheet(excel_file):
    try:
        # Load without header to scan
        df = pd.read_excel(excel_file, sheet_name=2, header=None)
    except Exception as e:
        st.error(f"Error reading Excel sheet 3: {e}")
        return {}

    data = {}
    
    # Locate Header Row
    header_row_idx = None
    column_map = {} # col_idx -> scale_name
    
    for idx, row in df.iterrows():
        row_values = [str(x).strip() for x in row.values]
        
        if "Periodiek" in row_values:
            # Found header candidate
            is_collecting = False
            for col_idx, cell_val in enumerate(row_values):
                if cell_val == "Periodiek":
                    is_collecting = True
                    continue
                
                if is_collecting and cell_val and cell_val.lower() != "nan" and cell_val != "":
                    if "Salaris" not in cell_val: 
                        column_map[col_idx] = cell_val
                        
            if column_map:
                header_row_idx = idx
                
        if column_map and header_row_idx is not None and idx > header_row_idx:
            first_scale_col = min(column_map.keys())
            period = None
            
            # Check period in columns to left
            for check_col in range(first_scale_col - 1, -1, -1):
                val = str(row.iloc[check_col]).strip()
                if val.isdigit():
                    period = val
                    break
                if val and val.lower() != "nan": 
                    break
            
            if period:
                for col_idx, scale in column_map.items():
                    if col_idx < len(row): # Bounds check
                        raw_val = row.iloc[col_idx]
                        if pd.isna(raw_val): continue
                        
                        try:
                            val_f = float(raw_val)
                            if val_f < 100: continue # Skip hourly
                            data[(period, scale)] = int(val_f)
                        except:
                            pass

    return data

# --- UI Layout ---

col1, col2 = st.columns(2)

# Check for default files
default_pdf_path = "salary-scale.pdf"
default_excel_path = "wage-excel.xlsx"

default_pdf_exists = os.path.exists(default_pdf_path)
default_excel_exists = os.path.exists(default_excel_path)

with col1:
    pdf_file = st.file_uploader("Upload PDF", type=["pdf"])
    if not pdf_file and default_pdf_exists:
        st.info(f"Using default: {default_pdf_path}")

with col2:
    excel_file = st.file_uploader("Upload Excel", type=["xlsx"])
    if not excel_file and default_excel_exists:
        st.info(f"Using default: {default_excel_path}")

if st.button("Compare Files"):
    # Determine files to use
    pdf_to_process = pdf_file if pdf_file else (default_pdf_path if default_pdf_exists else None)
    excel_to_process = excel_file if excel_file else (default_excel_path if default_excel_exists else None)

    if pdf_to_process and excel_to_process:
        with st.spinner("Parsing files..."):
            try:
                pdf_data = parse_pdf_with_geometry(pdf_to_process)
                excel_data = parse_excel_sheet(excel_to_process)
                
                # Comparison Logic
                results = []
                
                all_keys = set(pdf_data.keys()) | set(excel_data.keys())
                
                # Sort
                def sort_key(k):
                    p, s = k
                    try: p_i = int(p)
                    except: p_i = -1
                    s_clean = str(s).replace('A', '.5')
                    try: s_f = float(s_clean)
                    except: s_f = -1.0
                    return (s_f, p_i)
                
                for p, s in sorted(list(all_keys), key=sort_key):
                    pdf_val = pdf_data.get((p, s), None)
                    excel_val = excel_data.get((p, s), None)
                    
                    status = "✅ Match"
                    diff = 0
                    
                    if pdf_val is None or excel_val is None:
                        continue

                    if pdf_val == excel_val:
                        continue
                        
                    # It is a difference.
                    diff = excel_val - pdf_val
                    if excel_val == 2496 and pdf_val < 2496:
                        status = "ℹ️ MinWage Correction"
                    else:
                        status = "❌ Mismatch"
                            
                    results.append({
                        "Scale": s,
                        "Period": p,
                        "PDF Value": pdf_val,
                        "Excel Value": excel_val,
                        "Difference": diff,
                        "Status": status
                    })
                
                df_res = pd.DataFrame(results)
                
                if df_res.empty:
                    st.success("✅ No Mismatches Found! (All values match or represent explained MinWage corrections)")
                else:
                    st.warning("⚠️ Mismatches Found (Including MinWage Corrections)")
                    st.table(df_res)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.exception(e)
    else:
        st.warning("Please upload files or ensure default files exist to proceed.")
