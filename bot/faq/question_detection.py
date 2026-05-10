"""Deterministic question detection for multiple languages."""

import re

AR_QUESTION_SIGNALS = [
    "؟", "هل", "كيف", "متى", "أين", "لماذا", "كم", "ما", "من", 
    "وين", "ايش", "شلون", "ازاي"
]

EN_QUESTION_SIGNALS = [
    "?", "how", "when", "where", "why", "what", "who", 
    "can", "does", "do", "is", "are"
]

def is_question(text: str) -> bool:
    """Detect if a text is likely a question."""
    if not text or len(text.strip()) < 3:
        return False
        
    text_lower = text.lower().strip()
    
    # Check for question marks
    if "?" in text or "؟" in text:
        return True
        
    # Check for English question words at the start
    words = text_lower.split()
    if not words:
        return False
        
    first_word = words[0].rstrip('?,.!')
    if first_word in EN_QUESTION_SIGNALS:
        return True
        
    # Check for Arabic question words
    for signal in AR_QUESTION_SIGNALS:
        if text_lower.startswith(signal + " ") or text_lower == signal:
            return True
            
    return False
