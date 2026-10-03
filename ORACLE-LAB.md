# Oracle 19c Data Guard lab (Docker)

`docker compose up -d` builds a 19c **primary** and a **physical standby** from scratch,
using your image `oracle/database:19.3.0-ee-ext`. The agent's `oracle_prod` Toolbox
connects to the primary. Nothing is set up by hand.

Diagrams of the build and of redo flow: `ARCHITECTURE.html`.

## What gets created

| container | role | inside Docker | on this host |
|---|---|---|---|
| `oracle-init` | one-off: makes the shared volume writable, then exits | - | - |
| `oracle-primary` | CDB `ORCLCDB` + PDB `ORCLPDB1`, `db_unique_name=ORCLCDB`, ARCHIVELOG, FORCE LOGGING | `oracle-primary:1521` | `127.0.0.1:1531` |
| `oracle-standby` | physical standby `db_unique_name=ORCLCDB_STBY`, MOUNTED, real-time apply | `oracle-standby:1521` | `127.0.0.1:1532` |
| `toolbox-oracle-prod` | MCP Toolbox, 30 read-only tools, logs in as `C##AGENT_READER` | `toolbox-oracle-prod:5000` | `127.0.0.1:5004` |

Volumes: `oraprimary`, `orastandby` (each database's files) and `orashared` (hand-over
from primary to standby: password file + service name).

Data Guard settings (the same as your hand-built pair):

| parameter | primary | standby |
|---|---|---|
| `log_archive_config` | `DG_CONFIG=(ORCLCDB,ORCLCDB_STBY)` | same |
| `log_archive_dest_2` | `SERVICE=DG_STANDBY ASYNC ... DB_UNIQUE_NAME=ORCLCDB_STBY` | `SERVICE=DG_PRIMARY ASYNC ... DB_UNIQUE_NAME=ORCLCDB` |
| `fal_server` | `DG_STANDBY` | `DG_PRIMARY` |
| `standby_file_management` | `AUTO` | `AUTO` |
| standby redo logs | online groups + 1 | online groups + 1 |
| broker | not used | not used |

## How the build works

1. **oracle-init** chowns the `orashared` volume to `oracle` and exits.
2. **oracle-primary** runs the image's normal start-up: `createDB.sh` makes the CDB
   (15-40 minutes the first time), then `runUserScripts.sh` runs
   `db/oracle-lab/primary/01-dataguard-primary.sh` **once**. That script turns on force
   logging, sets the DG parameters, adds standby redo logs, adds the `DG_PRIMARY` /
   `DG_STANDBY` aliases to `tnsnames.ora`, creates `C##AGENT_READER`, and copies the password
   file to `orashared` with a `primary_ready` flag.
3. **oracle-standby** runs `db/oracle-lab/standby/standby.sh` instead of the image's
   start-up. It waits for `primary_ready`, copies the password file, writes its own
   listener (with a static entry, so RMAN can connect to a NOMOUNT instance), creates the
   primary's directories, starts a bare instance, then runs
   `DUPLICATE TARGET DATABASE FOR STANDBY FROM ACTIVE DATABASE`. Then it adds standby redo
   logs if needed, starts redo apply (MRP), and re-enables `log_archive_dest_2` on the
   primary.
4. **toolbox-oracle-prod** restarts until the primary accepts logins, then serves the tools.

Later starts are quick: the primary opens normally, and the standby does `STARTUP MOUNT`
and restarts apply. `docker compose stop` makes both do `SHUTDOWN IMMEDIATE`.

## Using Oracle's registry image instead

The build works the same with `container-registry.oracle.com/database/enterprise:19.3.0.0`:

1. Sign in at https://container-registry.oracle.com, open **Database → enterprise** and
   accept the licence (once).
2. On the VM: `docker login container-registry.oracle.com` (Oracle account e-mail; as the
   password use an **auth token** from your registry profile if your account has MFA/SSO).
3. In `.env`: `ORACLE_IMAGE=container-registry.oracle.com/database/enterprise:19.3.0.0`.
4. `docker compose up -d` pulls it (about 8 GB) the first time.

