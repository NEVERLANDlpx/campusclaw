const { chromium } = require('playwright');
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const base = process.env.BASE_URL || 'http://127.0.0.1:8080';
const output = path.resolve(process.env.EVIDENCE_OUTPUT || 'output/teacher-settings-browser');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const startedAt = new Date();
const runId = startedAt.toISOString().replace(/[:.]/g, '-');
const screenshotPath = path.join(output, `teacher-prompt-skill-settings-${runId}.png`);
const failureScreenshotPath = path.join(output, `teacher-prompt-skill-settings-failure-${runId}.png`);
const reportPath = path.join(output, `result-${runId}.json`);
fs.mkdirSync(output, {recursive: true});

async function main() {
  const browser = await chromium.launch({headless: true, executablePath});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'zh-CN'});
  const page = await context.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  const apiResults = [];
  const httpErrors = [];
  const assertions = {};
  const restoration = {attempted: false, succeeded: false, verified: false};
  let accessToken = null;
  let tutorAppId = null;
  let originalState = null;
  let runError = null;
  let restoreError = null;

  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname;
    if (response.status() >= 400) {
      httpErrors.push({method: response.request().method(), pathname, status: response.status()});
    }
    if (pathname.startsWith('/api/assistant/')) apiResults.push({method: response.request().method(), pathname, status: response.status()});
  });

  async function waitForAppSelect() {
    const select = page.locator('#assistant-app-select');
    await select.waitFor({state: 'visible'});
    return select;
  }

  async function selectTutor() {
    const select = await waitForAppSelect();
    assert(Number.isInteger(tutorAppId) && tutorAppId > 0, 'learning tutor app id is available');
    await select.selectOption(String(tutorAppId));
    await page.locator('#assistant-app-description').filter({hasText: '思路和步骤'}).waitFor();
    assert.strictEqual(Number(await select.inputValue()), tutorAppId, 'learning tutor app selected');
  }

  async function apiJson(method, pathname, data) {
    assert(accessToken, 'browser login must provide an access token before API snapshot/restore');
    const response = await context.request.fetch(base + pathname, {
      method,
      headers: {Authorization: `Bearer ${accessToken}`, Accept: 'application/json'},
      ...(data === undefined ? {} : {data}),
    });
    const body = await response.text();
    assert(response.ok(), `${method} ${pathname} failed with ${response.status()}: ${body.slice(0, 500)}`);
    return body ? JSON.parse(body) : {};
  }

  async function snapshotConfiguration() {
    const appDetail = await apiJson('GET', `/api/assistant/apps/${tutorAppId}`);
    const skills = (await apiJson('GET', '/api/assistant/skills')).items;
    return {
      app: appDetail.app,
      boundSkillIds: appDetail.skills.map(item => item.id).sort((a, b) => a - b),
      skills: skills.map(item => ({...item})),
    };
  }

  async function restoreConfiguration() {
    restoration.attempted = true;
    const app = originalState.app;
    await apiJson('PUT', `/api/assistant/apps/${tutorAppId}`, {
      system_prompt_template: app.system_prompt_template,
      model_override: app.model_override,
      temperature: app.temperature,
      max_tokens: app.max_tokens,
      retrieval_enabled: Boolean(app.retrieval_enabled),
      retrieval_mode: app.retrieval_mode,
      top_k: app.top_k,
      enabled: Boolean(app.enabled),
    });
    for (const skill of originalState.skills) {
      await apiJson('PUT', `/api/assistant/skills/${skill.id}`, {
        name: skill.name,
        description: skill.description,
        content: skill.content,
        trigger_keywords: skill.trigger_keywords,
        enabled: Boolean(skill.enabled),
        priority: skill.priority,
      });
    }
    await apiJson('PUT', `/api/assistant/apps/${tutorAppId}/skills`, {skill_ids: originalState.boundSkillIds});
    restoration.succeeded = true;

    const restored = await snapshotConfiguration();
    const appFields = ['system_prompt_template', 'model_override', 'temperature', 'max_tokens',
      'retrieval_enabled', 'retrieval_mode', 'top_k', 'enabled'];
    for (const field of appFields) {
      assert.deepStrictEqual(restored.app[field], originalState.app[field], `restored app field ${field}`);
    }
    assert.deepStrictEqual(restored.boundSkillIds, originalState.boundSkillIds, 'restored app Skill bindings');
    for (const expected of originalState.skills) {
      const actual = restored.skills.find(item => item.id === expected.id);
      assert(actual, `restored Skill ${expected.id} exists`);
      for (const field of ['name', 'description', 'content', 'trigger_keywords', 'enabled', 'priority']) {
        assert.deepStrictEqual(actual[field], expected[field], `restored Skill ${expected.id} field ${field}`);
      }
    }
    restoration.verified = true;
  }

  try {
    await page.goto(base + '/login');
    await page.locator('#username').fill('teacher_a');
    await page.locator('#password').fill('Campus@' + String(2026));
    await Promise.all([page.waitForURL('**/materials'), page.locator('#token-login-form button[type=submit]').click()]);
    await waitForAppSelect();
    assert(await page.locator('#save-assistant-settings').isVisible(), 'teacher settings are visible after teacher login');
    accessToken = await page.evaluate(() => sessionStorage.getItem('campusclaw_access_token'));
    assert(accessToken, 'teacher login stored a Bearer access token');
    assertions.teacher_login_and_permissions = true;

    const apps = (await apiJson('GET', '/api/assistant/apps')).apps;
    const tutor = apps.find(item => item.app_key === 'learning_tutor');
    assert(tutor, 'learning_tutor is available to the teacher');
    tutorAppId = tutor.id;
    await selectTutor();
    originalState = await snapshotConfiguration();
    assertions.learning_tutor_selected = true;

    const prompt = page.locator('#assistant-prompt');
    const original = {
      prompt: await prompt.inputValue(),
      temperature: await page.locator('#assistant-temperature').inputValue(),
      topK: await page.locator('#assistant-top-k').inputValue(),
      retrieval: await page.locator('#assistant-retrieval').isChecked(),
    };

    const templateLabels = ['通用 AI 对话模板', '课程知识库问答模板', '学习辅导助手模板', '课程工具助手模板'];
    const templateValues = [];
    for (const label of templateLabels) {
      await page.locator('#assistant-template-select').selectOption({label});
      const value = await prompt.inputValue();
      assert(value.length > 20, `${label} copied into editor`);
      templateValues.push(value);
    }
    assert.strictEqual(new Set(templateValues).size, 4, 'four templates produce distinct editor content');
    await page.locator('#assistant-template-select').selectOption('');
    assert.strictEqual(await prompt.inputValue(), original.prompt, 'no-template restores saved prompt');
    assertions.template_options = templateLabels;
    assertions.template_editor_values_distinct = true;

    await prompt.fill('{{not_allowed}}');
    await page.locator('#save-assistant-settings').click();
    await page.locator('#assistant-settings-status').filter({hasText: '不允许'}).waitFor();
    assert(await page.locator('#save-assistant-settings').isEnabled(), 'button recovers after failed save');
    assertions.failed_save_button_recovered = true;

    const marker = `浏览器配置验收-${Date.now()}`;
    await prompt.fill(original.prompt + '\n' + marker);
    await page.locator('#assistant-temperature').fill(original.temperature === '0.6' ? '0.7' : '0.6');
    await page.locator('#assistant-top-k').fill(original.topK === '5' ? '4' : '5');
    await page.locator('#assistant-retrieval').setChecked(!original.retrieval);
    await page.locator('#save-assistant-settings').click();
    await page.locator('#assistant-settings-status').filter({hasText: '已保存'}).waitFor();
    assert(await page.locator('#save-assistant-settings').isEnabled(), 'button recovers after successful save');
    await page.reload();
    await waitForAppSelect();
    await selectTutor();
    assert((await prompt.inputValue()).includes(marker), 'saved prompt persists after refresh');
    assertions.successful_save_persisted_after_refresh = true;

    await prompt.fill(original.prompt);
    await page.locator('#assistant-temperature').fill(original.temperature);
    await page.locator('#assistant-top-k').fill(original.topK);
    await page.locator('#assistant-retrieval').setChecked(original.retrieval);
    await page.locator('#save-assistant-settings').click();
    await page.locator('#assistant-settings-status').filter({hasText: '已保存'}).waitFor();

    const skillNames = ['解题引导', '知识库引用与证据约束', '课程术语与公式工具辅助'];
    for (const name of skillNames) {
      const card = page.locator('[data-skill-id]').filter({hasText: name}).first();
      await card.click();
      await page.locator('#assistant-skill-detail-name').filter({hasText: name}).waitFor();
      assert(await page.locator('#assistant-skill-detail').isVisible(), `${name} detail visible`);
      assert((await page.locator('#assistant-skill-content').inputValue()).length > 20, `${name} content visible`);
      const originalEnabled = await page.locator('#assistant-skill-enabled').isChecked();
      const originalBound = await page.locator('#assistant-skill-bound').isChecked();
      await page.locator('#assistant-skill-enabled').setChecked(!originalEnabled);
      await page.locator('#assistant-skill-bound').setChecked(!originalBound);
      await page.locator('#save-skill-settings').click();
      await page.locator('#assistant-skill-status').filter({hasText: '已保存'}).waitFor();
      await page.reload();
      await waitForAppSelect();
      await selectTutor();
      await page.locator('[data-skill-id]').filter({hasText: name}).first().click();
      assert.strictEqual(await page.locator('#assistant-skill-enabled').isChecked(), !originalEnabled, `${name} enabled state persists`);
      assert.strictEqual(await page.locator('#assistant-skill-bound').isChecked(), !originalBound, `${name} binding persists`);
      await page.locator('#assistant-skill-enabled').setChecked(originalEnabled);
      await page.locator('#assistant-skill-bound').setChecked(originalBound);
      await page.locator('#save-skill-settings').click();
      await page.locator('#assistant-skill-status').filter({hasText: '已保存'}).waitFor();
    }
    assertions.skill_cards_opened = skillNames;
    assertions.skill_enablement_and_binding_persisted_then_restored = true;

    await page.screenshot({path: screenshotPath, fullPage: true});
    assert.deepStrictEqual(pageErrors, [], `page errors: ${pageErrors.join('; ')}`);
    const unexpectedHttpErrors = httpErrors.filter(item =>
      !(item.method === 'PUT' && item.status === 400 && /\/api\/assistant\/apps\/\d+$/.test(item.pathname)) &&
      !(item.method === 'GET' && item.status === 404 && item.pathname === '/favicon.ico'));
    assert.deepStrictEqual(unexpectedHttpErrors, [], `unexpected HTTP errors: ${JSON.stringify(unexpectedHttpErrors)}`);
    assert(httpErrors.some(item => item.method === 'PUT' && item.status === 400 && /\/api\/assistant\/apps\/\d+$/.test(item.pathname)),
      'invalid Prompt save is rejected with HTTP 400');
    assert(apiResults.some(item => item.method === 'PUT' && /\/api\/assistant\/apps\/\d+$/.test(item.pathname) && item.status === 200));
    assert(apiResults.some(item => item.method === 'PUT' && /\/api\/assistant\/skills\/\d+$/.test(item.pathname) && item.status === 200));
    assertions.page_errors = pageErrors;
    assertions.expected_http_errors = httpErrors;
    assertions.unexpected_http_errors = unexpectedHttpErrors;
    assertions.console_messages_recorded = true;
    assertions.required_api_writes_observed = true;
  } catch (error) {
    runError = error;
    try {
      await page.screenshot({path: failureScreenshotPath, fullPage: true});
    } catch (_) {
      // The original failure remains authoritative if the diagnostic screenshot also fails.
    }
  } finally {
    if (originalState && accessToken && tutorAppId) {
      try {
        await restoreConfiguration();
      } catch (error) {
        restoreError = error;
      }
    }

    if (!restoreError && accessToken) {
      try {
        if (!page.url().startsWith(base)) await page.goto(base + '/materials');
        const logout = page.locator('.logout');
        if (await logout.isVisible()) {
          await Promise.all([page.waitForURL('**/login'), logout.click()]);
          assertions.logout_completed = true;
        }
      } catch (error) {
        if (!runError) runError = error;
      }
    }

    const effectiveError = runError || restoreError;
    const report = {
      captured_at: new Date().toISOString(),
      started_at: startedAt.toISOString(),
      status: effectiveError ? 'failed' : 'passed',
      base,
      browser: browser.version(),
      screenshot: fs.existsSync(screenshotPath) ? screenshotPath : null,
      failure_screenshot: fs.existsSync(failureScreenshotPath) ? failureScreenshotPath : null,
      assertions,
      page_errors: pageErrors,
      console_errors: consoleErrors,
      http_errors: httpErrors,
      restoration,
      failure: effectiveError ? {name: effectiveError.name, message: effectiveError.message, stack: effectiveError.stack} : null,
      api_results: apiResults,
    };
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    await context.close();
    await browser.close();
    if (effectiveError) throw effectiveError;
  }

  console.log(`teacher settings browser validation ok; screenshot=${screenshotPath}; report=${reportPath}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
