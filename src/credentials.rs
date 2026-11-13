//! Purpose: Isolates provider credentials in OS-backed stores with no plaintext file fallback.
use zeroize::Zeroizing;

const SERVICE: &str = "ai.archnemix.archxlab.provider.v1";
const MAX_KEYS: usize = 64;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Provider {
    OpenRouter,
    Grok,
    Gemini,
}

impl Provider {
    pub const ALL: [Self; 3] = [Self::OpenRouter, Self::Grok, Self::Gemini];

    pub fn name(self) -> &'static str {
        match self {
            Self::OpenRouter => "OpenRouter",
            Self::Grok => "Grok (xAI)",
            Self::Gemini => "Gemini",
        }
    }

    fn id(self) -> &'static str {
        match self {
            Self::OpenRouter => "openrouter",
            Self::Grok => "xai",
            Self::Gemini => "gemini",
        }
    }
}

// Never include raw keyring errors in a UI message or log; providers can include
// implementation-specific details that are not safe to surface verbatim.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultError {
    Unavailable,
    InvalidKey,
    IndexCorrupt,
    MissingKey,
    LimitReached,
    PartialAdd,
    PartialRemoval,
}

impl VaultError {
    pub fn message(self) -> &'static str {
        match self {
            Self::Unavailable => "The OS credential store is unavailable or locked. No key was saved.",
            Self::InvalidKey => "Enter a key without whitespace or control characters.",
            Self::IndexCorrupt => "The credential index could not be read safely. No changes were made.",
            Self::MissingKey => "That key is no longer available in the OS credential store.",
            Self::LimitReached => "The per-provider key limit is 64.",
            Self::PartialAdd => "The index update and cleanup failed. A key may remain in the OS vault; stop and review its entries.",
            Self::PartialRemoval => "The key was deleted, but its index could not be updated. Retry cleanup before adding another.",
        }
    }
}

// The store adapter is intentionally small so state/failure tests never touch a
// developer's OS vault. All production writes use the platform's native store.
trait CredentialStore {
    fn get(&self, account: &str) -> Result<Option<Zeroizing<String>>, VaultError>;
    fn set(&self, account: &str, secret: &str) -> Result<(), VaultError>;
    fn delete(&self, account: &str) -> Result<(), VaultError>;
}

pub struct OsStore;

impl CredentialStore for OsStore {
    fn get(&self, account: &str) -> Result<Option<Zeroizing<String>>, VaultError> {
        let entry = keyring::Entry::new(SERVICE, account).map_err(|_| VaultError::Unavailable)?;
        match entry.get_password() {
            Ok(secret) => Ok(Some(Zeroizing::new(secret))),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err(VaultError::Unavailable),
        }
    }

    fn set(&self, account: &str, secret: &str) -> Result<(), VaultError> {
        keyring::Entry::new(SERVICE, account)
            .map_err(|_| VaultError::Unavailable)?
            .set_password(secret)
            .map_err(|_| VaultError::Unavailable)
    }

    fn delete(&self, account: &str) -> Result<(), VaultError> {
        keyring::Entry::new(SERVICE, account)
            .map_err(|_| VaultError::Unavailable)?
            .delete_credential()
            .map_err(|_| VaultError::Unavailable)
    }
}

pub struct Vault<S = OsStore> {
    store: S,
}

impl Vault<OsStore> {
    pub fn os() -> Self {
        Self { store: OsStore }
    }
}

impl<S: CredentialStore> Vault<S> {
    fn index_account(provider: Provider) -> String {
        format!("{}/index", provider.id())
    }

    fn key_account(provider: Provider, id: u64) -> String {
        format!("{}/key/{id}", provider.id())
    }

    pub fn list(&self, provider: Provider) -> Result<Vec<u64>, VaultError> {
        let Some(index) = self.store.get(&Self::index_account(provider))? else {
            return Ok(Vec::new());
        };
        let Some(rest) = index.strip_prefix("v1\n") else {
            return Err(VaultError::IndexCorrupt);
        };
        let mut ids = Vec::new();
        for line in rest.lines() {
            let id: u64 = line.parse().map_err(|_| VaultError::IndexCorrupt)?;
            if id == 0 || ids.last().is_some_and(|last| id <= *last) || ids.len() >= MAX_KEYS {
                return Err(VaultError::IndexCorrupt);
            }
            ids.push(id);
        }
        Ok(ids)
    }

    fn write_index(&self, provider: Provider, ids: &[u64]) -> Result<(), VaultError> {
        let mut index = String::from("v1\n");
        for id in ids {
            index.push_str(&format!("{id}\n"));
        }
        self.store.set(&Self::index_account(provider), &index)
    }

