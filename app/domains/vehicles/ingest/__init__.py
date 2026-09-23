"""Commercial-vehicle ingestion package."""

from app.domains.vehicles.ingest.mid_ulster import PARSER_VERSION, SOURCE_ID, parse_catalogue

__all__ = ["PARSER_VERSION", "SOURCE_ID", "parse_catalogue"]
