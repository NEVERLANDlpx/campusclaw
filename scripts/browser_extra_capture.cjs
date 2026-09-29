const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert');
const output=path.resolve(process.env.EVIDENCE_OUTPUT||'extra-browser-evidence');
const base=process.env.BASE_URL||'http://127.0.0.1:8080';fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-gpu','--single-process','--no-zygote']});
 const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,locale:'zh-CN',acceptDownloads:true});
 const page=await context.newPage(),checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function screenshot(name){await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(output,name),fullPage:true});}
 async function login(name){await page.goto(base+'/login');await page.locator('[data-account="'+name+'"]').click();await Promise.all([page.waitForURL('**/materials'),page.locator('button[type=submit]').click()]);}
 async function logout(){await page.goto(base+'/materials');await Promise.all([page.waitForURL('**/login'),page.locator('.logout').click()]);}
 await login('teacher_a');
 // Send unsupported format using the file chooser's bypass available to any direct client.
 await page.locator('#file').setInputFiles({name:'unsupported.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4\nRejected example\n')});
 const response=page.waitForResponse(r=>r.url().endsWith('/api/materials/upload')&&r.request().method()==='POST');
 await page.locator('#upload-form button[type=submit]').click();assert.equal((await response).status(),400);
 await page.waitForFunction(()=>document.querySelector('#upload-result').textContent.includes('仅支持'));
 await screenshot('06a_PDF上传被服务端拒绝.png');checks.push('教师用文件选择器提交PDF，后端400，界面显示仅支持txt/md');
 await page.goto(base+'/materials/1');await screenshot('05a_教师原文件下载入口.png');
 const downloadPromise=page.waitForEvent('download');await page.locator('.download-link').click();const download=await downloadPromise;
 const teacherFile=path.join(output,'教师下载-sdd-guide.md');await download.saveAs(teacherFile);assert.equal(download.suggestedFilename(),'sdd-guide.md');checks.push('教师通过真实下载按钮保存sdd-guide.md');
 await logout();await login('student_a1');await page.goto(base+'/materials/1');assert.equal(await page.locator('.delete-form').count(),0);
 await screenshot('05b_学生可下载但不可删除.png');
 const studentPromise=page.waitForEvent('download');await page.locator('.download-link').click();const student=await studentPromise;
 const studentFile=path.join(output,'学生下载-sdd-guide.md');await student.saveAs(studentFile);
 assert(fs.readFileSync(studentFile).equals(fs.readFileSync(teacherFile)));checks.push('同班学生可下载，字节与教师下载一致，页面无删除入口');
 const api=await page.goto(base+'/api/me');assert.equal(api.status(),200);assert((await page.textContent('body')).includes('student_a1'));await screenshot('04a_浏览器直接访问身份API.png');checks.push('浏览器直接导航/api/me返回200及学生A1身份');
 const cross=await page.goto(base+'/api/materials/3/download');assert.equal(cross.status(),404);await screenshot('05c_跨班下载返回404.png');checks.push('学生A1直接导航B班下载API返回404');
 await logout();const anonymous=await page.goto(base+'/api/materials/1/download');assert.equal(anonymous.status(),401);await screenshot('05d_未登录下载返回401.png');checks.push('退出后直接导航下载API返回401');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'extra-browser-checks.json'),JSON.stringify({captured_at:new Date().toISOString(),browser:browser.version(),checks,download_sha256:crypto.createHash('sha256').update(fs.readFileSync(studentFile)).digest('hex'),console_errors:errors},null,2));
 await browser.close();console.log('Extra browser checks passed:',checks.length,'screenshots: 6');
})().catch(e=>{console.error(e);process.exit(1)});
