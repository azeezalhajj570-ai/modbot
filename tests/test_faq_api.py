"""Tests for FAQ API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from bot.dashboard.api.main import app
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

@pytest.mark.asyncio
async def test_faq_settings_api(patch_db_dependencies, seeded_group):
    group_id = seeded_group["group_id"]
    user_id = seeded_group["user_id"]
    
    identity = TelegramWebAppIdentity(
        user_id=user_id, 
        username="owner", 
        first_name="Owner", 
        last_name=None, 
        auth_date=12345, 
        raw={}
    )
    
    from bot.dashboard.api.dependencies import get_identity
    app.dependency_overrides[get_identity] = lambda: identity
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test",
        headers={"X-App-Boundary": "admin"}
    ) as ac:
        # 1. Get settings
        response = await ac.get(f"/api/groups/{group_id}/faq/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        
        # 2. Update settings
        payload = {
            "enabled": True,
            "safe_mode": False,
            "default_mode": "auto_reply"
        }
        response = await ac.put(f"/api/groups/{group_id}/faq/settings", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["safe_mode"] is False

@pytest.mark.asyncio
async def test_faq_entries_api(patch_db_dependencies, seeded_group):
    group_id = seeded_group["group_id"]
    user_id = seeded_group["user_id"]
    identity = TelegramWebAppIdentity(
        user_id=user_id, 
        username="owner", 
        first_name="Owner", 
        last_name=None, 
        auth_date=12345, 
        raw={}
    )
    
    from bot.dashboard.api.dependencies import get_identity
    app.dependency_overrides[get_identity] = lambda: identity
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test",
        headers={"X-App-Boundary": "admin"}
    ) as ac:
        # 1. Create entry
        payload = {
            "question": "How to join?",
            "answer": "Click this link.",
            "keywords": ["join", "link"]
        }
        response = await ac.post(f"/api/groups/{group_id}/faq/entries", json=payload)
        assert response.status_code == 201
        entry_id = response.json()["id"]
        
        # 2. List entries
        response = await ac.get(f"/api/groups/{group_id}/faq/entries")
        assert response.status_code == 200
        entries = response.json()
        assert len(entries) == 1
        assert entries[0]["question"] == "How to join?"
        
        # 3. Test matching
        test_payload = {"question": "how can I join?"}
        response = await ac.post(f"/api/groups/{group_id}/faq/test-match", json=test_payload)
        assert response.status_code == 200
        match_data = response.json()
        assert match_data["matched"] is True
        assert match_data["entry_id"] == entry_id

@pytest.mark.asyncio
async def test_faq_unanswered_questions_api(patch_db_dependencies, seeded_group, db_session):
    group_id = seeded_group["group_id"]
    user_id = seeded_group["user_id"]
    identity = TelegramWebAppIdentity(
        user_id=user_id, 
        username="owner", 
        first_name="Owner", 
        last_name=None, 
        auth_date=12345, 
        raw={}
    )
    
    from bot.dashboard.api.dependencies import get_identity
    app.dependency_overrides[get_identity] = lambda: identity
    
    # Manually add an unanswered question to the DB
    from bot.db.models.faq import UnansweredQuestion, UnansweredQuestionStatus
    unanswered = UnansweredQuestion(
        group_id=group_id,
        message_id=555,
        user_id=999,
        username="asker",
        question_preview="What is the meaning of life?",
        normalized_question="what is the meaning of life",
        normalized_question_hash="somehash",
        status=UnansweredQuestionStatus.NEW
    )
    db_session.add(unanswered)
    await db_session.commit()
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test",
        headers={"X-App-Boundary": "admin"}
    ) as ac:
        # 1. Get unanswered questions
        response = await ac.get(f"/api/groups/{group_id}/faq/unanswered")
        assert response.status_code == 200
        questions = response.json()
        assert len(questions) == 1
        assert questions[0]["question_preview"] == "What is the meaning of life?"
        
        # 2. Convert to FAQ
        conv_payload = {"answer": "42"}
        response = await ac.post(
            f"/api/groups/{group_id}/faq/unanswered/{questions[0]['id']}/convert", 
            json=conv_payload
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "42"
        
        # 3. Verify it's in FAQ entries
        response = await ac.get(f"/api/groups/{group_id}/faq/entries")
        entries = response.json()
        assert any(e["answer"] == "42" for e in entries)
