#!/usr/bin/env python3
"""はんだ付けマニュアル (docs/soldering-guide.md) を PDF にする。

    pip install markdown-it-py
    python hardware/wiring/make_pdf.py

- Markdown を印刷用の HTML にして、Chrome (または Chromium) の印刷機能で PDF にする
- 出力は docs/soldering-guide.pdf (A4 縦。配線のステップごとに改ページ)
- Chrome が見つからないときは、環境変数 CHROME に実行ファイルの場所を入れる
- マニュアルや図を直したら、このスクリプトも実行し直す
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
OUT = DOCS / "soldering-guide.pdf"
GITHUB = "https://github.com/furdabu/hayaoshi-buzzer/blob/main/"

CSS = """
@page { size: A4; margin: 15mm 14mm 17mm 14mm;
        @bottom-center { content: counter(page) " / " counter(pages); font-size: 9pt; color: #868e96; } }
* { box-sizing: border-box; }
body { font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Noto Sans CJK JP", "Yu Gothic", sans-serif;
       font-size: 10.5pt; line-height: 1.7; color: #212529; margin: 0; }
h1 { font-size: 23pt; margin: 0 0 2px; padding-bottom: 6px; border-bottom: 3px solid #0b7285; }
.sub { color: #495057; margin: 4px 0 14px; font-size: 10pt; }
h2 { font-size: 16pt; margin: 0 0 10px; padding-bottom: 4px; border-bottom: 2px solid #ced4da; break-before: page; break-after: avoid; }
h2:first-of-type { break-before: auto; margin-top: 18px; }
h3 { font-size: 12.5pt; margin: 18px 0 6px; break-after: avoid; }
h3.step { break-before: page; margin-top: 0; padding: 4px 10px; background: #e3fafc; border-left: 5px solid #0b7285; }
h4 { font-size: 11pt; margin: 14px 0 4px; break-after: avoid; }
p { margin: 6px 0; }
ul, ol { margin: 6px 0; padding-left: 22px; }
li { margin: 2px 0; }
img { display: block; max-width: 100%; max-height: 198mm; margin: 8px auto; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; line-height: 1.5; margin: 8px 0 12px; break-inside: avoid; }
th, td { border: 1px solid #ced4da; padding: 3px 6px; vertical-align: top; }
th { background: #f1f3f5; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
blockquote { margin: 10px 0; padding: 6px 12px; border-left: 4px solid #f08c00; background: #fff4e6; break-inside: avoid; }
blockquote p { margin: 2px 0; }
code { font-family: Menlo, Consolas, monospace; font-size: 0.9em; background: #f1f3f5; padding: 0 3px; border-radius: 3px; }
pre { background: #f1f3f5; padding: 8px 10px; border-radius: 4px; }
pre code { background: none; padding: 0; }
a { color: #1971c2; text-decoration: none; }
"""


def find_chrome() -> str:
    candidates = [os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  *(shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"))]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SystemExit("Chrome が見つかりません。環境変数 CHROME に実行ファイルの場所を入れてください")


def anchor(heading: str) -> str:
    """GitHub と同じ決まりで、見出しからリンク先の名前を作る"""
    h = re.sub(r"<[^>]+>", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", h).replace(" ", "-")


def build_html() -> str:
    text = (DOCS / "soldering-guide.md").read_text(encoding="utf-8")
    text = re.sub(r"<!-- /?AUTO[^>]*-->\n", "", text)
    text = re.sub(r"^- .*<!-- web -->\n", "", text, flags=re.M)  # 画面で読むときだけの案内は PDF に入れない
    text = text.replace("- [ ] ", "- ☐ ")
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)

    seen: dict = {}

    def heading(m):
        level, inner = m.group(1), m.group(2)
        a = anchor(inner)
        n = seen.get(a, 0)
        seen[a] = n + 1
        cls = ' class="step"' if level == "3" and inner.startswith("ステップ") else ""
        return f'<h{level} id="{a if n == 0 else f"{a}-{n}"}"{cls}>{inner}</h{level}>'

    def link(m):  # ほかの資料へのリンクは GitHub のページへ
        href = m.group(1)
        if href.startswith(("#", "http")):
            return m.group(0)
        path, _, frag = href.partition("#")
        rel = (DOCS / path).resolve().relative_to(REPO)
        return f'href="{GITHUB}{rel.as_posix()}{"#" + frag if frag else ""}"'

    html = re.sub(r"<h([1-4])>(.*?)</h\1>", heading, html)
    html = re.sub(r'href="([^"]+)"', link, html)
    html = re.sub(r'src="([^"]+)"', lambda m: f'src="{(DOCS / m.group(1)).resolve().as_uri()}"', html)
    sub = f'<p class="sub">ヤブイヌ式 早押しクイズボタン MK.1　/　{datetime.date.today():%Y-%m-%d} 版</p>'
    html = html.replace("</h1>", "</h1>\n" + sub, 1)
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>はんだ付けマニュアル</title>'
            f"<style>{CSS}</style></head><body>{html}</body></html>")


def main() -> None:
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "soldering-guide.html"
        page.write_text(build_html(), encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
                        f"--print-to-pdf={OUT}", page.as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"{OUT.relative_to(REPO)} を書き出しました ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
