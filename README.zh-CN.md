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

**本次只复验了离线脚本**，没有 API Key，也没有消耗额度：
`python -m pytest tests -q`（49 项通过）与 `python scripts/check_catalog.py`（81 个站点模块）已通过。
在线烟雾测试和逐站用例 **没有重跑**。下面的 2026-10-27 数字是历史记录，不是本次新的通过结论。

上次全站实测是 **2026-10-27**（15 个整套通过、11 个部分通过、55 个未通过），本分支没有重复该次审计。
查看[逐站实测报告与截图](docs/live-verification/2026-10-27.md)及[JSON 记录](docs/live-verification/2026-10-27.json)。
空结果不算验证成功。`results/` 里的文件是历史示例，不是本次在线输出。

历史示例（本次未复测）：当时 Bing 返回 30 条搜索结果和 8 条关键词建议；ChatGPT 回答包含 Paris。

![ChatGPT 真实验证截图](docs/live-verification/evidence/chatgpt-answer.png)

<!-- LIVE_VERIFIED_START -->

2026-10-27 整套通过的站点（本次未重跑）：

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

默认 CI 只做离线验证。真实测试需手动触发并配置密钥，本次没有执行。
[初始验证记录](docs/VERIFICATION.md)和[2026-10-27 实测报告](docs/live-verification/2026-10-27.md)描述的是更早的运行。

```bash
python -m pytest tests -q
python scripts/check_catalog.py
# 以下命令会使用额度。未设置国家时 live_test 默认 US；站点自己的 countryCode 优先。
export ADSCRAWL_API_KEY="你的 API Key"
export ADSCRAWL_DEFAULT_COUNTRY=US
python scripts/smoke.py
SELECTED_SCRAPER=bing-scraper python scripts/live_test.py
python -m pytest bing-scraper/test.py -v --reruns=0
```

---

采用 [OSL-3.0](LICENSE) 许可证，相关声明见 [NOTICE](NOTICE)。
