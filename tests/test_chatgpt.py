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


GUEST_UC_HTML = """
<body>
  <nav><p>New chat</p><p>Log in</p><p>Sign up for free</p></nav>
  <div>What is the capital of France?</div>
  <div>The capital of France is Paris. 🇫🇷</div>
  <form><div id="prompt-textarea">Ask ChatGPT</div></form>
</body>
"""


LIVE_CHROME = (
    "ChatGPT is AI and can make mistakes. ChatGPT New chat Images Plugins "
    "See plans and pricing Help Deep research Settings"
)


def test_guest_uc_page_without_role_attributes_is_the_paris_reply():
    answer = chatgpt.extract_assistant_answer(GUEST_UC_HTML, "What is the capital of France?")
    assert answer == "The capital of France is Paris. 🇫🇷"
    assert "New chat" not in answer and "Log in" not in answer
    prompt_only = "<body><p>What is the capital of France?</p><div>Ask ChatGPT</div></body>"
    assert chatgpt.extract_assistant_answer(prompt_only, "What is the capital of France?") == ""


def test_live_chrome_is_not_returned_as_the_assistant_reply():
    prompt = "What is the capital of France?"
    assert chatgpt._is_chrome(LIVE_CHROME)
    chrome_only = f"<main><p>{prompt}</p><p>{LIVE_CHROME}</p></main>"
    assert chatgpt.extract_assistant_answer(chrome_only, prompt) == ""
    with_reply = (
        f"<main><p>{prompt}</p><p>{LIVE_CHROME}</p>"
        "<p>The capital of France is Paris.</p></main>"
    )
    assert chatgpt.extract_assistant_answer(with_reply, prompt) == "The capital of France is Paris."
    role_is_chrome = (
        f'<article data-message-author-role="assistant">{LIVE_CHROME}</article>'
        f"<main><p>{prompt}</p><p>The capital of France is Paris.</p></main>"
    )
    assert chatgpt.extract_assistant_answer(role_is_chrome, prompt) == "The capital of France is Paris."
    stored = f'<html data-adscrawl-answer="{LIVE_CHROME}">{with_reply}</html>'
    assert chatgpt.extract_assistant_answer(stored, prompt) == "The capital of France is Paris."
    mixed = (
        f'<article data-message-author-role="assistant">{LIVE_CHROME}'
        " The capital of France is Paris.</article>"
    )
    assert chatgpt.extract_assistant_answer(mixed, prompt) == "The capital of France is Paris."
    helpful = f"<main><p>{prompt}</p><p>I can help. The capital of France is Paris.</p></main>"
    assert chatgpt.extract_assistant_answer(helpful, prompt) == "I can help. The capital of France is Paris."


def test_actions_read_an_answer_already_on_the_page_before_send():
    prompt = 'What is the capital of France? He said "Paris".'
    actions = chatgpt.conversation_actions(prompt)
    serialized = json.dumps(actions)
    assert "div[aria-live='polite'] button:first-of-type" not in serialized
    exits = [action for action in actions if action.get("outcome") == "exit_success"]
    assert exits == [{
        "type": "condition",
        "selector": chatgpt.ANSWER_ATTRIBUTE,
        "state": "existing",
        "outcome": "exit_success",
    }]
    mark = next(action for action in actions if action["type"] == "evaluate" and "already on the page" in action["script"])
    fill = next(action for action in actions if action["type"] == "fill")
    assert actions.index(mark) < actions.index(exits[0]) < actions.index(fill)
    assert fill["value"] == prompt and fill.get("optional") is True
    composer = next(action for action in actions if action["type"] == "waitForSelector")
    assert composer.get("optional") is True and "prompt-textarea" in composer["selector"]
    assert not any(action["type"] == "click" and not action.get("optional") for action in actions)
    wait = actions[-1]
    assert wait["type"] == "evaluate" and wait["timeoutMs"] == chatgpt.ANSWER_WAIT_MS
    assert json.dumps(prompt) in wait["script"]
    assert chatgpt.ASSISTANT_SELECTOR in wait["script"]
    assert "isChrome" in wait["script"] and "can make mistakes" in wait["script"]
    assert "querySelector(\"main\")" in wait["script"]
    assert "still rendering" in wait["script"]
    assert "!stopping" in wait["script"]
    for selector in chatgpt.SEND_BUTTON_SELECTORS:
        assert selector in wait["script"]
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
async def test_scrape_conversation_ignores_chrome_and_reads_the_reply(monkeypatch):
    async def fetch(request):
        html = (
            "<main><p>What is the capital of France?</p>"
            f"<p>{LIVE_CHROME}</p><p>The capital of France is Paris.</p></main>"
        )
        return Response(url=request.url, content=html, javascript=LIVE_CHROME)

    monkeypatch.setattr(chatgpt.CLIENT, "fetch", fetch)
    assert await chatgpt.scrape_conversation("What is the capital of France?") == "The capital of France is Paris."


def test_find_answer_script_skips_live_chrome():
    import subprocess
    script = chatgpt._FIND_ANSWER_JS + r"""
const prompt = "What is the capital of France?";
const chrome = "ChatGPT is AI and can make mistakes. ChatGPT New chat Images Plugins See plans and pricing Help Deep research Settings";
const document = {
  querySelectorAll: () => [],
  querySelector: (selector) => selector === "main" ? { innerText: prompt + " " + chrome } : null,
  body: { innerText: "ignored" },
};
if (findAnswer(prompt) !== "") throw new Error("chrome accepted: " + JSON.stringify(findAnswer(prompt)));
document.querySelector = (selector) => selector === "main"
  ? { innerText: prompt + " " + chrome + " The capital of France is Paris." }
  : null;
const answer = findAnswer(prompt);
if (answer !== "The capital of France is Paris.") throw new Error("missing reply: " + JSON.stringify(answer));
document.querySelectorAll = () => [{ innerText: "The capital of France is Paris." }];
if (findAnswer(prompt) !== "The capital of France is Paris.") throw new Error("role node ignored");
"""
    subprocess.run(["node", "-e", script], check=True)


@pytest.mark.asyncio
async def test_scrape_conversation_rejects_an_empty_page(monkeypatch):
    async def fetch(request):
        return Response(url=request.url, content="<main></main>", javascript="Thinking")

    monkeypatch.setattr(chatgpt.CLIENT, "fetch", fetch)
    with pytest.raises(ScrapeError) as caught:
        await chatgpt.scrape_conversation("What is the capital of France?")
    assert caught.value.code == "EMPTY_ANSWER"
    assert "EMPTY_ANSWER" in str(caught.value)
