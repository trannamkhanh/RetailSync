-- Demo catalog (PB-08-6): products, stock, accounts and default guardrail rules.
-- Safe to run repeatedly. Stores and POS terminals come from 001_demo_stores_pos.sql.
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0001')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0001', '8930000000011', N'Fresh milk 1L', 'Dairy', 32000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0002')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0002', '8930000000028', N'Yogurt 100g', 'Dairy', 7000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0003')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0003', '8930000000035', N'Cheese slices 200g', 'Dairy', 65000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0004')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0004', '8930000000042', N'Bread 400g', 'Bakery', 25000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0005')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0005', '8930000000059', N'Sponge cake 300g', 'Bakery', 45000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0006')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0006', '8930000000066', N'Butter cookies 200g', 'Bakery', 38000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0007')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0007', '8930000000073', N'Rice 5kg', 'Dry goods', 120000);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0008')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0008', '8930000000080', N'Instant noodles 75g', 'Dry goods', 4500);
IF NOT EXISTS (SELECT 1 FROM dbo.product WHERE sku = 'SKU-0009')
    INSERT dbo.product (sku, barcode, name, category, unit_price) VALUES ('SKU-0009', '8930000000097', N'Cooking oil 1L', 'Dry goods', 58000);

-- 27 rows: 3 stores x 9 SKUs. A row that already exists keeps its quantity.
INSERT dbo.inventory (store_id, sku, quantity)
SELECT s.store_id, p.sku,
       CASE s.store_id WHEN 'STORE-DN1' THEN 40 WHEN 'STORE-DN2' THEN 25 ELSE 15 END
FROM dbo.store s
CROSS JOIN dbo.product p
WHERE s.store_id IN ('STORE-DN1', 'STORE-DN2', 'STORE-DN3')
  AND p.sku IN ('SKU-0001', 'SKU-0002', 'SKU-0003', 'SKU-0004', 'SKU-0005',
                'SKU-0006', 'SKU-0007', 'SKU-0008', 'SKU-0009')
  AND NOT EXISTS (SELECT 1 FROM dbo.inventory i WHERE i.store_id = s.store_id AND i.sku = p.sku);

IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'staff_dn1')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('staff_dn1', N'Trần Minh Anh', 'STORE_STAFF', 'STORE-DN1', 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'staff_dn2')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('staff_dn2', N'Lê Thị Bình', 'STORE_STAFF', 'STORE-DN2', 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'staff_dn3')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('staff_dn3', N'Phạm Quốc Cường', 'STORE_STAFF', 'STORE-DN3', 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'manager_dn1')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('manager_dn1', N'Nguyễn Hoàng Dũng', 'STORE_MANAGER', 'STORE-DN1', 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'admin')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('admin', N'Quản trị hệ thống', 'ADMIN', NULL, 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'auditor')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('auditor', N'Kiểm toán viên', 'AUDITOR', NULL, 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'hq_operator')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('hq_operator', N'Điều hành HQ', 'HQ_OPERATOR', NULL, 1);
IF NOT EXISTS (SELECT 1 FROM dbo.staff_user WHERE username = 'pos_system')
    INSERT dbo.staff_user (username, full_name, role, store_id, is_active) VALUES ('pos_system', N'Hệ thống POS', 'POS_SYSTEM', NULL, 1);

-- DS-07 defaults. An empty category means every category.
IF NOT EXISTS (SELECT 1 FROM dbo.guardrail_rule WHERE rule_type = 'MIN_SHELF_LIFE' AND category IS NULL)
    INSERT dbo.guardrail_rule (rule_type, threshold, category, is_active) VALUES ('MIN_SHELF_LIFE', 1, NULL, 1);
IF NOT EXISTS (SELECT 1 FROM dbo.guardrail_rule WHERE rule_type = 'MAX_DISCOUNT' AND category IS NULL)
    INSERT dbo.guardrail_rule (rule_type, threshold, category, is_active) VALUES ('MAX_DISCOUNT', 50, NULL, 1);
IF NOT EXISTS (SELECT 1 FROM dbo.guardrail_rule WHERE rule_type = 'MIN_PRICE' AND category IS NULL)
    INSERT dbo.guardrail_rule (rule_type, threshold, category, is_active) VALUES ('MIN_PRICE', 1000, NULL, 1);
