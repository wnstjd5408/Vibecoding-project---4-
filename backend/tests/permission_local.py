"""Disposable worktree-local Auth/REST/Storage fixtures for MEG-69.

Only the stack prepared by scripts.local_backend in THIS worktree is accepted.
No remote URL/key is accepted and no credentials are printed. No auth/role,
rate-limit, REST, RPC or Storage implementation is mocked.
"""

import hashlib
import io
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app import quiz, session
from app.ai_explain import AiRuntime, get_ai_runtime
from app.ai_ledger import SupabaseLedgerStore
from app.config import REFRESH_COOKIE, SESSION_COOKIE
from app.main import app
from app.supabase import SupabaseClient, get_supabase
from scripts import local_backend

ORIGIN = {"Origin": "http://localhost:5173"}
NOTE, PRIVATE, TERM, AI_TERM, EXPLANATION, IMAGE, REPORT = range(69001, 69008)
BUCKET = "meg69-glossary"
NOTE_BUCKET = "meg69-notes"
PUBLIC_TABLES = (
    "profiles", "subjects", "notes", "note_subjects", "note_sources", "note_images",
    "terms", "glossary_entries", "glossary_images", "term_views", "favorites",
    "favorite_events", "ai_explanations", "ai_usage_ledger", "quiz_sets",
    "quiz_set_terms", "quiz_items", "quiz_answers", "quiz_followups", "reports",
    "storage_delete_jobs",
)


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def no_ai(*args, **kwargs):
    raise AssertionError("Permission fixtures must not call an external AI service")


