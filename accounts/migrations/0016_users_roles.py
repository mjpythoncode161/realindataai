from django.db import migrations, models


def copy_role_to_roles(apps, schema_editor):
    Users = apps.get_model("accounts", "Users")
    for user in Users.objects.all().only("u_id", "role"):
        if user.role:
            user.roles = [user.role]
            user.save(update_fields=["roles"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_users_signup_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="users",
            name="roles",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(copy_role_to_roles, migrations.RunPython.noop),
    ]
