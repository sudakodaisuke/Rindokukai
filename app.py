"""
輪読会準備アプリ（Streamlit Cloud 対応版）
英語医薬品ハンドブックの担当ページを英語語順・文節区切りで翻訳する台本を作成する。
"""

import json
import os
import re
import time

import fitz  # PyMuPDF
import streamlit as st

# ────────────────────────────────────────────
# パス定数
# ────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
BOOKS_DIR = os.path.join(BASE_DIR, "books")


# ────────────────────────────────────────────
# APIキー管理
# ────────────────────────────────────────────

def is_local() -> bool:
    """ローカル実行かどうかを判定。Streamlit Cloud では /mount/src にマウントされる。"""
    return not os.path.exists("/mount/src")


GEMINI_MODELS = [
    "gemini-2.5-flash-lite",          # 無料: 10RPM / 250K TPM（安定・デフォルト）
    "gemini-3.1-flash-lite-preview",  # 無料: 15RPM（プレビュー・レート超過で止まりやすい）
    "gemini-2.5-flash",               # 無料: 5RPM / 250K TPM
    "gemini-2.0-flash",               # 無料枠なし（使用不可）
]
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"


def load_api_keys() -> dict:
    """APIキーをセッション → config.json（ローカルのみ）の順で読み込む。"""
    keys = {"gemini_api_key": "", "deepl_api_key": "", "gemini_model": DEFAULT_GEMINI_MODEL}
    # ローカル実行時のみ config.json から読み込む（クラウドでは読まない）
    if is_local() and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
                for k in keys:
                    if saved.get(k):
                        keys[k] = saved[k]
        except Exception:
            pass
    # セッションステートから読み込む（ユーザーごとに完全に独立・安全）
    for k in keys:
        if st.session_state.get(k):
            keys[k] = st.session_state[k]
    # 廃止モデルが保存されていた場合はデフォルトに戻す
    if keys.get("gemini_model") not in GEMINI_MODELS:
        keys["gemini_model"] = DEFAULT_GEMINI_MODEL
    return keys


def save_api_keys(gemini_key: str, deepl_key: str, gemini_model: str = DEFAULT_GEMINI_MODEL) -> bool:
    """APIキーを保存する。
    - 常に: セッションステートに保存（ユーザーごとに独立・他のユーザーからは見えない）
    - ローカルのみ: config.json にも保存（次回起動時に再入力不要）
    """
    # セッションステートに保存（クラウド・ローカル共通・安全）
    st.session_state["gemini_api_key"] = gemini_key
    st.session_state["deepl_api_key"] = deepl_key
    st.session_state["gemini_model"] = gemini_model
    # ローカルのみ config.json にも保存
    if is_local():
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["gemini_api_key"] = gemini_key
        data["deepl_api_key"] = deepl_key
        data["gemini_model"] = gemini_model
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            pass
    return False


# ────────────────────────────────────────────
# PDF ユーティリティ
# ────────────────────────────────────────────

def scan_books() -> list[dict]:
    """books/ フォルダ内の PDF を自動スキャンして一覧を返す。"""
    os.makedirs(BOOKS_DIR, exist_ok=True)
    books = []
    for fname in sorted(os.listdir(BOOKS_DIR)):
        if fname.lower().endswith(".pdf"):
            path = os.path.join(BOOKS_DIR, fname)
            try:
                doc = fitz.open(path)
                total_pages = len(doc)
                doc.close()
            except Exception:
                total_pages = 0
            books.append({"name": fname, "path": path, "total_pages": total_pages})
    return books


@st.cache_data
def render_page_image(pdf_path: str, page_num: int) -> bytes:
    """PDFの指定ページを画像として返す（キャッシュ付き）。"""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def extract_text(pdf_path: str, start_page: int, end_page: int) -> str:
    """指定ページ範囲のテキストを抽出（ページ番号は1始まり）。"""
    doc = fitz.open(pdf_path)
    total = len(doc)
    start_page = max(1, min(start_page, total))
    end_page = max(start_page, min(end_page, total))
    texts = []
    for i in range(start_page - 1, end_page):
        page = doc[i]
        texts.append(page.get_text())
    doc.close()
    return "\n".join(texts)


