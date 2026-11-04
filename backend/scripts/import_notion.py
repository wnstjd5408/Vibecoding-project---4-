"""One-shot operator CLI. No .env loading, raw content logging or remote test data."""

import argparse
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from scripts.notion_content import canonical_id, convert, plain
from scripts.notion_images import ImageRejected, download, reencode

KST = timezone(timedelta(hours=9))


class ImportFailure(Exception):
    pass


@dataclass
class Counts:
    notes: int = 0
    images: int = 0
    skipped_pages: int = 0
    skipped_images: int = 0
    skipped_blocks: int = 0
    rejected_images: int = 0
    failed_pages: int = 0
    failed_images: int = 0
    fatal_errors: int = 0


class Notion:
    def __init__(self, http, token, data_source, checkbox, date_property, subjects_property="Subjects"):
        self.http, self.token = http, token
        self.data_source = canonical_id(data_source)
        self.checkbox, self.date_property = checkbox, date_property
        self.subjects_property = subjects_property

    def request(self, method, path, **kwargs):
        for attempt in range(4):
            response = self.http.request(method, "https://api.notion.com/v1/" + path,
                headers={"Authorization": f"Bearer {self.token}", "Notion-Version": "2026-03-11"}, **kwargs)
            if response.status_code == 429 and attempt < 3:
                delay = response.headers.get("Retry-After", "1")
                time.sleep(min(float(delay), 30) if delay.replace(".", "", 1).isdigit() else 1)
                continue
            if response.status_code != 200:
                raise ImportFailure("notion_http")
            return response.json()
        raise ImportFailure("notion_http")

    def validate(self):
        properties = self.request("GET", f"data_sources/{self.data_source}")["properties"]
        if properties.get(self.checkbox, {}).get("type") != "checkbox":
            raise ImportFailure("checkbox_schema")
        if self.date_property and properties.get(self.date_property, {}).get("type") != "date":
            raise ImportFailure("date_schema")
        if properties.get(self.subjects_property, {}).get("type") != "multi_select":
            raise ImportFailure("subjects_schema")

    def pages(self):
        cursor, seen = None, set()
        while True:
            body = {"page_size": 100, "filter": {"property": self.checkbox, "checkbox": {"equals": True}}}
            if cursor:
                body["start_cursor"] = cursor
            data = self.request("POST", f"data_sources/{self.data_source}/query", json=body)
            yield from data["results"]
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")
            if not cursor or cursor in seen:
                raise ImportFailure("pagination")
            seen.add(cursor)

    def children(self, block_id):
        cursor, seen = None, set()
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self.request("GET", f"blocks/{canonical_id(block_id)}/children", params=params)
            yield from data["results"]
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")
            if not cursor or cursor in seen:
                raise ImportFailure("pagination")
            seen.add(cursor)

    def selected(self, page):
        parent = page.get("parent", {})
        return (not page.get("archived") and not page.get("in_trash")
                and parent.get("type") == "data_source_id"
                and canonical_id(parent["data_source_id"]) == self.data_source
                and page.get("properties", {}).get(self.checkbox, {}).get("type") == "checkbox"
                and page["properties"][self.checkbox].get("checkbox") is True)


class Destination:
    def __init__(self, http, url, key, bucket):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ImportFailure("destination_url")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", bucket):
            raise ImportFailure("bucket")
        self.http, self.url, self.key, self.bucket = http, url.rstrip("/"), key, bucket

    def request(self, method, path, **kwargs):
        headers = {"apikey": self.key}
        headers.update(kwargs.pop("headers", {}))
        response = self.http.request(method, self.url + path, headers=headers, **kwargs)
        if response.status_code not in (200, 201, 204):
            raise ImportFailure("destination_http")
        return response.json() if response.content else None

    def validate(self):
        bucket = self.request("GET", f"/storage/v1/bucket/{self.bucket}")
        if bucket.get("public") is not False:
            raise ImportFailure("public_bucket")

    def note(self, page_id):
        rows = self.request("GET", "/rest/v1/notes", params={"notion_page_id": f"eq.{page_id}", "select": "id", "limit": "1"})
        return rows[0]["id"] if rows else None

    def insert_note(self, payload, subjects):
        result = self.request("POST", "/rest/v1/rpc/import_notion_note", json={
            "p_notion_page_id": payload["notion_page_id"], "p_title": payload["title"],
            "p_body_markdown": payload["body_markdown"], "p_studied_on": payload["studied_on"],
            "p_subject_names": subjects})
        if not isinstance(result.get("id"), int) or type(result.get("created")) is not bool:
            raise ImportFailure("import_response")
        return result["id"], result["created"]

    def has_image(self, note_id, block_id):
        return bool(self.request("GET", "/rest/v1/note_images", params={
            "note_id": f"eq.{note_id}", "notion_block_id": f"eq.{block_id}", "select": "id", "limit": "1"}))

    def save_image(self, note_id, image, content):
        path = f"notes/{int(note_id)}/{canonical_id(image['id'])}"
        self.request("POST", f"/storage/v1/object/{self.bucket}/{path}", content=content,
                     headers={"Content-Type": "image/png", "x-upsert": "true"})
        rows = self.request("POST", "/rest/v1/note_images", params={"on_conflict": "note_id,notion_block_id"},
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
            json={"note_id": note_id, "notion_block_id": image["id"], "storage_path": path, "alt": image["alt"]})
        return bool(rows)


