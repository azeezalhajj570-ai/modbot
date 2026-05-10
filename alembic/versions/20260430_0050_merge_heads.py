"""merge heads

Revision ID: 20260430_0050
Revises: 0016, 20260429_0030
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260430_0050"
down_revision: tuple[str, str] = ("0016", "20260429_0030")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
