-- Store Web add-on: a human-readable street address per store.
-- Nullable on purpose: older code (and any branch without this migration) keeps
-- working, and INSERTs that ignore the column stay valid.
-- Each ALTER is its own batch: SQL Server compiles a batch before running it, so a
-- CHECK on a column added in the same batch would not resolve.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

ALTER TABLE dbo.store ADD address_text nvarchar(300) NULL;
GO

ALTER TABLE dbo.store ADD CONSTRAINT ck_store_address_text_length
    CHECK (address_text IS NULL OR LEN(address_text) BETWEEN 1 AND 300);
GO

COMMIT;
