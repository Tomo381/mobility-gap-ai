"""
Mobility Gap AI - Data Processing Pipeline (愛知県全域・運行頻度加味対応版)
愛知県全域の公共交通データ（国土数値情報P11バス停・N02鉄道駅）と国勢調査500mメッシュ人口データを統合し、
鉄道運行頻度（ダイヤヘッドウェイ係数 F_train）を組み込んだ移動格差スコア（Mobility Gap Score: MGS）を算出する。
"""

import json
import math
import os
import re
import csv
import xml.etree.ElementTree as ET
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

def parse_p11_bus_stops(xml_file):
    """
    国土数値情報 P11 バス停留所データ (XML/GML) から座標と事業者・停留所名を抽出
    """
    print(f"P11 バス停留所XML解析中: {xml_file} ...")
    tree = ET.parse(xml_file)
    root = tree.getroot()

    ns = {
        'gml': 'http://schemas.opengis.net/gml/3.2.1',
        'ksj': 'http://nlftp.mlit.go.jp/ksj/schemas/ksj-app',
        'xlink': 'http://www.w3.org/1999/xlink'
    }

    points = {}
    for pt in root.findall('.//gml:Point', ns):
        pid = pt.attrib.get('{http://schemas.opengis.net/gml/3.2.1}id')
        pos = pt.find('gml:pos', ns)
        if pid and pos is not None and pos.text:
            lat, lon = map(float, pos.text.strip().split())
            points['#' + pid] = (lat, lon)

    bus_stops = []
    for bs in root.findall('.//ksj:BusStop', ns):
        loc = bs.find('ksj:loc', ns)
        if loc is None:
            continue
        href = loc.attrib.get('{http://www.w3.org/1999/xlink}href')
        if not href or href not in points:
            continue

        lat, lon = points[href]
        bsn_elem = bs.find('ksj:bsn', ns)
        boc_elem = bs.find('ksj:boc', ns)

        name = bsn_elem.text.strip() if bsn_elem is not None and bsn_elem.text else "不明停留所"
        operator = boc_elem.text.strip() if boc_elem is not None and boc_elem.text else "一般乗合バス"

        bus_stops.append({
            "stop_id": href.replace('#', ''),
            "stop_name": name,
            "operator": operator,
            "stop_lat": lat,
            "stop_lon": lon
        })

    return bus_stops

