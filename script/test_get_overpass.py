import urllib.request
import urllib.parse
import json

query = '[out:json][timeout:25];(node["shop"="supermarket"](35.0,136.9,35.2,137.0););out center 5;'
url = 'https://overpass-api.de/api/interpreter?data=' + urllib.parse.quote(query)

req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
try:
    with urllib.request.urlopen(req, timeout=15) as res:
        print('HTTP status:', res.status)
        d = json.loads(res.read().decode('utf-8'))
        print('Count:', len(d.get('elements', [])))
        for el in d.get('elements', []):
            print(' ', el.get('tags', {}).get('name'))
except Exception as e:
    print('Error:', e)
