// Annotation helpers injected before every manifest entry's own JavaScript.
// Images must stay text-free (the docs are translated), so there are only
// two helpers: an outline and a numbered badge that a numbered list in the
// doc body refers to. Change the style here and every screenshot follows.
(function () {
  const COLOUR = '#d7263d';

  function el(selector) {
    const node = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!node) console.warn('[annotate] no element for', selector);
    return node;
  }

  window.highlight = function (selector, options) {
    const node = el(selector);
    if (!node) return;
    const pad = (options && options.padding) || 4;
    const rect = node.getBoundingClientRect();
    const box = document.createElement('div');
    box.className = 'adl-annotation';
    Object.assign(box.style, {
      position: 'absolute',
      left: (rect.left + window.scrollX - pad) + 'px',
      top: (rect.top + window.scrollY - pad) + 'px',
      width: (rect.width + pad * 2) + 'px',
      height: (rect.height + pad * 2) + 'px',
      border: '3px solid ' + COLOUR,
      borderRadius: '6px',
      boxSizing: 'border-box',
      pointerEvents: 'none',
      zIndex: 99999,
    });
    document.body.appendChild(box);
  };

  window.badge = function (selector, n, options) {
    const node = el(selector);
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const size = 26;
    const b = document.createElement('div');
    b.className = 'adl-annotation';
    b.textContent = String(n);
    const side = (options && options.side) || 'left';
    const left = side === 'right' ? rect.right + window.scrollX + 6 : rect.left + window.scrollX - size - 6;
    Object.assign(b.style, {
      position: 'absolute',
      left: Math.max(left, 0) + 'px',
      top: (rect.top + window.scrollY + rect.height / 2 - size / 2) + 'px',
      width: size + 'px',
      height: size + 'px',
      lineHeight: size + 'px',
      textAlign: 'center',
      borderRadius: '50%',
      background: COLOUR,
      color: '#fff',
      font: 'bold 14px/26px system-ui, sans-serif',
      boxShadow: '0 1px 3px rgba(0,0,0,.4)',
      pointerEvents: 'none',
      zIndex: 99999,
    });
    document.body.appendChild(b);
  };

  // Hide the sticky Wagtail sidebar's hover states and any toast so shots are stable
  window.settle = function () {
    document.querySelectorAll('.messages').forEach(m => m.remove());
  };
})();
