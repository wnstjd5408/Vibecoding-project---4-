"""Convert only a selected page's own content blocks to Markdown."""

import re
from dataclasses import dataclass, field
from uuid import UUID
from urllib.parse import quote, urlsplit


def canonical_id(value: str) -> str:
    return str(UUID(value))


def plain(items: list) -> str:
    return "".join(item.get("plain_text", item.get("text", {}).get("content", "")) for item in items)


def escaped(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>!|])", r"\\\1", text)


def rich_text(items: list) -> str:
    chunks = []
    for item in items:
        raw = plain([item])
        text = escaped(raw)
        annotation = item.get("annotations", {})
        if annotation.get("code"):
            fence = "`" * max(1, max((len(x) + 1 for x in re.findall(r"`+", raw)), default=1))
            text = f"{fence} {raw} {fence}"
        else:
            for key, marker in (("bold", "**"), ("italic", "*"), ("strikethrough", "~~")):
                if annotation.get(key):
                    text = marker + text + marker
        link = item.get("text", {}).get("link") or {}
        url = link.get("url", "")
        if urlsplit(url).scheme in {"https", "http"}:
            text = f"[{text}]({quote(url, safe=':/?=&%#@+;,$')})"
        chunks.append(text)
    return "".join(chunks)


@dataclass
class Content:
    markdown: str = ""
    images: list[dict] = field(default_factory=list)
    skipped: int = 0


def convert(notion, page_id: str) -> Content:
    result = Content()
    count = 0
    visited = set()

    def list_item(body: str) -> str:
        first, *rest = body.split("\n")
        return "  - " + first + "".join("\n    " + line if line else "\n" for line in rest)

    def walk(parent: str, depth: int = 0, as_list: bool = False) -> str:
        nonlocal count
        if depth > 32 or parent in visited:
            raise ValueError("block_limit")
        visited.add(parent)
        lines = []
        for block in notion.children(parent):
            count += 1
            if count > 10000:
                raise ValueError("block_limit")
            if block.get("archived") or block.get("in_trash"):
                continue
            kind = block["type"]
            data = block.get(kind, {})
            block_id = canonical_id(block["id"])
            block_start = len(lines)
            text = rich_text(data.get("rich_text", []))
            # Never traverse child pages/databases, synced content, attachments,
            # bookmarks, mentions or link-to-page blocks.
            containers = {"paragraph", "heading_1", "heading_2", "heading_3",
                          "bulleted_list_item", "numbered_list_item", "to_do",
                          "toggle", "quote", "callout", "column", "column_list", "table"}
            if kind == "image":
                alt = plain(data.get("caption", []))
                result.images.append({"id": block_id, "alt": alt,
                                      "url": data.get("file", {}).get("url") if data.get("type") == "file" else None})
                lines.append(f"![{escaped(alt)}](note-image:{block_id})")
            elif kind == "code":
                code = plain(data.get("rich_text", []))
                fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", code)), default=3))
                lines.append(f"{fence}\n{code}\n{fence}")
            elif kind == "divider":
                lines.append("---")
            elif kind == "equation":
                lines.append(escaped(data.get("expression", "")))
            elif kind in containers:
                if kind == "table":
                    rows = list(notion.children(block_id))
                    count += len(rows)
                    if count > 10000:
                        raise ValueError("block_limit")
                    cells = [[rich_text(c).replace("\n", "<br>") for c in r.get("table_row", {}).get("cells", [])] for r in rows]
                    width = data.get("table_width", 0)
                    if not 1 <= width <= 100 or any(len(row) != width for row in cells):
                        raise ValueError("table_shape")
                    if not data.get("has_column_header"):
                        cells.insert(0, [""] * width)
                    if cells:
                        cells.insert(1, ["---"] * width)
                        table = "\n".join("| " + " | ".join(row) + " |" for row in cells)
                        lines.append(list_item(table) if as_list else table)
                    continue
                prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
                          "bulleted_list_item": "- ", "numbered_list_item": "1. ",
                          "quote": "> ", "callout": "> "}.get(kind, "")
                if kind == "to_do":
                    prefix = "- [x] " if data.get("checked") else "- [ ] "
                if kind == "toggle":
                    text = f"**{text}**"
                lines.append(prefix + text)
                if block.get("has_children"):
                    child = walk(block_id, depth + 1, as_list=kind == "toggle")
                    if kind in {"bulleted_list_item", "numbered_list_item", "to_do"}:
                        child = "\n".join("    " + line for line in child.splitlines())
                    lines.append(child)
            else:
                result.skipped += 1
            if as_list and len(lines) > block_start:
                # One list item per Notion block, not per source line. Fences,
                # multiline paragraphs and nested children keep their structure.
                lines[block_start:] = [list_item("\n\n".join(lines[block_start:]))]
        body = "\n\n".join(lines)
        if len(body) > 200000:
            raise ValueError("body_limit")
        return body

    result.markdown = walk(page_id)
    return result
