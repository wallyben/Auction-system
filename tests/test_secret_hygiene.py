from pathlib import Path

from app.sources.ebay import TOKEN_URL


def test_env_is_gitignored() -> None:
    text = Path(".gitignore").read_text()
    assert ".env" in text


def test_token_hosts_are_not_mixed() -> None:
    assert "sandbox" not in TOKEN_URL["production"]
    assert "sandbox" in TOKEN_URL["sandbox"]


def test_fixture_secrets_are_obviously_fake() -> None:
    fixtures = Path("tests/test_ebay_env.py").read_text() + Path("tests/test_ebay_filters.py").read_text()
    assert "Example-ARIE" in fixtures or "Wally-ARIE" in fixtures
    assert "sk_live" not in fixtures
    assert "Bearer eBay" not in fixtures
