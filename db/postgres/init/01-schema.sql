-- Sample e-commerce schema with comments (the agent reads these comments
-- through the list_tables tool, so good comments = better SQL).

CREATE TABLE customers (
    customer_id  SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    city         TEXT NOT NULL,
    country      TEXT NOT NULL,
    signup_date  DATE NOT NULL
);
COMMENT ON TABLE customers IS 'People who have an account in the shop.';

CREATE TABLE products (
    product_id   SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_price   NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    in_stock     INTEGER NOT NULL DEFAULT 0
);
COMMENT ON TABLE products IS 'Catalogue of items for sale. unit_price is in USD.';

CREATE TABLE orders (
    order_id     SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date   DATE NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending','shipped','delivered','cancelled'))
);
COMMENT ON TABLE orders IS 'One row per order. Order value = SUM(order_items.quantity * order_items.unit_price).';

CREATE TABLE order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10,2) NOT NULL
);
COMMENT ON TABLE order_items IS 'Line items. unit_price is the price at time of purchase (may differ from products.unit_price).';

INSERT INTO customers (full_name, email, city, country, signup_date) VALUES
 ('Ava Patel',      'ava.patel@example.com',      'Austin',     'USA',     '2025-01-14'),
 ('Liam Chen',      'liam.chen@example.com',      'Toronto',    'Canada',  '2025-02-03'),
 ('Sofia Rossi',    'sofia.rossi@example.com',    'Milan',      'Italy',   '2025-02-21'),
 ('Noah Williams',  'noah.w@example.com',         'Seattle',    'USA',     '2025-03-09'),
 ('Mia Müller',     'mia.mueller@example.com',    'Berlin',     'Germany', '2025-04-17'),
 ('Ethan Brown',    'ethan.brown@example.com',    'Denver',     'USA',     '2025-05-02'),
 ('Zara Khan',      'zara.khan@example.com',      'London',     'UK',      '2025-06-11'),
 ('Lucas Silva',    'lucas.silva@example.com',    'São Paulo',  'Brazil',  '2025-07-25'),
 ('Emma Dubois',    'emma.dubois@example.com',    'Paris',      'France',  '2025-09-05'),
 ('Oliver Smith',   'oliver.smith@example.com',   'Chicago',    'USA',     '2025-11-19');

INSERT INTO products (name, category, unit_price, in_stock) VALUES
 ('Wireless Mouse',        'Electronics', 24.99, 120),
 ('Mechanical Keyboard',   'Electronics', 89.00,  45),
 ('27" Monitor',           'Electronics', 249.00, 18),
 ('USB-C Hub',             'Electronics', 39.50,  75),
 ('Standing Desk',         'Furniture',   429.00,  6),
 ('Ergonomic Chair',       'Furniture',   315.00, 11),
 ('Desk Lamp',             'Furniture',    34.00, 60),
 ('Notebook (A5, 3-pack)', 'Stationery',   12.00, 300),
 ('Gel Pens (10-pack)',    'Stationery',    9.50, 250),
 ('Coffee Beans 1kg',      'Grocery',      21.00,   0);

INSERT INTO orders (customer_id, order_date, status) VALUES
 (1, '2026-01-05', 'delivered'), (2, '2026-01-12', 'delivered'),
 (3, '2026-02-02', 'delivered'), (1, '2026-02-18', 'delivered'),
 (4, '2026-03-03', 'cancelled'), (5, '2026-03-21', 'delivered'),
 (6, '2026-04-09', 'delivered'), (7, '2026-04-30', 'shipped'),
 (2, '2026-05-14', 'delivered'), (8, '2026-06-01', 'delivered'),
 (9, '2026-06-22', 'shipped'),   (1, '2026-07-07', 'delivered'),
 (10,'2026-08-15', 'pending'),   (4, '2026-08-29', 'delivered'),
 (3, '2026-09-10', 'shipped'),   (6, '2026-09-25', 'pending');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
 (1, 1, 2, 24.99), (1, 8, 3, 12.00),
 (2, 2, 1, 89.00), (2, 4, 1, 39.50),
 (3, 5, 1, 429.00),
 (4, 3, 2, 249.00), (4, 7, 1, 34.00),
 (5, 6, 1, 315.00),
 (6, 2, 1, 85.00), (6, 1, 1, 24.99), (6, 9, 2, 9.50),
 (7, 10, 4, 21.00),
 (8, 6, 1, 299.00), (8, 7, 2, 34.00),
 (9, 3, 1, 249.00),
 (10, 4, 2, 39.50), (10, 8, 5, 12.00),
 (11, 5, 1, 409.00),
 (12, 2, 1, 89.00), (12, 9, 3, 9.50),
 (13, 1, 1, 24.99),
 (14, 10, 2, 21.00), (14, 8, 2, 12.00),
 (15, 3, 1, 239.00), (15, 4, 1, 39.50),
 (16, 7, 3, 34.00);
