"""
playwright_handlers_local.py - Tool Handlers (Local Version)
Replaces Selenium Grid + CDP with direct Playwright.

Each tool function:
1. Resolve correct frame (main page or iframe)
2. Create Playwright Locator from XPath
3. Execute .click() / .fill() / .is_visible() etc.
4. Take base64 screenshot after action
5. Return {status, featurestep, screenshot, arguments}
"""
import base64
import asyncio
import logging
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from web_selectors.web_selectors import get_selector

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """Holds browser state for a test run."""
    browser: Browser = None
    context: BrowserContext = None
    page: Page = None
    run_id: str = ""
    screenshots: list = field(default_factory=list)
    _playwright: object = None


# Active sessions by run_id
_sessions: dict[str, BrowserSession] = {}


async def get_or_create_session(run_id: str) -> BrowserSession:
    """Get existing session or return empty one."""
    if run_id in _sessions:
        return _sessions[run_id]
    session = BrowserSession(run_id=run_id)
    _sessions[run_id] = session
    return session


async def _take_screenshot(page: Page) -> str:
    """Take screenshot and return base64."""
    try:
        buf = await page.screenshot(full_page=False)
        return base64.b64encode(buf).decode('utf-8')
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
        return ""


async def _resolve_frame(page: Page, frame_url: str = "", frame_name: str = ""):
    """Resolve the correct frame (main or iframe)."""
    if not frame_url and not frame_name:
        return page
    for frame in page.frames:
        if frame_url and frame.url and frame_url in frame.url:
            return frame
        if frame_name and frame.name == frame_name:
            return frame
    return page


# ── Tool Handlers ──

