-- ============================================================
-- StudyMarket — MySQL Database Setup
-- Run once: mysql -u root -p < setup_db.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS studymarket
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE studymarket;

-- Tables are auto-created by Flask on first run.
-- This script just ensures the database exists.

-- Optional: dedicated user (recommended for production)
-- CREATE USER IF NOT EXISTS 'studymarket_user'@'localhost' IDENTIFIED BY 'strongpassword';
-- GRANT ALL PRIVILEGES ON studymarket.* TO 'studymarket_user'@'localhost';
-- FLUSH PRIVILEGES;

SELECT '✅ Database studymarket ready' AS status;
