-- Product illustration for the store web: a URL the browser can load.
-- Nullable: a product without a picture still renders (the web falls back to a
-- placeholder), and existing INSERTs that ignore the column keep working.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

ALTER TABLE dbo.product ADD image_url nvarchar(300) NULL;
GO

ALTER TABLE dbo.product ADD CONSTRAINT ck_product_image_url_length
    CHECK (image_url IS NULL OR LEN(image_url) BETWEEN 1 AND 300);
GO

COMMIT;
