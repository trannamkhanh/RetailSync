"""Read-only own-store latest forecast, batch stock and business-time sales."""
from sqlalchemy import text
from sqlalchemy.orm import Session


def latest_forecasts(session: Session, store: str, today, start, end) -> list[dict]:
    rows = session.execute(text("""
        WITH ranked AS (
            SELECT f.*, ROW_NUMBER() OVER (
                PARTITION BY f.sku ORDER BY f.created_at DESC, f.forecast_id DESC
            ) AS rank
            FROM dbo.forecast f WHERE f.store_id = CAST(:store AS varchar(10))
        ), stock AS (
            SELECT sku, SUM(CAST(quantity AS bigint)) AS sellable_stock
            FROM dbo.product_batch
            WHERE store_id = CAST(:store AS varchar(10)) AND expiry_date >= :today AND quantity > 0
            GROUP BY sku
        ), sold AS (
            SELECT i.sku, SUM(CASE WHEN t.txn_type = 'SALE' THEN CAST(i.qty AS bigint)
                                  ELSE -CAST(i.qty AS bigint) END) AS sold_last_7_days
            FROM dbo.pos_transaction t JOIN dbo.transaction_item i ON i.txn_id = t.txn_id
            WHERE t.store_id = CAST(:store AS varchar(10)) AND (t.status = 'OK' OR (t.txn_type = 'SALE' AND t.status = 'CANCELLED'))
              AND t.txn_type IN ('SALE', 'RETURN', 'CANCELLATION')
              AND t.effective_at >= :start AND t.effective_at < :end
            GROUP BY i.sku
        )
        SELECT f.sku, p.name, p.category, f.horizon_days, f.predicted_demand,
               COALESCE(s.sellable_stock,0) AS sellable_stock,
               f.surplus_shortage, f.balance_status, f.model_version, f.created_at,
               COALESCE(d.sold_last_7_days,0) AS sold_last_7_days
        FROM ranked f JOIN dbo.product p ON p.sku = f.sku
        LEFT JOIN stock s ON s.sku = f.sku LEFT JOIN sold d ON d.sku = f.sku
        WHERE f.rank = 1
        ORDER BY CASE f.balance_status WHEN 'SHORTAGE' THEN 0 WHEN 'SURPLUS' THEN 1 ELSE 2 END, f.sku
    """), {"store": store, "today": today, "start": start, "end": end})
    return [dict(row) for row in rows.mappings()]
