/* Optional real-browser smoke test. Reuse an installed Playwright; no provider mocks.
 * Set PLAYWRIGHT_MODULE to an installed playwright/playwright-core module if needed.
 * Reads only the local demo login password; never prints credentials or headers.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const env = fs.existsSync(path.join(root, '.env')) ? fs.readFileSync(path.join(root, '.env'), 'utf8') : '';
const password = process.env.DEMO_PASSWORD || env.split(/\r?\n/).find(line => line.startsWith('DEMO_PASSWORD='))?.slice(14).trim();
const origin = process.env.APP_ORIGIN || 'http://localhost:3000';
const readOnly = process.argv.includes('--read-only');

(async () => {
  assert(password, 'Configure local DEMO_PASSWORD first.');
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.setDefaultTimeout(20000);
  async function login(portal, email) {
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/v1/auth/me')),
      page.goto(`${origin}/${portal}/`),
    ]);
    await page.locator('#loginForm').waitFor({ state: 'visible' });
    await page.locator('#loginId').fill(email);
    await page.locator('#loginPass').fill(password);
    const [response] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/v1/auth/login')),
      page.locator('#loginSubmit').click(),
    ]);
    assert.equal(response.status(), 200);
    await page.locator('#app').waitFor({ state: 'visible' });
    return (await response.json()).user;
  }
  async function go(id) {
    await page.locator(`.nav button[data-page="${id}"]`).click();
    await page.locator(`#${id}.page.active`).waitFor({ state: 'visible' });
  }
  async function logout() {
    const [response] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/v1/auth/logout')),
      page.locator('#logoutBtn').click(),
    ]);
    assert.equal(response.status(), 200);
    assert.equal(await page.locator('#chatmessages').textContent(), '');
    await page.locator('#loginForm').waitFor({ state: 'visible' });
  }
  async function chat(question, expected, patientId = null) {
    await go('assistant');
    await page.locator('#chatInput').fill(question);
    const [response] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/ai/chat'), { timeout: 240000 }),
      page.locator('#chatForm button').click(),
    ]);
    const result = await response.json();
    assert.equal(response.status(), 200, result.error || 'Real generation failed');
    assert(result.answer.includes(expected), 'Real answer missed the expected synthetic value');
    await page.waitForFunction(answer => [...document.querySelectorAll('#chatmessages .bubble')].some(node => node.textContent.includes(answer)), result.answer);
    assert(result.citations.length > 0);
    const detail = page.locator('#chatmessages details').last();
    await detail.locator('summary').click();
    const href = await detail.locator('a').getAttribute('href');
    if (patientId) assert(href.startsWith(`/api/v1/doctor/patients/${patientId}/documents/`));
    const source = await context.request.get(origin + href.split('#')[0]);
    assert.equal(source.status(), 200);
    assert((await source.text()).includes(result.citations.at(-1).excerpt));
    console.log(JSON.stringify({ browser_chat_verified: patientId ? 'doctor' : 'patient', answer: result.answer, citation_source_status: source.status() }));
  }
  try {
    const patient = await login('patient', 'demo.patient@example.test');
    await page.waitForFunction(() => document.getElementById('vitalBp').textContent === '124/80');
    for (const [id, label, unit] of [['vitalHr', 'Fasting glucose', 'mg/dL'], ['vitalWeight', 'Hemoglobin', 'g/dL'], ['vitalSpo2', 'HbA1c', '%']]) {
      const card = page.locator(`#${id}`).locator('..');
      assert.equal(await card.locator('small').textContent(), label);
      assert.equal(await card.locator('span').textContent(), unit);
    }
    assert.equal(await page.locator('#statRecords').textContent(), '5');
    await go('history');
    await page.locator('#historyRows').getByText(/SYNTHETIC CLINICAL NOTE/).first().waitFor();
    await go('doctors');
    await page.waitForFunction(() => document.querySelectorAll('#doctorGrid .doctor-card').length === 100);
    await go('records');
    assert.equal(await page.locator('#recordsBody tr').count(), 5);
    const sourceUrl = await page.locator('#recordsBody a').first().getAttribute('href');
    const original = await context.request.get(origin + sourceUrl);
    assert.equal(original.status(), 200);
    await page.locator('[data-open="record"]').first().click();
    await page.locator('#documentFile').setInputFiles({ name: 'synthetic-existing-copy.txt', mimeType: 'text/plain', buffer: await original.body() });
    const [upload] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/v1/documents')),
      page.locator('#modalSave').click(),
    ]);
    assert.equal(upload.status(), 200);
    assert.equal((await upload.json()).duplicate, true);
    await page.waitForFunction(() => document.getElementById('uploadStatus').textContent.includes('already indexed'));
    await page.locator('#modalCancel').click();
    await page.locator('#modal').waitFor({ state: 'hidden' });
    if (!process.argv.includes('--skip-ai')) {
      await go('assistant');
      await context.setOffline(true);
      try {
        await page.locator('#chatInput').fill('What was my latest blood pressure?');
        await page.locator('#chatForm button').click();
        await page.locator('#chatmessages').getByText(/Cannot reach the CareConnect API/).waitFor();
        assert.equal(await page.locator('#chatForm button').isEnabled(), true);
      } finally { await context.setOffline(false); }
      await chat('What was my latest blood pressure? Include its report date.', '124/80');
    }
    await go('consent');
    await page.locator('#consentRows button').first().waitFor();
    assert((await page.locator('#consentRows').textContent()).includes('Dr. Demo Clinician 001'));
    if (!readOnly) {
    const consentRow = page.locator('#consentRows .card').filter({ hasText: 'Dr. Demo Clinician 001' });
    const [revoked] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/consents/')),
      consentRow.getByRole('button', { name: 'Revoke all access' }).click(),
    ]);
    assert.equal(revoked.status(), 200);
    assert.equal((await revoked.json()).consent.records, false);
    await consentRow.getByText('Access revoked.', { exact: false }).waitFor();
    for (const checkbox of await consentRow.locator('input[type="checkbox"]').all()) await checkbox.check();
    const [restored] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/consents/')),
      consentRow.getByRole('button', { name: 'Save permissions' }).click(),
    ]);
    assert.equal(restored.status(), 200);
    assert.equal((await restored.json()).consent.ai, true);
    }
    await go('appointments');
    await page.locator('#appointmentRows .activity-row').first().waitFor();
    if (!readOnly) {
    await page.locator('#appointments [data-open="appointment"]').click();
    const option = page.locator('#bookingDoctor option').filter({ hasText: 'Dr. Demo Clinician 001' });
    await page.locator('#bookingDoctor').selectOption(await option.getAttribute('value'));
    await page.locator('#bookingTime').fill(new Date(Date.now() + 10 * 86400000).toISOString().slice(0, 16));
    const reason = `SYNTHETIC browser booking verification ${Date.now()}`;
    await page.locator('#bookingReason').fill(reason);
    const [booked] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/patient/appointments')),
      page.locator('#modalSave').click(),
    ]);
    assert.equal(booked.status(), 201);
    await page.locator('#bookingStatus').getByText(/Appointment requested/).waitFor();
    await page.locator('#modalCancel').click();
    const appointment = page.locator('#appointmentRows .activity-row').filter({ hasText: reason });
    const [cancelled] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().includes('/patient/appointments/')),
      appointment.getByRole('button', { name: 'Cancel request' }).click(),
    ]);
    assert.equal(cancelled.status(), 200);
    assert.equal((await cancelled.json()).appointment.status, 'CANCELLED');
    }
    await go('audit');
    await page.locator('#auditRows .activity-row').first().waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator('#menuBtn').isVisible());
    await page.setViewportSize({ width: 1440, height: 1000 });
    await logout();

    await login('doctor', 'demo.doctor@example.test');
    await page.locator(`#selectedPatient option[value="${patient.id}"]`).waitFor({ state: 'attached' });
    await page.locator('#selectedPatient').selectOption(patient.id);
    await page.locator('#historyRows').getByText(/SYNTHETIC CLINICAL NOTE/).first().waitFor();
    assert((await page.locator('#patientContext').textContent()).includes('Demo Patient 001'));
    await go('reports');
    await page.waitForFunction(() => document.querySelectorAll('#reportsRows tr').length === 5);
    await go('records');
    await page.locator('#notesRows').getByText(/SYNTHETIC CLINICAL NOTE/).first().waitFor();
    if (!readOnly) {
    const content = 'SYNTHETIC BROWSER VERIFICATION NOTE: reviewed the fictional longitudinal reports. This test note is structured-only and is not AI evidence.';
    await page.locator('#noteContent').fill(content);
    const [note] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/notes')),
      page.locator('#saveNote').click(),
    ]);
    assert.equal(note.status(), 201);
    await page.locator('#notesRows').getByText(content, { exact: true }).waitFor();
    }
    await go('schedule');
    await page.locator('#appointmentRows tr').first().waitFor();
    if (!process.argv.includes('--skip-ai')) await chat('What is the latest hemoglobin value and report date?', '14.6', patient.id);
    await go('profile');
    assert(!(await page.locator('#profileFields').textContent()).includes('[object Object]'));
    await logout();
    await login('doctor', 'demo.unrelated@example.test');
    await page.waitForFunction(() => !document.getElementById('patientsStatus').textContent.includes('Loading'));
    assert.equal(await page.locator(`#selectedPatient option[value="${patient.id}"]`).count(), 0);
    const denied = await context.request.get(`${origin}/api/v1/doctor/patients/${patient.id}/documents`);
    assert.equal(denied.status(), 403);
    await logout();
    assert.deepEqual(pageErrors, []);
    console.log(JSON.stringify({ browser_workflows_verified: true, live_ai_exercised: !process.argv.includes('--skip-ai'), page_errors: pageErrors, unrelated_doctor_status: denied.status(), duplicate_upload_preserved: true, booking_cancel_note_and_consent_writes_verified: !readOnly, read_only_mode: readOnly }));
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error('Browser verification failed:', error.message);
  process.exitCode = 1;
});
