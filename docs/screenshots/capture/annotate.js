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

  // -- masking identifiers from a live account --------------------------------
  //
  // A capture normally runs against a mock and nothing needs hiding. Three
  // plugins hard-code their vendor's host, so their sets can only be captured
  // against a real account, and the pages then carry that account's station
  // names and codes — a country's whole roster, published in the docs. These
  // rewrite those strings just before the shot, the way a `fill` step already
  // overwrites a password field.
  //
  // For identifiers only. Never use either to change a status, a count, a
  // reading, or what a message means: capturing a real instance is worth doing
  // precisely because the screen is true, and a doctored verdict would make
  // every other shot untrustworthy too.

  // Renumber a set of labels — <option>s, table cells — from a template.
  // {n} is the 1-based position, {n5} the same zero-padded to five digits:
  //   maskLabels('#id_station option', 'Demo Station {n} (TA{n5})')
  // An <option> with an empty value is left alone, so a "---------" placeholder
  // survives.
  window.maskLabels = function (selector, template) {
    let n = 0;
    document.querySelectorAll(selector).forEach(function (el) {
      if (el.tagName === 'OPTION' && el.value === '') return;
      n += 1;
      el.textContent = template
        .replace(/\{n5\}/g, String(n).padStart(5, '0'))
        .replace(/\{n\}/g, String(n));
    });
  };

  // Rewrite text matching a regex, anywhere under `selector`. For prose that
  // quotes an identifier — a source-check message naming the upstream station.
  window.maskText = function (selector, pattern, replacement) {
    const root = document.querySelector(selector) || document.body;
    const re = new RegExp(pattern, 'g');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      node.nodeValue = node.nodeValue.replace(re, replacement);
    });
  };

  // Collapse <main> onto its content, for `capture: {selector: main}`.
  //
  // The admin stretches its scroll container to the viewport, so a page with
  // three rows on it crops to three rows plus 500px of nothing. There is no
  // element wrapping just the slim header and the listing — cropping to
  // #listing-results loses the page title, which is the context that says
  // which list the shot is of — so the container is made to fit instead.
  //
  // Opt-in from a manifest (`- eval: "fitMain()"`) rather than applied to every
  // shot: turning it on globally would redraw every image already captured.
  window.fitMain = function () {
    const main = document.querySelector('main');
    if (!main) return;
    for (const el of [main, main.firstElementChild]) {
      if (el) { el.style.height = 'auto'; el.style.minHeight = '0'; }
    }
  };
})();
