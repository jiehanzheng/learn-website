from __future__ import annotations

from typing import Dict, Tuple

from playwright.sync_api import Page, sync_playwright


class BrowserHarness:
    def __init__(self, headless: bool = False, viewport: Tuple[int, int] = (1440, 900)) -> None:
        self.headless = headless
        self.viewport = viewport
        self._playwright = None
        self._browser = None
        self._context = None
        self.page: Page | None = None

    def start(self) -> Page:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(viewport={"width": self.viewport[0], "height": self.viewport[1]})
        self.page = self._context.new_page()
        return self.page

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def screenshot(self) -> bytes:
        if not self.page:
            raise RuntimeError("Browser not started")
        return self.page.screenshot(full_page=False)

    def viewport_size(self) -> Dict[str, int]:
        if not self.page:
            raise RuntimeError("Browser not started")
        size = self.page.viewport_size
        if not size:
            return {"width": self.viewport[0], "height": self.viewport[1]}
        return {"width": size["width"], "height": size["height"]}
