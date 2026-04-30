# Fake Redis Live Dashboard Test

This guide explains how to test `run_server --mode live` when the real Redis
market-data host is unavailable.

The recommended approach is to run a local Redis server and publish synthetic
messages that match the real feed protocol:

```text
local Redis Pub/Sub
  -> RedisLiveProvider
  -> run_daily_replay()
  -> LiveState
  -> FastAPI REST + Socket.IO
  -> React dashboard
```

This is not a production fake-data mode. The server still runs the normal live
path and will not silently fall back if Redis is unavailable.

## Prerequisites

Run from the repository root:

```bash
uv sync --extra live
```

The live server also needs valid reference/history inputs for the selected
trade date. Use the same `--date`, `--config`, `--data-dir`, `--files-dir`, and
`--group-file` values you would use for a normal live or replay run.

Build the dashboard if you want to open the browser UI at `/`:

```bash
cd dashboard
npm install
npm run build
cd ..
```

## Step 1: Start A Local Redis Server

Using Docker:

```bash
docker run --rm --name tw-signal-fake-redis -p 6379:6379 redis:7
```

Or with a native Redis install:

```bash
redis-server --port 6379
```

Leave this terminal running.

## Step 2: Start The Live Server Against Local Redis

In a second terminal, start live mode with `127.0.0.1:6379`:

```bash
uv run python -m tw_signal_engine.cli.run_server \
  --mode live \
  --date <YYYYMMDD> \
  --config exec/cfg/parameter.cfg \
  --data-dir <MARKET_DATA_DIR> \
  --files-dir <SYMBOLS_DIR> \
  --group-file <GROUP_FILE> \
  --redis-host 127.0.0.1 \
  --redis-port 6379
```

If your environment variables already provide the default paths, you can omit
the path flags:

```bash
uv run python -m tw_signal_engine.cli.run_server \
  --mode live \
  --date <YYYYMMDD> \
  --redis-host 127.0.0.1 \
  --redis-port 6379
```

Expected startup behavior:

- the FastAPI server starts;
- the engine thread starts;
- the Redis provider subscribes to the computed symbol universe;
- `/api/status.feed_status.connected` becomes `true`;
- `/api/status.feed_status.subscribed_channels` becomes non-zero.

## Step 3: Pick A Subscribed Channel

Redis Pub/Sub channels are stock symbols. The live provider subscribes only to
the engine's computed `tick_filter`, so publishing to an arbitrary symbol may do
nothing.

After the live server starts, list channels with active subscribers:

```bash
redis-cli -h 127.0.0.1 -p 6379 --raw PUBSUB CHANNELS | head
```

Pick one symbol from the output, for example `2330`. If the command returns no
channels, the live provider has not subscribed yet or the live engine failed
before entering the provider loop. Check:

```bash
curl http://127.0.0.1:8000/api/status
```

Common causes of no subscribed channels:

- missing symbol/reference files for the selected date;
- invalid history inputs;
- engine startup failure;
- no symbols passed the configured universe filters.

## Step 4: Publish Synthetic Trade/Depth Rows

In a third terminal, run this publisher. If `FAKE_REDIS_SYMBOL` is unset, it
uses the first active subscribed channel from Redis.

```bash
FAKE_REDIS_SYMBOL=<SYMBOL_FROM_PUBSUB_CHANNELS> \
uv run python - <<'PY'
from __future__ import annotations

import os
import time

import redis

HOST = "127.0.0.1"
PORT = 6379


def pick_symbol(client: redis.Redis) -> str:
    configured = os.environ.get("FAKE_REDIS_SYMBOL", "").strip()
    if configured:
        return configured

    channels = client.pubsub_channels()
    if not channels:
        raise SystemExit(
            "No active Redis Pub/Sub channels. Start live mode first, then retry."
        )
    first = channels[0]
    return first.decode("utf-8") if isinstance(first, bytes) else str(first)


r = redis.Redis(host=HOST, port=PORT, decode_responses=False)
symbol = pick_symbol(r)

base_time = 90_000_000_000   # 09:00:00.000000
base_price = 5_000_000       # 500.0000, because prices are scaled by 10000

print(f"Publishing fake Redis feed to channel {symbol!r}")

for i in range(180):
    match_time = base_time + i * 1_000_000
    price = base_price + i * 1_000
    cumulative_volume = 1_000 + i * 100

    trade = (
        f"Trade,{symbol}  ,{match_time},0,{price},100,"
        f"{cumulative_volume},1"
    )
    depth = (
        f"Depth,{symbol}  ,{match_time},"
        f"BID:1,{price - 1000},100,"
        f"ASK:1,{price + 1000},200"
    )

    r.publish(symbol, trade)
    r.publish(symbol, depth)
    print(trade)
    time.sleep(1.0)
PY
```

Message details:

- channel name is the stock symbol;
- `Trade` and `Depth` rows use the same protocol as the real feed;
- symbol fields intentionally include trailing spaces to exercise stripping;
- `func_code=0` marks normal trade data;
- price is integer scaled by 10,000;
- `Trade` arrives before `Depth` so the provider emits one paired `MarketTick`.

## Step 5: Verify Feed Health

