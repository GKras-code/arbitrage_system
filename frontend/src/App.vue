<template>
  <div class="terminal-shell">
    <section v-if="!authenticated" class="login-screen">
      <form class="login-panel" @submit.prevent="login">
        <div class="brand-mark">A</div>
        <p class="eyebrow">ARBITRAGE TERMINAL</p>
        <h1>Market spread<br />monitoring</h1>
        <label>Логин<input v-model="credentials.username" autocomplete="username" required /></label>
        <label>Пароль<input v-model="credentials.password" type="password" autocomplete="current-password" required /></label>
        <p v-if="loginError" class="form-error">{{ loginError }}</p>
        <button class="primary-button" :disabled="loginPending">{{ loginPending ? 'Проверка...' : 'Войти в терминал' }}</button>
      </form>
      <div class="login-status"><span></span> Защищенное подключение</div>
    </section>

    <template v-else>
      <header class="topbar">
        <div class="brand"><div class="brand-mark">A</div><div><p class="eyebrow">ARBITRAGE TERMINAL</p><strong>Spread Monitor</strong></div></div>
        <div class="topbar-actions"><span class="market-status"><i></i> Рынок онлайн</span><span class="user-name">{{ username }}</span><button class="logout-button" title="Выйти из терминала" @click="logout">Выйти</button></div>
      </header>
      <main class="workspace">
        <section class="dashboard-heading">
          <div><p class="eyebrow">МЕЖРЫНОЧНЫЙ АРБИТРАЖ</p><h1>Арбитражные пары</h1><p>Сравнение фьючерсных контрактов CME и FORTS</p></div>
          <div class="heading-metrics"><div><span>ПАР</span><strong>{{ pairs.length }}</strong></div><div><span>ОБНОВЛЕНО</span><strong>{{ updatedAt }}</strong></div></div>
        </section>
        <section class="add-pair-row">
          <div><p class="section-label">НОВАЯ ПАРА</p><span>Выберите контракты из синхронизированных справочников EXANTE и BCS.</span></div>
          <form class="add-pair-form" @submit.prevent="addPair">
            <div class="pair-fields">
              <label class="pair-select">EXANTE / CME ticker
                <input v-model="newCmeName" list="exante-options" placeholder="Например AAPL.NASDAQ" maxlength="100" required @focus="scheduleInstrumentSearch('exante', newCmeName)" @input="scheduleInstrumentSearch('exante', newCmeName)" />
                <small class="pair-hint">{{ exanteHint }}</small>
              </label>
              <label class="pair-select">BCS / FORTS ticker
                <input v-model="newFortsName" list="bcs-options" placeholder="Например SBER" maxlength="100" @focus="scheduleInstrumentSearch('bcs', newFortsName)" @input="scheduleInstrumentSearch('bcs', newFortsName)" />
                <small class="pair-hint">{{ bcsHint }}</small>
              </label>
              <datalist id="exante-options">
                <option v-for="option in exanteOptions" :key="`exante-${option.value}`" :value="option.value">{{ option.label }}</option>
              </datalist>
              <datalist id="bcs-options">
                <option v-for="option in bcsOptions" :key="`bcs-${option.value}`" :value="option.value">{{ option.label }}</option>
              </datalist>
            </div>
            <button class="primary-button" :disabled="addingPair">{{ addingPair ? 'Добавление...' : 'Добавить пару' }}</button>
          </form>
        </section>
        <p v-if="tableError" class="form-error table-error">{{ tableError }}</p>
        <section class="table-section">
          <div class="table-toolbar"><span><i></i> CME / FORTS</span><span>{{ pairs.length }} инструмент{{ pairEnding }}</span></div>
          <div class="table-wrap"><table><thead><tr>
            <th>CME name</th><th>Дата exp</th><th>Price</th><th>CME margin</th><th>Lot</th><th>Virt_0</th><th>FORTS name</th><th>Дата exp</th><th>Price</th><th>Price ratio</th><th>FORTS margin, RUB</th><th>Lot</th><th>DTE</th><th>Diff</th><th>Diff, %</th><th>Diff, YTM margin</th>
          </tr></thead><tbody>
            <tr v-if="loading"><td colspan="16" class="empty-state">Загрузка данных...</td></tr>
            <tr v-else-if="!pairs.length"><td colspan="16" class="empty-state">Арбитражных пар пока нет.</td></tr>
            <tr v-for="pair in pairs" :key="pair.id">
              <td class="instrument">{{ pair.cme_name }}</td><td>{{ formatDate(pair.cme_expiration) }}</td><td>{{ formatNumber(pair.cme_price) }}</td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'cme_margin') }" @dblclick="startCellEdit(pair, 'cme_margin')"><input v-if="isEditingCell(pair.id, 'cme_margin')" ref="editorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.cme_margin, 0) }}</span></td><td>{{ formatNumber(pair.cme_lot) }}</td><td class="editable-cell" :class="[numberClass(pair.virt_0), { 'is-invalid': isInvalidCell(pair.id, 'virt_0') }]" @dblclick="startCellEdit(pair, 'virt_0')"><input v-if="isEditingCell(pair.id, 'virt_0')" ref="editorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.virt_0) }}</span></td><td class="instrument">{{ pair.forts_name || 'Ожидает настройки' }}</td><td>{{ formatDate(pair.forts_expiration) }}</td><td>{{ formatNumber(pair.forts_price) }}</td><td>{{ formatNumber(pair.price_ratio) }}</td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'forts_margin_rub') }" @dblclick="startCellEdit(pair, 'forts_margin_rub')"><input v-if="isEditingCell(pair.id, 'forts_margin_rub')" ref="editorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.forts_margin_rub, 0) }}</span></td><td>{{ formatNumber(pair.forts_lot) }}</td><td>{{ pair.dte ?? '—' }}</td><td :class="numberClass(pair.diff)">{{ formatNumber(pair.diff) }}</td><td :class="numberClass(pair.diff_percent)">{{ formatPercent(pair.diff_percent) }}</td><td :class="numberClass(pair.diff_ytm_margin)">{{ formatPercent(pair.diff_ytm_margin) }}</td>
            </tr>
          </tbody></table></div>
        </section>
      </main>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

