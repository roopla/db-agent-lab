-- Run as the agent login (not as SYSDBA), from the machine that will run the agent if
-- you can, using the same connect string the agent will use:
--   sqlplus c##agent_reader@//<host>:1521/<service> @verify-agent-reader.sql
-- Every line should show a number; an ORA-00942 means a missing grant.
-- "sessions_all_containers" should be well above "sessions_root_only" on a busy CDB.

SET PAGESIZE 100 LINESIZE 160 FEEDBACK OFF
COLUMN check_name FORMAT A32
COLUMN result FORMAT A60

SELECT 'login'                    AS check_name, USER || ' @ ' || SYS_CONTEXT('USERENV', 'CON_NAME') AS result FROM dual
UNION ALL SELECT 'database role',             database_role || ' / ' || open_mode FROM v$database
UNION ALL SELECT 'standby destinations',      TO_CHAR(COUNT(*)) FROM v$archive_dest WHERE target = 'STANDBY' AND status <> 'INACTIVE'
UNION ALL SELECT 'archive dest status rows',  TO_CHAR(COUNT(*)) FROM gv$archive_dest_status
UNION ALL SELECT 'archived logs (14 days)',   TO_CHAR(COUNT(*)) FROM v$archived_log WHERE first_time > SYSDATE - 14
UNION ALL SELECT 'dataguard messages',        TO_CHAR(COUNT(*)) FROM gv$dataguard_status
UNION ALL SELECT 'sessions_all_containers',   TO_CHAR(COUNT(*)) FROM gv$session WHERE type = 'USER'
UNION ALL SELECT 'sessions_root_only',        TO_CHAR(COUNT(*)) FROM gv$session WHERE type = 'USER' AND con_id IN (0, 1)
UNION ALL SELECT 'ASH samples (15 min)',      TO_CHAR(COUNT(*)) FROM gv$active_session_history WHERE sample_time > CAST(SYSTIMESTAMP AS TIMESTAMP) - INTERVAL '15' MINUTE
UNION ALL SELECT 'AWR snapshots',             TO_CHAR(COUNT(*)) FROM dba_hist_snapshot
UNION ALL SELECT 'tablespaces (all PDBs)',    TO_CHAR(COUNT(*)) FROM cdb_tablespace_usage_metrics
UNION ALL SELECT 'FRA',                       NVL(MAX(name), '(no FRA configured)') FROM v$recovery_file_dest
UNION ALL SELECT 'RMAN jobs (3 days)',        TO_CHAR(COUNT(*)) FROM v$rman_backup_job_details WHERE start_time > SYSDATE - 3;

-- Write test: must FAIL with ORA-01031 (insufficient privileges).
PROMPT
PROMPT Write test (should fail with ORA-01031):
CREATE TABLE agent_write_test (x NUMBER);
