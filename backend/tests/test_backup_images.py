import gzip
import json
import urllib.error

import pytest

from scripts import backup_images
from scripts.backup_images import BackupError, compare, list_objects, run, safe_target


class FakeStorage:
    """Storage 목록·다운로드와 REST 행 조회를 흉내 낸다. 받은 호출을 기록한다.

    server_limit는 서버 쪽 상한(Storage limit, PostgREST max_rows)이다. 요청한 limit보다 작을 수 있다.
    """

    def __init__(self, objects: dict[str, bytes], rows: list[str], server_limit: int | None = None):
        self.objects = objects
        self.rows = rows
        self.server_limit = server_limit
        self.calls: list[tuple[str, str, dict | None]] = []

    def _cap(self, limit: int) -> int:
        return min(limit, self.server_limit) if self.server_limit else limit

    def __call__(self, method: str, url: str, body: dict | None) -> bytes:
        self.calls.append((method, url, body))
        if url.startswith("/storage/v1/object/list/"):
            return json.dumps(self._list(body["prefix"], body["offset"], self._cap(body["limit"]))).encode()
        if url.startswith("/storage/v1/object/authenticated/"):
            path = url.split("/", 6)[6]
            return self.objects[backup_images.urllib.parse.unquote(path)]
        if url.startswith("/rest/v1/"):
            query = backup_images.urllib.parse.parse_qs(url.split("?", 1)[1])
            assert query["order"] == ["id"]
            offset, limit = int(query["offset"][0]), self._cap(int(query["limit"][0]))
            return json.dumps([{"storage_path": p} for p in self.rows[offset : offset + limit]]).encode()
        raise AssertionError(url)

    def _list(self, prefix: str, offset: int, limit: int) -> list[dict]:
        entries: dict[str, dict] = {}
        for path in sorted(self.objects):
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix) :]
            head, sep, _ = rest.partition("/")
            # 폴더는 id가 null로 온다.
            entries[head] = {"name": head, "id": None} if sep else {"name": head, "id": "x"}
        return list(entries.values())[offset : offset + limit]


def test_list_objects_walks_folders_and_skips_placeholders():
    fake = FakeStorage(
        {"a.png": b"1", "n1/b.png": b"2", "n1/sub/c.png": b"3", "n1/sub/.emptyFolderPlaceholder": b""},
        [],
    )

    assert sorted(list_objects(fake, "glossary")) == ["a.png", "n1/b.png", "n1/sub/c.png"]


def test_list_objects_pages_inside_folders(monkeypatch):
    monkeypatch.setattr(backup_images, "PAGE_SIZE", 2)
    fake = FakeStorage({f"n1/f{i}.png": b"x" for i in range(4)}, [])

    assert len(list_objects(fake, "glossary")) == 4
    folder_offsets = [c[2]["offset"] for c in fake.calls if c[2]["prefix"] == "n1/"]
    # 쪽이 꽉 차 있으면 빈 쪽이 올 때까지 더 받는다.
    assert folder_offsets == [0, 2, 4]


def test_list_objects_survives_smaller_server_limit():
    fake = FakeStorage({f"f{i}.png": b"x" for i in range(5)}, [], server_limit=2)

    assert len(list_objects(fake, "glossary")) == 5


def test_compare_reports_both_directions():
    result = compare(["a", "b"], ["b", "c"])

    assert (result.files, result.rows) == (2, 2)
    assert result.missing_files == ["c"]
    assert result.extra_files == ["a"]
    assert not result.complete


def test_compare_extra_files_alone_is_complete():
    # 행을 지운 뒤 삭제 작업이 아직 객체를 지우지 않은 상태는 실패가 아니다.
    assert compare(["a", "b"], ["a"]).complete


@pytest.mark.parametrize("path", ["../x.png", "/etc/x", "a/../../x", "a//b", "./a", "", "a\\..\\x", "a/"])
def test_safe_target_rejects_escape(tmp_path, path):
    with pytest.raises(BackupError):
        safe_target(tmp_path, path)


