
import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Salary Comparator", layout="wide")
st.title("⚖️ Salary Comparator")

# --- 1. PDF Parser (Returns Dict: {(period, scale): value}) ---
def get_pdf_matrix(pdf_file):
    matrix = {}
    with pdfplumber.open(pdf_file) as pdf:
        if not pdf.pages: return {}
        page = pdf.pages[0]
        words = page.extract_words()

    # 1. Group words by Line (Y-coordinate)
    lines = {}
    for w in words:
        y = round(w['top'] / 2) * 2
        if y not in lines: lines[y] = []
        lines[y].append(w)
    
    sorted_y = sorted(lines.keys())
    
    # 2. Identify Table Headers and Data
    scale_cols = {} # {scale_name: x_center}
    
    table_found = False
    
    for y in sorted_y:
        row_words = sorted(lines[y], key=lambda w: w['x0'])
        text = " ".join([w['text'] for w in row_words]).lower()
        
        # STOP processing if we reach the July table
        if "per 1 juli" in text:
            break
            
        # START processing if we see January
        if "per 1 januari" in text:
            table_found = True
            
        # Detect Header Row (contains "Periodiek" and numbers)
        if "periodiek" in text:
            # If we haven't seen the Jan title yet, this might be the Jan header anyway
            # But if we passed July, we stopped. So this must be Jan.
            table_found = True
            
            # Extract Scale Columns
            # We look for words that are numbers (scales 1, 2... 10 etc)
            current_scale_cols = {}
            for w in row_words:
                t = w['text']
                if t.lower() == "periodiek": continue
                # Scale names are usually numbers or 10A etc.
                # Let's simple take everything else as a scale header
                current_scale_cols[t] = (w['x0'] + w['x1']) / 2
            
            if current_scale_cols:
                scale_cols = current_scale_cols
            continue

        if not table_found:
            continue
            
        # Process Data Rows
        # Row must start with a number (Period)
        if not row_words: continue
        
        first_text = row_words[0]['text']
        if re.match(r'^\d+$', first_text):
            period = first_text
            
            if not scale_cols: continue
            
            # Map remaining words to closest scale column
            for w in row_words[1:]:
                val_text = w['text'].replace('.','').replace(',','')
                if not val_text.isdigit(): continue
                val = int(val_text)
                
                w_center = (w['x0'] + w['x1']) / 2
                
                # Find closest scale
                closest_scale = None
                min_dist = 1000
                
                for scale, x_ref in scale_cols.items():
                    dist = abs(w_center - x_ref)
                    if dist < min_dist:
                        min_dist = dist
                        closest_scale = scale
                
                # Threshold to ensure valid mapping (e.g. 50px)
                if min_dist < 50:
                    matrix[(period, closest_scale)] = val
                    
    return matrix

# --- 2. Excel Parser (Returns Dict: {(period, scale): value}) ---
def get_excel_matrix(excel_file):
    matrix = {}
    try:
        # Read 3rd sheet (index 2)
        df = pd.read_excel(excel_file, sheet_name=2, header=None)
    except:
        return {}
        
    # Scan for "Periodiek" row
    header_map = {} # {col_idx: scale_name}
    header_row = -1
    
    for idx, row in df.iterrows():
        # Convert row to string list
        vals = [str(v).strip() for v in row.values]
        
        if "Periodiek" in vals:
            header_row = idx
            # Map columns
            # usually Periodiek is col X, then X+1 is Scale 1, etc.
            # Find index of Periodiek
            try:
                p_idx = vals.index("Periodiek")
                # All subsequent non-empty cols are scales
                for c in range(p_idx + 1, len(vals)):
                    scale_name = vals[c]
                    if scale_name and scale_name.lower() != 'nan':
                         header_map[c] = scale_name
            except:
                pass
            continue
            
        # Data Rows (must be after header)
        if header_row != -1 and idx > header_row and header_map:
            # Find Period value (usually in column p_idx)
            # Or scan first few cols for a digit
            period = None
            
            # We suspect Period is in the column where "Periodiek" was, or near it.
            # Let's search columns 0 to 5 for a digit
            row_clean = [str(v).strip() for v in row.values]
            
            for i in range(len(row_clean)):
                if row_clean[i].isdigit():
                    period = row_clean[i]
                    break
            
            if period:
                # Extract values for mapped scales
                for col_idx, scale in header_map.items():
                    if col_idx < len(row):
                        raw = row[col_idx]
                        try:
                            # Clean and Int
                            val = float(raw)
                            if val > 100: # Filter out hourly rates
                                matrix[(period, scale)] = int(val)
                        except:
                            pass
    return matrix

# --- 3. UI & Comparison ---

col1, col2 = st.columns(2)
f_pdf = col1.file_uploader("Upload PDF", type='pdf')
f_xls = col2.file_uploader("Upload Excel", type='xlsx')

if f_pdf and f_xls:
    # 1. Get Matrices
    mat_pdf = get_pdf_matrix(f_pdf)
    mat_xls = get_excel_matrix(f_xls)
    
    # 2. Compare
    # We want to compare every intersection
    all_periods = set([k[0] for k in mat_pdf.keys()] + [k[0] for k in mat_xls.keys()])
    all_scales = set([k[1] for k in mat_pdf.keys()] + [k[1] for k in mat_xls.keys()])
    
    mismatches = []
    
    # Sort keys for display
    def sort_p(p):
        try: return int(p)
        except: return 999
    def sort_s(s):
        try: return float(str(s).replace('A', '.5'))
        except: return 999
        
    top_p = sorted(list(all_periods), key=sort_p)
    top_s = sorted(list(all_scales), key=sort_s)
    
    for p in top_p:
        for s in top_s:
            key = (p, s)
            
            v_pdf = mat_pdf.get(key)
            v_xls = mat_xls.get(key)
            
            # User Rule: "only show mismatches"
            # Mismatch = Values exist and are different
            # Implicit: If one is missing and the other exists, is it a mismatch?
            # User said: "scale 1 , period 0 is empty right... and 2496 in the html... " -> This was handled as mismatch/explained earlier.
            # We will show it if they differ.
            
            # Treat Missing as None
            
            if v_pdf == v_xls:
                continue
                
            # If both missing, continue
            if v_pdf is None and v_xls is None:
                continue
                
            # Difference Found
            status = "Mismatch"
            
            # Logic for MinWage
            if v_xls == 2496:
                if v_pdf is None:
                    status = "MinWage Fill (PDF Empty)"
                elif v_pdf < 2496:
                    status = "MinWage Correction"
            
            # Prepare row
            mismatches.append({
                "Period": p,
                "Scale": s,
                "PDF": v_pdf,
                "Excel": v_xls,
                "Note": status
            })
            
    # 3. Display
    if mismatches:
        df_out = pd.DataFrame(mismatches)
        st.warning(f"Found {len(mismatches)} discrepancies")
        st.table(df_out)
    else:
        st.success("Perfect Match! No discrepancies found.")

