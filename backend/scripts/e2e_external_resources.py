"""Exact external resources created by an E2E run; no discovery/adoption cleanup."""
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import re
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx

from scripts.e2e_run_resources import CleanupConflict, digest, require


class GraphResources:
    kind = "graph"
    labels = {"Project", "Document", "DocumentVersion", "Chunk", "Tag"}
    relations = {"PROJECT_HAS_DOCUMENT", "DOCUMENT_HAS_VERSION", "VERSION_HAS_CHUNK", "CHUNK_HAS_TAG", "DOCUMENT_HAS_TAG"}

    def __init__(self, driver, database="neo4j"):
        self.driver, self.database = driver, database

    def binding(self):
        with self.driver.session(database=self.database) as session:
            record = session.run("CALL db.info() YIELD id, name RETURN id, name").single(strict=True)
            return dict(record)

    def create_node(self, journal, label, properties=None):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "graph_target_changed")
        require(label in self.labels, "graph_label_not_supported")
        props = dict(properties or {})
        props.setdefault("id", str(uuid4()))
        entry = journal.intent(self.kind, {"type": "node", "id": props["id"]})
        props.update(_e2e_run=journal.data["run_id"], _e2e_resource=entry["id"])
        with self.driver.session(database=self.database) as session, session.begin_transaction(timeout=10) as tx:
            require(tx.run("MATCH (n {id:$id}) RETURN count(n) AS count", id=props["id"]).single()["count"] == 0, "graph_resource_exists")
            row = tx.run(f"CREATE (n:{label}) SET n=$props RETURN elementId(n) AS element, labels(n) AS labels, properties(n) AS props", props=props).single(strict=True)
            journal.created(entry, {"element": row["element"], "hash": digest({"labels": sorted(row["labels"]), "props": row["props"]})})
            tx.commit()
        return entry

    def create_edge(self, journal, source, target, relation):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "graph_target_changed")
        require(relation in self.relations, "graph_relation_not_supported")
        rid = str(uuid4())
        entry = journal.intent(self.kind, {"type": "edge", "id": rid})
        props = {"id": rid, "_e2e_run": journal.data["run_id"], "_e2e_resource": entry["id"]}
        with self.driver.session(database=self.database) as session, session.begin_transaction(timeout=10) as tx:
            for node in (source, target):
                require(tx.run("MATCH (n) WHERE elementId(n)=$eid RETURN count(n) AS count", eid=node).single()["count"] == 1, "graph_endpoint_missing")
            row = tx.run(f"MATCH (a),(b) WHERE elementId(a)=$a AND elementId(b)=$b CREATE (a)-[r:{relation}]->(b) SET r=$props RETURN elementId(r) AS element",
                a=source, b=target, props=props).single(strict=True)
            journal.created(entry, {"element": row["element"], "hash": digest({"type": relation, "source": source, "target": target, "props": props})})
            tx.commit()
        return entry

    @contextmanager
    def prepare(self, entries):
        with self.driver.session(database=self.database) as session, session.begin_transaction(timeout=15) as tx:
            batch = GraphBatch(tx, entries)
            batch.preflight()
            yield batch


class GraphBatch:
    def __init__(self, tx, entries): self.tx, self.entries = tx, entries

    def preflight(self):
        self.nodes, self.edges = [], []
        for entry in self.entries:
            ident = entry["identity"]
            require(set(ident) == {"type", "id"} and ident["type"] in {"node", "edge"}, "graph_invalid_identity")
            if ident["type"] == "node":
                rows = list(self.tx.run("MATCH (n {id:$id}) RETURN elementId(n) AS element, labels(n) AS labels, properties(n) AS props", id=ident["id"]))
                if not rows: continue
                require(len(rows) == 1, "graph_duplicate_identity")
                row = rows[0]
                fingerprint = digest({"labels": sorted(row["labels"]), "props": row["props"]})
                self.nodes.append(row["element"])
            else:
                rows = list(self.tx.run("MATCH (a)-[r {id:$id}]->(b) RETURN elementId(r) AS element, type(r) AS type, elementId(a) AS source, elementId(b) AS target, properties(r) AS props", id=ident["id"]))
                if not rows: continue
                require(len(rows) == 1, "graph_duplicate_identity")
                row = rows[0]
                fingerprint = digest({k: row[k] for k in ("type", "source", "target", "props")})
                self.edges.append(row["element"])
            require(entry["state"] != "deleted" and entry["proof"] == {"element": row["element"], "hash": fingerprint}, "graph_ownership_changed")
        unknown = self.tx.run("MATCH (n)-[r]-() WHERE elementId(n) IN $nodes AND NOT elementId(r) IN $edges RETURN count(r) AS count",
            nodes=self.nodes, edges=self.edges).single()["count"]
        require(not unknown, "graph_unowned_relationship")

    def delete(self):
        self.preflight()
        self.tx.run("MATCH ()-[r]->() WHERE elementId(r) IN $ids DELETE r", ids=self.edges).consume()
        self.tx.run("MATCH (n) WHERE elementId(n) IN $ids DELETE n", ids=self.nodes).consume()
        self.tx.commit()


