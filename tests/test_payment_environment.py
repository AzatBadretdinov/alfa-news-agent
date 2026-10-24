"""Amounts and unknowns in the profile must reflect all payment edges."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from company_context import ContextStore, build_database

FIXTURES = Path(__file__).parent / "fixtures/company_context"


class PaymentEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "context.sqlite"
        build_database(FIXTURES / "companies.csv", self.db, FIXTURES / "links.csv", FIXTURES / "payments.csv")

    def profile(self, uid="U_A", top_n=20):
        with ContextStore(self.db) as store:
            return store.profile(uid, top_n)

    def test_industry_and_coverage_use_full_directional_amount(self):
        context = self.profile()["payment_summary"]["counterparty_context"]
        outgoing = context["out"]
        self.assertEqual(outgoing["amount_total"], 1)
        by_code = {row["okved_division"]: row for row in outgoing["industry_distribution"]}
        self.assertEqual(by_code["24"]["amount"], 0.3)
        self.assertEqual(by_code["24"]["share_of_direction"], 0.3)
        self.assertEqual(by_code[None]["amount"], 0.7)
        self.assertEqual(by_code[None]["counterparty_ids"], ["U_EXTERNAL"])
        self.assertEqual(outgoing["coverage"]["company_card"]["known_share"], 0.3)
        self.assertEqual(outgoing["coverage"]["industry"]["unknown_share"], 0.7)
        incoming = context["in"]
        self.assertEqual(incoming["amount_total"], 5)
        self.assertEqual(incoming["coverage"]["company_card"]["known_share"], 1)
        self.assertEqual(incoming["coverage"]["industry"]["known_share"], 1)

    def test_missing_group_id_is_unknown_not_other_group(self):
        context = self.profile()["payment_summary"]["counterparty_context"]
        self.assertEqual(context["out"]["group_distribution"]["same_group"]["share_of_direction"], 0.3)
        # U_C has a card but no GROUP_ID, and therefore remains unclassified.
        incoming = context["in"]
        self.assertEqual(incoming["group_distribution"]["unknown"]["share_of_direction"], 0.8)
        self.assertEqual(incoming["group_distribution"]["other_group"]["amount"], 0)
        self.assertEqual(incoming["coverage"]["group_membership"]["known_share"], 0.2)
        without_own_group = self.profile("U_C")["payment_summary"]["counterparty_context"]["out"]
        self.assertEqual(without_own_group["group_distribution"]["unknown"]["share_of_direction"], 1)

    def test_known_different_group_is_classified(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            data = json.loads(connection.execute("SELECT data FROM companies WHERE id='U_C'").fetchone()[0])
            data["GROUP_ID"] = "G_2"
            connection.execute("UPDATE companies SET group_id=?, data=? WHERE id='U_C'", ("G_2", json.dumps(data)))
        incoming = self.profile()["payment_summary"]["counterparty_context"]["in"]
        self.assertEqual(incoming["group_distribution"]["other_group"]["amount"], 4)
        self.assertEqual(incoming["group_distribution"]["other_group"]["share_of_direction"], 0.8)
        self.assertEqual(incoming["coverage"]["group_membership"]["unknown_share"], 0)

    def test_profile_limit_does_not_change_aggregates(self):
        full = self.profile()["payment_summary"]["counterparty_context"]
        limited = self.profile(top_n=1)["payment_summary"]["counterparty_context"]
        self.assertEqual(full, limited)
        self.assertEqual(len(self.profile(top_n=1)["counterparties"]), 1)

    def test_unknown_industry_is_distinct_from_missing_card(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            raw = json.loads(connection.execute("SELECT data FROM companies WHERE id='U_B'").fetchone()[0])
            raw["MAINOKVED_CODE"] = None
            connection.execute("UPDATE companies SET division=NULL, data=? WHERE id='U_B'", (json.dumps(raw),))
        flow = self.profile()["payment_summary"]["counterparty_context"]["out"]
        self.assertEqual(flow["coverage"]["company_card"]["known_share"], 0.3)
        self.assertEqual(flow["coverage"]["industry"]["known_share"], 0)
        self.assertEqual(len(flow["industry_distribution"]), 1)
        self.assertEqual(flow["industry_distribution"][0]["amount"], 1)

    def test_no_payments_and_zero_amount_do_not_create_shares(self):
        empty = self.profile("U_E")["payment_summary"]["counterparty_context"]
        self.assertTrue(empty["available"])
        self.assertEqual(empty["out"]["amount_total"], 0)
        self.assertIsNone(empty["out"]["coverage"]["industry"]["known_share"])
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("INSERT INTO payments VALUES ('U_E','U_C','0',1,100)")
        flow = self.profile("U_E")["payment_summary"]["counterparty_context"]["out"]
        self.assertEqual(flow["counterparties_count"], 1)
        for item in flow["industry_distribution"]:
            self.assertIsNone(item["share_of_direction"])

    def test_missing_source_has_no_directional_statistics(self):
        db = Path(self.temp.name) / "minimal.sqlite"
        build_database(FIXTURES / "companies.csv", db)
        with ContextStore(db) as store:
            context = store.profile("U_A")["payment_summary"]["counterparty_context"]
        self.assertFalse(context["available"])
        self.assertIsNone(context["in"])
        self.assertIsNone(context["out"])

    def test_large_industry_bucket_is_bounded_but_amount_not_truncated(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for i in range(550):
                uid = f"EXTRA_{i:03}"
                raw = {"MAINOKVED_CODE": "24.10"}
                connection.execute("INSERT INTO companies VALUES (?,NULL,'24',NULL,?,?)", (uid, i + 100, json.dumps(raw)))
                connection.execute("INSERT INTO payments VALUES ('U_E',?,'1',1,?)", (uid, i + 100))
        flow = self.profile("U_E", top_n=1)["payment_summary"]["counterparty_context"]["out"]
        item = next(row for row in flow["industry_distribution"] if row["okved_division"] == "24")
        self.assertEqual(item["amount"], 550)
        self.assertEqual(item["counterparties_count"], 550)
        self.assertEqual(len(item["counterparty_ids"]), 20)
        self.assertTrue(item["counterparty_ids_truncated"])
        self.assertEqual(item["share_of_direction"], 1)

    def test_new_signal_has_resolvable_evidence(self):
        profile = self.profile(top_n=1)
        signals = [s for s in profile["relevance_signals"] if s["topic"].startswith("отрасль контрагентов")]
        self.assertTrue(signals)
        for signal in signals:
            for path in signal["evidence"]:
                value = profile
                for key in path.strip("/").split("/"):
                    value = value[int(key)] if isinstance(value, list) else value[key]
                self.assertGreaterEqual(value["share_of_direction"], 0.25)
                self.assertIsNotNone(value["okved_division"])


if __name__ == "__main__":
    unittest.main()
