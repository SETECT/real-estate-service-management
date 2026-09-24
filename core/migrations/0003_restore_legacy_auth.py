"""Repair the existing database created without AUTH_USER_MODEL.

Fresh installations already use core.User, so this migration does nothing there.
Keep legacy tables intact and preserve account IDs, passwords and memberships.
"""
from django.core.management.color import no_style
from django.db import migrations


def restore_legacy_auth(apps, schema_editor):
    connection = schema_editor.connection
    alias = connection.alias
    User = apps.get_model("core", "User")
    quote = schema_editor.quote_name
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        if "auth_user" not in tables:
            return
        cursor.execute("SELECT id, password, last_login, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined FROM auth_user")
        columns = [column[0] for column in cursor.description]
        legacy_users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for values in legacy_users:
            if User.objects.using(alias).filter(pk=values["id"]).exists() or User.objects.using(alias).filter(username=values["username"]).exists():
                raise RuntimeError("Legacy and custom user accounts conflict. Resolve the accounts before applying this migration; no data has been overwritten.")
            values["role"] = "admin" if values["is_staff"] or values["is_superuser"] else "agent"
            User.objects.using(alias).create(**values)
        for table, relation, target in (
            ("auth_user_groups", User.groups.through, "group_id"),
            ("auth_user_user_permissions", User.user_permissions.through, "permission_id"),
        ):
            if table in tables:
                cursor.execute(f"SELECT user_id, {quote(target)} FROM {quote(table)}")
                for user_id, target_id in cursor.fetchall():
                    relation.objects.using(alias).get_or_create(user_id=user_id, **{target: target_id})
        for statement in connection.ops.sequence_reset_sql(no_style(), [User]):
            cursor.execute(statement)
        constraints = connection.introspection.get_constraints(cursor, "django_admin_log")
        for name, constraint in constraints.items():
            if constraint["foreign_key"] == ("auth_user", "id"):
                schema_editor.execute(f"ALTER TABLE django_admin_log DROP CONSTRAINT {quote(name)}")
                schema_editor.execute(
                    "ALTER TABLE django_admin_log ADD CONSTRAINT resms_admin_log_core_user_fk "
                    "FOREIGN KEY (user_id) REFERENCES core_user (id) DEFERRABLE INITIALLY DEFERRED"
                )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_user_timestamps"),
        ("admin", "0003_logentry_add_action_flag_choices"),
    ]
    operations = [migrations.RunPython(restore_legacy_auth)]
