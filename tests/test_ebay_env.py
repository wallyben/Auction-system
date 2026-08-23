from app.core.config import Settings


def test_sbx_client_id_selects_sandbox_hosts() -> None:
    s = Settings(ebay_client_id="Example-ARIE-SBX-000", ebay_client_secret="SBX-hidden", ebay_env="production")
    assert s.ebay_api_env == "sandbox"
    assert s.ebay_env == "production"


def test_production_keys_stay_on_production() -> None:
    s = Settings(ebay_client_id="Example-ARIE-PRD-000", ebay_client_secret="PRD-hidden", ebay_env="production")
    assert s.ebay_api_env == "production"
