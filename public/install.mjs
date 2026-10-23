import {escapeHTML as esc} from './schedule.mjs';
let pendingInstall=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();pendingInstall=e;});
window.addEventListener('appinstalled',()=>{pendingInstall=null;const result=document.querySelector('.install-status');if(result)result.textContent='已添加到桌面';});
if('serviceWorker' in navigator)navigator.serviceWorker.register('./push-sw.js',{scope:'./'}).catch(()=>{});
export function openInstall({showDialog,dialogTop}){
 const installed=matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
 const ua=navigator.userAgent,ios=/iPhone|iPad|iPod/i.test(ua)||(/Macintosh/.test(ua)&&navigator.maxTouchPoints>1),wechat=/MicroMessenger/i.test(ua),url=new URL('./',location.href).href;
 const steps=ios?'<li>用 <strong>Safari</strong> 打开课间。</li><li>轻点<strong>共享</strong>，选择<strong>添加到主屏幕</strong>。</li><li>如有“作为网页 App 打开”，保持开启，再添加。</li>':'<li>用 <strong>Chrome 或 Edge</strong> 打开课间。</li><li>打开浏览器菜单，选择<strong>安装应用</strong>或<strong>添加到主屏幕</strong>。</li><li>小米浏览器也可在菜单中查找“添加到桌面”，可用选项以浏览器为准。</li>';
 showDialog(`<div class="install-detail">${dialogTop('手机主屏幕')}<img class="install-icon" src="./apple-touch-icon.png" alt="课间图标" width="64" height="64"><h2 id="dialog-title">${installed?'已从桌面打开':'添加到手机主屏幕'}</h2>${installed?'<p class="install-lead">当前已在独立窗口中使用课间。</p>':`<ol class="install-steps">${steps}</ol>${wechat?'<p class="install-note">微信内请先复制链接，转到系统浏览器打开。</p>':''}${pendingInstall?'<button class="primary-button" id="install-now">安装课间</button>':''}`}<button class="primary-button" data-copy-link>复制课间链接</button><p class="copy-status install-status" role="status" aria-live="polite"></p><a class="install-url" href="${esc(url)}">${esc(url)}</a></div>`);
 const button=document.querySelector('#install-now');if(button)button.onclick=async()=>{if(!pendingInstall)return;button.disabled=true;const event=pendingInstall;pendingInstall=null;try{await event.prompt();const result=await event.userChoice;document.querySelector('.install-status').textContent=result.outcome==='accepted'?'已提交安装，请查看桌面':'已取消，可稍后从浏览器菜单添加';}catch{document.querySelector('.install-status').textContent='请从浏览器菜单添加到主屏幕';}};
}
