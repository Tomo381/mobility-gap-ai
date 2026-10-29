"""
Mobility Gap AI - Data Processing Pipeline
名古屋市エリアの公共交通データ（バス停・鉄道駅）と国勢調査500mメッシュ人口データを統合し、
交通空白地帯および移動格差スコア（Mobility Gap Score: MGS）を算出する。
"""

import json
import math
import os
import pandas as pd
import numpy as np

def meshcode_to_bbox(code_str):
    """
    9桁の500mメッシュコード（4次メッシュ）から緯度経度バウンディングボックスを計算
    戻り値: (min_lat, min_lon, max_lat, max_lon)
    """
    code = str(code_str).strip()
    lat = int(code[0:2]) / 1.5
    lon = int(code[2:4]) + 100.0
    lat += int(code[4]) * (5.0 / 60.0)
    lon += int(code[5]) * (7.5 / 60.0)
    lat += int(code[6]) * (30.0 / 3600.0)
    lon += int(code[7]) * (45.0 / 3600.0)
    lat_width = 30.0 / 3600.0
    lon_width = 45.0 / 3600.0

    if len(code) >= 9:
        div = int(code[8])
        if div == 2:
            lon += lon_width / 2.0
        elif div == 3:
            lat += lat_width / 2.0
        elif div == 4:
            lat += lat_width / 2.0
            lon += lon_width / 2.0
        lat_width /= 2.0
        lon_width /= 2.0

    return lat, lon, lat + lat_width, lon + lon_width

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    
    print("=== [Step 1] バス停データの読み込み ===")
    bus_file = os.path.join(data_dir, "Nagoya_bus_stop.text")
    df_bus = pd.read_csv(bus_file)
    bus_stops = df_bus[["stop_id", "stop_name", "stop_lat", "stop_lon"]].dropna().to_dict("records")
    print(f"有効なバス停留所数: {len(bus_stops)} 件")

    print("\n=== [Step 2] 鉄道駅データの抽出とGeoJSON生成 ===")
    station_file = os.path.join(data_dir, "N02-20_GML", "N02-20_Station.geojson")
    with open(station_file, "r", encoding="utf-8") as f:
        station_raw = json.load(f)

    # 対象範囲: 名古屋市および近郊
    LAT_MIN, LAT_MAX = 35.03, 35.28
    LON_MIN, LON_MAX = 136.78, 137.06

    station_features = []
    station_points = []
    seen_stations = set()

    for feat in station_raw.get("features", []):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        pts = []
        if geom.get("type") == "LineString":
            pts = coords
        elif geom.get("type") == "MultiLineString":
            for line in coords:
                pts.extend(line)
        if not pts:
            continue
        
        avg_lon = sum(p[0] for p in pts) / len(pts)
        avg_lat = sum(p[1] for p in pts) / len(pts)

        if LAT_MIN <= avg_lat <= LAT_MAX and LON_MIN <= avg_lon <= LON_MAX:
            props = feat.get("properties", {})
            st_name = props.get("N02_005", "不明")
            line_name = props.get("N02_003", "")
            operator = props.get("N02_004", "")
            
            key = (st_name, line_name, round(avg_lat, 3), round(avg_lon, 3))
            if key in seen_stations:
                continue
            seen_stations.add(key)

            st_item = {
                "name": st_name,
                "line": line_name,
                "operator": operator,
                "lat": avg_lat,
                "lon": avg_lon
            }
            station_points.append(st_item)

            station_features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(avg_lon, 6), round(avg_lat, 6)]
                },
                "properties": {
                    "name": st_name,
                    "line": line_name,
                    "operator": operator
                }
            })

    print(f"抽出された名古屋エリアの鉄道駅数: {len(station_features)} 件")
    
    station_out_file = os.path.join(data_dir, "nagoya_stations.geojson")
    with open(station_out_file, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": station_features}, f, ensure_ascii=False)

    print("\n=== [Step 3] 国勢調査500mメッシュデータの読み込みと幾何生成 ===")
    mesh_pop_file = os.path.join(data_dir, "tblT001101H23.txt")
    
    with open(mesh_pop_file, "r", encoding="shift_jis") as f:
        col_names = next(f).strip().split(",")
    df_mesh = pd.read_csv(mesh_pop_file, encoding="shift_jis", skiprows=1, low_memory=False)
    df_mesh.columns = col_names

    bus_lats = np.array([b["stop_lat"] for b in bus_stops])
    bus_lons = np.array([b["stop_lon"] for b in bus_stops])
    st_lats = np.array([s["lat"] for s in station_points])
    st_lons = np.array([s["lon"] for s in station_points])

    mesh_features = []
    
    total_area_pop = 0
    total_area_elderly = 0
    level_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    level_elderly = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    print("メッシュごとの最寄り交通アクセス距離 & 移動格差スコア(MGS)計算中...")

    for idx, row in df_mesh.iterrows():
        code = str(row["KEY_CODE"])
        if len(code) < 9:
            continue
        
        min_lat, min_lon, max_lat, max_lon = meshcode_to_bbox(code)
        c_lat = (min_lat + max_lat) / 2.0
        c_lon = (min_lon + max_lon) / 2.0

        if not (LAT_MIN <= c_lat <= LAT_MAX and LON_MIN <= c_lon <= LON_MAX):
            continue

        pop_raw = str(row.get("T001101001", "0"))
        elderly_raw = str(row.get("T001101019", "0"))
        elderly75_raw = str(row.get("T001101022", "0"))

        pop = float(pop_raw) if pop_raw not in ["*", ""] else 0.0
        elderly = float(elderly_raw) if elderly_raw not in ["*", ""] else 0.0
        elderly75 = float(elderly75_raw) if elderly75_raw not in ["*", ""] else 0.0

        if pop == 0:
            continue  # 人口ゼロメッシュ除外

        # 最寄りバス停距離 (m)
        d_lat_bus = (bus_lats - c_lat) * 111000.0
        d_lon_bus = (bus_lons - c_lon) * 91000.0
        min_d_bus = float(np.min(np.sqrt(d_lat_bus**2 + d_lon_bus**2)))

        # 最寄り駅距離 (m)
        if len(st_lats) > 0:
            d_lat_st = (st_lats - c_lat) * 111000.0
            d_lon_st = (st_lons - c_lon) * 91000.0
            min_d_station = float(np.min(np.sqrt(d_lat_st**2 + d_lon_st**2)))
        else:
            min_d_station = 99999.0

        # 高齢化率 (%)
        aging_rate = round((elderly / pop * 100.0), 1) if pop > 0 else 0.0

        # -------------------------------------------------------------
        # 【Mobility Gap Score: MGS 算出式】
        # MGS = 高齢者人口 × (バス離隔ペナルティ) × (鉄道駅離隔ペナルティ)
        # ・バス離隔ペナルティ = 最寄りバス停距離(m) ÷ 400m（徒歩5分基準）
        # ・鉄道駅離隔ペナルティ = 最寄り駅距離(m) ÷ 800m（徒歩10分基準）
        # -------------------------------------------------------------
        bus_penalty = round(min_d_bus / 400.0, 3)
        station_penalty = round(min_d_station / 800.0, 3)
        gap_score = round(elderly * bus_penalty * station_penalty, 1)

        # -------------------------------------------------------------
        # 【5段階リスクレベル分類（深刻度の低い順: 青 → 黄緑 → 黄 → 橙 → 赤）】
        # Level 1: 青 (MGS < 200) - 移動格差なし・交通至便
        # Level 2: 黄緑 (200 <= MGS < 600) - 良好・軽微な離隔
        # Level 3: 黄色 (600 <= MGS < 1,500) - 注意・交通不便エリア
        # Level 4: 橙色 (1,500 <= MGS < 4,000) - 交通空白地帯（要改善）
        # Level 5: 赤色 (MGS >= 4,000) - 深刻な交通空白地帯（最優先対策・基準引き上げ）
        # -------------------------------------------------------------
        if gap_score >= 4000.0:
            gap_level = 5
            risk_label = "深刻（最優先対策）"
            color = "#dc2626"  # 赤
        elif gap_score >= 1500.0:
            gap_level = 4
            risk_label = "交通空白地帯（要改善）"
            color = "#f97316"  # 橙
        elif gap_score >= 600.0:
            gap_level = 3
            risk_label = "注意（交通不便）"
            color = "#eab308"  # 黄
        elif gap_score >= 200.0:
            gap_level = 2
            risk_label = "良好（軽微）"
            color = "#22c55e"  # 黄緑
        else:
            gap_level = 1
            risk_label = "極めて良好（至便）"
            color = "#2563eb"  # 青

        level_counts[gap_level] += 1
        level_elderly[gap_level] += int(elderly)
        total_area_pop += pop
        total_area_elderly += elderly

        polygon_coords = [[
            [round(min_lon, 6), round(min_lat, 6)],
            [round(max_lon, 6), round(min_lat, 6)],
            [round(max_lon, 6), round(max_lat, 6)],
            [round(min_lon, 6), round(max_lat, 6)],
            [round(min_lon, 6), round(min_lat, 6)]
        ]]

        mesh_features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": polygon_coords
            },
            "properties": {
                "mesh_code": code,
                "pop": int(pop),
                "elderly": int(elderly),
                "elderly75": int(elderly75),
                "aging_rate": aging_rate,
                "d_bus": int(min_d_bus),
                "d_station": int(min_d_station),
                "bus_penalty": bus_penalty,
                "station_penalty": station_penalty,
                "gap_score": gap_score,
                "gap_level": gap_level,
                "risk_label": risk_label,
                "color": color
            }
        })

    print(f"有効居住メッシュ数: {len(mesh_features)} 件")
    print(f"5段階分類結果:")
    print(f"  Level 1 (青 / 極めて良好): {level_counts[1]} 件 (高齢者: {level_elderly[1]:,} 人)")
    print(f"  Level 2 (黄緑 / 良好):    {level_counts[2]} 件 (高齢者: {level_elderly[2]:,} 人)")
    print(f"  Level 3 (黄色 / 注意):    {level_counts[3]} 件 (高齢者: {level_elderly[3]:,} 人)")
    print(f"  Level 4 (橙色 / 空白):    {level_counts[4]} 件 (高齢者: {level_elderly[4]:,} 人)")
    print(f"  Level 5 (赤色 / 深刻):    {level_counts[5]} 件 (高齢者: {level_elderly[5]:,} 人)")

    mesh_out_file = os.path.join(data_dir, "nagoya_mobility_gap_mesh.geojson")
    with open(mesh_out_file, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": mesh_features}, f, ensure_ascii=False)

    summary_data = {
        "mesh_count": len(mesh_features),
        "total_population": int(total_area_pop),
        "total_elderly": int(total_area_elderly),
        "level_counts": level_counts,
        "level_elderly": level_elderly,
        "critical_mesh_count": level_counts[5],
        "critical_elderly": level_elderly[5],
        "blank_mesh_count": level_counts[4] + level_counts[5],
        "blank_elderly": level_elderly[4] + level_elderly[5],
        "station_count": len(station_features),
        "bus_stop_count": len(bus_stops)
    }
    summary_file = os.path.join(data_dir, "summary_metrics.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    print("\n[SUCCESS] すべての前処理が完了しました！")

if __name__ == "__main__":
    main()
