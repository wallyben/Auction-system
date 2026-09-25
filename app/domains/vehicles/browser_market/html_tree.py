"""Minimal HTML tree for card scoring. Fixtures stay synthetic."""

from __future__ import annotations

from html.parser import HTMLParser


class Node:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: Node | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.parent = parent
        self.children: list[Node] = []
        self.text_parts: list[str] = []

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return " ".join(part for part in parts if part).strip()

    def attr(self, name: str) -> str:
        return self.attrs.get(name, "")

    def walk(self) -> list[Node]:
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): (value or "") for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag.lower() not in {"br", "img", "meta", "link", "input", "hr", "source"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.stack[-1].text_parts.append(text)


def parse_html(html: str) -> Node:
    parser = _Tree()
    parser.feed(html or "")
    parser.close()
    return parser.root
