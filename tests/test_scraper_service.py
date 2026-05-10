from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.db.models import ScrapedGroup, ScrapedMember, ScrapedMessage
from bot.services.scraper_service import ScraperService


@pytest.mark.asyncio
async def test_scraper_bulk_upserts_replace_existing_rows_without_duplicates(db_session) -> None:
    scraped_group = ScrapedGroup(tg_group_id=-1007001, title="Scraper Group", group_type="supergroup")
    db_session.add(scraped_group)
    await db_session.commit()

    service = ScraperService(db_session)

    await service._bulk_upsert_scraped_members(
        [
            service._build_scraped_member_row(
                scraped_group_id=scraped_group.id,
                tg_group_id=scraped_group.tg_group_id,
                tg_user_id=501,
                username="first-pass",
                first_name="First",
                full_name="First Pass",
                role="member",
                raw_data={"source": "initial"},
            )
        ]
    )
    await service._bulk_upsert_scraped_members(
        [
            service._build_scraped_member_row(
                scraped_group_id=scraped_group.id,
                tg_group_id=scraped_group.tg_group_id,
                tg_user_id=501,
                username="second-pass",
                first_name="Second",
                full_name="Second Pass",
                role="admin",
                raw_data={"source": "updated"},
            )
        ]
    )

    await service._bulk_upsert_scraped_messages(
        [
            service._build_scraped_message_row(
                scraped_group_id=scraped_group.id,
                tg_group_id=scraped_group.tg_group_id,
                message_id=9001,
                sender_user_id=501,
                sender_username="first-pass",
                message_text="first",
                message_type="text",
                raw_data={"source": "initial"},
            )
        ]
    )
    await service._bulk_upsert_scraped_messages(
        [
            service._build_scraped_message_row(
                scraped_group_id=scraped_group.id,
                tg_group_id=scraped_group.tg_group_id,
                message_id=9001,
                sender_user_id=501,
                sender_username="second-pass",
                message_text="second",
                message_type="document",
                raw_data={"source": "updated"},
            )
        ]
    )
    await db_session.commit()

    members = (
        await db_session.execute(
            select(ScrapedMember).where(
                ScrapedMember.tg_group_id == scraped_group.tg_group_id,
                ScrapedMember.tg_user_id == 501,
            )
        )
    ).scalars().all()
    assert len(members) == 1
    assert members[0].username == "second-pass"
    assert members[0].role == "admin"
    assert members[0].raw_data["source"] == "updated"

    messages = (
        await db_session.execute(
            select(ScrapedMessage).where(
                ScrapedMessage.tg_group_id == scraped_group.tg_group_id,
                ScrapedMessage.message_id == 9001,
            )
        )
    ).scalars().all()
    assert len(messages) == 1
    assert messages[0].sender_username == "second-pass"
    assert messages[0].message_text == "second"
    assert messages[0].message_type == "document"
    assert messages[0].raw_data["source"] == "updated"
