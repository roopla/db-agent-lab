# db-agent deployment log
Host: dbaagent · started 2026-10-03T00:26:34+00:00 · Docker 29.8.2 · Compose v5.6.0

## 00:26 Step 1 - Preflight
- ran: `docker version`, `docker compose version` → result: OK - no sudo needed, Compose v5.6.0 (>= v2.20)
- ran: `docker image inspect "$ORACLE_IMAGE"` (ORACLE_IMAGE=container-registry.oracle.com/database/enterprise_ru:latest-19) → result: OK - present locally (14 GB, 19c RU image)
- ran: `free -g` → result: OK - 15 GB total (>= 14, SGA/PGA left at defaults)
- ran: `df -h .`, DockerRootDir=/var/lib/docker, `df -h /var/lib/docker` → result: OK - 119 GB free (same filesystem)
- ran: `ss -ltn` → result: OK - only 22 and 53 listening; all project ports free
- ran: `nproc` → result: OK - 8
- note: no other containers/volumes exist on this host (no old oracle19c pair)

## 00:30 Step 2 - uv
- ran: `uv --version` → FAILED (not installed)
- ran: `curl -LsSf https://astral.sh/uv/install.sh | sh` → result: OK - uv 0.12.22 in ~/.local/bin
  (note: `~/.local/bin/env` was not created by this installer version; `~/.local/bin` is already on PATH)

## 00:31 Step 3 - .env
- .env exists, not overwritten. Compared keys with .env.example: no missing keys.
- COMPOSE_PROFILES=oracle-lab,oracle-prod: OK
- ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB.localdomain: OK (to re-check against `lsnrctl status` once the primary is up)
- OPENAI_API_KEY: set (not the placeholder; value not shown)
- OPENAI_BASE_URL is https://api.openai.com/v1 and connection string points at oracle-primary → lab:
  uncommented `ALLOW_EXTERNAL_MODELS_FOR=oracle_prod` in .env
- ran: `docker compose config --quiet` → result: OK - printed nothing

## 00:34 Step 4 - Python
- ran: `uv sync` → result: OK - environment created, exited 0

## 00:31 Step 5 - Start
- ran: `docker compose up -d`, `docker compose ps` → result: OK - all containers created; oracle-init `Exited (0)`; toolbox-oracle-prod restarting (expected until primary is open)

## 00:33 Step 6 - Demo databases
- ran: `docker compose ps`, `docker compose logs <toolbox*> | tail` → result: OK - db, mysql, mariadb `(healthy)`; toolbox, toolbox-mysql, toolbox-mariadb `Up`, each logs "Server ready to serve!"

## 00:33 Step 7 - Oracle primary
- DBCA started ("Copying database files"); waiting for `DATABASE IS READY TO USE!`
- 00:41 still waiting, at step 7 (DBCA 36%)
- 00:51 still waiting, at step 7 (DBCA 43%)
- 01:00 still waiting, at step 7 (DBCA 46%)
- 01:04 primary log shows `DATABASE IS READY TO USE!` (~32 min)
- ran: `docker compose logs oracle-primary | grep -E "db-agent|ORA-"` → result: OK - `db-agent: Data Guard primary configured`, 4 standby redo logs created, no ORA- lines
- ran: v$database / v$standby_log / dba_users check → result: OK - ORCLCDB, PRIMARY, READ WRITE, ARCHIVELOG, FORCE_LOGGING YES; 4 standby redo logs; C##AGENT_READER present
- ran: `docker exec oracle-primary lsnrctl status` → services: `ORCLCDB`, `ORCLCDBXDB`, `orclpdb1`, PDB GUID. **No `ORCLCDB.localdomain`** (db_domain is empty in the enterprise_ru:latest-19 image)
  - cause: .env had `ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB.localdomain`; that service does not exist on this image
  - fix: in .env (not a project file, no secrets): `ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB`, then `docker compose up -d toolbox-oracle-prod` to recreate the toolbox with the new value
  - files changed: `.env` (that key only); `ORACLE-LAB.md` troubleshooting table, one new row:
    ```diff
    +| toolbox-oracle-prod keeps restarting with ORA-12514, primary is open | the image has no `db_domain` (e.g. `enterprise_ru:latest-19`), so the service is `ORCLCDB`, not `ORCLCDB.localdomain`. Check `docker exec oracle-primary lsnrctl status`, set `ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB` in `.env`, then `docker compose up -d toolbox-oracle-prod` |
    ```
  - note: the DG setup itself detects the service name (`primary service is ORCLCDB`), so DG_PRIMARY on both sides is already correct

