"""Explicit form binding; deliberately separate from Django's CSRF tag."""
from django import template
from django.conf import settings
from django.utils.html import format_html
from gateway import session_context

register = template.Library()


@register.simple_tag(takes_context=True)
def gateway_context(context):
    request = context.get('request')
    if not settings.JTH_GATEWAY:
        return ''
    if request is None or getattr(request, 'gateway_lineage', None) is None:
        raise RuntimeError('Gateway forms require a server-validated lineage request.')
    return format_html('<input type="hidden" name="{}" value="{}">',
                       session_context.FORM_FIELD, session_context.issue(request)['binding'])
