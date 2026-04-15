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


def load_api_keys() -> dict:
    """APIキーをセッション → config.json（ローカルのみ）の順で読み込む。"""
    keys = {"gemini_api_key": "", "deepl_api_key": ""}
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
    return keys


def save_api_keys(gemini_key: str, deepl_key: str) -> bool:
    """APIキーを保存する。
    - 常に: セッションステートに保存（ユーザーごとに独立・他のユーザーからは見えない）
    - ローカルのみ: config.json にも保存（次回起動時に再入力不要）
    """
    # セッションステートに保存（クラウド・ローカル共通・安全）
    st.session_state["gemini_api_key"] = gemini_key
    st.session_state["deepl_api_key"] = deepl_key
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
    # 置換を元に戻す
    result = []
    for s in sentences:
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

def translate_gemini(sentence: str, api_key: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(GEMINI_PROMPT.format(sentence=sentence))
        result = response.text.strip()
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


def translate_deepl_reorder(sentence: str, deepl_text: str, gemini_api_key: str) -> str:
    """DeepL訳をGeminiで英語語順・文節区切りに並び替える。"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
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

def build_script_text(results: list[dict]) -> str:
    lines = ["=" * 60, "輪読会 台本", "=" * 60, ""]
    for i, r in enumerate(results, 1):
        lines.append(f"【{i}】{r['sentence']}")
        lines.append("")
        if r.get("gemini"):
            lines.append("  🤖 Gemini（英語語順訳）:")
            lines.append(f"  {r['gemini']}")
        if r.get("deepl"):
            lines.append("  📝 DeepL（参考訳）:")
            lines.append(f"  {r['deepl']}")
        if r.get("deepl_reorder"):
            lines.append("  🔄 DeepL→Gemini並び替え:")
            lines.append(f"  {r['deepl_reorder']}")
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

    if st.button("APIキーを設定", type="primary"):
        new_gemini = gemini_input if gemini_input else keys["gemini_api_key"]
        new_deepl = deepl_input if deepl_input else keys["deepl_api_key"]
        saved_to_file = save_api_keys(new_gemini, new_deepl)
        if saved_to_file:
            st.success("✅ APIキーを保存しました。次回起動時も入力不要です。")
        else:
            st.success("✅ APIキーをこのセッションに設定しました。"
                       "（このタブを閉じるまで有効です。他のユーザーには見えません。）")

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

        # ── ページ範囲スライダー ──────────────
        st.markdown(f"**担当ページを選択**　（全 {total_pages} ページ）")
        page_range = st.slider(
            "担当ページ",
            min_value=1,
            max_value=total_pages,
            value=(1, min(4, total_pages)),
            key="page_range",
            label_visibility="collapsed",
        )
        start_page, end_page = page_range
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

        if st.button("テキストを抽出", type="primary"):
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
                    value=False,
                    disabled=not (gemini_key and deepl_key),
                    key="use_deepl_reorder",
                )
                if not (gemini_key and deepl_key):
                    st.caption("GeminiとDeepL両方のキーが必要です。")
                else:
                    st.caption("DeepL訳をGeminiで英語語順に並び替え")

            if not use_gemini and not use_deepl and not use_deepl_reorder:
                st.warning("少なくとも1つの翻訳方法を選択してください。")
            elif st.button("🚀 台本を作成する", type="primary", disabled=not sentences):
                results = []
                progress = st.progress(0, text="翻訳中...")
                for i, sentence in enumerate(sentences):
                    row = {"sentence": sentence, "gemini": "", "deepl": "", "deepl_reorder": ""}
                    deepl_text = ""
                    if use_deepl or use_deepl_reorder:
                        deepl_text = translate_deepl(sentence, deepl_key)
                        if use_deepl:
                            row["deepl"] = deepl_text
                    if use_gemini:
                        row["gemini"] = translate_gemini(sentence, gemini_key)
                        time.sleep(0.3)
                    if use_deepl_reorder and deepl_text:
                        row["deepl_reorder"] = translate_deepl_reorder(sentence, deepl_text, gemini_key)
                        time.sleep(0.3)
                    results.append(row)
                    progress.progress(
                        (i + 1) / len(sentences),
                        text=f"翻訳中... {i + 1}/{len(sentences)} 文",
                    )
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
        script_text = build_script_text(results)
        st.download_button(
            "📥 台本をテキストファイルでダウンロード",
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
                    parts = r["gemini"].split("／")
                    formatted = "　　**／** ".join(p.strip() for p in parts if p.strip())
                    st.markdown(f"> {formatted}")
                if r.get("deepl"):
                    st.markdown("📝 **DeepL（参考訳）**")
                    st.markdown(f"> {r['deepl']}")
                if r.get("deepl_reorder"):
                    st.markdown("🔄 **DeepL→Gemini並び替え**")
                    parts = r["deepl_reorder"].split("／")
                    formatted = "　　**／** ".join(p.strip() for p in parts if p.strip())
                    st.markdown(f"> {formatted}")
