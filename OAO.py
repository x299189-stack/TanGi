import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import io

st.set_page_config(layout="wide", page_title="時空路段速度分析")
st.title("交通路線路段速度視覺化")

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


uploaded_file = st.sidebar.file_uploader("請上傳檔案要xlsx", type=["xlsx"], key="file_uploade_main")

template_df = pd.DataFrame({
    "路線": ["路線A", "路線A"], 
    "時間": ["08:00", "09:00"],
    "里程點": [0, 500], 
    "速度": [40, 25],
    "起點經度": [120.6, 120.6], 
    "起點緯度": [24.1, 24.1], 
    "終點經度": [120.65, 120.65], 
    "終點緯度": [24.15, 24.15]
})

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
    template_df.to_excel(writer, index=False, sheet_name='Sheet1')

st.sidebar.download_button(
    label="📥 下載 Excel 格式範本",
    data=buffer.getvalue(),
    file_name="transport_data_template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    required_cols = ['路線', '時間', '里程點', '速度', '起點經度', '起點緯度', '終點經度', '終點緯度']
    if not all(col in df.columns for col in required_cols):
        st.error(f"❌ 檔案格式錯誤！請確認包含以下欄位：\n{', '.join(required_cols)}")
        st.stop() 
    
    st.success("✅ 檔案讀取成功！")
    
    # --- 原本的分析邏輯從這裡開始 ---



if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    all_routes = df['路線'].unique().tolist()
    selected_routes = st.sidebar.multiselect("選擇路線", all_routes, default=all_routes, key="route_select")
    
    all_times = sorted(df['時間'].astype(str).unique().tolist())
    selected_time = st.sidebar.selectbox("選擇時間", all_times, key="time_select")
    
    # 數據過濾
    filtered_df = df[(df['路線'].isin(selected_routes)) & (df['時間'].astype(str) == selected_time)]
    filtered_df = filtered_df.sort_values(['路線', '里程點'])
    
    if filtered_df.empty:
        st.warning("所選條件下無數據，請重新選擇！")
    else:
        min_speed, max_speed = filtered_df['速度'].min(), filtered_df['速度'].max()
        

        st.sidebar.markdown("### 速度顏色對照")
       
        steps = [min_speed + (max_speed - min_speed) * i / 4 for i in range(5)]
        for i in range(4):
            low, high = steps[i], steps[i+1]
            color = get_google_color((low + high) / 2, min_speed, max_speed)
            st.sidebar.markdown(f"**{int(low)} - {int(high)} km/h**: <span style='color:{color}'>●</span>", unsafe_allow_html=True)

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
                
                if last_coord and sub_coords:
                    sub_coords.insert(0, last_coord)
                
                if sub_coords:
                    line_color = get_google_color(row['速度'], min_speed, max_speed)
                    folium.PolyLine(
                        locations=[(c[1], c[0]) for c in sub_coords],
                        color=line_color,
                        weight=6,
                        opacity=0.9,
                        tooltip=f"路線: {route_name} | 里程: {target_m}m | 速度: {row['速度']} km/h"
                    ).add_to(m)
                    last_coord = sub_coords[-1]
                
                prev_m = target_m
                
        m.fit_bounds(m.get_bounds())    
        st_folium(m, width=1000, height=600)