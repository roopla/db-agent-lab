-- Sample inventory / purchasing data (MySQL). Runs once on an empty volume.
USE inventory;

CREATE TABLE suppliers (
  supplier_id   INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  country       VARCHAR(50)  NOT NULL,
  rating        TINYINT      NOT NULL COMMENT '1 (poor) to 5 (excellent)'
) COMMENT = 'Companies we buy stock from.';

CREATE TABLE warehouses (
  warehouse_id  INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  city          VARCHAR(50)  NOT NULL,
  capacity_units INT         NOT NULL
) COMMENT = 'Physical storage locations.';

CREATE TABLE purchase_orders (
  po_id         INT AUTO_INCREMENT PRIMARY KEY,
  supplier_id   INT NOT NULL,
  warehouse_id  INT NOT NULL,
  order_date    DATE NOT NULL,
  status        ENUM('open','received','cancelled') NOT NULL,
  total_usd     DECIMAL(12,2) NOT NULL,
  FOREIGN KEY (supplier_id)  REFERENCES suppliers(supplier_id),
  FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
) COMMENT = 'Orders placed with suppliers; total_usd is the full order value.';

INSERT INTO suppliers (name, country, rating) VALUES
 ('Acme Components', 'USA', 4), ('Nordic Supply AB', 'Sweden', 5),
 ('Shenzhen Parts Co', 'China', 3), ('Bavaria Industrial', 'Germany', 4),
 ('Andes Trading', 'Chile', 2);

INSERT INTO warehouses (name, city, capacity_units) VALUES
 ('East Hub', 'Newark', 50000), ('West Hub', 'Reno', 40000), ('Central DC', 'Dallas', 65000);

INSERT INTO purchase_orders (supplier_id, warehouse_id, order_date, status, total_usd) VALUES
 (1,1,'2026-01-08','received', 12500.00), (2,2,'2026-01-19','received',  8300.50),
 (3,3,'2026-02-02','received', 21400.00), (1,3,'2026-02-25','cancelled', 4000.00),
 (4,1,'2026-03-14','received', 15750.25), (5,2,'2026-04-03','received',  2900.00),
 (2,1,'2026-05-11','received',  9900.00), (3,2,'2026-06-20','received', 18800.00),
 (4,3,'2026-07-09','open',     11200.00), (1,2,'2026-08-17','open',      7600.75),
 (3,1,'2026-09-05','open',     24300.00), (2,3,'2026-09-28','open',      5100.00);
