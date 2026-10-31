// A draft is reusable UI state, not a saved conversation.
export const isDraft = chat => !(chat.messages || []).length && !(chat.branches || []).some(b => b.messages?.length);
export const isPersistentChat = chat => !chat.ephemeral && !isDraft(chat);
export function findDraft(chats, temporary) {
  return chats.find(chat => isDraft(chat) && !!chat.ephemeral === !!temporary && chat.modeId === 'simple-chat');
}
export function canConvertMode(from, to, available) {
  return from === to || (from === 'simple-chat' && available.includes(to));
}
