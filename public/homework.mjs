export function overdue(t,clock){return !t.completedAt&&!!t.dueDate&&(t.dueDate<clock.date||(t.dueDate===clock.date&&!!t.dueTime&&t.dueTime<=clock.time));}
export function sortTasks(tasks){return [...tasks].sort((a,b)=>(a.dueDate||'9999').localeCompare(b.dueDate||'9999')||(a.dueTime||'99:99').localeCompare(b.dueTime||'99:99')||a.createdAt.localeCompare(b.createdAt));}

// Legacy migration helpers retained for reading previous local data; classroom UI never writes through them.
export const HOMEWORK_KEY='kejian.homework.v1';
const validDate=s=>/^\d{4}-\d{2}-\d{2}$/.test(s)&&!isNaN(Date.parse(s+'T12:00:00Z'))&&new Date(s+'T12:00:00Z').toISOString().slice(0,10)===s;
export function validateTask(t){
 if(!t||typeof t.id!=='string'||typeof t.title!=='string'||!t.title.trim()||t.title.length>120||typeof t.courseId!=='string'||!t.courseId||typeof t.notes!=='string'||t.notes.length>10000)throw Error('请填写作业名称和课程，名称不超过120字、要求不超过10000字。');
 if(t.dueDate!==''&&!validDate(t.dueDate))throw Error('截止日期无效。');
 if(t.dueTime!==''&&(!t.dueDate||!/^([01]\d|2[0-3]):[0-5]\d$/.test(t.dueTime)))throw Error('请先选择日期，再填写有效时间。');
 if(typeof t.createdAt!=='string'||typeof t.updatedAt!=='string'||typeof t.completedAt!=='string'||typeof t.deletedAt!=='string'||typeof t.revision!=='string')throw Error('作业记录格式异常。');
 return t;
}
export function readTasks(storage){
 const raw=storage.getItem(HOMEWORK_KEY);if(raw===null)return [];
 let data;try{data=JSON.parse(raw);if(data.version!==1||!Array.isArray(data.items))throw Error();data.items.forEach(validateTask);if(new Set(data.items.map(t=>t.id)).size!==data.items.length)throw Error();}catch{throw Error('本机作业数据无法读取，原数据已保留，请勿清除浏览器数据。');}
 return data.items;
}
export function changeTask(storage,id,expected,mutate,revision){
 const items=readTasks(storage),index=items.findIndex(t=>t.id===id),before=index<0?null:items[index];
 if((before?.revision||null)!==expected)throw Error('这条作业已在其他页面更新，请重新打开后再修改。');
 const next=validateTask({...mutate(before),id,revision});
 if(index<0)items.push(next);else items[index]=next;
 storage.setItem(HOMEWORK_KEY,JSON.stringify({version:1,items}));return {before,next};
}
