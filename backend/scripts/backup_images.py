"""Supabase Storage 버킷 하나의 파일을 내려받고, 이미지 표의 행과 대조한다(MEG-94).

DB 덤프에는 Storage 파일이 들어 있지 않아서 따로 받는다. 백업 워크플로(.github/workflows/db-backup.yml)가
부르고, 받은 폴더를 S3 백업 버킷에 올린다. 운영자 PC에서도 같은 명령으로 실행할 수 있다.

    python backend/scripts/backup_images.py --bucket <버킷> --table glossary_images --out <폴더>

환경변수: SUPABASE_URL, SUPABASE_SECRET_KEY. 키는 출력하지 않는다.
표준 라이브러리만 쓴다. 워크플로가 의존성 설치 없이 실행하게 하려는 것이다.

종료 코드: 0 = 행마다 파일이 있다, 3 = 파일이 없는 행이 있다(받은 파일은 모두 남는다), 그 밖 = 실행 실패.
행이 없는 파일은 실패로 보지 않는다. 이미지 행을 지운 뒤 Storage 객체는 storage_delete_jobs가 나중에
지우므로(기술 검토 4절) 그 사이에는 정상적으로 생긴다. 목록을 받은 뒤 지워져 다운로드가 404인 파일은
건너뛰고 개수만 남긴다. 개수는 manifest.json과 출력에 남긴다.
공개 로그에는 개수만 찍는다. 경로 목록은 <폴더>/manifest.json에만 쓴다.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# 이미지 경로를 담은 표. 다른 표 이름은 받지 않는다(REST 경로에 그대로 들어가기 때문이다).
TABLES = frozenset({"note_images", "glossary_images"})
PAGE_SIZE = 1000
TIMEOUT_SECONDS = 30
EXIT_MISSING = 3
# 서버가 offset을 무시해 같은 쪽을 계속 돌려줄 때 끝없이 돌지 않게 하는 상한
MAX_ITEMS = 1_000_000
# Supabase 대시보드에서 폴더를 만들면 생기는 빈 객체. 이미지가 아니다.
PLACEHOLDER_NAME = ".emptyFolderPlaceholder"

# (method, url, json body 또는 None) -> 응답 본문
Fetch = Callable[[str, str, dict | None], bytes]


class BackupError(Exception):
    """설정 오류나 Supabase 응답 오류. 메시지에 키·객체 경로·응답 본문을 넣지 않는다."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Comparison:
    files: int
    rows: int
    missing_files: list[str]  # 행은 있는데 파일이 없다 — 백업이 빠진 것이다
    extra_files: list[str]  # 파일은 있는데 행이 없다 — 삭제 대기 중일 수 있다
    vanished_files: int = 0  # 목록에는 있었는데 다운로드 때 404 — 그 사이 지워졌다

    @property
    def complete(self) -> bool:
        return not self.missing_files


def _endpoint_kind(url: str) -> str:
    """오류 메시지에 쓸 요청 종류. 다운로드 URL에는 객체 경로가 들어 있어 그대로 쓰지 않는다."""
    if url.startswith("/storage/v1/object/list/"):
        return "Storage 목록"
    if url.startswith("/storage/v1/object/"):
        return "Storage 다운로드"
    if url.startswith("/rest/v1/"):
        return "REST 조회"
    return "기타"


def _status(error: urllib.error.HTTPError) -> int:
    """응답 상태. Storage는 없는 객체를 400과 본문 statusCode "404"(error "not_found")로 주기도 해서 404로 바꾼다.

    본문은 상태 판단에만 쓰고 메시지·로그에는 넣지 않는다.
    """
    if error.code != 400:
        return error.code
    try:
        body = json.loads(error.read())
    except (ValueError, OSError, AttributeError):
        return 400
    if isinstance(body, dict) and (str(body.get("statusCode")) == "404" or body.get("error") == "not_found"):
        return 404
    return 400


def make_fetch(base_url: str, secret_key: str) -> Fetch:
    """Supabase 호출 함수. 헤더는 backend/app/supabase.py와 같게 apikey와 Bearer에 secret key를 둔다."""
    headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}

    def fetch(method: str, url: str, body: dict | None) -> bytes:
        data = None
        request_headers = dict(headers)
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{base_url}{url}", data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise BackupError(f"Supabase 응답 {error.code}: {_endpoint_kind(url)}", status=_status(error)) from None
        except (urllib.error.URLError, OSError) as error:
            # 연결 실패, 본문을 읽다 끊김·시간 초과
            raise BackupError(f"Supabase 연결 실패({type(error).__name__}): {_endpoint_kind(url)}") from None

    return fetch


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))


def list_objects(fetch: Fetch, bucket: str, prefix: str = "") -> list[str]:
    """버킷의 모든 파일 경로. Storage 목록 API는 폴더를 한 단계씩만 보여 줘서 폴더마다 다시 부른다.

    폴더 항목은 id가 null이다(Supabase Storage API 동작). 서버 상한이 PAGE_SIZE보다 작아도 빠지지 않게
    빈 쪽이 올 때까지 받는다.
    """
    paths: list[str] = []
    offset = 0
    while True:
        body = {"prefix": prefix, "limit": PAGE_SIZE, "offset": offset, "sortBy": {"column": "name", "order": "asc"}}
        items = json.loads(fetch("POST", f"/storage/v1/object/list/{urllib.parse.quote(bucket, safe='')}", body))
        if not items:
            return paths
        for item in items:
            name = f"{prefix}{item['name']}"
            if item.get("id") is None:
                paths.extend(list_objects(fetch, bucket, f"{name}/"))
            elif item["name"] != PLACEHOLDER_NAME:
                paths.append(name)
        offset += len(items)
        if offset > MAX_ITEMS:
            raise BackupError("Storage 목록이 끝나지 않는다")


