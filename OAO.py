import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import io
import numpy as np
import plotly.express as px





st.set_page_config(layout="wide", page_title="交通分析系統")
st.title("交通路線路段速度視覺化")
# --- 顏色設定 ---
google_colors = ["#17DE97", "#FFD600", "#FF5252", "#9A0007"]
cmap = mcolors.LinearSegmentedColormap.from_list("google_map_cmap", google_colors)

def get_google_color(speed, min_s, max_s):
    norm = (max_s - speed) / (max_s - min_s + 1e-9)
    norm = max(0, min(1, norm))
    return mcolors.to_hex(cmap(norm))

@st.cache_data(show_spinner=False)
def get_path_with_distances(coords):
    distances = [0.0]
    for i in range(len(coords) - 1):
        d = geodesic((coords[i][1], coords[i][0]), (coords[i+1][1], coords[i+1][0])).meters
        distances.append(distances[-1] + d)
    return coords, distances

@st.cache_data(show_spinner=False)
def fetch_route_coords(start_lng, start_lat, end_lng, end_lat):
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lng},{start_lat};{end_lng},{end_lat}?overview=full&geometries=geojson"
    return requests.get(url).json()['routes'][0]['geometry']['coordinates']

# --- 分頁結構 ---

tab_map, tab_analysis,tab_settings = st.tabs([
    "🗺️ 路段速度地圖", "📈 尖峰離峰判定", "⚙️ 系統設定"
])

# --- 地圖分頁邏輯 ---

# --- 定義碎片化繪圖函式 ---

@st.fragment
def render_map_area(df):
    col1, col2 = st.columns(2)
    with col1:
        all_routes = df['路線'].unique().tolist()
        selected_routes = st.multiselect("選擇路線", all_routes, default=all_routes)
    with col2:
        all_times = sorted(df['時間'].astype(str).unique().tolist())
        selected_time = st.selectbox("選擇時間", all_times)
    filtered_df = df[(df['路線'].isin(selected_routes)) & (df['時間'].astype(str) == selected_time)].sort_values(['路線', '里程點'])
    if not filtered_df.empty:
        min_speed, max_speed = filtered_df['速度'].min(), filtered_df['速度'].max()
        m = folium.Map(location=[24.1477, 120.6736], zoom_start=12)
        for route_name in filtered_df['路線'].unique():
            sub_df = filtered_df[filtered_df['路線'] == route_name]
            base = sub_df.iloc[0]
            coords = fetch_route_coords(base['起點經度'], base['起點緯度'], base['終點經度'], base['終點緯度'])
            coords, dists = get_path_with_distances(coords)
            prev_m = 0
            last_coord = None
            for _, row in sub_df.iterrows():
                target_m = row['里程點']
                sub_coords = [coords[i] for i, d in enumerate(dists) if prev_m <= d <= target_m]
                if last_coord and sub_coords: sub_coords.insert(0, last_coord)
                if sub_coords:
                    folium.PolyLine(locations=[(c[1], c[0]) for c in sub_coords],
                                   color=get_google_color(row['速度'], min_speed, max_speed),
                                    weight=6, opacity=0.9).add_to(m)
                    last_coord = sub_coords[-1]
                prev_m = target_m

       

        m.fit_bounds(m.get_bounds())
        st_folium(m, width=1000, height=600)
    else:
        st.warning("所選條件下無數據")


def render_analysis_area():
    st.subheader("📊 尖峰離峰分析")
    uploaded_file = st.file_uploader("上傳交通流量 Excel 檔案", type=["xlsx"])
    
    if uploaded_file is not None:
        try:
            # 讀取並處理資料
            df = pd.read_excel(uploaded_file)
            df.columns = df.columns.astype(str).str.strip()
            
            # 統一欄位名稱
            rename_map = {'時間': '時間', 'Time': '時間', 'time': '時間',
                          '順向': '順向', 'forword': '順向', 'forward': '順向',
                          '逆向': '逆向', 'inverse': '逆向',
                          '加總': '加總', 'add': '加總', '總': '加總'}
            df = df.rename(columns=rename_map)
            
            # 日期標記
            records_per_day = 96
            num_days = 21
            dates = pd.date_range(start="2026-06-01", periods=num_days, freq="D")
            df['日期'] = np.repeat(dates, records_per_day)[:len(df)]
            df['日期時間'] = pd.to_datetime(df['日期'].astype(str) + ' ' + df['時間'].astype(str))

            # --- 功能 1：繪製趨勢圖 ---
            st.write("### 1. 21天車當量趨勢圖")
            fig = px.line(df, x='日期時間', y=['順向', '逆向', '加總'],
                          labels={'value': '車當量', 'variable': '類型'},
                          color_discrete_map={'順向': '#1f77b4', '逆向': '#2ca02c', '加總': '#d62728'})
            fig.update_layout(hovermode="x unified", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

            # --- 功能 2：分項交通流量最繁忙的六大時段 ---
            st.write("### 2. 分項交通流量最繁忙的六大時段")
            cols_to_analyze = ['順向', '逆向', '加總']
            tabs = st.tabs(cols_to_analyze)
            
            for i, col_name in enumerate(cols_to_analyze):
                with tabs[i]:
                    # 計算門檻與統計
                    threshold = df[col_name].mean()
                    busy_df = df[df[col_name] > threshold]
                    top_times = busy_df['時間'].value_counts().head(6).reset_index()
                    top_times.columns = ['時段', '出現次數']
                    
                    st.write(f"#### {col_name} 最繁忙時段")
                    st.table(top_times)
            
            st.info("💡 統計說明：分別統計過去21天內，該類別流量超過各自平均值的次數排行。")

        except Exception as e:
            # 這是捕捉錯誤的關鍵，這樣程式才不會噴 SyntaxError
            st.error(f"分析過程中出現錯誤: {e}")
# --- 主分頁結構 ---

with tab_map:
    col_up, col_dl = st.columns([2, 1])
    with col_up:
        uploaded_file = st.file_uploader("請上傳 Excel 檔案", type=["xlsx"], key="file_uploade_main")
    with col_dl:
        template_df = pd.DataFrame({"路線": ["路線A"], "時間": ["08:00"], "里程點": [0], "速度": [40], "起點經度": [120.6], "起點緯度": [24.1], "終點經度": [120.65], "終點緯度": [24.15]})
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            template_df.to_excel(writer, index=False, sheet_name='Sheet1')
        st.write("### ")
        st.download_button("📥 下載 Excel 範本", data=buffer.getvalue(), file_name="template.xlsx")
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        render_map_area(df)
# 呼叫碎片化函式###########################
####################################################################################################

with tab_analysis:
    render_analysis_area()