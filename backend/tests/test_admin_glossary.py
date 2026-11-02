"""E19~E23 운영자 사전 (MEG-81). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

SQL 함수 자체(트랜잭션, 무효화, 남는 데이터)는 tests/integration/test_glossary_admin_sql.py가 일회용 DB로 시험한다.
여기서는 권한·검사 순서·오류 응답·Storage 순서를 본다. 가짜는 SQL 함수와 같은 결과 모양을 낸다.
"""

import zlib
from dataclasses import dataclass, field
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app import admin_glossary
from app.common import install_common_layer
from app.images import MAX_UPLOAD_BYTES
from app.rate_limit import WRITE
from app.supabase import SupabaseConfigError, SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin

OPERATOR = "00000000-0000-0000-0000-0000000000a1"
MEMBER = "00000000-0000-0000-0000-0000000000b1"
GLOSSARY_TERM = 7
AI_TERM = 9
MISSING_TERM = 99


@dataclass
class FakeAdminSupabase(FakeSupabase):
    """terms·glossary_entries·glossary_images·storage_delete_jobs·Storage 객체 흉내."""

    terms: dict[int, dict] = field(default_factory=dict)
    entries: dict[int, dict] = field(default_factory=dict)
    images: dict[int, dict] = field(default_factory=dict)
    jobs: dict[int, dict] = field(default_factory=dict)
    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    # 유효한 AI 설명이 있는 용어 id. E20이 무효화하면 빠진다.
    valid_ai: set[int] = field(default_factory=set)
    upload_down: bool = False
    object_delete_down: bool = False
    add_image_down: bool = False
    # add_glossary_image 직전에 사전 설명을 지운 것처럼 만든다(E21과 겹친 경우).
    entry_vanishes_before_add: bool = False
    writes: list[str] = field(default_factory=list)
    _next_id: int = 100

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def list_admin_glossary_terms(self, limit: int, before_id: int | None) -> list[dict]:
        ids = sorted((tid for tid in self.terms if tid in self.entries), reverse=True)
        if before_id is not None:
            ids = [tid for tid in ids if tid < before_id]
        return [{"id": tid, "key": self.terms[tid]["key"], "label": self.terms[tid]["label"]} for tid in ids[:limit]]

    def glossary_entry_exists(self, term_id: int) -> bool:
        return term_id in self.entries

    def upsert_glossary_entry(self, key: str, label: str, body_markdown: str, updated_by: str) -> dict:
        self.writes.append("upsert")
        term_id = next((tid for tid, term in self.terms.items() if term["key"] == key), None)
        if term_id is None:
            term_id = self._new_id()
        self.terms[term_id] = {"key": key, "label": label, "source": "glossary"}
        created = term_id not in self.entries
        self.entries[term_id] = {"body_markdown": body_markdown, "updated_by": updated_by}
        self.valid_ai.discard(term_id)
        return {"id": term_id, "key": key, "label": label, "created": created}

    def _job(self, path: str) -> dict:
        job_id = self._new_id()
        self.jobs[job_id] = {"object_path": path, "status": "pending"}
        return {"job_id": job_id, "object_path": path}

    def delete_glossary_entry(self, term_id: int) -> list[dict] | None:
        self.writes.append("delete_entry")
        if term_id not in self.entries:
            return None
        jobs = [self._job(img["storage_path"]) for iid, img in sorted(self.images.items()) if img["term_id"] == term_id]
        self.images = {iid: img for iid, img in self.images.items() if img["term_id"] != term_id}
        del self.entries[term_id]
        self.terms[term_id]["source"] = "ai"
        return jobs

    def delete_glossary_image(self, term_id: int, image_id: int) -> dict | None:
        self.writes.append("delete_image")
        image = self.images.get(image_id)
        if image is None or image["term_id"] != term_id:
            return None
        del self.images[image_id]
        return self._job(image["storage_path"])

    def create_glossary_upload_job(self, object_path: str) -> int:
        self.writes.append("job")
        return self._job(object_path)["job_id"]

    def upload_glossary_image(self, object_path: str, data: bytes, content_type: str) -> None:
        self.writes.append("upload")
        if self.upload_down:
            raise SupabaseUnavailable("down")
        self.objects[object_path] = (data, content_type)

    def add_glossary_image(self, term_id: int, object_path: str, alt: str | None, job_id: int) -> int | None:
        self.writes.append("add_image")
        if self.add_image_down:
            raise SupabaseUnavailable("down")
        if self.entry_vanishes_before_add:
            self.entries.pop(term_id, None)
        if term_id not in self.entries:
            return None
        image_id = self._new_id()
        self.images[image_id] = {"term_id": term_id, "storage_path": object_path, "alt": alt}
        self.jobs.pop(job_id)
        return image_id

    def remove_glossary_objects(self, jobs: list[dict]) -> None:
        if self.object_delete_down:
            raise SupabaseUnavailable("down")
        for job in jobs:
            self.objects.pop(job["object_path"], None)
            self.jobs[job["job_id"]]["status"] = "done"


