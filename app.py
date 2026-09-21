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

# --- 主要ワインディングのプリセットURL定義 ---
SPOT_PRESETS = {
    "【北海道】中山峠（国道230号）": (
        "https://www.google.com/maps/dir/42.9669144,141.1676026/42.7972619,140.9508441/"
    ),
    "【北海道】支笏湖畔（国道453号）": (
        "https://www.google.com/maps/dir/42.9294804,141.3388389/42.7635329,141.433401/"
    ),
    "【岩手/秋田】八幡平アスピーテライン": (
        "https://www.google.com/maps/dir/39.9227227,140.9764819/39.9725475,140.8052669/"
    ),
    "【宮城】コバルトライン": (
        "https://www.google.com/maps/dir/38.43500383790911,+141.44633077780648/38.40267251250418,+141.45259500107528/38.32521250918779,+141.51287317973953/38.2804423,141.5185324/@38.3578769,141.3218905,11z/data=!3m1!4b1!4m15!4m14!1m3!2m2!1d141.4463308!2d38.4350038!1m3!2m2!1d141.452595!2d38.4026725!1m3!2m2!1d141.5128732!2d38.3252125!1m0!3e0?entry=ttu&g_ep=EgoyMDI2MDkxNi4wIKXMDSoASAFQAw%3D%3D"
    ),
    "【宮城/山形】蔵王エコーライン": (
        "https://www.google.com/maps/dir/38.1303618,140.5596896/38.1295749,140.3792595/"
    ),
    "【茨城】筑波スカイライン / 朝日峠": (
        "https://www.google.com/maps/dir/36.1595485,140.1655816/36.2128858,140.122155/"
    ),
    "【栃木】第二いろは坂（上り）": (
        "https://www.google.com/maps/dir/36.7382917,139.5256014/36.7376547,139.4988488/"
    ),
    "【神奈川】箱根ターンパイク": (
        "https://www.google.com/maps/dir/35.185495,139.0506673/35.2424302,139.1399881/"
    ),
    "【山梨】富士スバルライン": (
        "https://www.google.com/maps/dir/35.4851117,138.7698783/35.3939787,138.7307626/"
    ),
    "【長野】ビーナスライン": (
        "https://www.google.com/maps/dir/36.2183759,138.1411094/36.15023597920541,+138.14106974931596/36.110976385485344,+138.23882633673736/@36.1556956,138.0999304,12z/data=!3m1!4b1!4m11!4m10!1m0!1m3!2m2!1d138.1410697!2d36.150236!1m3!2m2!1d138.2388263!2d36.1109764!3e0?entry=ttu&g_ep=EgoyMDI2MDkxNi4wIKXMDSoASAFQAw%3D%3D"
    ),
    "【静岡】伊豆スカイライン": (
        "https://www.google.com/maps/dir/35.1200052,139.0387769/34.9058489,139.0388753/"
    ),
    "【三重/滋賀】鈴鹿スカイライン": (
        "https://www.google.com/maps/dir/34.9752636,136.3467787/35.0219461,136.4643708/"
    ),
    "【兵庫】西六甲ドライブウェイ": (
        "https://www.google.com/maps/dir/34.7406943,135.1751489/34.7496879,135.2157105/"
    ),
    "【和歌山/奈良】高野龍神スカイライン": (
        "https://www.google.com/maps/dir/34.215000,135.586000/34.045000,135.550000/"
    ),
    "【山口】カルストロード（秋吉台）": (
        "https://www.google.com/maps/dir/33.480000,133.010000/33.470000,132.930000/"
    ),
    "【愛媛/高知】四国カルスト（天狗高原）": (
        "https://www.google.com/maps/dir/33.478383,132.8778385/33.476513982071516,+133.0021898951934/@33.4674381,132.9568195,15.38z/data=!4m7!4m6!1m0!1m3!2m2!1d133.0021899!2d33.476514!3e0?entry=ttu&g_ep=EgoyMDI2MDkxNi4wIKXMDSoASAFQAw%3D%3D"
    ),
    "【熊本/大分】阿蘇やまなみハイウェイ": (
        "https://www.google.com/maps/dir/33.2470522,131.2919401/32.939607,131.1175302/"
    ),
}


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

