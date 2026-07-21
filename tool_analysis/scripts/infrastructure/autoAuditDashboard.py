import pandas as pd
import streamlit as st

# --- HOW TO RUN THIS APP ---
# 1. Open your terminal in this folder
# 2. Run: streamlit run dashboard.py
# ---------------------------

st.set_page_config(page_title="Web Audit Dashboard", layout="wide")

st.title("🌐 Web Architecture & Green Audit Dashboard")
st.markdown(
    "Upload your CSV to browse, search, and inspect website technical profiles."
)

uploaded_file = st.file_uploader("Choose your CSV file", type="csv")

if uploaded_file is not None:
    # Load data
    try:
        df = pd.read_csv(uploaded_file)
        df.columns = df.columns.str.strip()
    except Exception as e:
        st.error(f"Error loading CSV: {e}")
        st.stop()

    # --- SIDEBAR: SEARCH & FILTERS ---
    st.sidebar.header("🔍 Search & Filters")

    # 1. URL Search Box (Case-insensitive)
    search_query = st.sidebar.text_input("Search by URL or Keyword", "").strip().lower()

    # 2. Cluster Filter
    clusters = sorted(df["ai_cluster"].unique().tolist())
    selected_clusters = st.sidebar.multiselect(
        "Filter by Cluster", clusters, default=clusters
    )

    # 3. Rating Filter
    min_r, max_r = float(df["quality_rating"].min()), float(df["quality_rating"].max())
    rating_range = st.sidebar.slider(
        "Quality Rating Range", min_r, max_r, (min_r, max_r)
    )

    # --- APPLY FILTERS LOGIC ---
    # Start with basic filters
    mask = (
        (df["ai_cluster"].isin(selected_clusters))
        & (df["quality_rating"] >= rating_range[0])
        & (df["quality_rating"] <= rating_range[1])
    )

    # Apply Search filter using the CORRECT Pandas method: .str.contains(case=False)
    if search_query:
        mask = mask & (df["url"].str.contains(search_query, case=False, na=False))

    filtered_df = df[mask]

    # --- MAIN LAYOUT: MASTER-DETAIL VIEW ---
    left_col, right_col = st.columns([0.4, 0.6], gap="large")

    with left_col:
        st.subheader("📋 Site Directory")
        st.caption(f"Found {len(filtered_df)} sites matching your criteria")

        # Display a simplified table for the directory (Multiple URLs view)
        display_cols = ["url", "ai_cluster", "quality_rating"]

        # We use the selection feature to allow clicking rows
        event = st.dataframe(
            filtered_df[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )

    with right_col:
        st.subheader("🔍 Detailed Audit Report")

        # Check if a row was selected in the dataframe on the left
        selected_rows = event.get("selection", {}).get("rows", [])

        if selected_rows:
            # Get the index of the selected row from the FILTERED dataframe
            row_idx = selected_rows[0]
            row = filtered_df.iloc[row_idx]

            # --- DISPLAY THE DATA BEAUTIFULLY ---

            # 1. Header Area
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.markdown(f"### [{row['url']}]({row['url']})")
                st.markdown(f"**Cluster:** `{row['ai_cluster']}`")
            with col_b:
                # Color-coded rating badge
                r = row["quality_rating"]
                color = "green" if r >= 4 else "orange" if r >= 3 else "red"
                st.markdown(
                    f"""
                    <div style='text-align:center; padding:10px; border-radius:10px;
                    background-color:#f0f2f6; color:{color}; font-size:24px; font-weight:bold;'>
                        {r} / 5
                    </div>
                """,
                    unsafe_allow_html=True,
                )

            st.divider()

            # 2. The "Big Text" sections using Tabs
            tab1, tab2, tab3 = st.tabs(
                ["📝 Analysis", "⚡ Efficiency", "📊 Raw Metrics"]
            )

            with tab1:
                st.markdown("#### Technical Architecture Analysis")
                if pd.notna(row["ai_analysis"]):
                    st.info(row["ai_analysis"])
                else:
                    st.write("No analysis available.")

                st.markdown("#### Quality Assessment")
                if pd.notna(row["ai_quality"]):
                    st.warning(row["ai_quality"])
                else:
                    st.write("No quality assessment available.")

            with tab2:
                st.markdown("#### Performance & Sustainability Metrics")
                m1, m2, m3 = st.columns(3)
                # Use .get() or direct access depending on how your CSV is structured
                m1.metric("JS Ratio", row["js_ratio"])
                m2.metric("Scripts", int(row["scripts"]))
                m3.metric("Images", int(row["images"]))

            with tab3:
                st.markdown("#### Full Technical Data (JSON View)")
                tech_data = {
                    "Word Count": int(row["word_count"]),
                    "Script Tags": int(row["scripts"]),
                    "Style Tags": int(row["styles"]),
                    "Image Tags": int(row["images"]),
                    "JS Ratio": float(row["js_ratio"]),
                }
                st.json(tech_data)

        else:
            # Empty State
            st.info(
                "👈 Click a site in the directory on the left to view its full technical breakdown."
            )
            if search_query:
                st.write(f"Currently searching for: **'{search_query}'**")

else:
    # Landing state when no file is uploaded
    st.warning("Please upload your CSV file to begin the audit visualization.")