def test_safe_target_rejects_symlinked_folder(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    try:
        (out_dir / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없다")

    with pytest.raises(BackupError):
        safe_target(out_dir, "link/x.png")


def test_run_writes_nothing_when_any_path_is_bad(tmp_path):
    fake = FakeStorage({"ok.png": b"1", "n1/../../evil.png": b"2"}, [])
    # 목록이 나쁜 이름을 그대로 돌려주는 상황을 만든다.
    fake._list = lambda prefix, offset, limit: (
        [{"name": "ok.png", "id": "x"}, {"name": "../evil.png", "id": "x"}] if offset == 0 else []
    )

    with pytest.raises(BackupError):
        run(fake, "glossary", "glossary_images", tmp_path, fake.rows.copy())

    assert not (tmp_path / "files" / "ok.png").exists()
    assert not any(c for c in fake.calls if "/authenticated/" in c[1])


def test_run_never_reads_live_rows(tmp_path):
    fake = FakeStorage({"a.png": b"1"}, ["a.png"])

    run(fake, "glossary", "glossary_images", tmp_path, fake.rows.copy())

    kinds = [("rest" if "/rest/" in c[1] else "download" if "/authenticated/" in c[1] else "list") for c in fake.calls]
    assert "rest" not in kinds
    assert kinds.index("list") < kinds.index("download")


def test_run_skips_files_deleted_after_listing(tmp_path):
    status = 404
    fake = FakeStorage({"a.png": b"1", "gone.png": b"2"}, ["a.png"])
    original = fake.__call__

    def deleted_midway(method, url, body):
        if url.endswith("/gone.png"):
            raise BackupError("Supabase 응답", status=status)
        return original(method, url, body)

    result = run(deleted_midway, "glossary", "glossary_images", tmp_path, fake.rows.copy())

    assert result.complete
    assert (result.files, result.vanished_files, result.extra_files) == (1, 1, [])
    assert not (tmp_path / "files" / "gone.png").exists()


def test_run_fails_on_other_download_errors(tmp_path):
    fake = FakeStorage({"a.png": b"1"}, ["a.png"])
    original = fake.__call__

    def server_error(method, url, body):
        if "/authenticated/" in url:
            raise BackupError("Supabase 응답 500", status=500)
        return original(method, url, body)

    with pytest.raises(BackupError):
        run(server_error, "glossary", "glossary_images", tmp_path, fake.rows.copy())


def test_paging_stops_when_server_ignores_offset(monkeypatch):
    monkeypatch.setattr(backup_images, "MAX_ITEMS", 10)
    fake = FakeStorage({}, [])
    fake._list = lambda prefix, offset, limit: [{"name": "same.png", "id": "x"}]

    with pytest.raises(BackupError):
        list_objects(fake, "glossary")


def test_run_downloads_and_writes_manifest(tmp_path):
    fake = FakeStorage({"n1/한글 이름.png": b"img1", "n2/b.png": b"img2"}, ["n1/한글 이름.png", "n2/b.png"])

    result = run(fake, "note-images", "note_images", tmp_path, fake.rows.copy())

    assert result.complete
    assert (tmp_path / "files" / "n1" / "한글 이름.png").read_bytes() == b"img1"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == 2 and manifest["rows"] == 2 and manifest["complete"] is True
    # 다운로드 URL에서 경로의 공백·한글은 인코딩하고 폴더 구분자는 남긴다.
    download_urls = [c[1] for c in fake.calls if "/authenticated/" in c[1]]
    assert "/storage/v1/object/authenticated/note-images/n1/%ED%95%9C%EA%B8%80%20%EC%9D%B4%EB%A6%84.png" in download_urls


def _run_main(tmp_path, monkeypatch, fake, rows=None):
    monkeypatch.setattr(backup_images, "make_fetch", lambda url, key: fake)
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret-value")
    dump = tmp_path / "data.sql"
    dump.write_text("COPY public.glossary_images (storage_path) FROM stdin;\n" +
                    "".join(path + "\n" for path in (fake.rows if rows is None else rows)) + "\\.\n", encoding="utf-8")
    return backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path), "--dump", str(dump)])


