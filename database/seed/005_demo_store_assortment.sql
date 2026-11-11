-- Store-specific assortment: each branch sells products the other branches do not.
-- Safe to run repeatedly. Existing products, inventory rows and quantities are never
-- overwritten, and the SKU-0001..0009 catalogue from 002_demo_catalog.sql stays at
-- all three stores, so the baseline the demo scripts expect is unchanged.
--
-- Names below describe the photo each SKU shows (see 006_demo_product_images.sql),
-- so rows seeded before a photo was added are renamed by the UPDATE block at the
-- end of section 1.
--
-- What this adds:
--   STORE-DN1 (Hải Châu)  fresh produce           + shared dairy item
--   STORE-DN2 (Thanh Khê) drinks and sandwiches   + shared dairy item
--   STORE-DN3 (Sơn Trà)   household goods         + shared sandwich
-- The shop page can then answer "which store has this?" with a different store per
-- product, instead of every branch offering the same nine items.

DECLARE @today date = CAST(DATEADD(hour, 7, SYSUTCDATETIME()) AS date);

-- 1. Catalogue rows. A product exists once; stock decides which store sells it.
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0010')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0010', '8930000000103', N'Rau muống 500g', 'Fresh', 12000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0011')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0011', '8930000000110', N'Cà chua bi 1kg', 'Fresh', 18000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0012')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0012', '8930000000127', N'Chuối xanh 1kg', 'Fresh', 22000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0013')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0013', '8930000000134', N'Bia Budweiser 330ml', 'Beverages', 15000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0014')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0014', '8930000000141', N'Nước ngọt cola 330ml', 'Beverages', 21000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0015')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0015', '8930000000158', N'Cà phê hạt rang 250g', 'Beverages', 85000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0016')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0016', '8930000000165', N'Nước giặt 3kg', 'Household', 165000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0017')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0017', '8930000000172', N'Giấy ăn 2 lớp', 'Household', 32000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0018')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0018', '8930000000189', N'Nước rửa chén 750ml', 'Household', 45000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0019')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0019', '8930000000196', N'Trứng gà 6 quả', 'Fresh', 35000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0020')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0020', '8930000000202', N'Sữa chua uống Yakult', 'Dairy', 28000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0021')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0021', '8930000000219', N'Bánh mì sandwich thịt bò', 'Bakery', 27000);

-- The demo photo of each SKU shows what the row now names, so rows seeded with
-- the older wording are upgraded. Each UPDATE matches only its previous name,
-- which keeps an operator's own edit untouched and makes a rerun a no-op.
UPDATE dbo.product SET name = N'Cà chua bi 1kg' WHERE sku = 'SKU-0011' AND name = N'Cà chua 1kg';
UPDATE dbo.product SET name = N'Chuối xanh 1kg' WHERE sku = 'SKU-0012' AND name = N'Chuối già 1kg';
UPDATE dbo.product SET name = N'Bia Budweiser 330ml' WHERE sku = 'SKU-0013' AND name = N'Bia lon 330ml';
UPDATE dbo.product SET name = N'Nước ngọt cola 330ml' WHERE sku = 'SKU-0014' AND name = N'Nước ngọt 1.5L';
UPDATE dbo.product SET name = N'Cà phê hạt rang 250g' WHERE sku = 'SKU-0015' AND name = N'Cà phê rang xay 250g';
UPDATE dbo.product SET name = N'Trứng gà 6 quả' WHERE sku = 'SKU-0019' AND name = N'Trứng gà 10 quả';
UPDATE dbo.product SET name = N'Sữa chua uống Yakult' WHERE sku = 'SKU-0020' AND name = N'Sữa chua uống 4 lốc';
UPDATE dbo.product SET name = N'Bánh mì sandwich thịt bò' WHERE sku = 'SKU-0021' AND name = N'Bánh mì sandwich';

-- 2. Who sells what. Only the listed store gets an inventory row, so the product is
--    absent from every other branch's catalogue page.
;WITH assortment (store_id, sku, quantity) AS (
    SELECT * FROM (VALUES
        ('STORE-DN1', 'SKU-0010', 30),
        ('STORE-DN1', 'SKU-0011', 25),
        ('STORE-DN1', 'SKU-0012', 20),
        ('STORE-DN1', 'SKU-0019', 18),
        ('STORE-DN1', 'SKU-0020', 24),
        ('STORE-DN2', 'SKU-0013', 48),
        ('STORE-DN2', 'SKU-0014', 36),
        ('STORE-DN2', 'SKU-0015', 15),
        ('STORE-DN2', 'SKU-0021', 20),
        ('STORE-DN2', 'SKU-0020', 16),
        ('STORE-DN3', 'SKU-0016', 22),
        ('STORE-DN3', 'SKU-0017', 40),
        ('STORE-DN3', 'SKU-0018', 28),
        ('STORE-DN3', 'SKU-0021', 12)
    ) AS v (store_id, sku, quantity)
)
INSERT dbo.inventory (store_id, sku, quantity)
SELECT a.store_id, a.sku, a.quantity
FROM assortment AS a
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.inventory AS i
    WHERE i.store_id = a.store_id AND i.sku = a.sku
);

-- 3. Batches for any demo-store row that has stock but no batch yet. Same split as
--    003_demo_batches.sql (about 40% near expiry in 3 days), so a row added above
--    gets a batch list without a second Edit. Rows that already have batches are
--    skipped, which is why this runs harmlessly every time.
;WITH missing AS (
    SELECT i.store_id, i.sku, i.quantity, p.category
    FROM dbo.inventory AS i
    JOIN dbo.product AS p ON p.sku = i.sku
    WHERE i.store_id IN ('STORE-DN1', 'STORE-DN2', 'STORE-DN3')
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
                            WHEN 'Fresh' THEN 5
                            WHEN 'Bakery' THEN 10
                            WHEN 'Dairy' THEN 20
                            WHEN 'Beverages' THEN 120
                            ELSE 365
                        END, @today),
           quantity - near_quantity
    FROM split
    WHERE quantity - near_quantity > 0
) AS batches;
