import json
import urllib.error

import pytest

from scripts import backup_images
from scripts.backup_images import BackupError, compare, list_objects, list_row_paths, run, safe_target


class FakeStorage:
    """Storage 목록·다운로드와 REST 행 조회를 흉내 낸다. 받은 호출을 기록한다."""

    def __init__(self, objects: dict[str, bytes], rows: list[str], page_size: int = backup_images.PAGE_SIZE):
        self.objects = objects
        self.rows = rows
        self.page_size = page_size
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, url: str, body: dict | None) -> bytes:
        self.calls.append((method, url, body))
        if url.startswith("/storage/v1/object/list/"):
            return json.dumps(self._list(body["prefix"], body["offset"], body["limit"])).encode()
        if url.startswith("/storage/v1/object/authenticated/"):
            path = url.split("/", 6)[6]
            return self.objects[backup_images.urllib.parse.unquote(path)]
        if url.startswith("/rest/v1/"):
            query = backup_images.urllib.parse.parse_qs(url.split("?", 1)[1])
            offset, limit = int(query["offset"][0]), int(query["limit"][0])
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


def test_list_objects_walks_folders():
    fake = FakeStorage({"a.png": b"1", "n1/b.png": b"2", "n1/sub/c.png": b"3"}, [])

    assert sorted(list_objects(fake, "glossary")) == ["a.png", "n1/b.png", "n1/sub/c.png"]


def test_list_objects_pages(monkeypatch):
    monkeypatch.setattr(backup_images, "PAGE_SIZE", 2)
    fake = FakeStorage({f"f{i}.png": b"x" for i in range(5)}, [])

    assert len(list_objects(fake, "glossary")) == 5
    assert [c[2]["offset"] for c in fake.calls] == [0, 2, 4]


def test_list_row_paths_pages(monkeypatch):
    monkeypatch.setattr(backup_images, "PAGE_SIZE", 2)
    fake = FakeStorage({}, ["a", "b", "c", "d"])

    assert list_row_paths(fake, "note_images") == ["a", "b", "c", "d"]
    # 마지막 쪽이 꽉 찼으면 빈 쪽을 한 번 더 받아 끝을 확인한다.
    assert len(fake.calls) == 3


def test_list_row_paths_rejects_other_tables():
    with pytest.raises(BackupError):
        list_row_paths(FakeStorage({}, []), "profiles")


def test_compare_reports_both_directions():
    result = compare(["a", "b"], ["b", "c"])

    assert (result.files, result.rows) == (2, 2)
    assert result.missing_files == ["c"]
    assert result.extra_files == ["a"]
    assert not result.matches


@pytest.mark.parametrize("path", ["../x.png", "/etc/x", "a/../../x", "a//b", "./a", "", "a\\..\\x", "a/"])
def test_safe_target_rejects_escape(tmp_path, path):
    with pytest.raises(BackupError):
        safe_target(tmp_path, path)


def test_run_downloads_and_writes_manifest(tmp_path):
    fake = FakeStorage({"n1/한글 이름.png": b"img1", "n2/b.png": b"img2"}, ["n1/한글 이름.png", "n2/b.png"])

    result = run(fake, "note-images", "note_images", tmp_path)

    assert result.matches
    assert (tmp_path / "files" / "n1" / "한글 이름.png").read_bytes() == b"img1"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == 2 and manifest["rows"] == 2 and manifest["matches"] is True
    # 다운로드 URL에서 경로의 공백·한글은 인코딩하고 폴더 구분자는 남긴다.
    download_urls = [c[1] for c in fake.calls if "/authenticated/" in c[1]]
    assert "/storage/v1/object/authenticated/note-images/n1/%ED%95%9C%EA%B8%80%20%EC%9D%B4%EB%A6%84.png" in download_urls


def test_main_exit_code_on_mismatch(tmp_path, monkeypatch, capsys):
    fake = FakeStorage({"a.png": b"1"}, ["a.png", "b.png"])
    monkeypatch.setattr(backup_images, "make_fetch", lambda url, key: fake)
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret-value")

    code = backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path)])

    out = capsys.readouterr()
    assert code == backup_images.EXIT_MISMATCH
    assert "파일 1개, 행 2개, 파일 없음 1개, 행 없음 0개" in out.out
    # 공개 로그에 경로와 키가 찍히지 않는다.
    assert "b.png" not in out.out + out.err
    assert "test-secret-value" not in out.out + out.err


def test_main_requires_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)

    assert backup_images.main(["--bucket", "g", "--table", "glossary_images", "--out", str(tmp_path)]) == 2


def test_fetch_hides_response_body(monkeypatch):
    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(backup_images.urllib.request, "urlopen", raise_http_error)
    fetch = backup_images.make_fetch("https://example.test", "test-secret-value")

    with pytest.raises(BackupError) as error:
        fetch("GET", "/rest/v1/note_images?select=storage_path", None)

    assert str(error.value) == "Supabase 응답 404: GET /rest/v1/note_images"
