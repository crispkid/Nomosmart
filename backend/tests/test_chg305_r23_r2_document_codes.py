"""Real PostgreSQL transactions; requires an explicitly run-owned test database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
import queue
import time
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Document, Project, User
from app.domain.document_codes import allocate_document_code
from app.domain.document_imports import _next_document_code as upload_code
from app.api.routes.references import _next_document_code as reference_code
from app.api.routes.data_sources import allocate_document_code as data_source_code


class DocumentCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('NOMOSMART_SOURCE_COUNTER_CONTEXT') == '/Users/peter/Documents/GitHub/Nomosmart/.artifacts/chg414-919553ec/amendments/chg418/native-stage5/input-profile.json':
            from chg418_document_code_scope import database,Inputs
            lease=database();cls.engine=lease.__enter__();cls.addClassCleanup(lease.__exit__,None,None,None)
            cls.inputs=Inputs(cls.engine);cls.inputs.install();cls.addClassCleanup(cls.inputs.close)
            return
        if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
            from current_native_support import native_database
            lease = native_database()
            cls.engine = lease.__enter__()
            cls.addClassCleanup(lease.__exit__, None, None, None)
            return
        # A missing isolated service is an error, not an invented success/SQLite.
        assert os.environ.get('NOMOSMART_R23R2_TEST_DATABASE') == 'run-owned'
        cls.engine = create_engine(os.environ['DATABASE_URL'], hide_parameters=True)
        with cls.engine.connect() as connection:
            assert connection.scalar(text('SELECT version()')).startswith('PostgreSQL')
            assert connection.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname='documents_project_id_document_code_key'")) == 1

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def project(self):
        with Session(self.engine) as session:
            item = Project(name='R23R2-'+str(uuid4()))
            session.add(item)
            session.flush()
            identity = item.id
            session.commit()
        return identity

    def add(self, session, project, code, deleted=False):
        row = Document(project_id=project, document_code=code, title='owned test',
                       source_type='file_upload', is_deleted=deleted)
        session.add(row)
        return row

    def wait_lock(self, pid):
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            with self.engine.connect() as c:
                if c.scalar(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),{'pid':pid}) == 'Lock':
                    return
            time.sleep(.02)
        self.fail('second real PostgreSQL transaction never waited on lock')

    def test_empty_and_pending_with_runtime_autoflush_disabled(self):
        project = self.project()
        with Session(self.engine, autoflush=False) as s:
            self.assertEqual(upload_code(s,project),'DOC-000001')
            self.add(s,project,'DOC-000001')
            with s.no_autoflush:
                self.assertEqual(reference_code(s,project),'DOC-000002')
            self.add(s,project,'DOC-000002')
            self.assertEqual(data_source_code(s,project),'DOC-000003')
            s.commit()

    def test_numeric_max_gaps_soft_deleted_and_legacy(self):
        project = self.project()
        with Session(self.engine) as s:
            for code,deleted in [('DOC-000003',False),('DOC-999999',False),
                    ('DOC-1000000',True),('legacy-1000009',False),('DOC-wrong',False)]:
                self.add(s,project,code,deleted)
            s.commit()
            self.assertEqual(allocate_document_code(s,project),'DOC-1000001')

    def test_codes_larger_than_int64(self):
        project=self.project()
        with Session(self.engine) as s:
            self.add(s,project,'DOC-9999999999999999999999999999')
            s.commit()
            self.assertEqual(allocate_document_code(s,project),'DOC-10000000000000000000000000000')

    def test_same_project_commit_serializes_mixed_entry_helpers(self):
        project=self.project()
        q=queue.Queue()
        with Session(self.engine,autoflush=False) as first, ThreadPoolExecutor(max_workers=1) as pool:
            code=upload_code(first,project)
            self.add(first,project,code)
            def second():
                with Session(self.engine,autoflush=False) as s:
                    s.execute(text("SET LOCAL statement_timeout='5s'"))
                    q.put(s.scalar(text('SELECT pg_backend_pid()')))
                    next_code=reference_code(s,project)
                    self.add(s,project,next_code)
                    s.commit()
                    return next_code
            pending=pool.submit(second)
            try:
                self.wait_lock(q.get(timeout=3))
                self.assertFalse(pending.done())
                first.commit()
                self.assertEqual(pending.result(timeout=5),'DOC-000002')
            finally:
                first.rollback()
        with Session(self.engine) as s:
            self.assertEqual(set(s.scalars(select(Document.document_code).where(Document.project_id==project))),{'DOC-000001','DOC-000002'})

    def test_rollback_releases_lock_without_consuming_code(self):
        project=self.project()
        with Session(self.engine) as first:
            self.add(first,project,upload_code(first,project))
            first.flush()
            first.rollback()
        with Session(self.engine) as second:
            self.assertEqual(reference_code(second,project),'DOC-000001')

    def test_different_projects_are_independent(self):
        a,b=self.project(),self.project()
        with Session(self.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(upload_code(first,a),'DOC-000001')
            def other():
                with Session(self.engine) as s:
                    s.execute(text("SET LOCAL statement_timeout='2s'"))
                    return data_source_code(s,b)
            self.assertEqual(pool.submit(other).result(timeout=3),'DOC-000001')

    def test_missing_project_is_safe_error(self):
        with Session(self.engine) as s, self.assertRaises(AppError) as ctx:
            allocate_document_code(s,uuid4())
        self.assertEqual(ctx.exception.code,'project_not_found')

    def test_archived_project_is_rechecked_after_lock_wait(self):
        project=self.project()
        with Session(self.engine) as s:
            user=User(keycloak_user_id=str(uuid4()),display_name='test owner')
            s.add(user);s.flush();uid=user.id;s.commit()
        q=queue.Queue()
        with Session(self.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
            allocate_document_code(first,project)
            first.execute(text("UPDATE projects SET status='archived',archived_at=:now,archived_by=:uid WHERE id=:id"),
                          {'now':datetime.now(UTC),'uid':uid,'id':project})
            def second():
                with Session(self.engine) as s:
                    s.execute(text("SET LOCAL statement_timeout='5s'"))
                    q.put(s.scalar(text('SELECT pg_backend_pid()')))
                    try:
                        allocate_document_code(s,project)
                    except AppError as exc:
                        return exc.code
            pending=pool.submit(second)
            try:
                self.wait_lock(q.get(timeout=3));first.commit()
                self.assertEqual(pending.result(timeout=5),'project_archived')
            finally:
                first.rollback()


if __name__=='__main__':
    unittest.main(verbosity=2)
