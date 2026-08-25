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
    assert reject_title("RTX 4070", "Gigabyte RTX 4070 SUPER WINDFORCE") == "4070_super_mismatch"
    assert reject_title("RTX 4070", "HP RTX 4070 Super PC Omen 40L Desktop") == "4070_super_mismatch"


def test_rejects_dj_accessories_empty_box_and_wrong_sony() -> None:
    assert reject_title("Pioneer DDJ-FLX10", "Pioneer DDJ-FLX10 Stand") == "accessory"
    assert reject_title("Pioneer DDJ-1000", "Pioneer DDJ-1000 SRT Skin Protective Decal") == "accessory"
    assert reject_title("Pioneer DDJ-1000", "Power socket for Pioneer DDJ-1000 DKN1649") == "accessory"
    assert reject_title("iPhone 16 Pro 256GB", "BOITE iPhone 16 PRO max 256gb") == "accessory"
    assert reject_title("PlayStation 5", "PS5 APU Foam Pad Insulation") == "accessory"
    assert reject_title("PlayStation 5", "Playstation 5 PRO 2 TB come nuova") == "ps5_pro_mismatch"
    assert reject_title("PlayStation 5", "Playstation 5 PRO Faceplates") == "accessory"
    assert reject_title("Sony A7 IV", "Sony A7R IV ILCE-7RM4") == "wrong_generation_a7r"
    assert reject_title("Sony A7 IV", "Kit de lentes Sony A7IV ILCE-7M4") == "bundle_or_kit"
    assert reject_title("iPhone 15 Pro 256GB", "Apple iPhone 14 Pro 256GB") == "wrong_iphone_generation"
    assert reject_title("iPhone 15 Pro 256GB", "iPhone 15 Pro Max 256GB") == "iphone_pro_max_mismatch"
    assert reject_title("Pioneer DDJ-FLX10", "Pioneer DDJ-FLX10 4-Channel DJ Controller") is None
    assert reject_title("Shure SM7B", "Shure SM7B Cardioid Dynamic Vocal Microphone") is None


def test_browse_filter_price_band() -> None:
    assert "price:[80..2500]" in browse_filter()
    assert "priceCurrency:EUR" in browse_filter()
    assert "priceCurrency:GBP" in browse_filter(currency="GBP")
    assert "conditions:" in browse_filter()
    assert "buyingOptions:" in browse_filter()
    assert "FOR_PARTS_OR_NOT_WORKING" not in browse_filter()


def test_rejects_repair_lens_body_and_currency() -> None:
    from decimal import Decimal
    from app.sources.ebay_filters import reject_listing_fields

    assert reject_title("Sony A7 IV", "Sony A7 IV doesn't work shutter jammed") == "repair_or_parts"
    assert reject_title("Sony A7 IV", "Sony FE 24-70mm GM II Lens") == "lens_when_searching_body"
    assert reject_title("RTX 4070", "HP Omen 40L Desktop Gaming PC RTX 4070") == "not_desktop_gpu"
    assert (
        reject_listing_fields(
            "iPhone 15 Pro",
            title="Apple iPhone 15 Pro 256GB",
            currency="EUR",
            marketplace="EBAY_GB",
            asking_price=Decimal("400"),
            min_price=Decimal("220"),
            max_price=Decimal("1400"),
        )
        == "currency_mismatch"
    )


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
