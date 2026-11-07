"""Thin one-click wrapper around the actual protocol CLI; no IdP administration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from . import __version__
from .core import InstallerError, PreconditionError
from .protocol import ProtocolTarget
from .protocol_inputs import initialize_target, target_digest


def _parser():
    parser = argparse.ArgumentParser(prog="nomosmart-one-click", description="Current protocol installation using operator-managed services. General administrator sign-in/finalization remains a human checkpoint.")
    parser.add_argument("--version", action="version", version=__version__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--protocol-config", type=Path)
    inputs.add_argument("--config", type=Path, help="retired; use --protocol-config")
    parser.add_argument("--profile", choices=["external-services", "bundled"], default="external-services")
    parser.add_argument("--init-config", action="store_true", help="create new private target and values files; no service calls")
    parser.add_argument("--plan-only", action="store_true", help="run the real read-only installer plan")
    parser.add_argument("--test-candidate-scope", type=Path, help="explicit local unqualified test scope; never a release fallback")
    confirm = parser.add_mutually_exclusive_group()
    confirm.add_argument("--yes", action="store_true", help="approve the displayed current plan; never bypass identity checkpoints")
    confirm.add_argument("--confirm-digest", help="exact digest from --plan-only")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.config is not None or args.profile != "external-services":
            raise PreconditionError("Legacy --config/bundled wrapper input is archived. Use --protocol-config with external-services; bundled datastores remain available through direct Helm.")
        if (args.init_config or args.plan_only) and (args.yes or args.confirm_digest):
            raise PreconditionError("Initialization/plan-only cannot be combined with execution confirmation")
        if args.init_config and args.plan_only:
            raise PreconditionError("Initialization is a separate local-only step")
        if args.init_config and args.test_candidate_scope is not None:
            raise PreconditionError("Test scope cannot initialize a different target")
        if args.init_config:
            print(json.dumps(initialize_target(args.protocol_config), ensure_ascii=False, indent=2))
            return 0
        target = ProtocolTarget.load(args.protocol_config, allow_test_candidate=args.test_candidate_scope is not None)
        digest = target_digest(args.protocol_config, target)
        if args.confirm_digest and (not re.fullmatch(r"[0-9a-f]{64}", args.confirm_digest) or args.confirm_digest != digest):
            raise PreconditionError("Confirmation digest does not match this target/values/chart; run --plan-only again")
        installer = Path(__file__).resolve().parents[1] / "nomosmart-install"
        def call(operation, *, confirmed=False):
            command = [sys.executable, "-B", str(installer), operation, "--protocol-config", str(args.protocol_config)]
            if args.test_candidate_scope is not None:
                command += ["--test-candidate-scope", str(args.test_candidate_scope)]
            if confirmed:
                command += ["--confirm-digest", digest]
            result = subprocess.run(command, capture_output=True, text=True, timeout=1400 if confirmed else 240)
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            if result.returncode not in {0, 10}:
                raise PreconditionError("Protocol installer rejected " + operation + "; no automatic fallback was attempted")
            return result.returncode, json.loads(result.stdout)
        _, plan = call("plan")
        if plan.get("config_digest") != digest:
            raise PreconditionError("Protocol inputs changed before confirmation; obtain a new plan")
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        if args.plan_only:
            return 0
        if not args.yes and not args.confirm_digest:
            if not sys.stdin.isatty() or input("Apply exactly this protocol plan? [yes/no] ").strip() != "yes":
                raise PreconditionError("Execution needs --yes, the exact --confirm-digest, or interactive yes")
        if target_digest(args.protocol_config, ProtocolTarget.load(args.protocol_config, allow_test_candidate=args.test_candidate_scope is not None)) != digest:
            raise PreconditionError("Protocol inputs changed after confirmation")
        _, status = call("status")
        operation = "install" if status.get("status") == "not-installed" else "resume"
        code, result = call(operation, confirmed=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except InstallerError as exc:
        print(json.dumps({"status": "failed", "detail": str(exc), "exit_code": exc.exit_code}, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Interrupted; inspect the same explicit protocol target before resuming.", file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("Protocol wrapper failed without exposing protected output.", file=sys.stderr)
        return 30
