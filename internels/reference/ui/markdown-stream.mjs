export function closeUnfinishedFence(src) {
  const text = String(src || '');
  const lines = text.split(/\r?\n/);
  let open = null;
  for (const line of lines) {
    const match = line.match(/^\s*(`{3,}|~{3,})[^`~]*$/);
    if (!open) {
      if (match) open = { char: match[1][0], length: match[1].length };
      continue;
    }
    const close = new RegExp(`^\\s*${open.char}{${open.length},}\\s*$`);
    if (close.test(line)) open = null;
  }
  return open ? `${text}\n${open.char.repeat(open.length)}` : text;
}
