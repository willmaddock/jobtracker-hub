#!/bin/sh
# Writes deploy/local/.env with fresh random throwaway credentials. Local use only.
# Refuses to overwrite an existing file (delete it first to rotate).
set -e
out="$(dirname "$0")/.env"
[ -e "$out" ] && { echo "$out exists; delete it to regenerate." >&2; exit 1; }
fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }
pw="$(openssl rand -hex 16)"
{
  echo "DJANGO_SECRET_KEY=$(openssl rand -hex 40)"
  echo "DJANGO_DB_PASSWORD=$pw"
  echo "POSTGRES_PASSWORD=$pw"
  echo "GMAIL_TOKEN_ENCRYPTION_KEY=$(fernet)"
  echo "MICROSOFT_TOKEN_ENCRYPTION_KEY=$(fernet)"
  echo "IMAP_TOKEN_ENCRYPTION_KEY=$(fernet)"
  echo "MINIO_ROOT_USER=jthlocal"
  echo "MINIO_ROOT_PASSWORD=$(openssl rand -hex 16)"
} > "$out"
# The app reads S3 credentials under the AWS_* names; same values as MinIO's root login.
echo "AWS_ACCESS_KEY_ID=jthlocal" >> "$out"
echo "AWS_SECRET_ACCESS_KEY=$(grep '^MINIO_ROOT_PASSWORD=' "$out" | cut -d= -f2)" >> "$out"
chmod 600 "$out"
echo "wrote $out"
