# AdsCrawl Scrapers

由 AdsCrawl 维护的 Python 爬虫示例集，使用 [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python)，覆盖 81 个站点。
包含商品、搜索、评论、房产、航班等数据提取。完整目录见 [英文 README](README.md)。

## 安装与运行

需要 Python 3.10 或更新版本：

```bash
git clone https://github.com/AdsCrawl/adscrawl-scrapers.git
cd adscrawl-scrapers
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="你的 API Key"
export ADSCRAWL_DEFAULT_COUNTRY=US
cd amazon-scraper
python run.py
```

先修改 `run.py` 中的 URL、日期和页数。真实请求会消耗 AdsCrawl 额度。
默认每个客户端最多使用两个浏览器会话，可以通过 `ADSCRAWL_CONCURRENCY` 调整。
无需安装本地 Chromium；浏览器由 AdsCrawl 提供。

未指定国家或自定义代理时使用 **US 美国线路**。
`scripts/live_test.py` 在 `ADSCRAWL_DEFAULT_COUNTRY` 为空时设为 `US`，手动在线工作流也会设为 `US`。
自行设置该变量可改用其他线路。站点显式设置的 `countryCode` 优先。
自定义代理与国家路由不会同时发送。

## SDK 工作方式

- 通过官方 SDK 创建和关闭 CDP 会话，Playwright 负责导航、点击、滚动和 XHR 捕获。
- POST/JSON 请求也在远程浏览器中执行；命名会话在同一次站点操作中保留 Cookie 和浏览器状态。
- 每个站点包含独立的分页、解析逻辑和运行示例。
- Air France 使用同步 SDK；Google AI Mode 改为 AdsCrawl DOM 字段提取，可通过环境变量调整选择器。
- 所有新提交使用 `AdsCrawl <support@adscrawl.net>`。

## 验证状态

> 2026-11-03（Asia/Shanghai）用 PR #1 的验收脚本复测，默认美国线路，每轮不重试（`--reruns=0`），并发为 1。离线测试 47/47、目录检查 81/81 通过。在线烟雾测试通过（渲染后的 HTML、JSON POST、会话清理）。在线套件通过的是 **bing**（第二次 2/2，走代码里写死的英国线路）、**shopify**（5/5），以及提交 `3f7a7b4` 的 **chatgpt**（美国线路、未设置 `ADSCRAWL_CHATGPT_COUNTRY`，1/1，70.17 秒，退出码 0）。同一天更早的 ChatGPT 尝试没有通过：第一次复测 0/1（超时或空回答）；`ddd17ac` 先是 `ERR_TUNNEL_CONNECTION_FAILED` 再是 `ACTION_FAILED`；`ef4cc2b` 返回了导航和免责声明。其余站点本轮没有重测。上一次全站审计仍是 [2026-10-27 报告](docs/live-verification/2026-10-27.md)（15 个整套通过、11 个部分通过、55 个未通过）。这些结果只说明当天目标网站的表现。

2026-11-03 稍后的第一波在线修复没有开跑。这次 Cloud Agent 的进程环境和磁盘上都没有 `ADSCRAWL_API_KEY`，关联环境也没有完成过的构建，因此容器用的是默认镜像。`python3 scripts/smoke.py`（`ADSCRAWL_DEFAULT_COUNTRY=US`，`ADSCRAWL_CONCURRENCY=1`）退出码 2，错误码 `MISSING_API_KEY`，没有打开浏览器。名单里的 15 个站点都没有执行。这既不是通过，也不是失败，下面的在线通过表没有改动。说明见 [第一波受阻记录](docs/live-verification/2026-11-03-wave1.md)。同一检出的离线检查仍然通过：`pytest tests -q --reruns=0` 为 66 项通过，`check_catalog.py` 为 81/81。

`scripts/live_test.py` 在 `ADSCRAWL_DEFAULT_COUNTRY` 为空时设为 `US`。站点自己的 `countryCode` 会覆盖该默认值。Bing 的 `BASE_CONFIG` 写死 `countryCode` 为 `GB`，所以两次 Bing 都走英国线路，而不是这次的美国默认值。第一次 Bing 为 1 通过 / 1 失败（分页导航错误），第二次为 2/2。

