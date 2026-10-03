# Design: two logins per database, admin actions with approval

**Status:** design for review, nothing built yet. Docker-only.

**Goal:** the agent can do admin work, such as checking a mounted Oracle standby,
restarting redo apply or killing a blocking session, without ever giving the model
admin power.

---

## 1. The idea in one picture

```
                                   ┌────────────── existing, unchanged ──────────────┐
 you ─► agent (CLI / web UI) ──MCP─┤ Toolboxes ─ READ-ONLY login ─► every database    │
         │                         └──────────────────────────────────────────────────┘
         │  model picks a tool from the question
         │
         │  admin tool?  ── checks (read-only SQL)  → run straight away
         │               └─ actions (change things) → STOP: show you the action → Approve / Cancel
         │
         └──MCP──► db-actions (ONE new container) ─ ADMIN login ─► Oracle standbys (as SYSDG)
                       fixed SQL only                             Oracle primary, Postgres,
                       holds the admin passwords                  MySQL, MariaDB
                       writes the audit log
```

There are two logins per database:

| Login | Who holds the password | Used for | SQL written by |
|---|---|---|---|
| **Read-only** (existing `agent_reader` / `C##AGENT_READER`) | the Toolbox containers | all diagnosis, including free-form SELECTs | the model, but the database enforces read-only |
| **Admin** (new, least-privilege) | `db-actions` only | fixed **checks** (where read-only can't reach, for example a mounted standby) and fixed **actions** | **us, in code.** The model only chooses the action and fills in checked parameters. |

**How the login is chosen: by the tool, never by the SQL text.** The model reads your
question and picks a tool, exactly as it does today. Each tool is hard-wired to one login,
so the model can't make admin SQL; it can only ask for an action that already exists.

---

## 2. Why not "look at the SQL and switch login"

SQL that looks read-only isn't always read-only in Oracle:

- `WITH FUNCTION … SELECT` runs PL/SQL, including `EXECUTE IMMEDIATE`, inside a SELECT.
- A function called from a SELECT can do DML in an autonomous transaction.
- `CALL`, anonymous blocks and `ALTER SESSION` are other ways in.

With the read-only login none of this matters, because the database refuses. With an
admin login, a single misjudged statement on production or DR has no safety net. So
the admin login never runs SQL the model wrote.

---

## 3. Components

### 3.1 Agent (`app/agent.py`, `app/app.py`): small changes

- It connects to **db-actions** as one more MCP server, the same way it connects to a Toolbox.
- **Approval** uses LangChain's built-in `HumanInTheLoopMiddleware`. Every **action**
  tool is listed in `interrupt_on`, with only *approve* and *reject* allowed (no editing
  of parameters). **Check** tools aren't listed, so they run without asking.
- When the model calls an action, the agent **pauses**, shows you the action card
  (section 5) and resumes only after your decision. Pausing needs a per-conversation
  memory (a LangGraph checkpointer, one thread per CLI session or browser session).
- **Model guard:** actions and checks on `oracle_prod` require an internal model,
  the same rule as today.
- The tools each database sees are the Toolbox tools plus that database's own checks
  and actions from db-actions, so the model never sees actions for other databases.

### 3.2 db-actions (new container, Python)

- A small **MCP server** written in Python (the official `mcp` SDK). It speaks the same
  protocol as Toolbox.
- **Drivers:**
  - `python-oracledb` for Oracle: `mode=oracledb.AUTH_MODE_SYSDG` for standbys, a normal
    login for primary actions.
  - `psycopg` for PostgreSQL.
  - `PyMySQL` for MySQL and MariaDB.
- **Configuration:** `config/actions.toml` lists the **targets** (each database or
  standby, its connect string, its login type, and the names of the environment
  variables holding user and password) and which actions are enabled for each target.
- **Every tool is a Python function with fixed SQL.** Parameters are validated (types,
  ranges, allow-lists) and passed as **bind variables**. Identifiers that can't be
  bound, such as a destination number or a table name, are checked against an allow-list
  or a strict pattern first.
- **Safety limits:**
  - a statement timeout on every call
  - one action per approval
  - a per-target switch to turn actions off: `actions_enabled = false` gives a
    "checks only" mode
- **Audit log** (`logs/actions.jsonl`, append-only) records:
  - who approved it (CLI user or web session)
  - when
  - the model that proposed it
  - your question
  - the action, its parameters and the exact SQL that ran
  - the result or the error
- **Secrets:** admin passwords are only in this container's environment, from `.env`
  variables named `ADMIN_*`. The agent, the web UI and the model never receive them.
- It listens on `127.0.0.1:5005` (and on the internal Docker network), like the Toolboxes.

### 3.3 Toolboxes: no change

They keep the read-only logins and serve all diagnosis. No extra Toolboxes.

---

## 4. Proposed first catalogue

The first version would be a pick from this list. **C** = check (no approval),
**A** = action (approval required).

### Oracle standby: login `C##AGENT_DG` **as SYSDG** (works on a mounted standby)

| Tool | Type | Fixed SQL (summary) |
|---|---|---|
| `standby_status` | C | `v$database` (role, open_mode); `v$dataguard_stats` (transport lag, apply lag, apply finish time); `v$dataguard_process` (MRP/RFS: action, thread, sequence) |
| `standby_gaps` | C | `v$archive_gap`; last received vs applied sequence per thread (`v$archived_log`) |
| `standby_recent_errors` | C | Last ORA- lines from the standby alert log (`v$diag_alert_ext`, last N hours) |
| `start_apply` | A | `ALTER DATABASE RECOVER MANAGED STANDBY DATABASE DISCONNECT FROM SESSION` |
| `stop_apply` | A | `ALTER DATABASE RECOVER MANAGED STANDBY DATABASE CANCEL` |

### Oracle primary: login `C##AGENT_OPS` (normal login, grants `CREATE SESSION` + `ALTER SYSTEM`)

| Tool | Type | Fixed SQL |
|---|---|---|
| `set_dest_state` | A | `ALTER SYSTEM SET log_archive_dest_state_<n> = ENABLE \| DEFER SCOPE=BOTH SID='*'` (`n` 2-31, must be an active standby destination) |
| `kill_session` | A | `ALTER SYSTEM KILL SESSION '<sid>,<serial#>,@<inst>' IMMEDIATE` (numbers only; refused for background sessions and for the agent's own sessions) |

### PostgreSQL: login `agent_ops` (role `pg_signal_backend`)

| Tool | Type | Fixed SQL |
|---|---|---|
| `cancel_query` | A | `SELECT pg_cancel_backend(%s)` (pid) |
| `terminate_session` | A | `SELECT pg_terminate_backend(%s)` (pid; refused for superuser sessions) |

### MySQL / MariaDB: login `agent_ops` (`CONNECTION_ADMIN` on MySQL; `CONNECTION ADMIN` on MariaDB 10.5+)

| Tool | Type | Fixed SQL |
|---|---|---|
| `kill_query` | A | `KILL QUERY <id>` (integer only) |
| `kill_connection` | A | `KILL <id>` (integer only) |

### Later, if wanted

| Tool | Notes |
|---|---|
| `gather_table_stats` (Oracle), `analyze_table` (all engines) | Allow-listed schemas and tables only |
| `register_logfile` (Oracle standby) | File path restricted to the archive destination folder |
| `switch_logfile` (Oracle primary) | `ALTER SYSTEM ARCHIVE LOG CURRENT`, often used to resolve a transport hiccup |

**Not in scope, ever, through this agent:** switchover, failover, shutdown or startup,
dropping anything, changing users, passwords or parameters other than the ones above,
and free-form SQL with the admin login.

---

## 5. The approval step

**Web UI:** the answer pauses and shows a card:

```
⚠️  Action proposed: start_apply on standby STBY2 (Oracle, login C##AGENT_DG as SYSDG)
    Why: dg_health_check → dest 3 recovery_mode = IDLE; standby_status → no MRP process
    SQL: ALTER DATABASE RECOVER MANAGED STANDBY DATABASE DISCONNECT FROM SESSION
    Model: gpt-oss-120b
    [ Approve ]   [ Cancel ]
```

**CLI:**

```
Action proposed: start_apply on standby STBY2 ... (same details)
Approve? Type 'yes' to run, anything else to cancel:
```

After **Approve**, db-actions runs the fixed SQL with the admin login, writes the audit
line, and returns the result. The agent then re-runs the matching check, for example
`standby_status`, and tells you whether it worked. **Cancel** tells the model the action
was declined, and it answers without it.

---

## 6. End-to-end example

```
You:   is standby 2 in sync?
Agent: dg_health_check        (Toolbox, primary, read-only)  → dest 3 IDLE, apply lag 47 min
       standby_status STBY2   (db-actions, SYSDG, check)     → no MRP process; transport lag 0
       standby_recent_errors  (db-actions, SYSDG, check)     → ORA-00313 at 14:02 (log member missing)
       → Explains: transport is fine, apply stopped at 14:02 because of ORA-00313.
         Recommends fixing the missing standby redo log member first.
         Proposes start_apply once that's fixed.     [ Approve ] [ Cancel ]
```

---

## 7. Users and setup

| Database | Admin user | Privileges | Notes |
|---|---|---|---|
| Oracle (primary + standbys) | `C##AGENT_DG` | `SYSDG` (administrative privilege) | Create on the primary. The **password file** must reach the standbys (copy `orapw<SID>` to each standby after the grant), otherwise SYSDG logins fail there |
| Oracle primary | `C##AGENT_OPS` | `CREATE SESSION`, `ALTER SYSTEM` | ALTER SYSTEM is powerful. It's only safe because the SQL is fixed in db-actions |
| PostgreSQL | `agent_ops` | `pg_signal_backend` | Can't signal superuser sessions (by design) |
| MySQL | `agent_ops` | `CONNECTION_ADMIN` | No SUPER |
| MariaDB | `agent_ops` | `CONNECTION ADMIN` | |

Creation scripts would be supplied per engine, like `db/oracle-prod/`.

---

## 8. Configuration sketch

`config/actions.toml`:

```toml
[[target]]
key = "stby1"                       # name used in questions and on the action card
database = "oracle_prod"            # which agent database it belongs to
engine = "oracle"
dsn = "${ADMIN_STBY1_DSN}"          # e.g. stby1-host:1521/STBY1
login = "sysdg"                     # sysdg | normal
user = "${ADMIN_ORACLE_DG_USER}"
password = "${ADMIN_ORACLE_DG_PASSWORD}"
checks = ["standby_status", "standby_gaps", "standby_recent_errors"]
actions = ["start_apply", "stop_apply"]

[[target]]
key = "prod_primary"
database = "oracle_prod"
engine = "oracle"
dsn = "${ORACLE_PROD_CONNECTION_STRING}"
login = "normal"
user = "${ADMIN_ORACLE_OPS_USER}"
password = "${ADMIN_ORACLE_OPS_PASSWORD}"
actions = ["set_dest_state", "kill_session"]
```

`docker-compose.yml` gets one service, `db-actions` (profile `actions`, port `127.0.0.1:5005`),
which receives only the `ADMIN_*` variables.

---

## 9. Safety layers, summed up

1. **The model can't write admin SQL:** fixed SQL in code, validated parameters, bind variables.
2. **A human approves every change:** the approval card shows the exact SQL first.
3. **Least privilege:** SYSDG instead of SYS, `pg_signal_backend` instead of superuser, no MySQL SUPER.
4. **Passwords are isolated:** admin passwords live only in db-actions.
5. **Internal models only** for production targets.
6. **Audit log** of every action, including cancelled ones.
7. **Kill switch:** `actions_enabled = false` per target, or stop the `db-actions` container.

---

## 10. Testing plan (homelab)

1. Create the users; confirm a `C##AGENT_DG` SYSDG login works on the **mounted** standby
   from the db-actions container. If python-oracledb's default (Thin) mode can't make
   the SYSDG login to a mounted standby, switch the container to Thick mode with Oracle
   Instant Client.
2. Checks: compare `standby_status` with `v$dataguard_stats` run by hand.
3. Actions: stop apply by hand, then ask the agent. Expect a CRITICAL verdict, a proposed
   `start_apply`, Approve, `MANAGED REAL TIME APPLY`, and an audit line.
4. Cancel path: a proposal you cancel must not run (check the audit log and `v$dataguard_process`).
5. Guard: switch to an external model and ask the same question. Prod checks and actions
   must be blocked.

---

## 11. Decisions needed before building

| # | Decision | Default if you have no preference |
|---|---|---|
| 1 | First catalogue (section 4) | Oracle standby checks + `start_apply`/`stop_apply` + `kill_session` on all engines |
| 2 | Admin users | Dedicated least-privilege users (section 7) |
| 3 | Approval | Both: web UI buttons and `yes` in the CLI |
| 4 | Audit log location | `logs/actions.jsonl` on the Docker host |
