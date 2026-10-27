import {escapeHTML as esc} from './schedule.mjs';

// Only explicit HTTP(S) links become actionable; all other content stays text.
export function submissionHTML(value=''){
 const text=String(value||'').trim();
 if(!text)return '<p class="hw-submission-empty">待通知</p>';
 let cursor=0,html='';
 for(const match of text.matchAll(/https?:\/\/[^\s<>"'，。；！？、（）【】]+/giu)){
  const raw=match[0].replace(/[.,;!?)\]]+$/u,'');
  let url;try{url=new URL(raw);}catch{continue;}
  if(!['http:','https:'].includes(url.protocol)||!url.hostname||url.username||url.password)continue;
  html+=esc(text.slice(cursor,match.index));
  html+=`<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${esc(raw)}</a>`;
  cursor=match.index+raw.length;
 }
 return `<div class="hw-submission-content">${html+esc(text.slice(cursor))}</div>`;
}

export const submissionSection=value=>`<section class="hw-submission-section"><h3>提交方式</h3>${submissionHTML(value)}</section>`;
