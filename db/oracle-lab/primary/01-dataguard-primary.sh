# shellcheck shell=bash
# Oracle 19c lab PRIMARY: one-time setup after the image has created the database.
#
# Mounted at /opt/oracle/scripts/setup in the oracle-primary container. The image's
# runUserScripts.sh SOURCES this file once, as the oracle user, right after the CDB/PDB
# were created (ENABLE_ARCHIVELOG=true already put the database in ARCHIVELOG mode).
# Because it is sourced: no 'exit', no 'set -e' here.
#
# What it does:
#   0. ARCHIVELOG into the data volume, if the image didn't already do it
#   1. Data Guard on the primary: force logging, standby redo logs,
#      standby_file_management, log_archive_config, log_archive_dest_2 -> standby, fal_server
#   2. tnsnames.ora aliases DG_PRIMARY / DG_STANDBY
#   3. Read-only login for the agent: C##AGENT_READER (SELECT_CATALOG_ROLE, all containers)
#   4. Hands the password file + service name to the standby via the shared volume

echo "db-agent: configuring the Data Guard primary"

DG_STBY_UNIQUE="${STANDBY_UNIQUE_NAME:-${ORACLE_SID}_STBY}"
DG_STBY_HOST="${STANDBY_HOST:-oracle-standby}"
DG_PRIM_HOST="${PRIMARY_HOST:-oracle-primary}"
DG_SHARED=/opt/oracle/shared

DG_SERVICE=$(sqlplus -s / as sysdba <<'EOF' | tr -d '[:space:]'
set heading off feedback off pages 0
select coalesce(
         (select regexp_substr(value, '[^, ]+') from v$parameter where name = 'service_names'),
         (select u.value || nvl2(d.value, '.' || d.value, '')
            from v$parameter u, v$parameter d
           where u.name = 'db_unique_name' and d.name = 'db_domain'))
  from dual;
EOF
)
echo "db-agent: primary service is ${DG_SERVICE}"

# ---- 0. ARCHIVELOG, archiving into the data volume. The image does this when it
#         honours ENABLE_ARCHIVELOG; some images (e.g. older Oracle Container Registry
#         builds) don't, and the default destination ($ORACLE_HOME/dbs/arch) is lost
#         when the container is re-created.
DG_ARCH_DIR="$ORACLE_BASE/oradata/$ORACLE_SID/${ARCHIVELOG_DIR_NAME:-archive_logs}"
DG_LOGMODE=$(sqlplus -s / as sysdba <<'EOF' | tr -d '[:space:]'
set heading off feedback off pages 0
select log_mode from v$database;
EOF
)
DG_DEST1=$(sqlplus -s / as sysdba <<'EOF' | tr -d '[:space:]'
set heading off feedback off pages 0
select value from v$parameter where name = 'log_archive_dest_1';
EOF
)
if [ -z "$DG_DEST1" ]; then
  mkdir -p "$DG_ARCH_DIR"
  echo "alter system set log_archive_dest_1='LOCATION=${DG_ARCH_DIR}' scope=both;" | sqlplus -s / as sysdba
  echo "db-agent: archiving to ${DG_ARCH_DIR}"
fi
if [ "$DG_LOGMODE" != "ARCHIVELOG" ]; then
  echo "db-agent: database is in ${DG_LOGMODE} mode - switching to ARCHIVELOG (restarts the instance)"
  sqlplus -s / as sysdba <<'EOF'
shutdown immediate
startup mount
alter database archivelog;
alter database open;
alter pluggable database all open;
alter pluggable database all save state;
EOF
fi

# ---- 2. tnsnames.ora (follow the image's symlink into the data volume, so it persists)
DG_TNS=$(readlink -f "$ORACLE_HOME/network/admin/tnsnames.ora" 2>/dev/null || echo "$ORACLE_HOME/network/admin/tnsnames.ora")
if ! grep -q '^DG_STANDBY' "$DG_TNS" 2>/dev/null; then
  cat >> "$DG_TNS" <<EOF

DG_PRIMARY =
  (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(HOST = ${DG_PRIM_HOST})(PORT = 1521))
    (CONNECT_DATA = (SERVER = DEDICATED)(SERVICE_NAME = ${DG_SERVICE})))

DG_STANDBY =
  (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(HOST = ${DG_STBY_HOST})(PORT = 1521))
    (CONNECT_DATA = (SERVER = DEDICATED)(SERVICE_NAME = ${DG_STBY_UNIQUE})))
EOF
  echo "db-agent: added DG_PRIMARY / DG_STANDBY to ${DG_TNS}"
fi

# ---- 1 + 3. Data Guard parameters, standby redo logs, agent login
sqlplus -s / as sysdba <<EOF
set feedback on serveroutput on
whenever sqlerror continue
alter database force logging;
alter system set standby_file_management = AUTO scope=both;
alter system set log_archive_config = 'DG_CONFIG=(${ORACLE_SID},${DG_STBY_UNIQUE})' scope=both;
alter system set log_archive_dest_2 =
  'SERVICE=DG_STANDBY ASYNC VALID_FOR=(ONLINE_LOGFILES,PRIMARY_ROLE) DB_UNIQUE_NAME=${DG_STBY_UNIQUE}' scope=both;
alter system set log_archive_dest_state_2 = ENABLE scope=both;
alter system set fal_server = 'DG_STANDBY' scope=both;

-- Standby redo logs: one more group than the online logs (thread 1), same size
declare
  n_online number; sz number; dir varchar2(512); g number; n_srl number;
begin
  select count(*) into n_srl from v\$standby_log;
  if n_srl = 0 then
    select count(*), max(bytes) into n_online, sz from v\$log where thread# = 1;
    select substr(member, 1, instr(member, '/', -1)) into dir from v\$logfile where rownum = 1;
    select nvl(max(group#), 0) into g
      from (select group# from v\$log union all select group# from v\$standby_log);
    for i in 1 .. n_online + 1 loop
      g := g + 1;
      execute immediate 'alter database add standby logfile thread 1 group ' || g ||
                        ' (''' || dir || 'standby_redo' || g || '.log'') size ' || sz;
    end loop;
    dbms_output.put_line('db-agent: created ' || (n_online + 1) || ' standby redo logs');
  end if;
end;
/

-- Read-only login for the agent's Toolbox (all containers, no write privileges)
create user c##agent_reader identified by "${AGENT_READER_PASSWORD}" container = all;
grant create session, select_catalog_role to c##agent_reader container = all;
alter user c##agent_reader set container_data = all container = current;

alter system archive log current;
EOF

# ---- 4. Give the standby what it needs to clone itself
if [ -d "$DG_SHARED" ] && [ -w "$DG_SHARED" ]; then
  cp -L "$ORACLE_HOME/dbs/orapw${ORACLE_SID}" "$DG_SHARED/orapw${ORACLE_SID}" \
    && chmod 640 "$DG_SHARED/orapw${ORACLE_SID}"
  echo "${DG_SERVICE}" > "$DG_SHARED/primary_service"
  touch "$DG_SHARED/primary_ready"
  echo "db-agent: password file and service name handed to the standby"
else
  echo "db-agent: WARNING ${DG_SHARED} is not writable - the standby cannot be created"
fi

echo "db-agent: Data Guard primary configured"
unset DG_STBY_UNIQUE DG_STBY_HOST DG_PRIM_HOST DG_SHARED DG_SERVICE DG_TNS DG_ARCH_DIR DG_LOGMODE DG_DEST1
