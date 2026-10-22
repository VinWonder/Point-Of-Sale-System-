"""
Kept for backwards compatibility — the demo data now lives in a management command:

    python manage.py seed_demo

Running this file through the Django shell still works:
    python manage.py shell -c "exec(open('seed_demo_data.py').read())"
"""
from django.core.management import call_command

call_command('seed_demo')
