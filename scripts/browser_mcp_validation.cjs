const { chromium } = require('playwright');
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const base = process.env.BASE_URL || 'http://127.0.0.1:8080';
const expectFailure = process.env.EXPECT_MCP_FAILURE === '1';
const output = path.resolve(process.env.EVIDENCE_OUTPUT || 'output/mcp-browser');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const startedAt = new Date();
const runId = startedAt.toISOString().replace(/[:.]/g, '-');
const mode = expectFailure ? 'failure' : 'success';
const screenshotPath = path.join(output, `mcp-${mode}-${runId}.png`);
const reportPath = path.join(output, `mcp-${mode}-${runId}.json`);
fs.mkdirSync(output, {recursive: true});

async function main() {
  const browser = await chromium.launch({headless:true,executablePath});
  const context = await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN'});
  const page = await context.newPage();
  const pageErrors = [];
  const apiResults = [];
  const assertions = {};
  let failure = null;
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith('/api/mcp/') || pathname.includes('/tools')) {
      apiResults.push({method:response.request().method(),pathname,status:response.status()});
    }
  });
  await page.route('**/api/mcp/servers/*/connect', async route => {
    await new Promise(resolve => setTimeout(resolve,250));
    await route.continue();
  });

  try {
    await page.goto(base + '/login');
    await page.locator('#username').fill('teacher_a');
    await page.locator('#password').fill('Campus@' + String(2026));
    await Promise.all([page.waitForURL('**/materials'),page.locator('#token-login-form button[type=submit]').click()]);
    await page.locator('#assistant-app-select').waitFor({state:'visible'});
    assert(await page.locator('#mcp-server-list').isVisible(),'teacher can see MCP management');
    assertions.teacher_login_and_mcp_management_visible = true;

    const serverCard = page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first();
    await serverCard.waitFor({state:'visible'});
    const connectButton = serverCard.locator('[data-mcp-action="connect"]');
    assert(await connectButton.isVisible(),'connect and discover button is visible');
    const responsePromise = page.waitForResponse(response => /\/api\/mcp\/servers\/\d+\/connect$/.test(new URL(response.url()).pathname));
    await connectButton.click();
    await page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first().locator('[data-mcp-action="connect"]').waitFor({state:'visible'});
    assert(await page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first().locator('[data-mcp-action="connect"]').isDisabled(),'duplicate connect click is disabled while pending');
    assertions.concurrent_connect_prevented = true;
    const connectResponse = await responsePromise;

    if (expectFailure) {
      assert.strictEqual(connectResponse.status(),503,'unavailable MCP service returns 503');
      await page.locator('#management-status').filter({hasText:'连接失败'}).waitFor();
      await page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first().locator('.mcp-status.error').waitFor();
      const errorText = await page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first().locator('.mcp-server-error').textContent();
      assert(errorText && errorText.includes('网络连接失败'),'diagnostic network error is visible');
      assertions.failure_status_and_diagnostic_visible = true;
    } else {
      assert.strictEqual(connectResponse.status(),200,'real MCP connect succeeds');
      await page.locator('#management-status').filter({hasText:'MCP 已连接，发现 2 个工具'}).waitFor();
      const connectedCard = page.locator('[data-mcp-server-id]').filter({hasText:'course-tools'}).first();
      await connectedCard.locator('.mcp-status.connected').waitFor();
      await connectedCard.getByText('lookup_course_glossary',{exact:true}).waitFor();
      await connectedCard.getByText('formula_hint',{exact:true}).waitFor();
      await connectedCard.getByText('lookup_course_glossary',{exact:true}).click();
      await connectedCard.getByText('term',{exact:false}).waitFor();
      assertions.real_tools_and_schema_visible = ['lookup_course_glossary','formula_hint'];

      const appSelect = page.locator('#assistant-app-select');
      const toolAppOption = appSelect.locator('option').filter({hasText:'课程工具助手'}).first();
      const toolAppId = await toolAppOption.getAttribute('value');
      assert(toolAppId,'course tool app option exists');
      await appSelect.selectOption(toolAppId);
      await page.locator('#assistant-app-description').filter({hasText:'授权的 MCP 工具'}).waitFor();
      await page.locator('[data-skill-id]').filter({hasText:'课程术语与公式工具辅助'}).first().click();
      let toolCheckbox = page.locator('#assistant-skill-tools input[value="lookup_course_glossary@course-tools"]');
      await toolCheckbox.waitFor({state:'visible'});
      if (await toolCheckbox.isChecked()) {
        await toolCheckbox.setChecked(false);
        const clearResponsePromise = page.waitForResponse(response => /\/api\/assistant\/skills\/\d+\/tools$/.test(new URL(response.url()).pathname));
        await page.locator('#save-skill-settings').click();
        assert.strictEqual((await clearResponsePromise).status(),200,'existing Skill tool binding can be cleared before re-validation');
        await page.waitForFunction(() => !document.getElementById('save-skill-settings')?.disabled);
        toolCheckbox = page.locator('#assistant-skill-tools input[value="lookup_course_glossary@course-tools"]');
        await toolCheckbox.waitFor({state:'visible'});
      }
      await toolCheckbox.setChecked(true);
      const bindResponsePromise = page.waitForResponse(response => /\/api\/assistant\/skills\/\d+\/tools$/.test(new URL(response.url()).pathname));
      await page.locator('#save-skill-settings').click();
      const bindResponse = await bindResponsePromise;
      assert.strictEqual(bindResponse.status(),200,'Skill tool binding save succeeds');
      await page.locator('#assistant-skill-status').filter({hasText:'已保存'}).waitFor();
      await page.reload();
      await appSelect.waitFor({state:'visible'});
      await appSelect.selectOption(toolAppId);
      await page.locator('[data-skill-id]').filter({hasText:'课程术语与公式工具辅助'}).first().click();
      assert(await page.locator('#assistant-skill-tools input[value="lookup_course_glossary@course-tools"]').isChecked(),'tool binding persists after refresh');
      assertions.skill_tool_binding_persisted = true;
    }

    await page.screenshot({path:screenshotPath,fullPage:true});
    assert.deepStrictEqual(pageErrors,[],'browser page has no unhandled JavaScript errors');
    assertions.page_errors = pageErrors;
    await Promise.all([page.waitForURL('**/login'),page.locator('.logout').click()]);
    assertions.logout_completed = true;
  } catch (error) {
    failure = error;
    try { await page.screenshot({path:screenshotPath,fullPage:true}); } catch (_) { /* Preserve the original error. */ }
    throw error;
  } finally {
    const report = {
      captured_at:new Date().toISOString(),started_at:startedAt.toISOString(),status:failure ? 'failed' : 'passed',mode,
      base,browser:browser.version(),screenshot:fs.existsSync(screenshotPath) ? screenshotPath : null,
      assertions,page_errors:pageErrors,api_results:apiResults,
      failure:failure ? {name:failure.name,message:failure.message,stack:failure.stack} : null,
    };
    fs.writeFileSync(reportPath,JSON.stringify(report,null,2),'utf8');
    await context.close();
    await browser.close();
  }
  console.log(`mcp browser validation ok; mode=${mode}; screenshot=${screenshotPath}; report=${reportPath}`);
}

main().catch(error => { console.error(error); process.exit(1); });
