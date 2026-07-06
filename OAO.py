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
import holidays
from datetime import datetime
import os
import tempfile 
import zipfile
import uuid


st.set_page_config(layout="wide", page_title="交通分析系統")
st.title("交通路線路段速度視覺化")
# --- 顏色設定 ---
google_colors = ["#17DE97", "#FFD600", "#FF5252", "#9A0007"]
cmap = mcolors.LinearSegmentedColormap.from_list("google_map_cmap", google_colors)
#####################################################################
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
##################################################################

tab_map, tab_analysis,tab_merge = st.tabs([
    "🗺️ 路段速度地圖", "📈 尖峰離峰判定", "⚙️ 尖峰離峰資料合併"
])
##################################################################

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
        
        # --- 修改區塊開始 ---
        # 建立地圖，不直接指定 tiles
        m = folium.Map(location=[24.1477, 120.6736], zoom_start=12)
        
        folium.TileLayer("cartodbpositron", name="極簡模式").add_to(m)
    
    # 2. 衛星影像版 (使用 Esri World Imagery)
        folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="衛星影像模式"
        ).add_to(m)
        
        folium.LayerControl(position='topright').add_to(m)


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
                    # 這裡保持你原本正確的繪圖邏輯
                    folium.PolyLine(locations=[(lat, lon) for lon, lat in sub_coords],
                                       color=get_google_color(row['速度'], min_speed, max_speed),
                                       weight=6, opacity=0.9).add_to(m)
                    last_coord = sub_coords[-1]
                prev_m = target_m

        m.fit_bounds(m.get_bounds())
        st_folium(m, width=1000, height=600)
    else:
        st.warning("所選條件下無數據")

