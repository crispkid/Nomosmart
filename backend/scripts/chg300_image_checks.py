"""Real image-internal CHG-300 checks on run-owned services; no external scans."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import tempfile

from chg291_v049_rehearsal import ROOT, Rehearsal, TAGS as SERVICE_TAGS
from chg300_image_preparation import guard as image_guard
from chg300_migration_checks import prepare_gate_databases, gate_tests


class ImageLab(Rehearsal):
    def __init__(self, path, image_root):
        super().__init__(path)
        self.image_root = image_root
        self.manifest = image_guard(image_root)
        self.candidates = {}
        for key, name in (("backend", "backend"), ("flyway", "migrations")):
            build = json.loads((image_root / "images" / (name + "-build.json")).read_text())
            assert build["exitCode"] == 0 and build["sourceSha256"] == self.manifest["sourceSha256"]
            info = super().inspect("image", build["tag"])
            assert info["Id"] == build["imageId"]
            self.candidates[key] = build["imageId"]

    def inspect(self, kind, ident):
        if kind == "image":
            for key in ("backend", "flyway"):
                if ident == SERVICE_TAGS[key]:
                    ident = self.candidates[key]
        return super().inspect(kind, ident)

    def docker(self, *args, **kwargs):
        if args[0] == "create" and any(ident in args for ident in getattr(self, "candidates", {}).values()):
            args = ("create", "--read-only", "--tmpfs=/tmp:rw,nosuid,nodev,size=128m",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges", *args[1:])
        return super().docker(*args, **kwargs)

    def create(self, key, image, **kwargs):
        if key == "flyway":
            # No host SQL overlay: test the immutable image's actual SQL.
            password_file = self.path.parent / "flyway-wrapper.secret"
            password_file.write_text(self.state["secrets"]["NOMOSMART_MIGRATION_PASSWORD"])
            password_file.chmod(0o444)  # Private 0700 parent; readable by UID10001 bind mount.
            self.state.setdefault("secret_files", []).append(str(password_file))
            self.save()
            kwargs["mounts"] = [(str(password_file), "/run/secrets/flyway-password", True)]
        return super().create(key, image, **kwargs)

    def guard(self, db=None):
        image_guard(self.image_root)
        super().guard(db)
        for ident in self.state["containers"]:
            info = super().inspect("container", ident)
            if info["Image"] in self.candidates.values():
                assert info["HostConfig"]["ReadonlyRootfs"]
                assert info["Config"]["User"] not in ("", "root", "0", "0:0")
                assert all(mount["Destination"] not in ("/app/app", "/current/app", "/flyway/sql") for mount in info["Mounts"])

    def metadata(self):
        cid = self.state["services"]["flyway"]
        sha_result = self.docker("exec", cid, "sh", "-c", "sha256sum /flyway/sql/*.sql")
        actual = {line.split()[1].replace("/flyway/", ""): line.split()[0] for line in sha_result.stdout.decode().splitlines()}
        expected = {name.replace("sql/migrations/", "sql/"): value for name, value in self.manifest["files"].items()
                    if name.startswith("sql/migrations/")}
        assert actual == expected, "Image SQL differs from approved immutable source"
        metadata = {"sql_files": len(actual), "sql_hashes_match": True}
        for label, command in (
            ("uid", ["id", "-u"]), ("flyway", ["/flyway/flyway", "-v"]),
            ("java", ["java", "-version"]), ("apk", ["apk", "info", "-v"]),
            ("files", ["find", "/flyway", "-maxdepth", "3", "-type", "f"]),
        ):
            result = self.docker("exec", cid, *command, check=False)
            metadata[label] = {"exitCode": result.returncode,
                "output": (result.stdout + result.stderr).decode(errors="replace")[:30000]}
        assert metadata["uid"]["output"].strip() == "10001" and metadata["flyway"]["exitCode"] == 0
        assert "13.6.0" in metadata["flyway"]["output"]
        self.state["image_metadata"] = metadata
        self.save()

    def wrapper_validate(self):
        # Explicitly wrong inherited password must be replaced from the actual
        # secret file by the image's wrapper before a real DB validate succeeds.
        result = self.docker("exec", "-e", "FLYWAY_PASSWORD=deliberately-invalid-test-password",
            "-e", "NOMOSMART_SECRET_EXPORTS=FLYWAY_PASSWORD:/run/secrets/flyway-password",
            self.state["services"]["flyway"], "/opt/nomosmart/secret-env-entrypoint.sh", "flyway",
            "-url=jdbc:postgresql://pg:5432/v49_m300_ready", "validate")
        self.state["wrapper_validate"] = {"exitCode": result.returncode, "secret_file_override": True,
            "output": (result.stdout + result.stderr).decode(errors="replace")[-5000:]}
        self.save()


def main(image_root):
    image_guard(image_root)
    directory = Path(tempfile.mkdtemp(prefix="chg300-image-lab-", dir="/private/tmp")); directory.chmod(0o700)
    path = directory / "private-state.json"
    state = {"run": "v49-" + secrets.token_hex(6), "containers": [], "volumes": [], "databases": [],
        "services": {}, "allowed_mounts": [], "operations": [], "dumps": [],
        "secrets": {"pg": secrets.token_hex(24), "kc": secrets.token_hex(24), "app": secrets.token_hex(32)},
        "image_root": str(image_root), "image_tools": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), ROOT / "backend/scripts/chg300_migration_checks.py", ROOT / "backend/tests/test_chg300_migration_gate.py"]}}
    path.write_text(json.dumps(state)); path.chmod(0o600)
    lab = ImageLab(path, image_root)
    print(json.dumps({"lab": str(directory)}), flush=True)
    code = 1
    try:
        lab.setup()
        lab.metadata()
        prepare_gate_databases(lab)
        lab.wrapper_validate()
        code = gate_tests(lab, image_manifest=image_root / "manifest.json")
        assert code == 0, "Image gate suite failed"
        before = lab.snapshot("v49_m300_ready")
        lab.migrate("v49_m300_ready")
        assert lab.snapshot("v49_m300_ready") == before, "Migration rerun changed data/history"
        for version in (48, 49):
            db = lab.database("image_api" + str(version)); lab.migrate(db, version)
            lab.api(db, "image", "image-" + str(version), keepalive=True)
        candidate = lab.state["images"]["backend"]
        lab.state["images"]["backend"] = super(ImageLab, lab).inspect("image", SERVICE_TAGS["backend"])["Id"]
        lab.save()
        lab.api("v49_image_api49", "deployed", "rollback-49", keepalive=True)
        lab.state["images"]["backend"] = candidate
        lab.state["image_acceptance_complete"] = True
        lab.save()
    finally:
        cleanup_ok = False
        try:
            if "baseline" in lab.state:
                lab.cleanup()
            cleanup_ok = True
        finally:
            safe = {k: v for k, v in lab.state.items() if k not in ("secrets", "allowed_mounts")}
            safe.update(gate_exit_code=code, cleanup_ok=cleanup_ok, provider_calls=0, deployment=False)
            (directory / "evidence.json").write_text(json.dumps(safe, indent=2))
            if cleanup_ok:
                path.unlink()
            print(json.dumps({"evidence": str(directory / "evidence.json"), "cleanup": cleanup_ok}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    main(parser.parse_args().root)
