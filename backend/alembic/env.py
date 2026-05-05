"""
Price Sentinel — Alembic env.py
Configurazione per migrazioni database con import automatico dei modelli.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importa tutti i modelli per farli registrare nella metadata
from app.models import Base  # noqa: F401 — Importa Base con tutti i modelli
from app.config import settings

# Alembic Config object
config = context.config

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData dei modelli per autogenerate
target_metadata = Base.metadata

# Sovrascrive sqlalchemy.url con la stringa dal .env (sincrona per Alembic)
config.set_main_option("sqlalchemy.url", settings.database_url_sync)


def run_migrations_offline() -> None:
    """Run migrazioni in modalità 'offline' — genera SQL senza connessione."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrazioni in modalità 'online' — connessione diretta al DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
