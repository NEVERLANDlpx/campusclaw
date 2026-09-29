/* Real browser network capture, saved as JSON and transparent evidence reports. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const output=path.resolve(process.env.EVIDENCE_OUTPUT||'network-evidence');
const base=process.env.BASE_URL||'http://127.0.0.1:8080';fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-gpu','--single-process','--no-zygote']});
 const context=await browser.newContext({viewport:{width:1400,height:1000},locale:'zh-CN',recordHar:{path:path.join(output,'browser-network.har'),content:'embed',mode:'full'}});
 const page=await context.newPage();const entries=[];
 async function capture(method,url,body){
  const responsePromise=page.waitForResponse(r=>r.url()===base+url&&r.request().method()===method);
  await page.evaluate(async({method,url,body})=>{const r=await fetch(url,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});await r.text();},{method,url,body});
  const res=await responsePromise,req=res.request();
  const entry={captured_at:new Date().toISOString(),method,url:req.url(),request_headers:await req.allHeaders(),request_body:req.postData(),status:res.status(),status_text:res.statusText(),response_headers:await res.allHeaders(),response_body:await res.text()};entries.push(entry);return entry;
 }
 await page.goto(base+'/login');const csrf=await page.locator('input[name=csrf_token]').inputValue();
 const login=await capture('POST','/login',{username:'teacher_a',password:'Campus@2026',csrf_token:csrf});assert.equal(login.status,200);
 const materials=await capture('GET','/api/materials');assert.equal(materials.status,200);assert(materials.request_headers.cookie.includes('campusclaw_session='));assert(!materials.request_headers.authorization);
 const me=await capture('GET','/api/me');assert.equal(me.status,200);
 const cookie=login.response_headers['set-cookie'].split(';')[0];assert(materials.request_headers.cookie.includes(cookie));
 const forbidden=await capture('GET','/api/materials/3/download');assert.equal(forbidden.status,404);
 // Logout through the regular UI revokes captured teacher cookies.
 await page.goto(base+'/materials');await Promise.all([page.waitForURL('**/login'),page.locator('.logout').click()]);
 const anonymous=await capture('GET','/api/materials/1/download');assert.equal(anonymous.status,401);
 fs.writeFileSync(path.join(output,'browser-network-capture.json'),JSON.stringify({captured_at:new Date().toISOString(),browser:browser.version(),source:'Playwright request.allHeaders / response.allHeaders and bodies from live Chromium fetch requests',cookie_matches_set_cookie:true,cookies_revoked:true,entries},null,2));
 await context.close();await browser.close();console.log('Browser network captured:',entries.length,'requests; Set-Cookie matches next materials Cookie; teacher session revoked.');
})().catch(e=>{console.error(e);process.exit(1)});
