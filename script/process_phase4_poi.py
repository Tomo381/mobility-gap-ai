"""
Mobility Gap AI - Phase 4 POI Data Processing & Integration Script
愛知県の医療機関データ（国土数値情報P04）および商業施設データ（OSM）を標準化し、
全12,336メッシュに対する最寄り医療・商業施設アクセシビリティを高速計算して統合する。
"""

import json
import csv
import math
import os
import time

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_dir = os.path.join(base_dir, "data")

def haversine_m(lat1, lon1, lat2, lon2):
    """2点間の距離をメートル単位で計算 (Haversine formula)"""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

class SpatialGrid:
    """緯度経度ベースの簡易空間インデックス（高速近傍探索用）"""
    def __init__(self, cell_size_deg=0.03):
        self.cell_size = cell_size_deg
        self.grid = {}

    def _cell_key(self, lat, lon):
        return (int(lat / self.cell_size), int(lon / self.cell_size))

    def insert(self, item):
        lat = item['lat']
        lon = item['lon']
        key = self._cell_key(lat, lon)
        if key not in self.grid:
            self.grid[key] = []
        self.grid[key].append(item)

    def find_nearest(self, lat, lon, filter_fn=None):
        ck_lat, ck_lon = self._cell_key(lat, lon)
        min_dist = float('inf')
        nearest_item = None
        
        # 探索リングを拡大（1セル ≈ 0.03度 ≈ 2.7km〜3.3km）
        for ring in range(0, 35):
            for d_lat in range(-ring, ring + 1):
                for d_lon in range(-ring, ring + 1):
                    if max(abs(d_lat), abs(d_lon)) != ring:
                        continue
                    key = (ck_lat + d_lat, ck_lon + d_lon)
                    if key in self.grid:
                        for item in self.grid[key]:
                            if filter_fn and not filter_fn(item):
                                continue
                            d = haversine_m(lat, lon, item['lat'], item['lon'])
                            if d < min_dist:
                                min_dist = d
                                nearest_item = item
            
            # 次のリングのセルまでの最短距離の下限 (経度35度で1度約91km -> 0.03度約2.7km)
            approx_min_dist_to_next = max(0, (ring - 1)) * self.cell_size * 80000.0
            if nearest_item is not None and ring >= 2 and min_dist <= approx_min_dist_to_next:
                break

        return nearest_item, min_dist

