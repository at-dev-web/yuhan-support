import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
import json
import os
import re
from urllib.parse import quote_plus
from typing import Optional, Dict, Any, List

# ============================================
# 🛍️ 楽天SPUバナー設定（最上部に表示）
# ============================================
RAKUTEN_SPU_LINK_URL = "https://hb.afl.rakuten.co.jp/hsc/5553751d.8ddfad89.54e87a23.360f3ed3/?link_type=pict&ut=eyJwYWdlIjoic2hvcCIsInR5cGUiOiJwaWN0IiwiY29sIjoxLCJjYXQiOiI0NCIsImJhbiI6Mjc5NDg1OCwiYW1wIjpmYWxzZX0%3D"
RAKUTEN_SPU_IMAGE_URL = "https://hbb.afl.rakuten.co.jp/hsb/5553751d.8ddfad89.54e87a23.360f3ed3/?me_id=1&me_adv_id=2794858&t=pict"

# ============================================
# 🛍️ 楽天ママ割バナー設定（最下部に表示）
# ============================================
RAKUTEN_MAMA_LINK_URL = "https://event.rakuten.co.jp/family/?scid=afb_010240"
RAKUTEN_MAMA_IMAGE_URL = "https://grp01.rakuten.co.jp/grp/img/event/family/bnr_family_468_60.gif"

# ページ設定
st.set_page_config(page_title="平日夜ごはんサポート", page_icon="🍳")


# ============================================
# ヘルパー関数群
# ============================================
def parse_ingredients(text: str) -> List[str]:
    """食材文字列をリストに分割（スペース／カンマ／読点など全て対応）"""
    if not text:
        return []
    separators = ["、", "，", ",", " ", "　", "\n", "\t"]
    result = text
    for sep in separators:
        result = result.replace(sep, ",")
    parts = [p.strip() for p in result.split(",") if p.strip()]
    return parts


def call_ai(prompt: str) -> Optional[str]:
    """Gemini APIを呼び出してレシピを取得"""
    if not genai:
        st.error("Gemini が利用できません")
        return None
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.3,
            },
        )
        if response and hasattr(response, "text") and response.text:
            return response.text
        st.error("提案を取得できませんでした")
        return None
    except Exception as e:
        st.error(f"Gemini呼び出しでエラー: {e}")
        return None


