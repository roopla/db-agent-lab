#!/bin/bash
# Healthy = this instance is a PHYSICAL STANDBY and redo apply (MRP) is running.
out=$(sqlplus -s / as sysdba <<'EOF'
set heading off feedback off pages 0
select 'ROLE=' || database_role from v$database;
select 'MRP=' || count(*) from v$managed_standby where process like 'MRP%';
EOF
)
echo "$out" | grep -q 'ROLE=PHYSICAL STANDBY' || exit 1
echo "$out" | grep -q 'MRP=[1-9]' || exit 1
exit 0
