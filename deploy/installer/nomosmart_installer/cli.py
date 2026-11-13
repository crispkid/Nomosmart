"""Current protocol installer CLI. Historical installers are not imported."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import signal
import sys
from . import __version__
from .core import InstallerError, PreconditionError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nomosmart-install", description="Protocol-based NomoSmart Kubernetes installer")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "install", "resume", "status", "verify", "finalize", "doctor"):
        command = commands.add_parser(name)
        options = command.add_mutually_exclusive_group(required=True)
        options.add_argument("--protocol-config", type=Path, help="protocol contract 2 target TOML")
        options.add_argument("--config", type=Path, help="retired input; use --protocol-config")
        command.add_argument("--test-candidate-scope", type=Path, help="explicit private, human-approved local schema5 test scope")
        if name in {"install", "resume"}:
            command.add_argument("--confirm-digest", help="exact digest of the reviewed protocol target")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    protocol = None
    old_handlers = {}
    try:
        if args.config is not None:
            raise PreconditionError("Legacy installer configuration is archived. Use --protocol-config with the current target and values examples; bundled datastores use direct Helm.")
        from .protocol import ProtocolInstaller
        protocol = ProtocolInstaller(args.protocol_config, test_candidate_scope=args.test_candidate_scope)
        def terminate(signum, _frame):
            protocol.runner.forward_signal(signum)
            raise KeyboardInterrupt
        old_handlers = {sig: signal.signal(sig, terminate) for sig in (signal.SIGINT, signal.SIGTERM)}
        result = (getattr(protocol, args.command)(expected_digest=args.confirm_digest)
                  if args.command in {"install", "resume"} else getattr(protocol, args.command)())
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 10 if result.get("status") == "action-required" else 0
    except InstallerError as exc:
        print(json.dumps({"status": "action-required" if exc.exit_code == 10 else "failed", "detail": str(exc), "exit_code": exc.exit_code}, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "next_command": "status --protocol-config"}), file=sys.stderr)
        return 130
    except Exception:
        print(json.dumps({"status": "failed", "detail": "Installer failed without exposing protected command output", "exit_code": 30}), file=sys.stderr)
        return 30
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
