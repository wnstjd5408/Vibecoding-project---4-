import json
import urllib.error

import pytest

from scripts import backup_images
from scripts.backup_images import BackupError, compare, list_objects, list_row_paths, run, safe_target


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


def test_list_row_paths_survives_smaller_server_limit():
    # 서버 max_rows(2)가 요청 limit(1000)보다 작아도 짧은 쪽에서 멈추지 않는다.
    fake = FakeStorage({}, ["a", "b", "c", "d", "e"], server_limit=2)

    assert list_row_paths(fake, "note_images") == ["a", "b", "c", "d", "e"]


def test_list_row_paths_rejects_other_tables():
    with pytest.raises(BackupError):
        list_row_paths(FakeStorage({}, []), "profiles")


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
        run(fake, "glossary", "glossary_images", tmp_path)

    assert not (tmp_path / "files" / "ok.png").exists()
    assert not any(c for c in fake.calls if "/authenticated/" in c[1])


def test_run_reads_rows_before_downloading(tmp_path):
    fake = FakeStorage({"a.png": b"1"}, ["a.png"])

    run(fake, "glossary", "glossary_images", tmp_path)

    kinds = [("rest" if "/rest/" in c[1] else "download" if "/authenticated/" in c[1] else "list") for c in fake.calls]
    assert kinds.index("rest") < kinds.index("download")


def test_run_downloads_and_writes_manifest(tmp_path):
    fake = FakeStorage({"n1/한글 이름.png": b"img1", "n2/b.png": b"img2"}, ["n1/한글 이름.png", "n2/b.png"])

    result = run(fake, "note-images", "note_images", tmp_path)

    assert result.complete
    assert (tmp_path / "files" / "n1" / "한글 이름.png").read_bytes() == b"img1"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == 2 and manifest["rows"] == 2 and manifest["complete"] is True
    # 다운로드 URL에서 경로의 공백·한글은 인코딩하고 폴더 구분자는 남긴다.
    download_urls = [c[1] for c in fake.calls if "/authenticated/" in c[1]]
    assert "/storage/v1/object/authenticated/note-images/n1/%ED%95%9C%EA%B8%80%20%EC%9D%B4%EB%A6%84.png" in download_urls


def _run_main(tmp_path, monkeypatch, fake):
    monkeypatch.setattr(backup_images, "make_fetch", lambda url, key: fake)
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret-value")
    return backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path)])


def test_main_exit_code_when_rows_have_no_file(tmp_path, monkeypatch, capsys):
    code = _run_main(tmp_path, monkeypatch, FakeStorage({"a.png": b"1"}, ["a.png", "b.png"]))

    out = capsys.readouterr()
    assert code == backup_images.EXIT_MISSING
    assert "파일 1개, 행 2개, 파일 없는 행 1개, 행 없는 파일 0개" in out.out
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

    code = _run_main(tmp_path, monkeypatch, broken)

    out = capsys.readouterr()
    assert code == 1
    assert out.err.strip() == "이미지 백업 실패: TimeoutError"
    assert "secret-name" not in out.out + out.err


def test_main_requires_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)

    assert backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path)]) == 2


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
