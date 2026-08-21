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
        <nav class="table-tabs" aria-label="Тип таблицы">
          <button type="button" :class="{ 'is-active': activeTable === 'exante_forts' }" @click="selectTable('exante_forts')">EXANTE / CME — FORTS</button>
          <button type="button" :class="{ 'is-active': activeTable === 'moex_spot_future' }" @click="selectTable('moex_spot_future')">MOEX spot — MOEX futures</button>
          <button type="button" :class="{ 'is-active': activeTable === 'moex_future_future' }" @click="selectTable('moex_future_future')">MOEX futures — MOEX futures</button>
        </nav>
        <section v-if="activeTable === 'exante_forts'" class="add-pair-row">
          <div><p class="section-label">НОВАЯ ПАРА</p><span>Выберите контракты из синхронизированных справочников EXANTE и BCS.</span></div>
          <form class="add-pair-form" @submit.prevent="addPair">
            <div class="pair-fields">
              <label class="pair-select pair-select--cme combobox"><span class="pair-select-label">EXANTE / CME ticker</span>
                <div class="combobox-control">
                  <input ref="cmeInput" v-model="newCmeName" class="combobox-input" placeholder="Например NG.NYMEX.M2036" maxlength="100" autocomplete="off" required @focus="onCmeFocus" @input="onCmeInput" @keydown="onCmeKeydown" @blur="onCmeBlur" />
                  <ul v-if="cmeOpen && cmeMatches.length" class="combobox-menu" role="listbox">
                    <li v-for="(match, index) in cmeMatches" :key="match.value" role="option" :aria-selected="index === cmeHighlight" :class="{ 'is-active': index === cmeHighlight }" @mousedown.prevent="pickCme(match)" @mouseenter="cmeHighlight = index">
                      <span class="combobox-value" v-html="highlightMatch(match.value, newCmeName)"></span>
                      <span class="combobox-details">{{ match.details }}</span>
                    </li>
                  </ul>
                </div>
                <small class="pair-hint">{{ exanteHint }}</small>
              </label>
              <label class="pair-select pair-select--forts combobox"><span class="pair-select-label">BCS / FORTS ticker</span>
                <div class="combobox-control">
                  <input ref="fortsInput" v-model="newFortsName" class="combobox-input" placeholder="Например SBER" maxlength="100" autocomplete="off" @focus="onFortsFocus" @input="onFortsInput" @keydown="onFortsKeydown" @blur="onFortsBlur" />
                  <ul v-if="fortsOpen && fortsMatches.length" class="combobox-menu" role="listbox">
                    <li v-for="(match, index) in fortsMatches" :key="match.value" role="option" :aria-selected="index === fortsHighlight" :class="{ 'is-active': index === fortsHighlight }" @mousedown.prevent="pickForts(match)" @mouseenter="fortsHighlight = index">
                      <span class="combobox-value" v-html="highlightMatch(match.value, newFortsName)"></span>
                      <span class="combobox-details">{{ match.details }}</span>
                    </li>
                  </ul>
                </div>
                <small class="pair-hint">{{ bcsHint }}</small>
              </label>
              <label class="pair-select pair-select--currency"><span class="pair-select-label">Trade lot currency</span>
                <span class="pair-currency-control">
                  <select v-model="newTradeLotCurrency" class="pair-currency-select" aria-label="Валюта расчёта Trade lot">
                    <option value="USD">USD</option>
                    <option value="CNY">CNY</option>
                  </select>
                </span>
              </label>
            </div>
            <button class="primary-button" :disabled="addingPair">{{ addingPair ? 'Добавление...' : 'Добавить пару' }}</button>
          </form>
        </section>
        <p v-if="tableError" class="form-error table-error">{{ tableError }}</p>
        <section v-if="activeTable === 'exante_forts'" class="currency-rates" aria-label="Курсы MOEX">
          <div class="currency-rates-title"><span>КУРСЫ MOEX</span><small>расчётный курс за {{ currencyRateDate }}</small></div>
          <div class="currency-rate" v-for="rate in currencyRates" :key="rate.currency_code"><strong>{{ rate.currency_code }}/RUB</strong><span>{{ formatNumber(rate.rate, 4) }} RUB</span></div>
          <span v-if="!currencyRates.length" class="currency-rates-empty">Курсы пока недоступны</span>
        </section>
        <section v-if="activeTable === 'exante_forts'" class="table-section">
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
              <td v-if="showContractDetails">{{ pair.trade_lot_currency }}</td>
              <td>{{ pair.dte ?? '—' }}</td>
              <td class="editable-cell" :class="[numberClass(pair.virt_0), { 'is-invalid': isInvalidCell(pair.id, 'virt_0') }]" @click="startCellEdit(pair, 'virt_0')"><input v-if="isEditingCell(pair.id, 'virt_0')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveCellEdit(pair)" @keydown.enter.prevent="saveCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.virt_0) }}</span></td>
              <td :class="numberClass(pair.diff)">{{ formatExactNumber(pair.diff) }}</td>
              <td :class="numberClass(pair.diff_percent)">{{ formatPercent(pair.diff_percent) }}</td>
              <td :class="numberClass(pair.diff_ytm_margin)">{{ formatPercent(pair.diff_ytm_margin) }}</td>
              <td class="pair-action"><button class="delete-pair-button" type="button" :disabled="deletingPairId === pair.id" :title="`Удалить ${pair.cme_name} / ${pair.forts_name || 'FORTS'}`" :aria-label="`Удалить пару ${pair.cme_name} / ${pair.forts_name || 'FORTS'}`" @click.stop="deletePair(pair)">×</button></td>
            </tr>
          </tbody></table></div>
        </section>
        <template v-if="activeTable === 'moex_spot_future'">
          <section class="add-pair-row">
            <div><p class="section-label">НОВАЯ ПАРА</p><span>Выберите акцию или валюту и фьючерс из справочника MOEX.</span></div>
            <form class="add-pair-form moex-pair-form" @submit.prevent="addMoexPair">
              <div class="pair-fields">
                <label class="pair-select combobox"><span class="pair-select-label">MOEX / spot акция или валюта</span>
                  <div class="combobox-control">
                    <input ref="spotInput" v-model="newSpotName" class="combobox-input" placeholder="Например SBER" maxlength="100" autocomplete="off" required @focus="onSpotFocus" @input="onSpotInput" @keydown="onSpotKeydown" @blur="onSpotBlur" />
                    <ul v-if="spotOpen && spotMatches.length" class="combobox-menu" role="listbox">
                      <li v-for="(match, index) in spotMatches" :key="match.value" role="option" :aria-selected="index === spotHighlight" :class="{ 'is-active': index === spotHighlight }" @mousedown.prevent="pickSpot(match)" @mouseenter="spotHighlight = index">
                        <span class="combobox-value" v-html="highlightMatch(match.value, newSpotName)"></span><span class="combobox-details">{{ match.details }}</span>
                      </li>
                    </ul>
                  </div>
                  <small class="pair-hint">{{ spotHint }}</small>
                </label>
                <label class="pair-select combobox"><span class="pair-select-label">MOEX / futures</span>
                  <div class="combobox-control">
                    <input ref="futureInput" v-model="newFutureName" class="combobox-input" placeholder="Например SRU6" maxlength="100" autocomplete="off" required @focus="onFutureFocus" @input="onFutureInput" @keydown="onFutureKeydown" @blur="onFutureBlur" />
                    <ul v-if="futureOpen && futureMatches.length" class="combobox-menu" role="listbox">
                      <li v-for="(match, index) in futureMatches" :key="match.value" role="option" :aria-selected="index === futureHighlight" :class="{ 'is-active': index === futureHighlight }" @mousedown.prevent="pickFuture(match)" @mouseenter="futureHighlight = index">
                        <span class="combobox-value" v-html="highlightMatch(match.value, newFutureName)"></span><span class="combobox-details">{{ match.details }}</span>
                      </li>
                    </ul>
                  </div>
                  <small class="pair-hint">{{ futureHint }}</small>
                </label>
              </div>
              <button class="primary-button" :disabled="addingMoexPair">{{ addingMoexPair ? 'Добавление...' : 'Добавить пару' }}</button>
            </form>
          </section>
          <section class="table-section">
            <div class="table-toolbar"><span><i></i> MOEX SPOT / FUTURES</span><div class="table-toolbar-actions"><span>{{ moexPairs.length }} инструмент{{ moexPairEnding }}</span><button class="details-toggle" type="button" :aria-expanded="moexShowContractDetails" @click="moexShowContractDetails = !moexShowContractDetails">{{ moexShowContractDetails ? 'Скрыть параметры' : 'Параметры контрактов' }}</button></div></div>
            <div class="table-wrap"><table class="moex-table" :class="{ 'is-compact': !moexShowContractDetails }"><thead><tr>
              <th>Spot name</th><th>Spot price</th><th v-if="moexShowContractDetails">Discount</th><th>Spot margin</th><th v-if="moexShowContractDetails">Spot lot</th><th v-if="moexShowContractDetails">Spot trade lot</th><th v-if="moexShowContractDetails">Dividend</th><th>Future name</th><th>Future price</th><th>Future margin</th><th v-if="moexShowContractDetails">Future lot</th><th v-if="moexShowContractDetails">Future exp</th><th v-if="moexShowContractDetails">Future trade lot</th><th>DTE</th><th>Diff</th><th>Diff, %</th><th>Diff, YTM</th><th></th>
            </tr></thead><tbody>
              <tr v-if="moexLoading"><td :colspan="moexVisibleColumnCount" class="empty-state">Загрузка данных...</td></tr>
              <tr v-else-if="!moexPairs.length"><td :colspan="moexVisibleColumnCount" class="empty-state">Пар MOEX spot — futures пока нет.</td></tr>
              <tr v-for="pair in moexPairs" :key="pair.id">
                <td class="instrument">{{ pair.spot_name }}</td><td>{{ formatExactNumber(pair.spot_price) }}</td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'discount') }" @click="startCellEdit(pair, 'discount')"><input v-if="isEditingCell(pair.id, 'discount')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexCellEdit(pair)" @keydown.enter.prevent="saveMoexCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.discount, 4) }}</span></td><td>{{ formatNumber(pair.spot_margin, 4) }}</td><td>{{ formatNumber(pair.spot_lot, 4) }}</td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'spot_trade_lot') }" @click="startCellEdit(pair, 'spot_trade_lot')"><input v-if="isEditingCell(pair.id, 'spot_trade_lot')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexCellEdit(pair)" @keydown.enter.prevent="saveMoexCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.spot_trade_lot, 4) }}</span></td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'spot_dividend') }" @click="startCellEdit(pair, 'spot_dividend')"><input v-if="isEditingCell(pair.id, 'spot_dividend')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexCellEdit(pair)" @keydown.enter.prevent="saveMoexCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.spot_dividend, 4) }}</span></td><td class="instrument">{{ pair.future_name }}</td><td>{{ formatExactNumber(pair.future_price) }}</td><td>{{ formatNumber(pair.future_margin, 4) }}</td><td>{{ formatNumber(pair.future_lot, 4) }}</td><td>{{ formatDate(pair.future_data_exp) }}</td><td class="editable-cell" :class="{ 'is-invalid': isInvalidCell(pair.id, 'future_trade_lot') }" @click="startCellEdit(pair, 'future_trade_lot')"><input v-if="isEditingCell(pair.id, 'future_trade_lot')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexCellEdit(pair)" @keydown.enter.prevent="saveMoexCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.future_trade_lot, 4) }}</span></td><td>{{ pair.dte ?? '—' }}</td><td :class="numberClass(pair.diff)">{{ formatExactNumber(pair.diff) }}</td><td :class="numberClass(pair.diff_percent)">{{ formatPercent(pair.diff_percent) }}</td><td :class="numberClass(pair.diff_ytm_margin)">{{ formatPercent(pair.diff_ytm_margin) }}</td><td class="pair-action"><button class="delete-pair-button" type="button" title="Удалить пару" @click="deleteMoexPair(pair)">×</button></td>
              </tr>
            </tbody></table></div>
          </section>
          <section class="calculation-legend" aria-label="Формулы расчёта MOEX spot-futures">
            <div class="calculation-legend-title">ЛЕГЕНДА РАСЧЁТА</div>
            <div class="calculation-legend-grid">
              <div><strong>Spot margin</strong><span>Spot price × Spot lot × Discount</span></div>
              <div><strong>Diff</strong><span>Акция: Future price − Spot price × Future lot + Dividend; валюта: Future price − Spot price × Future lot / Spot lot + Dividend</span></div>
              <div><strong>DTE</strong><span>Количество дней до экспирации Future</span></div>
              <div><strong>Акция — Diff, %</strong><span>Diff / (Spot margin × Spot trade lot + Future margin)</span></div>
              <div><strong>Валюта — Diff, %</strong><span>Diff × Spot lot / max(Spot margin × Spot trade lot; Future margin × Future trade lot)</span></div>
              <div><strong>Diff, YTM</strong><span>Diff, % / DTE × 365</span></div>
            </div>
          </section>
        </template>
        <template v-if="activeTable === 'moex_future_future'">
          <section class="add-pair-row">
            <div><p class="section-label">НОВАЯ ПАРА</p><span>Выберите два фьючерса MOEX: например USDRUBF и SiU6.</span></div>
            <form class="add-pair-form moex-pair-form" @submit.prevent="addMoexFutureFuturePair">
              <div class="pair-fields">
                <label class="pair-select combobox"><span class="pair-select-label">First future</span>
                  <div class="combobox-control">
                    <input ref="firstFutureInput" v-model="newFirstFutureName" class="combobox-input" placeholder="Например USDRUBF" maxlength="100" autocomplete="off" required @focus="onFirstFutureFocus" @input="onFirstFutureInput" @keydown="onFirstFutureKeydown" @blur="onFirstFutureBlur" />
                    <ul v-if="firstFutureOpen && firstFutureMatches.length" class="combobox-menu" role="listbox">
                      <li v-for="(match, index) in firstFutureMatches" :key="match.value" role="option" :aria-selected="index === firstFutureHighlight" :class="{ 'is-active': index === firstFutureHighlight }" @mousedown.prevent="pickFirstFuture(match)" @mouseenter="firstFutureHighlight = index">
                        <span class="combobox-value" v-html="highlightMatch(match.value, newFirstFutureName)"></span><span class="combobox-details">{{ match.details }}</span>
                      </li>
                    </ul>
                  </div>
                  <small class="pair-hint">{{ firstFutureHint }}</small>
                </label>
                <label class="pair-select combobox"><span class="pair-select-label">Second future</span>
                  <div class="combobox-control">
                    <input ref="secondFutureInput" v-model="newSecondFutureName" class="combobox-input" placeholder="Например SiU6" maxlength="100" autocomplete="off" required @focus="onSecondFutureFocus" @input="onSecondFutureInput" @keydown="onSecondFutureKeydown" @blur="onSecondFutureBlur" />
                    <ul v-if="secondFutureOpen && secondFutureMatches.length" class="combobox-menu" role="listbox">
                      <li v-for="(match, index) in secondFutureMatches" :key="match.value" role="option" :aria-selected="index === secondFutureHighlight" :class="{ 'is-active': index === secondFutureHighlight }" @mousedown.prevent="pickSecondFuture(match)" @mouseenter="secondFutureHighlight = index">
                        <span class="combobox-value" v-html="highlightMatch(match.value, newSecondFutureName)"></span><span class="combobox-details">{{ match.details }}</span>
                      </li>
                    </ul>
                  </div>
                  <small class="pair-hint">{{ secondFutureHint }}</small>
                </label>
              </div>
              <button class="primary-button" :disabled="addingMoexFutureFuturePair">{{ addingMoexFutureFuturePair ? 'Добавление...' : 'Добавить пару' }}</button>
            </form>
          </section>
          <section class="table-section">
            <div class="table-toolbar"><span><i></i> MOEX FUTURES / FUTURES</span><span>{{ moexFutureFuturePairs.length }} инструмент{{ moexFutureFuturePairEnding }}</span></div>
            <div class="table-wrap"><table class="moex-table"><thead><tr>
              <th>First name</th><th>First price</th><th>First margin</th><th>First lot</th><th>First exp</th><th>Price ratio</th><th>First trade lot</th><th>Second name</th><th>Second price</th><th>Second margin</th><th>Second lot</th><th>Second exp</th><th>Second trade lot</th><th>DTE</th><th>Virt_0</th><th>Diff</th><th>Diff, %</th><th>Diff, YTM margin</th><th></th>
            </tr></thead><tbody>
              <tr v-if="moexFutureFutureLoading"><td colspan="19" class="empty-state">Загрузка данных...</td></tr>
              <tr v-else-if="!moexFutureFuturePairs.length"><td colspan="19" class="empty-state">Пар MOEX futures — futures пока нет.</td></tr>
              <tr v-for="pair in moexFutureFuturePairs" :key="pair.id">
                <td class="instrument">{{ pair.first_name }}</td><td>{{ formatExactNumber(pair.first_price) }}</td><td>{{ formatNumber(pair.first_margin, 4) }}</td><td>{{ formatNumber(pair.first_lot, 4) }}</td><td>{{ formatDate(pair.first_exp) }}</td><td class="editable-cell" @click="startCellEdit(pair, 'price_ratio')"><input v-if="isEditingCell(pair.id, 'price_ratio')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexFutureFutureCellEdit(pair)" @keydown.enter.prevent="saveMoexFutureFutureCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.price_ratio, 6) }}</span></td><td class="editable-cell" @click="startCellEdit(pair, 'first_trade_lot')"><input v-if="isEditingCell(pair.id, 'first_trade_lot')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexFutureFutureCellEdit(pair)" @keydown.enter.prevent="saveMoexFutureFutureCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.first_trade_lot, 4) }}</span></td>
                <td class="instrument">{{ pair.second_name }}</td><td>{{ formatExactNumber(pair.second_price) }}</td><td>{{ formatNumber(pair.second_margin, 4) }}</td><td>{{ formatNumber(pair.second_lot, 4) }}</td><td>{{ formatDate(pair.second_exp) }}</td><td class="editable-cell" @click="startCellEdit(pair, 'second_trade_lot')"><input v-if="isEditingCell(pair.id, 'second_trade_lot')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexFutureFutureCellEdit(pair)" @keydown.enter.prevent="saveMoexFutureFutureCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.second_trade_lot, 4) }}</span></td><td>{{ pair.dte ?? '—' }}</td><td class="editable-cell" @click="startCellEdit(pair, 'virt_0')"><input v-if="isEditingCell(pair.id, 'virt_0')" :ref="setEditorInput" v-model="editingCell.value" inputmode="decimal" @blur="saveMoexFutureFutureCellEdit(pair)" @keydown.enter.prevent="saveMoexFutureFutureCellEdit(pair)" @keydown.esc.prevent="cancelCellEdit" /><span v-else>{{ formatNumber(pair.virt_0, 4) }}</span></td><td :class="numberClass(pair.diff)">{{ formatExactNumber(pair.diff) }}</td><td :class="numberClass(pair.diff_percent)">{{ formatPercent(pair.diff_percent) }}</td><td :class="numberClass(pair.diff_ytm_margin)">{{ formatPercent(pair.diff_ytm_margin) }}</td><td class="pair-action"><button class="delete-pair-button" type="button" @click.stop="deleteMoexFutureFuturePair(pair)" aria-label="Удалить пару">×</button></td>
              </tr>
            </tbody></table></div>
          </section>
          <section class="calculation-legend" aria-label="Формулы расчёта MOEX futures-futures">
            <div class="calculation-legend-title">ЛЕГЕНДА РАСЧЁТА</div>
            <div class="calculation-legend-grid">
              <div><strong>Price ratio</strong><span>При создании и получении котировок: Second price / First price; значение можно изменить вручную.</span></div>
              <div><strong>Diff</strong><span>Second price − First price × Price ratio − Virt_0</span></div>
              <div><strong>DTE</strong><span>Количество дней до ближайшей экспирации First или Second future</span></div>
              <div><strong>Diff, %</strong><span>Diff / max(First margin × First trade lot; Second margin × Second trade lot)</span></div>
              <div><strong>Diff, YTM margin</strong><span>Diff, % / DTE × 365</span></div>
            </div>
          </section>
        </template>
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
const moexPairs = ref([])
const moexFutureFuturePairs = ref([])
const savedTable = localStorage.getItem('arbitrage_active_table')
const activeTable = ref(['exante_forts', 'moex_spot_future', 'moex_future_future'].includes(savedTable) ? savedTable : 'exante_forts')
const moexLoading = ref(false)
const moexFutureFutureLoading = ref(false)
const addingMoexPair = ref(false)
const addingMoexFutureFuturePair = ref(false)
const newSpotName = ref('')
const newFutureName = ref('')
const newFirstFutureName = ref('')
const newSecondFutureName = ref('')
const firstFutureHint = ref('Начните вводить тикер фьючерса, например USDRUBF.')
const secondFutureHint = ref('Начните вводить тикер фьючерса, например SiU6.')
const spotOptions = ref([])
const futureOptions = ref([])
const spotHint = ref('Начните вводить тикер акции или валюты MOEX.')
const futureHint = ref('Начните вводить тикер фьючерса MOEX.')
const spotOpen = ref(false)
const spotHighlight = ref(-1)
const spotMatches = ref([])
const spotTotal = ref(0)
const spotSuggestion = ref('')
const spotInput = ref(null)
const futureOpen = ref(false)
const futureHighlight = ref(-1)
const futureMatches = ref([])
const futureTotal = ref(0)
const futureSuggestion = ref('')
const futureInput = ref(null)
const firstFutureOpen = ref(false)
const firstFutureHighlight = ref(-1)
const firstFutureMatches = ref([])
const firstFutureTotal = ref(0)
const firstFutureSuggestion = ref('')
const firstFutureInput = ref(null)
const secondFutureOpen = ref(false)
const secondFutureHighlight = ref(-1)
const secondFutureMatches = ref([])
const secondFutureTotal = ref(0)
const secondFutureSuggestion = ref('')
const secondFutureInput = ref(null)
const sortColumn = ref(null)
const sortDirection = ref('desc')
const newCmeName = ref('')
const newFortsName = ref('')
const newTradeLotCurrency = ref('USD')
const exanteOptions = ref([])
const bcsOptions = ref([])
const exanteHint = ref('Начните вводить тикер или symbolId EXANTE.')
const bcsHint = ref('Начните вводить тикер BCS.')
const cmeOpen = ref(false)
const cmeHighlight = ref(-1)
const cmeMatches = ref([])
const cmeTotal = ref(0)
const cmeSuggestion = ref('')
const cmeInput = ref(null)
const fortsOpen = ref(false)
const fortsHighlight = ref(-1)
const fortsMatches = ref([])
const fortsTotal = ref(0)
const fortsSuggestion = ref('')
const fortsInput = ref(null)
const updatedAt = ref('—')
const currencyRates = ref([])
const editingCell = ref(null)
const editorInput = ref(null)
const invalidCells = ref({})
const showContractDetails = ref(false)
const moexShowContractDetails = ref(false)
const deletingPairId = ref(null)
let priceEvents = null
let priceRefreshTimer = null
let priceRefreshPending = false
let lastPriceRefresh = 0
const PRICE_REFRESH_INTERVAL = 1500