| 本次复测（2026-11-03） | 结果 |
| --- | --- |
| `scripts/smoke.py` | 通过，退出码 0：渲染 HTML、JSON POST、会话清理 |
| [bing](bing-scraper/) | 第二次 2/2，内置英国线路。第一次 1/2，分页导航错误 |
| [shopify](shopify-scraper/) | 5/5 通过 |
| [chatgpt](chatgpt-scraper/) | 两轮都是 0/1：超时或空回答。未通过 |
| [chatgpt](chatgpt-scraper/) `ddd17ac` | 美国线路未通过。第一次 `ERR_TUNNEL_CONNECTION_FAILED`（约 15 秒）。第二次 `ACTION_FAILED`（约 83 秒）。回答提取没有跑到 |
| [chatgpt](chatgpt-scraper/) `2669477` | 未通过。美国访客页已经显示 “The capital of France is Paris.”，约 85 秒后 `ACTION_FAILED`，回答没有返回 |
| [chatgpt](chatgpt-scraper/) `ef4cc2b` | 未通过。约 35 秒后退出码 1。`scrape_conversation` 记录了成功，随后 `assert "Paris" in result` 失败。返回的是导航和免责声明，不是助手回答。没有 `ScrapeError` |
| [chatgpt](chatgpt-scraper/) `3f7a7b4` | 通过。美国线路，未设置 `ADSCRAWL_CHATGPT_COUNTRY`。`test_scrape_conversation` 通过，1 项用时 70.17 秒，退出码 0。没有 `EMPTY_ANSWER`、`ACTION_FAILED`、`TIMEOUT` 或 `ERR_*` |

本次设置：`ADSCRAWL_DEFAULT_COUNTRY=US`，`ADSCRAWL_CONCURRENCY=1`，`--reruns=0`。

随后在 2026-11-03 对提交 `ddd17ac` 做了美国线路复测，ChatGPT 仍未通过。`scripts/smoke.py` 仍然通过，普通站点可以打开。`chatgpt-scraper` 第一次约 15 秒、退出码 1，错误是 `ScrapeError` `ERR_TUNNEL_CONNECTION_FAILED`。第二次约 83 秒、退出码 1，错误是 `ScrapeError` `ACTION_FAILED`。直接打开 chatgpt.com 也会遇到同一隧道错误，或是没有聊天界面的空白页。没有出现 `EMPTY_ANSWER`。回答提取逻辑没有跑到，因此不能算在线验证通过。

提交 `2669477` 又在同一美国线路复测。chatgpt.com 打开了，访客页 `https://chatgpt.com/uc/...` 已经显示 “The capital of France is Paris.”。`SELECTED_SCRAPER=chatgpt-scraper` 仍在约 85 秒后以 `ACTION_FAILED` 退出，回答没有返回。之后的提取改动会读取已经出现在页面上的回复（包括没有 assistant 角色属性的 `/uc/` 页面）。

提交 `ef4cc2b` 在美国线路、未设置 `ADSCRAWL_CHATGPT_COUNTRY` 的情况下复测。约 35 秒后退出码 1。没有 `ERR_*`、`TIMEOUT` 或 `ACTION_FAILED`。`scrape_conversation` 记录了成功，断言 `assert "Paris" in result` 失败。返回内容只有界面文字：`ChatGPT is AI and can make mistakes. ChatGPT New chat Images Plugins See plans and pricing Help Deep research Settings`。因为是断言失败而不是 `ScrapeError`，没有新的 `artifacts/scrape-failures` 文件。这次提交之后的提取会拒绝这段导航和免责声明，并等到稳定的助手回答出现。

提交 `3f7a7b4` 在美国线路通过。`ADSCRAWL_DEFAULT_COUNTRY=US`，`ADSCRAWL_CONCURRENCY=1`，未设置 `ADSCRAWL_CHATGPT_COUNTRY`。`SELECTED_SCRAPER=chatgpt-scraper python scripts/live_test.py` 退出码 0。`chatgpt-scraper/test.py::test_scrape_conversation` 通过，1 项用时 70.17 秒。没有 `EMPTY_ANSWER`、`ACTION_FAILED`、`TIMEOUT` 或 `ERR_*`。

