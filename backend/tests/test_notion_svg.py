"""Synthetic SVG only; no real files, credentials or remote services."""
import subprocess
from io import BytesIO
from unittest.mock import Mock
from xml.etree.ElementTree import ParseError

import pytest
from PIL import Image
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
