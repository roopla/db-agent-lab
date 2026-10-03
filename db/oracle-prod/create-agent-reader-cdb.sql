-- Read-only login for db-agent on a 19c MULTITENANT (CDB) PRIMARY.
-- Run in SQL*Plus as SYSDBA (or a DBA common user), connected to CDB$ROOT:
--   sqlplus / as sysdba @create-agent-reader-cdb.sql
-- The user and grants reach the physical standbys automatically through redo.
-- Nothing here grants any write privilege.

WHENEVER SQLERROR EXIT FAILURE
SET VERIFY OFF
ALTER SESSION SET CONTAINER = CDB$ROOT;

ACCEPT agent_pw CHAR PROMPT 'Password for C##AGENT_READER: ' HIDE

CREATE USER c##agent_reader IDENTIFIED BY "&agent_pw" CONTAINER = ALL;
GRANT CREATE SESSION TO c##agent_reader CONTAINER = ALL;

-- Read access to the data dictionary, V$/GV$, DBA_/CDB_ and DBA_HIST views, and
-- what DBMS_XPLAN needs. No access to application tables.
GRANT SELECT_CATALOG_ROLE TO c##agent_reader CONTAINER = ALL;

-- Without this, GV$SESSION, GV$SQL, ASH etc. queried from the root only show the
-- root's own sessions and SQL, not those of the PDBs.
ALTER USER c##agent_reader SET CONTAINER_DATA = ALL CONTAINER = CURRENT;

-- Optional: put the account on a profile your security team approves, so its password
-- does not expire unexpectedly and break the agent, e.g.
--   ALTER USER c##agent_reader PROFILE <monitoring_profile> CONTAINER = ALL;

PROMPT
PROMPT Created C##AGENT_READER. Connect the agent to the CDB root service, e.g.
PROMPT   ORACLE_PROD_CONNECTION_STRING=<scan-or-host>:1521/<cdb_service_name>
PROMPT Then run verify-agent-reader.sql as C##AGENT_READER.
