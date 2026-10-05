export type Mode = 'gemini' | 'deepl' | 'reorder';
export type Sentence = { id: string; source: string; english: string; japanese: string; reference?: string; note: string; checked: boolean; error?: string };
export const MODELS = ['gemini-3.1-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'];
export function splitSentences(raw: string): string[] {
  let text = raw.replace(/-\r?\n(?=[a-z])/g, '').replace(/\s+/g, ' ').trim();
  const protectedDots: string[] = [];
  text = text.replace(/\b(?:e\.g\.|i\.e\.|etc\.|Fig\.|Vol\.|No\.|Dr\.|Mr\.|Mrs\.|Prof\.|vs\.|cf\.|al\.|approx\.)/gi, (s) => {
    protectedDots.push(s); return `${s[0]}\uE000${protectedDots.length - 1}\uE001`;
  });
  return text.split(/(?<=[.!?])\s+(?=[A-Z\d“"])/).map(s => s.replace(/[A-Za-z]\uE000(\d+)\uE001/g, (_, i) => protectedDots[Number(i)]).trim()).filter(Boolean);
}
export function exportScript(title: string, rows: Sentence[], figures = ''): string {
  return `${title}\n輪読会 台本\n\n` + rows.map((r, i) => `【${i + 1}】${r.checked ? '確認済み' : '未確認'}\n[原文] ${r.source}\n[英] ${r.english}\n[日] ${r.japanese}${r.reference ? `\n[参考訳] ${r.reference}` : ''}${r.note ? `\n[メモ] ${r.note}` : ''}${r.error ? `\n[エラー] ${r.error}` : ''}`).join('\n\n') + (figures ? `\n\n図表・数式\n${figures}` : '');
}
export const sampleText = 'In wet granulation, it is conceptually important to consider drying and cooling as an integral part of the granulation process. The properties of the granules depend on the formulation and the processing conditions. Particle size distribution is one of the most important characteristics of pharmaceutical granules.';
export const sampleRows: Sentence[] = [
  { id: 'sample-1', source: splitSentences(sampleText)[0], english: 'In wet granulation, ／ it is conceptually important ／ to consider drying and cooling ／ as an integral part ／ of the granulation process.', japanese: '湿式造粒では、／ 概念的に重要である ／ 乾燥と冷却を位置づけることが ／ 不可欠な一部として ／ 造粒工程の。', note: '', checked: false },
  { id: 'sample-2', source: splitSentences(sampleText)[1], english: 'The properties of the granules ／ depend on ／ the formulation ／ and the processing conditions.', japanese: '顆粒の特性は ／ 依存する ／ 処方に ／ そして製造条件に。', note: '', checked: false },
  { id: 'sample-3', source: splitSentences(sampleText)[2], english: 'Particle size distribution ／ is one of the most important characteristics ／ of pharmaceutical granules.', japanese: '粒度分布は ／ 最も重要な特性の一つである ／ 医薬品顆粒の。', note: '', checked: false },
];
