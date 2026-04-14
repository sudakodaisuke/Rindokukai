"""
輪読会準備アプリ
英語医薬品ハンドブックの担当ページを、英語の語順で文節ごとに訳す台本を作成する。
"""

import json
import os
import re
import shutil
import time

import fitz  # PyMuPDF
import streamlit as st

# ─────────────────────────────────────────────
# 定数・設定ファイル
# ─────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
BOOKS_DIR = os.path.join(os.path.dirname(__file__), "books")

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "deepl_api_key": "",
    "books": [],
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# PDF ユーティリティ
# ─────────────────────────────────────────────

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
    # 改行を空白に
    text = re.sub(r"\n+", " ", text)
    # 複数空白を1つに
    text = re.sub(r" {2,}", " ", text).strip()

    # 文分割：ピリオド/!/?の後ろで大文字が続く場合
    # 略語（e.g., i.e., Fig., etc.）は分割しない
    abbreviations = r"(?<!\b(?:e\.g|i\.e|etc|Fig|Vol|No|Dr|Mr|Mrs|Ms|Prof|St|vs|cf|al|ca|approx|dept|est|incl|excl|ref|resp))"
    sentence_pattern = abbreviations + r"(?<=[.!?])\s+(?=[A-Z])"
    sentences = re.split(sentence_pattern, text)
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]


# ─────────────────────────────────────────────
# 翻訳ユーティリティ
# ─────────────────────────────────────────────

GEMINI_PROMPT = """あなたは医薬品製造の専門家です。
以下の英文を、英語の語順に従って文節ごとに訳してください。
日本語として自然な語順ではなく、英文の前から後ろへ順番に訳し、各文節を「／」で区切って1行で出力してください。
訳文のみ出力し、説明は不要です。

例：
英文: In wet granulation, it is conceptually important to consider drying and cooling as an integral part of the granulation process.
訳: 湿式造粒では、／概念的に重要である。／乾燥と冷却を／位置づけることが／造粒工程の不可欠な一部として

英文: {sentence}
訳:"""


