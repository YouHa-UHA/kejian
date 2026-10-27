import {escapeHTML as esc} from './schedule.mjs';

// Display helpers only. Enrollment and homework always keep the full course ID.
export function courseIdentity(course){
 if(!course)return '';
 const id=course.courseId||course.id||'';
 return [course.teacher,id&&!id.startsWith('import-')?'教学班 '+id:'',course.removed?'已移出课表':''].filter(Boolean).join(' · ');
}

export function courseChoice(course,fallback='选择课程'){
 if(!course)return `<span class="course-choice"><strong>${esc(fallback)}</strong></span>`;
 const identity=courseIdentity(course);
 return `<span class="course-choice"><strong>${esc(course.name)}</strong>${identity?`<small>${esc(identity)}</small>`:''}</span>`;
}

export function searchCourses(courses,query){
 const needle=query.trim().toLocaleLowerCase();
 return courses.filter(c=>[c.name,c.teacher,c.location,c.courseId||c.id].filter(Boolean).join(' ').toLocaleLowerCase().includes(needle));
}
