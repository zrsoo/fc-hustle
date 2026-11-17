'use strict';
// Historical public functions; synthetic HTTP responses, no browser or account.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const captured=JSON.parse(fs.readFileSync('docs/research/005/native-status-contract.json','utf8'));
const sandbox=vm.createContext({...captured.enums,
  _0x512d02:()=>{throw Error('unresolved public source lookup');},
  UTHttpResponseDTO:class{constructor(){this.success=false;}},
  UTServerErrorVO:class{constructor(code,reason){this.code=code;this.reason=reason;}},
  JSUtils:{isString:v=>typeof v==='string'}});
const methods=Object.fromEntries(Object.entries(captured.methods).map(([k,source])=>[k,vm.runInContext('('+source+')',sandbox)]));
let cases=0;
for(const [wire,expected] of [[461,403],[460,400],[458,401],[401,401],[200,200],[999,999]]){
  assert.equal(methods.convertUtasCodeToHttpStatus(wire),expected);cases++;
}
assert.equal(captured.enums.UtasErrorCode.PERMISSION_DENIED,461);
assert.equal(captured.enums.UtasErrorCode.CAPTCHA_REQUIRED,458);
for(const wire of [461,401]){
  let result;
  methods._notify.call({...methods,http:{status:wire,response:null,getResponseHeader:name=>{assert.equal(name,'Retry-After');return null;}},notify:v=>{result=v;}});
  assert.equal(result.status,wire===461?403:401);
  assert.equal(result.error.code,wire);assert.equal(result.success,false);cases++;
}
// This mapping diagnoses status translation. It cannot identify which native
// item was owned or prove the real server's reason for denying that operation.
assert.match(methods.generateErrorReason(461),/not owned/);
console.log('PASS '+cases+' captured native status translation cases; synthetic responses only');
