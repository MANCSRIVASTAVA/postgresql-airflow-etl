-- Separates the raw landing area from the curated model: anything extracted
-- straight from the source file lands in `staging`, survives no integrity
-- constraints, and gets reloaded wholesale on every run. The normalised
-- tables and reporting aggregates live in `public`, where constraints do
-- real work. Keeping them apart means a bad source file can never corrupt
-- the curated tables before validation has had a chance to reject it.

CREATE SCHEMA IF NOT EXISTS staging;
