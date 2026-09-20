import io
import os
import re
import urllib.parse
import folium
from PIL import Image
import requests
# Roadscore.py からすべての関数を読み込む
from Roadscore import *
import streamlit as st
from streamlit_folium import st_folium


def resolve_short_url(url):
    """maps.app.goo.gl などの短縮URLを展開して正式なURLを返す"""
    if "maps.app.goo.gl" in url or "goo.gl" in url:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
            response = requests.get(url, headers=headers, allow_redirects=True)
            return response.url
        except Exception as e:
            st.error(f"短縮URLの展開中にエラーが発生しました: {e}")
            return url
    return url


def create_clean_gmaps_url(route, coords):
    """ルートの座標データ等から、スッキリとしたGoogleマップ共有用URLを生成する"""
    if not coords or len(coords) < 2:
        return ""
    start_lat, start_lng = coords[0]
    end_lat, end_lng = coords[-1]

    origin_param = f"{start_lat},{start_lng}"
    dest_param = f"{end_lat},{end_lng}"

    clean_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_param}&destination={dest_param}&travelmode=driving"
    return clean_url


def parse_distance_km(route, metrics):
    """様々なデータ構造から安全に走行距離(km)を取得する関数"""
    if isinstance(metrics, dict):
        if "distance_km" in metrics:
            return float(metrics["distance_km"])
        if "distance_val" in metrics:
            return float(metrics["distance_val"]) / 1000.0

    if isinstance(route, dict):
        for key in ["distance_meters", "distance_val", "distance_m"]:
            if key in route and route[key]:
                return float(route[key]) / 1000.0
        for key in ["distance_km", "distance_num"]:
            if key in route and route[key]:
                return float(route[key])

        dist_str = str(route.get("distance", ""))
        match = re.search(r"([\d\.,]+)\s*(km|m)?", dist_str, re.IGNORECASE)
        if match:
            val = float(match.group(1).replace(",", ""))
            unit = match.group(2)
            if unit and unit.lower() == "m" and val > 500:
                return val / 1000.0
            return val

    return 0.0


