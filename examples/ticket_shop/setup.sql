DROP TABLE IF EXISTS seats;
CREATE TABLE seats (event_id int PRIMARY KEY, seats_left int NOT NULL);
INSERT INTO seats VALUES (1, 3);
