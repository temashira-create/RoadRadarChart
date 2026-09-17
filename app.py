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

# ★ メイン領域全体の背景色調整 ＆ スマホ表示最適化CSS
st.markdown(
    """
    <style>
        /* メインエリア全体の背景を薄い黄色に */
        .main .block-container {
            background-color: #fffde7;
            padding: 1.5rem;
            border-radius: 12px;
        }
        /* アプリ全体の背景 */
        .stApp {
            background-color: #fefce8;
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

        /* ★ スマホ向け見出しフォントサイズの微調整と改行防止 */
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.4rem !important; }
        h3 { font-size: 1.2rem !important; }
        
        h1, h2, h3 {
            word-break: keep-all;
            overflow-wrap: break-word;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- バックグラウンドでAPIキーと設定を取得 ---
api_key_default, thresholds_default, scoring_weights = load_config()
api_key = api_key_default

# --- アプリ基本URLの設定 ---
APP_BASE_URL = "https://roadradarchart-eh3pdimpf5mqnf96utrzd8.streamlit.app/"

# --- 𝕏 共有用のテキスト・URL作成 ---
share_text = "RoadRadarChart - ロード特性分析ツール #RoadRadarChart"
encoded_share_text = urllib.parse.quote(share_text)
encoded_app_url = urllib.parse.quote(APP_BASE_URL)
twitter_intent_url = f"https://twitter.com/intent/tweet?text={encoded_share_text}&url={encoded_app_url}"

# --- メインタイトル ＆ 𝕏 共有ボタン ---
title_col1, title_col2 = st.columns([3, 1])

with title_col1:
    styled_title = (
        'import io\nimport os\nimport re\nimport urllib.parse\nimport folium\nfrom PIL import Image\nimport requests\n# Roadscore.py からすべての関数を読み込む\nfrom Roadscore import *\nimport streamlit as st\nfrom streamlit_folium import st_folium\n\n\ndef resolve_short_url(url):\n    """maps.app.goo.gl などの短縮URLを展開して正式なURLを返す"""\n    if "maps.app.goo.gl" in url or "goo.gl" in url:\n        try:\n            headers = {\n                "User-Agent": (\n                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"\n                    " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"\n                )\n            }\n            response = requests.get(url, headers=headers, allow_redirects=True)\n            return response.url\n        except Exception as e:\n            st.error(f"短縮URLの展開中にエラーが発生しました: {e}")\n            return url\n    return url\n\n\ndef create_clean_gmaps_url(route, coords):\n    """ルートの座標データ等から、スッキリとしたGoogleマップ共有用URLを生成する"""\n    if not coords or len(coords) < 2:\n        return ""\n    start_lat, start_lng = coords[0]\n    end_lat, end_lng = coords[-1]\n\n    origin_param = f"{start_lat},{start_lng}"\n    dest_param = f"{end_lat},{end_lng}"\n\n    clean_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_param}&destination={dest_param}&travelmode=driving"\n    return clean_url\n\n\ndef parse_distance_km(route, metrics):\n    """様々なデータ構造から安全に走行距離(km)を取得する関数"""\n    if isinstance(metrics, dict):\n        if "distance_km" in metrics:\n            return float(metrics["distance_km"])\n        if "distance_val" in metrics:\n            return float(metrics["distance_val"]) / 1000.0\n\n    if isinstance(route, dict):\n        for key in ["distance_meters", "distance_val", "distance_m"]:\n            if key in route and route[key]:\n                return float(route[key]) / 1000.0\n        for key in ["distance_km", "distance_num"]:\n            if key in route and route[key]:\n                return float(route[key])\n\n        dist_str = str(route.get("distance", ""))\n        match = re.search(r"([\\d\\.,]+)\\s*(km|m)?", dist_str, re.IGNORECASE)\n        if match:\n            val = float(match.group(1).replace(",", ""))\n            unit = match.group(2)\n            if unit and unit.lower() == "m" and val > 500:\n                return val / 1000.0\n            return val\n\n    return 0.0\n\n\n# サイドバーを初期状態で閉じる設定\nst.set_page_config(\n    page_title="RoadRadarChart - ルート特性分析ツール",\n    layout="wide",\n    initial_sidebar_state="collapsed",\n)\n\n# ★ メイン領域全体の背景色調整 ＆ スマホ表示最適化CSS\nst.markdown(\n    """\n    <style>\n        /* メインエリア全体の背景を薄い黄色に */\n        .main .block-container {\n            background-color: #fffde7;\n            padding: 1.5rem;\n            border-radius: 12px;\n        }\n        /* アプリ全体の背景 */\n        .stApp {\n            background-color: #fefce8;\n        }\n        /* サイドバーを完全に隠す */\n        section[data-testid="stSidebar"] {\n            display: none;\n        }\n        /* Streamlitのコンテナやiframe背景の白を透明化 */\n        div[data-testid="stCustomComponentV1"], \n        div[data-testid="stElementToolbar"],\n        .stHtml, iframe {\n            background-color: transparent !important;\n        }\n        /* ヘッダー（Deployボタン・メニュー）を非表示にする */\n        header[data-testid="stHeader"] {\n            visibility: hidden !important;\n            height: 0px !important;\n            padding: 0px !important;\n        }\n        \n        /* フッター（Made with Streamlit）を非表示にする */\n        footer {\n            visibility: hidden !important;\n            height: 0px !important;\n            padding: 0px !important;\n        }\n\n        /* ★ スマホ向け見出しフォントサイズの微調整と改行防止 */\n        h1 { font-size: 1.8rem !important; }\n        h2 { font-size: 1.4rem !important; }\n        h3 { font-size: 1.2rem !important; }\n        \n        h1, h2, h3 {\n            word-break: keep-all;\n            overflow-wrap: break-word;\n        }\n    </style>\n    """,\n    unsafe_allow_html=True,\n)\n\n# --- バックグラウンドでAPIキーと設定を取得 ---\napi_key_default, thresholds_default, scoring_weights = load_config()\napi_key = api_key_default\n\n# --- アプリ基本URLの設定 ---\nAPP_BASE_URL = "https://roadradarchart-eh3pdimpf5mqnf96utrzd8.streamlit.app/"\n\n# --- 𝕏 共有用のテキスト・URL作成 ---\nshare_text = "RoadRadarChart - ロード特性分析ツール #RoadRadarChart"\nencoded_share_text = urllib.parse.quote(share_text)\nencoded_app_url = urllib.parse.quote(APP_BASE_URL)\ntwitter_intent_url = f"https://twitter.com/intent/tweet?text={encoded_share_text}&url={encoded_app_url}"\n\n# --- メインタイトル ＆ 𝕏 共有ボタン ---\ntitle_col1, title_col2 = st.columns([3, 1])\n\nwith title_col1:\n    styled_title = (\n        \'🛣️ <span style="font-weight: bold; font-size: 2.0rem;">\'\n        \'<span style="color: #B71C1C;">R</span>oad\'\n        \'<span style="color: #B71C1C;">R</span>adar\'\n        \'<span style="color: #E65100;">C</span>hart\'\n        "</span>"\n    )\n    st.markdown(styled_title, unsafe_allow_html=True)\n\nwith title_col2:\n    st.markdown(\n        f"""\n        <div style="display: flex; align-items: center; height: 100%; padding-top: 5px;">\n            <a href="{twitter_intent_url}" target="_blank" style="\n                background-color: #000000;\n                color: white;\n                padding: 8px 16px;\n                border-radius: 20px;\n                text-decoration: none;\n                font-weight: bold;\n                font-size: 13px;\n                display: inline-flex;\n                align-items: center;\n                gap: 6px;\n                box-shadow: 0 2px 4px rgba(0,0,0,0.2);\n                white-space: nowrap;\n            ">𝕏 で共有する</a>\n        </div>\n        """,\n        unsafe_allow_html=True,\n    )\n\n# --- URLパラメータから初期値取得 ---\nquery_params = st.query_params\ndefault_url = query_params.get("map_url", "")\n\n# --- ① ガイドテキスト ---\nst.markdown("### ① Googleマップで経路を検索して、そのURLをコピーしてください")\n\n# --- ※ 画像（1.jpg）の表示（60%相当のサイズに変更） ---\nscript_dir = os.path.dirname(os.path.abspath(__file__))\nimage_path = os.path.join(script_dir, "1.jpg")\n\nif os.path.exists(image_path):\n    img_col1, img_col2 = st.columns([0.6, 0.4])\n    with img_col1:\n        st.image(image_path, use_container_width=True)\nelse:\n    st.info(f"※ 画像ファイル (1.jpg) が見つかりません。参照パス: {image_path}")\n\n# --- ② 見出し ＆ URL入力 ---\nst.markdown("### ② URLをペーストしてください")\nurl_input = st.text_input(\n    "URL入力欄",\n    value=default_url,\n    placeholder="https://www.google.com/maps/dir/...",\n    label_visibility="collapsed",\n)\n\n# --- ③ 見出し ＆ タイトル入力 ---\nst.markdown("### ③ タイトルを入力してください")\ncustom_title_input = st.text_input(\n    "タイトル入力欄",\n    value="自動",\n    placeholder="未入力の場合は自動で設定されます",\n    label_visibility="collapsed",\n)\n\nst.markdown("<br>", unsafe_allow_html=True)\n\nif st.button("全ルート一括解析を実行", type="primary", use_container_width=True):\n    if not api_key:\n        st.error("APIキーが設定されていません。configファイル等を確認してください。")\n    elif not url_input:\n        st.warning("GoogleマップのURLを入力してください。")\n    else:\n        with st.spinner("URL解析中...":\n            expanded_url = resolve_short_url(url_input)\n            origin, destination, waypoints = parse_google_maps_url(expanded_url)\n\n        if not origin or not destination:\n            st.error(\n                "入力されたURLから有効な「出発地」および「目的地」を検出できませんでした。"\n            )\n        else:\n            with st.spinner("ルート候補を一括取得・解析中...":\n                routes = get_all_routes_info(origin, destination, waypoints, api_key)\n\n            if not routes:\n                st.error("経路情報が取得できませんでした。")\n            else:\n                all_results = []\n                user_title = custom_title_input.strip()\n\n                for i, route in enumerate(routes):\n                    if not user_title or user_title == "自動":\n                        image_title = route.get("summary", "")\n                    else:\n                        image_title = user_title\n\n                    coords = fetch_high_res_coords(route, api_key)\n\n                    sharp_curves, medium_curves, large_curves, straight_segments = (\n                        analyze_curves_and_straights(coords, thresholds_default)\n                    )\n\n                    elevations = get_elevation_data(coords, api_key)\n                    steep_slopes = analyze_steep_slopes(\n                        coords, elevations, thresholds_default\n                    )\n\n                    metrics = calculate_metrics_and_scores(\n                        route,\n                        sharp_curves,\n                        medium_curves,\n                        straight_segments,\n                        steep_slopes,\n                        scoring_weights,\n                    )\n\n                    combined_img, html_content = generate_route_image_memory(\n                        route,\n                        coords,\n                        sharp_curves,\n                        medium_curves,\n                        straight_segments,\n                        steep_slopes,\n                        thresholds_default,\n                        metrics,\n                        api_key,\n                        custom_summary=image_title,\n                    )\n\n                    clean_gmaps_url = create_clean_gmaps_url(route, coords)\n                    distance_km = parse_distance_km(route, metrics)\n\n                    all_results.append({\n                        "route": route,\n                        "coords": coords,\n                        "sharp_curves": sharp_curves,\n                        "medium_curves": medium_curves,\n                        "large_curves": large_curves,\n                        "straight_segments": straight_segments,\n                        "steep_slopes": steep_slopes,\n                        "metrics": metrics,\n                        "default_summary": route.get("summary", ""),\n                        "image_title": image_title,\n                        "combined_img": combined_img,\n                        "html_content": html_content,\n                        "clean_gmaps_url": clean_gmaps_url,\n                        "distance_km": distance_km,\n                    })\n\n                st.session_state["all_analysis_results"] = all_results\n                st.session_state["url_input"] = url_input\n\n# --- 解析結果の表示 ---\nif "all_analysis_results" in st.session_state:\n    all_results = st.session_state["all_analysis_results"]\n\n    st.success(f"{len(all_results)}件のルート解析が完了しました！")\n\n    has_over_100km = any(res.get("distance_km", 0) > 100 for res in all_results)\n    if has_over_100km:\n        st.warning(\n            "⚠️ **注意事項**: 総走行距離が100kmを超えるルートが含まれています。"\n            "長距離ルートではデータ取得・計算の仕様上、解析精度（カーブ・勾配等の検出精度）が低下する場合があります。"\n        )\n\n    tab1, tab2 = st.tabs(["🖼️ 出力画像生成", "🗺️ インタラクティブマップ"])\n\n    with tab1:\n        header_col1, header_col2 = st.columns([1, 1])\n\n        with header_col1:\n            st.subheader("合成画像出力一覧（SNS共有用）")\n\n        with header_col2:\n            if all_results and "clean_gmaps_url" in all_results[0]:\n                common_gmaps_url = all_results[0]["clean_gmaps_url"]\n                \n                # URLをテキスト本文に含めてきれいに共有できるように修正\n                tweet_body = f"🛣️ RoadRadarChartで解析したGoogle Mapsルートはこちら！\\n#RoadRadarChart\\n{common_gmaps_url}"\n                encoded_tweet_body = urllib.parse.quote(tweet_body)\n                route_x_share_url = f"https://twitter.com/intent/tweet?text={encoded_tweet_body}"\n\n                st.markdown(\n                    f"""\n                    <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-start; padding-bottom: 10px;">\n                        <a href="{common_gmaps_url}" target="_blank" style="\n                            background-color: #4285F4; color: white; padding: 6px 12px; border-radius: 6px;\n                            text-decoration: none; font-size: 12px; font-weight: bold; white-space: nowrap;\n                            box-shadow: 0 1px 3px rgba(0,0,0,0.2);\n                        ">🗺️ Google Maps表示</a>\n                        <a href="{route_x_share_url}" target="_blank" style="\n                            background-color: #000000; color: white; padding: 6px 12px; border-radius: 6px;\n                            text-decoration: none; font-size: 12px; font-weight: bold; white-space: nowrap;\n                            box-shadow: 0 1px 3px rgba(0,0,0,0.2);\n                        ">𝕏 ルートをXで共有</a>\n                        <span style="font-size: 11px; color: #666; white-space: nowrap;">※ルートは一致しないことがあります</span>\n                    </div>\n                    """,\n                    unsafe_allow_html=True,\n                )\n\n        if all_results:\n            num_routes = len(all_results)\n\n            # ★ ルート数に応じてカラム構造を動的に変更（PC表示での巨大化防止）\n            if num_routes == 1:\n                col_left, col_main, col_right = st.columns([1, 2, 1])\n                cols = [col_main]\n            elif num_routes == 2:\n                cols = st.columns(2)\n            else:\n                cols = st.columns(3)\n\n            for i, res in enumerate(all_results):\n                default_summary = res["default_summary"]\n                combined_img = res["combined_img"]\n                target_col = cols[i % len(cols)]\n\n                with target_col:\n                    st.markdown(\n                        f"""\n                        <div style="min-height: 50px; margin-bottom: 8px;">\n                            <h3 style="margin: 0 0 2px 0; font-size: 1.1rem;">ルート {i+1}</h3>\n                            <div style="font-weight: bold; font-size: 1.0rem; color: #333;">{default_summary}</div>\n                        </div>\n                        """,\n                        unsafe_allow_html=True,\n                    )\n\n                    if combined_img:\n                        buf = io.BytesIO()\n                        combined_img.save(buf, format="JPEG", quality=95)\n                        st.download_button(\n                            label=f"💾 ルート{i+1}画像を保存",\n                            data=buf.getvalue(),\n                            file_name=f"output_route_{i+1}.jpg",\n                            mime="image/jpeg",\n                            key=f"download_img_{i}",\n                            use_container_width=True,\n                        )\n\n                        st.image(combined_img, use_container_width=True)\n                    else:\n                        st.error("画像の生成に失敗しました。")\n\n                    st.markdown("<br>", unsafe_allow_html=True)\n\n    with tab2:\n        st.subheader("分析マップ（ルート別個別表示）")\n\n        for i, res in enumerate(all_results):\n            default_summary = res["default_summary"]\n            distance = res["route"]["distance"]\n            duration = res["route"]["duration"]\n\n            st.markdown(\n                f"### 📍 ルート {i+1}: {default_summary} ({distance} / {duration})"\n            )\n\n            coords = res["coords"]\n            start_lat, start_lng = coords[0]\n\n            m = folium.Map(location=[start_lat, start_lng], zoom_start=11)\n\n            folium.PolyLine(\n                coords, color="blue", weight=4, opacity=0.7, popup=f"ルート {i+1}"\n            ).add_to(m)\n\n            for seg in res["straight_segments"]:\n                folium.PolyLine(\n                    seg["coords"], color="green", weight=5, opacity=0.7\n                ).add_to(m)\n\n            for slope in res["steep_slopes"]:\n                folium.PolyLine(\n                    slope["coords"], color="darkviolet", weight=6, opacity=0.7\n                ).add_to(m)\n\n            for pt in res.get("sharp_curves", []):\n                folium.CircleMarker(\n                    [pt[0], pt[1]],\n                    radius=6,\n                    color="crimson",\n                    fill=True,\n                    fill_color="crimson",\n                    popup="ヘアピンコーナー",\n                ).add_to(m)\n\n            for pt in res.get("medium_curves", []):\n                folium.CircleMarker(\n                    [pt[0], pt[1]],\n                    radius=4,\n                    color="darkorange",\n                    fill=True,\n                    fill_color="darkorange",\n                    popup="中速コーナー",\n                ).add_to(m)\n\n            for pt in res.get("large_curves", []):\n                folium.CircleMarker(\n                    [pt[0], pt[1]],\n                    radius=4,\n                    color="dodgerblue",\n                    fill=True,\n                    fill_color="dodgerblue",\n                    popup="緩大コーナー (R=200m~400m)",\n                ).add_to(m)\n\n            legend_html = """\n            <div style="\n                position: fixed; \n                bottom: 30px; right: 20px; width: 160px;\n                background-color: rgba(255, 255, 255, 0.9);\n                border:2px solid grey; z-index:9999; font-size:13px;\n                padding: 10px; border-radius: 8px; box-shadow: 2px 2px 6px rgba(0,0,0,0.3);\n                font-family: sans-serif;\n            ">\n                <b>📍 マップ凡例</b><br>\n                <i style="background: green; width: 12px; height: 12px; display: inline-block; margin-right: 5px;"></i> 直線区間<br>\n                <i style="background: darkviolet; width: 12px; height: 12px; display: inline-block; margin-right: 5px;"></i> 激坂区間<br>\n                <i style="background: crimson; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> ヘアピン<br>\n                <i style="background: darkorange; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> 中速コーナー<br>\n                <i style="background: dodgerblue; width: 10px; height: 10px; display: inline-block; border-radius: 50%; margin-right: 7px;"></i> 緩大コーナー\n            </div>\n            """\n            m.get_root().html.add_child(folium.Element(legend_html))\n\n            st_folium(m, width=900, height=450, key=f"interactive_map_route_{i}")\n            st.markdown("---")\n'
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

# --- ※ 画像（1.jpg）の表示（60%相当のサイズに変更） ---
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
                
                # Google MapsのURLをテキスト本文に直接組み込む形に修正
                tweet_body = f"🛣️ RoadRadarChartで解析したGoogle Mapsルートはこちら！\n#RoadRadarChart\n{common_gmaps_url}"
                encoded_tweet_body = urllib.parse.quote(tweet_body)
                route_x_share_url = f"https://twitter.com/intent/tweet?text={encoded_tweet_body}"

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
            num_routes = len(all_results)

            # ルート数に応じてカラム構造を動的に変更（最大3列）
            if num_routes == 1:
                # 1件の時は中央配置にして最大幅を制限（巨大化防止）
                col_left, col_main, col_right = st.columns([1, 2, 1])
                cols = [col_main]
            elif num_routes == 2:
                # 2件の時は2列横並び
                cols = st.columns(2)
            else:
                # 3件以上の時は3列横並び
                cols = st.columns(3)

            for i, res in enumerate(all_results):
                default_summary = res["default_summary"]
                combined_img = res["combined_img"]
                target_col = cols[i % len(cols)]

                with target_col:
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