def build_app(fake: FakeAdminSupabase) -> FastAPI:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(admin_glossary.router)
    return app


@pytest.fixture
def fake() -> FakeAdminSupabase:
    fake = FakeAdminSupabase()
    fake.add_user("operator-token", OPERATOR, role="operator")
    fake.add_user("member-token", MEMBER)
    fake.terms = {
        GLOSSARY_TERM: {"key": "exampleterm", "label": "ExampleTerm", "source": "glossary"},
        AI_TERM: {"key": "aiterm", "label": "AiTerm", "source": "ai"},
    }
    fake.entries = {GLOSSARY_TERM: {"body_markdown": "합성 설명", "updated_by": OPERATOR}}
    fake.images = {
        3: {"term_id": GLOSSARY_TERM, "storage_path": "terms/7/a.png", "alt": None},
        5: {"term_id": GLOSSARY_TERM, "storage_path": "terms/7/b.png", "alt": "합성"},
    }
    fake.objects = {"terms/7/a.png": (b"a", "image/png"), "terms/7/b.png": (b"b", "image/png")}
    fake.valid_ai = {AI_TERM}
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_app(fake))


def auth(token: str | None = "operator-token") -> dict[str, str]:
    return {**origin(), **(cookie(token) if token else {})}


def assert_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def assert_field(response, name: str, reason: str):
    assert_error(response, 422, "validation_failed")
    assert {"name": name, "reason": reason} in [
        {"name": f["name"], "reason": f["reason"]} for f in response.json()["error"]["fields"]
    ]


def image_bytes(fmt: str = "PNG", size=(4, 3), exif: bool = False) -> bytes:
    image = Image.new("RGB", size, (200, 10, 10))
    output = BytesIO()
    if exif:
        data = image.getexif()
        data[0x010E] = "SYNTHETIC-SECRET-DESCRIPTION"
        image.save(output, format=fmt, exif=data)
    else:
        image.save(output, format=fmt)
    return output.getvalue()


def upload(client, data: bytes, content_type: str = "image/png", term=GLOSSARY_TERM, alt=None, token="operator-token"):
    form = {"alt": alt} if alt is not None else {}
    return client.post(
        f"/api/admin/glossary/{term}/images",
        files={"file": ("x.bin", data, content_type)},
        data=form,
        headers=auth(token),
    )


# --- AC-1: 운영자만 쓴다. 방문자 401, 일반 사용자 403, 거부되면 DB를 바꾸지 않는다 ---

CALLS = [
    ("GET", "/api/admin/glossary", None),
    ("POST", "/api/admin/glossary", {"label": "New", "body_markdown": "x"}),
    ("DELETE", f"/api/admin/glossary/{GLOSSARY_TERM}", None),
    ("DELETE", f"/api/admin/glossary/{GLOSSARY_TERM}/images/3", None),
]


