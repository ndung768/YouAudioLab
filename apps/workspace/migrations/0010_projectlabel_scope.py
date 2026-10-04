# Project label scope: whole segment, text span in transcript, or both.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0009_transcript_span"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectlabel",
            name="scope",
            field=models.CharField(
                choices=[
                    ("SEGMENT", "Whole segment"),
                    ("SPAN", "Text in transcript"),
                    ("BOTH", "Both"),
                ],
                default="BOTH",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="projectlabel",
            constraint=models.CheckConstraint(
                condition=models.Q(scope__in=["SEGMENT", "SPAN", "BOTH"]),
                name="ck_pl_scope",
            ),
        ),
    ]
