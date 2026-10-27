SET lock_timeout = '5s';        -- fail fast rather than queue behind live traffic
SET statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS order_statuses (
    id   SMALLINT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE
);
INSERT INTO order_statuses (id, code)
VALUES (1, 'pending'), (2, 'paid'), (3, 'shipped')
ON CONFLICT (code) DO NOTHING;

-- Nullable, no default: metadata-only change, brief lock
ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_id SMALLINT;

-- Postgres has no "ADD CONSTRAINT IF NOT EXISTS", so guard it for idempotency.
-- NOT VALID = existing rows aren't scanned now (validated later in 0003)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'orders_status_id_fkey') THEN
    ALTER TABLE orders ADD CONSTRAINT orders_status_id_fkey
      FOREIGN KEY (status_id) REFERENCES order_statuses (id) NOT VALID;
  END IF;
END $$;

-- Keeps the OLD app working: it only writes `status` text, the trigger fills status_id
CREATE OR REPLACE FUNCTION orders_sync_status_id() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status THEN
    SELECT id INTO NEW.status_id FROM order_statuses WHERE code = NEW.status;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER orders_sync_status_id
  BEFORE INSERT OR UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION orders_sync_status_id();