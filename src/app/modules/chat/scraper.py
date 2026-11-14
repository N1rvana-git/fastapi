"""Market-price scraper (optional capability).

Playwright is an optional dependency: importing it at module import time (as the
old code did) makes the whole API unimportable when the browser stack is not
installed.  It is imported lazily here and every failure degrades to a truthful
message instead of fabricated prices (the old fallback invented numbers).
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from src.app.core.logging import get_logger

logger = get_logger(__name__)


class ScraperUnavailable(RuntimeError):
    pass


async def search_market_price(item_name: str, *, timeout_seconds: float = 25.0) -> str:
    cleaned = item_name.strip()
    if not cleaned:
        raise ValueError("item_name must not be empty")
    try:
        return await asyncio.wait_for(_scrape(cleaned), timeout=timeout_seconds)
    except TimeoutError as exc:
        logger.warning("price scraper timed out", extra={"ctx_item": cleaned})
        raise ScraperUnavailable("全网比价超时，请稍后再试") from exc
    except ImportError as exc:
        raise ScraperUnavailable("当前部署未安装浏览器组件，暂不支持全网比价") from exc


async def _scrape(item_name: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise ImportError("playwright is not installed") from exc

    query = quote(f"{item_name} 二手 价格")
    url = f"https://www.sogou.com/web?query={query}"
    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(1500)
            text = " ".join((await page.locator("body").inner_text()).split())
            if len(text) < 100 or any(
                marker in text for marker in ("验证码", "异常访问", "If this persists")
            ):
                raise ScraperUnavailable("搜索引擎返回了反爬页面")
            logger.info("price scraped", extra={"ctx_item": item_name, "ctx_chars": len(text)})
            return text[:800]
    except ScraperUnavailable:
        raise
    except Exception as exc:
        logger.warning("price scrape failed: %s", exc)
        raise ScraperUnavailable("全网比价暂时不可用，请以平台内价格为准") from exc
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # pragma: no cover
                pass


__all__ = ["ScraperUnavailable", "search_market_price"]
