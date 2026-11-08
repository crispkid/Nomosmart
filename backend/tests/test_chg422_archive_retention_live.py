"""SYSUX-022: real failed-archive recovery; no seeds, mocks or direct task dispatch."""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import httpx
from sqlalchemy import create_engine, text
from app.core.config import get_settings
from app.integrations.s3_storage import S3ObjectStorage

def protected(settings, engine, project_id, version_id):
 with engine.connect() as c:
  c.exec_driver_sql('SET TRANSACTION READ ONLY');v=c.execute(text('select storage_bucket,storage_key,content_sha256 from document_versions where id=:v and project_id=:p'),{'v':version_id,'p':project_id}).mappings().one();source=S3ObjectStorage(settings).get_object(bucket=v['storage_bucket'],key=v['storage_key'],max_bytes=1024*1024).body;assert hashlib.sha256(source).hexdigest()==v['content_sha256'];proof={'source_sha256':hashlib.sha256(source).hexdigest()}
  for table,where,args in [('document_versions','id=:v',{'v':version_id}),('document_content_states','document_version_id=:v',{'v':version_id}),('chunks','document_version_id=:v',{'v':version_id}),('active_version_manifests','document_version_id=:v',{'v':version_id}),('ocr_document_receipts','document_version_id=:v',{'v':version_id})]:proof[table]=c.scalar(text('select md5(coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),\'[]\'::jsonb)::text) from '+table+' t where '+where),args)
  usage=[dict(x) for x in c.execute(text('select id,model_id,usage_purpose,status,attempted,input_tokens,output_tokens,total_tokens,estimated_cost from ai_model_usage_events where project_id=:p order by id'),{'p':project_id}).mappings()];proof['paid_usage_count']=len(usage);proof['paid_usage_sha256']=hashlib.sha256(json.dumps(usage,sort_keys=True,default=str).encode()).hexdigest();profile=c.scalar(text('select embedding_profile_id from active_version_manifests where document_version_id=:v'),{'v':version_id});assert profile;index=settings.opensearch_index_prefix+'-published-profile-'+str(profile)[:8]
 with httpx.Client(verify=settings.opensearch_httpx_verify,trust_env=False,timeout=20,auth=(settings.opensearch_username.get_secret_value(),settings.opensearch_password.get_secret_value())) as c:
  x=c.post(settings.opensearch_url+'/'+index+'/_count',json={'query':{'bool':{'filter':[{'term':{'project_id':project_id}},{'term':{'document_version_id':version_id}}]}}});assert x.status_code==200 and x.json()['_shards']['failed']==0;proof['published_scope_count']=x.json()['count'];assert proof['published_scope_count']>0
 return proof

