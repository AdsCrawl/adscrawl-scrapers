"""Offline checks for the ChatGPT conversation capture.

The 2026-11-03 live runs timed out waiting for `button[data-composer-submit]`
or returned an empty string. These tests lock the replacement: type the
prompt, submit through a current send control, and read the assistant message
even when `<main>` is empty. They do not call AdsCrawl.
"""
import json

import pytest
from markdownify import markdownify
from parsel import Selector

import chatgpt
from adscrawl_scrapers import Response, ScrapeError


PARIS_HTML = """
<main></main>
<article data-message-author-role="user"><p>What is the capital of France?</p></article>
<article data-message-author-role="assistant"><p>The capital of France is <strong>Paris</strong>.</p></article>
"""


def test_empty_main_markdown_drops_the_assistant_answer():
    root = Selector(PARIS_HTML).css("main").get() or PARIS_HTML
    assert root.strip().startswith("<main")
    assert "Paris" not in markdownify(root, heading_style="ATX")
    assert chatgpt.extract_assistant_answer(PARIS_HTML) == "The capital of France is Paris."


def test_extract_prefers_the_stable_answer_attribute_and_skips_placeholders():
    html = """
    <html data-adscrawl-answer="The capital of France is Paris.">
      <div data-message-author-role="assistant">Thinking</div>
    </html>
    """
    assert chatgpt.extract_assistant_answer(html) == "The capital of France is Paris."
    thinking_only = "<div data-message-author-role='assistant'>Thinking...</div>"
    assert chatgpt.extract_assistant_answer(thinking_only) == ""
    assert chatgpt.extract_assistant_answer("<main></main>") == ""
    assert chatgpt.extract_assistant_answer("") == ""


def test_extract_keeps_the_latest_real_assistant_turn():
    html = """
    <div data-message-author-role="assistant">Paris is the capital.</div>
    <div data-message-author-role="assistant">Generating</div>
    """
    assert chatgpt.extract_assistant_answer(html) == "Paris is the capital."


def test_actions_fill_the_prompt_and_wait_for_the_assistant_message():
    prompt = 'What is the capital of France? He said "Paris".'
    actions = chatgpt.conversation_actions(prompt)
    serialized = json.dumps(actions)
    assert "exit_success" not in serialized
    assert "div[aria-live='polite'] button:first-of-type" not in serialized
    assert actions[3]["type"] == "waitForSelector"
    assert actions[3]["timeoutMs"] == chatgpt.COMPOSER_WAIT_MS
    assert "prompt-textarea" in actions[3]["selector"]
    fill = next(action for action in actions if action["type"] == "fill")
    assert fill["value"] == prompt
    assert ":visible" in fill["selector"] and "prompt-textarea" in fill["selector"]
    wait = actions[-1]
    assert wait["type"] == "evaluate" and wait["timeoutMs"] == chatgpt.ANSWER_WAIT_MS
    assert json.dumps(prompt) in wait["script"]
    assert chatgpt.ASSISTANT_SELECTOR in wait["script"]
    assert chatgpt.USER_SELECTOR in wait["script"]
    assert "data-adscrawl-answer" in wait["script"]
    send = next(action for action in actions if action.get("type") == "click" and action.get("timeoutMs") == chatgpt.SEND_CLICK_TIMEOUT_MS)
    for selector in chatgpt.SEND_BUTTON_SELECTORS:
        assert selector in send["selector"]
    assert ":visible" in send["selector"]
    assert chatgpt.conversation_url(prompt).startswith("https://chatgpt.com/?prompt=")
    assert "Paris" in chatgpt.conversation_url(prompt)


def test_country_stays_us_unless_chatgpt_override_is_set(monkeypatch):
    monkeypatch.delenv("ADSCRAWL_CHATGPT_COUNTRY", raising=False)
    monkeypatch.setenv("ADSCRAWL_DEFAULT_COUNTRY", "DE")
    assert chatgpt.conversation_country() == "US"
    monkeypatch.setenv("ADSCRAWL_CHATGPT_COUNTRY", " gb ")
    assert chatgpt.conversation_country() == "GB"


def test_prompt_with_quotes_stays_inside_a_javascript_string():
    prompt = 'say "hi"\nnext'
    script = chatgpt.drive_conversation_script(prompt)
    assert json.dumps(prompt) in script
    assert 'const prompt = "say "hi"' not in script


@pytest.mark.asyncio
async def test_scrape_conversation_reads_the_answer_when_main_is_empty(monkeypatch):
    seen = {}

    async def fetch(request):
        seen["request"] = request
        return Response(url=request.url, content="<main></main>", javascript="The capital of France is Paris.")

    monkeypatch.delenv("ADSCRAWL_CHATGPT_COUNTRY", raising=False)
    monkeypatch.setattr(chatgpt.CLIENT, "fetch", fetch)
    result = await chatgpt.scrape_conversation("What is the capital of France?")
    request = seen["request"]
    assert result == "The capital of France is Paris."
    assert request.countryCode == "US"
    assert request.render is True
    assert request.contentMode == "html"
    assert request.url == chatgpt.conversation_url("What is the capital of France?")
    assert "button[data-testid='send-button']" in json.dumps(request.actions)
    assert "[data-message-author-role='assistant']" in request.javascript


@pytest.mark.asyncio
async def test_scrape_conversation_uses_html_when_the_script_result_is_blank(monkeypatch):
    async def fetch(request):
        return Response(url=request.url, content=PARIS_HTML, javascript="   ")

    monkeypatch.setattr(chatgpt.CLIENT, "fetch", fetch)
    assert await chatgpt.scrape_conversation("What is the capital of France?") == "The capital of France is Paris."


@pytest.mark.asyncio
async def test_scrape_conversation_rejects_an_empty_page(monkeypatch):
    async def fetch(request):
        return Response(url=request.url, content="<main></main>", javascript="Thinking")

    monkeypatch.setattr(chatgpt.CLIENT, "fetch", fetch)
    with pytest.raises(ScrapeError) as caught:
        await chatgpt.scrape_conversation("What is the capital of France?")
    assert caught.value.code == "EMPTY_ANSWER"
    assert "EMPTY_ANSWER" in str(caught.value)
