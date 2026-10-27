from django.db import migrations


def load_help_content(apps, schema_editor):
    from support import help_content

    help_content.load(apps)


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0003_errorcode_faq'),
    ]

    operations = [
        migrations.RunPython(load_help_content, migrations.RunPython.noop),
    ]
