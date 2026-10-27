import {test} from 'node:test';import assert from 'node:assert/strict';
import {HOMEWORK_KEY,readTasks,changeTask,overdue,sortTasks,filterTasks,taskCourses} from '../public/homework.mjs';
const task={id:'a',title:'案例分析',courseId:'course',notes:'<script>test</script>',dueDate:'2027-01-01',dueTime:'',completedAt:'',deletedAt:'',revision:'1',createdAt:'2026-10-19',updatedAt:'2026-10-19'};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)};}
test('date-only deadline is not overdue during that day; exact time and completion',()=>{assert.equal(overdue(task,{date:'2027-01-01',time:'23:59'}),false);assert.equal(overdue(task,{date:'2027-01-02',time:'00:00'}),true);assert.equal(overdue({...task,dueTime:'19:00'},{date:'2027-01-01',time:'19:00'}),true);assert.equal(overdue({...task,completedAt:'done'},{date:'2027-02-01'}),false);assert.equal(overdue({...task,dueDate:''},{date:'2027-02-01'}),false);});
test('save, refresh, edit conflicts, completion and undo preserve other tasks',()=>{const s=storage();changeTask(s,'a',null,()=>task,'1');changeTask(s,'b',null,()=>({...task,title:'另一个'}),'b1');assert.equal(readTasks(s).length,2);const r=changeTask(s,'a','1',t=>({...t,completedAt:'now'}),'2');assert.throws(()=>changeTask(s,'a','1',t=>t,'3'),/其他页面/);changeTask(s,'a','2',()=>r.before,'3');assert.equal(readTasks(s)[0].completedAt,'');assert.equal(readTasks(s)[1].title,'另一个');});
test('damaged storage is never overwritten, write failures remain errors',()=>{const s=storage();s.setItem(HOMEWORK_KEY,'broken');assert.throws(()=>changeTask(s,'a',null,()=>task,'1'),/原数据已保留/);assert.equal(s.getItem(HOMEWORK_KEY),'broken');assert.throws(()=>changeTask({getItem:()=>null,setItem:()=>{throw Error('quota');}},'a',null,()=>task,'1'),/quota/);});
test('reject impossible dates and orphan times; pending dates sort last',()=>{const s=storage();assert.throws(()=>changeTask(s,'a',null,()=>({...task,dueDate:'2027-02-29'}),'1'));assert.throws(()=>changeTask(s,'a',null,()=>({...task,dueDate:'',dueTime:'12:00'}),'1'));assert.deepEqual(sortTasks([{...task,id:'unknown',dueDate:''},{...task,id:'later',dueDate:'2027-01-02'},task]).map(t=>t.id),['a','later','unknown']);});

test('course, ownership and completion filters combine without leaking similarly named classes',()=>{
 const records=[
  {...task,id:'private-a',courseId:'class-a'},
  {...task,id:'public-a',courseId:'class-a',scope:'course'},
  {...task,id:'public-b',courseId:'class-b',scope:'course'},
  {...task,id:'done',courseId:'class-a',completedAt:'done',scope:'course'},
  {...task,id:'deleted',courseId:'class-a',deletedAt:'deleted',scope:'course'},
 ];
 assert.deepEqual(filterTasks(records,{courseId:'class-a',scope:'course'}).map(t=>t.id),['public-a']);
 assert.deepEqual(filterTasks(records,{scope:'personal'}).map(t=>t.id),['private-a']);
 assert.deepEqual(filterTasks(records,{status:'done',courseId:'class-a'}).map(t=>t.id),['done']);
 assert.equal(filterTasks(records).length,3);
 assert.equal(filterTasks(records,{courseId:'class-b',scope:'personal'}).length,0);
 assert.equal(records.length,5);
});
test('personal assignments from a removed course remain available in course filters',()=>{
 const courses=[{id:'active',name:'系统工程',teacher:'演示王老师'}];
 const records=[
  {...task,courseId:'removed',courseName:'工程经济'},
  {...task,id:'b',courseId:'removed',courseName:'工程经济'},
  {...task,id:'c',courseId:'gone',deletedAt:'deleted'},
 ];
 const choices=taskCourses(courses,records);
 assert.equal(courses.length,1);
 assert.equal(choices.length,2);
 assert.deepEqual(choices[1],{id:'removed',name:'工程经济',removed:true});
 assert.equal(filterTasks(records,{courseId:'removed'}).length,2);
});

test('deadline groups retain unknown times, cross year boundaries, and completed tasks',async()=>{
 const {groupTasks}=await import('../public/homework.mjs');
 const task=(id,dueDate,dueTime='',completedAt='')=>({id,dueDate,dueTime,completedAt,createdAt:'2026-12-01',deletedAt:''});
 const items=[task('past','2026-12-29'),task('exact','2026-12-30','18:00'),task('unknown-time','2026-12-30'),task('next-year','2027-01-03'),task('later','2027-01-12'),task('unknown-date',''),task('done','2026-12-01','','2026-12-02')];
 assert.deepEqual(groupTasks(items,{date:'2026-12-30',time:'18:01'}).map(g=>[g.id,g.items.map(t=>t.id)]),[
  ['overdue',['past','exact']],['today',['unknown-time']],['soon',['next-year']],['later',['later']],['pending',['unknown-date']],['done',['done']]
 ]);
 assert.equal(items[2].dueTime,'');
});
