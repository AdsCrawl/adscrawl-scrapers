# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
import pytest
import chatgpt



@pytest.mark.asyncio
async def test_scrape_conversation():
    result = await chatgpt.scrape_conversation("What is the capital of France?")
    assert isinstance(result, str)
    assert len(result.strip()) > 0
