import {escapeHTML as esc} from './schedule.mjs';
const names={course:'课前提醒','homework-new':'课程作业','homework-due':'截止提醒'};
const when=value=>new Date(value*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
function toggle({key,title,note,on,busy}){
 return `<label class="reminder-toggle"><span><strong>${title}</strong><small>${note}</small></span><input type="checkbox" role="switch" data-reminder-setting="${key}" aria-label="${title}" ${on?'checked':''} ${busy?'disabled':''}><span class="reminder-switch" aria-hidden="true"></span></label>`;
}
function choices(key,values,current,busy){return `<div class="reminder-choices" role="group" aria-label="${key==='courseMinutes'?'课前提前量':'作业截止提前量'}">${values.map(([value,label])=>`<button class="secondary-button" data-reminder-choice="${key}" data-value="${value}" aria-pressed="${current===value}" ${busy?'disabled':''}>${label}</button>`).join('')}</div>`;}
function upcoming(items){return `<div class="reminder-history">${items.map(item=>`<a href="${esc(item.url)}"><span class="reminder-history-kind">${names[item.kind]||'提醒'}</span><strong>${esc(item.title)}</strong><span>${esc(item.body)}</span><small>${esc(when(item.due))}</small></a>`).join('')}</div>`;}
export function reminderSettingsHTML({user,model,device,supported,ios,standalone,permission,busy,error='',notice=''}){
 const settings=model.settings,connected=device.enabled&&permission==='granted',enabled=connected&&device.remindersEnabled;
 const pendingTest=device.jobs?.some(job=>['scheduled','retry','sending'].includes(job.state));
 let title='锁屏也能收到提醒',connection;
 if(!ios){title='仅支持 iOS 设备接收';connection='<p>目前仅支持 iOS（iPhone / iPad）。从手机桌面的课间进入“更多 → 消息提醒”开启。</p>';}
 else if(!standalone){title='先把课间放到桌面';connection='<ol class="reminder-setup"><li>在 Safari 点分享，选择“添加到主屏幕”。</li><li>从桌面打开课间，再来这里开启提醒。</li></ol>';}
 else if(!supported){title='换个方式打开试试';connection='<p>请用较新版本的 Safari 将课间添加到主屏幕，再从桌面打开。</p>';}
 else if(permission==='denied'){title='还差一步，允许通知';connection='<p>请在系统设置中允许课间发送通知，再回到这里开启。</p>';}
 else if(!connected)connection=`<p>开启后，按你自己的课表和作业提醒。</p><button class="primary-button" data-reminder-connect ${busy?'disabled':''}>${busy?'正在连接…':'开启这台设备的提醒'}</button>`;
 else {title=enabled?'提醒已开启':'这台设备暂未接收';connection=toggle({key:'device',title:'这台设备接收提醒',note:'关闭仅影响这台设备。',on:enabled,busy});}
 const testing=enabled?`<div class="reminder-test-row"><span>${pendingTest?'已安排，锁屏等一小会儿。':'30 秒后发一条，锁屏试试看。'}</span><button class="secondary-button" data-reminder-test ${busy||pendingTest?'disabled':''}>${pendingTest?'等待发送':'测试一下'}</button></div>`:'';
 const help=ios&&standalone&&supported?'<details class="reminder-receive-help"><summary>收不到提醒？</summary><p>确认系统允许课间通知；专注模式可能会将通知静音。</p></details>':'';
 return `<div class="notification-layout reminder-layout reminder-simple"><section class="notification-card reminder-device-card"><div class="notification-device"><span class="notification-dot ${enabled?'ready':''}"></span><span>${esc(user.name)} · 此设备</span></div><h2>${title}</h2>${connection}${testing}${help}${error?`<p class="notification-error" role="alert">${esc(error)}</p>`:''}${notice?`<p class="reminder-saved" role="status">${esc(notice)}</p>`:''}${model.workerOnline===false?'<p class="notification-error" role="status">提醒服务正在恢复，请稍后再试。</p>':''}</section>
 <section class="notification-card reminder-content-card"><h2>提醒内容</h2><p class="reminder-card-caption">自动保存，换设备也适用。</p><div class="reminder-setting">${toggle({key:'course',title:'课前提醒',note:'按你的当前课表提醒，附老师、时间和教室。',on:settings.course,busy})}${settings.course?choices('courseMinutes',[[15,'提前15分钟'],[30,'提前30分钟'],[60,'提前1小时']],settings.courseMinutes,busy):''}</div><div class="reminder-setting">${toggle({key:'newHomework',title:'课程作业发布与更新',note:'只接收你已加入的那个教学班，其他班不会发给你。',on:settings.newHomework,busy})}</div><div class="reminder-setting">${toggle({key:'homeworkDue',title:'作业截止提醒',note:'个人作业和课程作业；已完成的作业不再提醒。',on:settings.homeworkDue,busy})}${settings.homeworkDue?choices('homeworkHours',[[24,'提前1天'],[2,'提前2小时']],settings.homeworkHours,busy):''}${settings.homeworkDue?'<p class="reminder-footnote">时间待定的作业，在截止前一天中午12:00提醒。</p>':''}</div></section>
 ${model.upcoming?.length?`<section class="notification-card reminder-upcoming-card"><h2>接下来</h2>${upcoming(model.upcoming)}</section>`:''}</div>`;
}
