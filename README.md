# Aave V3 Multi-Chain Risk Monitor

An always-on, RPC-native monitoring service for Aave V3 markets across multiple chains.

The monitor watches reserve health, liquidity, utilization, interest-rate models, configuration changes, and market activity, then delivers concise, data-driven alerts to Telegram. When a risk threshold is crossed, the system retrieves the relevant on-chain events and uses a locally hosted LLM to add quantitative context to the alert.

**Live monitoring channel:** [@AaveV3Risk](https://t.me/AaveV3Risk)

---

## Overview

Aave V3 markets can change rapidly as liquidity moves, borrowing demand increases, reserve parameters are updated, or liquidations occur.

This project is designed to answer two questions:

1. **What changed?**
2. **What on-chain activity and market conditions help explain the change?**

Rather than continuously indexing every event, the monitor uses a threshold-driven architecture:

```text
                    Aave V3 Contracts
                           |
                           v
                    RPC / Web3 Provider
                           |
                           v
                  Reserve Monitoring
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
        Utilization      Supply      Configuration
          / Rates        Changes       / IR Model
             |             |             |
             +-------------+-------------+
                           |
                    Alert Threshold?
                           |
                    +------+------+
                    |             |
                   No            Yes
                    |             |
                    |             v
                    |       Query relevant
                    |       on-chain events
                    |             |
                    |             v
                    |       Local LLM analysis
                    |             |
                    +-------> Telegram
```

The LLM is strictly supplemental. **It never determines whether an alert fires.**

---

## What It Monitors

| Category              | Detection                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------- |
| Reserve lifecycle     | Reserve onboarding or removal                                                             |
| Reserve configuration | Active, frozen, paused, borrowing-enabled and related configuration changes               |
| Utilization           | Crossings above or below the interest-rate model's optimal utilization                    |
| Supply                | Configurable percentage change in total supplied liquidity                                |
| Interest-rate model   | Changes to optimal utilization, base rate, or rate slopes                                 |
| On-chain activity     | Supply, Withdraw, Borrow, Repay, and LiquidationCall events relevant to a triggered alert |
| LLM analytics         | Quantitative interpretation of triggered alerts using a local model                       |

### Utilization Monitoring

The monitor dynamically reads the reserve's interest-rate strategy rather than relying on a hardcoded optimal utilization value.

When utilization crosses the optimal point, the alert identifies whether the reserve has:

* Entered slope 2
* Returned to slope 1
* Increased or decreased its utilization relative to the kink
* Changed its borrowing conditions

This allows the monitor to detect meaningful changes in the reserve's liquidity and borrowing environment rather than simply reporting a raw utilization number.

---

## Event-Aware Alerts

A major part of the monitoring architecture is **on-demand event tracking**.

The monitor does **not** continuously index Aave events. Instead, event logs are queried only after a supply or utilization threshold has actually triggered.

For a triggered alert, the monitor examines the blocks since the previous monitoring pass and retrieves relevant:

* `Supply`
* `Withdraw`
* `Borrow`
* `Repay`
* `LiquidationCall`

events.

The alert then surfaces the largest relevant activity and, where applicable, liquidation context.

For example:

```text
Utilization crosses optimal

        |
        v

Query events since previous check

        |
        +--> Supply
        +--> Withdraw
        +--> Borrow
        +--> Repay
        +--> LiquidationCall

        |
        v

Rank relevant activity

        |
        v

Attach largest activity to alert
```

This provides useful context without requiring a continuously running indexer or third-party data provider.

### Why this approach?

Continuous event indexing would generate substantially more RPC traffic and infrastructure requirements.

Instead:

> **Metrics determine when something is interesting. Events explain what happened.**

This keeps the system lightweight enough to run continuously on a Raspberry Pi while still providing substantially more context than a simple threshold monitor.

---

## Local LLM Analytics

Triggered alerts can be passed to a locally hosted language model for an additional quantitative interpretation.

The current implementation uses:

**Qwen 2.5 1.5B via Ollama**

The model runs locally on the monitoring Raspberry Pi.

No external LLM API is required.

### What the LLM receives

The monitor constructs a structured context containing quantitative information such as:

* Chain
* Asset
* Current utilization
* Optimal utilization
* Distance from optimal utilization
* Total supply
* Total debt
* Debt-to-supply ratio
* Unused supply
* Borrow APY
* Supply APY
* Current interest-rate slope
* Direction of utilization crossing
* Relevant on-chain activity

The model is explicitly instructed to use only the supplied information.

### What the LLM does

The model produces a short analytical note focused on the strongest risk or liquidity implication supported by the data.

For example, an alert might contain:

```text
Insight: Utilization is 37.4 percentage points above the 45% optimal
level, leaving only 17.6% of supplied liquidity unused. At 31.2% borrow
APY, the reserve is already deep into slope 2, increasing the cost of
additional borrowing and leaving a relatively thin liquidity buffer.
```

The insight is deliberately constrained to avoid:

* Investment advice
* Price predictions
* Invented events
* Unsupported causal claims
* Generic commentary
* Claims of insolvency or imminent liquidation without evidence

If no relevant activity was found, the model is instructed not to invent a cause for the alert.

### Fail-safe behavior

The monitoring system does not depend on the LLM.

If Ollama is:

* unavailable
* still loading
* too slow
* returns an error
* returns an empty response

the underlying Aave alert is still sent.

The LLM simply contributes an optional `Insight` section.

---

## Architecture

The project is intentionally designed around a small, self-contained infrastructure footprint.

```text
Raspberry Pi 4B
8 GB RAM
32 GB microSD
        |
        +-----------------------------+
        |                             |
        v                             v
 Aave V3 Monitor                  Ollama
        |                             |
        |                             |
        +-------------+---------------+
                      |
                      v
                   Telegram
                      |
                      v
                 @AaveV3Risk
```

The monitor communicates directly with Aave V3 contracts through configured RPC endpoints.

There is:

* No Aave subgraph dependency
* No third-party indexing service
* No database requirement
* No external LLM API
* No requirement to run a blockchain node

The system persists only the state necessary to compare the current monitoring pass with the previous one.

---

## Project Structure

```text
.
├── main.py
├── constants.py
├── config.json
├── config.example.json
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
│
├── aave_monitor/
│   ├── app.py
│   ├── alerts.py
│   ├── asset_monitor.py
│   ├── chain_monitor.py
│   ├── charts.py
│   ├── config.py
│   ├── events.py
│   ├── formatting.py
│   ├── llm.py
│   ├── logging_setup.py
│   ├── pool_data.py
│   ├── rate_model.py
│   ├── reserve_config.py
│   ├── secrets_store.py
│   └── web3_client.py
│
├── scripts/
│   ├── setup.py
│   ├── update_secret.py
│   ├── migrate_secrets.py
│   └── help.py
│
└── data/
    └── state.json
```

### Core modules

| Module              | Responsibility                                      |
| ------------------- | --------------------------------------------------- |
| `asset_monitor.py`  | Per-reserve monitoring and threshold detection      |
| `chain_monitor.py`  | Multi-chain orchestration                           |
| `pool_data.py`      | Aave Pool reserve data                              |
| `events.py`         | On-demand event retrieval and decoding              |
| `rate_model.py`     | Interest-rate strategy discovery and analysis       |
| `reserve_config.py` | Reserve configuration decoding and change detection |
| `alerts.py`         | Telegram alert construction                         |
| `llm.py`            | Local Ollama inference and insight processing       |
| `charts.py`         | Interest-rate model change charts                   |
| `web3_client.py`    | RPC and contract interaction                        |
| `secrets_store.py`  | Encrypted secret storage                            |
| `config.py`         | Configuration loading and secret substitution       |

---

## Supported Monitoring Architecture

Each configured chain can define its own:

* RPC endpoint
* Aave V3 Pool
* Explorer
* Assets
* Supply-change thresholds
* Event query limits
* Block-range limits

This makes the monitor suitable for both established Aave deployments and newer markets.

The current project has been designed for multi-chain monitoring including deployments such as:

* Ethereum
* Plasma
* Arbitrum
* Base
* Monad

The actual chains and reserves monitored are controlled through configuration.

---

# Deployment

## Hardware

The current production deployment runs on:

**Raspberry Pi 4B — 8 GB RAM**

**Storage: 32 GB microSD**

This hardware is more than sufficient for the monitor itself.

The workload is primarily:

* RPC requests
* Small state reads/writes
* Occasional event-log queries
* Telegram API requests
* Local inference from a small language model

The 8 GB Pi also provides enough memory headroom for the local Qwen 2.5 1.5B model through Ollama.

A desktop environment is unnecessary.

---

## Raspberry Pi OS

For a headless deployment, use:

**Raspberry Pi OS Lite 64-bit**

64-bit is recommended because it provides the best compatibility with current ARM64 Docker images and local AI tooling.

Install Raspberry Pi OS using [Raspberry Pi Imager](https://www.raspberrypi.com/software/).

During imaging:

* Set a hostname
* Enable SSH
* Configure the user account
* Configure Wi-Fi if Ethernet is unavailable
* Prefer Ethernet for an always-on monitoring server

After boot:

```bash
ssh <user>@<hostname>

sudo apt update
sudo apt full-upgrade -y

sudo apt install -y git vim ufw
```

A headless monitoring host should generally expose only the services it actually needs.

---

# Docker Deployment

Docker is the preferred way to run the monitor.

Install Docker:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

sudo usermod -aG docker $USER
newgrp docker
```

Verify:

```bash
docker --version
docker compose version
```

Clone the repository:

```bash
git clone git@github.com:sebidelamata/lendingMarketsRiskMonitor.git
cd lendingMarketsRiskMonitor
```

Configure the application:

```bash
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

For a new installation:

```bash
python scripts/setup.py
```

Then start the monitor:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

Stop the service:

```bash
docker compose down
```

The monitor is configured to restart automatically after crashes and reboots.

---

# Ollama / Local Analytics

The LLM analytics layer is designed to run locally rather than through an external API.

Install Ollama on the Raspberry Pi and pull the configured model:

```bash
ollama pull qwen2.5:1.5b
```

Verify that Ollama is responding:

```bash
ollama list
```

The monitor communicates with the local Ollama API:

```text
http://127.0.0.1:11434
```

The model is only invoked after an alert has already fired.

### Important architectural principle

```text
Aave data
    |
    v
Deterministic monitoring logic
    |
    +---- no threshold ----> continue monitoring
    |
    +---- threshold --------> build alert
                              |
                              v
                         query events
                              |
                              v
                         LLM analysis
                              |
                              v
                         Telegram alert
```

The LLM is therefore an **analytics layer**, not part of the monitoring decision itself.

This prevents model latency, hallucinations, or model availability from affecting the actual alerting logic.

---

# Alert Design

Alerts are intentionally structured around quantitative information.

A utilization alert contains:

* Chain
* Asset
* Optimal utilization
* Current utilization
* Borrow APY
* Supply APY
* Slope direction
* Relevant activity
* Liquidation context where applicable
* Optional LLM insight

Supply alerts contain:

* Direction of supply change
* Percentage change
* Previous supply
* Current supply
* Relevant activity
* Liquidation context where applicable
* Resulting LLM analysis

The goal is to make the Telegram channel useful as a **real-time DeFi risk feed**, rather than simply a stream of raw contract events.

---

# Telegram

The public monitoring channel is:

**[@AaveV3Risk](https://t.me/AaveV3Risk)**

The intended use is as a lightweight real-time analytics feed for Aave V3 markets.

Alerts are designed to be:

* Concise
* Quantitative
* Event-aware
* Cross-chain
* Actionable as research signals
* Independent of third-party indexing infrastructure

---

# Secrets

Sensitive configuration is deliberately kept outside the Git repository.

The following files should never be committed:

```text
config.json
secret.key
secrets.enc.json
state.json
```

The repository should instead contain:

```text
config.example.json
```

as the safe configuration template.

## Encryption

The project uses `cryptography`'s Fernet encryption for secrets.

Fernet is appropriate here because the application needs to recover the original values at runtime.

The workflow is:

```text
                 config.json
                     |
                     v
             ${secret_placeholder}
                     |
                     v
                secret.key
                     |
                     v
             secrets.enc.json
                     |
                     v
                decrypt at
                   runtime
```

The plaintext secrets are not stored in `config.json`.

For example:

```json
{
  "telegram_bot_token": "${telegram_bot_token}",
  "telegram_chat_id": "${telegram_chat_id}"
}
```

At runtime, the placeholders are resolved in memory.

### Updating a secret

```bash
python scripts/update_secret.py telegram_bot_token
```

### Important

Back up `secret.key` somewhere secure outside the repository.

If the key is permanently lost, the encrypted secrets cannot be recovered.

This encryption protects against accidental repository commits and unauthorized access to the encrypted secret file. It is not intended to protect against root access or an attacker who can already read both the application and its key.

---

# Git / Development Workflow

The Pi can act as a normal development machine and push directly to the GitHub repository.

Configure Git once:

```bash
git config --global user.name "Sebi de la Mata"
git config --global user.email "your-email@example.com"
```

Then:

```bash
git status
git add .
git commit -m "describe change"
git push
```

The primary branch is:

```text
main
```

SSH authentication is recommended for the Pi.

Test it with:

```bash
ssh -T git@github.com
```

A successful authentication should report that GitHub has authenticated the account but does not provide shell access.

---

# State Management

The monitor maintains a local state snapshot so it can compare the current reserve state with the previous monitoring pass.

State includes information such as:

* Reserve configuration
* Above/below optimal utilization
* Previous utilization
* Optimal utilization
* Interest-rate strategy
* Total supply
* Stable debt
* Variable debt
* Total debt
* Last monitoring timestamp

`state.json` is intentionally excluded from Git.

This means each deployment maintains its own monitoring history.

---

# RPC Architecture

The monitor communicates directly with Aave contracts through Web3/RPC.

It does not require:

* A blockchain node
* A subgraph
* A centralized database
* A continuously running event indexer

Normal monitoring consists primarily of contract reads.

Event logs are requested only when a configured threshold fires.

This significantly reduces unnecessary RPC usage while preserving detailed context around meaningful market changes.

---

# Reliability Philosophy

The system follows a few important design principles.

### Deterministic alerting

Thresholds are evaluated using explicit quantitative rules.

The LLM cannot create or suppress an alert.

### Event queries are conditional

`eth_getLogs` is not continuously executed for every reserve.

Logs are queried only when an alert requires additional context.

### Graceful LLM failure

If Ollama fails or times out, the normal alert continues without the insight.

### Persistent state

Reserve snapshots survive process restarts through the persisted state file.

### Containerized runtime

Docker provides a reproducible runtime environment and isolates the monitoring service from the host Python environment.

### Local inference

The LLM runs locally on the Raspberry Pi, keeping inference costs at effectively zero beyond the hardware and electricity required to operate the device.

---

# Resource Footprint

The system is intentionally lightweight.

The core monitor primarily performs:

```text
RPC reads
    +
threshold calculations
    +
occasional event queries
    +
Telegram messages
```

The local LLM is the most resource-intensive component.

The Raspberry Pi 4B 8 GB provides enough memory for the current small Qwen model while leaving the monitoring service isolated from the inference workload.

Docker resource limits can also be used to prevent one component from starving another.

---

# Security Considerations

This project is designed as a personal/research monitoring service rather than a hardened production financial infrastructure system.

Recommended practices include:

* Keep the Raspberry Pi updated
* Use SSH keys where practical
* Disable unnecessary services
* Use a firewall
* Keep secrets outside Git
* Back up `secret.key`
* Do not expose Ollama's API publicly
* Do not expose Docker services unnecessarily
* Use dedicated RPC/API credentials where appropriate
* Monitor disk usage on the microSD card

The Telegram bot token should be treated as a credential and never committed to Git.

---

# Command Reference

| Command                                  | Purpose                                               |
| ---------------------------------------- | ----------------------------------------------------- |
| `python scripts/setup.py`                | Initial configuration and secret setup                |
| `python scripts/migrate_secrets.py`      | Encrypt secrets already present in a plaintext config |
| `python scripts/update_secret.py <name>` | Update or add a stored secret                         |
| `docker compose up -d --build`           | Build and start the monitor                           |
| `docker compose logs -f`                 | Follow monitor logs                                   |
| `docker compose down`                    | Stop the monitor                                      |
| `docker compose restart`                 | Restart the monitor                                   |
| `python main.py`                         | Run directly outside Docker                           |

---

# Current Architecture

The current system can be summarized as:

```text
                    AAVE V3
                      |
             Direct RPC Contract Reads
                      |
                      v
             Multi-Chain Monitor
                      |
       +--------------+--------------+
       |              |              |
       v              v              v
    Reserve       Utilization      Supply
    Config          / Rates        Changes
       |              |              |
       +--------------+--------------+
                      |
                      v
                Alert Trigger
                      |
                      v
              Relevant Events
                      |
          +-----------+-----------+
          |                       |
          v                       v
     Activity Context       Liquidation Context
          |                       |
          +-----------+-----------+
                      |
                      v
                Local Ollama
               Qwen 2.5 1.5B
                      |
                      v
              Quantitative Insight
                      |
                      v
                  Telegram
                      |
                      v
                @AaveV3Risk
```

---

# Roadmap

The core monitoring, event tracking, Docker deployment, and local LLM analytics pipeline are now implemented.

Potential future work includes:

* [ ] Historical metric storage
* [ ] Long-term reserve analytics
* [ ] Prometheus/Grafana integration
* [ ] Interactive reserve dashboards
* [ ] Additional Aave V3 deployments
* [ ] More sophisticated liquidation analytics
* [ ] Historical utilization and liquidity trend analysis
* [ ] Additional local models for specialized DeFi analysis
* [ ] Automated detection of unusual activity beyond fixed thresholds

---

# Project Philosophy

The project is built around a simple idea:

> **Monitor the numbers. Investigate the events. Explain the risk.**

A threshold alone tells you that something changed.

On-chain events provide evidence for what happened.

Quantitative analysis provides context for why the change matters.

Combining all three produces a more useful real-time view of Aave V3 risk than any individual layer can provide on its own.

---

## Author

**Sebi de la Mata**

DeFi researcher and developer.

* Telegram: [@AaveV3Risk](https://t.me/AaveV3Risk)
* X: [@Sebi_de_la_Mata](https://x.com/Sebi_de_la_Mata)
* Website: [sebidelamata.com](https://sebidelamata.com)

The project is maintained as an independent DeFi research and monitoring tool.
