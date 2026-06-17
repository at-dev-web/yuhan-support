import streamlit as st
import google.generativeai as genai
import json
import os
from urllib.parse import quote_plus
from typing import Optional, Dict, Any

# ページ設定
st.set_page_config(page_title="夜ごはんサポート", page_icon="🍳")

# --- セキュリティ設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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
- 分量は、一般的な単位（g、個、本、大さじ等）で具体的に提案してください。
"""
    retry_context = ""
    if retry_type:
        retry_context = f"\n【再提案条件】{retry_type}を重視して、内容をガラッと変えてください。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理も提案可能です。" if inputs["spicy"] else "辛い料理は提案しないでください。"

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
"""
    return system_instruction + "\n" + prompt

def call_ai(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY: return None
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return response.text if hasattr(response, "text") else None
    except: return None

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
        st.write("---")
        st.subheader("🛠 ポチコのお役立ちアイテム")
        item_name = ad.get("title", "")
        query = quote_plus(item_name)
        with st.container(border=True):
            st.markdown(f"#### {item_name}")
            st.write(ad.get("reason", ""))
            st.caption("※ポチコおすすめの商品ページ（外部サイト）へ移動します。移動前にレシピのスクショをおすすめします。")
            c1, c2 = st.columns(2)
            with c1: st.link_button("Amazonでチェック", f"https://www.amazon.co.jp/s?k={query}", use_container_width=True)
            with c2:
    rakuten_id = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
    if rakuten_id:
        query = quote_plus(item_name)
        rakuten_url = f"https://hb.afl.rakuten.co.jp/hgc/{rakuten_id}/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{query}%2F&link_type=hybrid_url"
        st.link_button("楽天でチェック", rakuten_url, use_container_width=True)
    else:
        st.caption("※楽天リンクは現在準備中です")

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
                resp = call_ai(build_prompt(st.session_state.last_inputs))
                if resp: st.session_state.latest_result = parse_ai_response(resp)
                else: st.error("通信エラーが発生しました。")

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
    st.caption("※無料公開環境の仕様により、画面上部に外部サービスのアイコンが表示されますが、そのまま安心してご利用いただけます。")
    st.caption("【免責事項】AI生成案です。保護者の方が最終確認を行ってください。")

if __name__ == "__main__":
    main()
