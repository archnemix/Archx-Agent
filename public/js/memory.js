import { $, esc, toast } from './dom.js';
import { state, flushChatWrites, loadState } from './state.js';
import { isStreaming, stop } from './chat.js';
import { renderSidebar, renderMessages } from './render.js';

const labels = { chats: 'Conversations', messages: 'Messages', memories: 'Saved knowledge', artifacts: 'Artifacts' };
let kind = 'chats', offset = 0, revision = 0, selected = null;
let confirmDelete;
async function request(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || 'Library request failed.');
  return body;
}
export async function refreshLibrary() {
  const rev = ++revision;
  $('#memory-count').textContent = 'Updating index…';
  try {
    await flushChatWrites();
    const q = $('#memory-search').value;
    const data = await request(`/api/library?${new URLSearchParams({ kind, q, offset })}`);
    if (rev !== revision) return;
    if (offset && !data.rows.length) { offset = 0; return refreshLibrary(); }
    $('#memory-tabs').innerHTML = Object.entries(labels).map(([k, label]) => `<button role="tab" type="button" data-library-kind="${k}" aria-selected="${k === kind}">${label}<small>${data.counts[k]}</small></button>`).join('');
    $('#memory-list').innerHTML = data.rows.length ? data.rows.map(r => `<button class="memory-row" type="button" data-library-id="${esc(r.id)}" aria-pressed="${selected?.id === r.id}"><b>${esc(r.title || 'Untitled')}</b><span>${esc(r.preview || 'No text preview')}</span><small>${esc(r.date ? new Date(r.date).toLocaleString() : 'Saved item')}${r.file ? ' · file' : ''}</small></button>`).join('') : '<div class="memory-empty"><b>Nothing here yet.</b><br>Try another category or search. Saved conversations and new Studio files appear automatically; temporary chats never enter this library.</div>';
    $('#memory-count').textContent = `${data.total} ${labels[kind].toLowerCase()}${q ? ' matching your search' : ''}`;
    $('#memory-page').textContent = data.total ? `${offset + 1}–${Math.min(offset + 30, data.total)} of ${data.total}` : 'No items';
    $('#memory-prev').disabled = offset === 0;
    $('#memory-next').disabled = offset + 30 >= data.total;
  } catch (error) { if (rev === revision) $('#memory-count').textContent = error.message; }
}
async function selectItem(id) {
  try {
    const requestedKind = kind;
    const item = await request(`/api/library/item?${new URLSearchParams({ kind, id })}`);
    if (requestedKind !== kind) return;
    selected = item;
    $('#memory-detail').innerHTML = `<small class="dim">${labels[kind]}</small><h3>${esc(item.title || 'Untitled')}</h3>${item.file && item.mime?.startsWith('image/') ? `<img class="memory-media" alt="Saved artifact preview" src="/api/library/preview/${encodeURIComponent(id)}" />` : ''}${item.file && item.mime?.startsWith('audio/') ? `<audio class="memory-media" controls src="/api/library/preview/${encodeURIComponent(id)}"></audio>` : ''}<pre>${esc(item.content || '(No text)')}</pre>${item.reasoning ? `<details><summary>Model reasoning</summary><pre>${esc(item.reasoning)}</pre></details>` : ''}<div class="memory-detail-actions">${item.chatId ? '<button class="btn" id="memory-open-chat" type="button">Open conversation</button>' : ''}${item.file ? `<a class="btn" href="/api/library/file/${encodeURIComponent(id)}">Download file</a>` : ''}${kind === 'memories' ? '<button class="btn" id="memory-edit" type="button">Edit memory</button>' : ''}<button class="btn danger" id="memory-delete" type="button">Delete ${kind === 'chats' ? 'conversation' : kind === 'messages' ? 'message' : 'item'}</button></div>`;
    document.querySelectorAll('.memory-row').forEach(row => row.setAttribute('aria-pressed', String(row.dataset.libraryId === id)));
    $('#memory-open-chat')?.addEventListener('click', () => {
      for (const chat of state.chats.filter(c => c.ephemeral)) stop(chat.id);
      state.chats = state.chats.filter(c => !c.ephemeral);
      state.tempMode = false;
      state.activeId = item.chatId; renderSidebar(); renderMessages(); document.querySelector('[data-page="chat"]').click();
    });
    $('#memory-edit')?.addEventListener('click', () => showEditor(item));
    $('#memory-delete').addEventListener('click', async () => {
      if (item.chatId && isStreaming(item.chatId)) return toast('Stop this conversation before deleting its contents.', 'err');
      if (!await confirmDelete({ title: 'Delete this item?', message: kind === 'messages' ? 'This removes the message from saved branches too. Derived context and conversation request logs are cleared. This cannot be undone.' : 'This cannot be undone. Other library items are kept.', confirmText: 'Delete' })) return;
      try {
        await flushChatWrites();
        await request('/api/library/item', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: item.kind, id: item.id }) });
        const liveChats = state.chats.filter(c => isStreaming(c.id));
        const activeId = state.activeId;
        const localOnly = state.chats.filter(c => c.ephemeral || !c.messages.length);
        await loadState();
        state.chats = state.chats.map(c => liveChats.find(live => live.id === c.id) || c);
        if (state.chats.some(c => c.id === activeId)) state.activeId = activeId;
        state.chats.push(...localOnly.filter(c => !state.chats.some(x => x.id === c.id)));
        selected = null; $('#memory-detail').innerHTML = '<p class="dim">Item deleted. Select another to continue.</p>';
        renderSidebar(); renderMessages(); await refreshLibrary();
      } catch (error) { toast(error.message, 'err'); }
    });
  } catch (error) { toast(error.message, 'err'); }
}
function showEditor(item = {}) {
  $('#memory-detail').innerHTML = `<form id="memory-editor" class="memory-editor"><h3>${item.id ? 'Edit' : 'Add'} memory</h3><label>Title<input name="title" maxlength="160" value="${esc(item.title || '')}" required /></label><label>Type<select name="memoryType">${['permanent', 'project', 'learning', 'procedural', 'task', 'knowledge'].map(t => `<option ${item.memoryType === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label><label>What should be kept?<textarea name="content" required maxlength="100000">${esc(item.content || '')}</textarea></label><p class="dim">Stored in your library. This does not claim automatic memory retrieval in chat.</p><div><button class="btn primary" type="submit">Save memory</button> <button class="btn" id="memory-cancel" type="button">Cancel</button></div></form>`;
  $('#memory-cancel').onclick = () => { $('#memory-detail').innerHTML = '<p class="dim">Select an item to continue.</p>'; };
  $('#memory-editor').onsubmit = async event => {
    event.preventDefault();
    const button = event.target.querySelector('[type="submit"]'); button.disabled = true;
    try {
      const body = Object.fromEntries(new FormData(event.target));
      if (item.id) body.id = item.id;
      const saved = await request('/api/library/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      kind = 'memories'; offset = 0; $('#memory-search').value = ''; await refreshLibrary(); await selectItem(saved.id);
    } catch (error) { toast(error.message, 'err'); button.disabled = false; }
  };
}
export function bindLibrary(confirm) {
  confirmDelete = confirm;
  $('#memory-tabs').onclick = event => {
    const tab = event.target.closest('[data-library-kind]'); if (!tab) return;
    kind = tab.dataset.libraryKind; offset = 0; selected = null;
    $('#memory-detail').innerHTML = '<p class="dim">Select an item to read it and manage what stays.</p>'; void refreshLibrary();
  };
  $('#memory-list').onclick = event => { const row = event.target.closest('[data-library-id]'); if (row) void selectItem(row.dataset.libraryId); };
  let timer;
  $('#memory-search').oninput = () => { clearTimeout(timer); offset = 0; timer = setTimeout(refreshLibrary, 180); };
  $('#memory-prev').onclick = () => { offset = Math.max(0, offset - 30); void refreshLibrary(); };
  $('#memory-next').onclick = () => { offset += 30; void refreshLibrary(); };
  $('#memory-add').onclick = () => showEditor();
}