def translate_gemini(sentence: str, api_key: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = GEMINI_PROMPT.format(sentence=sentence)
        response = model.generate_content(prompt)
        result = response.text.strip()
        # 「訳:」が残っていれば除去
        result = re.sub(r"^訳[:：]\s*", "", result)
        return result
    except Exception as e:
        return f"[Gemini エラー: {e}]"


def translate_deepl(sentence: str, api_key: str) -> str:
    try:
        import deepl
        translator = deepl.Translator(api_key)
        result = translator.translate_text(sentence, target_lang="JA")
        return result.text
    except Exception as e:
        return f"[DeepL エラー: {e}]"


# ─────────────────────────────────────────────
# 台本テキスト生成（ダウンロード用）
# ─────────────────────────────────────────────

def build_script_text(results: list[dict]) -> str:
    lines = ["=" * 60, "輪読会 台本", "=" * 60, ""]
    for i, r in enumerate(results, 1):
        lines.append(f"【{i}】{r['sentence']}")
        lines.append("")
        if r.get("gemini"):
            lines.append(f"  🤖 Gemini（英語語順訳）:")
            lines.append(f"  {r['gemini']}")
        if r.get("deepl"):
            lines.append(f"  📝 DeepL（参考訳）:")
            lines.append(f"  {r['deepl']}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Streamlit アプリ本体
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="輪読会準備アプリ",
    page_icon="📖",
    layout="wide",
)

st.title("📖 輪読会準備アプリ")
st.caption("英語医薬品ハンドブックの担当ページを、英語の語順で文節ごとに訳す台本を作成します。")

# Session state 初期化
if "extracted_text" not in st.session_state:
    st.session_state.extracted_text = ""
if "translation_results" not in st.session_state:
    st.session_state.translation_results = []

cfg = load_config()

tab_settings, tab_pages, tab_script = st.tabs(["⚙️ 設定", "📄 ページ選択・テキスト確認", "📋 台本"])

# ══════════════════════════════════════════════
# Tab 1: 設定
# ══════════════════════════════════════════════
with tab_settings:
    st.header("⚙️ 設定")

    # ── API キー ────────────────────────────
    st.subheader("翻訳 API キー")

    col_g, col_d = st.columns(2)

    with col_g:
        st.markdown("**🤖 Gemini API キー**")
        gemini_key = st.text_input(
            "Gemini API キー",
            value=cfg.get("gemini_api_key", ""),
            type="password",
            key="gemini_key_input",
            label_visibility="collapsed",
        )
        with st.expander("Gemini API キーの取得方法"):
            st.markdown("""
1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセス
2. Googleアカウントでサインイン
3. 「APIキーを作成」をクリック
4. 生成されたキーをコピーして上の欄に貼り付け

**無料枠（2024年時点）：**
- Gemini 1.5 Flash: 毎分15リクエスト、1日100万トークン無料
- クレジットカード登録不要
""")

    with col_d:
        st.markdown("**📝 DeepL API キー**")
        deepl_key = st.text_input(
            "DeepL API キー",
            value=cfg.get("deepl_api_key", ""),
            type="password",
            key="deepl_key_input",
            label_visibility="collapsed",
        )
        with st.expander("DeepL API キーの取得方法"):
            st.markdown("""
1. [DeepL API](https://www.deepl.com/pro-api) にアクセス
2. 「無料で始める」→ DeepL API Free に登録
3. クレジットカードの登録が必要（無料枠を超えなければ課金なし）
4. アカウント設定ページで API キーを確認
5. コピーして上の欄に貼り付け

**無料枠：** 毎月 50万文字まで無料

> ⚠️ DeepL の無料 API キーは末尾が `:fx` になっています（例: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx`）
""")

    if st.button("APIキーを保存", type="primary"):
        cfg["gemini_api_key"] = gemini_key
        cfg["deepl_api_key"] = deepl_key
        save_config(cfg)
        st.success("APIキーを保存しました。")

    st.divider()

    # ── PDF 登録 ────────────────────────────
    st.subheader("📚 PDFの登録")

    uploaded = st.file_uploader(
        "PDFファイルをアップロード（一度登録すれば次回から選択するだけでOK）",
        type=["pdf"],
        key="pdf_uploader",
    )
    book_display_name = st.text_input(
        "本のタイトル（任意）",
        placeholder="例: HANDBOOK OF PHARMACEUTICAL GRANULATION 4th Ed.",
        key="book_title_input",
    )

    if st.button("PDFを登録", disabled=(uploaded is None)):
        os.makedirs(BOOKS_DIR, exist_ok=True)
        dest_path = os.path.join(BOOKS_DIR, uploaded.name)
        with open(dest_path, "wb") as f:
            f.write(uploaded.getbuffer())
        # ページ数取得
        doc = fitz.open(dest_path)
        total_pages = len(doc)
        doc.close()
        title = book_display_name.strip() or uploaded.name
        # 重複チェック
        existing_paths = [b["path"] for b in cfg["books"]]
        rel_path = os.path.join("books", uploaded.name)
        if rel_path not in existing_paths:
            cfg["books"].append({"name": title, "path": rel_path, "total_pages": total_pages})
            save_config(cfg)
            st.success(f"登録完了：{title}（{total_pages}ページ）")
        else:
            st.info("このPDFはすでに登録されています。")

    st.divider()

    # ── 登録済み本の一覧 ────────────────────
    st.subheader("登録済みの本")
    if not cfg["books"]:
        st.info("まだ本が登録されていません。上のフォームからPDFをアップロードしてください。")
    else:
        for idx, book in enumerate(cfg["books"]):
            col_name, col_pages, col_del = st.columns([4, 1, 1])
            with col_name:
                st.text(book["name"])
            with col_pages:
                st.text(f"{book['total_pages']}p")
            with col_del:
                if st.button("削除", key=f"del_{idx}"):
                    full_path = os.path.join(os.path.dirname(__file__), book["path"])
                    if os.path.exists(full_path):
                        os.remove(full_path)
                    cfg["books"].pop(idx)
                    save_config(cfg)
                    st.rerun()


# ══════════════════════════════════════════════
# Tab 2: ページ選択・テキスト確認
# ══════════════════════════════════════════════
with tab_pages:
    st.header("📄 ページ選択・テキスト確認")

    cfg = load_config()

    if not cfg["books"]:
        st.warning("まず「⚙️ 設定」タブでPDFを登録してください。")
    else:
        book_names = [b["name"] for b in cfg["books"]]
        selected_name = st.selectbox("本を選択", book_names, key="book_select")
        selected_book = next(b for b in cfg["books"] if b["name"] == selected_name)
        total_pages = selected_book["total_pages"]

        st.caption(f"総ページ数: {total_pages}ページ")

        col_start, col_end = st.columns(2)
        with col_start:
            start_page = st.number_input(
                "開始ページ（本のページ番号）",
                min_value=1,
                max_value=total_pages,
                value=1,
                key="start_page",
            )
        with col_end:
            end_page = st.number_input(
                "終了ページ（本のページ番号）",
                min_value=1,
                max_value=total_pages,
                value=min(4, total_pages),
                key="end_page",
            )

        if end_page < start_page:
            st.error("終了ページは開始ページ以上にしてください。")
        else:
            if st.button("テキストを抽出", type="primary"):
                pdf_full_path = os.path.join(os.path.dirname(__file__), selected_book["path"])
                if not os.path.exists(pdf_full_path):
                    st.error("PDFファイルが見つかりません。再登録してください。")
                else:
                    with st.spinner("テキストを抽出中..."):
                        text = extract_text(pdf_full_path, int(start_page), int(end_page))
                    st.session_state.extracted_text = text
                    st.session_state.translation_results = []
                    st.success(f"ページ {start_page}〜{end_page} のテキストを抽出しました。")

            if st.session_state.extracted_text:
                st.subheader("抽出テキストの確認・編集")
                st.caption("PDFのレイアウトによってはノイズが入ることがあります。不要な文字列は削除してから台本を作成してください。")
                edited_text = st.text_area(
                    "テキスト",
                    value=st.session_state.extracted_text,
                    height=400,
                    key="text_area",
                    label_visibility="collapsed",
                )
                st.session_state.extracted_text = edited_text

                sentences = split_sentences(edited_text)
                st.info(f"検出された文の数: {len(sentences)}文")

                # API キー確認
                cfg = load_config()
                has_gemini = bool(cfg.get("gemini_api_key"))
                has_deepl = bool(cfg.get("deepl_api_key"))

                col_use_gemini, col_use_deepl = st.columns(2)
                with col_use_gemini:
                    use_gemini = st.checkbox(
                        "🤖 Gemini で翻訳（英語語順・文節訳）",
                        value=has_gemini,
                        disabled=not has_gemini,
                        key="use_gemini",
                    )
                    if not has_gemini:
                        st.caption("「設定」タブで Gemini API キーを登録してください。")
                with col_use_deepl:
                    use_deepl = st.checkbox(
                        "📝 DeepL で翻訳（参考訳）",
                        value=has_deepl,
                        disabled=not has_deepl,
                        key="use_deepl",
                    )
                    if not has_deepl:
                        st.caption("「設定」タブで DeepL API キーを登録してください。")

                if not use_gemini and not use_deepl:
                    st.warning("少なくとも1つの翻訳サービスを選択してください。")
                elif st.button("🚀 台本を作成する", type="primary", disabled=(not sentences)):
                    results = []
                    progress = st.progress(0, text="翻訳中...")
                    for i, sentence in enumerate(sentences):
                        row = {"sentence": sentence, "gemini": "", "deepl": ""}
                        if use_gemini:
                            row["gemini"] = translate_gemini(sentence, cfg["gemini_api_key"])
                            time.sleep(0.3)  # レート制限を避けるための待機
                        if use_deepl:
                            row["deepl"] = translate_deepl(sentence, cfg["deepl_api_key"])
                        results.append(row)
                        progress.progress((i + 1) / len(sentences), text=f"翻訳中... {i+1}/{len(sentences)}")
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
        # ダウンロードボタン
        script_text = build_script_text(results)
        st.download_button(
            label="📥 台本をテキストファイルでダウンロード",
            data=script_text.encode("utf-8"),
            file_name="rindokukai_script.txt",
            mime="text/plain",
        )

        st.divider()

        for i, r in enumerate(results, 1):
            with st.container(border=True):
                st.markdown(f"**【{i}】** {r['sentence']}")
                if r.get("gemini"):
                    st.markdown("🤖 **Gemini（英語語順訳）**")
                    # ／区切りを視覚的に見やすくする
                    parts = r["gemini"].split("／")
                    formatted = "　　**／** ".join(p.strip() for p in parts if p.strip())
                    st.markdown(f"> {formatted}")
                if r.get("deepl"):
                    st.markdown("📝 **DeepL（参考訳）**")
                    st.markdown(f"> {r['deepl']}")
