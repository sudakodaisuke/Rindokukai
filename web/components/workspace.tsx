'use client';

import { useEffect, useRef, useState, useMemo, useId } from 'react';
import { ArrowDownToLine, ArrowRight, BookOpen, Check, CheckCheck, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Copy, FileText, FolderOpen, GraduationCap, LayoutGrid, LoaderCircle, Plus, Printer, RotateCcw, Settings2, Sparkles, Square, Upload, X } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { exportScript, MODELS, sampleRows, sampleText, splitSentences, type Mode, type Sentence } from '../lib/script';

type Saved = { id: string; title: string; rows: Sentence[]; text: string; figures: string; date: string };
const storageKey = 'rindoku-notes-v1';
const handbook = 'https://media.githubusercontent.com/media/sudakodaisuke/Rindokukai/claude/translation-prep-app-EscKN/books/Handbook%20-of-pharmaceutical-granulation-technology.pdf';
function download(content: string, name: string, type = 'text/plain;charset=utf-8') { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} aria-labelledby={headingId} className="modal" onCancel={close} onClick={e => { if (e.target === e.currentTarget) close(); }}><div className="modal-head"><h2 id={headingId}>{title}</h2><button className="icon-button" aria-label="閉じる" onClick={close}><X size={20} /></button></div>{children}</dialog>;
}

