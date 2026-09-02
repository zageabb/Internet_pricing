from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INDEX = ROOT / "instance" / "procurement.sqlite3"
LOCK = threading.Lock()


def connect(path=DEFAULT_INDEX):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS notices (
            notice_id TEXT PRIMARY KEY,
            ocid TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            buyer TEXT NOT NULL DEFAULT '',
            suppliers TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            values_json TEXT NOT NULL DEFAULT '[]',
            raw_json TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS notices_fts USING fts5(
            notice_id UNINDEXED, title, description, buyer, suppliers, values_text
        );
    """)
    return connection


def index_payload(payload, source, path=DEFAULT_INDEX):
    notices = list(extract_notices(payload, source))
    if not notices:
        return 0
    with LOCK, closing(connect(path)) as connection:
        with connection:
            for notice in notices:
                connection.execute("""
                INSERT INTO notices (notice_id, ocid, source, title, description, buyer, suppliers,
                                     published_at, url, values_json, raw_json, indexed_at)
                VALUES (:notice_id, :ocid, :source, :title, :description, :buyer, :suppliers,
                        :published_at, :url, :values_json, :raw_json, :indexed_at)
                ON CONFLICT(notice_id) DO UPDATE SET
                    ocid=excluded.ocid, source=excluded.source, title=excluded.title,
                    description=excluded.description, buyer=excluded.buyer, suppliers=excluded.suppliers,
                    published_at=excluded.published_at, url=excluded.url, values_json=excluded.values_json,
                    raw_json=excluded.raw_json, indexed_at=excluded.indexed_at
                """, notice)
                connection.execute("DELETE FROM notices_fts WHERE notice_id = ?", (notice["notice_id"],))
                connection.execute("""
                INSERT INTO notices_fts (notice_id, title, description, buyer, suppliers, values_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (notice["notice_id"], notice["title"], notice["description"], notice["buyer"],
                      notice["suppliers"], values_text(json.loads(notice["values_json"]))))
    return len(notices)


def search_procurement(query, limit=12, path=DEFAULT_INDEX):
    tokens = [token for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", str(query).lower())
              if token not in {"price", "pricing", "cost", "current", "global", "market", "with", "from", "the"}]
    if not tokens or not Path(path).exists():
        return []
    expression = " OR ".join(f'"{token}"*' for token in dict.fromkeys(tokens[:16]))
    with closing(connect(path)) as connection:
        rows = connection.execute("""
            SELECT n.*, bm25(notices_fts, 0, 5, 2, 1, 1, 4) AS text_rank
            FROM notices_fts JOIN notices n ON n.notice_id = notices_fts.notice_id
            WHERE notices_fts MATCH ? ORDER BY text_rank LIMIT ?
        """, (expression, max(1, min(int(limit), 50)))).fetchall()
    return [notice_candidate(row, query) for row in rows]


def notice_candidate(row, query):
    values = json.loads(row["values_json"] or "[]")
    value_summary = values_text(values)
    details = [row["description"], f"Buyer: {row['buyer']}" if row["buyer"] else "",
               f"Supplier: {row['suppliers']}" if row["suppliers"] else "", value_summary]
    indexed_text = "\n".join(part for part in details if part)
    return {"title": row["title"], "url": row["url"] or f"urn:ocid:{row['ocid']}",
            "snippet": indexed_text[:2_000], "query": query, "published_at": row["published_at"],
            "search_backend": f"procurement-index:{row['source']}", "indexed_text": indexed_text,
            "content_type": "application/ocds+json"}


def extract_notices(payload, source):
    releases = list(payload.get("releases") or [])
    releases += [record.get("compiledRelease") for record in payload.get("records") or []
                 if isinstance(record, dict) and isinstance(record.get("compiledRelease"), dict)]
    package_uri = str(payload.get("uri") or "")
    for release in releases:
        if not isinstance(release, dict):
            continue
        tender = release.get("tender") or {}
        planning = release.get("planning") or {}
        title = str(tender.get("title") or (planning.get("project") or {}).get("title") or "").strip()
        description = str(tender.get("description") or (planning.get("project") or {}).get("description") or "").strip()
        if not title and not description:
            continue
        ocid = str(release.get("ocid") or "")
        release_id = str(release.get("id") or ocid)
        notice_id = f"{source}:{release_id}"
        buyer = str((release.get("buyer") or {}).get("name") or "")
        awards = release.get("awards") or []
        suppliers = sorted({str(supplier.get("name") or "").strip() for award in awards
                            for supplier in (award.get("suppliers") or []) if supplier.get("name")})
        values = collect_values(release)
        url = first_document_url(release) or package_uri
        published_at = str(release.get("date") or "")
        yield {"notice_id": notice_id, "ocid": ocid, "source": source, "title": title,
               "description": description, "buyer": buyer, "suppliers": ", ".join(suppliers),
               "published_at": published_at, "url": url, "values_json": json.dumps(values),
               "raw_json": json.dumps(release, ensure_ascii=False),
               "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def collect_values(release):
    values = []
    candidates = [((release.get("planning") or {}).get("budget") or {}).get("amount"),
                  (release.get("tender") or {}).get("value")]
    candidates += [award.get("value") for award in release.get("awards") or []]
    candidates += [contract.get("value") for contract in release.get("contracts") or []]
    for value in candidates:
        if not isinstance(value, dict) or value.get("amount") is None or not value.get("currency"):
            continue
        values.append({"amount": value["amount"], "currency": str(value["currency"]).upper()})
    return values


def first_document_url(release):
    groups = [(release.get("tender") or {}).get("documents") or []]
    groups += [award.get("documents") or [] for award in release.get("awards") or []]
    groups += [contract.get("documents") or [] for contract in release.get("contracts") or []]
    for documents in groups:
        for document in documents:
            if str(document.get("url") or "").startswith(("http://", "https://")):
                return str(document["url"])
    return ""


def values_text(values):
    return "; ".join(f"Published procurement value: {value['amount']} {value['currency']}"
                     for value in values if value.get("amount") is not None and value.get("currency"))
