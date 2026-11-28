-- PB-52 demo dataset: 30 Vietnamese products across 6 categories, stock tiers, and non-expiring batches.
-- Demo database only (applied by scripts/demo/reset_demo_db.ps1; never run by migrate.sh on RTS_DB/RTS_DB_TEST).
-- Safe to run repeatedly.

-- 1. Rename the 9 existing catalogue SKUs to Vietnamese while keeping SKU, barcode, category and price.
UPDATE dbo.product SET name = N'Sữa tươi 1L' WHERE sku = 'SKU-0001';
UPDATE dbo.product SET name = N'Sữa chua 100g' WHERE sku = 'SKU-0002';
UPDATE dbo.product SET name = N'Phô mai lát 200g' WHERE sku = 'SKU-0003';
UPDATE dbo.product SET name = N'Bánh mì 400g' WHERE sku = 'SKU-0004';
UPDATE dbo.product SET name = N'Bánh bông lan 300g' WHERE sku = 'SKU-0005';
UPDATE dbo.product SET name = N'Bánh quy bơ 200g' WHERE sku = 'SKU-0006';
UPDATE dbo.product SET name = N'Gạo thơm 5kg' WHERE sku = 'SKU-0007';
UPDATE dbo.product SET name = N'Mì gói 75g' WHERE sku = 'SKU-0008';
UPDATE dbo.product SET name = N'Dầu ăn 1L' WHERE sku = 'SKU-0009';

-- 2. Add 21 new products (5 total per category across Dairy, Bakery, Dry goods, Beverages, Snacks, Frozen).
-- Categories stay English in DB (varchar(50)); client apps map them to Vietnamese for display.
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0010')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0010', '8930000000103', N'Sữa đặc có đường 380g', 'Dairy', 26000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0011')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0011', '8930000000110', N'Sữa đậu nành 200ml', 'Dairy', 6500);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0012')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0012', '8930000000127', N'Bánh mì sandwich 350g', 'Bakery', 22000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0013')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0013', '8930000000134', N'Bánh sừng bò 120g', 'Bakery', 18000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0014')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0014', '8930000000141', N'Nước mắm 500ml', 'Dry goods', 42000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0015')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0015', '8930000000158', N'Đường trắng 1kg', 'Dry goods', 28000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0016')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0016', '8930000000165', N'Nước suối 500ml', 'Beverages', 5000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0017')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0017', '8930000000172', N'Trà xanh đóng chai 455ml', 'Beverages', 10000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0018')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0018', '8930000000189', N'Nước ngọt có gas 330ml', 'Beverages', 11000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0019')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0019', '8930000000196', N'Cà phê sữa lon 240ml', 'Beverages', 15000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0020')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0020', '8930000000202', N'Nước tăng lực 250ml', 'Beverages', 14000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0021')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0021', '8930000000219', N'Snack khoai tây 75g', 'Snacks', 16000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0022')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0022', '8930000000226', N'Bánh gạo vị mặn 150g', 'Snacks', 24000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0023')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0023', '8930000000233', N'Đậu phộng da cá 100g', 'Snacks', 19000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0024')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0024', '8930000000240', N'Kẹo dẻo trái cây 100g', 'Snacks', 20000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0025')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0025', '8930000000257', N'Hạt điều rang muối 150g', 'Snacks', 68000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0026')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0026', '8930000000264', N'Xúc xích đông lạnh 500g', 'Frozen', 75000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0027')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0027', '8930000000271', N'Há cảo đông lạnh 300g', 'Frozen', 52000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0028')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0028', '8930000000288', N'Cá viên chiên 500g', 'Frozen', 62000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0029')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0029', '8930000000295', N'Kem hộp vani 450ml', 'Frozen', 55000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0030')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0030', '8930000000301', N'Khoai tây cọng đông lạnh 1kg', 'Frozen', 85000);

-- 3. Near-expiry thresholds for the 3 new English categories (demo DB only).
IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Beverages')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Beverages', 7);
IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Snacks')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Snacks', 30);
IF NOT EXISTS (SELECT 1 FROM dbo.near_expiry_config WHERE category = 'Frozen')
    INSERT dbo.near_expiry_config (category, threshold_days) VALUES ('Frozen', 14);

