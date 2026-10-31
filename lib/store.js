'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { isDeepStrictEqual } = require('util');
const { writePointer, configPath, manifestPath } = require('./paths.js');
const keys = require('./keys.js');
const { serializeMessageMeta, restoreMessageMeta } = require('./message-state.js');
const { openDatabase, transaction, now, json, parseJson, encodeVector, decodeVector, DB_FILENAME, SCHEMA_VERSION } = require('./db.js');
const { MEMORY_TYPES } = require('./memory/index.js');

const LEGACY_FILES = ['providers.json', 'settings.json', 'chats.json', 'endpoint.json', 'models.json'];
/* 1.7.2 crash-safe write queue: SQL writes are serialized through a single
   writer. While a drain is in flight, further requests are appended to a
   temp journal (write-queue.jsonl) in the data area and coalesced into the
   next drain — so concurrent chats can never lose a write, and a crash
   between enqueue and drain is replayed from the journal at next boot. */
const QUEUE_FILENAME = 'write-queue.jsonl';
const LEGACY_DIRS = ['logs'];
const DEFAULT_SYSTEM_PROMPT = [
  'You are {agentName} — a sharp, practical and friendly AI assistant.',
  'Be clear, concrete and concise. When a request is ambiguous, ask one focused clarifying question instead of guessing.',
  'Never invent facts, tool results, citations or actions. Clearly separate what is known from what is assumed, and say so when you are assuming.',
  'For technical work, prefer correct, runnable examples and briefly explain the trade-offs that actually matter.',
  'Use the personalization context appended to this prompt (preferred name, age) naturally when it is relevant — never mention the context itself.',
].join('\n');

const DEFAULTS = () => ({
  providers: { providers: [], active: { providerId: null, model: null }, profiles: [], activeProfileId: null },
  settings: {
    system: DEFAULT_SYSTEM_PROMPT,
    systemPrompts: [{ id: 'sp-default', name: 'Default', content: DEFAULT_SYSTEM_PROMPT }],
    defaultSystemPromptId: 'sp-default',
    defaultSystemPromptInitialized: true,
    systemPromptMode: 'stack',
    temperature: 0.7,
    maxTokens: null,
    stream: true,
    theme: 'dark',
    reasoning: true,
    logsMode: 'simple',
    advancedProfiles: true,
    username: '',
    age: '',
    preferredName: '',
    agentName: 'Archx Agent',
    personalizationOnboarded: false,
  },
  chats: { chats: [], activeId: null },
});

const deepEq = (a, b) => isDeepStrictEqual(a, b);
const isObject = (x) => x && typeof x === 'object' && !Array.isArray(x);
const strArr = (x) => Array.isArray(x) ? x.map((v) => String(v)).filter(Boolean) : [];
const freshId = (prefix) => `${prefix}-${crypto.randomBytes(6).toString('hex')}`;

function readJson(p) {
  try {
    const value = JSON.parse(fs.readFileSync(p, 'utf8'));
    return value && typeof value === 'object' ? value : null;
  } catch {
    return null;
  }
}

function closeQuietly(db) {
  try { db?.close(); } catch {}
}

/* chats.mode_id has a FK to modes; any handle that receives chat writes must
   have the built-in mode rows (migration targets previously didn't → the
   "FOREIGN KEY constraint failed" on storage moves). */
function seedModes(db) {
  db.prepare('INSERT OR IGNORE INTO modes(id, name, description, capabilities_json, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)')
    .run('simple-chat', 'Simple chat', 'Plain text conversation with the selected model. No tools.', json({ tools: false, textInput: true, textOutput: true }), now());
}

function vectorFromJson(value) {
  return Array.isArray(value) ? value.map(Number).filter(Number.isFinite) : [];
}

class Store {
  constructor(dataDir) {
    this.dir = dataDir || null;
    this.db = null;
    this.state = DEFAULTS();
    this._manifest = null;
    this._queue = [];
    this._writeBusy = false;
    this._drainScheduled = false;
    if (this.dir) this.#open();
    this.writeManifest();
  }

  #open() {
    const dbPath = path.join(this.dir, DB_FILENAME);
    const existed = fs.existsSync(dbPath);
    this.db = openDatabase(this.dir);
    this.#ensureModes();
    if (!existed && this.#legacyFilesExist()) this.#importLegacy();
    else if (!existed) this.#writeAllState(this.state);
    this.#loadFromDb();
    const recovered = this.#recoverJournal();
    if (recovered) console.log(`archx-agent: replayed ${recovered} queued write group(s) from ${QUEUE_FILENAME}.`);
  }

