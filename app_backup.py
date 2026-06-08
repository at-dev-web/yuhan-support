import streamlit as st
import google.generativeai as genai
import json
import os
from typing import Optional, Dict, Any

# ページ設定
st.set_page_config(page_title="夜ごはんサポート", page_icon="🍳")

# --- セキュリティ設定：Streamlit CloudのSecrets（環境変数）から読み込む ---
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
- 提案した料理に関連して「あると便利なアイテム」を1つ紹介してください。
- 食材や調味料は提案しないでください。

必ず以下のJSON形式でのみ回答してください。
{
  "meal_title": "今夜のおすすめ候補",
  "summary": "今回の3候補の全体説明",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜または副菜",
      "reason": "提案理由",
      "ingredients": ["材料1", "材料2"],
      "steps": ["手順1", "手順2"],
      "tip": "お子さん想いのポイント"
    }
  ],
  "ad_suggestion": {
    "title": "アイテム名",
    "reason": "おすすめの理由"
  }
}
"""

    retry_context = ""
    if retry_type == "もっと手抜きがいい":
        retry_context = "\n【再提案条件】工程を極限まで削った、より手軽で作りやすい案にしてください。"
    elif retry_type == "ちがう味付けがいい":
        retry_context = "\n【再提案条件】味の方向性をガラッと変えてください。"
    elif retry_type == "調理法を変えたい":
        retry_context = "\n【再提案条件】火の通し方を先ほどとは違うものにしてください。"
    elif retry_type == "完全に別の案にする":
        retry_context = "\n【再提案条件】まったく新しい3品を提案してください。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理は提案しないでください。"
    if inputs["spicy"]:
        spicy_rule = "辛い料理も提案可能です。"

    prompt = f"""
今夜の献立候補を3品提案してください。{retry_context}
- 使いたい食材: {inputs['ingredients']}
- 入れないもの: {inputs['exclude_ingredients'] if inputs['exclude_ingredients'] else "特になし"}
- かけられる時間: {inputs['cook_time']}
- 作りたいもの: {inputs['dish_type']}
- 条件: {conditions_text}
- 味の濃さ: {inputs['taste_level']}
- 補足: {inputs['constraints'] if inputs['constraints'] else "特になし"}
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
        if response and hasattr(response, "text") and response.text:
            return response.text
        return None
    except Exception:
        st.error("通信エラーが発生しました。しばらくしてからもう一度お試しください。")
        return None

def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text: return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        return json.loads(response_text[start:end])
    except: return None

def run_retry(retry_label: str):
    if not st.session_state.last_inputs:
        st.warning("先に提案を出してください。")
        return
    with st.spinner("別の候補を考えています..."):
        retry_prompt = build_prompt(st.session_state.last_inputs, retry_label)
        response = call_ai(retry_prompt)
        if response:
            result = parse_ai_response(response)
            if result:
                st.session_state.latest_result = result
                st.session_state.user_feedback = None
                st.rerun()

def render_candidate_card(candidate: Dict[str, Any], idx: int):
    with st.container(border=True):
        st.markdown(f"### {idx}. {candidate.get('menu_name', '')}")
        st.write(f"**おすすめ理由**：{candidate.get('reason', '')}")
        with st.expander("🍳 材料と作り方を見る"):
            st.markdown("**🛒 材料**")
            for item in candidate.get("ingredients", []): st.write(f"- {item}")
            st.markdown("**👩‍🍳 作り方の手順**")
            for i, step in enumerate(candidate.get("steps", []), 1): st.write(f"{i}. {step}")
        st.info(f"✨ お子さん想いのポイント：{candidate.get('tip', '')}")

def render_result(result: Dict[str, Any]):
    st.success(f"### {result.get('meal_title', '今夜のおすすめ候補')}")
    st.write(result.get("summary", ""))
    for idx, candidate in enumerate(result.get("candidates", [])[:3], start=1):
        render_candidate_card(candidate, idx)
    ad = result.get("ad_suggestion")
    if isinstance(ad, dict) and ad.get("title"):
        st.write("---")
        st.subheader("🛠 この献立に役立つアイテム (PR)")
        with st.container(border=True):
            st.markdown(f"#### {ad.get('title', '')}")
            st.write(ad.get("reason", ""))

def main():
    init_session_state()
    st.title("🍳 夜ごはんサポート")
    st.write("ポチポチ選ぶだけ。今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    with st.form("main_form"):
        ingredients = st.text_input("使いたい食材・家にあるもの *", placeholder="例：大根、ひき肉、豆腐")
        exclude_ingredients = st.text_input("入れないもの（苦手なもの）", placeholder="例：ピーマン、トマト")
        col1, col2 = st.columns(2)
        with col1: cook_time = st.radio("かけられる時間 *", ["5分", "10分", "15分", "20分"], index=1)
        with col2: dish_type = st.radio("何を作りたいですか *", ["主菜", "副菜", "どちらでも"], index=0)
        
        st.write("**条件（あてはまるものを選んでください）**")
        c1, c2, c3 = st.columns(3)
        with c1:
            cond_one_pan = st.checkbox("ワンパンでできる")
            cond_less_wash = st.checkbox("洗い物少なめ")
        with c2:
            cond_less_ingredients = st.checkbox("使う材料少なめ")
            cond_kid = st.checkbox("幼児向き")
        with c3:
            cond_party = st.checkbox("パーティー・おもてなし向き")
            cond_with_kids = st.checkbox("子どもと一緒に作れる")

        conditions = [l for l, c in zip(["ワンパンでできる", "洗い物少なめ", "使う材料少なめ", "幼児向き", "パーティー・おもてなし向き", "子どもと一緒に作れる"], [cond_one_pan, cond_less_wash, cond_less_ingredients, cond_kid, cond_party, cond_with_kids]) if c]
        taste_level = st.radio("味の濃さ *", ["薄味", "普通", "濃い目"], index=1, horizontal=True)
        spicy = st.toggle("辛い料理もOK", value=False)
        constraints = st.text_input("補足（任意）", placeholder="例：ちくわも消費したい")
        submit = st.form_submit_button("この条件でAIに聞く")

    if submit:
        if not ingredients.strip(): st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.last_inputs = {"ingredients": ingredients, "exclude_ingredients": exclude_ingredients, "cook_time": cook_time, "dish_type": dish_type, "conditions": conditions, "taste_level": taste_level, "spicy": spicy, "constraints": constraints}
            with st.spinner("今夜の候補を考えています..."):
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

    st.write("---")
    st.caption("【免責事項】AI生成案です。保護者の方が最終確認を行ってください。")

if __name__ == "__main__":
    main()
