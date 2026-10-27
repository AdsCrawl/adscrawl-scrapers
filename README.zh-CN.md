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

## 迁移方式

- 通过官方 SDK 创建和关闭 CDP 会话，Playwright 负责导航、点击、滚动和 XHR 捕获。
- POST/JSON 请求也在远程浏览器中执行；命名会话在同一次站点操作中保留 Cookie 和浏览器状态。
- 原站点的分页和解析逻辑保留，旧供应商专属开关已移除。
- Air France 使用同步 SDK；Google AI Mode 改为 AdsCrawl DOM 字段提取，可通过环境变量调整选择器。
- 所有新提交使用 `AdsCrawl <support@adscrawl.net>`。

## 验证状态

81 个站点已完成源码迁移，**尚未逐站验证真实网站的运行成功率**。
`results/` 是上游历史示例，不是本次 AdsCrawl 实测输出。
默认 CI 只做离线验证；真实测试需手动触发并配置密钥。
本次已通过 20 项离线测试、81 个模块检查，以及共享传输与 App Store 的有限实测。
详见[验证记录](docs/VERIFICATION.md)。

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
