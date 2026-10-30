"""Synthetic Notion/PostgREST/Storage contracts; never contact real services."""

import json
from io import BytesIO
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image, PngImagePlugin

from scripts import import_notion as importer
from scripts import notion_images as images
from scripts.notion_content import convert

SOURCE = "00000000-0000-4000-8000-000000000001"
PAGE = "00000000-0000-4000-8000-000000000002"
IMAGE = "00000000-0000-4000-8000-000000000003"
CHILD = "00000000-0000-4000-8000-000000000004"
URL = "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/example.png?signature=SYNTHETIC"


def png(size=(2, 2)):
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "synthetic metadata")
    Image.new("RGB", size, "red").save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def page(checked=True):
    return {"id": PAGE, "parent": {"type": "data_source_id", "data_source_id": SOURCE},
            "created_time": "2026-10-29T18:00:00Z", "properties": {
                "Import": {"type": "checkbox", "checkbox": checked},
                "Title": {"type": "title", "title": [{"plain_text": "Synthetic note"}]},
                "Date": {"type": "date", "date": None},
                "Subjects": {"type": "multi_select", "multi_select": [{"name": "Synthetic subject"}]},
                "Minutes": {"type": "number", "number": 60},
                "Understanding": {"type": "number", "number": 5}}}


class Service:
    def __init__(self):
        self.pages = [page()]
        self.blocks = [{"id": IMAGE, "type": "image", "image": {"type": "file", "file": {"url": URL}, "caption": []}},
                       {"id": CHILD, "type": "child_page", "has_children": True, "child_page": {"title": "not followed"}}]
        self.notes, self.rows, self.objects, self.requests = [], [], {}, []
        self.fail_record_once = False
        self.public = False

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content and "application/json" in request.headers.get("content-type", "") else None
        if path == f"/v1/data_sources/{SOURCE}":
            return httpx.Response(200, json={"properties": {"Import": {"type": "checkbox"}, "Date": {"type": "date"}, "Subjects": {"type": "multi_select"}}})
        if path.endswith("/query"):
            assert body["filter"] == {"property": "Import", "checkbox": {"equals": True}}
            return httpx.Response(200, json={"results": self.pages, "has_more": False})
        if path == f"/v1/blocks/{PAGE}/children":
            return httpx.Response(200, json={"results": self.blocks, "has_more": False})
        if path == "/storage/v1/bucket/private-notes":
            return httpx.Response(200, json={"public": self.public})
        if path == "/rest/v1/notes":
            if request.method == "GET":
                return httpx.Response(200, json=self.notes)
            pytest.fail("notes must be inserted atomically via RPC")
        if path == "/rest/v1/rpc/import_notion_note":
            assert body["p_subject_names"] == ["Synthetic subject"]
            assert set(body) == {"p_notion_page_id", "p_title", "p_body_markdown", "p_studied_on", "p_subject_names"}
            self.notes.append({"id": 7, "title": body["p_title"], "body_markdown": body["p_body_markdown"],
                               "studied_on": body["p_studied_on"], "is_published": False})
            return httpx.Response(200, json={"id": 7, "created": True})
        if path == "/rest/v1/note_images":
            if request.method == "GET":
                return httpx.Response(200, json=self.rows)
            if self.fail_record_once:
                self.fail_record_once = False
                return httpx.Response(503, json={"error": "synthetic failure"})
            self.rows.append({"id": 9, **body})
            return httpx.Response(201, json=self.rows)
        if path.startswith("/storage/v1/object/private-notes/"):
            assert request.headers["x-upsert"] == "true"
            self.objects[path] = request.content
            return httpx.Response(200, json={"Key": "synthetic"})
        pytest.fail(f"unexpected request path {path}")


def clients(service):
    http = httpx.Client(transport=httpx.MockTransport(service))
    return (importer.Notion(http, "synthetic", SOURCE, "Import", "Date"),
            importer.Destination(http, "https://synthetic.supabase.co", "synthetic", "private-notes"))


