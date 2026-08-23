from app.core.config import Settings
from app.sources.ebay import SEARCH_URL, TOKEN_URL, api_root
from app.sources.ebay_filters import browse_filter, reject_title


def test_iphone_rejects_case() -> None:
    assert reject_title("iPhone 15 Pro", "iPhone 15 Pro Leather Case") == "accessory"
    assert reject_title("iPhone 15 Pro", "Apple iPhone 15 Pro 256GB Unlocked") is None


def test_gm_ii_rejects_hood_and_gm_i() -> None:
    assert reject_title("Sony 24-70 GM II", "Sony FE 24-70mm GM II Lens Hood") == "accessory"
    assert reject_title("Sony 24-70 GM II", "Sony FE 24-70mm F2.8 GM II") is None
    assert reject_title("Sony 24-70 GM II", "Sony FE 24-70mm GM") == "wrong_generation_gm"


def test_rtx_rejects_laptop_and_super() -> None:
    assert reject_title("RTX 4080", "RTX 4080 Laptop GPU 12GB") == "accessory"
    assert reject_title("RTX 4080", "NVIDIA GeForce RTX 4080 SUPER") == "4080_super_mismatch"
    assert reject_title("RTX 4080", "NVIDIA GeForce RTX 4080 16GB") is None


def test_browse_filter_price_band() -> None:
    assert "price:[80..2500]" in browse_filter()


def test_prd_keys_use_production_host() -> None:
    s = Settings(ebay_client_id="Wally-ARIE-PRD-000000000", ebay_client_secret="PRD-abcdef", ebay_env="sandbox")
    assert s.ebay_api_env == "production"
    assert api_root(s.ebay_api_env) == "https://api.ebay.com"
    assert TOKEN_URL[s.ebay_api_env] == "https://api.ebay.com/identity/v1/oauth2/token"
    assert SEARCH_URL[s.ebay_api_env] == "https://api.ebay.com/buy/browse/v1/item_summary/search"


def test_sbx_keys_use_sandbox_host() -> None:
    s = Settings(ebay_client_id="Wally-ARIE-SBX-000000000", ebay_client_secret="SBX-abcdef", ebay_env="production")
    assert s.ebay_api_env == "sandbox"
    assert api_root(s.ebay_api_env) == "https://api.sandbox.ebay.com"
    assert TOKEN_URL[s.ebay_api_env].startswith("https://api.sandbox.ebay.com")
    assert SEARCH_URL[s.ebay_api_env].startswith("https://api.sandbox.ebay.com")
