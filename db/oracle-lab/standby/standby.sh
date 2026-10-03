#!/bin/bash
# Oracle 19c lab PHYSICAL STANDBY - entrypoint of the oracle-standby container.
#
# Same image as the primary (oracle/database:19.3.0-ee-ext), but instead of the image's
# runOracle.sh (which would create a NEW database) this script:
#
#   first start   1. waits until the primary has finished its Data Guard setup
#                    (/opt/oracle/shared/primary_ready, written by 01-dataguard-primary.sh)
#                 2. copies the primary's password file, writes tnsnames/listener/sqlnet
#                    (static listener entry, so RMAN can reach a NOMOUNT instance)
#                 3. creates the same directories the primary uses
#                 4. starts a bare instance (db_name only) in NOMOUNT
#                 5. RMAN: DUPLICATE TARGET DATABASE FOR STANDBY FROM ACTIVE DATABASE
#                 6. standby redo logs, starts redo apply (MRP), re-enables dest 2 on the primary
#   later starts  STARTUP MOUNT + start redo apply
#   docker stop   SHUTDOWN IMMEDIATE (trap on SIGTERM)
#
# Everything that must survive a container re-create (spfile, password file, network
# files) lives in the data volume under $ORACLE_BASE/oradata/dbconfig/<unique name>
# and is symlinked into $ORACLE_HOME on every start.

set -uo pipefail

SID=${ORACLE_SID:-ORCLCDB}
DB_NAME=${DB_NAME:-$SID}
PRIMARY_UNIQUE=${PRIMARY_UNIQUE_NAME:-$SID}
STBY_UNIQUE=${STANDBY_UNIQUE_NAME:-${SID}_STBY}
PRIM_HOST=${PRIMARY_HOST:-oracle-primary}
SHARED=/opt/oracle/shared
CONF=$ORACLE_BASE/oradata/dbconfig/$STBY_UNIQUE
MARKER=$CONF/.standby_created
NETADM=$ORACLE_HOME/network/admin
SYSPW=${ORACLE_PWD:?ORACLE_PWD must be set - the same SYS password as the primary}

log() { echo "$(date '+%F %T') standby: $*"; }

sql_local() { sqlplus -s / as sysdba; }                       # SQL on stdin
sql_primary() {                                               # SQL on stdin, runs on the primary
  { echo "connect sys/\"${SYSPW}\"@DG_PRIMARY as sysdba"; cat; } | sqlplus -s /nolog
}

link_config() {
  mkdir -p "$CONF" "$NETADM"
  local f
  for f in tnsnames.ora listener.ora sqlnet.ora; do
    [ -f "$CONF/$f" ] && ln -sf "$CONF/$f" "$NETADM/$f"
  done
  for f in "spfile${SID}.ora" "orapw${SID}"; do
    [ -f "$CONF/$f" ] && ln -sf "$CONF/$f" "$ORACLE_HOME/dbs/$f"
  done
  return 0
}

write_network_files() {
  local prim_service
  prim_service=$(cat "$SHARED/primary_service" 2>/dev/null || echo "${PRIMARY_UNIQUE}.localdomain")
  cat > "$CONF/tnsnames.ora" <<EOF
DG_PRIMARY =
  (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(HOST = ${PRIM_HOST})(PORT = 1521))
    (CONNECT_DATA = (SERVER = DEDICATED)(SERVICE_NAME = ${prim_service})))

DG_STANDBY =
  (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(HOST = localhost)(PORT = 1521))
    (CONNECT_DATA = (SERVER = DEDICATED)(SERVICE_NAME = ${STBY_UNIQUE})))
EOF
  # Static entry: a NOMOUNT / MOUNTED instance cannot register dynamically for remote SYS logins
  cat > "$CONF/listener.ora" <<EOF
LISTENER =
  (DESCRIPTION_LIST =
    (DESCRIPTION = (ADDRESS = (PROTOCOL = TCP)(HOST = 0.0.0.0)(PORT = 1521)))
    (DESCRIPTION = (ADDRESS = (PROTOCOL = IPC)(KEY = EXTPROC1))))

SID_LIST_LISTENER =
  (SID_LIST =
    (SID_DESC = (GLOBAL_DBNAME = ${STBY_UNIQUE})(ORACLE_HOME = ${ORACLE_HOME})(SID_NAME = ${SID})))
EOF
  echo "NAMES.DIRECTORY_PATH = (TNSNAMES, EZCONNECT)" > "$CONF/sqlnet.ora"
}

