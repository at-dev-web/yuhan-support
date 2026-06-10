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

def init_session_state():
    if "latest_result" not in st.session_state:
        st.session_state.latest_result = None
    if "last_inputs" not in st.session_state:
        st.session_state.last_inputs = None
    if "user_feedback" not in st.session_state:
        st.session_state.user_feedback = None

def build_prompt(inputs: Dict[str, Any], retry_type: Optional[str] = None) -> str:
    system_instruction = """
あなたは「ポチコ」という名前の、忙しい夜ごはんをやさしくサポートする献立アドバイザーです。
ユーザーの入力条件に基づき、現実的で作りやすく、おいしい夕食候補を3品提案してください。

【重要：言葉遣いと配慮のルール】
- 「子ども」という表現は使わず、必ず「お子さん」と呼んでください。
- 命令調や不躾な表現は避け、やさしく寄り添う自然な言い回しにしてください。
- 提案理由やポイントは、忙しい保護者に寄り添う内容にしてください。

【アイテム提案のルール】
- 提案した料理に関連して「ポチコが自信を持っておすすめする便利アイテム」を1つ紹介してください。
- 食材や調味料は提案しないでください（今日届かないため）。
- ジャンル：時短グッズ、食器、装飾、お子さん用エプロン等。

必ず以下のJSON形式でのみ回答してください。
{
  "meal_title": "ポチコのおすすめ候補",
  "summary": "今回の3候補の全体説明（やさしい言葉遣いで）",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜または副菜",
      "reason": "提案理由",
      "ingredients": ["材料1"],
      "steps": ["手順1"],
      "tip": "ポチコの推しポイント"
    }
  ],
  "ad_suggestion": {
    "title": "アイテム名",
    "reason": "なぜこれが今夜の献立に役立つのか（具体的におすすめする理由）"
  }
}
"""
    retry_context = ""
    if retry_type == "もっと手抜きがいい":
        retry_context = "\n【再提案条件】工程を極限まで削った超時短案にしてください。"
    elif retry_type == "ちがう味付けがいい":
        retry_context = "\n【再提案条件】味の方向性をガラッと変えてください。"
    elif retry_type == "調理法を変えたい":
        retry_context = "\n【再提案条件】火の通し方を先ほどとは全く違う方法にしてください。"
    elif retry_type == "完全に別の案にする":
        retry_context = "\n【再提案条件】全く新しい3品をゼロから提案し直してください。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理は提案しないでください。"
    if inputs["spicy"]:
        spicy_rule = "辛い料理も提案可能です。"

    prompt = f"""
今夜の献立候補を3品提案してください。{retry_context}
- 使いたい食材: {inputs['ingredients']}
- 入れないもの: {inputs['exclude_ingredients'] or '特になし'}
- かけられる時間: {inputs['cook_time']}
- 作りたいもの: {inputs['dish_type']}
- 条件: {conditions_text}
- 味の濃さ: {inputs['taste_level']}
- 補足: {inputs['constraints'] or '特になし'}
- 辛さルール: {spicy_rule}
"""
    return system_instruction + "\n" + prompt

def call_ai(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        st.error("システム設定エラー：APIキーが読み込めません。")
        return None
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return response.text if hasattr(response, "text") else None
    except Exception:
        return None

def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text: return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        return json.loads(response_text[start:end])
    except Exception: return None

def run_retry(retry_label: str):
    if not st.session_state.last_inputs: return
    with st.spinner(f"「{retry_label}」で考え直しています..."):
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
            st.markdown("**🛒 材料**")
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
        st.subheader("🛠 ポチコが見つけたお役立ちアイテム")
        item_name = ad.get("title", "")
        query = quote_plus(item_name)
        with st.container(border=True):
            st.markdown(f"#### {item_name}")
            st.write(ad.get("reason", ""))
            st.caption("※ポチコおすすめの商品ページ（外部サイト）へ移動します。")
            c1, c2 = st.columns(2)
            with c1:
                st.link_button("Amazonでチェック", f"https://www.amazon.co.jp/s?k={query}", use_container_width=True)
            with c2:
                st.link_button("楽天でチェック", f"https://search.rakuten.co.jp/search/mall/{query}/", use_container_width=True)

def main():
    init_session_state()

    # タイトルのレスポンシブ調整
    st.markdown(
        """
        <h1 style='font-size: clamp(1.8rem, 5vw, 2.5rem); line-height: 1.2; margin-bottom: 0.5rem;'>
        🍳 夜ごはんサポート
        </h1>
        """, 
        unsafe_allow_html=True
    )
    st.write("ポチポチ選ぶだけ。今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    with st.form("main_form", clear_on_submit=False):
        ingredients = st.text_input("使いたい食材・家にあるもの *", placeholder="例：大根、ひき肉、豆腐")
        exclude_ingredients = st.text_input("入れないもの（苦手なもの）", placeholder="例：ピーマン、トマト")
        
        col1, col2 = st.columns(2)
        with col1: cook_time = st.radio("かけられる時間 *", ["5分", "10分", "15分", "20分"], index=1)
        with col2: dish_type = st.radio("何を作りたいですか *", ["主菜", "副菜", "どちらでも"], index=0)

        st.write("**条件（あてはまるものを選んでください）**")
        c1, c2, c3 = st.columns(3)
        with c1:
            cond1 = st.checkbox("ワンパンでできる")
            cond2 = st.checkbox("洗い物少なめ")
        with c2:
            cond3 = st.checkbox("使う材料少なめ")
            cond4 = st.checkbox("幼児向き")
        with c3:
            cond5 = st.checkbox("パーティー・おもてなし向き")
            cond6 = st.checkbox("子どもと一緒に作れる")

        conditions = [l for l, c in zip(["ワンパンでできる", "洗い物少なめ", "使う材料少なめ", "幼児向き", "パーティー・おもてなし向き", "子どもと一緒に作れる"], [cond1, cond2, cond3, cond4, cond5, cond6]) if c]
        taste_level = st.radio("味の濃さ *", ["薄味", "普通", "濃い目"], index=1, horizontal=True)
        spicy = st.toggle("辛い料理もOK", value=False)
        
        # 自由記述欄（Press Enter...を意識させないよう、ラベルで補足）
        constraints = st.text_input("補足（任意：最後は下のボタンで送信してください）", placeholder="例：ちくわも消費したい、マヨネーズが残り少ない")

        submit = st.form_submit_button("この条件でポチコに聞く")

    if submit:
        if not ingredients.strip(): st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.last_inputs = {"ingredients": ingredients, "exclude_ingredients": exclude_ingredients, "cook_time": cook_time, "dish_type": dish_type, "conditions": conditions, "taste_level": taste_level, "spicy": spicy, "constraints": constraints}
            with st.spinner("ポチコが今夜の候補を考えています..."):
                resp = call_ai(build_prompt(st.session_state.last_inputs))
                if resp: st.session_state.latest_result = parse_ai_response(resp)

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
    # 公開版への注釈
    st.caption("※無料公開環境の仕様により、画面上部に外部サービス（GitHub等）のアイコンが表示されますが、そのまま安心してご利用いただけます。")
    st.caption("【免責事項】")
    st.caption("・本アプリはAIによる自動生成案を表示しています。アレルギーや月齢に合わせた判断は、必ず保護者の方が最終確認を行ってください。")

if __name__ == "__main__":
    main()
