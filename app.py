import streamlit as st
import google.generativeai as genai
import json
import os
import csv
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

# ページ設定
st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")

# --- スマホ画面用の文字サイズ調整 ---
st.markdown("""
<style>
h1 {
    font-size: 1.5rem !important;
    margin-top: 0.5rem !important;
}
h3 {
    font-size: 1.15rem !important;
}
p, label, .stMarkdown {
    font-size: 0.95rem !important;
}

/* スマホではほんの少しだけ小さく */
@media (max-width: 768px) {
    h1 {
        font-size: 1.4rem !important;
    }
    h3 {
        font-size: 1.1rem !important;
    }
    p, label, .stMarkdown {
        font-size: 0.95rem !important;
    }
}
</style>
""", unsafe_allow_html=True)

# Secrets から読み込み
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

# セッションステート初期化
def init_session_state():
    defaults = {
        "chat_history": [],
        "last_input_key": None,
        "results": [],
        "greeting": "",
        "tips": "",
        "user_feedback": None,
        "feedback_saved": False,
        "last_inputs": {},
        "retry_request": None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# キーワード辞書
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

# フィードバック保存
LOG_FILE = "feedback_log.csv"

def save_feedback(rating: str, meal_title: str, user_inputs: Dict[str, Any]):
    try:
        file_exists = os.path.isfile(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "timestamp", "rating", "meal_title",
                    "ingredients", "conditions", "constraints"
                ])
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                rating,
                meal_title,
                user_inputs.get("ingredients", ""),
                "|".join(user_inputs.get("conditions", [])),
                user_inputs.get("constraints", ""),
            ])
    except Exception:
        pass

