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
        <section class="currency-rates" aria-label="Официальные курсы ЦБ РФ">
          <div class="currency-rates-title"><span>КУРСЫ ЦБ РФ</span><small>официальный курс за {{ currencyRateDate }}</small></div>
          <div class="currency-rate" v-for="rate in currencyRates" :key="rate.currency_code"><strong>{{ rate.currency_code }}/RUB</strong><span>{{ formatNumber(rate.rate, 4) }} RUB</span></div>
          <span v-if="!currencyRates.length" class="currency-rates-empty">Курсы пока недоступны</span>
        </section>
        <section class="table-section">
          <div class="table-toolbar"><span><i></i> CME / FORTS</span><div class="table-toolbar-actions"><span>{{ pairs.length }} инструмент{{ pairEnding }}</span><button class="details-toggle" type="button" :aria-expanded="showContractDetails" @click="showContractDetails = !showContractDetails">{{ showContractDetails ? 'Скрыть параметры' : 'Параметры контрактов' }}</button></div></div>
          <div class="table-wrap"><table :class="{ 'is-compact': !showContractDetails }"><colgroup v-if="!showContractDetails"><col class="contract-column" /><col class="date-column" /><col class="price-column" /><col class="contract-column" /><col class="date-column" /><col class="price-column" /><col class="ratio-column" /><col class="dte-column" /><col class="virt-column" /><col class="diff-column" /><col class="percent-column" /><col class="ytm-column" /><col class="action-column" /></colgroup><thead><tr>
            <th><span class="header-label">CME<br>name</span></th><th><span class="header-label">CME<br>exp</span></th><th><span class="header-label">CME<br>price</span></th><th v-if="showContractDetails"><span class="header-label">CME margin,<br>USD</span></th><th v-if="showContractDetails"><span class="header-label">CME<br>lot</span></th><th><span class="header-label">FORTS<br>name</span></th><th><span class="header-label">FORTS<br>exp</span></th><th><span class="header-label">FORTS<br>price</span></th><th><span class="header-label">Price<br>ratio</span></th><th v-if="showContractDetails"><span class="header-label">FORTS margin,<br>RUB</span></th><th v-if="showContractDetails"><span class="header-label">Price<br>step</span></th><th v-if="showContractDetails"><span class="header-label">Step<br>value</span></th><th v-if="showContractDetails"><span class="header-label">Trade<br>lot</span></th><th v-if="showContractDetails"><span class="header-label">Trade lot<br>currency</span></th><th>DTE</th><th>Virt_0</th><th :aria-sort="sortAria('diff')"><button type="button" class="sort-header" :class="{ 'is-active': sortColumn === 'diff' }" title="Сортировать по Diff" @click="sortPairs('diff')">Diff <span aria-hidden="true">{{ sortIcon('diff') }}</span></button></th><th :aria-sort="sortAria('diff_percent')"><button type="button" class="sort-header" :class="{ 'is-active': sortColumn === 'diff_percent' }" title="Сортировать по Diff, %" @click="sortPairs('diff_percent')"><span class="header-label">Diff,<br>%</span> <span aria-hidden="true">{{ sortIcon('diff_percent') }}</span></button></th><th :aria-sort="sortAria('diff_ytm_margin')"><button type="button" class="sort-header" :class="{ 'is-active': sortColumn === 'diff_ytm_margin' }" title="Сортировать по Diff, YTM" @click="sortPairs('diff_ytm_margin')"><span class="header-label">Diff,<br>YTM</span> <span aria-hidden="true">{{ sortIcon('diff_ytm_margin') }}</span></button></th><th aria-label="Действия"></th>
          </tr></thead><tbody>
            <tr v-if="loading"><td :colspan="visibleColumnCount" class="empty-state">Загрузка данных...</td></tr>
            <tr v-else-if="!pairs.length"><td :colspan="visibleColumnCount" class="empty-state">Арбитражных пар пока нет.</td></tr>
            <tr v-for="pair in sortedPairs" :key="pair.id">
              <td class="instrument" :title="pair.cme_name">{{ pair.cme_name }}</td>
              <td>{{ formatDate(pair.cme_data_exp) }}</td>
              <td>{{ formatExactNumber(pair.cme_price) }}</td>
              <td v-if="showContractDetails" class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'cme_margin_usd') }" @click="startCellEdit(pair, 'cme_margin_usd')"><input v-if="isEditingCell(pair.id, 'cme_margin_usd')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.cme_margin_usd, 0) }}</span></td>
              <td v-if="showContractDetails">{{ formatNumber(pair.cme_lot) }}</td>
              <td class="instrument" :title="pair.forts_name || 'Ожидает настройки'">{{ pair.forts_name || 'Ожидает настройки' }}</td>
              <td>{{ formatDate(pair.forts_data_exp) }}</td>
              <td>{{ formatExactNumber(pair.forts_price) }}</td>
              <td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'price_ratio') }" @click="startCellEdit(pair, 'price_ratio')"><input v-if="isEditingCell(pair.id, 'price_ratio')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.price_ratio) }}</span></td>
              <td v-if="showContractDetails">{{ formatNumber(pair.forts_margin_rub, 0) }}</td>
              <td v-if="showContractDetails">{{ formatNumber(pair.forts_price_step, 8) }}</td>
              <td v-if="showContractDetails">{{ formatNumber(pair.forts_price_step_value, 8) }}</td>
              <td v-if="showContractDetails">{{ formatNumber(pair.forts_trade_lot, 4) }}</td>
              <td v-if="showContractDetails"><select class="trade-lot-currency" :value="pair.trade_lot_currency" :disabled="updatingCurrencyPairId === pair.id" :aria-label="`Валюта расчёта Trade lot для ${pair.cme_name}`" @change="updateTradeLotCurrency(pair, $event.target.value)"><option value="USD">USD</option><option value="CNY">CNY</option></select></td>
              <td>{{ pair.dte ?? '—' }}</td>
              <td class="editable-cell" :class="[numberClass(pair.virt_0), { 'is-invalid': isInvalidCell(pair.id, 'virt_0') }]" @click="startCellEdit(pair, 'virt_0')"><input v-if="isEditingCell(pair.id, 'virt_0')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.virt_0) }}</span></td>
              <td :class="numberClass(pair.diff)">{{ formatExactNumber(pair.diff) }}</td>
              <td :class="numberClass(pair.diff_percent)">{{ formatPercent(pair.diff_percent) }}</td>
              <td :class="numberClass(pair.diff_ytm_margin)">{{ formatPercent(pair.diff_ytm_margin) }}</td>
              <td class="pair-action"><button class="delete-pair-button" type="button" :disabled="deletingPairId === pair.id" :title="`Удалить ${pair.cme_name} / ${pair.forts_name || 'FORTS'}`" :aria-label="`Удалить пару ${pair.cme_name} / ${pair.forts_name || 'FORTS'}`" @click.stop="deletePair(pair)">×</button></td>
            </tr>
          </tbody></table></div>
        </section>
      </main>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

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
const sortColumn = ref(null)
const sortDirection = ref('desc')
const newCmeName = ref('')
const newFortsName = ref('')
const exanteOptions = ref([])
const bcsOptions = ref([])
const exanteHint = ref('Начните вводить тикер или symbolId EXANTE.')
const bcsHint = ref('Начните вводить тикер BCS.')
const updatedAt = ref('—')
const currencyRates = ref([])
const searchTimers = { exante: null, bcs: null }
const editingCell = ref(null)
const editorInput = ref(null)
const invalidCells = ref({})
const showContractDetails = ref(false)
const deletingPairId = ref(null)
const updatingCurrencyPairId = ref(null)
let priceEvents = null
let priceRefreshTimer = null

