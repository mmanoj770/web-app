/* MJ: site interactions. No framework; progressive enhancement over plain forms. */
(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || '';
  const escapeHtml = (text) => {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  };

  /* ---------- Toasts ---------- */
  const toastHost = () => {
    let host = $('.toasts');
    if (!host) {
      host = document.createElement('div');
      host.className = 'toasts';
      host.setAttribute('role', 'status');
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    return host;
  };
  const ICONS = { success: 'check-circle-fill', error: 'exclamation-circle-fill', warning: 'exclamation-triangle-fill', info: 'info-circle-fill' };
  function toast(message, opts = {}) {
    const type = opts.type || 'success';
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = (opts.image ? `<img src="${encodeURI(opts.image)}" alt="">` : `<i class="bi bi-${ICONS[type] || ICONS.info}"></i>`) +
      `<span>${escapeHtml(message)}</span>` +
      (opts.link ? `<a href="${encodeURI(opts.link.url)}">${escapeHtml(opts.link.label)}</a>` : '<button type="button" aria-label="Dismiss"><i class="bi bi-x"></i></button>');
    toastHost().appendChild(el);
    const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 300); };
    const btn = el.querySelector('button');
    if (btn) btn.addEventListener('click', close);
    setTimeout(close, opts.duration || 4200);
  }
  window.toast = toast;

  // Django messages rendered by the server.
  const initial = $('#django-messages');
  if (initial) {
    try {
      JSON.parse(initial.textContent).forEach((m, i) => setTimeout(() => toast(m.text, { type: m.level }), 150 + i * 200));
    } catch (e) { /* ignore malformed data */ }
  }

  /* ---------- Fetch helper ---------- */
  async function post(url, data) {
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), Accept: 'application/json' },
      body: data,
    });
    let json = {};
    try { json = await res.json(); } catch (e) { /* non-JSON response */ }
    return { ok: res.ok, status: res.status, data: json };
  }
  window.storePost = post;

  /* ---------- Colour themes ---------- */
  const root = document.documentElement;
  function syncTheme() {
    const current = root.dataset.theme;
    $$('[data-set-theme]').forEach((b) => b.classList.toggle('active', b.dataset.setTheme === current));
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = getComputedStyle(root).getPropertyValue('--theme-color').trim();
  }
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-set-theme]');
    if (!btn) return;
    root.classList.add('theme-switching');
    root.dataset.theme = btn.dataset.setTheme;
    try { window.localStorage.setItem('mj-theme', btn.dataset.setTheme); } catch (err) { /* storage unavailable */ }
    syncTheme();
    setTimeout(() => root.classList.remove('theme-switching'), 400);
  });
  syncTheme();

  /* ---------- Dropdowns ---------- */
  document.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-dropdown-toggle]');
    $$('.dropdown.open').forEach((d) => { if (!toggle || !d.contains(toggle)) d.classList.remove('open'); });
    if (toggle) {
      e.preventDefault();
      const dd = toggle.closest('.dropdown');
      dd.classList.toggle('open');
      toggle.setAttribute('aria-expanded', dd.classList.contains('open'));
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      $$('.dropdown.open').forEach((d) => d.classList.remove('open'));
      closeFilters();
      const lb = $('.lightbox.open');
      if (lb) lb.classList.remove('open');
    }
  });

  /* ---------- Search suggestions ---------- */
  const searchInput = $('#search-input');
  const suggestBox = $('#search-suggest');
  if (searchInput && suggestBox) {
    let timer = null;
    let active = -1;
    let lastQuery = '';
    const items = () => $$('.suggest-item', suggestBox);
    const close = () => { suggestBox.classList.remove('open'); active = -1; };
    const render = (data, q) => {
      if (!data.products.length && !data.categories.length) {
        suggestBox.innerHTML = `<div class="suggest-label">No quick matches. Press Enter to search "${escapeHtml(q)}"</div>`;
      } else {
        let html = '';
        if (data.categories.length) {
          html += '<div class="suggest-label">Categories</div>' + data.categories.map((c) =>
            `<a class="suggest-item" href="${encodeURI(c.url)}"><i class="bi bi-grid"></i><span>${escapeHtml(c.name)}</span></a>`).join('');
        }
        if (data.products.length) {
          html += '<div class="suggest-label">Products</div>' + data.products.map((p) =>
            `<a class="suggest-item" href="${encodeURI(p.url)}">${p.image ? `<img src="${encodeURI(p.image)}" alt="">` : ''}` +
            `<span><span>${escapeHtml(p.name)}</span><br><span class="xsmall muted">${escapeHtml(p.category)}</span></span>` +
            `<span class="price">₹${escapeHtml(p.price)}</span></a>`).join('');
        }
        suggestBox.innerHTML = html;
      }
      suggestBox.classList.add('open');
    };
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.trim();
      clearTimeout(timer);
      if (q.length < 2) { close(); return; }
      timer = setTimeout(async () => {
        lastQuery = q;
        try {
          const res = await fetch(`${searchInput.dataset.suggestUrl}?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
          const data = await res.json();
          if (q === lastQuery) render(data, q);
        } catch (e) { close(); }
      }, 160);
    });
    searchInput.addEventListener('keydown', (e) => {
      const list = items();
      if (!suggestBox.classList.contains('open') || !list.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length;
        list.forEach((el, i) => el.classList.toggle('active', i === active));
      } else if (e.key === 'Enter' && active >= 0) {
        e.preventDefault();
        window.location = list[active].href;
      }
    });
    document.addEventListener('click', (e) => { if (!e.target.closest('.search')) close(); });
  }

  /* ---------- Cart (AJAX add) ---------- */
  function setCount(selector, count) {
    $$(selector).forEach((el) => {
      el.textContent = count;
      el.hidden = !count;
      el.classList.remove('bump');
      void el.offsetWidth; // restart the animation
      el.classList.add('bump');
    });
  }
  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-cart-form]');
    if (!form) return;
    const submitter = e.submitter;
    if (submitter && submitter.name === 'buy_now') return; // let "Buy now" do a normal navigation
    e.preventDefault();
    const button = submitter || form.querySelector('button[type="submit"], button:not([type])');
    const original = button ? button.innerHTML : '';
    if (button) { button.disabled = true; }
    try {
      const { ok, data } = await post(form.action, new FormData(form));
      if (data.count !== undefined) setCount('[data-cart-count]', data.count);
      toast(data.message || (ok ? 'Added to bag' : 'Could not add to bag'), {
        type: ok ? 'success' : 'error',
        image: ok && data.product ? data.product.image : null,
        link: ok ? { url: document.body.dataset.cartUrl, label: 'View bag' } : null,
      });
      if (ok && button) {
        button.innerHTML = '<i class="bi bi-check-lg"></i> Added';
        setTimeout(() => { button.innerHTML = original; }, 1600);
      }
    } catch (err) {
      form.submit();
    } finally {
      if (button) button.disabled = false;
    }
  });

  /* ---------- Wishlist ---------- */
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-wishlist-url]');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const { status, data } = await post(btn.dataset.wishlistUrl, new FormData());
    if (status === 401 || data.login_required) {
      window.location = `${document.body.dataset.loginUrl}?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    if (!data.message) {
      toast('Could not update your wishlist. Please try again.', { type: 'error' });
      return;
    }
    $$(`button[data-wishlist-url="${btn.dataset.wishlistUrl}"]`).forEach((b) => {
      b.classList.toggle('saved', data.saved);
      b.setAttribute('aria-pressed', data.saved);
      b.classList.remove('pulse'); void b.offsetWidth; b.classList.add('pulse');
    });
    setCount('[data-wishlist-count]', data.count);
    toast(data.message, { type: 'success', link: data.saved ? { url: document.body.dataset.wishlistPage, label: 'View' } : null });
  });

  /* ---------- Product rails ---------- */
  $$('.rail').forEach((rail) => {
    const track = $('.rail-track', rail);
    const prev = $('.rail-btn.prev', rail);
    const next = $('.rail-btn.next', rail);
    if (!track || !prev || !next) return;
    const update = () => {
      prev.hidden = track.scrollLeft < 8;
      next.hidden = track.scrollLeft + track.clientWidth >= track.scrollWidth - 8;
    };
    prev.addEventListener('click', () => track.scrollBy({ left: -track.clientWidth * 0.9 }));
    next.addEventListener('click', () => track.scrollBy({ left: track.clientWidth * 0.9 }));
    track.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  });

  /* ---------- Hero carousel ---------- */
  const hero = $('.hero');
  if (hero) {
    const slides = $$('.hero-slide', hero);
    const dots = $$('.hero-dots button', hero);
    let index = 0;
    let timer = null;
    const show = (i) => {
      index = (i + slides.length) % slides.length;
      slides.forEach((s, n) => s.classList.toggle('active', n === index));
      dots.forEach((d, n) => d.classList.toggle('active', n === index));
    };
    const start = () => { stop(); if (slides.length > 1) timer = setInterval(() => show(index + 1), 6000); };
    const stop = () => clearInterval(timer);
    dots.forEach((d, n) => d.addEventListener('click', () => { show(n); start(); }));
    hero.addEventListener('mouseenter', stop);
    hero.addEventListener('mouseleave', start);
    let touchX = null;
    hero.addEventListener('touchstart', (e) => { touchX = e.touches[0].clientX; }, { passive: true });
    hero.addEventListener('touchend', (e) => {
      if (touchX === null) return;
      const dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 40) { show(index + (dx < 0 ? 1 : -1)); start(); }
      touchX = null;
    });
    start();
  }

  /* ---------- Product gallery ---------- */
  const gallery = $('[data-gallery]');
  if (gallery) {
    const main = $('.gallery-main', gallery);
    const mainImg = $('img', main);
    const credit = $('[data-credit]', gallery.parentElement);
    $$('.gallery-thumbs button', gallery).forEach((btn) => {
      const activate = () => {
        if (btn.classList.contains('active')) return;
        $$('.gallery-thumbs button', gallery).forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        mainImg.style.opacity = '0';
        setTimeout(() => {
          mainImg.src = btn.dataset.full;
          mainImg.onload = () => { mainImg.style.opacity = '1'; };
        }, 120);
        if (credit) {
          credit.hidden = !btn.dataset.source;
          $('[data-c-author]', credit).textContent = btn.dataset.author || 'Unknown';
          const lic = $('[data-c-license]', credit);
          lic.textContent = btn.dataset.license || 'License';
          lic.href = btn.dataset.licenseUrl || btn.dataset.source || '#';
          $('[data-c-source]', credit).href = btn.dataset.source || '#';
        }
      };
      btn.addEventListener('click', activate);
      btn.addEventListener('mouseenter', activate);
    });
    if (window.matchMedia('(hover: hover)').matches) {
      main.addEventListener('mousemove', (e) => {
        const r = main.getBoundingClientRect();
        mainImg.style.transformOrigin = `${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`;
      });
      main.addEventListener('mouseenter', () => main.classList.add('zoom'));
      main.addEventListener('mouseleave', () => main.classList.remove('zoom'));
    }
    main.addEventListener('click', (e) => {
      if (e.target.closest('.wish-btn')) return;
      openLightbox(mainImg.src);
    });
  }

  /* ---------- Lightbox ---------- */
  function openLightbox(src) {
    let lb = $('.lightbox');
    if (!lb) {
      lb = document.createElement('div');
      lb.className = 'lightbox';
      lb.innerHTML = '<img alt="">';
      lb.addEventListener('click', () => lb.classList.remove('open'));
      document.body.appendChild(lb);
    }
    $('img', lb).src = src;
    lb.classList.add('open');
  }
  document.addEventListener('click', (e) => {
    const img = e.target.closest('img[data-lightbox]');
    if (img) openLightbox(img.dataset.full || img.src);
  });

  /* ---------- Quantity steppers ---------- */
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.qty button[data-step]');
    if (!btn) return;
    e.preventDefault();
    const input = $('input', btn.closest('.qty'));
    const min = Number(input.min || 0);
    const max = Number(input.max || 99);
    const value = Math.min(max, Math.max(min, Number(input.value || 0) + Number(btn.dataset.step)));
    if (String(value) === input.value) return;
    input.value = value;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });

  /* ---------- Auto-submitting forms (filters, cart quantities) ---------- */
  document.addEventListener('change', (e) => {
    const form = e.target.closest('form[data-autosubmit]');
    if (!form || e.target.matches('[data-no-autosubmit]')) return;
    clearTimeout(form._t);
    form._t = setTimeout(() => form.requestSubmit ? form.requestSubmit() : form.submit(), e.target.type === 'number' ? 500 : 60);
  });

  // Price shortcut chips set the price range and apply the filters.
  document.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-max-price]');
    if (!chip) return;
    const form = chip.form;
    form.min_price.value = '';
    form.max_price.value = chip.dataset.maxPrice;
    form.requestSubmit ? form.requestSubmit() : form.submit();
  });

  /* ---------- Filter drawer (mobile) ---------- */
  function closeFilters() {
    const f = $('.filters.open');
    if (f) f.classList.remove('open');
  }
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-open-filters]')) { e.preventDefault(); $('.filters').classList.add('open'); }
    else if (e.target.closest('[data-close-filters]')) { e.preventDefault(); closeFilters(); }
  });

  /* ---------- Payment method panels ---------- */
  const methodInputs = $$('input[name="method"]');
  if (methodInputs.length) {
    const sync = () => {
      const checked = methodInputs.find((i) => i.checked);
      $$('.pay-panel').forEach((p) => p.classList.toggle('active', checked && p.dataset.method === checked.value));
      const btn = $('[data-pay-label]');
      if (btn && checked) btn.textContent = checked.value === 'upi' ? btn.dataset.upiLabel : btn.dataset.cardLabel;
    };
    methodInputs.forEach((i) => i.addEventListener('change', sync));
    sync();
  }
  // Format card number in groups of four.
  const cardInput = $('#id_card_number');
  if (cardInput) {
    cardInput.addEventListener('input', () => {
      const digits = cardInput.value.replace(/\D/g, '').slice(0, 19);
      cardInput.value = digits.replace(/(.{4})/g, '$1 ').trim();
    });
  }
  const expiryInput = $('#id_expiry');
  if (expiryInput) {
    expiryInput.addEventListener('input', () => {
      const d = expiryInput.value.replace(/\D/g, '').slice(0, 4);
      expiryInput.value = d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
    });
  }

  /* ---------- Ticket wizard ---------- */
  const wizard = $('[data-wizard]');
  if (wizard) {
    const steps = $$('.wizard-step', wizard);
    const bar = $('.wizard-progress span', wizard);
    const orderCats = JSON.parse(wizard.dataset.orderCategories || '[]');
    const tips = JSON.parse(wizard.dataset.tips || '{}');
    const hasOrders = wizard.dataset.hasOrders === '1';
    let current = 0;
    const category = () => (($('input[name="category"]:checked', wizard) || {}).value || '');
    // Customers without orders skip the order step.
    const visibleSteps = () => steps.filter((s) => s.dataset.step !== 'order' || hasOrders);
    const go = (i) => {
      const list = visibleSteps();
      current = Math.max(0, Math.min(i, list.length - 1));
      steps.forEach((s) => s.classList.remove('active'));
      list[current].classList.add('active');
      if (bar) bar.style.width = `${((current + 1) / list.length) * 100}%`;
      const tip = $('[data-tip]', wizard);
      if (tip) {
        const text = tips[category()];
        tip.hidden = !text;
        if (text) $('span', tip).textContent = text;
      }
      const orderHint = $('[data-order-hint]', wizard);
      if (orderHint) orderHint.hidden = !orderCats.includes(category());
      const first = $('input:not([type=hidden]), textarea', list[current]);
      if (first && current > 0 && first.type !== 'radio') first.focus({ preventScroll: true });
      wizard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    wizard.addEventListener('click', (e) => {
      if (e.target.closest('[data-next]')) {
        e.preventDefault();
        if (current === 0 && !category()) { toast('Choose what you need help with', { type: 'warning' }); return; }
        const step = visibleSteps()[current];
        const chosen = $('input[name="order"]:checked', wizard);
        if (step.dataset.step === 'order' && orderCats.includes(category()) && !(chosen && chosen.value)) {
          toast('Please choose the order this is about', { type: 'warning' });
          return;
        }
        go(current + 1);
      } else if (e.target.closest('[data-back]')) {
        e.preventDefault();
        go(current - 1);
      }
    });
    $$('input[name="category"]', wizard).forEach((r) => r.addEventListener('change', () => setTimeout(() => go(1), 220)));
    // Start on the step with server-side errors, or after a pre-selected category.
    const errorStep = steps.findIndex((s) => $('.error', s));
    if (errorStep >= 0) go(visibleSteps().indexOf(steps[errorStep]));
    else go(category() ? 1 : 0);
  }

  /* ---------- Photo upload previews and drag & drop ---------- */
  $$('input[type="file"][data-preview]').forEach((input) => {
    const box = $(input.dataset.preview);
    const zone = input.closest('.dropzone');
    const render = () => {
      if (!box) return;
      box.innerHTML = '';
      Array.from(input.files).slice(0, 5).forEach((file) => {
        if (!file.type.startsWith('image/')) return;
        const img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.alt = file.name;
        box.appendChild(img);
      });
    };
    input.addEventListener('change', render);
    if (zone) {
      ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('drag'); }));
      ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('drag'); }));
      zone.addEventListener('drop', (e) => { input.files = e.dataTransfer.files; render(); });
    }
  });

  /* ---------- Delivery date by PIN code (India Post API via /api/pincode/, local estimate fallback) ---------- */
  const METRO_PREFIXES = ['11', '40', '56', '60', '70', '50', '41', '38'];
  const localEstimate = (pin) => {
    const days = METRO_PREFIXES.includes(pin.slice(0, 2)) ? 3 : 6;
    const date = new Date();
    let added = 0;
    while (added < days) { date.setDate(date.getDate() + 1); if (date.getDay() !== 0) added += 1; }
    const label = date.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
    return { valid: true, message: `Free delivery by ${label}`, city: '', source: 'estimate' };
  };
  async function lookupPin(url, pin) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    try {
      const res = await fetch(url.replace('000000', pin), { signal: controller.signal });
      return await res.json();
    } catch (e) {
      return localEstimate(pin); // Server unreachable: same estimate the server would fall back to.
    } finally {
      clearTimeout(timer);
    }
  }

  $$('[data-pincode]').forEach((form) => {
    const out = $('[data-pincode-result]', form.parentElement);
    let saved = null;
    try { saved = window.localStorage.getItem('pincode'); } catch (e) { /* storage unavailable */ }
    const input = $('input', form);
    const check = async (pin) => {
      if (!/^[1-9]\d{5}$/.test(pin)) { out.innerHTML = '<span class="error">Enter a valid 6-digit PIN code</span>'; return; }
      out.innerHTML = '<i class="bi bi-truck"></i> Checking…';
      const data = await lookupPin(form.dataset.pincodeUrl, pin);
      if (!data.valid) { out.innerHTML = `<span class="error">${escapeHtml(data.message)}</span>`; return; }
      out.innerHTML = `<i class="bi bi-truck"></i> ${escapeHtml(data.message)} · <span class="off">Free</span>`;
      try { window.localStorage.setItem('pincode', pin); } catch (e) { /* storage unavailable */ }
    };
    form.addEventListener('submit', (e) => { e.preventDefault(); check(input.value.trim()); });
    if (saved) { input.value = saved; check(saved); }
  });

  // Checkout: fill in the city from the PIN code and show the delivery date.
  $$('input[data-pincode-lookup]').forEach((input) => {
    const city = input.form && input.form.elements.city;
    const hint = document.createElement('div');
    hint.className = 'small mt-1';
    input.insertAdjacentElement('afterend', hint);
    let filled = '';
    const check = async () => {
      const pin = input.value.trim();
      if (!/^\d{6}$/.test(pin)) { hint.textContent = ''; return; }
      const data = await lookupPin(input.dataset.pincodeLookup, pin);
      if (!data.valid) { hint.innerHTML = `<span class="error">${escapeHtml(data.message)}</span>`; return; }
      hint.innerHTML = `<i class="bi bi-truck"></i> ${escapeHtml(data.message)}`;
      if (city && data.city && (!city.value.trim() || city.value === filled)) {
        city.value = data.city;
        filled = data.city;
      }
    };
    input.addEventListener('input', check);
    if (input.value) check();
  });

  /* ---------- Show / hide password ---------- */
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-password-toggle]');
    if (!btn) return;
    const input = document.getElementById(btn.getAttribute('aria-controls'));
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.setAttribute('aria-pressed', String(show));
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    btn.innerHTML = `<i class="bi bi-eye${show ? '-slash' : ''}"></i>`;
    input.focus({ preventScroll: true });
  });

  /* ---------- FAQs from /api/faqs/ ---------- */
  $$('[data-faq-api]').forEach((root) => {
    const results = $('[data-faq-results]', root);
    const chips = $('[data-faq-categories]', root);
    const search = $('[data-faq-search]', root);
    let category = '';
    let timer = null;
    const render = (data) => {
      if (!data.results.length) {
        results.innerHTML = `<div class="faq-empty" style="grid-column: 1 / -1">No FAQs match.
          <button class="btn btn-white btn-sm" type="button" data-ask="${escapeHtml(search.value || 'I have a question')}"><i class="bi bi-stars"></i> Ask AI</button></div>`;
        return;
      }
      // Groups follow the category order from the API; searches keep the best match first.
      const groups = new Map(search.value.trim() ? [] : data.categories.map((c) => [c.label, []]));
      data.results.forEach((f) => {
        if (!groups.has(f.category_label)) groups.set(f.category_label, []);
        groups.get(f.category_label).push(f);
      });
      results.innerHTML = Array.from(groups).filter(([, faqs]) => faqs.length).map(([label, faqs]) => `
        <div class="card faq">
          <div class="card-head"><h3>${escapeHtml(label)}</h3></div>
          ${faqs.map((f) => `<details><summary>${escapeHtml(f.question)}</summary><p>${escapeHtml(f.answer)}</p></details>`).join('')}
        </div>`).join('');
      if (search.value.trim()) $('details', results)?.setAttribute('open', '');
    };
    const load = async () => {
      const params = new URLSearchParams();
      if (search.value.trim()) params.set('q', search.value.trim());
      if (category) params.set('category', category);
      try {
        const res = await fetch(`${root.dataset.faqApi}?${params}`);
        const data = await res.json();
        if (!chips.children.length) {
          chips.innerHTML = [{ key: '', label: 'All' }, ...data.categories].map((c) =>
            `<button class="chip${c.key === category ? ' active' : ''}" type="button" data-key="${escapeHtml(c.key)}">${escapeHtml(c.label)}</button>`).join('');
        }
        render(data);
      } catch (e) {
        results.innerHTML = '<div class="faq-empty">Could not load FAQs. Please refresh, or ask our assistant.</div>';
      }
    };
    chips.addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      category = chip.dataset.key;
      $$('.chip', chips).forEach((c) => c.classList.toggle('active', c === chip));
      load();
    });
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
    load();
  });

  /* ---------- Error codes from /api/error-codes/ ---------- */
  $$('[data-error-api]').forEach(async (root) => {
    const results = $('[data-error-results]', root);
    const search = $('[data-error-search]', root);
    let codes = [];
    const render = () => {
      const q = search.value.trim().toLowerCase();
      const shown = codes.filter((c) => !q || `${c.code} ${c.title} ${c.meaning} ${c.area_label}`.toLowerCase().includes(q));
      results.innerHTML = shown.length ? shown.map((c) => `
        <article class="card" id="${escapeHtml(c.code)}">
          <div class="row-between"><span class="code-pill">${escapeHtml(c.code)}</span><span class="xsmall muted">${c.http_status ? `HTTP ${c.http_status} · ` : ''}${escapeHtml(c.area_label)}</span></div>
          <h3>${escapeHtml(c.title)}</h3>
          <p><strong>What happened:</strong> ${escapeHtml(c.meaning)}</p>
          <p><strong>What to do:</strong> ${escapeHtml(c.resolution)}</p>
          <div class="row mt-2" style="flex-wrap: wrap">
            <button class="btn btn-white btn-sm" type="button" data-ask="What does error ${escapeHtml(c.code)} mean?"><i class="bi bi-stars"></i> Ask AI</button>
            ${c.ticket_category ? `<a class="btn btn-outline btn-sm" href="${root.dataset.ticketUrl}?category=${encodeURIComponent(c.ticket_category)}">Raise a ticket</a>` : ''}
          </div>
        </article>`).join('') : '<div class="faq-empty">No error codes match.</div>';
    };
    try {
      const res = await fetch(root.dataset.errorApi);
      codes = (await res.json()).results;
      render();
      if (window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    } catch (e) {
      results.innerHTML = '<div class="faq-empty">Could not load error codes. Please refresh, or ask our assistant.</div>';
    }
    search.addEventListener('input', render);
  });

  /* ---------- Canned replies (dashboard) ---------- */
  $$('select[data-canned]').forEach((select) => {
    select.addEventListener('change', () => {
      const target = $(select.dataset.canned);
      if (target && select.value) { target.value = select.value; target.focus(); }
      select.selectedIndex = 0;
    });
  });

  /* ---------- Confirmations ---------- */
  document.addEventListener('submit', (e) => {
    const msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);

  /* ---------- Reveal on scroll ---------- */
  const reveals = $$('.reveal');
  if ('IntersectionObserver' in window && reveals.length) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { entry.target.classList.add('in'); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -40px 0px', threshold: 0.05 });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add('in'));
  }
})();
