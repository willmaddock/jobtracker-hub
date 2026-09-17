"""Preserve the old section adapter as explicitly synthetic organizational groups.

This is not physical-folder reconstruction. Only an exact section-key override
supplies the archive flag the adapter previously displayed. All override rows,
including conflicting section metadata and unused/path-like keys, remain intact.
"""
from django.db import migrations


SECTIONS = ('credentials', 'network', 'resume_library', 'leads', 'compliance', 'personal', 'misc')


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Application = apps.get_model('applications', 'Application')
    Category = apps.get_model('documents', 'Category')
    Membership = apps.get_model('documents', 'CategoryMembership')
    FolderOverride = apps.get_model('documents', 'FolderOverride')
    groups = Application.objects.using(alias).exclude(section='applications').values_list(
        'workspace_id', 'section').distinct()
    for workspace_id, source_section in groups:
        provenance = {'kind': 'synthetic_section_group', 'source_section': source_section}
        # The old adapter keyed only by folder == section. Preserve that observed
        # presentation state on this ONE synthetic group, never infer a folder.
        override = FolderOverride.objects.using(alias).filter(workspace_id=workspace_id, folder=source_section).first()
        if override:
            provenance['archive_adapter_override_id'] = override.pk
        category = Category.objects.using(alias).filter(workspace_id=workspace_id, provenance=provenance).first()
        if category is None:
            category = Category.objects.using(alias).create(
                workspace_id=workspace_id, name=f'Legacy section group: {source_section!r}'[:255],
                section=source_section if source_section in SECTIONS else 'misc',
                archived=bool(override and override.archived), provenance=provenance)
        for application in Application.objects.using(alias).filter(workspace_id=workspace_id, section=source_section).iterator():
            _, created = Membership.objects.using(alias).get_or_create(
                application_id=application.pk, defaults={'category_id': category.pk})
            if created:
                Application.objects.using(alias).filter(pk=application.pk).update(category_revision=1)


class Migration(migrations.Migration):
    dependencies = [('documents', '0003_category_categorymembership_and_more')]
    # No reverse cleanup: once native writes exist, an undo cannot identify which
    # memberships a user retained or changed. Rehearse backup/restore separately.
    operations = [migrations.RunPython(backfill)]