async def launch_browser(args: dict, config: dict) -> dict:
    """
    Launch browser (direct Playwright, no Selenium Grid).
    1. Create browser + context + page
    2. Navigate to URL
    3. Store in BrowserSession
    """
    run_id = args.get("run_id", "default")
    url = args.get("url", "")

    try:
        pw = await async_playwright().__aenter__()
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized", "--window-position=0,0"]
        )
        context = await browser.new_context(
            no_viewport=True,
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        session = await get_or_create_session(run_id)
        session.browser = browser
        session.context = context
        session.page = page
        session._playwright = pw

        screenshot = await _take_screenshot(page)

        return {
            "status": "success",
            "featurestep": f'Given I navigate to "{url}"',
            "screenshot": screenshot,
            "arguments": args,
        }
    except Exception as e:
        logger.error(f"launch_browser failed: {e}")
        return {"status": "failed", "featurestep": f'FAILED: navigate to "{url}"', "error": str(e)}


async def navigate_to_url(args: dict, config: dict) -> dict:
    """Navigate to a new URL."""
    run_id = args.get("run_id", "default")
    url = args.get("url", "")
    session = await get_or_create_session(run_id)

    try:
        await session.page.goto(url, wait_until="networkidle", timeout=30000)
        screenshot = await _take_screenshot(session.page)
        return {
            "status": "success",
            "featurestep": f'And I navigate to "{url}"',
            "screenshot": screenshot,
        }
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: navigate to "{url}"', "error": str(e)}


async def click(args: dict, config: dict) -> dict:
    """
    Click on an element.
    1. get_or_create_session
    2. get_selector(page, field_name, field_type, action) → PHASE 5
    3. Resolve frame
    4. page.locator(xpath).click()
    5. Screenshot → base64
    """
    run_id = args.get("run_id", "default")
    field_name = args.get("field_name", "")
    field_type = args.get("field_type", "element")
    session = await get_or_create_session(run_id)

    try:
        locator_info = await get_selector(
            session.page, field_name, field_type, "click", config
        )
        xpath = locator_info.get("xpath", "")
        if not xpath:
            return {"status": "failed", "featurestep": f'FAILED: click on "{field_name}" - no locator found'}

        frame = await _resolve_frame(
            session.page,
            locator_info.get("frame_url", ""),
            locator_info.get("frame_name", "")
        )

        await frame.locator(f"xpath={xpath}").first.click(timeout=10000)
        await asyncio.sleep(1)  # Wait for UI reaction
        screenshot = await _take_screenshot(session.page)

        return {
            "status": "success",
            "featurestep": f'When I click on "{field_name}"',
            "screenshot": screenshot,
            "xpath": xpath,
        }
    except Exception as e:
        logger.error(f"click failed for '{field_name}': {e}")
        return {"status": "failed", "featurestep": f'FAILED: click on "{field_name}"', "error": str(e)}


async def enter_text(args: dict, config: dict) -> dict:
    """Enter text into an input field."""
    run_id = args.get("run_id", "default")
    field_name = args.get("field_name", "")
    text = args.get("textToEnter", "")
    session = await get_or_create_session(run_id)

    try:
        locator_info = await get_selector(
            session.page, field_name, "input", "type", config
        )
        xpath = locator_info.get("xpath", "")
        if not xpath:
            return {"status": "failed", "featurestep": f'FAILED: enter "{text}" in "{field_name}" - no locator'}

        frame = await _resolve_frame(session.page, locator_info.get("frame_url", ""), locator_info.get("frame_name", ""))
        await frame.locator(f"xpath={xpath}").first.fill(text, timeout=10000)
        await asyncio.sleep(0.5)
        screenshot = await _take_screenshot(session.page)

        return {
            "status": "success",
            "featurestep": f'When I enter "{text}" in "{field_name}"',
            "screenshot": screenshot,
        }
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: enter "{text}" in "{field_name}"', "error": str(e)}


async def select_dropdown(args: dict, config: dict) -> dict:
    """Select from dropdown."""
    run_id = args.get("run_id", "default")
    field_name = args.get("field_name", "")
    value = args.get("value", "")
    session = await get_or_create_session(run_id)

    try:
        locator_info = await get_selector(session.page, field_name, "select", "select", config)
        xpath = locator_info.get("xpath", "")
        frame = await _resolve_frame(session.page, locator_info.get("frame_url", ""), locator_info.get("frame_name", ""))
        await frame.locator(f"xpath={xpath}").first.select_option(value, timeout=10000)
        screenshot = await _take_screenshot(session.page)

        return {
            "status": "success",
            "featurestep": f'When I select "{value}" from "{field_name}"',
            "screenshot": screenshot,
        }
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: select "{value}" from "{field_name}"', "error": str(e)}


async def hover(args: dict, config: dict) -> dict:
    """Hover over an element."""
    run_id = args.get("run_id", "default")
    field_name = args.get("field_name", "")
    field_type = args.get("field_type", "element")
    session = await get_or_create_session(run_id)

    try:
        locator_info = await get_selector(session.page, field_name, field_type, "hover", config)
        xpath = locator_info.get("xpath", "")
        frame = await _resolve_frame(session.page, locator_info.get("frame_url", ""), locator_info.get("frame_name", ""))
        await frame.locator(f"xpath={xpath}").first.hover(timeout=10000)
        screenshot = await _take_screenshot(session.page)

        return {
            "status": "success",
            "featurestep": f'When I hover over "{field_name}"',
            "screenshot": screenshot,
        }
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: hover "{field_name}"', "error": str(e)}


async def assert_element_visible(args: dict, config: dict) -> dict:
    """Assert an element with specific text is visible."""
    run_id = args.get("run_id", "default")
    expected = args.get("expected_field_name", "")
    session = await get_or_create_session(run_id)

    try:
        locator_info = await get_selector(session.page, expected, "element", "assert", config)
        xpath = locator_info.get("xpath", "")
        frame = await _resolve_frame(session.page, locator_info.get("frame_url", ""), locator_info.get("frame_name", ""))

        is_visible = await frame.locator(f"xpath={xpath}").first.is_visible(timeout=10000)
        screenshot = await _take_screenshot(session.page)

        if is_visible:
            return {
                "status": "success",
                "featurestep": f'Then I should see "{expected}"',
                "screenshot": screenshot,
            }
        else:
            return {
                "status": "failed",
                "featurestep": f'FAILED: "{expected}" not visible',
                "screenshot": screenshot,
            }
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: assert "{expected}" visible', "error": str(e)}


async def scroll(args: dict, config: dict) -> dict:
    """Scroll the page."""
    run_id = args.get("run_id", "default")
    direction = args.get("direction", "down")
    pixels = args.get("pixels", 500)
    session = await get_or_create_session(run_id)

    try:
        delta = pixels if direction == "down" else -pixels
        await session.page.mouse.wheel(0, delta)
        await asyncio.sleep(0.5)
        screenshot = await _take_screenshot(session.page)
        return {"status": "success", "featurestep": f'And I scroll {direction} {pixels}px', "screenshot": screenshot}
    except Exception as e:
        return {"status": "failed", "featurestep": f'FAILED: scroll {direction}', "error": str(e)}


async def wait_action(args: dict, config: dict) -> dict:
    """Wait for specified duration."""
    seconds = args.get("seconds", 2)
    await asyncio.sleep(seconds)
    return {"status": "success", "featurestep": f'And I wait {seconds} seconds'}


async def take_screenshot(args: dict, config: dict) -> dict:
    """Take a screenshot."""
    run_id = args.get("run_id", "default")
    name = args.get("name", "screenshot")
    session = await get_or_create_session(run_id)
    screenshot = await _take_screenshot(session.page)
    return {"status": "success", "featurestep": f'And I take screenshot "{name}"', "screenshot": screenshot}


async def close_browser(args: dict, config: dict) -> dict:
    """Close the browser and cleanup."""
    run_id = args.get("run_id", "default")
    session = _sessions.get(run_id)

    if session:
        try:
            if session.context:
                await session.context.close()
            if session.browser:
                await session.browser.close()
            if session._playwright:
                await session._playwright.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        del _sessions[run_id]

    return {"status": "success", "featurestep": "And I close the browser"}


# Tool registry
TOOL_HANDLERS = {
    "launch_browser": launch_browser,
    "navigate_to_url": navigate_to_url,
    "click": click,
    "enter_text": enter_text,
    "select_dropdown": select_dropdown,
    "hover": hover,
    "assert_element_visible": assert_element_visible,
    "scroll": scroll,
    "wait": wait_action,
    "take_screenshot": take_screenshot,
    "close_browser": close_browser,
}


async def execute_tool(tool_name: str, args: dict, config: dict) -> dict:
    """Execute a tool by name."""
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {"status": "failed", "error": f"Unknown tool: {tool_name}"}
    return await handler(args, config)
