CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(50)
);

INSERT INTO products (id, name, description, price, category) VALUES
(101, 'Mechanical Keyboard', 'Clicky switches', 120.00, 'Electronics'),
(102, 'Wireless Mouse', 'Ergonomic design', 45.00, 'Electronics'),
(103, 'Monitor Stand', 'Adjustable height', 30.00, 'Accessories');

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
