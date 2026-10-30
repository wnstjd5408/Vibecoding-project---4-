"""Supabase Storage 버킷 하나의 파일을 내려받고, 이미지 표의 행과 대조한다(MEG-94).

DB 덤프에는 Storage 파일이 들어 있지 않아서 따로 받는다. 백업 워크플로(.github/workflows/db-backup.yml)가
부르고, 받은 폴더를 S3 백업 버킷에 올린다. 운영자 PC에서도 같은 명령으로 실행할 수 있다.

    python backend/scripts/backup_images.py --bucket <버킷> --table glossary_images --out <폴더>

환경변수: SUPABASE_URL, SUPABASE_SECRET_KEY. 키는 출력하지 않는다.
표준 라이브러리만 쓴다. 워크플로가 의존성 설치 없이 실행하게 하려는 것이다.

종료 코드: 0 = 파일과 행이 일치, 3 = 불일치(파일은 모두 받았다), 그 밖 = 실행 실패.
대조 결과는 <폴더>/manifest.json에 쓰고, 표준 출력에는 개수만 찍는다(공개 로그).
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
EXIT_MISMATCH = 3

# (method, url, json body 또는 None) -> 응답 본문
Fetch = Callable[[str, str, dict | None], bytes]


class BackupError(Exception):
    """설정 오류나 Supabase 응답 오류. 메시지에 키나 응답 본문을 넣지 않는다."""


@dataclass(frozen=True)
class Comparison:
    files: int
    rows: int
    missing_files: list[str]  # 행은 있는데 파일이 없다
    extra_files: list[str]  # 파일은 있는데 행이 없다

    @property
    def matches(self) -> bool:
        return not self.missing_files and not self.extra_files


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
            # 응답 본문에 경로가 들어 있을 수 있어 상태 코드만 남긴다.
            raise BackupError(f"Supabase 응답 {error.code}: {method} {url.split('?')[0]}") from None
        except urllib.error.URLError as error:
            raise BackupError(f"Supabase 연결 실패: {type(error.reason).__name__}") from None

    return fetch


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))


def list_objects(fetch: Fetch, bucket: str, prefix: str = "") -> list[str]:
    """버킷의 모든 파일 경로. Storage 목록 API는 폴더를 한 단계씩만 보여 줘서 폴더마다 다시 부른다.

    폴더 항목은 id가 null이다(Supabase Storage API 동작).
    """
    paths: list[str] = []
    offset = 0
    while True:
        body = {"prefix": prefix, "limit": PAGE_SIZE, "offset": offset, "sortBy": {"column": "name", "order": "asc"}}
        items = json.loads(fetch("POST", f"/storage/v1/object/list/{urllib.parse.quote(bucket, safe='')}", body))
        for item in items:
            name = f"{prefix}{item['name']}"
            if item.get("id") is None:
                paths.extend(list_objects(fetch, bucket, f"{name}/"))
            else:
                paths.append(name)
        if len(items) < PAGE_SIZE:
            return paths
        offset += PAGE_SIZE


def list_row_paths(fetch: Fetch, table: str) -> list[str]:
    """이미지 표의 storage_path 전부. id 순으로 나눠 받는다."""
    if table not in TABLES:
        raise BackupError(f"허용하지 않는 표: {table}")
    paths: list[str] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"select": "storage_path", "order": "id", "limit": PAGE_SIZE, "offset": offset})
        rows = json.loads(fetch("GET", f"/rest/v1/{table}?{query}", None))
        paths.extend(row["storage_path"] for row in rows)
        if len(rows) < PAGE_SIZE:
            return paths
        offset += PAGE_SIZE


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


def download_all(fetch: Fetch, bucket: str, paths: list[str], out_dir: Path) -> None:
    quoted_bucket = urllib.parse.quote(bucket, safe="")
    for path in paths:
        target = safe_target(out_dir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetch("GET", f"/storage/v1/object/authenticated/{quoted_bucket}/{_quote_path(path)}", None))


def compare(file_paths: list[str], row_paths: list[str]) -> Comparison:
    """파일 목록과 행의 storage_path를 경로 단위로 대조한다. storage_path는 버킷 안 경로다."""
    files = set(file_paths)
    rows = set(row_paths)
    return Comparison(
        files=len(file_paths),
        rows=len(row_paths),
        missing_files=sorted(rows - files),
        extra_files=sorted(files - rows),
    )


def run(fetch: Fetch, bucket: str, table: str, out_dir: Path) -> Comparison:
    files_dir = out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    object_paths = list_objects(fetch, bucket)
    download_all(fetch, bucket, object_paths, files_dir)
    result = compare(object_paths, list_row_paths(fetch, table))
    manifest = {
        "bucket": bucket,
        "table": table,
        "files": result.files,
        "rows": result.rows,
        "matches": result.matches,
        "missing_files": result.missing_files,
        "extra_files": result.extra_files,
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

    # 공개 로그에는 개수만 남긴다. 경로 목록은 manifest.json(비공개 버킷)에만 있다.
    print(
        f"{args.table}: 파일 {result.files}개, 행 {result.rows}개, "
        f"파일 없음 {len(result.missing_files)}개, 행 없음 {len(result.extra_files)}개"
    )
    return 0 if result.matches else EXIT_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
