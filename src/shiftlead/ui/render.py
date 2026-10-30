"""The closed markdown subset a message to the person is drawn in (design §4.10 *How a message to a
person is written*, §4.5a *Inbox row: details*; TD-127, built by TD-138).

The UI's **own renderer**, not a vendored library behind a sanitiser, so that *no raw HTML reaches
a page* is a property of this code rather than of a configuration: every character of the source
passes through `html.escape` on its way out, and the only tags emitted are the ones written below.

The subset: paragraphs (a line break inside one is kept), `*em*` and `**strong**`, `` `code` ``,
fenced code blocks, `-` and `1.` lists, and `[text](url)`. Everything else — raw HTML, headings,
images, tables — is drawn as the characters typed.

**A link is the one pressable thing text can make** (§4.5, TD-071 item 8): drawn only when its
target is absolute `http` or `https` and not the UI's own origin, opened in a new tab with
`noopener`, and followed by its host in small print, so link text can never pass for one of the
page's controls. Any other link is its characters.

`fold` is the Inbox's split of a text into what the row draws and what goes under *details*;
`fold_head` is a board line's (TD-279), cut after its bold head and the sentence after it.
"""

from __future__ import annotations

import functools
import re
from html import escape
from urllib.parse import urlsplit

from sessionorc.mail import SENTENCE

# §4.5a *Inbox row: details*: the backstop for text nobody shaped — no blank line and longer than this.
FOLD_CHARS = 300
# design §4.10 *How a message to a person is written* (TD-127, built by TD-139): past this many words
# the first paragraph is more than the person reads before deciding, and `ao msg` says so.
FIRST_PARA_WORDS = 60

_FENCE = re.compile(r"^[ \t]*```")
_UL = re.compile(r"^[ \t]*-[ \t]+(.*)$")
_OL = re.compile(r"^[ \t]*(\d{1,9})[.)][ \t]+(.*)$")
_INLINE = re.compile(
    r"(?P<code>`+)(?P<ctext>.+?)(?P=code)"  # a code span: its contents are characters
    r"|(?<!!)\[(?P<ltext>[^\[\]\n]+)\]\((?P<url>[^()\s]+)\)"  # a link, never an image
    r"|\*\*(?P<strong>(?=\S).+?(?<=\S))\*\*"
    r"|(?<![*\w])\*(?P<em>(?=[^\s*]).*?(?<=[^\s*]))\*(?![*\w])"
)
# the end of a sentence, for the backstop: a stop and then white space or the end
_SENTENCE_END = re.compile(r"[.!?][)\"'”’]*(?=\s|$)")
_CODE_SPAN = re.compile(r"(`+).+?\1")


def _netloc(url: str) -> str:
    return (urlsplit(url).netloc or "").lower()


