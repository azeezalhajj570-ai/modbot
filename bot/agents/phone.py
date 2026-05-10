from __future__ import annotations

import re


PHONE_INPUT_RE = re.compile(r"^[+\d\s().-]+$")
E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
PHONE_NUMBER_ERROR = "Phone number must be in international format, for example +15551234567"


def normalize_agent_phone_number(phone_number: str | None) -> str:
    raw_phone = str(phone_number or "").strip()
    if not raw_phone:
        raise ValueError("Phone number is required")
    if not PHONE_INPUT_RE.fullmatch(raw_phone):
        raise ValueError(PHONE_NUMBER_ERROR)

    digits = re.sub(r"\D", "", raw_phone)
    normalized_phone = f"+{digits}" if raw_phone.startswith("+") else raw_phone
    if not E164_PHONE_RE.fullmatch(normalized_phone):
        raise ValueError(PHONE_NUMBER_ERROR)
    return normalized_phone


def normalize_optional_agent_phone_number(phone_number: str | None) -> str | None:
    if phone_number is None or not str(phone_number).strip():
        return None
    return normalize_agent_phone_number(phone_number)
