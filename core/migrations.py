from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config

MigrationTree = Literal["shared", "per_env"]


def migration_config(tree: MigrationTree, database_url: str) -> Config:
    repo_root = Path(__file__).resolve().parents[1]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "migrations" / tree))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_upgrade(tree: MigrationTree, database_url: str, revision: str = "head") -> None:
    command.upgrade(migration_config(tree, database_url), revision)
