"""Exact descriptive agreement only; stateless advisory discovery, never identity."""
from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import APIException

from .models import JobPosting
from .retained_interpretations import InterpretationObservation, observe_posting_interpretation

RULE_VERSION = 1
MAX_ID = 9223372036854775807


class InvalidPostingCandidateNavigation(APIException):
    status_code = 400
    default_code = "invalid_posting_candidate_navigation"
    default_detail = "Invalid posting candidate navigation."


@dataclass(frozen=True, slots=True)
class CandidateCursor:
    rule_version: int
    workspace_id: int
    item_id: int
    interpretation_revision: int
    applicable_output_id: int
    membership_revision: int
    last_examined_pk: int


@dataclass(frozen=True, slots=True)
class PostingCandidate:
    posting_id: int
    portable_id: UUID
    company: str
    title: str
    location: str | None
    status: str
    saved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateDiscovery:
    interpretation: InterpretationObservation
    outcome: str
    candidates: tuple[PostingCandidate, ...]
    next_cursor: CandidateCursor | None
    exhausted: bool
    rule_version: int = RULE_VERSION
    consistency: str = "advisory"


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _canonical_rows(workspace_id, company, title, last, limit):
    return tuple(JobPosting.objects.filter(workspace_id=workspace_id,
        account__workspace_id=workspace_id, company=company, title=title, pk__gt=last)
        .order_by("pk").values("id", "portable_id", "company", "title", "location",
                               "status", "saved")[:limit + 1])


def discover_retained_posting_candidates(*, actor, workspace, item_id, limit=100, cursor=None):
    """Bound examined coarse matches, not returned candidates; no page-filling loop.

    The lookahead is unconsumed. Continuation does not freeze canonical rows and
    never requires its prior anchor to exist. All returned values are detached.
    """
    if type(limit) is not int or not 1 <= limit <= 200:
        raise InvalidPostingCandidateNavigation()
    if cursor is not None and (type(cursor) is not CandidateCursor or any(
            type(value) is not int or not 1 <= value <= MAX_ID for value in (
                cursor.rule_version, cursor.workspace_id, cursor.item_id,
                cursor.interpretation_revision, cursor.applicable_output_id,
                cursor.last_examined_pk)) or type(cursor.membership_revision) is not int
            or not 0 <= cursor.membership_revision <= MAX_ID):
        raise InvalidPostingCandidateNavigation()
    observed = observe_posting_interpretation(actor=actor, workspace=workspace, item_id=item_id)
    context = (RULE_VERSION, observed.workspace_id, observed.item_id, observed.revision,
               observed.applicable_output_id, observed.current_membership_revision)
    if cursor is not None and context != (cursor.rule_version, cursor.workspace_id,
            cursor.item_id, cursor.interpretation_revision, cursor.applicable_output_id,
            cursor.membership_revision):
        raise InvalidPostingCandidateNavigation()
    evidence = observed.evidence
    if evidence is None or not _nonblank(evidence.company) or not _nonblank(evidence.title):
        return CandidateDiscovery(observed, "no_applicable_evidence", (), None, True)
    rows = _canonical_rows(observed.workspace_id, evidence.company, evidence.title,
                           cursor.last_examined_pk if cursor else 0, limit)
    examined = rows[:limit]
    candidates = []
    for row in examined:
        if row["company"] != evidence.company or row["title"] != evidence.title:
            continue
        reasons = ("company_exact_equal", "title_exact_equal")
        if (_nonblank(evidence.location) and _nonblank(row["location"])
                and row["location"] == evidence.location):
            reasons += ("location_exact_equal",)
        candidates.append(PostingCandidate(row["id"], row["portable_id"], row["company"],
            row["title"], row["location"], row["status"], row["saved"], reasons))
    more = len(rows) > limit
    next_cursor = CandidateCursor(*context, examined[-1]["id"]) if more else None
    return CandidateDiscovery(observed, "evaluated", tuple(candidates), next_cursor, not more)
