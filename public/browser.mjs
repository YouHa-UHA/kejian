export const ROUTES = ['today', 'week', 'homework', 'courses', 'ai', 'manage'];
export const routeFromHash = hash => ROUTES.includes(hash.slice(1)) ? hash.slice(1) : 'today';

// Top-level tabs are alternative views of one app, not a stack of visited pages.
export function replaceRoute(route, browser = window) {
  if (!ROUTES.includes(route)) return false;
  if (browser.location.hash !== `#${route}`) {
    browser.history.replaceState(browser.history.state, '', `#${route}`);
  }
  return true;
}

export function viewportLayout({height, visualHeight = height, offsetTop = 0, scale = 1, editing = false}) {
  // Do not chase the zoomed viewport: this would move navigation across enlarged content.
  const zoomed = Math.abs(scale - 1) > 0.05;
  const covered = zoomed ? 0 : Math.max(0, height - visualHeight - offsetTop);
  return {bottom: Math.round(covered), height: Math.round(zoomed ? height : visualHeight), keyboard: editing && !zoomed && covered > 120};
}

export function watchViewport(browser = window) {
  const root = browser.document.documentElement;
  let frame;
  const update = () => {
    frame = null;
    const viewport = browser.visualViewport;
    const active = browser.document.activeElement;
    const layout = viewportLayout({height: browser.innerHeight, visualHeight: viewport?.height,
      offsetTop: viewport?.offsetTop, scale: viewport?.scale,
      editing: !!active?.matches('input,textarea,[contenteditable="true"]')});
    root.style.setProperty('--viewport-bottom', `${layout.bottom}px`);
    root.style.setProperty('--visible-height', `${layout.height}px`);
    const top=Math.abs((viewport?.scale??1)-1)>0.05?0:(viewport?.offsetTop??0);
    root.style.setProperty('--viewport-top', `${Math.round(top)}px`);
    root.classList.toggle('keyboard-open', layout.keyboard);
  };
  const schedule = () => { if (!frame) frame = browser.requestAnimationFrame(update); };
  browser.addEventListener('resize', schedule, {passive:true});
  browser.visualViewport?.addEventListener('resize', schedule, {passive:true});
  browser.visualViewport?.addEventListener('scroll', schedule, {passive:true});
  browser.document.addEventListener('focusin', schedule);
  browser.document.addEventListener('focusout', schedule);
  update();
}

// All course and deadline pickers share the same dismissal and keyboard behavior.
export function mountPickers(root = document){
 const closeOthers=current=>root.querySelectorAll('.hw-picker[open]').forEach(p=>{if(p!==current)p.open=false;});
 root.addEventListener('toggle',event=>{
  if(event.target.matches?.('.hw-picker[open]'))closeOthers(event.target);
 },true);
 root.addEventListener('click',event=>{
  root.querySelectorAll('.hw-picker[open]').forEach(p=>{if(!p.contains(event.target))p.open=false;});
 });
 root.addEventListener('keydown',event=>{
  const picker=event.target.closest('.hw-picker');
  if(!picker)return;
  const summary=picker.querySelector('summary');
  if(event.key==='Escape'&&picker.open){
   event.preventDefault();event.stopPropagation();picker.open=false;summary.focus();return;
  }
  // The calendar manages date navigation itself.
  if(picker.classList.contains('hw-date-picker'))return;
  const options=[...picker.querySelectorAll('.hw-picker-options button:not(:disabled):not([hidden])')];
  if(!options.length)return;
  if(event.target===summary&&['ArrowDown','ArrowUp'].includes(event.key)){
   event.preventDefault();closeOthers(picker);picker.open=true;
   (options.find(b=>b.getAttribute('aria-pressed')==='true')||options[event.key==='ArrowDown'?0:options.length-1]).focus();return;
  }
  const index=options.indexOf(event.target);
  if(index<0||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  event.preventDefault();
  const next=event.key==='Home'?0:event.key==='End'?options.length-1:(index+(event.key==='ArrowDown'?1:options.length-1))%options.length;
  options[next].focus();
 },true);
 root.addEventListener('input',event=>{
  if(!event.target.matches?.('[data-picker-search]'))return;
  const picker=event.target.closest('.hw-picker');
  const query=event.target.value.trim().toLocaleLowerCase();
  const options=[...picker.querySelectorAll('.hw-picker-options button')];
  options.forEach(option=>{option.hidden=!option.textContent.toLocaleLowerCase().includes(query);});
  const empty=picker.querySelector('.picker-empty');
  if(empty)empty.hidden=options.some(option=>!option.hidden);
 });
}

export function captureView(root,browser=window){
 const active=root.ownerDocument.activeElement;
 const focus=root.contains(active)?{id:active.id,attrs:[...active.attributes].filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value])}:null;
 return {x:browser.scrollX,y:browser.scrollY,focus};
}
export function restoreView(root,view,browser=window){
 if(view.focus){
  const {id,attrs}=view.focus;
  const target=id?[...root.querySelectorAll('[id]')].find(el=>el.id===id):attrs.length?[...root.querySelectorAll('button,a,summary')].find(el=>attrs.every(([k,v])=>el.getAttribute(k)===v)):null;
  target?.focus({preventScroll:true});
 }
 browser.scrollTo({left:view.x,top:view.y,behavior:'instant'});
}

// Keep background reads separate from page navigation and unsaved form content.
export function createScheduleSync({owner,blocked,read,apply}){
 let signature='',epoch=0,flight=null;
 return {
  seed(source){epoch++;signature=JSON.stringify(source);flight=null;},
  clear(){epoch++;signature='';flight=null;},
  refresh(){
   const member=owner();
   if(!member||blocked())return Promise.resolve(false);
   if(flight)return flight.promise;
   const ticket={epoch,member};
   flight=ticket;
   ticket.promise=(async()=>{
    try{
     const source=await read();
     if(ticket.epoch!==epoch||owner()!==member||blocked())return false;
     if(source?.owner!==member||!Array.isArray(source.courses)||!Array.isArray(source.events))throw Error('课表格式不正确');
     const next=JSON.stringify(source);
     if(next===signature)return false;
     apply(source);signature=next;return true;
    }finally{if(flight===ticket)flight=null;}
   })();
   return ticket.promise;
  },
 };
}