@pytest.mark.parametrize("method,path,body", CALLS)
@pytest.mark.parametrize("token,status,code", [(None, 401, "login_required"), ("member-token", 403, "forbidden")])
def test_non_operators_are_rejected_without_writes(client, fake, method, path, body, token, status, code):
    response = client.request(method, path, json=body, headers=auth(token))
    assert_error(response, status, code)
    assert fake.writes == []
    assert fake.rpc_calls == []


@pytest.mark.parametrize("token,status,code", [(None, 401, "login_required"), ("member-token", 403, "forbidden")])
def test_non_operators_cannot_upload_even_with_a_bad_file(client, fake, token, status, code):
    # 권한(검사 순서 3)이 형식 검사(4)보다 먼저다.
    assert_error(upload(client, b"not an image", token=token), status, code)
    assert fake.writes == [] and fake.rpc_calls == []


@pytest.mark.parametrize("method,path", [("POST", "/api/admin/glossary"), ("DELETE", "/api/admin/glossary/7")])
def test_writes_without_allowed_origin_are_rejected(client, fake, method, path):
    response = client.request(method, path, json={"label": "x"}, headers=cookie("operator-token"))
    assert_error(response, 403, "origin_not_allowed")
    assert fake.writes == []


# --- E19 목록 ---


def test_list_returns_only_glossary_terms_newest_first(client, fake):
    fake.upsert_glossary_entry("second", "Second", "", OPERATOR)
    response = client.get("/api/admin/glossary", headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "terms": [
            {"id": 101, "key": "second", "label": "Second"},
            {"id": GLOSSARY_TERM, "key": "exampleterm", "label": "ExampleTerm"},
        ],
        "next_cursor": None,
    }


def test_list_pages_with_cursor(client, fake):
    for label in ("A", "B", "C"):
        fake.upsert_glossary_entry(label.lower(), label, "", OPERATOR)
    first = client.get("/api/admin/glossary", params={"limit": 2}, headers=auth()).json()
    assert [t["id"] for t in first["terms"]] == [103, 102]
    assert first["next_cursor"] == "102"
    second = client.get("/api/admin/glossary", params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth())
    assert [t["id"] for t in second.json()["terms"]] == [101, GLOSSARY_TERM]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize("params,name,reason", [
    ({"limit": 0}, "limit", "out_of_range"),
    ({"limit": 101}, "limit", "out_of_range"),
    ({"limit": "x"}, "limit", "invalid_format"),
    ({"cursor": "abc"}, "cursor", "invalid_format"),
    ({"cursor": "0"}, "cursor", "invalid_format"),
    ({"cursor": str(2**63)}, "cursor", "invalid_format"),
])
def test_list_rejects_bad_paging(client, params, name, reason):
    assert_field(client.get("/api/admin/glossary", params=params, headers=auth()), name, reason)


# --- E20 등록·갱신 (AC-2는 가짜에서 무효화 호출만, SQL 결과는 통합 시험) ---


def test_new_label_creates_a_glossary_term_with_normalized_key(client, fake):
    response = client.post(
        "/api/admin/glossary", json={"label": "  TCP/IP   Stack ", "body_markdown": "설명"}, headers=auth()
    )
    assert response.status_code == 201
    term = response.json()["term"]
    assert term["key"] == "tcp/ip stack" and term["label"] == "TCP/IP   Stack"
    assert fake.entries[term["id"]]["updated_by"] == OPERATOR


def test_same_key_updates_label_and_body_with_200(client, fake):
    response = client.post("/api/admin/glossary", json={"label": "EXAMPLETERM", "body_markdown": "새 설명"}, headers=auth())
    assert response.status_code == 200
    assert response.json() == {"term": {"id": GLOSSARY_TERM, "key": "exampleterm", "label": "EXAMPLETERM"}}
    assert fake.entries[GLOSSARY_TERM]["body_markdown"] == "새 설명"


def test_ai_term_becomes_glossary_and_its_ai_explanation_is_invalidated(client, fake):
    response = client.post("/api/admin/glossary", json={"label": "AiTerm", "body_markdown": "사전"}, headers=auth())
    assert response.status_code == 201
    assert response.json()["term"]["id"] == AI_TERM
    assert fake.terms[AI_TERM]["source"] == "glossary"
    assert AI_TERM not in fake.valid_ai


