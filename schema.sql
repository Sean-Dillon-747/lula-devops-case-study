-- Baseline schema, loaded into Postgres on first start (via docker-compose).
-- Your migration should evolve THIS table safely under live traffic.

CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    amount      NUMERIC(12, 2) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A little seed data so there's something to migrate.
INSERT INTO orders (amount, status)
SELECT
    (random() * 1000)::numeric(12, 2),
    (ARRAY['pending', 'paid', 'shipped'])[1 + floor(random() * 3)]
FROM generate_series(1, 20);
