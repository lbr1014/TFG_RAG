from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoAlertPresentException, NoSuchElementException
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


class PlaywrightElement:
    def __init__(self, page, locator):
        self.page = page
        self.locator = locator.first

    @property
    def text(self):
        return self.locator.inner_text(timeout=30_000)

    @property
    def tag_name(self):
        return self.locator.evaluate("element => element.tagName.toLowerCase()")

    def click(self):
        if self.tag_name == "option":
            self.locator.evaluate(
                """option => {
                    option.selected = true;
                    const select = option.closest('select');
                    if (select) {
                        select.value = option.value;
                        select.dispatchEvent(new Event('input', { bubbles: true }));
                        select.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }"""
            )
            return
        try:
            self.locator.click(timeout=30_000, force=True)
        except Exception:
            self.locator.evaluate("element => element.click()")

    def clear(self):
        self.locator.fill("", timeout=30_000)

    def send_keys(self, *values):
        text = "".join(str(value) for value in values)
        text = text.replace(Keys.ENTER, "\n").replace(Keys.RETURN, "\n")
        if text == Keys.DOWN:
            self.locator.press("ArrowDown", timeout=30_000)
        elif text in ("\n", "\r\n"):
            self.locator.press("Enter", timeout=30_000)
        else:
            self.locator.type(text, timeout=30_000)

    def get_attribute(self, name):
        return self.locator.get_attribute(name, timeout=30_000) or ""

    def is_selected(self):
        return self.locator.is_checked(timeout=30_000)

    def find_elements(self, by=By.ID, value=None):
        selector = _selector(by, value)
        locators = self.locator.locator(selector)
        return [PlaywrightElement(self.page, locators.nth(i)) for i in range(locators.count())]

    def find_elements_by_tag_name(self, tag_name):
        return self.find_elements(By.TAG_NAME, tag_name)


class PlaywrightDriver:
    def __init__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._page = self._browser.new_page(viewport={"width": 1440, "height": 1000})
        self._page.set_default_timeout(30_000)

    @property
    def title(self):
        return self._page.title()

    def implicitly_wait(self, seconds):
        self._page.set_default_timeout(int(seconds * 1000))

    def get(self, url):
        if url.startswith("https://www.google.com/chrome://newtab/"):
            url = url.removeprefix("https://www.google.com/chrome://newtab/")
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    def find_element(self, by=By.ID, value=None):
        return self._find(_selector(by, value))

    def find_element_by_id(self, value):
        return self._find(f"#{value}")

    def find_element_by_name(self, value):
        return self._find(f"[name='{value}']")

    def find_element_by_xpath(self, value):
        return self._find(f"xpath={value}")

    def find_element_by_link_text(self, value):
        return self._find(f"text={value}")

    def switch_to_alert(self):
        raise NoAlertPresentException()

    def quit(self):
        self._browser.close()
        self._playwright.stop()

    def _find(self, selector):
        locator = self._page.locator(selector)
        try:
            locator.first.wait_for(state="attached", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            raise NoSuchElementException(selector) from exc
        return PlaywrightElement(self._page, locator)


def create_driver():
    return PlaywrightDriver()


def _selector(by, value):
    if by == By.ID:
        return f"#{value}"
    if by == By.NAME:
        return f"[name='{value}']"
    if by == By.XPATH:
        return f"xpath={value}"
    if by == By.LINK_TEXT:
        return f"text={value}"
    if by == By.TAG_NAME:
        return value
    return value