###############################################################
def render_analysis_area(df_input, start_date):

            records_per_day = 96
            num_days = len(df) // records_per_day
            dates = pd.date_range(start=start_date, periods=num_days + 1, freq="D")
            df['日期'] = np.repeat(dates, records_per_day)[:len(df)]
            df['日期時間'] = pd.to_datetime(df['日期'].astype(str) + ' ' + df['時間'].astype(str))
    

            st.write("### 1. 21天車當量趨勢圖")
            fig = px.line(df, x='日期時間', y=['順向', '逆向', '加總'],
                          labels={'value': '車當量', 'variable': '類型'},
                          color_discrete_map={'順向': '#1f77b4', '逆向': '#2ca02c', '加總': '#d62728'})
            fig.update_layout(hovermode="x unified", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

            st.sidebar.header("資料分析設定")
            freq_type = st.sidebar.selectbox("請選擇資料紀錄頻率：", ["每15分鐘 (96筆/天)", "每小時 (24筆/天)"])

            st.write(f"### 2. 統計結果 ({freq_type})")

            day_filter = st.radio("選擇統計區間：", ["總和", "平日", "假日"], horizontal=True)

            from collections import defaultdict
            
            def is_holiday(date_val):
                tw_holidays = holidays.TW()
                return '假日' if (pd.to_datetime(date_val).weekday() >= 5 or pd.to_datetime(date_val) in tw_holidays) else '平日'

            if '日期類型' not in df.columns:
                df['日期類型'] = df['日期'].apply(is_holiday)

            df_process_base = df.copy()
            if day_filter == "平日":
                df_process_base = df[df['日期類型'] == '平日'].copy()
            elif day_filter == "假日":
                df_process_base = df[df['日期類型'] == '假日'].copy()

            if "每小時" in freq_type:
                df_process = df_process_base.copy()
                df_process[['順向', '逆向', '加總']] = df_process[['順向', '逆向', '加總']].rolling(window=4).sum()
                df_process = df_process[df_process['時間'].astype(str).str.contains(r'00:00$')]
                records_per_day = 24
            else:
                df_process = df_process_base.copy()
                records_per_day = 96

            unique_dates = pd.to_datetime(df_process_base['日期']).dt.date.unique()
            
            with st.expander(f"點擊查看包含的具體日期 ({len(unique_dates)} 天)"):
                date_str_list = [d.strftime('%m/%d') for d in sorted(unique_dates)]
                st.write(", ".join(date_str_list))

            counts = {'順向': defaultdict(int), '逆向': defaultdict(int), '加總': defaultdict(int)}
            
            n_days = len(df_process) // records_per_day
            for d in range(n_days):
                day_data = df_process.iloc[d*records_per_day : (d+1)*records_per_day]
                
                for col in ['順向', '逆向', '加總']:
                    top6 = day_data.nlargest(6, col)['時間'].astype(str)
                    for t in top6:
                        counts[col][t] += 1
            
            tabs = st.tabs(['順向', '逆向', '加總'])
            for i, col_name in enumerate(['順向', '逆向', '加總']):
                with tabs[i]:
                    res_df = pd.DataFrame.from_dict(counts[col_name], orient='index', columns=[col_name])
                    st.table(res_df.sort_values(by=col_name, ascending=False))
        
#################################################################
def get_clean_master_data(base_path):
    all_data = []
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                df['日期'] = date_str
                df['方向'] = direction
                all_data.append(df)
    
    if not all_data: return None
    
    df_all = pd.concat(all_data, ignore_index=True)
    df_all['時間戳記'] = pd.to_datetime(df_all['日期'] + ' ' + df_all['時間'].astype(str))
    
    start, end = df_all['時間戳記'].min(), df_all['時間戳記'].max()
    full_range = pd.date_range(start=start, end=end + pd.Timedelta(days=1), freq='15min')[:-1]
    
    results = {}
    for direction in ["順向", "逆向"]:
        sub = df_all[df_all['方向'] == direction].set_index('時間戳記')
        results[direction] = sub['車當量'].reindex(full_range, fill_value=0)
    
    df_final = pd.DataFrame(results)
    df_final['加總車當量'] = df_final['順向'] + df_final['逆向']
    df_final = df_final.reset_index().rename(columns={'index': '時間戳記'})
    df_final['日期'] = df_final['時間戳記'].dt.strftime('%Y-%m-%d')
    df_final['時間'] = df_final['時間戳記'].dt.strftime('%H:%M:%S')
    
    return df_final[['日期', '時間', '順向', '逆向', '加總車當量']]
    all_data = []
    
    # 1. 遍歷資料夾
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path):
            st.error(f"找不到資料夾: {dir_path}")
            continue
            
        files = [f for f in os.listdir(dir_path) if f.endswith(".xlsx")]
        for file in files:
            try:
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                df['日期'] = date_str
                df['方向'] = direction
                all_data.append(df)
            except Exception as e:
                st.warning(f"無法讀取檔案 {file}: {e}")
    
    if not all_data:
        st.error("沒有讀取到任何資料！")
        return None

    df_all = pd.concat(all_data, ignore_index=True)
    df_all['時間戳記'] = pd.to_datetime(df_all['日期'] + ' ' + df_all['時間'].astype(str))

    start = df_all['時間戳記'].min()
    end = df_all['時間戳記'].max()
    full_range = pd.date_range(start=start, end=end + pd.Timedelta(days=1), freq='15min')[:-1]
    results = {}
    for direction in ["順向", "逆向"]:
        sub = df_all[df_all['方向'] == direction].set_index('時間戳記')
        results[direction] = sub['車當量'].reindex(full_range, fill_value=0)
    
    df_final = pd.DataFrame(results)
    df_final['加總車當量'] = df_final['順向'] + df_final['逆向']
 
    df_final = df_final.reset_index()
    df_final['日期'] = df_final['index'].dt.strftime('%Y-%m-%d')
    df_final['時間'] = df_final['index'].dt.strftime('%H:%M:%S')
    
    return df_final.drop(columns=['index'])
    all_data = []

    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): 
            st.warning(f"找不到資料夾: {dir_path}")
            continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                file_path = os.path.join(dir_path, file)
                df = pd.read_excel(file_path, usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                
                df['日期'] = date_str
                df['方向'] = direction
                all_data.append(df)
    
    if not all_data:
        return None
    
    df_all = pd.concat(all_data, ignore_index=True)
    
    start_date = pd.to_datetime(df_all['日期']).min()
    end_date = pd.to_datetime(df_all['日期']).max()
    
    full_time_range = pd.date_range(start=start_date, end=end_date + pd.Timedelta(days=1), freq='15min')[:-1]
    
    master_df = pd.DataFrame({'時間戳記': full_time_range})
    master_df['日期'] = master_df['時間戳記'].dt.strftime('%Y-%m-%d')
    master_df['時間'] = master_df['時間戳記'].dt.strftime('%H:%M:%S')
    

    df_all['時間戳記'] = pd.to_datetime(df_all['日期'] + ' ' + df_all['時間'].astype(str))
    

    merged_df = pd.merge(master_df, df_all, on=['日期', '時間'], how='left')
    

    df_pivot = merged_df.pivot_table(
        index=['日期', '時間'], 
        columns='方向', 
        values='車當量', 
        aggfunc='sum'
    ).fillna(0) 
    
    df_pivot['加總車當量'] = df_pivot['順向'] + df_pivot['逆向']
    
    return df_pivot.reset_index()
    all_data = []
    
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        st.write(f"正在檢查路徑: {dir_path}") 
        
        if not os.path.exists(dir_path):
            st.warning(f"找不到資料夾: {dir_path}")
            continue
            
        files = [f for f in os.listdir(dir_path) if f.endswith(".xlsx")]
        st.write(f"在 {direction} 資料夾找到 {len(files)} 個檔案") # 偵錯：顯示檔案數
        
        for file in files:
            file_path = os.path.join(dir_path, file)
            df = pd.read_excel(file_path, usecols=['時間', '車當量'])
            
            date_str = f"2026-{file[:2]}-{file[2:4]}"
            df['日期'] = date_str
            df['方向'] = direction
            all_data.append(df)
    
    st.write(f"總共收集到 {len(all_data)} 個 Excel 檔案的資料")
    
    if not all_data: return None
    
    df_all = pd.concat(all_data, ignore_index=True)
    st.write(f"合併後的總行數: {len(df_all)}") 
    
    df_pivot = df_all.pivot_table(
        index=['日期', '時間'], 
        columns='方向', 
        values='車當量', 
        aggfunc='sum'
    ).fillna(0)
    
    df_pivot['加總車當量'] = df_pivot['順向'] + df_pivot['逆向']
    return df_pivot.reset_index()
    all_data = [] 
    
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                
                df['日期'] = date_str
                df['方向'] = direction
                
                all_data.append(df)
    

    if not all_data:
        return None
    
    df_all = pd.concat(all_data, ignore_index=True)
    
    df_all['時間戳記'] = pd.to_datetime(df_all['日期'] + ' ' + df_all['時間'].astype(str))
    

    df_pivot = df_all.pivot_table(
        index=['日期', '時間'], 
        columns='方向', 
        values='車當量', 
        aggfunc='sum'
    ).fillna(0) 
    
    df_pivot['加總車當量'] = df_pivot['順向'] + df_pivot['逆向']
    
    return df_pivot.reset_index()
    all_data = []
    
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                df['日期'] = date_str
                df['方向'] = direction
                all_data.append(df)

    if not all_data: return None
    
    df_all = pd.concat(all_data, ignore_index=True)
    

    unique_dates = df_all['日期'].nunique()
    total_expected = unique_dates * 96 
    
    st.write(f"系統偵測到共 {unique_dates} 個資料檔，預期總筆數: {total_expected}")
    

    df_pivot = df_all.pivot_table(
        index=['日期', '時間'], 
        columns='方向', 
        values='車當量', 
        aggfunc='sum'
    ).fillna(0)
    
    df_pivot['加總車當量'] = df_pivot['順向'] + df_pivot['逆向']
    
    return df_pivot.reset_index()

    master_list = []
    

    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                
                df['日期'] = date_str
                df['方向'] = direction
                df['車當量_填入'] = df['車當量']
                
                master_list.append(df[['日期', '時間', '方向', '車當量_填入']])
    
    df_all = pd.concat(master_list, ignore_index=True)
    
    df_pivot = df_all.pivot_table(
        index=['日期', '時間'], 
        columns='方向', 
        values='車當量_填入', 
        aggfunc='sum'
    ).fillna(0) 
    
    df_pivot['加總車當量'] = df_pivot['順向'] + df_pivot['逆向']
    
    return df_pivot.reset_index()
    all_data = []
    
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                
                df['時間戳記'] = pd.to_datetime(f"{date_str} " + df['時間'].astype(str))
                df['方向'] = direction
                all_data.append(df)
    
    df_combined = pd.concat(all_data, ignore_index=True)
    
    all_time_index = pd.date_range(start=df_combined['時間戳記'].min(), 
                                   end=df_combined['時間戳記'].max(), 
                                   freq='15min')
    

    results = {}
    for direction in ["順向", "逆向"]:
        sub = df_combined[df_combined['方向'] == direction]
        grouped = sub.groupby('時間戳記')['車當量'].sum()
        results[direction] = grouped.reindex(all_time_index, fill_value=0)
        
    df_final = pd.DataFrame(results)
    df_final['加總'] = df_final['順向'] + df_final['逆向']
    
    return df_final.reset_index().rename(columns={'index': '時間戳記'})
    all_data = []
    
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])
                date_str = f"2026-{file[:2]}-{file[2:4]}"
                full_time_index = pd.date_range(start=f"{date_str} 00:00", end=f"{date_str} 23:45", freq='15min')
                
                df['時間戳記'] = pd.to_datetime(f"{date_str} " + df['時間'].astype(str))
                df = df.set_index('時間戳記').reindex(full_time_index, fill_value=0)
                
                df['方向'] = direction 
                df['日期'] = date_str
                all_data.append(df) 
    
    df_combined = pd.concat(all_data)
    
    df_wide = df_combined.pivot_table(index=df_combined.index, columns='方向', values='車當量', aggfunc='sum')
    df_wide['加總'] = df_wide['順向'] + df_wide['逆向']
    
    return df_wide.reset_index()
    all_data = []

    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path): continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df = pd.read_excel(os.path.join(dir_path, file), usecols=['時間', '車當量'])

                date_str = f"2026-{file[:2]}-{file[2:4]}"
                

                full_time_index = pd.date_range(start=f"{date_str} 00:00", end=f"{date_str} 23:45", freq='15min')
                df['時間戳記'] = pd.to_datetime(f"{date_str} " + df['時間'].astype(str))
                
                df = df.set_index('時間戳記').reindex(full_time_index, fill_value=0)
                df['方向'] = direction
                all_data.append(df)
    
    if not all_data:
        return None
        
    df_final = pd.concat(all_data)
    
    df_wide = df_final.pivot_table(index=df_final.index, columns='方向', values='車當量', aggfunc='sum')
    df_wide['加總'] = df_wide['順向'] + df_wide['逆向']
    
    return df_wide.reset_index().rename(columns={'index': '時間戳記'})
    all_data = []
    for direction in ["順向", "逆向"]:
        dir_path = os.path.join(base_path, direction)
        if not os.path.exists(dir_path):
            continue
            
        for file in os.listdir(dir_path):
            if file.endswith(".xlsx"):
                df_temp = pd.read_excel(os.path.join(dir_path, file))
                df_temp['日期'] = file.replace('.xlsx', '')
                df_temp['方向'] = direction
                all_data.append(df_temp)
    
    if not all_data:
        return None
        
    df_merged = pd.concat(all_data, ignore_index=True)
    
    df_merged['時間戳記'] = pd.to_datetime(df_merged['日期'].astype(str) + ' ' + df_merged['時間'].astype(str))
    

    start = df_merged['時間戳記'].min().date()
    end = df_merged['時間戳記'].max().date()
    full_range = pd.date_range(start=start, end=end + pd.Timedelta(days=1), freq='15min')[:-1]
    
    df_final = pd.DataFrame(index=full_range)
    for direction in ["順向", "逆向"]:
        sub = df_merged[df_merged['方向'] == direction].set_index('時間戳記')
        df_final[direction] = sub['車當量'].reindex(full_range, fill_value=0)
        
    df_final['加總'] = df_final['順向'] + df_final['逆向']
    return df_final.reset_index().rename(columns={'index': '時間'})