function authHeaders() { return { Authorization: `Bearer ${token.value}` } }
async function login() {
  loginPending.value = true; loginError.value = ''
  try {
    const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(credentials.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить вход')
    token.value = data.access_token; username.value = data.username
    localStorage.setItem('arbitrage_token', token.value); localStorage.setItem('arbitrage_username', username.value)
    await Promise.all([loadPairs(), loadCurrencyRates()]); connectPriceEvents()
  } catch (error) { loginError.value = error.message } finally { loginPending.value = false }
}
async function loadPairs(showLoading = true) {
  if (showLoading) loading.value = true
  tableError.value = ''
  try {
    const response = await fetch('/api/arbitrage-pairs', { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить данные')
    pairs.value = data.pairs
    updatedAt.value = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date())
  } catch (error) { tableError.value = error.message } finally { if (showLoading) loading.value = false }
}
async function loadCurrencyRates() {
  try {
    const response = await fetch('/api/currency-rates', { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить курсы валют')
    currencyRates.value = Array.isArray(data.rates) ? data.rates : []
  } catch (error) {
    currencyRates.value = []
  }
}
function connectPriceEvents() {
  priceEvents?.close()
  priceEvents = new EventSource(`/api/arbitrage-pairs/events?token=${encodeURIComponent(token.value)}`)
  priceEvents.onmessage = () => {
    if (priceRefreshTimer) return
    priceRefreshTimer = setTimeout(() => { priceRefreshTimer = null; loadPairs(false) }, 100)
  }
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
async function deletePair(pair) {
  const pairLabel = `${pair.cme_name} / ${pair.forts_name || 'FORTS'}`
  if (!window.confirm(`Удалить пару ${pairLabel}?`)) return
  deletingPairId.value = pair.id
  tableError.value = ''
  try {
    const response = await fetch(`/api/arbitrage-pairs/${pair.id}`, { method: 'DELETE', headers: authHeaders() })
    if (response.status === 401) return logout()
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Не удалось удалить пару')
    }
    pairs.value = pairs.value.filter(item => item.id !== pair.id)
    if (editingCell.value?.pairId === pair.id) editingCell.value = null
  } catch (error) {
    tableError.value = error.message || 'Не удалось удалить пару'
  } finally {
    deletingPairId.value = null
  }
}
async function updateTradeLotCurrency(pair, currency) {
  if (currency === pair.trade_lot_currency) return
  updatingCurrencyPairId.value = pair.id
  tableError.value = ''
  try {
    const response = await fetch(`/api/arbitrage-pairs/${pair.id}/trade-lot-currency`, {
      method: 'PATCH',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ currency }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить валюту расчёта')
    pair.trade_lot_currency = data.trade_lot_currency
    await loadPairs(false)
  } catch (error) {
    tableError.value = error.message || 'Не удалось сохранить валюту расчёта'
    await loadPairs(false)
  } finally {
    updatingCurrencyPairId.value = null
  }
}
function cellKey(pairId, field) { return `${pairId}:${field}` }
function isEditingCell(pairId, field) { return editingCell.value?.pairId === pairId && editingCell.value?.field === field }
function isInvalidCell(pairId, field) { return Boolean(invalidCells.value[cellKey(pairId, field)]) }
function setEditorInput(element) { editorInput.value = element }
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
  if (!Number.isFinite(parsed) || field === 'cme_margin_usd' && parsed < 0) return null
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
function logout() { priceEvents?.close(); priceEvents = null; token.value = ''; username.value = ''; pairs.value = []; localStorage.removeItem('arbitrage_token'); localStorage.removeItem('arbitrage_username') }
function formatDate(value) { return value ? new Intl.DateTimeFormat('ru-RU').format(new Date(`${value}T00:00:00`)) : '—' }
function formatNumber(value, maximumFractionDigits = 2) { return value === null || value === undefined ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits }).format(value) }
function formatExactNumber(value) { return value === null || value === undefined ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 20 }).format(value) }
function formatPercent(value) { return value === null || value === undefined ? '—' : `${formatNumber(value * 100)}%` }
function numberClass(value) { return value > 0 ? 'positive' : value < 0 ? 'negative' : '' }
function sortPairs(column) {
  if (sortColumn.value === column) sortDirection.value = sortDirection.value === 'desc' ? 'asc' : 'desc'
  else { sortColumn.value = column; sortDirection.value = 'desc' }
}
function sortIcon(column) { return sortColumn.value === column ? sortDirection.value === 'desc' ? '↓' : '↑' : '↕' }
function sortAria(column) { return sortColumn.value === column ? sortDirection.value === 'desc' ? 'descending' : 'ascending' : 'none' }
const sortedPairs = computed(() => {
  if (!sortColumn.value) return pairs.value
  const direction = sortDirection.value === 'desc' ? -1 : 1
  return [...pairs.value].sort((left, right) => {
    const leftValue = Number(left[sortColumn.value])
    const rightValue = Number(right[sortColumn.value])
    const leftValid = Number.isFinite(leftValue)
    const rightValid = Number.isFinite(rightValue)
    if (!leftValid || !rightValid) return leftValid === rightValid ? 0 : leftValid ? -1 : 1
    return (leftValue - rightValue) * direction
  })
})
const currencyRateDate = computed(() => currencyRates.value[0]?.rate_date ? formatDate(currencyRates.value[0].rate_date) : '—')
const pairEnding = computed(() => { const remainder = pairs.value.length % 10; return remainder === 1 && pairs.value.length % 100 !== 11 ? '' : remainder >= 2 && remainder <= 4 ? 'а' : 'ов' })
const visibleColumnCount = computed(() => showContractDetails.value ? 20 : 13)
onMounted(() => { if (authenticated.value) { loadPairs(); loadCurrencyRates(); connectPriceEvents(); loadInstrumentOptions('exante'); loadInstrumentOptions('bcs') } })
onBeforeUnmount(() => { priceEvents?.close(); if (priceRefreshTimer) clearTimeout(priceRefreshTimer) })
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
.currency-rates { display: flex; align-items: stretch; margin-bottom: 18px; border: 1px solid #35423d; background: #161d1a; font: 11px 'IBM Plex Mono', monospace; } .currency-rates-title, .currency-rate { display: flex; flex-direction: column; justify-content: center; padding: 12px 16px; border-right: 1px solid #35423d; } .currency-rates-title { min-width: 215px; color: #77d6b6; letter-spacing: .6px; } .currency-rates-title small, .currency-rates-empty { margin-top: 4px; color: #7f8d86; font-size: 10px; letter-spacing: 0; } .currency-rate { min-width: 150px; gap: 4px; } .currency-rate strong { color: #aeb9b3; font-weight: 500; } .currency-rate span { color: #e4eee9; font-size: 13px; font-weight: 600; } .currency-rates-empty { align-self: center; margin: 0; padding: 0 16px; }
.table-toolbar { align-items: center; gap: 12px; padding: 10px 12px; } .table-toolbar-actions { display: flex; align-items: center; gap: 12px; } .details-toggle { border: 1px solid #46574f; border-radius: 2px; padding: 6px 8px; color: #b9c7c0; background: #19211e; font: 10px 'IBM Plex Mono', monospace; } .details-toggle:hover { border-color: #77d6b6; color: #e7f4ed; } th, td { text-align: center !important; } th { padding: 9px 8px; line-height: 1.25; } .header-label { display: inline-block; } .sort-header { display: inline-flex; align-items: center; justify-content: center; gap: 3px; border: 0; padding: 0; color: inherit; background: transparent; font: inherit; text-align: inherit; } .sort-header:hover, .sort-header:focus-visible, .sort-header.is-active { color: #77d6b6; } .sort-header:focus-visible { outline: 1px solid #77d6b6; outline-offset: 3px; } table.is-compact { min-width: 920px; table-layout: fixed; } .contract-column { width: 14%; } .date-column { width: 9%; } .price-column, .ratio-column { width: 8%; } .dte-column, .percent-column { width: 5%; } .virt-column, .diff-column { width: 7%; } .ytm-column { width: 6%; } .action-column { width: 4%; } td { max-width: 132px; padding: 10px 8px; } .instrument { display: block; max-width: 100%; overflow: hidden; text-align: center; text-overflow: ellipsis; } .editable-cell input { min-width: 64px; margin: -5px 0; padding: 5px 6px; } .trade-lot-currency { border: 1px solid #46574f; border-radius: 2px; padding: 5px 6px; color: #dbe4df; background: #19211e; font: inherit; } .trade-lot-currency:focus { border-color: #77d6b6; outline: none; } .trade-lot-currency:disabled { cursor: wait; opacity: .6; } .pair-action { padding: 0 4px; } .delete-pair-button { width: 24px; height: 24px; border: 1px solid transparent; border-radius: 2px; padding: 0; color: #87958e; background: transparent; font: 500 18px/1 'IBM Plex Mono', monospace; } .delete-pair-button:hover:not(:disabled) { border-color: #a85850; color: #ff9989; background: rgba(158, 54, 44, .18); } .delete-pair-button:disabled { cursor: wait; opacity: .45; }
@media (max-width: 700px) { .topbar, .dashboard-heading, .add-pair-row { align-items: flex-start; flex-direction: column; } .topbar-actions { width: 100%; justify-content: space-between; } .workspace { padding: 30px 14px; } .heading-metrics { width: 100%; } .add-pair-form { width: 100%; flex-direction: column; } .pair-fields { width: 100%; flex-direction: column; } .pair-select { width: 100%; } .add-pair-form .primary-button { width: 100%; } .currency-rates { flex-wrap: wrap; } .currency-rates-title { width: 100%; min-width: 0; border-bottom: 1px solid #35423d; } .currency-rate { flex: 1; min-width: 0; } .currency-rate:last-of-type { border-right: 0; } .login-panel { padding: 28px 23px; } }
</style>