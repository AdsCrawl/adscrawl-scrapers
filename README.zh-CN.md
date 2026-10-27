# AdsCrawl Scrapers

使用 [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python) 的 81 个站点爬虫示例。
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
cd amazon-scraper
python run.py
```

先修改 `run.py` 中的 URL、日期和页数。真实请求会消耗 AdsCrawl 额度。
默认每个客户端最多使用两个浏览器会话，可以通过 `ADSCRAWL_CONCURRENCY` 调整。
无需安装本地 Chromium；浏览器由 AdsCrawl 提供。

未指定国家或自定义代理时，默认使用 **US 美国线路**。
可以用 `ADSCRAWL_DEFAULT_COUNTRY` 修改默认值；站点显式设置的 `countryCode` 优先。
自定义代理与国家路由不会同时发送。

## 迁移方式

- 通过官方 SDK 创建和关闭 CDP 会话，Playwright 负责导航、点击、滚动和 XHR 捕获。
- POST/JSON 请求也在远程浏览器中执行；命名会话在同一次站点操作中保留 Cookie 和浏览器状态。
- 原站点的分页和解析逻辑保留，旧供应商专属开关已移除。
- Air France 使用同步 SDK；Google AI Mode 改为 AdsCrawl DOM 字段提取，可通过环境变量调整选择器。
- 所有新提交使用 `AdsCrawl <support@adscrawl.net>`。

## 验证状态

81 个站点已完成源码迁移，**正在逐站进行真实请求验证和修复**。
查看[逐站实测报告与截图](docs/live-verification/2026-10-27.md)及[JSON 记录](docs/live-verification/2026-10-27.json)。
通过、部分通过、失败和待测会分别标注；空结果不算验证成功。

已核验示例：Bing 返回 30 条搜索结果和 8 条关键词建议；ChatGPT 实测回答包含正确答案 Paris。

![ChatGPT 真实验证截图](docs/live-verification/evidence/chatgpt-answer.png)

<!-- LIVE_VERIFIED_START -->

本轮整套现有实测通过的站点（2026-10-27）：

| 爬虫 | 通过的实测用例 |
| --- | --- |
| [bing](bing-scraper/) | 2/2 |
| [chatgpt](chatgpt-scraper/) | 1/1 |
| [idealo](idealo-scraper/) | 4/4 |
| [imovelweb](imovelweb-scraper/) | 2/2 |
| [rightmove](rightmove-scraper/) | 2/2 |
| [shopify](shopify-scraper/) | 5/5 |
| [similarweb](similarweb-scraper/) | 4/4 |
| [ticketmaster](ticketmaster-scraper/) | 2/2 |
| [twitter](twitter-scraper/) | 2/2 |
| [vestiairecollective](vestiairecollective-scraper/) | 2/2 |
| [zillow](zillow-scraper/) | 2/2 |

[查看验证范围、输出数量和限制](docs/live-verification/2026-10-27.md)

<!-- LIVE_VERIFIED_END -->

`results/` 是上游历史示例，不是本次 AdsCrawl 实测输出。
默认 CI 只做离线验证；真实测试需手动触发并配置密钥。
初次迁移的离线与烟雾测试见[初始验证记录](docs/VERIFICATION.md)；
当前逐站结果以实测报告为准。

```bash
python -m pytest tests -q
python scripts/check_catalog.py
# 以下命令会使用额度：
python -m pytest amazon-scraper/test.py -v
```

## 来源与许可证

本项目改编自 [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers)，
保留来源、作者和历史样例。依据上游 NPOSL-3.0 第 17(d) 条，以 **OSL-3.0** 发布衍生作品。
使用、修改或再分发前请阅读 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
详见 [迁移说明](docs/MIGRATION.md)。