def _link(text: str, url: str, origin: str | None) -> str | None:
    """The link's HTML, or None when the target is not one this page may draw (§4.10)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    if origin and parts.netloc.lower() == _netloc(origin):
        return None  # the UI's own origin: a link there would be a control made from text
    return (
        f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(text)}</a>'
        f' <small class="lhost">{escape(host)}</small>'
    )


def inline(text: str, origin: str | None = None, links: bool = True) -> str:
    """One run of text, inline constructs rendered and every other character escaped. Without
    `links` a link is its characters too: text in which nothing may be pressable (TD-071)."""
    out: list[str] = []
    pos = 0
    for m in _INLINE.finditer(text):
        out.append(escape(text[pos : m.start()]))
        pos = m.end()
        if m.group("code"):
            out.append(f"<code>{escape(m.group('ctext'))}</code>")
        elif m.group("url") is not None:
            got = _link(m.group("ltext"), m.group("url"), origin) if links else None
            out.append(got if got is not None else escape(m.group(0)))
        elif m.group("strong") is not None:
            out.append(f"<strong>{inline(m.group('strong'), origin, links)}</strong>")
        else:
            out.append(f"<em>{inline(m.group('em'), origin, links)}</em>")
    out.append(escape(text[pos:]))
    return "".join(out)


def _lines(lines: list[str], origin: str | None, links: bool = True) -> str:
    return "<br>".join(inline(x.strip(), origin, links) for x in lines)


def _indent(line: str) -> int:
    wide = line.expandtabs(4)
    return len(wide) - len(wide.lstrip())


def _list(items: list[tuple[int, str, list[str]]], start: int, origin: str | None, links: bool) -> tuple[str, int]:
    """One list from `items[start]` — `(indent, kind, lines)` each — and the index after it: its
    items at that item's indent and kind; an item indented deeper opens a list inside the item above
    it (§4.5a *Inbox board row: detail block*, TD-312), one shallower or of the other kind at this
    indent ends it."""
    depth, tag = items[start][0], items[start][1]
    parts: list[str] = []
    i = start
    while i < len(items):
        ind, kind, body = items[i]
        if ind < depth or (ind == depth and kind != tag):
            break
        if ind > depth and parts:
            sub, i = _list(items, i, origin, links)
            parts[-1] += sub
            continue
        parts.append(_lines(body, origin, links))
        i += 1
    return f"<{tag}>" + "".join(f"<li>{x}</li>" for x in parts) + f"</{tag}>", i


def _block(lines: list[str], origin: str | None, links: bool = True) -> list[str]:
    """One block between blank lines: runs of list items and runs of paragraph lines, in order. A
    list nests by indent: an item indented deeper than the one above it is a list inside that item."""
    out: list[str] = []
    para: list[str] = []
    items: list[tuple[int, str, list[str]]] = []

    def flush() -> None:
        nonlocal items, para
        i = 0
        while i < len(items):
            html, i = _list(items, i, origin, links)
            out.append(html)
        items = []
        if para:
            out.append(f"<p>{_lines(para, origin, links)}</p>")
            para = []

    for line in lines:
        ul, ol = _UL.match(line), _OL.match(line)
        if ul or ol:
            if para:
                flush()
            items.append((_indent(line), "ul" if ul else "ol", [ul.group(1) if ul else ol.group(2)]))  # type: ignore[union-attr]
        elif items and line[:1] in (" ", "\t") and line.strip():
            items[-1][2].append(line)  # an indented line continues the item above it
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return out


@functools.lru_cache(maxsize=4096)
def render(text: str, origin: str | None = None, links: bool = True) -> str:
    """The whole text as HTML from the closed subset (§4.10). `origin` is the UI's own
    `scheme://host:port`, so a link back to the page itself is drawn as characters; without `links`
    every link is. Kept per argument triple: a function of its arguments alone, so a text drawn on
    every Inbox request — a mail entry's never changes — is rendered once (TD-747)."""
    out: list[str] = []
    block: list[str] = []
    fence: list[str] | None = None
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence is not None:
            if _FENCE.match(line):
                out.append(f"<pre><code>{escape(chr(10).join(fence))}</code></pre>")
                fence = None
            else:
                fence.append(line)
        elif _FENCE.match(line):
            out.extend(_block(block, origin, links))
            block, fence = [], []
        elif not line.strip():
            out.extend(_block(block, origin, links))
            block = []
        else:
            block.append(line)
    if fence is not None:  # an unclosed fence runs to the end, as a reader expects
        out.append(f"<pre><code>{escape(chr(10).join(fence))}</code></pre>")
    out.extend(_block(block, origin, links))
    return "".join(out)


