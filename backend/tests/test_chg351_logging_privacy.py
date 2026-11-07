"""Native logging behavior; real HTTP/access-log proof is recorded separately."""
import io
import logging
import unittest

from app.core.logging import ApprovalAccessLogPrivacy


class ApprovalLoggingPrivacyTests(unittest.TestCase):
    def render(self, target):
        output = io.StringIO()
        logger = logging.Logger("chg351-native-access", logging.INFO)
        logger.addFilter(ApprovalAccessLogPrivacy())
        handler = logging.StreamHandler(output)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.info('%s - "%s %s HTTP/%s" %d', "local-client", "GET", target, "1.1", 200)
        return output.getvalue()

    def test_filters_are_absent_but_operational_facts_remain(self):
        result = self.render("/api/v1/approvals/pending?q=private-document&submitter_id=private-person&cursor=opaque")
        self.assertIn('GET /api/v1/approvals/pending HTTP/1.1" 200', result)
        for value in ("private-document", "private-person", "opaque", "?"):
            self.assertNotIn(value, result)

    def test_encoded_route_names_and_candidate_queries_are_private(self):
        result = self.render("/api/v1/%61pprovals/filter-options?kind=submitter&q=private-person")
        self.assertIn("/api/v1/%61pprovals/filter-options HTTP/", result)
        self.assertNotIn("private-person", result)

    def test_unrelated_route_and_non_access_records_are_unchanged(self):
        self.assertIn("/health?detail=1", self.render("/health?detail=1"))
        record = logging.LogRecord("application", logging.INFO, __file__, 1, "Fact %s", ("retained",), None)
        self.assertTrue(ApprovalAccessLogPrivacy().filter(record))
        self.assertEqual(record.getMessage(), "Fact retained")


if __name__ == "__main__":
    unittest.main()