function authHeaders() { return { Authorization: `Bearer ${token.value}` } }
async function login() {
  loginPending.value = true; loginError.value = ''
  try {
    const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(credentials.value) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить вход')
    token.value = data.access_token; username.value = data.username
    localStorage.setItem('arbitrage_token', token.value); localStorage.setItem('arbitrage_username', username.value)
    await Promise.all([loadPairs(), loadCurrencyRates(), loadInstrumentOptions('bcs', '', 'SPOT'), loadInstrumentOptions('bcs', '', 'FUTURES')]); connectPriceEvents()
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
async function loadMoexPairs(showLoading = true) {
  if (showLoading) moexLoading.value = true
  tableError.value = ''
  try {
    const response = await fetch('/api/moex-spot-future-pairs', { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить пары MOEX')
    moexPairs.value = data.pairs
    updatedAt.value = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date())
  } catch (error) { tableError.value = error.message } finally { if (showLoading) moexLoading.value = false }
}
async function loadMoexFutureFuturePairs(showLoading = true) {
  if (showLoading) moexFutureFutureLoading.value = true
  tableError.value = ''
  try {
    const response = await fetch('/api/moex-future-future-pairs', { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить пары future–future')
    moexFutureFuturePairs.value = data.pairs
    updatedAt.value = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date())
  } catch (error) { tableError.value = error.message } finally { if (showLoading) moexFutureFutureLoading.value = false }
}
function selectTable(table) {
  activeTable.value = table
  localStorage.setItem('arbitrage_active_table', table)
  if (table === 'moex_spot_future' && !moexPairs.value.length) loadMoexPairs()
  if (table === 'moex_future_future' && !moexFutureFuturePairs.value.length) loadMoexFutureFuturePairs()
}
async function addMoexFutureFuturePair() {
  addingMoexFutureFuturePair.value = true; tableError.value = ''
  try {
    const response = await fetch('/api/moex-future-future-pairs', { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ first_name: canonicalValue(futureOptions, newFirstFutureName.value), second_name: canonicalValue(futureOptions, newSecondFutureName.value) }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось добавить пару future–future')
    newFirstFutureName.value = ''; newSecondFutureName.value = ''; await loadMoexFutureFuturePairs()
  } catch (error) { tableError.value = error.message } finally { addingMoexFutureFuturePair.value = false }
}
async function deleteMoexFutureFuturePair(pair) {
  if (!window.confirm(`Удалить пару ${pair.first_name} / ${pair.second_name}?`)) return
  try {
    const response = await fetch(`/api/moex-future-future-pairs/${pair.id}`, { method: 'DELETE', headers: authHeaders() })
    if (response.status === 401) return logout()
    if (!response.ok) throw new Error('Не удалось удалить пару future–future')
    moexFutureFuturePairs.value = moexFutureFuturePairs.value.filter(item => item.id !== pair.id)
  } catch (error) { tableError.value = error.message }
}
async function addMoexPair() {
  addingMoexPair.value = true; tableError.value = ''
  try {
    const response = await fetch('/api/moex-spot-future-pairs', { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ spot_name: newSpotName.value.trim().toUpperCase(), future_name: newFutureName.value.trim().toUpperCase() }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось добавить пару MOEX')
    newSpotName.value = ''; newFutureName.value = ''; await loadMoexPairs()
  } catch (error) { tableError.value = error.message } finally { addingMoexPair.value = false }
}
async function deleteMoexPair(pair) {
  if (!window.confirm(`Удалить пару ${pair.spot_name} / ${pair.future_name}?`)) return
  try {
    const response = await fetch(`/api/moex-spot-future-pairs/${pair.id}`, { method: 'DELETE', headers: authHeaders() })
    if (response.status === 401) return logout()
    if (!response.ok) throw new Error('Не удалось удалить пару MOEX')
    moexPairs.value = moexPairs.value.filter(item => item.id !== pair.id)
  } catch (error) { tableError.value = error.message }
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
  priceEvents.onmessage = schedulePriceRefresh
}
function schedulePriceRefresh() {
  const now = Date.now()
  const remaining = lastPriceRefresh + PRICE_REFRESH_INTERVAL - now
  if (remaining <= 0) {
    lastPriceRefresh = now
    loadPairs(false)
    loadMoexPairs(false)
    loadMoexFutureFuturePairs(false)
    loadCurrencyRates()
    return
  }
  if (priceRefreshPending) return
  priceRefreshPending = true
  priceRefreshTimer = setTimeout(() => {
    priceRefreshPending = false
    priceRefreshTimer = null
    lastPriceRefresh = Date.now()
    loadPairs(false)
    loadMoexPairs(false)
    loadMoexFutureFuturePairs(false)
    loadCurrencyRates()
  }, remaining)
}
async function addPair() {
  addingPair.value = true; tableError.value = ''
  const cmeName = canonicalValue(exanteOptions, newCmeName.value)
  const fortsName = canonicalValue(bcsOptions, newFortsName.value)
  try {
    const response = await fetch('/api/arbitrage-pairs', { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ cme_name: cmeName, forts_name: fortsName, trade_lot_currency: newTradeLotCurrency.value }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось добавить пару')
    newCmeName.value = ''; newFortsName.value = ''; newTradeLotCurrency.value = 'USD'; await loadPairs()
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
  if (field === 'discount' && (parsed < 0.08 || parsed > 1)) return null
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
async function saveMoexCellEdit(pair) {
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
    const response = await fetch(`/api/moex-spot-future-pairs/${pair.id}/manual-value`, {
      method: 'PATCH',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ field: edit.field, value: normalizedValue }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить значение')
    pair[edit.field] = data.value
    if (edit.field === 'discount' && data.spot_margin !== undefined) pair.spot_margin = data.spot_margin
    for (const field of ['diff', 'diff_percent', 'diff_ytm_margin', 'dte']) {
      if (data[field] !== undefined) pair[field] = data[field]
    }
    delete invalidCells.value[key]
    editingCell.value = null
  } catch (error) {
    invalidCells.value[key] = true
    tableError.value = error.message || 'Не удалось сохранить значение'
    nextTick(() => editorInput.value?.focus())
  }
}
async function saveMoexFutureFutureCellEdit(pair) {
  const edit = editingCell.value
  if (!edit || edit.pairId !== pair.id) return
  const normalizedValue = validateManualValue(edit.field, edit.value)
  const key = cellKey(edit.pairId, edit.field)
  if (normalizedValue === null) { invalidCells.value[key] = true; nextTick(() => editorInput.value?.focus()); return }
  try {
    const response = await fetch(`/api/moex-future-future-pairs/${pair.id}/manual-value`, { method: 'PATCH', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ field: edit.field, value: normalizedValue }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить значение')
    pair[edit.field] = data.value
    for (const field of ['diff', 'diff_percent', 'diff_ytm_margin', 'dte']) if (data[field] !== undefined) pair[field] = data[field]
    delete invalidCells.value[key]; editingCell.value = null
  } catch (error) { invalidCells.value[key] = true; tableError.value = error.message || 'Не удалось сохранить значение'; nextTick(() => editorInput.value?.focus()) }
}
async function loadInstrumentOptions(provider, query = '', instrumentType = '') {
  if (!token.value) return
  try {
    const typeQuery = instrumentType ? `&instrument_type=${encodeURIComponent(instrumentType)}` : ''
    const response = await fetch(`/api/instrument-options?provider=${encodeURIComponent(provider)}&query=${encodeURIComponent(query)}&limit=20000${typeQuery}`, { headers: authHeaders() })
    if (response.status === 401) return logout()
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить список тикеров')
    const items = Array.isArray(data.items) ? data.items : []
    if (provider === 'exante') {
      exanteOptions.value = items
      updateCmeMatches()
    } else {
      if (instrumentType === 'SPOT') {
        spotOptions.value = items
      } else if (instrumentType === 'FUTURES') {
        futureOptions.value = items
      } else {
        bcsOptions.value = items
        updateFortsMatches()
      }
    }
  } catch (error) {
    const message = error.message || 'Не удалось получить список тикеров'
    if (provider === 'exante') {
      exanteOptions.value = []
      updateCmeMatches()
      exanteHint.value = message
    } else {
      bcsHint.value = message
      bcsOptions.value = []
    }
  }
}
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]))
}
function canonicalValue(options, input) {
  const folded = String(input || '').trim().toLowerCase()
  if (!folded) return ''
  const exact = options.value.find(option => option.value.toLowerCase() === folded)
  return exact ? exact.value : String(input || '').trim()
}
function instrumentMatchRank(value, query) {
  const foldedValue = String(value || '').toLowerCase()
  const foldedQuery = String(query || '').trim().toLowerCase()
  if (!foldedQuery) return 0
  if (foldedValue === foldedQuery) return 0
  if (foldedValue.startsWith(foldedQuery)) return 1
  const valueParts = foldedValue.split('.')
  const queryParts = foldedQuery.split('.')
  const hasDot = foldedQuery.includes('.')
  if (queryParts.length <= valueParts.length && queryParts.every((part, index) => !part || valueParts[index].startsWith(part))) return 2
  if (hasDot) return null
  if (valueParts.some(part => part.startsWith(foldedQuery))) return 3
  if (foldedValue.includes(foldedQuery)) return 4
  return null
}
function rankOption(option, query) {
  let best = null
  for (const candidate of [option.value, option.label, option.details]) {
    const rank = instrumentMatchRank(candidate, query)
    if (rank !== null && (best === null || rank < best)) best = rank
  }
  return best
}
function computeRanked(options, query) {
  const ranked = []
  for (const option of options) {
    const rank = rankOption(option, query)
    if (rank !== null) ranked.push({ option, rank })
  }
  ranked.sort((left, right) => (left.rank - right.rank) || left.option.value.localeCompare(right.option.value, 'en'))
  return ranked
}
function computeSuggestion(matches, typed) {
  if (!typed || !matches.length) return ''
  const values = matches.map(option => option.value)
  const typedParts = typed.split('.')
  const segmentIndex = typedParts.length - 1
  const currentTyped = typedParts[segmentIndex].toLowerCase()
  const maxSegments = Math.max(...values.map(value => value.split('.').length))

  const currentOptions = new Set()
  for (const value of values) {
    const parts = value.split('.')
    if (parts.length <= segmentIndex) return ''
    currentOptions.add(parts[segmentIndex])
  }
  if (currentOptions.size !== 1) return ''
  const currentFull = [...currentOptions][0]
  if (!currentFull.toLowerCase().startsWith(currentTyped)) return ''

  const head = typedParts.slice(0, segmentIndex)
  let result = head.length ? `${head.join('.')}.${currentFull}` : currentFull
  for (let index = segmentIndex + 1; index < maxSegments; index += 1) {
    const options = new Set(values.map(value => value.split('.')[index]))
    if (options.size !== 1) break
    const only = [...options][0]
    if (!only) break
    result += `.${only}`
  }
  return result
}
function updateCombobox({ options, query, matches, total, highlight, suggestion, hint, providerLabel, emptyHint }) {
  const ranked = computeRanked(options.value, query.value.trim())
  total.value = ranked.length
  matches.value = ranked.slice(0, 200).map(item => item.option)
  highlight.value = matches.value.length ? 0 : -1
  suggestion.value = computeSuggestion(matches.value, query.value.trim())
  const typed = query.value.trim()
  if (!typed) {
    hint.value = options.value.length
      ? `В справочнике ${options.value.length} контрактов ${providerLabel}.`
      : emptyHint
  } else if (!total.value) {
    hint.value = `Совпадений ${providerLabel} не найдено.`
  } else if (total.value === 1) {
    hint.value = `Единственный вариант: ${matches.value[0].value} — Enter или Tab, чтобы выбрать.`
  } else {
    const suggestionText = suggestion.value ? ` Tab — дополнить до ${suggestion.value}.` : ''
    hint.value = `Найдено ${total.value} вариантов. Enter — выбрать первый.${suggestionText}`
  }
}
function updateCmeMatches() {
  updateCombobox({
    options: exanteOptions, query: newCmeName, matches: cmeMatches, total: cmeTotal,
    highlight: cmeHighlight, suggestion: cmeSuggestion, hint: exanteHint,
    providerLabel: 'EXANTE', emptyHint: 'Начните вводить тикер или symbolId EXANTE.',
  })
}
function updateFortsMatches() {
  updateCombobox({
    options: bcsOptions, query: newFortsName, matches: fortsMatches, total: fortsTotal,
    highlight: fortsHighlight, suggestion: fortsSuggestion, hint: bcsHint,
    providerLabel: 'BCS', emptyHint: 'Начните вводить тикер BCS.',
  })
}
function updateSpotMatches() {
  updateCombobox({
    options: spotOptions, query: newSpotName, matches: spotMatches, total: spotTotal,
    highlight: spotHighlight, suggestion: spotSuggestion, hint: spotHint,
    providerLabel: 'MOEX spot', emptyHint: 'Начните вводить тикер акции или валюты MOEX.',
  })
}
function updateFutureMatches() {
  updateCombobox({
    options: futureOptions, query: newFutureName, matches: futureMatches, total: futureTotal,
    highlight: futureHighlight, suggestion: futureSuggestion, hint: futureHint,
    providerLabel: 'MOEX фьючерсы', emptyHint: 'Начните вводить тикер фьючерса MOEX.',
  })
}
function updateFutureFutureMatches(query, matches, total, highlight, suggestion, hint) {
  updateCombobox({
    options: futureOptions, query, matches, total, highlight, suggestion, hint,
    providerLabel: 'MOEX фьючерсы', emptyHint: 'Начните вводить тикер фьючерса MOEX.',
  })
}
function highlightMatch(value, query) {
  const foldedQuery = String(query || '').trim().toLowerCase()
  if (!foldedQuery) return escapeHtml(value)
  const index = String(value).toLowerCase().indexOf(foldedQuery)
  if (index === -1) return escapeHtml(value)
  return `${escapeHtml(value.slice(0, index))}<mark>${escapeHtml(value.slice(index, index + foldedQuery.length))}</mark>${escapeHtml(value.slice(index + foldedQuery.length))}`
}
function openCme() { cmeOpen.value = true }
function closeCme() { cmeOpen.value = false; cmeHighlight.value = -1 }
function onCmeFocus() {
  openCme()
  if (exanteOptions.value.length) {
    updateCmeMatches()
  } else {
    loadInstrumentOptions('exante', '').then(() => { updateCmeMatches(); openCme() })
  }
}
function onCmeInput(event) { openCme(); upperCaseField(event, newCmeName); updateCmeMatches() }
function onFortsInput(event) { upperCaseField(event, newFortsName); openForts(); updateFortsMatches() }
function upperCaseField(event, modelRef) {
  const element = event?.target
  const start = element?.selectionStart ?? null
  const end = element?.selectionEnd ?? null
  const upper = String(modelRef.value || '').toUpperCase()
  if (upper !== modelRef.value) {
    modelRef.value = upper
    if (element && start !== null && end !== null) {
      element.setSelectionRange(start, end)
    }
  }
}
function onCmeBlur() { setTimeout(() => { closeCme() }, 150) }
function pickCme(match) {
  newCmeName.value = match.value
  closeCme()
  nextTick(() => cmeInput.value?.focus())
}
function onCmeKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    openCme()
    if (cmeMatches.value.length) cmeHighlight.value = Math.min(cmeHighlight.value + 1, cmeMatches.value.length - 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    openCme()
    if (cmeMatches.value.length) cmeHighlight.value = Math.max(cmeHighlight.value - 1, 0)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    closeCme()
  } else if (event.key === 'Tab') {
    if (cmeSuggestion.value) {
      event.preventDefault()
      newCmeName.value = cmeSuggestion.value
      updateCmeMatches()
      openCme()
    }
  } else if (event.key === 'Enter') {
    if (cmeOpen.value && cmeMatches.value.length) {
      const target = cmeMatches.value[Math.max(cmeHighlight.value, 0)]
      if (target && target.value.toLowerCase() === newCmeName.value.trim().toLowerCase()) {
        closeCme()
        return
      }
      event.preventDefault()
      pickCme(target)
    }
  }
}
function openForts() { fortsOpen.value = true }
function closeForts() { fortsOpen.value = false; fortsHighlight.value = -1 }
function onFortsFocus() {
  openForts()
  if (bcsOptions.value.length) {
    updateFortsMatches()
  } else {
    loadInstrumentOptions('bcs', '').then(() => { updateFortsMatches(); openForts() })
  }
}
function onFortsBlur() { setTimeout(() => { closeForts() }, 150) }
function pickForts(match) {
  newFortsName.value = match.value
  closeForts()
  nextTick(() => fortsInput.value?.focus())
}
function onFortsKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    openForts()
    if (fortsMatches.value.length) fortsHighlight.value = Math.min(fortsHighlight.value + 1, fortsMatches.value.length - 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    openForts()
    if (fortsMatches.value.length) fortsHighlight.value = Math.max(fortsHighlight.value - 1, 0)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    closeForts()
  } else if (event.key === 'Tab') {
    if (fortsSuggestion.value) {
      event.preventDefault()
      newFortsName.value = fortsSuggestion.value
      updateFortsMatches()
      openForts()
    }
  } else if (event.key === 'Enter') {
    if (fortsOpen.value && fortsMatches.value.length) {
      const target = fortsMatches.value[Math.max(fortsHighlight.value, 0)]
      if (target && target.value.toLowerCase() === newFortsName.value.trim().toLowerCase()) {
        closeForts()
        return
      }
      event.preventDefault()
      pickForts(target)
    }
  }
}
function onSpotFocus() {
  spotOpen.value = true
  if (spotOptions.value.length) updateSpotMatches()
  else loadInstrumentOptions('bcs', '', 'SPOT').then(() => { updateSpotMatches(); spotOpen.value = true })
}
function onSpotInput(event) { upperCaseField(event, newSpotName); spotOpen.value = true; updateSpotMatches() }
function onSpotBlur() { setTimeout(() => { spotOpen.value = false; spotHighlight.value = -1 }, 150) }
function pickSpot(match) { newSpotName.value = match.value; spotOpen.value = false; nextTick(() => spotInput.value?.focus()) }
function onSpotKeydown(event) {
  if (event.key === 'ArrowDown') { event.preventDefault(); spotOpen.value = true; if (spotMatches.value.length) spotHighlight.value = Math.min(spotHighlight.value + 1, spotMatches.value.length - 1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); spotOpen.value = true; if (spotMatches.value.length) spotHighlight.value = Math.max(spotHighlight.value - 1, 0) }
  else if (event.key === 'Escape') { event.preventDefault(); spotOpen.value = false; spotHighlight.value = -1 }
  else if (event.key === 'Tab' && spotSuggestion.value) { event.preventDefault(); newSpotName.value = spotSuggestion.value; updateSpotMatches(); spotOpen.value = true }
  else if (event.key === 'Enter' && spotOpen.value && spotMatches.value.length) { const target = spotMatches.value[Math.max(spotHighlight.value, 0)]; if (target && target.value.toLowerCase() === newSpotName.value.trim().toLowerCase()) { spotOpen.value = false; return }; event.preventDefault(); pickSpot(target) }
}
function onFutureFocus() {
  futureOpen.value = true
  if (futureOptions.value.length) updateFutureMatches()
  else loadInstrumentOptions('bcs', '', 'FUTURES').then(() => { updateFutureMatches(); futureOpen.value = true })
}
function onFutureInput(event) { upperCaseField(event, newFutureName); futureOpen.value = true; updateFutureMatches() }
function onFutureBlur() { setTimeout(() => { futureOpen.value = false; futureHighlight.value = -1 }, 150) }
function pickFuture(match) { newFutureName.value = match.value; futureOpen.value = false; nextTick(() => futureInput.value?.focus()) }
function onFutureKeydown(event) {
  if (event.key === 'ArrowDown') { event.preventDefault(); futureOpen.value = true; if (futureMatches.value.length) futureHighlight.value = Math.min(futureHighlight.value + 1, futureMatches.value.length - 1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); futureOpen.value = true; if (futureMatches.value.length) futureHighlight.value = Math.max(futureHighlight.value - 1, 0) }
  else if (event.key === 'Escape') { event.preventDefault(); futureOpen.value = false; futureHighlight.value = -1 }
  else if (event.key === 'Tab' && futureSuggestion.value) { event.preventDefault(); newFutureName.value = futureSuggestion.value; updateFutureMatches(); futureOpen.value = true }
  else if (event.key === 'Enter' && futureOpen.value && futureMatches.value.length) { const target = futureMatches.value[Math.max(futureHighlight.value, 0)]; if (target && target.value.toLowerCase() === newFutureName.value.trim().toLowerCase()) { futureOpen.value = false; return }; event.preventDefault(); pickFuture(target) }
}
function onFutureFutureFocus(query, matches, total, highlight, suggestion, hint, open) {
  open.value = true
  if (futureOptions.value.length) updateFutureFutureMatches(query, matches, total, highlight, suggestion, hint)
  else loadInstrumentOptions('bcs', '', 'FUTURES').then(() => { updateFutureFutureMatches(query, matches, total, highlight, suggestion, hint); open.value = true })
}
function onFirstFutureFocus() { onFutureFutureFocus(newFirstFutureName, firstFutureMatches, firstFutureTotal, firstFutureHighlight, firstFutureSuggestion, firstFutureHint, firstFutureOpen) }
function onSecondFutureFocus() { onFutureFutureFocus(newSecondFutureName, secondFutureMatches, secondFutureTotal, secondFutureHighlight, secondFutureSuggestion, secondFutureHint, secondFutureOpen) }
function onFutureFutureInput(event, query, matches, total, highlight, suggestion, hint, open) {
  open.value = true
  updateFutureFutureMatches(query, matches, total, highlight, suggestion, hint)
}
function onFirstFutureInput(event) { onFutureFutureInput(event, newFirstFutureName, firstFutureMatches, firstFutureTotal, firstFutureHighlight, firstFutureSuggestion, firstFutureHint, firstFutureOpen) }
function onSecondFutureInput(event) { onFutureFutureInput(event, newSecondFutureName, secondFutureMatches, secondFutureTotal, secondFutureHighlight, secondFutureSuggestion, secondFutureHint, secondFutureOpen) }
function onFutureFutureBlur(open, highlight) { setTimeout(() => { open.value = false; highlight.value = -1 }, 150) }
function onFirstFutureBlur() { onFutureFutureBlur(firstFutureOpen, firstFutureHighlight) }
function onSecondFutureBlur() { onFutureFutureBlur(secondFutureOpen, secondFutureHighlight) }
function pickFutureFuture(query, match, open, input) { query.value = match.value; open.value = false; nextTick(() => input.value?.focus()) }
function pickFirstFuture(match) { pickFutureFuture(newFirstFutureName, match, firstFutureOpen, firstFutureInput) }
function pickSecondFuture(match) { pickFutureFuture(newSecondFutureName, match, secondFutureOpen, secondFutureInput) }
function onFutureFutureKeydown(event, query, matches, total, highlight, suggestion, hint, open, input) {
  if (event.key === 'ArrowDown') { event.preventDefault(); open.value = true; if (matches.value.length) highlight.value = Math.min(highlight.value + 1, matches.value.length - 1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); open.value = true; if (matches.value.length) highlight.value = Math.max(highlight.value - 1, 0) }
  else if (event.key === 'Escape') { event.preventDefault(); open.value = false; highlight.value = -1 }
  else if (event.key === 'Tab' && suggestion.value) { event.preventDefault(); query.value = suggestion.value; updateFutureFutureMatches(query, matches, total, highlight, suggestion, hint); open.value = true }
  else if (event.key === 'Enter' && open.value && matches.value.length) { const target = matches.value[Math.max(highlight.value, 0)]; if (target && target.value.toLowerCase() === query.value.trim().toLowerCase()) { open.value = false; return }; event.preventDefault(); pickFutureFuture(query, target, open, input) }
}
function onFirstFutureKeydown(event) { onFutureFutureKeydown(event, newFirstFutureName, firstFutureMatches, firstFutureTotal, firstFutureHighlight, firstFutureSuggestion, firstFutureHint, firstFutureOpen, firstFutureInput) }
function onSecondFutureKeydown(event) { onFutureFutureKeydown(event, newSecondFutureName, secondFutureMatches, secondFutureTotal, secondFutureHighlight, secondFutureSuggestion, secondFutureHint, secondFutureOpen, secondFutureInput) }
function logout() { priceEvents?.close(); priceEvents = null; token.value = ''; username.value = ''; pairs.value = []; moexPairs.value = []; moexFutureFuturePairs.value = []; localStorage.removeItem('arbitrage_token'); localStorage.removeItem('arbitrage_username') }
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
const moexPairEnding = computed(() => { const remainder = moexPairs.value.length % 10; return remainder === 1 && moexPairs.value.length % 100 !== 11 ? '' : remainder >= 2 && remainder <= 4 ? 'а' : 'ов' })
const moexFutureFuturePairEnding = computed(() => { const remainder = moexFutureFuturePairs.value.length % 10; return remainder === 1 && moexFutureFuturePairs.value.length % 100 !== 11 ? '' : remainder >= 2 && remainder <= 4 ? 'а' : 'ов' })
const visibleColumnCount = computed(() => showContractDetails.value ? 20 : 13)
const moexVisibleColumnCount = computed(() => moexShowContractDetails.value ? 18 : 10)
onMounted(() => { if (authenticated.value) { loadPairs(); if (activeTable.value === 'moex_spot_future') loadMoexPairs(); if (activeTable.value === 'moex_future_future') loadMoexFutureFuturePairs(); loadCurrencyRates(); connectPriceEvents(); loadInstrumentOptions('exante'); loadInstrumentOptions('bcs'); loadInstrumentOptions('bcs', '', 'SPOT'); loadInstrumentOptions('bcs', '', 'FUTURES') } })
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
.add-pair-row { display: flex; justify-content: space-between; align-items: end; gap: 24px; padding: 19px 20px; margin-bottom: 18px; border: 1px solid #35423d; background: #19201e; } .section-label { margin-bottom: 7px; } .add-pair-form { display: flex; width: min(100%,700px); gap: 8px; align-items: end; } .pair-fields { display: flex; flex: 1; gap: 8px; } .pair-fields input { margin: 0; flex: 1; min-width: 0; } .pair-select { flex: 1; margin: 0; min-width: 0; } .pair-select input { margin-top: 7px; } .pair-hint { display: block; margin-top: 7px; color: #7f8d86; font-size: 11px; line-height: 1.4; text-transform: none; letter-spacing: 0; }
.combobox { position: relative; }
.combobox-control { position: relative; margin-top: 7px; }
.pair-select .combobox-control { margin-top: 0; }
.combobox-input { position: relative; z-index: 2; margin-top: 0 !important; }
.combobox-menu { position: absolute; z-index: 30; top: 100%; left: 0; width: max-content; min-width: 100%; max-width: calc(100vw - 28px); max-height: 280px; margin: 4px 0 0; padding: 4px 0; overflow-x: auto; overflow-y: auto; border: 1px solid #35423d; border-top: 2px solid #77d6b6; background: #101514; list-style: none; text-transform: none; box-shadow: 0 18px 44px rgba(0, 0, 0, .45); }
.combobox-menu li { display: flex; width: max-content; min-width: 100%; align-items: baseline; gap: 8px; padding: 8px 12px; cursor: pointer; }
.combobox-menu li.is-active { background: #1a2420; }
.combobox-value { color: #eef6f1; font: 500 12px 'IBM Plex Mono', monospace; white-space: nowrap; }
.combobox-value mark { color: #77d6b6; background: rgba(119, 214, 182, .12); padding: 0 1px; }
.combobox-details { flex: none; color: #7f8d86; font: 11px 'IBM Plex Mono', monospace; white-space: nowrap; }
.add-pair-form .primary-button { white-space: nowrap; } .table-section { border: 1px solid #35423d; background: #141a18; } .table-toolbar { display: flex; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #35423d; color: #aeb9b3; font: 12px 'IBM Plex Mono', monospace; } .table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font: 12px 'IBM Plex Mono', monospace; } th { padding: 13px 12px; color: #84948c; font-weight: 500; text-align: right; white-space: nowrap; background: #171e1b; } td { padding: 14px 12px; color: #dbe4df; text-align: right; white-space: nowrap; border-top: 1px solid #28322e; } th:first-child, th:nth-child(7), td:first-child, td:nth-child(7) { text-align: left; } tbody tr:hover { background: #1a2420; } .instrument { color: #f0f7f3; font-weight: 600; } .positive { color: #75dbb6; } .negative { color: #ff9989; } .editable-cell { cursor: text; outline: 1px dashed transparent; outline-offset: -4px; } .editable-cell:hover { outline-color: #587269; background: #18221e; } .editable-cell input { width: 100%; min-width: 72px; margin: -7px 0; border-color: #77d6b6; padding: 6px 7px; text-align: right; font: inherit; } .editable-cell.is-invalid { color: #ff9d8b; outline-color: #ff7567; background: rgba(158, 54, 44, .24); } .editable-cell.is-invalid input { border-color: #ff7567; } .empty-state { padding: 35px; color: #8f9d96; text-align: center !important; } .table-error { margin-bottom: 14px; }
.currency-rates { display: flex; align-items: stretch; margin-bottom: 18px; border: 1px solid #35423d; background: #161d1a; font: 12px 'IBM Plex Mono', monospace; } .currency-rates-title, .currency-rate { display: flex; flex-direction: column; justify-content: center; padding: 12px 16px; border-right: 1px solid #35423d; } .currency-rates-title { min-width: 215px; color: #77d6b6; letter-spacing: .6px; } .currency-rates-title small, .currency-rates-empty { margin-top: 4px; color: #7f8d86; font-size: 11px; letter-spacing: 0; } .currency-rate { min-width: 150px; gap: 4px; } .currency-rate strong { color: #aeb9b3; font-weight: 500; } .currency-rate span { color: #e4eee9; font-size: 14px; font-weight: 600; } .currency-rates-empty { align-self: center; margin: 0; padding: 0 16px; }
.table-toolbar { align-items: center; gap: 12px; padding: 10px 12px; } .table-toolbar-actions { display: flex; align-items: center; gap: 12px; } .details-toggle { border: 1px solid #46574f; border-radius: 2px; padding: 6px 8px; color: #b9c7c0; background: #19211e; font: 11px 'IBM Plex Mono', monospace; } .details-toggle:hover { border-color: #77d6b6; color: #e7f4ed; } th, td { text-align: center !important; } th { padding: 9px 8px; line-height: 1.25; } .header-label { display: inline-block; } .sort-header { display: inline-flex; align-items: center; justify-content: center; gap: 3px; border: 0; padding: 0; color: inherit; background: transparent; font: inherit; text-align: inherit; } .sort-header:hover, .sort-header:focus-visible, .sort-header.is-active { color: #77d6b6; } .sort-header:focus-visible { outline: 1px solid #77d6b6; outline-offset: 3px; } table.is-compact { min-width: 920px; table-layout: fixed; } .contract-column { width: 14%; } .date-column { width: 9%; } .price-column, .ratio-column { width: 8%; } .dte-column, .percent-column { width: 5%; } .virt-column, .diff-column { width: 7%; } .ytm-column { width: 6%; } .action-column { width: 4%; } td { max-width: 132px; padding: 10px 8px; } .instrument { display: block; max-width: 100%; overflow: hidden; text-align: center; text-overflow: ellipsis; } .editable-cell input { min-width: 64px; margin: -5px 0; padding: 5px 6px; } .trade-lot-currency { border: 1px solid #46574f; border-radius: 2px; padding: 5px 6px; color: #dbe4df; background: #19211e; font: inherit; } .trade-lot-currency:focus { border-color: #77d6b6; outline: none; } .trade-lot-currency:disabled { cursor: wait; opacity: .6; } .pair-action { padding: 0 4px; } .delete-pair-button { width: 24px; height: 24px; border: 1px solid transparent; border-radius: 2px; padding: 0; color: #87958e; background: transparent; font: 500 18px/1 'IBM Plex Mono', monospace; } .delete-pair-button:hover:not(:disabled) { border-color: #a85850; color: #ff9989; background: rgba(158, 54, 44, .18); } .delete-pair-button:disabled { cursor: wait; opacity: .45; }
@media (max-width: 700px) { .topbar, .dashboard-heading, .add-pair-row { align-items: flex-start; flex-direction: column; } .topbar-actions { width: 100%; justify-content: space-between; } .workspace { padding: 30px 14px; } .heading-metrics { width: 100%; } .add-pair-form { width: 100%; flex-direction: column; } .pair-fields { width: 100%; flex-direction: column; } .pair-select { width: 100%; } .add-pair-form .primary-button { width: 100%; } .currency-rates { flex-wrap: wrap; } .currency-rates-title { width: 100%; min-width: 0; border-bottom: 1px solid #35423d; } .currency-rate { flex: 1; min-width: 0; } .currency-rate:last-of-type { border-right: 0; } .login-panel { padding: 28px 23px; } }
.add-pair-form { width: min(100%, 620px); }
.pair-fields { align-items: flex-start; }
.pair-select { flex: 0 1 170px; }
.pair-select--cme { flex-basis: 190px; }
.pair-select--forts { flex-basis: 170px; }
.pair-select--currency { flex: 0 0 130px; }
.pair-select { display: grid; grid-template-rows: 14px 40px minmax(15px, auto); gap: 7px; }
.pair-select-label { overflow: hidden; line-height: 14px; text-overflow: ellipsis; white-space: nowrap; }
.pair-select input, .pair-currency-select { height: 40px; }
.pair-select input { margin-top: 0; padding: 0 12px; }
.pair-select .pair-hint { margin-top: 0; }
.pair-currency-control { display: block; position: relative; margin-top: 0; }
.pair-currency-control::after { content: ''; position: absolute; top: 50%; right: 14px; width: 6px; height: 6px; border-right: 1px solid #aeb9b3; border-bottom: 1px solid #aeb9b3; pointer-events: none; transform: translateY(-70%) rotate(45deg); }
.pair-currency-select { width: 100%; appearance: none; border: 1px solid #3b4742; border-radius: 2px; padding: 0 32px 0 12px; color: #eef6f1; background: #101514; font: inherit; cursor: pointer; }
.pair-currency-select:focus { border-color: #77d6b6; outline: none; }
.add-pair-form .primary-button { align-self: flex-start; height: 40px; margin-top: 21px; padding: 0 16px; }
@media (max-width: 700px) { .add-pair-form .primary-button { margin-top: 0; } }
.table-tabs { display: flex; gap: 2px; margin-bottom: 18px; border-bottom: 1px solid #35423d; }
.table-tabs button { border: 1px solid transparent; border-bottom: 0; border-radius: 2px 2px 0 0; padding: 11px 14px; color: #7f8d86; background: transparent; font: 11px 'IBM Plex Mono', monospace; }
.table-tabs button:hover, .table-tabs button.is-active { color: #dff3e9; border-color: #35423d; background: #19201e; }
.table-tabs button.is-active { color: #77d6b6; border-top-color: #77d6b6; }
.moex-table { min-width: 1680px; }
.moex-table.is-compact { min-width: 920px; table-layout: fixed; }
.moex-table.is-compact td:nth-child(3),
.moex-table.is-compact td:nth-child(5),
.moex-table.is-compact td:nth-child(6),
.moex-table.is-compact td:nth-child(7),
.moex-table.is-compact td:nth-child(11),
.moex-table.is-compact td:nth-child(12),
.moex-table.is-compact td:nth-child(13) { display: none; }
.calculation-legend { margin-top: 12px; border: 1px solid #35423d; background: #141a18; }
.calculation-legend-title { padding: 10px 12px; border-bottom: 1px solid #35423d; color: #77d6b6; font: 600 10px 'IBM Plex Mono', monospace; letter-spacing: 1px; }
.calculation-legend-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: #35423d; }
.calculation-legend-grid div { min-width: 0; padding: 11px 12px; background: #19211e; }
.calculation-legend-grid strong { display: block; margin-bottom: 5px; color: #dbe4df; font: 500 11px 'IBM Plex Mono', monospace; }
.calculation-legend-grid span { display: block; color: #8f9d96; font: 11px/1.45 'IBM Plex Mono', monospace; }
@media (max-width: 900px) { .calculation-legend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .calculation-legend-grid { grid-template-columns: 1fr; } }
</style>