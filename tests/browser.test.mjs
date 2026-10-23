import test from 'node:test';
import assert from 'node:assert/strict';
import {routeFromHash,replaceRoute,viewportLayout} from '../public/browser.mjs';

test('switching primary tabs preserves one browser-history entry and the shareable route',()=>{
 const entries=['https://example.test/chat','https://example.test/mem/#today'];
 const location={hash:'#today'},savedState={fixture:'preserve'};
 const browser={location,history:{state:savedState,replaceState(state,unused,hash){
  assert.equal(state,savedState);entries[1]='https://example.test/mem/'+hash;location.hash=hash;
 }}};
 for(const route of ['week','courses','ai','today','week','week'])assert.equal(replaceRoute(route,browser),true);
 assert.equal(entries.length,2);assert.equal(entries[0],'https://example.test/chat');
 assert.equal(entries[1],'https://example.test/mem/#week');assert.equal(routeFromHash(location.hash),'week');
 assert.equal(replaceRoute('https://another.test/',browser),false);assert.equal(location.hash,'#week');
 assert.equal(routeFromHash('#unknown'),'today');
});

test('viewport adapts to obscured space, keeps keyboard separate and does not chase pinch zoom',()=>{
 assert.deepEqual(viewportLayout({height:800,visualHeight:744}),{bottom:56,height:744,keyboard:false});
 assert.deepEqual(viewportLayout({height:800,visualHeight:800}),{bottom:0,height:800,keyboard:false});
 assert.deepEqual(viewportLayout({height:800,visualHeight:470,offsetTop:20,editing:true}),{bottom:310,height:470,keyboard:true});
 assert.deepEqual(viewportLayout({height:800,visualHeight:400,scale:2,editing:true}),{bottom:0,height:800,keyboard:false});
 assert.deepEqual(viewportLayout({height:800}),{bottom:0,height:800,keyboard:false});
 assert.equal(viewportLayout({height:800,visualHeight:810}).bottom,0);
});
