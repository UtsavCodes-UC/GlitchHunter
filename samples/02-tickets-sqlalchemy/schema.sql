CREATE TABLE events (id serial PRIMARY KEY, name varchar(80) NOT NULL, seats_left int NOT NULL);
INSERT INTO events (name, seats_left) VALUES ('Concert', 1);
