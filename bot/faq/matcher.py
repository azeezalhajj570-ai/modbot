"""Deterministic FAQ matcher with text normalization and fuzzy matching."""

import re
import hashlib
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class MatchResult:
    faq_entry_id: Optional[int]
    confidence: float
    question: str
    answer: Optional[str] = None
    normalized_question: Optional[str] = None

def normalize_text(text: str) -> str:
    """Normalize text for matching."""
    if not text:
        return ""
        
    # Lowercase
    text = text.lower()
    
    # Normalize Arabic characters
    # أ, إ, آ -> ا
    text = re.sub(r'[أإآ]', 'ا', text)
    # ة -> ه
    text = re.sub(r'ة', 'ه', text)
    # ى -> ي
    text = re.sub(r'ى', 'ي', text)
    
    # Remove punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', ' ', text)
    
    # Remove repeated spaces and trim
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def get_question_hash(normalized_text: str) -> str:
    """Generate a hash for a normalized question."""
    return hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()

def _levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(s2)]


def _fuzzy_similarity(a: str, b: str) -> float:
    distance = _levenshtein_distance(a, b)
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - (distance / max_len)


class DeterministicFAQMatcher:
    """Matches questions against FAQ entries using deterministic rules."""
    
    def match(self, question: str, entries: List[Any]) -> MatchResult:
        """
        Find the best match for a question among entries.
        entries should be a list of FAQEntry objects or similar.
        """
        if not entries:
            return MatchResult(faq_entry_id=None, confidence=0.0, question=question)
            
        norm_q = normalize_text(question)
        if not norm_q:
            return MatchResult(faq_entry_id=None, confidence=0.0, question=question)
            
        best_entry = None
        best_confidence = 0.0
        
        q_tokens = set(norm_q.split())
        
        for entry in entries:
            if not entry.enabled:
                continue
                
            norm_entry_q = normalize_text(entry.question)
            entry_tokens = set(norm_entry_q.split())
            
            confidence = 0.0
            
            # 1. Exact normalized match
            if norm_q == norm_entry_q:
                confidence = 0.95
            else:
                # 2. Token overlap (Jaccard similarity)
                intersection = q_tokens.intersection(entry_tokens)
                union = q_tokens.union(entry_tokens)
                jaccard = len(intersection) / len(union) if union else 0
                
                # 3. Levenshtein fuzzy similarity for typo/bendict similarity
                fuzzy_score = _fuzzy_similarity(norm_q, norm_entry_q)
                
                # 4. Keyword overlap
                keyword_score = 0.0
                if hasattr(entry, 'keywords') and entry.keywords:
                    entry_keywords = [normalize_text(k) for k in entry.keywords]
                    keyword_matches = [k for k in entry_keywords if k in norm_q]
                    keyword_score = len(keyword_matches) / len(entry_keywords) if entry_keywords else 0.0
                
                # Weighted confidence (jaccard + fuzzy + keywords)
                confidence = (jaccard * 0.4) + (fuzzy_score * 0.3) + (keyword_score * 0.3)
                
                # 5. Phrase containment
                if norm_entry_q in norm_q or norm_q in norm_entry_q:
                    confidence = max(confidence, 0.8)
            
            if confidence > best_confidence:
                best_confidence = confidence
                best_entry = entry
                
        if best_entry and best_confidence >= 0.1:
            return MatchResult(
                faq_entry_id=best_entry.id,
                confidence=best_confidence,
                question=question,
                answer=best_entry.answer,
                normalized_question=norm_q
            )
            
        return MatchResult(
            faq_entry_id=None, 
            confidence=best_confidence, 
            question=question,
            normalized_question=norm_q
        )
