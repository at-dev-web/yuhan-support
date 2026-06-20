import streamlit as st
import google.generativeai as genai
import json
import os
import re
from urllib.parse import quote_plus
from typing import Optional, Dict, Any, List

# ページ設定
st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")

# Secrets から読み込み
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def normalize_ingredients(text: str) -> str:
    """食材入力を自動整形：スペース・読点も全部カンマ区切りに揃える"""
    if not text:
        return ""
    text = text.strip()
    text = text.replace("、", ",").replace("，", ",").replace("　", " ")
    text = re.sub(r"[、，,;；]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    parts = [p.strip() for p in text.split(" ") if p.strip()]
    return ", ".join(parts)


def clean_generated_text(text: str, ingredient_csv: str = "") -> str:
    """
    生成テキストから不要な敬称・プレースホルダーを取り除く
    """
    if not isinstance(text, str):
        return text
    cleaned = text
    # プレースホルダー
    cleaned = cleaned.replace("〇〇", "この食材")
    cleaned = cleaned.replace("◯◯", "この食材")
    cleaned = cleaned.replace("XXX", "")
    cleaned = cleaned.replace("xx", "")
    # 食材名敬称Cleanup（食材リストに一致した場合のみ）
    ingredients = [x.strip() for x in ingredient_csv.split(",") if x.strip()]
    for ing in ingredients:
        cleaned = cleaned.replace(f"{ing}さん", ing)
        cleaned = cleaned.replace(f"{ing}ちゃん", ing)
    # 全角丸記号で囲まれたプレースホルダー
    cleaned = re.sub(r"『[〇◯]+』", "この食材", cleaned)
    cleaned = re.sub(r"「[〇◯]+」", "この食材", cleaned)
    cleaned = re.sub(r"[〇◯]{2,}", "この食材", cleaned)
    # 「食材名さん」「食材名ちゃん」など CSV を越えて一般的に付く敬称も一応ケア
    common_suffixes = [
        "さん", "ちゃん", "くん", "様",
    ]
    # ruffus じゃなく、食材リスト以外の言葉には触らないが、明らかに変な「◯◯さん」等はここで救済
    cleaned = re.sub(r"[〇◯]+さん", "この食材", cleaned)
    cleaned = re.sub(r"[〇◯]+ちゃん", "この食材", cleaned)
    # 連続スペース整理
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    _ = common_suffixes  # noqa
    return cleaned


def sanitize_result(result: Dict[str, Any], ingredient_csv: str) -> Dict[str, Any]:
    """
    AI が返した結果を画面に出す前に整える
    """
    if not isinstance(result, dict):
        return result
    if "meal_title" in result:
        result["meal_title"] = clean_generated_text(
            result.get("meal_title", ""), ingredient_csv
        )
    if "summary" in result:
        result["summary"] = clean_generated_text(
            result.get("summary", ""), ingredient_csv
        )
    candidates = result.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ["menu_name", "dish_type", "reason", "tip"]:
                if key in candidate:
                    candidate[key] = clean_generated_text(
                        candidate.get(key, ""), ingredient_csv
                    )
            if isinstance(candidate.get("ingredients"), list):
                candidate["ingredients"] = [
                    clean_generated_text(item, ingredient_csv)
                    for item in candidate["ingredients"]
                ]
            if isinstance(candidate.get("steps"), list):
                candidate["steps"] = [
                    clean_generated_text(step, ingredient_csv)
                    for step in candidate["steps"]
                ]
    if isinstance(result.get("ad_suggestion"), dict):
        ad = result["ad_suggestion"]
        ad["title"] = clean_generated_text(ad.get("title", ""), ingredient_csv)
        ad["reason"] = clean_generated_text(ad.get("reason", ""), ingredient_csv)
    return result


# CSS
st.markdown(
    """
<style>
small{display:none!important}
div[data-testid="stMarkdownContainer"] p{font-size:1rem}
h1{font-size:clamp(1.5rem,5vw,2.2rem)!important;line-height:1.2!important}
h3{font-size:clamp(1.2rem,4vw,1.8rem)!important;line-height:1.2!important}
.stSuccess h3{font-size:1.1rem!important}
</style>
""",
    unsafe_allow_html=True,
)


def init_session_state():
    if "latest_result" not in st.session_state:
        st.session_state.latest_result = None
    if "last_inputs" not in st.session_state:
        st.session_state.last_inputs = None
    if "user_feedback" not in st.session_state:
        st.session_state.user_feedback = None


def get_genai_model():
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-2.5-flash")
    except Exception:
        return None


def build_prompt(inputs, retry_type=None):
    system_instruction = """
あなたは「ポチコ」という名前の献立アドバイザーです。
現実的で作りやすく、おいしい夕食候補を3品提案してください。
やさしいトーンで、寄り添うような言葉遣いをしてください。

必ず以下のJSON形式でのみ回答してください：
{
  "meal_title": "ポチコのおすすめ候補",
  "summary": "今回の3候補の全体説明",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜または副菜",
      "reason": "提案理由",
      "ingredients": ["ひき肉 200g", "大根 1/4本"],
      "steps": ["手順1", "手順2"],
      "tip": "ポチコの推しポイント"
    }
  ],
  "ad_suggestion": {"title": "アイテム名", "reason": "おすすめ理由"}
}

【重要】
- ingredients（材料）には、必ず「分量（目安）」を併記してください。
- 分量は一般的な単位（g、個、本、大さじ等）で具体的に。

【文章ルール】
- summary は2文以内で、自然な日本語にしてください。
- 食材名に「さん」「ちゃん」などの敬称を付けないでください（例: 「ほうれん草さん」は禁止）。
- 「〇〇」「◯◯」「XXX」などのプレースホルダーを出力しないでください。
- 変な記号や記号だけの残骸、意味不明な擬人化表現を出さないでください。
- 「〜な夜に」「忙しい日の味方」など、読める自然な日本語にしてください。
"""
    retry_context = ""
    if retry_type:
        retry_context = f"\n【再提案条件】{retry_type}を重視して、内容をガラッと変えてください。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理も提案可能です。" if inputs["spicy"] else "辛い料理は提案しないでください。"

    only_ingredients_constraint = ""
    if "この材料だけで作る" in inputs["conditions"]:
        only_ingredients_constraint = f"""
【重要・厳守ルール】「この材料だけで作る」が選択されました。
- 使いたい食材「{inputs['ingredients']}」だけで完結するレシピにすること
- 上記以外の食材（野菜・肉・魚・調味料）を一切追加しないこと
- 足りない分は「水少量・塩ひとつまみ」など、家庭に常備されている調味料のみ可
- 新しく食材を買い足す提案は禁止
"""

    prompt = f"""
今夜の献立を3品提案して。{retry_context}
- 使いたい食材: {inputs['ingredients']}
- 苦手なもの: {inputs['exclude_ingredients']}
- 時間: {inputs['cook_time']}
- 種類: {inputs['dish_type']}
- 条件: {conditions_text}
- 味: {inputs['taste_level']}
- 補足: {inputs['constraints']}
- 辛さ: {spicy_rule}
{only_ingredients_constraint}
"""
    return system_instruction + "\n" + prompt


def call_ai(prompt: str) -> Optional[str]:
    model = get_genai_model()
    if model is None:
        return None
    try:
        response = model.generate_content(prompt)
        return response.text if hasattr(response, "text") else None
    except Exception:
        return None


def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text:
        return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        return json.loads(response_text[start:end])
    except Exception:
        return None


def run_retry(retry_label: str):
    if not st.session_state.last_inputs:
        return
    with st.spinner(f"「{retry_label}」で考え直しています..."):
        response = call_ai(build_prompt(st.session_state.last_inputs, retry_label))
        if response:
            result = parse_ai_response(response)
            if result:
                result = sanitize_result(
                    result, st.session_state.last_inputs["ingredients"]
                )
                st.session_state.latest_result = result
                st.session_state.user_feedback = None
                st.rerun()


def get_item_keyword(item_name: str) -> str:
    keywords = {
        "お肉": "解凍プレート+肉", "肉": "解凍プレート+肉",
        "鶏": "解凍プレート+鶏肉", "豚": "解凍プレート+豚肉",
        "牛": "解凍プレート+牛肉", "魚": "解凍プレート+魚",
        "野菜": "キッチンばさみ+野菜", "サラダ": "スライサー+野菜",
        "カット": "スライサー+野菜", "揚げ": "ノンフライヤー",
        "フライ": "ノンフライヤー", "天ぷら": "ノンフライヤー",
        "コロッケ": "ノンフライヤー",
        "ごぼう": "ごぼうの皮むき手袋",
        "にんじん": "スライサー+野菜",
        "大根": "スライサー+大根",
        "スープ": "電子レンジ対応容器+スープ",
        "パスタ": "パスタ鍋", "麺": "麺ボウル",
        "丼": "丼ぶり鉢",
        "オムライス": "卵ふわふわメーカー",
        "ハンバーグ": "ハンバーグ成形器",
        "カレー": "圧力鍋", "煮物": "圧力鍋",
        "中華": "中華鍋", "焼き": "耐熱フライパン",
        "蒸し": "電子レンジ対応蒸し器",
    }
    for key, kw in keywords.items():
        if key in item_name:
            return kw
    return f"{item_name}+キッチン用品"


def render_candidate_card(candidate: Dict[str, Any], idx: int):
    with st.container(border=True):
        st.markdown(f"### {idx}. {candidate.get('menu_name', '')}")
        if candidate.get("dish_type"):
            st.caption(candidate.get("dish_type"))
        st.write(f"**おすすめ理由**：{candidate.get('reason', '')}")
        with st.expander("🍳 材料と作り方を見る"):
            st.markdown("**🛒 材料（分量の目安）**")
            for item in candidate.get("ingredients", []):
                st.write(f"- {item}")
            st.write("")
            st.markdown("**👩‍🍳 作り方の手順**")
            for i, step in enumerate(candidate.get("steps", []), 1):
                st.write(f"{i}. {step}")
        st.info(f"✨ ポチコの推しポイント：{candidate.get('tip', '')}")


def render_result(result: Dict[str, Any]):
    st.success(f"### {result.get('meal_title', 'ポチコのおすすめ候補')}")
    st.write(result.get("summary", ""))
    for idx, candidate in enumerate(result.get("candidates", [])[:3], start=1):
        render_candidate_card(candidate, idx)

    ad = result.get("ad_suggestion")
    if isinstance(ad, dict) and ad.get("title"):
        item_name = ad.get("title", "")
        search_keyword = get_item_keyword(item_name)
        query = quote_plus(search_keyword)
        st.write("---")
        st.subheader("🛠 ポチコが見つけたお役立ちアイテム")
        with st.container(border=True):
            st.markdown(f"#### {item_name}")
            st.write(ad.get("reason", ""))
            st.caption("💡 ジャンルに応じて最適なキッチングッズを検索")
            col1, col2 = st.columns(2)
            with col1:
                st.link_button("Amazonでチェック", f"https://www.amazon.co.jp/s?k={query}", use_container_width=True)
            with col2:
                if RAKUTEN_AFFILIATE_ID:
                    rakuten_url = (
                        f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/"
                        f"?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{query}%2F"
                        f"&link_type=hybrid_url"
                    )
                    st.link_button("楽天でチェック", rakuten_url, use_container_width=True)
                else:
                    st.link_button("楽天でチェック", f"https://search.rakuten.co.jp/search/mall/{query}/", use_container_width=True)
        st.caption("※ポチコおすすめの商品ページへ移動します。移動前にレシピのスクショをおすすめします。")


def main():
    init_session_state()
    st.title("🍳 夜ごはんサポート")
    st.write("今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    raw_ingredients = st.text_input(
        "使いたい食材・家にあるもの *",
        placeholder="例：大根、ひき肉、豆腐  （スペースでも , でもOK）",
        value=st.session_state.get("ingredients_raw", ""),
        key="ingredients_raw",
    )

    raw_exclude = st.text_input(
        "入れないもの（苦手なもの）",
        placeholder="例：ピーマン、トマト",
        value=st.session_state.get("exclude_raw", ""),
        key="exclude_raw",
    )

    normalized_ingredients = normalize_ingredients(raw_ingredients)
    normalized_exclude = normalize_ingredients(raw_exclude)

    if raw_ingredients and normalized_ingredients != raw_ingredients:
        st.caption(f"✅ 認識された食材: `{normalized_ingredients}`")

    col1, col2 = st.columns(2)
    with col1:
        cook_time = st.radio("かけられる時間 *", ["5分", "10分", "15分", "20分"], index=1)
    with col2:
        dish_type = st.radio("何を作りたいですか *", ["主菜", "副菜", "どちらでも"], index=0)

    st.write("**条件（あてはまるものを選んでください）**")
    c1, c2, c3 = st.columns(3)
    with c1:
        cond_less_ingredients = st.checkbox("この材料だけで作る")
        cond_one_pan = st.checkbox("ワンパンでできる")
    with c2:
        cond_less_wash = st.checkbox("洗い物少なめ")
        cond_kid = st.checkbox("幼児向き")
    with c3:
        cond_party = st.checkbox("パーティー・おもてなし向き")
        cond_with_kids = st.checkbox("子どもと一緒に作れる")

    conditions = [l for l, c in zip(
        ["この材料だけで作る", "ワンパンでできる", "洗い物少なめ", "幼児向き", "パーティー・おもてなし向き", "子どもと一緒に作れる"],
        [cond_less_ingredients, cond_one_pan, cond_less_wash, cond_kid, cond_party, cond_with_kids]
    ) if c]

    taste_level = st.radio("味の濃さ *", ["薄味", "普通", "濃い目"], index=1, horizontal=True)
    spicy = st.toggle("辛い料理もOK", value=False)
    constraints = st.text_input("補足（任意）", placeholder="例：ちくわも消費したい")

    if st.button("この条件でポチコに聞く", type="primary", use_container_width=True):
        if not normalized_ingredients:
            st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.latest_result = None
            st.session_state.user_feedback = None
            st.session_state.last_inputs = {
                "ingredients": normalized_ingredients,
                "exclude_ingredients": normalized_exclude,
                "cook_time": cook_time, "dish_type": dish_type,
                "conditions": conditions, "taste_level": taste_level,
                "spicy": spicy, "constraints": constraints,
            }
            with st.spinner("ポチコが今夜の候補を考えています..."):
                if not GEMINI_API_KEY:
                    st.error("APIキーが設定されていません。Streamlit Cloud の Secrets を確認してください。")
                else:
                    resp = call_ai(build_prompt(st.session_state.last_inputs))
                    if resp:
                        result = parse_ai_response(resp)
                        if result:
                            result = sanitize_result(
                                result, normalized_ingredients
                            )
                            st.session_state.latest_result = result
                        else:
                            st.error("提案の読み取りに失敗しました。もう一度試してみてね。")
                    else:
                        st.error("ポチコとの通信がうまくいきませんでした。少し時間を置いてもう一度試してね。")

    if st.session_state.latest_result:
        render_result(st.session_state.latest_result)
        st.write("---")
        st.write("イメージと違ったら、近いものを選んでください。")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if st.button("もっと手抜きがいい"):
                run_retry("もっと手抜きがいい")
        with c2:
            if st.button("ちがう味付けがいい"):
                run_retry("ちがう味付けがいい")
        with c3:
            if st.button("調理法を変えたい"):
                run_retry("調理法を変えたい")
        with c4:
            if st.button("完全に別の案にする"):
                run_retry("完全に別の案にする")

        st.write("---")
        if st.session_state.user_feedback is None:
            f1, f2, f3 = st.columns(3)
            with f1:
                if st.button("👍 役に立った"):
                    st.session_state.user_feedback = "Good"
                    st.toast("ありがとうございます！")
            with f2:
                if st.button("🤔 もう少し"):
                    st.session_state.user_feedback = "Normal"
                    st.toast("次に活かします。")
            with f3:
                if st.button("👋 今回は使わない"):
                    st.session_state.user_feedback = "Bad"
                    st.toast("ご意見ありがとうございます。")
        else:
            st.caption("評価ありがとうございます！")

    st.write("---")
    st.caption("無料公開のため、画面上部に Streamlit の Fork ボタン等が表示されることがあります。")
    st.caption("【免責事項】AI生成案です。保護者の方が最終確認を行ってください。")


if __name__ == "__main__":
    main()
