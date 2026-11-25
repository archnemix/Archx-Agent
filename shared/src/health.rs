//! Purpose: Rotates vault keys round-robin and rests failing ones, and tracks per-model health for auto-disable.
//!
//! Two independent pieces of state:
//!   * `KeyHealthSet` — one entry per vault key id (never the key itself), with a
//!     failure count, a rest deadline and the provider's reason. A key that hit a
//!     key-specific failure (auth, quota, rate limit) is skipped until its
//!     deadline; a key that succeeded comes straight back.
//!   * `ModelHealthSet` — per model id: enabled/disabled, why, and the last
//!     failure. Auto-disable is opt-in and only acts on model-specific errors
//!     (retired id, no access) or on repeated provider failures, never on a
//!     single transport timeout.

use serde_json::{json, Value};

use crate::diagnostics::{Diagnosis, Owner};

/// Consecutive provider-side failures before a model is auto-disabled.
pub const PROVIDER_FAILURE_LIMIT: u32 = 3;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct KeySlot {
    pub id: u64,
    pub failures: u32,
    pub cooldown_until: u64,
    pub reason: String,
    pub last_used: u64,
}

impl KeySlot {
    pub fn cooling(&self, now: u64) -> bool {
        self.cooldown_until > now
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct KeyHealthSet {
    pub slots: Vec<KeySlot>,
    /// Rotation position, independent of the vault's ordering.
    pub cursor: usize,
    /// When true, a request retries once with the next healthy key after a
    /// key-specific failure instead of failing the turn.
    pub auto_rotate: bool,
}

impl KeyHealthSet {
    pub fn new() -> Self {
        Self { slots: Vec::new(), cursor: 0, auto_rotate: true }
    }

    /// Keeps one slot per vault key id, preserving existing state.
    pub fn sync(&mut self, ids: &[u64]) {
        self.slots.retain(|slot| ids.contains(&slot.id));
        for id in ids {
            if !self.slots.iter().any(|slot| slot.id == *id) {
                self.slots.push(KeySlot { id: *id, ..KeySlot::default() });
            }
        }
        self.slots.sort_by_key(|slot| slot.id);
        if self.slots.is_empty() { self.cursor = 0; }
        else { self.cursor %= self.slots.len(); }
    }

    pub fn slot(&self, id: u64) -> Option<&KeySlot> {
        self.slots.iter().find(|slot| slot.id == id)
    }

    /// Clears elapsed rest windows; returns how many keys became usable.
    pub fn expire(&mut self, now: u64) -> usize {
        let mut freed = 0;
        for slot in &mut self.slots {
            if slot.cooldown_until != 0 && slot.cooldown_until <= now {
                slot.cooldown_until = 0;
                slot.reason.clear();
                slot.failures = 0;
                freed += 1;
            }
        }
        freed
    }

    /// Chooses the next key: round-robin over keys not resting. When every key
    /// is resting, chooses the one whose window ends first (still returns it,
    /// because sending with a far-future key would just fail again).
    pub fn pick(&self, now: u64) -> Option<(usize, u64)> {
        if self.slots.is_empty() { return None; }
        for step in 0..self.slots.len() {
            let position = (self.cursor + step) % self.slots.len();
            let slot = &self.slots[position];
            if !slot.cooling(now) {
                return Some((position, slot.id));
            }
        }
        let soonest = self.slots.iter().enumerate()
            .min_by_key(|(_, slot)| slot.cooldown_until)
            .map(|(position, slot)| (position, slot.id));
        soonest
    }

    /// Advances the rotation after a pick.
    pub fn advance(&mut self) {
        if !self.slots.is_empty() {
            self.cursor = (self.cursor + 1) % self.slots.len();
        }
    }

    /// Moves the rotation to just after `position`, so the next pick is the next
    /// key rather than the one just used.
    pub fn advance_from(&mut self, position: usize) {
        if !self.slots.is_empty() {
            self.cursor = (position + 1) % self.slots.len();
        }
    }

    pub fn record_success(&mut self, id: u64, now: u64) {
        if let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) {
            slot.failures = 0;
            slot.cooldown_until = 0;
            slot.reason.clear();
            slot.last_used = now;
        }
    }

    /// Records a key-specific failure. Returns true when the key was rested.
    pub fn record_failure(&mut self, id: u64, diagnosis: &Diagnosis, now: u64) -> bool {
        let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) else { return false; };
        slot.failures = slot.failures.saturating_add(1);
        slot.last_used = now;
        if diagnosis.retries_key() {
            let seconds = diagnosis.cooldown.unwrap_or(crate::diagnostics::KEY_COOLDOWN_SECS);
            slot.cooldown_until = now.saturating_add(seconds);
            slot.reason = diagnosis.summary.clone();
            return true;
        }
        false
    }

