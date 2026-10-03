-- Read-only login for db-agent on a 19c NON-CDB PRIMARY.
-- Run in SQL*Plus as SYSDBA (or a DBA user):
--   sqlplus / as sysdba @create-agent-reader-noncdb.sql
-- The user and grants reach the physical standbys automatically through redo.
-- Nothing here grants any write privilege.

WHENEVER SQLERROR EXIT FAILURE
SET VERIFY OFF

ACCEPT agent_pw CHAR PROMPT 'Password for AGENT_READER: ' HIDE

CREATE USER agent_reader IDENTIFIED BY "&agent_pw";
GRANT CREATE SESSION TO agent_reader;

-- Read access to the data dictionary, V$/GV$, DBA_ and DBA_HIST views, and what
-- DBMS_XPLAN needs. No access to application tables.
GRANT SELECT_CATALOG_ROLE TO agent_reader;

-- Optional: a profile your security team approves, so the password does not expire
-- unexpectedly and break the agent:
--   ALTER USER agent_reader PROFILE <monitoring_profile>;

PROMPT
PROMPT Created AGENT_READER. Then run verify-agent-reader.sql as AGENT_READER.
