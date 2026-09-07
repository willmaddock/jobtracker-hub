from django.test import SimpleTestCase

from .services import (
    compute_bulk_override_fields,
    compute_override_fields,
    resolve_effective_status,
)


class ComputeOverrideFieldsTests(SimpleTestCase):
    def test_only_sent_fields_are_included(self):
        fields = compute_override_fields({"notes"}, {"notes": "called back"}, reset_status=False)
        self.assertEqual(fields, {"notes": "called back"})

    def test_date_applied_without_source_clears_provenance(self):
        fields = compute_override_fields(
            {"date_applied"}, {"date_applied": "2026-01-05"}, reset_status=False
        )
        self.assertEqual(fields["date_applied"], "2026-01-05")
        self.assertIsNone(fields["date_applied_source"])

    def test_date_applied_with_source_keeps_provenance(self):
        fields = compute_override_fields(
            {"date_applied", "date_applied_source"},
            {"date_applied": "2026-01-05", "date_applied_source": "confirmation"},
            reset_status=False,
        )
        self.assertEqual(fields["date_applied_source"], "confirmation")

    def test_reset_status_wins_over_manual_status(self):
        fields = compute_override_fields(
            {"manual_status"}, {"manual_status": "interviewing"}, reset_status=True
        )
        self.assertEqual(fields, {"manual_status": None})

    def test_manual_status_not_sent_is_absent_not_none(self):
        fields = compute_override_fields(set(), {}, reset_status=False)
        self.assertNotIn("manual_status", fields)


class ComputeBulkOverrideFieldsTests(SimpleTestCase):
    def test_notes_and_date_applied_are_not_bulk_fields(self):
        fields = compute_bulk_override_fields(
            {"notes", "archived"}, {"notes": "x", "archived": True}, reset_status=False
        )
        self.assertNotIn("notes", fields)
        self.assertEqual(fields["archived"], True)


class ResolveEffectiveStatusTests(SimpleTestCase):
    def test_none_when_manual_status_untouched(self):
        self.assertIsNone(resolve_effective_status({"notes": "x"}, auto_status="applied"))

    def test_falls_back_to_auto_status_when_cleared(self):
        self.assertEqual(
            resolve_effective_status({"manual_status": None}, auto_status="applied"), "applied"
        )

    def test_uses_manual_status_when_set(self):
        self.assertEqual(
            resolve_effective_status({"manual_status": "rejected"}, auto_status="applied"),
            "rejected",
        )
