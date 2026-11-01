-- HQ mock database (not part of RTS_DB). Database Design v1.3, tables 21, 22.
CREATE TABLE dbo.hq_sync_batch (
    sync_batch_id varchar(40) NOT NULL CONSTRAINT pk_hq_sync_batch PRIMARY KEY,
    store_id varchar(10) NOT NULL,
    txn_count int NOT NULL,
    received_at datetime2 NOT NULL CONSTRAINT df_hq_sync_batch_received DEFAULT SYSUTCDATETIME(),
    duplicate_count int NOT NULL CONSTRAINT df_hq_sync_batch_duplicates DEFAULT 0,
    payload_hash char(64) NOT NULL
);

CREATE TABLE dbo.hq_sales_total (
    store_id varchar(10) NOT NULL,
    sku varchar(20) NOT NULL,
    sold_qty int NOT NULL,
    returned_qty int NOT NULL,
    net_revenue decimal(14,2) NOT NULL,
    CONSTRAINT pk_hq_sales_total PRIMARY KEY (store_id, sku)
);
