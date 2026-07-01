import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

st.set_page_config(layout="wide", page_title="時空路段速度分析")
st.title("交通路線路段速度畫圖上")

uploaded_file = st.sidebar.file_uploader("請上傳檔案要xlsx", type=["xlsx"])

# Viridis 顏色轉換函數
cmap = plt.get_cmap('viridis')
def get_viridis_color(speed, min_s, max_s):
    norm = (speed - min_s) / (max_s - min_s + 1e-9)
    return mcolors.to_hex(cmap(norm))

# 計算路徑累計距離
def get_path_with_distances(coords):
    distances = [0.0]
    for i in range(len(coords) - 1):
        d = geodesic((coords[i][1], coords[i][0]), (coords[i+1][1], coords[i+1][0])).meters
        distances.append(distances[-1] + d)
    return coords, distances

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    
    # --- 新增：側邊欄選單 ---
    all_routes = df['路線'].unique().tolist()
    selected_routes = st.sidebar.multiselect("選擇路線", all_routes, default=all_routes)
    
    all_times = sorted(df['時間'].astype(str).unique().tolist())
    selected_time = st.sidebar.selectbox("選擇時間", all_times)
    
    # --- 新增：根據選單過濾數據 ---
    filtered_df = df[(df['路線'].isin(selected_routes)) & (df['時間'].astype(str) == selected_time)]
    filtered_df = filtered_df.sort_values(['路線', '里程點'])
    
    if filtered_df.empty:
        st.warning("所選條件下無數據，請重新選擇！")
    else:
        min_speed, max_speed = df['速度'].min(), df['速度'].max()
        m = folium.Map(location=[filtered_df['起點緯度'].mean(), filtered_df['起點經度'].mean()], zoom_start=15)

        for route_name in filtered_df['路線'].unique():
            sub_df = filtered_df[filtered_df['路線'] == route_name]
            base = sub_df.iloc[0]
            
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
                    line_color = get_viridis_color(row['速度'], min_speed, max_speed)
                    folium.PolyLine(
                        locations=[(c[1], c[0]) for c in sub_coords],
                        color=line_color,
                        weight=4,
                        opacity=0.9,
                        tooltip=f"里程: {target_m}m | 速度: {row['速度']} km/h"
                    ).add_to(m)
                    last_coord = sub_coords[-1]
                
                prev_m = target_m
                
        st_folium(m, width=1000, height=600)