start_apply() {
  sql_local <<'EOF'
set feedback on serveroutput on
whenever sqlerror continue
-- Standby redo logs: one more group than the online logs, same size (if RMAN made none)
declare
  n_online number; sz number; dir varchar2(512); g number; n_srl number;
begin
  select count(*) into n_srl from v$standby_log;
  if n_srl = 0 then
    select count(*), max(bytes) into n_online, sz from v$log where thread# = 1;
    select substr(member, 1, instr(member, '/', -1)) into dir from v$logfile where rownum = 1;
    select nvl(max(group#), 0) into g
      from (select group# from v$log union all select group# from v$standby_log);
    for i in 1 .. n_online + 1 loop
      g := g + 1;
      execute immediate 'alter database add standby logfile thread 1 group ' || g ||
                        ' (''' || dir || 'standby_redo' || g || '.log'') size ' || sz;
    end loop;
    dbms_output.put_line('standby: created ' || (n_online + 1) || ' standby redo logs');
  end if;
end;
/
alter database recover managed standby database disconnect from session;
EOF
}

shutdown_db() {
  log "SIGTERM - shutting the standby down"
  echo "shutdown immediate" | sql_local
  lsnrctl stop >/dev/null 2>&1
  exit 0
}
trap shutdown_db TERM INT

# ------------------------------------------------------------------ first start
if [ ! -f "$MARKER" ]; then
  log "no standby yet - creating ${STBY_UNIQUE} from primary ${PRIMARY_UNIQUE} on ${PRIM_HOST}"
  mkdir -p "$CONF"

  log "waiting for the primary to finish creating its database (first run takes 15-40 min)"
  n=0
  until [ -f "$SHARED/primary_ready" ]; do
    sleep 30; n=$((n + 1))
    [ $((n % 10)) -eq 0 ] && log "still waiting for $SHARED/primary_ready ..."
  done

  cp -f "$SHARED/orapw${SID}" "$CONF/orapw${SID}"
  write_network_files
  link_config
  lsnrctl start

  log "waiting until SYS can log in to the primary over DG_PRIMARY"
  until echo "select 'PRIMARY_OK' from dual;" | sql_primary | grep -q PRIMARY_OK; do sleep 20; done

  log "creating the primary's directories here"
  sql_primary <<'EOF' | grep '^/' | while read -r p; do mkdir -p "$(dirname "$p")"; done
set heading off feedback off pages 0 lines 1000 trimspool on
select name from v$datafile
union select name from v$tempfile
union select member from v$logfile
union select name from v$controlfile
union select regexp_substr(value, 'LOCATION *= *([^ ,]+)', 1, 1, 'i', 1) || '/x'
        from v$parameter where name like 'log_archive_dest__' and upper(value) like '%LOCATION%'
union select value || '/x' from v$parameter
       where name in ('audit_file_dest', 'db_recovery_file_dest') and value is not null;
EOF

  log "starting a bare instance in NOMOUNT"
  echo "shutdown abort" | sql_local >/dev/null 2>&1
  rm -f "$ORACLE_HOME/dbs/spfile${SID}.ora" "$CONF/spfile${SID}.ora"
  echo "db_name=${DB_NAME}" > "$ORACLE_HOME/dbs/init${SID}.ora"
  echo "startup nomount pfile='$ORACLE_HOME/dbs/init${SID}.ora'" | sql_local

  log "RMAN duplicate for standby from active database (copies every datafile over the network)"
  rman <<EOF | tee "$CONF/duplicate.log"
connect target sys/${SYSPW}@DG_PRIMARY
connect auxiliary sys/${SYSPW}@DG_STANDBY
duplicate target database for standby from active database
  spfile
    set db_unique_name='${STBY_UNIQUE}'
    set fal_server='DG_PRIMARY'
    set log_archive_config='DG_CONFIG=(${PRIMARY_UNIQUE},${STBY_UNIQUE})'
    set log_archive_dest_2='SERVICE=DG_PRIMARY ASYNC VALID_FOR=(ONLINE_LOGFILES,PRIMARY_ROLE) DB_UNIQUE_NAME=${PRIMARY_UNIQUE}'
    set standby_file_management='AUTO'
    set log_file_name_convert='${ORACLE_BASE}/oradata/${SID}/','${ORACLE_BASE}/oradata/${SID}/'
  nofilenamecheck;
exit
EOF
  if ! grep -q "Finished Duplicate Db" "$CONF/duplicate.log"; then
    log "ERROR: RMAN duplicate failed - see $CONF/duplicate.log. Fix the cause, then:"
    log "       docker compose restart oracle-standby   (it starts over from scratch)"
    sleep infinity & wait $!
    exit 1
  fi

  # Keep the spfile in the volume
  mv "$ORACLE_HOME/dbs/spfile${SID}.ora" "$CONF/spfile${SID}.ora"
  rm -f "$ORACLE_HOME/dbs/init${SID}.ora"
  link_config

  log "starting redo apply"
  start_apply

  log "re-enabling redo shipping on the primary"
  sql_primary <<'EOF'
alter system set log_archive_dest_state_2 = ENABLE scope=both;
alter system archive log current;
EOF
  touch "$MARKER"
  log "physical standby ${STBY_UNIQUE} created"

# ------------------------------------------------------------------ later starts
else
  log "starting existing standby ${STBY_UNIQUE}"
  link_config
  lsnrctl start
  echo "startup mount" | sql_local
  start_apply
fi

echo "#########################"
echo "STANDBY IS READY TO USE!"
echo "#########################"

ALERT=$ORACLE_BASE/diag/rdbms/${STBY_UNIQUE,,}/${SID}/trace/alert_${SID}.log
touch "$ALERT" 2>/dev/null || true
tail -F "$ALERT" &
wait $!
