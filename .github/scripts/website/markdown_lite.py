"""A tiny Markdown-to-HTML converter (standard library only).

Supported: headings (with id anchors), paragraphs, bold, italic, inline code,
fenced code blocks, links, unordered and ordered lists (nestable), tables,
blockquotes and horizontal rules. All text is HTML-escaped; raw HTML in the
input is never passed through.
"""

from __future__ import annotations

import html
import re
from typing import Callable

LinkRewrite = Callable[[str], str]

_SAFE_URL = re.compile(r"^(https?:|mailto:|#|/|\.{0,2}/|[A-Za-z0-9_.~-]+(/|\.md|#|$|\?))", re.I)
_LINK = re.compile(r'\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+"([^"]*)")?\s*\)')
_CODE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])|(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])")
_PLACEHOLDER = re.compile("\x00(\\d+)\x00")

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def slugify(text: str) -> str:
    text = re.sub(r"[`*_]", "", text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def _stash(store: list[str], value: str) -> str:
    store.append(value)
    return f"\x00{len(store) - 1}\x00"


def _inline(text: str, store: list[str], rewrite: LinkRewrite | None) -> str:
    def code(m: re.Match) -> str:
        return _stash(store, "<code>" + html.escape(m.group(2).strip(), quote=False) + "</code>")

    text = _CODE.sub(code, text)

    def link(m: re.Match) -> str:
        label, url, title = m.group(1), m.group(2), m.group(3)
        if not _SAFE_URL.match(url):
            return m.group(0)
        if rewrite is not None:
            url = rewrite(url)
        attrs = f'href="{html.escape(url)}"'
        if title:
            attrs += f' title="{html.escape(title)}"'
        if re.match(r"https?:", url, re.I):
            attrs += ' rel="noopener"'
        inner = _inline(label, store, rewrite)
        return _stash(store, f"<a {attrs}>{inner}</a>")

    text = _LINK.sub(link, text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(lambda m: "<strong>" + (m.group(1) or m.group(2)) + "</strong>", text)
    text = _ITALIC.sub(lambda m: "<em>" + (m.group(1) or m.group(2)) + "</em>", text)
    return text


def _restore(text: str, store: list[str]) -> str:
    while True:
        new = _PLACEHOLDER.sub(lambda m: store[int(m.group(1))], text)
        if new == text:
            return new
        text = new


def inline_html(text: str, rewrite: LinkRewrite | None = None) -> str:
    """Render inline markdown (no block structure) to HTML."""
    store: list[str] = []
    return _restore(_inline(text, store, rewrite), store)


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [c.replace("\\|", "|").strip() for c in cells]


class _Converter:
    def __init__(self, rewrite: LinkRewrite | None):
        self.rewrite = rewrite
        self.ids: dict[str, int] = {}

    def inline(self, text: str) -> str:
        return inline_html(text, self.rewrite)

    def heading_id(self, text: str) -> str:
        base = slugify(text)
        count = self.ids.get(base, 0)
        self.ids[base] = count + 1
        return base if count == 0 else f"{base}-{count + 1}"

    # -- blocks ---------------------------------------------------------
    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            m = _FENCE.match(line)
            if m:
                marker, lang = m.group(1), m.group(2)
                i += 1
                body: list[str] = []
                while i < n:
                    s = lines[i].strip()
                    if s and set(s) == {marker[0]} and len(s) >= len(marker):
                        break
                    body.append(lines[i])
                    i += 1
                i += 1  # closing fence (or end of input)
                cls = f' class="language-{html.escape(lang)}"' if lang else ""
                out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}\n</code></pre>")
                continue

            m = _HEADING.match(line)
            if m:
                level = len(m.group(1))
                text = m.group(2)
                hid = self.heading_id(text)
                out.append(f'<h{level} id="{hid}">{self.inline(text)}</h{level}>')
                i += 1
                continue

            if _HR.match(line) and not _LIST.match(line):
                out.append("<hr>")
                i += 1
                continue

            if line.lstrip().startswith(">"):
                quote: list[str] = []
                while i < n and lines[i].lstrip().startswith(">"):
                    quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                out.append("<blockquote>\n" + self.blocks(quote) + "\n</blockquote>")
                continue

            if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
                header = _split_row(line)
                aligns = [self._align(c) for c in _split_row(lines[i + 1])]
                i += 2
                rows: list[list[str]] = []
                while i < n and lines[i].strip() and "|" in lines[i]:
                    rows.append(_split_row(lines[i]))
                    i += 1
                out.append(self._table(header, aligns, rows))
                continue

            if _LIST.match(line):
                chunk, i = self._list(lines, i)
                out.append(chunk)
                continue

            para: list[str] = []
            while i < n and lines[i].strip():
                cur = lines[i]
                if para and (_FENCE.match(cur) or _HEADING.match(cur) or _LIST.match(cur)
                             or cur.lstrip().startswith(">")):
                    break
                para.append(cur.strip())
                i += 1
            out.append("<p>" + self.inline(" ".join(para)) + "</p>")
        return "\n".join(out)

    @staticmethod
    def _align(cell: str) -> str:
        cell = cell.strip()
        if cell.startswith(":") and cell.endswith(":"):
            return "center"
        if cell.endswith(":"):
            return "right"
        return ""

    def _table(self, header: list[str], aligns: list[str], rows: list[list[str]]) -> str:
        def cell(tag: str, text: str, idx: int) -> str:
            align = aligns[idx] if idx < len(aligns) else ""
            style = f' style="text-align:{align}"' if align else ""
            return f"<{tag}{style}>{self.inline(text)}</{tag}>"

        parts = ['<div class="table-wrap"><table>', "<thead><tr>"]
        parts += [cell("th", c, k) for k, c in enumerate(header)]
        parts.append("</tr></thead>\n<tbody>")
        for row in rows:
            parts.append("<tr>" + "".join(cell("td", c, k) for k, c in enumerate(row)) + "</tr>")
        parts.append("</tbody></table></div>")
        return "".join(parts)

    def _list(self, lines: list[str], i: int) -> tuple[str, int]:
        n = len(lines)
        first = _LIST.match(lines[i])
        assert first
        base = len(first.group(1).expandtabs(4))
        ordered = first.group(2)[0].isdigit()
        items: list[tuple[list[str], list[str]]] = []  # (text lines, nested html chunks)
        while i < n:
            line = lines[i]
            if not line.strip():
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                nxt = _LIST.match(lines[j]) if j < n else None
                if nxt and len(nxt.group(1).expandtabs(4)) >= base and items:
                    i = j
                    continue
                break
            m = _LIST.match(line)
            if m:
                indent = len(m.group(1).expandtabs(4))
                if indent < base:
                    break
                if indent > base:
                    if not items:
                        break
                    chunk, i = self._list(lines, i)
                    items[-1][1].append(chunk)
                    continue
                if m.group(2)[0].isdigit() != ordered:
                    break
                items.append(([m.group(3)], []))
                i += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent > base and items:
                items[-1][0].append(line.strip())
                i += 1
                continue
            break
        tag = "ol" if ordered else "ul"
        parts = [f"<{tag}>"]
        for text_lines, nested in items:
            parts.append("<li>" + self.inline(" ".join(text_lines)) + ("\n" + "\n".join(nested) if nested else "") + "</li>")
        parts.append(f"</{tag}>")
        return "\n".join(parts), i


def convert(text: str, link_rewrite: LinkRewrite | None = None) -> str:
    """Convert markdown text to an HTML fragment."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return _Converter(link_rewrite).blocks(lines)


def first_heading(text: str) -> str | None:
    """Raw text of the first level-1 heading, if any (skipping fenced code)."""
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#\s+(.*?)\s*#*\s*$", line)
        if m:
            return m.group(1)
    return None


def first_paragraph(text: str) -> str:
    """Raw text of the first plain paragraph after the title ('' if none)."""
    para: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if not stripped:
            if para:
                break
            continue
        if _HEADING.match(line) or _LIST.match(line) or stripped.startswith((">", "|")):
            if para:
                break
            continue
        para.append(stripped)
    return " ".join(para)
