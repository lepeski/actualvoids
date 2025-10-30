# Withdrawal Discord Bot

A Discord bot paired with a FastAPI web service that accepts withdrawal requests from a Minecraft plugin and allows administrators to approve or reject payouts. Approved requests trigger automated payments through a wallet client integration.

## Features

- **HTTP API for the Minecraft plugin** – submit withdrawal requests via REST and query their status later.
- **Discord notifications** – each request is posted to a configured channel with interactive buttons for admins to approve or reject.
- **Wallet abstraction** – integrate a real cryptocurrency wallet by replacing the provided dummy implementation.
- **Persistent storage** – SQLite keeps track of pending, approved, rejected, and failed withdrawals.
- **Slash command** – `/withdrawal_status <id>` lets moderators check the latest status of any request.

## Prerequisites

- Python 3.10+
- A Discord bot token with the necessary intents (`Guilds` and `Members`).
- (Optional) A `.env` file in the repository root for local development.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

The application reads its configuration from environment variables. You can store them in a `.env` file for convenience.

| Variable | Description |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token. **Required.** |
| `WITHDRAWAL_CHANNEL_ID` | ID of the channel where withdrawal requests are posted. **Required.** |
| `ADMIN_ROLE_IDS` | Comma-separated list of role IDs that are allowed to approve/reject requests. If omitted, all administrators may act. |
| `HOME_GUILD_ID` | Guild ID for syncing slash commands faster. Optional. |
| `API_HOST` | Host for the FastAPI server (default `0.0.0.0`). |
| `API_PORT` | Port for the FastAPI server (default `8080`). |
| `DATABASE_PATH` | Path to the SQLite database file (default `withdrawals.db`). |
| `LOG_LEVEL` | Logging level (default `INFO`). |
| `WALLET_PROVIDER` | Set to `piteas` to use the bundled Piteas integration. Default `auto`. |
| `WALLET_ENDPOINT`, `WALLET_API_KEY` | Configure a custom HTTP wallet endpoint and optional bearer token when `WALLET_PROVIDER` is not `piteas`. |
| `PITEAS_API_URL` | Base URL for your Piteas API instance (defaults to the hosted cloud API). |
| `PITEAS_API_KEY` | API key generated from the Piteas dashboard. Required when `WALLET_PROVIDER=piteas`. |
| `PITEAS_PROJECT_ID` | Project identifier from Piteas. Required when `WALLET_PROVIDER=piteas`. |
| `PITEAS_WALLET_ID` | Wallet identifier to debit from. Required when `WALLET_PROVIDER=piteas`. |
| `PITEAS_ASSET_SYMBOL` | Asset ticker (e.g. `USDT`). Required when `WALLET_PROVIDER=piteas`. |
| `PITEAS_NETWORK` | Network name recognised by Piteas (e.g. `TRON`). Required when `WALLET_PROVIDER=piteas`. |
| `PITEAS_PRIORITY` | Optional withdrawal priority (`low`, `medium`, `high`). |

## Running the bot

```bash
python -m bot.main
```

The FastAPI server starts in the background and listens for new requests while the Discord bot stays online waiting for admin approvals. Use `Ctrl+C` to shut everything down gracefully.

## API reference

### `POST /withdrawals`

Create a new withdrawal request. Example payload:

```json
{
  "player_name": "Notch",
  "player_uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
  "wallet_address": "bc1qexample",
  "amount": "0.5",
  "currency": "BTC",
  "metadata": {
    "server": "survival",
    "reason": "Weekly payout"
  }
}
```

Returns the created request with status `pending`.

### `GET /withdrawals/{id}`

Fetch the latest status of a specific request.

### `GET /withdrawals?status=pending`

List requests by status. Supported values: `pending`, `processing`, `approved`, `rejected`, `failed`.

### `GET /health`

Simple health-check endpoint returning `{ "status": "ok" }`.

## Wallet integration

By default the bot uses a simulated wallet that logs payments for local development. There are two production-grade options available: a generic HTTP webhook and a first-class [Piteas](https://github.com/piteasio/piteas-api-monorepo) integration.

### Generic HTTP wallet

Set `WALLET_PROVIDER=auto` (the default), define `WALLET_ENDPOINT` (and optionally `WALLET_API_KEY`), and the bot will POST withdrawal details as JSON to the configured endpoint. It expects a response shaped like:

```json
{
  "transaction_id": "abc123"
}
```

If your service responds with a different key, `txid` or `id` are also recognised. Any non-2xx HTTP code or missing transaction identifier will be treated as a failure and the withdrawal is marked as failed.

### Piteas wallet

To rely on [Piteas](https://piteas.io) for on-chain fulfilment:

1. Deploy the [Piteas API](https://github.com/piteasio/piteas-api-monorepo) locally or use the hosted cloud service.
2. Create a project and wallet, then generate an API key with withdrawal permissions.
3. Export the following environment variables:

   ```bash
   export WALLET_PROVIDER=piteas
   export PITEAS_API_KEY="<your api key>"
   export PITEAS_PROJECT_ID="<project id>"
   export PITEAS_WALLET_ID="<wallet id>"
   export PITEAS_ASSET_SYMBOL="USDT"
   export PITEAS_NETWORK="TRON"
   # Optional overrides
   export PITEAS_API_URL="https://api.piteas.io"
   export PITEAS_PRIORITY="medium"
   ```

When administrators approve a withdrawal, the bot will call the Piteas `/api/projects/{project_id}/wallets/{wallet_id}/withdrawals` endpoint and record the returned `transactionHash`, `transaction_id`, or `id` value against the request. Any error from Piteas marks the withdrawal as failed so that it can be retried.

To completely customise the behaviour you can still subclass `WalletClient` in `bot/wallet.py` and wire it up in `bot/main.py`.

## Linking with your Minecraft plugin

Point the plugin's HTTP client to the FastAPI server (`http://<host>:<port>`). After submitting a request, wait for the Discord admins to approve it; the bot will make the payout through the wallet client and update the request status automatically.

