import io
import datetime
import json
import math
import os
import re
import shutil
import urllib.parse
import urllib.request
import requests
import googlemaps
import folium
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont # ImageDraw, ImageFontを追加
import qrcode # QRコード生成用
import streamlit as st

def load_config():
    """`config.json`（ローカル環境）または Streamlit Secrets（クラウド環境）から

    APIキーと境界値パラメーターを読み込む関数
    """
    default_thresholds = {
        "sharp_curve_max_r": 100.0,
        "medium_curve_max_r": 200.0,
        "curve_cluster_distance_m": 80.0,
        "min_straight_length_m": 500.0,
        "max_straight_angle_change_deg": 12.0,
        "steep_slope_min_deg": 5.7,  # 激坂とみなす角度（5.7度 ≒ 勾配10%）
        "min_slope_segment_m": 200.0,  # 激坂としてカウントする最小連続距離(m)
    }

    default_scoring_weights = {
        "distance_scale_km": 5.0,  # 距離スコアの係数
        "hairpin_density_weight": 2.0,  # ヘアピン率の重要度係数
        "medium_curve_density_weight": 2.0,  # 中速コーナー率の重要度係数
        "straight_penalty_weight": 0.5,  # ストレート率の減点係数
    }

    data = {}

    # 1. まずローカルの config.json を確認して存在すれば読み込む
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"config.json の読み込みエラー: {e}")

    # 2. config.json が無い（または読み込めない）場合、Streamlit Secrets を探す
    if not data and hasattr(st, "secrets"):
        try:
            # Secretsに全データを辞書形式で展開
            data = dict(st.secrets)
        except Exception as e:
            print(f"Streamlit Secrets の読み込みエラー: {e}")

    # データから各種設定を取り出し（どちらも取れなかった場合は空の辞書）
    api_key = data.get("api_key")
    user_thresholds = data.get("thresholds", {})
    user_scoring = data.get("scoring_weights", {})

    # デフォルト値とマージし、float型へ変換
    thresholds = {}
    for key, val in default_thresholds.items():
        thresholds[key] = float(user_thresholds.get(key, val))

    scoring_weights = {}
    for key, val in default_scoring_weights.items():
        scoring_weights[key] = float(user_scoring.get(key, val))

    return api_key, thresholds, scoring_weights

def archive_old_outputs(base_dir):
    """過去に生成された output_* ファイル（HTML/JPG問わず全て）を output_old フォルダへ移動する"""
    old_dir = os.path.join(base_dir, "output_old")
    if not os.path.exists(old_dir):
        os.makedirs(old_dir)

    files = os.listdir(base_dir)
    moved_count = 0

    for file in files:
        if file.startswith("output_") and os.path.isfile(os.path.join(base_dir, file)):
            src_path = os.path.join(base_dir, file)
            dst_path = os.path.join(old_dir, file)
            shutil.move(src_path, dst_path)
            moved_count += 1

    if moved_count > 0:
        print(f"[整理完了] 過去の出力ファイル {moved_count} 件を 'output_old/' に移動しました。")

def expand_url(short_url):
    """短縮URLの展開（JSリダイレクトや中間ページ対策を強化）"""
    if not short_url or ("maps.app.goo.gl" not in short_url and "goo.gl" not in short_url):
        return short_url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    }
    try:
        response = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
        final_url = response.url

        # Googleマップ特有の中間ページやメタタグからURLを回収するフォールバック
        if "google.com/maps" not in final_url or "maps.app.goo.gl" in final_url:
            # HTML内から window.location や meta refresh のURLを探す
            match = re.search(r'href="(https://www\.google\.com/maps/dir/[^"]+)"', response.text)
            if match:
                final_url = match.group(1)
            else:
                # 代替パターン
                match_meta = re.search(r'content="0;url=(https://www\.google\.com/maps/[^"]+)"', response.text)
                if match_meta:
                    final_url = match_meta.group(1)

        return final_url
    except Exception as e:
        print(f"URL展開エラー: {e}")
        return short_url

def parse_google_maps_url(url):
    """GoogleマップのURLから出発地・目的地・経由地を多角的に抽出"""
    # 解析前に短縮URLを展開
    if "goo.gl" in url or "maps.app" in url:
        url = expand_url(url)

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    # --- パターン1: saddr / daddr 形式（スマホ共有アプリから生成されるURLなど）---
    if 'saddr' in params and 'daddr' in params:
        origin = urllib.parse.unquote(params['saddr'][0])
        raw_daddr = urllib.parse.unquote(params['daddr'][0])
        
        waypoints = []
        if 'via' in params:
            waypoints.extend([urllib.parse.unquote(v) for v in params['via']])

        # ★追加：daddrの中に「to:」が含まれている場合の分離処理
        # 例: "37.0747350,138.8288350 to:37.0725460,138.8496120"
        # または "+to:" がスペースやプラスに変換されている場合への対策
        # まずは " to:" や "+to:" や "to:" で分割できるようにする
        if "to:" in raw_daddr or "+to:" in raw_daddr:
            # プレースホルダや正規表現を使って to: で分割
            # ここではシンプルに "to:"（前後のプラスやスペースも含めて）でsplitするアプローチ
            import re
            # to: の前後に挟まる空白や "+" を考慮して分割
            parts = re.split(r'[\+\s]*to:', raw_daddr)
            
            if len(parts) >= 2:
                # 最後の要素が真の目的地
                destination = parts[-1].strip()
                # 最後の要素以外（1つ目、あるいは途中のもの）はすべて経由地（waypoints）として追加する
                intermediate_points = [p.strip() for p in parts[:-1] if p.strip()]
                waypoints.extend(intermediate_points)
            else:
                destination = raw_daddr
        else:
            destination = raw_daddr

        # waypointsが空リストならNoneに戻す
        if not waypoints:
            waypoints = None

        return origin, destination, waypoints, "Pattern 1 (saddr/daddr with to: split)"

    # --- パターン2: origin / destination 形式 ---
    if 'origin' in params and 'destination' in params:
        origin = urllib.parse.unquote(params['origin'][0])
        destination = urllib.parse.unquote(params['destination'][0])
        
        waypoints = None
        if 'waypoints' in params:
            waypoints = [urllib.parse.unquote(pt) for pt in params['waypoints'][0].split('|')]
        return origin, destination, waypoints, "Pattern 2 (origin/destination)" # ← 目印を追加

    # --- パターン3: !1d...!2d... (dataパラメータ内座標埋め込み) ---
    coords_in_data = re.findall(r'!1d([0-9\.-]+)!2d([0-9\.-]+)', url)
    if len(coords_in_data) >= 2:
        points = [f"{pt[1]},{pt[0]}" for pt in coords_in_data]
        origin = points[0]
        destination = points[-1]
        waypoints = points[1:-1] if len(points) > 2 else None
        return origin, destination, waypoints, "Pattern 3 (data coords)" # ← 目印を追加

    # --- パターン4: /dir/ パターン（PCブラウザなど） ---
    pattern_dir = r'/dir/([^?]+)'
    match_dir = re.search(pattern_dir, parsed.path if parsed.path else url)
    if match_dir:
        path_segments = match_dir.group(1).split('/')
        cleaned_segments = []
        for seg in path_segments:
            s = urllib.parse.unquote(seg).strip()
            if s and not s.startswith('@') and not s.startswith('data='):
                cleaned_segments.append(re.sub(r'[\+\s]', ' ', s))

        if len(cleaned_segments) >= 2:
            origin = cleaned_segments[0]
            destination = cleaned_segments[-1]
            waypoints = cleaned_segments[1:-1] if len(cleaned_segments) > 2 else None
            return origin, destination, waypoints, "Pattern 4 (/dir/ path)" # ← 目印を追加

    # --- パターン5: URL全体から緯度経度ペアを全抽出する最終フォールバック ---
    lat_lng_pairs = re.findall(r'([0-9]+\.[0-9]+),([0-9]+\.[0-9]+)', url)
    valid_coords = []
    for lat_s, lng_s in lat_lng_pairs:
        lat, lng = float(lat_s), float(lng_s)
        if 20.0 <= lat <= 46.0 and 122.0 <= lng <= 154.0:
            coord_str = f"{lat},{lng}"
            if coord_str not in valid_coords:
                valid_coords.append(coord_str)

    if len(valid_coords) >= 2:
        origin = valid_coords[0]
        destination = valid_coords[-1]
        waypoints = valid_coords[1:-1] if len(valid_coords) > 2 else None
        return origin, destination, waypoints, "Pattern 5 (fallback coords)" # ← 目印を追加

    return None, None, None, "None (Failed)"