    /// A model-specific failure proves nothing about the key, so no cooldown.
    pub fn record_neutral(&mut self, id: u64) {
        if let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) {
            slot.last_used = crate::storage::now_secs();
        }
    }

    pub fn healthy(&self, now: u64) -> usize {
        self.slots.iter().filter(|slot| !slot.cooling(now)).count()
    }

    pub fn to_json(&self) -> Value {
        json!({
            "auto_rotate": self.auto_rotate,
            "cursor": self.cursor,
            "keys": self.slots.iter().map(|slot| json!({
                "id": slot.id,
                "failures": slot.failures,
                "cooldown_until": slot.cooldown_until,
                "reason": slot.reason,
            })).collect::<Vec<_>>(),
        })
    }

    pub fn from_json(value: &Value) -> Self {
        let mut set = Self::new();
        set.auto_rotate = value.get("auto_rotate").and_then(Value::as_bool).unwrap_or(true);
        set.cursor = value.get("cursor").and_then(Value::as_u64).unwrap_or(0) as usize;
        if let Some(keys) = value.get("keys").and_then(Value::as_array) {
            for key in keys.iter().take(64) {
                let Some(id) = key.get("id").and_then(Value::as_u64).filter(|id| *id > 0) else { continue };
                set.slots.push(KeySlot {
                    id,
                    failures: key.get("failures").and_then(Value::as_u64).unwrap_or(0).min(99) as u32,
                    cooldown_until: key.get("cooldown_until").and_then(Value::as_u64).unwrap_or(0),
                    reason: key.get("reason").and_then(Value::as_str).unwrap_or("").chars().take(300).collect(),
                    last_used: 0,
                });
            }
            set.slots.sort_by_key(|slot| slot.id);
        }
        set
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ModelSlot {
    pub id: String,
    pub disabled: bool,
    pub reason: String,
    pub provider_failures: u32,
    pub last_failure: u64,
    pub last_success: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ModelHealthSet {
    pub slots: Vec<ModelSlot>,
    /// Opt-in: only acts on model-specific or repeated provider failures.
    pub auto_disable: bool,
}

impl ModelHealthSet {
    pub fn new() -> Self {
        Self { slots: Vec::new(), auto_disable: true }
    }

    pub fn sync(&mut self, ids: &[String]) {
        self.slots.retain(|slot| ids.contains(&slot.id));
        for id in ids {
            if !self.slots.iter().any(|slot| &slot.id == id) {
                self.slots.push(ModelSlot { id: id.clone(), ..ModelSlot::default() });
            }
        }
    }

    pub fn is_enabled(&self, id: &str) -> bool {
        self.slots.iter().find(|slot| slot.id == id).is_none_or(|slot| !slot.disabled)
    }

    pub fn slot(&self, id: &str) -> Option<&ModelSlot> {
        self.slots.iter().find(|slot| slot.id == id)
    }

    pub fn disable(&mut self, id: &str, reason: &str, now: u64) {
        if let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) {
            slot.disabled = true;
            slot.reason = reason.chars().take(240).collect();
            slot.last_failure = now;
        }
    }

    pub fn enable(&mut self, id: &str) {
        if let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) {
            slot.disabled = false;
            slot.reason.clear();
            slot.provider_failures = 0;
        }
    }

    pub fn record_success(&mut self, id: &str, now: u64) {
        if let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) {
            slot.provider_failures = 0;
            slot.last_success = now;
        }
    }

    /// Returns a user-facing note when the failure changed this model's state.
    pub fn record_failure(&mut self, id: &str, diagnosis: &Diagnosis, now: u64) -> Option<String> {
        let Some(slot) = self.slots.iter_mut().find(|slot| slot.id == id) else { return None };
        slot.last_failure = now;
        if diagnosis.owner == Owner::Key {
            // The key is at fault; the model keeps working with another key.
            return None;
        }
        if diagnosis.retries_model() {
            let reason = diagnosis.summary.clone();
            if self.auto_disable {
                slot.disabled = true;
                slot.reason = reason.clone();
                return Some(format!("Auto-disabled \"{id}\": {reason}"));
            }
            return Some(format!("\"{id}\" looks unavailable: {reason}"));
        }
        slot.provider_failures = slot.provider_failures.saturating_add(1);
        if self.auto_disable && slot.provider_failures >= PROVIDER_FAILURE_LIMIT {
            slot.disabled = true;
            slot.reason = format!("{} consecutive provider failures; last: {}", slot.provider_failures, diagnosis.summary);
            return Some(format!("Auto-disabled \"{id}\" after {} consecutive provider failures.", slot.provider_failures));
        }
        None
    }

    pub fn disabled_ids(&self) -> Vec<&str> {
        self.slots.iter().filter(|slot| slot.disabled).map(|slot| slot.id.as_str()).collect()
    }

    pub fn to_json(&self) -> Value {
        json!({
            "auto_disable": self.auto_disable,
            "models": self.slots.iter().map(|slot| json!({
                "id": slot.id,
                "disabled": slot.disabled,
                "reason": slot.reason,
                "provider_failures": slot.provider_failures,
                "last_failure": slot.last_failure,
                "last_success": slot.last_success,
            })).collect::<Vec<_>>(),
        })
    }

    pub fn from_json(value: &Value) -> Self {
        let mut set = Self::new();
        set.auto_disable = value.get("auto_disable").and_then(Value::as_bool).unwrap_or(true);
        if let Some(models) = value.get("models").and_then(Value::as_array) {
            for model in models.iter().take(4096) {
                let Some(id) = model.get("id").and_then(Value::as_str).filter(|id| !id.is_empty()) else { continue };
                set.slots.push(ModelSlot {
                    id: id.chars().take(200).collect(),
                    disabled: model.get("disabled").and_then(Value::as_bool).unwrap_or(false),
                    reason: model.get("reason").and_then(Value::as_str).unwrap_or("").chars().take(300).collect(),
                    provider_failures: model.get("provider_failures").and_then(Value::as_u64).unwrap_or(0).min(99) as u32,
                    last_failure: model.get("last_failure").and_then(Value::as_u64).unwrap_or(0),
                    last_success: model.get("last_success").and_then(Value::as_u64).unwrap_or(0),
                });
            }
        }
        set
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::diagnostics::{from_http, transport};

    #[test]
    fn rotation_skips_a_resting_key_and_wraps() {
        let mut set = KeyHealthSet::new();
        set.sync(&[1, 2, 3]);
        assert_eq!(set.pick(0), Some((0, 1)));
        set.advance();
        // Key 2 hits a quota error and rests: rotation skips it entirely.
        assert!(set.record_failure(2, &from_http(429, Some("quota exceeded")), 100));
        assert_eq!(set.healthy(100), 2);
        let (position, id) = set.pick(100).expect("a healthy key");
        assert_eq!(id, 3, "the resting key is skipped, not handed out again");
        set.advance_from(position);
        // With key 3 used, the rotation wraps to key 1 and still never key 2.
        let (position, id) = set.pick(100).expect("a healthy key");
        assert_eq!(id, 1);
        set.advance_from(position);
        assert_eq!(set.pick(100).map(|(_, id)| id), Some(3));
        // After the window elapses the key returns with a clean count.
        assert_eq!(set.expire(100 + crate::diagnostics::KEY_COOLDOWN_SECS), 1);
        assert_eq!(set.healthy(500), 3);
        assert_eq!(set.pick(500), Some((1, 2)));
    }

    #[test]
    fn when_every_key_is_resting_the_soonest_one_is_chosen() {
        let mut set = KeyHealthSet::new();
        set.sync(&[1, 2]);
        set.record_failure(1, &from_http(401, Some("invalid api key")), 0);
        let mut late = from_http(429, Some("rate limit"));
        late.cooldown = Some(900);
        set.record_failure(2, &late, 0);
        // Key 1 wakes first (300 s), so it is preferred over the 900 s key.
        assert_eq!(set.pick(0), Some((0, 1)));
    }

    #[test]
    fn model_and_provider_failures_do_not_bench_a_key() {
        let mut set = KeyHealthSet::new();
        set.sync(&[1]);
        assert!(!set.record_failure(1, &from_http(404, Some("model not found")), 0));
        assert!(!set.record_failure(1, &transport(true), 0));
        assert_eq!(set.healthy(0), 1);
        assert_eq!(set.slot(1).map(|slot| slot.failures), Some(2));
    }

    #[test]
    fn a_retired_model_is_disabled_but_a_single_timeout_is_not() {
        let mut set = ModelHealthSet::new();
        set.sync(&["vendor/a".into(), "vendor/b".into()]);
        assert!(set.auto_disable);
        let note = set.record_failure("vendor/a", &from_http(404, Some("this model has been decommissioned")), 10);
        assert!(note.is_some_and(|text| text.contains("Auto-disabled")));
        assert!(!set.is_enabled("vendor/a"));
        // One transport timeout is ours, not proof the model is gone.
        assert_eq!(set.record_failure("vendor/b", &transport(true), 10), None);
        assert!(set.is_enabled("vendor/b"));
        // Three consecutive provider failures do disable it; one timeout counts
        // as the first of them, because a timeout is not proof of anything yet.
        let overloaded = from_http(503, Some("overloaded"));
        assert_eq!(set.record_failure("vendor/b", &overloaded, 11), None);
        assert!(set.record_failure("vendor/b", &overloaded, 12).is_some());
        assert!(!set.is_enabled("vendor/b"));
        set.enable("vendor/b");
        assert!(set.is_enabled("vendor/b"));
        assert_eq!(set.disabled_ids(), vec!["vendor/a"]);
    }

    #[test]
    fn key_failures_never_disable_a_model_and_the_toggle_is_respected() {
        let mut set = ModelHealthSet::new();
        set.sync(&["vendor/a".into()]);
        assert_eq!(set.record_failure("vendor/a", &from_http(401, Some("invalid key")), 1), None);
        assert!(set.is_enabled("vendor/a"));
        set.auto_disable = false;
        let note = set.record_failure("vendor/a", &from_http(410, Some("model retired")), 2);
        assert!(note.is_some_and(|text| text.contains("looks unavailable")));
        assert!(set.is_enabled("vendor/a"));
    }

    #[test]
    fn health_json_round_trips_without_credentials() {
        let mut keys = KeyHealthSet::new();
        keys.sync(&[1, 2]);
        keys.record_failure(2, &from_http(429, Some("quota")), 50);
        let restored = KeyHealthSet::from_json(&keys.to_json());
        assert_eq!(restored.slots.len(), 2);
        assert_eq!(restored.slot(2).map(|slot| slot.cooldown_until), Some(50 + crate::diagnostics::KEY_COOLDOWN_SECS));
        assert_eq!(crate::storage::credential_field(&keys.to_json()), None);

        let mut models = ModelHealthSet::new();
        models.sync(&["vendor/a".into()]);
        models.disable("vendor/a", "retired", 5);
        let restored = ModelHealthSet::from_json(&models.to_json());
        assert!(!restored.is_enabled("vendor/a"));
        assert_eq!(crate::storage::credential_field(&models.to_json()), None);
        // Corrupt or hostile input degrades to an empty set instead of panicking.
        assert!(ModelHealthSet::from_json(&json!({"models": "nope"})).slots.is_empty());
        assert!(KeyHealthSet::from_json(&json!({"keys": [{"id": 0}, {"id": "x"}]})).slots.is_empty());
    }
}