export default function Workspace() {
  const [view, setView] = useState<'workspace' | 'saved'>('workspace');
  const [modal, setModal] = useState<'settings' | 'help' | null>(null);
  const [title, setTitle] = useState('新しい輪読ノート');
  const [text, setText] = useState(sampleText);
  const [rows, setRows] = useState<Sentence[]>(sampleRows);
  const [isSample, setIsSample] = useState(true);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [noteId, setNoteId] = useState<string | null>(null);
  const [geminiKey, setGeminiKey] = useState('');
  const [deeplKey, setDeeplKey] = useState('');
  const [model, setModel] = useState(MODELS[0]);
  const [mode, setMode] = useState<Mode>('gemini');
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);
  const [fileName, setFileName] = useState('');
  const [start, setStart] = useState(1);
  const [end, setEnd] = useState(1);
  const [page, setPage] = useState(1);
  const [leftTab, setLeftTab] = useState<'pdf' | 'text'>('pdf');
  const [busy, setBusy] = useState('');
  const [translating, setTranslating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [figures, setFigures] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [scriptFilter, setScriptFilter] = useState<'all' | 'unchecked'>('all');
  const [dragOver, setDragOver] = useState(false);
  const [storageReady, setStorageReady] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const sentences = useMemo(() => splitSentences(text), [text]);
  const checked = rows.filter(r => r.checked).length;
  const visibleRows = rows.filter(r => scriptFilter === 'all' || !r.checked);

  useEffect(() => {
    try {
      const notes = JSON.parse(localStorage.getItem(storageKey) || '[]');
      if (Array.isArray(notes)) setSaved(notes.filter(validNote));
      const draft = JSON.parse(localStorage.getItem('rindoku-draft-v1') || 'null');
      if (draft && validNote(draft)) { setTitle(draft.title); setText(draft.text); setRows(draft.rows); setFigures(draft.figures || ''); setIsSample(false); setLeftTab('text'); setNoteId(draft.id === 'draft' ? null : draft.id); }
    } catch { setNotice('保存データを読み込めませんでした。新しいノートから始められます。'); }
    setStorageReady(true);
    return () => { controller.current?.abort(); void pdfRef.current?.destroy(); };
  }, []);
  useEffect(() => {
    if (!storageReady || isSample) return;
    const timer = setTimeout(() => {
      try { localStorage.setItem('rindoku-draft-v1', JSON.stringify({ id: noteId || 'draft', title, text, rows, figures, date: '' })); } catch { setError('ブラウザに保存できません。台本をダウンロードしてください。'); }
    }, 600);
    return () => clearTimeout(timer);
  }, [title, text, rows, figures, storageReady, isSample, noteId]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(timer); }, [notice]);
  useEffect(() => {
    if (!pdf || leftTab !== 'pdf' || view !== 'workspace') return;
    let cancelled = false;
    let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    (async () => {
      try {
        const p = await pdf.getPage(page);
        if (cancelled || !canvas.current) return;
        const viewport = p.getViewport({ scale: 1.4 });
        const target = canvas.current;
        target.width = viewport.width; target.height = viewport.height;
        task = p.render({ canvas: target, viewport }); await task.promise;
      } catch (err) { if (!cancelled && (err as Error).name !== 'RenderingCancelledException') setError('ページを表示できませんでした。別のページを選んでください。'); }
    })();
    return () => { cancelled = true; task?.cancel(); };
  }, [pdf, page, leftTab, view]);

  function validNote(note: unknown): note is Saved {
    if (!note || typeof note !== 'object') return false;
    const n = note as Saved;
    return typeof n.id === 'string' && typeof n.title === 'string' && typeof n.text === 'string' && typeof n.date === 'string' && Array.isArray(n.rows) && n.rows.length <= 1000 && n.rows.every(r => typeof r.id === 'string' && typeof r.source === 'string' && typeof r.english === 'string' && typeof r.japanese === 'string' && typeof r.note === 'string' && typeof r.checked === 'boolean' && (r.reference === undefined || typeof r.reference === 'string') && (r.error === undefined || typeof r.error === 'string')) && (n.figures === undefined || typeof n.figures === 'string');
  }
  async function openPdf(file: File | string) {
    if (busy || translating) return;
    setBusy('PDFを読み込んでいます…'); setError('');
    try {
      const name = typeof file === 'string' ? 'Handbook of Pharmaceutical Granulation Technology.pdf' : file.name;
      if (typeof file !== 'string' && (file.size > 150 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.pdf'))) throw new Error('150MB以下のPDFを選んでください。');
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
      const document = await pdfjs.getDocument(typeof file === 'string' ? { url: file, cMapUrl: '/cmaps/', cMapPacked: true, standardFontDataUrl: '/standard_fonts/', wasmUrl: '/wasm/' } : { data: new Uint8Array(await file.arrayBuffer()), cMapUrl: '/cmaps/', cMapPacked: true, standardFontDataUrl: '/standard_fonts/', wasmUrl: '/wasm/' }).promise;
      await pdfRef.current?.destroy(); pdfRef.current = document; setPdf(document); setFileName(name); setStart(1); setEnd(1); setPage(1); setLeftTab('pdf'); setIsSample(false); setRows([]); setText(''); setFigures(''); setTitle(name.replace(/\.pdf$/i, '')); setNoteId(null);
    } catch (err) { setError((err as Error).name === 'PasswordException' ? 'パスワード付きPDFは、解除してから読み込んでください。' : typeof file === 'string' ? 'ハンドブックを読み込めませんでした。PDFをダウンロードしてアップロードしてください。' : `PDFを読み込めませんでした。${(err as Error).message}`); }
    finally { setBusy(''); if (fileInput.current) fileInput.current.value = ''; }
  }
  async function extract() {
    if (!pdf) return;
    if (end < start || end - start > 29) { setError('開始ページ以降の、30ページ以内の範囲を選んでください。'); return; }
    setBusy('本文を抽出しています…'); setError('');
    try {
      const parts: string[] = [];
      for (let n = start; n <= end; n++) {
        const page = await pdf.getPage(n); const content = await page.getTextContent();
        parts.push(content.items.map(item => 'str' in item ? item.str + (item.hasEOL ? '\n' : ' ') : '').join(''));
      }
      const extracted = parts.join('\n\n').trim();
      if (!extracted) throw new Error('本文を抽出できませんでした。画像のみのPDFは、文字認識したPDFをご利用ください。');
      setText(extracted); setRows([]); setFigures(''); setLeftTab('text'); setNotice(`${start}〜${end}ページの本文を抽出しました。`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(''); }
  }
  function needsKeys(figure = false) {
    const missing = (figure || mode !== 'deepl') && !geminiKey.trim() || !figure && mode !== 'gemini' && !deeplKey.trim();
    if (missing) { setModal('settings'); setError('選択した翻訳方法に必要なAPIキーを入力してください。'); }
    return missing;
  }
  async function translate(retryIds?: string[]) {
    if (needsKeys()) return;
    const initial = retryIds ? rows : sentences.map((source, i) => ({ id: `${Date.now()}-${i}`, source, english: source, japanese: '', note: '', checked: false }));
    if (!initial.length) { setError('先に本文を入力するか、PDFから抽出してください。'); return; }
    if (initial.length > 500 || initial.some(r => r.source.length > 8000)) { setError('500文以内に分け、1文を8,000文字以内にしてください。'); return; }
    const ids = retryIds || initial.map(r => r.id);
    setRows(initial); setIsSample(false); setTranslating(true); setProgress(0); setError(''); setScriptFilter('all');
    const abort = new AbortController(); controller.current = abort;
    let done = 0;
    try {
      for (let i = 0; i < ids.length;) {
        const batch: Sentence[] = []; let size = 0;
        while (i < ids.length && batch.length < 6) { const r = initial.find(r => r.id === ids[i])!; if (batch.length && size + r.source.length > 16000) break; batch.push(r); size += r.source.length; i++; }
        try {
          const response = await fetch('/api/translate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sentences: batch.map(r => r.source), mode, geminiKey, deeplKey, model }), signal: abort.signal });
          const data = await response.json(); if (!response.ok) throw new Error(data.error || '翻訳に失敗しました。');
          setRows(prev => prev.map(r => { const index = batch.findIndex(b => b.id === r.id); return index < 0 ? r : { ...r, ...data.rows[index], error: undefined }; }));
        } catch (err) {
          if (abort.signal.aborted) throw err;
          setRows(prev => prev.map(r => batch.some(b => b.id === r.id) ? { ...r, error: (err as Error).message } : r));
          setError((err as Error).message);
          if (i < ids.length) { const rest = ids.slice(i); setRows(prev => prev.map(r => rest.includes(r.id) ? { ...r, error: '処理を中断しました。再実行できます。' } : r)); }
          break;
        }
        done += batch.length; setProgress(Math.round(done / ids.length * 100));
      }
      if (done === ids.length) setNotice('台本ができました。訳文を確認して、メモを添えましょう。');
    } catch {
      setRows(prev => prev.map(r => ids.includes(r.id) && !r.japanese ? { ...r, error: '処理を中断しました。再実行できます。' } : r)); setNotice('翻訳を停止しました。完了した結果は残っています。');
    } finally { setTranslating(false); controller.current = null; }
  }
  async function readFigures() {
    if (!pdf || needsKeys(true)) return;
    setBusy('このページの図・数式を読み取っています…'); setError('');
    try {
      const p = await pdf.getPage(page); const c = document.createElement('canvas'); const viewport = p.getViewport({ scale: 1.3 }); c.width = viewport.width; c.height = viewport.height; await p.render({ canvas: c, viewport }).promise;
      const response = await fetch('/api/figures', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: c.toDataURL('image/jpeg', 0.8).split(',')[1], geminiKey, model }) }); const data = await response.json();
      if (!response.ok) throw new Error(data.error); setFigures(prev => `${prev ? prev + "\n\n" : ""}p. ${page}\n${data.text}`); setNotice('図表の読み取り結果を台本の下に追加しました。');
    } catch (err) { setError((err as Error).message); } finally { setBusy(''); }
  }
  function editRow(id: string, patch: Partial<Sentence>) { setRows(prev => prev.map(r => r.id === id ? { ...r, ...patch } : r)); setIsSample(false); }
  function saveNote() {
    const note: Saved = { id: noteId || crypto.randomUUID(), title, text, rows, figures, date: new Date().toISOString() }; const next = [note, ...saved.filter(n => n.id !== note.id)];
    try { localStorage.setItem(storageKey, JSON.stringify(next)); localStorage.setItem("rindoku-draft-v1", JSON.stringify(note)); setSaved(next); setNoteId(note.id); setIsSample(false); setNotice('このブラウザにノートを保存しました。'); } catch { setError('保存できません。台本をダウンロードしてください。'); }
  }
  function openNote(note: Saved) { setTitle(note.title); setText(note.text); setRows(note.rows); setFigures(note.figures || ''); setNoteId(note.id); setIsSample(false); setView('workspace'); setLeftTab('text'); setScriptFilter('all'); void pdfRef.current?.destroy(); pdfRef.current = null; setPdf(null); setFileName(''); }
  function newNote() { if (translating || busy) return; setNoteId(null); setTitle('新しい輪読ノート'); setText(''); setRows([]); setFigures(''); setIsSample(false); setView('workspace'); setLeftTab('pdf'); setFileName(''); void pdfRef.current?.destroy(); pdfRef.current = null; setPdf(null); setError(''); }
  async function importNote(file?: File) { if (!file) return; try { if (file.size > 5_000_000) throw new Error(); const note = JSON.parse(await file.text()); if (!validNote(note)) throw new Error(); openNote(note); setNotice('ノートを読み込みました。「ノートを保存」で保存できます。'); } catch { setError('有効な輪読ノートのJSONファイルを選んでください。'); } finally { if (importInput.current) importInput.current.value = ''; } }

  return <div className="app-shell">
    <aside className="sidebar no-print">
      <a className="brand" href="/" aria-label="輪読ノート ホーム"><span className="brand-mark"><BookOpen size={21} strokeWidth={1.6} /></span><span>輪読ノート<span className="brand-sub">RINDOKU NOTE</span></span></a>
      <div className="sidebar-label">WORKSPACE</div>
      <nav aria-label="メインメニュー"><button className={view === 'workspace' ? 'nav-item active' : 'nav-item'} onClick={() => setView('workspace')}><LayoutGrid size={18} />輪読の準備<span className="nav-dot" /></button><button disabled={translating || !!busy} className={view === 'saved' ? 'nav-item active' : 'nav-item'} onClick={() => setView('saved')}><FolderOpen size={18} />保存したノート<span className="count">{saved.length}</span></button></nav>
      <button className="new-note" onClick={newNote} disabled={translating || !!busy}><Plus size={17} />新しいノート</button>
      <div className="sidebar-bottom"><div className="tip-card"><span className="tip-icon"><GraduationCap size={19} /></span><p>英文を、前から理解する。</p><span>文節ごとの対訳で、<br />輪読会の準備をスムーズに。</span><button onClick={() => setModal('help')}>使い方を見る<ArrowRight size={14} /></button></div><button className="nav-item" onClick={() => setModal('settings')}><Settings2 size={18} />翻訳の設定<span className={geminiKey || deeplKey ? 'status-dot ready' : 'status-dot'} /></button><div className="sidebar-foot"><span className="tiny-book">R</span><span>あなたの読む時間に、余白を。<small>輪読会準備ワークスペース</small></span></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar no-print"><div className="breadcrumb">ワークスペース<ChevronRight size={13} /><strong>{view === 'workspace' ? '輪読の準備' : '保存したノート'}</strong></div><div className="topbar-actions"><span className="local-status"><span />ブラウザ内に保存</span><button className="icon-button" aria-label="使い方" onClick={() => setModal('help')}><CircleHelp size={19} /></button><span className="avatar">読</span></div></header>
      <main>
        <div className="page-heading no-print"><div><div className="eyebrow">A LITTLE PREPARATION, A DEEPER UNDERSTANDING.</div><h1>{view === 'workspace' ? '輪読の準備' : '保存したノート'}<span className="heading-dot">.</span></h1><p>{view === 'workspace' ? '英文を読み解く準備を、ひとつの場所で。' : '読み進めたこと、考えたこと。いつでも続きを。'}</p></div><button className="button subtle" onClick={() => setModal('help')}><BookOpen size={16} />使い方ガイド<ArrowUpRight /></button></div>
        {error && <div className="error-banner no-print" role="alert"><span>{error}</span><button className="icon-button" aria-label="エラーを閉じる" onClick={() => setError('')}><X size={16} /></button></div>}
        {view === 'saved' ? <section className="saved-section"><div className="section-title"><h2>あなたのノート <span>{saved.length}</span></h2><div className="actions"><button className="button" onClick={() => importInput.current?.click()}><Upload size={15} />読み込む</button><button className="button primary" onClick={newNote}><Plus size={16} />新しいノート</button></div></div>{saved.length ? <div className="saved-grid">{saved.map(note => <article className="saved-card" key={note.id}><BookOpen size={23} /><h3>{note.title}</h3><p>{note.rows.length}文 · {note.rows.filter(r => r.checked).length}文を確認済み</p><span>{new Date(note.date).toLocaleDateString('ja-JP')}</span><div className="actions"><button className="button primary" onClick={() => openNote(note)}>続きを開く<ArrowRight size={14} /></button><button className="button" onClick={() => download(JSON.stringify(note, null, 2), `${note.title}.json`, 'application/json')}>書き出す</button></div></article>)}</div> : <div className="saved-empty"><FolderOpen size={36} /><h3>ノートをここに残しましょう。</h3><p>台本を作成して「ノートを保存」を押すと、ここに並びます。</p><button className="button primary" onClick={newNote}>輪読の準備を始める<ArrowRight size={16} /></button></div>}<p className="storage-note">ノートはこの端末・ブラウザに保存されます。別の端末へ移す場合はJSONを書き出してください。</p></section> : <>
          <section className="workflow no-print" aria-label="準備の流れ"><div className={`workflow-step ${pdf || !isSample && text ? 'complete' : 'current'}`}><span className="step-number">{pdf ? <Check size={14} /> : '01'}</span><div><strong>担当ページを選ぶ</strong><small>PDFを読み込んで範囲を指定</small></div></div><span className="step-line" /><div className={`workflow-step ${text && !isSample ? 'current' : ''}`}><span className="step-number">02</span><div><strong>原文を確認する</strong><small>抽出した英文を整える</small></div></div><span className="step-line" /><div className={`workflow-step ${rows.length && !isSample ? 'current' : ''}`}><span className="step-number">03</span><div><strong>台本をつくる</strong><small>対訳とメモで理解を深める</small></div></div><span className="workflow-decoration"><Sparkles size={21} strokeWidth={1.3} /></span></section>
          <div className="document-bar"><div className="document-name"><span className="document-icon"><BookOpen size={17} /></span><input aria-label="ノートのタイトル" value={title} onChange={e => { setTitle(e.target.value); setIsSample(false); }} maxLength={150} /><span className="draft-badge">{isSample ? 'サンプル' : '下書き'}</span></div><button className="button no-print" onClick={saveNote} disabled={translating || !!busy}><FolderOpen size={15} />ノートを保存</button></div>
          <div className="workspace-grid">
            <section className="source-panel panel no-print"><div className="panel-heading"><div className="panel-title"><FileText size={17} /><h2>原文・ページ</h2></div><span className="panel-kicker">SOURCE</span></div><div className="source-tabs"><button className={leftTab === 'pdf' ? 'selected' : ''} onClick={() => setLeftTab('pdf')}>PDFプレビュー</button><button className={leftTab === 'text' ? 'selected' : ''} onClick={() => setLeftTab('text')}>抽出テキスト{text && <span>{sentences.length}</span>}</button></div>
              {leftTab === 'pdf' ? pdf ? <><div className="pdf-meta"><FileText size={15} /><span title={fileName}>{fileName}</span><button className="icon-button" aria-label="PDFを変更" onClick={() => fileInput.current?.click()} disabled={translating || !!busy}><Upload size={15} /></button></div><div className="page-range"><label>担当ページ<span className="page-total">全{pdf.numPages}ページ</span></label><div className="range-inputs"><label className="sr-only" htmlFor="page-start">開始ページ</label><input id="page-start" type="number" min={1} max={pdf.numPages} value={start} disabled={translating || !!busy} onChange={e => { const n = Math.max(1, Math.min(pdf.numPages, Number(e.target.value) || 1)); setStart(n); setEnd(prev => Math.max(n, prev)); setPage(n); }} /><span>—</span><label className="sr-only" htmlFor="page-end">終了ページ</label><input id="page-end" type="number" min={start} max={pdf.numPages} value={end} disabled={translating || !!busy} onChange={e => setEnd(Math.max(start, Math.min(pdf.numPages, Number(e.target.value) || start)))} /><span className="range-size">{end - start + 1}ページ</span></div></div><div className="pdf-canvas-wrap"><canvas ref={canvas} aria-label={`PDF ${page}ページのプレビュー`} /></div><div className="pdf-navigation"><button className="icon-button" aria-label="前のページ" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={18} /></button><span>{page} / {pdf.numPages}</span><button className="icon-button" aria-label="次のページ" disabled={page >= pdf.numPages} onClick={() => setPage(p => p + 1)}><ChevronRight size={18} /></button></div><div className="source-actions"><button className="button primary full" onClick={extract} disabled={!!busy || translating}><FileText size={16} />本文を抽出する<ArrowRight size={16} /></button><button className="button full" onClick={readFigures} disabled={!!busy || translating}><Sparkles size={15} />表示ページの図・数式を読む</button></div></> : <div className="upload-section"><div className={`dropzone ${dragOver ? 'dragover' : ''}`} onDragOver={e => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={e => { e.preventDefault(); setDragOver(false); const file = e.dataTransfer.files[0]; if (file) void openPdf(file); }}><div className="upload-art"><span className="paper-back" /><span className="paper-front"><FileText size={29} strokeWidth={1.3} /><i /><i /><i /></span><span className="upload-bubble"><Upload size={16} /></span></div><h3>ここから、読み始めよう。</h3><p>担当のPDFをドラッグ＆ドロップ<br />またはファイルを選択してください。</p><button className="button primary" disabled={!!busy || translating} onClick={() => fileInput.current?.click()}><Plus size={16} />PDFを選択</button><small>PDF形式 · 150MBまで</small></div><div className="privacy-note"><span className="little-dot" />PDFはブラウザ内で読み込みます。</div><div className="or-divider"><span />または<span /></div><button className="library-book" onClick={() => void openPdf(handbook)} disabled={!!busy || translating}><span className="book-cover">HANDBOOK<br /><strong>Pharmaceutical<br />Granulation<br />Technology</strong><i /></span><span className="library-info"><span>元のハンドブック</span><strong>Pharmaceutical<br />Granulation Technology</strong><small>PDF · 約92MB<ArrowRight size={14} /></small></span></button><a className="book-download" href={handbook} target="_blank" rel="noreferrer">PDFを別タブで開く<ArrowUpRight /></a></div> : <div className="text-editor"><div className="editor-note"><span className="little-dot" />ヘッダーや不要な改行を整えましょう。</div><textarea aria-label="原文テキスト" value={text} onChange={e => { setText(e.target.value); setIsSample(false); }} disabled={translating || !!busy} placeholder="英文を貼り付けるか、PDFから本文を抽出してください。" /><div className="text-stats"><span>{sentences.length}文</span><span>{text.length.toLocaleString()}文字</span></div></div>}
              {busy && <div className="busy-status" role="status"><LoaderCircle size={16} className="spin" />{busy}</div>}
              <div className="translate-controls"><label htmlFor="mode">翻訳方法<button className="text-button" onClick={() => setModal('settings')}><Settings2 size={13} />設定</button></label><div className="select-wrap"><select id="mode" value={mode} disabled={translating || !!busy} onChange={e => setMode(e.target.value as Mode)}><option value="gemini">Gemini · 英語語順で訳す</option><option value="deepl">DeepL · 自然な日本語で訳す</option><option value="reorder">DeepL → Gemini · 語順を整える</option></select><ChevronDown size={15} /></div>{translating ? <><button className="button primary full" onClick={() => controller.current?.abort()}><Square size={13} />翻訳を停止する<span>{progress}%</span></button><div className="progress-bar"><span style={{ width: `${progress}%` }} /></div></> : <button className="button primary full generate" disabled={!text.trim() || !!busy} onClick={() => void translate()}><Sparkles size={16} />台本を作成する<ArrowRight size={16} /></button>}<small>原文は選択した翻訳サービスに送信されます。</small></div>
            </section>
            <section className="script-panel panel"><div className="panel-heading"><div className="panel-title"><BookOpen size={18} /><h2>輪読台本</h2><span className="count">{rows.length}</span></div><div className="actions no-print"><button className="icon-button" title="全文をコピー" aria-label="全文をコピー" disabled={!rows.length || translating} onClick={async () => { try { await navigator.clipboard.writeText(exportScript(title, rows, figures)); setNotice('台本をコピーしました。'); } catch { setError('コピーできませんでした。ダウンロードをご利用ください。'); } }}><Copy size={16} /></button><button className="icon-button" title="印刷 / PDF保存" aria-label="印刷 / PDF保存" disabled={!rows.length || translating} onClick={() => window.print()}><Printer size={16} /></button><button className="button export-button" disabled={!rows.length || translating} onClick={() => download(exportScript(title, rows, figures), `${title || '輪読台本'}.txt`)}><ArrowDownToLine size={15} />書き出す</button></div></div>
              <div className="script-toolbar no-print"><div className="script-filters"><button className={scriptFilter === 'all' ? 'selected' : ''} onClick={() => setScriptFilter('all')}>すべての文</button><button className={scriptFilter === 'unchecked' ? 'selected' : ''} onClick={() => setScriptFilter('unchecked')}>未確認<span>{rows.length - checked}</span></button></div><span className="checked-count"><CheckCheck size={14} />{checked} / {rows.length} 確認済み</span></div>
              {isSample && <div className="sample-banner no-print"><Sparkles size={15} /><span>台本のサンプルです。PDFを選んで、あなたの台本を。</span></div>}
              {rows.some(r => r.error) && <div className="retry-banner no-print"><span>{rows.filter(r => r.error).length}文で翻訳が完了していません。</span><button className="text-button" disabled={translating || !!busy} onClick={() => void translate(rows.filter(r => r.error).map(r => r.id))}><RotateCcw size={14} />失敗した文を再実行</button></div>}
              <div className="sentences">{!rows.length ? <div className="script-empty"><span><BookOpen size={31} strokeWidth={1.2} /></span><h3>読む準備が、ここに整います。</h3><p>原文を確認して「台本を作成する」を押すと、<br />英語と日本語の対訳が並びます。</p><button className="button" disabled={!!busy || translating} onClick={() => { setRows(sampleRows); setText(sampleText); setIsSample(true); setLeftTab('text'); }}>サンプルを試す<ArrowRight size={14} /></button></div> : !visibleRows.length ? <div className="script-empty"><CheckCheck size={30} /><h3>すべての文を確認しました。</h3><p>輪読会の準備が一歩進みました。</p></div> : visibleRows.map(row => <article key={row.id} className={`sentence-card ${row.checked ? 'is-checked' : ''}`}><div className="sentence-top"><span className="sentence-number">{String(rows.findIndex(r => r.id === row.id) + 1).padStart(2, '0')}</span><span className="sentence-label">{row.error ? '翻訳を確認してください' : mode === 'deepl' && !isSample ? '自然な日本語訳' : '英語の語順で読む'}</span><label className="check-label no-print"><input type="checkbox" checked={row.checked} disabled={translating} onChange={e => editRow(row.id, { checked: e.target.checked })} /><span><Check size={11} /></span>確認済み</label></div><div className="sentence-content"><div className="language-tag">EN</div><p className="english">{row.english.split('／').map((part, index) => <span key={index}>{index > 0 && <em> / </em>}{part.trim()}</span>)}</p><div className="language-tag japanese-tag">JP</div><div className="japanese">{row.japanese ? <><textarea aria-label={`第${rows.findIndex(r => r.id === row.id) + 1}文の日本語訳`} value={row.japanese} onChange={e => editRow(row.id, { japanese: e.target.value, checked: false })} disabled={translating} rows={Math.max(2, Math.ceil(row.japanese.length / 35))} /><p className="print-only printed-translation">{row.japanese}</p></> : row.error ? <p className="row-error">{row.error}</p> : <span className="pending"><LoaderCircle size={13} className={translating ? 'spin' : ''} />{translating ? '翻訳を待っています…' : '翻訳はまだありません'}</span>}</div></div>{row.reference && <details className="reference"><summary>DeepLの参考訳</summary><p>{row.reference}</p></details>}<div className="sentence-note"><Plus size={13} /><input aria-label={`第${rows.findIndex(r => r.id === row.id) + 1}文のメモ`} placeholder="気づいたこと、輪読会で聞きたいことをメモ…" value={row.note} onChange={e => editRow(row.id, { note: e.target.value })} /></div></article>)}</div>
              {figures && <div className="figures"><h3><Sparkles size={17} />図・数式の読み取り</h3><textarea aria-label="図表・数式の読み取り結果" value={figures} onChange={e => setFigures(e.target.value)} rows={10} /><p className="print-only printed-translation">{figures}</p></div>}
              <div className="script-footer no-print"><span><span className="little-dot" />訳文はクリックして編集できます。</span><span>READ. THINK. SHARE.</span></div>
            </section>
          </div><div className="workspace-footer no-print"><span>急がず、一文ずつ。理解を重ねていこう。</span><span>輪読ノート <span className="footer-star">✳</span></span></div>
        </>}
      </main>
    </div>
    <input ref={fileInput} type="file" accept="application/pdf,.pdf" className="hidden" onChange={e => { const file = e.target.files?.[0]; if (file) void openPdf(file); }} /><input ref={importInput} type="file" accept="application/json,.json" className="hidden" onChange={e => void importNote(e.target.files?.[0])} />
    {notice && <div className="toast no-print" role="status"><Check size={17} />{notice}</div>}
    {modal === 'settings' && <Modal title="翻訳の設定" close={() => setModal(null)}><p className="modal-description">使いたい翻訳サービスのAPIキーを入力してください。キーはこの画面を開いている間だけ保持し、ノートには保存しません。</p><label className="setting-field">Gemini APIキー<input type="password" autoComplete="off" value={geminiKey} onChange={e => setGeminiKey(e.target.value)} placeholder="AIza…" /></label><a className="setting-link" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Google AI Studioでキーを取得<ArrowUpRight /></a><label className="setting-field">Geminiモデル<input value={model} onChange={e => setModel(e.target.value)} list="models" placeholder="gemini-3.1-flash-lite" /><datalist id="models">{MODELS.map(m => <option key={m} value={m} />)}</datalist></label><label className="setting-field">DeepL APIキー <span>DeepLを使う場合のみ</span><input type="password" autoComplete="off" value={deeplKey} onChange={e => setDeeplKey(e.target.value)} placeholder="xxxxxxxx:fx" /></label><a className="setting-link" href="https://www.deepl.com/ja/your-account/keys" target="_blank" rel="noreferrer">DeepLのAPIキーを確認<ArrowUpRight /></a><div className="settings-info">翻訳時は本文、図表の読み取り時は表示ページの画像を、選択したサービスに送信します。利用料金・上限は各サービスの契約に従います。</div><div className="modal-actions"><button className="button" onClick={() => { setGeminiKey(''); setDeeplKey(''); setNotice('APIキーを消去しました。'); }}>キーを消去</button><button className="button primary" onClick={() => { setModal(null); setError(''); setNotice('設定を適用しました。'); }}><Check size={16} />設定を適用</button></div></Modal>}
    {modal === 'help' && <Modal title="輪読ノートの使い方" close={() => setModal(null)}><p className="modal-description">英語の語順をたどりながら、一文ずつ理解するための輪読会準備ツールです。</p><ol className="help-steps"><li><span>01</span><div><strong>PDFを選んで、担当ページを指定。</strong><p>手元のPDFを読み込み、「本文を抽出する」を押します。ページ番号はPDFの先頭から数えた番号です。</p></div></li><li><span>02</span><div><strong>抽出した英文を確認。</strong><p>ヘッダーや不要な文字を編集してください。英文を直接貼り付けることもできます。画像だけのPDFは事前に文字認識が必要です。</p></div></li><li><span>03</span><div><strong>対訳を作って、自分の台本へ。</strong><p>翻訳の設定にAPIキーを入力し、台本を作成。訳文を編集し、メモ・確認マークを付けられます。訳文は原文と照らし合わせて確認してください。</p></div></li></ol><div className="settings-info">下書きは自動でこのブラウザに保存します。「ノートを保存」で一覧に残せます。テキストの書き出し、印刷からPDF保存、JSONでの別端末への移動にも対応しています。</div><button className="button primary full" onClick={() => setModal(null)}>準備を始める<ArrowRight size={16} /></button></Modal>}
  </div>;
}
function ArrowUpRight() { return <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 12 12 4M4 4h8v8" stroke="currentColor" strokeWidth="1.4" /></svg>; }
