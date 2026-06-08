import streamlit as st
import google.generativeai as genai
import json
import os
from typing import Optional, Dict, Any

st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")

def init_session_state():
    if "latest_result" not in st.session_state:
        st.session_state.latest_result = None
    if "last_inputs" not in st.session_state:
        st.session_state.last_inputs = None
    if "retry_type" not in st.session_state:
        st.session_state.retry_type = None
    if "user_feedback" not in st.session_state:
        st.session_state.user_feedback = None

with st.sidebar:
        st.markdown("### 🔑 API設定")
        
api_key = st.text_input("Gemini APIキー", type="password")
if api_key:
                        genai.configure(api_key=api_key)



def build_prompt(inputs: Dict[str, Any], retry_type: Optional[str] = None) -> str:
    system_instruction = """
    あなたは忙しい平日夜の保護者を助ける献立アドバイザーです。
    ユーザーの入力条件に基づき、現実的で美味しい夕食の提案を1つだけ行ってください。
    必ず以下のJSON形式でのみ回答してください。他の文章は一切含めないでください。
    {
      "menu_name": "料理名",
      "reason": "提案理由（1〜2文）",
      "ingredients": ["材料1", "材料2"],
      "steps": ["手順1", "手順2"],
      "tip": "失敗しにくくするポイント",
      "ad_suggestion": {
        "title": "おすすめ調理器具や食材",
        "reason": "なぜおすすめか",
        "url": ""
      }
    }
    """
    retry_context = ""
    if retry_type == "もっと楽なの":
        retry_context = "\n【再提案条件】工程をさらに減らし、洗い物が極限まで少ない超時短案にしてください。"
    elif retry_type == "家にそれ無い":
        retry_context = "\n【再提案条件】材料を代替しやすいものにするか、品数を減らしてください。"
    elif retry_type == "子ども無理そう":
        retry_context = "\n【再提案条件】味付けをよりマイルドにし、子どもが喜ぶ要素を強めてください。"
    elif retry_type == "気分じゃない":
        retry_context = "\n【再提案条件】先ほどの提案とは味の方向性（和洋中など）をガラッと変えてください。"
    
    prompt = f"""
    今夜の献立を1案提案してください。{retry_context}
    - 使いたい食材: {inputs['ingredients']}
    - 調理時間: {inputs['cook_time']}
    - 気分: {inputs['mood']}
    - 子どもの配慮: {inputs['kid_friendly']}
    - 補足: {inputs['constraints'] if inputs['constraints'] else "特になし"}
    """
    return system_instruction + "\n" + prompt
def call_ai(prompt: str) -> Optional[str]:
    if not api_key:
        st.error("上部の APIキー入力欄に Gemini APIキー を入力してください。")
        return None

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        if response and hasattr(response, "text") and response.text:
            return response.text

        st.error("提案を取得できませんでした。")
        return None

    except Exception as e:
        st.error("Gemini 呼び出しでエラーが出ました。")
        st.exception(e)
        return None

def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text:
        return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        json_text = response_text[start:end]
        return json.loads(json_text)
    except Exception:
        return None
def run_retry(retry_label: str):
    if not st.session_state.last_inputs:
        st.warning("先に最初の献立提案を出してください。")
        return

    with st.spinner(f"了解です。「{retry_label}」で出し直します..."):
        retry_prompt = build_prompt(st.session_state.last_inputs, retry_label)
        response = call_ai(retry_prompt)

        if response:
            result = parse_ai_response(response)
            if result:
                st.session_state.latest_result = result
                st.session_state.user_feedback = None
                st.rerun()
            else:
                st.error("提案の読み取りに失敗しました。")       
def save_feedback(feedback: str, menu_name: str):
    print(f"Feedback: {feedback} for {menu_name}")