def split_sentences(text: str) -> list[str]:
    """テキストを文ごとに分割する。"""
    # ハイフネーションされた改行を結合
    text = re.sub(r"-\n(\w)", r"\1", text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" {2,}", " ", text).strip()
    # 略語のピリオドを一時的に置換して誤分割を防ぐ
    abbrevs = [
        "e.g.", "i.e.", "etc.", "Fig.", "Vol.", "No.", "Dr.", "Mr.",
        "Mrs.", "Ms.", "Prof.", "St.", "vs.", "cf.", "al.", "ca.",
        "approx.", "dept.", "est.", "incl.", "excl.", "ref.", "resp.",
    ]
    for ab in abbrevs:
        text = text.replace(ab, ab.replace(".", "§"))
    # 固定幅のlookbehindのみ使用（Python 3.14対応）
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    # セクション番号ヘッダー（例: 3.3.4 TRUE DENSITY）の前でも分割
    # ※ "3.3.4 TRUE" のように「数字.数字 大文字2字以上」が続く場合
    expanded = []
    for s in sentences:
        parts = re.split(r"(?<=[.!?])\s+(?=\d+\.\d+[\d.]*\s+[A-Z]{2,})", s)
        expanded.extend(parts)
    # 置換を元に戻す
    result = []
    for s in expanded:
        s = s.replace("§", ".").strip()
        if s and len(s) > 10:
            result.append(s)
    return result


# ────────────────────────────────────────────
# 翻訳
# ────────────────────────────────────────────

GEMINI_PROMPT = """あなたは医薬品製造の専門家です。
以下の英文を、英語の語順に従って文節ごとに訳してください。
日本語として自然な語順ではなく、英文の前から後ろへ順番に訳し、各文節を「／」で区切って1行で出力してください。
訳文のみ出力し、説明は不要です。

例：
英文: In wet granulation, it is conceptually important to consider drying and cooling as an integral part of the granulation process.
訳: 湿式造粒では、／概念的に重要である。／乾燥と冷却を／位置づけることが／造粒工程の不可欠な一部として

英文: {sentence}
訳:"""

GEMINI_REORDER_PROMPT = """あなたは医薬品製造の専門家です。
以下は英文をDeepLで翻訳した日本語訳です。この訳を、元の英文の語順に従って文節ごとに並び替えてください。
日本語として自然な語順ではなく、英文の前から後ろへ順番に並び替え、各文節を「／」で区切って1行で出力してください。
並び替えた訳文のみ出力し、説明は不要です。

例：
英文: In wet granulation, it is conceptually important to consider drying and cooling as an integral part of the granulation process.
DeepL訳: 湿式造粒では、乾燥と冷却を造粒工程の不可欠な一部として位置づけることが概念的に重要です。
並び替え後: 湿式造粒では、／概念的に重要です。／乾燥と冷却を／位置づけることが／造粒工程の不可欠な一部として

英文: {sentence}
DeepL訳: {deepl_text}
並び替え後:"""



def translate_gemini_batch(
    sentences: list[str], api_key: str, model_name: str = DEFAULT_GEMINI_MODEL,
) -> list[dict]:
    """複数の文を1回のAPIリクエストでまとめて翻訳する（英語語順・文節訳）。
    戻り値: [{"english": "英文スラッシュ区切り", "japanese": "日本語スラッシュ区切り"}, ...]
    """
    if not sentences:
        return []
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        numbered = "\n".join(f"【{i+1}】{s}" for i, s in enumerate(sentences))
        prompt = f"""あなたは医薬品製造の専門家です。
以下の英文リストを、英語の語順に従って文節ごとに訳してください。
日本語として自然な語順ではなく、英文の前から後ろへ順番に訳し、各文節を「／」で区切ってください。
さらに、英文も同じ文節の区切り位置でスラッシュ区切りにしてください。

出力形式（番号・英・日のみ、説明不要）：
【例】
英: In wet granulation, ／it is conceptually important ／to consider drying and cooling ／as an integral part ／of the granulation process.
日: 湿式造粒では、／概念的に重要である。／乾燥と冷却を／位置づけることが／造粒工程の不可欠な一部として

英文リスト：
{numbered}"""
        response = model.generate_content(prompt, request_options={"timeout": 120})
        result_text = response.text.strip()
        results = [{"english": "", "japanese": ""} for _ in sentences]
        block_pat = re.compile(
            r"【(\d+)】\s*\n英[:：]\s*(.+?)\n日[:：]\s*(.+?)(?=\n?【\d+】|$)", re.DOTALL
        )
        matched = list(block_pat.finditer(result_text))
        if matched:
            for m in matched:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(sentences):
                    results[idx]["english"] = m.group(2).strip()
                    results[idx]["japanese"] = m.group(3).strip()
        else:
            for m in re.finditer(r"【(\d+)】\s*(.+?)(?=【\d+】|$)", result_text, re.DOTALL):
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(sentences):
                    results[idx]["japanese"] = m.group(2).strip()
        return results
    except Exception as e:
        return [{"english": "", "japanese": f"[Gemini バッチエラー: {e}]"}] * len(sentences)