def build_prompt(
    ingredients: List[str],
    genre: str,
    servings: int,
    allergies: List[str],
    disliked: List[str],
    favorite: List[str],
    wants_filling: bool,
    wants_few_dishes: bool,
    low_budget: bool,
    quick: bool,
    notes: str,
) -> str:
    """プロンプトを構築"""
    base = f"""あなたは「ポチコ」という名前の家庭料理コンシェルジュです。
以下の条件でレシピを提案してください。

【食材】{', '.join(ingredients)}
【ジャンル】{genre}
【分量】{servings}人前
"""

    if allergies:
        base += f"\n【アレルギー】{'、'.join(allergies)}は使用不可"
    if disliked:
        base += f"\n【苦手食材】{'、'.join(disliked)}は使わない"
    if favorite:
        base += f"\n【好きな食材】{'、'.join(favorite)}を活用"
    if wants_filling:
        base += "\n【条件】子どもが満足する満腹感重視"
    if wants_few_dishes:
        base += "\n【条件】洗い物を少なくしたい"
    if low_budget:
        base += "\n【条件】節約志向"
    if quick:
        base += "\n【条件】手早く作りたい"
    if notes:
        base += f"\n【メモ】{notes}"

    base += """

【重要】以下のJSON形式のみで回答してください。Markdownや前置きは不要です。

{
  "candidate_1": {
    "title": "レシピ名",
    "summary": "一言紹介（20文字程度、絵文字なし、食材名に敬称をつけない）",
    "ingredients": ["食材1 分量", "食材2 分量"],
    "steps": ["手順1", "手順2"]
  },
  "candidate_2": {...},
  "candidate_3": {...}
}

【禁止事項】
- 「〇〇さん」「◯◯」「ほうれん草さん」のような表現は使用しないこと
- JSONの前後に説明文を絶対に付けないこと
"""
    return base


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """テキストからJSONを抽出"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def render_recipe_card(recipe_data: Dict[str, Any], idx: int) -> None:
    """レシピカードを1件分描画"""
    if not recipe_data:
        return
    title = recipe_data.get("title", f"献立{idx}")
    summary = recipe_data.get("summary", "")
    ingredients = recipe_data.get("ingredients", [])
    steps = recipe_data.get("steps", [])

    st.markdown(f"### 🍽️ 献立{idx}：{title}")
    if summary:
        st.write(summary)

    # 楽天市場検索リンク
    query_str = quote_plus(title)
    rakuten_url = f"https://search.rakuten.co.jp/search/mall/{query_str}/"
    st.link_button(
        f"🛒 「{title}」を楽天市場で探す",
        rakuten_url,
        use_container_width=False,
    )

    if ingredients:
        st.markdown("**🥗 材料**")
        for ing in ingredients:
            st.write(f"・{ing}")

    if steps:
        st.markdown("**📝 手順**")
        for i, step in enumerate(steps, 1):
            st.write(f"{i}. {step}")
    st.write("---")


def render_top_sp_banner() -> None:
    """楽天SPUバナーを画面上部に固定表示"""
    components.html(
        f"""
        <div id="rakuten-top-sp" style="
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 9999;
            background-color: #ffffff;
            padding: 6px 10px;
            border-bottom: 1px solid #e6e6e6;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            text-align: center;
        ">
            <a href="{RAKUTEN_SPU_LINK_URL}"
               target="_blank"
               rel="nofollow sponsored noopener"
               style="text-decoration:none; display:inline-block;">
               <img src="{RAKUTEN_SPU_IMAGE_URL}"
                    alt="楽天SPU"
                    style="max-width:468px; width:100%; height:auto; border-radius:4px;">
            </a>
        </div>
        <div style="height:74px;"></div>
        """,
        height=0,
    )


def render_spu_banner() -> None:
    """ページメインエリア上部に表示するSPUバナー（タイトル上）"""
    st.markdown(
        f"""
        <div style="text-align:center; margin: 16px 0 8px 0;">
            <a href="{RAKUTEN_SPU_LINK_URL}"
               target="_blank"
               rel="nofollow sponsored noopener"
               style="text-decoration:none;">
               <img src="{RAKUTEN_SPU_IMAGE_URL}"
                    alt="楽天SPU"
                    style="max-width:468px; width:100%; height:auto; border-radius:6px;">
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mama_banner() -> None:
    """楽天ママ割バナー（ページ下部）"""
    st.write("---")
    st.markdown("### 🌸 楽天ママ割")
    st.write("ママ・パパのお買い物をもっとお得に。楽天ママ割で賢く節約しましょう🌟")
    st.markdown(
        f"""
        <div style="text-align:center; margin: 8px 0 24px 0;">
            <a href="{RAKUTEN_MAMA_LINK_URL}"
               target="_blank"
               rel="nofollow sponsored noopener"
               style="text-decoration:none;">
               <img src="{RAKUTEN_MAMA_IMAGE_URL}"
                    alt="楽天ママ割"
                    style="max-width:468px; width:100%; height:auto; border-radius:4px;">
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_disclaimer() -> None:
    """注意書き（シンプル版）"""
    st.write("---")
    st.caption("🦝 ポチコからのおことわり｜提案はAIによるものです。 材料や手順にミスがあるかもしれません。")


# ============================================
# メイン画面
# ============================================
def main() -> None:
    # 📌 画面上部に固定バナー表示
    render_top_sp_banner()

    # 📢 ページメインエリア：一番上にSPUバナー表示（タイトル前）
    render_spu_banner()

    # 🦝 ヘッダー
    st.title("🍳 夜ごはんサポート")
    st.write("～ひと息つける献立を提案します～")
    st.write("🔎 今夜のおかずごちそうしたい「うちの味」をAIが【ポチコ】が提案します。")
    st.write("💡 一人暮らし・単身赴任・じゃがいも（スペースでもOK）")

    # ⚙️ 入力フォーム
    st.write("---")
    st.subheader("📝 今日の献立を考えよう")

    ingredients_text = st.text_input(
        "使いたい食材・家にあるもの *",
        placeholder="例：大根、ひき肉、豆腐  （スペースでも 、 でもOK）",
    )
    ingredients = parse_ingredients(ingredients_text)

    servings = st.radio(
        "何人前か（分量）",
        ["1人", "2人", "3人", "4人以上"],
        index=1,
    )
    servings_num = {"1人": 1, "2人": 2, "3人": 3, "4人以上": 4}[servings]

    genre = st.radio(
        "何を作りたいですか *",
        ["主菜", "副菜", "3品(主菜・副菜・スープのセット)"],
    )

    st.markdown("**条件（あてはまるものを💡選んでください）**")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        fill_c = st.checkbox("子どもが満足する")
        dishy = st.checkbox("ワンプレートでできる")
    with col_b:
        quick = st.checkbox("手早くできる")
        low_bdg = st.checkbox("ふだんの節約✨")
    with col_c:
        baby_friendly = st.checkbox("ベビー♠ おもてなし仕様")
        clean = st.checkbox("子どもと一緒につくれる")

    favorite = st.text_input("好きな食材", placeholder="例：じゃがいも、にんじん")
    allergy = st.text_input("アレルギー（食べられないもの）", placeholder="例：卵、乳、小麦")
    disliked = st.text_input("苦手な食材", placeholder="例：ピーマン")

    notes = st.text_area("補足（任意）", placeholder="例：冷蔵庫の残りものでOK")

    if st.button("🍽 献立を聞く", type="primary", use_container_width=True):
        if not ingredients:
            st.warning("食材を何か入れてください 🌟")
            return

        favorite_list = parse_ingredients(favorite)
        allergy_list = parse_ingredients(allergy)
        disliked_list = parse_ingredients(disliked)

        prompt = build_prompt(
            ingredients=ingredients,
            genre=genre,
            servings=servings_num,
            allergies=allergy_list,
            disliked=disliked_list,
            favorite=favorite_list,
            wants_filling=fill_c,
            wants_few_dishes=dishy,
            low_budget=low_bdg,
            quick=quick,
            notes=notes,
        )

        with st.spinner("🍳 ポチコが献立を考えています..."):
            raw = call_ai(prompt)

        data = extract_json(raw) if raw else None
        if not data:
            st.error("提案の読み取りに失敗しました。もう一度お試しください。")
            return

        # レシピ表示
        for i, key in enumerate(["candidate_1", "candidate_2", "candidate_3"], 1):
            render_recipe_card(data.get(key), i)

        # おことわり
        render_disclaimer()

        # 🌸 楽天ママ割バナー（ページ下部）
        render_mama_banner()


if __name__ == "__main__":
    main()
