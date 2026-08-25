"""Reduce eBay seller identity persistence without dropping fraud-useful aggregates."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from app.privacy.identifiers import identifier_hash

if TYPE_CHECKING:
    from app.sources.base import NormalizedListing

EBAY_SOURCE_ID = "ebay_browse"

_USERNAME_KEYS = {"username", "userName", "user_name", "sellerId", "userId", "userid", "eiasToken", "eias_token"}


def strip_seller_pii(obj: Any) -> Any:
    """Drop username/userId/eiasToken keys; keep feedback score/percentage."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in _USERNAME_KEYS or key.lower() in {"username", "userid", "eiastoken", "eias_token"}:
                continue
            if key == "seller" and isinstance(value, dict):
                kept = {
                    inner_k: strip_seller_pii(inner_v)
                    for inner_k, inner_v in value.items()
                    if inner_k not in _USERNAME_KEYS
                    and inner_k.lower() not in {"username", "userid", "eiastoken"}
                }
                out[key] = kept
            else:
                out[key] = strip_seller_pii(value)
        return out
    if isinstance(obj, list):
        return [strip_seller_pii(item) for item in obj]
    return obj


def minimise_normalized_listing(item: NormalizedListing) -> NormalizedListing:
    """Hash seller identifiers, strip plaintext identity, keep feedback aggregates."""
    if item.source_id != EBAY_SOURCE_ID:
        return item
    extras = dict(item.extras or {})
    raw = item.raw if isinstance(item.raw, dict) else {}
    seller_obj = raw.get("seller") if isinstance(raw.get("seller"), dict) else {}
    username = item.seller or seller_obj.get("username")
    if username:
        extras["seller_username_hash"] = identifier_hash(str(username))
        extras["seller_present"] = True
    user_id = seller_obj.get("userId") or seller_obj.get("user_id")
    if user_id:
        extras["seller_user_id_hash"] = identifier_hash(str(user_id))
        extras["seller_present"] = True
    eias = seller_obj.get("eiasToken") or seller_obj.get("eias_token")
    if eias:
        extras["seller_eias_hash"] = identifier_hash(str(eias))
        extras["seller_present"] = True
    extras.pop("username", None)
    extras.pop("seller_username", None)
    item.seller = None
    item.extras = extras
    item.raw = strip_seller_pii(deepcopy(item.raw or {}))
    return item


minimise_normalized_listing = minimise_normalized_listing
strip_seller_pii = strip_seller_pii
