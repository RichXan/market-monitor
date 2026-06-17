# Market Monitor

Local market dashboard for A-share, Hong Kong, US equity, and Shanghai Gold Exchange spot gold monitoring.

## Data Sources

- A-share quotes and A-share sector boards: AKShare / Eastmoney, with yfinance/Yahoo single-symbol fallback when AKShare quote feeds are slow or unavailable
- Hong Kong quotes: AKShare / Eastmoney delayed quote feed, with yfinance/Yahoo single-symbol fallback when AKShare quote feeds are slow or unavailable
- US quotes: yfinance / Yahoo Finance
- Gold: AKShare / Shanghai Gold Exchange `Au99.99`
- Hong Kong and US sector panels use strict mode. They show an unavailable state unless a reliable free daily active sector ranking source is configured.

## Run

Docker Compose:

```powershell
docker compose up -d
```

Then open `http://127.0.0.1:5173`.

Services:

- Frontend: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8000`
- Redis: `127.0.0.1:6379`

Useful commands:

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose down
```

The first startup installs Python and Node dependencies inside containers, so it can take a few minutes. The Compose stack uses Redis for backend quote/gold/sector caching and persists Redis data in the `redis-data` volume. The watchlist remains in `backend/data/watchlist.json`.

Local development without Docker:

Backend:

```powershell
cd .\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
cd .\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Test

Backend:

```powershell
cd .\backend
.\.venv\Scripts\python -m pytest -q
```

Frontend:

```powershell
cd .\frontend
npm test -- --run
npm run build
```

## Local Data

The watchlist is stored in `backend/data/watchlist.json` by default. Set `MARKET_MONITOR_DATA` before starting the backend to use another data directory.

## Cache

The backend caches quote, gold, and sector API responses to reduce repeated calls to AKShare and Yahoo Finance. By default it uses an in-process memory cache.

To use Redis instead, start Redis locally or point to an existing Redis instance before starting the backend:

```powershell
$env:MARKET_MONITOR_REDIS_URL = "redis://localhost:6379/0"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Optional TTL settings:

- `MARKET_MONITOR_QUOTE_CACHE_TTL_SECONDS`, default `15`
- `MARKET_MONITOR_GOLD_CACHE_TTL_SECONDS`, default `15`
- `MARKET_MONITOR_SECTOR_CACHE_TTL_SECONDS`, default `60`
