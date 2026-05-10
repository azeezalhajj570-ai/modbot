"""deduplicate scraped_groups and add unique constraint on tg_group_id

Revision ID: b82c40b0b4a8
Revises: 0dd9a36ecbd3
Create Date: 2026-04-24 22:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b82c40b0b4a8'
down_revision = '0dd9a36ecbd3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    
    # 1. Deduplicate scraped_groups
    # We find groups with the same tg_group_id, pick the one with highest ID as survivor
    # and update related tables before deleting duplicates.
    
    if bind.dialect.name == "postgresql":
        # Find all duplicates
        op.execute("""
            CREATE TEMP TABLE group_duplicates AS
            SELECT tg_group_id, MAX(id) as survivor_id
            FROM scraped_groups
            GROUP BY tg_group_id
            HAVING COUNT(id) > 1
        """)
        
        # Update members to point to survivors
        op.execute("""
            UPDATE scraped_members m
            SET scraped_group_id = d.survivor_id
            FROM scraped_groups g
            JOIN group_duplicates d ON g.tg_group_id = d.tg_group_id
            WHERE m.scraped_group_id = g.id AND g.id != d.survivor_id
        """)
        
        # Update messages to point to survivors
        op.execute("""
            UPDATE scraped_messages m
            SET scraped_group_id = d.survivor_id
            FROM scraped_groups g
            JOIN group_duplicates d ON g.tg_group_id = d.tg_group_id
            WHERE m.scraped_group_id = g.id AND g.id != d.survivor_id
        """)
        
        # Delete non-surviving duplicates
        op.execute("""
            DELETE FROM scraped_groups
            WHERE id IN (
                SELECT g.id 
                FROM scraped_groups g
                JOIN group_duplicates d ON g.tg_group_id = d.tg_group_id
                WHERE g.id != d.survivor_id
            )
        """)
        
        op.execute("DROP TABLE group_duplicates")

    # 2. Add unique constraint/index
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table('scraped_groups', schema=None) as batch_op:
            # We first need to drop the old index if it exists
            batch_op.drop_index('ix_scraped_groups_tg_group_id')
            batch_op.create_index('ix_scraped_groups_tg_group_id', ['tg_group_id'], unique=True)
    else:
        # Postgres
        op.drop_index('ix_scraped_groups_tg_group_id', table_name='scraped_groups')
        op.create_index('ix_scraped_groups_tg_group_id', 'scraped_groups', ['tg_group_id'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table('scraped_groups', schema=None) as batch_op:
            batch_op.drop_index('ix_scraped_groups_tg_group_id')
            batch_op.create_index('ix_scraped_groups_tg_group_id', ['tg_group_id'], unique=False)
    else:
        op.drop_index('ix_scraped_groups_tg_group_id', table_name='scraped_groups')
        op.create_index('ix_scraped_groups_tg_group_id', 'scraped_groups', ['tg_group_id'], unique=False)
