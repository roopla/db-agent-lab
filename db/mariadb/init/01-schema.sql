-- Sample customer-support data (MariaDB). Runs once on an empty volume.
USE support;

CREATE TABLE support_agents (
  agent_id   INT AUTO_INCREMENT PRIMARY KEY,
  full_name  VARCHAR(100) NOT NULL,
  team       VARCHAR(30)  NOT NULL COMMENT 'billing, technical or general',
  hired_on   DATE NOT NULL
) COMMENT = 'Support staff who handle tickets.';

CREATE TABLE tickets (
  ticket_id      INT AUTO_INCREMENT PRIMARY KEY,
  agent_id       INT NULL,
  customer_email VARCHAR(120) NOT NULL,
  subject        VARCHAR(200) NOT NULL,
  priority       ENUM('low','medium','high','urgent') NOT NULL,
  status         ENUM('open','pending','resolved','closed') NOT NULL,
  opened_at      DATETIME NOT NULL,
  resolved_at    DATETIME NULL COMMENT 'NULL while the ticket is unresolved',
  FOREIGN KEY (agent_id) REFERENCES support_agents(agent_id)
) COMMENT = 'Customer support tickets. Resolution time = resolved_at - opened_at.';

INSERT INTO support_agents (full_name, team, hired_on) VALUES
 ('Priya Nair','billing','2024-03-01'), ('Marco Diaz','technical','2023-11-15'),
 ('Hannah Lee','technical','2025-02-10'), ('Tom Becker','general','2022-07-20');

INSERT INTO tickets (agent_id, customer_email, subject, priority, status, opened_at, resolved_at) VALUES
 (1,'ava.patel@example.com','Charged twice for order','high','resolved','2026-08-02 09:15','2026-08-02 13:40'),
 (2,'liam.chen@example.com','Cannot log in','urgent','resolved','2026-08-05 08:00','2026-08-05 09:10'),
 (3,'sofia.rossi@example.com','Monitor arrived damaged','medium','closed','2026-08-11 14:20','2026-08-13 10:00'),
 (4,'noah.w@example.com','Change delivery address','low','resolved','2026-08-19 11:05','2026-08-19 16:30'),
 (2,'mia.mueller@example.com','App crashes on checkout','high','pending','2026-09-03 10:45',NULL),
 (1,'ethan.brown@example.com','Refund status?','medium','open','2026-09-12 15:00',NULL),
 (NULL,'zara.khan@example.com','Wrong item received','high','open','2026-09-20 09:30',NULL),
 (3,'lucas.silva@example.com','Password reset email missing','urgent','resolved','2026-09-24 07:50','2026-09-24 08:20'),
 (NULL,'emma.dubois@example.com','Invoice copy request','low','open','2026-09-29 12:10',NULL);
