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
ANSWER_ATTRIBUTE = "[data-adscrawl-answer]"
COMPOSER_WAIT_MS = 15_000
ANSWER_WAIT_MS = 55_000
_PLACEHOLDER = re.compile(r"^(thinking|generating|hang tight)[.!…\s]*$", re.IGNORECASE)
# Composer chrome that follows a guest /uc/ reply. Cutting here keeps the
# sidebar (Log in, New chat), which is rendered before the answer, out of it.
# Phrases from the ef4cc2b US run, which returned this chrome instead of the
# reply: "ChatGPT is AI and can make mistakes. ChatGPT New chat Images ..."
_CHROME_PHRASES = (
    "ChatGPT is AI and can make mistakes",
    "can make mistakes",
    "New chat",
    "See plans and pricing",
    "Deep research",
    "Ask ChatGPT",
    "Message ChatGPT",
    "Sign up for free",
    "Get responses tailored to you",
)
_CHROME_WORDS = ("Images", "Plugins", "Settings", "Help")

# Playwright's `:visible` is resolved when the action runs. Tagging a node and
# clicking it later loses the mark if React redraws the composer.
COMPOSER_FILL_SELECTOR = ", ".join(f"{part.strip()}:visible" for part in COMPOSER_SELECTOR.split(","))

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

_CHROME_EDGES = (*_CHROME_WORDS, "ChatGPT")


def _chrome_split_pattern() -> str:
    # Split on the long labels only. Short menu words ("Help", "Settings")
    # stay inside a sentence such as "I can help" and are peeled off the
    # edges afterwards. Splitting them out of the live chrome string left
    # ". ChatGPT", which was then returned as the reply.
    phrases = [re.escape(part) for part in sorted(_CHROME_PHRASES, key=len, reverse=True)]
    return "(" + "|".join(phrases) + ")"


# Guest /uc/ replies are the assistant message, not the nav or the disclaimer.
# A stop control often never appears, so its absence is not a reason to read
# the sidebar instead.
_FIND_ANSWER_JS = r"""
function cleanText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}
function cleanPiece(value) {
  let text = cleanText(value);
  const edges = __CHROME_EDGES__;
  const edge = edges.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const leading = new RegExp("^[\\s.|:;,\u2013\u2014\\-·]*(?:" + edge + ")\\b[\\s.|:;,\u2013\u2014\\-·]*", "i");
  const trailing = new RegExp("[\\s.|:;,\u2013\u2014\\-·]*\\b(?:" + edge + ")[\\s.|:;,\u2013\u2014\\-·]*$", "i");
  let previous = "";
  while (text && text !== previous) {
    previous = text;
    text = text.replace(leading, "").replace(trailing, "").replace(/^[\s.|:;,\u2013\u2014\-·]+/, "").trim();
  }
  return text;
}
function isChrome(value) {
  const text = cleanText(value).toLowerCase();
  if (!text) return true;
  if (text.includes("can make mistakes")) return true;
  const words = text.match(/[a-z0-9]+/g) || [];
  if (words.length > 0 && words.every((word) => word === "chatgpt")) return true;
  const phrases = __CHROME_PHRASES__;
  const menu = __CHROME_WORDS__;
  let hits = 0;
  for (const phrase of phrases) {
    if (text.includes(phrase.toLowerCase())) hits += 1;
  }
  for (const word of menu) {
    if (new RegExp("\\b" + word.toLowerCase() + "\\b", "i").test(text)) hits += 1;
  }
  if (hits >= 2) return true;
  for (const phrase of phrases) {
    if (text === phrase.toLowerCase()) return true;
  }
  for (const word of menu) {
    if (text === word.toLowerCase()) return true;
  }
  return false;
}
function findAnswer(prompt) {
  const prefix = prompt.slice(0, Math.min(prompt.length, 80));
  const placeholder = (value) => /^(thinking|generating|hang tight)[.!…\s]*$/i.test(cleanText(value));
  const usable = (value) => {
    if (isChrome(value)) return "";
    const text = cleanPiece(value);
    if (!text || placeholder(text) || text === prefix || text.length < 3 || isChrome(text)) return "";
    return text;
  };
  const split = new RegExp(__CHROME_SPLIT__, "i");
  const fromAfter = (after) => {
    for (const piece of after.split(split)) {
      const text = usable(piece);
      if (text) return text;
    }
    return "";
  };
  const roleNodes = [...document.querySelectorAll("__ASSISTANT__")];
  for (let index = roleNodes.length - 1; index >= 0; index -= 1) {
    const text = fromAfter(roleNodes[index].innerText || roleNodes[index].textContent || "");
    if (text) return text;
  }
  const root = document.querySelector("main") || document.body;
  const body = cleanText(root && (root.innerText || root.textContent));
  let from = 0;
  while (from < body.length) {
    const at = body.indexOf(prefix, from);
    if (at < 0) break;
    let after = body.slice(at + prefix.length);
    const nextPrompt = after.indexOf(prefix);
    if (nextPrompt >= 0) after = after.slice(0, nextPrompt);
    const text = fromAfter(after);
    if (text) return text;
    from = at + Math.max(prefix.length, 1);
  }
  return "";
}
""".replace("__ASSISTANT__", ASSISTANT_SELECTOR).replace(
    "__CHROME_PHRASES__", json.dumps(list(_CHROME_PHRASES))
).replace(
    "__CHROME_WORDS__", json.dumps(list(_CHROME_WORDS))
).replace(
    "__CHROME_EDGES__", json.dumps(sorted(_CHROME_EDGES, key=len, reverse=True))
).replace(
    "__CHROME_SPLIT__", json.dumps(_chrome_split_pattern())
)

