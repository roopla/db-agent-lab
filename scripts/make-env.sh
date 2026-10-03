#!/bin/bash
# Creates .env from .env.example with strong random passwords.
# Usage: bash scripts/make-env.sh            (then put your OpenAI key in .env)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  echo ".env already exists - not overwriting. Delete it first to regenerate."
  exit 1
fi
rand() { openssl rand -hex 16; }
sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(rand)/" \
    -e "s/^DB_READER_PASSWORD=.*/DB_READER_PASSWORD=$(rand)/" \
    -e "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$(rand)/" \
    -e "s/^MYSQL_READER_PASSWORD=.*/MYSQL_READER_PASSWORD=$(rand)/" \
    -e "s/^MARIADB_ROOT_PASSWORD=.*/MARIADB_ROOT_PASSWORD=$(rand)/" \
    -e "s/^MARIADB_READER_PASSWORD=.*/MARIADB_READER_PASSWORD=$(rand)/" \
    -e "s/^ORACLE_SYS_PASSWORD=.*/ORACLE_SYS_PASSWORD=Ora$(openssl rand -hex 10)/" \
    -e "s/^ORACLE_PROD_PASSWORD=.*/ORACLE_PROD_PASSWORD=Rdr$(openssl rand -hex 10)/" \
    .env.example > .env
chmod 600 .env
echo "Created .env with random passwords."
echo "Next: edit .env and set OPENAI_API_KEY  (nano .env)"
