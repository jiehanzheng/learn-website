from __future__ import annotations

from typing import Any, Dict, Optional

from playwright.sync_api import Page


_CAPTURE_SCRIPT = r"""
({ x, y }) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;

  function shortText(text, limit = 200) {
    if (!text) return "";
    const t = text.replace(/\s+/g, " ").trim();
    return t.length > limit ? t.slice(0, limit) + "…" : t;
  }

  function cssPath(node) {
    if (!(node instanceof Element)) return "";
    if (node.id) return `#${node.id}`;
    const parts = [];
    let current = node;
    while (current && current.nodeType === 1 && parts.length < 8) {
      const tag = current.tagName.toLowerCase();
      let selector = tag;
      if (current.classList && current.classList.length) {
        selector += "." + Array.from(current.classList).slice(0, 3).join(".");
      }
      parts.unshift(selector);
      current = current.parentElement;
    }
    return parts.join(" > ");
  }

  function nodeInfo(node) {
    const rect = node.getBoundingClientRect();
    const attrs = {};
    for (const attr of node.attributes) {
      attrs[attr.name] = attr.value;
    }
    return {
      tag: node.tagName.toLowerCase(),
      id: node.id || null,
      classes: Array.from(node.classList || []),
      text: shortText(node.innerText || node.textContent || ""),
      attributes: attrs,
      ariaLabel: node.getAttribute("aria-label"),
      role: node.getAttribute("role"),
      href: node.getAttribute("href"),
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
      selector: cssPath(node),
    };
  }

  const ancestors = [];
  let current = el;
  while (current && current.nodeType === 1) {
    ancestors.push(nodeInfo(current));
    if (current === document.documentElement) break;
    current = current.parentElement;
  }

  return {
    ...nodeInfo(el),
    ancestors,
  };
}
"""


def capture_element_at(page: Page, x: float, y: float) -> Optional[Dict[str, Any]]:
    return page.evaluate(_CAPTURE_SCRIPT, {"x": x, "y": y})
