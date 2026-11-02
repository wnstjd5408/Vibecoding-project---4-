"""Synthetic SVG only; no real files, credentials or remote services."""
import subprocess
import base64
from io import BytesIO
from unittest.mock import Mock
from xml.etree.ElementTree import ParseError

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from defusedxml.common import DefusedXmlException

from scripts import notion_images as images
from scripts import notion_svg_worker as worker


def svg(body='', attributes='width="20" height="10"'):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}>{body}</svg>').encode()


def test_svg_becomes_metadata_free_png_in_real_worker():
    data = svg('<style>.red {fill: red}</style><rect class="red" width="20" height="10"/>')
    output = images.reencode(data)
    with Image.open(BytesIO(output)) as picture:
        assert picture.format == "PNG" and picture.size == (20, 10)
        assert picture.getpixel((5, 5)) == (255, 0, 0, 255)
        assert not picture.info


def test_internal_gradient_and_viewbox():
    data = svg('<defs><linearGradient id="g"><stop stop-color="red"/></linearGradient></defs>'
               '<rect width="20" height="10" fill="url(#g)"/>', 'viewBox="0 0 20 10"')
    with Image.open(BytesIO(images.reencode(data))) as picture:
        assert picture.size == (20, 10)
        assert picture.getpixel((5, 5)) == (255, 0, 0, 255)


def raster_uri(fmt="PNG", size=(20, 10)):
    output = BytesIO()
    metadata = PngInfo()
    metadata.add_text("private", "synthetic metadata")
    Image.new("RGB", size, "red").save(output, format=fmt,
        **({"pnginfo": metadata} if fmt == "PNG" else {}))
    return "data:image/" + {"PNG": "png", "JPEG": "jpeg", "GIF": "gif"}[fmt] + ";base64," + base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
@pytest.mark.parametrize("href", ["href", "xlink:href"])
def test_embedded_raster_is_reencoded_and_rendered(fmt, href):
    data = svg(f'<image xmlns:xlink="http://www.w3.org/1999/xlink" {href}="{raster_uri(fmt)}" width="20" height="10"/>')
    normalized, _, _ = worker.prepare(data)
    root = worker.fromstring(normalized)
    value = next(iter(root)).get("href") or next(iter(root)).get("{http://www.w3.org/1999/xlink}href")
    assert value.startswith("data:image/png;base64,")
    with Image.open(BytesIO(base64.b64decode(value.split(",", 1)[1]))) as embedded:
        assert embedded.format == "PNG" and not embedded.info
    with Image.open(BytesIO(images.reencode(data))) as result:
        assert result.size == (20, 10) and not result.info
        red, green, blue, alpha = result.getpixel((5, 5))
        assert red >= 250 and green <= 5 and blue <= 5 and alpha == 255


@pytest.mark.parametrize("value", [
    "https://example.invalid/x.png", "file:///private.png", "../private.png", "#local",
    "data:image/svg+xml;base64,PHN2Zy8+", "data:image/png;base64,PHN2Zy8+",
    "data:image/png;base64,%%%", "data:image/png;base64,AA==",
    "data:image/png,raw", raster_uri("GIF"),
    raster_uri("JPEG").replace("image/jpeg", "image/png"),
    raster_uri().replace("image/png", "image/jpeg"),
], ids=[f"source-{i}" for i in range(12)])
def test_bad_embedded_source_never_reaches_renderer(monkeypatch, value):
    renderer = Mock(side_effect=AssertionError)
    monkeypatch.setattr(worker.resvg_py, "svg_to_bytes", renderer)
    with pytest.raises(ValueError):
        worker.render(svg(f'<image href="{value}"/>'))
    renderer.assert_not_called()


@pytest.mark.parametrize("attrs", [
    '', 'href="#x" xlink:href="#y"', 'other:href="#x"', 'HREF="#x"'
])
def test_ambiguous_or_unknown_image_reference_rejected(attrs):
    with pytest.raises(ValueError, match="embedded_source"):
        worker.prepare(svg('<image xmlns:xlink="http://www.w3.org/1999/xlink" '
                           f'xmlns:other="urn:other" {attrs}/>'))


def test_embedded_total_pixels_checked_before_decode(monkeypatch):
    monkeypatch.setattr(worker, "MAX_PIXELS", 300)
    data = svg(f'<image href="{raster_uri()}"/><image href="{raster_uri()}"/>')
    with pytest.raises(ValueError, match="embedded_pixels"):
        worker.prepare(data)


def test_embedded_dimension_limit():
    with pytest.raises(ValueError, match="embedded_pixels"):
        worker.prepare(svg(f'<image href="{raster_uri(size=(8001, 1))}"/>'))


def test_embedded_total_byte_limits():
    with pytest.raises(ValueError, match="embedded_size"):
        worker.embedded_png(raster_uri(), [worker.MAX_BYTES, 0, 0])
    with pytest.raises(ValueError, match="embedded_size"):
        worker.embedded_png(raster_uri(), [0, 0, worker.MAX_BYTES])


def test_animated_embedded_png_rejected():
    output = BytesIO()
    first = Image.new("RGB", (2, 2), "red")
    first.save(output, format="PNG", save_all=True,
               append_images=[Image.new("RGB", (2, 2), "blue")], duration=100)
    uri = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    with pytest.raises(ValueError, match="embedded_pixels"):
        worker.prepare(svg(f'<image href="{uri}"/>'))