def decode_polyline(polyline_str):
    """Polylineのデコード"""
    index = 0
    lat = 0
    lng = 0
    coordinates = []

    while index < len(polyline_str):
        shift = 0
        result = 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_lat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += delta_lat

        shift = 0
        result = 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_lng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += delta_lng

        coordinates.append((lat / 1e5, lng / 1e5))

    return coordinates

def calculate_distance_m(p1, p2):
    """2点間の距離(メートル)を計算"""
    R = 6378137.0
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])

    dlat = lat2 - lat1
    dlng = lng2 - lng1

    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_radius_r(p1, p2, p3):
    """3点から外接円の半径R（曲率半径m）を計算"""
    a = calculate_distance_m(p2, p3)
    b = calculate_distance_m(p1, p3)
    c = calculate_distance_m(p1, p2)

    s = (a + b + c) / 2
    area_sq = s * (s - a) * (s - b) * (s - c)
    if area_sq <= 0:
        return float('inf')

    area = math.sqrt(area_sq)
    if area == 0:
        return float('inf')

    return (a * b * c) / (4 * area)

def calculate_bearing(p1, p2):
    """2点間の進行方位角（0〜360度）を計算"""
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])

    dlng = lng2 - lng1
    y = math.sin(dlng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def cluster_curve_points(points, distance_threshold):
    """近接するカーブ検出地点を1つのグループにまとめる"""
    if not points:
        return []

    clusters = []
    current_cluster = [points[0]]

    for i in range(1, len(points)):
        prev = current_cluster[-1]
        curr = points[i]
        
        if calculate_distance_m(prev, curr) <= distance_threshold:
            current_cluster.append(curr)
        else:
            clusters.append(current_cluster)
            current_cluster = [curr]
    
    if current_cluster:
        clusters.append(current_cluster)

    return [cluster[len(cluster) // 2] for cluster in clusters]

def analyze_curves_and_straights(coordinates, thresholds):
  """前後約10m離れた3点で曲率半径(R)を計算し、カーブおよび直線の解析を実施"""
  sharp_max_r = thresholds["sharp_curve_max_r"]
  medium_max_r = thresholds["medium_curve_max_r"]
  large_max_r = 400.0
  cluster_dist = thresholds["curve_cluster_distance_m"]
  min_straight_len = thresholds["min_straight_length_m"]
  max_angle_change = thresholds["max_straight_angle_change_deg"]

  target_dist = 10.0

  # R値も一緒に保持する構造に変更: (coordinate, R_value)
  raw_sharp = []
  raw_medium = []
  raw_large = []

  n = len(coordinates)

  for i in range(n):
    p2 = coordinates[i]

    p1 = None
    accum_dist_back = 0.0
    for j in range(i - 1, -1, -1):
      d = calculate_distance_m(coordinates[j], coordinates[j + 1])
      accum_dist_back += d
      if accum_dist_back >= target_dist:
        p1 = coordinates[j]
        break

    p3 = None
    accum_dist_forward = 0.0
    for k in range(i + 1, n):
      d = calculate_distance_m(coordinates[k - 1], coordinates[k])
      accum_dist_forward += d
      if accum_dist_forward >= target_dist:
        p3 = coordinates[k]
        break

    if p1 is None or p3 is None:
      continue

    r = calculate_radius_r(p1, p2, p3)

    if r <= sharp_max_r:
      raw_sharp.append((p2, r))
    elif sharp_max_r < r <= medium_max_r:
      raw_medium.append((p2, r))
    elif medium_max_r < r <= large_max_r:
      raw_large.append((p2, r))

  # --- 「最もRが小さい点（一番キツい頂点）」を代表として残すクラスタリング関数 ---
  def select_peak_points(point_r_tuples, dist_threshold):
    if not point_r_tuples:
      return []

    # Rが小さい順（最も急なカーブ順）にソート
    sorted_pts = sorted(point_r_tuples, key=lambda x: x[1])
    selected = []

    for pt, r in sorted_pts:
      # すでに選ばれた強い頂点から dist_threshold 以内にある点は除外（重複防止）
      if not any(
          calculate_distance_m(pt, sel_pt) <= dist_threshold
          for sel_pt in selected
      ):
        selected.append(pt)

    return selected

  # 1. 最も急な点（頂点）を優先的に抽出
  sharp_curves = select_peak_points(raw_sharp, cluster_dist)

  # 2. 中速コーナーの選出（確定したヘアピンの近くにあるものは除く）
  raw_medium_filtered = [
      item
      for item in raw_medium
      if not any(
          calculate_distance_m(item[0], sp) <= cluster_dist
          for sp in sharp_curves
      )
  ]
  medium_curves = select_peak_points(raw_medium_filtered, cluster_dist)

  # 3. 緩大コーナーの選出（確定済みのヘアピン・中速の近くにあるものは除く）
  all_higher = sharp_curves + medium_curves
  raw_large_filtered = [
      item
      for item in raw_large
      if not any(
          calculate_distance_m(item[0], hp) <= cluster_dist
          for hp in all_higher
      )
  ]
  large_curves = select_peak_points(raw_large_filtered, cluster_dist)

  # --- 直線区間の計算（既存通り） ---
  straight_segments = []
  if len(coordinates) >= 2:
    current_segment = [coordinates[0]]
    accumulated_dist = 0.0

    for i in range(len(coordinates) - 1):
      p_curr = coordinates[i]
      p_next = coordinates[i + 1]
      dist = calculate_distance_m(p_curr, p_next)

      if len(current_segment) >= 2:
        prev_bearing = calculate_bearing(
            current_segment[-2], current_segment[-1]
        )
        curr_bearing = calculate_bearing(p_curr, p_next)

        angle_diff = abs(curr_bearing - prev_bearing)
        if angle_diff > 180:
          angle_diff = 360 - angle_diff

        if angle_diff > max_angle_change:
          if accumulated_dist >= min_straight_len:
            straight_segments.append({
                "coords": current_segment.copy(),
                "length_m": round(accumulated_dist, 1),
            })
          current_segment = [p_curr]
          accumulated_dist = 0.0

      current_segment.append(p_next)
      accumulated_dist += dist

    if accumulated_dist >= min_straight_len:
      straight_segments.append({
          "coords": current_segment.copy(),
          "length_m": round(accumulated_dist, 1),
      })

  return sharp_curves, medium_curves, large_curves, straight_segments

def get_elevation_data(coordinates, api_key):
    """Google Elevation API を使用して全座標の標高（メートル）を取得"""
    gmaps = googlemaps.Client(key=api_key)
    try:
        locations = [(pt[0], pt[1]) for pt in coordinates]
        results = []
        chunk_size = 400
        for i in range(0, len(locations), chunk_size):
            chunk = locations[i:i + chunk_size]
            res = gmaps.elevation(chunk)
            results.extend(res)
            
        return [item["elevation"] for item in results]
    except Exception as e:
        print(f"標高データの取得に失敗しました: {e}")
        return []


def analyze_steep_slopes(coordinates, elevations, thresholds):
  """連続した「上り」または「下り」区間を抽出し、指定角度および距離を超える「激坂」を割り出す"""
  steep_min_deg = thresholds["steep_slope_min_deg"]
  min_slope_m = thresholds["min_slope_segment_m"]

  if not elevations or len(coordinates) != len(elevations):
    return []

  steep_slopes = []
  current_mode = None  # 'climb' (上り), 'descent' (下り), None (平坦・未設定)
  start_idx = 0
  current_dist = 0.0

  def process_slope_segment(start_i, end_i, length_m, mode):
    """区間の斜度を計算し、条件を満たせばリストに追加する内部関数"""
    if length_m < min_slope_m or mode is None:
      return

    elev_diff = elevations[end_i] - elevations[start_i]
    if elev_diff == 0:
      return

    # 斜度（角度）の計算
    slope_angle_deg = math.degrees(math.atan(elev_diff / length_m))

    # 上り・下り問わず指定角度（絶対値）を超えているか判定
    if abs(slope_angle_deg) >= steep_min_deg:
      steep_slopes.append({
          "coords": coordinates[start_i : end_i + 1],
          "start_coords": coordinates[start_i],
          "end_coords": coordinates[end_i],
          "length_m": round(length_m, 1),
          "elev_diff_m": round(elev_diff, 1),
          "angle_deg": round(slope_angle_deg, 1),
          "slope_type": "climb" if mode == "climb" else "descent",  # 種別を追加
      })

  for i in range(len(coordinates) - 1):
    p1, p2 = coordinates[i], coordinates[i + 1]
    e1, e2 = elevations[i], elevations[i + 1]

    seg_dist = calculate_distance_m(p1, p2)

    # 現在のセグメントの傾斜方向を判定
    if e2 > e1:
      seg_mode = "climb"
    elif e2 < e1:
      seg_mode = "descent"
    else:
      seg_mode = None  # 完全な平坦

    # 状態（上り・下り・平坦）が変化したかの判定
    if seg_mode != current_mode:
      # 直前までの区間を処理・確定
      if current_mode is not None:
        process_slope_segment(start_idx, i, current_dist, current_mode)

      # 新しい区間の開始
      current_mode = seg_mode
      start_idx = i
      current_dist = seg_dist if seg_mode is not None else 0.0
    else:
      # 同じ状態が継続中
      if current_mode is not None:
        current_dist += seg_dist

  # ループ終了後の最終区間の処理
  if current_mode is not None:
    process_slope_segment(
        start_idx, len(coordinates) - 1, current_dist, current_mode
    )

  return steep_slopes

def calculate_metrics_and_scores(selected_route, sharp_curves, medium_curves, straight_segments, steep_slopes, scoring_config):
    """①〜⑥の指標を計算し、上限撤廃で算出する"""
    dist_km = selected_route["distance_km"]
    
    duration_str = selected_route["duration"]
    hours = 0
    mins = 0
    if "時間" in duration_str:
        parts = duration_str.split("時間")
        hours = float(parts[0])
        if "分" in parts[1]:
            mins = float(parts[1].replace("分", ""))
    elif "分" in duration_str:
        mins = float(duration_str.replace("分", ""))
    total_hours = hours + (mins / 60.0)
    
    val_distance = dist_km
    dist_scale = scoring_config.get("distance_scale_km", 5.0)
    score_distance = max(0.0, (val_distance / dist_scale)) if val_distance > 0 else 0.0

    total_straight_m = sum(seg["length_m"] for seg in straight_segments)
    val_straight_rate = (total_straight_m / (dist_km * 1000)) * 100 if dist_km > 0 else 0.0
    score_straight = max(0.0, val_straight_rate / 10.0) if val_straight_rate > 0 else 0.0

    val_hairpin_density = len(sharp_curves) / dist_km if dist_km > 0 else 0.0
    score_hairpin = max(0.0, val_hairpin_density * 2.0) if val_hairpin_density > 0 else 0.0

    val_medium_density = len(medium_curves) / dist_km if dist_km > 0 else 0.0
    score_medium = max(0.0, val_medium_density * 2.0) if val_medium_density > 0 else 0.0

    total_steep_m = sum(slope["length_m"] for slope in steep_slopes)
    val_steep_rate = (total_steep_m / (dist_km * 1000)) * 100 if dist_km > 0 else 0.0
    score_steep = max(0.0, val_steep_rate) if val_steep_rate > 0 else 0.0

    val_avg_speed = dist_km / total_hours if total_hours > 0 else 0.0
    score_speed = max(0.0, val_avg_speed / 10.0) if val_avg_speed > 0 else 0.0

    metrics = [
        {"name": "①総走行距離", "raw": f"{round(val_distance, 1)} km", "score": score_distance},
        {"name": "②ストレート率", "raw": f"{round(val_straight_rate, 1)} %", "score": score_straight},
        {"name": "③ヘアピン率", "raw": f"{round(val_hairpin_density, 2)} 箇所/km", "score": score_hairpin},
        {"name": "④中速コーナー率", "raw": f"{round(val_medium_density, 2)} 箇所/km", "score": score_medium},
        {"name": "⑤激坂(上下)率", "raw": f"{round(val_steep_rate, 1)} %", "score": score_steep},
        {"name": "⑥平均速度", "raw": f"{round(val_avg_speed, 1)} km/h", "score": score_speed},
    ]

    return metrics

def render_bar(score):
    """スコアを「■」と「□」のバー表現に変換する"""
    if score <= 0:
        return "□" * 10
    filled_count = round(score)
    if filled_count <= 0:
        return "□" * 10
    return "■" * filled_count + "□" * max(0, 10 - filled_count)

def get_all_routes_info(origin, destination, waypoints, api_key):
    """Directions API でルート情報取得"""
    gmaps = googlemaps.Client(key=api_key)
    
    try:
        directions_result = gmaps.directions(
            origin,
            destination,
            waypoints=waypoints,
            mode="driving",
            alternatives=True,
            language="ja"
        )

        if not directions_result:
            print("該当する経路が見つかりませんでした。")
            return None

        routes_list = []
        for idx, route in enumerate(directions_result, 1):
            total_distance_m = sum(leg["distance"]["value"] for leg in route["legs"])
            total_duration_s = sum(leg["duration"]["value"] for leg in route["legs"])
            
            dist_km = round(total_distance_m / 1000, 1)
            hours = total_duration_s // 3600
            mins = (total_duration_s % 3600) // 60
            duration_str = f"{hours}時間{mins}分" if hours > 0 else f"{mins}分"

            summary = route.get("summary", f"ルート {idx}")
            overview_polyline = route.get("overview_polyline", {}).get("points", "")

            routes_list.append({
                "index": idx,
                "summary": summary,
                "distance": f"{dist_km}km",
                "distance_km": dist_km,
                "duration": duration_str,
                "polyline": overview_polyline,
                "raw_route": route
            })

        return routes_list

    except googlemaps.exceptions.ApiError as e:
        print(f"\n[APIエラー] 検索に失敗しました。詳細: {e}")
        return None

def fetch_high_res_coords(selected_route, api_key):
    """距離に応じて分割数を変更"""
    dist_km = selected_route["distance_km"]
    base_coords = decode_polyline(selected_route["polyline"])

    if dist_km <= 35.0:
        return base_coords

    split_count = 2 if dist_km <= 70.0 else 3
    print(f"\n[高精度モード発動] 総距離 {dist_km}km のため、ルートを {split_count} 分割して高細度データを取得中...")

    n = len(base_coords)
    sub_targets = []

    if split_count == 2:
        sub_targets = [
            (base_coords[0], base_coords[n // 2]),
            (base_coords[n // 2], base_coords[-1])
        ]
    elif split_count == 3:
        sub_targets = [
            (base_coords[0], base_coords[n // 3]),
            (base_coords[n // 3], base_coords[(2 * n) // 3]),
            (base_coords[(2 * n) // 3], base_coords[-1])
        ]

    gmaps = googlemaps.Client(key=api_key)
    combined_coords = []

    for idx, (start_pt, end_pt) in enumerate(sub_targets, 1):
        orig_str = f"{start_pt[0]},{start_pt[1]}"
        dest_str = f"{end_pt[0]},{end_pt[1]}"
        
        try:
            res = gmaps.directions(orig_str, dest_str, mode="driving", language="ja")
            if res:
                sub_poly = res[0].get("overview_polyline", {}).get("points", "")
                sub_coords = decode_polyline(sub_poly)
                
                if combined_coords:
                    combined_coords.extend(sub_coords[1:])
                else:
                    combined_coords.extend(sub_coords)
                print(f"  ├─ 分割区間 {idx}/{split_count} 取得完了 ({len(sub_coords)} ポイント)")
        except Exception as e:
            print(f"  └─ 分割区間 {idx} の取得失敗、ベース座標を代替使用します: {e}")
            return base_coords

    print(f"[高精度モード完了] 計 {len(combined_coords)} ポイントの精密座標を取得しました。")
    return combined_coords

def sanitize_filename_component(text):
    text = re.sub(r'[\/:*?"<>|]', '_', text)
    text = re.sub(r'\s+', '', text)
    return text


from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

def create_radar_chart_image(metrics, title_text="ルート特性"):
  """真円が崩れないように余白とタイトル位置を固定したレーダーチャート生成関数"""
  import os
  from matplotlib.font_manager import FontProperties

  # OSに合わせて存在する日本語フォントを自動で選択
  font_path_win = "C:\\Windows\\Fonts\\meiryob.ttc"
  font_path_linux = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

  if os.path.exists(font_path_win):
    jp_font = FontProperties(fname=font_path_win)
  elif os.path.exists(font_path_linux):
    jp_font = FontProperties(fname=font_path_linux)
  else:
    # どちらも見つからない場合はフォントファミリー名で検索
    jp_font = FontProperties(family="sans-serif")

  labels = [m["name"] for m in metrics]
  scores = [m["score"] for m in metrics]
  raw_values = [m["raw"] for m in metrics]

  num_vars = len(labels)
  angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()

  scores = list(scores) + [scores[0]]
  angles = list(angles) + [angles[0]]

  # 図のサイズを正方形（8x8インチ）に固定
  fig = Figure(figsize=(8, 8), dpi=100)
  canvas = FigureCanvasAgg(fig)

  # グラフの位置（rect=[left, bottom, width, height]）を明示的に指定して、上がどれだけ長くても円を真円に固定
  ax = fig.add_axes([0.1, 0.1, 0.8, 0.78], polar=True)

  ax.set_theta_offset(np.pi / 2)
  ax.set_theta_direction(-1)

  ax.set_xticks(angles[:-1])
  ax.set_xticklabels(
      labels,
      fontproperties=jp_font,
      size=20,
      fontweight="bold",
      color="#111111",
  )
  ax.tick_params(axis="x", pad=15)

  ax.set_rlabel_position(0)
  ax.set_rticks([2, 4, 6, 8, 10])
  ax.set_yticklabels(["", "", "", "", ""], color="grey")
  ax.set_ylim(0, 10)

  ax.plot(angles, scores, linewidth=3.0, linestyle="solid", color="#1f77b4")
  ax.fill(angles, scores, color="#1f77b4", alpha=0.3)

  for angle, score, raw_text in zip(angles[:-1], scores[:-1], raw_values):
    text_r = score + 1.5 if score < 7.5 else score - 1.8
    text_r = max(1.5, min(text_r, 9.0))

    ax.text(
        angle,
        text_r,
        str(raw_text),
        fontproperties=jp_font,
        horizontalalignment="center",
        verticalalignment="center",
        size=18,
        fontweight="bold",
        color="#000000",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor="white",
            edgecolor="#cccccc",
            alpha=0.9,
        ),
    )

  # --- タイトル文字列の整形 ---
  display_title = str(title_text).strip()
  if not (display_title.startswith("【") and display_title.endswith("】")):
    display_title = f"【{display_title}】"

  # タイトルの位置を y=1.08 に固定
  ax.set_title(
      display_title,
      fontproperties=jp_font,
      size=24,
      fontweight="bold",
      y=1.08,
      pad=10,
  )

  # tight_layout() は使わず、そのまま画像バッファへ保存
  buf = io.BytesIO()
  fig.savefig(buf, format="jpg", dpi=100)
  buf.seek(0)

  radar_img = Image.open(buf).copy()
  buf.close()

  return radar_img


def generate_route_image_memory(
    selected_route,
    coords,
    sharp_points,
    medium_points,
    straight_segments,
    steep_slopes,
    thresholds,
    metrics,
    api_key,
    custom_summary=None,
):
  """ファイルを一切ディスクに保存せず、メモリ上でレーダーチャートと地図を合成したPillow画像と、

  FoliumのHTML文字列を生成して返す
  """
  import os

  # フォントパスの定義（Windows用・Linux用）
  font_path_win = "C:\\Windows\\Fonts\\meiryob.ttc"
  font_path_linux = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

  # --- タイトルテキストの確定処理 ---
  if (
      custom_summary
      and custom_summary.strip()
      and custom_summary.strip() != "自動"
  ):
    summary_text = custom_summary.strip()
  else:
    summary_text = selected_route.get("summary", "")

  # --- 1. HTMLマップ出力（メモリ上の文字列として生成） ---
  start_lat, start_lng = coords[0]
  m = folium.Map(location=[start_lat, start_lng], zoom_start=11)
  folium.PolyLine(
      coords, color="blue", weight=4, opacity=0.6, popup="全ルート"
  ).add_to(m)

  for idx, seg in enumerate(straight_segments, 1):
    folium.PolyLine(
        seg["coords"],
        color="green",
        weight=7,
        opacity=0.8,
        popup=f"直線 #{idx}",
    ).add_to(m)
  for idx, slope in enumerate(steep_slopes, 1):
    folium.PolyLine(
        slope["coords"],
        color="purple",
        weight=8,
        opacity=0.8,
        popup=f"激坂 #{idx}",
    ).add_to(m)
  for pt in sharp_points:
    folium.CircleMarker(
        location=[pt[0], pt[1]],
        radius=6,
        color="red",
        fill=True,
        fill_color="red",
    ).add_to(m)
  for pt in medium_points:
    folium.CircleMarker(
        location=[pt[0], pt[1]],
        radius=5,
        color="orange",
        fill=True,
        fill_color="yellow",
    ).add_to(m)

  html_content = m._repr_html_()

  # --- 2. 静止画マップ (640x600) をメモリ上で取得 ---
  base_url = "https://maps.googleapis.com/maps/api/staticmap"
  map_url = f"{base_url}?size=640x600&maptype=roadmap&format=jpg&path=color:0x0000ffff|weight:6|enc:{selected_route['polyline']}&key={api_key}"

  img_map = None
  try:
    req = urllib.request.urlopen(map_url)
    map_buf = io.BytesIO(req.read())
    img_map = Image.open(map_buf).resize((640, 600))
  except Exception as e:
    print(f"[マップ画像取得エラー]: {e}")
    return None, None

  # --- 3. レーダーチャート画像生成 (メモリ上) ---
  img_radar = create_radar_chart_image(
      metrics, title_text=summary_text
  ).resize((640, 640))

  # --- 4. Pillowで合成、オーバーレイ描画 ---
  try:
    img_map_with_overlay = img_map.convert("RGBA")
    overlay_draw = ImageDraw.Draw(img_map_with_overlay)

    # 距離・時間表示のフォント設定（自動判定）
    if os.path.exists(font_path_win):
      font_main = ImageFont.truetype(font_path_win, 30)
      font_unit = ImageFont.truetype(font_path_win, 20)
    elif os.path.exists(font_path_linux):
      font_main = ImageFont.truetype(font_path_linux, 30)
      font_unit = ImageFont.truetype(font_path_linux, 20)
    else:
      font_main = ImageFont.load_default()
      font_unit = ImageFont.load_default()

    text_dist = selected_route["distance"]
    text_dur = selected_route["duration"]

    margin_right = 10
    margin_top = 10
    p_info_x = 640 - margin_right
    p_info_y = margin_top

    dist_value_text = text_dist.replace("km", "")
    dist_value_bbox = overlay_draw.textbbox(
        (0, 0), dist_value_text, font=font_main
    )
    dist_value_width = dist_value_bbox[2] - dist_value_bbox[0]

    dist_unit_text = "km"
    dist_unit_bbox = overlay_draw.textbbox(
        (0, 0), dist_unit_text, font=font_unit
    )
    dist_unit_width = dist_unit_bbox[2] - dist_unit_bbox[0]

    total_dist_width = dist_value_width + dist_unit_width

    dur_bbox = overlay_draw.textbbox((0, 0), text_dur, font=font_main)
    dur_width = dur_bbox[2] - dur_bbox[0]
    dur_height = dur_bbox[3] - dur_bbox[1]

    bg_width = max(total_dist_width, dur_width) + 20
    bg_height = (p_info_y + 35 + dur_height + 10) + 10
    bg_x1 = 640 - bg_width
    bg_y1 = 0
    bg_x2 = 640
    bg_y2 = bg_height + 10

    bg_layer = Image.new("RGBA", (640, 600), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg_layer)
    bg_draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=(0, 0, 0, 180))

    img_map_with_overlay = Image.alpha_composite(
        img_map_with_overlay, bg_layer
    )
    overlay_draw = ImageDraw.Draw(img_map_with_overlay)

    line1_y = p_info_y + 10
    overlay_draw.text(
        (640 - margin_right - total_dist_width, line1_y),
        dist_value_text,
        font=font_main,
        fill=(255, 255, 255, 255),
    )
    overlay_draw.text(
        (640 - margin_right - dist_unit_width, line1_y + 10),
        dist_unit_text,
        font=font_unit,
        fill=(255, 255, 255, 255),
    )

    line2_y = line1_y + 40
    overlay_draw.text(
        (640 - margin_right - dur_width, line2_y),
        text_dur,
        font=font_main,
        fill=(255, 255, 255, 255),
    )

    img_map_final = img_map_with_overlay.convert("RGB")

    # 上下に結合 (640 x 1240)
    combined_img = Image.new("RGB", (640, 1240))
    combined_img.paste(img_radar, (0, 0))
    combined_img.paste(img_map_final, (0, 640))

    # ロゴ overlay 描画処理（自動判定）
    if os.path.exists(font_path_win):
      font_logo = ImageFont.truetype(font_path_win, 22)
    elif os.path.exists(font_path_linux):
      font_logo = ImageFont.truetype(font_path_linux, 22)
    else:
      font_logo = ImageFont.load_default()

    logo_text = "RoadRadarChart"

    draw_temp = ImageDraw.Draw(combined_img)
    bbox_logo = draw_temp.textbbox((0, 0), logo_text, font=font_logo)
    logo_w = bbox_logo[2] - bbox_logo[0]
    logo_h = bbox_logo[3] - bbox_logo[1]

    logo_x = (640 - logo_w) // 2
    logo_y = 1240 - logo_h - 10

    padding_x, padding_y = 12, 4
    logo_bg_layer = Image.new("RGBA", (640, 1240), (0, 0, 0, 0))
    logo_bg_draw = ImageDraw.Draw(logo_bg_layer)
    logo_bg_draw.rounded_rectangle(
        [
            logo_x - padding_x,
            logo_y - padding_y,
            logo_x + logo_w + padding_x,
            logo_y + logo_h + padding_y,
        ],
        radius=6,
        fill=(0, 0, 0, 180),
    )

    combined_img = Image.alpha_composite(
        combined_img.convert("RGBA"), logo_bg_layer
    ).convert("RGB")
    draw_final = ImageDraw.Draw(combined_img)
    draw_final.text(
        (logo_x, logo_y), logo_text, font=font_logo, fill=(255, 255, 255)
    )

    return combined_img, html_content

  except Exception as e:
    print(f"[画像結合エラー]: {e}")
    return None, None

def save_outputs(selected_route, coords, sharp_points, medium_points, straight_segments, steep_slopes, thresholds, metrics, api_key, base_dir, custom_summary=None, maps_url=None):
    """
    HTMLと、レーダー（QR付き）上・地図下（情報オーバーレイ付き）の縦長結合JPG画像を出力
    selected_route: ルート情報（距離・時間のオーバーレイ用）
    maps_url: スマホ誘導用のGoogleマップURL（QRコード用）
    """
    archive_old_outputs(base_dir)

    now_str = datetime.datetime.now().strftime("%y%m%d%H%M%S")
    
    if custom_summary and custom_summary.strip():
        summary_text = custom_summary.strip()
    else:
        summary_text = selected_route["summary"]

    summary_clean = sanitize_filename_component(summary_text)
    distance_clean = sanitize_filename_component(selected_route["distance"])
    duration_clean = sanitize_filename_component(selected_route["duration"])

    # --- 1. HTMLマップ出力 ---
    html_filename = f"output_map_{now_str}_{summary_clean}_{distance_clean}.html"
    html_path = os.path.join(base_dir, html_filename)

    start_lat, start_lng = coords[0]
    m = folium.Map(location=[start_lat, start_lng], zoom_start=11)
    folium.PolyLine(coords, color="blue", weight=4, opacity=0.6, popup="全ルート").add_to(m)

    for idx, seg in enumerate(straight_segments, 1):
        folium.PolyLine(seg["coords"], color="green", weight=7, opacity=0.8, popup=f"直線 #{idx}").add_to(m)
    for idx, slope in enumerate(steep_slopes, 1):
        folium.PolyLine(slope["coords"], color="purple", weight=8, opacity=0.8, popup=f"激坂 #{idx}").add_to(m)
    for pt in sharp_points:
        folium.CircleMarker(location=[pt[0], pt[1]], radius=6, color="red", fill=True, fill_color="red").add_to(m)
    for pt in medium_points:
        folium.CircleMarker(location=[pt[0], pt[1]], radius=5, color="orange", fill=True, fill_color="yellow").add_to(m)

    m.save(html_path)

    # --- 2. 静止画マップ (640x600) 取得 ---
    map_jpg_filename = f"temp_map_{now_str}.jpg"
    map_jpg_path = os.path.join(base_dir, map_jpg_filename)
    
    base_url = "https://maps.googleapis.com/maps/api/staticmap"
    # polylineの weight:6 (地図が見やすいように少し太く), color:0x0000ffff (青)
    map_url = f"{base_url}?size=640x600&maptype=roadmap&format=jpg&path=color:0x0000ffff|weight:6|enc:{selected_route['polyline']}&key={api_key}"
    
    try:
        urllib.request.urlretrieve(map_url, map_jpg_path)
    except Exception as e:
        print(f"[マップ画像取得エラー]: {e}")
        return

    # --- 3. レーダーチャート画像生成 ( temp_radar ) ---
    radar_jpg_filename = f"temp_radar_{now_str}.jpg"
    radar_jpg_path = os.path.join(base_dir, radar_jpg_filename)
    create_radar_chart_image(metrics, radar_jpg_path, title_text=summary_text)

    # --- 5. Pillowで合成、オーバーレイ、および結合 ---
    combined_jpg_filename = f"output_route_{now_str}_{summary_clean}_{distance_clean}_{duration_clean}.jpg"
    combined_jpg_path = os.path.join(base_dir, combined_jpg_filename)

    try:
        # 画像を読み込み
        img_radar = Image.open(radar_jpg_path).resize((640, 640)) # レーダーは正方形
        img_map = Image.open(map_jpg_path).resize((640, 600))   # 地図

        # --- 合成2：地図画像の右上に距離と時間のオーバーレイを描画 ---
        # 描画用のオブジェクトを作成（アルファチャンネルを扱うためRGBAモードに変換）
        img_map_with_overlay = img_map.convert("RGBA")
        overlay_draw = ImageDraw.Draw(img_map_with_overlay)

        # フォントの設定（環境に応じてフォントを取得）
        try:
            # Linux (Streamlit Cloud) / Windows / Mac 等のフォントフォールバック処理
            font_path = "C:\\Windows\\Fonts\\meiryob.ttc"
            font_main = ImageFont.truetype(font_path, 30)
            font_unit = ImageFont.truetype(font_path, 20)
        except (IOError, OSError):
            try:
                # Streamlit Cloud (Linux) で packages.txt (fonts-noto-cjk) を入れた場合のフォントパス
                font_path_linux = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
                font_main = ImageFont.truetype(font_path_linux, 30)
                font_unit = ImageFont.truetype(font_path_linux, 20)
            except (IOError, OSError):
                # どちらもない場合はデフォルトフォント
                font_main = ImageFont.load_default()
                font_unit = ImageFont.load_default()

        # 表示するテキストを準備（例: "30km\n37分"）
        text_dist = selected_route['distance'] # "26.6km"
        text_dur = selected_route['duration']  # "34分"
        
        # テキストの描画位置（地図画像(640x600)に対する相対位置。右上から少しマージンを取る）
        # テキスト全体の幅と高さを計算して配置
        # ImageDraw.textbbox() を使用 (PIL >= 8.0.0)
        # 距離と時間を分けて描画（単位を少し小さくするため）
        
        # 描画位置の定義 (右上起点)
        margin_right = 10
        margin_top = 10
        p_info_x = 640 - margin_right # 右端（ここから左に文字が進む）
        p_info_y = margin_top

        # テキストを描画（白い文字）
        # PILのImageDrawは標準で右寄せ描画をサポートしていないため、textbboxで幅を取得して位置を調整
        
        # 1行目: 距離 (例: "26.6km")
        # "km" 単位を少し小さく表示する実装例
        
        # "26.6" の部分の幅
        dist_value_text = text_dist.replace("km", "")
        dist_value_bbox = overlay_draw.textbbox((0, 0), dist_value_text, font=font_main)
        dist_value_width = dist_value_bbox[2] - dist_value_bbox[0]
        
        # "km" の部分の幅
        dist_unit_text = "km"
        dist_unit_bbox = overlay_draw.textbbox((0, 0), dist_unit_text, font=font_unit)
        dist_unit_width = dist_unit_bbox[2] - dist_unit_bbox[0]

        total_dist_width = dist_value_width + dist_unit_width
        
        # 2行目: 時間 (例: "34分")
        dur_bbox = overlay_draw.textbbox((0, 0), text_dur, font=font_main)
        dur_width = dur_bbox[2] - dur_bbox[0]
        dur_height = dur_bbox[3] - dur_bbox[1]

        # --- オーバーレイ背景（半透明の黒い四角形）を描画 ---
        # テキストの背景範囲を計算
        bg_width = max(total_dist_width, dur_width) + 20 # 左右に10px余白
        bg_height = (p_info_y + 35 + dur_height + 10) + 10 # 2行分の高さ + 上下10pxマージン
        bg_x1 = 640 - bg_width
        bg_y1 = 0
        bg_x2 = 640
        bg_y2 = bg_height + 10
        
        # アルファチャンネル(透明度)を持つレイヤーを作成して背景を描画
        bg_layer = Image.new("RGBA", (640, 600), (0, 0, 0, 0))
        bg_draw = ImageDraw.Draw(bg_layer)
        bg_draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=(0, 0, 0, 180)) # RGBA (黒, 透明度180/255)

        # 地図画像と背景レイヤーを合成
        img_map_with_overlay = Image.alpha_composite(img_map_with_overlay, bg_layer)
        overlay_draw = ImageDraw.Draw(img_map_with_overlay) # 合成後に再度Drawオブジェクトを作成

        # --- テキスト本体を描画 ---
        # 1行目（距離）
        line1_y = p_info_y + 10
        overlay_draw.text((640 - margin_right - total_dist_width, line1_y), dist_value_text, font=font_main, fill=(255, 255, 255, 255))
        overlay_draw.text((640 - margin_right - dist_unit_width, line1_y + 10), dist_unit_text, font=font_unit, fill=(255, 255, 255, 255)) # kmは少し下げる

        # 2行目（時間）
        line2_y = line1_y + 40 # 1行目から40px下
        overlay_draw.text((640 - margin_right - dur_width, line2_y), text_dur, font=font_main, fill=(255, 255, 255, 255))


        # 合成したRGBA画像をRGBモードに戻す
        img_map_final = img_map_with_overlay.convert("RGB")

        # --- 結合：全体を 640 x 1240 に調整して上下に結合 ---
        combined_img = Image.new('RGB', (640, 1240))
        combined_img.paste(img_radar, (0, 0)) # 上にレーダー（QR付き）
        combined_img.paste(img_map_final, (0, 640)) # 下に地図（オーバーレイ付き）



        # --------------------------------------------------
        # ★ ロゴ描画処理（直接描画で確実に反映）
        # --------------------------------------------------
        logo_text = "RoadRadarChart"
        
        try:
            # メイリオ太字（サイズ24pt）
            font_logo = ImageFont.truetype("C:\\Windows\\Fonts\\meiryob.ttc", 24)
        except IOError:
            try:
                # meiryo.ttc や arial.ttf などの代替
                font_logo = ImageFont.truetype("arial.ttf", 24)
            except IOError:
                font_logo = ImageFont.load_default()

        # 一時的にRGBAに変換して黒背景＋白文字を描画
        img_rgba = combined_img.convert("RGBA")
        overlay = Image.new("RGBA", img_rgba.size, (255, 255, 255, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        # テキストのサイズを取得
        bbox_logo = draw_overlay.textbbox((0, 0), logo_text, font=font_logo)
        logo_w = bbox_logo[2] - bbox_logo[0]
        logo_h = bbox_logo[3] - bbox_logo[1]

        # 配置位置（下中央）
        logo_x = (640 - logo_w) // 2
        logo_y = 1240 - logo_h - 30

        # 背景の黒い角丸座布団（パディング付き）
        px, py = 14, 6
        draw_overlay.rounded_rectangle(
            [logo_x - px, logo_y - py, logo_x + logo_w + px, logo_y + logo_h + py],
            radius=6,
            fill=(0, 0, 0, 200) # 黒（不透明度 約80%）
        )

        # 白文字を描画
        draw_overlay.text((logo_x, logo_y), logo_text, font=font_logo, fill=(255, 255, 255, 255))

        # 画像を重ね合わせてRGBに戻す
        combined_img = Image.alpha_composite(img_rgba, overlay).convert("RGB")
        # --------------------------------------------------



        combined_img.save(combined_jpg_path, quality=95)
        print(f"\n[JPG保存完了] 地図情報付き縦長画像 (640x1240): {combined_jpg_filename}")
        
    except Exception as e:
        print(f"[画像結合エラー]: {e}")
    finally:
        # 一時ファイルを削除
        if os.path.exists(map_jpg_path):
            os.remove(map_jpg_path)
        if os.path.exists(radar_jpg_path):
            os.remove(radar_jpg_path)

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_key, thresholds, scoring_weights = load_config()
    
    if not api_key:
        print("エラー: config.json に正しく api_key を設定してください。")
    else:
        print("=== Google Map 経路情報 & 情報地図出力ツール ===")
        print(f"[設定ロード完了] 急: R<={thresholds['sharp_curve_max_r']}m | 中: R<={thresholds['medium_curve_max_r']}m | 直線: >={thresholds['min_straight_length_m']}m | 激坂: >={thresholds['steep_slope_min_deg']}°")
        
        maps_url_input = input("\nGoogleマップのURLを入力してください: ").strip()

        if maps_url_input:
            # 入力されたURLを保存しておく（QRコードに使用）
            origin, destination, waypoints = parse_google_maps_url(maps_url_input)
            
            if origin and destination:
                routes = get_all_routes_info(origin, destination, waypoints, api_key)
                
                if routes:
                    selected_route = routes[0] if len(routes) == 1 else None
                    if not selected_route:
                        print("\n==========================")
                        for r in routes:
                            print(f"【{r['index']}】 経由: {r['summary']} | 距離: {r['distance']} | 時間: {r['duration']}")
                        print("==========================")
                        while True:
                            choice = input(f"ルート番号(1〜{len(routes)}): ").strip()
                            if choice.isdigit() and 1 <= int(choice) <= len(routes):
                                selected_route = routes[int(choice) - 1]
                                break

                    if selected_route["distance_km"] > 100.0:
                        print("\n【警告】 100kmを超えると精度が顕著に荒くなる恐れがあります。")
                        confirm = input("このまま実行しますか？ (y/n): ").strip().lower()
                        if confirm != 'y':
                            print("処理を中断しました。")
                            exit(0)

                    coords = fetch_high_res_coords(selected_route, api_key)

                    print("\n--------------------------")
                    print(f"【選択ルート】 ルート {selected_route['index']} ({selected_route['summary']})")

                    sharp_curves, medium_curves, straight_segments = analyze_curves_and_straights(coords, thresholds)
                    elevations = get_elevation_data(coords, api_key)
                    steep_slopes = analyze_steep_slopes(coords, elevations, thresholds)

                    total_straight_m = sum(seg["length_m"] for seg in straight_segments)
                    
                    print(f"■ 総走行距離 : {selected_route['distance']}")
                    print(f"■ 想定所要時間 : {selected_route['duration']}")
                    print(f"■ 急カーブ (R <= {int(thresholds['sharp_curve_max_r'])}m)    : {len(sharp_curves)} 箇所")
                    print(f"■ 中カーブ ({int(thresholds['sharp_curve_max_r'])}m < R <= {int(thresholds['medium_curve_max_r'])}m) : {len(medium_curves)} 箇所")
                    print(f"■ 直線区間 ({int(thresholds['min_straight_length_m'])}m以上)     : {len(straight_segments)} 箇所（合計長: {round(total_straight_m/1000, 2)} km）")
                    print(f"■ 激坂区間 ({thresholds['steep_slope_min_deg']}°以上 / {thresholds['min_slope_segment_m']}m以上): {len(steep_slopes)} 箇所")
                    
                    metrics = calculate_metrics_and_scores(
                        selected_route, sharp_curves, medium_curves, 
                        straight_segments, steep_slopes, scoring_weights
                    )
                    
                    print("\n【ルート特性スコア】")
                    for m in metrics:
                        bar_str = render_bar(m["score"])
                        print(f"{m['name']} ({m['raw']})\n {bar_str}")
                    print("--------------------------")
                    
                    default_title = selected_route['summary']
                    custom_title = input(f"\n出力するルート名/タイトルを入力してください (Enterのみでデフォルト [{default_title}]): ").strip()
                    if not custom_title:
                        custom_title = default_title

                    # save_outputs 関数に maps_url_input と selected_route を渡す
                    save_outputs(selected_route, coords, sharp_curves, medium_curves, straight_segments, steep_slopes, thresholds, metrics, api_key, base_dir, custom_summary=custom_title, maps_url=maps_url_input)
            else:
                print("【エラー】 入力されたURLから有効な「出発地」および「目的地」を検出できませんでした。")