
import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

st.set_page_config(page_title="Salary Scale Comparator", layout="wide")

st.title("📊 Salary Scale Comparator")
st.markdown("""
Upload your **Salary Scale PDF** and the corresponding **Excel Sheet** to compare values.
""")

# --- Parsing Logic ---

def parse_pdf_with_geometry(pdf_file):
    data = {} # (period, scale) -> value
    
    with pdfplumber.open(pdf_file) as pdf:
        if len(pdf.pages) == 0:
            return data
        page = pdf.pages[0]
        words = page.extract_words()
        
    # Cluster words into lines based on 'top' coordinate
    lines = {}
    for w in words:
        y = round(w['top'] / 2) * 2
        if y not in lines: lines[y] = []
        lines[y].append(w)
        
    sorted_y = sorted(lines.keys())
    
    scale_columns = {}
    table_active = False
    
    for y in sorted_y:
        row_words = sorted(lines[y], key=lambda w: w['x0'])
        text_line = " ".join([w['text'] for w in row_words])
        
        # Stop processing if we hit the July table
        if "De salaristabel is per 1 juli" in text_line.lower():
            break

        # Heuristic to look for the table start if usually dates are mentioned
        if "De salaristabel is per" in text_line:
            # Check if it is January (or just enable if we haven't hit July yet)
            if "januari" in text_line.lower():
                table_active = True
            continue 
            
        # Or just start if we see "Periodiek"
        if "Periodiek" in text_line:
            table_active = True
            
            seen_periodiek = False
            scale_columns = {} 
            for w in row_words:
                if "Periodiek" in w['text']:
                    seen_periodiek = True
                    continue
                if seen_periodiek:
                    scale_name = w['text']
                    x_center = (w['x0'] + w['x1']) / 2
                    scale_columns[scale_name] = x_center
            continue
            
        if not table_active:
            continue
            
        # Data Row
        if not row_words: continue
        
        first_word = row_words[0]
        # Period should be a number or maybe "0"
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
                # Skip massive numbers or tiny numbers if they look like artifacts, 
                # but salary 2000-10000 is expected.
                
                w_center = (w['x0'] + w['x1']) / 2
                
                closest_scale = None
                min_dist = 9999
                
                for scale, col_x in scale_columns.items():
                    dist = abs(w_center - col_x)
                    if dist < min_dist:
                        min_dist = dist
                        closest_scale = scale
                
                if min_dist < 50 and closest_scale:
                    data[(period, closest_scale)] = val

    return data

def parse_excel_sheet(excel_file):
    # User said 3rd sheet
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
        # Look for "Periodiek"
        row_values = [str(x).strip() for x in row.values]
        
        if "Periodiek" in row_values:
            # Found header candidate
            # Map columns
            is_collecting = False
            for col_idx, cell_val in enumerate(row_values):
                if cell_val == "Periodiek":
                    is_collecting = True
                    # The periodiek column is usually THIS one or below it? 
                    # In the PDF logic, Periodiek was a label row.
                    # In Excel, usually Periodiek is a column header, but here it seems "Periodiek" is a label for the scale columns row?
                    # Let's rely on finding numbers/scales.
                    continue
                
                if is_collecting and cell_val and cell_val.lower() != "nan" and cell_val != "":
                    # likely a scale
                    if "Salaris" not in cell_val: # Avoid "Salarisschaal" label
                        column_map[col_idx] = cell_val
                        
            if column_map:
                header_row_idx = idx
                # st.write(f"DEBUG: Found header at row {idx} with scales: {column_map}")
                # We assume the table continues until it ends or new header
                pass
                
        # If we have an active column map, check for data
        if column_map and idx > header_row_idx:
            # Check for period number in columns to the left of the first scale
            first_scale_col = min(column_map.keys())
            
            # Period is likely 1 or 2 cols to the left
            period = None
            
            # Check safely
            for check_col in range(first_scale_col - 1, -1, -1):
                val = str(row.iloc[check_col]).strip()
                if val.isdigit():
                    period = val
                    break
                if val and val.lower() != "nan": 
                    # Found something non-digit non-empty, maybe stop searching
                    break
            
            if period:
                # Extract Data
                for col_idx, scale in column_map.items():
                    raw_val = row.iloc[col_idx]
                    if pd.isna(raw_val): continue
                    
                    try:
                        # Fix formatting if string
                        val_str = str(raw_val).replace('.', '').replace(',', '')
                        # Sometimes Excel reads as float 2496.0
                        val_f = float(raw_val)
                        # Check if it's hourly (small number)
                        if val_f < 100: continue
                        
                        data[(period, scale)] = int(val_f)
                    except:
                        pass

    return data

# --- UI Layout ---

col1, col2 = st.columns(2)

with col1:
    pdf_file = st.file_uploader("Upload PDF", type=["pdf"])

with col2:
    excel_file = st.file_uploader("Upload Excel", type=["xlsx"])

if st.button("Compare Files"):
    if pdf_file and excel_file:
        with st.spinner("Parsing files..."):
            try:
                pdf_data = parse_pdf_with_geometry(pdf_file)
                excel_data = parse_excel_sheet(excel_file)
                
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
                    
                    if pdf_val is None and excel_val is None:
                        continue
                    elif pdf_val is None:
                        status = "⚠️ Missing in PDF"
                        if excel_val == 2496: status = "ℹ️ MinWage Fill"
                    elif excel_val is None:
                        status = "⚠️ Missing in Excel"
                    elif pdf_val != excel_val:
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
                        "Difference": diff if diff != 0 else "",
                        "Status": status
                    })
                
                df_res = pd.DataFrame(results)
                
                st.success("Comparison Complete!")
                
                # Summary Metrics
                total = len(results)
                matches = len(df_res[df_res['Status'] == "✅ Match"])
                explained = len(df_res[df_res['Status'].str.contains("MinWage")])
                mismatches = len(df_res[df_res['Status'] == "❌ Mismatch"])
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Points", total)
                m2.metric("Exact Matches", matches)
                m3.metric("Explained (MinWage)", explained)
                m4.metric("Mismatches", mismatches)
                
                st.dataframe(df_res, use_container_width=True)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.exception(e)
    else:
        st.warning("Please upload both files to proceed.")
