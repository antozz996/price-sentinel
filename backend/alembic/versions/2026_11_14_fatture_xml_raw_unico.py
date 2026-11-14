"""Una sola fattura per xml_raw: indice UNIQUE su fatture(xml_raw_id).

Le fatture doppie vanno cancellate prima (script dati): se ce ne sono ancora la
migrazione si ferma con un messaggio chiaro invece di lasciare l'indice a metà.
"""

from alembic import op
import sqlalchemy as sa

revision = "fatture_xml_raw_unico"
down_revision = "alias_fattore_confezione"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_fatture_xml_raw_id"


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        "SELECT count(*) FROM ("
        "SELECT xml_raw_id FROM fatture GROUP BY xml_raw_id HAVING count(*) > 1"
        ") AS doppie"
    )).scalar()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} xml_raw hanno più di una fattura: cancellare le fatture doppie "
            f"prima di creare l'indice {INDEX_NAME}."
        )
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON fatture (xml_raw_id)")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
