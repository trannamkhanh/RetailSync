-- Demo data: 3 stores with 2 POS terminals each. Safe to run repeatedly.
IF NOT EXISTS (SELECT 1 FROM dbo.store WHERE store_id = 'STORE-DN1')
    INSERT dbo.store (store_id, name, latitude, longitude, region_id) VALUES ('STORE-DN1', N'Cửa hàng Hải Châu', 16.067800, 108.220800, 'DN');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN1-01')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN1-01', 'STORE-DN1', 'ACTIVE');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN1-02')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN1-02', 'STORE-DN1', 'ACTIVE');
IF NOT EXISTS (SELECT 1 FROM dbo.store WHERE store_id = 'STORE-DN2')
    INSERT dbo.store (store_id, name, latitude, longitude, region_id) VALUES ('STORE-DN2', N'Cửa hàng Thanh Khê', 16.061000, 108.180000, 'DN');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN2-01')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN2-01', 'STORE-DN2', 'ACTIVE');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN2-02')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN2-02', 'STORE-DN2', 'ACTIVE');
IF NOT EXISTS (SELECT 1 FROM dbo.store WHERE store_id = 'STORE-DN3')
    INSERT dbo.store (store_id, name, latitude, longitude, region_id) VALUES ('STORE-DN3', N'Cửa hàng Sơn Trà', 16.075000, 108.235000, 'DN');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN3-01')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN3-01', 'STORE-DN3', 'ACTIVE');
IF NOT EXISTS (SELECT 1 FROM dbo.pos_terminal WHERE pos_id = 'POS-DN3-02')
    INSERT dbo.pos_terminal (pos_id, store_id, status) VALUES ('POS-DN3-02', 'STORE-DN3', 'ACTIVE');