const token = ref(localStorage.getItem('arbitrage_token') || '')
const username = ref(localStorage.getItem('arbitrage_username') || '')
const authenticated = computed(() => Boolean(token.value))
const credentials = ref({ username: '', password: '' })
const loginPending = ref(false)
const loginError = ref('')
const loading = ref(false)
const addingPair = ref(false)
const tableError = ref('')
const pairs = ref([])
const newCmeName = ref('')
const newFortsName = ref('')
const exanteOptions = ref([])
const bcsOptions = ref([])
const exanteHint = ref('Начните вводить тикер или symbolId EXANTE.')
const bcsHint = ref('Начните вводить тикер BCS.')
const updatedAt = ref('—')
const searchTimers = { exante: null, bcs: null }
const editingCell = ref(null)
const editorInput = ref(null)
const invalidCells = ref({})

function authHeaders() { return { Authorization: `Bearer ${token.value}` } }
async function login() {
  loginPending.value = true; loginError.value = ''
  try {
    const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(credentials.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить вход')
    token.value = data.access_token; username.value = data.username
    localStorage.setItem('arbitrage_token', token.value); localStorage.setItem('arbitrage_username', username.value)
    await loadPairs()
  } catch (error) { loginError.value = error.message } finally { loginPending.value = false }
}
async function loadPairs() {
  loading.value = true; tableError.value = ''
  try {
    const response = await fetch('/api/arbitrage-pairs', { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить данные')
    pairs.value = data.pairs
    updatedAt.value = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date())
  } catch (error) { tableError.value = error.message } finally { loading.value = false }
}
async function addPair() {
  addingPair.value = true; tableError.value = ''
  try {
    const response = await fetch('/api/arbitrage-pairs', { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ cme_name: newCmeName.value, forts_name: newFortsName.value }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось добавить пару')
    newCmeName.value = ''; newFortsName.value = ''; await loadPairs()
  } catch (error) { tableError.value = error.message } finally { addingPair.value = false }
}
function cellKey(pairId, field) { return `${pairId}:${field}` }
function isEditingCell(pairId, field) { return editingCell.value?.pairId === pairId && editingCell.value?.field === field }
function isInvalidCell(pairId, field) { return Boolean(invalidCells.value[cellKey(pairId, field)]) }
function startCellEdit(pair, field) {
  if (editingCell.value) return
  const key = cellKey(pair.id, field)
  delete invalidCells.value[key]
  editingCell.value = { pairId: pair.id, field, value: pair[field] ?? '', savedValue: pair[field] }
  nextTick(() => { editorInput.value?.focus(); editorInput.value?.select() })
}
function cancelCellEdit() { editingCell.value = null }
function validateManualValue(field, value) {
  const normalized = String(value).trim().replace(',', '.')
  if (!normalized || !/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(normalized)) return null
  const parsed = Number(normalized)
  if (!Number.isFinite(parsed) || ((field === 'cme_margin' || field === 'forts_margin_rub') && parsed < 0)) return null
  return normalized
}
async function saveCellEdit(pair) {
  const edit = editingCell.value
  if (!edit || edit.pairId !== pair.id) return
  const normalizedValue = validateManualValue(edit.field, edit.value)
  const key = cellKey(edit.pairId, edit.field)
  if (normalizedValue === null) {
    invalidCells.value[key] = true
    nextTick(() => editorInput.value?.focus())
    return
  }
  try {
    const response = await fetch(`/api/arbitrage-pairs/${pair.id}/manual-value`, {
      method: 'PATCH',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ field: edit.field, value: normalizedValue }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить значение')
    pair[edit.field] = data.value
    delete invalidCells.value[key]
    editingCell.value = null
  } catch (error) {
    invalidCells.value[key] = true
    tableError.value = error.message || 'Не удалось сохранить значение'
    nextTick(() => editorInput.value?.focus())
  }
}
async function loadInstrumentOptions(provider, query = '') {
  if (!token.value) return
  try {
    const response = await fetch(`/api/instrument-options?provider=${encodeURIComponent(provider)}&query=${encodeURIComponent(query)}&limit=20000`, { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить список тикеров')
    const items = Array.isArray(data.items) ? data.items : []
    if (provider === 'exante') {
      exanteOptions.value = items
      exanteHint.value = items.length ? `Найдено ${items.length} вариантов EXANTE.` : 'Совпадений EXANTE не найдено.'
    } else {
      bcsOptions.value = items
      bcsHint.value = items.length ? `Найдено ${items.length} вариантов BCS.` : 'Совпадений BCS не найдено.'
    }
  } catch (error) {
    const message = error.message || 'Не удалось получить список тикеров'
    if (provider === 'exante') {
      exanteHint.value = message
      exanteOptions.value = []
    } else {
      bcsHint.value = message
      bcsOptions.value = []
    }
  }
}
function scheduleInstrumentSearch(provider, query) {
  if (searchTimers[provider]) clearTimeout(searchTimers[provider])
  const normalized = (query || '').trim()
  searchTimers[provider] = setTimeout(() => { loadInstrumentOptions(provider, normalized) }, normalized ? 180 : 0)
}
function logout() { token.value = ''; username.value = ''; pairs.value = []; localStorage.removeItem('arbitrage_token'); localStorage.removeItem('arbitrage_username') }
function formatDate(value) { return value ? new Intl.DateTimeFormat('ru-RU').format(new Date(`${value}T00:00:00`)) : '—' }
function formatNumber(value, maximumFractionDigits = 2) { return value === null || value === undefined ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits }).format(value) }
function formatPercent(value) { return value === null || value === undefined ? '—' : `${formatNumber(value)}%` }
function numberClass(value) { return value > 0 ? 'positive' : value < 0 ? 'negative' : '' }
const pairEnding = computed(() => { const remainder = pairs.value.length % 10; return remainder === 1 && pairs.value.length % 100 !== 11 ? '' : remainder >= 2 && remainder <= 4 ? 'а' : 'ов' })
onMounted(() => { if (authenticated.value) { loadPairs(); loadInstrumentOptions('exante'); loadInstrumentOptions('bcs') } })
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700&display=swap');
:root { color: #e7ece9; background: #101414; font-family: Manrope, sans-serif; } * { box-sizing: border-box; } body { margin: 0; min-width: 320px; background: #101414; } button, input { font: inherit; } button { cursor: pointer; }
.terminal-shell { min-height: 100vh; background: linear-gradient(120deg, #101414, #151b1a 55%, #161b18); } .eyebrow, .section-label { margin: 0; color: #77d6b6; font: 600 10px 'IBM Plex Mono', monospace; letter-spacing: 1.4px; }
.login-screen { min-height: 100vh; display: grid; place-content: center; position: relative; padding: 24px; overflow: hidden; } .login-screen::before { content: ''; position: absolute; inset: 0; background-image: linear-gradient(rgba(119,214,182,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(119,214,182,.035) 1px, transparent 1px); background-size: 40px 40px; } .login-panel { width: min(100%,410px); position: relative; border: 1px solid #35423d; border-top: 2px solid #77d6b6; padding: 38px; background: rgba(20,27,25,.96); box-shadow: 0 28px 70px rgba(0,0,0,.28); } .brand-mark { width: 34px; height: 34px; display: grid; place-items: center; color: #10201b; background: #77d6b6; font: 700 20px 'IBM Plex Mono', monospace; } .login-panel .brand-mark { margin-bottom: 22px; } .login-panel h1 { margin: 10px 0 12px; font-size: 28px; line-height: 1.18; letter-spacing: 0; } .login-copy { margin: 0 0 28px; color: #9eaaa4; font-size: 13px; line-height: 1.65; }
label { display: block; margin: 15px 0; color: #aeb9b3; font: 500 11px 'IBM Plex Mono', monospace; letter-spacing: .6px; text-transform: uppercase; } input { width: 100%; margin-top: 7px; border: 1px solid #3b4742; border-radius: 2px; padding: 11px 12px; outline: none; color: #eef6f1; background: #101514; } input:focus { border-color: #77d6b6; } .primary-button { border: 1px solid #77d6b6; border-radius: 2px; padding: 11px 16px; color: #10201b; background: #77d6b6; font-weight: 700; font-size: 12px; letter-spacing: .2px; } .primary-button:hover { background: #9ae3c9; } .primary-button:disabled { cursor: wait; opacity: .65; } .login-panel .primary-button { width: 100%; margin-top: 12px; } .form-error { margin: 12px 0 0; color: #ff9d8b; font-size: 12px; } .login-status { position: absolute; bottom: 28px; color: #72827a; font: 10px 'IBM Plex Mono', monospace; letter-spacing: .4px; } .login-status span, .market-status i, .table-toolbar i { display: inline-block; width: 7px; height: 7px; margin-right: 7px; border-radius: 50%; background: #77d6b6; box-shadow: 0 0 12px #77d6b6; }
.topbar { min-height: 70px; display: flex; justify-content: space-between; align-items: center; padding: 12px max(22px, calc((100% - 1440px) / 2)); border-bottom: 1px solid #2c3632; background: rgba(14,19,18,.94); } .brand, .topbar-actions { display: flex; align-items: center; gap: 12px; } .brand strong { display: block; margin-top: 3px; font-size: 14px; } .market-status, .user-name, .logout-button { color: #aeb9b3; font: 11px 'IBM Plex Mono', monospace; } .logout-button { border: 1px solid #3b4742; border-radius: 2px; padding: 8px 10px; background: transparent; } .logout-button:hover { color: #fff; border-color: #76837d; }
.workspace { max-width: 1440px; margin: 0 auto; padding: 46px 22px; } .dashboard-heading { display: flex; justify-content: space-between; align-items: end; gap: 24px; margin-bottom: 34px; } .dashboard-heading h1 { margin: 8px 0 7px; font-size: clamp(26px,3vw,38px); line-height: 1; letter-spacing: 0; } .dashboard-heading > div > p:last-child, .add-pair-row span { margin: 0; color: #8f9d96; font-size: 13px; } .heading-metrics { display: flex; gap: 30px; } .heading-metrics div { min-width: 84px; border-left: 1px solid #3a4641; padding-left: 12px; } .heading-metrics span { display: block; color: #7f8d86; font: 10px 'IBM Plex Mono', monospace; letter-spacing: .7px; } .heading-metrics strong { display: block; margin-top: 4px; color: #e4eee9; font: 600 15px 'IBM Plex Mono', monospace; }
.add-pair-row { display: flex; justify-content: space-between; align-items: end; gap: 24px; padding: 19px 20px; margin-bottom: 18px; border: 1px solid #35423d; background: #19201e; } .section-label { margin-bottom: 7px; } .add-pair-form { display: flex; width: min(100%,700px); gap: 8px; align-items: end; } .pair-fields { display: flex; flex: 1; gap: 8px; } .pair-fields input { margin: 0; flex: 1; min-width: 0; } .pair-select { flex: 1; margin: 0; min-width: 0; } .pair-select input { margin-top: 7px; } .pair-hint { display: block; margin-top: 7px; color: #7f8d86; font-size: 11px; line-height: 1.4; text-transform: none; letter-spacing: 0; } .add-pair-form .primary-button { white-space: nowrap; } .table-section { border: 1px solid #35423d; background: #141a18; } .table-toolbar { display: flex; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #35423d; color: #aeb9b3; font: 11px 'IBM Plex Mono', monospace; } .table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font: 11px 'IBM Plex Mono', monospace; } th { padding: 13px 12px; color: #84948c; font-weight: 500; text-align: right; white-space: nowrap; background: #171e1b; } td { padding: 14px 12px; color: #dbe4df; text-align: right; white-space: nowrap; border-top: 1px solid #28322e; } th:first-child, th:nth-child(7), td:first-child, td:nth-child(7) { text-align: left; } tbody tr:hover { background: #1a2420; } .instrument { color: #f0f7f3; font-weight: 600; } .positive { color: #75dbb6; } .negative { color: #ff9989; } .editable-cell { cursor: text; outline: 1px dashed transparent; outline-offset: -4px; } .editable-cell:hover { outline-color: #587269; background: #18221e; } .editable-cell input { width: 100%; min-width: 72px; margin: -7px 0; border-color: #77d6b6; padding: 6px 7px; text-align: right; font: inherit; } .editable-cell.is-invalid { color: #ff9d8b; outline-color: #ff7567; background: rgba(158, 54, 44, .24); } .editable-cell.is-invalid input { border-color: #ff7567; } .empty-state { padding: 35px; color: #8f9d96; text-align: center !important; } .table-error { margin-bottom: 14px; }
@media (max-width: 700px) { .topbar, .dashboard-heading, .add-pair-row { align-items: flex-start; flex-direction: column; } .topbar-actions { width: 100%; justify-content: space-between; } .workspace { padding: 30px 14px; } .heading-metrics { width: 100%; } .add-pair-form { width: 100%; flex-direction: column; } .pair-fields { width: 100%; flex-direction: column; } .pair-select { width: 100%; } .add-pair-form .primary-button { width: 100%; } .login-panel { padding: 28px 23px; } }
</style>