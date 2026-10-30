from django.db import migrations


def load_help_content(apps, schema_editor):
    from support import help_content

    # Adds the new codes (WEB-405, WEB-408, WEB-413, WEB-429, WEB-502, WEB-504, NET-001, NET-002)
    # without touching wording that has been edited in the Django admin.
    help_content.load(apps, only_missing=True)


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0006_alter_errorcode_area'),
    ]

    operations = [
        migrations.RunPython(load_help_content, migrations.RunPython.noop),
    ]
