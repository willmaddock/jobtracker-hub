"""Loads the shared endpoint policy from _app/gateway_policy.py by file path.

Loading by path (not by adding _app/ to sys.path) keeps the original app's flat modules
(db, labels, domain...) from shadowing anything in Django's import namespace.
"""
import importlib.util

from django.conf import settings

_spec = importlib.util.spec_from_file_location("jth_gateway_policy", settings.JTH_APP_SOURCE / "gateway_policy.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

decide = _mod.decide
UNSAFE_METHODS = _mod.UNSAFE_METHODS
