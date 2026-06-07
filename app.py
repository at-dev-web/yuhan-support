import streamlit as st
import google.generativeai as genai
import json
import os
from typing import Optional, Dict, Any

# ページ設定
st.set_page_config(page_title="夜ごはんサポート", page_icon="🍳")

# --- セキュリティ設定：環境変数からAPIキーを読み込む ---
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
- 「〜もおすすめです」「〜と一緒に楽しめます」「〜しやすいです」など、やわらかい表現を使ってください。
- ポチコらしい親しみやすさは残しつつ、文章は落ち着いて読みやすくしてください。
- 提案理由やポイントは、忙しい保護者に寄り添う内容にしてください。

【アイテム提案のルール】
- 提案した料理に関連して「あると便利なアイテム」を1つ紹介してください。
- 食材や調味料は提案しないでください。
- 時短グッズ、食器、パーティー装飾、お子さん用エプロン等から選んでください。

必ず以下のJSON形式でのみ回答してください。他の文章は一切含めないでください。
{
  "meal_title": "ポチコのおすすめ候補",
  "summary": "今回の3候補の全体説明（やさしい言葉遣いで）",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜または副菜",
      "reason": "提案理由（お子さんへの配慮も含めて）",
      "ingredients": ["材料1", "材料2"],
      "steps": ["手順1", "手順2"],
      "tip": "ポチコの推しポイント（お子さんとの調理や食べやすさのアドバイス）"
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
        retry_context = "\n【再提案条件】工程を極限まで削った、より手軽で作りやすい案にしてください。忙しい日でも負担になりにくいことを重視してください。"
    elif retry_type == "ちがう味付けがいい":
        retry_context = "\n【再提案条件】味の方向性をガラッと変えてください。和風なら洋風や中華風にするなど、はっきり違いが出るるようにしてください。"
    elif retry_type == "調理法を変えたい":
        retry_context = "\n【再提案条件】火の通し方や調理方法を先ほどとは違うものにしてください。炒める以外に、煮る、蒸す、焼く、レンジ加熱なども検討してください。"
    elif retry_type == "完全に別の案にする":
        retry_context = "\n【再提案条件】ジャンルも調理法も全体の方向性もリセットして、まったく新しい3品を提案してください。"

    conditions_text = "、".join(inputs["conditions"]) if inputs["conditions"] else "なし"
    spicy_rule = "辛い料理は提案しないでください。"
    if inputs["spicy"]:
        spicy_rule = "辛い料理も提案可能です。"

    prompt = f"""
今夜のおすすめ献立を3品考えてください。{retry_context}
- 使いたい食材: {inputs['ingredients']}
- 入れないもの: {inputs['exclude_ingredients'] if inputs['exclude_ingredients'] else "特になし"}
- かけられる時間: {inputs['cook_time']}
- 作りたいもの: {inputs['dish_type']}
- 条件: {conditions_text}
- 味の濃さ: {inputs['taste_level']}
- 補足: {inputs['constraints'] if inputs['constraints'] else "特になし"}
- 辛さルール: {spicy_rule}

追加ルール:
- 「お子さん」という言葉を使い、やさしく自然なトーンで回答してください。
- 「子どもと一緒に作れる」が含まれる場合は、お子さんが無理なく手伝わる具体的なポイントを添えてください。
- 「幼児向き」が含まれる場合は、食べやすさや味のやさしさに配慮してください。
- 「パーティー・おもてなし向き」が含まれる場合は、見た目の楽しさや出しやすさも意識してください。
- 候補は必ず3つ出し、JSON以外の文章は出さないでください。
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
        st.error("通信でエラーが発生しました。しばらくしてからもう一度お試しください。")
        return None


def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text:
        return None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        return json.loads(response_text[start:end])
    except Exception:
        return None


def run_retry(retry_label: str):
    if not st.session_state.last_inputs:
        st.warning("先に提案を出してください。")
        return
    with st.spinner("今とは別の候補を考えています..."):
        retry_prompt = build_prompt(st.session_state.last_inputs, retry_label)
        response = call_ai(retry_prompt)
        if response:
            result = parse_ai_response(response)
            if result:
                st.session_state.latest_result = result
                st.session_state.user_feedback = None
                st.rerun()


def render_candidate_card(candidate: Dict[str, Any], idx: int):
    menu_name = candidate.get("menu_name", f"候補{idx}")
    dish_type = candidate.get("dish_type", "")
    reason = candidate.get("reason", "")
    tip = candidate.get("tip", "")
    ingredients = candidate.get("ingredients", [])
    if not isinstance(ingredients, list):
        ingredients = [str(ingredients)]
    steps = candidate.get("steps", [])
    if not isinstance(steps, list):
        steps = [str(steps)]

    with st.container(border=True):
        st.markdown(f"### {idx}. {menu_name}")
        if dish_type:
            st.caption(dish_type)

        st.write(f"**おすすめ理由**：{reason}")

        with st.expander("🍳 材料と作り方を見る"):
            st.markdown("**🛒 材料**")
            for item in ingredients:
                st.write(f"- {item}")
            st.write("")
            st.markdown("**👩‍🍳 作り方の手順**")
            for i, step in enumerate(steps, 1):
                st.write(f"{i}. {step}")

        st.info(f"✨ ポチコの推しポイント：{tip}")


def render_result(result: Dict[str, Any]):
    st.success(f"### {result.get('meal_title', 'ポチコのおすすめ候補')}")
    st.write(result.get("summary", ""))

    candidates = result.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []

    for idx, candidate in enumerate(candidates[:3], start=1):
        render_candidate_card(candidate, idx)

    ad = result.get("ad_suggestion")
    if isinstance(ad, dict) and ad.get("title"):
        st.write("---")
        st.subheader("🛠 ポチコが見つけたお役立ちアイテム (PR)")
        with st.container(border=True):
            st.markdown(f"#### {ad.get('title', '')}")
            st.write(ad.get("reason", ""))
            st.caption("※紹介したアイテムは外部サイト（Amazon/楽天など）で購入できる想定です。")


def main():
    init_session_state()

    st.title("🍳 夜ごはんサポート")
    st.write("ポチポチ選ぶだけ。今夜のおかずにちょうどいい「3つの候補」をAI【ポチコ】が提案します。")

    with st.form("main_form"):
        ingredients = st.text_input(
            "使いたい食材・家にあるもの *",
            placeholder="例：大根、ひき肉、豆腐"
        )
        exclude_ingredients = st.text_input(
            "入れないもの（苦手なもの）",
            placeholder="例：ピーマン、トマト"
        )

        col1, col2 = st.columns(2)
        with col1:
            cook_time = st.radio(
                "かけられる時間 *",
                ["5分", "10分", "15分", "20分"],
                index=1
            )
        with col2:
            dish_type = st.radio(
                "何を作りたいですか *",
                ["主菜", "副菜", "どちらでも"],
                index=0
            )

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

        conditions = [
            label for label, checked in zip(
                [
                    "ワンパンでできる",
                    "洗い物écia少なめ",
                    "使う材料或少め",
                    "幼児向き",
                    "パーティー・おもてなし向き",
                    "子どもと一緒に作れる"
                ],
                [
                    cond_one_pan,
                    cond_less_wash,
                    cond_less_ingredients,
                    cond_kid,
                    cond_party,
                    cond_with_kids
                ]
            ) if checked
        ]

        taste_level = st.radio(
            "味の濃さ *",
            ["薄味", "普通", "濃い目"],
            index=1,
            horizontal=True
        )

        spicy = st.toggle("辛い料理もOK", value=False)

        constraints = st.text_input(
            "補足（任意）",
            placeholder="例：ちくわも消費したい、マヨネーズが残り少ない"
        )

        submit = st.form_submit_button("この条件でポチコに聞く")

    if submit:
        if not ingredients.strip():
            st.warning("使いたい食材を入力してください。")
        else:
            st.session_state.latest_result = None
            st.session_state.user_feedback = None
            st.session_state.last_inputs = {
                "ingredients": ingredients,
                "exclude_ingredients": exclude_ingredients,
                "cook_time": cook_time,
                "dish_type": dish_type,
                "conditions": conditions,
                "taste_level": taste_level,
                "spicy": spicy,
                "constraints": constraints
            }

            with st.spinner("ポチコがおすすめ候補を考え中..."):
                prompt = build_prompt(st.session_state.last_inputs)
                response = call_ai(prompt)
                if response:
                    result = parse_ai_response(response)
                    if result:
                        st.session_state.latest_result = result
                    else:
                        st.error("提案の読み取りに失敗しました。")

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
            st.caption("評価ありがとうございます")

    st.write("---")
    st.caption("【免責事項】")
    st.caption("・本アプリはAIによる自動生成案を表示しています。アレルギーや月齢に合わせた判断は、必ず保護者の方が最終確認を行ってください。")


if __name__ == "__main__":
    main()
