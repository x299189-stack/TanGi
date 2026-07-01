import streamlit as st #網頁
import pandas as pd #資料處理
import folium #地圖
from streamlit_folium import st_folium 
import requests
from geopy.distance import geodesic
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

st.set_page_config(layout="wide", page_title="速度路線分析")  #網頁的基本外觀與資訊
st.title("路段速度視覺化")  #網頁的主視窗中大標題。

uploaded_file = st.sidebar.file_uploader("請上傳 ready_to_plot.xlsx", type=["xlsx"])
#在網頁側邊欄建立一個檔案上傳器

cmap = plt.get_cmap('viridis')  #仔入colormap
def get_viridis_color(speed, min_s, max_s): #抓資料內最小速度 最大速度 速度
    norm = (speed - min_s) / (max_s - min_s + 1e-9)    # 正規化速度到 0-1 之間 轉成hex顏色
    return mcolors.to_hex(cmap(norm))

def get_path_with_distances(coords):
    distances = [0.0] #初始化列表 (起點 里程:0)
    for i in range(len(coords) - 1):  #計算點雨點距離(距離 = 點數量-1)
        d = geodesic((coords[i][1], coords[i][0]), (coords[i+1][1], coords[i+1][0])).meters
        distances.append(distances[-1] + d) #將點轉換成經緯度取得距離結果(公尺)
    return coords, distances

if uploaded_file is not None:   ##檢查使用者是否成功上傳檔案
    df = pd.read_excel(uploaded_file)
    df = df.sort_values(['路線', '里程點'])
    
    min_speed, max_speed = df['速度'].min(), df['速度'].max()
    #抓資料內最小速度 最大速度 速度
    m = folium.Map(location=[df['起點緯度'].mean(), df['起點經度'].mean()], zoom_start=15) #建立地圖

    for route_name in df['路線'].unique():  #找出資料中所有不重複的路線名稱，並依序對每一條路線進行迴圈。
        sub_df = df[df['路線'] == route_name]  #建立了一個新的變數sub_df，只包含當前迴圈的那條路線的所有數據。
        base = sub_df.iloc[0]  #取得該路徑的首筆資料
        
        url = f"http://router.project-osrm.org/route/v1/driving/{base['起點經度']},{base['起點緯度']};{base['終點經度']},{base['終點緯度']}?overview=full&geometries=geojson"
        #組裝向OSRM API的網路請求網址
        coords = requests.get(url).json()['routes'][0]['geometry']['coordinates'] #發送請求並解析回傳的資料
        coords, dists = get_path_with_distances(coords) #計算每個座標點的累積距離，並將結果存儲在coords和dists變數中。
        
        prev_m = 0 #初始化上一個里程點的變數，初始值為0
        last_coord = None #初始化上一個座標點的變數，初始值為None
        
        for _, row in sub_df.iterrows(): #對於sub_df中的每一行數據，進行迴圈操作。
            target_m = row['里程點'] #取得當前行的里程點值
            
            sub_coords = [coords[i] for i, d in enumerate(dists) if prev_m <= d <= target_m] #抓取符合條件的座標點，條件是累積距離在上一個里程點和當前里程點之間。
            
            if last_coord and sub_coords: #如果上一個座標點存在且符合條件的座標點列表不為空，則將上一個座標點插入到符合條件的座標點列表的開頭，以確保路線連續。
                sub_coords.insert(0, last_coord) 
            
            if sub_coords: #如果符合條件的座標點列表不為空，則進行以下操作：
                line_color = get_viridis_color(row['速度'], min_speed, max_speed) #根據當前行的速度值，計算對應的顏色。
                
                folium.PolyLine(
                    locations=[(c[1], c[0]) for c in sub_coords],
                    color=line_color,
                    weight=4,
                    opacity=0.9,
                    tooltip=f"里程: {target_m}m | 速度: {row['速度']} km/h"
                ).add_to(m) #在地圖上繪製一條多段線，表示從上一個里程點到當前里程點的路段，並使用計算出的顏色來表示速度。
                
                last_coord = sub_coords[-1] #將符合條件的座標點列表中的最後一個座標點存儲到last_coord變數中，以便在下一次迴圈中使用。
            
            prev_m = target_m #將當前行的里程點值存儲到prev_m變數中，以便在下一次迴圈中使用。
            
    st_folium(m, width=1000, height=600) #在網頁上顯示地圖，並設置地圖的寬度和高度。