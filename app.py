import streamlit as st
import google.generativeai as genai
import json
import os
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

# ページ設定
st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")

# セキュリティ設定（Secrets から読み込む）
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

# 初期化
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_input_key" not in st.session_state:
    st.session_state.last_input_key = None
if "results" not in st.session_state:
    st.session_state.results = []

@st.cache_data(show_spinner=False)
def call_ai(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        if response and hasattr(response, "text") and response.text:
            return response.text
        return None
    except Exception:
        return None

def safe_json_loads(text: str) -> Optional[Dict[str, Any]]:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception:
        return None

def get_item_keyword(item_name: str) -> str:
    keywords = {
        "お肉": "解凍プレート+肉",
        "肉": "解凍プレート+肉",
        "鶏": "解凍プレート+鶏肉",
        "豚": "解凍プレート+豚肉",
        "牛": "解凍プレート+牛肉",
        "魚": "解凍プレート+魚",
        "野菜": "キッチンばさみ+野菜",
        "サラダ": "スライサー+野菜",
        "カット": "スライサー+野菜",
        "揚げ": "ノンフライヤー",
        "フライ": "ノンフライヤー",
        "天ぷら": "ノンフライヤー",
        "コロッケ": "ノンフライヤー",
        "ごぼう": "ごぼうの皮むき手袋",
        "にんじん": "スライサー+野菜",
        "大根": "スライサー+大根",
        "スープ": "電子レンジ対応容器+スープ",
        "パスタ": "パスタ鍋",
        "麺": "麺ボウル",
        "丼": "丼ぶり鉢",
        "オムライス": "卵ふわふわメーカー",
        "ハンバーグ": "ハンバーグ成形器",
        "カレー": "圧力鍋",
        "煮物": "圧力鍋",
        "中華": "中華鍋",
        "焼き": "耐熱フライパン",
        "蒸し": "電子レンジ対応蒸し器",
    }
    for key, kw in keywords.items():
        if key in item_name:
            return kw
    return f"{item_name}+キッチン用品"

# UI
st.title("🍳 平日夜ごはんサポート")
st.markdown("ポチコが、今日のあなたの条件に合わせてかんたんな夜ごはんを3つ提案します。")

# 入力欄
st.markdown("### 🛒 食材の条件")
col1, col2 = st.columns(2)
with col1:
    use_extras = st.checkbox("ワンパンでできる", value=True, key="use_extras")
with col2:
    only_ingredients = st.checkbox("この材料だけで作る", value=False, key="only_ingredients")

ingredients_text = st.text_area(
    "使う材料（持っているもの）",
    placeholder="例）鶏もも肉、じゃがいも、にんじん",
    key="ing_text_area",
    height=80,
)

avoid_text = st.text_area(
    "使わない材料（アレルギー・苦手など）",
    placeholder="例）乳製品、辛いもの",
    key="avoid_text_area",
    height=60,
)

free_text = st.text_area(
    "リクエスト・わがまま",
    placeholder="例）15分以内で作りたい・和食がいい・子どもが喜びそうなもの",
    key="free_text_area",
    height=80,
)

# ボタン
generate_btn = st.button("🍽 ポチコに聞いてみる", type="primary", use_container_width=True)

if generate_btn:
    ing_text = (ingredients_text or st.session_state.get("ing_text_area", "")).strip()
    avoid = (avoid_text or st.session_state.get("avoid_text_area", "")).strip()
    free = (free_text or st.session_state.get("free_text_area", "")).strip()

    if not ing_text:
        st.warning("「使う材料」を1つ以上入力してね")
    else:
        # プロンプト作成
        user_constraints = []

        if use_extras:
            user_constraints.append(
                "鍋・フライパンは1つだけで完結するレシピにすること（複数の調理器具を使わない）"
            )

        if only_ingredients:
            user_constraints.append(
                f"【厳守ルール】ユーザーは「{ing_text}」だけで完結するレシピを求めています。\n"
                f"・上記以外の食材(野菜・肉・魚・調味料)を一切追加しないこと\n"
                f"・足りない分は「水少量・塩ひとつまみ」など、家庭に常備されている最低限の調味料のみ可\n"
                f"・新しく食材を買い足す提案は禁止\n"
                f"・材料リストにはユーザーが指定した食材以外は記載しないこと"
            )

        if avoid:
            user_constraints.append(f"【避けてほしい食材】{avoid} は使わないこと")

        if free:
            user_constraints.append(f"【リクエスト】{free}")

        constraints_text = "\n".join(user_constraints)

        prompt = f"""あなたは「ポチコ」というキャラクターです。ユーザーの夕食の献立相談に、親しみやすく寄り添う口調で答えてください。

# キャラクター設定
- 名前：ポチコ
- 口調：優しく、温かく、ママを励ますような語りかけ
- 一人称は使わず「ポチコが〜」「ポチコのおすすめ〜」のような表現
- 「〜だよ」「〜してみてね」「きっと喜ぶよ」などのやわらかい言葉を使う

# 提案ルール
- 日本語で出力
- 3つの献立候補を必ず提案
- 各献立には分量付きの材料リスト、簡単な手順、所要時間を必ず記載
- 子ども連れママ向けにわかりやすく

# ポチコの制約
{constraints_text}

# 出力フォーマット(JSON形式で厳密に出力)
{{
  "greeting": "ポチコからユーザーへの優しいメッセージ（80文字程度）",
  "menus": [
    {{
      "name": "献立名",
      "time": "調理時間（例：約15分）",
      "appeal": "この献立の魅力・おすすめポイント（40文字程度）",
      "ingredients": [
        {{"name": "材料名", "amount": "分量（例：200g, 1/2個, 大さじ2）"}}
      ],
      "steps": ["手順1", "手順2", "手順3"]
    }}
  ],
  "tips": "ポチコからの補足アドバイス（安全・時短・子どもの反応など、60文字程度）"
}}

# 使う材料
{ing_text}
"""

        with st.spinner("ポチコが考えています（30秒ほどかかる場合があります）..."):
            ai_text = call_ai(prompt)

        if ai_text:
            parsed = safe_json_loads(ai_text)
            if parsed and "menus" in parsed:
                st.session_state.results = parsed["menus"]
                st.session_state.greeting = parsed.get("greeting", "")
                st.session_state.tips = parsed.get("tips", "")

                if st.session_state.greeting:
                    st.info(f"🐾 {st.session_state.greeting}")

                for i, menu in enumerate(st.session_state.results, 1):
                    with st.container(border=True):
                        st.markdown(f"### 🍴 献立{i}：{menu.get('name', '名前未設定')}")

                        if menu.get('time'):
                            st.caption(f"⏱ {menu['time']}")
                        if menu.get('appeal'):
                            st.write(menu['appeal'])

                        if menu.get('ingredients'):
                            st.markdown("**📋 材料（目安）**")
                            for ing in menu['ingredients']:
                                name = ing.get('name', '')
                                amount = ing.get('amount', '')
                                if amount:
                                    st.write(f"・{name} … {amount}")
                                else:
                                    st.write(f"・{name}")

                        if menu.get('steps'):
                            st.markdown("**👩‍🍳 手順**")
                            for j, step in enumerate(menu['steps'], 1):
                                st.write(f"{j}. {step}")

                        # 🔧 ポチコが見つけたお役立ちアイテム
                        menu_name = menu.get('name', '')
                        if menu_name:
                            st.markdown("---")
                            st.markdown("**🔧 ポチコが見つけたお役立ちアイテム**")
                            st.caption("※楽天市場での検索結果リンクです")

                            keyword = get_item_keyword(menu_name)

                            try:
                                query = quote_plus(keyword, safe='')
                            except Exception:
                                query = quote_plus(keyword)

                            # 楽天ボタン
                            if RAKUTEN_AFFILIATE_ID:
                                rakuten_url = (
                                    f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/"
                                    f"?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{query}%2F"
                                    f"&link_type=hybrid_url"
                                )
                                st.link_button("🛒 楽天でチェック", rakuten_url, use_container_width=True)
                            else:
                                st.link_button(
                                    "🛒 楽天でチェック",
                                    f"https://search.rakuten.co.jp/search/mall/{query}/",
                                    use_container_width=True,
                                )

                            st.caption("💡 ジャンル例：お肉→解凍プレート／野菜カット→スライサー／揚げ物→ノンフライヤー／ごぼう→皮むき手袋")

                if st.session_state.tips:
                    st.success(f"💡 {st.session_state.tips}")

                st.caption("📸 移動前にレシピのスクショを撮るのをおすすめします")
            else:
                st.error("ポチコからの提案を読み込めませんでした。もう一度試してみてね。")
        else:
            if not GEMINI_API_KEY:
                st.error("APIキーが設定されていません。Streamlit Cloud の Secrets を確認してください。")
            else:
                st.error("ポチコとの通信がうまくいきませんでした。少し時間を置いてもう一度試してね。")

# フッター
st.markdown("---")
st.caption("Powered by Gemini | 平日夜ごはんサポート 🌙")
