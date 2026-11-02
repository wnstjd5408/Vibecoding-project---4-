"""Restricted SVG rasterizer process. Input/output are bytes, never log content."""

import math
import base64
import binascii
import re
import sys
from io import BytesIO
from xml.etree.ElementTree import tostring

from defusedxml.ElementTree import fromstring
import resvg_py
import tinycss2
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10_000_000
MAX_SIDE = 8_000
MAX_PIXELS = 25_000_000
SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED_TAGS = {
    "svg", "g", "defs", "title", "desc", "style", "path", "rect", "circle",
    "ellipse", "line", "polyline", "polygon", "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "image",
}
IMAGE_HREFS = {"href", "{http://www.w3.org/1999/xlink}href"}


def embedded_png(value, budget):
    """Decode only embedded PNG/JPEG; share byte/pixel budgets across images."""
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)", value)
    if not match:
        raise ValueError("embedded_source")
    try:
        raw = base64.b64decode(re.sub(r"\s", "", match[2]), validate=True)
        budget[0] += len(raw)
        if budget[0] > MAX_BYTES:
            raise ValueError("embedded_size")
        with Image.open(BytesIO(raw)) as source:
            if source.format != {"png": "PNG", "jpeg": "JPEG"}[match[1]]:
                raise ValueError("embedded_format")
            width, height = source.size
            budget[1] += width * height
            if (max(width, height) > MAX_SIDE or budget[1] > MAX_PIXELS
                    or getattr(source, "n_frames", 1) != 1):
                raise ValueError("embedded_pixels")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            source.load()
            clean = Image.new("RGBA", source.size)
            clean.paste(source.convert("RGBA"))
            output = BytesIO()
            clean.save(output, format="PNG")
        encoded = output.getvalue()
        budget[2] += len(encoded)
        if budget[2] > MAX_BYTES:
            raise ValueError("embedded_size")
        return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("embedded_format") from None


def fragment(value):
    if not re.fullmatch(r"#[A-Za-z0-9_.:-]+", value):
        raise ValueError("reference")


def check_css(tokens, depth=0):
    if depth > 32:
        raise ValueError("depth")
    for token in tokens:
        if token.type in {"error", "at-keyword"}:
            raise ValueError("css")
        if token.type == "url":
            fragment(token.value)
        elif token.type == "function":
            if token.lower_name == "url":
                args = [t for t in token.arguments if t.type not in {"whitespace", "comment"}]
                if len(args) != 1 or args[0].type != "string":
                    raise ValueError("reference")
                fragment(args[0].value)
            else:
                check_css(token.arguments, depth + 1)
        elif hasattr(token, "content"):
            check_css(token.content, depth + 1)


def dimension(value, fallback):
    if value is None or value.endswith("%"):
        number = fallback
    else:
        match = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(px|pt|pc|mm|cm|in)?\s*", value)
        if not match:
            raise ValueError("dimension")
        units = {None: 1, "px": 1, "pt": 96 / 72, "pc": 16, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}
        number = float(match[1]) * units[match[2]]
    if number is None or not math.isfinite(number) or not 0 < number <= MAX_SIDE:
        raise ValueError("dimension")
    return math.ceil(number)


def prepare(data):
    if len(data) > MAX_BYTES:
        raise ValueError("size")
    # UTF-8 only; defusedxml rejects DTDs/entities/external resolution.
    text = data.decode("utf-8-sig")
    without_declaration = re.sub(r"\A<\?xml\s[^?]*\?>", "", text, count=1)
    if "<?" in without_declaration:
        raise ValueError("processing_instruction")
    root = fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag != "{" + SVG_NS + "}svg":
        raise ValueError("root")
    stack, count = [(root, 0)], 0
    embedded_budget = [0, 0, 0]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 10_000 or depth > 32:
            raise ValueError("complexity")
        if not node.tag.startswith("{" + SVG_NS + "}") or node.tag.split("}", 1)[1] not in ALLOWED_TAGS:
            # No script, foreignObject, use, animation or filters.
            raise ValueError("element")
        image_href = None
        if node.tag == "{" + SVG_NS + "}image":
            references = [name for name in node.attrib if name.rsplit("}", 1)[-1].lower() == "href"]
            if len(references) != 1 or references[0] not in IMAGE_HREFS:
                raise ValueError("embedded_source")
            image_href = references[0]
            node.set(image_href, embedded_png(node.get(image_href), embedded_budget))
        for name, value in node.attrib.items():
            if name == image_href:
                # This single reference is now our own metadata-free PNG data URI.
                continue
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on") or local in {"base", "src"}:
                raise ValueError("attribute")
            if local == "href":
                fragment(value)
            check_css(tinycss2.parse_component_value_list(value))
        if node.tag == "{" + SVG_NS + "}style":
            check_css(tinycss2.parse_component_value_list(node.text or ""))
        stack.extend((child, depth + 1) for child in node)
    box = [float(x) for x in re.split(r"[\s,]+", root.get("viewBox", "").strip()) if x]
    if box and (len(box) != 4 or not all(math.isfinite(x) for x in box) or min(box[2:]) <= 0):
        raise ValueError("viewbox")
    width = dimension(root.get("width"), box[2] if box else None)
    height = dimension(root.get("height"), box[3] if box else None)
    if width * height > MAX_PIXELS:
        raise ValueError("pixels")
    root.set("width", str(width))
    root.set("height", str(height))
    normalized = tostring(root, encoding="unicode")
    if len(normalized.encode("utf-8")) > MAX_BYTES:
        raise ValueError("size")
    return normalized, width, height


def render(data):
    svg, width, height = prepare(data)
    result = resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height,
                                  resources_dir=None, log_information=False)
    if len(result) > MAX_BYTES:
        raise ValueError("output_size")
    return result


if __name__ == "__main__":
    try:
        output = render(sys.stdin.buffer.read(MAX_BYTES + 1))
    except BaseException:
        sys.exit(2)
    sys.stdout.buffer.write(output)
