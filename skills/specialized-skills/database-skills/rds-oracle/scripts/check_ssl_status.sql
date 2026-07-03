-- Check SSL/TLS and encryption status for the current session
-- Run this after connecting to RDS Oracle to verify encryption is active
-- Usage: @check_ssl_status.sql (from sqlplus/SQLcl)

SET LINESIZE 200
SET PAGESIZE 50

PROMPT === Network Protocol ===
SELECT SYS_CONTEXT('USERENV', 'NETWORK_PROTOCOL') AS network_protocol FROM dual;
-- 'tcps' = SSL/TLS active, 'tcp' = unencrypted (check NNE below)

PROMPT === Encryption Banners ===
SELECT network_service_banner
FROM v$session_connect_info
WHERE sid = SYS_CONTEXT('USERENV', 'SID')
AND network_service_banner IS NOT NULL;

PROMPT === Authentication Info ===
SELECT
    SYS_CONTEXT('USERENV', 'AUTHENTICATION_METHOD') AS auth_method,
    SYS_CONTEXT('USERENV', 'AUTHENTICATED_IDENTITY') AS identity,
    SYS_CONTEXT('USERENV', 'SESSION_USER') AS session_user,
    SYS_CONTEXT('USERENV', 'HOST') AS client_host
FROM dual;

PROMPT === Session Details ===
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.program,
    s.machine,
    s.status,
    s.logon_time
FROM v$session s
WHERE s.sid = SYS_CONTEXT('USERENV', 'SID');

PROMPT === Database Version ===
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
