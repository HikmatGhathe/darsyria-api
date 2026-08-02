-- Runs automatically the first time Postgres initializes an empty data
-- directory (docker-entrypoint-initdb.d). Ensures the pgvector extension
-- exists before any migration creates a VECTOR column, so a fresh deploy
-- never fails with: type "vector" does not exist.
CREATE EXTENSION IF NOT EXISTS vector;
