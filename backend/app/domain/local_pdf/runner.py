"""Sequential, bounded Poppler/Tesseract PDF processing inside the Worker.

Preserves blank pages, page order and existing text-first/OCR selection. Not a
network or credential sandbox. Caller supplies the immutable DB policy snapshot.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import time
from uuid import uuid4

from .errors import need
from .files import PageStore, Workspace, ensure_root
from .process import Tools

PROGRAMS = {"text", "split", "local_ocr", "text_or_split", "text_or_local_ocr"}


class LocalPDF:
    def __init__(self, settings, policy, *, heartbeat, progress):
        self.settings, self.policy = settings, policy
        self.heartbeat, self.progress = heartbeat, progress
        self.launch_uid = str(uuid4())
        self.work = self.store = self.tools = None
        self.cleaned = False
        self.setup_failed = False
        self.setup_state = "new"
        self.setup_cleanup_confirmed = False

    def setup(self):
        need(self.setup_state == "new", "runtime_unavailable")
        self.setup_state = "preparing"
        try:
            ensure_root(self.settings.pdf_scratch_dir)
            self.work = Workspace(self.settings.pdf_scratch_dir, deferred=True)
            self.work.open()
            self.store = PageStore(self.settings.pdf_scratch_dir, deferred=True)
            self.store.open()
            self.tools = Tools(cwd=self.work.path,
                deadline=time.monotonic() + self.policy["pdf_parser_timeout_seconds"],
                scratch_limit=self.policy["pdf_parser_scratch_mib"] * 1024**2,
                check=self.check_budget, heartbeat=self.heartbeat,
                retry_attempts=self.policy["pdf_parser_retry_max_attempts"],
                retry_delay=self.policy["pdf_parser_retry_delay_seconds"],
                retry_codes=self.policy["pdf_parser_retryable_error_codes"])
        except BaseException:
            self.setup_failed = True
            self.setup_state = "failed"
            # No command can run before setup returns. Clean every recorded
            # allocation, including a constructor/open that failed partway.
            cleanup_ok = True
            for store in (self.work, self.store):
                if store is not None:
                    try:
                        store.close()
                    except BaseException:
                        cleanup_ok = False
            self.setup_cleanup_confirmed = cleanup_ok
            raise
        self.setup_state = "ready"

    def command(self, name, *args, stdout_limit=65536):
        need(self.setup_state == "ready" and not self.cleaned, "runtime_unavailable")
        configured = shlex.split(getattr(self.settings, name))
        need(bool(configured), "runtime_unavailable")
        executable = shutil.which(configured[0])
        need(executable is not None, "runtime_unavailable")
        return self.tools.run([str(Path(executable).absolute()), *configured[1:], *map(str, args)], stdout_limit=stdout_limit)

    def check_budget(self):
        need(self.work.usage() + self.store.bytes <= self.policy["pdf_parser_scratch_mib"] * 1024**2, "scratch_limit")

    def check_encoding(self):
        root = Path(self.settings.pdf_encoding_data_dir)
        need(root.is_absolute(), "runtime_unavailable")
        for name in ("cMap/Adobe-CNS1/UniCNS-UCS2-H", "cMap/Adobe-CNS1/UniCNS-UTF16-H", "cidToUnicode/Adobe-CNS1"):
            fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                meta = os.fstat(fd)
                need(stat.S_ISREG(meta.st_mode) and 0 < meta.st_size <= 4*1024**2, "runtime_unavailable")
            finally:
                os.close(fd)

    def inventory(self, source, *extra):
        data = self.command("pdf_info_command", *extra, source).decode("utf-8", errors="strict")
        need(not re.search(r"^Encrypted:\s+yes", data, re.M), "encrypted_pdf")
        match = re.search(r"^Pages:\s+(\d+)\s*$", data, re.M)
        need(match is not None, "invalid_output")
        pages = int(match.group(1))
        need(1 <= pages <= self.policy["pdf_parser_max_pages"], "page_limit")
        return pages, data

    def page(self, number, operation):
        source = str(self.work.path / "input.pdf")
        maximum = min(self.settings.pdf_max_page_bytes, self.policy["pdf_parser_max_output_mib"] * 1024**2)
        if operation == "text":
            target = self.work.target("text.txt")
            try:
                self.command("pdf_text_command", "-f", number, "-l", number, "-layout", "-enc", "UTF-8", "-nopgbrk", source, target)
                return self.work.read_file("text.txt", maximum).decode("utf-8", errors="strict").strip().encode("utf-8")
            finally:
                self.work.discard("text.txt")
        if operation == "split":
            name = f"split-{number}.pdf"
            self.work.target(name)
            try:
                self.command("pdf_separate_command", "-f", number, "-l", number, source, str(self.work.path / "split-%d.pdf"))
                body = self.work.read_file(name, maximum)
                need(body.startswith(b"%PDF-"), "invalid_output")
                need(self.inventory(str(self.work.path / name))[0] == 1, "invalid_output")
                return body
            finally:
                self.work.discard(name)
        _, information = self.inventory(source, "-f", number, "-l", number)
        match = re.search(r"(?:Page\s+\d+\s+size|Page size):\s*([\d.]+)\s+x\s+([\d.]+)\s+pts", information)
        need(match is not None, "invalid_output")
        pixels = math.ceil(float(match.group(1))*200/72)*math.ceil(float(match.group(2))*200/72)
        need(0 < pixels <= self.settings.pdf_max_pixels, "output_limit")
        target = self.work.target("raster.png")
        try:
            self.command("tesseract_pdf_command", "-f", number, "-l", number, "-singlefile", "-r", 200, "-png", source, str(self.work.path / "raster"))
            header = self.work.read_file("raster.png", self.policy["pdf_parser_scratch_mib"]*1024**2)
            need(header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24 and header[12:16] == b"IHDR", "invalid_output")
            width, height = int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
            need(width > 0 and height > 0 and width * height <= self.settings.pdf_max_pixels, "output_limit")
            return self.command("tesseract_command", target, "stdout", "-l", "+".join(self.languages), "--dpi", 200,
                                stdout_limit=maximum).decode("utf-8", errors="strict").strip().encode("utf-8")
        finally:
            self.work.discard("raster.png")

    def run(self, body, program, languages):
        need(self.setup_state == "ready" and not self.cleaned, "runtime_unavailable")
        need(program in PROGRAMS and body.startswith(b"%PDF-"), "invalid_request")
        self.languages = list(languages)
        need(all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_]{1,40}", v) for v in self.languages), "invalid_request")
        self.check_encoding()
        self.work.write_input(body)
        self.check_budget()
        pages, _ = self.inventory(str(self.work.path / "input.pdf"))
        operation = "text" if program.startswith("text_or_") else program
        versions = {}
        for pass_number in range(2):
            if operation == "local_ocr":
                need(bool(self.languages), "runtime_unavailable")
                raw_version = self.command("tesseract_command", "--version").decode("utf-8").splitlines()[0]
                need(re.fullmatch(r"tesseract [A-Za-z0-9.+:~_-]{1,100}", raw_version), "runtime_unavailable")
                versions["tesseract"] = raw_version.removeprefix("tesseract ")
                available = self.command("tesseract_command", "--list-langs").decode("utf-8").splitlines()
                need(set(self.languages) <= set(available), "runtime_unavailable")
            digest, has_text = hashlib.sha256(), False
            for number in range(1, pages+1):
                self.heartbeat()
                page = self.page(number, operation)
                has_text = has_text or bool(page.strip())
                need(self.work.usage() + self.store.bytes + len(page) <= self.policy["pdf_parser_scratch_mib"]*1024**2, "scratch_limit")
                self.store.stage(number, page, page_limit=self.settings.pdf_max_page_bytes,
                                 total_limit=self.policy["pdf_parser_max_output_mib"]*1024**2)
                digest.update(page)
                self.check_budget()
                # First pass may fall back: do not publish regressible completed page counts.
                self.progress(number if not program.startswith("text_or_") or pass_number else 0, pages)
            if program.startswith("text_or_") and operation == "text" and not has_text:
                self.store.close()
                self.store = PageStore(self.settings.pdf_scratch_dir, deferred=True)
                self.store.open()
                operation = program.removeprefix("text_or_")
                continue
            self.progress(pages, pages)
            return {"operation": operation, "pages": pages, "input_hash": hashlib.sha256(body).hexdigest(),
                    "sha256": digest.hexdigest(), "bytes": self.store.bytes, "tools": versions}
        raise AssertionError("unreachable")

    def clean_parser(self):
        need(self.setup_state in {"ready", "failed"}, "cleanup_unconfirmed")
        if self.setup_failed:
            need(self.setup_cleanup_confirmed, "cleanup_unconfirmed")
        need(self.tools is None or self.tools.stop_confirmed, "stop_unconfirmed")
        if self.work is not None:
            self.work.close()
        self.cleaned = True

    def stop_evidence(self, generation):
        need(self.cleaned and (self.tools is None or self.tools.stop_confirmed), "stop_unconfirmed")
        codes = [item["returncode"] for item in self.tools.exits] if self.tools else []
        return {"generation": str(generation), "source": "local_process", "stopped": True,
                "cleanup_confirmed": True, "workload_uid": self.launch_uid,
                "child_count": len(codes), "all_children_reaped": True,
                "exit_codes_sha256": hashlib.sha256(json.dumps(codes).encode()).hexdigest(),
                "all_exits_zero": all(code == 0 for code in codes)}
