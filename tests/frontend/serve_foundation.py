"""Disposable browser test server. Run with backend/venv/bin/python from repo root.

All database/media state lives in a new TemporaryDirectory. No tracker data or
.env database settings are used. Test-only routes are absent from product URLs.
"""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"

from django.conf import settings

with tempfile.TemporaryDirectory(prefix="jth-foundation-") as directory:
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(Path(directory) / "browser.sqlite3")}}
    settings.MEDIA_ROOT = str(Path(directory) / "media")
    settings.SESSION_COOKIE_NAME = "jth_foundation_session"
    settings.CSRF_COOKIE_NAME = "jth_foundation_csrf"
    settings.SECRET_KEY = "isolated-browser-test-only"
    settings.ROOT_URLCONF = __name__
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.http import HttpResponse, JsonResponse
    from django.urls import path
    from django.views.decorators.csrf import csrf_protect
    from django.views.decorators.clickjacking import xframe_options_sameorigin
    from core.frontend import index as product_index
    from accounts.models import Workspace
    from config.urls import urlpatterns as product_urls
    from rest_framework.views import APIView
    from rest_framework.response import Response
    call_command("migrate", verbosity=0)
    for username, names in (("alice", ["A", "B"]), ("bob", ["C"])):
        user = get_user_model().objects.create_user(username=username, password="browser-fixture-only")
        for name in names:
            Workspace.objects.create(owner=user, name=name)

    # Core read fixtures only; no user tracker is opened.
    from applications.models import Application, Override
    from documents.models import Category, CategoryMembership
    from datetime import date
    a = Workspace.objects.get(pk=1)
    first = Application.objects.create(workspace=a, section="applications", company="Repeated Co", role_label="Engineer", status="applied")
    Override.objects.create(application=first, manual_status="interviewing", archived=True,
                            date_applied=date(2026, 9, 1), date_applied_mode="manual")
    category = Category.objects.create(workspace=a, name="Fixture category", section="misc")
    CategoryMembership.objects.create(application=first, category=category)
    second = Application.objects.create(workspace=a, section="applications", company="Repeated Co", role_label="Engineer")
    Application.objects.create(workspace=a, section="credentials", company="Certificate", role_label="Other section")
    Application.objects.create(workspace=Workspace.objects.get(pk=3), section="applications", company="Bob private", role_label="Foreign")

    # Normal evidence is created exclusively through existing domain authorities.
    import uuid
    from email_sync.retention import establish_mailbox, retain_observation
    from email_sync.models import RetainedMessage
    from email_sync.tests.test_retention import fixture
    from postings.retained_extractions import record_posting_extraction
    from postings.tests.test_retained_extractions import spec, fields
    from postings.models import RetainedPostingExtraction
    alice = get_user_model().objects.get(username="alice")
    workspace = Workspace.objects.get(pk=1)
    mailbox = establish_mailbox(actor=alice, workspace=workspace, provider="gmail",
                               evidence={"method":"test", "reference":"browser-fixtures"})
    sources = {}
    def retained(label, subject=None):
        data = fixture(mailbox)
        data["source"]["value"] = "private-locator-" + label
        data["content"]["subject"] = subject if subject is not None else "private-subject-" + label
        data["content"]["text"]["value"] = "private-body-" + label
        result = retain_observation(actor=alice, workspace=workspace, key=str(uuid.uuid4()), observation=data)
        return RetainedMessage.objects.get(pk=result.message_id)
    def extraction(message, outputs):
        return record_posting_extraction(actor=alice, workspace=workspace, retained_message_id=message.pk,
            operation_id=uuid.uuid4(), extractor_method="job_alert_rules", extractor_version="1",
            input_spec=spec(), extracted_at="2026-10-05T12:00:00Z", outputs=outputs)
    for label in ("no-history", "zero", "history", "maximum", "conflict", "invalid-source", "corrupt", "lookahead"):
        message = retained(label)
        sources[label] = message.pk
        if label == "zero":
            extraction(message, [])
        elif label == "history":
            descriptor = {**fields("<script>window.evidenceInjected=true</script>"), "company":"<img src=x onerror=alert(1)>"}
            extraction(message, [descriptor, descriptor, fields("")])
            extraction(message, [])
            extraction(message, [fields("Later operation")])
        elif label == "maximum":
            extraction(message, [fields("Output " + str(index + 1)) for index in range(1000)])
            extraction(message, [fields("Other operation")])
        elif label == "conflict":
            extraction(message, [fields()])
            RetainedMessage.objects.filter(pk=message.pk).update(has_conflict=True)
        elif label == "invalid-source":
            RetainedMessage.objects.filter(pk=message.pk).update(content_digest="0" * 64)
        elif label == "corrupt":
            recorded = extraction(message, [fields()])
            RetainedPostingExtraction.objects.filter(pk=recorded.operation.pk).update(payload_digest="0" * 64)
        elif label == "lookahead":
            extraction(message, [fields()]); extraction(message, [fields()])
            recorded = extraction(message, [fields()])
            RetainedPostingExtraction.objects.filter(pk=recorded.operation.pk).update(payload_digest="0" * 64)
    # More than 50 sources exercises the actual summary endpoint continuation.
    for index in range(46):
        retained("summary-" + str(index))

    # Canonical review fixtures share the disposable source authority, never credentials.
    from applications.retained_reviews import ensure_application_review, set_review_dismissal
    from applications.message_relationships import attach_message
    from applications.review_views import RetainedApplicationReviewCreate
    from rest_framework.test import APIRequestFactory, force_authenticate
    from core.lifecycle import set_trash
    reviews = {}
    renamed = Application.objects.create(workspace=workspace, section="applications", company="Initial name", role_label="Initial role")
    removed = Application.objects.create(workspace=workspace, section="misc", company="Removed", role_label="Gone")
    trashed = Application.objects.create(workspace=workspace, section="credentials", company="Trashed reference", role_label="Read only")
    for label, ids in (("multiple", [first.pk, second.pk, renamed.pk, removed.pk]), ("dismissed", [first.pk]),
                       ("restored", []), ("conflict", []), ("trashed", [trashed.pk]), ("created", [])):
        message = retained("review-" + label, subject="<img src=x onerror=window.reviewInjected=true> Review " + label)
        review, _ = ensure_application_review(actor=alice, workspace=workspace, retained_message_id=message.pk,
            observation_id=message.observations.order_by("pk").first().pk,
            classification="ambiguous" if len(ids)>1 else "match" if ids else "application", candidate_ids=ids)
        reviews[label] = review.pk
        if label == "multiple":
            attach_message(actor=alice, workspace=workspace, application_id=first.pk, retained_message_id=message.pk)
            attach_message(actor=alice, workspace=workspace, application_id=second.pk, retained_message_id=message.pk)
        if label in {"dismissed", "restored"}:
            set_review_dismissal(actor=alice, workspace=workspace, review_id=review.pk, dismissed=True, expected_revision=0)
            if label == "restored":
                set_review_dismissal(actor=alice, workspace=workspace, review_id=review.pk, dismissed=False, expected_revision=1)
        if label == "conflict":
            RetainedMessage.objects.filter(pk=message.pk).update(has_conflict=True)
        if label == "created":
            request = APIRequestFactory().post("/fixture", {"company":"CREATION PRIVATE PAYLOAD","role_label":"Excluded creation"}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            force_authenticate(request, user=alice)
            result = RetainedApplicationReviewCreate.as_view()(request, workspace_id=workspace.pk, pk=review.pk)
            assert result.status_code == 201, result.data
    renamed.company = "<script>window.reviewInjected=true</script> Current name"
    renamed.role_label = "Current role"; renamed.save(update_fields=["company", "role_label"])
    # Privileged fixture deletion exercises the existing nullable candidate contract only.
    removed.delete()
    set_trash(actor=alice, workspace=workspace, kind="applications", pk=trashed.pk, trashed=True, expected_revision=0)
    for index in range(46):
        message=retained("review-page-"+str(index))
        ensure_application_review(actor=alice, workspace=workspace, retained_message_id=message.pk,
            observation_id=message.observations.get().pk, classification="application",candidate_ids=[])
    # Category fixtures remain disposable and independent of older workflow fixtures.
    categories = {}
    category_members = {}
    for label, name, archived, section in (
        ("live", "<img src=x onerror=window.categoryInjected=true> Category", False, "network"),
        ("archived", "Same name", True, "credentials"),
        ("duplicate", "Same name", False, "misc"),
        ("empty", "Empty", False, "personal"),
        ("archived-empty", "Archived empty", True, "misc"),
        ("large", "Large", False, "misc"),
        ("trashed", "Trashed fixture", False, "misc")):
        item = Category.objects.create(workspace=workspace, name=name, section=section, archived=archived)
        categories[label] = item.pk
    for label, archived in (("live", False), ("archived", True), ("moved", False), ("unavailable", False), ("later-trash", False)):
        app = Application.objects.create(workspace=workspace, company="<script>window.categoryInjected=true</script> Member " + label,
                                         role_label="Role " + label, section="applications")
        if archived:
            Override.objects.create(application=app, archived=True)
        CategoryMembership.objects.create(application=app, category_id=categories["live"])
        category_members[label] = app.pk
    app = Application.objects.create(workspace=workspace, company="Archived category member", role_label="Visible", section="misc")
    CategoryMembership.objects.create(application=app, category_id=categories["archived"])
    Override.objects.create(application=app, archived=True)
    hidden = Application.objects.create(workspace=workspace, company="Trashed membership excluded", role_label="Hidden", section="applications")
    CategoryMembership.objects.create(application=hidden, category_id=categories["live"])
    set_trash(actor=alice, workspace=workspace, kind="applications", pk=hidden.pk, trashed=True, expected_revision=0)
    set_trash(actor=alice, workspace=workspace, kind="categories", pk=categories["trashed"], trashed=True, expected_revision=0)
    for index in range(61):
        Category.objects.create(workspace=workspace, name="Extra category " + str(index), section="misc")
        app = Application.objects.create(workspace=workspace, company="Large member", role_label=str(index), section="credentials")
        CategoryMembership.objects.create(application=app, category_id=categories["large"])
    Category.objects.create(workspace=Workspace.objects.get(pk=3), name="Foreign Category", section="misc")
    # Assignment-only synthetic resources; faults never touch production contracts.
    assignment_apps = {}
    assignment_categories = {}
    for label, archived, trashed_flag in (("live", False, False), ("archived", True, False), ("empty", False, False), ("duplicate", False, False), ("trashed", False, True)):
        item = Category.objects.create(workspace=workspace, name="Assignment same" if label in {"archived", "duplicate"} else "Assignment " + label, section="network" if label == "archived" else "misc", archived=archived)
        assignment_categories[label] = item.pk
        if trashed_flag:
            set_trash(actor=alice, workspace=workspace, kind="categories", pk=item.pk, trashed=True, expected_revision=0)
    for label in ("categorized", "uncategorized", "archived", "trashed", "trashed-source"):
        app = Application.objects.create(workspace=workspace, company="Assignment " + label, role_label="Assignment role", section="applications")
        assignment_apps[label] = app.pk
        if label != "uncategorized":
            CategoryMembership.objects.create(application=app, category_id=assignment_categories["trashed" if label == "trashed-source" else "live"])
        if label == "archived":
            Override.objects.create(application=app, archived=True)
        if label == "trashed":
            set_trash(actor=alice, workspace=workspace, kind="applications", pk=app.pk, trashed=True, expected_revision=0)

    def assignment_fixtures(request):
        return JsonResponse({"applications":assignment_apps,"categories":assignment_categories})

    class AssignmentFixtureControl(APIView):
        def post(self, request):
            # Test-controller traffic is outside product-frame traffic. Only fixed fixture IDs admitted.
            from documents.category_services import assign_category
            command = request.data.get("command")
            if request.user.pk != alice.pk:
                return Response(status=404)
            app = Application.objects.get(pk=assignment_apps[request.data.get("application", "categorized")])
            target = Category.objects.get(pk=assignment_categories[request.data.get("category", "empty")])
            if command == "move":
                return assign_category(actor=alice, workspace=workspace, application_id=app.pk, category_id=target.pk, expected_revision=app.category_revision)
            if command == "trash-target":
                set_trash(actor=alice, workspace=workspace, kind="categories", pk=target.pk, trashed=True, expected_revision=target.lifecycle_revision)
            elif command == "restore-target":
                set_trash(actor=alice, workspace=workspace, kind="categories", pk=target.pk, trashed=False, expected_revision=target.lifecycle_revision)
            elif command == "trash-app":
                set_trash(actor=alice, workspace=workspace, kind="applications", pk=app.pk, trashed=True, expected_revision=app.lifecycle_revision)
            elif command == "restore-app":
                set_trash(actor=alice, workspace=workspace, kind="applications", pk=app.pk, trashed=False, expected_revision=app.lifecycle_revision)
            else:
                return Response(status=400)
            return Response({"ok": True})

    def category_fixtures(request):
        return JsonResponse({"categories":categories,"members":category_members})

    def review_fixtures(request):
        return JsonResponse({"reviews":reviews,"renamed":renamed.pk,"trashed":trashed.pk})

    def evidence_fixtures(request):
        return JsonResponse({"sources":sources, "empty_workspace":2, "foreign_workspace":3})

    class UploadProbe(APIView):
        def post(self, request):
            file = request.FILES.get("file")
            return Response({"actor": request.user.username, "label": request.data.get("label"),
                             "filename": file.name if file else None,
                             "content": file.read().decode() if file else None})

    class SlowProbe(APIView):
        def get(self, request):
            time.sleep(1)
            return Response({"ok": True})

    @xframe_options_sameorigin
    def framed_product(request):
        response = product_index(request)
        # Installed before React/client construction, so the captured fetch binding
        # remains the actual runtime boundary. Hooks exist only on disposable pages.
        hook = """<script>(function(){
          const nativeFetch=window.fetch.bind(window);
          window.__fixtureNativeFetch=nativeFetch; window.__fixtureTraffic=[];
          window.fetch=function(url,options){
            const entry={url:String(url),method:options&&options.method||'GET',body:options&&options.body};
            if(entry.method==='PUT'&&window.__fixtureAssignmentIntent){entry.assignmentIntent=window.__fixtureAssignmentIntent;window.__fixtureAssignmentIntent=null;}
            if(window.__fixtureFoundationAction==='logout'&&entry.url==='/api/auth/logout'&&entry.method==='POST'){
              entry.foundationAction='logout'; window.__fixtureFoundationAction=null;
            }
            window.__fixtureTraffic.push(entry);
            if(window.parent!==window&&Array.isArray(window.parent.__fixtureAggregateTraffic)){
              window.parent.__fixtureAggregateTraffic.push(entry);
            }
            const result=window.__fixtureIntercept&&window.__fixtureIntercept(String(url),options);
            return result||nativeFetch(url,options);
          };
        })();</script>"""
        response.content = response.content.decode().replace('<script src="/workspace-context.js">',
                                                             hook + '<script src="/workspace-context.js">', 1)
        return response

    def application_fixtures(request):
        return JsonResponse({"first": first.pk, "second": second.pk, "category": category.pk})

    def harness(request):
        return HttpResponse((ROOT / "tests/frontend/foundation-browser.html").read_text())

    # Same-origin frames exercise independent actual React roots in this disposable
    # harness only. Production entry retains its normal clickjacking policy.
    urlpatterns = [path("", framed_product),
                   path("foundation-tests", harness),
                   path("api/test-only/evidence-fixtures", evidence_fixtures),
                   path("api/test-only/application-fixtures", application_fixtures),
                   path("api/test-only/review-fixtures", review_fixtures),
                   path("api/test-only/category-fixtures", category_fixtures),
                   path("api/test-only/assignment-fixtures", assignment_fixtures),
                   path("api/test-only/assignment-control", AssignmentFixtureControl.as_view()),
                   path("api/test-only/upload", UploadProbe.as_view()),
                   path("api/test-only/slow", SlowProbe.as_view())] + product_urls
    print("Disposable fixtures: alice / bob; password browser-fixture-only; workspaces A=1 B=2 C=3", flush=True)
    call_command("runserver", "127.0.0.1:8765", use_reloader=False)
