-- One photo per demo SKU, served from the SPA's own static files.
--
-- The value is a root-relative URL, not a file path: the browser loads it from
-- whichever origin serves the page (API on 5180 in production, Vite on 5173 in
-- dev), and the files live in web/public/products so `pnpm build` copies them to
-- web/dist/products. No image host is contacted.
--
-- The JPGs are real photos from Wikimedia Commons, downloaded by
-- api/tools/fetch_product_photos.py; web/public/products/ATTRIBUTION.md keeps the
-- author and licence of every file. The flat SVG illustrations stay in the same
-- folder but nothing references them any more.
--
-- Safe to run repeatedly: it only fills rows with no picture, or upgrades a row
-- that still points at the old illustration, so a URL edited by hand survives a
-- reseed.
UPDATE dbo.product SET image_url = N'/products/fresh-milk.jpg' WHERE sku = 'SKU-0001' AND (image_url IS NULL OR image_url = N'/products/fresh-milk.svg');
UPDATE dbo.product SET image_url = N'/products/yogurt.jpg' WHERE sku = 'SKU-0002' AND (image_url IS NULL OR image_url = N'/products/yogurt.svg');
UPDATE dbo.product SET image_url = N'/products/cheese.jpg' WHERE sku = 'SKU-0003' AND (image_url IS NULL OR image_url = N'/products/cheese.svg');
UPDATE dbo.product SET image_url = N'/products/bread.jpg' WHERE sku = 'SKU-0004' AND (image_url IS NULL OR image_url = N'/products/bread.svg');
UPDATE dbo.product SET image_url = N'/products/sponge-cake.jpg' WHERE sku = 'SKU-0005' AND (image_url IS NULL OR image_url = N'/products/sponge-cake.svg');
UPDATE dbo.product SET image_url = N'/products/butter-cookies.jpg' WHERE sku = 'SKU-0006' AND (image_url IS NULL OR image_url = N'/products/butter-cookies.svg');
UPDATE dbo.product SET image_url = N'/products/rice.jpg' WHERE sku = 'SKU-0007' AND (image_url IS NULL OR image_url = N'/products/rice.svg');
UPDATE dbo.product SET image_url = N'/products/instant-noodles.jpg' WHERE sku = 'SKU-0008' AND (image_url IS NULL OR image_url = N'/products/instant-noodles.svg');
UPDATE dbo.product SET image_url = N'/products/cooking-oil.jpg' WHERE sku = 'SKU-0009' AND (image_url IS NULL OR image_url = N'/products/cooking-oil.svg');
UPDATE dbo.product SET image_url = N'/products/water-spinach.jpg' WHERE sku = 'SKU-0010' AND (image_url IS NULL OR image_url = N'/products/water-spinach.svg');
UPDATE dbo.product SET image_url = N'/products/tomato.jpg' WHERE sku = 'SKU-0011' AND (image_url IS NULL OR image_url = N'/products/tomato.svg');
UPDATE dbo.product SET image_url = N'/products/banana.jpg' WHERE sku = 'SKU-0012' AND (image_url IS NULL OR image_url = N'/products/banana.svg');
UPDATE dbo.product SET image_url = N'/products/beer-can.jpg' WHERE sku = 'SKU-0013' AND (image_url IS NULL OR image_url = N'/products/beer-can.svg');
UPDATE dbo.product SET image_url = N'/products/soft-drink.jpg' WHERE sku = 'SKU-0014' AND (image_url IS NULL OR image_url = N'/products/soft-drink.svg');
UPDATE dbo.product SET image_url = N'/products/coffee.jpg' WHERE sku = 'SKU-0015' AND (image_url IS NULL OR image_url = N'/products/coffee.svg');
UPDATE dbo.product SET image_url = N'/products/laundry.jpg' WHERE sku = 'SKU-0016' AND (image_url IS NULL OR image_url = N'/products/laundry.svg');
UPDATE dbo.product SET image_url = N'/products/tissues.jpg' WHERE sku = 'SKU-0017' AND (image_url IS NULL OR image_url = N'/products/tissues.svg');
UPDATE dbo.product SET image_url = N'/products/dish-soap.jpg' WHERE sku = 'SKU-0018' AND (image_url IS NULL OR image_url = N'/products/dish-soap.svg');
UPDATE dbo.product SET image_url = N'/products/eggs.jpg' WHERE sku = 'SKU-0019' AND (image_url IS NULL OR image_url = N'/products/eggs.svg');
UPDATE dbo.product SET image_url = N'/products/drinking-yogurt.jpg' WHERE sku = 'SKU-0020' AND (image_url IS NULL OR image_url = N'/products/drinking-yogurt.svg');
UPDATE dbo.product SET image_url = N'/products/sandwich.jpg' WHERE sku = 'SKU-0021' AND (image_url IS NULL OR image_url = N'/products/sandwich.svg');