    pub fn add(&self, provider: Provider, secret: Zeroizing<String>) -> Result<u64, VaultError> {
        if secret.is_empty() || secret.chars().any(char::is_whitespace) || secret.chars().any(char::is_control) {
            return Err(VaultError::InvalidKey);
        }
        let mut ids = self.list(provider)?;
        if ids.len() >= MAX_KEYS {
            return Err(VaultError::LimitReached);
        }
        let id = ids.last().copied().unwrap_or(0).checked_add(1).ok_or(VaultError::LimitReached)?;
        let account = Self::key_account(provider, id);
        // Never overwrite an orphan from an interrupted index update or deletion.
        if self.store.get(&account)?.is_some() {
            return Err(VaultError::IndexCorrupt);
        }
        self.store.set(&account, &secret)?;
        ids.push(id);
        if let Err(error) = self.write_index(provider, &ids) {
            if self.store.delete(&account).is_err() {
                return Err(VaultError::PartialAdd);
            }
            return Err(error);
        }
        Ok(id)
    }

    pub fn remove(&self, provider: Provider, id: u64) -> Result<(), VaultError> {
        let mut ids = self.list(provider)?;
        if !ids.contains(&id) {
            return Err(VaultError::MissingKey);
        }
        self.store.delete(&Self::key_account(provider, id))?;
        ids.retain(|other| *other != id);
        self.write_index(provider, &ids).map_err(|_| VaultError::PartialRemoval)
    }

    // The closure may send the key in a TLS Authorization header or display it
    // briefly. The retrieved allocation is zeroized after the closure returns;
    // HTTP/UI libraries can still make copies beyond this boundary.
    pub fn with_key<R>(&self, provider: Provider, id: u64, use_key: impl FnOnce(&str) -> R) -> Result<R, VaultError> {
        if !self.list(provider)?.contains(&id) {
            return Err(VaultError::MissingKey);
        }
        let secret = self.store.get(&Self::key_account(provider, id))?.ok_or(VaultError::MissingKey)?;
        Ok(use_key(&secret))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::HashMap;

    #[derive(Default)]
    struct FakeStore(RefCell<HashMap<String, String>>);
    impl CredentialStore for FakeStore {
        fn get(&self, key: &str) -> Result<Option<Zeroizing<String>>, VaultError> {
            Ok(self.0.borrow().get(key).cloned().map(Zeroizing::new))
        }
        fn set(&self, key: &str, value: &str) -> Result<(), VaultError> {
            self.0.borrow_mut().insert(key.into(), value.into());
            Ok(())
        }
        fn delete(&self, key: &str) -> Result<(), VaultError> {
            self.0.borrow_mut().remove(key);
            Ok(())
        }
    }

    #[test]
    fn multiple_keys_are_provider_isolated_and_delete_removes_secret() {
        let vault = Vault { store: FakeStore::default() };
        let one = vault.add(Provider::OpenRouter, Zeroizing::new("sample-one".into())).unwrap();
        let two = vault.add(Provider::OpenRouter, Zeroizing::new("sample-two".into())).unwrap();
        vault.add(Provider::Gemini, Zeroizing::new("sample-three".into())).unwrap();
        assert_eq!(vault.list(Provider::OpenRouter).unwrap(), vec![one, two]);
        assert_eq!(vault.with_key(Provider::OpenRouter, two, str::len).unwrap(), 10);
        assert_eq!(vault.with_key(Provider::Grok, one, str::len), Err(VaultError::MissingKey));
        vault.remove(Provider::OpenRouter, one).unwrap();
        assert_eq!(vault.with_key(Provider::OpenRouter, one, str::len), Err(VaultError::MissingKey));
        assert_eq!(vault.list(Provider::Gemini).unwrap(), vec![1]);
    }

    #[test]
    fn orphaned_account_cannot_be_overwritten() {
        let vault = Vault { store: FakeStore::default() };
        vault.store.set("openrouter/key/1", "existing-orphan").unwrap();
        assert_eq!(vault.add(Provider::OpenRouter, Zeroizing::new("replacement".into())), Err(VaultError::IndexCorrupt));
        assert_eq!(vault.store.get("openrouter/key/1").unwrap().as_deref(), Some("existing-orphan"));
    }

    #[test]
    fn corrupt_index_and_invalid_input_fail_closed() {
        let vault = Vault { store: FakeStore::default() };
        assert_eq!(vault.add(Provider::Grok, Zeroizing::new("bad\nkey".into())), Err(VaultError::InvalidKey));
        vault.store.set(&Vault::<FakeStore>::index_account(Provider::Grok), "v1\n2\n2\n").unwrap();
        assert_eq!(vault.list(Provider::Grok), Err(VaultError::IndexCorrupt));
        assert_eq!(vault.add(Provider::Grok, Zeroizing::new("sample".into())), Err(VaultError::IndexCorrupt));
    }
}
