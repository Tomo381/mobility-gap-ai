"""
Mobility Gap AI - Data Processing Pipeline
名古屋市エリアの公共交通データ（バス停・鉄道駅）と国勢調査500mメッシュ人口データを統合し、
交通空白地帯および移動格差スコア（Mobility Gap Score）を算出する。
"""

import json
import math
import os
import pandas as pd
import numpy as np

# -------------------------------------------------------------
# 1. 座標・メッシュコード変換関数 (JIS X 0410)
# -------------------------------------------------------------
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

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    2点間の直線距離 (メートル) を計算
    """
    R = 6371000.0  # 地球の半径 (m)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

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
    
    # 鉄道駅GeoJSON保存
    station_out_file = os.path.join(data_dir, "nagoya_stations.geojson")
    with open(station_out_file, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": station_features}, f, ensure_ascii=False)
    print(f"保存完了: {station_out_file}")

    print("\n=== [Step 3] 国勢調査500mメッシュデータの読み込みと幾何生成 ===")
    mesh_pop_file = os.path.join(data_dir, "tblT001101H23.txt")
    
    # カラム名取得
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
    total_desert_pop = 0
    total_desert_elderly = 0
    high_risk_count = 0

    print("メッシュごとの最寄り交通アクセス距離 & 移動格差スコア計算中...")

    for idx, row in df_mesh.iterrows():
        code = str(row["KEY_CODE"])
        if len(code) < 9:
            continue
        
        min_lat, min_lon, max_lat, max_lon = meshcode_to_bbox(code)
        c_lat = (min_lat + max_lat) / 2.0
        c_lon = (min_lon + max_lon) / 2.0

        # 名古屋エリア判定
        if not (LAT_MIN <= c_lat <= LAT_MAX and LON_MIN <= c_lon <= LON_MAX):
            continue

        # 人口抽出
        pop_raw = str(row.get("T001101001", "0"))
        elderly_raw = str(row.get("T001101019", "0"))
        elderly75_raw = str(row.get("T001101022", "0"))

        pop = float(pop_raw) if pop_raw not in ["*", ""] else 0.0
        elderly = float(elderly_raw) if elderly_raw not in ["*", ""] else 0.0
        elderly75 = float(elderly75_raw) if elderly75_raw not in ["*", ""] else 0.0

        if pop == 0:
            continue  # 人口ゼロのメッシュ（山林、海、工業専用地など）は除外

        # 最寄りバス停距離 (メートル)
        # 簡易ユークリッド平面近似による高速計算: 1度 ≈ 111km (lat), 1度 ≈ 91km (lon at 35N)
        d_lat_bus = (bus_lats - c_lat) * 111000.0
        d_lon_bus = (bus_lons - c_lon) * 91000.0
        min_d_bus = float(np.min(np.sqrt(d_lat_bus**2 + d_lon_bus**2)))

        # 最寄り駅距離 (メートル)
        if len(st_lats) > 0:
            d_lat_st = (st_lats - c_lat) * 111000.0
            d_lon_st = (st_lons - c_lon) * 91000.0
            min_d_station = float(np.min(np.sqrt(d_lat_st**2 + d_lon_st**2)))
        else:
            min_d_station = 99999.0

        # Mobility Gap 判定基準:
        # ・バス停から徒歩5分(約400m)超
        # ・駅から徒歩10分(約800m)超
        is_bus_desert = (min_d_bus > 400.0)
        is_station_desert = (min_d_station > 800.0)
        is_transit_desert = is_bus_desert and is_station_desert

        # 高齢化率 (%)
        aging_rate = round((elderly / pop * 100.0), 1) if pop > 0 else 0.0

        # リスクレベル分類 (0〜3)
        # 0: 良好 (バス停400m以内 または 駅800m以内)
        # 1: やや不便 (バス停400〜600m、駅800m超)
        # 2: 交通空白地帯 (バス停600〜800m、駅800m超)
        # 3: 高リスク移動困難地帯 (バス停800m超[徒歩10分以上]、駅800m超、かつ高齢者が一定数居住)
        if not is_transit_desert:
            gap_level = 0
            risk_label = "アクセス良好"
        else:
            if min_d_bus <= 600.0:
                gap_level = 1
                risk_label = "注意（バス停400〜600m）"
            elif min_d_bus <= 800.0:
                gap_level = 2
                risk_label = "交通空白（バス停600〜800m）"
            else:
                gap_level = 3
                risk_label = "深刻な交通空白地帯（バス・駅共に800m以上）"
                if elderly >= 50:
                    high_risk_count += 1

        # 移動格差指数 (Mobility Gap Score)
        # 高齢者人口 × 交通距離係数
        dist_factor = (min_d_bus / 400.0) * (min_d_station / 800.0)
        gap_score = round(elderly * dist_factor, 1)

        total_area_pop += pop
        total_area_elderly += elderly
        if is_transit_desert:
            total_desert_pop += pop
            total_desert_elderly += elderly

        # ポリゴン頂点 (反時計回り)
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
                "is_desert": is_transit_desert,
                "gap_level": gap_level,
                "risk_label": risk_label,
                "gap_score": gap_score
            }
        })

    print(f"有効居住メッシュ数: {len(mesh_features)} 件")
    print(f"対象地域総人口: {int(total_area_pop):,} 人 (うち65歳以上: {int(total_area_elderly):,} 人)")
    print(f"交通空白地帯の人口: {int(total_desert_pop):,} 人 (うち65歳以上: {int(total_desert_elderly):,} 人)")
    print(f"深刻な高リスクメッシュ数: {high_risk_count} 箇所")

    # メッシュGeoJSON保存
    mesh_out_file = os.path.join(data_dir, "nagoya_mobility_gap_mesh.geojson")
    with open(mesh_out_file, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": mesh_features}, f, ensure_ascii=False)
    print(f"保存完了: {mesh_out_file}")

    # サマリー指標保存
    summary_data = {
        "mesh_count": len(mesh_features),
        "total_population": int(total_area_pop),
        "total_elderly": int(total_area_elderly),
        "desert_population": int(total_desert_pop),
        "desert_elderly": int(total_desert_elderly),
        "high_risk_mesh_count": high_risk_count,
        "desert_population_ratio": round(total_desert_pop / total_area_pop * 100, 1) if total_area_pop > 0 else 0,
        "desert_elderly_ratio": round(total_desert_elderly / total_area_elderly * 100, 1) if total_area_elderly > 0 else 0,
        "station_count": len(station_features),
        "bus_stop_count": len(bus_stops)
    }
    summary_file = os.path.join(data_dir, "summary_metrics.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    print(f"サマリー保存完了: {summary_file}")
    print("\n[SUCCESS] すべての前処理が完了しました！")

if __name__ == "__main__":
    main()
