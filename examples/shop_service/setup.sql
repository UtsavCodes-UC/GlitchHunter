DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
CREATE TABLE products (id integer PRIMARY KEY, name varchar NOT NULL, stock integer NOT NULL);
CREATE TABLE orders (id serial PRIMARY KEY, product_id integer REFERENCES products(id), quantity integer NOT NULL);
INSERT INTO products VALUES (1, 'Widget', 3);
