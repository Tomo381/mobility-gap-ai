import pandas as pd
import json

df = pd.read_csv("data/stops.txt")

features = []

for _, row in df.iterrows():

    features.append({
        "type": "Feature",
        "properties": {
            "stop_id": str(row["stop_id"]),
            "name": row["stop_name"]
        },
        "geometry": {
            "type": "Point",
            "coordinates": [
                float(row["stop_lon"]),
                float(row["stop_lat"])
            ]
        }
    })

geojson = {
    "type": "FeatureCollection",
    "features": features
}

with open(
    "frontend/bus_stops.geojson",
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        geojson,
        f,
        ensure_ascii=False
    )

print(f"{len(features)} stops exported")
