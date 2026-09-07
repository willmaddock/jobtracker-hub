"""
Production settings. Real values (SECRET_KEY, ALLOWED_HOSTS, database
credentials, etc.) should come from environment variables before this
is ever actually deployed — the placeholders below are not safe to
ship as-is. See docs/DJANGO_MIGRATION_PLAN.md Phase 10.
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# File storage — Phase 4. Overrides base.py's plain-filesystem
# STORAGES["default"] with S3 (or any S3-compatible endpoint, e.g.
# MinIO/R2/Spaces — that's what AWS_S3_ENDPOINT_URL is for; leave it
# unset for real AWS S3). Resumes/cover letters/evidence PDFs are
# personal documents, so the bucket is treated as private: no public
# ACL, and URLs handed to the frontend are short-lived signed links
# rather than permanent public ones (AWS_QUERYSTRING_AUTH=True,
# AWS_QUERYSTRING_EXPIRE below). AWS_S3_FILE_OVERWRITE=False so two
# uploads that happen to share a filename get distinct storage keys
# instead of one silently clobbering the other.
STORAGES['default'] = {
    'BACKEND': 'storages.backends.s3.S3Storage',
}

AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', '')
# Only set for non-AWS S3-compatible providers; leave unset for real S3.
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL') or None
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 300  # signed download links expire after 5 minutes
