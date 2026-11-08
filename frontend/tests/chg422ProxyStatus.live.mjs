// REL422-003 / SYSUX-018: actual HTTPS proxy refusals, never replacement responses.
import test from 'node:test';
import assert from 'node:assert/strict';
import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';

const privatePath=process.env.CHG422_LIVE_API_CONTEXT;
assert.ok(privatePath && path.isAbsolute(privatePath));
assert.equal(fs.realpathSync(privatePath),privatePath);
const stat=fs.statSync(privatePath);assert.equal(stat.uid,process.getuid());assert.equal(stat.mode&0o077,0);
const config=JSON.parse(fs.readFileSync(privatePath));
const owner=JSON.parse(fs.readFileSync(path.resolve(path.dirname(privatePath),'../owner.json')));
assert.equal(owner.change_id,'CHG-422');assert.equal(owner.run_uuid,config.run_uuid);
assert.equal(owner.execution_closed,false);assert.ok(Date.now()<Date.parse(owner.deadline));
const ca=fs.readFileSync(config.ca_file);
const origin=new URL(config.origin);assert.equal(origin.protocol,'https:');assert.equal(origin.hostname,'localhost');

function request(relative,{method='GET',body,headers={}}={}) {
 return new Promise((resolve,reject)=>{
  const payload=body===undefined?undefined:Buffer.from(JSON.stringify(body));
  const req=https.request(config.origin+'/api/backend/'+relative,{method,ca,rejectUnauthorized:true,
   headers:{Origin:config.origin,...(payload?{'Content-Type':'application/json'}:{}),...headers}},response=>{
   const chunks=[];let length=0;
   response.on('data',chunk=>{length+=chunk.length;if(length>262144){response.destroy();reject(new Error('response_too_large'));}else chunks.push(chunk);});
   response.on('error',()=>reject(new Error('real_response_failed')));
   response.on('end',()=>{try {const bytes=Buffer.concat(chunks);resolve({status:response.statusCode,headers:response.headers,data:bytes.length?JSON.parse(bytes.toString()):null});}catch{reject(new Error('real_JSON_response_required'));}});
  });
  req.setTimeout(20000,()=>req.destroy(new Error('real_request_timeout')));req.on('error',()=>reject(new Error('real_HTTPS_request_failed')));
  if(payload)req.write(payload);req.end();
 });
}

test('Unauthenticated streamed JSON preserves the genuine upstream 401',async()=>{
 const response=await request('auth/session-drafts',{method:'POST',body:{form_key:'system.parameters',return_path:'/system',nonce:'CHG422-real-proxy-regression-nonce',payload:{timezone:'UTC'}}});
 assert.equal(response.status,401);assert.ok(response.data.code);assert.notEqual(response.data.code,'backend_proxy_unreachable');
});

test('Failed fresh authentication remains 401, preserves login, and CSRF remains enforced',async()=>{
 const actor=config.actors.owner;
 const login=await request('auth/login',{method:'POST',body:{username:actor.username,password:actor.password}});
 assert.equal(login.status,200);
 const cookie=(login.headers['set-cookie']??[]).find(value=>value.startsWith('__Host-nomosmart_session='))?.split(';')[0];
 assert.ok(cookie);
 let csrf;
 try {
  const session=await request('auth/session',{headers:{Cookie:cookie}});assert.equal(session.status,200);assert.equal(session.data.authenticated,true);csrf=session.data.csrf_token;
  const before=await request('system/parameters',{headers:{Cookie:cookie}});assert.equal(before.status,200);
  const failed=await request('system/identity-settings/reauth/start',{method:'POST',headers:{Cookie:cookie,'X-CSRF-Token':csrf},body:{username:actor.username,password:'invalid-owned-test-password'}});
  assert.equal(failed.status,401);assert.equal(failed.data.code,'invalid_credentials');
  const still=await request('auth/session',{headers:{Cookie:cookie}});assert.equal(still.status,200);assert.equal(still.data.authenticated,true);
  const blocked=await request('system/parameters',{method:'PATCH',headers:{Cookie:cookie},body:{section:'general',expected_revision:before.data.section_revisions.general,values:{default_timezone:'UTC'}}});
  assert.equal(blocked.status,403);
  const after=await request('system/parameters',{headers:{Cookie:cookie}});assert.equal(after.status,200);assert.deepEqual(after.data,before.data);
 } finally {
  if(csrf){const logout=await request('auth/logout',{method:'POST',headers:{Cookie:cookie,'X-CSRF-Token':csrf}});assert.equal(logout.status,204);}
 }
});