def test_body_defaults_to_empty(client, fake):
    response = client.post("/api/admin/glossary", json={"label": "Only"}, headers=auth())
    assert response.status_code == 201
    assert fake.entries[response.json()["term"]["id"]]["body_markdown"] == ""


@pytest.mark.parametrize("body,name,reason", [
    ({}, "label", "required"),
    ({"label": ""}, "label", "required"),
    ({"label": "   "}, "label", "required"),
    ({"label": "x" * 201}, "label", "too_long"),
    ({"label": 7}, "label", "invalid_format"),
    ({"label": "x", "body_markdown": "y" * 200_001}, "body_markdown", "too_long"),
    ({"label": "x", "key": "x"}, "body", "invalid_format"),
])
def test_bad_entry_bodies_are_422_without_writes(client, fake, body, name, reason):
    assert_field(client.post("/api/admin/glossary", json=body, headers=auth()), name, reason)
    assert fake.writes == []


def test_writes_count_against_the_write_limit(client, fake):
    client.post("/api/admin/glossary", json={"label": "Count"}, headers=auth())
    assert fake.hits(f"{WRITE.name}:{fake.keyed_hash(f'user:{OPERATOR}')}", WRITE.window_seconds) == 1


# --- E21 사전 설명·이미지 삭제 (AC-3: 용어는 남고 source가 ai) ---


def test_delete_entry_removes_entry_images_and_objects_but_keeps_the_term(client, fake):
    response = client.delete(f"/api/admin/glossary/{GLOSSARY_TERM}", headers=auth())
    assert response.status_code == 204 and response.content == b""
    assert GLOSSARY_TERM not in fake.entries
    assert fake.terms[GLOSSARY_TERM]["source"] == "ai"
    assert fake.images == {} and fake.objects == {}
    assert [job["status"] for job in fake.jobs.values()] == ["done", "done"]


def test_delete_entry_is_204_when_object_delete_fails_and_jobs_stay_pending(client, fake):
    fake.object_delete_down = True
    assert client.delete(f"/api/admin/glossary/{GLOSSARY_TERM}", headers=auth()).status_code == 204
    assert GLOSSARY_TERM not in fake.entries
    assert [job["status"] for job in fake.jobs.values()] == ["pending", "pending"]


@pytest.mark.parametrize("term", [AI_TERM, MISSING_TERM, "0", "abc", str(2**63)])
def test_delete_entry_of_non_glossary_term_is_404(client, fake, term):
    assert_error(client.delete(f"/api/admin/glossary/{term}", headers=auth()), 404, "not_found")
    assert fake.terms[AI_TERM]["source"] == "ai" and fake.jobs == {}


# --- E22 이미지 올리기 ---


def test_upload_stores_a_reencoded_image_and_returns_its_id(client, fake):
    response = upload(client, image_bytes("PNG"), alt="  합성 그림 ")
    assert response.status_code == 201
    image = fake.images[response.json()["id"]]
    assert image["alt"] == "합성 그림"
    assert image["storage_path"].startswith("terms/7/") and image["storage_path"].endswith(".png")
    data, content_type = fake.objects[image["storage_path"]]
    assert content_type == "image/png"
    assert Image.open(BytesIO(data)).size == (4, 3)
    # 성공하면 1단계 삭제 작업은 지워진다.
    assert fake.jobs == {}
    assert fake.writes == ["job", "upload", "add_image"]


def test_jpeg_metadata_is_removed(client, fake):
    original = image_bytes("JPEG", exif=True)
    assert b"SYNTHETIC-SECRET-DESCRIPTION" in original
    response = upload(client, original, content_type="image/jpeg")
    data, content_type = fake.objects[fake.images[response.json()["id"]]["storage_path"]]
    assert content_type == "image/jpeg"
    assert b"SYNTHETIC-SECRET-DESCRIPTION" not in data
    assert not Image.open(BytesIO(data)).getexif()