# ★ CSSの設定：アコーディオン枠も含め入力エリア全体を統一グレー化
st.markdown(
    """
    <style>
        /* メインエリアの余白調整 */
        .main .block-container {
            padding-top: 0rem !important;
            padding-bottom: 1.5rem;
            padding-left: 1.5rem;
            padding-right: 1.5rem;
        }
        /* サイドバーを隠す */
        section[data-testid="stSidebar"] {
            display: none;
        }
        /* ヘッダー・フッターの非表示化 */
        header[data-testid="stHeader"] {
            display: none !important;
        }
        footer {
            visibility: hidden !important;
            height: 0px !important;
            padding: 0px !important;
        }

        /* ★ 入力バー・セレクトボックス・アコーディオン（expander）をグレーに統一 */
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stExpander"] {
            background-color: #f2f2f2 !important;
            border-radius: 8px !important;
            border: 1px solid #e0e0e0 !important;
        }

        /* 見出しのスタイル調整 */
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.4rem !important; }
        h3 { font-size: 1.2rem !important; }
        
        h1, h2, h3 {
            word-break: keep-all;
            overflow-wrap: break-word;
        }

        /* スマホ向けレスポンシブ化 */
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

# --- アプリ基本URL（外部ブラウザ強制起動パラメータ付き） ---
APP_BASE_URL = "https://roadradarchart-eh3pdimpf5mqnf96utrzd8.streamlit.app/?openExternalBrowser=1"

# --- 𝕏 共有用のテキスト・URL作成 ---
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

# --- セッション状態の初期化 ---
if "main_url_input" not in st.session_state:
    st.session_state["main_url_input"] = default_url
if "selected_preset_key" not in st.session_state:
    st.session_state["selected_preset_key"] = "-- 選択してください --"
if "custom_title_input" not in st.session_state:
    st.session_state["custom_title_input"] = ""


# --- コールバック関数の定義 ---

# 1. プリセットが選択されたとき
def on_preset_select():
    selected = st.session_state.get("selected_preset_key")
    if selected in SPOT_PRESETS:
        # URLを反映
        st.session_state["main_url_input"] = SPOT_PRESETS[selected]
        # タイトルにプリセット名を自動入力
        st.session_state["custom_title_input"] = selected


# 2. 手動でURLが入力・変更されたとき
def on_url_input_change():
    # 選択ボックスをデフォルトに戻す
    st.session_state["selected_preset_key"] = "-- 選択してください --"

    current_title = st.session_state.get("custom_title_input", "")
    # タイトル欄に入っている文字が「いずれかのプリセット名」と一致している場合はクリア
    if current_title in SPOT_PRESETS:
        st.session_state["custom_title_input"] = ""
    # ユーザーオリジナルの文字が書かれている場合はそのまま保持される


# --- ① 道を選択してください ---
st.markdown("### ① 道を選択してください")

# 1. プリセットセレクトボックス
st.selectbox(
    "主要ワインディングプリセット",
    options=["-- 選択してください --"] + list(SPOT_PRESETS.keys()),
    label_visibility="collapsed",
    key="selected_preset_key",
    on_change=on_preset_select,
)

# 2. アコーディオン（グレー背景化）
with st.expander("👉 独自の経路を入力する"):
    st.markdown("Googleマップで経路を検索して、そのURLをコピー＆ペーストしてください。")

    # 手動URL入力バー
    url_input = st.text_input(
        "URL入力欄",
        placeholder="https://www.google.com/maps/dir/...",
        label_visibility="collapsed",
        key="main_url_input",
        on_change=on_url_input_change,
    )

    # 画像（1.jpg）の表示
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(script_dir, "1.jpg")

    if os.path.exists(image_path):
        img_col1, img_col2 = st.columns([0.8, 0.2])
        with img_col1:
            st.image(image_path, use_container_width=True)
    else:
        st.info(f"※ 画像ファイル (1.jpg) が見つかりません。参照パス: {image_path}")

# --- ② タイトルを入力してください ---
st.markdown("### ② タイトルを入力してください")
st.text_input(
    "タイトル入力欄",
    placeholder="未入力の場合は自動で設定されます",
    label_visibility="collapsed",
    key="custom_title_input",
)

st.markdown("<br>", unsafe_allow_html=True)

if st.button("全ルート一括解析を実行", type="primary", use_container_width=True):
    # 最新の入力値を取得
    target_url = st.session_state.get("main_url_input", "").strip()
    user_title = st.session_state.get("custom_title_input", "").strip()

    if not api_key:
        st.error("APIキーが設定されていません。configファイル等を確認してください。")
    elif not target_url:
        st.warning("道を選択するか、GoogleマップのURLを入力してください。")
    else:
        with st.spinner("URL解析中..."):
            expanded_url = resolve_short_url(target_url)
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

                for i, route in enumerate(routes):
                    # タイトル未入力（空欄）または「自動」の場合はルートのサマリーを使用
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

                route_share_text = f"RoadRadarChartで解析したGoogle Mapsルートはこちら：\n{common_gmaps_url}"
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
            num_columns = max(3, len(all_results))
            cols = st.columns(num_columns)

            for i, res in enumerate(all_results):
                default_summary = res["default_summary"]
                combined_img = res["combined_img"]

                with cols[i]:
                    st.markdown(
                        f"""
                        <div style="min-height: 45px; margin-bottom: 4px;">
                            <h3 style="margin: 0 0 2px 0; font-size: 1.1rem;">ルート {i+1}</h3>
                            <div style="font-weight: bold; font-size: 1.0rem; color: #333;">{default_summary}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if combined_img:
                        st.markdown(
                            '<div style="font-size: 0.85rem; color: #555555; background-color: #f5f5f5; padding: 6px 10px; border-radius: 6px; border: 1px solid #dddddd; margin-bottom: 8px; text-align: center;">'
                            "📲 <b>画像を長押しして保存できます。</b>"
                            "</div>",
                            unsafe_allow_html=True,
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

        max_angle = thresholds_default.get("max_straight_angle_change_deg", 15.0)
        min_len = int(thresholds_default.get("min_straight_length_m", 300))

        st.markdown("### 🔍 分析パラメータ・各指標の判定基準")
        st.markdown(
            f"""
            <style>
                .param-table {{
                    font-size: 0.9rem;
                    line-height: 1.6;
                    border-collapse: collapse;
                    width: 100%;
                }}
                .param-table td {{
                    padding: 4px 8px;
                    border-bottom: 1px solid #ddd;
                }}
                .param-table .col-item {{
                    white-space: nowrap;
                    min-width: 140px;
                    font-weight: normal;
                }}
            </style>
            <table class="param-table">
                <tr><td class="col-item">🔴 ヘアピン</td><td>曲率半径 R < 80m のコーナー</td></tr>
                <tr><td class="col-item">🟠 中速コーナー</td><td>曲率半径 80m ≤ R < 200m のコーナー</td></tr>
                <tr><td class="col-item">🟢 ストレート</td><td>角度{max_angle}°以内で{min_len}m以上続く区間</td></tr>
                <tr><td class="col-item">🟣 激坂(上下)</td><td>勾配斜度 ±8% 以上</td></tr>
                <tr><td class="col-item">⚪ 総走行距離</td><td>Google情報の総走行距離(km)</td></tr>
                <tr><td class="col-item">⚪ 平均速度</td><td>Google情報の総走行距離(km) ÷ Google情報の所要時間(h)</td></tr>
            </table>
            """,
            unsafe_allow_html=True,
        )