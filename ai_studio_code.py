import streamlit as st
import pdfplumber
import pandas as pd
import numpy as np

st.set_page_config(page_title="CAO Salary Checker", layout="wide")

st.title("📊 CAO Gemeenten 2026 Salary Comparison Tool")
st.info("This app compares the official PDF (Jan 2026) against your Excel Sheet (Opmerkingen+Controle).")

# --- STEP 1: EXTRACT DATA FROM PDF ---
def get_pdf_data(pdf_file):
    all_scales = []
    with pdfplumber.open(pdf_file) as pdf:
        # Page 16 (Index 15)
        page = pdf.pages[15]
        tables = page.extract_tables()
        
        # Table 1 (Scales 1-10) and Table 2 (Scales 10A-18)
        for table in tables:
            df = pd.DataFrame(table[1:], columns=table[0])
            df = df.set_index('Periodiek')
            all_scales.append(df)
            
    # Combine horizontally (merge scales 1-10 with 10A-18)
    master_pdf = pd.concat(all_scales, axis=1)
    # Clean numeric values (remove dots/spaces)
    master_pdf = master_pdf.replace(r'[\.\s-]', '', regex=True).apply(pd.to_numeric)
    return master_pdf

# --- STEP 2: EXTRACT DATA FROM EXCEL ---
def get_excel_data(url):
    # Read 3rd sheet, skip first 10 lines (starts at line 11)
    df = pd.read_excel(url, sheet_name=2, skiprows=10)
    # We assume the first column is 'Periodiek' and others are scales
    df = df.rename(columns={df.columns[0]: "Periodiek"})
    df = df.set_index("Periodiek")
    # Take only the relevant columns (1 through 18)
    # This cleans up extra columns in the Excel
    return df.apply(pd.to_numeric, errors='coerce')

# --- UI LOGIC ---
excel_url = "YOUR_EXCEL_URL_HERE" # User provides this or we hardcode it

uploaded_pdf = st.file_uploader("Upload the CAO PDF", type="pdf")

if uploaded_pdf:
    with st.spinner("Processing official PDF and Excel file..."):
        try:
            pdf_table = get_pdf_data(uploaded_pdf)
            # Use the URL provided by the user
            excel_table = get_excel_data(excel_url)
            
            # Reindex Excel to match PDF structure for 1:1 comparison
            excel_table = excel_table.reindex(index=pdf_table.index, columns=pdf_table.columns)

            # --- STEP 3: COMPARISON ---
            diff = (pdf_table == excel_table)
            
            st.subheader("Comparison Result")
            
            def highlight_diff(data):
                # Create a copy of the dataframe with styling
                attr = 'background-color: #ffcccc; color: black' # Red for mismatch
                other = 'background-color: #ccffcc; color: black' # Green for match
                
                # Compare against the pdf_table
                is_correct = (data == pdf_table.loc[data.name])
                return [other if v else attr for v in is_correct]

            st.write("Mismatching values are highlighted in Red. Correct values in Green.")
            st.dataframe(excel_table.style.apply(highlight_diff, axis=1))

            if diff.all().all():
                st.success("✅ Perfect Match! All values in the Excel match the CAO PDF.")
            else:
                st.error("❌ Discrepancies found. Please check the red cells above.")
                
        except Exception as e:
            st.error(f"Error: {e}")