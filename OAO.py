import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

st.set_page_config(layout="wide", page_title="時空路段速度分析")
st.title("交通路線路段速度視覺化")

google_colors = ["#17DE97", "#FFD600", "#FF5252", "#9A0007"] 
cmap = mcolors.LinearSegmentedColormap.from_list("google_map_cmap", google_colors)


def get_google_color(speed, min_s, max_s):
    norm = (max_s - speed) / (max_s - min_s + 1e-9)
    norm = max(0, min(1, norm)) 
    return mcolors.to_hex(cmap(norm))


# 計算路徑累計距離
def get_path_with_distances(coords):
    distances = [0.0]
    for i in range(len(coords) - 1):
        d = geodesic((coords[i][1], coords[i][0]), (coords[i+1][1], coords[i+1][0])).meters
        distances.append(distances[-1] + d)
    return coords, distances

# --- 側邊欄 ---
uploaded_file = st.sidebar.file_uploader("請上傳檔案要xlsx", type=["xlsx"], key="file_uploade_main")

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # 建立選單
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
        # 使用過濾後的資料範圍，確保顏色對比度足夠
        min_speed, max_speed = filtered_df['速度'].min(), filtered_df['速度'].max()
        

        
        # --- 在側邊欄顯示顏色對照表 (Legend) ---
        st.sidebar.markdown("### 速度顏色對照")
        # 切分四個區間來顯示
        steps = [min_speed + (max_speed - min_speed) * i / 4 for i in range(5)]
        for i in range(4):
            low, high = steps[i], steps[i+1]
            color = get_google_color((low + high) / 2, min_speed, max_speed)
            st.sidebar.markdown(f"**{int(low)} - {int(high)} km/h**: <span style='color:{color}'>●</span>", unsafe_allow_html=True)

        m = folium.Map(location=[filtered_df['起點緯度'].mean(), filtered_df['起點經度'].mean()], zoom_start=15)

        for route_name in filtered_df['路線'].unique():
            sub_df = filtered_df[filtered_df['路線'] == route_name]
            base = sub_df.iloc[0]
            
            # OSRM 路徑規劃
            url = f"http://router.project-osrm.org/route/v1/driving/{base['起點經度']},{base['起點緯度']};{base['終點經度']},{base['終點緯度']}?overview=full&geometries=geojson"
            coords = requests.get(url).json()['routes'][0]['geometry']['coordinates']
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
                
        st_folium(m, width=1000, height=600)