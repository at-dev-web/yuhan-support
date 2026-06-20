import streamlit as st
import google.generativeai as genai
import json
import os
import re
from urllib.parse import quote_plus
from typing import Optional, Dict, Any, List

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
    small { display: none !important; }
    div[data-testid="stMarkdownContainer"] p { font-size: 1rem; }
    h1 { font-size: clamp(1.5rem, 5vw, 2.2rem) !important; line-height: 1.2 !important; }
    h3 { font-size: clamp(1.2rem, 4vw, 1.8rem) !important; line-height: 1.2 !important; }
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

# 提案ルール（★厳守）
1. **必ず3つのすべての献立に、指定された食材を「全員」主材料または副材料として含めてください。**
   - メニュー1・メニュー2・メニュー3の**すべて**にユーザーが指定した食材を入れること。
   - 1品でも指定食材が入っていない献立は絶対に禁止です。
2. **3つの献立の「調理アプローチ」を完全にバラバラにしてください。**
   - 炒め物、レンジ蒸し、和え物、スープ・煮物、焼き物など、異なる調理法に分散させること。
   - 味付けも醤油・マヨ・ごま油・コンソメ・味噌など分散させること。
   - ❌ 「ツナ＋電子レンジ」が3品に固まるような、似たり寄ったりの提案は禁止。
3. **たんぱく質素材を分散させること**（鶏・豚・牛・卵・魚・豆腐をそれぞれ違う献立で主役にする）
4. 日本語で出力し、子ども連れママ向けにわかりやすく。
5. 各献立には分量付き材料リスト、簡単な手順を必須とします。

# 出力（厳密なJSON・必須・唯一の出力形式）
{
  "meal_title": "ポチコのおすすめ候補",
  "summary": "今回の3候補の全体説明",
  "candidates": [
    {
      "menu_name": "料理名",
      "dish_type": "主菜",
      "reason": "提案理由",
      "ingredients": [
        {"name": "材料名", "amount": "分量（例：200g, 1/2個, 大さじ2）"}
      ],
      "steps": ["手順1", "手順2", "手順3"]
    }
  ],
  "ad_suggestion": {"title": "アイテム名", "reason": "おすすめ理由"}
}

【超重要】上記JSON以外の出力は絶対にしないでください。
前置きや説明文は不要。最初の1文字は「{」、最後の1文字は「}」にしてください。
Markdownの ```json 〜 ``` フェンスは不要です。
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

    prompt = f"""
今夜の献立を3品提案して。{retry_context}

# 必ず使う食材
{inputs['ingredients']}
→ 3品すべてに、上記食材を必ず含めてください。
→ 1品でも入っていない献立は禁止です。

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

def call_ai(prompt: str, retry_count: int = 0) -> Optional[str]:
    """キャッシュなし + Temperature 0.7 + 自動リトライ"""
    model = get_genai_model()
    if model is None:
        return None
    try:
        from google.generativeai.types import GenerationConfig
        config = GenerationConfig(
            temperature=0.7,
            top_p=0.9,
            top_k=40,
            max_output_tokens=2048,
        )
        response = model.generate_content(prompt, generation_config=config)
        if response and hasattr(response, "text") and response.text:
            return response.text
        return None
    except Exception:
        if retry_count < 1:
            return call_ai(prompt, retry_count + 1)
        return None

def _normalize_candidate(m: Dict[str, Any]) -> Dict[str, Any]:
    """1つの献立データを UI 表示形式に正規化"""
    raw_ings = m.get("ingredients", [])
    norm_ings = []
    for x in raw_ings:
        if isinstance(x, dict):
            name = x.get("name", "")
            amount = x.get("amount", "")
            if amount:
                norm_ings.append(f"{name} {amount}")
            else:
                norm_ings.append(name)
        elif isinstance(x, str):
            norm_ings.append(x)
    return {
        "menu_name": m.get("menu_name") or m.get("name") or "",
        "dish_type": m.get("dish_type") or "",
        "reason": m.get("reason") or m.get("appeal") or "",
        "ingredients": norm_ings,
        "steps": m.get("steps", []),
        "tip": m.get("tip") or "",
    }

def _normalize_result(result: Any) -> Optional[Dict[str, Any]]:
    """API の返り値を UI 形式に統一"""
    if not isinstance(result, dict):
        return None
    raw_list = result.get("candidates") or result.get("menus") or result.get("menu")
    if not isinstance(raw_list, list) or len(raw_list) == 0:
        return None
    norm = [_normalize_candidate(m) for m in raw_list if isinstance(m, dict)]
    return {
        "meal_title": result.get("meal_title", "ポチコのおすすめ候補"),
        "summary": result.get("summary", ""),
        "candidates": norm,
        "ad_suggestion": result.get("ad_suggestion", {})
        if isinstance(result.get("ad_suggestion"), dict)
        else {},
    }

def parse_ai_response(response_text: str) -> Optional[Dict[str, Any]]:
    """複数のパターンに対応する堅牢な JSON 抽出"""
    if not response_text:
        return None

    text = response_text.strip()

    # パターン1: ```json ブロック
    json_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block_match:
        try:
            normalized = _normalize_result(json.loads(json_block_match.group(1)))
            if normalized:
                return normalized
        except json.JSONDecodeError:
            pass

    # パターン2: 文字列内の { から最後の }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            normalized = _normalize_result(json.loads(text[start:end+1]))
            if normalized:
                return normalized
        except json.JSONDecodeError:
            pass

    # パターン3: greeting + menus形式のゆるい抽出
    try:
        menus_match = re.search(r'"menus"\s*:\s*(\[.*?\])\s*[,\}]', text, re.DOTALL)
        if menus_match:
            menus = json.loads(menus_match.group(1))
            if isinstance(menus, list) and menus:
                return _normalize_result({"menus": menus})
    except (json.JSONDecodeError, AttributeError):
        pass

    return None

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
