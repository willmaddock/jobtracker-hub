"""Additive allocation schema preserves a populated 0011 checkpoint."""
import tempfile
from django.conf import settings
from django.db import connections, migrations
import uuid
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class JobPostingAllocationMigrationTests(TransactionTestCase):
    def test_populated_checkpoint_preserved_without_fabrication(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = "job_posting_allocation_fixture"
            config = dict(connections["default"].settings_dict)
            config.update(NAME=temp + "/fixture.sqlite3", ENGINE="django.db.backends.sqlite3", OPTIONS={})
            original = self.databases
            type(self).databases = original | {alias}
            connections.databases[alias] = config
            db = connections[alias]
            try:
                executor = MigrationExecutor(db)
                others = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "postings"]
                baseline = others + [("postings", "0011_job_posting_descriptor_projections")]
                target = others + [("postings", "0012_job_posting_allocations")]
                executor.migrate(baseline)
                old = executor.loader.project_state(baseline).apps
                def create(app, model, **values):
                    return old.get_model(app, model).objects.using(alias).create(**values)
                user = create("accounts", "User", username="migration")
                stamp = timezone.now()
                for n in range(3):
                    ws = create("accounts", "Workspace", owner_id=user.pk, name=str(n))
                    app = create("applications", "Application", workspace_id=ws.pk, company="Same", section="applications",
                        status="applied", first_activity=stamp, last_activity=stamp, derivation_state="complete",
                        derivation_fingerprint="old", derived_at=stamp,
                        source_relpath="legacy/path", trashed_at=stamp if n == 1 else None, lifecycle_revision=4)
                    create("applications", "Override", application_id=app.pk, manual_status="applied", notes="retain", archived=True)
                    create("applications", "StatusHistory", application_id=app.pk, status="applied", changed_at=stamp)
                    doc = create("documents", "Document", workspace_id=ws.pk, application_id=app.pk, file="retained/original.pdf",
                        filename="original.pdf", ext=".pdf", size=20, content_hash=str(n), doc_type="application_confirmation",
                        trashed_at=stamp if n == 2 else None, lifecycle_revision=2)
                    create("documents", "DocumentOverride", document_id=doc.pk, doc_type_override="application_confirmation")
                    create("documents", "DocumentExtraction", workspace_id=ws.pk, document_id=doc.pk,
                        content_hash=str(n), extractor_version="4", extracted_json={"retained": True}, extracted_at=stamp)
                    cat = create("documents", "Category", workspace_id=ws.pk, name="Shelf", section="misc", archived=True)
                    create("documents", "CategoryMembership", application_id=app.pk, category_id=cat.pk)
                    create("documents", "FolderOverride", workspace_id=ws.pk, folder="legacy", section="misc")
                    intent = create("core", "ApplicationRequestIntent", actor_id=user.pk, workspace_id=ws.pk, key=str(n),
                        digest="retained", kind="manual", application_id=app.pk, result_portable_id=app.portable_id, completed=True)
                    account = create("email_sync", "EmailAccount", workspace_id=ws.pk, email="same@example.test", provider=["gmail", "outlook", "imap"][n])
                    create("email_sync", "GmailCredential", account_id=account.pk, access_token="fixture-ciphertext", refresh_token="fixture-ciphertext")
                    create("email_sync", "OutlookCredential", account_id=account.pk, access_token="fixture-ciphertext", refresh_token="fixture-ciphertext")
                    create("email_sync", "IMAPCredential", account_id=account.pk, host="fixture", username="fixture", password="fixture-ciphertext")
                    create("email_sync", "AccountMatch", account_id=account.pk, application_id=app.pk, message_id="<weak>", subject="Old metadata", received_at=stamp)
                    discovery = create("email_sync", "Discovery", account_id=account.pk, message_id="<weak>", status="dismissed", received_at=stamp)
                    discovery.candidate_applications.add(app)
                    create("email_sync", "ThreadIdentifier", application_id=app.pk, message_id="<weak>")
                    create("email_sync", "JobPostingSender", workspace_id=ws.pk, sender="fixture")
                    posting = create("postings", "JobPosting", workspace_id=ws.pk, account_id=account.pk, dedupe_key=str(n))
                    create("postings", "PostingApplicationConversion", workspace_id=ws.pk, posting_id=posting.pk,
                        application_id=app.pk, application_portable_id=app.portable_id, request_intent_id=intent.pk)
                mailbox = create("email_sync", "MailboxLineage", workspace_id=ws.pk, provider="gmail",
                                 evidence={"method": "fixture", "reference": "preserve"})
                message = create("email_sync", "RetainedMessage", workspace_id=ws.pk, mailbox_id=mailbox.pk,
                                 provider="gmail", locator_kind="gmail_message_id", locator_value="native",
                                 stability="v1", content={"historical": "preserved"}, content_digest="preserve")
                key = create("email_sync", "RetentionKey", workspace_id=ws.pk, key="original", initial_digest="preserve")
                observation = create("email_sync", "RetainedObservation", workspace_id=ws.pk, key_id=key.pk,
                    message_id=message.pk, mailbox_id=mailbox.pk, digest="preserve", payload={"fixture": True},
                    state="retained", observed_at=stamp)
                review = create("applications", "RetainedApplicationReview", workspace_id=ws.pk,
                    retained_message_id=message.pk, originating_observation_id=observation.pk,
                    initial_classification="match")
                create("applications", "RetainedApplicationReviewCandidate", review_id=review.pk,
                       application_id=app.pk, application_portable_id=app.portable_id)
                create("applications", "RetainedApplicationReviewDisposition", review_id=review.pk,
                       dismissed_at=stamp, revision=2)
                create("applications", "ApplicationMessage", workspace_id=ws.pk, application_id=app.pk,
                       retained_message_id=message.pk)
                for n in range(3):
                    extraction = create("postings", "RetainedPostingExtraction", retained_message_id=message.pk,
                        operation_id=uuid.uuid4(), extractor_method="job_alert_rules", extractor_version="1",
                        snapshot_version=1, input_spec={"historical": "unchanged"}, payload_digest="a" * 64,
                        extracted_at=stamp)
                    for position in range(n):
                        output = create("postings", "RetainedPostingExtractionOutput", extraction_id=extraction.pk,
                            portable_id=uuid.uuid4(), position=position, fields={"title": "Same"})
                        item = create("postings", "RetainedPostingItem", retained_message_id=message.pk)
                        association = create("postings", "RetainedPostingItemAssociation", item_id=item.pk, output_id=output.pk,
                               actor_id=user.pk, mode="allocate_new", method="explicit_owner", decision_version=1)
                        create("postings", "RetainedPostingItemCorrection", initial_association_id=association.pk,
                               operation_id=uuid.uuid4(), revision=1, mode="withdraw", actor_id=user.pk,
                               method="explicit_owner", decision_version=1)
                initial_source = create("postings", "PostingSource", item_id=item.pk, posting_id=posting.pk,
                       actor_id=user.pk, method="explicit_owner", decision_version=1)
                create("postings", "PostingSourceCorrection", initial_source_id=initial_source.pk,
                       operation_id=uuid.uuid4(), revision=1, mode="withdraw", actor_id=user.pk,
                       method="explicit_owner", decision_version=1)
                create("postings", "RetainedPostingInterpretationDecision", item_id=item.pk,
                       operation_id=uuid.uuid4(), revision=1, mode="withdraw", actor_id=user.pk)
                create("postings", "JobPostingInterpretationDecision", posting_id=posting.pk,
                       actor_id=user.pk, operation_id=uuid.uuid4(), revision=1, mode="withdraw")
                authority = create("postings", "JobPostingInterpretationDecision", posting_id=posting.pk,
                    actor_id=user.pk, operation_id=uuid.uuid4(), revision=2, mode="withdraw")
                create("postings", "JobPostingDescriptorProjection", posting_id=posting.pk,
                    arbitration_decision_id=authority.pk, actor_id=user.pk, operation_id=uuid.uuid4(),
                    revision=1, snapshot={"historical": "preserved"}, expected_descriptor_digest="a" * 64)
                def snapshot(table):
                    with db.cursor() as cursor:
                        cursor.execute(f"SELECT * FROM {db.ops.quote_name(table)} ORDER BY 1")
                        return [col[0] for col in cursor.description], cursor.fetchall()
                tables = set(db.introspection.table_names()) - {"django_migrations"}
                before = {table: snapshot(table) for table in tables}
                executor = MigrationExecutor(db)
                migration = executor.loader.get_migration("postings", "0012_job_posting_allocations")
                self.assertEqual(migration.dependencies, [("email_sync", "0007_gmail_mailbox_identity"), ("postings", "0011_job_posting_descriptor_projections"),
                                                          migrations.swappable_dependency(settings.AUTH_USER_MODEL)])
                self.assertEqual([type(op).__name__ for op in migration.operations],
                                 ["CreateModel"])
                self.assertEqual([m.name for m, reverse in executor.migration_plan(target)],
                                 ["0012_job_posting_allocations"])
                self.assertEqual(len(migration.operations[0].options["constraints"]), 2)
                executor.migrate(target)
                new_tables = {"postings_jobpostingallocation"}
                def check():
                    self.assertEqual(set(db.introspection.table_names()) - {"django_migrations"}, tables | new_tables)
                    for table in tables:
                        self.assertEqual(before[table], snapshot(table), table)
                    for table in new_tables:
                        self.assertEqual(snapshot(table)[1], [])
                check()
                MigrationExecutor(db).migrate(target)
                check()
                # Exercise current model validation on a real non-default alias.
                # No query may accidentally escape to the default connection.
                from unittest.mock import patch
                from postings.models import JobPostingInterpretationDecision as Decision
                from postings import extraction_contract as contract
                from postings.tests.test_retained_extractions import fields, spec
                unknown = {"precision": "unknown", "value": None, "source": "unknown"}
                content = {"version": 1, "subject": None, "addresses": {"from": [{"name": "", "address": "a@b.test"}]},
                    "headers": [], "text": {"value": "", "completeness": "complete", "reason": ""},
                    "html": {"value": None, "completeness": "unavailable", "reason": "missing"},
                    "header_sent": unknown, "provider_received": unknown,
                    "provenance": {"method": "fixture", "version": "1"}, "conversation_id": ""}
                digest = contract.digest(content)
                old.get_model("email_sync", "RetainedMessage").objects.using(alias).filter(pk=message.pk).update(
                    content=content, content_digest=digest)
                operation = uuid.uuid4()
                envelope = contract.validate_envelope(operation, "job_alert_rules", "1", spec(),
                    stamp.isoformat(), [fields()])
                fingerprint = contract.replay_digest(envelope, dict(workspace_id=ws.pk, retained_message_id=message.pk,
                    retained_message_portable_id=str(message.portable_id), representation_version=1, content_digest=digest))
                extraction = create("postings", "RetainedPostingExtraction", retained_message_id=message.pk,
                    operation_id=operation, extractor_method="job_alert_rules", extractor_version="1",
                    snapshot_version=1, input_spec=spec(), payload_digest=fingerprint, extracted_at=stamp)
                output = create("postings", "RetainedPostingExtractionOutput", extraction_id=extraction.pk,
                    portable_id=uuid.uuid4(), position=0, fields=fields())
                item = create("postings", "RetainedPostingItem", retained_message_id=message.pk)
                association = create("postings", "RetainedPostingItemAssociation", item_id=item.pk, output_id=output.pk,
                    actor_id=user.pk, mode="allocate_new", method="explicit_owner", decision_version=1)
                selected = create("postings", "RetainedPostingInterpretationDecision", item_id=item.pk,
                    actor_id=user.pk, selected_association_id=association.pk, membership_revision=0,
                    operation_id=uuid.uuid4(), revision=1, mode="select")
                initial = create("postings", "PostingSource", item_id=item.pk, posting_id=posting.pk,
                    actor_id=user.pk)
                old.get_model("email_sync", "EmailAccount").objects.using(alias).filter(pk=account.pk).update(provider="gmail")
                binding = create("email_sync", "AccountMailboxBinding", account_id=account.pk, mailbox_id=mailbox.pk)
                key = f"retained-allocation:v1:{item.pk}"
                old.get_model("postings", "JobPosting").objects.using(alias).filter(pk=posting.pk).update(dedupe_key=key)
                historical = executor.loader.project_state(target).apps.get_model("postings", "JobPostingAllocation")
                fact = historical.objects.using(alias).create(posting_id=posting.pk, item_id=item.pk,
                    initial_source_id=initial.pk, interpretation_decision_id=selected.pk, account_binding_id=binding.pk,
                    actor_id=user.pk, operation_id=uuid.uuid4())
                from postings.models import JobPostingAllocation, JobPosting
                from postings import job_posting_allocations as allocations
                from django.core.exceptions import ValidationError
                with patch.object(connections["default"], "cursor", side_effect=AssertionError("default DB used")):
                    row = JobPostingAllocation.objects.using(alias).get(pk=fact.pk)
                    allocations.validate_allocation(row, alias)
                    with self.assertRaises(ValidationError):
                        row.save(using=alias)
                    current = JobPosting.objects.using(alias).get(pk=posting.pk)
                    current.dedupe_key = "forbidden"
                    with self.assertRaises(ValidationError):
                        current.save(using=alias, update_fields=["dedupe_key"])
                    current.saved = True
                    current.save(using=alias, update_fields=["saved"])
                    historical.objects.using(alias).filter(pk=fact.pk).update(operation_id=uuid.UUID(int=0))
                    with self.assertRaises(allocations.JobPostingAllocationConflict):
                        allocations.validate_allocation(JobPostingAllocation.objects.using(alias).get(pk=fact.pk), alias)
            finally:
                db.close()
                del connections[alias]
                del connections.databases[alias]
                type(self).databases = original