class LocalMatrix:
    def __init__(self):
        # Identity check occurs before any SQL or HTTP mutation.
        self.url, key = local_backend.connection()
        self.container = f"supabase_db_{local_backend.project_id()}"
        self.calls = []
        self.http = httpx.Client(trust_env=False, follow_redirects=False, timeout=15,
                                 event_hooks={"request": [self.audit]})
        self.db = SupabaseClient(self.url, key, http=self.http,
                                 note_image_bucket=NOTE_BUCKET, glossary_image_bucket=BUCKET)
        self.users = {}
        self.cookies = {}
        self.password = secrets.token_urlsafe(24)
        self.created = []
        self.bucket_created = []
        self.tag = uuid4().hex
        self.seeded = False

    def audit(self, request):
        assert str(request.url).startswith(self.url + "/"), "remote request forbidden"
        self.calls.append((request.method, request.url.path))

    def sql(self, query):
        local_backend.docker_local()
        return local_backend.run(["docker", "exec", "-i", self.container, "psql", "-U", "postgres",
                                  "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-qAt"], input_text=query).strip()

    def request(self, method, path, **kwargs):
        response = self.db._request(method, path, headers=self.db._headers(), **kwargs)
        assert response.status_code < 300, f"Fixture {method} failed: HTTP {response.status_code}"
        return response

    def setup(self):
        # Refuse to overwrite existing fixtures, even in the correct local project.
        assert self.sql(f"select count(*) from notes where id in ({NOTE},{PRIVATE});") == "0"
        assert self.sql(f"select count(*) from terms where id in ({TERM},{AI_TERM});") == "0"
        assert self.sql(f"select count(*) from ai_explanations where id={EXPLANATION};") == "0"
        assert self.sql(f"select count(*) from reports where id={REPORT};") == "0"
        assert self.sql(f"select count(*) from glossary_images where id={IMAGE};") == "0"
        assert self.sql("select count(*) from quiz_sets where id between 69201 and 69203;") == "0"
        assert self.sql("select count(*) from quiz_items where id between 69101 and 69103;") == "0"
        for bucket, public in ((BUCKET, True), (NOTE_BUCKET, False)):
            self.request("POST", "/storage/v1/bucket", json={"id": bucket, "name": bucket, "public": public})
            self.bucket_created.append(bucket)
        for index, role in enumerate(("operator", "member", "inactive")):
            email = f"meg69-{role}-{self.tag}@example.test"
            uid = self.db.create_auth_user(email, self.password)
            self.created.append(uid)
            self.users[role] = {"id": uid, "email": email, "item": 69101 + index, "set": 69201 + index}
            self.request("POST", "/rest/v1/profiles", json={
                "user_id": uid, "role": "operator" if role == "operator" else "member",
                "is_active": True, "display_name": f"Synthetic {role}",
            })
            with TestClient(app, base_url="https://testserver") as client:
                result = client.post("/api/auth/login", headers=ORIGIN, json={"email": email, "password": self.password})
                assert result.status_code == 200, f"Fixture login: HTTP {result.status_code}"
                self.cookies[role] = dict(client.cookies)
        uid = self.users["inactive"]["id"]
        self.request("PATCH", f"/rest/v1/profiles?user_id=eq.{uid}", json={"is_active": False})

    def reset(self):
        ids = ",".join(f"'{u['id']}'" for u in self.users.values())
        # Only this suite's users/objects; rate counters belong to the disposable stack.
        self.sql(f"""
          delete from reports where user_id in ({ids});
          delete from quiz_sets where user_id in ({ids});
          delete from ai_explanations where id = {EXPLANATION};
          delete from terms where id in ({TERM},{AI_TERM}) or key like 'meg69 {self.tag}%';
          delete from notes where id in ({NOTE},{PRIVATE});
          delete from storage_delete_jobs where bucket in ('{BUCKET}','{NOTE_BUCKET}');
          delete from rate_limit_counters;
        """)
        for bucket in self.bucket_created:
            self.request("POST", f"/storage/v1/bucket/{bucket}/empty", json={})

    def seed(self):
        self.seeded = True
        self.reset()
        owner = self.users["member"]["id"]
        self.sql(f"""
          insert into notes(id,title,body_markdown,is_published) overriding system value values
            ({NOTE},'MEG69 public','MatrixTerm is synthetic.',true),
            ({PRIVATE},'MEG69 private','MatrixTerm is synthetic.',false);
          insert into terms(id,key,label,source) overriding system value values
            ({TERM},'matrix glossary','Matrix glossary','glossary'),
            ({AI_TERM},'matrixterm','MatrixTerm','ai');
          insert into glossary_entries(term_id,body_markdown) values ({TERM},'Synthetic dictionary');
          insert into ai_explanations(id,term_id,term_key_snapshot,note_id,note_revision,body,model,prompt_version)
            overriding system value values
            ({EXPLANATION},{AI_TERM},'matrixterm',{NOTE},1,'Synthetic cached explanation','synthetic','fixture-v1');
          insert into reports(id,user_id,ai_explanation_id,body) overriding system value
            values ({REPORT},'{owner}',{EXPLANATION},'Synthetic report');
        """)
        for user in self.users.values():
            self.sql(f"""
              insert into quiz_sets(id,user_id,quiz_date,source_date,status) overriding system value
                values ({user['set']},'{user['id']}','2026-11-03','2026-11-02','ready');
              insert into quiz_set_terms(set_id,term_id,reason) values ({user['set']},{AI_TERM},'favorited');
              insert into quiz_items(id,set_id,term_id,question,answer,explanation,difficulty) overriding system value
                values ({user['item']},{user['set']},{AI_TERM},'Synthetic question','Synthetic answer','Synthetic reason','하');
              insert into quiz_followups(item_id,seq,question) values ({user['item']},1,'Synthetic followup');
            """)
        self.request("POST", f"/storage/v1/object/{BUCKET}/fixture.png", content=png())
        self.request("POST", f"/storage/v1/object/{NOTE_BUCKET}/fixture.png", content=png())
        self.sql(f"""
          insert into glossary_images(id,term_id,storage_path,alt) overriding system value
            values ({IMAGE},{TERM},'fixture.png','Synthetic image');
          insert into note_images(note_id,notion_block_id,storage_path,alt)
            values ({PRIVATE},'69000000-0000-4000-8000-000000000001','fixture.png','Private synthetic image');
        """)

    def snapshot(self):
        # Hash complete row values (not just counts); never print auth records or content.
        queries = [f"select '{t}',coalesce(jsonb_agg(j order by j::text),'[]') from "
                   f"(select to_jsonb(r) j from public.{t} r) q;" for t in PUBLIC_TABLES]
        queries += ["select coalesce(jsonb_agg(id order by id),'[]') from auth.users;",
                    "select coalesce(jsonb_agg(j order by j::text),'[]') from "
                    "(select to_jsonb(r) j from storage.objects r) q;"]
        return hashlib.sha256(self.sql("\n".join(queries)).encode()).hexdigest()

    @contextmanager
    def client(self, role):
        with TestClient(app, base_url="https://testserver") as client:
            if role == "inactive":
                # A fresh real Auth session on every case proves the DB active check,
                # not merely rejection of a token revoked by an earlier case.
                self.renew(role)
            if role in self.cookies:
                client.cookies.update(self.cookies[role])
            elif role == "expired":
                # No access cookie (its lifetime has ended), authentic signed refresh
                # cookie beyond the application's maximum lifetime. No clock/auth mock.
                refresh = self.cookies["member"][REFRESH_COOKIE].split(".", 2)[2]
                client.cookies.set(REFRESH_COOKIE, session.encode_refresh_cookie(
                    self.db.keyed_hash, refresh, int(session.now()) - 1))
            yield client

    def renew(self, role):
        auth = self.db.sign_in_with_password(self.users[role]["email"], self.password)
        assert auth is not None, "fixture Auth session issuance failed"
        self.cookies[role] = {
            SESSION_COOKIE: auth.access_token,
            REFRESH_COOKIE: session.encode_refresh_cookie(self.db.keyed_hash, auth.refresh_token, session.new_deadline()),
        }

    def prepare_request(self, endpoint, role, *, foreign=False, private=False):
        user = self.users.get(role, self.users["member"])
        item = self.users["member" if role == "operator" else "operator"]["item"] if foreign else user["item"]
        note = PRIVATE if private else NOTE
        path = endpoint.path.format(note_id=note, term_id=TERM, item_id=item, seq=1, image_id=IMAGE, report_id=REPORT)
        headers = {**ORIGIN, "Idempotency-Key": str(uuid4())}
        body = {
            "E01": {"email": user["email"], "password": self.password},
            "E07": {"term_id": TERM}, "E08": {"favorited": True},
            "E09": {"note_id": note, "note_revision": 1, "selection": {"start": 0, "end": 10}},
            "E10": {"target": {"type": "quiz_item", "id": item}, "body": "Synthetic report"},
            "E12": {"answer": "Synthetic answer"}, "E14": {"answer": "Synthetic followup answer"},
            "E16": {"title": "Synthetic new note"}, "E17": {"is_published": True},
            "E20": {"label": f"meg69 {self.tag} new", "body_markdown": "Synthetic dictionary"},
            "E24": {"email": f"meg69-issued-{uuid4().hex}@example.com", "display_name": "Synthetic issued",
                    "initial_password": secrets.token_urlsafe(24)},
            "E26": {"status": "resolved", "invalidate_explanation": True},
        }.get(endpoint.id)
        if endpoint.id in ("E13", "E14"):
            self.sql(f"insert into quiz_answers(item_id,user_answer) values ({item},'Synthetic answer');")
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        if endpoint.id == "E22":
            kwargs["files"] = {"file": ("synthetic.png", png(), "image/png")}
        return path, kwargs

    def assert_no_effect(self, before, call_offset):
        assert self.snapshot() == before, "Denied request changed application/Auth-user/Storage data"
        # Session revocation for inactive accounts is intentional; counters are not business writes.
        allowed = {"/auth/v1/logout", "/auth/v1/token", "/rest/v1/rpc/rate_limit_hit",
                   "/rest/v1/rpc/rate_limit_release"}
        writes = [(method, path) for method, path in self.calls[call_offset:]
                  if method not in ("GET", "HEAD") and path not in allowed]
        assert not writes, f"Denied request attempted a mutation: {writes}"

    def close(self):
        try:
            if self.seeded:
                self.reset()
            for bucket in reversed(self.bucket_created):
                self.request("DELETE", f"/storage/v1/bucket/{bucket}")
            for uid in reversed(self.created):
                self.db.delete_auth_user(uid)
        finally:
            self.http.close()


def install(matrix, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_supabase, lambda: matrix.db)
    runtime = AiRuntime(store=SupabaseLedgerStore(matrix.db), load_budget=no_ai,
                        load_settings=no_ai, client_factory=no_ai)
    monkeypatch.setitem(app.dependency_overrides, get_ai_runtime, lambda: runtime)
    # Only the quiz business clock is fixed; Auth/token and rate-limit clocks are real.
    monkeypatch.setattr(quiz, "kst_now", lambda: datetime(2026, 11, 3, 12, tzinfo=timezone(timedelta(hours=9))))
