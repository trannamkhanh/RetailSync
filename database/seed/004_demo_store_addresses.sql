-- Demo addresses for the three seeded stores. Safe to run repeatedly.
-- Streets match the sample customer addresses in the store web (app/geo.py) so the
-- demo distances and the addresses shown on the shop page stay consistent.
UPDATE dbo.store
SET address_text = N'123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng'
WHERE store_id = 'STORE-DN1' AND address_text IS NULL;

UPDATE dbo.store
SET address_text = N'456 Nguyễn Văn Linh, Phường Tân Chính, Quận Thanh Khê, Đà Nẵng'
WHERE store_id = 'STORE-DN2' AND address_text IS NULL;

UPDATE dbo.store
SET address_text = N'789 Ngô Quyền, Phường An Hải Bắc, Quận Sơn Trà, Đà Nẵng'
WHERE store_id = 'STORE-DN3' AND address_text IS NULL;
