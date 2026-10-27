/* AI shopping assistant chat widget. */
(function () {
  'use strict';

  const panel = document.getElementById('ai-panel');
  const launcher = document.getElementById('ai-launcher');
  if (!panel || !launcher) return;

  const log = document.getElementById('ai-log');
  const form = document.getElementById('ai-form');
  const input = document.getElementById('ai-input');
  const sendBtn = form.querySelector('button');
  const engine = document.getElementById('ai-engine');
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const OPEN_KEY = 'ai-open';
  let ready = null; // Promise for the chat history load.
  let busy = false;

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  // Minimal formatting: **bold**, "- " bullets and line breaks. Input is escaped first.
  function format(text) {
    const lines = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').split('\n');
    let html = '';
    let inList = false;
    for (const line of lines) {
      const bullet = line.match(/^\s*(?:[-•*]|\d+\.)\s+(.*)/);
      if (bullet) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += `<li>${bullet[1]}</li>`;
      } else {
        if (inList) { html += '</ul>'; inList = false; }
        html += line ? `${line}<br>` : '<br>';
      }
    }
    if (inList) html += '</ul>';
    return html.replace(/(<br>)+$/, '').replace(/^(<br>)+/, '');
  }

  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  function addMessage(role, text) {
    const bubble = document.createElement('div');
    bubble.className = `ai-msg ${role}`;
    bubble.innerHTML = format(text);
    log.appendChild(bubble);
    scrollDown();
    return bubble;
  }

  // Thumbs up/down under an assistant reply; stored with the conversation (and in MongoDB).
  function addFeedback(id, helpful) {
    if (!id || !panel.dataset.feedbackUrl) return;
    const wrap = document.createElement('div');
    wrap.className = 'ai-feedback';
    wrap.innerHTML = `<span>Helpful?</span>
      <button type="button" data-helpful="true" aria-label="Helpful"><i class="bi bi-hand-thumbs-up"></i></button>
      <button type="button" data-helpful="false" aria-label="Not helpful"><i class="bi bi-hand-thumbs-down"></i></button>`;
    const mark = (value) => wrap.querySelectorAll('button').forEach((b) => {
      b.classList.toggle('active', b.dataset.helpful === String(value));
    });
    if (helpful === true || helpful === false) mark(helpful);
    wrap.addEventListener('click', async (e) => {
      const btn = e.target.closest('button[data-helpful]');
      if (!btn) return;
      const value = btn.dataset.helpful === 'true';
      mark(value);
      try {
        await fetch(panel.dataset.feedbackUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
          body: JSON.stringify({ id, helpful: value }),
        });
        wrap.querySelector('span').textContent = value ? 'Thanks!' : 'Thanks, noted.';
      } catch (err) { /* feedback is best effort */ }
    });
    log.appendChild(wrap);
    scrollDown();
  }

  function addTyping() {
    const el = document.createElement('div');
    el.className = 'ai-msg assistant ai-typing';
    el.innerHTML = '<span></span><span></span><span></span>';
    log.appendChild(el);
    scrollDown();
    return el;
  }

  function addProducts(products) {
    if (!products || !products.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'ai-cards';
    for (const p of products) {
      const card = document.createElement('div');
      card.className = 'ai-card';
      card.innerHTML = `
        ${p.image ? `<a href="${encodeURI(p.url)}"><img src="${encodeURI(p.image)}" alt="" loading="lazy"></a>` : ''}
        <div class="ai-card-body">
          <a class="ai-card-name" href="${encodeURI(p.url)}">${escapeHtml(p.name)}</a>
          ${p.rating ? `<div><span class="rating-pill">${escapeHtml(p.rating)} <i class="bi bi-star-fill"></i></span></div>` : ''}
          <div class="row"><strong>${escapeHtml(p.price)}</strong>${p.mrp ? `<span class="mrp">${escapeHtml(p.mrp)}</span>` : ''}${p.discount ? `<span class="off">${p.discount}% off</span>` : ''}</div>
          ${p.in_stock ? `<form method="post" action="${encodeURI(p.add_url)}" data-cart-form>
            <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(csrf())}">
            <button class="btn btn-cta btn-sm btn-block" type="submit"><i class="bi bi-bag-plus"></i> Add to bag</button>
          </form>` : '<span class="xsmall muted">Out of stock</span>'}
        </div>`;
      wrap.appendChild(card);
    }
    log.appendChild(wrap);
    scrollDown();
  }

  function addActions(actions) {
    if (!actions || !actions.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'ai-actions';
    for (const a of actions) {
      const link = document.createElement('a');
      link.className = 'btn btn-outline btn-sm';
      link.href = a.url;
      link.textContent = a.label;
      wrap.appendChild(link);
    }
    log.appendChild(wrap);
    scrollDown();
  }

  // Tappable follow-up answers ("My order hasn't arrived", ...) that send themselves.
  function addSuggestions(suggestions) {
    if (!suggestions || !suggestions.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'ai-suggest';
    for (const text of suggestions) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = text;
      btn.addEventListener('click', () => { wrap.remove(); send(text); });
      wrap.appendChild(btn);
    }
    log.appendChild(wrap);
    scrollDown();
  }

  function greet() {
    addMessage('assistant', "Hi! I'm your shopping assistant. I can recommend products for your budget, compare options, track your orders or help with a problem. What can I do for you?");
  }

  async function loadHistory() {
    try {
      const res = await fetch(panel.dataset.historyUrl, { credentials: 'same-origin' });
      const data = await res.json();
      if (data.assistant) engine.textContent = data.assistant;
      if (data.messages.length) {
        data.messages.forEach((m) => {
          addMessage(m.role, m.content);
          if (m.role === 'assistant') addFeedback(m.id, m.helpful);
        });
      }
      else greet();
    } catch (e) {
      greet();
    }
  }

  function ensureLoaded() {
    if (!ready) ready = loadHistory();
    return ready;
  }

  function setOpen(open) {
    panel.classList.toggle('open', open);
    panel.setAttribute('aria-hidden', String(!open));
    launcher.setAttribute('aria-expanded', String(open));
    launcher.style.visibility = open ? 'hidden' : '';
    try { window.sessionStorage.setItem(OPEN_KEY, open ? '1' : ''); } catch (e) { /* storage unavailable */ }
    if (open) {
      ensureLoaded();
      setTimeout(() => input.focus({ preventScroll: true }), 250);
    }
  }

  async function send(text) {
    text = text.trim();
    if (busy || !text) return;
    busy = true;
    sendBtn.disabled = true;
    log.querySelectorAll('.ai-suggest').forEach((el) => el.remove());
    addMessage('user', text);
    input.value = '';
    autosize();
    const typing = addTyping();
    try {
      const res = await fetch(panel.dataset.chatUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      typing.remove();
      if (!res.ok) {
        addMessage('assistant', data.error || 'Something went wrong. Please try again.');
      } else {
        if (data.assistant) engine.textContent = data.assistant;
        addMessage('assistant', data.reply);
        addProducts(data.products);
        addActions(data.actions);
        addFeedback(data.id);
        addSuggestions(data.suggestions);
      }
    } catch (e) {
      typing.remove();
      addMessage('assistant', 'I could not reach the server. Please check your connection and try again.');
    } finally {
      busy = false;
      sendBtn.disabled = !input.value.trim();
      input.focus({ preventScroll: true });
    }
  }

  function autosize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  launcher.addEventListener('click', () => setOpen(true));
  document.getElementById('ai-close').addEventListener('click', () => setOpen(false));
  document.getElementById('ai-clear').addEventListener('click', async () => {
    await fetch(panel.dataset.clearUrl, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf() } });
    log.innerHTML = '';
    greet();
  });
  document.querySelectorAll('#ai-chips button').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.hasAttribute('data-human')) {
        addMessage('user', btn.textContent);
        addMessage('assistant', 'Of course. Raise a ticket and a support agent will get back to you. You can track it until it is resolved.');
        addActions([{ label: 'Raise a ticket', url: panel.dataset.ticketUrl }]);
        return;
      }
      send(btn.textContent);
    });
  });
  input.addEventListener('input', () => { autosize(); sendBtn.disabled = busy || !input.value.trim(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); send(input.value); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && panel.classList.contains('open')) setOpen(false); });

  // Any element with data-ask="question" opens the assistant and asks it.
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-ask]');
    if (!trigger) return;
    e.preventDefault();
    setOpen(true);
    const question = trigger.dataset.ask;
    ensureLoaded().then(() => setTimeout(() => send(question), 200));
  });

  // Links like /support/?ask=WEB-500 (from the plain error page) ask about that error code.
  // Only error codes are accepted, so a link can't make the assistant send arbitrary messages.
  const askCode = new URLSearchParams(window.location.search).get('ask');
  if (askCode && /^[A-Z]{2,4}-\d{3}$/.test(askCode)) {
    setOpen(true);
    ensureLoaded().then(() => setTimeout(() => send(`What does error ${askCode} mean?`), 200));
  }

  // Keep the panel open across page navigations within the session
  // (desktop only: on phones the panel covers the page).
  try {
    if (window.innerWidth > 720 && window.sessionStorage.getItem(OPEN_KEY)) setOpen(true);
  } catch (e) { /* storage unavailable */ }
})();