def test_two_runs_preserve_app_edits_and_add_zero_rows():
    service = Service()
    notion, destination = clients(service)
    fetch = Mock(return_value=png())
    first = importer.Counts()
    importer.run(notion, destination, first, fetch)
    assert (first.notes, first.images, first.failed_pages, first.failed_images) == (1, 1, 0, 0)
    assert service.notes[0]["studied_on"] == "2026-10-30"
    assert f"note-image:{IMAGE}" in service.notes[0]["body_markdown"]
    assert "signature" not in service.notes[0]["body_markdown"]
    service.notes[0]["body_markdown"] = "app edit"
    service.notes[0]["is_published"] = True
    second = importer.Counts()
    importer.run(notion, destination, second, fetch)
    assert (second.notes, second.images, second.skipped_pages, second.skipped_images) == (0, 0, 1, 1)
    assert service.notes[0]["body_markdown"] == "app edit" and service.notes[0]["is_published"] is True
    assert len(service.notes) == len(service.rows) == len(service.objects) == fetch.call_count == 1
    assert not any(CHILD in str(r.url) for r in service.requests)


def test_resume_after_storage_upload_before_image_row():
    service = Service()
    service.fail_record_once = True
    notion, destination = clients(service)
    first, second = importer.Counts(), importer.Counts()
    importer.run(notion, destination, first, lambda _: png())
    assert first.failed_images == 1 and len(service.objects) == 1 and not service.rows
    importer.run(notion, destination, second, lambda _: png())
    assert second.notes == 0 and second.images == 1 and len(service.objects) == 1


@pytest.mark.parametrize("change", ["unchecked", "archived", "foreign_parent"])
def test_unselected_pages_never_read_or_written(change):
    service = Service()
    if change == "unchecked":
        service.pages = [page(False)]
    elif change == "archived":
        service.pages[0]["archived"] = True
    else:
        service.pages[0]["parent"]["data_source_id"] = CHILD
    counts = importer.Counts()
    importer.run(*clients(service), counts, Mock(side_effect=AssertionError))
    assert counts.skipped_pages == 1
    assert not service.notes and not any("/blocks/" in r.url.path for r in service.requests)


def test_public_bucket_fails_before_page_reads():
    service = Service()
    service.public = True
    with pytest.raises(importer.ImportFailure):
        importer.run(*clients(service), importer.Counts())
    assert not service.notes and not any("/query" in r.url.path for r in service.requests)


def test_external_image_not_downloaded():
    service = Service()
    service.blocks[0]["image"] = {"type": "external", "external": {"url": URL}}
    counts, fetch = importer.Counts(), Mock()
    importer.run(*clients(service), counts, fetch)
    assert counts.rejected_images == 1 and not service.rows
    fetch.assert_not_called()


def test_png_reencoded_metadata_removed():
    raw = png()
    result = images.reencode(raw)
    assert result != raw
    with Image.open(BytesIO(result)) as decoded:
        assert decoded.format == "PNG" and decoded.size == (2, 2) and not decoded.info


@pytest.mark.parametrize("data", [b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"not an image", b"x" * (images.MAX_BYTES + 1), png((8001, 1))], ids=["svg", "unknown", "bytes", "dimensions"])
def test_invalid_and_oversized_images_rejected(data):
    with pytest.raises(images.ImageRejected):
        images.reencode(data)


@pytest.mark.parametrize("url", ["http://s3.us-west-2.amazonaws.com/secure.notion-static.com/a", "https://127.0.0.1/a",
    "https://evil.example/a", "https://s3.us-west-2.amazonaws.com.evil.example/secure.notion-static.com/a",
    "https://s3.us-west-2.amazonaws.com/other-bucket/a", URL.replace("https://", "https://user:pass@"),
    URL.replace(".com/", ".com:444/"), URL + "#fragment", URL + "\r\nInjected: true",
    URL.replace("example.png", "../other-bucket/file"), URL.replace("example.png", "%2e%2e/other-bucket/file")])
