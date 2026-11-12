#!/bin/bash
# Runs once, on first container init, as the bootstrap superuser
# (POSTGRES_USER/POSTGRES_DB — Airflow's own metadata DB). Creates the
# second role+database this project actually loads data into, using the
# RETAIL_DB_* env vars the compose file maps in from .env.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE "$RETAIL_DB_USER" WITH LOGIN PASSWORD '$RETAIL_DB_PASSWORD';
    CREATE DATABASE "$RETAIL_DB_NAME" OWNER "$RETAIL_DB_USER";
EOSQL