def translate_deepl_batch(sentences: list[str], api_key: str) -> list[str]:
    """複数の文を1回のAPIリクエストでまとめてDeepL翻訳する。"""
    if not sentences:
        return []
    try:
        import deepl
        translator = deepl.Translator(api_key)
        results = translator.translate_text(sentences, target_lang="JA")
        return [r.text for r in results]
    except Exception as e:
        return [f"[DeepL バッチエラー: {e}]"] * len(sentences)


def translate_deepl_reorder_batch(
    sentences: list[str], deepl_texts: list[str], api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
) -> list[dict]:
    """DeepL訳をGeminiで並び替え、英文も同じ位置でスラッシュ区切りして返す。
    戻り値: [{"english": "英文スラッシュ区切り", "japanese": "日本語スラッシュ区切り"}, ...]
    """
    if not sentences:
        return []
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        numbered = "\n".join(
            f"【{i+1}】英文: {s}\n　　DeepL訳: {d}"
            for i, (s, d) in enumerate(zip(sentences, deepl_texts))
        )
        prompt = f"""あなたは医薬品製造の専門家です。
以下の各英文とDeepL訳のペアについて、DeepL訳を元の英文の語順に従って文節ごとに並び替えてください。
さらに、英文も同じ文節の区切り位置でスラッシュ区切りにしてください。

出力形式（番号・英・日のみ、説明不要）：
【例】
英: In wet granulation, ／it is conceptually important ／to consider drying and cooling ／as an integral part ／of the granulation process.
日: 湿式造粒では、／概念的に重要です。／乃至は乾燥と冷却を／位置づけることが／造粒工程の不可欠な一部として

{numbered}"""
        response = model.generate_content(prompt, request_options={"timeout": 120})
        result_text = response.text.strip()
        results = [{"english": "", "japanese": ""} for _ in sentences]
        block_pat = re.compile(
            r"【(\d+)】\s*\n英[:：]\s*(.+?)\n日[:：]\s*(.+?)(?=\n?【\d+】|$)", re.DOTALL
        )
        for m in block_pat.finditer(result_text):
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(sentences):
                results[idx]["english"] = m.group(2).strip()
                results[idx]["japanese"] = m.group(3).strip()
        return results
    except Exception as e:
        return [{"english": "", "japanese": f"[並び替えバッチエラー: {e}]"}] * len(sentences)