class ArchiveRetentionRecoveryLive(unittest.TestCase):
    def test_normal_retry_preserves_published_and_paid_records(self):
        path = os.environ.get('NMS422_ARCHIVE_LIVE_CONTEXT')
        if not path:
            raise RuntimeError('Owned real failed-archive input is required')
        config = json.loads(Path(path).read_text())
        owner = json.loads(Path(config['owner_file']).read_text())
        self.assertEqual(owner['change_id'], 'CHG-422')
        self.assertEqual(owner['run_uuid'], config['run_uuid'])
        self.assertFalse(owner['execution_closed'])
        self.assertLess(datetime.now(UTC), datetime.fromisoformat(owner['deadline']))
        source = Path(__file__).resolve().parents[1] / 'app/domain/project_archival.py'
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(digest, config['product_source_sha256'])
        for path in config['runtime_provenance']:
            runtime = json.loads(Path(path).read_text())
            self.assertEqual(runtime['run_uuid'], config['run_uuid'])
            self.assertEqual(runtime['source_files']['backend/app/domain/project_archival.py'], digest)
        original = json.loads(Path(config['original_failure']).read_text())
        self.assertEqual(original['status'], 'FAILED')
        self.assertEqual(original['actual_cleanup']['id'], config['archive_run_id'])
        self.assertEqual(original['project_id'], config['project_id'])
        settings = get_settings()
        engine = create_engine(config['database_url'], hide_parameters=True)
        output = Path(config['result_file'])
        self.assertFalse(output.exists(), 'Original observation must not be overwritten')
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql('SET TRANSACTION READ ONLY')
                self.assertEqual(conn.scalar(text('select current_database()')), config['database_name'])
                initial_run = dict(conn.execute(text('select status,attempt from project_archive_runs where id=:id'), {'id': config['archive_run_id']}).mappings().one())
                self.assertIn(initial_run['status'], ('failed', 'completed'))
                if initial_run['status'] == 'failed':
                    job = conn.execute(text('select status,attempt from staging_retention_jobs where id=:id'), {'id': original['actual_future_job']['id']}).mappings().one()
                    self.assertEqual(dict(job), {'status': 'cancelled', 'attempt': 0})
            before = protected(settings, engine, config['project_id'], config['published_version_id'])
            expected = {**original['before'], 'document_content_states': config['published_content_state_before']}
            self.assertEqual(before, expected)
            with httpx.Client(base_url=config['origin']+'/api/backend/', verify=config['ca_file'], trust_env=False, timeout=60, headers={'Origin': config['origin']}) as client:
                response = client.post('auth/login', json={'username': config['username'], 'password': config['password']})
                self.assertEqual(response.status_code, 200)
                state = client.get('auth/session')
                self.assertEqual(state.status_code, 200)
                self.assertTrue(state.json()['authenticated'])
                client.headers['X-CSRF-Token'] = state.json()['csrf_token']
                try:
                    if initial_run['status'] == 'failed':
                        response = client.post('projects/'+config['project_id']+'/archive-cleanup/retry')
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()['status'], 'archived')
                finally:
                    self.assertEqual(client.post('auth/logout').status_code, 204)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                with engine.connect() as conn:
                    conn.exec_driver_sql('SET TRANSACTION READ ONLY')
                    run = dict(conn.execute(text('select id,status,attempt,error_code,completed_at,deleted_version_count,deleted_document_count from project_archive_runs where id=:id'), {'id': config['archive_run_id']}).mappings().one())
                if run['status'] == 'completed':
                    break
                self.assertNotEqual(run['status'], 'failed', 'Genuine retry failed')
                time.sleep(2)
            else:
                self.fail('Normal Beat/Outbox/Worker retry did not complete')
            with engine.connect() as conn:
                conn.exec_driver_sql('SET TRANSACTION READ ONLY')
                audits = [dict(row) for row in conn.execute(text("select actor_user_id,request_id,result,summary,created_at from audit_logs where resource_id=:p and action='project.archive.cleanup.retried' order by created_at"), {'p': config['project_id']}).mappings()]
            matching = [row for row in audits if row['result']=='success' and row['request_id'] and row['summary'].get('archive_run_id')==config['archive_run_id'] and row['summary'].get('next_attempt')==run['attempt']]
            self.assertEqual(len(matching), 1, 'Actual normal retry audit must bind the observed attempt')
            self.assertLessEqual(matching[0]['created_at'], run['completed_at'])
            self.assertEqual(str(matching[0]['actor_user_id']), config['owner_user_id'])
            if initial_run['status']=='failed':
                self.assertEqual(run['attempt'], initial_run['attempt']+1)
            self.assertGreater(run['deleted_version_count'], 0)
            self.assertEqual(protected(settings, engine, config['project_id'], config['published_version_id']), before)
            with engine.connect() as conn:
                conn.exec_driver_sql('SET TRANSACTION READ ONLY')
                self.assertEqual(conn.scalar(text('select count(*) from staging_retention_jobs where id=:id'), {'id': original['actual_future_job']['id']}), 0)
                self.assertEqual(conn.scalar(text('select count(*) from document_content_states where project_id=:p and document_version_id<>:v'), {'p': config['project_id'], 'v': config['published_version_id']}), 0)
                cancelled = conn.scalar(text("select count(*) from audit_logs where resource_id=:p and action='staging.retention.cancelled' and result='success'"), {'p': config['project_id']})
                self.assertGreaterEqual(cancelled, 1)
            output.write_text(json.dumps({'status':'PASS_REAL_NORMAL_ARCHIVE_RETRY_OBSERVATION','retry_requested_during_this_check':initial_run['status']=='failed','actual_retry_audit':matching[0],'run_uuid':config['run_uuid'],'actual_cleanup':run,'protected_before_and_after':before,'unpublished_content_states_removed':True,'future_retention_cancelled_without_execution':True,'manual_task_dispatches':0,'clock_or_expiry_changes':0,'model_calls_added':0},default=str,indent=2))
        finally:
            engine.dispose()
