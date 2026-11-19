import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Query only supermarkets in Aichi
query = """
[out:json][timeout:30];
(
  node["shop"="supermarket"](34.50,136.60,35.45,137.85);
  way["shop"="supermarket"](34.50,136.60,35.45,137.85);
);
out center;
"""

mirrors = [
    'https://lz4.overpass-api.de/api/interpreter',
    'https://z.overpass-api.de/api/interpreter',
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter'
]

data = None
for url in mirrors:
    try:
        print(f"Trying {url} ...")
        req = urllib.request.Request(
            url, 
            data=urllib.parse.urlencode({'data': query}).encode('utf-8'),
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as res:
            data = json.loads(res.read().decode('utf-8'))
            print("Success from", url)
            break
    except Exception as e:
        print("Failed:", url, e)

if data:
    elements = data.get('elements', [])
    print(f"Found {len(elements)} supermarkets in Aichi!")
    stores = []
    for el in elements:
        tags = el.get('tags', {})
        lat = el.get('lat') or (el.get('center', {}).get('lat') if 'center' in el else None)
        lon = el.get('lon') or (el.get('center', {}).get('lon') if 'center' in el else None)
        name = tags.get('name', tags.get('brand', 'スーパー'))
        if lat and lon:
            stores.append({
                'name': name,
                'lat': lat,
                'lon': lon,
                'brand': tags.get('brand', '')
            })
    print("Sample store:", stores[0] if stores else None)