## 01:05 Step 8 - Oracle standby
- standby got `primary_ready`, SYS login over DG_PRIMARY works, NOMOUNT instance started, RMAN duplicate running
- 01:08 `Finished Duplicate Db`, `STANDBY IS READY TO USE!`, `docker compose ps oracle-standby` → `(healthy)` → result: OK (duplicate took ~4 min)
- (ORA-00313/ORA-00312/ORA-27037 for online redo logs in the standby log right after the duplicate: normal, the online logs are cleared when apply starts)

## 01:09 Step 9a - Redo flow (first run)
- ran: the step 9a SQL on primary and standby → result: FAILED (one check) - dest 2 VALID, MANAGED REAL TIME APPLY, NO GAP, last archived 21 / applied 21, PHYSICAL STANDBY MOUNTED, MRP0 present, **but transport lag and apply lag = `+00 00:01:00`**
- cause: on the standby all standby redo logs (groups 4-7) were `UNASSIGNED`, and their files did not exist. The alert log showed
  `ORA-19527: physical standby redo log must be renamed` for every SRL, then `rfs: No SRLs available for T-1`.
  Standby and primary use the same paths (`nofilenamecheck`), and Oracle won't create or clear redo log files at an identical path unless
  `log_file_name_convert` is set. Without SRLs, redo only arrived at each log switch, hence the lag.
- fix (live, standby only, no data deleted):
  - `alter system set log_file_name_convert='/opt/oracle/oradata/ORCLCDB/','/opt/oracle/oradata/ORCLCDB/' scope=spfile;` on oracle-standby
  - `docker compose restart oracle-standby` (allowed; with the marker in place it does `startup mount` and restarts apply)
  - RFS then created the SRL files on its own: SRL groups 7, then 4, `ACTIVE`
- fix (for future builds), files changed: `db/oracle-lab/standby/standby.sh`
  ```diff
       set standby_file_management='AUTO'
  +    set log_file_name_convert='${ORACLE_BASE}/oradata/${SID}/','${ORACLE_BASE}/oradata/${SID}/'
     nofilenamecheck;
  ```
  `ORACLE-LAB.md` troubleshooting table, one new row:
  ```diff
  +| standby lag stays at about a minute; standby `v$standby_log` all `UNASSIGNED`; alert log `ORA-19527: physical standby redo log must be renamed` / `No SRLs available` | `log_file_name_convert` not set on a same-path standby, so Oracle won't create the SRL files. On the standby: `alter system set log_file_name_convert='/opt/oracle/oradata/ORCLCDB/','/opt/oracle/oradata/ORCLCDB/' scope=spfile;` then `docker compose restart oracle-standby`. New builds set it in `standby.sh` |
  ```

## 01:12 Step 9a - Redo flow (re-run after the fix)
- ran: the step 9a SQL → result: OK - see the table in Result

## 01:14 Step 9b - check.py
- ran: `uv run --env-file .env python scripts/check.py` → result: OK - 4/4 reachable, oracle_prod 30 tools (first attempt)

## 01:15 Step 9c - Agent smoke test
- ran: `printf 'oracle_prod\nIs Data Guard healthy?\nquit\n' | uv run --env-file .env python app/agent.py` (DEFAULT_DATABASE empty, so the menu line was kept)
- result: OK - "Yes — Data Guard looks healthy (VERDICT = OK)", names standby `ORCLCDB_STBY`, VALID, MANAGED REAL TIME APPLY, NO GAP, logs_behind 0.
  Note: the tool's verdict field says `OK`, not the literal word `HEALTHY`. It also confirms C##AGENT_READER logs in over `oracle-primary:1521/ORCLCDB`.

## Result

```
OK    postgres     32 tools  http://127.0.0.1:5000
OK    mysql         9 tools  http://127.0.0.1:5001
OK    mariadb       9 tools  http://127.0.0.1:5002
OK    oracle_prod  30 tools  http://127.0.0.1:5004

4/4 databases reachable.
```

| check (9a) | expected | actual | |
|---|---|---|---|
| dest 2 status / error | VALID, no error | VALID, (none) | OK |
| recovery_mode / gap_status | MANAGED REAL TIME APPLY / NO GAP | MANAGED REAL TIME APPLY / NO GAP | OK |
| last applied vs last archived | within 1 | 22 / 23 | OK |
| standby role / open mode | PHYSICAL STANDBY / MOUNTED | PHYSICAL STANDBY / MOUNTED | OK |
| MRP | MRP0 line | MRP0 APPLYING_LOG seq 24 | OK |
| transport lag | +00 00:00:0x | +00 00:00:00 | OK |
| apply lag | +00 00:00:0x | +00 00:00:00 | OK |

