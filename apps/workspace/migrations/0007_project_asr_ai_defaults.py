# Generated manually for project ASR/AI research-protocol defaults

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0006_research_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectsettings",
            name="asr_provider",
            field=models.CharField(
                blank=True,
                help_text="local | openai; null inherits account/system ASR defaults.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="asr_model",
            field=models.CharField(
                blank=True,
                help_text="Whisper size or OpenAI model id; null inherits.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="ai_enabled",
            field=models.BooleanField(
                blank=True,
                help_text="null inherits system AI enabled flag.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="ai_provider",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="ai_ollama_base_url",
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="ai_ollama_model",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