def test_url_policy_before_dns(monkeypatch, url):
    dns = Mock(side_effect=AssertionError)
    monkeypatch.setattr(images.socket, "getaddrinfo", dns)
    with pytest.raises(images.ImageRejected):
        images.download(url)
    dns.assert_not_called()


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1", "0.0.0.0"])
def test_dns_any_nonpublic_answer_rejected_before_connect(monkeypatch, ip):
    monkeypatch.setattr(images.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", (ip, 443))])
    connect = Mock(side_effect=AssertionError)
    monkeypatch.setattr(images, "PinnedHTTPSConnection", connect)
    with pytest.raises(images.ImageRejected):
        images.download(URL)
    connect.assert_not_called()


def test_numeric_connection_preserves_tls_hostname(monkeypatch):
    sock, context = Mock(), Mock()
    monkeypatch.setattr(images.socket, "socket", Mock(return_value=sock))
    monkeypatch.setattr(images.ssl, "create_default_context", Mock(return_value=context))
    connection = images.PinnedHTTPSConnection(images.HOST, (2, 1, 6, "", ("8.8.8.8", 443)))
    connection.connect()
    sock.connect.assert_called_once_with(("8.8.8.8", 443))
    context.wrap_socket.assert_called_once_with(sock, server_hostname=images.HOST)


@pytest.mark.parametrize("status,headers,data", [(302, {"Location": "http://127.0.0.1"}, b""),
    (200, {"Content-Length": str(images.MAX_BYTES + 1)}, b""), (200, {"Content-Encoding": "gzip"}, b""),
    (200, {"Content-Type": "image/svg+xml"}, b"<svg/>"), (200, {}, b"x" * (images.MAX_BYTES + 1))], ids=["redirect", "length", "encoding", "svg", "stream"])
def test_download_rejects_redirect_and_stream_limits(monkeypatch, status, headers, data):
    connection, response = Mock(), Mock()
    response.status = status
    response.getheader.side_effect = lambda key, default=None: headers.get(key, default)
    response.read.return_value = data
    connection.getresponse.return_value = response
    monkeypatch.setattr(images, "public_addresses", lambda host: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(images, "PinnedHTTPSConnection", lambda *a: connection)
    with pytest.raises(images.ImageRejected):
        images.download(URL)
    connection.close.assert_called_once()
    assert connection.request.call_count == 1
    if "Content-Length" in headers:
        response.read.assert_not_called()


def test_table_toggle_and_forbidden_subtrees():
    table, toggle, paragraph = [f"00000000-0000-4000-8000-{n:012d}" for n in (5, 6, 7)]
    tree = {PAGE: [{"id": table, "type": "table", "table": {"table_width": 2, "has_column_header": True}},
                   {"id": toggle, "type": "toggle", "has_children": True, "toggle": {"rich_text": [{"plain_text": "Details"}]}},
                   {"id": CHILD, "type": "synced_block", "has_children": True}],
            table: [{"table_row": {"cells": [[{"plain_text": "A"}], [{"plain_text": "B"}]]}},
                    {"table_row": {"cells": [[{"plain_text": "C"}], [{"plain_text": "D"}]]}}],
            toggle: [{"id": paragraph, "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Text"}]}}]}
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    result = convert(notion, PAGE)
    assert "| A | B |\n| --- | --- |\n| C | D |" in result.markdown
    assert "**Details**" in result.markdown and "  - Text" in result.markdown
    assert result.skipped == 1


