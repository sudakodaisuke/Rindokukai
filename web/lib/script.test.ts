import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitSentences, exportScript, sampleRows } from './script';
import { POST } from '../app/api/translate/route';

test('sentence splitting preserves abbreviations, decimals and PDF hyphenation', () => {
  assert.deepEqual(splitSentences('Dr. Smith used Fig. 3 at 2.5 mg. The gran-\nules were dry. E.g. this is useful!'), ['Dr. Smith used Fig. 3 at 2.5 mg.', 'The granules were dry.', 'E.g. this is useful!']);
});
test('exports edited translations, notes, references and figure text', () => {
  const result = exportScript('Test', [{ ...sampleRows[0], checked: true, note: '確認する', reference: '参考訳' }], 'x = 2');
  assert.match(result, /確認済み/); assert.match(result, /\[メモ\] 確認する/); assert.match(result, /\[参考訳\] 参考訳/); assert.match(result, /x = 2/);
});
test('translation route rejects cross-origin requests and missing keys', async () => {
  const cross = await POST(new Request('https://test.example/api/translate', { method: 'POST', headers: { origin: 'https://evil.example' }, body: '{}' })); assert.equal(cross.status, 403);
  const missing = await POST(new Request('https://test.example/api/translate', { method: 'POST', body: JSON.stringify({ sentences: ['Some text.'], mode: 'gemini' }) })); assert.equal(missing.status, 400);
});
test('translation route preserves alignment and rejects missing or altered source text', async () => {
  const originalFetch = global.fetch;
  const request = () => new Request('https://test.example/api/translate', { method: 'POST', body: JSON.stringify({ sentences: ['The granules are dry.'], mode: 'gemini', geminiKey: 'test-key', model: 'gemini-2.5-flash' }) });
  let output = { rows: [{ english: 'The granules ／ are dry.', japanese: '顆粒は ／ 乾燥している。' }] };
  global.fetch = async () => Response.json({ candidates: [{ content: { parts: [{ text: JSON.stringify(output) }] } }] });
  try {
    const success = await POST(request()); assert.equal(success.status, 200); assert.equal((await success.json()).rows[0].source, 'The granules are dry.');
    output = { rows: [{ english: 'The granules ／ are dry.', japanese: '顆粒は乾燥している。' }] }; assert.equal((await POST(request())).status, 502);
    output = { rows: [{ english: 'The particles ／ are dry.', japanese: '粒子は ／ 乾燥している。' }] }; assert.equal((await POST(request())).status, 502);
  } finally { global.fetch = originalFetch; }
});
