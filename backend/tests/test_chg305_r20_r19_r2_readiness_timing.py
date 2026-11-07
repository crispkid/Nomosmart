"""Actual clock/files/logging and opted-in real-service HTTP, never fake health.

Local tests exercise diagnostics, not dependency availability. The live test
uses an approved current service context or explicitly configured legacy services. No writes,
bootstrap ensure, token acquisition, Provider calls or infrastructure creation.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import io
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.logging import JsonFormatter
from app.core.readiness_diagnostics import CHECK_NAMES, ReadinessDiagnostics, run_check


@contextmanager
def captured_logs(name="nomosmart.readiness"):
    # A real handler/formatter and output stream, not a patched logger.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    target = logging.getLogger(name)
    old_level, old_propagate = target.level, target.propagate
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    target.propagate = False
    try:
        yield stream
    finally:
        target.removeHandler(handler)
        target.setLevel(old_level)
        target.propagate = old_propagate
        handler.close()


def entries(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_thirteen_real_file_reads_produce_one_bounded_summary(tmp_path):
    source = tmp_path / "local-diagnostic-input.txt"
    source.write_text("private-document-canary", encoding="utf8")
    recorder = ReadinessDiagnostics()
    request_id = str(uuid4())
    before = time.perf_counter()
    with captured_logs() as stream:
        for name in CHECK_NAMES:
            with recorder.check(name) as check:
                assert source.read_text(encoding="utf8") == "private-document-canary"
                check.result = "healthy"
        recorder.emit(request_id, "healthy")
        recorder.emit(request_id, "healthy")
    rows = entries(stream)
    assert len(rows) == 1
    record = rows[0]
    assert record["message"] == "readiness_diagnostics"
    assert record["request_id"] == request_id
    assert record["result"] == "healthy"
    assert [x["name"] for x in record["readiness_checks"]] == list(CHECK_NAMES)
    assert all(set(x) == {"name", "latency_ms", "result"} for x in record["readiness_checks"])
    assert all(0 <= x["latency_ms"] <= record["latency_ms"] for x in record["readiness_checks"])
    assert 0 < record["latency_ms"] <= (time.perf_counter() - before) * 1000 + 10
    assert "private-document-canary" not in stream.getvalue()


def test_actual_file_error_propagates_without_raw_details(tmp_path):
    recorder = ReadinessDiagnostics()
    missing = tmp_path / "sensitive-error-canary"
    with captured_logs() as stream:
        with pytest.raises(FileNotFoundError) as caught:
            try:
                with recorder.check("s3"):
                    missing.read_bytes()
            finally:
                recorder.emit(str(uuid4()), "error")
    assert caught.value.filename == str(missing)
    row = entries(stream)[0]
    assert row["result"] == "error"
    assert len(row["readiness_checks"]) == 1
    assert row["readiness_checks"][0]["result"] == "error"
    assert "sensitive-error-canary" not in stream.getvalue()
    assert "FileNotFoundError" not in stream.getvalue()


@pytest.mark.parametrize("invalid", [None, "raw-secret-canary", {}, [None],
    [{"name": "s3", "latency_ms": float("nan"), "result": "healthy"}],
    [{"name": "s3", "latency_ms": float("inf"), "result": "healthy"}],
    [{"name": "s3", "latency_ms": -1, "result": "healthy"}],
    [{"name": "s3", "latency_ms": True, "result": "healthy"}],
    [{"name": "raw-secret-canary", "latency_ms": 1, "result": "healthy"}],
    [{"name": "s3", "latency_ms": 1, "result": "raw-secret-canary"}]])
def test_formatter_rejects_invalid_diagnostic_data(invalid):
    record = logging.LogRecord("nomosmart.readiness", logging.INFO, __file__, 0, "readiness_diagnostics", (), None)
    record.readiness_checks = invalid
    encoded = JsonFormatter().format(record)
    assert json.loads(encoded).get("readiness_checks", []) == []
    assert "raw-secret-canary" not in encoded


def test_formatter_projects_only_safe_fields_and_caps_entries():
    record = logging.LogRecord("nomosmart.readiness", logging.INFO, __file__, 0, "readiness_diagnostics", (), None)
    record.readiness_checks = [
        {"name": name, "latency_ms": 1, "result": "healthy", "url": "https://secret-canary.invalid", "password": "secret-canary"}
        for name in CHECK_NAMES
    ] * 2
    encoded = JsonFormatter().format(record)
    checks = json.loads(encoded)["readiness_checks"]
    assert len(checks) == len(CHECK_NAMES)
    assert [item["name"] for item in checks] == list(CHECK_NAMES)
    assert all(set(item) == {"name", "latency_ms", "result"} for item in checks)
    assert "secret-canary" not in encoded


def test_unknown_and_repeated_names_do_not_expand_log(tmp_path):
    recorder = ReadinessDiagnostics()
    with captured_logs() as stream:
        for name in ["credential-canary", *("s3" for _ in range(30))]:
            with recorder.check(name) as timing:
                assert tmp_path.is_dir()
                timing.result = "healthy"
        recorder.emit(str(uuid4()), "healthy")
    assert len(entries(stream)[0]["readiness_checks"]) == 1
    assert "credential-canary" not in stream.getvalue()


def test_two_recorders_are_isolated_with_real_concurrent_reads(tmp_path):
    ids = [str(uuid4()), str(uuid4())]
    def read_one(index):
        recorder = ReadinessDiagnostics()
        with recorder.check(CHECK_NAMES[index]) as timing:
            assert tmp_path.stat().st_size >= 0
            timing.result = "healthy"
        recorder.emit(ids[index], "healthy")
    with captured_logs() as stream:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(read_one, range(2)))
    rows = {row["request_id"]: row for row in entries(stream)}
    assert set(rows) == set(ids)
    for index in range(2):
        assert [x["name"] for x in rows[ids[index]]["readiness_checks"]] == [CHECK_NAMES[index]]


def test_real_postgresql_refusal_preserves_status_with_and_without_recorder():
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.integrations.health import _postgresql_status
    from app.deployment.bootstrap import _database_check, _runtime_bootstrap_check

    # Obtain then release a local port and verify actual ECONNREFUSED. A bound
    # non-listening socket can time out on macOS rather than immediately refuse.
    # No fake PostgreSQL server and no fault injection against a shared service.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        reserved.close()
        _assert_refused(port)
        settings = Settings(_env_file=None, app_env="development").model_copy(update={
            "database_url": SecretStr(f"postgresql+psycopg2://readonly@127.0.0.1:{port}/probe?connect_timeout=1"),
            # Valid test-only contract shape reaches libpq; never verified/applied.
            "migration_required_version": "1", "migration_required_checksum": 0,
            "migration_check_timeout_seconds": 1,
        })
        recorder = ReadinessDiagnostics()
        with captured_logs() as stream:
            original = run_check(None, "postgresql", lambda: _postgresql_status(settings))
            assert stream.getvalue() == ""
            observed = run_check(recorder, "postgresql", lambda: _postgresql_status(settings))
            bootstrap = run_check(recorder, "deployment.database", lambda: _runtime_bootstrap_check(
                "deployment.database", lambda: _database_check(settings)))
            recorder.emit(str(uuid4()), "unhealthy")
        _assert_refused(port)
    assert original == observed
    assert observed.healthy is False and bootstrap.healthy is False
    assert bootstrap.detail == "database_unavailable"
    row = entries(stream)[0]
    assert [x["result"] for x in row["readiness_checks"]] == ["unhealthy", "unhealthy"]
    assert "readonly" not in stream.getvalue() and "127.0.0.1" not in stream.getvalue()


@pytest.mark.parametrize("phase", ["onboarding", "factory_acceptance", "operational"])
def test_real_http_503_and_concurrent_correlation_with_refused_test_endpoints(phase):
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.main import create_app

    # A real network-negative test, not a simulated dependency or healthy path.
    # All overrides live only in this new local candidate HTTP app's settings.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        settings = Settings(_env_file=None, app_env="development", deployment_phase=phase).model_copy(update={
            "database_url": SecretStr(f"postgresql+psycopg2://readonly@127.0.0.1:{port}/probe?connect_timeout=1"),
            "migration_required_version": "1", "migration_required_checksum": 0,
            "migration_check_timeout_seconds": 1,
            "redis_url": SecretStr(f"redis://127.0.0.1:{port}/0"),
            "celery_broker_url": SecretStr(f"redis://127.0.0.1:{port}/1"),
            "celery_result_backend": SecretStr(f"redis://127.0.0.1:{port}/2"),
            "redis_ha_mode": "standalone",
            "s3_endpoint_url": f"http://127.0.0.1:{port}",
            "opensearch_url": f"https://127.0.0.1:{port}",
            "neo4j_uri": f"bolt://127.0.0.1:{port}",
            "neo4j_ca_cert_path": "",
            "oidc_issuer_url": f"http://127.0.0.1:{port}/realms/diagnostic",
            "oidc_discovery_url": "",
        })
        _exercise_candidate_http(create_app(settings), expected_http=503, refused_socket=reserved)


@pytest.mark.skipif(os.environ.get("READY_TIMING_LIVE") != "1" and not os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT') and not os.environ.get('NOMOSMART_CURRENT_KUBERNETES_CONTEXT'),
                    reason="BLOCKED unless configured live HTTP prerequisites are explicitly enabled")
def test_live_candidate_http_response_correlation_and_concurrency():
    if os.environ.get('NOMOSMART_CURRENT_KUBERNETES_CONTEXT'):
        from current_kubernetes_live_support import exercise_readiness
        exercise_readiness()
        return
    from app.core.config import Settings
    from app.main import create_app

    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_live_support import load_current_context
        settings = Settings(_env_file=None)
        context = load_current_context(settings)
        _exercise_current_candidate_http(settings, context)
        return
    else:
        settings = Settings(_env_file=Path(__file__).resolve().parents[1] / ".env")
    # Healthy configured-service acceptance must not pass on thirteen failures.
    # Actual503 behavior is tested separately with closed local endpoints.
    _exercise_candidate_http(create_app(settings), expected_http=200)


def _assert_refused(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", port)) == errno.ECONNREFUSED, "test port is not confirmed closed"


def _exercise_candidate_http(app, expected_http=None, refused_socket=None):
    import httpx
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, access_log=False))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "candidate HTTP startup unavailable"
        refused_port = None
        if refused_socket is not None:
            refused_port = refused_socket.getsockname()[1]
            refused_socket.close()
            _assert_refused(refused_port)
        ids = [str(uuid4()) for _ in range(2)]
        def request_one(request_id):
            return httpx.get(f"http://127.0.0.1:{port}/api/v1/ready", headers={"X-Request-Id": request_id}, timeout=30)
        with captured_logs() as diagnostics, captured_logs("nomosmart.request") as requests:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(request_one, ids))
        if refused_port is not None:
            _assert_refused(refused_port)
        records = entries(diagnostics)
        assert len(records) == 2
        by_id = {row["request_id"]: row for row in records}
        request_rows = {row["request_id"]: row for row in entries(requests) if row["message"] == "request_completed"}
        assert set(by_id) == set(ids) == set(request_rows)
        for request_id, response in zip(ids, responses):
            assert response.headers["X-Request-Id"] == request_id
            assert response.status_code in (200, 503)
            if expected_http is not None:
                assert response.status_code == expected_http
            body = response.json()
            assert set(body) == {"status", "dependencies"}
            expected_names = [name for name in CHECK_NAMES
                              if name != "deployment.onboarding" or app.state.settings.deployment_phase == "operational"]
            assert list(body["dependencies"]) == expected_names
            row = by_id[request_id]
            assert [item["name"] for item in row["readiness_checks"]] == expected_names
            for item in row["readiness_checks"]:
                status = body["dependencies"][item["name"]]
                assert set(status) == {"healthy", "detail"}
                assert item["result"] == ("healthy" if status["healthy"] else "unhealthy")
            assert row["result"] == ("healthy" if response.status_code == 200 else "unhealthy")
            assert request_rows[request_id]["latency_ms"] + 0.02 >= row["latency_ms"]
    finally:
        server.should_exit = True
        thread.join(timeout=35)
        sock.close()
        assert not thread.is_alive(), "candidate HTTP did not stop"


def _exercise_current_candidate_http(settings, context):
    """Same actual owned HTTPS API and original on-disk JSON request logs."""
    from current_queue_graph_support import _private_runtime_record, _bound_chg388_application_source
    import httpx
    root=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    owner=_private_runtime_record(root/'owner.json')
    execution_phase,_=_bound_chg388_application_source(root,owner,owner['processes']['api'])
    observed=_private_runtime_record(execution_phase/'api-owner.json')
    api=owner['processes']['api'];process=Path('/proc',str(api['pid']))
    assert observed['closed'] is False and process.stat().st_uid==os.getuid()
    assert int((process/'stat').read_text().split()[21])==api['start_ticks']
    assert __import__('hashlib').sha256((process/'cmdline').read_bytes()).hexdigest()==api['argv_sha256']
    path=execution_phase/'api-private.log'
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        assert __import__('stat').S_ISREG(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode & 0o077
        offset=info.st_size;ids=[str(uuid4()) for _ in range(2)]
        def request_one(request_id):
            with httpx.Client(verify=context['ca_file'],trust_env=False,timeout=30) as client:
                return client.get(context['backend_url']+'/api/v1/ready',headers={'X-Request-Id':request_id})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(request_one,ids))
        os.lseek(fd,offset,os.SEEK_SET);body=os.read(fd,1024**2+1);assert len(body)<=1024**2
        assert os.fstat(fd).st_ino==info.st_ino
    finally:os.close(fd)
    rows=[]
    for line in body.decode('utf8').splitlines():
        try:value=json.loads(line)
        except json.JSONDecodeError:continue
        if isinstance(value,dict) and value.get('request_id') in ids:rows.append(value)
    records=[row for row in rows if row.get('message')=='readiness_diagnostics']
    assert len(records)==2
    by_id={row['request_id']:row for row in records}
    request_rows={row['request_id']:row for row in rows if row.get('message')=='request_completed'}
    assert set(by_id)==set(ids)==set(request_rows)
    for request_id,response in zip(ids,responses):
        assert response.headers['X-Request-Id']==request_id
        assert response.status_code in (200,503)
        assert response.status_code==200
        payload=response.json();assert set(payload)=={'status','dependencies'}
        expected_names=[name for name in CHECK_NAMES if name!='deployment.onboarding' or settings.deployment_phase=='operational']
        assert list(payload['dependencies'])==expected_names
        row=by_id[request_id];assert [item['name'] for item in row['readiness_checks']]==expected_names
        for item in row['readiness_checks']:
            status=payload['dependencies'][item['name']]
            assert set(status)=={'healthy','detail'}
            assert item['result']==('healthy' if status['healthy'] else 'unhealthy')
        assert row['result']==('healthy' if response.status_code==200 else 'unhealthy')
        assert request_rows[request_id]['latency_ms']+0.02>=row['latency_ms']
    receipt={'operation_uuid':owner['operation_uuid'],'request_ids':ids,
        'actual_HTTP':[r.status_code for r in responses],'actual_log_records':rows,
        'responses':[r.json() for r in responses],'second_API_started':False,'model_calls':0}
    target=root/'actual-readiness-correlation.json';target.write_text(json.dumps(receipt,indent=2));target.chmod(0o600)
