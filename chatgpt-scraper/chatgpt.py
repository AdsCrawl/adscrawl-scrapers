# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for chatgpt.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

from loguru import logger as log
from parsel import Selector

from adscrawl_scrapers import Request, ScrapeError, ScraperClient, managed


CLIENT = ScraperClient()

BASE_CONFIG = {
    "countryCode": "US",
}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

# The 2026-11-03 live runs failed in two ways that share one action list.
# `button[data-composer-submit]` is not on every current composer, so the
# 15s wait timed out (browser action timeout). When that control was present,
# the scenario treated "submit button exists" as success. That is also the
# state before a prompt is sent, and the following markdown step keeps
# `css("main")` even when `<main>` is empty, so the test received a blank
# string. Fill the composer, click an enabled send control, and wait until
# the assistant message itself is non-empty.
COMPOSER_SELECTOR = "#prompt-textarea, textarea[name='prompt-textarea'], textarea#mobile-composer-prompt"
SEND_BUTTON_SELECTORS = (
    "button[data-testid='send-button']",
    "button[data-testid='composer-send-button']",
    "#composer-submit-button",
    "button[data-composer-submit]",
    "button[aria-label='Send prompt']",
    "button[aria-label='Send message']",
    "button[aria-label='Send']",
    "button.composer-submit-btn",
)
ASSISTANT_SELECTOR = "[data-message-author-role='assistant']"
USER_SELECTOR = "[data-message-author-role='user']"
COMPOSER_WAIT_MS = 30_000
ANSWER_WAIT_MS = 65_000
_PLACEHOLDER = re.compile(r"^(thinking|generating|hang tight)[.!…\s]*$", re.IGNORECASE)

# Playwright's `:visible` is resolved when the action runs. Tagging a node and
# clicking it later loses the mark if React redraws the composer.
COMPOSER_FILL_SELECTOR = ", ".join(f"{part.strip()}:visible" for part in COMPOSER_SELECTOR.split(","))
SEND_CLICK_SELECTOR = ", ".join(f"{selector}:visible" for selector in SEND_BUTTON_SELECTORS)
SEND_CLICK_TIMEOUT_MS = 20_000

_DISMISS_SCRIPT = """
const visible = (node) => {
  if (!node) return false;
  const style = getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
};
for (let attempt = 0; attempt < 4; attempt += 1) {
  const dialog = document.querySelector("[role='dialog'], #credentials-picker-container");
  const close = dialog && dialog.querySelector("#close, button[data-testid='close-button'], button[aria-label='Close']");
  if (!visible(close)) break;
  close.click();
  await new Promise((resolve) => setTimeout(resolve, 250));
}
"""

_WAIT_ANSWER_TEMPLATE = """
const prompt = __PROMPT_LITERAL__;
const visible = (node) => {
  if (!node) return false;
  const style = getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
};
const textOf = (node) => ((node && (node.innerText || node.textContent)) || "").replace(/\\s+/g, " ").trim();
const placeholder = (value) => /^(thinking|generating|hang tight)[.!…\\s]*$/i.test(value);
const deadline = Date.now() + 60000;
let previous = "";
let stableTicks = 0;
let answer = "";
while (Date.now() < deadline) {
  const promptPrefix = prompt.slice(0, Math.min(prompt.length, 80));
  const asked = [...document.querySelectorAll("__USER__, [data-testid*='conversation-turn']")].some((node) =>
    (node.textContent || "").replace(/\\s+/g, " ").includes(promptPrefix));
  const latest = textOf([...document.querySelectorAll("__ASSISTANT__")].filter(visible).at(-1));
  const stopping = [...document.querySelectorAll("button[data-testid='stop-button'], button[data-testid='composer-stop-button'], button[aria-label^='Stop']")].some(visible);
  if (asked && latest && !placeholder(latest) && !stopping && latest === previous) {
    stableTicks += 1;
    if (stableTicks >= 3) {
      answer = latest;
      break;
    }
  } else {
    stableTicks = 0;
  }
  previous = latest;
  await new Promise((resolve) => setTimeout(resolve, 400));
}
if (!answer) throw new Error("ChatGPT assistant answer was empty");
document.documentElement.setAttribute("data-adscrawl-answer", answer);
return answer;
"""