-- 4. Inventory for the 21 new SKUs in three tiers (DN1 / DN2 / DN3).
-- Existing SKU-0001..0009 keep 40/25/15 untouched.
-- Slow (80/60/45):   SKU-0010, SKU-0014, SKU-0023, SKU-0025 (S2), SKU-0028, SKU-0029, SKU-0030 (S2)
-- Medium (55/45/30): SKU-0013, SKU-0015, SKU-0017 (S1), SKU-0020 (S1), SKU-0022 (S1), SKU-0024, SKU-0027
-- Fast (40/25/15):   SKU-0011, SKU-0012, SKU-0016, SKU-0018, SKU-0019, SKU-0021, SKU-0026
INSERT dbo.inventory (store_id, sku, quantity)
SELECT s.store_id,
       t.sku,
       CASE s.store_id
           WHEN 'STORE-DN1' THEN t.dn1
           WHEN 'STORE-DN2' THEN t.dn2
           ELSE t.dn3
       END
FROM dbo.store AS s
CROSS JOIN (VALUES
    ('SKU-0010', 80, 60, 45),
    ('SKU-0011', 40, 25, 15),
    ('SKU-0012', 40, 25, 15),
    ('SKU-0013', 55, 45, 30),
    ('SKU-0014', 80, 60, 45),
    ('SKU-0015', 55, 45, 30),
    ('SKU-0016', 40, 25, 15),
    ('SKU-0017', 55, 45, 30),
    ('SKU-0018', 40, 25, 15),
    ('SKU-0019', 40, 25, 15),
    ('SKU-0020', 55, 45, 30),
    ('SKU-0021', 40, 25, 15),
    ('SKU-0022', 55, 45, 30),
    ('SKU-0023', 80, 60, 45),
    ('SKU-0024', 55, 45, 30),
    ('SKU-0025', 80, 60, 45),
    ('SKU-0026', 40, 25, 15),
    ('SKU-0027', 55, 45, 30),
    ('SKU-0028', 80, 60, 45),
    ('SKU-0029', 80, 60, 45),
    ('SKU-0030', 80, 60, 45)
) AS t(sku, dn1, dn2, dn3)
WHERE s.store_id IN ('STORE-DN1', 'STORE-DN2', 'STORE-DN3')
  AND NOT EXISTS (
      SELECT 1 FROM dbo.inventory AS i
      WHERE i.store_id = s.store_id AND i.sku = t.sku
  );

-- 5. Batches for the 21 new SKUs: every batch expires strictly outside its category's near-expiry threshold
-- (and outside Dairy's Act 6 step 2 raised threshold of 7 days) so Act 6 alerts stay focused on the base Dairy/Bakery SKUs.
DECLARE @today date = CAST(DATEADD(hour, 7, SYSUTCDATETIME()) AS date);

;WITH missing AS (
    SELECT i.store_id, i.sku, i.quantity, p.category
    FROM dbo.inventory AS i
    JOIN dbo.product AS p ON p.sku = i.sku
    WHERE i.store_id IN ('STORE-DN1', 'STORE-DN2', 'STORE-DN3')
      AND i.sku IN (
          'SKU-0010', 'SKU-0011', 'SKU-0012', 'SKU-0013', 'SKU-0014', 'SKU-0015', 'SKU-0016',
          'SKU-0017', 'SKU-0018', 'SKU-0019', 'SKU-0020', 'SKU-0021', 'SKU-0022', 'SKU-0023',
          'SKU-0024', 'SKU-0025', 'SKU-0026', 'SKU-0027', 'SKU-0028', 'SKU-0029', 'SKU-0030'
      )
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
           END AS first_qty
    FROM missing
)
INSERT INTO dbo.product_batch (batch_id, sku, store_id, expiry_date, quantity)
SELECT batch_id, sku, store_id, expiry_date, quantity
FROM (
    SELECT store_id,
           sku,
           'B-' + store_id + '-' + sku + '-1' AS batch_id,
           DATEADD(day, CASE category
                            WHEN 'Dairy' THEN 14
                            WHEN 'Bakery' THEN 10
                            WHEN 'Beverages' THEN 45
                            WHEN 'Frozen' THEN 60
                            ELSE 90
                        END, @today) AS expiry_date,
           first_qty AS quantity
    FROM split
    WHERE first_qty > 0
    UNION ALL
    SELECT store_id,
           sku,
           'B-' + store_id + '-' + sku + '-2' AS batch_id,
           DATEADD(day, CASE category
                            WHEN 'Dairy' THEN 30
                            WHEN 'Bakery' THEN 20
                            WHEN 'Beverages' THEN 120
                            WHEN 'Frozen' THEN 150
                            ELSE 180
                        END, @today) AS expiry_date,
           quantity - first_qty AS quantity
    FROM split
    WHERE quantity - first_qty > 0
) AS batches;