def test_notion_pagination_and_rate_limit(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        if len(calls) == 2:
            return httpx.Response(200, json={"results": [page()], "has_more": True, "next_cursor": CHILD})
        assert json.loads(request.content)["start_cursor"] == CHILD
        return httpx.Response(200, json={"results": [], "has_more": False})
    monkeypatch.setattr(importer.time, "sleep", Mock())
    notion = importer.Notion(httpx.Client(transport=httpx.MockTransport(handle)), "synthetic", SOURCE, "Import", None)
    assert len(list(notion.pages())) == 1 and len(calls) == 3


def test_cli_errors_are_counts_only(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["import_notion"])
    monkeypatch.delenv("NOTION_IMPORT_SUPABASE_SECRET_KEY", raising=False)
    assert importer.main() == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["fatal_errors"] == 1 and out.err == ""


def test_pixel_limit_before_decode(monkeypatch):
    source = Mock()
    source.format, source.size = "PNG", (6000, 5000)
    source.__enter__ = Mock(return_value=source)
    source.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(images.Image, "open", Mock(return_value=source))
    with pytest.raises(images.ImageRejected):
        images.reencode(b"synthetic")
    source.load.assert_not_called()
    source.verify.assert_not_called()


def test_download_success_is_bounded_and_credential_free(monkeypatch):
    connection, response = Mock(), Mock()
    response.status = 200
    response.getheader.side_effect = lambda key, default=None: default
    response.read.return_value = png()
    connection.getresponse.return_value = response
    monkeypatch.setattr(images, "public_addresses", lambda host: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(images, "PinnedHTTPSConnection", lambda *a: connection)
    assert images.download(URL) == png()
    response.read.assert_called_once_with(images.MAX_BYTES + 1)
    assert connection.request.call_args.kwargs["headers"] == {"Accept-Encoding": "identity"}


def test_preserves_formatting_without_fetching_links():
    from scripts.notion_content import rich_text
    value = rich_text([{"text": {"content": "Example", "link": {"url": "https://example.test/a(b)"}}, "annotations": {"bold": True}}])
    assert value == "[**Example**](https://example.test/a%28b%29)"
    assert "javascript:" not in rich_text([{"text": {"content": "text", "link": {"url": "javascript:alert(1)"}}}])


def test_date_property_and_omitted_learning_fields():
    value = page()
    value["properties"]["Date"]["date"] = {"start": "2026-10-01"}
    result = importer.note_payload(value, "synthetic", "Date")
    assert result["studied_on"] == "2026-10-01"
    assert set(result) == {"notion_page_id", "title", "body_markdown", "studied_on", "is_published", "imported_at"}


def test_duplicate_insert_uses_existing_row():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": 12, "created": False})
    destination = importer.Destination(httpx.Client(transport=httpx.MockTransport(handler)),
        "https://synthetic.supabase.co", "synthetic", "private-notes")
    assert destination.insert_note(importer.note_payload(page(), "synthetic", "Date"), []) == (12, False)
    assert [r.method for r in requests] == ["POST"]
    assert all("authorization" not in r.headers for r in requests)


def test_api_failure_never_exposes_response_or_secret(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["import_notion"])
    monkeypatch.setenv("NOTION_IMPORT_SUPABASE_SECRET_KEY", "sb_secret_SYNTHETIC")
    monkeypatch.setenv("NOTION_IMPORT_TOKEN", "synthetic_notion_secret")
    monkeypatch.setenv("NOTION_IMPORT_DATA_SOURCE_ID", SOURCE)
    monkeypatch.setenv("NOTION_IMPORT_CHECKBOX", "Import")
    monkeypatch.setenv("NOTION_IMPORT_DATE_PROPERTY", "Date")
    monkeypatch.setenv("NOTION_IMPORT_SUBJECTS_PROPERTY", "Subjects")
    monkeypatch.setenv("NOTION_IMPORT_SUPABASE_URL", "https://synthetic.supabase.co")
    monkeypatch.setenv("NOTION_IMPORT_BUCKET", "private-notes")
    monkeypatch.setattr(importer.Notion, "validate", Mock(side_effect=ValueError("private body and secret")))
    assert importer.main() == 1
    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result["fatal_errors"] == 1 and all(isinstance(x, int) for x in result.values())
    assert "private" not in out.out and out.err == ""