  #ensureModes() {
    seedModes(this.db);
  }

  #legacyFilesExist() {
    return LEGACY_FILES.some((file) => fs.existsSync(path.join(this.dir, file)));
  }

  #importLegacy() {
    const legacyProviders = readJson(path.join(this.dir, 'providers.json'));
    const legacySettings = readJson(path.join(this.dir, 'settings.json'));
    const legacyChats = readJson(path.join(this.dir, 'chats.json'));
    const endpoint = readJson(path.join(this.dir, 'endpoint.json'));
    const models = readJson(path.join(this.dir, 'models.json'));

    const imported = DEFAULTS();
    if (isObject(legacySettings)) imported.settings = { ...imported.settings, ...legacySettings };
    if (isObject(legacyChats)) imported.chats = { ...imported.chats, ...legacyChats };
    if (isObject(legacyProviders)) imported.providers = { ...imported.providers, ...legacyProviders };

    if (!Array.isArray(imported.providers.providers) || !imported.providers.providers.length) {
      if (endpoint) {
        let name = 'default';
        try { name = new URL(endpoint.baseUrl || 'http://default').host || 'default'; } catch {}
        const id = freshId('p');
        imported.providers.providers = [{
          id,
          name,
          adapter: 'openai-compatible',
          baseUrl: endpoint.baseUrl || null,
          keyCipher: endpoint.apiKey ? keys.encrypt(endpoint.apiKey) : null,
          models: { catalog: [], catalogInitialized: false, selectionMode: 'legacy', hidden: strArr(models?.hidden), custom: strArr(models?.custom) },
          freeOnly: false,
          freeOnlySnapshot: [],
          freeOnlyAutoHidden: [],
          freeOnlyManualEnabled: [],
          defaultModel: null,
        }];
        imported.providers.active = { providerId: id, model: null };
      }
    }

    imported.providers.providers = (imported.providers.providers || []).map((provider) => ({
      ...provider,
      adapter: provider.adapter || 'openai-compatible',
      models: {
        catalog: strArr(provider.models?.catalog),
        custom: strArr(provider.models?.custom),
        hidden: strArr(provider.models?.hidden),
        catalogInitialized: provider.models?.catalogInitialized === true || strArr(provider.models?.catalog).length > 0,
        selectionMode: provider.models?.selectionMode === 'checklist' ? 'checklist' : 'legacy',
      },
      freeOnly: !!provider.freeOnly,
      freeOnlySnapshot: strArr(provider.freeOnlySnapshot),
      freeOnlyAutoHidden: strArr(provider.freeOnlyAutoHidden),
      freeOnlyManualEnabled: strArr(provider.freeOnlyManualEnabled),
      defaultModel: provider.defaultModel || null,
    }));
    imported.providers.profiles = (imported.providers.profiles || []).map((profile, index) => ({
      id: profile.id || freshId('mp'),
      name: typeof profile.name === 'string' && profile.name.trim() ? profile.name.trim() : `Profile ${index + 1}`,
      items: Array.isArray(profile.items) ? profile.items : [],
    }));
    imported.chats.chats = (imported.chats.chats || []).map((chat) => ({
      ...chat,
      modeId: chat.modeId || 'simple-chat',
      systemPromptId: chat.systemPromptId || null,
      enabledPromptIds: Array.isArray(chat.enabledPromptIds) ? chat.enabledPromptIds : [],
      debugTraceIds: Array.isArray(chat.debugTraceIds) ? chat.debugTraceIds : [],
      debugEvents: Array.isArray(chat.debugEvents) ? chat.debugEvents : [],
      messages: (chat.messages || []).map((message) => ({
        ...message,
        reasoning: message.reasoning || '',
        pending: !!message.pending,
        error: !!message.error,
        meta: isObject(message.meta) ? message.meta : {},
      })),
    }));

    this.#writeAllState(imported);
    const importedLogCount = this.#importLegacyLogs();
    const roundTrip = this.#readAllState();
    const dbLogCount = this.db.prepare('SELECT COUNT(*) AS count FROM request_logs').get().count;
    if (!deepEq(this.#migrationComparable(imported), this.#migrationComparable(roundTrip)) || Number(dbLogCount) !== importedLogCount) {
      throw new Error('SQLite migration verification failed; legacy files were left untouched.');
    }

    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    for (const file of LEGACY_FILES) {
      const src = path.join(this.dir, file);
      if (!fs.existsSync(src)) continue;
      try { fs.renameSync(src, `${src}.migrated-${stamp}`); } catch {}
    }
    const legacyLogs = path.join(this.dir, 'logs');
    if (fs.existsSync(legacyLogs)) {
      try { fs.renameSync(legacyLogs, `${legacyLogs}.migrated-${stamp}`); } catch {}
    }
  }

  /* Normalizes a state snapshot to exactly the shape a database round-trip
     produces (default-filled message/chat fields, stable ordering, system
     prompt resolved the way #loadFromDb resolves it) so copy verification
     compares like with like. */
  #migrationComparable(state) {
    const copy = JSON.parse(JSON.stringify(state));
    const prompts = Array.isArray(copy.settings?.systemPrompts) ? copy.settings.systemPrompts : [];
    const defId = copy.settings?.defaultSystemPromptId;
    copy.settings = {
      ...(copy.settings || {}),
      system: (prompts.find((p) => p.id === defId) || prompts[0] || {}).content || copy.settings?.system || '',
      systemPrompts: prompts.map((p) => ({ id: p.id, name: p.name, content: p.content })),
    };
    copy.chats = {
      ...(copy.chats || {}),
      chats: (copy.chats?.chats || [])
        .map((c) => ({
          ...c,
          modeId: c.modeId || 'simple-chat',
          systemPromptId: c.systemPromptId ?? null,
          enabledPromptIds: c.enabledPromptIds || [],
          debugTraceIds: c.debugTraceIds || [],
          debugEvents: c.debugEvents || [],
          branches: (c.branches || []).map((b) => ({ ...b, messages: (b.messages || []).map((m) => this.#normMsg(m)) })),
          messages: (c.messages || []).map((m) => this.#normMsg(m)),
        }))
        .sort((a, b) => String(a.id).localeCompare(String(b.id))),
    };
    copy.providers = {
      ...(copy.providers || {}),
      // 1.8.0 fix: the DB round-trip reads providers back in id order while
      // memory keeps insertion order — compare order-insensitively or every
      // migration after an add/delete falsely fails verification.
      providers: (copy.providers?.providers || [])
        .slice()
        .sort((a, b) => String(a.id).localeCompare(String(b.id))),
      profiles: (copy.providers?.profiles || []).map((p) => ({ id: p.id, name: p.name, items: (p.items || []).map((i) => ({ providerId: i.providerId, model: i.model, priority: Number(i.priority) || 1, order: Number.isFinite(Number(i.order)) ? Number(i.order) : 0, enabled: i.enabled !== false })) })),
    };
    return copy;
  }

  #normMsg(m) {
    return {
      role: m.role || 'user',
      content: m.content || '',
      reasoning: m.reasoning || '',
      pending: !!m.pending,
      error: !!m.error,
      tools: Array.isArray(m.tools) ? m.tools : [],
      errorMessage: typeof m.errorMessage === 'string' ? m.errorMessage : '',
      ts: Number(m.ts) || 0,
      meta: m.meta && typeof m.meta === 'object' ? m.meta : {},
    };
  }

  #importLegacyLogs() {
    const logsDir = path.join(this.dir, 'logs');
    if (!fs.existsSync(logsDir)) return 0;
    const insert = this.db.prepare('INSERT INTO request_logs(ts, mode, trace_id, chat_id, provider_id, kind, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)');
    let imported = 0;
    transaction(this.db, () => {
      const files = fs.readdirSync(logsDir).filter((file) => file.endsWith('.jsonl')).sort();
      for (const file of files) {
        let lines = [];
        try { lines = fs.readFileSync(path.join(logsDir, file), 'utf8').split('\n').filter(Boolean); } catch { continue; }
        for (const line of lines) {
          try {
            const raw = JSON.parse(line);
            const encrypted = raw && raw.mode === 'detailed';
            const envelope = encrypted ? { ts: new Date().toISOString(), mode: 'detailed-encrypted', ...raw } : raw;
            insert.run(envelope.ts || now(), encrypted ? 'detailed-encrypted' : 'simple', envelope.traceId || null, envelope.chatId || null, envelope.providerId || null, envelope.kind || null, JSON.stringify(encrypted ? raw : envelope));
            imported += 1;
          } catch {}
        }
      }
    });
    return imported;
  }

  #loadFromDb() {
    const next = DEFAULTS();
    const rows = this.db.prepare('SELECT key, value_json FROM settings').all();
    for (const row of rows) next.settings[row.key] = parseJson(row.value_json, next.settings[row.key]);

    const stateRows = this.db.prepare('SELECT key, value_json FROM app_state').all();
    const active = {};
    for (const row of stateRows) active[row.key] = parseJson(row.value_json, null);

    const prompts = this.db.prepare('SELECT id, name, content FROM system_prompts ORDER BY created_at, id').all();
    if (prompts.length) next.settings.systemPrompts = prompts.map((p) => ({ id: p.id, name: p.name, content: p.content }));
    if (!next.settings.systemPrompts.length) next.settings.systemPrompts = DEFAULTS().settings.systemPrompts;
    next.settings.defaultSystemPromptId = next.settings.defaultSystemPromptId || next.settings.systemPrompts[0]?.id || 'sp-default';
    next.settings.system = next.settings.systemPrompts.find((p) => p.id === next.settings.defaultSystemPromptId)?.content || DEFAULT_SYSTEM_PROMPT;

    const providers = this.db.prepare('SELECT * FROM providers ORDER BY created_at, id').all();
    const endpoints = this.db.prepare('SELECT * FROM model_endpoints ORDER BY provider_id, created_at, remote_model_id').all();
    const endpointByProvider = new Map();
    for (const row of endpoints) {
      if (!endpointByProvider.has(row.provider_id)) endpointByProvider.set(row.provider_id, []);
      endpointByProvider.get(row.provider_id).push(row);
    }
    const providerState = providers.map((p) => {
      const config = parseJson(p.model_config_json, {});
      const eps = endpointByProvider.get(p.id) || [];
      const catalog = eps.filter((x) => !x.is_custom).map((x) => x.remote_model_id);
      const custom = eps.filter((x) => x.is_custom).map((x) => x.remote_model_id);
      const hidden = eps.filter((x) => x.is_hidden).map((x) => x.remote_model_id);
      return {
        id: p.id,
        name: p.name,
        adapter: p.adapter,
        baseUrl: p.base_url,
        keyCipher: parseJson(p.key_cipher_json, null),
        models: { ...config, catalog, custom, hidden, catalogInitialized: config.catalogInitialized === true || catalog.length > 0 },
        freeOnly: !!p.free_only,
        freeOnlySnapshot: parseJson(p.free_only_snapshot_json, []),
        freeOnlyAutoHidden: parseJson(p.free_only_auto_hidden_json, []),
        freeOnlyManualEnabled: parseJson(p.free_only_manual_enabled_json, []),
        defaultModel: p.default_model || null,
      };
    });
    next.providers.providers = providerState;
    next.providers.active = {
      providerId: active.activeProviderId || null,
      model: active.activeModel || null,
    };

    const profiles = this.db.prepare('SELECT id, name, description, parked_json FROM profiles ORDER BY created_at, id').all();
    const items = this.db.prepare('SELECT profile_id, provider_id, model_id, priority, item_order, enabled FROM profile_items ORDER BY profile_id, priority, item_order').all();
    const itemsByProfile = new Map();
    for (const item of items) {
      if (!itemsByProfile.has(item.profile_id)) itemsByProfile.set(item.profile_id, []);
      itemsByProfile.get(item.profile_id).push({ providerId: item.provider_id, model: item.model_id, priority: item.priority, order: item.item_order, enabled: !!item.enabled });
    }
    next.providers.profiles = profiles.map((p) => ({ id: p.id, name: p.name, description: p.description || '', items: [...(itemsByProfile.get(p.id) || []), ...parseJson(p.parked_json, []).map((x) => ({ ...x, parked: true, enabled: false }))] }));
    next.providers.activeProfileId = active.activeProfileId || null;

    next.chats = this.#readChats(active.activeChatId || null);
    this.state = next;
  }

  #readChats(activeId) {
    const chats = this.db.prepare('SELECT * FROM chats ORDER BY updated_at DESC, created_at DESC').all();
    const messages = this.db.prepare('SELECT * FROM messages ORDER BY chat_id, ordinal').all();
    const byChat = new Map();
    for (const row of messages) {
      if (!byChat.has(row.chat_id)) byChat.set(row.chat_id, []);
      byChat.get(row.chat_id).push({
        id: row.id,
        role: row.role,
        content: row.content,
        reasoning: row.reasoning,
        pending: !!row.pending,
        error: !!row.is_error,
        ts: row.ts,
        ...restoreMessageMeta(parseJson(row.meta_json, {})),
      });
    }
    return {
      chats: chats.map((c) => ({
        id: c.id,
        title: c.title,
        modeId: c.mode_id || 'simple-chat',
        systemPromptId: c.system_prompt_id,
        enabledPromptIds: parseJson(c.enabled_prompt_ids_json, []),
        debugTraceIds: parseJson(c.debug_trace_ids_json, []),
        debugEvents: parseJson(c.debug_events_json, []),
        branches: parseJson(c.branches_json, []),
        pinned: !!c.pinned,
        messages: byChat.get(c.id) || [],
      })),
      activeId: activeId || null,
    };
  }

  #writeAllState(state) {
    transaction(this.db, () => {
      this.#writeSettings(state.settings);
      this.#writeProviders(state.providers);
      this.#writeChats(state.chats);
    });
  }

  #writeSettings(settings) {
    this.db.prepare('DELETE FROM settings').run();
    const insert = this.db.prepare('INSERT INTO settings(key, value_json) VALUES (?, ?)');
    for (const [key, value] of Object.entries(settings || {})) insert.run(key, json(value));

    const promptRows = this.db.prepare('SELECT id FROM system_prompts').all();
    const incoming = new Set((settings.systemPrompts || []).map((prompt) => String(prompt.id)));
    const removePrompt = this.db.prepare('UPDATE chats SET system_prompt_id = NULL WHERE system_prompt_id = ?');
    const deletePrompt = this.db.prepare('DELETE FROM system_prompts WHERE id = ?');
    for (const row of promptRows) {
      if (!incoming.has(row.id)) {
        removePrompt.run(row.id);
        deletePrompt.run(row.id);
        if (this.state.settings === settings && this.state.chats?.chats) {
          for (const chat of this.state.chats.chats) {
            if (chat.systemPromptId === row.id) chat.systemPromptId = null;
            chat.enabledPromptIds = (chat.enabledPromptIds || []).filter((id) => id !== row.id);
          }
        }
      }
    }

    const upsertPrompt = this.db.prepare(`INSERT INTO system_prompts(id, name, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET name=excluded.name, content=excluded.content, updated_at=excluded.updated_at`);
    const stamp = now();
    for (const prompt of settings.systemPrompts || []) {
      if (!prompt?.id) continue;
      upsertPrompt.run(prompt.id, prompt.name || prompt.id, prompt.content || '', stamp, stamp);
    }
  }

  #writeProviders(providersState) {
    this.db.prepare('DELETE FROM profile_items').run();
    this.db.prepare('DELETE FROM profiles').run();
    this.db.prepare('DELETE FROM model_endpoints').run();
    this.db.prepare('DELETE FROM models').run();
    this.db.prepare('DELETE FROM providers').run();

    const stamp = now();
    const providerInsert = this.db.prepare(`INSERT INTO providers(id, name, adapter, base_url, key_cipher_json, default_model, free_only, free_only_snapshot_json, free_only_auto_hidden_json, free_only_manual_enabled_json, model_config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
    const modelInsert = this.db.prepare(`INSERT INTO models(id, canonical_name, family, metadata_json, created_at, updated_at) VALUES (?, ?, NULL, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at`);
    const endpointInsert = this.db.prepare(`INSERT INTO model_endpoints(provider_id, model_id, endpoint_kind, remote_model_id, is_custom, is_hidden, is_enabled, owned_by, endpoint_url, capabilities_json, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
    for (const provider of providersState.providers || []) {
      providerInsert.run(
        provider.id,
        provider.name || provider.id,
        provider.adapter || 'openai-compatible',
        provider.baseUrl || null,
        provider.keyCipher ? json(provider.keyCipher) : null,
        provider.defaultModel || null,
        provider.freeOnly ? 1 : 0,
        json(provider.freeOnlySnapshot || []),
        json(provider.freeOnlyAutoHidden || []),
        json(provider.freeOnlyManualEnabled || []),
        json(provider.models || {}),
        stamp,
        stamp,
      );
      const models = provider.models || {};
      const catalog = strArr(models.catalog);
      const custom = strArr(models.custom);
      const hidden = new Set(strArr(models.hidden));
      const ids = [...new Set([...catalog, ...custom])];
      for (const remoteModelId of ids) {
        modelInsert.run(remoteModelId, remoteModelId, json({}), stamp, stamp);
        endpointInsert.run(provider.id, remoteModelId, 'chat', remoteModelId, custom.includes(remoteModelId) ? 1 : 0, hidden.has(remoteModelId) ? 1 : 0, hidden.has(remoteModelId) ? 0 : 1, null, null, json({ textInput: true, textOutput: true }), json({}), stamp, stamp);
      }
    }

    const profileInsert = this.db.prepare('INSERT INTO profiles(id, name, description, parked_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)');
    const itemInsert = this.db.prepare('INSERT INTO profile_items(profile_id, provider_id, model_id, priority, item_order, enabled) VALUES (?, ?, ?, ?, ?, ?)');
    const usedProfileNames = new Set();
    const liveProviderIds = new Set((providersState.providers || []).map((p) => p.id));
    for (const profile of providersState.profiles || []) {
      const requested = typeof profile.name === 'string' ? profile.name.trim() : '';
      const base = requested || 'Profile';
      let name = base;
      let suffix = 2;
      while (usedProfileNames.has(name.toLocaleLowerCase())) name = `${base} (${suffix++})`;
      usedProfileNames.add(name.toLocaleLowerCase());
      profile.name = name;
      profile.description = typeof profile.description === 'string' ? profile.description : '';
      // 1.8.0: entries whose provider no longer exists are parked in a JSON
      // column (the profile_items FK would reject a dangling provider id).
      const parked = [];
      const live = [];
      for (const item of profile.items || []) {
        if (item.parked === true || !liveProviderIds.has(item.providerId)) parked.push(item);
        else live.push(item);
      }
      profileInsert.run(profile.id || freshId('mp'), name, profile.description, json(parked), stamp, stamp);
      for (const item of live) {
        modelInsert.run(item.model, item.model, json({}), stamp, stamp);
        const endpointExists = this.db.prepare('SELECT 1 FROM model_endpoints WHERE provider_id = ? AND model_id = ? AND endpoint_kind = \'chat\'').get(item.providerId, item.model);
        if (!endpointExists) endpointInsert.run(item.providerId, item.model, 'chat', item.model, 0, 0, 1, null, null, json({ textInput: true, textOutput: true }), json({}), stamp, stamp);
        itemInsert.run(profile.id, item.providerId, item.model, Math.max(1, Number(item.priority) || 1), Number.isFinite(Number(item.order)) ? Number(item.order) : 0, item.enabled === false ? 0 : 1);
      }
    }

    this.db.prepare('DELETE FROM app_state').run();
    const appStateInsert = this.db.prepare('INSERT INTO app_state(key, value_json) VALUES (?, ?)');
    appStateInsert.run('activeProviderId', json(providersState.active?.providerId || null));
    appStateInsert.run('activeModel', json(providersState.active?.model || null));
    appStateInsert.run('activeProfileId', json(providersState.activeProfileId || null));
  }

  #writeChats(chatsState) {
    const incomingChats = chatsState.chats || [];
    // 1.8.0 temporary mode: ephemeral chats live only in client memory. They
    // are never written, and if a chat turns temporary after being persisted,
    // its stored copy is removed.
    const persistable = incomingChats.filter((chat) => !chat.ephemeral);
    const incomingIds = new Set(persistable.map((chat) => String(chat.id)));
    const ephemeralIds = new Set(incomingChats.filter((chat) => chat.ephemeral).map((chat) => String(chat.id)));
    if (incomingIds.size || ephemeralIds.size) {
      const existing = this.db.prepare('SELECT id FROM chats').all();
      const deleteChat = this.db.prepare('DELETE FROM chats WHERE id = ?');
      for (const row of existing) {
        if (!incomingIds.has(row.id) || ephemeralIds.has(row.id)) deleteChat.run(row.id);
      }
    } else {
      this.db.prepare('DELETE FROM chats').run();
    }

    const chatInsert = this.db.prepare(`INSERT INTO chats(id, title, mode_id, system_prompt_id, enabled_prompt_ids_json, created_at, updated_at, debug_trace_ids_json, debug_events_json, pinned, branches_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET title=excluded.title, mode_id=excluded.mode_id, system_prompt_id=excluded.system_prompt_id,
        enabled_prompt_ids_json=excluded.enabled_prompt_ids_json, updated_at=excluded.updated_at,
        debug_trace_ids_json=excluded.debug_trace_ids_json, debug_events_json=excluded.debug_events_json, pinned=excluded.pinned, branches_json=excluded.branches_json`);
    const messageUpsert = this.db.prepare(`INSERT INTO messages(id, chat_id, ordinal, role, content, reasoning, pending, is_error, ts, meta_json, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(chat_id, ordinal) DO UPDATE SET id=excluded.id, role=excluded.role, content=excluded.content,
        reasoning=excluded.reasoning, pending=excluded.pending, is_error=excluded.is_error, ts=excluded.ts, meta_json=excluded.meta_json`);
    const deleteTail = this.db.prepare('DELETE FROM messages WHERE chat_id = ? AND ordinal >= ?');
    const stamp = now();
    const modeExists = this.db.prepare('SELECT 1 FROM modes WHERE id = ?');
    const promptExists = this.db.prepare('SELECT 1 FROM system_prompts WHERE id = ?');

    for (const chat of persistable) {
      const created = new Date(chat.messages?.[0]?.ts || Date.now()).toISOString();
      const modeId = chat.modeId && modeExists.get(chat.modeId) ? chat.modeId : 'simple-chat';
      const systemPromptId = chat.systemPromptId && promptExists.get(chat.systemPromptId) ? chat.systemPromptId : null;
      chat.modeId = modeId;
      chat.systemPromptId = systemPromptId;
      chatInsert.run(
        chat.id,
        chat.title || 'New chat',
        modeId,
        systemPromptId,
        json(chat.enabledPromptIds || []),
        created,
        stamp,
        json(chat.debugTraceIds || []),
        json(chat.debugEvents || []),
        chat.pinned ? 1 : 0,
        json(chat.branches || []),
      );

      const messages = chat.messages || [];
      deleteTail.run(chat.id, messages.length);
      for (let ordinal = 0; ordinal < messages.length; ordinal += 1) {
        const message = messages[ordinal];
        const ts = Number(message.ts) || Date.now();
        const id = message.id || `m-${chat.id}-${ordinal + 1}`;
        message.id = id;
        messageUpsert.run(
          id,
          chat.id,
          ordinal,
          message.role || 'user',
          message.content || '',
          message.reasoning || '',
          message.pending ? 1 : 0,
          message.error ? 1 : 0,
          ts,
          json(serializeMessageMeta(message)),
          new Date(ts).toISOString(),
        );
      }
    }
    this.db.prepare('INSERT INTO app_state(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json').run('activeChatId', json(chatsState.activeId || null));
  }

  #readAllState() {
    const current = this.state;
    this.#loadFromDb();
    const loaded = this.state;
    this.state = current;
    return loaded;
  }

  manifest() {
    return {
      version: 2,
      updatedAt: new Date().toISOString(),
      app: {
        name: 'archx-agent',
        version: require('../package.json').version,
        installPath: path.resolve(__dirname, '..'),
        bin: path.resolve(__dirname, '..', 'bin', 'archx-agent.js'),
        node: process.version,
        platform: `${process.platform}/${process.arch}`,
      },
      storage: {
        engine: 'sqlite',
        database: this.dir ? path.join(this.dir, DB_FILENAME) : null,
        dataDir: this.dir,
        pointerConfig: configPath(),
        manifest: manifestPath(),
        reservedWorkspace: 'process cwd (future tool workspace — never the data area)',
      },
      paths: {
        database: DB_FILENAME,
        media: 'media',
      },
    };
  }

  writeManifest() {
    this._manifest = this.manifest();
    try {
      const p = manifestPath();
      fs.mkdirSync(path.dirname(p), { recursive: true });
      const tmp = p + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this._manifest, null, 2));
      fs.renameSync(tmp, p);
    } catch {}
    if (this.dir) {
      try { fs.mkdirSync(path.join(this.dir, 'media'), { recursive: true }); } catch {}
    }
    return this._manifest;
  }

  getManifest() { return this._manifest || this.manifest(); }
  get memoryOnly() { return !this.dir; }

  provider(id) { return this.state.providers.providers.find((p) => p.id === id) || null; }
  activeProvider() { return this.provider(this.state.providers.active.providerId); }
  keyOf(provider) {
    if (!provider || !provider.keyCipher) return null;
    return keys.decrypt(provider.keyCipher);
  }

  #writeKey(key) {
    transaction(this.db, () => {
      if (key === 'settings') this.#writeSettings(this.state.settings);
      else if (key === 'providers') this.#writeProviders(this.state.providers);
      else if (key === 'chats') this.#writeChats(this.state.chats);
      else throw new Error(`Unknown state key “${key}”.`);
    });
  }

  #queueFile() { return this.dir ? path.join(this.dir, QUEUE_FILENAME) : null; }

  #journalAppend(key) {
    const file = this.#queueFile();
    if (!file) return;
    try {
      const value = key === 'settings' ? this.state.settings : key === 'providers' ? this.state.providers : this.state.chats;
      fs.appendFileSync(file, JSON.stringify({ ts: new Date().toISOString(), key, value }) + '\n');
    } catch { /* journal is best-effort; the drain below is the source of truth */ }
  }

  #journalTruncate() {
    const file = this.#queueFile();
    if (!file) return;
    try { fs.writeFileSync(file, ''); } catch {}
  }

  #scheduleDrain() {
    if (this._drainScheduled) return;
    this._drainScheduled = true;
    setImmediate(() => this.#drain());
  }

  #drain() {
    this._drainScheduled = false;
    if (!this.dir || !this.db) { this._queue.length = 0; return; }
    if (this._writeBusy) { this._drainScheduled = true; return; }
    this._writeBusy = true;
    try {
      const keys = [...new Set(this._queue)];
      this._queue.length = 0;
      for (const key of keys) this.#writeKey(key);
      this.#journalTruncate();
    } catch { /* keep the journal so nothing is lost; retry on next enqueue */ }
    finally {
      this._writeBusy = false;
      if (this._queue.length) this.#scheduleDrain();
    }
  }

  /** Synchronous flush — used before migrations, wipes and shutdown. */
  flushWrites() {
    if (this._queue.length) this.#drain();
  }

  /** Enqueue a state slice for writing (coalesced, journaled, crash-safe). */
  persist(key) {
    if (!this.dir || !this.db) return;
    this.#journalAppend(key);
    if (!this._queue.includes(key)) this._queue.push(key);
    this.#scheduleDrain();
  }

  /** Immediate durable write (legacy/migration paths). */
  persistSync(key) {
    if (!this.dir || !this.db) return;
    this.flushWrites();
    this.#writeKey(key);
  }

  #recoverJournal() {
    const file = this.#queueFile();
    if (!file || !fs.existsSync(file)) return 0;
    let lines = [];
    try { lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean); } catch { return 0; }
    if (!lines.length) return 0;
    const keys = [];
    for (const line of lines) {
      let rec = null;
      try { rec = JSON.parse(line); } catch { continue; }
      if (!rec || !rec.key || rec.value === undefined) continue;
      if (rec.key === 'settings') this.state.settings = rec.value;
      else if (rec.key === 'providers') this.state.providers = rec.value;
      else if (rec.key === 'chats') this.state.chats = rec.value;
      else continue;
      if (!keys.includes(rec.key)) keys.push(rec.key);
    }
    for (const key of keys) { try { this.#writeKey(key); } catch {} }
    this.#journalTruncate();
    return keys.length;
  }

  set(key, value) {
    this.state[key] = value;
    this.persist(key);
    return this.state[key];
  }

  listLogs({ limit = 500, chatId = null, traceIds = [] } = {}) {
    if (!this.db) return [];
    let sql = 'SELECT id, ts, mode, trace_id, chat_id, provider_id, kind, payload_json FROM request_logs';
    const params = [];
    const where = [];
    if (chatId) { where.push('chat_id = ?'); params.push(chatId); }
    if (traceIds.length) { where.push(`trace_id IN (${traceIds.map(() => '?').join(',')})`); params.push(...traceIds); }
    if (where.length) sql += ` WHERE ${where.join(' AND ')}`;
    sql += ' ORDER BY id DESC LIMIT ?';
    params.push(Math.min(5000, Math.max(1, Number(limit) || 500)));
    const rows = this.db.prepare(sql).all(...params);
    return rows.map((row) => {
      const raw = parseJson(row.payload_json, {});
      let entry = raw;
      if (row.mode === 'detailed-encrypted') {
        // BUGFIX(1.7.0): decryptDetailed() returns the plaintext *JSON string*.
        // Spreading that string into an object produced character-indexed
        // garbage, which is why encrypted entries rendered as anonymous
        // "event" rows whose metadata was just {"_encrypted": true} and why
        // they all shared one log id (opening one opened them all).
        try {
          const parsed = parseJson(keys.decryptDetailed(raw), null);
          entry = parsed && typeof parsed === 'object' ? parsed : { ts: row.ts, kind: row.kind, error: 'Detailed log payload was not valid JSON.' };
        } catch {
          entry = { ts: row.ts, kind: row.kind, error: 'Detailed log could not be decrypted on this machine.' };
        }
      }
      // Always carry the stable row identity + journal columns so the UI can
      // key rows uniquely even when a payload fails to decode.
      return {
        id: row.id,
        ts: entry.ts || row.ts,
        kind: entry.kind || row.kind,
        providerId: entry.providerId !== undefined ? entry.providerId : row.provider_id,
        traceId: entry.traceId !== undefined ? entry.traceId : row.trace_id,
        chatId: entry.chatId !== undefined ? entry.chatId : row.chat_id,
        ...entry,
        _encrypted: row.mode === 'detailed-encrypted',
      };
    });
  }

  /** Cheap journal revision stamp: changes whenever a log row is appended. */
  logsRev() {
    if (!this.db) return { rev: 0, count: 0 };
    try {
      const row = this.db.prepare('SELECT MAX(id) AS last, COUNT(*) AS count FROM request_logs').get();
      return { rev: Number(row?.last || 0), count: Number(row?.count || 0) };
    } catch {
      return { rev: 0, count: 0 };
    }
  }

  /** Upsert a single chat (streaming hot path) instead of rewriting them all. */
  upsertChat(chat, activeId) {
    if (!chat || !chat.id) return false;
    this.state.chats.activeId = typeof activeId === 'string' ? activeId : this.state.chats.activeId;
    const list = this.state.chats.chats;
    const idx = list.findIndex((c) => c.id === chat.id);
    if (idx >= 0) list[idx] = chat; else list.unshift(chat);
    this.persist('chats');
    return true;
  }

  appendLog(envelope, mode) {
    if (!this.db) return;
    try {
      const stored = mode === 'detailed-encrypted' ? keys.encryptDetailed(envelope) : envelope;
      this.db.prepare('INSERT INTO request_logs(ts, mode, trace_id, chat_id, provider_id, kind, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)').run(
        envelope.ts || now(),
        mode,
        envelope.traceId || null,
        envelope.chatId || null,
        envelope.providerId || null,
        envelope.kind || null,
        json(stored, {}),
      );
    } catch {}
  }

  clearLogs() {
    if (!this.db) return;
    try { this.db.prepare('DELETE FROM request_logs').run(); } catch {}
  }

  /* 1.8.0 log retention (issue 12): purge request logs older than the
     per-category retention window. `rules` = { allDays, apiDays, toolsDays,
     configDays } — null/0 means keep forever. Returns rows removed. */
  static logCategoryOf(kind) {
    const k = String(kind || '').toLowerCase();
    if (k.startsWith('tool')) return 'tools';
    if (['chat', 'chat-fallback', 'model-test', 'model-test-batch', 'provider-test', 'provider-test-all', 'models'].includes(k)) return 'api';
    return 'config';
  }
  purgeLogs(rules = {}) {
    if (!this.db) return 0;
    const cutoffFor = (days) => {
      const d = Number(days);
      if (!Number.isFinite(d) || d <= 0) return null;
      return new Date(Date.now() - d * 86400000).toISOString();
    };
    const allCut = cutoffFor(rules.allDays);
    const cuts = { api: cutoffFor(rules.apiDays), tools: cutoffFor(rules.toolsDays), config: cutoffFor(rules.configDays) };
    let removed = 0;
    try {
      const rows = this.db.prepare('SELECT id, ts, kind FROM request_logs').all();
      const ids = [];
      for (const row of rows) {
        const cat = Store.logCategoryOf(row.kind);
        const cut = cuts[cat] || allCut;
        const effective = cut && allCut ? (cut < allCut ? cut : allCut) : (cut || allCut);
        if (effective && String(row.ts) < effective) ids.push(row.id);
      }
      if (ids.length) {
        transaction(this.db, () => {
          const del = this.db.prepare('DELETE FROM request_logs WHERE id = ?');
          for (const id of ids) del.run(id);
        });
        removed = ids.length;
      }
    } catch {}
    return removed;
  }

  saveConversationSummary({ id = freshId('sum'), chatId, summary, modelName = null, messageStartId = null, messageEndId = null, version = 1 }) {
    if (!this.db || !chatId) throw new Error('chatId is required for a conversation summary.');
    const ts = now();
    this.db.prepare(`INSERT INTO conversation_summaries(id, chat_id, summary, model_name, message_start_id, message_end_id, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, model_name=excluded.model_name, message_start_id=excluded.message_start_id, message_end_id=excluded.message_end_id, version=excluded.version, updated_at=excluded.updated_at`).run(id, chatId, summary || '', modelName, messageStartId, messageEndId, version, ts, ts);
    return id;
  }

  latestConversationSummary(chatId) {
    if (!this.db) return null;
    const row = this.db.prepare('SELECT * FROM conversation_summaries WHERE chat_id = ? ORDER BY updated_at DESC LIMIT 1').get(chatId);
    if (!row) return null;
    return { ...row };
  }

  saveMemory(memory) {
    if (!this.db) throw new Error('Memory persistence requires a storage area.');
    if (!MEMORY_TYPES.includes(memory.memoryType)) throw new Error(`Unknown memory type “${memory.memoryType}”.`);
    const id = memory.id || freshId('mem');
    const ts = now();
    this.db.prepare(`INSERT INTO memories(id, memory_type, scope_type, scope_id, memory_key, content, value_json, source, confidence, importance, created_at, updated_at, last_confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET memory_type=excluded.memory_type, scope_type=excluded.scope_type, scope_id=excluded.scope_id, memory_key=excluded.memory_key, content=excluded.content, value_json=excluded.value_json, source=excluded.source, confidence=excluded.confidence, importance=excluded.importance, updated_at=excluded.updated_at, last_confirmed_at=excluded.last_confirmed_at`).run(
      id,
      memory.memoryType,
      memory.scopeType || null,
      memory.scopeId || null,
      memory.key || null,
      memory.content || '',
      json(memory.value || {}),
      memory.source || null,
      memory.confidence == null ? null : Number(memory.confidence),
      memory.importance == null ? null : Number(memory.importance),
      ts,
      ts,
      memory.lastConfirmedAt || null,
    );
    return id;
  }

  saveEmbedding({ id = freshId('emb'), ownerType, ownerId, modelName, providerId = null, vector, metadata = {} }) {
    if (!this.db) throw new Error('Embedding persistence requires a storage area.');
    const values = vectorFromJson(vector);
    if (!values.length) throw new Error('vector must contain at least one numeric value.');
    if (ownerType === 'message') {
      this.db.prepare('INSERT INTO message_embeddings(id, message_id, model_name, provider_id, dimensions, vector_blob, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, ownerId, modelName, providerId, values.length, encodeVector(values), now(), json(metadata));
    } else if (ownerType === 'memory') {
      this.db.prepare('INSERT INTO memory_embeddings(id, memory_id, model_name, provider_id, dimensions, vector_blob, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, ownerId, modelName, providerId, values.length, encodeVector(values), now(), json(metadata));
    } else if (ownerType === 'asset') {
      this.db.prepare('INSERT INTO asset_embeddings(id, asset_id, model_name, provider_id, dimensions, vector_blob, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, ownerId, modelName, providerId, values.length, encodeVector(values), now(), json(metadata));
    } else {
      throw new Error(`Unsupported embedding owner type “${ownerType}”.`);
    }
    return id;
  }

  readEmbedding(ownerType, ownerId, modelName) {
    if (!this.db) return null;
    const table = ownerType === 'message' ? 'message_embeddings' : ownerType === 'memory' ? 'memory_embeddings' : ownerType === 'asset' ? 'asset_embeddings' : null;
    if (!table) return null;
    const key = ownerType === 'message' ? 'message_id' : ownerType === 'memory' ? 'memory_id' : 'asset_id';
    const row = this.db.prepare(`SELECT * FROM ${table} WHERE ${key} = ? AND model_name = ? ORDER BY created_at DESC LIMIT 1`).get(ownerId, modelName);
    return row ? { ...row, vector: decodeVector(row.vector_blob), metadata: parseJson(row.metadata_json, {}) } : null;
  }

  saveAsset(asset) {
    if (!this.db) throw new Error('Asset persistence requires a storage area.');
    const id = asset.id || freshId('asset');
    const ts = now();
    this.db.prepare(`INSERT INTO assets(id, chat_id, message_id, kind, mime_type, filename, size_bytes, sha256, storage_path, short_description, detailed_description, ocr_text, transcript, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET chat_id=excluded.chat_id, message_id=excluded.message_id, kind=excluded.kind, mime_type=excluded.mime_type, filename=excluded.filename, size_bytes=excluded.size_bytes, sha256=excluded.sha256, storage_path=excluded.storage_path, short_description=excluded.short_description, detailed_description=excluded.detailed_description, ocr_text=excluded.ocr_text, transcript=excluded.transcript, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at`).run(
      id, asset.chatId || null, asset.messageId || null, asset.kind || 'file', asset.mimeType || null, asset.filename || null,
      asset.sizeBytes == null ? null : Number(asset.sizeBytes), asset.sha256 || null, asset.storagePath, asset.shortDescription || null,
      asset.detailedDescription || null, asset.ocrText || null, asset.transcript || null, json(asset.metadata || {}), ts, ts,
    );
    return id;
  }

  setChatContextState(chatId, state) {
    if (!this.db) return;
    const ts = now();
    this.db.prepare(`INSERT INTO chat_context_state(chat_id, model_name, provider_id, context_tokens_estimate, reserved_output_tokens, compacted_at, revision, state_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET model_name=excluded.model_name, provider_id=excluded.provider_id, context_tokens_estimate=excluded.context_tokens_estimate, reserved_output_tokens=excluded.reserved_output_tokens, compacted_at=excluded.compacted_at, revision=excluded.revision, state_json=excluded.state_json, updated_at=excluded.updated_at`).run(
      chatId,
      state.modelName || null,
      state.providerId || null,
      Number(state.contextTokensEstimate) || 0,
      state.reservedOutputTokens == null ? null : Number(state.reservedOutputTokens),
      state.compactedAt || null,
      Number(state.revision) || 0,
      json(state.state || {}),
      ts,
    );
  }

  getChatContextState(chatId) {
    if (!this.db) return null;
    const row = this.db.prepare('SELECT * FROM chat_context_state WHERE chat_id = ?').get(chatId);
    return row ? { ...row, state: parseJson(row.state_json, {}) } : null;
  }

  #directoryFingerprint(dir) {
    if (!fs.existsSync(dir)) return [];
    const rows = [];
    const walk = (current, prefix = '') => {
      for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
        const rel = path.join(prefix, entry.name);
        const full = path.join(current, entry.name);
        if (entry.isDirectory()) walk(full, rel);
        else if (entry.isFile()) {
          const hash = crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
          rows.push([rel, fs.statSync(full).size, hash]);
        }
      }
    };
    walk(dir);
    return rows.sort((a, b) => a[0].localeCompare(b[0]));
  }

  migrateTo(newDir) {
    this.flushWrites();
    const oldDir = this.dir;
    const target = newDir || null;
    // 1.8.0: same-area moves are a no-op with a COMPLETE report shape — the
    // UI reads report.copied/removedOld and used to crash ("Cannot read
    // properties of undefined (reading 'length')") on the short form.
    const samePath = (a, b) => {
      if (!a || !b) return a === b;
      try { return path.resolve(a) === path.resolve(b); } catch { return a === b; }
    };
    if (samePath(target, oldDir)) {
      return { from: oldDir, to: target, switched: false, reason: 'same area', copied: [], verified: true, removedOld: [] };
    }
    const report = { from: oldDir, to: target, copied: [], verified: false, switched: false, removedOld: [] };
    const snapshot = JSON.parse(JSON.stringify(this.state));

    if (target) {
      fs.mkdirSync(target, { recursive: true });
      const targetDb = openDatabase(target);
      seedModes(targetDb);
      try {
        this.#writeAllStateInto(targetDb, snapshot);
        const verified = this.#readAllStateFrom(targetDb);
        const aC = this.#migrationComparable(snapshot);
        const bC = this.#migrationComparable(verified);
        if (!deepEq(aC, bC)) {
          if (process.env.ARCHX_MIG_DEBUG) {
            const walk = (a, b, p) => {
              if (a && b && typeof a === 'object' && typeof b === 'object') {
                const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
                for (const k of keys) walk(a[k], b[k], p + '.' + k);
                return;
              }
              if (a !== b) console.error('DIFF', p, '=>', JSON.stringify(a)?.slice(0,120), '!==', JSON.stringify(b)?.slice(0,120));
            };
            walk(aC, bC, '$');
          }
          throw new Error('Verification failed for SQLite data; old area left untouched.');
        }
        report.copied.push(DB_FILENAME);
        if (oldDir && fs.existsSync(path.join(oldDir, 'media'))) {
          fs.rmSync(path.join(target, 'media'), { recursive: true, force: true });
          fs.cpSync(path.join(oldDir, 'media'), path.join(target, 'media'), { recursive: true });
          if (!deepEq(this.#directoryFingerprint(path.join(oldDir, 'media')), this.#directoryFingerprint(path.join(target, 'media')))) {
            throw new Error('Verification failed for media files — old area left untouched.');
          }
          report.copied.push('media/');
        }
      } finally {
        try { targetDb.exec('PRAGMA wal_checkpoint(TRUNCATE)'); } catch {}
        closeQuietly(targetDb);
      }
      report.verified = true;
    } else {
      report.verified = true;
    }

    closeQuietly(this.db);
    writePointer(target);
    this.dir = target;
    this.db = target ? openDatabase(target) : null;
    this.state = target ? this.#readAllStateFrom(this.db) : DEFAULTS();
    report.switched = true;
    this.writeManifest();

    if (oldDir && oldDir !== target) {
      for (const f of [...LEGACY_FILES, DB_FILENAME]) {
        try { fs.unlinkSync(path.join(oldDir, f)); report.removedOld.push(f); } catch {}
        try { fs.unlinkSync(path.join(oldDir, `${f}-wal`)); } catch {}
        try { fs.unlinkSync(path.join(oldDir, `${f}-shm`)); } catch {}
      }
      try { fs.rmSync(path.join(oldDir, 'media'), { recursive: true, force: true }); } catch {}
      try { fs.rmdirSync(oldDir); } catch {}
    }
    return report;
  }

  #writeAllStateInto(db, state) {
    const originalDb = this.db;
    this.db = db;
    try { transaction(db, () => { this.#writeSettings(state.settings); this.#writeProviders(state.providers); this.#writeChats(state.chats); }); }
    finally { this.db = originalDb; }
  }

  #readAllStateFrom(db) {
    const originalDb = this.db;
    this.db = db;
    try {
      const current = this.state;
      this.#loadFromDb();
      const loaded = this.state;
      this.state = current;
      return loaded;
    } finally { this.db = originalDb; }
  }

  #deleteAssets(filter) {
    if (!this.db) return 0;
    const rows = this.db.prepare('SELECT id, storage_path, mime_type FROM assets').all();
    const targets = rows.filter(filter);
    if (!targets.length) return 0;
    const ids = new Set(targets.map((r) => r.id));
    transaction(this.db, () => {
      for (const id of ids) {
        this.db.prepare('DELETE FROM asset_embeddings WHERE asset_id = ?').run(id);
        this.db.prepare('DELETE FROM assets WHERE id = ?').run(id);
      }
    });
    for (const row of targets) {
      try {
        if (row.storage_path && this.dir && row.storage_path.startsWith(this.dir)) fs.unlinkSync(row.storage_path);
      } catch {}
    }
    return targets.length;
  }

  /**
   * Scoped wipes (1.7.2):
   *  all             — everything (previous behaviour)
   *  keep-providers  — chats/logs/memories/settings reset; providers, keys,
   *                    models and profiles survive
   *  chats           — conversations only; keys, settings and artifacts stay
   *  media-images / media-videos / media-docs — one asset class + its files
   *  library         — every asset record + all media files
   */
  wipe(scope = 'all') {
    this.flushWrites();
    const dir = this.dir;
    if (scope === 'keep-providers' || scope === 'chats') {
      if (this.db) {
        const tables = scope === 'chats'
          ? ['messages', 'chats', 'conversation_summaries', 'chat_context_state']
          : ['messages', 'chats', 'conversation_summaries', 'chat_context_state', 'request_logs', 'memories', 'memory_embeddings', 'message_embeddings'];
        transaction(this.db, () => { for (const t of tables) this.db.prepare(`DELETE FROM ${t}`).run(); });
      }
      this.state.chats = DEFAULTS().chats;
      // 1.7.3: "keep providers & keys" also keeps everything personal —
      // personalization, agent name, theme, prompts and generation prefs.
      // Only chat-generated data (conversations, logs, memories) goes.
      this.persistSync('chats');
      this.writeManifest();
      return;
    }
    if (scope === 'media-images' || scope === 'media-videos' || scope === 'media-docs' || scope === 'library') {
      const group = (r) => scope === 'library' ? true
        : scope === 'media-images' ? String(r.mime_type || '').startsWith('image/')
        : scope === 'media-videos' ? String(r.mime_type || '').startsWith('video/')
        : !String(r.mime_type || '').startsWith('image/') && !String(r.mime_type || '').startsWith('video/');
      this.#deleteAssets(group);
      if (scope === 'library' && dir) {
        try {
          for (const f of fs.readdirSync(path.join(dir, 'media'))) {
            try { fs.rmSync(path.join(dir, 'media', f), { recursive: true, force: true }); } catch {}
          }
        } catch {}
      }
      return;
    }
    // scope === 'all' (default, unchanged behaviour)
    if (this.db) {
      const tables = ['request_logs', 'chat_context_state', 'asset_embeddings', 'assets', 'memory_embeddings', 'message_embeddings', 'conversation_summaries', 'messages', 'chats', 'system_prompts', 'profile_items', 'profiles', 'model_endpoints', 'models', 'providers', 'modes', 'app_state', 'settings'];
      transaction(this.db, () => { for (const table of tables) this.db.prepare(`DELETE FROM ${table}`).run(); });
      this.#ensureModes();
    }
    this.state = DEFAULTS();
    if (dir) {
      for (const file of [...LEGACY_FILES]) {
        try { fs.unlinkSync(path.join(dir, file)); } catch {}
      }
      try { fs.rmSync(path.join(dir, 'media'), { recursive: true, force: true }); } catch {}
      for (const legacyDir of LEGACY_DIRS) { try { fs.rmSync(path.join(dir, legacyDir), { recursive: true, force: true }); } catch {} }
      try { fs.mkdirSync(path.join(dir, 'media'), { recursive: true }); } catch {}
    }
    this.persist('settings');
    this.persist('providers');
    this.persist('chats');
    this.writeManifest();
  }

  close() {
    if (!this.db) return;
    this.flushWrites();
    try { this.db.exec('PRAGMA wal_checkpoint(TRUNCATE)'); } catch {}
    closeQuietly(this.db);
    this.db = null;
  }
}

module.exports = { Store, LEGACY_FILES, FILES: [DB_FILENAME] };
