CREATE DATABASE IF NOT EXISTS assignmentsdb;
USE assignmentsdb;

CREATE TABLE IF NOT EXISTS answers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100),
    assignment VARCHAR(100),
    question VARCHAR(100),
    answer TEXT,
    grade INT,
    feedback TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
