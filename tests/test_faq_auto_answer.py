"""Integration tests for FAQ service and policy."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from bot.faq.service import FAQService
from bot.db.models.faq import FAQMode, FAQEntry, FAQInteractionStatus
from bot.faq.policy import FAQAction

@pytest.mark.asyncio
async def test_faq_service_flow(db_session: AsyncSession):
    service = FAQService(db_session)
    group_id = 1
    
    # 1. Setup settings
    settings = await service.get_settings(group_id)
    await service.update_settings(group_id, enabled=True, safe_mode=False, default_mode=FAQMode.AUTO_REPLY)
    
    # 2. Add entry
    await service.add_entry(
        group_id=group_id,
        question="What is the price?",
        answer="It is $10.",
        keywords=["price", "cost"]
    )
    
    # 3. Process matching message
    result = await service.process_message(
        group_id=group_id,
        message_id=100,
        user_id=200,
        username="testuser",
        text="What is the price?",
        global_enabled=True
    )
    
    assert result is not None
    assert result.action == FAQAction.AUTO_REPLY
    assert result.answer == "It is $10."
    
    # 4. Check interaction logged
    from bot.db.models.faq import FAQInteraction
    from sqlalchemy import select
    
    stmt = select(FAQInteraction).where(FAQInteraction.message_id == 100)
    db_result = await db_session.execute(stmt)
    interaction = db_result.scalar_one()
    assert interaction.status == FAQInteractionStatus.SENT
    assert interaction.confidence >= 0.9

@pytest.mark.asyncio
async def test_unanswered_question_logging(db_session: AsyncSession):
    service = FAQService(db_session)
    group_id = 1
    
    await service.update_settings(group_id, enabled=True, log_unanswered_questions=True)
    
    # Process unknown question
    result = await service.process_message(
        group_id=group_id,
        message_id=101,
        user_id=201,
        username="testuser2",
        text="How do I fly to the moon?",
        global_enabled=True
    )
    
    assert result is not None
    assert result.action == FAQAction.LOG_UNANSWERED
    
    # Check unanswered question logged
    from bot.db.models.faq import UnansweredQuestion
    from sqlalchemy import select
    
    stmt = select(UnansweredQuestion).where(UnansweredQuestion.message_id == 101)
    db_result = await db_session.execute(stmt)
    unanswered = db_result.scalar_one()
    assert unanswered.question_preview == "How do I fly to the moon?"
    assert unanswered.frequency_count == 1
    
    # Duplicate question increments count
    await service.process_message(
        group_id=group_id,
        message_id=102,
        user_id=202,
        username="testuser3",
        text="How do I fly to the moon?",
        global_enabled=True
    )
    
    await db_session.refresh(unanswered)
    assert unanswered.frequency_count == 2

@pytest.mark.asyncio
async def test_safe_mode_downgrade(db_session: AsyncSession):
    service = FAQService(db_session)
    group_id = 1
    
    # Safe mode enabled, default_mode is AUTO_REPLY
    await service.update_settings(
        group_id=group_id, 
        enabled=True, 
        safe_mode=True, 
        default_mode=FAQMode.AUTO_REPLY
    )
    
    await service.add_entry(
        group_id=group_id,
        question="Is it safe?",
        answer="Yes it is."
    )
    
    result = await service.process_message(
        group_id=group_id,
        message_id=103,
        user_id=203,
        username="testuser4",
        text="Is it safe?",
        global_enabled=True
    )
    
    # Should be downgraded to SUGGEST_TO_ADMIN because of safe_mode=True
    assert result.action == FAQAction.SUGGEST_TO_ADMIN
