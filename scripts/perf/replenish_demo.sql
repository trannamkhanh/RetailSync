SET XACT_ABORT ON;
IF DB_NAME() <> 'RTS_DB_DEMO' THROW 50000, 'Demo database required', 1;
BEGIN TRANSACTION;
DECLARE @added TABLE(store_id varchar(10), sku varchar(20));
;WITH ranked AS (
 SELECT batch_id, ROW_NUMBER() OVER (PARTITION BY store_id, sku ORDER BY expiry_date DESC, batch_id) AS ranking
 FROM dbo.product_batch WHERE store_id IN ('STORE-DN1','STORE-DN2','STORE-DN3')
 AND expiry_date >= CAST(DATEADD(hour,7,SYSUTCDATETIME()) AS date)
)
UPDATE b SET quantity = quantity + 5000 OUTPUT inserted.store_id, inserted.sku INTO @added
FROM dbo.product_batch b JOIN ranked r ON r.batch_id=b.batch_id WHERE r.ranking=1;
IF (SELECT COUNT(*) FROM @added) <> 27 THROW 50001, 'Expected 27 seeded store/SKU pairs', 1;
UPDATE i SET quantity=i.quantity+5000 FROM dbo.inventory i JOIN @added a ON a.store_id=i.store_id AND a.sku=i.sku;
IF @@ROWCOUNT <> 27 THROW 50002, 'Expected 27 inventory rows', 1;
COMMIT;
