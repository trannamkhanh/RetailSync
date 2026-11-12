-- Default near-expiry thresholds (PB-21). Safe to run repeatedly.
--
-- A category that has no row here uses NEAR_EXPIRY_DEFAULT_DAYS, which is 3.
-- Only a missing category is inserted, so a threshold an Admin changed through
-- the API is never overwritten by a later migration run.

IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Dairy')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Dairy', 3);
IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Bakery')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Bakery', 2);
IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Dry goods')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Dry goods', 30);
