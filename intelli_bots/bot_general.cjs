// script_version: 1.0.0
// Purpose: Shared Node script preflight, versioned JSON and redacted diagnostic formatting.
// Usage: import scriptInterface/writeJson from bot_general.cjs; direct --help or --version describes this library.
// Output: library
'use strict';
const path = require('node:path');
let pendingDocument=null,structuredIdentity=null,unexpectedStdout=false;
process.once('exit',()=>{
  if (structuredIdentity && (unexpectedStdout || pendingDocument===null)) {
    pendingDocument=JSON.stringify({ok:false,error:'Invalid structured output',error_type:'OutputContractError',exit_code:1,info:{script:path.basename(structuredIdentity.script),script_version:structuredIdentity.version}})+'\n';
    process.exitCode=1;
  }
  if(pendingDocument!==null) {
    const bytes=Buffer.from(pendingDocument),deadline=Date.now()+10000,waiter=new Int32Array(new SharedArrayBuffer(4));let offset=0;
    while(offset<bytes.length) {
      try {offset+=require('node:fs').writeSync(1,bytes,offset,bytes.length-offset);}
      catch(error) {if(!['EAGAIN','EWOULDBLOCK','EINTR'].includes(error.code)||Date.now()>=deadline)throw error;Atomics.wait(waiter,0,0,1);}
    }
  }
});
function writeJson(value, identity, pretty = process.argv.includes('--pretty')) {
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new TypeError('JSON result must be an object');
  pendingDocument=JSON.stringify({...value,info:{...value.info,script:path.basename(identity.script),script_version:identity.version}},null,pretty?2:undefined)+'\n';
}
function scriptInterface(identity) {
  const args=process.argv.slice(2);const owned=args.includes('--')?args.slice(0,args.indexOf('--')):args;
  if (owned.includes('--version')) { process.stdout.write(path.basename(identity.script)+' '+identity.version+'\n');process.exit(0); }
  if (owned.includes('--help') || owned.includes('-h')) { process.stdout.write(identity.purpose+'\n'+identity.usage+'\nOutput: '+identity.output+'. JSON roles support --json/--pretty; other roles reject them before work.\n');process.exit(0); }
  const structured=owned.includes('--json') || owned.includes('--pretty');
  if (structured && identity.output!=='json') {writeJson({ok:false,error:'JSON CLI output unsupported for '+identity.output},identity);process.exit(2);}
  if (identity.output==='library') {process.stderr.write('Import this library; use --help or --version.\n');process.exit(2);}
  if (structured) {
    structuredIdentity=identity;
    // Hold stray console writes instead of corrupting the final JSON document.
    process.stdout.write=(chunk,encoding,callback)=>{unexpectedStdout=true;const done=typeof encoding==='function'?encoding:callback;if(done)process.nextTick(done);return true;};
    process.stderr.write=(chunk,encoding,callback)=>{const done=typeof encoding==='function'?encoding:callback;if(done)process.nextTick(done);return true;};
    process.once('uncaughtException',()=>{writeJson({ok:false,error:'Operation failed',exit_code:1},identity);process.exit(1);});
    process.once('unhandledRejection',()=>{writeJson({ok:false,error:'Operation failed',exit_code:1},identity);process.exit(1);});
  }
  if (!structured) {
    const script=path.basename(identity.script),run=require('node:crypto').randomBytes(3).toString('hex');
    const line=(new Error().stack.split('\n')[2]||'').match(/:(\d+):\d+\)?$/)?.[1]||'0';
    process.stderr.write(new Date().toISOString()+':main['+line+'] [INFO] '+script+' run='+run+' '+script+' script_version='+identity.version+'\n');
  }
  return identity;
}
module.exports={scriptInterface,writeJson};
if (require.main===module) scriptInterface({script:__filename,version:'1.0.0',purpose:'Shared Node script interface runtime.',usage:'bot_general.cjs --help | --version',output:'library'});
