# Arbitrage System Context

## Project Purpose
Arbitrage System is a FastAPI + Vue application for monitoring arbitrage pairs and extending them with broker/data-provider integrations.

Current workspace structure:
- backend: FastAPI API, auth, arbitrage pair CRUD, broker-backed helper endpoints
- frontend: Vue/Vite terminal-style UI for login, table view, and pair creation
- connectors: async integrations for BCS and EXANTE
- db.py: asyncpg pool factory
- run_local.py: local backend entrypoint via uvicorn reload

## External Documentation
- BCS Trade API: https://trade-api.bcs.ru/
- BCS HTTP reference root: https://trade-api.bcs.ru/http
- BCS information directory: https://trade-api.bcs.ru/http/information
- EXANTE HTTP API landing: https://api.exante.eu/http-api/
- EXANTE API docs base: https://api-live.exante.eu/api-docs/

## Integration Notes
- BCS auth uses refresh_token -> access_token flow.
- EXANTE supports JWT and Basic Auth; this project already has an async connector for both.
- The UI now requests ticker suggestions from `/api/instrument-options`.
- EXANTE suggestions are built from live symbol/group references.
- BCS suggestions first try the documented instruments-by-ticker route and then fall back to portfolio / known local pair symbols if the endpoint is unavailable or changes.

## Current UX Assumption
- The first add-pair field is populated from EXANTE suggestions.
- The second add-pair field is populated from BCS suggestions.
- Database field names still remain `cme_name` and `forts_name`, so future refactors may want to rename them to provider-neutral names.
