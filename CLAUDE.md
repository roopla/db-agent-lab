# CLAUDE.md: deploy and verify db-agent on this machine

You are deploying this project on a home-lab Linux VM. **Goal: deploy and verify only.**
At the end, show the `check.py` output and say **READY TO GO**, or say exactly what is
still broken.

Fix problems yourself, and write down everything you do in `DEPLOY-LOG.md` as you go.
Don't run the Data Guard "break it on purpose" tests, and don't add features.

## What the user has already done (check it, don't redo it)

- Installed Docker Engine and the Compose plugin, and added their user to the `docker` group.
- Loaded the Oracle image `oracle/database:19.3.0-ee-ext`, **or** ran
  `docker login container-registry.oracle.com` so Compose can pull
  `container-registry.oracle.com/database/enterprise:19.3.0.0` (set as `ORACLE_IMAGE` in `.env`).
- Unzipped this project. You are in its folder.

If any of these is missing, stop and tell the user what to run. Don't install Docker,
and don't use `sudo` at all. If something truly needs root, give the user the exact
command and wait.

## Read first

- `SETUP.md` sections 6-9: the normal steps and what each should print.
- `ORACLE-LAB.md`: how the Oracle primary and standby build, plus its troubleshooting table.
- `docker-compose.yml`, `db/oracle-lab/primary/01-dataguard-primary.sh`,
  `db/oracle-lab/standby/standby.sh`: what actually runs.

## Rules (follow these strictly)

1. **Never delete data without asking the user first.** That covers:
   - `docker compose down -v`
   - `docker volume rm`
   - `docker system prune` / `docker volume prune`
   - `rm` inside volumes

   The Oracle primary takes up to 40 minutes to build, so a mistaken reset is expensive.
   Exception: `docker compose restart oracle-standby` is fine. The standby script starts
   over on its own.
2. **Never touch containers or volumes that aren't part of this project.** For example,
   the user's older `oracle19c` / `oracle19c-stby` pair, if it exists. Only use
   `docker compose …` from this folder, or the container names `oracle-primary` /
   `oracle-standby`.
3. **Never show secrets.**
   - Don't `cat .env`, and don't echo passwords or the API key. To check a value, mask it:
     `grep -E '^NAME=' .env | sed 's/=.*/=<set>/'`.
   - Never put a secret in `DEPLOY-LOG.md`.
   - Don't ask the user to paste their API key into the chat. They edit `.env` themselves.
4. **Keep everything on localhost.** Don't change any `127.0.0.1:` port binding, and
   don't open firewall ports.
5. **Make the smallest fix that works.** If you change a project file:
   - Log the file, the reason, and a short diff in `DEPLOY-LOG.md`.
   - If you hit a new problem, add a row for it to the troubleshooting table in
     `ORACLE-LAB.md` (Oracle) or `SETUP.md` section 13 (everything else).
   - Don't rewrite or refactor anything else.
6. **Waiting is normal here.** Poll in chunks of at most 9 minutes per command, for
   example `timeout 540 bash -c 'until <check>; do sleep 30; done'`. Never use `-f` on
   logs without a timeout. Write a short "still waiting, at step X" line to the log about
   every 10 minutes.
7. **If the same problem fails three times, stop.** Write up what you tried in the log
   and ask the user.

## DEPLOY-LOG.md

Create it at the start, and add to it after every step:

```markdown
# db-agent deployment log
Host: <hostname> · started <date -Is> · Docker <version> · Compose <version>

## <HH:MM> Step N - <name>
- ran: `<command>` (no secrets)
- result: OK / FAILED - <one line>
- (if a problem) cause: … · fix: … · files changed: … (diff below)
```

End it with a `## Result` section that holds the final `check.py` output and the
verification table from step 9.

## Steps

**1. Preflight.** Run each check and log the result:

| check | must show |
|---|---|
| `docker version`, `docker compose version` | works without sudo; Compose **v2.20 or newer** |
| `docker image inspect "$ORACLE_IMAGE"` (value from `.env`, default `oracle/database:19.3.0-ee-ext`) | exists, **or** it's a `container-registry.oracle.com/...` image and `docker pull` of it works (logged in). If neither, stop and tell the user |
| `free -g` | 14 GB or more total. If it's under 14 GB, see the note below |
| `df -h .` and `docker info -f '{{.DockerRootDir}}'`, then `df -h` on that path | 60 GB or more free |
| `ss -ltn` | ports 5432 3306 3307 1531 1532 5000 5001 5002 5004 8501 are free |
| `nproc` | 4 or more is recommended; 2 works, just slowly |

If total RAM is under 14 GB: before the Oracle databases are created, add
`ORACLE_SGA_MB=1024` and `ORACLE_PGA_MB=256` to `.env`, and log that you did. If a port
is busy, find out what's using it (`docker ps`, `ss -ltnp`). If it's another stack, ask
the user. For the Oracle ports you can set `ORACLE_PRIMARY_PORT` or
`ORACLE_STANDBY_PORT` in `.env` instead.

**2. uv.** If `uv --version` fails:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

This installs into your home folder, so no sudo is needed.

**3. `.env`.**

- If it doesn't exist, run `bash scripts/make-env.sh`.
- If it does exist, don't overwrite it. Compare it with `.env.example` and add any
  missing keys, giving any missing password a random `Ora…` / `Rdr…` + hex value, the
  way `make-env.sh` does.
- Then check:
  - `COMPOSE_PROFILES=oracle-lab,oracle-prod`
  - `ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB.localdomain`
