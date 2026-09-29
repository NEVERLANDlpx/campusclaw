const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const base = process.env.BASE_URL || 'http://127.0.0.1:8080';
const output = path.resolve(process.env.EVIDENCE_OUTPUT || 'deliverables/03_截图与证据/browser-evidence');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
fs.mkdirSync(output, { recursive: true });

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, locale: 'zh-CN', acceptDownloads: true });
  const page = await context.newPage();
  const entries = [];

  async function pushEntry(res) {
    const req = res.request();
    const url = req.url();
    if (!url.startsWith(base)) return;
    const pathname = new URL(url).pathname;
    if (!(pathname === '/login' || pathname.startsWith('/api/materials') || pathname === '/api/me' || pathname === '/health')) return;
    entries.push({
      at: new Date().toISOString(),
      method: req.method(),
      url,
      resource_type: req.resourceType(),
      request_headers: await req.allHeaders(),
      post_data: req.postData(),
      status: res.status(),
      response_headers: await res.allHeaders(),
      response_body: '',
    });
  }
  page.on('response', response => pushEntry(response).catch(() => {}));

  await page.goto(base + '/login');
  await page.locator('#username').fill('teacher_a');
  await page.locator('#password').fill('Campus@2026');
  await Promise.all([page.waitForURL('**/materials'), page.locator('button[type=submit]').click()]);
  const firstMaterialsRes = await page.waitForResponse(r => r.url() === base + '/api/materials' && r.request().method() === 'GET');
  const firstMaterialsEntry = entries.findLast(e => e.url === base + '/api/materials' && e.method === 'GET');
  if (firstMaterialsEntry) firstMaterialsEntry.response_body = (await firstMaterialsRes.text()).slice(0, 2000);
  await page.waitForLoadState('networkidle');

  const teacherText = await page.locator('body').innerText();
  assert(teacherText.includes('教师 A'));
  assert(teacherText.includes('班级 A'));
  assert(teacherText.includes('上传教学材料'));
  assert(teacherText.includes('A 班'));
  assert(!teacherText.includes('B 班 · 独立教学材料'));

  const uploadFile = path.join(output, 'browser-upload.txt');
  fs.writeFileSync(uploadFile, '浏览器上传验收\n这是一份由 Playwright 通过真实页面上传的 txt。', 'utf8');
  await page.locator('#file').setInputFiles(uploadFile);
  await page.locator('#title').fill('浏览器网络验收材料');
  const uploadRes = await Promise.all([
    page.waitForResponse(r => r.url() === base + '/api/materials/upload' && r.request().method() === 'POST'),
    page.locator('#upload-form button[type=submit]').click(),
  ]).then(values => values[0]);
  assert.strictEqual(uploadRes.status(), 201);
  const uploadEntry = entries.findLast(e => e.url === base + '/api/materials/upload' && e.method === 'POST');
  if (uploadEntry) uploadEntry.response_body = '201 JSON response observed by browser; page immediately navigated to /materials?uploaded=1';

  await page.waitForURL('**/materials?uploaded=1');
  const afterUploadMaterials = await page.waitForResponse(r => r.url() === base + '/api/materials' && r.request().method() === 'GET');
  const afterUploadData = await afterUploadMaterials.json();
  const uploaded = afterUploadData.materials.filter(item => item.title === '浏览器网络验收材料').sort((a, b) => b.id - a.id)[0];
  assert(uploaded, 'uploaded material appears in refreshed materials list');
  const mid = uploaded.id;
  await page.goto(base + `/materials/${mid}`);
  const downloadEvent = page.waitForEvent('download');
  const downloadRes = await Promise.all([
    page.waitForResponse(r => r.url() === base + `/api/materials/${mid}/download` && r.request().method() === 'GET'),
    page.locator('.download-link').click(),
  ]).then(values => values[0]);
  const download = await downloadEvent;
  assert.strictEqual(downloadRes.status(), 200);
  assert((await downloadRes.headerValue('content-disposition')).includes('attachment'));
  await download.delete().catch(() => {});

  const csrf = await page.locator('input[name=csrf_token]').first().inputValue();
  await page.request.post(base + `/api/materials/${mid}/delete`, { form: { csrf_token: csrf } });
  await Promise.all([page.waitForURL('**/login'), page.locator('.logout').click()]);

  const anonDownload = await page.request.get(base + `/api/materials/${mid}/download`);
  entries.push({ at: new Date().toISOString(), method: 'GET', url: base + `/api/materials/${mid}/download`, resource_type: 'api_request_context', request_headers: {}, post_data: null, status: anonDownload.status(), response_headers: await anonDownload.headers(), response_body: (await anonDownload.text()).slice(0, 2000) });
  assert.strictEqual(anonDownload.status(), 401);

  await page.goto(base + '/login');
  await page.locator('#username').fill('student_a1');
  await page.locator('#password').fill('Campus@2026');
  await Promise.all([page.waitForURL('**/materials'), page.locator('button[type=submit]').click()]);
  await page.waitForResponse(r => r.url() === base + '/api/materials' && r.request().method() === 'GET');
  const studentText = await page.locator('body').innerText();
  assert(studentText.includes('学生 A1'));
  assert(!studentText.includes('上传教学材料'));

  const me = await page.request.get(base + '/api/me');
  const csrfStudent = (await me.json()).csrf_token;
  const studentUpload = await page.request.post(base + '/api/materials/upload', {
    multipart: {
      csrf_token: csrfStudent,
      title: '学生越权上传',
      file: { name: 'bad.txt', mimeType: 'text/plain', buffer: Buffer.from('student should fail') },
    },
  });
  entries.push({ at: new Date().toISOString(), method: 'POST', url: base + '/api/materials/upload', resource_type: 'api_request_context', request_headers: {}, post_data: 'multipart file=bad.txt title=学生越权上传', status: studentUpload.status(), response_headers: await studentUpload.headers(), response_body: (await studentUpload.text()).slice(0, 2000) });
  assert.strictEqual(studentUpload.status(), 403);

  const cross = await page.request.get(base + '/api/materials/3/download');
  entries.push({ at: new Date().toISOString(), method: 'GET', url: base + '/api/materials/3/download', resource_type: 'api_request_context', request_headers: {}, post_data: null, status: cross.status(), response_headers: await cross.headers(), response_body: (await cross.text()).slice(0, 2000) });
  assert.strictEqual(cross.status(), 404);

  const health = await page.request.get(base + '/health');
  entries.push({ at: new Date().toISOString(), method: 'GET', url: base + '/health', resource_type: 'api_request_context', request_headers: {}, post_data: null, status: health.status(), response_headers: await health.headers(), response_body: (await health.text()).slice(0, 2000) });
  assert.strictEqual(health.status(), 200);

  await page.screenshot({ path: path.join(output, 'teacher-page-after-validation.png'), fullPage: true });
  const browserVersion = browser.version();
  await context.close();
  await browser.close();

  const materialEntry = entries.find(e => e.url === base + '/api/materials' && e.method === 'GET' && e.request_headers.cookie);
  assert(materialEntry, 'materials fetch with Cookie was captured');
  fs.writeFileSync(path.join(output, 'browser-network-validation.json'), JSON.stringify({
    captured_at: new Date().toISOString(),
    base,
    browser: browserVersion,
    executablePath,
    assertions: [
      'teacher login redirects to /materials',
      'GET /api/materials was issued by browser page',
      'materials request carries campusclaw_session cookie',
      'A class list excludes B class sample',
      'teacher multipart upload returns 201',
      'download returns 200 attachment',
      'anonymous download returns 401',
      'student direct upload returns 403',
      'cross-class download returns 404',
      'anonymous health returns 200',
    ],
    entries,
  }, null, 2), 'utf8');
  console.log(`browser validation ok; entries=${entries.length}; output=${output}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
