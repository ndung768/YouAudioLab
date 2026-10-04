# Catalog label default scope (used when adding a label to a project).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0010_projectlabel_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="label",
            name="default_scope",
            field=models.CharField(
                choices=[
                    ("SEGMENT", "Whole segment"),
                    ("SPAN", "Text in transcript"),
                    ("BOTH", "Both"),
                ],
                default="BOTH",
                help_text="Default use when this catalog label is added to a project.",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="label",
            constraint=models.CheckConstraint(
                condition=models.Q(default_scope__in=["SEGMENT", "SPAN", "BOTH"]),
                name="ck_label_default_scope",
            ),
        ),
    ]