def test_main_exit_code_when_rows_have_no_file(tmp_path, monkeypatch, capsys):
    code = _run_main(tmp_path, monkeypatch, FakeStorage({"a.png": b"1"}, ["a.png", "b.png"]))

    out = capsys.readouterr()
    assert code == backup_images.EXIT_MISSING
    assert "파일 1개, 행 2개, 파일 없는 행 1개, 행 없는 파일 0개, 받는 중 지워진 파일 0개" in out.out
    # 공개 로그에 경로가 찍히지 않는다.
    assert "b.png" not in out.out + out.err


def test_main_succeeds_with_extra_files(tmp_path, monkeypatch, capsys):
    code = _run_main(tmp_path, monkeypatch, FakeStorage({"a.png": b"1", "old.png": b"2"}, ["a.png"]))

    assert code == 0
    assert "행 없는 파일 1개" in capsys.readouterr().out


def test_main_hides_unexpected_errors(tmp_path, monkeypatch, capsys):
    fake = FakeStorage({"secret-name.png": b"1"}, ["secret-name.png"])
    original = fake.__call__

    def broken(method, url, body):
        if "/authenticated/" in url:
            raise TimeoutError(f"timed out reading {url}")
        return original(method, url, body)

    code = _run_main(tmp_path, monkeypatch, broken, fake.rows)

    out = capsys.readouterr()
    assert code == 1
    assert out.err.strip() == "이미지 백업 실패: TimeoutError"
    assert "secret-name" not in out.out + out.err


def test_main_requires_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)

    assert backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path), "--dump", str(tmp_path / "data.sql")]) == 2


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("/rest/v1/note_images?select=storage_path", "REST 조회"),
        ("/storage/v1/object/authenticated/note-images/n1/secret-name.png", "Storage 다운로드"),
        ("/storage/v1/object/list/note-images", "Storage 목록"),
    ],
)
def test_fetch_errors_hide_url_and_key(monkeypatch, url, kind):
    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(backup_images.urllib.request, "urlopen", raise_http_error)
    fetch = backup_images.make_fetch("https://example.test", "test-secret-value")

    with pytest.raises(BackupError) as error:
        fetch("GET", url, None)

    assert str(error.value) == f"Supabase 응답 404: {kind}"


def test_fetch_wraps_read_timeout(monkeypatch):
    def raise_timeout(request, timeout):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(backup_images.urllib.request, "urlopen", raise_timeout)
    fetch = backup_images.make_fetch("https://example.test", "test-secret-value")

    with pytest.raises(BackupError) as error:
        fetch("GET", "/storage/v1/object/authenticated/b/secret-name.png", None)

    assert "secret-name" not in str(error.value)
    assert "TimeoutError" in str(error.value)


