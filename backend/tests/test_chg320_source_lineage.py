"""Real isolated PostgreSQL source-lineage regression; no Provider or commit."""
import os
import unittest
from uuid import UUID, uuid4

from sqlalchemy import select
from app.db.models import Document, DocumentVersion, Project
from app.db.session import get_session_factory
from app.api.routes.documents import _reference_source_summary

PROJECT = UUID("fee58304-8247-474e-8ea5-ff739c99ef07")
DOCUMENT = UUID("36f8b18d-ad4c-46a5-a01a-adfd8dd9c77e")
VERSION = UUID("80b0ac93-989c-49e7-8f89-d49a82f85a53")


class SourceLineageDatabaseTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
            from current_source_lineage_support import native_source_lineage
            scope = native_source_lineage()
            self.db, self.project_id, self.document, self.version = scope.__enter__()
            self.document_id, self.version_id = self.document.id, self.version.id
            self.addCleanup(scope.__exit__, None, None, None)
            return
        if os.environ.get("NOMOSMART_CHG320_ISOLATED_PROJECT_ID") != str(PROJECT):
            self.skipTest("BLOCKED: current owned CHG320 PostgreSQL scope required")
        self.db = get_session_factory()()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        project = self.db.get(Project, PROJECT)
        self.assertIsNotNone(project)
        self.assertEqual(project.name, "CHG320 isolated integrity acceptance")
        self.document = self.db.get(Document, DOCUMENT)
        self.version = self.db.get(DocumentVersion, VERSION)
        self.project_id, self.document_id, self.version_id = PROJECT, DOCUMENT, VERSION
        self.assertEqual(self.document.project_id, PROJECT)
        self.assertEqual(self.version.document_id, DOCUMENT)

    def test_same_document_rebuild_is_not_cross_document_reference(self):
        self.assertEqual(self.document.source_type, "file_upload")
        self.assertEqual(self.version.source_document_id, self.document_id)
        self.assertIsNotNone(self.version.source_version_id)
        self.assertIsNone(_reference_source_summary(self.db, self.document, self.version, {self.project_id}))
        self.assertIsNone(_reference_source_summary(self.db, self.document, self.version, set()))

    def test_real_distinct_document_copy_retains_source_identity(self):
        target = Document(id=uuid4(), project_id=self.project_id, document_code=uuid4().hex,
                          title="Scoped source-lineage copy", source_type="document_reference")
        self.db.add(target)
        self.db.flush()
        copied = DocumentVersion(id=uuid4(), project_id=self.project_id, document_id=target.id,
                                 version_major=1, extraction_revision=0, version_label="v1.0", status="draft",
                                 source_document_id=self.document_id, source_version_id=self.version_id, chunk_strategy={})
        self.db.add(copied)
        self.db.flush()
        source = _reference_source_summary(self.db, target, copied, {self.project_id})
        self.assertEqual(source.source_document_id, self.document_id)
        self.assertEqual(source.source_version_id, self.version_id)
        self.assertEqual(source.status, "copied")
        self.assertTrue(source.has_access)
        denied = _reference_source_summary(self.db, target, copied, set())
        self.assertFalse(denied.has_access)
        self.assertIsNone(_reference_source_summary(self.db, target, None, {self.project_id}))
        self.db.rollback()
        self.assertIsNone(self.db.get(Document, target.id))


if __name__ == "__main__":
    unittest.main()