def translate_gemini(sentence: str, api_key: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(GEMINI_PROMPT.format(sentence=sentence))
        result = response.text.strip()
        result = re.sub(r"^訳[:：]\s*", "", result)
        return result
    except Exception as e:
        return f"[Gemini エラー: {e}]"


def read_page_figures(pdf_path: str, page_num: int, api_key: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    """Gemini Vision APIでページ内の図・数式・表を読み取る。"""
    try:
        import google.generativeai as genai
        img_bytes = render_page_image(pdf_path, page_num)
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = """この医薬品ハンドブックのページに含まれる図、グラフ、数式、表を全て抽出・説明してください。
本文テキストは無視して、以下のものだけに集中してください：
- 数式：できるだけそのまま文字で表現（例: k = A·exp(-Ea/RT)）
- グラフ・図：タイトル、軸ラベル、内容を日本語で説明
- 表：内容をテキストで再現
図表・数式が何もない場合は「このページに図表・数式はありません」とだけ出力してください。"""
        response = model.generate_content([
            prompt,
            {"mime_type": "image/png", "data": img_bytes},
        ])
        return response.text.strip()
    except Exception as e:
        return f"[読み取りエラー: {e}]"


def translate_deepl(sentence: str, api_key: str) -> str:
    try:
        import deepl
        translator = deepl.Translator(api_key)
        result = translator.translate_text(sentence, target_lang="JA")
        return result.text
    except Exception as e:
        return f"[DeepL エラー: {e}]"


def translate_deepl_reorder(sentence: str, deepl_text: str, gemini_api_key: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    """DeepL訳をGeminiで英語語順・文節区切りに並び替える。"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel(model_name)
        prompt = GEMINI_REORDER_PROMPT.format(sentence=sentence, deepl_text=deepl_text)
        response = model.generate_content(prompt)
        result = response.text.strip()
        result = re.sub(r"^並び替え後[:：]\s*", "", result)
        return result
    except Exception as e:
        return f"[並び替えエラー: {e}]"


# ────────────────────────────────────────────
# 台本テキスト生成（ダウンロード用）
# ────────────────────────────────────────────

DOWNLOAD_MODE_LABELS = {
    "gemini":        "🤖 Gemini（英語語順訳）",
    "deepl":         "📝 DeepL（参考訳）",
    "deepl_reorder": "🔄 DeepL→Gemini並び替え",
}


def build_script_text(results: list[dict], modes: list[str] | None = None) -> str:
    """台本テキストを生成する。modes で含める翻訳種別を指定（None のとき全種別）。"""
    if modes is None:
        modes = list(DOWNLOAD_MODE_LABELS.keys())

    CIRCLED = ["①", "②", "③", "④"]
    multi = len(modes) > 1

    lines = ["=" * 60, "輪読会 台本", "=" * 60, ""]

    # 複数モード選択時: 凡例を先頭に1回だけ出す
    if multi:
        legend = "  ".join(
            f"{CIRCLED[i]} {DOWNLOAD_MODE_LABELS[m]}"
            for i, m in enumerate(modes) if i < len(CIRCLED)
        )
        lines.append(f"凡例: {legend}")
        lines.append("")

    for i, r in enumerate(results, 1):
        lines.append(f"【{i}】{r['sentence']}")
        lines.append("")

        for j, m in enumerate(modes):
            prefix = f"{CIRCLED[j]} " if multi else ""

            if m == "gemini" and r.get("gemini"):
                if r.get("gemini_en"):
                    lines.append(f"  {prefix}[英] {r['gemini_en']}")
                    lines.append(f"  {'　 ' if multi else ''}[日] {r['gemini']}")
                else:
                    lines.append(f"  {prefix}{r['gemini']}")

            elif m == "deepl" and r.get("deepl"):
                lines.append(f"  {prefix}{r['deepl']}")

            elif m == "deepl_reorder" and r.get("deepl_reorder"):
                if r.get("deepl_reorder_en"):
                    lines.append(f"  {prefix}[英] {r['deepl_reorder_en']}")
                    lines.append(f"  {'　 ' if multi else ''}[日] {r['deepl_reorder']}")
                else:
                    lines.append(f"  {prefix}{r['deepl_reorder']}")

        lines.append("")
        lines.append("-" * 60)
        lines.append("")
    return "\n".join(lines)


# ────────────────────────────────────────────
# Streamlit アプリ本体
# ────────────────────────────────────────────

st.set_page_config(page_title="輪読会準備アプリ", page_icon="📖", layout="wide")
st.title("📖 輪読会準備アプリ")
st.caption("英語医薬品ハンドブックの担当ページを、英語の語順で文節ごとに訳す台本を作成します。")

# セッション初期化
if "extracted_text" not in st.session_state:
    st.session_state.extracted_text = ""
if "translation_results" not in st.session_state:
    st.session_state.translation_results = []

tab_settings, tab_pages, tab_script = st.tabs(["⚙️ 設定", "📄 ページ選択・テキスト確認", "📋 台本"])


# ══════════════════════════════════════════════
# Tab 1: 設定
# ══════════════════════════════════════════════
with tab_settings:
    st.header("⚙️ 設定")

    # ── APIキー ──────────────────────────────
    st.subheader("翻訳 API キー")

    keys = load_api_keys()

    col_g, col_d = st.columns(2)

    with col_g:
        st.markdown("**🤖 Gemini API キー**")
        gemini_input = st.text_input(
            "Gemini API キー",
            value=keys["gemini_api_key"],
            type="password",
            placeholder="AIzaSy...",
            key="gemini_key_input",
            label_visibility="collapsed",
        )
        with st.expander("Gemini API キーの取得方法"):
            st.markdown("""
1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセス
2. Googleアカウントでサインイン
3. 「**Create API key**」をクリック
4. 生成されたキー（`AIzaSy...`）をコピーして上の欄に貼り付け

**無料枠（2024年時点）：**
- Gemini 1.5 Flash: 1分あたり15リクエスト、1日100万トークン
- クレジットカード登録不要
""")

    with col_d:
        st.markdown("**📝 DeepL API キー**")
        deepl_input = st.text_input(
            "DeepL API キー",
            value=keys["deepl_api_key"],
            type="password",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx",
            key="deepl_key_input",
            label_visibility="collapsed",
        )
        with st.expander("DeepL API キーの取得方法"):
            st.markdown("""
1. [DeepL API](https://www.deepl.com/ja/pro-api) にアクセス
2. 「**無料で始める**」→ **DeepL API Free** に登録
3. クレジットカードの登録が必要（無料枠内なら課金なし）
4. アカウント設定ページで API キーを確認・コピー

**無料枠：** 毎月 50万文字まで無料

> ⚠️ 無料版のキーは末尾が `:fx` になっています
> 例: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx`
""")

    st.markdown("**🤖 Gemini モデル**")
    current_model = keys.get("gemini_model", DEFAULT_GEMINI_MODEL)
    model_idx = GEMINI_MODELS.index(current_model) if current_model in GEMINI_MODELS else 0
    selected_model = st.selectbox(
        "Geminiモデル（候補）",
        GEMINI_MODELS,
        index=model_idx,
        key="gemini_model_select",
    )
    custom_model = st.text_input(
        "モデル名を直接入力（エラーが出る場合のみ。空欄なら上の候補を使用）",
        placeholder="例: gemini-3.1-flash-lite-001 など",
        key="custom_model_input",
    )
    effective_model = custom_model.strip() if custom_model.strip() else selected_model
    st.caption(f"使用するモデル: `{effective_model}`")

    st.info(
        "💡 Gemini API はモデルごとに **1分あたりの利用回数（RPM）** に上限があります。"
        "うまくいかない・止まる場合は **別のモデルに切り替えて**「確定して保存する」を押してみてください。"
        "制限は **1分後に自動回復** します。"
    )

    with st.expander("📊 モデルの無料枠とエラー時の対処"):
        st.markdown("""
**RPM（1分あたりの上限回数）について**
Gemini API は無料で使える回数が1分間に制限されています。
超えると応答が止まりますが、**1分待てば自動的に回復**します。

| モデル | RPM（1分） | 安定性 | おすすめ |
|---|---|---|---|
| `gemini-2.5-flash-lite` | 10回/分 | ⭐ 安定 | ★★★ デフォルト |
| `gemini-3.1-flash-lite-preview` | 15回/分 | ⚠️ プレビュー版・超過しやすい | ★★ |
| `gemini-2.5-flash` | 5回/分 | ⭐ 安定 | ★ |
| `gemini-2.0-flash` | **0（使用不可）** | ❌ | ❌ |

**止まる・エラーになる場合：**
1. 別のモデルを選んで「確定して保存する」を押す
2. 1分ほど待ってから再度「台本を作成する」を押す

**モデル名エラーの場合：**
[Google AI Studio](https://aistudio.google.com) → モデル選択 → 「Get code」→「Python」でコード内の正確な名前を確認できます。
""")

    st.warning("⚠️ APIキーやモデルを変更したら、必ず下のボタンを押してください！")
    if st.button("✅ 確定して保存する", type="primary", use_container_width=True):
        new_gemini = gemini_input if gemini_input else keys["gemini_api_key"]
        new_deepl = deepl_input if deepl_input else keys["deepl_api_key"]
        saved_to_file = save_api_keys(new_gemini, new_deepl, effective_model)
        if saved_to_file:
            st.success("✅ 保存しました！次回起動時も入力不要です。")
        else:
            st.success("✅ このセッションに設定しました。（タブを閉じるまで有効）")

    st.divider()

    # ── PDF管理 ──────────────────────────────
    st.subheader("📚 PDF の管理")

    books = scan_books()
    if books:
        st.success(f"{len(books)} 件の PDF が books/ フォルダにあります。")
        for b in books:
            st.text(f"  📄 {b['name']}  （{b['total_pages']} ページ）")
    else:
        st.info("books/ フォルダに PDF がありません。下の手順で追加してください。")

    with st.expander("📤 PDF をアップロードする（ローカル実行時のみ）"):
        st.caption("Streamlit Cloud では Git LFS を使って事前に books/ に入れてください（下の手順参照）。")
        uploaded = st.file_uploader("PDFファイル", type=["pdf"], key="pdf_uploader")
        if st.button("books/ に保存", disabled=(uploaded is None)):
            dest = os.path.join(BOOKS_DIR, uploaded.name)
            with open(dest, "wb") as f:
                f.write(uploaded.getbuffer())
            st.success(f"保存しました: {uploaded.name}")
            st.rerun()

    with st.expander("☁️ Streamlit Cloud へのデプロイ手順（初回のみ）"):
        st.markdown("""
### ステップ 1｜Git LFS のインストール

**Mac:**
```bash
brew install git-lfs
```
**Windows:**  Git for Windows に含まれています。下記を実行するだけ。
```bash
git lfs install
```

---

### ステップ 2｜リポジトリで Git LFS を有効化

```bash
cd Rindokukai
git lfs install
# .gitattributes はすでに設定済みです（このリポジトリに含まれています）
```

---

### ステップ 3｜PDF を books/ に追加してコミット

```bash
# PDF ファイルを books/ フォルダにコピー
cp /path/to/handbook.pdf books/

# コミット（Git LFS が自動で大きいファイルを管理）
git add books/handbook.pdf
git commit -m "ハンドブックPDFを追加（Git LFS）"
git push
```

---

### ステップ 4｜Streamlit Community Cloud でデプロイ

1. [share.streamlit.io](https://share.streamlit.io) にアクセス（GitHub アカウントでログイン）
2. 「**New app**」→ このリポジトリを選択 → メインファイルに `app.py` を指定
3. 「**Advanced settings**」→ **Secrets** に以下を貼り付け：

```toml
gemini_api_key = "AIzaSy..."
deepl_api_key = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx"
```

4. 「**Deploy**」をクリック → 数分でURLが発行されます

> ✅ このURLをスマホのブラウザで開けば完成です！
""")


# ══════════════════════════════════════════════
# Tab 2: ページ選択・テキスト確認
# ══════════════════════════════════════════════
with tab_pages:
    st.header("📄 ページ選択・テキスト確認")

    books = scan_books()

    if not books:
        st.warning("books/ フォルダに PDF がありません。「⚙️ 設定」タブから追加してください。")
    else:
        book_options = {b["name"]: b for b in books}
        selected_name = st.selectbox("本を選択", list(book_options.keys()), key="book_select")
        selected_book = book_options[selected_name]
        total_pages = selected_book["total_pages"]

        # ── ページ範囲選択（スライダー＋数値入力の連動） ──
        st.markdown(f"**担当ページを選択**　（全 {total_pages} ページ）")

        # セッション状態の初期化
        if "range_start" not in st.session_state:
            st.session_state.range_start = 1
        if "range_end" not in st.session_state:
            st.session_state.range_end = min(4, total_pages)

        def on_slider_change():
            s, e = st.session_state["slider_range"]
            st.session_state.range_start = s
            st.session_state.range_end = e

        def on_input_change():
            s = st.session_state.range_start
            e = st.session_state.range_end
            if s > e:
                st.session_state.range_end = s

        st.slider(
            "スライダーで範囲選択",
            min_value=1,
            max_value=total_pages,
            value=(st.session_state.range_start, st.session_state.range_end),
            key="slider_range",
            on_change=on_slider_change,
            label_visibility="collapsed",
        )

        col_s, col_e = st.columns(2)
        with col_s:
            st.number_input(
                "開始ページ（直接入力可）",
                min_value=1, max_value=total_pages,
                key="range_start",
                on_change=on_input_change,
            )
        with col_e:
            st.number_input(
                "終了ページ（直接入力可）",
                min_value=1, max_value=total_pages,
                key="range_end",
                on_change=on_input_change,
            )

        start_page = st.session_state.range_start
        end_page = st.session_state.range_end
        st.caption(f"選択中: **{start_page} 〜 {end_page} ページ**（{end_page - start_page + 1} ページ分）")

        # ── ページプレビュー ──────────────────
        num_selected = end_page - start_page + 1
        MAX_PREVIEW = 6
        preview_pages = list(range(start_page, min(end_page + 1, start_page + MAX_PREVIEW)))

        st.markdown("**ページプレビュー**")
        if num_selected > MAX_PREVIEW:
            st.caption(f"最初の {MAX_PREVIEW} ページを表示しています。")

        cols = st.columns(min(num_selected, 3))
        for i, pnum in enumerate(preview_pages):
            with cols[i % 3]:
                img = render_page_image(selected_book["path"], pnum)
                st.image(img, caption=f"p. {pnum}", use_container_width=True)

        st.divider()

        # ── 図・数式の読み取り ────────────────
        fig_gemini_key = load_api_keys()["gemini_api_key"]
        fig_model = load_api_keys().get("gemini_model", DEFAULT_GEMINI_MODEL)
        col_ext, col_fig = st.columns(2)
        with col_ext:
            extract_btn = st.button("📄 テキストを抽出", type="primary")
        with col_fig:
            fig_btn = st.button(
                "🔍 Geminiで図・数式を読み取る",
                disabled=not fig_gemini_key,
                help="選択ページの図・グラフ・数式・表をGeminiが説明します。APIキーが必要です。",
            )

        if extract_btn:
            with st.spinner("テキストを抽出中..."):
                text = extract_text(selected_book["path"], int(start_page), int(end_page))
            st.session_state.extracted_text = text
            st.session_state.translation_results = []
            st.success(f"ページ {start_page}〜{end_page} のテキストを抽出しました。")

        if fig_btn:
            all_pages = list(range(start_page, end_page + 1))
            fig_results = []
            prog = st.progress(0, text="図・数式を読み取り中...")
            for i, pnum in enumerate(all_pages):
                result = read_page_figures(selected_book["path"], pnum, fig_gemini_key, fig_model)
                fig_results.append(f"=== p.{pnum} ===\n{result}")
                prog.progress((i + 1) / len(all_pages), text=f"p.{pnum} 読み取り中... {i+1}/{len(all_pages)}")
            prog.empty()
            combined = "\n\n".join(fig_results)
            st.subheader("🔍 図・数式の読み取り結果")
            st.text_area(
                "読み取り結果（必要な箇所をコピーしてテキスト編集欄に追記できます）",
                value=combined,
                height=300,
                label_visibility="collapsed",
            )

            with st.spinner("テキストを抽出中..."):
                text = extract_text(selected_book["path"], int(start_page), int(end_page))
            st.session_state.extracted_text = text
            st.session_state.translation_results = []
            st.success(f"ページ {start_page}〜{end_page} のテキストを抽出しました。")

        if st.session_state.extracted_text:
            st.subheader("抽出テキストの確認・編集")
            st.caption("ヘッダー・フッター・図の説明文など不要なテキストは削除してから台本を作成してください。")
            edited = st.text_area(
                "テキスト",
                value=st.session_state.extracted_text,
                height=400,
                label_visibility="collapsed",
            )
            st.session_state.extracted_text = edited

            sentences = split_sentences(edited)
            st.info(f"検出された文の数: {len(sentences)} 文")

            keys = load_api_keys()
            gemini_key = keys["gemini_api_key"]
            deepl_key = keys["deepl_api_key"]
            gemini_model = keys.get("gemini_model", DEFAULT_GEMINI_MODEL)

            st.markdown("**翻訳方法を選択**")
            col_ug, col_ud, col_ur = st.columns(3)
            with col_ug:
                use_gemini = st.checkbox(
                    "🤖 Gemini（英語語順・文節訳）",
                    value=bool(gemini_key),
                    disabled=not gemini_key,
                    key="use_gemini",
                )
                if not gemini_key:
                    st.caption("「設定」タブで Gemini キーを入力してください。")
            with col_ud:
                use_deepl = st.checkbox(
                    "📝 DeepL（参考訳）",
                    value=bool(deepl_key),
                    disabled=not deepl_key,
                    key="use_deepl",
                )
                if not deepl_key:
                    st.caption("「設定」タブで DeepL キーを入力してください。")
            with col_ur:
                use_deepl_reorder = st.checkbox(
                    "🔄 DeepL→Gemini並び替え",
                    value=bool(gemini_key and deepl_key),
                    disabled=not (gemini_key and deepl_key),
                    key="use_deepl_reorder",
                )
                if not (gemini_key and deepl_key):
                    st.caption("GeminiとDeepL両方のキーが必要です。")
                else:
                    st.caption("DeepL訳をGeminiで英語語順に並び替え")

            if not use_gemini and not use_deepl and not use_deepl_reorder:
                st.warning("少なくとも1つの翻訳方法を選択してください。")
            else:
                gemini_calls = (1 if use_gemini else 0) + (1 if use_deepl_reorder else 0)
                st.info(
                    f"📡 Gemini APIリクエスト数: **{gemini_calls} 回** / DeepL: {'1 回' if (use_deepl or use_deepl_reorder) else '0 回'}  \n"
                    "⚠️ 止まったり失敗したら **1〜2分待ってから** 再度押してください（レート制限は1分で回復します）"
                )
                if st.button("🚀 台本を作成する", type="primary", disabled=not sentences):
                    results = [{"sentence": s, "gemini": "", "gemini_en": "", "deepl": "", "deepl_reorder": "", "deepl_reorder_en": ""} for s in sentences]
                    progress = st.progress(0, text="翻訳中...")

                    # DeepLバッチ翻訳（1回で全文）
                    deepl_texts = [""] * len(sentences)
                    if use_deepl or use_deepl_reorder:
                        progress.progress(0.1, text="DeepL 翻訳中（まとめて1回送信）...")
                        deepl_texts = translate_deepl_batch(sentences, deepl_key)
                        if use_deepl:
                            for i, r in enumerate(results):
                                r["deepl"] = deepl_texts[i]

                    # Geminiバッチ翻訳（1回で全文）
                    if use_gemini:
                        progress.progress(0.4, text="Gemini 翻訳中（まとめて1回送信）...")
                        gemini_dicts = translate_gemini_batch(sentences, gemini_key, gemini_model)
                        for i, r in enumerate(results):
                            r["gemini"] = gemini_dicts[i]["japanese"]
                            r["gemini_en"] = gemini_dicts[i]["english"]

                    # DeepL→Gemini並び替え（1回で全文）
                    if use_deepl_reorder:
                        progress.progress(0.7, text="Gemini 並び替え中（まとめて1回送信）...")
                        reorder_dicts = translate_deepl_reorder_batch(
                            sentences, deepl_texts, gemini_key, gemini_model
                        )
                        for i, r in enumerate(results):
                            r["deepl_reorder"] = reorder_dicts[i]["japanese"]
                            r["deepl_reorder_en"] = reorder_dicts[i]["english"]

                    st.session_state.translation_results = results
                    progress.empty()
                    st.success("台本を作成しました。「📋 台本」タブで確認してください。")


# ══════════════════════════════════════════════
# Tab 3: 台本
# ══════════════════════════════════════════════
with tab_script:
    st.header("📋 台本")

    results = st.session_state.translation_results
    if not results:
        st.info("「📄 ページ選択・テキスト確認」タブで台本を作成してください。")
    else:
        # ── ダウンロード形式の選択 ──────────────
        available_modes = [k for k, _ in DOWNLOAD_MODE_LABELS.items() if any(r.get(k) for r in results)]
        selected_labels = st.multiselect(
            "ダウンロードに含める訳を選択",
            options=[DOWNLOAD_MODE_LABELS[k] for k in available_modes],
            default=[DOWNLOAD_MODE_LABELS[k] for k in available_modes],
            key="download_modes",
        )
        label_to_key = {v: k for k, v in DOWNLOAD_MODE_LABELS.items()}
        selected_modes = [label_to_key[lbl] for lbl in selected_labels if lbl in label_to_key]

        script_text = build_script_text(results, selected_modes if selected_modes else None)
        st.download_button(
            "📥 台本をテキストファイルでダウンロード",
            data=script_text.encode("utf-8"),
            file_name="rindokukai_script.txt",
            mime="text/plain",
            disabled=not selected_modes,
        )
        st.divider()
        for i, r in enumerate(results, 1):
            with st.container(border=True):
                st.markdown(f"**【{i}】** {r['sentence']}")
                if r.get("gemini"):
                    st.markdown("🤖 **Gemini（英語語順訳）**")
                    if r.get("gemini_en"):
                        en_parts = r["gemini_en"].split("／")
                        en_formatted = "　**／** ".join(p.strip() for p in en_parts if p.strip())
                        st.markdown(f"> 🇬🇧 {en_formatted}")
                    ja_parts = r["gemini"].split("／")
                    ja_formatted = "　**／** ".join(p.strip() for p in ja_parts if p.strip())
                    st.markdown(f"> 🇯🇵 {ja_formatted}")
                if r.get("deepl"):
                    st.markdown("📝 **DeepL（参考訳）**")
                    st.markdown(f"> {r['deepl']}")
                if r.get("deepl_reorder"):
                    st.markdown("🔄 **DeepL→Gemini並び替え**")
                    if r.get("deepl_reorder_en"):
                        en_parts = r["deepl_reorder_en"].split("／")
                        en_formatted = "　**／** ".join(p.strip() for p in en_parts if p.strip())
                        st.markdown(f"> 🇬🇧 {en_formatted}")
                    ja_parts = r["deepl_reorder"].split("／")
                    ja_formatted = "　**／** ".join(p.strip() for p in ja_parts if p.strip())
                    st.markdown(f"> 🇯🇵 {ja_formatted}")
