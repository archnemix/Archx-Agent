'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { MEMORY_TYPES } = require('./index.js');
const fingerprint = message => crypto.createHash('sha256').update(JSON.stringify([message.id, message.role, message.ts, message.content])).digest('hex');
const problem = (message, status = 400) => Object.assign(new Error(message), { status });

function libraryRows(store) {
  const rows = [];
  for (const chat of store.state.chats.chats.filter(c => !c.ephemeral)) {
    rows.push({ kind: 'chats', id: chat.id, chatId: chat.id, title: chat.title, content: `${chat.messages.length} messages`, date: chat.messages.at(-1)?.ts });
    const seen = new Set();
    for (const message of [chat.messages, ...(chat.branches || []).map(b => b.messages || [])].flat()) {
      const id = `${chat.id}:${fingerprint(message)}`;
      if (seen.has(id)) continue;
      seen.add(id);
      rows.push({ kind: 'messages', id, chatId: chat.id, title: `${message.role} · ${chat.title}`, content: message.content || '', reasoning: message.reasoning || '', date: message.ts });
      for (const [index, match] of [...String(message.content || '').matchAll(/```([^\n]*)\n([\s\S]*?)```/g)].entries()) {
        rows.push({ kind: 'artifacts', id: `${id}:${index}`, chatId: chat.id, messageId: id, codeIndex: index, title: `${match[1] || 'Code'} · ${chat.title}`, content: match[2], date: message.ts, mime: 'text/plain' });
      }
    }
  }
  if (store.db) {
    for (const m of store.db.prepare('SELECT * FROM memories ORDER BY updated_at DESC').all()) {
      rows.push({ kind: 'memories', id: m.id, title: m.memory_key || 'Untitled memory', content: m.content, memoryType: m.memory_type, date: m.updated_at });
    }
    for (const a of store.db.prepare('SELECT * FROM assets ORDER BY created_at DESC').all()) {
      rows.push({ kind: 'artifacts', id: a.id, title: a.filename || a.kind, content: a.short_description || a.transcript || a.ocr_text || '', date: a.created_at, mime: a.mime_type, bytes: a.size_bytes, file: true });
    }
  }
  return rows;
}
function assetPath(store, asset) {
  const root = fs.realpathSync(path.join(store.dir, 'media'));
  const file = fs.realpathSync(asset.storage_path);
  const rel = path.relative(root, file);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw problem('Artifact is outside the media library.', 403);
  return file;
}
function mountLibrary(app, store) {
  app.get('/api/library', (req, res) => {
    store.flushWrites();
    const all = libraryRows(store);
    const counts = Object.fromEntries(['chats', 'messages', 'memories', 'artifacts'].map(k => [k, all.filter(r => r.kind === k).length]));
    const q = String(req.query.q || '').toLowerCase().slice(0, 500);
    const kind = req.query.kind || 'chats';
    const matches = all.filter(r => r.kind === kind && `${r.title} ${r.content} ${r.reasoning || ''}`.toLowerCase().includes(q));
    const offset = Math.max(0, Number(req.query.offset) || 0);
    const rows = matches.slice(offset, offset + 30).map(({ content, reasoning, ...r }) => ({ ...r, preview: content.slice(0, 180) }));
    res.json({ rows, counts, total: matches.length, offset, limit: 30, indexedAt: new Date().toISOString() });
  });
  app.get('/api/library/item', (req, res) => {
    const row = libraryRows(store).find(r => r.kind === req.query.kind && r.id === req.query.id);
    if (!row) return res.status(404).json({ error: { message: 'This item no longer exists.' } });
    res.json(row);
  });
  app.get('/api/library/file/:id', (req, res) => {
    const a = store.db?.prepare('SELECT * FROM assets WHERE id = ?').get(req.params.id);
    if (!a) return res.status(404).end();
    try { res.download(assetPath(store, a), path.basename(a.filename || 'artifact')); }
    catch (error) { res.status(error.status || 404).json({ error: { message: error.message } }); }
  });
  app.post('/api/library/memory', (req, res) => {
    const b = req.body || {};
    if (!store.db) return res.status(409).json({ error: { message: 'Choose a storage area before saving memory.' } });
    if (!String(b.content || '').trim() || !MEMORY_TYPES.includes(b.memoryType)) return res.status(400).json({ error: { message: 'Choose a memory type and enter its content.' } });
    if (b.id && !store.db.prepare('SELECT id FROM memories WHERE id = ?').get(b.id)) return res.status(404).json({ error: { message: 'Memory no longer exists.' } });
    const id = store.saveMemory({ id: b.id, memoryType: b.memoryType, key: String(b.title || '').slice(0, 160), content: String(b.content).slice(0, 100000), source: 'user', scopeType: 'global' });
    res.json({ id });
  });
  app.delete('/api/library/item', (req, res) => {
    try {
      store.flushWrites();
      const { kind, id } = req.body || {};
      const row = libraryRows(store).find(r => r.kind === kind && r.id === id);
      if (!row) throw problem('This item no longer exists.', 404);
      const chat = store.state.chats.chats.find(c => c.id === row.chatId);
      if (chat?.messages.some(m => m.pending)) throw problem('Stop the conversation before deleting its contents.', 409);
      if (kind === 'chats') store.state.chats.chats = store.state.chats.chats.filter(c => c.id !== id);
      else if (kind === 'memories') store.db.prepare('DELETE FROM memories WHERE id = ?').run(id);
      else if (kind === 'artifacts' && row.file) {
        const asset = store.db.prepare('SELECT * FROM assets WHERE id = ?').get(id);
        // Never unlink arbitrary imported paths or symlink targets outside media/.
        if (fs.existsSync(asset.storage_path)) fs.unlinkSync(assetPath(store, asset));
        store.db.prepare('DELETE FROM assets WHERE id = ?').run(id);
      } else {
        for (const owner of [chat, ...(chat.branches || [])]) {
          owner.messages = (owner.messages || []).filter(message => {
            const messageId = `${chat.id}:${fingerprint(message)}`;
            if (kind === 'messages') return messageId !== id;
            if (messageId === row.messageId) {
              let index = -1;
              message.content = message.content.replace(/```[^\n]*\n[\s\S]*?```/g, block => ++index === row.codeIndex ? '' : block);
            }
            return true;
          });
        }
      }
      if (row.chatId) {
        // Remove context derived from deleted text, and detailed copies in request logs.
        store.db?.prepare('DELETE FROM request_logs WHERE chat_id = ?').run(row.chatId);
        store.db?.prepare('DELETE FROM conversation_summaries WHERE chat_id = ?').run(row.chatId);
        store.db?.prepare('DELETE FROM chat_context_state WHERE chat_id = ?').run(row.chatId);
        if (store.state.chats.activeId === id) store.state.chats.activeId = null;
        store.set('chats', store.state.chats);
        store.flushWrites();
      }
      res.json({ ok: true });
    } catch (error) { res.status(error.status || 500).json({ error: { message: error.message } }); }
  });
}
function saveGeneratedAsset(store, result, description) {
  if (!store.dir || !store.db) return null;
  const bytes = Buffer.from(result.base64, 'base64');
  const mime = String(result.mime || 'application/octet-stream');
  const extension = ({ 'image/png': 'png', 'image/jpeg': 'jpg', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/mpeg': 'mp3' })[mime] || 'bin';
  const id = crypto.randomUUID();
  const dir = path.join(store.dir, 'media');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${id}.${extension}`);
  fs.writeFileSync(file, bytes, { mode: 0o600 });
  try { return store.saveAsset({ id, filename: path.basename(file), kind: mime.startsWith('image/') ? 'image' : 'audio', mimeType: mime, storagePath: file, sizeBytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), shortDescription: description.slice(0, 500) }); }
  catch (error) { fs.unlinkSync(file); throw error; }
}
module.exports = { mountLibrary, libraryRows, saveGeneratedAsset };
