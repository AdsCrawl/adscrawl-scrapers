# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
import json
import os
from pathlib import Path
from cerberus import Validator as _Validator
import pytest

import amazon
import pprint

pp = pprint.PrettyPrinter(indent=4)



class Validator(_Validator):
    def _validate_min_presence(self, min_presence, field, value):
        pass  # required for adding non-standard keys to schema

def require_min_presence(items, key, min_perc=0.1, count_null=False):
    """check whether dataset contains items with some amount of non-null values for a given key.

    count_null is for a nullable field Amazon can omit. An explicit null counts.
    An empty string does not: that is the style value the PS5 and MacBook pages
    returned before it was normalized.
    """
    def present(item):
        value = item.get(key)
        if value:
            return True
        return bool(count_null and key in item and item[key] is None)

    count = sum(1 for item in items if present(item))
    if count < len(items) * min_perc:
        pytest.fail(
            f'inadequate presence of "{key}" field in dataset, only {count} out of {len(items)} items have it (expected {min_perc*100}%)'
        )


def validate_or_fail(item, validator):
    if not validator.validate(item):
        pp.pformat(item)
        pytest.fail(f"Validation failed for item: {pp.pformat(item)}\nErrors: {validator.errors}")


@pytest.mark.asyncio
async def test_product_scraping():
    # One product at a time. Gathering four URLs on the 2026-11-03 US retest
    # timed out Atomic Habits (0735211299) and the fabric multipack
    # (B01GCLS32M, which also fans out into many variants). These two finished
    # on the first attempt in that run. Schema checks below are unchanged.
    urls = [
        "https://www.amazon.com/PlayStation%C2%AE5-console-slim-PlayStation-5/dp/B0CL61F39H",
        "https://www.amazon.com/Apple-2024-MacBook-13-inch-Laptop/dp/B0CX22ZW1T",
    ]
    results = []
    for url in urls:
        results.extend(await amazon.scrape_product(url))
    schema = {
        "name": {"type": "string"},
        "asin": {"type": "string"},
        "description": {"type": "string", "min_presence": 0.01},
        "stars": {"type": "string"},
        "rating_count": {"type": "string"},
        "style": {"type": "string", "nullable": True},
        "features": {"type": "list", "schema": {"type": "string"}},
        "images": {"type": "list", "schema": {"type": "string", "regex": "https://.*media-amazon.com.*"}},
        "info_table": {"type": "dict"},
    }
    validator = Validator(schema, allow_unknown=True)
    for result in results:
        validate_or_fail(result, validator)
    for k in schema:
        nullable = bool(schema[k].get("nullable")) and "min_presence" not in schema[k]
        require_min_presence(
            results, k, min_perc=schema[k].get("min_presence", 0.1), count_null=nullable,
        )
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        (Path(__file__).parent / 'results/product.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))


@pytest.mark.asyncio
async def test_search_scraping():
    url = "https://www.amazon.com/s?k=kindle"
    result = await amazon.scrape_search(url, max_pages=3)
    assert len(result) > 30  # the number can vary as search parser skips ads
    schema = {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "price": {"type": "string", "nullable": True},
        "real_price": {"type": "string", "nullable": True, "min_presence": 0.1},
        "rating": {"type": "float", "nullable": True, "min_presence": 0.2},
        "rating_count": {"type": "integer", "nullable": True, "min_presence": 0.2},
    }
    validator = Validator(schema, allow_unknown=True)
    for product in result:
        validate_or_fail(product, validator)
    for k in schema:
        require_min_presence(result, k, min_perc=schema[k].get("min_presence", 0.1))
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        (Path(__file__).parent / 'results/search.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))



@pytest.mark.asyncio
async def test_review_scraping():
    # B0BCNKKZ91 and B0CL61F39H both 404 on /product-reviews/, and the PS5 product
    # page never rendered the review widget. Atomic Habits is a long-lived book
    # ASIN; scrape_reviews also tries the reviews ajax endpoint first.
    url = "https://www.amazon.com/Atomic-Habits-Proven-Build-Break/dp/0735211299"
    result = await amazon.scrape_reviews(url)
    assert len(result) != 0
    schema = {
        "text": {"type": "string"},
        "title": {"type": "string"},
        "location_and_date": {"type": "string"},
        "verified": {"type": "boolean"},
        "rating": {"type": "float"},
    }
    validator = Validator(schema, allow_unknown=True)
    for review in result:
        validate_or_fail(review, validator)
    for k in schema:
        require_min_presence(result, k, min_perc=schema[k].get("min_presence", 0.1))
    if os.getenv("SAVE_TEST_RESULTS") == "true":
        (Path(__file__).parent / 'results/reviews.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
