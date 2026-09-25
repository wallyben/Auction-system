"""Stop when a page asks for a human. Do not try to pass the challenge."""

from __future__ import annotations

import re

_CAPTCHA = re.compile(r"\b(?:captcha|recaptcha|hcaptcha|turnstile)\b", re.I)
_HUMAN = re.compile(r"verify you are human|are you a human|human verification|bot challenge", re.I)
_CF = re.compile(
    r"just a moment|cf-challenge|attention required|checking your browser|verify you are human|cf-browser-verification",
    re.I,
)
_DENIED = re.compile(r"access denied|you have been blocked|request blocked|forbidden", re.I)
_LOGIN = re.compile(r"\b(?:sign in|log in|login to continue|create an account to view)\b", re.I)


def detect_challenge(status_code: int, html: str, final_url: str = "") -> str:
    text = f"{final_url}\n{(html or '')[:20000]}"
    if status_code == 429 or re.search(r"\brate limit", text, re.I):
        return "RATE_LIMITED"
    if status_code in {401, 407}:
        return "BLOCKED_LOGIN"
    if re.search(r"login required|sign in to continue|log in to continue|log in to view", text, re.I):
        return "BLOCKED_LOGIN"
    if status_code in {403} and (_CF.search(text) or _CAPTCHA.search(text) or _DENIED.search(text) or _HUMAN.search(text)):
        return "BLOCKED_CHALLENGE"
    if _CAPTCHA.search(text) or _HUMAN.search(text) or _CF.search(text):
        return "BLOCKED_CHALLENGE"
    if status_code == 403 or _DENIED.search(text):
        return "BLOCKED_CHALLENGE"
    if status_code >= 500:
        return ""
    if status_code == 0:
        return "NAVIGATION_FAILED"
    return ""


def retryable(challenge: str, status_code: int) -> bool:
    if challenge in {"BLOCKED_CHALLENGE", "BLOCKED_LOGIN", "RATE_LIMITED"}:
        return False
    if status_code in {403, 401, 429}:
        return False
    return status_code in {0, 500, 502, 503, 504} or challenge == "NAVIGATION_FAILED"