def list_row_paths(fetch: Fetch, table: str) -> list[str]:
    """이미지 표의 storage_path 전부. id 순으로, 빈 쪽이 올 때까지 나눠 받는다."""
    if table not in TABLES:
        raise BackupError(f"허용하지 않는 표: {table}")
    paths: list[str] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"select": "storage_path", "order": "id", "limit": PAGE_SIZE, "offset": offset})
        rows = json.loads(fetch("GET", f"/rest/v1/{table}?{query}", None))
        if not rows:
            return paths
        paths.extend(row["storage_path"] for row in rows)
        offset += len(rows)
        if offset > MAX_ITEMS:
            raise BackupError("REST 조회가 끝나지 않는다")


def safe_target(out_dir: Path, object_path: str) -> Path:
    """내려받을 위치. 객체 이름에 ..나 절대 경로가 있으면 거부한다(백업 폴더 밖에 쓰지 않는다)."""
    # PurePosixPath는 "a//b"·"./a"를 조용히 정규화하므로 원문을 직접 나눠 검사한다.
    parts = object_path.split("/")
    if any(part in ("", ".", "..") or "\\" in part for part in parts):
        raise BackupError("허용하지 않는 객체 경로가 있다")
    target = out_dir.joinpath(*parts)
    if not target.resolve().is_relative_to(out_dir.resolve()):
        raise BackupError("허용하지 않는 객체 경로가 있다")
    return target


def download_all(fetch: Fetch, bucket: str, paths: list[str], out_dir: Path) -> list[str]:
    """받은 파일 경로를 돌려준다. 그 사이 지워져 404인 파일은 빠진다."""
    quoted_bucket = urllib.parse.quote(bucket, safe="")
    # 받기 전에 모든 경로를 검사해 나쁜 이름이 하나라도 있으면 아무것도 쓰지 않는다.
    targets = [(path, safe_target(out_dir, path)) for path in paths]
    downloaded: list[str] = []
    for path, target in targets:
        try:
            content = fetch("GET", f"/storage/v1/object/authenticated/{quoted_bucket}/{_quote_path(path)}", None)
        except BackupError as error:
            # 없는 객체는 _status가 404로 맞춘다. 다른 400은 요청 오류라 실패로 둔다.
            if error.status == 404:
                continue
            raise
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        downloaded.append(path)
    return downloaded


def compare(file_paths: list[str], row_paths: list[str], vanished_files: int = 0) -> Comparison:
    """받은 파일과 행의 storage_path를 경로 단위로 대조한다. storage_path는 버킷 안 경로다."""
    files = set(file_paths)
    rows = set(row_paths)
    return Comparison(
        files=len(file_paths),
        rows=len(row_paths),
        missing_files=sorted(rows - files),
        extra_files=sorted(files - rows),
        vanished_files=vanished_files,
    )


def run(fetch: Fetch, bucket: str, table: str, out_dir: Path) -> Comparison:
    files_dir = out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    # 행을 먼저 읽고 바로 목록을 받는다. 그 사이 올라온 이미지는 "행 없는 파일"(경고)로만 잡힌다.
    # 반대 순서면 "파일 없는 행"(실패)으로 잡힌다.
    row_paths = list_row_paths(fetch, table)
    object_paths = list_objects(fetch, bucket)
    downloaded = download_all(fetch, bucket, object_paths, files_dir)
    result = compare(downloaded, row_paths, vanished_files=len(object_paths) - len(downloaded))
    manifest = {
        "bucket": bucket,
        "table": table,
        "files": result.files,
        "rows": result.rows,
        "complete": result.complete,
        "missing_files": result.missing_files,
        "extra_files": result.extra_files,
        "vanished_files": result.vanished_files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--table", required=True, choices=sorted(TABLES))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not base_url or not secret_key:
        print("SUPABASE_URL과 SUPABASE_SECRET_KEY가 필요하다", file=sys.stderr)
        return 2

    try:
        result = run(make_fetch(base_url, secret_key), args.bucket, args.table, args.out)
    except BackupError as error:
        print(f"이미지 백업 실패: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 — 공개 로그에 traceback(경로가 들어갈 수 있다)을 남기지 않는다
        print(f"이미지 백업 실패: {type(error).__name__}", file=sys.stderr)
        return 1

    print(
        f"{args.table}: 파일 {result.files}개, 행 {result.rows}개, "
        f"파일 없는 행 {len(result.missing_files)}개, 행 없는 파일 {len(result.extra_files)}개, "
        f"받는 중 지워진 파일 {result.vanished_files}개"
    )
    return 0 if result.complete else EXIT_MISSING


if __name__ == "__main__":
    sys.exit(main())
