# Generated by Django 5.1.4 on 2024-12-19 13:05

import django.db.models.deletion
import i18nfield.fields
import pretalx.common.models.mixins
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("event", "0037_remove_event_accept_template_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventExtraLink",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("label", i18nfield.fields.I18nCharField(max_length=200)),
                ("url", models.URLField()),
                ("role", models.CharField(default="footer", max_length=6)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extra_links",
                        to="event.event",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
            bases=(
                pretalx.common.models.mixins.OrderedModel,
                pretalx.common.models.mixins.LogMixin,
                pretalx.common.models.mixins.FileCleanupMixin,
                models.Model,
            ),
        ),
    ]