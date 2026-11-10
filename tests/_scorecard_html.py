"""HTML helpers for the scorecard tests (stdlib ``html.parser`` only; no browser, Q3).

``parse(html)`` returns a ``Doc``:

- ``nodes``: every visible text node (stripped, non-empty), outside ``script``,
  ``style`` and ``template``, each with the stack of enclosing elements;
- ``elements``: every start tag as ``(tag, attrs dict)``;
- ``headings``: heading levels in document order;
- ``scripts``: the text of each ``<script>`` element, by ``id``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"meta", "link", "br", "img", "input", "hr", "path", "circle"}
HIDDEN = {"script", "style", "template", "title"}


@dataclass
class Node:
    text: str
    stack: tuple[tuple[str, dict], ...]

    def inside(self, tag: str | None = None, **attrs) -> bool:
        for t, a in self.stack:
            if (tag is None or t == tag) and all((a.get(k.replace("_", "-")) == v if v is not True else k.replace("_", "-") in a) for k, v in attrs.items()):
                return True
        return False

    def attr(self, name: str) -> str | None:
        for _, a in reversed(self.stack):
            if name in a:
                return a[name]
        return None


@dataclass
class Doc:
    nodes: list[Node] = field(default_factory=list)
    elements: list[tuple[str, dict]] = field(default_factory=list)
    headings: list[int] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    title: str = ""

    def text(self, **where) -> str:
        nodes = [n for n in self.nodes if not where or n.inside(**where)]
        return " ".join(n.text for n in nodes)

    def tag_shape(self) -> Counter:
        return Counter((t, tuple(sorted(a))) for t, a in self.elements)


class _P(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = Doc()
        self.stack: list[tuple[str, dict]] = []
        self._script_id: str | None = None
        self._script_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.doc.elements.append((tag, a))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.doc.headings.append(int(tag[1]))
        if tag == "script":
            self._script_id = a.get("id", f"_anon{len(self.doc.scripts)}")
            self._script_buf = []
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.doc.elements.append((tag, a))

    def handle_endtag(self, tag):
        if tag == "script" and self._script_id is not None:
            self.doc.scripts[self._script_id] = "".join(self._script_buf)
            self._script_id = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._script_id is not None:
            self._script_buf.append(data)
            return
        if any(t == "title" for t, _ in self.stack):
            self.doc.title += data
            return
        if any(t in HIDDEN for t, _ in self.stack):
            return
        s = data.strip()
        if s:
            self.doc.nodes.append(Node(s, tuple(self.stack)))


def parse(html: str) -> Doc:
    p = _P()
    p.feed(html)
    p.close()
    return p.doc