`results/` 是历史示例，不是这次复测的输出。
下面的截图来自 2026-10-27 审计。2026-11-03 的 ChatGPT 通过是上面的 `3f7a7b4` 在线测试，不是这张图。

![2026-10-27 审计中的 ChatGPT 回答](docs/live-verification/evidence/chatgpt-answer.png)

<!-- LIVE_VERIFIED_START -->

2026-10-27 整套通过的站点。2026-11-03 只重跑了 Bing、Shopify 和 ChatGPT，其余行仍是 2026-10-27 的结果。

| 爬虫 | 通过的实测用例 |
| --- | --- |
| [app-store](app-store-scraper/) | 2/2 |
| [bing](bing-scraper/) | 2/2 |
| [chatgpt](chatgpt-scraper/) | 1/1 |
| [fashionphile](fashionphile-scraper/) | 2/2 |
| [idealo](idealo-scraper/) | 4/4 |
| [imdb](imdb-scraper/) | 5/5 |
| [imovelweb](imovelweb-scraper/) | 2/2 |
| [reddit](reddit-scraper/) | 4/4 |
| [rightmove](rightmove-scraper/) | 2/2 |
| [shopify](shopify-scraper/) | 5/5 |
| [similarweb](similarweb-scraper/) | 4/4 |
| [ticketmaster](ticketmaster-scraper/) | 2/2 |
| [twitter](twitter-scraper/) | 2/2 |
| [vestiairecollective](vestiairecollective-scraper/) | 2/2 |
| [zillow](zillow-scraper/) | 2/2 |

[查看验证范围、输出数量和限制](docs/live-verification/2026-10-27.md)

<!-- LIVE_VERIFIED_END -->

默认 CI 只做离线验证。2026-11-03 的在线复测只覆盖烟雾测试、Bing、Shopify 和 ChatGPT，不是全站通过。提交 `ddd17ac` 当天又在美国线路复测了 ChatGPT：烟雾测试仍通过，ChatGPT 因 `ERR_TUNNEL_CONNECTION_FAILED`（约 15 秒）和 `ACTION_FAILED`（约 83 秒）失败。回答提取逻辑没有跑到。提交 `2669477` 的复测里，页面已经出现 Paris 回答，约 85 秒后仍是 `ACTION_FAILED`。提交 `ef4cc2b` 约 35 秒后返回了导航和免责声明（`scrape_conversation` 记为成功，`assert "Paris" in result` 失败，没有 `ScrapeError`）。提交 `3f7a7b4` 随后在美国线路、未设置 `ADSCRAWL_CHATGPT_COUNTRY` 的情况下通过：`test_scrape_conversation` 通过，1 项用时 70.17 秒，退出码 0。没有 `EMPTY_ANSWER`、`ACTION_FAILED`、`TIMEOUT` 或 `ERR_*`。
[初始验证记录](docs/VERIFICATION.md)和[2026-10-27 实测报告](docs/live-verification/2026-10-27.md)是更早的全站审计。

```bash
python -m pytest tests -q
python scripts/check_catalog.py
# 以下命令会使用额度。未设置国家时 live_test 默认 US；站点自己的 countryCode 优先。
# Bing 写死 GB，因此不会改走 US。
export ADSCRAWL_API_KEY="你的 API Key"
export ADSCRAWL_DEFAULT_COUNTRY=US
export ADSCRAWL_CONCURRENCY=1
python scripts/smoke.py
SELECTED_SCRAPER=bing-scraper python scripts/live_test.py
SELECTED_SCRAPER=shopify-scraper python scripts/live_test.py
SELECTED_SCRAPER=chatgpt-scraper python scripts/live_test.py
# 未设置 ADSCRAWL_CHATGPT_COUNTRY 时，ChatGPT 固定走 US，不受 ADSCRAWL_DEFAULT_COUNTRY 影响。
# 只改这一站的线路：export ADSCRAWL_CHATGPT_COUNTRY=GB
```

`ERR_*`、`TIMEOUT`、`ACTION_FAILED` 会把打码后的页面 URL、标题和截图写到 `artifacts/scrape-failures/`（已加入 gitignore）。Pytest 失败文本里会带上这三项。不要提交这个目录。

---

采用 [OSL-3.0](LICENSE) 许可证，相关声明见 [NOTICE](NOTICE)。