def test_sanitized_svg_size_is_bounded(monkeypatch):
    data = svg(f'<image href="{raster_uri()}"/>')
    monkeypatch.setattr(worker, "embedded_png", lambda *args: "x" * worker.MAX_BYTES)
    with pytest.raises(ValueError, match="size"):
        worker.prepare(data)


def test_embedded_raster_does_not_relax_css_or_events():
    for extra in ['onload="alert(1)"', 'style="fill:url(file:///private.svg)"']:
        with pytest.raises(ValueError):
            worker.prepare(svg(f'<image href="{raster_uri()}" {extra}/>'))


@pytest.mark.parametrize('body', [
    '<script>alert(1)</script>', '<rect onload="alert(1)"/>',
    '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>',
    '<image href="https://example.invalid/image.png"/>',
    '<image href="file:///private.txt"/>', '<image href="data:image/png;base64,AA=="/>',
    '<use href="#loop" id="loop"/>', '<filter id="f"><feGaussianBlur/></filter>',
    '<animate attributeName="href" to="file:///private.txt"/>',
    '<linearGradient href="file:///private.txt"/>',
    '<g xml:base="https://example.invalid/"/>',
    '<style>@import "https://example.invalid/style.css";</style>',
    '<style>@font-face {src: url(file:///private.ttf)}</style>',
    '<rect fill="url(https://example.invalid/pattern.svg)"/>',
    '<rect style="fill: url(&quot;file:///private.svg&quot;)"/>',
    '<style>rect {fill: u\\72l(https://example.invalid/x)}</style>',
    '<style>@\\69mport "https://example.invalid/x";</style>',
    '<style>rect {fill: url(\\68ttps://example.invalid/x)}</style>',
    '<style>rect {fill: url(}</style>',
    '<?xml-stylesheet href="file:///private.css"?>',
], ids=[f"unsafe-{i}" for i in range(20)])
def test_unsafe_svg_rejected_before_renderer(monkeypatch, body):
    renderer = Mock(side_effect=AssertionError("must not render"))
    monkeypatch.setattr(worker.resvg_py, 'svg_to_bytes', renderer)
    with pytest.raises(ValueError):
        worker.render(svg(body))
    renderer.assert_not_called()


@pytest.mark.parametrize('data', [
    b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///private.txt">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    b'<!DOCTYPE svg SYSTEM "https://example.invalid/test.dtd"><svg/>',
    b'<html/>', b'<svg', b'x' * (worker.MAX_BYTES + 1),
    svg(attributes='width="8001" height="1"'),
    svg(attributes='width="6000" height="6000"'),
    svg(attributes='viewBox="0 0 inf 5"'),
    svg(attributes='width="0" height="10"'),
    svg(attributes=''), svg('<g>' * 34 + '</g>' * 34),
    svg('<rect/>' * 10001),
], ids=['entity', 'dtd', 'html', 'invalid', 'bytes', 'side', 'pixels', 'infinite', 'zero', 'missing-size', 'depth', 'nodes'])
def test_invalid_and_excessive_svg_rejected_before_renderer(monkeypatch, data):
    renderer = Mock(side_effect=AssertionError("must not render"))
    monkeypatch.setattr(worker.resvg_py, 'svg_to_bytes', renderer)
    with pytest.raises((ValueError, DefusedXmlException, ParseError)):
        worker.prepare(data)
    renderer.assert_not_called()


def test_svg_download_uses_same_bounded_transport(monkeypatch):
    raw = svg('<rect width="20" height="10" fill="blue"/>')
    response, connection = Mock(), Mock()
    response.status = 200
    response.getheader.side_effect = lambda key, default=None: {
        'Content-Type': 'image/svg+xml', 'Content-Length': str(len(raw))}.get(key, default)
    response.read.return_value = raw
    connection.getresponse.return_value = response
    monkeypatch.setattr(images, 'public_addresses', lambda host: [('address',)])
    monkeypatch.setattr(images, 'PinnedHTTPSConnection', lambda *args: connection)
    data = images.download('https://' + images.FILE_HOST + '/synthetic.svg')
    assert images.reencode(data).startswith(b'\x89PNG')
    connection.close.assert_called_once()


def test_timeout_kills_worker_and_hides_secrets(monkeypatch):
    monkeypatch.setenv('NOTION_IMPORT_TOKEN', 'SYNTHETIC_SECRET')
    real_run = subprocess.run
    def sleeping_worker(command, **kwargs):
        assert 'NOTION_IMPORT_TOKEN' not in kwargs['env']
        assert command[1] == '-I'
        assert kwargs['stderr'] == subprocess.DEVNULL
        return real_run([command[0], '-I', '-c', 'import time; time.sleep(30)'], **kwargs)
    monkeypatch.setattr(images.subprocess, 'run', sleeping_worker)
    monkeypatch.setattr(images, 'SVG_TIMEOUT', 0.1)
    with pytest.raises(images.ImageRejected, match='svg_timeout'):
        images.reencode(svg())


@pytest.mark.parametrize('code,output', [(2, b''), (0, b'not PNG'), (0, b'\x89PNG\r\n\x1a\n' + b'x' * images.MAX_BYTES)], ids=['failed', 'invalid', 'oversized'])
def test_bad_worker_output_rejected(monkeypatch, code, output):
    monkeypatch.setattr(images.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, code, output))
    with pytest.raises(images.ImageRejected):
        images.reencode(svg())
