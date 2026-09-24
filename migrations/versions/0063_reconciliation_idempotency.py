"""Protect local ad hierarchy reconciliation from duplicate rows."""

from typing import Sequence, Union

from alembic import op


revision: str = "0063_reconciliation_idempotency"
down_revision: Union[str, None] = "0062_creative_asset_current_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("adset_instances") as batch_op:
        batch_op.create_unique_constraint(
            "uq_campaign_instance_meta_adset",
            ["campaign_instance_id", "meta_adset_id"],
        )
    with op.batch_alter_table("ad_instances") as batch_op:
        batch_op.create_unique_constraint(
            "uq_adset_instance_meta_ad",
            ["adset_instance_id", "meta_ad_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ad_instances") as batch_op:
        batch_op.drop_constraint("uq_adset_instance_meta_ad", type_="unique")
    with op.batch_alter_table("adset_instances") as batch_op:
        batch_op.drop_constraint("uq_campaign_instance_meta_adset", type_="unique")
