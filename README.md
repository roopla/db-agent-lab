# db-agent: ask your databases in plain English

> **New here? Follow [SETUP.md](SETUP.md)** (or open `SETUP.html` in a browser): step-by-step
> from an empty VM (VirtualBox home lab or cloud) to a working agent.
> **Diagrams and workflows:** open `ARCHITECTURE.html`.
> **Let Claude Code deploy it:** after installing Docker and loading the Oracle image, run
> Claude Code in this folder and say *"Deploy and verify this project following CLAUDE.md."*

![Architecture](docs/architecture.png)

LangChain agent + MCP Toolbox over **PostgreSQL, MySQL, MariaDB** (demo data) and an
**Oracle 19c Data Guard lab** (primary + physical standby, built by Docker Compose).
You choose one database at a time; the agent turns your question into read-only
queries (or uses ready-made DBA tools) and answers in plain English.

```
you ──► agent (uv, LangChain + OpenAI-compatible model) ──► MCP Toolbox ──► database (read-only login)
                                                             one per database
```

| key         | Database                      | Data                                              | DB port | Toolbox |
|-------------|-------------------------------|---------------------------------------------------|---------|---------|
| postgres    | PostgreSQL 16                 | shop: customers, products, orders, order_items    | 5432    | 5000    |
| mysql       | MySQL 8.4                     | inventory: suppliers, warehouses, purchase_orders | 3306    | 5001    |
| mariadb     | MariaDB 11.4                  | support: support_agents, tickets                  | 3307    | 5002    |
| oracle_prod | Oracle 19c primary + standby  | Data Guard, performance, space, FRA, RMAN (30 tools) | 1531 / 1532 | 5004 |

All ports are bound to 127.0.0.1 only.

## Requirements
- Linux x86-64 with Docker + Docker Compose v2.20+, and `uv`
- 16 GB RAM, 4 vCPU, 100 GB disk (the Oracle pair uses ~6 GB RAM; without it, 2 GB is enough)
- The Oracle image `oracle/database:19.3.0-ee-ext` loaded on the machine (SETUP.md section 5)
- An OpenAI API key, or an OpenAI-compatible gateway (e.g. Open WebUI)

## Setup
```bash
unzip db-agent-docker.zip && cd db-agent
bash scripts/make-env.sh          # creates .env with random passwords
nano .env                         # set OPENAI_API_KEY (lab + OpenAI: uncomment ALLOW_EXTERNAL_MODELS_FOR)
uv sync                           # installs Python + libraries into .venv
docker compose up -d              # 3 demo DBs, Oracle primary + standby, 4 Toolbox servers
docker compose logs -f oracle-standby             # first run: wait for STANDBY IS READY TO USE! (30-70 min)
uv run --env-file .env python scripts/check.py   # all 4 should say OK
uv run --env-file .env python app/agent.py       # start chatting
```

## Using it
Terminal: pick a database from the menu, then ask (try `Is Data Guard healthy?` on
`oracle_prod`). Commands:

| Command | Does |
|---|---|
| `use mysql` | switch database (fresh conversation) |
| `@oracle_prod <question>` | ask another database once, without switching |
| `dbs` | list databases and their status |
| `tools` | list the current database's tools |
| `models` / `model <n or id>` | list models / switch model |
| `quit` | leave |

Web UI (on the server): `uv run --env-file .env streamlit run app/app.py`,
then from your laptop: `ssh -L 8501:localhost:8501 <user>@<server>` and open
http://localhost:8501.

## Safety
Every database has a read-only login (`agent_reader`; Oracle `C##AGENT_READER` with
`SELECT_CATALOG_ROLE`). Writes are refused by the database itself. `oracle_prod` refuses
external models unless you allow it for the lab.

## Files
```
docker-compose.yml           demo DBs + Oracle primary/standby + 4 Toolbox servers
.env.example                 settings template (scripts/make-env.sh fills it in)
app/agent.py                 the agent (terminal chat)
app/app.py                   web UI
app/databases.toml           which databases exist; 'about' and 'notes' guide the agent
config/postgres-custom.yaml  custom Postgres tools (+ all prebuilt ones)
config/oracle-prod.yaml      the 30 Oracle tools
db/<engine>/init/            demo data + read-only login (run once, on first start)
db/oracle-lab/               builds the Data Guard primary + standby
db/oracle-prod/              read-only login scripts for a REAL primary
scripts/make-env.sh          generates .env
scripts/check.py             checks every Toolbox is reachable (no model calls)
ARCHITECTURE.html            diagrams: architecture, question flow, Data Guard build, redo flow
ORACLE-LAB.md / ORACLE-PROD.md / ADMIN-ACTIONS-DESIGN.md   Oracle guides
```

## Troubleshooting
| Symptom | Check |
|---|---|
| A database is not (healthy) | `docker compose logs <service> \| tail -30` |
| A toolbox keeps restarting | `docker compose logs toolbox-<db> \| tail -20` (oracle: normal until the primary is open) |
| check.py says FAIL | the toolbox for that database isn't up yet, or its login failed |
| Oracle standby not ready | `ORACLE-LAB.md`, Troubleshooting |
| Changed passwords after first start | reset that database (SETUP.md section 12) |
| Port already in use | another stack is running; stop it with `docker compose down` in its folder |

## Adding a real database
1. Create a read-only login on it (copy the grants from `db/<engine>/init/`, or `db/oracle-prod/`).
2. Add a Toolbox service in `docker-compose.yml` on a free port, pointing at it.
3. Add a `[[database]]` block to `app/databases.toml`.
4. `docker compose up -d`, then run `scripts/check.py`.