_MARK_TEMPLATE = r"""
// Capture an answer already on the page before clicking send.
const prompt = __PROMPT_LITERAL__;
__FIND_ANSWER__
const deadline = Date.now() + 40000;
let previous = "";
let ticks = 0;
while (Date.now() < deadline) {
  const answer = findAnswer(prompt);
  if (answer && answer === previous) {
    ticks += 1;
    if (ticks >= 2) {
      document.documentElement.setAttribute("data-adscrawl-answer", answer);
      return answer;
    }
  } else {
    ticks = 0;
  }
  previous = answer;
  await new Promise((resolve) => setTimeout(resolve, 400));
}
return "";
"""

_DRIVE_TEMPLATE = r"""
const prompt = __PROMPT_LITERAL__;
__FIND_ANSWER__
const visible = (node) => {
  if (!node) return false;
  const style = getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
};
function clickSend() {
  const selectors = __SEND_SELECTORS__;
  for (const selector of selectors) {
    const button = [...document.querySelectorAll(selector)].find((node) =>
      visible(node) && !node.disabled && node.getAttribute("aria-disabled") !== "true");
    if (button) {
      button.click();
      return true;
    }
  }
  return false;
}
const root = document.querySelector("main") || document.body;
const promptVisible = cleanText(root && (root.innerText || root.textContent)).includes(prompt.slice(0, Math.min(prompt.length, 80)));
// Do not submit again while a guest reply is still rendering.
if (!findAnswer(prompt) && !promptVisible) clickSend();
const deadline = Date.now() + 45000;
let previous = "";
let ticks = 0;
let answer = "";
while (Date.now() < deadline) {
  const latest = findAnswer(prompt);
  const stopping = [...document.querySelectorAll("button[data-testid='stop-button'], button[data-testid='composer-stop-button'], button[aria-label^='Stop']")].some(visible);
  if (latest && !stopping && latest === previous) {
    ticks += 1;
    if (ticks >= 2) {
      answer = latest;
      break;
    }
  } else {
    ticks = 0;
  }
  previous = latest;
  await new Promise((resolve) => setTimeout(resolve, 400));
}
if (!answer) throw new Error("ChatGPT assistant answer was empty");
document.documentElement.setAttribute("data-adscrawl-answer", answer);
return answer;
"""

