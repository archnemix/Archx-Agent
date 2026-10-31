'use strict';

const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

const DB_FILENAME = 'archx.db';
const SCHEMA_VERSION = 1;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS db_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS modes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  capabilities_json TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  adapter TEXT NOT NULL,
  base_url TEXT,
  key_cipher_json TEXT,
  default_model TEXT,
  free_only INTEGER NOT NULL DEFAULT 0,
  free_only_snapshot_json TEXT NOT NULL DEFAULT '[]',
  free_only_auto_hidden_json TEXT NOT NULL DEFAULT '[]',
  free_only_manual_enabled_json TEXT NOT NULL DEFAULT '[]',
  model_config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  family TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_endpoints (
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  endpoint_kind TEXT NOT NULL,
  remote_model_id TEXT NOT NULL,
  is_custom INTEGER NOT NULL DEFAULT 0,
  is_hidden INTEGER NOT NULL DEFAULT 0,
  is_enabled INTEGER NOT NULL DEFAULT 1,
  owned_by TEXT,
  endpoint_url TEXT,
  capabilities_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (provider_id, model_id, endpoint_kind),
  FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE,
  FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_model_endpoints_provider ON model_endpoints(provider_id);

CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  parked_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_items (
  profile_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 1,
  item_order INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (profile_id, provider_id, model_id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
  FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE,
  FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profile_items_profile ON profile_items(profile_id, priority, item_order);

CREATE TABLE IF NOT EXISTS system_prompts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  mode_id TEXT NOT NULL DEFAULT 'simple-chat',
  system_prompt_id TEXT,
  enabled_prompt_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  debug_trace_ids_json TEXT NOT NULL DEFAULT '[]',
  debug_events_json TEXT NOT NULL DEFAULT '[]',
  branches_json TEXT NOT NULL DEFAULT '[]',
  pinned INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (mode_id) REFERENCES modes(id),
  FOREIGN KEY (system_prompt_id) REFERENCES system_prompts(id)
);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  reasoning TEXT NOT NULL DEFAULT '',
  pending INTEGER NOT NULL DEFAULT 0,
  is_error INTEGER NOT NULL DEFAULT 0,
  ts INTEGER NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
  UNIQUE (chat_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, ordinal);

CREATE TABLE IF NOT EXISTS message_embeddings (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  provider_id TEXT,
  dimensions INTEGER NOT NULL,
  vector_blob BLOB NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_message_embeddings_message ON message_embeddings(message_id);

CREATE TABLE IF NOT EXISTS conversation_summaries (
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  summary TEXT NOT NULL,
  model_name TEXT,
  message_start_id TEXT,
  message_end_id TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_summaries_chat ON conversation_summaries(chat_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  scope_type TEXT,
  scope_id TEXT,
  memory_key TEXT,
  content TEXT NOT NULL,
  value_json TEXT NOT NULL DEFAULT '{}',
  source TEXT,
  confidence REAL,
  importance REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_type_scope ON memories(memory_type, scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(memory_key);

CREATE TABLE IF NOT EXISTS memory_embeddings (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  provider_id TEXT,
  dimensions INTEGER NOT NULL,
  vector_blob BLOB NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  chat_id TEXT,
  message_id TEXT,
  kind TEXT NOT NULL,
  mime_type TEXT,
  filename TEXT,
  size_bytes INTEGER,
  sha256 TEXT,
  storage_path TEXT NOT NULL,
  short_description TEXT,
  detailed_description TEXT,
  ocr_text TEXT,
  transcript TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE SET NULL,
  FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_chat ON assets(chat_id, created_at);

CREATE TABLE IF NOT EXISTS asset_embeddings (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  provider_id TEXT,
  dimensions INTEGER NOT NULL,
  vector_blob BLOB NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_asset_embeddings_asset ON asset_embeddings(asset_id);

CREATE TABLE IF NOT EXISTS chat_context_state (
  chat_id TEXT PRIMARY KEY,
  model_name TEXT,
  provider_id TEXT,
  context_tokens_estimate INTEGER NOT NULL DEFAULT 0,
  reserved_output_tokens INTEGER,
  compacted_at TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  state_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS request_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  mode TEXT NOT NULL,
  trace_id TEXT,
  chat_id TEXT,
  provider_id TEXT,
  kind TEXT,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_logs_ts ON request_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_chat ON request_logs(chat_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_trace ON request_logs(trace_id, ts DESC);
`;

function now() {
  return new Date().toISOString();
}

function json(value, fallback = null) {
  try {
    return JSON.stringify(value === undefined ? fallback : value);
  } catch {
    return JSON.stringify(fallback);
  }
}

function parseJson(value, fallback) {
  try {
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function encodeVector(values) {
  const arr = Array.from(values || [], Number);
  const buffer = Buffer.allocUnsafe(arr.length * 4);
  const view = new Float32Array(buffer.buffer, buffer.byteOffset, arr.length);
  view.set(arr);
  return buffer;
}

function decodeVector(buffer) {
  if (!buffer || typeof buffer.byteLength !== 'number') return [];
  const bytes = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  const view = new Float32Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 4));
  return Array.from(view);
}

function openDatabase(dataDir) {
  if (!dataDir) return null;
  fs.mkdirSync(dataDir, { recursive: true });
  const db = new DatabaseSync(path.join(dataDir, DB_FILENAME));
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec('PRAGMA foreign_keys = ON;');
  db.exec('PRAGMA busy_timeout = 5000;');
  db.exec(SCHEMA);
  // 1.7.2 migration: chats gained a branches column for alternate continuations
  const chatCols = db.prepare('PRAGMA table_info(chats)').all().map((c) => c.name);
  if (!chatCols.includes('branches_json')) {
    db.exec("ALTER TABLE chats ADD COLUMN branches_json TEXT NOT NULL DEFAULT '[]'");
  }
  // 1.8.0 migration: chats gained a pinned flag
  if (!chatCols.includes('pinned')) {
    db.exec("ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0");
  }
  // 1.8.0 migration: profiles gained a description
  const profileCols = db.prepare('PRAGMA table_info(profiles)').all().map((c) => c.name);
  if (!profileCols.includes('description')) {
    db.exec("ALTER TABLE profiles ADD COLUMN description TEXT NOT NULL DEFAULT ''");
  }
  if (!profileCols.includes('parked_json')) {
    db.exec("ALTER TABLE profiles ADD COLUMN parked_json TEXT NOT NULL DEFAULT '[]'");
  }
  db.prepare('INSERT OR IGNORE INTO db_meta(key, value_json) VALUES (?, ?)').run('schemaVersion', json(SCHEMA_VERSION));
  db.prepare('INSERT OR IGNORE INTO db_meta(key, value_json) VALUES (?, ?)').run('createdAt', json(now()));
  return db;
}

function transaction(db, fn) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const result = fn();
    db.exec('COMMIT');
    return result;
  } catch (err) {
    try { db.exec('ROLLBACK'); } catch {}
    throw err;
  }
}

module.exports = {
  DB_FILENAME,
  SCHEMA_VERSION,
  openDatabase,
  transaction,
  now,
  json,
  parseJson,
  encodeVector,
  decodeVector,
};
