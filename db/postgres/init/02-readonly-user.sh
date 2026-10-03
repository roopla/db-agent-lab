#!/bin/bash
# Creates the login that Toolbox (and therefore the LLM) uses.
# It can only SELECT, every transaction is read-only, and queries time out after 10s.
# Runs once, on first start of an empty database volume.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v reader_pw="$DB_READER_PASSWORD" \
     -v dbname="$POSTGRES_DB" <<'EOSQL'
CREATE ROLE agent_reader LOGIN PASSWORD :'reader_pw';

GRANT CONNECT ON DATABASE :"dbname" TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_reader;

-- Belt and braces: even if a grant slips through later, writes are refused.
ALTER ROLE agent_reader SET default_transaction_read_only = on;
-- Stop runaway LLM-written queries.
ALTER ROLE agent_reader SET statement_timeout = '10s';
EOSQL

# Monitoring access for the DBA tools (still read-only) + query statistics.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
GRANT pg_monitor TO agent_reader;
EOSQL