_READ_TEMPLATE = r"""
__FIND_ANSWER__
const stored = document.documentElement.getAttribute("data-adscrawl-answer");
const prompt = __PROMPT_LITERAL__;
if (stored && !isChrome(stored)) return stored.trim();
return findAnswer(prompt) || "";
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


def _script(template: str, prompt: str) -> str:
    return (
        template
        .replace("__PROMPT_LITERAL__", json.dumps(prompt), 1)
        .replace("__FIND_ANSWER__", _FIND_ANSWER_JS, 1)
        .replace("__SEND_SELECTORS__", json.dumps(list(SEND_BUTTON_SELECTORS)), 1)
    )


def drive_conversation_script(prompt: str) -> str:
    """Browser script that resolves when a stable assistant answer is visible.

    A missing stop button is normal on a finished guest /uc/ reply. The send
    control is clicked only when that reply is not already on the page.
    """
    return _script(_DRIVE_TEMPLATE, prompt)


def conversation_actions(prompt: str) -> list[dict]:
    # The 2026-11-03 US retest of 2669477 already showed
    # "The capital of France is Paris." on /uc/... and then ACTION_FAILED.
    # Reading that reply has to happen before composer fill/click timeouts.
    return [
        {"type": "click", "selector": "#credentials-picker-container #close", "optional": True},
        {"type": "click", "selector": "button[data-testid='close-button']", "optional": True},
        {"type": "click", "selector": "[role='dialog'] button[aria-label='Close']", "optional": True},
        {"type": "evaluate", "script": _script(_MARK_TEMPLATE, prompt), "timeoutMs": 50_000},
        {
            "type": "condition",
            "selector": ANSWER_ATTRIBUTE,
            "state": "existing",
            "outcome": "exit_success",
        },
        {"type": "waitForSelector", "selector": COMPOSER_SELECTOR, "timeoutMs": COMPOSER_WAIT_MS, "optional": True},
        {"type": "evaluate", "script": _DISMISS_SCRIPT, "timeoutMs": 5_000, "optional": True},
        {"type": "fill", "selector": COMPOSER_FILL_SELECTOR, "value": prompt, "timeoutMs": 10_000, "optional": True},
        {"type": "evaluate", "script": drive_conversation_script(prompt), "timeoutMs": ANSWER_WAIT_MS},
    ]


def _spaced_html(html: str) -> str:
    """Put a space at block boundaries so ``Settings</p><p>Paris`` is not one word."""
    spaced = re.sub(r"(?i)<br\s*/?>", " ", html or "")
    return re.sub(
        r"(?i)</(p|div|li|tr|h[1-6]|section|article|button|nav|aside|footer|header|ul|ol|td|th|main)>",
        r" </\1>",
        spaced,
    )


def _block_text(html: str) -> str:
    return Selector(text=_spaced_html(html)).xpath("string(.)").get() or ""


def _usable_answer(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned or _PLACEHOLDER.match(cleaned):
        return ""
    return cleaned


def _is_chrome(value: str) -> bool:
    """Nav, disclaimer, and composer labels are not an assistant reply."""
    lowered = re.sub(r"\s+", " ", value or "").strip().lower()
    if not lowered:
        return True
    if "can make mistakes" in lowered:
        return True
    words = re.findall(r"[a-z0-9]+", lowered)
    if words and all(word == "chatgpt" for word in words):
        return True
    hits = 0
    for phrase in _CHROME_PHRASES:
        if phrase.lower() in lowered:
            hits += 1
    for word in _CHROME_WORDS:
        if re.search(rf"\b{re.escape(word.lower())}\b", lowered):
            hits += 1
    if hits >= 2:
        return True
    if any(lowered == phrase.lower() for phrase in _CHROME_PHRASES):
        return True
    return any(lowered == word.lower() for word in _CHROME_WORDS)


def _clean_piece(value: str) -> str:
    """Drop menu words and a leftover "ChatGPT" glued to either end."""
    text = re.sub(r"\s+", " ", value or "").strip()
    edge = "|".join(re.escape(word) for word in sorted(_CHROME_EDGES, key=len, reverse=True))
    leading = re.compile(rf"^[\s.·|:;,\-–—]*(?:{edge})\b[\s.·|:;,\-–—]*", re.IGNORECASE)
    trailing = re.compile(rf"[\s.·|:;,\-–—]*\b(?:{edge})[\s.·|:;,\-–—]*$", re.IGNORECASE)
    previous = None
    while text and text != previous:
        previous = text
        text = trailing.sub("", leading.sub("", text))
        text = re.sub(r"^[\s.·|:;,\-–—]+", "", text).strip()
    return text


def _reply_pieces(text: str) -> list[str]:
    return re.split(_chrome_split_pattern(), text, flags=re.IGNORECASE)


def _first_reply(text: str, prefix: str = "") -> str:
    for piece in _reply_pieces(text):
        # Classify the raw piece first. Edge-stripping "Ask ChatGPT" would
        # otherwise leave the word "Ask" and return that as the reply.
        if _is_chrome(piece):
            continue
        answer = _usable_answer(_clean_piece(piece))
        if answer and answer != prefix and len(answer) >= 3 and not _is_chrome(answer):
            return answer
    return ""


def extract_guest_reply(html: str, prompt: str) -> str:
    """Reply text on a guest /uc/ page that has no assistant role attribute.

    The search stays inside ``main`` when that element exists so the sidebar
    is not the reply. Chrome after the prompt is discarded, and a later
    sentence on the same page can still be the answer.
    """
    prefix = re.sub(r"\s+", " ", prompt or "").strip()[:80]
    if not html or not prefix:
        return ""
    selector = Selector(text=_spaced_html(html))
    mains = selector.xpath("//main")
    raw = " ".join(node.xpath("string(.)").get() or "" for node in mains) if mains else ""
    if not raw.strip():
        raw = selector.xpath("string(//body)").get() or selector.xpath("string(.)").get() or ""
    text = re.sub(r"\s+", " ", raw).strip()
    start = 0
    while start < len(text):
        at = text.find(prefix, start)
        if at < 0:
            return ""
        after = text[at + len(prefix):]
        next_prompt = after.find(prefix)
        if next_prompt >= 0:
            after = after[:next_prompt]
        answer = _first_reply(after, prefix)
        if answer:
            return answer
        start = at + max(len(prefix), 1)
    return ""


def extract_assistant_answer(html: str, prompt: str = "") -> str:
    """Pull the assistant text from the page, including when `<main>` is empty.

    Markdown mode uses the first `<main>` whenever that element exists. An
    empty main is truthy, so the conversation nodes outside it disappear.
    A guest /uc/ reply can also sit in plain text with no role attribute.
    """
    if not html or not html.strip():
        return ""
    selector = Selector(text=html)
    stored = _usable_answer(selector.css("[data-adscrawl-answer]::attr(data-adscrawl-answer)").get())
    if stored and not _is_chrome(stored):
        return stored
    texts = []
    for node in selector.css(ASSISTANT_SELECTOR):
        # string(.) concatenates descendant text. Joining ::text with spaces
        # turns "<strong>Paris</strong>." into "Paris ."
        # A guest turn can wrap the reply in the same text as the disclaimer.
        # Keep the sentence and drop the chrome around it.
        answer = _first_reply(_block_text(node.get() or ""))
        if answer:
            texts.append(answer)
    if texts:
        return texts[-1]
    return extract_guest_reply(html, prompt)


def answer_from_response(javascript: object, html: str, prompt: str = "") -> str:
    scripted = _usable_answer(javascript)
    if scripted and not _is_chrome(scripted):
        return scripted
    return extract_assistant_answer(html, prompt)


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
            javascript=_script(_READ_TEMPLATE, prompt),
            countryCode=conversation_country(),
        )
    )
    answer = answer_from_response(response.javascript, response.content, prompt)
    if not answer:
        raise ScrapeError("ChatGPT returned an empty answer", response=response, code="EMPTY_ANSWER")
    log.success("finished scraping ChatGPT for the prompt: {}", prompt)
    return answer
