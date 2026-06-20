import streamlit as st
import google.generativeai as genai
import json
import os
from urllib.parse import quote_plus
from typing import Optional, Dict, Any

# Secrets から安全な読み込み
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

def get_genai_model():
    """毎回モデルを取得（キャッシュしない）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.5-flash")
    except Exception:
        return None

# ページ設定
st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")

# --- セキュリティ設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- CSSで見た目を一気に調整 ---
st.markdown(
    """
    <style>
    /* 1. 「Press Enter to submit form」を強制非表示 */
    small { display: none !important; }
    div[data-testid="stMarkdownContainer"] p { font-size: 1rem; }

    /* 2. スマホでタイトルや料理名が2行にならないようサイズ調整 */
    h1 { font-size: clamp(1.5rem, 5vw, 2.2rem) !important; line-height: 1.2 !important; }
    h3 { font-size: clamp(1.2rem, 4vw, 1.8rem) !important; line-height: 1.2 !important; }

    /* 3. 成功メッセージ内のタイトルも小さく */
    .stSuccess h3 { font-size: 1.1rem !important; }
    </style>
    """,
    unsafe_allow_html=True
)

def init_session_state():
    if "latest_result" not in st.session_state:
        st.session_state.latest_result = None
    if "last_inputs" not in st.session_state:
        st.session_state.last_inputs = None
    if "user_feedback" not in st.session_state:
        st.session_state.user_feedback = None

def build_prompt(inputs: Dict[str, Any], retry_type: Optional[str] = None) -> str:
    system_instruction = """
あなたは「ポチコ」という名前の献立アドバイザーです。
現実的で作りやすく、おいしい夕食候補を3品提案してください。
「お子さん」という言葉を使い、やさしく寄り添うトーンで。

# 厳守ルール（全献立共通・最重要）
1. 【食材厳守】ユーザーが指定した食材は、必ず3品中【すべて】に使うこと
   - 1品でも指定食材が入っていない献立はNG
   - 食材名は日本語で正確に（例：「しめじ」「ほうれん草」「きゅうり」）
2. 【多様性ルール】3品は互いに違う特徴にすること
   - ❌ 同じ調理法3つ（炒める・炒める・炒める）
   - ❌ 同じ主食材3つ（ツナ・ツナ・ツナ）
   - ✅ 調理法：「炒める」「和える」「スープ」「焼く」「煮る」「揚げる」から3つ選ぶ
   - ✅ 主食材：鶏・豚・牛・卵・魚・豆腐をそれぞれ違う献立で主役にする
3. 【分量厳守】ingredientsリストには必ず分量（目安）を併記
   - 例：「しめじ 1株」「ほうれん草 1/2束」「鶏もも肉 200g」

# JSON出力形式（厳密・必須）
{
  "meal_title": "ポチコのおすすめ候補",
  "summary": "今回の3候補の全体説明（指定食材の活用ポイントも触れる）",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜または副菜",
      "reason": "提案理由",
      "ingredients": ["材料名 分量", "材料名 分量"],
      "steps": ["手順1", "手順2"],
      "tip": "ポチコの推しポイント"
    }
  ],
  "ad_suggestion": {"title": "アイテム名", "reason": "おすすめ理由"}
}
"""
    retry_context = ""
    if retry_type:
        retry_context = f"\n【再提案条件】{retry_type}を重視して、内容をガラッと変えてください。前回と被らない献立にすること。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理も提案可能です。" if inputs["spicy"] else "辛い料理は提案しないでください。"

    only_ingredients_constraint = ""
    if "この材料だけで作る" in inputs["conditions"]:
        only_ingredients_constraint = f"""
【厳守】「この材料だけで作る」が選ばれました。
- 使いたい食材「{inputs['ingredients']}」だけで完結するレシピにすること
- 上記以外の食材(野菜・肉・魚・調味料)を一切追加しないこと
- 足りない分は「水少量・塩ひとつまみ」など、家庭に常備されている調味料のみ可
- 新しく食材を買い足す提案は絶対禁止
- 材料リストにはユーザーが指定した食材以外は記載しないこと
"""

    # 入力食材リストを明示的に使うよう指示
    ingredients_check = f"""