def load_frequency_master(master_file):
    """
    鉄道運行頻度マスターCSVを読み込み
    """
    rules = []
    if os.path.exists(master_file):
        with open(master_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rules.append({
                    "operator": r["operator"].strip(),
                    "line": r["line"].strip(),
                    "station_pattern": r["station_pattern"].strip(),
                    "daytime_frequency_hourly": float(r["daytime_frequency_hourly"]),
                    "headway_minutes": float(r["headway_minutes"]),
                    "frequency_penalty": float(r["frequency_penalty"]),
                    "service_level": r["service_level"].strip(),
                    "remarks": r["remarks"].strip()
                })
        print(f"運行頻度マスター読み込み完了: {len(rules)} 件のルール")
    else:
        print(f"警告: 運行頻度マスターが見つかりません ({master_file})")
    return rules

def get_station_frequency_info(st_name, line_name, operator, master_rules):
    """
    駅名・路線名・事業者名から運行頻度属性を取得
    """
    best_rule = None
    # 1. operator + line + station_pattern 完全マッチ
    for rule in master_rules:
        if rule["operator"] == operator and rule["line"] == line_name:
            pat = rule["station_pattern"]
            if pat and re.search(pat, st_name):
                best_rule = rule
                break
            elif not pat and best_rule is None:
                best_rule = rule

    # 2. line 名のみでのフォールバック
    if best_rule is None:
        for rule in master_rules:
            if rule["line"] == line_name:
                best_rule = rule
                break

    if best_rule:
        return {
            "daytime_freq": best_rule["daytime_frequency_hourly"],
            "headway_min": best_rule["headway_minutes"],
            "freq_penalty": best_rule["frequency_penalty"],
            "service_level": best_rule["service_level"],
            "remarks": best_rule["remarks"]
        }
    else:
        # デフォルト標準
        return {
            "daytime_freq": 4.0,
            "headway_min": 15.0,
            "freq_penalty": 1.3,
            "service_level": "標準",
            "remarks": "標準値フォールバック"
        }

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    
    # 愛知県全域の緯度経度範囲（バウンディングボックス）
    LAT_MIN, LAT_MAX = 34.50, 35.45
    LON_MIN, LON_MAX = 136.60, 137.85

    # 運行頻度マスター読み込み
    freq_master_file = os.path.join(data_dir, "railway_frequency_master.csv")
    master_rules = load_frequency_master(freq_master_file)

    print("\n=== [Step 1] 愛知県全域バス停データの読み込み ===")
    p11_xml = os.path.join(data_dir, "P11-22_23_GML", "P11-22_23.xml")
    if os.path.exists(p11_xml):
        bus_stops = parse_p11_bus_stops(p11_xml)
    else:
        print("P11 XMLが見つからないため、既存の名古屋市バス停データを使用します。")
        bus_file = os.path.join(data_dir, "Nagoya_bus_stop.text")
        df_bus = pd.read_csv(bus_file)
        bus_stops = df_bus[["stop_id", "stop_name", "stop_lat", "stop_lon"]].dropna().to_dict("records")
        for b in bus_stops:
            b["operator"] = "名古屋市交通局"

    print(f"愛知県全域の有効なバス停留所数: {len(bus_stops):,} 件")

    # バス停データをCSVとしても保存
    df_bus_out = pd.DataFrame(bus_stops)
    bus_out_csv = os.path.join(data_dir, "aichi_bus_stops.csv")
    df_bus_out.to_csv(bus_out_csv, index=False, encoding="utf-8")
    print(f"バス停CSV保存完了: {bus_out_csv}")

    print("\n=== [Step 2] 愛知県全域の鉄道駅データの抽出・運行頻度属性付与 ===")
    station_file = os.path.join(data_dir, "N02-20_GML", "N02-20_Station.geojson")
    with open(station_file, "r", encoding="utf-8") as f:
        station_raw = json.load(f)

    station_features = []
    station_points = []
    seen_stations = set()
    freq_level_counts = {}

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

            # 運行頻度マスターから情報取得
            f_info = get_station_frequency_info(st_name, line_name, operator, master_rules)
            freq_level_counts[f_info["service_level"]] = freq_level_counts.get(f_info["service_level"], 0) + 1

            st_item = {
                "name": st_name,
                "line": line_name,
                "operator": operator,
                "lat": avg_lat,
                "lon": avg_lon,
                "daytime_freq": f_info["daytime_freq"],
                "headway_min": f_info["headway_min"],
                "freq_penalty": f_info["freq_penalty"],
                "service_level": f_info["service_level"],
                "remarks": f_info["remarks"]
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
                    "operator": operator,
                    "daytime_freq": f_info["daytime_freq"],
                    "headway_min": f_info["headway_min"],
                    "freq_penalty": f_info["freq_penalty"],
                    "service_level": f_info["service_level"],
                    "remarks": f_info["remarks"]
                }
            })

    print(f"抽出された愛知県全域の鉄道駅数: {len(station_features):,} 件")
    print("駅の運行頻度水準別内訳:")
    for lvl, cnt in sorted(freq_level_counts.items(), key=lambda x: -x[1]):
        print(f"  ・{lvl}: {cnt} 駅")
    
    # 互換性のため2つのファイル名で出力
    for st_fname in ["aichi_stations.geojson", "nagoya_stations.geojson"]:
        station_out_file = os.path.join(data_dir, st_fname)
        with open(station_out_file, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": station_features}, f, ensure_ascii=False)

    print("\n=== [Step 3] 国勢調査500mメッシュデータの読み込みと新・MGS計算 ===")
    mesh_pop_file = os.path.join(data_dir, "tblT001101H23.txt")
    
    with open(mesh_pop_file, "r", encoding="shift_jis") as f:
        col_names = next(f).strip().split(",")
    df_mesh = pd.read_csv(mesh_pop_file, encoding="shift_jis", skiprows=1, low_memory=False)
    df_mesh.columns = col_names

    bus_lats = np.array([b["stop_lat"] for b in bus_stops], dtype=np.float64)
    bus_lons = np.array([b["stop_lon"] for b in bus_stops], dtype=np.float64)
    st_lats = np.array([s["lat"] for s in station_points], dtype=np.float64)
    st_lons = np.array([s["lon"] for s in station_points], dtype=np.float64)

    # 有効な居住メッシュの抽出
    valid_meshes = []
    for idx, row in df_mesh.iterrows():
        code = str(row["KEY_CODE"]).strip()
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
            continue

        valid_meshes.append({
            "code": code,
            "c_lat": c_lat,
            "c_lon": c_lon,
            "min_lat": min_lat,
            "min_lon": min_lon,
            "max_lat": max_lat,
            "max_lon": max_lon,
            "pop": pop,
            "elderly": elderly,
            "elderly75": elderly75
        })

    print(f"愛知県全域の有効居住メッシュ数: {len(valid_meshes):,} 件")

    mesh_c_lats = np.array([m["c_lat"] for m in valid_meshes], dtype=np.float64)
    mesh_c_lons = np.array([m["c_lon"] for m in valid_meshes], dtype=np.float64)

    # 高速ベクトル化チャンク計算（バス停距離 & 最寄り駅同定 & 駅距離）
    print("NumPyチャンクベクトル計算による最寄りアクセス距離および運行頻度の算出中...")
    CHUNK_SIZE = 1000
    min_d_bus_all = []
    min_d_station_all = []
    nearest_st_idx_all = []

    M_PER_LAT = 111000.0
    M_PER_LON = 91000.0

    for i in range(0, len(mesh_c_lats), CHUNK_SIZE):
        mlat = mesh_c_lats[i:i + CHUNK_SIZE, None]
        mlon = mesh_c_lons[i:i + CHUNK_SIZE, None]

        # バス停までの距離 (m)
        d_lat_b = (bus_lats - mlat) * M_PER_LAT
        d_lon_b = (bus_lons - mlon) * M_PER_LON
        d_bus_chunk = np.sqrt(np.min(d_lat_b**2 + d_lon_b**2, axis=1))
        min_d_bus_all.extend(d_bus_chunk)

        # 鉄道駅までの距離 (m) および最近傍駅インデックス
        if len(st_lats) > 0:
            d_lat_s = (st_lats - mlat) * M_PER_LAT
            d_lon_s = (st_lons - mlon) * M_PER_LON
            st_dist_sq = d_lat_s**2 + d_lon_s**2
            min_st_indices = np.argmin(st_dist_sq, axis=1)
            min_st_dist = np.sqrt(st_dist_sq[np.arange(len(st_dist_sq)), min_st_indices])
            
            min_d_station_all.extend(min_st_dist)
            nearest_st_idx_all.extend(min_st_indices)
        else:
            min_d_station_all.extend([99999.0] * len(mlat))
            nearest_st_idx_all.extend([-1] * len(mlat))

    min_d_bus_all = np.array(min_d_bus_all)
    min_d_station_all = np.array(min_d_station_all)

    mesh_features = []
    total_area_pop = 0
    total_area_elderly = 0
    level_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    level_elderly = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for idx, m in enumerate(valid_meshes):
        pop = m["pop"]
        elderly = m["elderly"]
        elderly75 = m["elderly75"]
        min_d_bus = float(min_d_bus_all[idx])
        min_d_station = float(min_d_station_all[idx])
        st_idx = nearest_st_idx_all[idx]

        if st_idx >= 0:
            st_info = station_points[st_idx]
            st_name = st_info["name"]
            st_line = st_info["line"]
            st_op = st_info["operator"]
            st_freq = st_info["daytime_freq"]
            st_headway = st_info["headway_min"]
            st_penalty_rate = st_info["freq_penalty"]
            st_level = st_info["service_level"]
        else:
            st_name = "なし"
            st_line = ""
            st_op = ""
            st_freq = 0.0
            st_headway = 999.0
            st_penalty_rate = 2.0
            st_level = "なし"

        aging_rate = round((elderly / pop * 100.0), 1) if pop > 0 else 0.0

        # Mobility Gap Score (新・MGS計算式: 運行頻度係数 F_train を乗算)
        bus_penalty = round(min_d_bus / 400.0, 3)
        station_penalty = round((min_d_station / 800.0) * st_penalty_rate, 3)
        gap_score = round(elderly * bus_penalty * station_penalty, 1)

        # 5段階リスクレベル分類
        if gap_score >= 4000.0:
            gap_level = 5
            risk_label = "深刻（最優先対策）"
            color = "#dc2626"
        elif gap_score >= 1500.0:
            gap_level = 4
            risk_label = "交通空白地帯（要改善）"
            color = "#f97316"
        elif gap_score >= 600.0:
            gap_level = 3
            risk_label = "注意（交通不便）"
            color = "#eab308"
        elif gap_score >= 200.0:
            gap_level = 2
            risk_label = "良好（軽微）"
            color = "#22c55e"
        else:
            gap_level = 1
            risk_label = "極めて良好（至便）"
            color = "#2563eb"

        level_counts[gap_level] += 1
        level_elderly[gap_level] += int(elderly)
        total_area_pop += pop
        total_area_elderly += elderly

        polygon_coords = [[
            [round(m["min_lon"], 5), round(m["min_lat"], 5)],
            [round(m["max_lon"], 5), round(m["min_lat"], 5)],
            [round(m["max_lon"], 5), round(m["max_lat"], 5)],
            [round(m["min_lon"], 5), round(m["max_lat"], 5)],
            [round(m["min_lon"], 5), round(m["min_lat"], 5)]
        ]]

        mesh_features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": polygon_coords
            },
            "properties": {
                "mesh_code": m["code"],
                "pop": int(pop),
                "elderly": int(elderly),
                "elderly75": int(elderly75),
                "aging_rate": aging_rate,
                "d_bus": int(min_d_bus),
                "d_station": int(min_d_station),
                "bus_penalty": bus_penalty,
                "station_penalty": station_penalty,
                "station_name": st_name,
                "station_line": st_line,
                "station_op": st_op,
                "station_freq": st_freq,
                "station_headway": st_headway,
                "station_freq_penalty": st_penalty_rate,
                "station_service_level": st_level,
                "gap_score": gap_score,
                "gap_level": gap_level,
                "risk_label": risk_label,
                "color": color
            }
        })

    print(f"\n=== 愛知県全域 運行頻度加味後の5段階分類結果 ===")
    print(f"対象地域総人口: {int(total_area_pop):,} 人 (うち高齢者: {int(total_area_elderly):,} 人)")
    print(f"  Level 1 (青 / 極めて良好): {level_counts[1]:,} 件 (高齢者: {level_elderly[1]:,} 人)")
    print(f"  Level 2 (黄緑 / 良好):    {level_counts[2]:,} 件 (高齢者: {level_elderly[2]:,} 人)")
    print(f"  Level 3 (黄色 / 注意):    {level_counts[3]:,} 件 (高齢者: {level_elderly[3]:,} 人)")
    print(f"  Level 4 (橙色 / 空白):    {level_counts[4]:,} 件 (高齢者: {level_elderly[4]:,} 人)")
    print(f"  Level 5 (赤色 / 深刻):    {level_counts[5]:,} 件 (高齢者: {level_elderly[5]:,} 人)")

    # 互換性のため2つのファイル名で出力
    for mesh_fname in ["aichi_mobility_gap_mesh.geojson", "nagoya_mobility_gap_mesh.geojson"]:
        mesh_out_file = os.path.join(data_dir, mesh_fname)
        with open(mesh_out_file, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": mesh_features}, f, ensure_ascii=False)
        print(f"メッシュGeoJSON保存完了: {mesh_out_file}")

    summary_data = {
        "region_name": "愛知県全域",
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
        "station_freq_summary": freq_level_counts,
        "bus_stop_count": len(bus_stops)
    }
    summary_file = os.path.join(data_dir, "summary_metrics.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    print(f"サマリー指標保存完了: {summary_file}")

    print("\n[SUCCESS] 愛知県全域の運行頻度加味前処理・新MGS算出がすべて完了しました！")

if __name__ == "__main__":
    main()