def main():
    print("=== Phase 4: 医療機関・商業施設POIデータの処理とメッシュ統合開始 ===")
    t0 = time.time()

    # 1. 医療機関データ (P04) の読み込みと標準化
    p04_file = os.path.join(data_dir, "P04-20_23_GML", "P04-20_23.geojson")
    print(f"医療機関GeoJSON読み込み中: {p04_file} ...")
    with open(p04_file, "r", encoding="utf-8") as f:
        p04_raw = json.load(f)

    category_map = {
        1: "病院",
        2: "診療所・クリニック",
        3: "歯科診療所"
    }

    medical_items = []
    medical_geojson_features = []
    for feat in p04_raw["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        cat_code = props.get("P04_001", 2)
        cat_name = category_map.get(cat_code, "医療機関")
        name = props.get("P04_002") or "名称不明医療機関"
        addr = props.get("P04_003") or ""
        dept = props.get("P04_004") or ""

        item = {
            "name": name,
            "category_code": cat_code,
            "category": cat_name,
            "address": addr,
            "departments": dept,
            "lat": round(lat, 6),
            "lon": round(lon, 6)
        }
        medical_items.append(item)

        medical_geojson_features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 6), round(lat, 6)]
            },
            "properties": {
                "name": name,
                "category_code": cat_code,
                "category": cat_name,
                "address": addr,
                "departments": dept
            }
        })

    print(f"医療機関データ標準化完了: {len(medical_items):,} 件")
    med_geojson_out = os.path.join(data_dir, "aichi_medical_facilities.geojson")
    with open(med_geojson_out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": medical_geojson_features}, f, ensure_ascii=False)
    print(f"保存完了: {med_geojson_out}")

    med_csv_out = os.path.join(data_dir, "aichi_medical_facilities.csv")
    with open(med_csv_out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "category_code", "category", "address", "departments", "lat", "lon"])
        writer.writeheader()
        writer.writerows(medical_items)
    print(f"保存完了: {med_csv_out}")

    # 2. 商業施設データ (OSM) の読み込み
    comm_file = os.path.join(data_dir, "aichi_commercial_facilities.geojson")
    print(f"商業施設GeoJSON読み込み中: {comm_file} ...")
    with open(comm_file, "r", encoding="utf-8") as f:
        comm_raw = json.load(f)

    commercial_items = []
    for feat in comm_raw["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        name = props.get("name") or "商業施設"
        category = props.get("category") or "スーパーマーケット"
        brand = props.get("brand") or ""
        commercial_items.append({
            "name": name,
            "category": category,
            "brand": brand,
            "lat": round(lat, 6),
            "lon": round(lon, 6)
        })
    print(f"商業施設データ読み込み完了: {len(commercial_items):,} 件")

    # 3. 空間インデックス構築
    print("空間インデックス構築中...")
    grid_med_all = SpatialGrid(cell_size_deg=0.03)
    grid_hospital = SpatialGrid(cell_size_deg=0.05)
    for m in medical_items:
        grid_med_all.insert(m)
        if m["category_code"] == 1: # 病院
            grid_hospital.insert(m)

    grid_comm_all = SpatialGrid(cell_size_deg=0.03)
    grid_supermarket = SpatialGrid(cell_size_deg=0.04)
    for c in commercial_items:
        grid_comm_all.insert(c)
        if c["category"] == "スーパーマーケット":
            grid_supermarket.insert(c)

    # 4. メッシュGeoJSON読み込み
    mesh_file = os.path.join(data_dir, "aichi_mobility_gap_mesh.geojson")
    print(f"メッシュGeoJSON読み込み中: {mesh_file} ...")
    with open(mesh_file, "r", encoding="utf-8") as f:
        mesh_raw = json.load(f)

    mesh_features = mesh_raw["features"]
    total_meshes = len(mesh_features)
    print(f"対象メッシュ数: {total_meshes:,} 件")

    # 5. 各メッシュの最寄りPOI計算
    print("各メッシュの最寄りPOIアクセシビリティ計算中...")
    
    medical_desert_count = 0     # 医療機関(病院/診療所)まで 1,500m 以上
    medical_desert_elderly = 0
    shopping_desert_count = 0    # スーパーまで 1,000m 以上 (農水省基準)
    shopping_desert_elderly = 0
    double_desert_count = 0      # 交通空白(Lv4/5) かつ 買い物困難
    double_desert_elderly = 0

    for idx, feat in enumerate(mesh_features):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [[]])[0]
        c_lon = sum(pt[0] for pt in coords) / len(coords)
        c_lat = sum(pt[1] for pt in coords) / len(coords)

        # 1. 最寄り医療機関 (病院 or 診療所・クリニック)
        near_med, d_med = grid_med_all.find_nearest(c_lat, c_lon, filter_fn=lambda x: x["category_code"] in [1, 2])
        # 2. 最寄り総合病院 (病院)
        near_hosp, d_hosp = grid_hospital.find_nearest(c_lat, c_lon)
        # 3. 最寄り商業施設 (スーパー or ドラッグストア)
        near_comm, d_comm = grid_comm_all.find_nearest(c_lat, c_lon)
        # 4. 最寄りスーパーマーケット
        near_sm, d_sm = grid_supermarket.find_nearest(c_lat, c_lon)

        p = feat["properties"]
        d_med_int = int(round(d_med)) if near_med else 9999
        d_hosp_int = int(round(d_hosp)) if near_hosp else 9999
        d_comm_int = int(round(d_comm)) if near_comm else 9999
        d_sm_int = int(round(d_sm)) if near_sm else 9999

        # 生活アクセス評価フラグ
        is_shopping_desert = d_sm_int >= 1000
        is_medical_desert = d_med_int >= 1500

        p["d_med"] = d_med_int
        p["med_name"] = near_med["name"] if near_med else ""
        p["med_cat"] = near_med["category"] if near_med else ""
        p["med_dept"] = near_med["departments"] if near_med else ""

        p["d_hosp"] = d_hosp_int
        p["hosp_name"] = near_hosp["name"] if near_hosp else ""

        p["d_comm"] = d_comm_int
        p["comm_name"] = near_comm["name"] if near_comm else ""
        p["comm_cat"] = near_comm["category"] if near_comm else ""

        p["d_supermarket"] = d_sm_int
        p["supermarket_name"] = near_sm["name"] if near_sm else ""

        p["is_shopping_desert"] = is_shopping_desert
        p["is_medical_desert"] = is_medical_desert

        elderly = p.get("elderly", 0)
        gap_level = p.get("gap_level", 1)

        if is_medical_desert:
            medical_desert_count += 1
            medical_desert_elderly += elderly

        if is_shopping_desert:
            shopping_desert_count += 1
            shopping_desert_elderly += elderly

        if is_shopping_desert and gap_level >= 4:
            double_desert_count += 1
            double_desert_elderly += elderly

    elapsed = time.time() - t0
    print(f"最寄りPOI計算完了: 所要時間 {elapsed:.2f} 秒")
    print(f"・医療アクセス困難 (病院/診療所 ≥ 1.5km): {medical_desert_count:,} メッシュ (高齢者: {medical_desert_elderly:,} 人)")
    print(f"・買い物困難 (スーパー ≥ 1km): {shopping_desert_count:,} メッシュ (高齢者: {shopping_desert_elderly:,} 人)")
    print(f"・交通空白 × 買い物難民 重複エリア: {double_desert_count:,} メッシュ (高齢者: {double_desert_elderly:,} 人)")

    # 6. メッシュGeoJSON保存
    print("メッシュGeoJSON保存中...")
    with open(mesh_file, "w", encoding="utf-8") as f:
        json.dump(mesh_raw, f, ensure_ascii=False)
    print(f"保存完了: {mesh_file}")

    # 互換性ファイル nagoya_mobility_gap_mesh.geojson も更新
    nagoya_mesh_file = os.path.join(data_dir, "nagoya_mobility_gap_mesh.geojson")
    with open(nagoya_mesh_file, "w", encoding="utf-8") as f:
        json.dump(mesh_raw, f, ensure_ascii=False)
    print(f"保存完了: {nagoya_mesh_file}")

    # 7. サマリー指標 (summary_metrics.json) の更新
    summary_file = os.path.join(data_dir, "summary_metrics.json")
    with open(summary_file, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # 医療・商業の指標を追加
    summary["medical_count"] = len(medical_items)
    summary["hospital_count"] = sum(1 for m in medical_items if m["category_code"] == 1)
    summary["clinic_count"] = sum(1 for m in medical_items if m["category_code"] == 2)
    summary["dental_count"] = sum(1 for m in medical_items if m["category_code"] == 3)
    summary["commercial_count"] = len(commercial_items)
    summary["supermarket_count"] = sum(1 for c in commercial_items if c["category"] == "スーパーマーケット")
    summary["drugstore_count"] = sum(1 for c in commercial_items if c["category"] == "ドラッグストア")

    summary["medical_desert_mesh_count"] = medical_desert_count
    summary["medical_desert_elderly"] = medical_desert_elderly
    summary["shopping_desert_mesh_count"] = shopping_desert_count
    summary["shopping_desert_elderly"] = shopping_desert_elderly
    summary["double_desert_mesh_count"] = double_desert_count
    summary["double_desert_elderly"] = double_desert_elderly

    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"サマリー指標更新完了: {summary_file}")

    print("\n[SUCCESS] Phase 4 POIデータ統合パイプラインが正常に完了しました！")

if __name__ == "__main__":
    main()
