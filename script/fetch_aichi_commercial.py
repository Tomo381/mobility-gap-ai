import urllib.request
import urllib.parse
import json
import ssl
import os
import time
import pandas as pd

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_dir = os.path.join(base_dir, "data")

endpoint = 'https://overpass.openstreetmap.fr/api/interpreter'

# 1. Fetch supermarkets
query_supermarkets = """
[out:json][timeout:60];
(
  node["shop"="supermarket"](34.50,136.60,35.45,137.85);
  way["shop"="supermarket"](34.50,136.60,35.45,137.85);
);
out center tags;
"""

# 2. Fetch drugstores
query_drugstores = """
[out:json][timeout:60];
(
  node["shop"="chemist"](34.50,136.60,35.45,137.85);
  way["shop"="chemist"](34.50,136.60,35.45,137.85);
  node["shop"="drugstore"](34.50,136.60,35.45,137.85);
  way["shop"="drugstore"](34.50,136.60,35.45,137.85);
);
out center tags;
"""

def fetch_overpass(q, desc):
    print(f"Fetching {desc} ...")
    url = endpoint + '?data=' + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={'User-Agent': 'MobilityGapAI/1.0 (test)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as res:
                d = json.loads(res.read().decode('utf-8'))
                elements = d.get('elements', [])
                print(f"  -> Got {len(elements):,} elements for {desc}")
                return elements
        except Exception as e:
            print(f"  -> Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    return []

sm_elements = fetch_overpass(query_supermarkets, "Supermarkets")
ds_elements = fetch_overpass(query_drugstores, "Drugstores")

facilities = []
seen = set()

for el in sm_elements:
    tags = el.get('tags', {})
    lat = el.get('lat') or (el.get('center', {}).get('lat') if 'center' in el else None)
    lon = el.get('lon') or (el.get('center', {}).get('lon') if 'center' in el else None)
    if not lat or not lon: continue
    key = (round(lat, 4), round(lon, 4))
    if key in seen: continue
    seen.add(key)
    name = tags.get('name') or tags.get('name:ja') or tags.get('brand') or '名称不明スーパー'
    brand = tags.get('brand', '')
    facilities.append({
        'name': name,
        'category': 'スーパーマーケット',
        'brand': brand,
        'lat': round(lat, 6),
        'lon': round(lon, 6)
    })

for el in ds_elements:
    tags = el.get('tags', {})
    lat = el.get('lat') or (el.get('center', {}).get('lat') if 'center' in el else None)
    lon = el.get('lon') or (el.get('center', {}).get('lon') if 'center' in el else None)
    if not lat or not lon: continue
    key = (round(lat, 4), round(lon, 4))
    if key in seen: continue
    seen.add(key)
    name = tags.get('name') or tags.get('name:ja') or tags.get('brand') or 'ドラッグストア'
    brand = tags.get('brand', '')
    facilities.append({
        'name': name,
        'category': 'ドラッグストア',
        'brand': brand,
        'lat': round(lat, 6),
        'lon': round(lon, 6)
    })

print(f"\nTotal commercial POIs combined: {len(facilities):,}")
df = pd.DataFrame(facilities)
print(df['category'].value_counts())

# Save CSV
csv_path = os.path.join(data_dir, 'aichi_commercial_facilities.csv')
df.to_csv(csv_path, index=False, encoding='utf-8')
print(f"Saved: {csv_path}")

# Save GeoJSON
geojson_features = []
for f in facilities:
    geojson_features.append({
        'type': 'Feature',
        'geometry': {
            'type': 'Point',
            'coordinates': [f['lon'], f['lat']]
        },
        'properties': {
            'name': f['name'],
            'category': f['category'],
            'brand': f['brand']
        }
    })

geojson_path = os.path.join(data_dir, 'aichi_commercial_facilities.geojson')
with open(geojson_path, 'w', encoding='utf-8') as out:
    json.dump({'type': 'FeatureCollection', 'features': geojson_features}, out, ensure_ascii=False)
print(f"Saved: {geojson_path}")
