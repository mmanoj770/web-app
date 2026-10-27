from django.db import migrations


def load_help_content(apps, schema_editor):
    from support import help_content

    # Adds the new codes (WEB-400, WEB-401, WEB-503) without touching content edited in the admin.
    help_content.load(apps, only_missing=True)


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0004_load_help_content'),
    ]

    operations = [
        migrations.RunPython(load_help_content, migrations.RunPython.noop),
    ]
