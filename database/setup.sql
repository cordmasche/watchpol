-- One-time database setup. Run as a PostgreSQL superuser:
--     psql -d postgres -f database/setup.sql
-- (docker compose runs this automatically on first start.)
--
-- Creates:
--   incident         owns the tables; the app writes with this role
--   incident_reader  read-only role used by the SQL console
--   incidents        main database
--   incidents_test   throwaway database for the test suite
--
-- The passwords below are for LOCAL DEVELOPMENT ONLY. Change them on a server.

CREATE ROLE incident        LOGIN PASSWORD 'incident';
CREATE ROLE incident_reader LOGIN PASSWORD 'reader';

-- Even if a query slips through, this role cannot write and cannot run long.
ALTER ROLE incident_reader SET default_transaction_read_only = on;
ALTER ROLE incident_reader SET statement_timeout = '5s';

CREATE DATABASE incidents      OWNER incident;
CREATE DATABASE incidents_test OWNER incident;

\connect incidents
GRANT USAGE ON SCHEMA public TO incident_reader;

\connect incidents_test
GRANT USAGE ON SCHEMA public TO incident_reader;

-- SELECT on the events table is granted by the app (flask init-db / on start).