def render_result(result: Dict[str, Any]):
    menu_name = result.get("menu_name", "提案メニュー")
    reason = result.get("reason", "条件に合う献立として提案しました。")
    tip = result.get("tip", "無理なく作れるものから試してみてください。")
    ingredients = result.get("ingredients", [])
    if not isinstance(ingredients, list):
        ingredients = [str(ingredients)]
    steps = result.get("steps", [])
    if not isinstance(steps, list):
        steps = [str(steps)]
    
    st.success(f"### 今夜はこれ！： {menu_name}")
    st.write(f"**💡 理由:** {reason}")
    c1, c2 = st.columns(2)
    with c1:
        st.write("**🛒 材料**")
        for item in ingredients:
            st.write(f"- {item}")
    with c2:
        st.write("**🍳 作り方**")
        for i, step in enumerate(steps, 1):
            st.write(f"{i}. {step}")
    st.info(f"**✨ ポイント:** {tip}")
    
    ad = result.get("ad_suggestion")
    if isinstance(ad, dict) and ad.get("title"):
        with st.expander("🛠 あると便利なもの (PR含む)"):
            st.write(f"**{ad.get('title', '')}**")
            st.write(ad.get("reason", ""))
def main():
    init_session_state()

    st.title("🍳 平日夜ごはんサポート")
    st.write("考えるのがしんどい時、ポチポチ選ぶだけで「今夜これにしよう」をお届けします。")

    with st.form("main_form"):
        ingredients = st.text_input("使いたい食材・残っているもの *", placeholder="例：大根、ひき肉、豆腐")
        col1, col2 = st.columns(2)

        with col1:
            cook_time = st.radio("作りたい時間 *", ["5分", "10分", "15分", "20分"], index=1)

        with col2:
            mood = st.radio("今の気分 *", ["がっつり", "ヘルシーな", "あっさり", "あたたかい"])

        kid_friendly = st.select_slider(
            "こどもの食べやすさ *",
            options=["食べやすさ優先", "普通", "大人寄りでもOK"],
            value="普通"
        )

        constraints = st.text_input("避けたいこと・補足（任意）", placeholder="例：洗い物少なめ")
        submit = st.form_submit_button("AIに聞く")

    if submit:
        if not ingredients.strip():
            st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.latest_result = None
            st.session_state.user_feedback = None
            st.session_state.last_inputs = {
                "ingredients": ingredients,
                "cook_time": cook_time,
                "mood": mood,
                "kid_friendly": kid_friendly,
                "constraints": constraints,
            }

            with st.spinner("今夜のベストな1案を考えています..."):
                prompt = build_prompt(st.session_state.last_inputs)
                response = call_ai(prompt)

                if response:
                    result = parse_ai_response(response)
                    if result:
                        st.session_state.latest_result = result
                    else:
                        st.error("提案の読み取りに失敗しました。もう一度お試しください。")

    if st.session_state.latest_result:
        render_result(st.session_state.latest_result)

        st.write("---")
        st.write("イメージと違いましたか？")

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            if st.button("もっと楽なの", key="retry_easy"):
                run_retry("もっと楽なの")

        with c2:
            if st.button("家にそれはない", key="retry_missing"):
                run_retry("家にそれはない")

        with c3:
            if st.button("無理そう", key="retry_kid"):
                run_retry("無理そう")

        with c4:
            if st.button("気分じゃない", key="retry_mood"):
                run_retry("気分じゃない")

        st.write("---")
        menu_name = st.session_state.latest_result.get("menu_name", "")

        if st.session_state.user_feedback is None:
            f1, f2, f3 = st.columns(3)

            with f1:
                if st.button("👍 役立った", key="feedback_good"):
                    st.session_state.user_feedback = "Good"
                    save_feedback("Good", menu_name)
                    st.toast("ありがとうございます！")

            with f2:
                if st.button("🤔 微妙", key="feedback_normal"):
                    st.session_state.user_feedback = "Normal"
                    save_feedback("Normal", menu_name)
                    st.toast("改善します")

            with f3:
                if st.button("👋 使わない", key="feedback_bad"):
                    st.session_state.user_feedback = "Bad"
                    save_feedback("Bad", menu_name)
                    st.toast("次は頑張ります")
        else:
            feedback_label_map = {
                "Good": "👍 役立った",
                "Normal": "🤔 微妙",
                "Bad": "👋 使わない",
            }
            st.caption(f"評価ありがとうございます：{feedback_label_map.get(st.session_state.user_feedback, '')}")

if __name__ == "__main__":
    main()
