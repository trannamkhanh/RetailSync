-- Sprint 3 (PB-14, 20, 21, 22). Database Design v1.3, tables 7, 13-16.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE dbo.product_batch (
    batch_id varchar(30) NOT NULL CONSTRAINT pk_product_batch PRIMARY KEY,
    sku varchar(20) NOT NULL CONSTRAINT fk_product_batch_product REFERENCES dbo.product(sku),
    store_id varchar(10) NOT NULL CONSTRAINT fk_product_batch_store REFERENCES dbo.store(store_id),
    expiry_date date NOT NULL,
    quantity int NOT NULL CONSTRAINT ck_product_batch_quantity CHECK (quantity >= 0),
    received_at datetime2 NOT NULL CONSTRAINT df_product_batch_received DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_product_batch_fefo ON dbo.product_batch(store_id, sku, expiry_date);

ALTER TABLE dbo.inventory_movement ADD CONSTRAINT fk_inventory_movement_batch FOREIGN KEY (batch_id) REFERENCES dbo.product_batch(batch_id);

CREATE TABLE dbo.sales_summary_line (
    line_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_sales_summary_line PRIMARY KEY,
    sync_batch_id varchar(40) NOT NULL CONSTRAINT fk_sales_summary_line_batch REFERENCES dbo.sync_batch(sync_batch_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_sales_summary_line_product REFERENCES dbo.product(sku),
    sold_qty int NOT NULL,
    returned_qty int NOT NULL,
    net_revenue decimal(14,2) NOT NULL,
    CONSTRAINT uq_sales_summary_line UNIQUE (sync_batch_id, sku)
);

CREATE TABLE dbo.near_expiry_config (
    category varchar(50) NOT NULL CONSTRAINT pk_near_expiry_config PRIMARY KEY,
    threshold_days int NOT NULL CONSTRAINT ck_near_expiry_config_days CHECK (threshold_days >= 0),
    updated_by int NULL CONSTRAINT fk_near_expiry_config_user REFERENCES dbo.staff_user(user_id),
    updated_at datetime2 NOT NULL CONSTRAINT df_near_expiry_config_updated DEFAULT SYSUTCDATETIME()
);

CREATE TABLE dbo.near_expiry_alert (
    alert_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_near_expiry_alert PRIMARY KEY,
    batch_id varchar(30) NOT NULL CONSTRAINT fk_near_expiry_alert_batch REFERENCES dbo.product_batch(batch_id),
    store_id varchar(10) NOT NULL CONSTRAINT fk_near_expiry_alert_store REFERENCES dbo.store(store_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_near_expiry_alert_product REFERENCES dbo.product(sku),
    days_to_expiry int NOT NULL,
    remaining_qty int NOT NULL,
    alert_type varchar(12) NOT NULL CONSTRAINT ck_near_expiry_alert_type CHECK (alert_type IN ('NEAR_EXPIRY','EXPIRED')),
    status varchar(10) NOT NULL CONSTRAINT ck_near_expiry_alert_status CHECK (status IN ('OPEN','RESOLVED')),
    created_at datetime2 NOT NULL CONSTRAINT df_near_expiry_alert_created DEFAULT SYSUTCDATETIME()
);
CREATE UNIQUE INDEX uq_near_expiry_alert_open ON dbo.near_expiry_alert(batch_id) WHERE status = 'OPEN';

CREATE TABLE dbo.forecast (
    forecast_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_forecast PRIMARY KEY,
    store_id varchar(10) NOT NULL CONSTRAINT fk_forecast_store REFERENCES dbo.store(store_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_forecast_product REFERENCES dbo.product(sku),
    horizon_days int NOT NULL,
    predicted_demand decimal(10,2) NOT NULL,
    surplus_shortage decimal(10,2) NOT NULL,
    balance_status varchar(10) NOT NULL CONSTRAINT ck_forecast_balance CHECK (balance_status IN ('SURPLUS','SHORTAGE','BALANCED')),
    model_version varchar(30) NOT NULL,
    created_at datetime2 NOT NULL CONSTRAINT df_forecast_created DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_forecast_store_sku ON dbo.forecast(store_id, sku, created_at);

COMMIT;