# UI
st.title("🍳 平日夜ごはんサポート")
st.write("ポチポチ選ぶだけ。今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

st.markdown("### 🛒 食材の条件")

ingredients = st.text_input(
    "使いたい食材・家にあるもの *",
    placeholder="例：大根、ひき肉、豆腐",
    key="ingredients",
)

exclude_ingredients = st.text_input(
    "入れないもの（苦手なもの）",
    placeholder="例：ピーマン、トマト",
    key="exclude_ingredients",
)

cond_only_ingredients = st.checkbox(
    "この材料だけで作る（買い物なし）",
    value=False,
    key="cond_only_ingredients",
)

col_t1, col_t2 = st.columns(2)
with col_t1:
    cook_time = st.radio(
        "かけられる時間",
        ["5分", "10分", "15分", "20分"],
        index=1, horizontal=False,
    )
with col_t2:
    dish_type = st.radio(
        "主菜・副菜",
        ["主菜", "副菜", "どちらでも"],
        index=0,
    )

st.markdown("**その他の条件**")
c1, c2, c3 = st.columns(3)
extra_conditions = []

with c1:
    cond_one_pan = st.checkbox("ワンパン", value=False, key="cond_one_pan")
    cond_easy = st.checkbox("洗い物少なめ", value=False, key="cond_easy")
    cond_kid = st.checkbox("幼児向き", value=False, key="cond_kid")
with c2:
    cond_party = st.checkbox("パーティー向き", value=False, key="cond_party")
    cond_with_kid = st.checkbox("子どもと一緒に作れる", value=False, key="cond_with_kid")
with c3:
    cond_less_wash = st.checkbox("包丁いらず", value=False, key="cond_less_wash")
    cond_healthy = st.checkbox("健康に良さそう", value=False, key="cond_healthy")

# 条件リストの統合
for label, checked in [
    ("ワンパン", cond_one_pan), ("洗い物少なめ", cond_easy), ("幼児向き", cond_kid),
    ("パーティー向き", cond_party), ("子どもと一緒に作れる", cond_with_kid),
    ("包丁いらず", cond_less_wash), ("健康に良さそう", cond_healthy),
]:
    if checked:
        extra_conditions.append(label)

taste_level = st.radio(
    "味の濃さ",
    ["薄味", "普通", "濃い目"],
    index=1, horizontal=True,
)
spicy = st.toggle("辛い料理もOK", value=False)

constraints = st.text_input(
    "補足（任意）",
    placeholder="例：ちくわも消費したい、マヨネーズが少ない",
    key="constraints",
)

generate_btn = st.button("🍽 この条件でAIに聞く", type="primary", use_container_width=True)

# 再生成リクエストまたは新規生成ボタンが押された場合の処理
if generate_btn or st.session_state.retry_request:
    if not ingredients.strip():
        st.warning("使いたい食材を入力してください。")
    else:
        user_constraints = []

        if cond_one_pan:
            user_constraints.append("鍋・フライパンは1つだけで完結するレシピにすること")
        if cond_only_ingredients:
            user_constraints.append(
                f"【厳守ルール】ユーザーは「{ingredients}」だけで完結するレシピを求めています。\n"
                f"・上記以外の食材(野菜・肉・魚・調味料)を一切追加しないこと\n"
                f"・足りない分は「水少量・塩ひとつまみ」など、家庭に常備されている調味料のみ可\n"
                f"・新しく食材を買い足す提案は禁止\n"
                f"・材料リストにはユーザーが指定した食材以外は記載しないこと"
            )
        if exclude_ingredients.strip():
            user_constraints.append(f"【避けてほしい食材】{exclude_ingredients} は使わないこと")
        if extra_conditions:
            user_constraints.append(f"【追加条件】{', '.join(extra_conditions)}")
        if taste_level:
            user_constraints.append(f"【味付け】{taste_level}")
        if spicy:
            user_constraints.append("辛い味付けもOK")
        if constraints.strip():
            user_constraints.append(f"【補足要望】{constraints}")
        
        # もし再生成ボタンからの要望があればプロンプトに追加
        if st.session_state.retry_request:
            user_constraints.append(f"【重要：変更要望】前回の提案を踏まえ、次は「{st.session_state.retry_request}」という要望を満たす全く別の提案にしてください。")
            
        user_constraints.append(f"【調理時間】{cook_time}以内で完成すること")
        user_constraints.append(f"【カテゴリ】{dish_type}を作る")

        constraints_text = "\n".join(user_constraints)

        prompt = f"""あなたは「ポチコ」という夕食の献立提案AIアシスタントです。
ユーザーの夕食の献立相談に、親しみやすく寄り添う口調で答えてください。

# キャラクター設定
- 名前：ポチコ
- 口調：優しく、温かく、ママを励ます語りかけ
- 「ポチコが〜」「ポチコのおすすめ〜」のような表現
- 「〜だよ」「〜してみてね」などのやわらかい言葉を使う

# 提案ルール
- 日本語で出力
- 3つの献立候補を提案
- 各献立には分量付き材料リスト、簡単な手順、所要時間を必須
- 子ども連れママ向けにわかりやすく

# 制約
{constraints_text}

# 出力（厳密なJSON）
{{
  "greeting": "ポチコからユーザーへの優しいメッセージ（80文字程度）",
  "menus": [
    {{
      "name": "献立名",
      "time": "調理時間（例：約15分）",
      "appeal": "この献立の魅力・おすすめポイント（30〜40文字）",
      "ingredients": [
        {{"name": "材料名", "amount": "分量（例：200g, 1/2個, 大さじ2）"}}
      ],
      "steps": ["手順1", "手順2", "手順3"]
    }}
  ],
  "tips": "ポチコからの補足アドバイス（60文字程度）"
}}

# 家にある食材
{ingredients}
"""

        with st.spinner("今夜の候補を考えています（30秒ほどかかる場合があります）..."):
            ai_text = call_ai(prompt)

        if ai_text:
            parsed = safe_json_loads(ai_text)
            if parsed and "menus" in parsed:
                st.session_state.results = parsed["menus"]
                st.session_state.greeting = parsed.get("greeting", "")
                st.session_state.tips = parsed.get("tips", "")
                st.session_state.user_feedback = None
                st.session_state.feedback_saved = False
                st.session_state.last_inputs = {
                    "ingredients": ingredients,
                    "exclude_ingredients": exclude_ingredients,
                    "conditions": extra_conditions,
                    "constraints": constraints,
                }
            else:
                st.error("提案の読み取りに失敗しました。もう一度試してみてね。")
        else:
            if not GEMINI_API_KEY:
                st.error("APIキーが設定されていません。Streamlit Cloud の Secrets を確認してください。")
            else:
                st.error("ポチコとの通信がうまくいきませんでした。少し時間を置いてもう一度試してね。")
        
        # 再生成リクエストをリセット
        st.session_state.retry_request = None

# --- ここから「常に画面に結果を表示する」ための独立したブロック ---
if st.session_state.results:
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

            menu_name = menu.get('name', '')
            if menu_name:
                st.markdown("---")
                st.markdown("**🔧 ポチコが見つけたお役立ちアイテム**")
                keyword = get_item_keyword(menu_name)
                try:
                    query = quote_plus(keyword, safe='')
                except Exception:
                    query = quote_plus(keyword)
                if RAKUTEN_AFFILIATE_ID:
                    rakuten_url = (
                        f"[https://hb.afl.rakuten.co.jp/hgc/](https://hb.afl.rakuten.co.jp/hgc/){RAKUTEN_AFFILIATE_ID}/"
                        f"?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{query}%2F"
                        f"&link_type=hybrid_url"
                    )
                else:
                    rakuten_url = f"[https://search.rakuten.co.jp/search/mall/](https://search.rakuten.co.jp/search/mall/){query}/"
                st.link_button("🛒 楽天でチェック", rakuten_url, use_container_width=True)
                st.caption("※楽天市場の検索結果リンクです")

    if st.session_state.tips:
        st.success(f"💡 {st.session_state.tips}")
    st.caption("📸 移動前にレシピのスクショを撮るのをおすすめします")

    # 再生成ボタン
    st.markdown("---")
    st.write("**イメージと違ったら、近いものを選んでください**")
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        if st.button("もっと手抜きがいい", key="retry_easy"):
            st.session_state.retry_request = "もっと手抜きにしたい"
            st.rerun()
    with rc2:
        if st.button("違う味付けがいい", key="retry_taste"):
            st.session_state.retry_request = "違う味付けにして"
            st.rerun()
    with rc3:
        if st.button("調理法を変えたい", key="retry_method"):
            st.session_state.retry_request = "調理法を変えて"
            st.rerun()
    with rc4:
        if st.button("完全に別の案にする", key="retry_other"):
            st.session_state.retry_request = "全く別の案にして"
            st.rerun()

    # フィードバック
    st.markdown("---")
    meal_title = st.session_state.results[0].get("name", "") if st.session_state.results else ""
    if not st.session_state.feedback_saved:
        f1, f2, f3 = st.columns(3)
        with f1:
            if st.button("👍 役に立った", key="feedback_good"):
                st.session_state.feedback_saved = True
                save_feedback("Good", meal_title, st.session_state.last_inputs)
                st.toast("ありがとうございます！")
                st.rerun()
        with f2:
            if st.button("🤔 もう少し", key="feedback_normal"):
                st.session_state.feedback_saved = True
                save_feedback("Normal", meal_title, st.session_state.last_inputs)
                st.toast("次に活かします。")
                st.rerun()
        with f3:
            if st.button("👋 今回は使わない", key="feedback_bad"):
                st.session_state.feedback_saved = True
                save_feedback("Bad", meal_title, st.session_state.last_inputs)
                st.toast("ご意見ありがとうございます。")
                st.rerun()
    else:
        st.caption("評価ありがとうございました")

# フッター・免責事項
st.markdown("---")
st.caption("【免責事項】")
st.caption("・本アプリはAI（Gemini）による自動生成案を表示しています。正確性や安全性を保証できません。")
st.caption("・アレルギー物質の有無や、お子様の月齢・発達段階に合わせた調理判断は、必ず保護者の方が最終確認を行ってください。")
st.caption("・本提案を利用したことによるトラブルや損害について、当方は一切の責任を負いかねます。")
st.caption("Powered by Gemini | 平日夜ごはんサポート 🌙")
