<template>
  <div class="app">
    <header class="header">
      <div class="container">
        <h1>🤖 Arbitrage System</h1>
        <p class="subtitle">Система арбитража криптовалют / ценных бумаг</p>
      </div>
    </header>

    <main class="container">
      <!-- Статус -->
      <section class="card">
        <h2>📊 Статус системы</h2>
        <div class="status-grid">
          <div class="status-item" :class="healthStatus">
            <span class="status-label">API</span>
            <span class="status-dot"></span>
            <span class="status-text">{{ healthText }}</span>
          </div>
          <div class="status-item" :class="bcsStatus">
            <span class="status-label">БКС</span>
            <span class="status-dot"></span>
            <span class="status-text">{{ bcsText }}</span>
          </div>
          <div class="status-item" :class="exanteStatus">
            <span class="status-label">EXANTE</span>
            <span class="status-dot"></span>
            <span class="status-text">{{ exanteText }}</span>
          </div>
        </div>
      </section>

      <!-- Портфель -->
      <section class="card">
        <h2>💼 Портфель</h2>
        <p v-if="portfolio.message" class="placeholder">{{ portfolio.message }}</p>
        <div v-else>
          <p>Общая стоимость: ${{ portfolio.totalValue }}</p>
          <p>Свободно: ${{ portfolio.freeBalance }}</p>
        </div>
      </section>

      <!-- Заявки -->
      <section class="card">
        <h2>📋 Активные заявки</h2>
        <p v-if="orders.message" class="placeholder">{{ orders.message }}</p>
        <ul v-else>
          <li v-for="o in orders.orders" :key="o.id">{{ o.ticker }} — {{ o.side }} — {{ o.quantity }}</li>
        </ul>
      </section>

      <!-- Сводка -->
      <section class="card info-card">
        <h2>ℹ️ Информация</h2>
        <table class="info-table">
          <tr>
            <td>Бэкенд</td>
            <td>FastAPI (Python)</td>
          </tr>
          <tr>
            <td>БД</td>
            <td>PostgreSQL</td>
          </tr>
          <tr>
            <td>Подключения</td>
            <td>БКС (REST + WebSocket), EXANTE (REST + Stream)</td>
          </tr>
        </table>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const healthStatus = ref('loading')
const healthText = ref('Проверка...')
const bcsStatus = ref('loading')
const bcsText = ref('Проверка...')
const exanteStatus = ref('loading')
const exanteText = ref('Проверка...')

const portfolio = ref({ message: 'Загрузка...' })
const orders = ref({ message: 'Загрузка...' })

async function checkHealth() {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    healthStatus.value = 'ok'
    healthText.value = `OK (${data.service})`
  } catch {
    healthStatus.value = 'error'
    healthText.value = 'Недоступен'
  }
}

async function checkConnectors() {
  try {
    const res = await fetch('/api/connectors')
    const data = await res.json()
    for (const c of data.connectors) {
      if (c.name === 'bcs') {
        bcsStatus.value = c.status === 'configured' ? 'ok' : 'warn'
        bcsText.value = c.status === 'configured' ? 'Настроен' : 'Не настроен'
      }
      if (c.name === 'exante') {
        exanteStatus.value = c.status === 'configured' ? 'ok' : 'warn'
        exanteText.value = c.status === 'configured' ? 'Настроен' : 'Не настроен'
      }
    }
  } catch {
    bcsStatus.value = 'error'
    bcsText.value = 'Ошибка'
    exanteStatus.value = 'error'
    exanteText.value = 'Ошибка'
  }
}

async function fetchPortfolio() {
  try {
    const res = await fetch('/api/portfolio')
    portfolio.value = await res.json()
  } catch {
    portfolio.value = { message: 'Ошибка загрузки' }
  }
}

async function fetchOrders() {
  try {
    const res = await fetch('/api/orders')
    orders.value = await res.json()
  } catch {
    orders.value = { message: 'Ошибка загрузки' }
  }
}

onMounted(() => {
  checkHealth()
  checkConnectors()
  fetchPortfolio()
  fetchOrders()
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
  background: #0f172a;
  color: #e2e8f0;
  min-height: 100vh;
}

.container {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 20px;
}

.header {
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-bottom: 1px solid #334155;
  padding: 40px 0 30px;
  text-align: center;
}

.header h1 {
  font-size: 2rem;
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.subtitle {
  color: #94a3b8;
  margin-top: 8px;
  font-size: 1rem;
}

main {
  padding: 30px 0;
}

.card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 20px;
}

.card h2 {
  font-size: 1.1rem;
  margin-bottom: 16px;
  color: #f1f5f9;
}

.status-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #0f172a;
  border-radius: 8px;
  border: 1px solid #334155;
  font-size: 0.9rem;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #64748b;
}

.status-item.ok .status-dot { background: #22c55e; }
.status-item.warn .status-dot { background: #f59e0b; }
.status-item.error .status-dot { background: #ef4444; }
.status-item.loading .status-dot { background: #64748b; animation: pulse 1s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.placeholder {
  color: #64748b;
  font-style: italic;
}

.info-table {
  width: 100%;
  border-collapse: collapse;
}

.info-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #334155;
  font-size: 0.9rem;
}

.info-table td:first-child {
  color: #94a3b8;
  width: 140px;
}
</style>
