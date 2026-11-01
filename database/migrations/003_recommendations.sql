-- Sprint 4 (PB-25, 27, 33). Database Design v1.3, tables 17, 19, 20.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE dbo.recommendation (
    rec_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_recommendation PRIMARY KEY,
    store_id varchar(10) NOT NULL CONSTRAINT fk_recommendation_store REFERENCES dbo.store(store_id),
    sku varchar(20) NOT NULL CONSTRAINT fk_recommendation_product REFERENCES dbo.product(sku),
    batch_id varchar(30) NULL CONSTRAINT fk_recommendation_batch REFERENCES dbo.product_batch(batch_id),
    alert_id bigint NULL CONSTRAINT fk_recommendation_alert REFERENCES dbo.near_expiry_alert(alert_id),
    forecast_id bigint NULL CONSTRAINT fk_recommendation_forecast REFERENCES dbo.forecast(forecast_id),
    action_type varchar(15) NOT NULL CONSTRAINT ck_recommendation_action CHECK (action_type IN ('DISCOUNT','CLEARANCE','REDISTRIBUTION')),
    discount_pct decimal(5,2) NULL CONSTRAINT ck_recommendation_discount CHECK (discount_pct BETWEEN 0 AND 100),
    proposed_qty int NULL CONSTRAINT ck_recommendation_qty CHECK (proposed_qty > 0),
    reason nvarchar(300) NOT NULL,
    status varchar(12) NOT NULL CONSTRAINT ck_recommendation_status CHECK (status IN ('GENERATED','BLOCKED','PENDING','ACCEPTED','REJECTED')),
    created_at datetime2 NOT NULL CONSTRAINT df_recommendation_created DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_recommendation_store_status ON dbo.recommendation(store_id, status);

CREATE TABLE dbo.guardrail_result (
    result_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_guardrail_result PRIMARY KEY,
    rec_id bigint NOT NULL CONSTRAINT fk_guardrail_result_rec REFERENCES dbo.recommendation(rec_id),
    rule_id int NOT NULL CONSTRAINT fk_guardrail_result_rule REFERENCES dbo.guardrail_rule(rule_id),
    outcome varchar(10) NOT NULL CONSTRAINT ck_guardrail_result_outcome CHECK (outcome IN ('PASSED','ADJUSTED','BLOCKED')),
    original_value decimal(12,2) NULL,
    adjusted_value decimal(12,2) NULL,
    message nvarchar(200) NULL,
    checked_at datetime2 NOT NULL CONSTRAINT df_guardrail_result_checked DEFAULT SYSUTCDATETIME()
);

CREATE TABLE dbo.staff_decision (
    decision_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT pk_staff_decision PRIMARY KEY,
    rec_id bigint NOT NULL CONSTRAINT uq_staff_decision_rec UNIQUE CONSTRAINT fk_staff_decision_rec REFERENCES dbo.recommendation(rec_id),
    user_id int NOT NULL CONSTRAINT fk_staff_decision_user REFERENCES dbo.staff_user(user_id),
    decision varchar(10) NOT NULL CONSTRAINT ck_staff_decision CHECK (decision IN ('ACCEPT','REJECT')),
    decided_at datetime2 NOT NULL CONSTRAINT df_staff_decision_decided DEFAULT SYSUTCDATETIME()
);

COMMIT;
