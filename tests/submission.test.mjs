import test from 'node:test';
import assert from 'node:assert/strict';
import {submissionHTML,submissionSection} from '../public/submission.mjs';

test('submission is separate from requirements and unknown channels stay unknown',()=>{
 assert.match(submissionSection(''),/<h3>提交方式<\/h3>/);
 assert.match(submissionHTML(''),/待通知/);
 assert.match(submissionHTML('线下交到演示楼 301'),/线下交到演示楼 301/);
});
test('HTTP links preserve explicit ports and have safe new-window attributes',()=>{
 const html=submissionHTML('提交到 https://portal.example.test:88/ ，备注姓名。');
 assert.match(html,/href="https:\/\/portal.example.test:88\/"/);
 assert.match(html,/rel="noopener noreferrer"/);
});
test('HTML and non-HTTP protocols remain escaped text',()=>{
 const html=submissionHTML('<img src=x onerror=alert(1)> javascript:alert(1)');
 assert.ok(!html.includes('<img'));assert.ok(!html.includes('<a '));assert.match(html,/&lt;img/);
});
test('embedded credentials never become a clickable link',()=>{
 assert.ok(!submissionHTML('https://user:pass@example.test/upload').includes('<a '));
});
