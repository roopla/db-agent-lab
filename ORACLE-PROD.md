# oracle_prod: performance and Data Guard tools for your real Oracle 19c

The agent's Oracle entry is **`oracle_prod`**. It points at an **Oracle 19c primary** (your
real one, or the Data Guard lab from `ORACLE-LAB.md`) and comes with 30 read-only tools for:

- **Data Guard:** sync, lag and archive gaps.
- **Live performance:** waits, top SQL, blocking sessions and execution plans.
- **Space:** tablespaces, temp, undo, the Fast Recovery Area (FRA) and RMAN backups.

When it finds a problem, the agent tells you the cause, shows the evidence, and gives
the exact commands for a DBA to run. It never runs them itself. That's phase 1.
Approved actions (click to approve) come in phase 2.

**For a real primary, no database is created.** The only piece is an **MCP Toolbox container**
that connects out to your primary with a read-only login. (For the home lab, `ORACLE-LAB.md`
builds a primary and standby in Docker and points this Toolbox at it; sections 3-5 below are
then done for you.)

---

## Contents

1. [How it fits](#1-how-it-fits)
2. [What it can and cannot see](#2-what-it-can-and-cannot-see)
3. [Before you start](#3-before-you-start)
4. [Create the read-only login](#4-create-the-read-only-login)
5. [Switch it on](#5-switch-it-on)
6. [Use it](#6-use-it)
7. [The 30 tools](#7-the-30-tools)
8. [How Data Guard is diagnosed from the primary](#8-how-data-guard-is-diagnosed-from-the-primary)
9. [Recommended actions: what the agent will and won't do](#9-recommended-actions-what-the-agent-will-and-wont-do)
10. [Test plan](#10-test-plan)
11. [Troubleshooting](#11-troubleshooting)
12. [Files](#12-files)
13. [Next: approved actions (phase 2)](#13-next-approved-actions-phase-2)

---

## 1. How it fits

```
              ┌─────────────── your machine (Docker Compose) ───────────────┐
 you ──► app ─┤► toolbox-oracle-prod  ─────────────────────────────────────────┼──► Oracle 19c PRIMARY
 (CLI or web) │   (127.0.0.1:5004)                                           │     (read-only login, port 1521)
              └──────────────────────────────────────────────────────────────┘     lab: oracle-primary container
                                                                                       │ redo
                                                                                       ▼
                                                                         physical standby(s), MOUNTED
                                                                         (state reported by the primary)
```

| Piece | What it is |
|---|---|
| `config/oracle-prod.yaml` | The 30 tools (SQL) and the connection settings |
| `toolbox-oracle-prod` (Compose service) | Toolbox server on `127.0.0.1:5004`. Only starts with the `oracle-prod` profile. |
| `oracle_prod` in `app/databases.toml` | The menu entry, plus the diagnosis rules the agent follows |
| `db/oracle-prod/*.sql` | Scripts that create and verify the read-only login |

Full picture of the whole stack: `ARCHITECTURE.html`.

---

## 2. What it can and cannot see

Your standbys are **mounted**. A mounted database only accepts SYSDBA or SYSDG logins,
and Toolbox can't use those. So **every tool runs on the primary**, which already tracks
each standby destination.

| Can see (from the primary) | Cannot see (needs a login on the standby) |
|---|---|
| Whether redo is shipping to each standby, and any transport error | The standby's own `V$DATAGUARD_STATS` (exact transport and apply lag) |
| Archive gap status, and which log sequences are missing | `V$DATAGUARD_PROCESS` / MRP process details |
| Whether redo apply is running on the standby (`RECOVERY_MODE`: `IDLE` = MRP stopped) | The standby's alert log, i.e. *why* MRP stopped |
| Last SCN the standby has applied, giving apply lag in minutes | Standby FRA and space |
| Last archived vs applied sequence, per RAC thread | |
| Data Guard messages, parameters, standby redo log setup, redo rate | |
| Performance, space, FRA and RMAN on the primary, all instances and PDBs | Performance on the standby |

For "MRP stopped", the agent can tell you *that* it stopped and give the commands to
investigate and restart. Finding *why* means looking at the standby, and that's still
your job in phase 1.

---

## 3. Before you start

| Need | Check |
|---|---|
| The machine running the agent can reach the primary's listener | `timeout 5 bash -c '</dev/tcp/<primary-host-or-scan>/1521' && echo reachable` |
| The project already runs with Docker Compose on that machine | `docker compose ps` shows the toolboxes |
| Whether the primary is a CDB (multitenant) or non-CDB | as a DBA: `SELECT cdb FROM v$database;` |
| The service name to connect to | CDB: the **root** service (often the DB_UNIQUE_NAME). Non-CDB: the database service. RAC: use the SCAN name. |
| Diagnostics Pack licence | Required for `perf_ash_*`, `perf_sql_plan_awr` and `perf_sql_plan_history`. You confirmed you have it. |

The GKE playground can't reach your company network. Run this on a machine inside your
network, such as your dev host.

---

## 4. Create the read-only login

A DBA runs one script on the **primary**. The user and grants reach the standbys
automatically through redo.

**CDB (multitenant), connected to CDB$ROOT:**

```bash
sqlplus / as sysdba @db/oracle-prod/create-agent-reader-cdb.sql
```

It asks for a password, then creates `C##AGENT_READER` with:

- `CREATE SESSION`
- `SELECT_CATALOG_ROLE`, which gives read access to the data dictionary, `V$`/`GV$`,
  `DBA_`/`CDB_` and `DBA_HIST` views. It gives **no** access to application tables.
- `CONTAINER_DATA=ALL`. Without this, sessions, SQL and ASH queried from the root would
  hide everything happening inside the PDBs.

**Non-CDB:**

```bash
sqlplus / as sysdba @db/oracle-prod/create-agent-reader-noncdb.sql
```

This creates `AGENT_READER` with the same two grants.

Put the account on a profile your security team approves, so its password doesn't
expire one day and silently break the agent.

**Verify, as the new user, ideally from the agent's machine:**

```bash
sqlplus 'c##agent_reader@//<host-or-scan>:1521/<service>' @db/oracle-prod/verify-agent-reader.sql
```

Every line should show a value. At the end there's a write test, which **must fail**
with `ORA-01031: insufficient privileges`.

---

## 5. Switch it on

**1. Fill in `.env`.** These lines are already in `.env.example`:

```bash
ORACLE_PROD_CONNECTION_STRING=dbprod-scan.example.com:1521/PRODCDB
ORACLE_PROD_USERNAME=C##AGENT_READER
ORACLE_PROD_PASSWORD=<the password you chose>
COMPOSE_PROFILES=oracle-prod
```

`COMPOSE_PROFILES=oracle-prod` makes `docker compose up` include the Toolbox. Drop
`oracle-lab` from it when you point at a real primary, so the lab databases don't start.

**2. Start it:**

```bash
docker compose up -d toolbox-oracle-prod
docker compose logs --tail 20 toolbox-oracle-prod
```

**You should see:** the Toolbox start-up lines and *no* `ORA-` errors. Toolbox
connects to the database as it starts, so a wrong host, service or password shows up
here straight away.

**3. Check:**

```bash
uv run --env-file .env python scripts/check.py
```

**You should see:** `OK    oracle_prod  30 tools  http://127.0.0.1:5004` and `4/4 databases reachable.`

To switch it off again: `docker compose stop toolbox-oracle-prod`, then empty
`ORACLE_PROD_CONNECTION_STRING`. The menu entry only appears when that variable is set.

---

## 6. Use it

**Model rule:** `oracle_prod` only runs with an **internal** model (your in-house gateway, not
OpenAI and not `internet/…` / `zcloud/…` connections). With an external model the agent answers
"Blocked: …" and the web UI disables the question box. For a homelab Data Guard pair with OpenAI,
set `ALLOW_EXTERNAL_MODELS_FOR=oracle_prod` in `.env` (lab only). See SETUP.md section 11a.

Terminal:

```bash
uv run --env-file .env python app/agent.py      # then pick oracle_prod, or type: use oracle_prod
```

Web UI: pick **Oracle PROD (primary + Data Guard)** in the sidebar.

Questions to start with:

| Ask | What the agent does |
|---|---|
| "Is Data Guard healthy?" / "Is the standby in sync?" | `dg_health_check`, then explains each verdict |
| "Why is the standby lagging?" | `dg_health_check` → `dg_apply_progress` → `dg_redo_rate` / `dg_destinations` |
| "Do we have an archive gap?" | `dg_health_check` → `dg_missing_logs` |
| "Is redo apply running?" | `dg_health_check` (`recovery_mode`) |
| "Why is the database slow right now?" | `perf_load_profile`, `perf_waits_now` or `perf_ash_top_events` → `perf_ash_top_sql` |
| "What was slow in the last 30 minutes?" | `perf_ash_top_events(30)`, `perf_ash_top_sql(30)` |
| "Who is blocking whom?" | `perf_blocking_sessions` |
| "Explain sql_id 7h35uxf5uhmm1" / "Did its plan change?" | `perf_sql_details`, `perf_sql_plan`, `perf_sql_plan_history` |
| "Which tablespaces are nearly full?" | `space_tablespaces` |
| "Is the FRA filling up, and why?" | `space_fra_usage`, `space_rman_config`, `space_recent_backups` |
| "Any ORA-01555 errors today?" | `space_undo` |

In the CLI, type `tools` to list all 30 tools.

---

## 7. The 30 tools

**General**

| Tool | Parameters | What it returns |
|---|---|---|
| `database_overview` | – | Role (PRIMARY), open mode, protection mode and level, switchover status, force logging, flashback, CDB, current SCN, every RAC instance |
| `execute_sql` | (SQL) | Any read-only SELECT, used when no dedicated tool fits |
| `list_invalid_objects` | – | INVALID objects in all PDBs, excluding Oracle-maintained schemas |
| `list_active_sessions` | – | Active user sessions, all instances and PDBs |

**Data Guard**

| Tool | Parameters | What it returns |
|---|---|---|
| `dg_health_check` | warn_lag_minutes=10 | **Start here.** One row per standby (and per RAC instance), with a verdict (OK / WARNING / CRITICAL / UNKNOWN), apply lag in minutes, gap status, apply mode and transport error |
| `dg_destinations` | – | Transport settings and state: SYNC/ASYNC, AFFIRM, NET_TIMEOUT, REOPEN, DELAY, VALID_FOR, failure count and last failure, error, SRL use |
| `dg_apply_progress` | – | Per standby and RAC thread: last archived, received and applied sequence, logs not received or not applied (NULL = no record) |
| `dg_missing_logs` | dest_id | Log sequences the standby hasn't received above its applied point, and whether each file is still on disk on the primary |
| `dg_messages` | errors_only=N | Recent `GV$DATAGUARD_STATUS` messages, newest first |
| `dg_standby_redo_logs` | – | Online vs standby redo log groups and sizes per thread |
| `dg_parameters` | – | log_archive_config, log_archive_dest_n, non-ENABLE dest states, fal_server, standby_file_management, name conversions, FRA, … |
| `dg_redo_rate` | hours=24 | Redo MB and log switches per hour |

**Performance** (GV$, all RAC instances; ASH and AWR tools need the Diagnostics Pack)

| Tool | Parameters | What it returns |
|---|---|---|
| `perf_load_profile` | – | Last-minute metrics per instance: host CPU, average active sessions, CPU/wait ratio, executions, transactions, hard parses, logons, redo and I/O throughput |
| `perf_waits_now` | – | Active sessions right now, grouped by wait class and event |
| `perf_ash_top_events` | minutes=15 | Share of DB time per event over the window (ASH) |
| `perf_ash_top_sql` | minutes=15 | Top SQL by DB time over the window, with main event, user, PDB and text (ASH) |
| `perf_blocking_sessions` | – | Blocked sessions and their blockers (who, what, how long) |
| `perf_long_running_sql` | min_seconds=60 | Calls running longer than N seconds right now |
| `perf_longops` | – | Long operations with percent done and time remaining |
| `perf_top_sql` | metric, limit=10 | Top shared-pool SQL by elapsed time, CPU, reads, gets or executions, with per-execution averages |
| `perf_sql_details` | sql_id | Child cursors, plan hash, per-execution stats, profile or baseline, full text |
| `perf_sql_plan` | sql_id | Cached plan(s) via `DBMS_XPLAN.DISPLAY_CURSOR`, on the connected instance |
| `perf_sql_plan_awr` | sql_id | Plans captured in AWR (`DISPLAY_WORKLOAD_REPOSITORY`) |
| `perf_sql_plan_history` | sql_id | Plan hash values over time, with ms and buffer gets per execution, to spot plan regressions |

**Space**

| Tool | Parameters | What it returns |
|---|---|---|
| `space_tablespaces` | – | Used vs **max** size (autoextend included), every PDB, fullest first |
| `space_temp_usage` | – | Temp totals per PDB and the top 20 temp-using sessions |
| `space_undo` | hours=24 | Longest query, tuned retention, ORA-01555 and undo-space errors per hour |
| `space_fra_usage` | – | FRA limit, used, reclaimable and effective %, by file type |
| `space_rman_config` | – | Non-default RMAN settings, including the archivelog deletion policy |
| `space_recent_backups` | days=3 | RMAN jobs with status, duration and size |

---

## 8. How Data Guard is diagnosed from the primary

`dg_health_check` reads `GV$ARCHIVE_DEST` and `GV$ARCHIVE_DEST_STATUS` for every
active standby destination (`TARGET='STANDBY'`, `VALID_NOW='YES'`). It then applies
these checks in order and stops at the first match:

| # | Condition (columns) | Verdict | What it means |
|---|---|---|---|
| 1 | `STATUS = 'DEFERRED'` | WARNING | Someone set `log_archive_dest_state_N=DEFER`, so redo isn't shipped |
| 2 | `STATUS <> 'VALID'` or `ERROR` not empty | CRITICAL | Transport is failing: network, listener, standby down, password file, standby FRA full |
| 3 | `GAP_STATUS` like `%UNRESOLVABLE%` | CRITICAL | Logs are missing that FAL can't fetch automatically |
| 4 | `RECOVERY_MODE = 'IDLE'` | CRITICAL | Redo apply (MRP) isn't running on the standby |
| 5 | Applied SCN older than one day (no apply delay configured) | CRITICAL | The standby hasn't applied anything for over a day |
| 6 | `GAP_STATUS = 'RESOLVABLE GAP'` | WARNING | A gap that FAL should close by itself. Re-check in a few minutes. |
| 7 | `APPLIED_SCN = 0` | UNKNOWN | The primary has no applied-SCN information for this destination |
| 8 | Apply lag > `warn_lag_minutes` | WARNING | Applying, but behind |
| 9 | `RECOVERY_MODE` not real-time apply (no delay configured) | WARNING | Applying from archived logs only. Usually missing standby redo logs (SRLs). |
| – | none of the above | OK | |

**Apply lag** is `SYSDATE − SCN_TO_TIMESTAMP(V$ARCHIVE_DEST.APPLIED_SCN)`: how old the
last change the standby has applied is. Three caveats:

- **On a primary that has generated no redo for a while**, this overstates the lag,
  because the last applied change *is* old. `logs_behind` and `dg_redo_rate` tell the
  two cases apart, and the agent is told to check them.
- `SCN_TO_TIMESTAMP` is accurate to a few seconds.
- The query only converts SCNs from the last day. Anything older is reported as
  "more than a day" (check 5).

**RAC:** transport is per instance, so each standby appears once per primary instance.
A problem on one instance only, such as one thread's archiver, shows up on that row.

**`dg_apply_progress` and `dg_missing_logs`** use the primary's archived-log records,
limited to the last 14 days. Oracle documents the `APPLIED` flag mainly for the standby
side, so treat these as **best effort**. NULL means "no record", never "zero". The
SCN-based lag in `dg_health_check` is the more reliable number.

---

## 9. Recommended actions: what the agent will and won't do

**It will:**

- explain the problem with evidence: which tool, which column, which value
- end with **"Recommended actions (run these yourself)"**. For each command it says
  *where* to run it (primary or standby), *as whom* (SYSDBA, SYSDG or DBA), *why*, and
  *how to verify*.
- mark destructive commands (KILL SESSION, RMAN DELETE, resizing) as **DESTRUCTIVE**,
  with what to check first

**It won't:**

- run any command (its login can't)
- claim it fixed anything
- change data, even if asked: it answers in one sentence that it's read-only

Example of the kind of answer you should get, for "is the standby in sync?" when MRP has
stopped:

> **Verdict: CRITICAL.** Redo apply is not running on standby `PRODSBY`
> (dest 2, `recovery_mode = IDLE`). Transport is fine: status VALID, no error, no gap.
> The standby is receiving redo but not applying it. Last applied SCN is about 47 minutes old.
>
> **Recommended actions (run these yourself)**
> 1. On the **standby**, as SYSDBA or SYSDG, find out why apply stopped: check the alert
>    log for ORA- errors around the time apply stopped, and run
>    `SELECT name, role, action, thread#, sequence# FROM v$dataguard_process;`
> 2. Once the cause is fixed, start apply on the **standby**:
>    `ALTER DATABASE RECOVER MANAGED STANDBY DATABASE DISCONNECT FROM SESSION;`
> 3. Verify on the standby: `SELECT name, value FROM v$dataguard_stats WHERE name IN ('transport lag','apply lag');`
>    then ask me "is Data Guard healthy?" again. Expect `MANAGED REAL TIME APPLY`.

The rules behind this are the `notes` of `oracle_prod` in `app/databases.toml`. Edit
them to match your team's runbook, for example your naming, who to page, or extra
checks. The agent follows them on its next start.

---

## 10. Test plan

The demo Oracle container can't run Data Guard, so these tools were checked in four ways:

- every statement was parsed as Oracle SQL
- every bind and parameter was checked
- view and column names were reviewed against the Oracle 19c Reference
- Toolbox's parameter handling was checked in its source code

**They haven't run against a live Data Guard pair yet.** Test them in this order:

| Step | Do | Expect |
|---|---|---|
| 1 | `verify-agent-reader.sql` as the new user | All values filled in; the write test fails with ORA-01031 |
| 2 | `check.py` | `oracle_prod 30 tools` |
| 3 | CLI: `use oracle_prod`, then `tools` | 30 tools listed |
| 4 | Ask for each tool once ("run dg_health_check", "run perf_load_profile", …) | No ORA- errors. Note any tool that errors and send me the message. |
| 5 | Compare `dg_health_check` with the standby itself (`v$dataguard_stats` as SYSDBA) | Apply lag within a minute or so; `recovery_mode` matches whether MRP runs |
| 6 | **On a non-production pair only:** stop apply on the standby (`… RECOVER MANAGED STANDBY DATABASE CANCEL;`), wait 1–2 minutes, ask "is Data Guard healthy?" | CRITICAL, apply not running, plus the restart command. Then restart apply. |
| 7 | **Non-production only:** `ALTER SYSTEM SET log_archive_dest_state_2=DEFER;`, then ask | WARNING, DEFERRED, plus the ENABLE command. Then re-enable it. |
| 8 | Performance: run a known slow query in a test PDB, ask "what is slow right now?" | It finds the sql_id and shows its plan |

Step 4 is the important one. Any tool with a wrong column name for your exact patch
level fails cleanly with an ORA- error, and it's a one-line fix in `config/oracle-prod.yaml`.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `toolbox-oracle-prod` keeps restarting; log shows `ORA-12514` / `ORA-12541` / timeout | Wrong host, port or service name, or a firewall | Test with `sqlplus user@//host:1521/service` from the same machine. Use the SCAN name on RAC. |
| Log shows `ORA-01017` | Wrong user or password, or a case-sensitive password | Check `.env`. Common user names start with `C##`. |
| Log shows `ORA-28001` (password expired) | Profile expired the password | Reset it; put the user on a non-expiring monitoring profile |
| `oracle_prod` missing from the menu | `ORACLE_PROD_CONNECTION_STRING` empty, or the agent was started without `--env-file .env` | Fill it in; start with `uv run --env-file .env …` |
| `check.py`: FAIL oracle_prod, connection refused | The Toolbox isn't running | `COMPOSE_PROFILES=oracle-prod` in `.env`, then `docker compose up -d toolbox-oracle-prod` |
| A tool returns `ORA-00942: table or view does not exist` | Missing grant | Make sure `SELECT_CATALOG_ROLE` was granted (`CONTAINER=ALL` on a CDB) |
| Sessions, SQL or ASH show nothing from the PDBs | `CONTAINER_DATA` not set | `ALTER USER c##agent_reader SET CONTAINER_DATA=ALL CONTAINER=CURRENT;` in CDB$ROOT |
| `perf_sql_plan`: "cannot find cursor" | Statement aged out, or it's cached on another RAC instance | Use `perf_sql_plan_awr` |
| `dg_health_check` returns no rows | No active standby destinations, or connected to a **standby** | `database_overview` should say PRIMARY. Check `dg_parameters`. |
| Lag reported while the primary is idle | See section 8 (no new redo) | Compare `logs_behind` and `dg_redo_rate` |

---

## 12. Files

```
config/oracle-prod.yaml                    30 tools + connection (reads ORACLE_PROD_* env)
app/databases.toml                         [[database]] oracle_prod: menu entry + diagnosis rules (notes)
app/agent.py, scripts/check.py             skip databases whose requires_env variable is empty
db/oracle-lab/                             home-lab primary + standby scripts (see ORACLE-LAB.md)
docker-compose.yml                         service toolbox-oracle-prod (profile oracle-prod, 127.0.0.1:5004)
.env.example                               ORACLE_PROD_CONNECTION_STRING / USERNAME / PASSWORD, COMPOSE_PROFILES
db/oracle-prod/create-agent-reader-cdb.sql     login for a CDB (C##AGENT_READER, CONTAINER_DATA=ALL)
db/oracle-prod/create-agent-reader-noncdb.sql  login for a non-CDB (AGENT_READER)
db/oracle-prod/verify-agent-reader.sql         run as the login: visibility + write test
```

Adding your own tool is the same as before: add a `kind: tool` block to
`config/oracle-prod.yaml`, then run `docker compose restart toolbox-oracle-prod`. The
agent picks it up when it next connects. Write a clear `description`: it's what the
model reads to decide when to use the tool.

---

## 13. Next: approved actions (phase 2)

The plan we agreed:

- **A small separate action service** with a fixed list of actions. To start: stop MRP,
  start MRP, defer or enable a destination. Never free-form SQL.
- **The agent can only propose an action.** It runs after you click **Approve** in the
  web UI, or type the approval in the CLI.
- **Its own SYSDG login**, kept separate from the read-only one.
- **Every action is logged**, with who approved it and when.

That's also when the standby itself becomes visible (`V$DATAGUARD_STATS`,
`V$DATAGUARD_PROCESS`), through the same privileged path.
