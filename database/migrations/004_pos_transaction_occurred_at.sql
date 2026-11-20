-- Dashboard revenue (Dashboard_Backend_Tasks M1). Database Design: pos_transaction
-- gains the moment the sale, return or cancellation actually happened, which the
-- POS already sends as `timestamp` and the Middleware used to drop.
--
--   occurred_at  datetime2 NULL  the POS-declared moment; NULL for old rows.
--   effective_at datetime2 NOT NULL  the moment the Dashboard reads:
--                COALESCE(occurred_at, created_at), computed and persisted.
--
-- No row is backfilled and no row is rewritten: old transactions keep
-- occurred_at NULL, so effective_at falls back to created_at (the moment the
-- Middleware received them) and the Dashboard can say so.
--
-- Forward-only: 001-003 are not edited and there is no down migration.
--
-- Each statement sits in its own batch. SQL Server compiles a whole batch before
-- running it, so referencing occurred_at in the same batch that adds it fails
-- with "Invalid column name" even though the ALTER comes first; the computed
-- column and the index on it have the same problem. sqlcmd treats GO as a batch
-- separator in the same session, so the transaction below still spans the file
-- and SET XACT_ABORT ON rolls the whole migration back if any batch fails.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
GO

ALTER TABLE dbo.pos_transaction ADD occurred_at datetime2 NULL CONSTRAINT df_pos_transaction_occurred_at DEFAULT NULL;
GO

ALTER TABLE dbo.pos_transaction ADD effective_at AS COALESCE(occurred_at, created_at) PERSISTED;
GO

-- Range queries on one store, and the system-wide chart, filter and group by
-- effective_at, so it carries its own index.
CREATE INDEX ix_pos_transaction_effective_at ON dbo.pos_transaction(effective_at);
GO

COMMIT;
GO
