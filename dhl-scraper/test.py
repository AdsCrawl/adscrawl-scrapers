# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
import pytest
from cerberus import Validator

import dhl

tracking_event_schema = {
    "timestamp": {"type": "string", "nullable": True},
    "status": {"type": "string", "nullable": True},
    "description": {"type": "string", "nullable": True},
    "location": {"type": "string", "nullable": True},
}

tracking_result_schema = {
    "classification": {"type": "string"},
    "tracking_number": {"type": "string"},
    "status": {"type": "string", "nullable": True},
    "events": {
        "type": "list",
        "minlength": 1,
        "schema": {"type": "dict", "schema": tracking_event_schema},
    },
    "estimated_delivery": {"type": "string", "nullable": True},
    "origin": {"type": "string", "nullable": True},
    "destination": {"type": "string", "nullable": True},
}


def _validate_or_raise(item, schema):
    validator = Validator(schema, allow_unknown=True)
    if not validator.validate(item):
        raise Exception({"item": item, "errors": validator.errors})


@pytest.mark.asyncio
async def test_scrape_tracking():
    result = await dhl.scrape_tracking("LBAA19526")
    assert result.get("classification") == "success", "No shipment returned; a current valid test tracking number is required"
    assert result.get("events"), "A passing tracking test must include real tracking events"
    _validate_or_raise(result, tracking_result_schema)