# 食材使用チェックリスト
指定食材: {inputs['ingredients']}
→ 3品すべてに、指定食材のうち少なくとも1つ以上を含めること。
→ 1品目: 主菜で指定食材を使う
→ 2品目: 副菜で指定食材を使う（主菜と違う調理法）
→ 3品目: スープ・和え物など、別の調理法で指定食材を使う
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
{ingredients_check}
"""
    return system_instruction + "\n" + prompt

def call_ai(prompt: str) -> Optional[str]:
    """キャッシュなしで毎回実行 + Temperature 指定で多様性UP"""
    model = get_genai_model()
    if model is None:
        return None
    try:
        from google.generativeai.types import GenerationConfig
        config = GenerationConfig(
            temperature=1.0,         # 多様性重視
            top_p=0.95,             # 上位95%から選択（安定性も確保）
            top_k=40,               # 上位40トークンから選択
            max_output_tokens=2048, # 十分な長さ
        )
        response = model.generate_content(prompt, generation_config=config)
        return response.text if hasattr(response, "text") else None
    except Exception:
        return None

def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text: return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        return json.loads(response_text[start:end])
    except: return None

def run_retry(retry_label: str):
    if not st.session_state.last_inputs: return
    with st.spinner(f"「{retry_label}」で考え直しています（30秒ほどかかる場合があります）..."):
        response = call_ai(build_prompt(st.session_state.last_inputs, retry_label))
        if response:
            result = parse_ai_response(response)
            if result:
                st.session_state.latest_result = result
                st.session_state.user_feedback = None
                st.rerun()

# キーワード辞書（新設）
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

def render_candidate_card(candidate: Dict[str, Any], idx: int):
    with st.container(border=True):
        st.markdown(f"### {idx}. {candidate.get('menu_name', '')}")
        if candidate.get("dish_type"): st.caption(candidate.get("dish_type"))
        st.write(f"**おすすめ理由**：{candidate.get('reason', '')}")
        with st.expander("🍳 材料と作り方を見る"):
            st.markdown("**🛒 材料（分量の目安）**")
            for item in candidate.get("ingredients", []): st.write(f"- {item}")
            st.write("")
            st.markdown("**👩‍🍳 作り方の手順**")
            for i, step in enumerate(candidate.get("steps", []), 1): st.write(f"{i}. {step}")
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
            st.caption(f"💡 ジャンルに応じて最適なキッチングッズを検索")
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
        st.caption("※ポチコおすすめの商品ページ（外部サイト）へ移動します。移動前にレシピのスクショをおすすめします。")

def main():
    init_session_state()
    st.title("🍳 夜ごはんサポート")
    st.write("今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    ingredients = st.text_input("使いたい食材・家にあるもの *", placeholder="例：大根、ひき肉、豆腐")
    exclude_ingredients = st.text_input("入れないもの（苦手なもの）", placeholder="例：ピーマン、トマト")

    col1, col2 = st.columns(2)
    with col1: cook_time = st.radio("かけられる時間 *", ["5分", "10分", "15分", "20分"], index=1)
    with col2: dish_type = st.radio("何を作りたいですか *", ["主菜", "副菜", "どちらでも"], index=0)

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

    conditions = [l for l, c in zip(["この材料だけで作る", "ワンパンでできる", "洗い物少なめ", "幼児向き", "パーティー・おもてなし向き", "子どもと一緒に作れる"], [cond_less_ingredients, cond_one_pan, cond_less_wash, cond_kid, cond_party, cond_with_kids]) if c]
    taste_level = st.radio("味の濃さ *", ["薄味", "普通", "濃い目"], index=1, horizontal=True)
    spicy = st.toggle("辛い料理もOK", value=False)
    constraints = st.text_input("補足（任意）", placeholder="例：ちくわも消費したい")

    if st.button("この条件でポチコに聞く", type="primary", use_container_width=True):
        if not ingredients.strip():
            st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.latest_result = None
            st.session_state.user_feedback = None
            st.session_state.last_inputs = {
                "ingredients": ingredients, "exclude_ingredients": exclude_ingredients,
                "cook_time": cook_time, "dish_type": dish_type,
                "conditions": conditions, "taste_level": taste_level,
                "spicy": spicy, "constraints": constraints
            }
            with st.spinner("ポチコが今夜の候補を考えています（30秒ほどかかる場合があります）..."):
                if not GEMINI_API_KEY:
                    st.error("APIキーが設定されていません。Streamlit Cloud の Secrets を確認してください。")
                else:
                    resp = call_ai(build_prompt(st.session_state.last_inputs))
                    if resp:
                        result = parse_ai_response(resp)
                        if result:
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
            if st.button("もっと手抜きがいい"): run_retry("もっと手抜きがいい")
        with c2:
            if st.button("ちがう味付けがいい"): run_retry("ちがう味付けがいい")
        with c3:
            if st.button("調理法を変えたい"): run_retry("調理法を変えたい")
        with c4:
            if st.button("完全に別の案にする"): run_retry("完全に別の案にする")

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
        else: st.caption("評価ありがとうございます！")

    st.write("---")
    st.caption("無料公開のため、画面上部に Streamlit の Fork ボタン等が表示されることがあります。")
    st.caption("【免責事項】AI生成案です。保護者の方が最終確認を行ってください。")

if __name__ == "__main__":
    main()