Problems fixed:
1. `ORACLE_PROD_CONNECTION_STRING` pointed at `ORCLCDB.localdomain`; this image's service is `ORCLCDB` → `.env` updated; ORACLE-LAB.md troubleshooting row added
2. Standby redo logs never created (ORA-19527, `log_file_name_convert` missing) → set on the live standby + `db/oracle-lab/standby/standby.sh`; ORACLE-LAB.md troubleshooting row added
3. uv not installed → installed to ~/.local/bin

✅ READY TO GO

# Break-it tests (run at the user's explicit request, after deployment)
## 01:27 Test 1 - apply stopped
- broke: on standby `alter database recover managed standby database cancel;` + 3 log switches on the primary
- state: MRP 0, recovery_mode IDLE, archived 26 / applied 23, apply lag +00 00:02:02
- agent ("Is Data Guard healthy?"): **CAUGHT** - "No ... CRITICAL: redo apply (MRP) is not running", IDLE, 3 logs not applied, apply lag 2.2 min, suggests `... disconnect from session`.
  Side note: it also listed old ORA-12541 / "LAD:2 not using SRLs" messages (from the build and the SRL fix) as if they were current
- restored: `alter database recover managed standby database disconnect from session;`
- result: restored OK - MRP back, archived 27 / applied 26, lags 0
## 01:31 Test 2 - transport broken
- broke: `docker stop oracle-standby` + 2 log switches on the primary
- state: dest 2 ERROR `ORA-03135: connection lost contact`, gap RESOLVABLE GAP, archived 29 / applied 26
- agent: **CAUGHT** - "No ... LOG_ARCHIVE_DEST_2 is in ERROR / INACTIVE", ORA-03135, fail time, suggests listener/network checks, re-enabling dest 2, `dg_missing_logs` for gaps
- result: restored OK - `docker compose up -d oracle-standby`, dest 2 VALID after the primary's reopen, real-time apply back, archived 30 / applied 29, lags 0
## 01:36 Test 3 - gap
- broke: `docker stop oracle-standby` + 5 log switches on the primary
- state: dest 2 ERROR ORA-03135, RESOLVABLE GAP, archived 35 / applied 29, sequences 31-35 not shipped
- agent ("Any archive gaps? Which sequences is the standby missing?"): **CAUGHT** - "missing sequences 31 through 35 (thread 1) ... still present on the primary" (dg_missing_logs, STILL_ON_DISK=YES), expects FAL to fetch them once reconnected
- restored: `docker compose up -d oracle-standby`; the standby's alert log shows `Client is FAL` RFS sessions and `Media Recovery Log ...1_31` through `1_35`
- result: restored OK - dest 2 VALID, MANAGED REAL TIME APPLY, NO GAP, archived 36 / applied 35, lags 0, both containers (healthy)
- agent afterwards ("Is Data Guard healthy now?"): "Yes ... healthy now and there is no gap", VERDICT OK

## Break-it summary
| test | agent caught it | restored |
|---|---|---|
| apply stopped | yes - CRITICAL, MRP not running, 3 logs not applied | yes |
| transport broken | yes - dest 2 ERROR/INACTIVE, ORA-03135 | yes |
| gap | yes - exact missing sequences 31-35, still on disk; later reports gap resolved | yes |
Observation: the agent's `dg_messages` output includes old errors (ORA-12541 from the build, "LAD:2 not using SRLs" from the SRL fix), which it presents as recent. Not fixed (no feature changes).

## Follow-up - doc fix
- `SETUP.md` §12 (and the same row in `SETUP.html`): SQL Developer connection for the primary was `localhost:1531/ORCLCDB.localdomain`, which doesn't exist on enterprise_ru:latest-19
  ```diff
  -| From SQL Developer on the VM | `localhost:1531/ORCLCDB.localdomain` (primary), ...
  +| From SQL Developer on the VM | `localhost:1531/ORCLCDB` (primary; `ORCLCDB.localdomain` on images that set `db_domain`, check `lsnrctl status`), ...
  ```

## 01:42 Follow-up - restart primary to clear old Data Guard messages
- ran: `docker compose restart oracle-primary` (standby left running)
- result: OK - primary reopened (instance started 01:42:37), `v$dataguard_status` has no Error/Fatal/Warning rows
- after one log switch: dest 2 VALID, MANAGED REAL TIME APPLY, NO GAP, archived 38 / applied 38, lags 0, both Oracle containers (healthy)
- check.py: 4/4 reachable, oracle_prod 30 tools (toolbox reconnected by itself)
- agent ("Is Data Guard healthy? Any recent Data Guard errors?"): "healthy and there are no recent Data Guard errors", VERDICT OK
