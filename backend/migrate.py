from pathlib import Path


def migration_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "sql" / "migrations"


if __name__ == "__main__":
    print(migration_directory())

