/* Archx Agent — DOM helpers, icons, toasts */

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
export const uid = () =>
  Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
export const escAttr = (s) => String(s ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const msNow = () => performance.now();

export const ICON = {
  copy: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  edit: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>',
  regen: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-2.6-6.3M21 3v6h-6"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6"/></svg>',
  eyeOff: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.6 10.6 0 0 1 12 19c-6.5 0-10-7-10-7a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A9.9 9.9 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22"/></svg>',
  eye: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>',
  plus: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
};

export function toast(msg, kind = '', ttl = 4200) {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transition = 'opacity .3s';
  }, ttl - 300);
  setTimeout(() => t.remove(), ttl);
}

/* ── 1.9.0: custom dropdown — wraps a native <select> in a styled menu ──
   The <select> stays the source of truth (options are filled by renderers);
   this adds a pixel-consistent button + popover listbox on top of it. */
export function attachDropdown(sel) {
  if (!sel || sel.dataset.ddOn) return;
  sel.dataset.ddOn = '1';
  sel.style.display = 'none';
  const wrap = document.createElement('div');
  wrap.className = 'dd';
  sel.after(wrap);
  wrap.append(sel);
  wrap.insertAdjacentHTML('beforeend',
    `<button type="button" class="dd-btn" aria-haspopup="listbox"><span class="dd-label"></span><span class="dd-caret">▾</span></button><div class="dd-menu" role="listbox"></div>`);
  const btn = wrap.querySelector('.dd-btn');
  const menu = wrap.querySelector('.dd-menu');
  const label = wrap.querySelector('.dd-label');

  const refresh = () => {
    const opt = sel.selectedOptions[0];
    label.textContent = opt ? opt.textContent : (sel.options[0] ? sel.options[0].textContent : '—');
    menu.innerHTML = [...sel.options].map((o) =>
      `<div class="dd-item${o.selected ? ' sel' : ''}" role="option" data-v="${escAttr(o.value)}"><span>${esc(o.textContent)}</span>${o.dataset.sub ? `<small>${esc(o.dataset.sub)}</small>` : ''}</div>`).join('');
  };
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = wrap.classList.contains('open');
    document.querySelectorAll('.dd.open').forEach((d) => d.classList.remove('open'));
    if (!open) { refresh(); wrap.classList.add('open'); }
  });
  menu.addEventListener('click', (e) => {
    const item = e.target.closest('.dd-item');
    if (!item) return;
    sel.value = item.dataset.v;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    wrap.classList.remove('open');
    refresh();
  });
  new MutationObserver(refresh).observe(sel, { childList: true, subtree: true, attributes: true, characterData: true });
  refresh();
  return { refresh };
}
document.addEventListener('click', () => document.querySelectorAll('.dd.open').forEach((d) => d.classList.remove('open')));

/* ── 1.9.0: custom file pick — styled button + name + drag/drop + thumbs ── */
export function attachFilePick(input, { thumbs = false } = {}) {
  if (!input || input.dataset.fpOn) return;
  input.dataset.fpOn = '1';
  input.style.display = 'none';
  const wrap = document.createElement('div');
  wrap.className = 'file-pick';
  input.after(wrap);
  wrap.append(input);
  wrap.insertAdjacentHTML('beforeend',
    `<button type="button" class="btn fp-btn">${input.multiple ? 'Choose files' : 'Choose file'}</button><span class="file-pick-name">No file${input.multiple ? 's' : ''} chosen — or drop here</span>`);
  const nameEl = wrap.querySelector('.file-pick-name');
  const btn = wrap.querySelector('.fp-btn');
  let thumbsEl = null;
  if (thumbs) { thumbsEl = document.createElement('div'); thumbsEl.className = 'file-thumbs'; wrap.after(thumbsEl); }

  const paint = () => {
    const files = [...(input.files || [])];
    nameEl.textContent = files.length ? files.map((f) => f.name).join(', ') : `No file${input.multiple ? 's' : ''} chosen — or drop here`;
    if (thumbsEl) {
      thumbsEl.innerHTML = '';
      files.forEach((f, i) => {
        if (!f.type.startsWith('image/')) return;
        const t = document.createElement('div');
        t.className = 'file-thumb';
        t.innerHTML = `<img alt="${escAttr(f.name)}" /><button type="button" title="Remove">✕</button>`;
        t.querySelector('img').src = URL.createObjectURL(f);
        t.querySelector('button').addEventListener('click', () => removeAt(i));
        thumbsEl.append(t);
      });
    }
  };
  const removeAt = (i) => {
    const files = [...(input.files || [])];
    files.splice(i, 1);
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    input.files = dt.files;
    paint();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  btn.addEventListener('click', () => input.click());
  input.addEventListener('change', paint);
  wrap.addEventListener('dragover', (e) => { e.preventDefault(); wrap.classList.add('drag'); });
  wrap.addEventListener('dragleave', () => wrap.classList.remove('drag'));
  wrap.addEventListener('drop', (e) => {
    e.preventDefault();
    wrap.classList.remove('drag');
    if (e.dataTransfer?.files?.length) {
      const dt = new DataTransfer();
      const existing = input.multiple ? [...(input.files || [])] : [];
      [...existing, ...e.dataTransfer.files].forEach((f) => dt.items.add(f));
      input.files = dt.files;
      paint();
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
  paint();
}