def test_format_comes_from_content_not_the_declared_type(client, fake):
    response = upload(client, image_bytes("WEBP"), content_type="image/gif")
    assert response.status_code == 201
    assert fake.objects[fake.images[response.json()["id"]]["storage_path"]][1] == "image/webp"


def test_empty_alt_is_stored_as_null(client, fake):
    response = upload(client, image_bytes(), alt="   ")
    assert fake.images[response.json()["id"]]["alt"] is None


@pytest.mark.parametrize("data,status,code", [
    (b"\x89PNG" + b"0" * MAX_UPLOAD_BYTES, 413, "payload_too_large"),
    (b"plain text, not an image", 415, "unsupported_media_type"),
    (image_bytes("GIF"), 415, "unsupported_media_type"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", 415, "unsupported_media_type"),
], ids=["over_4mb", "text", "gif", "svg"])
def test_rejected_files_write_nothing(client, fake, data, status, code):
    assert_error(upload(client, data), status, code)
    assert fake.writes == []


def test_broken_image_is_422_invalid_format(client, fake):
    broken = image_bytes("PNG", size=(64, 64))[:60]
    assert_field(upload(client, broken), "file", "invalid_format")
    assert fake.writes == []


def test_too_many_pixels_is_422_invalid_format(client, fake):
    assert_field(upload(client, image_bytes("PNG", size=(8001, 1))), "file", "invalid_format")


@pytest.mark.parametrize("term", [AI_TERM, MISSING_TERM, "abc"])
def test_upload_to_non_glossary_term_is_404_before_any_write(client, fake, term):
    assert_error(upload(client, image_bytes(), term=term), 404, "not_found")
    assert fake.writes == []


def test_missing_file_and_long_alt_are_422(client):
    response = client.post(f"/api/admin/glossary/{GLOSSARY_TERM}/images", data={"alt": "x"}, headers=auth())
    assert_field(response, "file", "required")
    assert_field(upload(client, image_bytes(), alt="x" * 1001), "alt", "too_long")


def test_upload_failure_is_503_and_leaves_the_pending_job(client, fake):
    fake.upload_down = True
    assert_error(upload(client, image_bytes()), 503, "service_unavailable")
    assert [job["status"] for job in fake.jobs.values()] == ["pending"]
    assert len(fake.images) == 2


def test_db_failure_after_upload_is_500_not_503(client, fake):
    fake.add_image_down = True
    assert_error(upload(client, image_bytes()), 500, "internal_error")
    # 작업이 남아 올린 객체를 지울 대상이 된다.
    assert [job["status"] for job in fake.jobs.values()] == ["pending"]


def test_entry_deleted_during_upload_is_404_and_the_object_is_removed(client, fake):
    fake.entry_vanishes_before_add = True
    assert_error(upload(client, image_bytes()), 404, "not_found")
    assert [job["status"] for job in fake.jobs.values()] == ["done"]
    assert set(fake.objects) == {"terms/7/a.png", "terms/7/b.png"}


def test_bucket_not_configured_is_500(client, fake, monkeypatch):
    def broken(*args, **kwargs):
        raise SupabaseConfigError("GLOSSARY_IMAGE_BUCKET is not set or invalid")

    monkeypatch.setattr(fake, "create_glossary_upload_job", broken)
    assert_error(upload(client, image_bytes()), 500, "internal_error")


# --- E23 이미지 삭제 ---


def test_delete_image_removes_row_and_object(client, fake):
    assert client.delete(f"/api/admin/glossary/{GLOSSARY_TERM}/images/3", headers=auth()).status_code == 204
    assert set(fake.images) == {5}
    assert set(fake.objects) == {"terms/7/b.png"}
    assert [job["status"] for job in fake.jobs.values()] == ["done"]


def test_delete_image_is_204_when_object_delete_fails(client, fake):
    fake.object_delete_down = True
    assert client.delete(f"/api/admin/glossary/{GLOSSARY_TERM}/images/3", headers=auth()).status_code == 204
    assert set(fake.images) == {5}
    assert [job["status"] for job in fake.jobs.values()] == ["pending"]


@pytest.mark.parametrize("path", [f"{AI_TERM}/images/3", f"{GLOSSARY_TERM}/images/99", f"{GLOSSARY_TERM}/images/x"])
def test_delete_image_of_another_term_or_missing_is_404(client, fake, path):
    assert_error(client.delete(f"/api/admin/glossary/{path}", headers=auth()), 404, "not_found")
    assert len(fake.images) == 2 and fake.jobs == {}


# --- 리뷰 지적 회귀: 이미지 처리 ---


def test_exif_orientation_is_applied_before_metadata_is_stripped(client, fake):
    # 가로 40x20 픽셀에 Orientation=6(시계 방향 90도)이면 화면에서는 세로 20x40이다.
    image = Image.new("RGB", (40, 20), (200, 10, 10))
    exif = image.getexif()
    exif[0x0112] = 6
    out = BytesIO()
    image.save(out, format="JPEG", exif=exif)
    response = upload(client, out.getvalue(), content_type="image/jpeg")
    stored = Image.open(BytesIO(fake.objects[fake.images[response.json()["id"]]["storage_path"]][0]))
    assert stored.size == (20, 40)
    assert not stored.getexif()


def test_mpo_jpeg_from_phones_is_accepted_as_jpeg(client, fake):
    out = BytesIO()
    first, second = Image.new("RGB", (6, 4), (1, 2, 3)), Image.new("RGB", (6, 4), (9, 9, 9))
    first.save(out, format="MPO", save_all=True, append_images=[second])
    assert Image.open(BytesIO(out.getvalue())).format == "MPO"
    response = upload(client, out.getvalue(), content_type="image/jpeg")
    assert response.status_code == 201
    path = fake.images[response.json()["id"]]["storage_path"]
    assert path.endswith(".jpg") and fake.objects[path][1] == "image/jpeg"


def test_huge_declared_dimensions_are_422_not_415(client, fake):
    # 머리말만 20000x20000인 PNG. Pillow가 압축 폭탄으로 거절하는 크기다.
    header = image_bytes("PNG", size=(1, 1))
    ihdr = (20000).to_bytes(4, "big") * 2 + header[24:29]
    crc = zlib.crc32(b"IHDR" + ihdr).to_bytes(4, "big")
    wide = header[:16] + ihdr + crc + header[33:]
    assert_field(upload(client, wide), "file", "invalid_format")
    assert fake.writes == []


def test_opaque_png_stays_small_and_transparent_png_keeps_alpha(client, fake):
    opaque = upload(client, image_bytes("PNG", size=(32, 32)))
    stored = Image.open(BytesIO(fake.objects[fake.images[opaque.json()["id"]]["storage_path"]][0]))
    assert stored.mode == "RGB"
    out = BytesIO()
    Image.new("RGBA", (4, 4), (1, 2, 3, 0)).save(out, format="PNG")
    transparent = upload(client, out.getvalue())
    stored = Image.open(BytesIO(fake.objects[fake.images[transparent.json()["id"]]["storage_path"]][0]))
    assert stored.mode == "RGBA" and stored.getpixel((0, 0))[3] == 0


# --- 리뷰 지적 회귀: NUL 문자는 500이 아니라 422 ---


@pytest.mark.parametrize("body,name", [
    ({"label": "a\x00b"}, "label"),
    ({"label": "ok", "body_markdown": "a\x00b"}, "body_markdown"),
])
def test_nul_characters_are_422(client, fake, body, name):
    response = client.post("/api/admin/glossary", json=body, headers=auth())
    assert_error(response, 422, "validation_failed")
    assert response.json()["error"]["fields"][0]["name"] == name
    assert fake.writes == []


def test_nul_in_alt_is_422(client, fake):
    assert_field(upload(client, image_bytes(), alt="a\x00b"), "alt", "invalid_format")
    assert fake.writes == []
