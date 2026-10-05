import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: '輪読ノート — 英文を、理解へ。', description: 'PDFから英語の語順に沿った日本語の台本を作成。医薬品ハンドブックの輪読会準備を、ひとつのワークスペースで。' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ja"><body>{children}</body></html>; }
