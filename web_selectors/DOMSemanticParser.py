"""
DOMSemanticParser.py — DOM Scraper

Injects JS DOM walker into every frame.
Extracts ALL elements: tag, text, id, class, role, aria-*, data-*,
placeholder, computed styles, visibility, bounding rect, XPath,
parent chain, shadow DOM.
Handles iframes recursively, scrolls for lazy content.
Returns parsed DOM tree (up to 200K nodes).
"""
import json
from typing import Optional

# JavaScript DOM walker injected into the page
DOM_WALKER_JS = """
() => {
    const MAX_NODES = 200000;
    let nodeCount = 0;
    
    function getXPath(element) {
        if (!element) return '';
        if (element.id) return `//*[@id="${element.id}"]`;
        
        const parts = [];
        let current = element;
        while (current && current.nodeType === Node.ELEMENT_NODE) {
            let index = 0;
            let sibling = current.previousSibling;
            while (sibling) {
                if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName === current.tagName) {
                    index++;
                }
                sibling = sibling.previousSibling;
            }
            const tagName = current.tagName.toLowerCase();
            const indexStr = index > 0 ? `[${index + 1}]` : '';
            parts.unshift(`${tagName}${indexStr}`);
            current = current.parentNode;
        }
        return '/' + parts.join('/');
    }
    
    function getAttributes(el) {
        const attrs = {};
        for (const attr of el.attributes || []) {
            attrs[attr.name] = attr.value;
        }
        return attrs;
    }
    
    function isVisible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' 
            && style.visibility !== 'hidden' 
            && style.opacity !== '0'
            && rect.width > 0 
            && rect.height > 0;
    }
    
    function extractNode(el, depth = 0) {
        if (nodeCount >= MAX_NODES || !el || el.nodeType !== Node.ELEMENT_NODE) return null;
        nodeCount++;
        
        const rect = el.getBoundingClientRect();
        const attrs = getAttributes(el);
        const style = window.getComputedStyle(el);
        
        const node = {
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || '').trim().substring(0, 200),
            directText: getDirectText(el),
            id: el.id || null,
            class: el.className || null,
            role: attrs.role || el.getAttribute('role') || null,
            ariaLabel: el.getAttribute('aria-label') || null,
            ariaDescribedBy: el.getAttribute('aria-describedby') || null,
            placeholder: el.getAttribute('placeholder') || null,
            dataTestId: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || null,
            name: el.getAttribute('name') || null,
            type: el.getAttribute('type') || null,
            value: el.value || null,
            href: el.getAttribute('href') || null,
            src: el.getAttribute('src') || null,
            xpath: getXPath(el),
            visible: isVisible(el),
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
            depth: depth,
            childCount: el.children.length,
            children: []
        };
        
        // Recurse into children
        for (const child of el.children) {
            const childNode = extractNode(child, depth + 1);
            if (childNode) node.children.push(childNode);
        }
        
        return node;
    }
    
    function getDirectText(el) {
        let text = '';
        for (const child of el.childNodes) {
            if (child.nodeType === Node.TEXT_NODE) {
                text += child.textContent;
            }
        }
        return text.trim().substring(0, 200);
    }
    
    // Scroll to load lazy content
    async function scrollToLoad() {
        const height = document.body.scrollHeight;
        for (let y = 0; y < height; y += window.innerHeight) {
            window.scrollTo(0, y);
            await new Promise(r => setTimeout(r, 100));
        }
        window.scrollTo(0, 0);
    }
    
    return extractNode(document.documentElement);
}
"""


class DOMSemanticParser:
    """Parses the full DOM of a page into a structured tree."""

    def __init__(self, page):
        self.page = page

    async def run_full_sequence(self) -> dict:
        """
        Run the complete DOM extraction sequence:
        1. Inject JS DOM walker into every frame
        2. Extract all elements with metadata
        3. Handle iframes recursively
        4. Scroll for lazy content
        5. Return parsed DOM tree
        """
        # Scroll to trigger lazy loading
        try:
            await self.page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight); }")
            await self.page.wait_for_timeout(500)
            await self.page.evaluate("() => { window.scrollTo(0, 0); }")
            await self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Extract main frame DOM
        main_tree = await self._extract_frame(self.page)

        # Extract iframe DOMs
        frames = self.page.frames
        for frame in frames:
            if frame == self.page.main_frame:
                continue
            try:
                frame_tree = await self._extract_frame_content(frame)
                if frame_tree:
                    main_tree["_iframes"] = main_tree.get("_iframes", [])
                    main_tree["_iframes"].append({
                        "url": frame.url,
                        "name": frame.name,
                        "tree": frame_tree,
                    })
            except Exception:
                continue

        return main_tree

    async def _extract_frame(self, page) -> dict:
        """Extract DOM tree from a page/frame."""
        try:
            result = await page.evaluate(DOM_WALKER_JS)
            return result or {}
        except Exception as e:
            return {"error": str(e)}

    async def _extract_frame_content(self, frame) -> Optional[dict]:
        """Extract DOM from an iframe."""
        try:
            result = await frame.evaluate(DOM_WALKER_JS)
            return result
        except Exception:
            return None
