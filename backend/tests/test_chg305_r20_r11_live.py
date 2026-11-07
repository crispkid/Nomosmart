"""R20 R11: retained real Neo4j/PDF and retired-source claim-release checks.

Inputs may be synthetic; no adapter/driver/process result is simulated. The
separate approved runner creates services and sets R11_TEST_CONFIG; this module
never provisions services or obtains credentials from the current deployment.
"""
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path
import signal
import ssl
import socket
import time
import subprocess
import sys
from threading import Thread, Event
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pydantic import ValidationError
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.core.config import Settings, create_neo4j_driver, neo4j_driver_options
from app.core.errors import AppError


def config():
    path = os.environ.get("R11_TEST_CONFIG")
    if not path:
        pytest.fail("R11_TEST_CONFIG is required: real isolated services are not provisioned")
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_live_support import load_current_context
        from scripts.current_e2e_governance_fixture import read_private
        context = load_current_context()
        authority = read_private(Path(os.environ["NOMOSMART_TEST_SCOPE"]))
        root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
        assert Path(path) == root / "r11-current-config.json"
        value = read_private(path)
        assert value["operation_uuid"] == authority["operation_uuid"]
        assert value["run_id"] == context["run_id"]
        assert value["source_inventory_sha256"] == authority["public_inventory"]["sha256"]
        assert value["config"]["settings"]["neo4j_uri"] == authority["store_endpoints"]["neo4j"]
        ca = Path(value["config"]["ca"])
        assert ca.parent == root and not ca.is_symlink() and ca.resolve() == ca
        assert hashlib.sha256(ca.read_bytes()).hexdigest() == value["ca_sha256"]
        assert Path(value["config"]["samples"]) == root / "pdf-samples"
        return value["config"]
    return json.loads(Path(path).read_text())


def settings(**overrides):
    return Settings(_env_file=None, **(config()["settings"] | overrides))


@pytest.mark.parametrize("scheme", ["bolt", "neo4j"])
@pytest.mark.parametrize("trust", ["plaintext", "custom", "system"])
def test_real_neo4j_modes_and_common_consumers(scheme, trust):
    secure = trust != "plaintext"
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from urllib.parse import urlsplit
        authority = urlsplit(config()["settings"]["neo4j_uri"]).netloc
    else:
        authority = "neo4j:7687"
    s = settings(neo4j_uri=f"{scheme}{'+s' if secure else ''}://{authority}",
                 neo4j_ca_cert_path=config()["ca"] if trust == "custom" else "")
    original = s.neo4j_uri
    with create_neo4j_driver(s, connection_timeout=3, max_transaction_retry_time=0) as driver:
        assert driver.encrypted is secure
        driver.verify_connectivity()
        with driver.session(database=s.neo4j_database) as session:
            assert session.run("RETURN 1 AS ready").single()["ready"] == 1
    assert s.neo4j_uri == original
    from app.integrations.health import _neo4j_status
    from app.deployment.bootstrap import _neo4j_check
    from app.domain.graph_reconciliation import Neo4jProjectionStore
    from app.domain.review_publish import LiveNeo4jGraphSyncAdapter
    assert _neo4j_status(s).healthy
    assert _neo4j_check(s).name == "neo4j"
    with Neo4jProjectionStore(s).connection() as session:
        assert session.run("RETURN 1 AS ready").single()["ready"] == 1
    with LiveNeo4jGraphSyncAdapter(s)._driver() as driver:
        driver.verify_connectivity()


