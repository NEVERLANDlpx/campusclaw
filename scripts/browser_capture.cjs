/* npm install playwright; npx playwright install chromium; node scripts/browser_capture.cjs */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const output=path.resolve(process.env.EVIDENCE_OUTPUT || 'browser-evidence');
const base=process.env.BASE_URL || 'http://127.0.0.1:8080';
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-gpu','--single-process','--no-zygote']});
 const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,locale:'zh-CN',timezoneId:'UTC'});
 const page=await context.newPage();const errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function shot(name){await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(output,name),fullPage:true});}
 async function login(name){await page.goto(base+'/login');await page.locator('[data-account="'+name+'"]').click();await Promise.all([page.waitForURL('**/materials'),page.locator('button[type=submit]').click()]);assert.equal(await page.locator('.user-card small').textContent(),name);}
 async function logout(){await Promise.all([page.waitForURL('**/login'),page.locator('.logout').click()]);}
 await page.goto(base+'/login');await shot('03a_登录页面.png');
 await login('teacher_a');checks.push('教师A通过真实浏览器登录');
 await page.locator('#file').setInputFiles({name:'login-session-lab.md',mimeType:'text/markdown',buffer:Buffer.from('# 登录身份与 HTTP 会话实验\n\n本材料由教师 A 在真实浏览器中上传。\n\n1. 登录时提交账号、密码和 CSRF 令牌。\n2. 响应通过 Set-Cookie 写入签名会话。\n3. 浏览器在后续请求中自动携带 Cookie。\n4. 服务端验证会话，再检查角色与班级。\n\n验收：A 班学生可以阅读本页，B 班访问同一材料返回 404。')});
 await page.locator('#title').fill('A 班 · 登录身份与 HTTP 会话实验');
 const resultPromise=page.waitForResponse(r=>r.url().endsWith('/api/materials/upload')&&r.request().method()==='POST');
 await page.locator('#upload-form button[type=submit]').click();const result=await resultPromise;assert.equal(result.status(),201);await page.waitForURL('**/materials?uploaded=1');const items=await page.evaluate(async()=> (await (await fetch('/api/materials')).json()).materials);const mid=items.find(x=>x.title==='A 班 · 登录身份与 HTTP 会话实验').id;
 await page.waitForURL('**/materials?uploaded=1');await shot('03b_教师登录与上传成功.png');checks.push('教师浏览器上传返回201并出现在真实数据库列表');
 await page.goto(base+'/materials/'+mid);assert((await page.locator('.document-body').textContent()).includes('本材料由教师 A'));await shot('03d_知识库入库正文.png');
 await logout();await login('student_a1');assert.equal(await page.locator('#upload-form').count(),0);assert((await page.locator('.material-list').textContent()).includes('登录身份与 HTTP 会话实验'));await shot('03c_学生A只读与本班可见.png');checks.push('学生A1列表可见教师新上传材料，且无上传入口');
 const forbidden=await page.evaluate(async()=>{let r=await fetch('/api/materials/upload',{method:'POST'});return{status:r.status,body:await r.json()}});assert.equal(forbidden.status,403);checks.push('学生强行POST上传实际返回403');
 const cross=await page.goto(base+'/materials/3');assert.equal(cross.status(),404);await shot('03f_跨班访问被拒绝.png');checks.push('学生A1访问B班材料页面实际返回404');
 await page.goto(base+'/materials');await page.setViewportSize({width:390,height:844});await shot('03g_手机端学生页面.png');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));checks.push('390px手机端无横向溢出');
 await page.setViewportSize({width:1440,height:1000});await logout();await login('student_b1');const btext=await page.locator('.material-list').textContent();assert(btext.includes('B 班')&&!btext.includes('A 班'));await shot('03e_学生B独立班级.png');checks.push('学生B1仅看到B班材料');
 await logout();assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(output,'browser-checks.json'),JSON.stringify({captured_at:new Date().toISOString(),browser:browser.version(),base,material_id:mid,checks,student_upload:forbidden,console_errors:errors},null,2));
 await browser.close();console.log('Browser checks passed:',checks.length,'screenshots: 7');
})().catch(e=>{console.error(e);process.exit(1)});
