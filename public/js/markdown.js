/* Archx Agent — structured Markdown renderer: tolerant GFM parsing, code/table actions + exports */
import { esc } from './dom.js';
import { closeUnfinishedFence } from './markdown-stream.mjs';
const hasWindow = typeof window !== 'undefined';
let md = null;
if (hasWindow && (window.markdownit || window.markdownIt)) {
  md = (window.markdownit || window.markdownIt)({
    html: false, linkify: true, breaks: true,
    highlight(code, lang) {
      if (window.hljs) {
        try {
          if (lang && window.hljs.getLanguage(lang)) return window.hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
          if (code.length < 4000) return window.hljs.highlightAuto(code).value;
        } catch {}
      }
      return '';
    },
  });
}
export const markdownReady = () => !!md;
const COPY_SVG = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
const DOWNLOAD_SVG = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>';

/*
 * Models occasionally return Markdown that has been escaped one level too far,
 * e.g. "\\## Heading" or "\\---". These are block-level constructs only, so we
 * can safely repair the common accidental escaping without touching inline paths,
 * regular prose backslashes, or code block contents.
 */
function normalizeBlockMarkdown(src) {
  const lines = String(src || '').split(/\r?\n/);
  let fence = null;
  return lines.map((line) => {
    const fenceMatch = line.match(/^\s*(\\)(```+|~~~+)\s*([\w.+-]*)\s*$/);
    if (fenceMatch && !fence) {
      fence = fenceMatch[2][0];
      return line.replace(/^\s*\\/, '');
    }
    if (/^\s*(```+|~~~+)/.test(line)) {
      const ch = line.trim()[0];
      if (fence && ch === fence) fence = null;
      return line;
    }
    if (fence) return line;
    let out = line;
    out = out.replace(/^(\s*)\\(#{1,6})(\s+)/, '$1$2$3');
    out = out.replace(/^(\s*)\\((?:---+|___+|\*\*\*+))\s*$/, '$1$2');
    out = out.replace(/^(\s*)\\([*-])\s+/, '$1$2 ');
    out = out.replace(/^(\s*)\\(\d+\.)\s+/, '$1$2 ');
    return out;
  }).join('\n');
}

function splitCells(line) {
  let t = String(line).trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
  const out=[]; let cur='', escp=false;
  for (const ch of t) {
    if (escp) { cur += ch; escp=false; continue; }
    if (ch === '\\') { escp=true; cur += ch; continue; }
    if (ch === '|') { out.push(cur.trim().replace(/\\\|/g,'|')); cur=''; }
    else cur += ch;
  }
  if (cur || t.endsWith('|') === false) out.push(cur.trim().replace(/\\\|/g,'|'));
  return out;
}
function isSeparatorLine(line) {
  const cells = splitCells(line);
  if (cells.length < 1) return false;
  return cells.every(c => /^:?-{1,}:?$/.test(c.trim()));
}
function parseAlignment(c) {
  c=c.trim(); const l=c.startsWith(':'); const r=c.endsWith(':');
  return l&&r?'center':r?'right':l?'left':'';
}
function tableHTML(rows) {
  const header=splitCells(rows[0]); const sep=splitCells(rows[1]);
  const cols=Math.max(header.length, sep.length, ...rows.slice(2).map(r=>splitCells(r).length));
  while(header.length<cols) header.push('');
  const aligns=Array.from({length:cols},(_,i)=>parseAlignment(sep[i]||''));
  const inlineCell=(text) => md ? md.renderInline(String(text || '')) : inlineFallback(String(text || ''));
  const renderCell=(tag,text,i)=>`<${tag}${aligns[i]?` style="text-align:${aligns[i]}"`:''}>${inlineCell(text)}</${tag}>`;
  let html='<table data-archx-table="1"><thead><tr>';
  header.forEach((c,i)=>html+=renderCell('th',c,i)); html+='</tr></thead><tbody>';
  for(const row of rows.slice(2)) { const cells=splitCells(row); while(cells.length<cols) cells.push(''); html+='<tr>'; cells.slice(0,cols).forEach((c,i)=>html+=renderCell('td',c,i)); html+='</tr>'; }
  html+='</tbody></table>'; return html;
}

/** Finds genuine GFM tables outside fenced code. */
export function extractTables(src) {
  const lines=String(src||'').split(/\r?\n/), out=[], tables=[]; let i=0, fence=null;
  while(i<lines.length){
    const line=lines[i]; const fm=line.match(/^\s*(```+|~~~+)\s*/);
    if(fm){ fence=fence?null:fm[1][0]; out.push(line); i++; continue; }
    if(!fence && i+1<lines.length && line.includes('|') && isSeparatorLine(lines[i+1])) {
      const head=splitCells(line), sep=splitCells(lines[i+1]);
      if(head.length>=2 && sep.length===head.length){
        const rows=[line, lines[i+1]]; let j=i+2;
        while(j<lines.length && lines[j].trim() && lines[j].includes('|')) { rows.push(lines[j]); j++; }
        const token=`ARCHXTABLE${tables.length}TOKEN`;
        tables.push(tableHTML(rows)); out.push(token); i=j; continue;
      }
    }
    out.push(line); i++;
  }
  return { text:out.join('\n'), tables };
}

export function normalizeTables(src) { return extractTables(src).text; }
export function renderMarkdown(text) {
  const src = closeUnfinishedFence(normalizeBlockMarkdown(text));
  const {text:prepared,tables}=extractTables(src);
  if(!md) {
    let html=fallbackMd(prepared);
    tables.forEach((table,i)=>{ const token=`ARCHXTABLE${i}TOKEN`; html=html.replace(new RegExp(`<p>\\s*${token}\\s*</p>`),table).replace(new RegExp(token,'g'),table); });
    return html || '<p></p>';
  }
  let html=md.render(prepared);
  tables.forEach((table,i)=>{
    const token=`ARCHXTABLE${i}TOKEN`;
    html=html.replace(new RegExp(`<p>\\s*${token}\\s*</p>`),table);
    html=html.replace(new RegExp(token,'g'),table);
  });
  return html || '<p></p>';
}

function codeBlockHtml(lang,code){
  let inner=esc(code); if(hasWindow&&window.hljs){try{inner=lang&&window.hljs.getLanguage(lang)?window.hljs.highlight(code,{language:lang,ignoreIllegals:true}).value:window.hljs.highlightAuto(code).value;}catch{}}
  return `<div class="codeblock"><div class="cb-head"><span>${esc(lang||'code')}</span><span class="cb-actions"><button class="cb-copy" type="button">${COPY_SVG} copy</button><button class="cb-download" type="button">${DOWNLOAD_SVG} download</button></span></div><pre><code class="hljs${lang?' language-'+esc(lang):''}">${inner}</code></pre></div>`;
}
function inlineFallback(s){
  return esc(s)
    .replace(/`([^`\n]+)`/g,(x,c)=>`<code>${esc(c)}</code>`)
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g,'<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g,'<em>$1</em>')
    .replace(/_([^_\n]+)_/g,'<em>$1</em>')
    .replace(/\n/g,'<br>');
}
function fallbackMd(t){
  const lines=String(t||'').split(/\r?\n/),out=[]; let i=0;
  const fenceRe=/^\s*```([\w+.-]*)\s*$/;
  while(i<lines.length){
    const line=lines[i];
    if(!line.trim()){ i++; continue; }
    const fm=line.match(fenceRe);
    if(fm){
      const lang=fm[1]||''; const code=[]; i++;
      while(i<lines.length && !/^\s*```\s*$/.test(lines[i])){ code.push(lines[i]); i++; }
      if(i<lines.length)i++;
      out.push(codeBlockHtml(lang,code.join('\n'))); continue;
    }
    const hm=line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if(hm){ const level=hm[1].length; out.push(`<h${level}>${inlineFallback(hm[2])}</h${level}>`); i++; continue; }
    if(/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)){ out.push('<hr>'); i++; continue; }
    if(/^\s*(?:[-*+]\s+|\d+\.\s+)/.test(line)){
      const ordered=/^\s*\d+\.\s+/.test(line); const tag=ordered?'ol':'ul'; const items=[];
      while(i<lines.length && new RegExp(`^\\s*${ordered?'\\d+\\.':'[-*+]'}\\s+`).test(lines[i])){
        items.push(`<li>${inlineFallback(lines[i].replace(new RegExp(`^\\s*${ordered?'\\d+\\.':'[-*+]' }\\s+`,'i'),'').trim())}</li>`); i++;
      }
      out.push(`<${tag}>${items.join('')}</${tag}>`); continue;
    }
    const para=[line]; i++;
    while(i<lines.length && lines[i].trim() && !/^\s*(#{1,6})\s+/.test(lines[i]) && !/^\s*```/.test(lines[i]) && !/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(lines[i]) && !/^\s*(?:[-*+]\s+|\d+\.\s+)/.test(lines[i])) { para.push(lines[i]); i++; }
    out.push(`<p>${inlineFallback(para.join('\n'))}</p>`);
  }
  return out.join('')||'<p></p>';
}

export function decorateCode(root){
  Array.from(root.querySelectorAll('pre')).forEach((pre, index)=>{
    if(pre.parentElement?.classList.contains('codeblock')) return;
    const code=pre.querySelector('code'); const m=code&&/language-([\w+.-]+)/.exec(code.className||'');
    const wrap=document.createElement('div'); wrap.className='codeblock'; wrap.dataset.downloadIndex=String(index+1);
    const head=document.createElement('div'); head.className='cb-head';
    head.innerHTML=`<span>${esc(m?m[1]:'code')}</span><span class="cb-actions"><button class="cb-copy" type="button">${COPY_SVG} copy</button><button class="cb-download" type="button">${DOWNLOAD_SVG} download</button></span>`;
    pre.parentNode.insertBefore(wrap,pre); wrap.appendChild(head); wrap.appendChild(pre);
  });
  Array.from(root.querySelectorAll('.codeblock')).forEach((block,index)=>{ if(!block.dataset.downloadIndex) block.dataset.downloadIndex=String(index+1); });
}
export function decorateTables(root){
  Array.from(root.querySelectorAll('table')).forEach((t,index)=>{
    if(t.parentElement?.classList.contains('tableblock'))return;
    const rows=t.rows?.length||0,cols=t.rows?.[0]?.cells.length||0;
    const shell=document.createElement('div'); shell.className='tableblock'; shell.dataset.downloadIndex=String(index+1);
    const head=document.createElement('div'); head.className='tb-head';
    head.innerHTML=`<span>table · ${Math.max(0,rows-1)} rows × ${cols} cols</span><span class="tb-actions"><button class="tb-copy" type="button">${COPY_SVG} copy CSV</button><button class="tb-download" data-format="csv" type="button">${DOWNLOAD_SVG} CSV</button><button class="tb-download" data-format="json" type="button">JSON</button><button class="tb-download" data-format="html" type="button">HTML</button><button class="tb-download" data-format="md" type="button">MD</button></span>`;
    const wrap=document.createElement('div'); wrap.className='table-wrap'; t.parentNode.insertBefore(shell,t); shell.appendChild(head); shell.appendChild(wrap); wrap.appendChild(t);
  });
}
export function tableToCSV(table){const out=[];Array.from(table.rows).forEach(r=>out.push(Array.from(r.cells).map(c=>{const v=(c.textContent||'').replace(/\s+/g,' ').trim();return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}).join(',')));return out.join('\n');}
export function tableToTSV(table){return Array.from(table.rows).map(r=>Array.from(r.cells).map(c=>(c.textContent||'').replace(/\s+/g,' ').trim().replace(/\t/g,' ')).join('\t')).join('\n');}
export function tableToJSON(table){const rows=Array.from(table.rows).map(r=>Array.from(r.cells).map(c=>(c.textContent||'').replace(/\s+/g,' ').trim()));if(!rows.length)return '[]';const headers=rows[0];return JSON.stringify(rows.slice(1).map(r=>Object.fromEntries(headers.map((h,i)=>[h||`column_${i+1}`,r[i] ?? '']))),null,2);}
export function tableToMarkdown(table){
  const rows=Array.from(table.rows).map(r=>Array.from(r.cells).map(c=>(c.textContent||'').replace(/\|/g,'\\|').replace(/\n/g,' ').trim()));
  if(!rows.length)return '';
  const width=rows[0].length;
  const out=['| '+rows[0].map(v=>v||' ').join(' | ')+' |','| '+Array.from({length:width},()=> '---').join(' | ')+' |'];
  rows.slice(1).forEach(r=>{while(r.length<width)r.push('');out.push('| '+r.slice(0,width).map(v=>v||' ').join(' | ')+' |');});
  return out.join('\n');
}
export function tableToHTML(table){return '<!doctype html><meta charset="utf-8"><title>Archx table</title>'+table.outerHTML;}
export function downloadText(text,filename,mime='text/plain;charset=utf-8'){const blob=new Blob([text],{type:mime});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
