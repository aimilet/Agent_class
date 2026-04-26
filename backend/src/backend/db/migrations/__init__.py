def get_migrations():
    from backend.db.migrations.versions.v0001_initial import migration as v0001_initial

    return [v0001_initial]
