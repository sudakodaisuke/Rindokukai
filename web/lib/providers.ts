export class ProviderError extends Error { constructor(message: string, public status = 502) { super(message); } }
export function validateOrigin(request: Request) {
  const origin = request.headers.get('origin');
  const expected = new URL(request.url).origin;
  if (origin && origin !== expected) throw new ProviderError('このサイトからリクエストしてください。', 403);
}
export async function readBody(request: Request) {
  const body = await request.text();
  if (body.length > 3_000_000) throw new ProviderError('送信データが大きすぎます。', 413);
  try { return JSON.parse(body); } catch { throw new ProviderError('入力形式が正しくありません。', 400); }
}
export function key(value: unknown, provider: string) {
  if (typeof value !== 'string' || !value.trim() || value.length > 500 || /[\r\n]/.test(value)) throw new ProviderError(`${provider}のAPIキーを設定してください。`, 400);
  return value.trim();
}
export async function gemini(apiKey: string, model: string, parts: unknown[], json = false) {
  if (!/^gemini-[a-zA-Z0-9.-]{1,80}$/.test(model)) throw new ProviderError('モデル名を確認してください。', 400);
  const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey }, body: JSON.stringify({ contents: [{ role: 'user', parts }], generationConfig: { temperature: 0.15, ...(json ? { responseMimeType: 'application/json' } : {}) } }), signal: AbortSignal.timeout(100_000), cache: 'no-store' });
  if (!res.ok) throw new ProviderError(res.status === 429 ? 'Geminiの利用上限に達しました。少し待ってから再実行してください。' : res.status === 400 || res.status === 401 || res.status === 403 ? 'GeminiのAPIキー、モデル名、利用権限を確認してください。' : 'Geminiに接続できませんでした。再実行してください。', res.status === 429 ? 429 : 502);
  const data = await res.json();
  const text = data.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text || '').join('');
  if (!text) throw new ProviderError('Geminiから結果を取得できませんでした。原文を確認してください。');
  return text as string;
}
export async function deepl(apiKey: string, sentences: string[]) {
  const host = apiKey.endsWith(':fx') ? 'api-free.deepl.com' : 'api.deepl.com';
  const res = await fetch(`https://${host}/v2/translate`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `DeepL-Auth-Key ${apiKey}` }, body: JSON.stringify({ text: sentences, source_lang: 'EN', target_lang: 'JA' }), signal: AbortSignal.timeout(60_000), cache: 'no-store' });
  if (!res.ok) throw new ProviderError(res.status === 429 || res.status === 456 ? 'DeepLの利用上限に達しました。利用枠を確認してください。' : 'DeepLのAPIキーまたは接続を確認してください。', res.status === 429 ? 429 : 502);
  const data = await res.json();
  if (!Array.isArray(data.translations) || data.translations.length !== sentences.length || data.translations.some((t: { text?: string }) => typeof t.text !== 'string' || !t.text)) throw new ProviderError('DeepLの翻訳結果が不足しています。再実行してください。');
  return data.translations.map((t: { text: string }) => t.text) as string[];
}
export function errorResponse(error: unknown) {
  const known = error instanceof ProviderError;
  return Response.json({ error: known ? error.message : '処理に失敗しました。時間をおいて再実行してください。' }, { status: known ? error.status : 502, headers: { 'Cache-Control': 'no-store' } });
}
