"""add explicit supplier identity equivalences

Revision ID: ls_s5_supplier_equivalence
Revises: ls_s5_reconcile
Create Date: 2026-07-26 09:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ls_s5_supplier_equivalence"
down_revision: Union[str, None] = "ls_s5_reconcile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_identity_equivalences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("canonical_supplier_id", sa.Integer(), nullable=False),
        sa.Column("equivalent_supplier_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_supplier_id <> equivalent_supplier_id",
            name="ck_supplier_identity_equivalences_distinct",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) >= 8",
            name="ck_supplier_identity_equivalences_reason",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_supplier_id"],
            ["fornitori.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["equivalent_supplier_id"],
            ["fornitori.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["utenti.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["utenti.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supplier_identity_equivalences_canonical",
        "supplier_identity_equivalences",
        ["canonical_supplier_id"],
    )
    op.create_index(
        "ix_supplier_identity_equivalences_equivalent",
        "supplier_identity_equivalences",
        ["equivalent_supplier_id"],
    )
    op.execute(
        """
        create unique index uq_supplier_identity_equivalences_unordered_pair
          on supplier_identity_equivalences (
            least(canonical_supplier_id,equivalent_supplier_id),
            greatest(canonical_supplier_id,equivalent_supplier_id)
          )
        """
    )

    op.create_table(
        "supplier_identity_equivalence_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("equivalence_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("canonical_supplier_id", sa.Integer(), nullable=False),
        sa.Column("equivalent_supplier_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action in ('created','activated','deactivated','updated')",
            name="ck_supplier_identity_equivalence_audit_action",
        ),
        sa.ForeignKeyConstraint(
            ["equivalence_id"],
            ["supplier_identity_equivalences.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_supplier_id"],
            ["fornitori.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["equivalent_supplier_id"],
            ["fornitori.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["utenti.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supplier_identity_equivalence_audit_equivalence",
        "supplier_identity_equivalence_audit",
        ["equivalence_id", "occurred_at"],
    )

    op.execute(
        """
        create function enforce_supplier_identity_equivalence()
        returns trigger
        language plpgsql
        as $$
        begin
          if tg_op = 'DELETE' then
            raise exception 'supplier_identity_equivalence_delete_forbidden'
              using errcode = '23514';
          end if;
          if tg_op = 'UPDATE'
             and (
               new.canonical_supplier_id is distinct from old.canonical_supplier_id
               or new.equivalent_supplier_id is distinct from old.equivalent_supplier_id
             ) then
            raise exception 'supplier_identity_equivalence_identity_immutable'
              using errcode = '23514';
          end if;
          if new.is_active then
            perform pg_advisory_xact_lock(
              72651,
              least(new.canonical_supplier_id,new.equivalent_supplier_id)
            );
            perform pg_advisory_xact_lock(
              72651,
              greatest(new.canonical_supplier_id,new.equivalent_supplier_id)
            );
            if exists (
              select 1
              from supplier_identity_equivalences existing
              where existing.is_active
                and existing.id is distinct from new.id
                and (
                  existing.canonical_supplier_id in (
                    new.canonical_supplier_id,new.equivalent_supplier_id
                  )
                  or existing.equivalent_supplier_id in (
                    new.canonical_supplier_id,new.equivalent_supplier_id
                  )
                )
            ) then
              raise exception
                'supplier_identity_equivalence_transitive_or_cycle_forbidden'
                using errcode = '23514';
            end if;
          end if;
          new.updated_at = now();
          return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger supplier_identity_equivalence_guard
        before insert or update or delete
        on supplier_identity_equivalences
        for each row execute function enforce_supplier_identity_equivalence()
        """
    )
    op.execute(
        """
        create function audit_supplier_identity_equivalence()
        returns trigger
        language plpgsql
        as $$
        declare
          audit_action text;
        begin
          audit_action := case
            when tg_op = 'INSERT' then 'created'
            when not old.is_active and new.is_active then 'activated'
            when old.is_active and not new.is_active then 'deactivated'
            else 'updated'
          end;
          insert into supplier_identity_equivalence_audit (
            equivalence_id,
            action,
            canonical_supplier_id,
            equivalent_supplier_id,
            is_active,
            reason,
            actor_id,
            occurred_at
          ) values (
            new.id,
            audit_action,
            new.canonical_supplier_id,
            new.equivalent_supplier_id,
            new.is_active,
            new.reason,
            new.updated_by,
            now()
          );
          return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger supplier_identity_equivalence_audit
        after insert or update
        on supplier_identity_equivalences
        for each row execute function audit_supplier_identity_equivalence()
        """
    )

    op.add_column(
        "purchase_order_reconciliations",
        sa.Column("invoice_supplier_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "purchase_order_reconciliations",
        sa.Column("supplier_equivalence_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "purchase_order_reconciliations",
        sa.Column(
            "supplier_equivalence_approved_by", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "purchase_order_reconciliations",
        sa.Column(
            "supplier_equivalence_approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_reconciliations",
        sa.Column(
            "supplier_equivalence_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_reconciliations",
        sa.Column(
            "supplier_equivalence_reason_snapshot", sa.Text(), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_po_reconciliations_invoice_supplier",
        "purchase_order_reconciliations",
        "fornitori",
        ["invoice_supplier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_po_reconciliations_supplier_equivalence",
        "purchase_order_reconciliations",
        "supplier_identity_equivalences",
        ["supplier_equivalence_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_po_reconciliations_equivalence_approver",
        "purchase_order_reconciliations",
        "utenti",
        ["supplier_equivalence_approved_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_po_reconciliations_invoice_supplier",
        "purchase_order_reconciliations",
        ["invoice_supplier_id"],
    )
    op.create_index(
        "ix_po_reconciliations_supplier_equivalence",
        "purchase_order_reconciliations",
        ["supplier_equivalence_id"],
    )
    op.execute(
        """
        update purchase_order_reconciliations reconciliation
        set invoice_supplier_id = invoice.fornitore_id
        from fatture invoice
        where reconciliation.fattura_id = invoice.id
          and reconciliation.invoice_supplier_id is null
        """
    )
    op.create_check_constraint(
        "ck_po_reconciliations_supplier_identity_audit",
        "purchase_order_reconciliations",
        """
        (
          fattura_id is null
          and invoice_supplier_id is null
          and supplier_equivalence_id is null
          and supplier_equivalence_approved_by is null
          and supplier_equivalence_approved_at is null
          and supplier_equivalence_used_at is null
          and supplier_equivalence_reason_snapshot is null
        )
        or
        (
          fattura_id is not null
          and invoice_supplier_id is not null
          and (
            (
              supplier_id = invoice_supplier_id
              and supplier_equivalence_id is null
              and supplier_equivalence_approved_by is null
              and supplier_equivalence_approved_at is null
              and supplier_equivalence_used_at is null
              and supplier_equivalence_reason_snapshot is null
            )
            or
            (
              supplier_id <> invoice_supplier_id
              and supplier_equivalence_id is not null
              and supplier_equivalence_approved_by is not null
              and supplier_equivalence_approved_at is not null
              and supplier_equivalence_used_at is not null
              and supplier_equivalence_reason_snapshot is not null
            )
          )
        )
        """,
    )

    op.add_column(
        "purchase_order_reconciliation_items",
        sa.Column("match_alias_supplier_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_po_reconciliation_items_alias_supplier",
        "purchase_order_reconciliation_items",
        "fornitori",
        ["match_alias_supplier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_po_reconciliation_items_alias_supplier",
        "purchase_order_reconciliation_items",
        ["match_alias_supplier_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    used = connection.execute(
        sa.text(
            """
            select count(*)
            from purchase_order_reconciliations
            where supplier_equivalence_id is not null
            """
        )
    ).scalar_one()
    if used:
        raise RuntimeError(
            "rollback_blocked: operational reconciliations use supplier equivalences"
        )
    equivalences = connection.execute(
        sa.text("select count(*) from supplier_identity_equivalences")
    ).scalar_one()
    if equivalences:
        raise RuntimeError(
            "rollback_blocked: supplier equivalence audit data exists"
        )

    op.drop_index(
        "ix_po_reconciliation_items_alias_supplier",
        table_name="purchase_order_reconciliation_items",
    )
    op.drop_constraint(
        "fk_po_reconciliation_items_alias_supplier",
        "purchase_order_reconciliation_items",
        type_="foreignkey",
    )
    op.drop_column(
        "purchase_order_reconciliation_items", "match_alias_supplier_id"
    )

    op.drop_constraint(
        "ck_po_reconciliations_supplier_identity_audit",
        "purchase_order_reconciliations",
        type_="check",
    )
    op.drop_index(
        "ix_po_reconciliations_supplier_equivalence",
        table_name="purchase_order_reconciliations",
    )
    op.drop_index(
        "ix_po_reconciliations_invoice_supplier",
        table_name="purchase_order_reconciliations",
    )
    op.drop_constraint(
        "fk_po_reconciliations_equivalence_approver",
        "purchase_order_reconciliations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_po_reconciliations_supplier_equivalence",
        "purchase_order_reconciliations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_po_reconciliations_invoice_supplier",
        "purchase_order_reconciliations",
        type_="foreignkey",
    )
    for column in (
        "supplier_equivalence_reason_snapshot",
        "supplier_equivalence_used_at",
        "supplier_equivalence_approved_at",
        "supplier_equivalence_approved_by",
        "supplier_equivalence_id",
        "invoice_supplier_id",
    ):
        op.drop_column("purchase_order_reconciliations", column)

    op.execute(
        "drop trigger supplier_identity_equivalence_audit "
        "on supplier_identity_equivalences"
    )
    op.execute("drop function audit_supplier_identity_equivalence()")
    op.execute(
        "drop trigger supplier_identity_equivalence_guard "
        "on supplier_identity_equivalences"
    )
    op.execute("drop function enforce_supplier_identity_equivalence()")
    op.drop_table("supplier_identity_equivalence_audit")
    op.drop_table("supplier_identity_equivalences")
