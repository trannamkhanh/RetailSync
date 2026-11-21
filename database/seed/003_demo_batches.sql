-- Demo batches for PB-20 (Sprint 3, phase 5). Safe to run repeatedly.
--
-- Every store and SKU of the demo stores that still has stock and no batch gets
-- two batches whose quantities add up to its current inventory.quantity: about
-- 40% expires in 3 days, the rest later by category, so the FEFO rules and the
-- near-expiry screens have something to show.
--
-- Only the nine catalogue SKUs are split. The batch id is
-- 'B-' + store_id + '-' + sku + '-N', and batch_id is varchar(30) while store_id
-- is varchar(10) and sku is varchar(20), so a longer SKU that reached a demo
-- store (an imported barcode, for instance) would overflow the column. The seed
-- files run on every migrate.sh, so that overflow failed a re-run with SQL 2628
-- and aborted the migration step. Inventory of any other SKU keeps its stock and
-- simply gets no generated batch; the demo only shows the catalogue.
--
-- Dates are the business date: SYSUTCDATETIME() plus the 7 hour UTC offset
-- (Sprint 3 decision 6). The quantity comes from inventory, not from the 40/25/15
-- the older seed writes, so the same script is correct on a database whose stock
-- has moved. The single INSERT is atomic, and it runs again harmlessly because a
-- store and SKU that already has a batch is skipped.

DECLARE @today date = CAST(DATEADD(hour, 7, SYSUTCDATETIME()) AS date);

;WITH missing AS (
    SELECT i.store_id, i.sku, i.quantity, p.category
    FROM dbo.inventory AS i
    JOIN dbo.product AS p ON p.sku = i.sku
    WHERE i.store_id IN ('STORE-DN1', 'STORE-DN2', 'STORE-DN3')
      AND i.sku IN ('SKU-0001', 'SKU-0002', 'SKU-0003', 'SKU-0004', 'SKU-0005',
                    'SKU-0006', 'SKU-0007', 'SKU-0008', 'SKU-0009')
      AND i.quantity > 0
      AND NOT EXISTS (
          SELECT 1 FROM dbo.product_batch AS b
          WHERE b.store_id = i.store_id AND b.sku = i.sku
      )
),
split AS (
    SELECT store_id, sku, quantity, category,
           CASE
               WHEN quantity < 2 THEN 0
               WHEN quantity * 2 / 5 > 0 THEN quantity * 2 / 5
               ELSE 1
           END AS near_quantity
    FROM missing
)
INSERT INTO dbo.product_batch (batch_id, sku, store_id, expiry_date, quantity)
SELECT batch_id, sku, store_id, expiry_date, quantity
FROM (
    SELECT store_id,
           sku,
           'B-' + store_id + '-' + sku + '-1' AS batch_id,
           DATEADD(day, 3, @today) AS expiry_date,
           near_quantity AS quantity
    FROM split
    WHERE near_quantity > 0
    UNION ALL
    SELECT store_id,
           sku,
           'B-' + store_id + '-' + sku + '-2',
           DATEADD(day, CASE category
                            WHEN 'Dairy' THEN 20
                            WHEN 'Bakery' THEN 10
                            ELSE 180
                        END, @today),
           quantity - near_quantity
    FROM split
    WHERE quantity - near_quantity > 0
) AS batches;
