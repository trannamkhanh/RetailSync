-- Sprint 2 (PB-01). Database Design v1.3, tables 2-6, 8-13, 18.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE dbo.store (
    store_id varchar(10) NOT NULL CONSTRAINT pk_store PRIMARY KEY,
    name nvarchar(100) NOT NULL,
    latitude decimal(9,6) NOT NULL CONSTRAINT ck_store_latitude CHECK (latitude BETWEEN -90 AND 90),
    longitude decimal(9,6) NOT NULL CONSTRAINT ck_store_longitude CHECK (longitude BETWEEN -180 AND 180),
    region_id varchar(10) NOT NULL,
    is_active bit NOT NULL CONSTRAINT df_store_active DEFAULT 1
);

CREATE TABLE dbo.pos_terminal (
    pos_id varchar(20) NOT NULL CONSTRAINT pk_pos_terminal PRIMARY KEY,
    store_id varchar(10) NOT NULL CONSTRAINT fk_pos_terminal_store REFERENCES dbo.store(store_id),
    status varchar(10) NOT NULL CONSTRAINT ck_pos_terminal_status CHECK (status IN ('ACTIVE','INACTIVE')),
    registered_at datetime2 NOT NULL CONSTRAINT df_pos_terminal_registered DEFAULT SYSUTCDATETIME(),
    cert_fingerprint char(64) NULL
);
CREATE UNIQUE INDEX uq_pos_terminal_cert ON dbo.pos_terminal(cert_fingerprint) WHERE cert_fingerprint IS NOT NULL;

CREATE TABLE dbo.staff_user (
    user_id int IDENTITY(1,1) NOT NULL CONSTRAINT pk_staff_user PRIMARY KEY,
    username varchar(50) NOT NULL CONSTRAINT uq_staff_user_username UNIQUE,
    full_name nvarchar(100) NOT NULL,
    role varchar(20) NOT NULL CONSTRAINT ck_staff_user_role CHECK (role IN ('STORE_STAFF','STORE_MANAGER','HQ_OPERATOR','ADMIN','AUDITOR','POS_SYSTEM')),
    store_id varchar(10) NULL CONSTRAINT fk_staff_user_store REFERENCES dbo.store(store_id),
    is_active bit NOT NULL CONSTRAINT df_staff_user_active DEFAULT 1
);

