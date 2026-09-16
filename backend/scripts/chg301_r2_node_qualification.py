"""CHG-301 R2: bounded, static-only public OCI qualification. No image execution."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import tarfile
import tempfile
import time
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.parse
import urllib.request

import certifi
import yaml

from chg301_r2_ingress import source_snapshot, GIT_BASE, assess_sarif

ROOT = Path(__file__).resolve().parents[2]
SECTION = "CHG-301 R2 Node And Infrastructure Static Qualification"
PLAN = ROOT / "docs/CHG-301-R2-NODE-QUALIFICATION-PLAN.md"
PLAN_SHA = "0254bfebb4713c4c5ae5325ce0ceecc2ed1dc0bb258ac662a5bc76e5ab536154"
PREAPPROVAL_SHA = "f1cc8bec449f60aa4e4eae29f3d7eb9c7f4bc67badb1c8b3936650f7c43ac132"
APPROVAL = "核准 CHG-301 R2 節點與基礎映像整批靜態判定計畫"
DEADLINE = datetime.fromisoformat("2026-09-15T20:17:52.088462+00:00")
STOP_WORK = DEADLINE - timedelta(minutes=10)
NODE_INDEX = "sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
NODE_ARM64 = "sha256:10210eabcf5dc4b585756bbd3f7fbb60cc0a12a252f28aeba269d93e0070c025"
NODE = "docker.io/kindest/node:v1.36.4"
GiB = 1024 ** 3
MAX_BLOB = 4 * GiB
MAX_LAYER = 8 * GiB
DOCKER = ["docker", "--context", "desktop-linux"]
GOVULNCHECK = Path("/private/tmp/chg301-r2-repair-8tn60fwz/tools/govulncheck")
GOVULNCHECK_SHA = "095a30ec3676ec9bbfa17e4d411b5079bae3bb4b52120491e781eb9c0261cb0f"
DEBIAN_KEYS = {
    "archive-key-12.asc": "B8B80B5B623EAB6AD8775C45B7C5D7D6350947F8",
    "archive-key-12-security.asc": "05AB90340C0C5E797F44A8C8254CF3B5AEC0A8F0",
    "archive-key-13.asc": "04B54C3CDCA79751B16BC6B5225629DF75B188BD",
    "archive-key-13-security.asc": "5E04A1E3223A19A20706E20F9904613D4CCE68C6",
    "release-13.asc": "41587F7DB8C774BCCF131416762F67A0B2C39DE4"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_new(path, value):
    data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, indent=2).encode()
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write(data)


def exact_owned_file(root, relative, identity=None):
    """No glob cleanup or artifact links: validate a single regular owned file."""
    path = root / safe_name(relative)
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise ValueError("cleanup_link")
    if not path.is_relative_to(root) or any(p.is_symlink() for p in path.parents if p.is_relative_to(root)):
        raise ValueError("cleanup_path")
    st = path.stat()
    if not path.is_file() or st.st_uid != os.getuid():
        raise ValueError("cleanup_owner_type")
    current = {"path": relative, "inode": st.st_ino, "owner_uid": st.st_uid,
               "bytes": st.st_size, "sha256": file_sha(path)}
    if identity is not None and current != identity:
        raise ValueError("cleanup_identity_drift")
    return current


def debian_fixed_versions(tables, source):
    # Use the explicit source-package table, not a preceding rowspan belonging
    # to a different package (e.g. Perl's separately packaged Socket module).
    return sorted({row[3] for row in tables if len(row) >= 4
                   and row[:3] == [source, "source", "trixie"] and row[3] not in {"(unfixed)", "(undetermined)"}})


def signed_release_index(release, verification, suite, now):
    if "[GNUPG:] VALIDSIG " not in verification or any(x in verification for x in ("BADSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY")):
        raise ValueError("debian_release_signature")
    if not re.search(r"^Codename: " + re.escape(suite) + "$", release, re.M):
        raise ValueError("debian_suite_identity")
    expiry = re.search(r"^Valid-Until: (.+)$", release, re.M)
    if expiry and parsedate_to_datetime(expiry[1]) <= now:
        raise ValueError("debian_release_expired")
    checksum_lines = release.split("\nSHA256:\n", 1)[1].split("\nSHA512:", 1)[0]
    candidates = [line.split() for line in checksum_lines.splitlines() if re.fullmatch(r"\s*[0-9a-f]{64}\s+\d+\s+main/binary-arm64/Packages.xz", line)]
    if len(candidates) != 1:
        raise ValueError("debian_package_index_binding")
    digest, size, name = candidates[0]
    if int(size) > 32 * 1024**2:
        raise ValueError("debian_package_index_size")
    return digest, int(size), name


def approval_guard(plan, active, now):
    if sha(plan) != PLAN_SHA:
        raise ValueError("approved_plan_hash")
    title = "## " + SECTION
    if title not in active:
        raise ValueError("active_plan_missing")
    if active.split("## ", 1)[1].splitlines()[0] != SECTION:
        raise ValueError("historical_plan_not_active")
    section = active.split(title, 1)[1].split("\n## ", 1)[0]
    if "Gate 4 approval: APPROVED." not in section or APPROVAL not in section or PREAPPROVAL_SHA not in section:
        raise ValueError("explicit_current_approval_required")
    if now >= STOP_WORK:
        raise ValueError("original_batch_time_exhausted")


def safe_name(value):
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise ValueError("archive_path")
    name = PurePosixPath(value)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError("archive_path")
    return str(name)


def selected_file(name):
    return (name in {"usr/bin/kubeadm", "usr/bin/kubelet", "var/lib/dpkg/status"}
            or name.startswith(("usr/local/bin/", "kind/", "etc/containerd/", "etc/kubernetes/", "etc/apt/")))


def validate_layer_digest(actual, expected):
    if actual != expected.removeprefix("sha256:"):
        raise ValueError("layer_diff_id")


def validate_archive_member(member, ordinal, seen):
    """Pure metadata policy; operational extraction still requires its own guard."""
    if ordinal >= 1_000_000 or member.size > MAX_LAYER or member.size < 0:
        raise ValueError("archive_entry_bound")
    name = safe_name(member.name)
    if name in seen:
        raise ValueError("archive_duplicate")
    return name


def apply_layer(lower, layer):
    effective = dict(lower)
    for name in layer:
        p = PurePosixPath(name)
        if p.name == ".wh..wh..opq":
            prefix = "" if str(p.parent) == "." else str(p.parent) + "/"
            effective = {k: v for k, v in effective.items() if not k.startswith(prefix)}
        elif p.name.startswith(".wh."):
            target = str(p.with_name(p.name[4:]))
            effective = {k: v for k, v in effective.items() if k != target and not k.startswith(target + "/")}
    for name, value in layer.items():
        if PurePosixPath(name).name.startswith(".wh."):
            continue
        # A file replacing a lower directory hides its descendants as well.
        if value["type"] != "directory":
            effective = {k: v for k, v in effective.items() if not k.startswith(name + "/")}
        effective[name] = value
    return effective


def validate_url(url, allowed_hosts):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in {None, 443} or parsed.fragment or parsed.hostname not in allowed_hosts):
        raise ValueError("public_url_scope")
    for info in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("nonpublic_download_address")


def elf_identity(path):
    with path.open("rb") as stream:
        head = stream.read(64)
    if head[:4] != b"\x7fELF":
        return None
    if len(head) < 64 or head[4] not in (1, 2) or head[5] not in (1, 2):
        raise ValueError("invalid_elf_header")
    machine = struct.unpack("<H" if head[5] == 1 else ">H", head[18:20])[0]
    return {"class_bits": 64 if head[4] == 2 else 32, "machine": machine,
            "architecture": "arm64" if machine == 183 else "other"}


def go_build_info(text):
    result = {"modules": [], "build_settings": {}}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[0] == "path":
            result["path"] = parts[1]
        elif len(parts) >= 3 and parts[0] in {"mod", "dep"}:
            result["modules"].append({"kind": parts[0], "name": parts[1], "version": parts[2],
                                      "sum": parts[3] if len(parts) > 3 else None})
        elif len(parts) >= 2 and parts[0] == "build":
            key, _, value = parts[1].partition("=")
            result["build_settings"][key] = value
        elif line and not line.startswith("\t"):
            result["go_version"] = line.split()[-1]
        elif parts[0] == "=>":
            result.setdefault("replacements", []).append(parts[1:])
    return result


def image_fields(value, location=""):
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = location + "/" + str(key)
            if key == "image" and isinstance(child, str):
                rows.append({"field": child_path, "reference": child})
            rows.extend(image_fields(child, child_path))
    elif isinstance(value, list):
        for n, child in enumerate(value):
            rows.extend(image_fields(child, location + "/" + str(n)))
    return rows


def process_usage(root_pid):
    # Only numeric process metadata, never arguments/environment/credentials.
    out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,rss=,%cpu="], capture_output=True, timeout=10, check=True).stdout
    rows = [line.split() for line in out.decode().splitlines()]
    selected = {root_pid}
    for _ in range(16):
        children = {int(p) for p, parent, _, _ in rows if int(parent) in selected}
        if children <= selected:
            break
        selected |= children
    return {"rss_bytes": sum(int(rss) * 1024 for p, _, rss, _ in rows if int(p) in selected),
            "cpu_percent": sum(float(cpu) for p, _, _, cpu in rows if int(p) in selected)}


def purl_parts(purl):
    path = urllib.parse.unquote(purl.split("?", 1)[0])
    name, version = path.rsplit("@", 1)
    return name.removeprefix("pkg:golang/").removeprefix("pkg:deb/debian/"), version.removeprefix("v")


def deb_packages(text):
    rows = []
    for paragraph in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line and not line.startswith(" "))
        if fields.get("Status") != "install ok installed":
            continue
        source = fields.get("Source", fields.get("Package", ""))
        match = re.fullmatch(r"([^ ]+) \(([^)]+)\)", source)
        rows.append({"package": fields.get("Package"), "version": fields.get("Version"),
                     "architecture": fields.get("Architecture"), "source": match[1] if match else source,
                     "source_version": match[2] if match else fields.get("Version")})
    return rows


class AdvisoryHTML(HTMLParser):
    """Extract official human-readable tables without executing HTML/scripts."""
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.cell, self.text = [], [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.cells:
            self.rows.append(self.cells)

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Qualification:
    def __init__(self, manifest=None):
        approval_guard(PLAN.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text(), datetime.now(UTC))
        os.umask(0o077)
        if manifest is None:
            self.work = Path(tempfile.mkdtemp(prefix="chg301-r2-node-qual-", dir="/private/tmp"))
            self.work.chmod(0o700)
            self.record = {"scope": SECTION, "plan_sha256": PLAN_SHA, "preapproval_sha256": PREAPPROVAL_SHA,
                           "started_at": datetime.now(UTC).isoformat(), "owner_uid": os.getuid(),
                           "root_inode": self.work.stat().st_ino, "commands": [], "downloads": [],
                           "phases": [], "gaps": [], "runtime_operations": 0, "provider_calls": 0,
                           "pr_writes": 0, "waivers_applied": []}
            self.manifest = self.work / "manifest.json"
        else:
            self.manifest = Path(manifest)
            self.work = self.manifest.parent
            if (self.work.parent != Path("/private/tmp") or not self.work.name.startswith("chg301-r2-node-qual-")
                    or self.manifest.name != "manifest.json" or self.work.is_symlink() or self.manifest.is_symlink()):
                raise ValueError("run_identity_path")
            self.record = json.loads(self.manifest.read_bytes())
            if (self.work.stat().st_ino != self.record["root_inode"] or os.getuid() != self.record["owner_uid"]
                    or self.record["plan_sha256"] != PLAN_SHA):
                raise ValueError("run_identity_owner")
        for name in ("raw", "blobs", "payload", "analysis"):
            (self.work / name).mkdir(exist_ok=True, mode=0o700)
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
        self.record.setdefault("implementation_history", []).append({
            "time": datetime.now(UTC).isoformat(),
            "runner_sha256": file_sha(Path(__file__)),
            "test_sha256": file_sha(ROOT / "backend/tests/test_chg301_r2_node_qualification.py")})

    def checkpoint(self):
        # Generated run evidence is atomically updated; never accepts an external target.
        tmp = self.work / "manifest-next.json"
        write_new(tmp, self.record)
        tmp.replace(self.manifest)

    def guard(self):
        approval_guard(PLAN.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text(), datetime.now(UTC))
        if shutil.disk_usage(self.work).free < 100 * GiB:
            raise ValueError("host_static_disk_headroom")
        used = sum(p.stat().st_size for p in self.work.rglob("*") if p.is_file() and not p.is_symlink())
        if used > 40 * GiB:
            raise ValueError("run_disk_limit")
        # macOS ru_maxrss is bytes; this runner is bound to the current local host.
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 4 * GiB:
            raise ValueError("analysis_rss_limit")
        if "source" in self.record and source_snapshot() != self.record["source"]:
            raise ValueError("source_drift")

    def command(self, args, timeout=120, private_go=False):
        if not args:
            raise ValueError("static_command_scope")
        allowed = False
        if args[:3] == DOCKER:
            tail = args[3:]
            allowed = (tail in [["ps", "-aq", "--no-trunc"],
                               ["network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"],
                               ["image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"],
                               ["stats", "--no-stream", "--format", "{{.ID}} {{.CPUPerc}} {{.MemUsage}}"],
                               ["info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}'], ["scout", "version"]]
                       or (len(tail) == 4 and tail[:3] == ["inspect", "--format", '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}'] and re.fullmatch(r"[0-9a-f]{64}", tail[3]))
                       or tail == ["buildx", "imagetools", "inspect", NODE, "--raw"]
                       or (tail[:3] == ["buildx", "imagetools", "inspect"] and len(tail) == 5 and tail[-1] == "--raw"
                           and tail[3] in {x.get("reference") for x in getattr(self, "record", {}).get("cilium", {}).get("images", [])})
                       or (tail[:2] in [["scout", "cves"], ["scout", "sbom"]] and self.scan_command_allowed(tail)))
        elif args[:4] == ["git", "-C", str(ROOT), "rev-parse"] and args[4:] == ["HEAD", "MERGE_HEAD"]:
            allowed = True
        elif args[0] == "go" and args[1:2] == ["version"]:
            allowed = len(args) == 2 or (len(args) == 4 and args[2] == "-m" and Path(args[3]).parent == self.work / "payload")
        elif args == ["helm", "version", "--short"]:
            allowed = True
        elif args[:3] == ["helm", "template", "chg301-cilium-static"]:
            allowed = args[3:] == [str(self.work / "blobs/cilium-1.20.1.tgz"),
                "--namespace", "kube-system", "--kube-version", "1.36.4", "--include-crds",
                "--dry-run=client", "--values", str(self.work / "analysis/cilium-values.yaml")]
        elif args == ["memory_pressure", "-Q"]:
            allowed = True
        elif args[0] == str(GOVULNCHECK) and len(args) == 3 and args[1] == "-mode=extract":
            allowed = (Path(args[2]).parent == self.work / "payload" and file_sha(GOVULNCHECK) == GOVULNCHECK_SHA)
        elif args[0] == "gpg" and args[:6] == ["gpg", "--no-options", "--batch", "--homedir", str(self.work / "gpg"), "--no-default-keyring"]:
            allowed = (args[6:8] == ["--with-colons", "--show-keys"] and len(args) == 9
                       and Path(args[8]).parent == self.work / "raw" and Path(args[8]).name in DEBIAN_KEYS)
            allowed |= (args[6:7] == ["--dearmor"] and len(args) == 8
                        and args[7] == str(self.work / "analysis/debian-keys-v3.asc"))
        elif args[0] == "gpgv" and args[:5] == ["gpgv", "--homedir", str(self.work / "gpg"), "--keyring", str(self.work / "analysis/debian-keys-v3.gpg")]:
            allowed = (len(args) == 8 and args[5:7] == ["--status-fd", "1"]
                       and Path(args[7]).parent == self.work / "raw" and Path(args[7]).name in {"trixie.InRelease", "trixie-security.InRelease"})
        if not allowed:
            raise ValueError("static_command_scope")
        self.guard()
        if args[0] in self.record.get("tools", {}):
            identity = self.record["tools"][args[0]]
            if str(Path(shutil.which(args[0])).resolve()) != identity["path"] or file_sha(Path(identity["path"])) != identity["sha256"]:
                raise ValueError("tool_binary_drift")
        env = self.env.copy()
        if private_go:
            env = {"PATH": self.env["PATH"], "HOME": str(self.work), "GOENV": "off", "GOTOOLCHAIN": "local",
                   "GOWORK": "off", "GOTELEMETRY": "off", "GOPROXY": "off", "GOSUMDB": "off"}
        if args[0] == "helm":
            env.update(HOME=str(self.work), KUBECONFIG=str(self.work / "no-kubeconfig"),
                       HELM_PLUGINS=str(self.work / "no-plugins"), HELM_CONFIG_HOME=str(self.work / "helm-config"),
                       HELM_CACHE_HOME=str(self.work / "helm-cache"), HELM_DATA_HOME=str(self.work / "helm-data"))
        if args[0] in {"gpg", "gpgv"}:
            env = {"PATH": self.env["PATH"], "HOME": str(self.work), "GNUPGHOME": str(self.work / "gpg")}
        n = len(self.record["commands"])
        started = datetime.now(UTC).isoformat()
        remaining = (STOP_WORK - datetime.now(UTC)).total_seconds()
        with (self.work / "raw" / f"{n:03d}.stdout").open("xb") as out, (self.work / "raw" / f"{n:03d}.stderr").open("xb") as err:
            proc = subprocess.Popen(args, cwd=self.work, env=env, stdout=out, stderr=err, start_new_session=True)
            limit = time.monotonic() + min(timeout, remaining)
            peak = {"rss_bytes": 0, "cpu_percent": 0}
            try:
                while proc.poll() is None:
                    usage = process_usage(os.getpid())
                    peak = {k: max(peak[k], usage[k]) for k in peak}
                    if usage["rss_bytes"] > 4 * GiB or os.cpu_count() - os.getloadavg()[0] < 4:
                        raise ValueError("analysis_process_resource_limit")
                    if time.monotonic() >= limit:
                        raise ValueError("static_process_timeout")
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                raise
        self.record["commands"].append({"argv": args, "exit_code": proc.returncode, "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "process_tree_peak": peak,
            "stdout_sha256": file_sha(self.work / "raw" / f"{n:03d}.stdout"),
            "stderr_sha256": file_sha(self.work / "raw" / f"{n:03d}.stderr")})
        self.checkpoint()
        if proc.returncode:
            raise ValueError("static_tool_exit")
        return (self.work / "raw" / f"{n:03d}.stdout").read_bytes()

    def scan_command_allowed(self, tail):
        if len(tail) != 9 or tail[2:5] != ["--platform", "linux/arm64", "--format"] or tail[6] != "--output":
            return False
        if tail[5] != ("sarif" if tail[1] == "cves" else "spdx"):
            return False
        if Path(tail[7]).parent != self.work / "analysis" or Path(tail[7]).exists():
            return False
        allowed = {x["scan_reference"] for x in self.record.get("scan_inventory", []) if x.get("enabled")}
        return tail[8] in allowed

    def baseline(self):
        ids = self.command([*DOCKER, "ps", "-aq", "--no-trunc"]).decode().split()
        return {"containers": [json.loads(self.command([*DOCKER, "inspect", "--format",
            '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', i])) for i in sorted(ids)],
            "networks": sorted(self.command([*DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).decode().splitlines()),
            "images": sorted(self.command([*DOCKER, "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).decode().splitlines())}

    def fetch(self, url, target, *, expected=None, maximum=16 * 1024**2, headers=None, hosts=None):
        self.guard()
        if target.parent not in {self.work / "raw", self.work / "blobs"} or target.exists():
            raise ValueError("download_target")
        allowed = set(hosts or [])
        original = url
        start = time.monotonic()
        for hop in range(4):
            validate_url(url, allowed)
            try:
                response = self.opener.open(urllib.request.Request(url, headers=headers or {}), timeout=30)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise
                redirect = urllib.parse.urljoin(url, exc.headers.get("Location", ""))
                host = urllib.parse.urlsplit(redirect).hostname or ""
                # Known official Docker distribution blob CDN only; never forward credentials.
                # Docker's published distribution CDN allowlist (2026-05-20):
                # https://docs.docker.com/desktop/setup/allow-list/
                if host in {"production.cloudflare.docker.com", "production.cloudfront.docker.com"}:
                    allowed.add(host)
                validate_url(redirect, allowed)
                url, headers = redirect, {}
        else:
            raise ValueError("redirect_limit")
        h, count = hashlib.sha256(), 0
        with response, target.open("xb") as stream:
            target.chmod(0o600)
            if response.status != 200 or int(response.headers.get("Content-Length", 0)) > maximum:
                raise ValueError("download_length_status")
            while data := response.read(1024 * 1024):
                count += len(data)
                if count > maximum or time.monotonic() - start > 1200 or datetime.now(UTC) >= STOP_WORK:
                    raise ValueError("download_bound")
                h.update(data)
                stream.write(data)
            if expected and h.hexdigest() != expected.removeprefix("sha256:"):
                raise ValueError("download_digest")
        self.record["downloads"].append({"url": original, "redirect_hosts": sorted(allowed), "file": str(target.relative_to(self.work)),
                                          "sha256": h.hexdigest(), "bytes": count})
        self.checkpoint()
        return target

    def preflight(self):
        if self.command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split() != GIT_BASE:
            raise ValueError("git_parent_drift")
        self.record["source"] = source_snapshot()
        current = self.baseline()
        if "baseline_before" in self.record and current != self.record["baseline_before"]:
            raise ValueError("preflight_baseline_drift")
        self.record.setdefault("baseline_before", current)
        self.record["capacity"] = json.loads(self.command([*DOCKER, "info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}']))
        self.record["docker_stats"] = self.command([*DOCKER, "stats", "--no-stream", "--format", "{{.ID}} {{.CPUPerc}} {{.MemUsage}}"]).decode()
        # Docker totals are not VM available memory: report host static-analysis
        # headroom separately; do not assert that hidden Kubernetes use is zero.
        self.record["host_cpu_count"] = os.cpu_count()
        self.record["host_load_averages"] = list(os.getloadavg())
        if os.cpu_count() - os.getloadavg()[0] < 5:
            raise ValueError("host_cpu_headroom")
        pressure = self.command(["memory_pressure", "-Q"]).decode()
        total = re.search(r"system has (\d+)", pressure)
        free = re.search(r"memory free percentage: (\d+)%", pressure)
        if not total or not free:
            raise ValueError("host_memory_evidence_missing")
        total_bytes = int(total[1])
        free_bytes = total_bytes * int(free[1]) // 100
        if free_bytes < max(8 * GiB, total_bytes // 5) + 4 * GiB:
            raise ValueError("host_memory_headroom")
        self.record["host_memory"] = {"total_bytes": total_bytes, "available_estimate_bytes": free_bytes,
                                      "query": "memory_pressure -Q", "not_vm_available_memory": True}
        self.record["host_free_bytes"] = shutil.disk_usage(self.work).free
        for tool in ("go", "helm", "docker"):
            path = Path(shutil.which(tool)).resolve()
            self.record.setdefault("tools", {})[tool] = {"path": str(path), "sha256": file_sha(path)}
        self.record["go_version"] = self.command(["go", "version"], private_go=True).decode().strip()
        self.record["scout_version"] = self.command([*DOCKER, "scout", "version"]).decode().strip()
        self.record["helm_version"] = self.command(["helm", "version", "--short"]).decode().strip()
        self.record["phases"].append("preflight")
        self.checkpoint()

    def registry_node(self):
        self.guard()
        # Response token is transient in memory; never write credentials to raw evidence.
        token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:kindest/node:pull"
        validate_url(token_url, {"auth.docker.io"})
        with self.opener.open(token_url, timeout=30) as response:
            token = json.loads(response.read(1024**2))["token"]
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json"}
        prefix = "https://registry-1.docker.io/v2/kindest/node/"
        def get(kind, key, name, limit=16 * 1024**2):
            target = self.work / "blobs" / name
            if target.exists():
                if file_sha(target) != key.removeprefix("sha256:"):
                    raise ValueError("existing_blob_digest")
                return target
            return self.fetch(prefix + kind + "/" + key, target, expected=key, maximum=limit,
                              headers=headers, hosts={"registry-1.docker.io"})
        index = json.loads(get("manifests", NODE_INDEX, "node-index.json").read_bytes())
        entries = [m for m in index["manifests"] if m.get("platform", {}).get("architecture") == "arm64" and m.get("platform", {}).get("os") == "linux"]
        if len(entries) != 1 or entries[0]["digest"] != NODE_ARM64:
            raise ValueError("node_platform_identity")
        manifest = json.loads(get("manifests", NODE_ARM64, "node-manifest.json").read_bytes())
        config = json.loads(get("blobs", manifest["config"]["digest"], "node-config.json").read_bytes())
        if config.get("architecture") != "arm64" or config.get("os") != "linux" or len(manifest["layers"]) > 64:
            raise ValueError("node_config_identity")
        if len(config["rootfs"]["diff_ids"]) != len(manifest["layers"]):
            raise ValueError("node_layer_count")
        self.record["node"] = {"index": NODE_INDEX, "arm64": NODE_ARM64, "config": manifest["config"]["digest"], "layers": manifest["layers"]}
        self.checkpoint()
        effective = {}
        for n, (layer, diff) in enumerate(zip(manifest["layers"], config["rootfs"]["diff_ids"])):
            if layer["size"] > MAX_BLOB:
                raise ValueError("layer_compressed_limit")
            blob = get("blobs", layer["digest"], f"layer-{n:02d}.blob", MAX_BLOB)
            metadata = self.layer(blob, diff, n, layer["mediaType"])
            effective = apply_layer(effective, metadata)
            if len(effective) > 1_000_000:
                raise ValueError("image_entry_bound")
            print(json.dumps({"phase": "layer", "ordinal": n, "entries": len(metadata)}), flush=True)
        write_new(self.work / "analysis" / "node-files.json", effective)
        self.record["node"]["effective_files"] = len(effective)
        self.record["phases"].append("inventory-node")
        self.checkpoint()

    def layer(self, blob, expected_diff, ordinal, media_type):
        started = time.monotonic()
        raw = self.work / "blobs" / f"layer-{ordinal:02d}.tar"
        opener = gzip.open if "gzip" in media_type else open
        if "zstd" in media_type:
            raise ValueError("unsupported_zstd_layer")
        total, h = 0, hashlib.sha256()
        with opener(blob, "rb") as inp, raw.open("xb") as out:
            while data := inp.read(1024**2):
                total += len(data)
                if total > MAX_LAYER or datetime.now(UTC) >= STOP_WORK:
                    raise ValueError("layer_expansion_bound")
                if total % (64 * 1024**2) == 0:
                    self.guard()
                out.write(data)
                h.update(data)
        validate_layer_digest(h.hexdigest(), expected_diff)
        self.guard()
        rows = {}
        with tarfile.open(raw, mode="r:") as archive:
            for n, member in enumerate(archive):
                if n % 1000 == 0:
                    self.guard()
                    if time.monotonic() - started > 1200:
                        raise ValueError("layer_analysis_timeout")
                name = validate_archive_member(member, n, rows)
                row = {"mode": member.mode, "uid": member.uid, "gid": member.gid, "size": member.size}
                if member.isfile():
                    stream = archive.extractfile(member)
                    h = hashlib.sha256()
                    retained = selected_file(name)
                    payload = self.work / "payload" / sha(name.encode())
                    if payload.exists():
                        payload = self.work / "payload" / sha((str(ordinal) + name).encode())
                    out = payload.open("xb") if retained else None
                    try:
                        size = 0
                        while data := stream.read(1024**2):
                            size += len(data)
                            h.update(data)
                            if out:
                                out.write(data)
                        if size != member.size:
                            raise ValueError("archive_file_size")
                    finally:
                        if out:
                            out.close()
                            payload.chmod(0o600)
                    row.update(type="file", sha256=h.hexdigest(), payload=str(payload.relative_to(self.work)) if retained else None)
                elif member.isdir():
                    row.update(type="directory")
                elif member.issym():
                    row.update(type="symlink", link=member.linkname)
                elif member.islnk():
                    row.update(type="hardlink", link=safe_name(member.linkname))
                else:
                    row.update(type="special-not-materialized")
                rows[name] = row
        write_new(self.work / "analysis" / f"layer-{ordinal:02d}.json", rows)
        return rows

    def details(self):
        self.guard()
        files = json.loads((self.work / "analysis/node-files.json").read_bytes())
        binaries = []
        for name, row in files.items():
            if not row.get("payload"):
                continue
            path = self.work / row["payload"]
            if file_sha(path) != row["sha256"]:
                raise ValueError("retained_payload_drift")
            elf = elf_identity(path)
            if elf:
                output = self.command(["go", "version", "-m", str(path)], private_go=True).decode()
                binaries.append({"node_path": name, "sha256": row["sha256"], "elf": elf,
                                 "build_info": go_build_info(output), "payload": row["payload"],
                                 "limitations": "Build metadata only; no runtime/callgraph proof."})
        write_new(self.work / "analysis/node-binaries.json", binaries)
        # Containerd stores content-addressed blobs, not a conventional nested
        # archive. Read only small descriptors from verified layer tar files.
        prefix = "var/lib/containerd/io.containerd.content.v1.content/blobs/sha256/"
        descriptors = {}
        for ordinal, diff in enumerate(json.loads((self.work / "blobs/node-config.json").read_bytes())["rootfs"]["diff_ids"]):
            layer_path = self.work / "blobs" / f"layer-{ordinal:02d}.tar"
            if file_sha(layer_path) != diff.removeprefix("sha256:"):
                raise ValueError("retained_layer_drift")
            with tarfile.open(layer_path, "r:") as archive:
                for member in archive:
                    name = safe_name(member.name)
                    if not (name.startswith(prefix) and member.isfile() and member.size <= 1024**2):
                        continue
                    data = archive.extractfile(member).read(1024**2 + 1)
                    if sha(data) != PurePosixPath(name).name or files.get(name, {}).get("sha256") != sha(data):
                        raise ValueError("containerd_content_digest")
                    try:
                        value = json.loads(data)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(value, dict):
                        descriptors["sha256:" + sha(data)] = value
        write_new(self.work / "analysis/nested-descriptors.json", descriptors)
        images = []
        for digest, desc in descriptors.items():
            if "config" not in desc or "layers" not in desc:
                continue
            config = descriptors.get(desc["config"]["digest"])
            present = all(prefix + x["digest"].removeprefix("sha256:") in files for x in desc["layers"])
            images.append({"digest": digest, "config_digest": desc["config"]["digest"],
                "platform": {k: config.get(k) for k in ("os", "architecture")} if config else None,
                "annotations": desc.get("annotations", {}), "config": config,
                "all_layer_blobs_present": present, "parent_node": NODE_ARM64,
                "layer_count": len(desc["layers"]), "scan_status": "NOT_YET_SCANNED"})
        write_new(self.work / "analysis/nested-images.json", images)
        self.record["details"] = {"binaries": len(binaries), "content_descriptors": len(descriptors), "image_manifests": len(images)}
        self.record["phases"].append("details")
        self.checkpoint()

    def cilium(self):
        self.guard()
        index_path = self.work / "raw/cilium-index.yaml"
        if not index_path.exists():
            self.fetch("https://helm.cilium.io/index.yaml", index_path, hosts={"helm.cilium.io"})
        entries = [x for x in yaml.safe_load(index_path.read_bytes())["entries"]["cilium"] if x["version"] == "1.20.1"]
        if len(entries) != 1 or entries[0]["appVersion"] != "1.20.1" or entries[0]["urls"] != ["cilium-1.20.1.tgz"]:
            raise ValueError("chart_index_identity")
        entry = entries[0]
        archive_path = self.work / "blobs/cilium-1.20.1.tgz"
        if not archive_path.exists():
            self.fetch("https://helm.cilium.io/cilium-1.20.1.tgz", archive_path,
                       expected=entry["digest"], hosts={"helm.cilium.io"})
        if file_sha(archive_path) != entry["digest"]:
            raise ValueError("retained_chart_digest")
        content, total = {}, 0
        with tarfile.open(archive_path, "r:gz") as archive:
            for n, member in enumerate(archive):
                name = safe_name(member.name)
                total += member.size
                if n > 10000 or total > 64 * 1024**2 or name in content or not member.isfile():
                    raise ValueError("chart_archive_bound_or_type")
                content[name] = archive.extractfile(member).read().decode()
        chart = yaml.safe_load(content["cilium/Chart.yaml"])
        if chart["version"] != "1.20.1" or chart["appVersion"] != "1.20.1" or chart.get("dependencies"):
            raise ValueError("chart_identity_or_dependency")
        # Fixed chart's lookup sites are Hubble certificate handling and the
        # explicit k8sServiceHost=auto option. Both are disabled below. Helm's
        # client-only renderer also does not connect to a cluster (Helm docs).
        # Keep the earlier conservative rejection in history, not as a PASS.
        lookup_files = sorted(k for k, v in content.items() if re.search(r"{{[^}]*\blookup\b", v))
        if lookup_files != ["cilium/templates/_helpers.tpl", "cilium/templates/hubble/tls-helm/relay-client-secret.yaml",
                            "cilium/templates/hubble/tls-helm/server-secret.yaml"]:
            raise ValueError("unreviewed_chart_lookup_site")
        values = {"ipam": {"mode": "kubernetes"}, "kubeProxyReplacement": False,
                  "k8sServiceHost": "",
                  "hubble": {"enabled": False, "relay": {"enabled": False}, "ui": {"enabled": False}}}
        write_new(self.work / "analysis/cilium-values.yaml", yaml.safe_dump(values).encode())
        rendered = self.command(["helm", "template", "chg301-cilium-static", str(archive_path),
            "--namespace", "kube-system", "--kube-version", "1.36.4", "--include-crds",
            "--dry-run=client", "--values", str(self.work / "analysis/cilium-values.yaml")])
        write_new(self.work / "analysis/cilium-render.yaml", rendered)
        images = []
        for doc in yaml.safe_load_all(rendered):
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "Secret":
                raise ValueError("unexpected_rendered_secret")
            for row in image_fields(doc):
                images.append({**row, "resource": doc.get("kind", "") + "/" + doc.get("metadata", {}).get("name", ""),
                    "hook": doc.get("metadata", {}).get("annotations", {}).get("helm.sh/hook"),
                    "parent_chart_sha256": file_sha(archive_path)})
        write_new(self.work / "analysis/cilium-images.json", images)
        # Preserve every image-bearing source/default entry for manual disabled
        # feature accounting instead of assuming rendered list = all options.
        write_new(self.work / "analysis/cilium-chart-source.json", content)
        self.record["cilium"] = {"chart_sha256": file_sha(archive_path), "version": chart["version"],
                                 "render_sha256": sha(rendered), "images": images,
                                 "runtime_tested": False, "capabilities_limit": "Offline Kubernetes 1.36.4 defaults; no CRD discovery."}
        self.record["phases"].append("cilium")
        self.checkpoint()

    def scan(self):
        self.guard()
        nested = json.loads((self.work / "analysis/nested-images.json").read_bytes())
        descriptors = json.loads((self.work / "analysis/nested-descriptors.json").read_bytes())
        prefix = "var/lib/containerd/io.containerd.content.v1.content/blobs/sha256/"
        cas = self.work / "nested-content"
        cas.mkdir(mode=0o700)
        files = json.loads((self.work / "analysis/node-files.json").read_bytes())
        # Materialize CAS bytes only, never artifact paths, link targets or modes.
        for ordinal in range(len(self.record["node"]["layers"])):
            with tarfile.open(self.work / "blobs" / f"layer-{ordinal:02d}.tar", "r:") as archive:
                for member in archive:
                    name = safe_name(member.name)
                    if not (name.startswith(prefix) and member.isfile()):
                        continue
                    digest = PurePosixPath(name).name
                    if not re.fullmatch(r"[0-9a-f]{64}", digest) or member.size > MAX_BLOB:
                        raise ValueError("nested_blob_scope")
                    target = cas / digest
                    if target.exists():
                        raise ValueError("nested_duplicate_payload")
                    h = hashlib.sha256()
                    with archive.extractfile(member) as src, target.open("xb") as dst:
                        while data := src.read(1024**2):
                            h.update(data)
                            dst.write(data)
                    if h.hexdigest() != digest or files[name]["sha256"] != digest:
                        raise ValueError("nested_payload_hash")
                    self.guard()
        inventory = []
        for item in nested:
            if item["platform"] != {"os": "linux", "architecture": "arm64"}:
                continue
            digest = item["digest"]
            if not item["all_layer_blobs_present"]:
                raise ValueError("nested_incomplete_blob_closure")
            desc = descriptors[digest]
            label = digest[7:19]
            directory = self.work / ("oci-" + label)
            (directory / "blobs/sha256").mkdir(parents=True, mode=0o700)
            refs = []
            for parent in descriptors.values():
                refs += [x.get("annotations", {}).get("io.containerd.image.name") for x in parent.get("manifests", []) if x["digest"] == digest]
            refs = sorted({x for x in refs if x})
            entry = {"mediaType": desc["mediaType"], "digest": digest, "size": (cas / digest[7:]).stat().st_size,
                     "platform": item["platform"]}
            write_new(directory / "oci-layout", {"imageLayoutVersion": "1.0.0"})
            write_new(directory / "index.json", {"schemaVersion": 2, "manifests": [entry]})
            keys = [digest, desc["config"]["digest"], *[x["digest"] for x in desc["layers"]]]
            for key in set(keys):
                # Links created here only join run-owned verified regular CAS
                # files; no symlink/hardlink from the downloaded archive is used.
                source = cas / key[7:]
                if source.is_symlink() or not source.is_file() or file_sha(source) != key[7:]:
                    raise ValueError("nested_cas_identity")
                os.link(source, directory / "blobs/sha256" / key[7:])
            disabled = item["config"].get("config", {}).get("Cmd") == ["/bin/kindnetd"]
            inventory.append({"name": label, "parent": NODE_ARM64, "manifest_digest": digest,
                "config_digest": desc["config"]["digest"], "source_references": refs,
                "scan_reference": "oci-dir://" + str(directory), "enabled": not disabled,
                "reason": "Default kindnet disabled; approved CNI is Cilium" if disabled else "Preloaded ARM64 runtime/helper image",
                "entrypoint": item["config"].get("config", {}).get("Entrypoint"),
                "cmd": item["config"].get("config", {}).get("Cmd")})
        # Bind Cilium index -> ARM64 manifest using registry metadata only.
        for ref in sorted({x["reference"] for x in self.record["cilium"]["images"]}):
            if not re.fullmatch(r"quay\.io/cilium/[a-z0-9-]+:[a-zA-Z0-9._-]+@sha256:[0-9a-f]{64}", ref):
                raise ValueError("cilium_registry_reference")
            raw = self.command([*DOCKER, "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"])
            manifest = json.loads(raw)
            if manifest["digest"] != ref.split("@")[1]:
                raise ValueError("cilium_index_drift")
            platform = [x for x in manifest.get("manifests", []) if x.get("platform", {}).get("os") == "linux" and x.get("platform", {}).get("architecture") == "arm64"]
            if len(platform) != 1:
                raise ValueError("cilium_platform_missing")
            inventory.append({"name": ref.split("/")[-1].split(":")[0], "parent": self.record["cilium"]["chart_sha256"],
                "manifest_digest": platform[0]["digest"], "index_digest": manifest["digest"],
                "scan_reference": "registry://" + ref, "enabled": True, "reason": "Fixed chart rendered workload"})
        self.record["scan_inventory"] = inventory
        self.checkpoint()
        for item in inventory:
            if not item["enabled"]:
                continue
            self.guard()
            name = item["name"]
            print(json.dumps({"phase": "scan", "name": name}), flush=True)
            try:
                for mode, fmt in (("cves", "sarif"), ("sbom", "spdx")):
                    path = self.work / "analysis" / f"{name}.{fmt}.json"
                    self.command([*DOCKER, "scout", mode, "--platform", "linux/arm64", "--format", fmt,
                                  "--output", str(path), item["scan_reference"]], 1200)
                    item[fmt + "_sha256"] = file_sha(path)
                spdx = json.loads((self.work / "analysis" / f"{name}.spdx.json").read_bytes())
                purls = [x.get("referenceLocator", "") for p in spdx.get("packages", []) for x in p.get("externalRefs", [])]
                item["spdx_image_bound"] = any(x.startswith("pkg:oci/") and item["manifest_digest"] in x for x in purls)
                item["assessment"] = assess_sarif(json.loads((self.work / "analysis" / f"{name}.sarif.json").read_bytes()))
                item["scan_status"] = "RAW_SCAN_COMPLETE" if item["spdx_image_bound"] else "BLOCKED_SBOM_IMAGE_BINDING"
                item["database_version"] = "Scout does not expose DB revision; command timestamps retained"
            except (ValueError, OSError) as exc:
                item["scan_status"] = "BLOCKED_SCAN"
                item["error_type"] = type(exc).__name__
                self.record["gaps"].append({"phase": "scan", "name": name, "reason": str(exc) if isinstance(exc, ValueError) else "tool_error"})
            self.checkpoint()
        self.record["phases"].append("scan")
        self.checkpoint()

    def assess(self):
        self.guard()
        research_path = ROOT / "docs/CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json"
        if file_sha(research_path) != "c457eb15d3322451e6aefc544c70e1b969fa5b68cb8616f7224ef21c4f2f77ba":
            raise ValueError("prior_research_drift")
        research = json.loads(research_path.read_bytes())
        prior = Path(research["artifacts"]["root"])
        raw_path = prior / "all-severity.sarif.json"
        if file_sha(raw_path) != research["artifacts"][raw_path.name]:
            raise ValueError("prior_raw_drift")
        raw = json.loads(raw_path.read_bytes())["runs"][0]
        files = json.loads((self.work / "analysis/node-files.json").read_bytes())
        binaries = json.loads((self.work / "analysis/node-binaries.json").read_bytes())
        status = files["var/lib/dpkg/status"]
        packages = deb_packages((self.work / status["payload"]).read_text())
        installed_path = self.work / "analysis/debian-installed.json"
        if not installed_path.exists():
            write_new(installed_path, packages)
        elif json.loads(installed_path.read_bytes()) != packages:
            raise ValueError("installed_metadata_drift")
        def download(url, name, hosts, maximum=16*1024**2):
            path = self.work / "raw" / name
            if not path.exists():
                self.fetch(url, path, hosts=hosts, maximum=maximum)
            binding = [x for x in self.record["downloads"] if x["file"] == str(path.relative_to(self.work))]
            if len(binding) != 1 or file_sha(path) != binding[0]["sha256"]:
                raise ValueError("source_download_binding")
            return json.loads(path.read_bytes())
        # The full tracker exceeded the fixed 64 MiB request budget (74,178,057
        # bytes). Preserve its failed zero-byte artifact, do not enlarge limits.
        # Fetch only the 32 approved CVE pages, bounded to 512 KiB each.
        goindex = download("https://vuln.go.dev/index/vulns.json", "go-vulns-index.json", {"vuln.go.dev"})
        download("https://vuln.go.dev/index/db.json", "go-db.json", {"vuln.go.dev"})
        alias = {}
        for item in goindex:
            for key in [item["id"], *item.get("aliases", [])]:
                alias.setdefault(key, []).append(item["id"])
        capabilities = []
        for binary in binaries:
            out = self.command([str(GOVULNCHECK), "-mode=extract", str(self.work / binary["payload"])], private_go=True)
            messages = [json.loads(line) for line in out.splitlines() if line.strip()]
            capability = {"node_path": binary["node_path"], "binary_sha256": binary["sha256"],
                "tool_sha256": GOVULNCHECK_SHA, "output_sha256": sha(out),
                "symbols_count": sum(len(m.get("symbols", [])) for m in messages),
                "extraction_not_callgraph": True, "source_closure_verified": False,
                "limitation": "No complete compiled package/call graph; source/environment parity not established."}
            capabilities.append(capability)
        write_new(self.work / "analysis/binary-analysis-capability.json", capabilities)
        ledger = []
        for finding in research["candidate"]["findings"]:
            self.guard()
            fid = finding["id"]
            rules = [x for x in raw["tool"]["driver"]["rules"] if x["id"] == fid]
            matches = [x for x in raw["results"] if x["ruleId"] == fid]
            row = {"id": fid, "raw_severity": finding["severity"], "purls": finding["purls"],
                   "raw_sarif_sha256": file_sha(raw_path), "node_manifest": NODE_ARM64,
                   "raw_rules": rules, "raw_instances": matches, "actual_components": [],
                   "official_advisories": [], "assessment": "INDETERMINATE", "accepted": False,
                   "limitations": [], "repair_materials": []}
            paths = sorted({loc["physicalLocation"]["artifactLocation"]["uri"].lstrip("/") for match in matches for loc in match.get("locations", [])})
            row["actual_locations"] = [{"path": path, **files.get(path, {"type": "NOT_IN_EFFECTIVE_VIEW"})} for path in paths]
            for purl in finding["purls"]:
                name, version = purl_parts(purl)
                if purl.startswith("pkg:deb/"):
                    row["actual_components"] += [x for x in packages if x["source"] == name]
                    page = self.work / "raw" / (fid + ".html")
                    if not page.exists():
                        self.fetch("https://security-tracker.debian.org/tracker/" + fid, page,
                                   hosts={"security-tracker.debian.org"}, maximum=512*1024)
                    parsed = AdvisoryHTML()
                    parsed.feed(page.read_text())
                    row["official_advisories"].append({"url": "https://security-tracker.debian.org/tracker/" + fid,
                        "tables": parsed.rows, "text": " ".join(parsed.text), "snapshot_sha256": file_sha(page)})
                    fixed = None
                    row["repair_materials"].append({"component": name, "installed_source": version,
                        "proposed_version": fixed, "status": "UNRESOLVED_SIGNED_PACKAGE_AND_DEPENDENCY_CLOSURE",
                        "note": "Tracker status refers to Debian archive, not this image; no image patch applied."})
                    row["limitations"].append("Installed package metadata bound; official patch/package signature and source closure not yet established.")
                else:
                    for binary in binaries:
                        deps = binary["build_info"]["modules"]
                        matched = [d for d in deps if d["name"] == name and d["version"].removeprefix("v") == version]
                        if name == "stdlib" and binary["build_info"].get("go_version", "").removeprefix("go") == version:
                            matched = [{"name": "stdlib", "version": version}]
                        if matched:
                            row["actual_components"].append({"binary": binary["node_path"], "sha256": binary["sha256"],
                                "elf": binary["elf"], "modules": matched, "build_settings": binary["build_info"]["build_settings"]})
                    row["repair_materials"].append({"component": name, "installed_version": version,
                        "status": "UNRESOLVED_OFFICIAL_BINARY_OR_REBUILD", "binary_rebuild_may_be_required": True,
                        "note": "Do not replace embedded Go modules as standalone files."})
                    row["limitations"].append("Build-info/module presence is not reachability; stripped/partial symbol evidence cannot prove not affected.")
            for goid in sorted(set(alias.get(fid, []))):
                if not re.fullmatch(r"GO-\d{4}-\d+", goid):
                    raise ValueError("official_go_id")
                value = download("https://vuln.go.dev/ID/" + goid + ".json", goid + ".json", {"vuln.go.dev"})
                row["official_advisories"].append({"url": "https://vuln.go.dev/ID/" + goid + ".json",
                    "osv": value, "sha256": file_sha(self.work / "raw" / (goid + ".json"))})
            if not row["official_advisories"]:
                row["limitations"].append("No matching Go database alias; upstream advisory/source comparison remains required.")
            row["limitations"] = sorted(set(row["limitations"]))
            ledger.append(row)
        if len(ledger) != 59 or {x["id"] for x in ledger} != {x["id"] for x in research["candidate"]["findings"]}:
            raise ValueError("incomplete_original_ledger")
        write_new(self.work / "analysis/node-assessment-ledger.json", ledger)
        self.record["ledger"] = {"entries": len(ledger), "path": "analysis/node-assessment-ledger.json",
                                "sha256": file_sha(self.work / "analysis/node-assessment-ledger.json"),
                                "status": "TRIAGE_RECORDED_NOT_APPLICABILITY_PASS"}
        self.record["phases"].append("assess")
        self.checkpoint()

    def materials(self):
        self.guard()
        (self.work / "gpg").mkdir(mode=0o700, exist_ok=True)
        keys = []
        def bound_fetch(url, path, **kwargs):
            if not path.exists():
                return self.fetch(url, path, **kwargs)
            rows = [x for x in self.record["downloads"] if x["file"] == str(path.relative_to(self.work)) and x["url"] == url]
            if len(rows) != 1 or file_sha(path) != rows[0]["sha256"]:
                raise ValueError("existing_material_identity")
            if kwargs.get("expected") and file_sha(path) != kwargs["expected"]:
                raise ValueError("existing_material_index_digest")
            return path
        for tool in ("gpg", "gpgv"):
            path = Path(shutil.which(tool)).resolve()
            self.record.setdefault("tools", {})[tool] = {"path": str(path), "sha256": file_sha(path)}
        for name, fingerprint in DEBIAN_KEYS.items():
            path = bound_fetch("https://ftp-master.debian.org/keys/" + name, self.work / "raw" / name,
                              hosts={"ftp-master.debian.org"}, maximum=1024**2)
            data = self.command(["gpg", "--no-options", "--batch", "--homedir", str(self.work / "gpg"),
                                 "--no-default-keyring", "--with-colons", "--show-keys", str(path)]).decode()
            fingerprints = [line.split(":")[9] for line in data.splitlines() if line.startswith("fpr:")]
            if not fingerprints or fingerprints[0] != fingerprint:
                raise ValueError("debian_official_key_fingerprint")
            keys.append(path.read_bytes())
        write_new(self.work / "analysis/debian-keys-v3.asc", b"\n".join(keys))
        self.command(["gpg", "--no-options", "--batch", "--homedir", str(self.work / "gpg"),
                      "--no-default-keyring", "--dearmor", str(self.work / "analysis/debian-keys-v3.asc")])
        # --dearmor FILE writes FILE.gpg by default; use the produced file,
        # not any shared system keyring. Empty stdout is normal.
        generated_keyring = self.work / "analysis/debian-keys-v3.asc.gpg"
        if not generated_keyring.is_file() or not generated_keyring.stat().st_size:
            raise ValueError("private_debian_keyring_missing")
        generated_keyring.rename(self.work / "analysis/debian-keys-v3.gpg")
        installed = json.loads((self.work / "analysis/debian-installed.json").read_bytes())
        ledger = json.loads((self.work / "analysis/node-assessment-ledger.json").read_bytes())
        wanted = {purl_parts(p)[0] for row in ledger for p in row["purls"] if p.startswith("pkg:deb/")}
        selected = []
        for suite, base in (("trixie", "https://deb.debian.org/debian"), ("trixie-security", "https://security.debian.org/debian-security")):
            host = urllib.parse.urlsplit(base).hostname
            release_path = bound_fetch(base + "/dists/" + suite + "/InRelease", self.work / "raw" / (suite + ".InRelease"), hosts={host})
            verification = self.command(["gpgv", "--homedir", str(self.work / "gpg"), "--keyring", str(self.work / "analysis/debian-keys-v3.gpg"),
                                         "--status-fd", "1", str(release_path)]).decode()
            release = release_path.read_text()
            digest, size, index_name = signed_release_index(release, verification, suite, datetime.now(UTC))
            index = bound_fetch(base + "/dists/" + suite + "/" + index_name, self.work / "raw" / (suite + ".Packages.xz"),
                               expected=digest, hosts={host}, maximum=32*1024**2)
            total, buffer = 0, ""
            with lzma.open(index, "rt") as stream:
                for line in stream:
                    total += len(line.encode())
                    if total > 256*1024**2:
                        raise ValueError("debian_package_expansion_bound")
                    if line.strip():
                        buffer += line
                        if len(buffer) > 1024**2:
                            raise ValueError("debian_stanza_bound")
                        continue
                    fields = dict(v.split(": ", 1) for v in buffer.splitlines() if ": " in v and not v.startswith(" "))
                    buffer = ""
                    source = fields.get("Source", fields.get("Package", "")).split(" ", 1)[0]
                    if source in wanted and any(x["package"] == fields.get("Package") for x in installed):
                        selected.append({"suite": suite, "source": source, "package": fields["Package"],
                            "version": fields["Version"], "architecture": fields["Architecture"],
                            "url": base + "/" + fields["Filename"], "sha256": fields["SHA256"], "bytes": int(fields["Size"]),
                            "depends": fields.get("Depends"), "pre_depends": fields.get("Pre-Depends"),
                            "release_sha256": file_sha(release_path), "index_sha256": digest,
                            "signature_status": "VALID_WITH_OFFICIAL_TLS_FETCHED_KEYS", "payload_downloaded": False,
                            "dependency_closure": "UNRESOLVED_NOT_AN_EXECUTABLE_LOCK"})
        write_new(self.work / "analysis/debian-material-candidates.json", selected)
        self.record["materials"] = {"candidate_packages": len(selected), "signature_trust": "Public HTTPS keys + published fingerprints; no independent out-of-band trust validation",
            "status": "PROPOSAL_ONLY_DEPENDENCY_CLOSURE_UNRESOLVED", "no_package_install": True}
        self.record["phases"].append("materials")
        self.checkpoint()

    def retained_file(self, name):
        """Read selected bytes from verified layers without materializing links."""
        files = json.loads((self.work / "analysis/node-files.json").read_bytes())
        row = files[safe_name(name)]
        if row["type"] != "file" or row["size"] > 10 * 1024**2:
            raise ValueError("selected_file_type_size")
        if row.get("payload"):
            path = self.work / row["payload"]
            if file_sha(path) != row["sha256"]:
                raise ValueError("selected_file_digest")
            return path
        config = json.loads((self.work / "blobs/node-config.json").read_bytes())
        for ordinal, diff in enumerate(config["rootfs"]["diff_ids"]):
            tarpath = self.work / "blobs" / f"layer-{ordinal:02d}.tar"
            if file_sha(tarpath) != diff.removeprefix("sha256:"):
                raise ValueError("selected_layer_digest")
            with tarfile.open(tarpath, "r:") as archive:
                for member in archive:
                    if safe_name(member.name) != name or not member.isfile() or member.size != row["size"]:
                        continue
                    data = archive.extractfile(member).read(10 * 1024**2 + 1)
                    if sha(data) == row["sha256"]:
                        target = self.work / "payload" / sha(("extra:" + name).encode())
                        write_new(target, data)
                        self.record.setdefault("extra_files", []).append({"node_path": name, "sha256": sha(data), "payload": str(target.relative_to(self.work))})
                        return target
        raise ValueError("selected_effective_file_missing")

    def supplement(self):
        self.guard()
        tag = self.command([*DOCKER, "buildx", "imagetools", "inspect", NODE, "--raw"])
        if sha(tag) != NODE_INDEX.removeprefix("sha256:"):
            # Some buildx versions append a newline; it is not part of the OCI
            # object and must not become an excuse to accept altered JSON.
            if not tag.endswith(b"\n") or sha(tag[:-1]) != NODE_INDEX.removeprefix("sha256:"):
                raise ValueError("node_tag_digest_drift")
        self.record["tag_recheck"] = {"reference": NODE, "index_digest": NODE_INDEX, "observed_at": datetime.now(UTC).isoformat(), "precheck_limitation": "Earlier research verified tag; this run initially fetched digest directly, not a fresh tag precheck."}
        upstream = {}
        for ident, repo in (("GHSA-2v4p-qf9q-27wj", "grpc/grpc-go"),
                            ("GHSA-vp52-pcj8-j9qc", "grpc/grpc-go"),
                            ("GHSA-p7v4-vr35-mj6f", "containerd/containerd")):
            url = "https://github.com/" + repo + "/security/advisories/" + ident
            path = self.fetch(url, self.work / "raw" / (ident + ".html"), hosts={"github.com"}, maximum=3 * 1024**2)
            upstream[ident] = {"url": url, "sha256": file_sha(path)}
        perl = self.retained_file("usr/bin/perl")
        config = self.retained_file("usr/lib/aarch64-linux-gnu/perl-base/Config.pm")
        heavy = self.retained_file("usr/lib/aarch64-linux-gnu/perl-base/Config_heavy.pl")
        content = config.read_text() + "\n" + heavy.read_text()
        sizes = {k: re.findall(r"(?:^|\n)\s*" + k + r"\s*(?:=>|=)\s*['\"]?(\d+)", content) for k in ("ivsize", "ptrsize", "sizesize")}
        self.record["perl_architecture"] = {"elf": elf_identity(perl), "binary_sha256": file_sha(perl), "config_sha256": [file_sha(config), file_sha(heavy)], "sizes": sizes}
        ledger = json.loads((self.work / "analysis/node-assessment-ledger.json").read_bytes())
        packages = json.loads((self.work / "analysis/debian-material-candidates.json").read_bytes())
        for row in ledger:
            row["assessment_basis"] = "Module presence is insufficient to prove vulnerable code or runtime reachability; no complete source closure."
            row["trigger_evidence"] = []
            for advisory in row["official_advisories"]:
                if "osv" in advisory:
                    osv = advisory["osv"]
                    row["trigger_evidence"].append({"url": advisory["url"], "summary": osv.get("summary"),
                        "affected_packages": [{"package": x["package"], "ranges": x.get("ranges"), "imports": x.get("ecosystem_specific", {}).get("imports")} for x in osv.get("affected", [])]})
                    for material in row["repair_materials"]:
                        material.setdefault("upstream_fixed_versions", []).extend({"url": advisory["url"], "version": e["fixed"]} for x in osv.get("affected", []) if x["package"]["name"] == material["component"] for r in x.get("ranges", []) for e in r.get("events", []) if "fixed" in e)
                if "tables" in advisory:
                    row["trigger_evidence"].extend({"url": advisory["url"], "description": x[1]} for x in advisory["tables"] if len(x) == 2 and x[0] == "Description")
                    for material in row["repair_materials"]:
                        fixed = debian_fixed_versions(advisory["tables"], material["component"])
                        material["upstream_fixed_versions"] = fixed
                        material["signed_index_candidates"] = [p for p in packages if p["source"] == material["component"] and p["version"] in fixed]
                        material["status"] = "OFFICIAL_CANDIDATE_METADATA_DEPENDENCY_CLOSURE_UNRESOLVED" if material["signed_index_candidates"] else "UNRESOLVED_NO_BOUND_FIXED_PACKAGE"
                    row["assessment"] = "AFFECTED"
                    row["assessment_basis"] = "Installed Debian source version is on the reported affected branch and precedes the source-qualified Debian fix; package-level conservative assessment, not a demonstrated runtime exploit."
                    if row["id"] == "CVE-2026-85091":
                        row["assessment"] = "INDETERMINATE"
                        row["assessment_basis"] = "Tracker flags Debian 1.3.1, but description starts at upstream 1.3.1.2; patch/source comparison unresolved and no bound fixed package."
            if row["id"] in {"CVE-2026-84445", "CVE-2026-84304"}:
                ident = "GHSA-2v4p-qf9q-27wj" if row["id"] == "CVE-2026-84445" else "GHSA-vp52-pcj8-j9qc"
                row["official_advisories"].append(upstream[ident])
                row["trigger_evidence"].append({"url": upstream[ident]["url"], "condition": "xDS gRPC server missing authority/Host triggers panic" if row["id"] == "CVE-2026-84445" else "Tiny HTTP/2 DATA frames cause server receive-buffer memory exhaustion"})
                for material in row["repair_materials"]:
                    material["upstream_fixed_versions"] = ["1.83.2", "1.82.2"] if row["id"] == "CVE-2026-84445" else ["1.83.1"]
            if row["id"] == "CVE-2026-8376" and elf_identity(perl) == {"class_bits": 64, "machine": 183, "architecture": "arm64"} and all(sizes[k] and set(sizes[k]) == {"8"} for k in sizes):
                row["assessment"] = "PROPOSED_NOT_AFFECTED"
                row["assessment_basis"] = "Exact Perl ELF64 ARM64 and ivsize/ptrsize/sizesize=8 do not match the advisory's 32-bit-build condition; proposal only, not a waiver."
                row["architecture_evidence"] = self.record["perl_architecture"]
        write_new(self.work / "analysis/node-assessment-final.json", ledger)
        self.record["final_ledger"] = {"path": "analysis/node-assessment-final.json", "sha256": file_sha(self.work / "analysis/node-assessment-final.json"), "entries": len(ledger), "classifications": dict(Counter(x["assessment"] for x in ledger)), "accepted": 0}
        supplemental = {"id": "GHSA-p7v4-vr35-mj6f", "source": upstream["GHSA-p7v4-vr35-mj6f"], "assessment": "INDETERMINATE", "separate_from_original_59": True,
            "main_daemon": "containerd 2.3.4 disables the experimental checkpoint restore by default; future effective runtime config is unverified.",
            "snapshotter": "Embeds containerd 2.2.0; daemon and optional snapshotter package reachability cannot be conflated.", "runtime_required": "Verify effective containerd config has no enable_experimental_restore_via_create opt-in; no such runtime performed."}
        write_new(self.work / "analysis/containerd-supplemental.json", supplemental)
        image_ledger = []
        for item in self.record["scan_inventory"]:
            if not item["enabled"]:
                continue
            raw = json.loads((self.work / "analysis" / (item["name"] + ".sarif.json")).read_bytes())["runs"][0]
            sbom = json.loads((self.work / "analysis" / (item["name"] + ".spdx.json")).read_bytes())
            for rule in raw["tool"]["driver"].get("rules", []):
                instances = [r for r in raw["results"] if r["ruleId"] == rule["id"]]
                image_ledger.append({"image": item["name"], "manifest_digest": item["manifest_digest"], "id": rule["id"],
                    "raw_rule": rule, "raw_instances": instances, "assessment": "INDETERMINATE", "accepted": False,
                    "sarif_sha256": item["sarif_sha256"], "spdx_sha256": item["spdx_sha256"],
                    "package_count": len(sbom["packages"]), "limitation": "Raw package/binary findings retained; per-component official source closure and repair artifact dependency closure not completed. No inherited waiver."})
        write_new(self.work / "analysis/additional-image-findings.json", image_ledger)
        self.record["additional_image_ledger"] = {"entries": len(image_ledger), "unique_ids": len({x["id"] for x in image_ledger}), "path": "analysis/additional-image-findings.json", "sha256": file_sha(self.work / "analysis/additional-image-findings.json")}
        self.record["phases"].append("supplement")
        self.checkpoint()

    def evidence(self):
        self.guard()
        immutable = {
            "docs/CHG-301-R2-NODE-REMEDIATION-RESEARCH.md": "108971961a27e7b11ac33b2d251d7854e5e9c21f01dc3bc60dfab2ed09adf785",
            "docs/CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json": "c457eb15d3322451e6aefc544c70e1b969fa5b68cb8616f7224ef21c4f2f77ba",
            "backend/scripts/chg301_r2_ingress.py": "3cd35bbc03c1f65151fc22b6d951baedcacd067d5755c895d948c52f58406675",
            "backend/scripts/chg301_r2_node_candidate.py": "c91d15f80e2d84040d84051325d21ac3d3244be0dee2344ba4e7620f6ebe53db",
            "backend/tests/test_chg301_r2_ingress.py": "b96bbdb98544b2e56c5b74605f9f42e0ab0ae1518fa5aa84be88d34cec69ac40",
            "docs/CHG-301-R2-APPLICABILITY-ACCEPTANCE.json": "87c5c7b4e26e363a51a8328780955b93d57855d40821e51f2e883807b10a7110"}
        # The original report digest is explicit, not recomputed as an expected
        # value. Retain its previous result rather than recasting it as new.
        for name, digest in immutable.items():
            if file_sha(ROOT / name) != digest:
                raise ValueError("immutable_prior_evidence_drift")
        self.record["immutable_rechecks"] = immutable
        if self.baseline() != self.record["baseline_before"]:
            raise ValueError("final_docker_baseline_drift")
        final = json.loads((self.work / "analysis/node-assessment-final.json").read_bytes())
        summary_rows = []
        for row in final:
            summary_rows.append({"id": row["id"], "raw_severity": row["raw_severity"],
                "assessment": row["assessment"], "assessment_basis": row["assessment_basis"], "accepted": False,
                "purls": row["purls"], "locations": [{k: x.get(k) for k in ("path", "type", "sha256")} for x in row["actual_locations"]],
                "components": row["actual_components"],
                "official_sources": [{k: x.get(k) for k in ("url", "snapshot_sha256", "sha256") if x.get(k)} for x in row["official_advisories"]],
                "materials": row["repair_materials"], "limitations": row["limitations"]})
        write_new(self.work / "analysis/public-node-ledger.json", summary_rows)
        additional = json.loads((self.work / "analysis/additional-image-findings.json").read_bytes())
        additional_summary = [{"image": x["image"], "manifest_digest": x["manifest_digest"], "id": x["id"],
            "raw_severity": x["raw_rule"].get("properties", {}).get("cvssV3_severity", "UNSPECIFIED"),
            "assessment": x["assessment"], "accepted": False,
            "package_instances": [{"properties": r.get("properties"), "locations": r.get("locations")} for r in x["raw_instances"]],
            "sarif_sha256": x["sarif_sha256"], "spdx_sha256": x["spdx_sha256"]} for x in additional]
        write_new(self.work / "analysis/public-additional-ledger.json", additional_summary)
        self.record["assessment_status"] = "PARTIAL_RUNTIME_BLOCKED"
        self.record["outstanding"] = [
            "27 Go applicability cases lack full compiled source/import closure; zero extracted symbols are not absence evidence.",
            "zlib upstream versus Debian version applicability is unresolved.",
            "339 additional per-image advisory entries (139 IDs) have real raw evidence, but their official source-level applicability and repair closure remain unresolved.",
            "Debian candidate package URLs/hash/dependencies are signed-index metadata only, not downloaded payloads or complete solver closure.",
            "One Perl architecture-based not-affected proposal is not accepted; no new waiver.",
            "No effective runtime containerd/Cilium/Ingress test; full R2 and 80% coverage gates are unchanged.",
            "Tag precheck was inherited earlier research, not freshly observed before download; current tag recheck matches pinned index."]
        self.record["phases"].append("evidence")
        self.checkpoint()

    def cleanup(self):
        self.guard()
        files = json.loads((self.work / "analysis/node-files.json").read_bytes())
        configuration = files["etc/containerd/config.toml"]
        entrypoint = files["usr/local/bin/entrypoint"]
        for row in (configuration, entrypoint):
            if file_sha(self.work / row["payload"]) != row["sha256"]:
                raise ValueError("final_containerd_source_drift")
        config_text = (self.work / configuration["payload"]).read_text()
        entrypoint_text = (self.work / entrypoint["payload"]).read_text()
        self.record["containerd_configuration"] = {
            "config_sha256": configuration["sha256"], "entrypoint_sha256": entrypoint["sha256"],
            "base_uses_overlayfs": 'snapshotter = "overlayfs"' in config_text,
            "base_restore_optin_present": "enable_experimental_restore_via_create" in config_text,
            "entrypoint_can_enable_fuse_service": "systemctl enable containerd-fuse-overlayfs" in entrypoint_text,
            "effective_runtime_verified": False}
        acceptance = json.loads((ROOT / "docs/CHG-301-R2-APPLICABILITY-ACCEPTANCE.json").read_bytes())
        retained = Path("/private/tmp/chg301-r2-two-lib-say0hh9k")
        for name, key in (("all-severity.sarif.json", "rawSarifSha256"), ("sbom.spdx.json", "rawSpdxSha256")):
            if file_sha(retained / name) != acceptance[key]:
                raise ValueError("traefik_accepted_raw_drift")
        self.record["traefik_recheck"] = {"image_id": acceptance["imageId"], "binary_sha256": acceptance["binarySha256"],
            "raw_sarif_sha256": acceptance["rawSarifSha256"], "raw_spdx_sha256": acceptance["rawSpdxSha256"],
            "existing_acceptance_sha256": file_sha(ROOT / "docs/CHG-301-R2-APPLICABILITY-ACCEPTANCE.json"),
            "not_reexecuted": True, "not_extended_to_node": True}
        scout = Path("/Applications/Docker.app/Contents/Resources/cli-plugins/docker-scout")
        self.record["scout_binary_closeout"] = {"path": str(scout), "sha256": file_sha(scout),
            "limitation": "Recorded at closeout; individual scan command times/version retained, not an initial binary attestation."}
        # Only a failed, zero-length metadata transfer. Verified public OCI,
        # source snapshots, signatures and raw scans remain available for audit.
        relative = "raw/debian-tracker.json"
        identity = exact_owned_file(self.work, relative)
        if identity["bytes"] != 0 or identity["sha256"] != sha(b""):
            raise ValueError("cleanup_target_not_failed_empty_download")
        write_new(self.work / "analysis/cleanup-dry-run.json", [identity])
        exact_owned_file(self.work, relative, identity)
        (self.work / relative).unlink()
        self.record["cleanup"] = {"removed": [identity], "removed_bytes": 0,
            "retention_reason": "Retain verified public artifacts, raw scans, signature failures/successes, source metadata and test reports for reproducibility; no shared cache or prior evidence removed.",
            "retained_logical_bytes": sum(p.stat().st_size for p in self.work.rglob("*") if p.is_file() and not p.is_symlink())}
        self.record["phases"].append("cleanup")
        self.checkpoint()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["preflight", "inventory", "details", "cilium", "scan", "assess", "materials", "supplement", "evidence", "cleanup"] , required=True)
    parser.add_argument("--run-manifest")
    args = parser.parse_args()
    if os.environ.get("CHG301_R2_ISOLATED") != "1":
        raise SystemExit("explicit isolated opt-in required")
    run = Qualification(args.run_manifest)
    try:
        {"preflight": run.preflight, "inventory": run.registry_node, "details": run.details, "cilium": run.cilium, "scan": run.scan, "assess": run.assess, "materials": run.materials, "supplement": run.supplement, "evidence": run.evidence, "cleanup": run.cleanup}[args.phase]()
        run.record["status"] = "STATIC_PHASE_COMPLETE_RUNTIME_NOT_AUTHORIZED"
    except Exception as exc:
        run.record["status"] = "BLOCKED_STATIC_PHASE"
        run.record["gaps"].append({"phase": args.phase, "error_type": type(exc).__name__,
                                  "reason": str(exc) if isinstance(exc, ValueError) else "tool_or_network_error"})
    finally:
        if "baseline_before" in run.record:
            try:
                run.record["baseline_after"] = run.baseline()
                run.record["baseline_unchanged"] = run.record["baseline_before"] == run.record["baseline_after"]
                if not run.record["baseline_unchanged"]:
                    run.record["status"] = "BLOCKED_BASELINE_DRIFT"
            except Exception:
                run.record["status"] = "BLOCKED_BASELINE_CHECK"
        run.record["finished_at"] = datetime.now(UTC).isoformat()
        run.checkpoint()
        print(json.dumps({"status": run.record["status"], "manifest": str(run.manifest), "gaps": run.record["gaps"]}, indent=2))
    return 0 if run.record["status"] == "STATIC_PHASE_COMPLETE_RUNTIME_NOT_AUTHORIZED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
