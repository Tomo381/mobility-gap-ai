import urllib.request
import urllib.parse
import json

# Overpass QL query for supermarkets and drugstores in Aichi prefecture bounding box
# Bounding box: south=34.50, west=136.60, north=35.45, east=137.85
query = """
[out:json][timeout:60];
(
  node["shop"="supermarket"](34.50, 136.60, 35.45, 137.85);
  way["shop"="supermarket"](34.50, 136.60, 35.45, 137.85);
  node["shop"="chemist"](34.50, 136.60, 35.45, 137.85);
  way["shop"="chemist"](34.50, 136.60, 35.45, 137.85);
  node["amenity"="pharmacy"](34.50, 136.60, 35.45, 137.85);
  way["amenity"="pharmacy"](34.50, 136.60, 35.45, 137.85);
);
out center tags;
"""

servers = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter'
]

data = None
for s in servers:
    try:
        print(f"Trying Overpass server: {s} ...")
        req = urllib.request.Request(
            s, 
            data=urllib.parse.urlencode({'data': query}).encode('utf-8'),
            headers={'User-Agent': 'MobilityGapAI/1.0'}
        )
        with urllib.request.urlopen(req, timeout=45) as res:
            data = json.loads(res.read().decode('utf-8'))
            print("Successfully received data!")
            break
    except Exception as e:
        print("Server failed:", e)

if data:
    elements = data.get('elements', [])
    print(f"Total elements retrieved: {len(elements)}")
    supermarkets = []
    pharmacies = []
    for el in elements:
        tags = el.get('tags', {})
        lat = el.get('lat') or (el.get('center', {}).get('lat') if 'center' in el else None)
        lon = el.get('lon') or (el.get('center', {}).get('lon') if 'center' in el else None)
        name = tags.get('name', '名称不明')
        shop = tags.get('shop')
        amenity = tags.get('amenity')
        if shop == 'supermarket':
            supermarkets.append({'name': name, 'lat': lat, 'lon': lon, 'type': 'スーパー'})
        elif shop == 'chemist' or amenity == 'pharmacy':
            pharmacies.append({'name': name, 'lat': lat, 'lon': lon, 'type': 'ドラッグストア・薬局'})
    print(f"Supermarkets: {len(supermarkets)}")
    print(f"Pharmacies/Drugstores: {len(pharmacies)}")
    print("Sample supermarkets:", supermarkets[:3])
