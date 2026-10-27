SET lock_timeout = '5s';

-- Reverse order of the up. Safe: the old app never reads status_id.
DROP TRIGGER IF EXISTS orders_sync_status_id ON orders;
DROP FUNCTION IF EXISTS orders_sync_status_id();
ALTER TABLE orders DROP COLUMN IF EXISTS status_id;   -- also drops the FK
DROP TABLE IF EXISTS order_statuses;