@pytest.mark.parametrize("failure", ["wrong_ca", "wrong_host", "expired", "password"])
def test_real_tls_and_auth_negatives_no_plaintext_fallback(failure):
    current = bool(os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"))
    base = config()
    values = {"neo4j_uri": base["settings"]["neo4j_uri"] if current else "bolt+s://neo4j:7687", "neo4j_ca_cert_path": base["ca"]}
    if failure == "wrong_ca": values["neo4j_ca_cert_path"] = base["wrong_ca"]
    if failure == "wrong_host": values["neo4j_uri"] = base["negative_endpoints"]["wrong_host"] if current else "bolt+s://wrong-neo4j:7687"
    if failure == "expired":
        values["neo4j_uri"] = base["negative_endpoints"]["expired"] if current else "bolt+s://expired:7687"
        if current: values["neo4j_ca_cert_path"] = base["expired_ca"]
    if failure == "password": values["neo4j_password"] = "incorrect-disposable-test-password"
    s = settings(**values)
    with create_neo4j_driver(s, connection_timeout=2, connection_acquisition_timeout=3,
                            max_transaction_retry_time=0) as driver:
        with pytest.raises(AuthError if failure == "password" else ServiceUnavailable):
            driver.verify_connectivity()
    # The same service accepts plaintext: an illicit TLS->plain fallback would
    # have made the failed certificate cases succeed. Good TLS must remain usable.
    with create_neo4j_driver(settings(), connection_timeout=3) as driver:
        driver.verify_connectivity()


def test_true_tls_socket_verifies_san_chain_and_validity():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from urllib.parse import urlsplit
        endpoint = urlsplit(settings().neo4j_uri)
        host, port = endpoint.hostname, endpoint.port or 7687
    else:
        host, port = "neo4j", 7687
    with socket.create_connection((host, port), timeout=3) as raw:
        with ssl.create_default_context(cafile=config()["ca"]).wrap_socket(raw, server_hostname=host) as tls:
            assert tls.version() in {"TLSv1.2", "TLSv1.3"}
            assert any(kind in {"DNS", "IP Address"} and value == host for kind, value in tls.getpeercert()["subjectAltName"])


def test_real_bootstrap_explicit_admin_and_service_credentials():
    from app.deployment.bootstrap import DeploymentBootstrapSettings, _ensure_neo4j_service_identity
    values=config()['settings'] | dict(neo4j_username='r11_'+uuid4().hex,
        neo4j_password=uuid4().hex,neo4j_admin_username='neo4j',
        neo4j_admin_password=config()['settings']['neo4j_password'],neo4j_community_admin_equivalent_accepted=True)
    s=DeploymentBootstrapSettings(_env_file=None,**values)
    _ensure_neo4j_service_identity(s)
    _ensure_neo4j_service_identity(s)  # Existing credential verification uses the same TLS factory.
    with create_neo4j_driver(s,connection_timeout=3) as driver: driver.verify_connectivity()


@pytest.mark.parametrize("uri,ca", [
    ("bolt://neo4j:7687", "configured"), ("neo4j+ssc://neo4j:7687", ""),
    ("https://neo4j:7687", ""), ("bolt+s://user:secret@neo4j:7687", ""),
    ("bolt+s://neo4j:bad", ""), ("bolt+s://neo4j:7687/extra", ""),
])
def test_conflicting_or_unsafe_configuration_rejected(uri, ca):
    with pytest.raises(ValidationError):
        settings(neo4j_uri=uri, neo4j_ca_cert_path=ca)


def test_missing_symlink_ca_and_transport_override_rejected(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        create_neo4j_driver(settings(neo4j_ca_cert_path=str(tmp_path/'missing')))
    link = tmp_path/'ca'; link.symlink_to(config()["ca"])
    with pytest.raises(ValueError, match="regular file"):
        create_neo4j_driver(settings(neo4j_ca_cert_path=str(link)))
    from neo4j import TrustAll
    for override in ({'encrypted':False},{'trusted_certificates':TrustAll()},
                     {'ssl_context':ssl._create_unverified_context()},
                     {'trust':'TRUST_ALL_CERTIFICATES'}):
        with pytest.raises(ValueError, match="overrides"):
            create_neo4j_driver(settings(), **override)






































def test_existing_local_pdf_text_and_split_are_unchanged(tmp_path):
    from app.domain.local_pdf.runner import LocalPDF
    from test_chg305_r20_local_pdf import policy
    s=settings(pdf_scratch_dir=str(tmp_path/'pdf'))
    body=(Path(config()['samples'])/'regression.pdf').read_bytes()
    def parse(content,operation):
        progress=[]
        runner=LocalPDF(s,policy(),heartbeat=lambda:None,progress=lambda done,total:progress.append((done,total)))
        runner.setup()
        try:
            result=runner.run(content,operation,['eng'])
            pages=[runner.store.read(n) for n in range(1,result['pages']+1)]
            runner.clean_parser()
            assert runner.stop_evidence('r11-regression')['all_children_reaped']
            assert progress[-1]==(len(pages),len(pages))
            return pages
        finally:
            runner.clean_parser();runner.store.close()
            assert list(Path(s.pdf_scratch_dir).iterdir())==[]
    text=parse(body,'text')
    assert text==[b'R11 PDF page one',b'R11 PDF page two']
    split=parse(body,'split')
    assert len(split)==2
    assert [parse(page,'text')[0] for page in split]==text


def test_real_failed_docx_pipeline_releases_document_claim_without_pdf_slot(tmp_path):
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_failed_docx_support import failed_docx_claim_release
        return failed_docx_claim_release(tmp_path)
    from datetime import UTC,datetime,timedelta
    from sqlalchemy import create_engine,select,func
    from sqlalchemy.orm import Session
    from app.db.models import (Project,Document,DocumentVersion,PipelineRun,PipelineRunStep,User,Role,RoleUser,
        RolePermission,FileProcessingExecution,FileProcessingTask)
    from app.security.auth import IdentityPrincipal
    from app.domain.file_processing_settings import initialize_policy,PlatformCapabilities
    from app.domain.file_processing_dispatch import prepare_dispatch,claim_task,quiesce_task,finalize_task
    from app.domain.extraction_pipeline import initialize_pipeline_steps,execute_auto_extraction
    from app.integrations.s3_storage import S3ObjectStorage
    s=settings();engine=create_engine(s.database_url.get_secret_value(),hide_parameters=True)
    subject='r11-'+uuid4().hex;now=datetime.now(UTC);caps=PlatformCapabilities({})
    # Direct authenticated-domain INPUT, not evidence of OIDC or browser login.
    principal=IdentityPrincipal(subject,None,None,'R11 isolated operator',(),None,None,expires_at=now+timedelta(hours=1))
    with Session(engine) as db:
        user=User(keycloak_user_id=subject,display_name=subject,is_active=True);role=Role(name=subject)
        db.add_all([user,role]);db.flush()
        db.add_all([RoleUser(user_id=user.id,role_id=role.id,source='manual'),
            RolePermission(role_id=role.id,module_name='Menu',function_name='SystemManagement',can_view=True,can_edit=True)])
        db.commit()
        initialize_policy(db,principal=principal,deployment_id=uuid4(),legacy_timeout_seconds=120,
            legacy_max_pages=200,legacy_upload_mib=100,capabilities=caps);db.commit()
        p=Project(name=subject,created_by=user.id);db.add(p);db.flush()
        d=Document(project_id=p.id,document_code=subject,title='Invalid DOCX',source_type='file_upload');db.add(d);db.flush()
        body=b'PK invalid';key=f'r11/{uuid4()}/failure.docx'
        S3ObjectStorage(s).put_object(bucket=s.s3_bucket,key=key,body=body,content_type='application/octet-stream')
        v=DocumentVersion(project_id=p.id,document_id=d.id,version_major=1,extraction_revision=0,version_label='v1',
            status='processing',content_sha256=hashlib.sha256(body).hexdigest(),canonical_extension='.docx',
            storage_bucket=s.s3_bucket,storage_key=key,chunk_strategy={})
        db.add(v);db.flush()
        pipeline=PipelineRun(project_id=p.id,document_id=d.id,document_version_id=v.id,project_generation=1,
            run_type='auto_extraction',status='queued',created_at=now)
        db.add(pipeline);db.flush();initialize_pipeline_steps(db,pipeline,ocr_model_id=None,ocr_name='',force_ocr=False);db.commit()
        dispatch=prepare_dispatch(db,run_id=pipeline.id,capabilities=caps);db.commit()
        claim=claim_task(db,task_id=dispatch.task_id,generation=dispatch.generation,
            broker_task_id=dispatch.broker_task_id,worker_identity='r11-isolated-domain');db.commit()
        execute_auto_extraction(session=db,settings=s,project=p,document=d,version=v,pipeline=pipeline,durable=True,execution_claim=claim)
        assert pipeline.status=='failed' and v.status=='failed'
        step=db.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id==pipeline.id,PipelineRunStep.step_name==pipeline.current_step_name))
        assert step.status=='failed' and not step.output_artifact_ref
        assert step.artifact_payload['error_code']=='unsupported_upload_type'
        quiesce_task(db,claim,disposition='failed');db.commit()
        assert finalize_task(db,claim.task_id);db.commit()
        assert db.get(FileProcessingTask,claim.task_id).state=='finalized'
        assert db.get(FileProcessingExecution,claim.execution_id).released_at is not None
        assert db.scalar(select(func.count()).select_from(FileProcessingExecution).where(FileProcessingExecution.kind=='parser'))==0
    engine.dispose()