Check the API:

```bash
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/dashboard/status
```

Expected live feed fields:

```json
{
  "mode": "live",
  "engine_status": "running",
  "feed_status": {
    "source": "redis",
    "connected": true,
    "subscribed_channels": 123,
    "last_message_at": "2026-04-30T...",
    "last_tick_time_raw": 90000000000,
    "reconnect_count": 0,
    "parse_error_count": 0,
    "ignored_message_count": 0,
    "queue_depth": 0,
    "last_error": ""
  }
}
```

Important interpretation:

- If `connected=true` but `last_message_at` does not advance, you are probably
  publishing to a channel the provider did not subscribe to.
- If `last_message_at` advances but `last_tick_time_raw` does not, the provider
  is receiving messages but not emitting ticks. Check malformed rows,
  `func_code`, and Trade/Depth pairing.
- If `last_tick_time_raw` advances but `tick_count` does not, the provider is
  emitting ticks but the engine may be blocked, stopped, or still initializing.
- Dashboard snapshots may update only at minute boundaries or when the strategy
  has enough state to build a snapshot. Feed health is the first thing to check
  during a fake-feed smoke test.

Open the dashboard:

```text
http://127.0.0.1:8000/
```

Expected UI behavior:

- socket status shows connected;
- Redis status shows connected;
- feed age stays fresh while the publisher runs;
- subscribed channel count is non-zero;
- reconnect and parse-error counts remain zero.

## Negative Tests

Use these to confirm the diagnostics are wired correctly.

Replace `<SYMBOL>` with a subscribed channel from `PUBSUB CHANNELS`.

### Malformed Trade Row

```bash
redis-cli -h 127.0.0.1 -p 6379 PUBLISH <SYMBOL> 'Trade,2330'
```

Expected:

- `feed_status.parse_error_count` increases;
- `feed_status.last_error` mentions a malformed Trade row;
- the server and dashboard remain up.

### Unknown Message Type

```bash
redis-cli -h 127.0.0.1 -p 6379 PUBLISH <SYMBOL> 'Quote,2330,90000000000'
```

Expected:

- `feed_status.ignored_message_count` increases;
- no tick is emitted.

### Non-Normal Trade

```bash
redis-cli -h 127.0.0.1 -p 6379 PUBLISH <SYMBOL> 'Trade,2330,90000000000,1,5000000,100'
redis-cli -h 127.0.0.1 -p 6379 PUBLISH <SYMBOL> 'Depth,2330,90000000000,BID:1,4999000,100,ASK:1,5001000,200'
```

Expected:

- the row is ignored because `func_code != 0`;
- `feed_status.ignored_message_count` increases after the Trade row is paired
  with the Depth row.

### Redis Disconnect/Reconnect

If using Docker, stop the local Redis container:

```bash
docker stop tw-signal-fake-redis
```

Expected while Redis is down:

- `feed_status.connected` becomes `false`;
- `feed_status.reconnect_count` increases;
- the FastAPI server remains reachable;
- the dashboard shows Redis disconnected/retrying separately from browser socket
  status.

Start Redis again:

```bash
docker run --rm --name tw-signal-fake-redis -p 6379:6379 redis:7
```

The provider should reconnect and resubscribe. Re-run the publisher to confirm
`last_message_at` and `last_tick_time_raw` advance again.

## Troubleshooting

### `/api/status` Has No `feed_status`

The server is not in live mode. Confirm the command uses:

```bash
--mode live
```

Replay mode intentionally omits Redis health.

### `connected=false` With `Connection refused`

Local Redis is not running or the wrong port is configured. Start Redis on the
same port passed to `--redis-port`.

### `connected=true`, `subscribed_channels=0`

The provider had no symbols to subscribe to. Check reference data, group file,
and strategy filters for the selected date/config.

### Published Messages Do Not Change `last_message_at`

You are publishing to the wrong channel. Use:

```bash
redis-cli -h 127.0.0.1 -p 6379 --raw PUBSUB CHANNELS | head
```

Then publish to one of those exact channel names.

### `parse_error_count` Increases

Check the CSV row shape. The minimal valid Trade/Depth pair is:

```text
Trade,2330  ,90000000000,0,5000000,100,1000,1
Depth,2330  ,90000000000,BID:1,4999000,100,ASK:1,5001000,200
```

### Dashboard Loads But Shows Stale Data

Check feed health first:

```bash
curl http://127.0.0.1:8000/api/dashboard/status
```

If feed health is fresh but dashboard snapshots are stale, the synthetic stream
may not be enough to drive strategy state or minute snapshots. Continue
publishing across minute boundaries, or use replay dashboard mode for complete
UI workflow testing.

## What This Test Proves

This fake Redis setup proves:

- the server can connect to Redis and subscribe;
- Redis Pub/Sub messages reach `RedisLiveProvider`;
- Trade/Depth parsing and pairing produce live ticks;
- feed health reaches `/api/status` and `/api/dashboard/status`;
- the React dashboard distinguishes socket health from Redis feed health;
- Redis outages are visible without crashing the web server.

It does not prove trading-strategy correctness against real market conditions.
Use replay validation and real Redis market-hours smoke tests for that.