# サイドバーを初期状態で閉じる設定
st.set_page_config(
    page_title="RoadRadarChart - ルート特性分析ツール",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ★ CSSの設定：ダークモード対策の文字色強制指定 ＆ レスポンシブ化
st.markdown(
    """
    <style>
        /* メインエリア全体の背景と文字色（①ダークモード視認性対策） */
        .main .block-container {
            background-color: #fffde7 !important;
            color: #333333 !important;
            padding: 1.5rem;
            border-radius: 12px;
        }
        /* アプリ全体の背景と標準テキストカラー指定 */
        .stApp {
            background-color: #fefce8 !important;
            color: #333333 !important;
        }
        
        /* 見出し・段落・ラベル・ボタン内等のテキスト色を固定 */
        h1, h2, h3, h4, h5, h6, p, label, span, div {
            color: #333333;
        }

        /* サイドバーを完全に隠す */
        section[data-testid="stSidebar"] {
            display: none;
        }
        /* Streamlitのコンテナやiframe背景の白を透明化 */
        div[data-testid="stCustomComponentV1"], 
        div[data-testid="stElementToolbar"],
        .stHtml, iframe {
            background-color: transparent !important;
        }
        /* ヘッダー（Deployボタン・メニュー）を非表示にする */
        header[data-testid="stHeader"] {
            visibility: hidden !important;
            height: 0px !important;
            padding: 0px !important;
        }
        
        /* フッター（Made with Streamlit）を非表示にする */
        footer {
            visibility: hidden !important;
            height: 0px !important;
            padding: 0px !important;
        }

        /* スマホ向け見出しフォントサイズの微調整と改行防止 */
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.4rem !important; }
        h3 { font-size: 1.2rem !important; }
        
        h1, h2, h3 {
            word-break: keep-all;
            overflow-wrap: break-word;
        }

        /* PCで横並び・スマホで縦並びにするレスポンシブCSS */
        @media (max-width: 768px) {
            div[data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- バックグラウンドでAPIキーと設定を取得 ---
api_key_default, thresholds_default, scoring_weights = load_config()
api_key = api_key_default

# --- ② アプリ基本URL（外部ブラウザ強制起動パラメータ付き） ---
APP_BASE_URL = "https://roadradarchart-eh3pdimpf5mqnf96utrzd8.streamlit.app/?openExternalBrowser=1"

# --- 𝕏 共有用のテキスト・URL作成（ハッシュタグ後に改行を入れる設定） ---
share_text = f"RoadRadarChart - ロード特性分析ツール\n#RoadRadarChart\n{APP_BASE_URL}"
encoded_share_text = urllib.parse.quote(share_text)
twitter_intent_url = f"https://twitter.com/intent/tweet?text={encoded_share_text}"

# --- メインタイトル ＆ 𝕏 共有ボタン ---
title_col1, title_col2 = st.columns([3, 1])

with title_col1:
    styled_title = (
        '🛣️ <span style="font-weight: bold; font-size: 2.0rem;">'
        '<span style="color: #B71C1C;">R</span>oad'
        '<span style="color: #B71C1C;">R</span>adar'
        '<span style="color: #E65100;">C</span>hart'
        "</span>"
    )
    st.markdown(styled_title, unsafe_allow_html=True)

with title_col2:
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; height: 100%; padding-top: 5px;">
            <a href="{twitter_intent_url}" target="_blank" style="
                background-color: #000000;
                color: white;
                padding: 8px 16px;
                border-radius: 20px;
                text-decoration: none;
                font-weight: bold;
                font-size: 13px;
                display: inline-flex;
                align-items: center;
                gap: 6px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                white-space: nowrap;
            ">𝕏 で共有する</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- URLパラメータから初期値取得 ---
query_params = st.query_params
default_url = query_params.get("map_url", "")

# --- ① ガイドテキスト ---
st.markdown("### ① Googleマップで経路を検索して、そのURLをコピーしてください")

# --- ※ 画像（1.jpg）の表示 ---
script_dir = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join(script_dir, "1.jpg")

if os.path.exists(image_path):
    img_col1, img_col2 = st.columns([0.6, 0.4])
    with img_col1:
        st.image(image_path, use_container_width=True)
else:
    st.info(f"※ 画像ファイル (1.jpg) が見つかりません。参照パス: {image_path}")

# --- ② 見出し ＆ URL入力 ---
st.markdown("### ② URLをペーストしてください")
url_input = st.text_input(
    "URL入力欄",
    value=default_url,
    placeholder="https://www.google.com/maps/dir/...",
    label_visibility="collapsed",
)

# --- ③ 見出し ＆ タイトル入力 ---
st.markdown("### ③ タイトルを入力してください")
custom_title_input = st.text_input(
    "タイトル入力欄",
    value="自動",
    placeholder="未入力の場合は自動で設定されます",
    label_visibility="collapsed",
)

st.markdown("<br>", unsafe_allow_html=True)

if st.button("全ルート一括解析を実行", type="primary", use_container_width=True):
    if not api_key:
        st.error("APIキーが設定されていません。configファイル等を確認してください。")
    elif not url_input:
        st.warning("GoogleマップのURLを入力してください。")
    else:
        with st.spinner("URL解析中..."):
            expanded_url = resolve_short_url(url_input)
            origin, destination, waypoints = parse_google_maps_url(expanded_url)

        if not origin or not destination:
            st.error(
                "入力されたURLから有効な「出発地」および「目的地」を検出できませんでした。"
            )
        else:
            with st.spinner("ルート候補を一括取得・解析中..."):
                routes = get_all_routes_info(origin, destination, waypoints, api_key)

            if not routes:
                st.error("経路情報が取得できませんでした。")
            else:
                all_results = []
                user_title = custom_title_input.strip()

                for i, route in enumerate(routes):
                    if not user_title or user_title == "自動":
                        image_title = route.get("summary", "")
                    else:
                        image_title = user_title

                    coords = fetch_high_res_coords(route, api_key)

                    sharp_curves, medium_curves, large_curves, straight_segments = (
                        analyze_curves_and_straights(coords, thresholds_default)
                    )

                    elevations = get_elevation_data(coords, api_key)
                    steep_slopes = analyze_steep_slopes(
                        coords, elevations, thresholds_default
                    )

                    metrics = calculate_metrics_and_scores(
                        route,
                        sharp_curves,
                        medium_curves,
                        straight_segments,
                        steep_slopes,
                        scoring_weights,
                    )

                    combined_img, html_content = generate_route_image_memory(
                        route,
                        coords,
                        sharp_curves,
                        medium_curves,
                        straight_segments,
                        steep_slopes,
                        thresholds_default,
                        metrics,
                        api_key,
                        custom_summary=image_title,
                    )

                    clean_gmaps_url = create_clean_gmaps_url(route, coords)
                    distance_km = parse_distance_km(route, metrics)

                    all_results.append({
                        "route": route,
                        "coords": coords,
                        "sharp_curves": sharp_curves,
                        "medium_curves": medium_curves,
                        "large_curves": large_curves,
                        "straight_segments": straight_segments,
                        "steep_slopes": steep_slopes,
                        "metrics": metrics,
                        "default_summary": route.get("summary", ""),
                        "image_title": image_title,
                        "combined_img": combined_img,
                        "html_content": html_content,
                        "clean_gmaps_url": clean_gmaps_url,
                        "distance_km": distance_km,
                    })

                st.session_state["all_analysis_results"] = all_results
                st.session_state["url_input"] = url_input

# --- 解析結果の表示 ---
if "all_analysis_results" in st.session_state:
    all_results = st.session_state["all_analysis_results"]

    st.success(f"{len(all_results)}件のルート解析が完了しました！")

    has_over_100km = any(res.get("distance_km", 0) > 100 for res in all_results)
    if has_over_100km:
        st.warning(
            "⚠️ **注意事項**: 総走行距離が100kmを超えるルートが含まれています。"
            "長距離ルートではデータ取得・計算の仕様上、解析精度（カーブ・勾配等の検出精度）が低下する場合があります。"
        )

    tab1, tab2 = st.tabs(["🖼️ 出力画像生成", "🗺️ インタラクティブマップ"])

    with tab1:
        header_col1, header_col2 = st.columns([1, 1])

        with header_col1:
            st.subheader("合成画像出力一覧（SNS共有用）")

        with header_col2:
            if all_results and "clean_gmaps_url" in all_results[0]:
                common_gmaps_url = all_results[0]["clean_gmaps_url"]
                
                route_share_text = f"🛣️ RoadRadarChartで解析したGoogle Mapsルートはこちら：\n{common_gmaps_url}"
                encoded_route_share_text = urllib.parse.quote(route_share_text)
                route_x_share_url = f"https://twitter.com/intent/tweet?text={encoded_route_share_text}"

                st.markdown(
                    f"""
                    <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-start; padding-bottom: 10px;">
                        <a href="{common_gmaps_url}" target="_blank" style="
                            background-color: #4285F4; color: white; padding: 6px 12px; border-radius: 6px;
                            text-decoration: none; font-size: 12px; font-weight: bold; white-space: nowrap;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                        ">🗺️ Google Maps表示</a>
                        <a href="{route_x_share_url}" target="_blank" style="
                            background-color: #000000; color: white; padding: 6px 12px; border-radius: 6px;
                            text-decoration: none; font-size: 12px; font-weight: bold; white-space: nowrap;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                        ">𝕏 ルートをXで共有</a>
                        <span style="font-size: 11px; color: #666; white-space: nowrap;">※ルートは一致しないことがあります</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if all_results:
            cols = st.columns(len(all_results))

            for i, res in enumerate(all_results):
                default_summary = res["default_summary"]
                combined_img = res["combined_img"]

                with cols[i]:
                    st.markdown(
                        f"""
                        <div style="min-height: 50px; margin-bottom: 8px;">
                            <h3 style="margin: 0 0 2px 0; font-size: 1.1rem;">ルート {i+1}</h3>
                            <div style="font-weight: bold; font-size: 1.0rem; color: #333;">{default_summary}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if combined_img:
                        buf = io.BytesIO()
                        combined_img.save(buf, format="JPEG", quality=95)
                        st.download_button(
                            label=f"💾 ルート{i+1}画像を保存",
                            data=buf.getvalue(),
                            file_name=f"output_route_{i+1}.jpg",
                            mime="image/jpeg",
                            key=f"download_img_{i}",
                            use_container_width=True,
                        )

                        st.image(combined_img, use_container_width=True)
                    else:
                        st.error("画像の生成に失敗しました。")

                    st.markdown("<br>", unsafe_allow_html=True)

    with tab2:
        st.subheader("分析マップ（ルート別個別表示）")

        for i, res in enumerate(all_results):
            default_summary = res["default_summary"]
            distance = res["route"]["distance"]
            duration = res["route"]["duration"]

            st.markdown(
                f"### 📍 ルート {i+1}: {default_summary} ({distance} / {duration})"
            )

            coords = res["coords"]
            start_lat, start_lng = coords[0]

            m = folium.Map(location=[start_lat, start_lng], zoom_start=11)

            folium.PolyLine(
                coords, color="blue", weight=4, opacity=0.7, popup=f"ルート {i+1}"
            ).add_to(m)

            for seg in res["straight_segments"]:
                folium.PolyLine(
                    seg["coords"], color="green", weight=5, opacity=0.7
                ).add_to(m)

            for slope in res["steep_slopes"]:
                folium.PolyLine(
                    slope["coords"], color="darkviolet", weight=6, opacity=0.7
                ).add_to(m)

            for pt in res.get("sharp_curves", []):
                folium.CircleMarker(
                    [pt[0], pt[1]],
                    radius=6,
                    color="crimson",
                    fill=True,
                    fill_color="crimson",
                    popup="ヘアピンコーナー",
                ).add_to(m)

            for pt in res.get("medium_curves", []):
                folium.CircleMarker(
                    [pt[0], pt[1]],
                    radius=4,
                    color="darkorange",
                    fill=True,
                    fill_color="darkorange",
                    popup="中速コーナー",
                ).add_to(m)

            for pt in res.get("large_curves", []):
                folium.CircleMarker(
                    [pt[0], pt[1]],
                    radius=4,
                    color="dodgerblue",
                    fill=True,
                    fill_color="dodgerblue",
                    popup="緩大コーナー (R=200m~400m)",
                ).add_to(m)

            legend_html = """
            <div style="
                position: fixed; 
                bottom: 30px; right: 20px; width: 160px;
                background-color: rgba(255, 255, 255, 0.9);
                border:2px solid grey; z-index:9999; font-size:13px;
                padding: 10px; border-radius: 8px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
                font-family: sans-serif;
            ">
                <b>📍 マップ凡例</b><br>
                <i style="background: green; width: 12px; height: 12px; display: inline-block; margin-right: 5px;"></i> 直線区間<br>
                <i style="background: darkviolet; width: 12px; height: 12px; display: inline-block; margin-right: 5px;"></i> 激坂区間<br>
                <i style="background: crimson; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> ヘアピン<br>
                <i style="background: darkorange; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> 中速コーナー<br>
                <i style="background: dodgerblue; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> 緩大コーナー
            </div>
            """
            m.get_root().html.add_child(folium.Element(legend_html))

            st_folium(m, width=900, height=450, key=f"interactive_map_route_{i}")
            st.markdown("---")

        # ③ インタラクティブマップ下部に各種分析判定基準（パラメータ詳細）を表示
        with st.expander("🔍 **分析パラメータ・各指標の判定基準を見る**", expanded=True):
            st.markdown(
                """
                | 分析項目 | 検出・判定基準 | 解説 |
                | :--- | :--- | :--- |
                | 🔴 **ヘアピン率** | **曲率半径 R < 80m** | 1kmあたりの極小コーナー（急カーブ）の箇所数 |
                | 🟠 **中速コーナー率** | **曲率半径 80m ≤ R < 200m** | 1kmあたりの中速で抜けられるコーナーの箇所数 |
                | 🟢 **ストレート率** | **直線区間（見通し直線）** | 全走行距離に対するストレート区間の割合(%) |
                | 🟣 **激坂（上下）率** | **勾配斜度 ±8% 以上** | 全走行距離に対する急な上り坂・下り坂の割合(%) |
                | 🔵 **平均速度** | **想定平均移動速度** | 距離と所要時間から算出される平均車速(km/h) |
                """
            )