CREATE TABLE dbo.audit_log (
    audit_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_audit_log PRIMARY KEY,
    user_id int NULL CONSTRAINT fk_audit_log_user REFERENCES dbo.staff_user(user_id),
    action varchar(50) NOT NULL,
    entity_name varchar(50) NOT NULL,
    entity_key varchar(50) NULL,
    details nvarchar(500) NULL,
    created_at datetime2 NOT NULL CONSTRAINT df_audit_log_created DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_audit_log_created ON dbo.audit_log(created_at);

CREATE TABLE dbo.product (
    sku varchar(20) NOT NULL CONSTRAINT pk_product PRIMARY KEY,
    barcode varchar(30) NOT NULL CONSTRAINT uq_product_barcode UNIQUE,
    name nvarchar(150) NOT NULL,
    category varchar(50) NOT NULL,
    unit_price decimal(12,2) NOT NULL CONSTRAINT ck_product_price CHECK (unit_price >= 0)
);

CREATE TABLE dbo.inventory (
    store_id varchar(10) NOT NULL CONSTRAINT fk_inventory_store REFERENCES dbo.store(store_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_inventory_product REFERENCES dbo.product(sku),
    quantity int NOT NULL CONSTRAINT ck_inventory_quantity CHECK (quantity >= 0),
    updated_at datetime2 NOT NULL CONSTRAINT df_inventory_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_inventory PRIMARY KEY (store_id, sku)
);

CREATE TABLE dbo.sync_batch (
    sync_batch_id varchar(40) NOT NULL CONSTRAINT pk_sync_batch PRIMARY KEY,
    store_id varchar(10) NOT NULL CONSTRAINT fk_sync_batch_store REFERENCES dbo.store(store_id),
    period_start datetime2 NOT NULL,
    period_end datetime2 NOT NULL,
    txn_count int NOT NULL,
    payload_bytes int NULL,
    raw_bytes int NULL,
    status varchar(10) NOT NULL CONSTRAINT ck_sync_batch_status CHECK (status IN ('PENDING','SENT','ACKED','FAILED')),
    attempts int NOT NULL CONSTRAINT df_sync_batch_attempts DEFAULT 0,
    last_error nvarchar(200) NULL,
    next_retry_at datetime2 NULL,
    created_at datetime2 NOT NULL CONSTRAINT df_sync_batch_created DEFAULT SYSUTCDATETIME(),
    acked_at datetime2 NULL
);
CREATE INDEX ix_sync_batch_status ON dbo.sync_batch(status, created_at);

CREATE TABLE dbo.pos_transaction (
    txn_id varchar(40) NOT NULL CONSTRAINT pk_pos_transaction PRIMARY KEY,
    store_id varchar(10) NOT NULL CONSTRAINT fk_pos_transaction_store REFERENCES dbo.store(store_id),
    pos_id varchar(20) NOT NULL CONSTRAINT fk_pos_transaction_pos REFERENCES dbo.pos_terminal(pos_id),
    txn_type varchar(15) NOT NULL CONSTRAINT ck_pos_transaction_type CHECK (txn_type IN ('SALE','RETURN','CANCELLATION')),
    ref_txn_id varchar(40) NULL CONSTRAINT fk_pos_transaction_ref REFERENCES dbo.pos_transaction(txn_id),
    status varchar(12) NOT NULL CONSTRAINT ck_pos_transaction_status CHECK (status IN ('OK','CANCELLED')),
    sync_batch_id varchar(40) NULL CONSTRAINT fk_pos_transaction_batch REFERENCES dbo.sync_batch(sync_batch_id),
    payload_hash char(64) NOT NULL,
    created_at datetime2 NOT NULL CONSTRAINT df_pos_transaction_created DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_pos_transaction_unbatched ON dbo.pos_transaction(store_id, created_at) WHERE sync_batch_id IS NULL;
CREATE INDEX ix_pos_transaction_ref ON dbo.pos_transaction(ref_txn_id) WHERE ref_txn_id IS NOT NULL;

CREATE TABLE dbo.transaction_item (
    item_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_transaction_item PRIMARY KEY,
    txn_id varchar(40) NOT NULL CONSTRAINT fk_transaction_item_txn REFERENCES dbo.pos_transaction(txn_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_transaction_item_product REFERENCES dbo.product(sku),
    qty int NOT NULL CONSTRAINT ck_transaction_item_qty CHECK (qty > 0),
    unit_price decimal(12,2) NOT NULL CONSTRAINT ck_transaction_item_price CHECK (unit_price >= 0)
);
CREATE INDEX ix_transaction_item_txn ON dbo.transaction_item(txn_id);

CREATE TABLE dbo.inventory_movement (
    movement_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_inventory_movement PRIMARY KEY,
    store_id varchar(10) NOT NULL,
    sku varchar(20) NOT NULL,
    movement_type varchar(20) NOT NULL CONSTRAINT ck_inventory_movement_type CHECK (movement_type IN ('SALE','RETURN','CANCELLATION','ADJUSTMENT','STOCK_RECEIVED','TRANSFER_IN','TRANSFER_OUT')),
    quantity int NOT NULL,
    txn_id varchar(40) NULL CONSTRAINT fk_inventory_movement_txn REFERENCES dbo.pos_transaction(txn_id),
    batch_id varchar(30) NULL,
    reason nvarchar(200) NULL,
    created_by int NULL CONSTRAINT fk_inventory_movement_user REFERENCES dbo.staff_user(user_id),
    created_at datetime2 NOT NULL CONSTRAINT df_inventory_movement_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_inventory_movement_inventory FOREIGN KEY (store_id, sku) REFERENCES dbo.inventory(store_id, sku)
);
CREATE INDEX ix_inventory_movement_txn ON dbo.inventory_movement(txn_id) WHERE txn_id IS NOT NULL;

CREATE TABLE dbo.guardrail_rule (
    rule_id int IDENTITY(1,1) NOT NULL CONSTRAINT pk_guardrail_rule PRIMARY KEY,
    rule_type varchar(20) NOT NULL CONSTRAINT ck_guardrail_rule_type CHECK (rule_type IN ('MAX_DISCOUNT','MIN_PRICE','MIN_SHELF_LIFE')),
    threshold decimal(12,2) NOT NULL CONSTRAINT ck_guardrail_rule_threshold CHECK (threshold >= 0),
    category varchar(50) NULL,
    is_active bit NOT NULL CONSTRAINT df_guardrail_rule_active DEFAULT 1,
    updated_by int NULL CONSTRAINT fk_guardrail_rule_user REFERENCES dbo.staff_user(user_id),
    updated_at datetime2 NOT NULL CONSTRAINT df_guardrail_rule_updated DEFAULT SYSUTCDATETIME()
);

COMMIT;