def paragraph_break(text: str) -> tuple[str, str] | None:
    """`(first paragraph, the rest)` split at the first blank line — one inside a code block does
    not count, and `\r\n` is a line break — or None when the text has no such line. The one
    definition of *a blank line* that `fold` and `ao msg`'s shape warning share (design §4.10)."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = t.split("\n")
    fenced = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and not line.strip():
            return "\n".join(lines[:i]).rstrip(), "\n".join(lines[i + 1 :]).strip()
    return None


def fold(text: str) -> tuple[str, str]:
    """design §4.5a *Inbox row: details*: `(lead, rest)` — the first paragraph, up to the first
    blank line (`paragraph_break`), and the rest; for text with no blank line and longer than
    `FOLD_CHARS`, the lead ends at the last sentence end before that, else at `FOLD_CHARS`. `rest`
    is empty when there is nothing to fold, and the row then draws no disclosure."""
    split = paragraph_break(text)
    if split is not None:
        return split
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(t) <= FOLD_CHARS:
        return t, ""
    ends = [m.end() for m in _SENTENCE_END.finditer(t, 0, FOLD_CHARS)]
    cut = ends[-1] if ends else FOLD_CHARS
    return t[:cut].rstrip(), t[cut:].strip()


def one_sentence(text: str) -> bool:
    """design §4.10 *An item leads with one sentence* (TD-913): whether the text's first paragraph
    (`paragraph_break`, else the whole text), folded, is one sentence — within `FIRST_PARA_WORDS` and
    matched whole by the subject rule's sentence pattern (`sessionorc.mail.SENTENCE`), its inline code
    spans skipped first so a stop inside one ends nothing. An id or an abbreviation followed by a space
    (*TD-909. Which…*, *e.g. this*) fails it: a false warning, and a warning is all it is."""
    split = paragraph_break(text)
    first = split[0] if split is not None else (text or "")
    flat = " ".join(first.split())
    if not flat or len(flat.split()) > FIRST_PARA_WORDS:
        return False
    bare = " ".join(_CODE_SPAN.sub("code", flat).split())
    m = SENTENCE.match(bare)
    return m is not None and m.group(1) == bare


# §4.5a *Inbox board row: text* (TD-279): how far into a board line its bold head may start — past
# the kind, the date and the session that open every line — and still be read as the line's head
HEAD_WITHIN = 200
_BOLD_HEAD = re.compile(r"\*\*(?=\S)(?P<head>.+?)(?<=\S)\*\*")


def fold_head(text: str) -> tuple[str, str]:
    """design §4.5a *Inbox board row: text* (TD-279): `(lead, rest)` for a board line — one
    paragraph by the board's own format, so `fold`'s first paragraph would be the whole of it. A
    line whose bold head opens within `HEAD_WITHIN` characters leads with everything up to the end
    of that head and the one sentence after it; a line with no such head takes `fold`'s backstop.
    `rest` is empty when the line is no longer than `FOLD_CHARS`, or nothing follows the lead."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(t) <= FOLD_CHARS:
        return t, ""
    h = _BOLD_HEAD.search(t)
    if h is None or h.start() > HEAD_WITHIN:
        return fold(t)
    end = _SENTENCE_END.search(t, h.end())
    cut = end.end() if end else len(t)
    return t[:cut].rstrip(), t[cut:].strip()


def head_split(text: str) -> tuple[str, str, str, str]:
    """design §4.5 screen 12 *An item's shape* (TD-1066): a board line as a card draws it — `(prefix, head,
    leads, after)`: what stands before its first bold run (kind, date, *(session … on <host>)*), the run's
    words, the one sentence after it, and the rest. A line with no bold run is its own head."""
    t = " ".join((text or "").split())
    h = _BOLD_HEAD.search(t)
    if h is None:
        return "", t, "", ""
    after = t[h.end() :].strip()
    end = _SENTENCE_END.search(after)
    cut = end.end() if end else len(after)
    return t[: h.start()].rstrip(" —-"), h.group("head"), after[:cut].strip(), after[cut:].strip()


# a bold run ending in a colon after a sentence's end — *… (TD-095). **Cards:** a report …* — is the
# head of a part of a long line, and opens a paragraph under *details*: markdown, not the board's format
_PART_HEAD = re.compile(r"(?<=[.;!?)])\s+(?=\*\*[^*\n]{1,80}?:\*\*)")


def part_heads(text: str) -> str:
    """`text` with each part's bold head (`_PART_HEAD`) opening a paragraph of its own."""
    return _PART_HEAD.sub("\n\n", text)