class IndexResources:
    kind = "index"
    def __init__(self, url, *, auth=None, verify=True):
        self.http = httpx.Client(base_url=url.rstrip("/"), auth=auth, verify=verify, timeout=10, trust_env=False)

    def request(self, method, path, body=None, *, missing=False):
        response = self.http.request(method, path, json=body)
        if missing and response.status_code == 404: return None
        require(response.is_success, "index_service_failure")
        return response.json()

    def binding(self): return {"cluster_uuid": self.request("GET", "/")["cluster_uuid"]}

    def create(self, journal):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "index_target_changed")
        name = "e2e-" + journal.data["run_id"] + "-" + uuid4().hex
        entry = journal.intent(self.kind, {"name": name})
        marker = {"e2e_run": journal.data["run_id"], "e2e_resource": entry["id"]}
        self.request("PUT", "/" + name, {"settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"_meta": marker, "properties": {"_e2e_run": {"type": "keyword"}}}})
        current = self.request("GET", "/" + name)[name]
        journal.created(entry, {"uuid": current["settings"]["index"]["uuid"], "marker": marker, "documents": []})
        return entry

    def create_document(self, journal, entry, content):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "index_target_changed")
        require(entry in journal.data["resources"] and entry["proof"].get("marker", {}).get("e2e_run") == journal.data["run_id"],
            "index_not_in_run_receipt")
        require(entry["state"] == "created" and journal.data["state"] == "preparing", "index_creation_closed")
        self.check(entry)
        ident = str(uuid4())
        # Intent before write: losing a reply does not lose the exact document identity.
        entry["proof"]["documents"].append(ident); journal.save()
        self.request("PUT", f"/{entry['identity']['name']}/_create/{ident}?refresh=true", {**content, "_e2e_run": journal.data["run_id"]})
        return ident

    def check(self, entry):
        name = entry["identity"].get("name", "")
        require(set(entry["identity"]) == {"name"} and re.fullmatch(r"e2e-[a-z0-9-]{32,100}", name), "index_invalid_name")
        payload = self.request("GET", "/" + name, missing=True)
        if payload is None: return False
        require(entry["state"] != "deleted" and set(payload) == {name}, "index_ownership_changed")
        current, proof = payload[name], entry["proof"]
        require(current["settings"]["index"]["uuid"] == proof.get("uuid") and not current.get("aliases")
            and current["mappings"].get("_meta") == proof.get("marker"), "index_ownership_changed")
        self.request("POST", "/" + name + "/_refresh")
        result = self.request("POST", "/" + name + "/_search", {"size": 10000, "track_total_hits": True,
            "_source": ["_e2e_run"], "query": {"match_all": {}}})["hits"]
        require(result["total"]["value"] <= 10000 and result["total"]["relation"] == "eq", "index_inventory_limit")
        require(all(h["_id"] in proof.get("documents", []) and h["_source"].get("_e2e_run") == proof["marker"]["e2e_run"]
            for h in result["hits"]), "index_foreign_document")
        return True

    @contextmanager
    def prepare(self, entries):
        for entry in entries: self.check(entry)
        yield IndexBatch(self, entries)


class IndexBatch:
    def __init__(self, service, entries): self.service, self.entries = service, entries
    def delete(self, on_deleted=None):
        for entry in self.entries:
            if not self.service.check(entry): continue
            name = entry["identity"]["name"]
            # Blocks API waits for in-flight writes. Metadata/admin replacement still
            # requires the explicitly exclusive disposable-service ownership contract.
            block = self.service.request("PUT", "/" + name + "/_block/write")
            require(block.get("acknowledged") is True, "index_write_fence_unconfirmed")
            self.service.check(entry)
            self.service.request("DELETE", "/" + name)
            if on_deleted: on_deleted(entry)


class ObjectResources:
    """Versioned S3 objects only; unversioned/unknown conditional semantics refuse."""
    kind = "object"
    def __init__(self, config, bucket):
        self.config, self.bucket = config, bucket
        self.http = httpx.Client(verify=config.verify_tls, timeout=10, trust_env=False)

    def request(self, method, key=None, *, query=None, body=b"", headers=None):
        # Independent test client extends signing with query and metadata; production
        # S3ObjectStorage is unchanged (its signer currently assumes no query).
        url = self.config.endpoint_url.rstrip("/") + "/" + quote(self.bucket, safe="")
        if key is not None: url += "/" + quote(key, safe="/")
        query_text = urlencode(sorted((query or {}).items()), quote_via=quote)
        if query_text: url += "?" + query_text
        now = datetime.now(UTC); stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        parts = urlsplit(url)
        signed = {"host": parts.netloc, "x-amz-date": stamp, "x-amz-content-sha256": hashlib.sha256(body).hexdigest(), **(headers or {})}
        if self.config.session_token: signed["x-amz-security-token"] = self.config.session_token
        names = ";".join(sorted(signed))
        canonical = "\n".join((method, parts.path, query_text, "".join(f"{k}:{signed[k]}\n" for k in sorted(signed)), names, signed["x-amz-content-sha256"]))
        scope = f"{day}/{self.config.region}/s3/aws4_request"
        signing = ("AWS4" + self.config.secret_key).encode()
        for value in (day, self.config.region, "s3", "aws4_request"):
            signing = hmac.new(signing, value.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing, ("AWS4-HMAC-SHA256\n" + stamp + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()).encode(), hashlib.sha256).hexdigest()
        signed["authorization"] = f"AWS4-HMAC-SHA256 Credential={self.config.access_key}/{scope}, SignedHeaders={names}, Signature={signature}"
        return self.http.request(method, url, content=body, headers=signed)

    def binding(self):
        response = self.request("GET", query={"versioning": ""})
        require(response.is_success, "object_bucket_unavailable")
        root = ET.fromstring(response.content)
        require(root.findtext("{*}Status") == "Enabled", "object_versioning_required")
        # Object version IDs and creation markers additionally bind every resource;
        # bucket name/endpoint alone is never accepted as deletion proof.
        return {"endpoint_sha256": digest(self.config.endpoint_url), "bucket": self.bucket, "versioning": "Enabled"}

    def create(self, journal, body):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "object_target_changed")
        key = "e2e/" + journal.data["run_id"] + "/" + uuid4().hex
        entry = journal.intent(self.kind, {"bucket": self.bucket, "key": key})
        response = self.request("PUT", key, body=body, headers={"if-none-match": "*",
            "x-amz-meta-e2e-run": journal.data["run_id"], "x-amz-meta-e2e-resource": entry["id"]})
        require(response.is_success, "object_create_failed")
        version = response.headers.get("x-amz-version-id")
        require(version not in (None, "", "null"), "object_version_receipt_missing")
        journal.created(entry, {"version": version, "etag": response.headers.get("etag"), "run_id": journal.data["run_id"]})
        return entry

    def check(self, entry):
        ident, proof = entry["identity"], entry["proof"]
        require(set(ident) == {"bucket", "key"} and ident["bucket"] == self.bucket
            and re.fullmatch(r"e2e/[a-z0-9-]{36}/[a-f0-9]{32}", ident["key"]), "object_invalid_identity")
        require(proof.get("version") not in (None, "", "null") and bool(proof.get("etag")), "object_receipt_unconfirmed")
        response = self.request("HEAD", ident["key"], query={"versionId": proof["version"]})
        if response.status_code == 404: return False
        require(response.is_success and entry["state"] != "deleted"
            and response.headers.get("etag") == proof["etag"]
            and response.headers.get("x-amz-meta-e2e-resource") == entry["id"]
            and response.headers.get("x-amz-meta-e2e-run") == proof["run_id"], "object_ownership_changed")
        return True

    @contextmanager
    def prepare(self, entries):
        for entry in entries: self.check(entry)
        yield ObjectBatch(self, entries)


class ObjectBatch:
    def __init__(self, service, entries): self.service, self.entries = service, entries
    def delete(self, on_deleted=None):
        for entry in self.entries:
            if not self.service.check(entry): continue
            response = self.service.request("DELETE", entry["identity"]["key"],
                query={"versionId": entry["proof"]["version"]}, headers={"if-match": entry["proof"]["etag"]})
            require(response.is_success, "object_delete_failed")
            if on_deleted: on_deleted(entry)