_READ_ANSWER_SCRIPT = """
const stored = document.documentElement.getAttribute("data-adscrawl-answer");
if (stored && stored.trim()) return stored.trim();
const visible = (node) => {
  if (!node) return false;
  const style = getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
};
const node = [...document.querySelectorAll("__ASSISTANT__")].filter(visible).at(-1);
return node ? (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim() : "";
"""


def conversation_url(prompt: str) -> str:
    return f"https://chatgpt.com/?prompt={quote_plus(prompt)}"


def conversation_country() -> str:
    """US unless ``ADSCRAWL_CHATGPT_COUNTRY`` names another route.

    The process-wide ``ADSCRAWL_DEFAULT_COUNTRY`` does not replace this site's
    explicit country. Set the ChatGPT variable to try another route while
    other scrapers stay on the US default.
    """
    chosen = os.environ.get("ADSCRAWL_CHATGPT_COUNTRY", "").strip()
    return chosen.upper() if chosen else BASE_CONFIG["countryCode"]


def drive_conversation_script(prompt: str) -> str:
    """Browser script that resolves only after a stable assistant answer."""
    return (
        _WAIT_ANSWER_TEMPLATE
        .replace("__PROMPT_LITERAL__", json.dumps(prompt), 1)
        .replace("__USER__", USER_SELECTOR, 1)
        .replace("__ASSISTANT__", ASSISTANT_SELECTOR, 1)
    )


def conversation_actions(prompt: str) -> list[dict]:
    return [
        {"type": "click", "selector": "#credentials-picker-container #close", "optional": True},
        {"type": "click", "selector": "button[data-testid='close-button']", "optional": True},
        {"type": "click", "selector": "[role='dialog'] button[aria-label='Close']", "optional": True},
        {"type": "waitForSelector", "selector": COMPOSER_SELECTOR, "timeoutMs": COMPOSER_WAIT_MS},
        {"type": "evaluate", "script": _DISMISS_SCRIPT, "timeoutMs": 5_000},
        {"type": "fill", "selector": COMPOSER_FILL_SELECTOR, "value": prompt, "timeoutMs": 15_000},
        {"type": "click", "selector": SEND_CLICK_SELECTOR, "timeoutMs": SEND_CLICK_TIMEOUT_MS},
        {"type": "evaluate", "script": drive_conversation_script(prompt), "timeoutMs": ANSWER_WAIT_MS},
    ]


def _usable_answer(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned or _PLACEHOLDER.match(cleaned):
        return ""
    return cleaned


def extract_assistant_answer(html: str) -> str:
    """Pull the assistant text from the page, including when `<main>` is empty.

    Markdown mode uses the first `<main>` whenever that element exists. An
    empty main is truthy, so the conversation nodes outside it disappear.
    """
    if not html or not html.strip():
        return ""
    selector = Selector(text=html)
    stored = _usable_answer(selector.css("[data-adscrawl-answer]::attr(data-adscrawl-answer)").get())
    if stored:
        return stored
    texts = []
    for node in selector.css(ASSISTANT_SELECTOR):
        # string(.) concatenates descendant text. Joining ::text with spaces
        # turns "<strong>Paris</strong>." into "Paris ."
        text = _usable_answer(node.xpath("string(.)").get() or "")
        if text:
            texts.append(text)
    return texts[-1] if texts else ""


def answer_from_response(javascript: object, html: str) -> str:
    return _usable_answer(javascript) or extract_assistant_answer(html)


@managed
async def scrape_conversation(prompt: str) -> str:
    url = conversation_url(prompt)
    log.info("scraping conversation for prompt: {}", prompt)
    response = await CLIENT.fetch(
        Request(
            url=url,
            contentMode="html",
            render=True,
            actions=conversation_actions(prompt),
            javascript=_READ_ANSWER_SCRIPT.replace("__ASSISTANT__", ASSISTANT_SELECTOR, 1),
            countryCode=conversation_country(),
        )
    )
    answer = answer_from_response(response.javascript, response.content)
    if not answer:
        raise ScrapeError("ChatGPT returned an empty answer", response=response, code="EMPTY_ANSWER")
    log.success("finished scraping ChatGPT for the prompt: {}", prompt)
    return answer
