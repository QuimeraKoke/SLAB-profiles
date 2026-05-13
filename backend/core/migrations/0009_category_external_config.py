from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_player_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="external_config",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Provider binding for external match-data APIs. Leave "
                    "empty for categories not covered by any provider "
                    "(e.g. academy / youth). API-Football shape (pulls "
                    "every competition the team played that season — "
                    "league, cup, continental, friendlies): "
                    '<code>{"provider": "api_football", "team_id": 257, '
                    '"season": 2026}</code>. Optional <code>league_ids</code> '
                    "array restricts the sync to specific competitions."
                ),
            ),
        ),
    ]
