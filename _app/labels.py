"""Section and document-type display labels used by the web app.

Kept in their own module, independent of any UI framework, since they're
plain data consumed by the API and rendered by frontend/index.html.
"""

from __future__ import annotations

SECTION_LABELS = {
    "applications": "📋 Applications",
    "credentials": "🎓 Credentials",
    "network": "🤝 Recommendations & Network",
    "resume_library": "📄 Resume Library",
    "leads": "🔍 Leads",
    "compliance": "🗂️ Case Management",
    "personal": "🔒 Personal",
    "misc": "📎 Misc",
}

DOC_TYPE_LABELS = {
    "resume": "Resume",
    "cover_letter": "Cover letter",
    "interview_prep": "Interview prep",
    "rejection_notice": "Rejection notice",
    "interview_notice": "Interview notice",
    "application_confirmation": "Confirmation",
    "job_posting": "Job posting",
    "certificate": "Certificate",
    "readme": "Readme",
    "other": "Other",
}
