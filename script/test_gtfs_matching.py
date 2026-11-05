import os
import zipfile
import pandas as pd
import numpy as np

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
zip_path = os.path.join(base_dir, 'data', 'nagoya_citybus_gtfs.zip')
p11_csv = os.path.join(base_dir, 'data', 'aichi_bus_stops.csv')
with zipfile.ZipFile(zip_path) as z:
    with z.open('trips.txt') as f:
        df_trips = pd.read_csv(f)
    weekday_trips = set(df_trips[df_trips['service_id'].str.contains('平日')]['trip_id'])
    
    with z.open('stop_times.txt') as f:
        df_st = pd.read_csv(f, usecols=['trip_id', 'departure_time', 'stop_id'], dtype={'stop_id': str})
    
    with z.open('stops.txt') as f:
        df_stops = pd.read_csv(f, dtype={'stop_id': str})

# 平日のみ
df_st = df_st[df_st['trip_id'].isin(weekday_trips)].copy()
df_st['hour'] = df_st['departure_time'].apply(lambda x: int(str(x).split(':')[0]) if pd.notnull(x) else -1)
df_daytime = df_st[(df_st['hour'] >= 10) & (df_st['hour'] < 16)]

total_counts = df_st.groupby('stop_id').size().rename('daily_trips')
daytime_counts = df_daytime.groupby('stop_id').size().rename('daytime_trips')

gtfs_summary = pd.concat([total_counts, daytime_counts], axis=1).fillna(0).reset_index()
gtfs_summary = gtfs_summary.merge(df_stops[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']], on='stop_id', how='left')
gtfs_summary['daytime_freq_hourly'] = (gtfs_summary['daytime_trips'] / 6.0).round(2)

print(f"GTFS bus stop pole counts: {len(gtfs_summary)}")
print(gtfs_summary.head())

# 2. P11のバス停データ（aichi_bus_stops.csv）を読込
df_p11 = pd.read_csv(p11_csv)
print(f"\nP11 total bus stops: {len(df_p11)}")
p11_nagoya = df_p11[df_p11['operator'].str.contains('名古屋市', na=False)]
print(f"P11 Nagoya City bus stops: {len(p11_nagoya)}")

# NumPyチャンク計算で最近傍マッチング
gtfs_lats = gtfs_summary['stop_lat'].values
gtfs_lons = gtfs_summary['stop_lon'].values
p11_lats = df_p11['stop_lat'].values
p11_lons = df_p11['stop_lon'].values

M_PER_LAT = 111000.0
M_PER_LON = 91000.0

matched = 0
for i in range(0, len(p11_lats), 1000):
    plat = p11_lats[i:i+1000, None]
    plon = p11_lons[i:i+1000, None]
    
    d_lat = (gtfs_lats - plat) * M_PER_LAT
    d_lon = (gtfs_lons - plon) * M_PER_LON
    dists = np.sqrt(np.min(d_lat**2 + d_lon**2, axis=1))
    matched += np.sum(dists <= 150.0)

print(f"P11 stops within 150m of GTFS stop: {matched} / {len(df_p11)} ({matched / len(df_p11) * 100:.1f}%)")
