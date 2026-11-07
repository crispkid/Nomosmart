"""Direct production validation only, NOT simulated OpenSearch integration.

Run with unittest for the narrow contract tier. Full pytest coverage gates remain
unchanged; real OpenSearch/DB acceptance requires its separately owned context.
"""
import copy
import unittest

from app.core.errors import AppError
from app.domain.extraction_pipeline import StagingEvidenceError, validate_staging_bulk_result


class StagingBulkContract(unittest.TestCase):
    def valid(self):
        return {"errors": False, "items": [{"index": {"_index": "owned-contract-index",
            "_id": "v:c", "status": 201, "_shards": {"failed": 0}}}]}

    def validate(self, value):
        validate_staging_bulk_result(value, index="owned-contract-index", document_ids=["v:c"])

    def test_exact_receipt_contract(self):
        for status in (200, 201):
            value = self.valid()
            value["items"][0]["index"]["status"] = status
            before = copy.deepcopy(value)
            self.validate(value)
            self.assertEqual(value, before)

    def test_malformed_or_partial_results_rejected(self):
        for value in (None, [], {}, {"errors": True, "items": []}, {"errors": 0, "items": []},
                      {"errors": False, "items": None}, {"errors": False, "items": []},
                      {"errors": False, "items": [None]}, {"errors": False, "items": [{"create": {}}]}):
            with self.subTest(value=value), self.assertRaises(AppError) as error:
                self.validate(value)
            self.assertEqual(error.exception.code, "opensearch_staging_write_failed")
            self.assertEqual(error.exception.status_code, 502)

    def test_every_item_identity_error_status_and_shards_are_checked(self):
        for key, value in (("_index", "wrong"), ("_id", "wrong"), ("status", 429), ("status", "201"),
                           ("status", True), ("error", {"reason": "sensitive-provider-content"}),
                           ("error", None), ("_shards", {}), ("_shards", {"failed": 1}), ("_shards", "invalid")):
            with self.subTest(field=key, value=value):
                payload = self.valid()
                payload["items"][0]["index"][key] = value
                with self.assertRaises(AppError) as error:
                    self.validate(payload)
                self.assertEqual(str(error.exception), "OpenSearch staging write failed")
                self.assertEqual(error.exception.details, {})

    def test_receipt_count_and_order_must_be_exact(self):
        payload = self.valid()
        payload["items"].append(copy.deepcopy(payload["items"][0]))
        with self.assertRaises(AppError):
            self.validate(payload)
        with self.assertRaises(AppError):
            validate_staging_bulk_result(payload, index="owned-contract-index", document_ids=["v:c", "v:other"])

    def test_diagnostic_reason_does_not_change_public_error_details(self):
        error = StagingEvidenceError("transport", "Existing staging evidence is unavailable")
        self.assertEqual(error.reason, "transport")
        self.assertEqual(error.code, "vector_index_not_ready")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.details, {})


if __name__ == "__main__":
    unittest.main()