def note_payload(page, body, date_property):
    props = page["properties"]
    titles = [p for p in props.values() if p.get("type") == "title"]
    if len(titles) != 1:
        raise ImportFailure("title_schema")
    title = plain(titles[0]["title"])
    if not 1 <= len(title) <= 300:
        raise ImportFailure("title_length")
    date = (props.get(date_property, {}).get("date") or {}).get("start") if date_property else None
    date = date or page["created_time"]
    if len(date) == 10:
        studied = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        timestamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ImportFailure("date_timezone")
        studied = timestamp.astimezone(KST).date()
    return {"notion_page_id": canonical_id(page["id"]), "title": title, "body_markdown": body,
            "studied_on": studied.isoformat(), "is_published": False,
            "imported_at": datetime.now(timezone.utc).isoformat()}


def run(notion, destination, counts, fetch_image=download):
    notion.validate()
    destination.validate()
    for page in notion.pages():
        try:
            if not notion.selected(page):
                counts.skipped_pages += 1
                continue
            page_id = canonical_id(page["id"])
            content = convert(notion, page_id)
            counts.skipped_blocks += content.skipped
            note_id = destination.note(page_id)
            created = False
            if note_id is None:
                subject_prop = page["properties"][notion.subjects_property]
                if subject_prop.get("type") != "multi_select":
                    raise ImportFailure("subjects_schema")
                subjects = [s["name"] for s in subject_prop["multi_select"]]
                if len(subjects) > 100 or any(not isinstance(s, str) or not 1 <= len(s) <= 100 for s in subjects):
                    raise ImportFailure("subjects_values")
                note_id, created = destination.insert_note(note_payload(page, content.markdown, notion.date_property), subjects)
            counts.notes += int(created)
            counts.skipped_pages += int(not created)
            for image in content.images:
                try:
                    if destination.has_image(note_id, image["id"]):
                        counts.skipped_images += 1
                        continue
                    if not image["url"]:
                        raise ImageRejected("source")
                    encoded = reencode(fetch_image(image["url"]))
                    inserted = destination.save_image(note_id, image, encoded)
                    counts.images += int(inserted)
                    counts.skipped_images += int(not inserted)
                except ImageRejected:
                    counts.rejected_images += 1
                except Exception:
                    counts.failed_images += 1
        except Exception:
            counts.failed_pages += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    counts = Counts()
    # Library debug logging must not expose credentials, signed URLs or content.
    logging.disable(logging.CRITICAL)
    try:
        env = os.environ
        key = env["NOTION_IMPORT_SUPABASE_SECRET_KEY"]
        if not key.startswith("sb_secret_") or key == env.get("SUPABASE_SECRET_KEY"):
            raise ImportFailure("dedicated_key")
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as http:
            notion = Notion(http, env["NOTION_IMPORT_TOKEN"], env["NOTION_IMPORT_DATA_SOURCE_ID"],
                            env["NOTION_IMPORT_CHECKBOX"], env["NOTION_IMPORT_DATE_PROPERTY"],
                            env["NOTION_IMPORT_SUBJECTS_PROPERTY"])
            destination = Destination(http, env["NOTION_IMPORT_SUPABASE_URL"], key, env["NOTION_IMPORT_BUCKET"])
            run(notion, destination, counts)
    except (Exception, KeyboardInterrupt):
        counts.fatal_errors += 1
    print(json.dumps(asdict(counts), sort_keys=True))
    return 1 if counts.fatal_errors or counts.failed_pages or counts.failed_images or counts.rejected_images else 0


if __name__ == "__main__":
    raise SystemExit(main())
