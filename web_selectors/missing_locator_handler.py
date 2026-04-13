"""
missing_locator_handler.py - Manual Fallback (Step H)
Injects a modal dialog in the browser.
User clicks target element → captures XPath from click event.
"""
import logging
import asyncio

logger = logging.getLogger(__name__)

CLICK_CAPTURE_JS = """
() => {
    return new Promise((resolve) => {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;cursor:crosshair;background:rgba(0,0,0,0.1);';
        
        // Create instruction banner
        const banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:1000000;background:#333;color:#fff;padding:15px 25px;border-radius:8px;font-family:sans-serif;font-size:16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
        banner.textContent = '🎯 Click on the element you want to locate';
        document.body.appendChild(banner);
        
        // Hover highlighting
        let lastHighlighted = null;
        overlay.addEventListener('mousemove', (e) => {
            overlay.style.pointerEvents = 'none';
            const el = document.elementFromPoint(e.clientX, e.clientY);
            overlay.style.pointerEvents = 'auto';
            
            if (lastHighlighted) {
                lastHighlighted.style.outline = lastHighlighted._origOutline || '';
            }
            if (el && el !== overlay && el !== banner) {
                el._origOutline = el.style.outline;
                el.style.outline = '2px solid #00ff00';
                lastHighlighted = el;
            }
        });
        
        overlay.addEventListener('click', (e) => {
            overlay.style.pointerEvents = 'none';
            const el = document.elementFromPoint(e.clientX, e.clientY);
            overlay.style.pointerEvents = 'auto';
            
            if (lastHighlighted) {
                lastHighlighted.style.outline = lastHighlighted._origOutline || '';
            }
            overlay.remove();
            banner.remove();
            
            if (!el) {
                resolve({ xpath: '', error: 'No element found' });
                return;
            }
            
            // Build XPath
            function getXPath(element) {
                if (element.id) return `//*[@id="${element.id}"]`;
                const parts = [];
                let current = element;
                while (current && current.nodeType === 1) {
                    let index = 0;
                    let sib = current.previousSibling;
                    while (sib) {
                        if (sib.nodeType === 1 && sib.tagName === current.tagName) index++;
                        sib = sib.previousSibling;
                    }
                    const tag = current.tagName.toLowerCase();
                    parts.unshift(index > 0 ? `${tag}[${index+1}]` : tag);
                    current = current.parentNode;
                }
                return '/' + parts.join('/');
            }
            
            resolve({
                xpath: getXPath(el),
                tag: el.tagName.toLowerCase(),
                text: (el.textContent || '').trim().substring(0, 200),
                id: el.id || '',
                className: el.className || '',
            });
        });
        
        document.body.appendChild(overlay);
    });
}
"""


async def manual_locate(page, field_name: str, timeout: int = 30) -> dict:
    """
    Last resort: inject click-capture modal in browser.
    User clicks target element → captures XPath from click event.
    Returns: {xpath, tag, text, ...}
    """
    logger.info(f"Manual fallback: asking user to click '{field_name}'")

    try:
        result = await page.evaluate(CLICK_CAPTURE_JS)
        if result and result.get("xpath"):
            logger.info(f"Manual capture: {result['xpath']}")
            return {
                "xpath": result["xpath"],
                "frame_url": "",
                "frame_name": "",
                "confidence": "manual",
                "reasoning": f"Manually captured by user click for '{field_name}'",
                "match_count": 1,
            }
        else:
            return {"xpath": "", "confidence": "none", "error": "Manual capture failed"}
    except Exception as e:
        logger.error(f"Manual capture error: {e}")
        return {"xpath": "", "confidence": "none", "error": str(e)}