If that image ignores `ENABLE_ARCHIVELOG`, the primary setup script switches the database
to ARCHIVELOG itself (you'll see `switching to ARCHIVELOG` in the log).

## Before you start

- **RAM:** about 8 GB free (2 x (SGA 1.5 GB + PGA 0.5 GB) plus overhead). Smaller:
  `ORACLE_SGA_MB=1024`, `ORACLE_PGA_MB=256` in `.env`.
- **Disk:** about 30 GB in Docker's data directory.
- **Image:** `docker images oracle/database` must show `19.3.0-ee-ext`.
- **Your old pair** (`oracle19c` / `oracle19c-stby`) can keep running: the new
  containers use other names, other volumes, and host ports 1531/1532. Stop the old pair
  if RAM is tight. `oracle_prod` now points at the new primary.

## Run it

```bash
cd db-agent
# new install: bash scripts/make-env.sh   (creates .env with random passwords)
# existing .env: add these lines (letters and digits only in passwords)
#   ORACLE_IMAGE=oracle/database:19.3.0-ee-ext
#   ORACLE_SYS_PASSWORD=Ora<random>
#   ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB.localdomain
#   ORACLE_PROD_USERNAME=C##AGENT_READER
#   ORACLE_PROD_PASSWORD=Rdr<random>
#   COMPOSE_PROFILES=oracle-lab,oracle-prod
#   (and delete ORACLE_LAB_NETWORK if it is there)
# lab with OpenAI as the model: also uncomment ALLOW_EXTERNAL_MODELS_FOR=oracle_prod

docker compose up -d
docker compose logs -f oracle-primary     # wait for: DATABASE IS READY TO USE!
docker compose logs -f oracle-standby     # wait for: STANDBY IS READY TO USE!
docker compose ps                         # oracle-standby -> (healthy)
uv run python scripts/check.py            # oracle_prod -> OK, 30 tools
```

## Check Data Guard by hand

```bash
# primary: is dest 2 shipping?
docker exec -it oracle-primary bash -c "sqlplus -s / as sysdba <<'EOF'
select dest_id, status, error from v\$archive_dest where dest_id = 2;
select max(sequence#) from v\$archived_log where dest_id = 2 and applied = 'YES';
EOF"

# standby: role, apply, lag
docker exec -it oracle-standby bash -c "sqlplus -s / as sysdba <<'EOF'
select database_role, open_mode from v\$database;
select process, status, sequence# from v\$managed_standby where process like 'MRP%';
select name, value from v\$dataguard_stats where name in ('transport lag','apply lag');
EOF"
```

Then ask the agent (database `oracle_prod`): *"Is Data Guard healthy?"*, *"What is the
apply lag?"*, *"Any archive gaps?"*.

## Break it on purpose (to test the agent)

| test | how | the agent should report |
|---|---|---|
| apply stopped | standby: `alter database recover managed standby database cancel;` | apply lag growing, MRP missing |
| transport broken | `docker stop oracle-standby` | dest 2 in ERROR (ORA-12541/12514) |
| gap | stop the standby, primary: `alter system archive log current;` x5, start the standby | gap, then FAL catching up |

Restart apply: `alter database recover managed standby database disconnect from session;`

## Troubleshooting

| symptom | cause / fix |
|---|---|
| standby log stops at "waiting for .../primary_ready" | the primary is still creating, or its setup script failed: `docker compose logs oracle-primary \| grep db-agent` |
| `ERROR: RMAN duplicate failed` | read `duplicate.log` (`docker exec oracle-standby cat /opt/oracle/oradata/dbconfig/ORCLCDB_STBY/duplicate.log`), fix, `docker compose restart oracle-standby` (it starts over) |
| ORA-01017 during duplicate | SYS password differs: both containers must get the same `ORACLE_SYS_PASSWORD`. Changing it after the primary was created does nothing; start over (below) |
| toolbox-oracle-prod keeps restarting | normal until the primary is open; after that check `ORACLE_PROD_PASSWORD` |
| toolbox-oracle-prod keeps restarting with ORA-12514, primary is open | the image has no `db_domain` (e.g. `enterprise_ru:latest-19`), so the service is `ORCLCDB`, not `ORCLCDB.localdomain`. Check `docker exec oracle-primary lsnrctl status`, set `ORACLE_PROD_CONNECTION_STRING=oracle-primary:1521/ORCLCDB` in `.env`, then `docker compose up -d toolbox-oracle-prod` |
| `oracle-init` failed | the image has no `oracle` user/`oinstall` group: change the chown to `54321:54321` |
| out of memory / ORA-27102 | lower `ORACLE_SGA_MB` (only takes effect on a fresh build) |
| standby lag stays at about a minute; standby `v$standby_log` all `UNASSIGNED`; alert log `ORA-19527: physical standby redo log must be renamed` / `No SRLs available` | `log_file_name_convert` not set on a same-path standby, so Oracle won't create the SRL files. On the standby: `alter system set log_file_name_convert='/opt/oracle/oradata/ORCLCDB/','/opt/oracle/oradata/ORCLCDB/' scope=spfile;` then `docker compose restart oracle-standby`. New builds set it in `standby.sh` |

**Start over** (deletes both lab databases):

```bash
docker compose rm -sf oracle-primary oracle-standby oracle-init
docker volume rm db-agent_oraprimary db-agent_orastandby db-agent_orashared
docker compose up -d
```

(the volume prefix is your folder name; `docker volume ls | grep ora` shows it)

## Files

```
db/oracle-lab/primary/01-dataguard-primary.sh   one-time DG setup on the primary (sourced by the image)
db/oracle-lab/standby/standby.sh                 standby entrypoint: clone, apply, shutdown trap
db/oracle-lab/standby/healthcheck.sh             healthy = PHYSICAL STANDBY + MRP running
docker-compose.yml                               oracle-init / oracle-primary / oracle-standby / toolbox-oracle-prod
```

> Lab only. Passwords sit in `.env`, the standby is built over the network with SYS, and
> there is no broker or backup. Your real primary/standby keep their own setup; for them,
> just point `ORACLE_PROD_CONNECTION_STRING` at the primary.
