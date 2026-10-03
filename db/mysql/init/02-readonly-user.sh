#!/bin/bash
# Read-only login for the agent: SELECT on the app schema, plus read-only
# monitoring (PROCESS = see running queries, performance_schema = query stats).
set -euo pipefail
mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
CREATE USER 'agent_reader'@'%' IDENTIFIED BY '${DB_READER_PASSWORD}';
GRANT SELECT, SHOW VIEW ON \`${MYSQL_DATABASE}\`.* TO 'agent_reader'@'%';
GRANT PROCESS ON *.* TO 'agent_reader'@'%';
GRANT SELECT ON performance_schema.* TO 'agent_reader'@'%';
FLUSH PRIVILEGES;
SQL
