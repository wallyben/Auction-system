"""NI plates stay unproven, and owner labels do not call a pre-tax ceiling safe."""

from app.domains.vehicles.enums import ProvenanceState, RegistrationSignal
from app.domains.vehicles.evidence import EvidenceLedger
from app.domains.vehicles.identity import registration_signal
from app.domains.vehicles.owner_view import owner_status, plain_provenance
from app.domains.vehicles.provenance import ProvenanceInput, assess_provenance


def test_ni_looking_plates_need_documents() -> None:
    for plate in ("UGZ 3040", "SGZ 3284", "WHZ 9432", "OGZ 2913", "TRZ 9507"):
        assert registration_signal(plate) is RegistrationSignal.NI_FORMAT_WEAK
        result = assess_provenance(
            ProvenanceInput(registration_signal=RegistrationSignal.NI_FORMAT_WEAK, auction_country="NI"),
            EvidenceLedger(),
        )
        assert result.state is ProvenanceState.LIKELY_NI_NEEDS_DOCUMENTS
        assert result.customs_clear is False
        assert plain_provenance(result.state.value) == "NI history possible — documents needed"


def test_tax_diligence_is_not_market_ready() -> None:
    assert owner_status({"prebid_group": "ECONOMICALLY_INTERESTING_TAX_DILIGENCE", "buy_ready": False}) == "TAX DILIGENCE"
    assert owner_status({"prebid_group": "REJECT_WRITE_OFF_CAT_S"}) == "HARD REJECT"
    assert owner_status({"prebid_group": "MARKET_INSUFFICIENT"}) == "MARKET INSUFFICIENT"