##################################################################

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

######################$#####################################################################################################

with tab_analysis:
    st.subheader("📊 尖峰離峰分析")
    uploaded_file = st.file_uploader("上傳交通流量 Excel 檔案", type=["xlsx"])

    start_date = st.date_input("請選擇資料開始日期", value=pd.to_datetime("2026-06-01"),key="unique_start_date_key")

    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.astype(str).str.strip()
        
        rename_map = {'時間': '時間', 'Time': '時間', 'time': '時間',
                      '順向': '順向', 'forword': '順向', 'forward': '順向',
                      '逆向': '逆向', 'inverse': '逆向',
                      '加總': '加總', 'add': '加總', '加總車當量': '加總'}
        df = df.rename(columns=rename_map)

        render_analysis_area(df, start_date)
    
#####################################################################
 

with tab_merge:
    st.subheader("📂 批量資料夾匯入")
    uploaded_zip = st.file_uploader("請上傳 .zip 壓縮檔", type=["zip"])
    
    # 1. 執行合併的邏輯
    if uploaded_zip and st.button("執行合併與清洗", key="final_merge_btn"):
        import zipfile
        import uuid
        
        unique_id = uuid.uuid4().hex[:8]
        work_dir = os.path.join(os.getcwd(), f"work_folder_{unique_id}")
        os.makedirs(work_dir)
        
        with zipfile.ZipFile(uploaded_zip, 'r') as z:
            z.extractall(work_dir)
            
        df_result = get_clean_master_data(work_dir)
        
        if df_result is not None:
            st.session_state['df_main'] = df_result # 把結果存起來
            st.success("合併完成！")
        else:
            st.error("未能找到資料夾，請確認壓縮檔內的結構。")

    # 2. 【關鍵】：把下載按鈕放在這裡，只要 session 裡面有資料，它就一定會出現
    if 'df_main' in st.session_state:
        df_result = st.session_state['df_main']
        st.dataframe(df_result) # 順便顯示一下資料表
        
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_result.to_excel(writer, index=False)
        
        st.download_button(
            label="📥 下載處理好的 Excel 檔",
            data=output.getvalue(),
            file_name="交通流量分析資料.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="final_download_btn"
        )