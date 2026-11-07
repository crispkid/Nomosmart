"""Run inside the owned configured backend against actual PostgreSQL; roll back every case."""
import unittest
from sqlalchemy import select
from app.db.session import get_session_factory
from app.db.models import SystemParameter
from app.domain.ocr_token_settings import load_settings, from_snapshot, from_rows, PAGE_KEY, DOCUMENT_KEY
from app.core.errors import AppError

class LiveTokenDatabase(unittest.TestCase):
    def setUp(self): self.db=get_session_factory()()
    def tearDown(self): self.db.rollback(); self.db.close()
    def row(self,key): return self.db.scalar(select(SystemParameter).where(SystemParameter.key==key))
    def test_real_defaults_and_metadata(self):
        actual=load_settings(self.db)
        self.assertEqual((actual.page,actual.document),(10000,1000000))
        defaults=from_rows([self.row(PAGE_KEY),self.row(DOCUMENT_KEY)],defaults=True)
        self.assertEqual((defaults.page,defaults.document),(10000,1000000))
    def test_snapshot_fixed_while_database_changes(self):
        frozen=load_settings(self.db).snapshot()
        self.row(PAGE_KEY).value=8000;self.row(DOCUMENT_KEY).value=900000;self.db.flush()
        self.assertEqual(load_settings(self.db).page,8000)
        self.assertEqual(from_snapshot(frozen).page,10000)
        self.assertEqual(from_snapshot(frozen).document,1000000)
    def test_missing_database_value_rejected(self):
        self.db.delete(self.row(PAGE_KEY));self.db.flush()
        with self.assertRaises(AppError) as caught:load_settings(self.db)
        self.assertEqual(caught.exception.code,'ocr_token_settings_missing')
    def test_boolean_database_value_rejected(self):
        self.row(PAGE_KEY).value=True;self.db.flush()
        with self.assertRaises(AppError):load_settings(self.db)
    def test_invalid_unit_rejected(self):
        self.row(PAGE_KEY).unit='total_tokens';self.db.flush()
        with self.assertRaises(AppError):load_settings(self.db)
    def test_invalid_default_rejected(self):
        self.row(PAGE_KEY).default_value=0;self.db.flush()
        with self.assertRaises(AppError):from_rows([self.row(PAGE_KEY),self.row(DOCUMENT_KEY)],defaults=True)

if __name__=='__main__':unittest.main()
