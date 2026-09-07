"""
Phase 4: introduces Document (docs/DJANGO_MIGRATION_PLAN.md Phase 4)
and wires DocumentOverride/DocumentExtraction to it -- see the
documents/models.py module docstring for why the two got wired up
differently (OneToOne vs. a provenance-only nullable FK).

Hand-written, not `makemigrations`-generated: this container has no
network access to install Django and run it for real. Sequencing and
field/constraint definitions were checked by hand against
0001_initial.py and models.py -- run `manage.py makemigrations
--check documents` after applying to confirm there's no drift before
you migrate a real database with it.

DocumentOverride goes through DeleteModel + CreateModel rather than a
field-by-field alter, since its identity is changing (auto `id` PK ->
`document` OneToOneField PK) and there's no existing DocumentOverride
data on this branch yet to preserve. If you've already got real rows
in that table, don't run this as-is -- write a data migration instead
so a rebuild/relink step maps each old (workspace, relpath) row onto
its new Document row before the old columns are dropped.
"""

import django.db.models.deletion
from django.db import migrations, models

import documents.models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('applications', '0001_initial'),
        ('documents', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Document',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to=documents.models.document_upload_path)),
                ('filename', models.CharField(max_length=255)),
                ('doc_type', models.CharField(
                    choices=[
                        ('readme', 'Readme'),
                        ('resume', 'Resume'),
                        ('cover_letter', 'Cover letter'),
                        ('interview_prep', 'Interview prep'),
                        ('rejection_notice', 'Rejection notice'),
                        ('interview_notice', 'Interview notice'),
                        ('application_confirmation', 'Application confirmation'),
                        ('job_posting', 'Job posting'),
                        ('certificate', 'Certificate'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=32,
                )),
                ('ext', models.CharField(max_length=16)),
                ('content_hash', models.CharField(db_index=True, max_length=64)),
                ('size', models.PositiveBigIntegerField()),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='applications.application')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='accounts.workspace')),
            ],
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['workspace', 'application'], name='doc_workspace_app_idx'),
        ),
        migrations.AddIndex(
            model_name='document',
            index=models.Index(fields=['workspace', 'content_hash'], name='doc_workspace_hash_idx'),
        ),
        migrations.AddField(
            model_name='documentextraction',
            name='document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='extractions',
                to='documents.document',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='documentoverride',
            name='unique_document_override_per_workspace',
        ),
        migrations.DeleteModel(
            name='DocumentOverride',
        ),
        migrations.CreateModel(
            name='DocumentOverride',
            fields=[
                ('document', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='override',
                    serialize=False,
                    to='documents.document',
                )),
                ('doc_type_override', models.CharField(blank=True, max_length=64, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
