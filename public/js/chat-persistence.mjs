/* Coalesce changes per chat, never one chat in place of another. */
export function createChatWriter(write, {
  getActiveId = () => null,
  onError = () => {},
  delay = 350,
  schedule = setTimeout,
  cancel = clearTimeout,
} = {}) {
  const pending = new Map();
  let timer = null;
  async function flush() {
    if (timer !== null) cancel(timer);
    timer = null;
    const batch = [...pending.values()];
    pending.clear();
    const activeId = getActiveId();
    const results = [];
    for (const chat of batch) {
      try { await write(chat, activeId); results.push(true); }
      catch (error) { onError(error, chat.id); results.push(false); }
    }
    return results;
  }
  return {
    queue(chat) {
      if (!chat?.id) return;
      pending.set(chat.id, chat);
      if (timer === null) timer = schedule(() => { void flush(); }, delay);
    },
    flush,
  };
}
