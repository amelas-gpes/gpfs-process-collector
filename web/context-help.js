/* One transient hint for static and newly rendered controls. The browser continues to
 * own existing title tooltips on hover, including the SVG map's source details. */
(() => {
  "use strict";
  const controls = "button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [aria-description]";
  const tip = document.createElement("div");
  tip.id = "collector-context-help";
  tip.setAttribute("role", "tooltip");
  tip.setAttribute("popover", "manual");
  let anchor = null, pending = null, showTimer, hideTimer, keyboard = false;

  function controlAt(target) {
    const control = target?.closest?.(controls) || target?.closest?.("label")?.control;
    return control instanceof HTMLElement && !control.closest('[hidden], [inert], [aria-hidden=true]') ? control : null;
  }

  function message(control) {
    if (control.title) return control.title;
    if (control.hasAttribute("aria-description")) return control.getAttribute("aria-description");
    // Labels on icon buttons and the visible explanations beside settings switches
    // already describe these controls. Use the same wording as the interface.
    const label = control.labels?.[0];
    return label?.querySelector("small")?.textContent.trim()
      || control.getAttribute("aria-label") || "";
  }

  function hide() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    pending = null;
    if (!anchor) return;
    observer.disconnect();
    const ids = (anchor.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== tip.id);
    if (ids.length) anchor.setAttribute("aria-describedby", ids.join(" "));
    else anchor.removeAttribute("aria-describedby");
    tip.remove();
    anchor = null;
  }

  const observer = new MutationObserver(() => {
    if (!anchor?.isConnected || !anchor.getClientRects().length || message(anchor) !== tip.textContent) hide();
  });

  function show(control) {
    if (!control.isConnected || !control.getClientRects().length) return;
    const text = message(control);
    if (!text) return;
    anchor = control;
    const host = control.closest("dialog[open], [popover]") || document.body;
    tip.textContent = text;
    host.append(tip);
    tip.showPopover?.();
    const ids = [control.getAttribute("aria-describedby"), tip.id].filter(Boolean);
    control.setAttribute("aria-describedby", ids.join(" "));
    const box = control.getBoundingClientRect();
    const width = document.documentElement.clientWidth, height = document.documentElement.clientHeight;
    const tipWidth = tip.offsetWidth, tipHeight = tip.offsetHeight;
    let left = box.left + (box.width - tipWidth) / 2;
    let top = box.bottom + 4;
    if (top + tipHeight > height - 6) top = box.top - tipHeight - 4;
    // A hoverable hint over the next menu item would intercept the pointer as it moves there.
    const menu = control.closest(".session-menu, .transcript-export-options, .map-tool-panel, .report-index");
    if (menu) {
      const bounds = menu.getBoundingClientRect();
      const fitsRight = bounds.right + 4 + tipWidth <= width - 6;
      const fitsLeft = bounds.left - 4 - tipWidth >= 6;
      if (fitsRight || fitsLeft) {
        left = fitsRight ? bounds.right + 4 : bounds.left - tipWidth - 4;
        top = box.top + (box.height - tipHeight) / 2;
      } else if (bounds.bottom + 4 + tipHeight <= height - 6) {
        top = bounds.bottom + 4;
      } else if (bounds.top - 4 - tipHeight >= 6) {
        top = bounds.top - tipHeight - 4;
      }
    }
    tip.style.left = Math.max(6, Math.min(left, width - tipWidth - 6)) + "px";
    tip.style.top = Math.max(6, Math.min(top, height - tipHeight - 6)) + "px";
    observer.observe(document.body, {childList:true, subtree:true, attributes:true,
      attributeFilter:["hidden", "open", "title", "aria-description", "aria-label"]});
  }

  function offer(control, delay, nativeHover) {
    clearTimeout(hideTimer);
    if (anchor === control || (pending && pending === control)) return;
    hide();
    if (!control || (nativeHover && control.title) || !message(control)) return;
    pending = control;
    showTimer = setTimeout(() => {
      pending = null;
      const hovered = control.matches(":hover") || Array.from(control.labels || []).some(label => label.matches(":hover"));
      if (nativeHover ? hovered : control === document.activeElement) show(control);
    }, delay);
  }

  document.addEventListener("pointerover", event => {
    if (event.pointerType === "touch") return;
    if (tip.contains(event.target)) { clearTimeout(hideTimer); return; }
    const control = controlAt(event.target);
    if (control) offer(control, 430, true);
  });
  document.addEventListener("pointerout", event => {
    if (event.pointerType === "touch") return;
    const previous = controlAt(event.target), next = controlAt(event.relatedTarget);
    if ((next && previous === next) || tip.contains(event.relatedTarget)) return;
    if ((previous && (previous === anchor || previous === pending)) || tip.contains(event.target)) {
      clearTimeout(showTimer);
      pending = null;
      hideTimer = setTimeout(hide, 140);
    }
  });
  document.addEventListener("pointerdown", () => { keyboard = false; hide(); }, true);
  document.addEventListener("focusin", event => {
    if (keyboard) offer(controlAt(event.target), 350, false);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("input", hide);
  document.addEventListener("keydown", event => {
    if (event.key === "Tab" || event.key.startsWith("Arrow")) keyboard = true;
    if (event.key === "Escape" && anchor) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
    hide();
  }, true);
  document.addEventListener("scroll", () => { if (anchor) hide(); }, true);
  document.addEventListener("close", hide, true);
  window.addEventListener("resize", hide);
  window.addEventListener("blur", hide);
})();
