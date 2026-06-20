# ============================================================
# 📦 インポート
# ============================================================
import streamlit as st
import google.generativeai as genai
import json
import os
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

# ============================================================
# ⚙️ ページ設定 & CSS
# ============================================================
st.set_page_config(
    page_title="平日夜ごはんサポート",
    page_icon="🍳",
    layout="centered",
    initial_sidebar_state="expanded",
)

# モバイル最適化CSS
st.markdown(
    """
<style>
    h1 {
        font-size: 1.3rem !important;
        margin-bottom: 0.5rem !important;
    }
    @media (max-width: 768px) {
        h1 {
            font-size: 1.2rem !important;
        }
        h2, h3 {
            font-size: 1.05rem !important;
        }
        p, div, li {
            font-size: 0.95rem !important;
        }
    }
    footer {visibility: hidden;}
    [data-testid="InputInstructions"] {
        visibility: hidden;
        height: 0;
    }
    .stButton > button {
        font-size: 1rem !important;
        padding: 0.5rem 1rem !important;
    }
    .debug-box {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
        border: 1px solid #ccc;
        font-family: monospace;
        font-size: 0.8rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 🔑 Secrets 取得（Streamlit Cloud から安全に）
# ============================================================
@st.cache_data(ttl=300)
def load_secrets():
    """Streamlit Cloud の Secrets から API キーと楽天IDを取得"""
    gemini_key = ""
    rakuten_id = ""
    try:
        if hasattr(st, "secrets") and st.secrets:
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
            rakuten_id = st.secrets.get("RAKUTEN_AFFILIATE_ID", "")
    except Exception:
        pass
    # フォールバック (環境変数)
    if not gemini_key:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not rakuten_id:
        rakuten_id = os.getenv("RAKUTEN_AFFILIATE_ID", "")
    return gemini_key, rakuten_id

GEMINI_API_KEY, RAKUTEN_AFFILIATE_ID = load_secrets()

# ============================================================
# 🧠 セッション状態の初期化
# ============================================================
def init_session_state():
    defaults = {
        "results": None,
        "error_message": None,
        "debug_mode": False,
        "last_status": "未実行",
        "last_raw_response": "",
        "last_response_length": 0,
        "last_error_type": "",
        "last_error_message": "",
        "last_prompt": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# ============================================================
# 🤖 Gemini モデル取得
# ============================================================
def get_genai_model():
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        st.session_state["last_error_type"] = type(e).__name__
        st.session_state["last_error_message"] = f"モデル初期化失敗: {str(e)}"
        return None

# ============================================================
# 📝 プロンプト構築
# ============================================================
def build_prompt(ingredients: str, options: Dict[str, bool]) -> str:
    constraints = []
    labels = {
        "quick": "調理時間は15分以内で済ませたい",
        "no_cooking": "火を一切使わない(電子レンジや混ぜるだけなど)",
        "one_pan": "フライパン1つだけで完結したい",
        "only_ingredients": "【最重要】他の食材を絶対に加えない。指定食材だけで完結する料理を提案",
        "lunchbox": "翌日のお弁当にも入れられるようにしたい",
        "kids_friendly": "子どもが食べやすい味付け・形状にしてほしい",
    }
    for key, label in labels.items():
        if options.get(key):
            constraints.append(f"- {label}")

    constraints_text = "\n".join(constraints) if constraints else "- 特に無し"

    system_instruction = f"""あなたは「ポチコ」という家庭料理AIアシスタントです。子どものいる共働き家庭のママ・パパ向けに、優しさあふれる口調で3つの献立を提案してください。

【★最重要ルール】
1. 3つのすべての献立に、指定された食材「{ingredients}」を必ず含めてください。指定食材を使わない料理は【絶対禁止】です。
2. 3つの献立の調理法を完全にバラバラにしてください(炒め物/スープ/レンジ/和え物 など分散)。
3. 主菜・副菜・主食・汁物 など、ジャンルも分散させてください。
4. 子どもが食べやすい味付け・切り方で提案してください。
5. 各献立に分量付き材料・3〜5手順・調理時間・ワンポイントアドバイスを必ず含めてください。

【出力形式 - 厳守】
- 必ず有効なJSON形式のみで出力
- 説明文・前置き・マークダウンフェンス(```json)は不要
- 最初の1文字は `{{`、最後の1文字は `}}`

【JSONスキーマ】
{{
  "crew_greeting": "ポチコからユーザーへの温かい挨拶(50〜80文字)",
  "candidates": [
    {{
      "title": "献立名",
      "dish_type": "ジャンル(主菜/副菜/汁物/丼 など)",
      "cooking_time": "約XX分",
      "appeal": "この献立の魅力、おすすめポイント(40〜60文字)",
      "ingredients": [
        {{"name": "材料名", "amount": "分量"}}
      ],
      "steps": ["手順1", "手順2", "手順3"],
      "tip": "ポチコからのワンポイントアドバイス(30〜50文字)",
      "recommended_item": {{
        "name": "おすすめアイテム名",
        "reason": "なぜ便利か(30〜50文字)",
        "keywords": ["検索キーワード1", "検索キーワード2"]
      }}
    }}
  ],
  "footer_advice": "ポチコからの補足メッセージ(60〜80文字)"
}}
"""
    user_prompt = f"""# 家にある食材
{ingredients}

# 追加条件
{constraints_text}

3つの異なる献立を提案してください。"""
    return system_instruction + "\n\n" + user_prompt


# ============================================================
# 🛒 楽天・アマゾン アフィリエイトリンク生成
# ============================================================
ITEM_KEYWORD_MAP = {
    "meat": ["解凍プレート", "時短調理"],
    "vegetable_cut": ["チョッパー", "スライサー", "野菜カッター"],
    "fried": ["ノンフライヤー", "エアフライヤー"],
    "rice": ["炊飯器 一人暮らし", "保温弁当箱"],
    "soup": ["スープジャー", "電子レンジ スープ容器"],
    "salad": ["サラダスピナー", "水切り容器"],
    "noodle": ["電子レンジ パスタ容器", "麺 茹で"],
    "fish": ["楽ちん 魚焼き"],
    "default": ["シリコンスチーマー", "時短料理"],
}


def recommend_keywords(dish_type: str, recommended_item_name: str = "") -> List[str]:
    keywords = []
    name_lower = recommended_item_name.lower()
    if any(k in recommended_item_name for k in ["肉", "解凍", "牛", "豚", "鶏"]):
        keywords.extend(ITEM_KEYWORD_MAP["meat"])
    if any(k in recommended_item_name for k in ["カッター", "スライサー", "チョッパー", "野菜"]):
        keywords.extend(ITEM_KEYWORD_MAP["vegetable_cut"])
    if any(k in recommended_item_name for k in ["フライ", "揚げ", "天ぷら"]):
        keywords.extend(ITEM_KEYWORD_MAP["fried"])
    if "ご飯" in recommended_item_name or "ライス" in recommended_item_name:
        keywords.extend(ITEM_KEYWORD_MAP["rice"])
    if "スープ" in recommended_item_name or "汁" in recommended_item_name:
        keywords.extend(ITEM_KEYWORD_MAP["soup"])
    if "サラダ" in recommended_item_name:
        keywords.extend(ITEM_KEYWORD_MAP["salad"])
    if "麺" in recommended_item_name or "パスタ" in recommended_item_name:
        keywords.extend(ITEM_KEYWORD_MAP["noodle"])
    if not keywords:
        keywords.extend(ITEM_KEYWORD_MAP["default"])
    return list(dict.fromkeys(keywords))[:2]  # 重複除去して2つまで


def generate_rakuten_link(keyword: str) -> Optional[str]:
    if not keyword:
        return None
    if not RAKUTEN_AFFILIATE_ID:
        # 楽天IDが未設定ならAmazonリンクにフォールバック
        return generate_amazon_link(keyword)
    encoded = quote_plus(keyword)
    return f"https://search.rakuten.co.jp/search/mall/{encoded}/?f=1&grp=ssl&sv=1&afid={RAKUTEN_AFFILIATE_ID}"


def generate_amazon_link(keyword: str) -> str:
    encoded = quote_plus(keyword)
    return f"https://www.amazon.co.jp/s?k={encoded}"


# ============================================================
# 🤖 Gemini 呼び出し
# ============================================================
def call_ai(prompt: str) -> Optional[str]:
    model = get_genai_model()
    if not model:
        st.session_state["last_status"] = "ERROR"
        if not GEMINI_API_KEY:
            st.session_state["last_error_type"] = "NoAPIKey"
            st.session_state["last_error_message"] = "GEMINI_API_KEY が Secrets に未登録"
        return None
    try:
        config = genai.GenerationConfig(
            temperature=0.3,
            top_p=0.8,
            top_k=40,
            max_output_tokens=4096,
            response_mime_type="application/json",
        )
        response = model.generate_content(prompt, generation_config=config)
        
        # デバッグ情報記録
        st.session_state["last_prompt"] = prompt[:500]
        
        if response and hasattr(response, "text") and response.text:
            raw = response.text
            st.session_state["last_status"] = "SUCCESS"
            st.session_state["last_raw_response"] = raw
            st.session_state["last_response_length"] = len(raw)
            return raw
        else:
            st.session_state["last_status"] = "EMPTY"
            st.session_state["last_error_message"] = "Gemini から空のレスポンス"
            return None
    except Exception as e:
        st.session_state["last_status"] = "ERROR"
        st.session_state["last_error_type"] = type(e).__name__
        st.session_state["last_error_message"] = str(e)
        return None


# ============================================================
# 🧩 堅牢な JSON パース
# ============================================================
def parse_ai_response(raw: str) -> Optional[Dict[str, Any]]:
    """AI の返答を堅牢にパースする"""
    if not raw:
        return None
    
    text = raw.strip()
    
    # パターン1: ```json ... ``` フェンス除去
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
    if m:
        text = m.group(1).strip()
    
    # パターン2: 最初の { から最後の } までを抽出
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    
    # パターン3: そのまま
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # パターン4: 壊れた JSON の救済 (閉じ括弧補完)
    try:
        # 末尾の不完全な JSON を切り落とす
        last = text.rfind("}")
        if last != -1:
            truncated = text[:last + 1]
            return json.loads(truncated)
    except json.JSONDecodeError:
        pass
    
    # パターン5: candidates 配列だけ抽出
    m = re.search(r'\{[\s\S]*"candidates"\s*:\s*\[([\s\S]*?)\][\s\S]*\}', text)
    if m:
        # 完全な JSON として再構築を試行
        try:
            return {"candidates": json.loads(f"[{m.group(1)}]")}
        except json.JSONDecodeError:
            pass
    
    return None


def normalize_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    """AI の出力を UI 用の形に統一"""
    ingredients = c.get("ingredients", [])
    # 材料がオブジェクトのリストなら文字列のリストに変換
    if ingredients and isinstance(ingredients[0], dict):
        ingredients = [
            f"{item.get('name', '')} {item.get('amount', '')}".strip()
            for item in ingredients
        ]
    return {
        "title": c.get("title") or c.get("name") or "（献立名なし）",
        "dish_type": c.get("dish_type", "主菜"),
        "cooking_time": c.get("cooking_time", "約15分"),
        "appeal": c.get("appeal") or c.get("reason", ""),
        "ingredients": ingredients,
        "steps": c.get("steps", []),
        "tip": c.get("tip", ""),
        "recommended_item": c.get("recommended_item", {}),
    }


def normalize_results(data: Dict[str, Any]) -> Dict[str, Any]:
    """AI の結果を UI 用の形に統一"""
    candidates_raw = (
        data.get("candidates")
        or data.get("menus")
        or []
    )
    candidates = [normalize_candidate(c) for c in candidates_raw]
    return {
        "greeting": data.get("crew_greeting") or data.get("greeting", ""),
        "candidates": candidates,
        "footer_advice": data.get("footer_advice") or data.get("tips", ""),
    }


# ============================================================
# 🎨 UI 表示関数
# ============================================================
def render_debug_sidebar():
    """サイドバーにデバッグ情報を表示"""
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🔧 デバッグ情報")
        st.session_state["debug_mode"] = st.checkbox(
            "デバッグモード",
            value=st.session_state.get("debug_mode", False),
            key="debug_checkbox",
        )

        if st.session_state.get("debug_mode"):
            st.write(f"**最終ステータス:** {st.session_state.get('last_status', '未実行')}")
            st.write(f"**API キー設定:** {'✅ あり' if GEMINI_API_KEY else '❌ なし'}")
            st.write(f"**楽天ID 設定:** {'✅ あり' if RAKUTEN_AFFILIATE_ID else '❌ なし'}")

            if st.session_state.get("last_status") == "SUCCESS":
                st.write(f"**返答長:** {st.session_state.get('last_response_length', 0)} 文字")
                raw = st.session_state.get("last_raw_response", "")
                st.text_area(
                    "Gemini 生出力 (先頭1000文字)",
                    raw[:1000] if raw else "(なし)",
                    height=200,
                )
            elif st.session_state.get("last_status") == "ERROR":
                st.write(f"**エラー種類:** {st.session_state.get('last_error_type', '?')}")
                st.text_area(
                    "エラーメッセージ",
                    st.session_state.get("last_error_message", "?"),
                    height=100,
                )
            
            # パース試行ボタン
            if st.session_state.get("last_raw_response"):
                if st.button("🔬 パースを再試行"):
                    parsed = parse_ai_response(st.session_state["last_raw_response"])
                    if parsed:
                        st.success(f"✅ パース成功！ {len(parsed.get('candidates', []))} 件取得")
                    else:
                        st.error("❌ パース失敗")
                        st.text_area(
                            "生出力(全文)",
                            st.session_state["last_raw_response"][:3000],
                            height=300,
                        )


def render_results(results: Dict[str, Any]):
    """AI の提案結果を画面に表示"""
    # 挨拶
    if results.get("greeting"):
        st.info(f"🐷 {results['greeting']}")
    
    # 3つの候補
    for idx, c in enumerate(results.get("candidates", []), 1):
        st.markdown(f"### 🍽️ 献立 {idx}: {c['title']}")
        st.caption(f"📂 {c['dish_type']} ／ ⏱️ {c['cooking_time']}")
        if c.get("appeal"):
            st.write(f"💡 **魅力**: {c['appeal']}")
        
        if c.get("ingredients"):
            with st.expander("📋 材料", expanded=True):
                for ing in c["ingredients"]:
                    st.write(f"- {ing}")
        
        if c.get("steps"):
            with st.expander("👩‍🍳 作り方", expanded=True):
                for i, step in enumerate(c["steps"], 1):
                    st.write(f"{i}. {step}")
        
        if c.get("tip"):
            st.success(f"✨ ポチコから: {c['tip']}")
        
        # おすすめアイテム
        item = c.get("recommended_item") or {}
        if item:
            st.markdown("##### 🛒 ポチコが見つけたお役立ちアイテム")
            st.write(f"**{item.get('name', 'おすすめアイテム')}**")
            if item.get("reason"):
                st.caption(item["reason"])
            # キーワード生成（item.name もしくは item.keywords から）
            kws = item.get("keywords") or []
            if not kws:
                kws = recommend_keywords(c.get("dish_type", ""), item.get("name", ""))
            # リンクボタン生成
            cols = st.columns(len(kws[:2]))
            for i, kw in enumerate(kws[:2]):
                with cols[i]:
                    link = generate_rakuten_link(kw)
                    st.markdown(
                        f'<a href="{link}" target="_blank">'
                        f'<button style="background-color:#E74C3C;color:white;border:none;padding:8px 16px;border-radius:5px;cursor:pointer;width:100%;">'
                        f'🔍 {kw} で探す</button></a>',
                        unsafe_allow_html=True,
                    )
        st.markdown("---")
    
    # 補足アドバイス
    if results.get("footer_advice"):
        st.success(f"🌟 {results['footer_advice']}")


# ============================================================
# 🚀 メイン画面
# ============================================================
def main():
    # タイトル
    st.title("🍳 平日夜ごはんサポート")
    st.write("ポチポチ選ぶだけ。今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    # 入力フォーム
    with st.form("main_form", clear_on_submit=False):
        st.markdown("### 🛒 家にある食材")
        ingredients = st.text_input(
            "食材をカンマ区切りで入力 (例: 鶏もも肉, 玉ねぎ, ブロッコリー)",
            placeholder="例: しめじ, ほうれん草, ツナ缶",
            value=st.session_state.get("ingredients_input", ""),
            key="ingredients_input",
        )

        st.markdown("### ⚙️ その他の条件")
        col1, col2, col3 = st.columns(3)
        with col1:
            opt_quick = st.checkbox("⚡ 15分以内")
            opt_no_cook = st.checkbox("🥗 火を使わない")
        with col2:
            opt_only = st.checkbox("🎯 この材料だけで作る")
            opt_one_pan = st.checkbox("🍳 ワンパンでできる")
        with col3:
            opt_lunch = st.checkbox("🍱 お弁当に使える")
            opt_kids = st.checkbox("👶 子どもが食べやすい")
        
        st.markdown("---")
        submitted = st.form_submit_button("🤖 ポチコに聞く（AIに聞く）", use_container_width=True)
    
    # デバッグサイドバー
    render_debug_sidebar()

    # AI 呼び出し
    if submitted:
        # API キーチェック
        if not GEMINI_API_KEY:
            st.error("⚠️ Gemini API キーが Streamlit Cloud の Secrets に設定されていません。")
            st.info("Settings → Secrets で `GEMINI_API_KEY = \"...\"` を追加してください。")
            return
        
        # 入力チェック
        if not ingredients.strip():
            st.warning("⚠️ 食材を入力してください。")
            return
        
        options = {
            "quick": opt_quick,
            "no_cooking": opt_no_cook,
            "one_pan": opt_one_pan,
            "only_ingredients": opt_only,
            "lunchbox": opt_lunch,
            "kids_friendly": opt_kids,
        }
        
        prompt = build_prompt(ingredients, options)
        with st.spinner("🐷 ポチコが献立を考えています..."):
            raw = call_ai(prompt)
        
        if not raw:
            st.error(f"💭 ポチコとの通信がうまくいきませんでした。少し時間を置いてもう一度試してね。")
            if st.session_state.get("debug_mode"):
                st.info("サイドバーのデバッグ情報を確認してください。")
            return
        
        # パース
        parsed = parse_ai_response(raw)
        if not parsed:
            st.error("💭 提案の読み取りに失敗しました。もう一度試してね。")
            if st.session_state.get("debug_mode"):
                st.info("サイドバーに生の出力を表示しています。「パースを再試行」ボタンも試してみてください。")
                st.code(raw[:2000] if raw else "(空)", language="json")
            return
        
        # 正規化して保存
        normalized = normalize_results(parsed)
        st.session_state["results"] = normalized
        st.session_state["error_message"] = None
    
    # 結果表示
    if st.session_state.get("results"):
        st.markdown("---")
        render_results(st.session_state["results"])
        
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 別の献立を提案", use_container_width=True):
                # 再生成
                ingredients = st.session_state.get("ingredients_input", "")
                options = {
                    "quick": st.session_state.get("opt_quick", False),
                    "no_cooking": st.session_state.get("opt_no_cook", False),
                    "one_pan": st.session_state.get("opt_one_pan", False),
                    "only_ingredients": st.session_state.get("opt_only", False),
                    "lunchbox": st.session_state.get("opt_lunch", False),
                    "kids_friendly": st.session_state.get("opt_kids", False),
                }
                if ingredients.strip() and GEMINI_API_KEY:
                    prompt = build_prompt(ingredients, options)
                    with st.spinner("🐷 ポチコが別の献立を考えています..."):
                        raw = call_ai(prompt)
                    if raw:
                        parsed = parse_ai_response(raw)
                        if parsed:
                            st.session_state["results"] = normalize_results(parsed)
                            st.rerun()


main()
