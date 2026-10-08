#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Defaults to dev settings; override with an env var for prod
    # (e.g. DJANGO_SETTINGS_MODULE=config.settings.prod).
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Match Django's early selector parsing, including CLI precedence. Admission
    # must precede dispatch: Django can suppress settings errors for shell/help.
    from django.core.management.base import CommandError, CommandParser
    parser = CommandParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--settings')
    parser.add_argument('--pythonpath')
    parser.add_argument('args', nargs='*')
    try:
        options, _ = parser.parse_known_args(sys.argv[2:])
    except CommandError:
        options = None  # Django defers malformed option handling to the command.
    selected = (options.settings if options and options.settings else
                os.environ['DJANGO_SETTINGS_MODULE'])
    if selected == 'config.settings.prod':
        os.environ['DJANGO_SETTINGS_MODULE'] = selected
        if options and options.pythonpath:
            sys.path.insert(0, options.pythonpath)
        try:
            from django.conf import settings
            settings.INSTALLED_APPS  # Force admission without service probes.
        finally:
            if options and options.pythonpath:
                sys.path.remove(options.pythonpath)  # Dispatch applies it itself.
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