def test_fetch_sends_secret_key_headers(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"[]"

    def capture(request, timeout):
        seen.update(request.header_items())
        return Response()

    monkeypatch.setattr(backup_images.urllib.request, "urlopen", capture)
    backup_images.make_fetch("https://example.test", "k")("GET", "/rest/v1/note_images", None)

    assert seen["Apikey"] == "k"
    assert seen["Authorization"] == "Bearer k"


def _http_error(code, body):
    import io

    return urllib.error.HTTPError("https://example.test/x", code, "err", {}, io.BytesIO(body))


@pytest.mark.parametrize(
    ("code", "body", "expected"),
    [
        (400, b'{"statusCode": "404", "error": "not_found", "message": "Object not found"}', 404),
        (400, b'{"error": "not_found"}', 404),
        (400, b'{"statusCode": "400", "error": "InvalidKey"}', 400),
        (400, b"not json", 400),
        (404, b"", 404),
        (500, b"", 500),
    ],
)
def test_status_maps_storage_not_found(code, body, expected):
    assert backup_images._status(_http_error(code, body)) == expected


def test_run_fails_on_plain_400(tmp_path):
    fake = FakeStorage({"a.png": b"1"}, ["a.png"])
    original = fake.__call__

    def bad_request(method, url, body):
        if "/authenticated/" in url:
            raise BackupError("Supabase 응답 400", status=400)
        return original(method, url, body)

    with pytest.raises(BackupError):
        run(bad_request, "glossary", "glossary_images", tmp_path, fake.rows.copy())


@pytest.mark.parametrize("after_listing", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_dump_image_deleted_after_dump_fails_cli(tmp_path, monkeypatch, capsys, after_listing, compressed):
    # 덤프 당시에는 행과 파일이 있었다. 실행 때는 DB 행이 이미 삭제됐다.
    dump = tmp_path / "data.sql"
    dump.write_text("COPY public.glossary_images (id, storage_path) FROM stdin;\n1\tdeleted.png\n\\.\n", encoding="utf-8")
    if compressed:
        compressed_dump = dump.with_suffix(".sql.gz")
        compressed_dump.write_bytes(gzip.compress(dump.read_bytes()))
        dump = compressed_dump
    fake = FakeStorage({"deleted.png": b"old"} if after_listing else {}, [])
    def fetch(method, url, body):
        assert "/rest/" not in url
        if "/authenticated/" in url:
            raise BackupError("gone", status=404)
        return fake(method, url, body)
    monkeypatch.setattr(backup_images, "make_fetch", lambda *args: fetch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test")
    code = backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path / "out"), "--dump", str(dump)])
    assert code == 3
    manifest = json.loads((tmp_path / "out/manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["rows"] == 1
    assert manifest["missing_files"] == ["deleted.png"]
    assert manifest["vanished_files"] == int(after_listing)
    captured = capsys.readouterr()
    assert "deleted.png" not in captured.out + captured.err


def test_dump_paths_decode_copy_escapes_and_select_correct_table(tmp_path):
    dump = tmp_path / "data.sql"
    dump.write_bytes(
        b'COPY public.notes (body) FROM stdin;\n'
        b'COPY public.glossary_images (storage_path) FROM stdin;\n\\.\n'
        b'COPY public.note_images (storage_path) FROM stdin;\nother.png\n\\.\n'
        b'COPY "public"."glossary_images" ("id", "storage_path", "alt") FROM stdin;\n'
        b'1\tfolder/space name.png\tx\n'
        b'2\t\xed\x95\x9c.png\tx\n'
        b'3\t\\355\\225\\234.png\tx\n'
        b'4\t\\xED\\x95\\x9C.png\tx\n'
        b'5\ta\\tb\\nc\\\\d\tx\n\\.\n'
    )
    assert backup_images.dump_row_paths(dump, "glossary_images") == [
        "folder/space name.png", "한.png", "한.png", "한.png", "a\tb\nc\\d",
    ]


@pytest.mark.parametrize("body", [
    "",  # 대상 표 누락은 빈 표가 아니다.
    "INSERT INTO public.glossary_images VALUES (1, 'private.png');\n",
    "COPY public.glossary_images (id) FROM stdin;\n1\n\\.\n",
    "COPY public.glossary_images (storage_path) FROM stdin;\nprivate.png\n",
    "COPY public.glossary_images (id, storage_path) FROM stdin;\n1\n\\.\n",
    "COPY public.glossary_images (storage_path) FROM stdin;\n\\N\n\\.\n",
    "COPY public.glossary_images (storage_path) FROM stdin;\n\\.\n" * 2,
])
def test_bad_dump_fails_before_network_without_leaking_data(tmp_path, monkeypatch, capsys, body):
    dump = tmp_path / "data.sql"
    dump.write_text(body, encoding="utf-8")
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test")
    def no_network(*args):
        pytest.fail("Invalid dump must fail before accessing Storage")
    monkeypatch.setattr(backup_images, "make_fetch", no_network)
    assert backup_images.main([
        "--bucket", "g", "--table", "glossary_images", "--dump", str(dump), "--out", str(tmp_path / "out"),
    ]) == 1
    captured = capsys.readouterr()
    assert "private.png" not in captured.out + captured.err
    assert not (tmp_path / "out/manifest.json").exists()


def test_empty_dump_table_is_valid_and_new_objects_are_extra(tmp_path, monkeypatch):
    fake = FakeStorage({"added-after-dump.png": b"new"}, [])
    assert _run_main(tmp_path, monkeypatch, fake) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rows"] == 0
    assert manifest["row_source"] == "database_dump"
    assert manifest["extra_files"] == ["added-after-dump.png"]
