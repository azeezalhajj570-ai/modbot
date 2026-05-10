"""Tests for FAQ matching logic."""

import pytest
from bot.faq.matcher import DeterministicFAQMatcher, normalize_text, get_question_hash
from bot.faq.question_detection import is_question

class MockEntry:
    def __init__(self, id, question, answer, keywords=None, enabled=True):
        self.id = id
        self.question = question
        self.answer = answer
        self.keywords = keywords or []
        self.enabled = enabled

def test_question_detection_arabic():
    assert is_question("متى يبدأ الدرس اليوم؟") is True
    assert is_question("هل يوجد درس؟") is True
    assert is_question("كيف حالك") is True # technically a question
    assert is_question("السلام عليكم") is False
    assert is_question("أين يقع المكتب") is True
 # with signal

def test_question_detection_english():
    assert is_question("When does the session start?") is True
    assert is_question("How do I join?") is True
    assert is_question("I want to join") is False
    assert is_question("What is this?") is True

def test_normalization():
    assert normalize_text("متى يبدأ الدرس؟") == "متي يبدا الدرس"
    assert normalize_text("How are you?") == "how are you"
    assert normalize_text("  Spaced   text  ") == "spaced text"

def test_exact_match():
    matcher = DeterministicFAQMatcher()
    entries = [
        MockEntry(1, "متى يبدأ الدرس؟", "يبدأ الساعة 9 مساءً.")
    ]
    result = matcher.match("متى يبدأ الدرس؟", entries)
    assert result.faq_entry_id == 1
    assert result.confidence >= 0.90

def test_keyword_match():
    matcher = DeterministicFAQMatcher()
    entries = [
        MockEntry(1, "موعد الدرس", "يبدأ الساعة 9 مساءً.", keywords=["درس", "موعد"])
    ]
    result = matcher.match("ايش موعد الدرس اليوم؟", entries)
    assert result.faq_entry_id == 1
    assert result.confidence > 0.5

def test_no_match():
    matcher = DeterministicFAQMatcher()
    entries = [
        MockEntry(1, "موعد الدرس", "يبدأ الساعة 9 مساءً.")
    ]
    result = matcher.match("كيف حال الشباب؟", entries)
    assert result.faq_entry_id is None
    assert result.confidence < 0.3
