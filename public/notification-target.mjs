export function notificationTarget(search,member){
 const params=new URLSearchParams(search),owner=params.get('noticeOwner');
 if(owner!==null&&owner!==String(member))return {kind:'wrong-account'};
 const homework=params.get('homework'),event=params.get('event');
 if(homework)return homework.length<=200?{kind:'homework',id:homework}:{kind:'unavailable'};
 if(event)return event.length<=400?{kind:'event',id:event}:{kind:'unavailable'};
 return {kind:'none'};
}