- **The API key.** If `OPENAI_API_KEY` is still `sk-REPLACE_ME`, carry on: deployment and
  `check.py` don't need it. Remind the user in the final report.
- **External models.** If `OPENAI_BASE_URL` is `https://api.openai.com/v1` (or empty) and
  `ORACLE_PROD_CONNECTION_STRING` points at `oracle-primary`, this is the lab. Set
  `ALLOW_EXTERNAL_MODELS_FOR=oracle_prod`, so the agent can use `oracle_prod` with
  OpenAI, and log it. Never set it when the connection string points anywhere else.
- Finish with `docker compose config --quiet`. It must print nothing.

**4. Python.** `uv sync`. It must end without errors.

**5. Start.** `docker compose up -d`, then `docker compose ps`.

Expect `oracle-init` to show `Exited (0)`. Expect `toolbox-oracle-prod` to keep
restarting until the primary is open. Both are normal.

**6. Demo databases (within about 3 minutes).** `db`, `mysql` and `mariadb` should be
`(healthy)`, and `toolbox`, `toolbox-mysql` and `toolbox-mariadb` should be `Up`. If not,
run `docker compose logs <svc> | tail -40` and fix it.

**7. Oracle primary (allow up to 60 minutes).**

- Wait until `docker compose logs oracle-primary` contains `DATABASE IS READY TO USE!`.
- The setup script must have printed `db-agent: Data Guard primary configured`, and
  there must be no `ORA-` lines from `db-agent` steps. Check with
  `docker compose logs oracle-primary | grep -E "db-agent|ORA-"`.
- Then check:
  ```bash
  docker exec -i oracle-primary bash -c "sqlplus -s / as sysdba" <<'EOF'
  set lines 200 pages 100
  select name, db_unique_name, database_role, open_mode, log_mode, force_logging from v$database;
  select count(*) standby_redo_logs from v$standby_log;
  select username from dba_users where username = 'C##AGENT_READER';
  EOF
  ```
  You want: PRIMARY, READ WRITE, ARCHIVELOG, YES, at least 4 standby redo logs, and the
  user present.

If the setup script failed, it only runs once. Fix the cause, then run the failed part
by hand: `docker exec -i oracle-primary bash` with the same SQL. Don't rebuild the
primary unless the user agrees (rule 1).

**8. Oracle standby (allow up to 60 more minutes).**

- Wait until `docker compose logs oracle-standby` contains `STANDBY IS READY TO USE!`
  and `docker compose ps oracle-standby` shows `(healthy)`.
- If you see `ERROR: RMAN duplicate failed`:
  - Read `/opt/oracle/oradata/dbconfig/ORCLCDB_STBY/duplicate.log` in the standby.
  - Fix the cause.
  - `docker compose restart oracle-standby`. It starts over by itself.
- Common causes are in the `ORACLE-LAB.md` troubleshooting table.

**9. Verify everything.**

a. Redo actually flows:

```bash
docker exec -i oracle-primary bash -c "sqlplus -s / as sysdba" <<'EOF'
alter system archive log current;
alter system archive log current;
EOF
sleep 60
docker exec -i oracle-primary bash -c "sqlplus -s / as sysdba" <<'EOF'
set lines 200
select dest_id, status, error from v$archive_dest where dest_id = 2;
select recovery_mode, gap_status from v$archive_dest_status where dest_id = 2;
select max(sequence#) last_archived from v$archived_log where dest_id = 1;
select max(sequence#) last_applied from v$archived_log where dest_id = 2 and applied = 'YES';
EOF
docker exec -i oracle-standby bash -c "sqlplus -s / as sysdba" <<'EOF'
set lines 200
select database_role, open_mode from v$database;
select process, status, sequence# from v$managed_standby where process like 'MRP%';
select name, value from v$dataguard_stats where name in ('transport lag', 'apply lag');
EOF
```

You want:
- dest 2 `VALID` with no error
- `MANAGED REAL TIME APPLY`, `NO GAP`
- last applied within 1 of last archived
- `PHYSICAL STANDBY` / `MOUNTED`, an `MRP0` line
- lags at `+00 00:00:0x`

b. `uv run --env-file .env python scripts/check.py`. You want `4/4 databases reachable`
and `oracle_prod` with **30 tools**. Retry for up to 5 minutes if the Toolbox is still
starting.

c. Agent smoke test, **only if** `OPENAI_API_KEY` is set (never print it):

```bash
printf 'oracle_prod\nIs Data Guard healthy?\nquit\n' | uv run --env-file .env python app/agent.py
```

The first line answers the database menu. If `DEFAULT_DATABASE` is set in `.env`, the
menu is skipped, so drop that first line. You want a HEALTHY verdict that names
`ORCLCDB_STBY`. If the key isn't set, write
"skipped: no API key" in the log.

## Final report (show this to the user)

1. The exact `check.py` output, in a code block.
2. A verification table: each check from step 9a, with expected value, actual value and
   OK / FAIL.
3. Problems fixed: one line each, plus the files changed.
4. Notes, if any: API key still to be set, memory lowered, ports changed.
5. How to use it next: the terminal command, and the web UI command with its SSH tunnel
   (`SETUP.md` section 11).
6. Then a single line:

```
✅ READY TO GO
```

Print it only if `check.py` shows 4/4 **and** every step 9a check passes. Otherwise print
`❌ NOT READY - <what is left>`. The same result goes at the end of `DEPLOY-LOG.md`.
