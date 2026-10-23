import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDeadlineTime} from '../public/deadline-ui.mjs';

test('unknown deadline time stays unknown rather than becoming end of day',()=>{
 assert.deepEqual(parseDeadlineTime('',''),{value:'',error:''});
 assert.equal(parseDeadlineTime('0','0').value,'00:00');
 assert.equal(parseDeadlineTime('23','59').value,'23:59');
});
test('hour-only input means that hour, and Chinese full-width digits are accepted',()=>{
 assert.equal(parseDeadlineTime('9','').value,'09:00');
 assert.equal(parseDeadlineTime('２０','０５').value,'20:05');
 assert.equal(parseDeadlineTime(' 8 ',' 5 ').value,'08:05');
});
test('malformed and out-of-range times cannot silently become saved deadlines',()=>{
 for(const [h,m] of [['2大','00'],['24','00'],['12','60'],['-1','30'],['1.5','0'],['','30'],['200','0'],['20','ab'],['20','1e1'],['20:00','']]){
  const result=parseDeadlineTime(h,m);assert.ok(result.error,`${h}:${m}`);assert.equal(result.value,'');
 }
});
