"""CouchDB helper surface for object platform services."""
from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlsplit
import json

logger = logging.getLogger(__name__)


class CouchDBClient:
    _ensured_databases: set[str] = set()

    def __init__(self, base_url: str, database: str = "catalog") -> None:
        self.base_url = base_url.rstrip("/")
        self.database = database

    @property
    def database_url(self) -> str:
        return f"{self.base_url}/{self.database}"

    def document_url(self, doc_id: str) -> str:
        return f"{self.database_url}/{quote(doc_id, safe='')}"

    def ensure_database(self) -> None:
        import requests

        if self.database_url in self._ensured_databases:
            return
        deadline = time.monotonic() + 90
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = requests.put(self.database_url, timeout=10)
                if response.status_code not in {201, 202, 412}:
                    response.raise_for_status()
                self._ensured_databases.add(self.database_url)
                return
            except requests.RequestException as exc:
                last_error = exc
                logger.info("Waiting for CouchDB database %s on %s", self.database, urlsplit(self.base_url).hostname)
                time.sleep(2)
        if last_error is not None:
            raise last_error

    def ensure_databases(self, databases: list[str]) -> None:
        for database in databases:
            CouchDBClient(self.base_url, database).ensure_database()

    def upsert_document(self, doc_id: str, document: dict[str, object]) -> None:
        import requests

        self.ensure_database()
        for attempt in range(3):
            get_response = requests.get(self.document_url(doc_id), timeout=10)
            if get_response.status_code == 200:
                document["_rev"] = get_response.json()["_rev"]
            elif get_response.status_code == 404:
                document.pop("_rev", None)
            else:
                get_response.raise_for_status()
            put_response = requests.put(self.document_url(doc_id), json=document, timeout=10)
            if put_response.status_code == 409 and attempt < 2:
                logger.warning("Conflict while upserting %s into %s, retrying", doc_id, self.database)
                continue
            put_response.raise_for_status()
            logger.info("Upserted CouchDB document %s into %s", doc_id, self.database)
            return
        raise RuntimeError(f"Failed to upsert {doc_id} into {self.database}")

    def get_document(self, doc_id: str) -> dict[str, object] | None:
        import requests

        self.ensure_database()
        response = requests.get(self.document_url(doc_id), timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def delete_document(self, doc_id: str) -> bool:
        import requests

        document = self.get_document(doc_id)
        if document is None:
            return False
        response = requests.delete(self.document_url(doc_id), params={"rev": document["_rev"]}, timeout=10)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        logger.info("Deleted CouchDB document %s from %s", doc_id, self.database)
        return True

    def list_documents(self, limit: int = 50) -> list[dict[str, object]]:
        import requests

        self.ensure_database()
        response = requests.get(
            f"{self.database_url}/_all_docs",
            params={"include_docs": "true", "limit": limit},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return [row["doc"] for row in payload.get("rows", []) if "doc" in row]

    def find_documents(self, selector: dict[str, object], limit: int = 50) -> list[dict[str, object]]:
        import requests

        self.ensure_database()
        response = requests.post(
            f"{self.database_url}/_find",
            json={"selector": selector, "limit": limit},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("docs", [])

    def iter_documents(self, page_size: int = 500):
        """Walk by document ID; deletion during a scan does not skip later rows."""
        import requests

        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.ensure_database()
        startkey = None
        while True:
            limit = page_size + (1 if startkey is not None else 0)
            params = {"include_docs": "true", "limit": limit}
            if startkey is not None:
                params["startkey"] = json.dumps(startkey)
            response = requests.get(f"{self.database_url}/_all_docs", params=params, timeout=30)
            response.raise_for_status()
            rows = response.json().get("rows", [])
            # Never use skip=1: the cursor row may have been deleted during a scan.
            remaining = [row for row in rows if startkey is None or row["id"] > startkey]
            if not remaining:
                return
            for row in remaining:
                doc = row.get("doc")
                if doc and not doc.get("_deleted"):
                    yield doc
            startkey = remaining[-1]["id"]
            if len(rows) < limit:
                return

    def create_document(self, doc_id: str, document: dict[str, object]) -> bool:
        """Create defaults without overwriting operator changes."""
        import requests

        self.ensure_database()
        response = requests.put(self.document_url(doc_id), json=document, timeout=10)
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    def ensure_type_view(self) -> None:
        self.create_document("_design/type_counts", {
            "_id": "_design/type_counts",
            "views": {"by_type": {
                "map": "function(doc) { if (doc.type && (!doc.retention || doc.retention.status !== 'deleted')) { emit(doc.type, 1); } }",
                "reduce": "_count",
            }},
        })

    def type_counts(self) -> dict[str, int]:
        import requests

        response = requests.get(f"{self.database_url}/_design/type_counts/_view/by_type",
                                params={"group": "true"}, timeout=60)
        response.raise_for_status()
        return {row["key"]: row["value"] for row in response.json().get("rows", [])}
