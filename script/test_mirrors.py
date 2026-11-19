import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

query = '[out:json][timeout:20];node["shop"="supermarket"](35.10,136.90,35.15,136.95);out 3;'
endpoints = [
    'https://overpass.openstreetmap.fr/api/interpreter',
    'https://overpass.nchc.org.tw/api/interpreter',
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter'
]

for ep in endpoints:
    try:
        url = ep + '?data=' + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={'User-Agent': 'MobilityGapAI/1.0 (test)'})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as res:
            d = json.loads(res.read().decode('utf-8'))
            print('SUCCESS from:', ep, 'count:', len(d.get('elements', [])))
            break
    except Exception as e:
        print('FAILED:', ep, e)
