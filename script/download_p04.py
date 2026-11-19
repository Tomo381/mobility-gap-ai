import urllib.request
import zipfile
import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_dir = os.path.join(base_dir, "data")
dest_dir = os.path.join(data_dir, "P04-20_23_GML")
os.makedirs(dest_dir, exist_ok=True)

zip_url = "https://nlftp.mlit.go.jp/ksj/gml/data/P04/P04-20/P04-20_23_GML.zip"
zip_path = os.path.join(dest_dir, "P04-20_23_GML.zip")

print(f"Downloading P04 medical facilities data from {zip_url} ...")
req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=30) as res, open(zip_path, 'wb') as out:
    out.write(res.read())

print(f"Downloaded {os.path.getsize(zip_path):,} bytes. Extracting ...")
with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(dest_dir)

print(f"Extracted to {dest_dir}. Files:")
for f in os.listdir(dest_dir):
    print(" -", f)
