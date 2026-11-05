-- ============================================================
--  SMART HIRE AI  -  DBMS Project
--  File 1 of 3: schema.sql
--  Creates: database, 10 tables, indexes, 1 function,
--           3 stored procedures, 3 triggers, 4 views
--  Works on: MySQL 8.0+  (and MariaDB 10.5+)
--  Run:      mysql -u root -p < database/schema.sql
-- ============================================================

DROP DATABASE IF EXISTS smart_hire_ai;
CREATE DATABASE smart_hire_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_hire_ai;

-- ------------------------------------------------------------
-- 1. TABLES  (normalized up to 3NF)
-- ------------------------------------------------------------

-- All logins live here. "role" decides what the person can do.
CREATE TABLE users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    email          VARCHAR(120) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    role           ENUM('candidate','recruiter','admin') NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- One recruiter account manages one company.
CREATE TABLE companies (
    company_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL UNIQUE,
    name        VARCHAR(100) NOT NULL UNIQUE,
    industry    VARCHAR(80)  NOT NULL,
    location    VARCHAR(80)  NOT NULL,
    website     VARCHAR(150),
    CONSTRAINT fk_company_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE candidates (
    candidate_id      INT AUTO_INCREMENT PRIMARY KEY,
    user_id           INT NOT NULL UNIQUE,
    experience_years  DECIMAL(4,1) NOT NULL DEFAULT 0,
    education         VARCHAR(100) NOT NULL,
    location          VARCHAR(80)  NOT NULL,
    resume_link       VARCHAR(200),
    CONSTRAINT chk_experience CHECK (experience_years >= 0),
    CONSTRAINT fk_candidate_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Master list of skills (no skill name is ever repeated).
CREATE TABLE skills (
    skill_id    INT AUTO_INCREMENT PRIMARY KEY,
    skill_name  VARCHAR(50) NOT NULL UNIQUE,
    category    VARCHAR(40) NOT NULL
) ENGINE=InnoDB;

-- Many-to-many: a candidate has many skills, a skill belongs to many candidates.
CREATE TABLE candidate_skills (
    candidate_id  INT NOT NULL,
    skill_id      INT NOT NULL,
    PRIMARY KEY (candidate_id, skill_id),
    CONSTRAINT fk_cs_candidate FOREIGN KEY (candidate_id)
        REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    CONSTRAINT fk_cs_skill FOREIGN KEY (skill_id)
        REFERENCES skills(skill_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE jobs (
    job_id               INT AUTO_INCREMENT PRIMARY KEY,
    company_id           INT NOT NULL,
    title                VARCHAR(100) NOT NULL,
    description          TEXT,
    experience_required  DECIMAL(4,1) NOT NULL DEFAULT 0,
    location             VARCHAR(80)  NOT NULL,
    salary_lpa           DECIMAL(6,2) NOT NULL,
    status               ENUM('open','closed') NOT NULL DEFAULT 'open',
    posted_date          DATE NOT NULL DEFAULT (CURRENT_DATE),
    CONSTRAINT chk_salary CHECK (salary_lpa > 0),
    CONSTRAINT fk_job_company FOREIGN KEY (company_id)
        REFERENCES companies(company_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Many-to-many: skills a job requires.
CREATE TABLE job_skills (
    job_id    INT NOT NULL,
    skill_id  INT NOT NULL,
    PRIMARY KEY (job_id, skill_id),
    CONSTRAINT fk_js_job FOREIGN KEY (job_id)
        REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT fk_js_skill FOREIGN KEY (skill_id)
        REFERENCES skills(skill_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- A candidate can apply to a job only once (UNIQUE job_id + candidate_id).
-- match_score is filled automatically by a trigger.
CREATE TABLE applications (
    application_id  INT AUTO_INCREMENT PRIMARY KEY,
    job_id          INT NOT NULL,
    candidate_id    INT NOT NULL,
    status          ENUM('Applied','Shortlisted','Rejected','Selected')
                    NOT NULL DEFAULT 'Applied',
    applied_date    DATE NOT NULL DEFAULT (CURRENT_DATE),
    match_score     DECIMAL(5,2) NOT NULL DEFAULT 0,
    UNIQUE KEY uq_one_application (job_id, candidate_id),
    CONSTRAINT fk_app_job FOREIGN KEY (job_id)
        REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT fk_app_candidate FOREIGN KEY (candidate_id)
        REFERENCES candidates(candidate_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE interviews (
    interview_id     INT AUTO_INCREMENT PRIMARY KEY,
    application_id   INT NOT NULL UNIQUE,
    interview_date   DATETIME NOT NULL,
    mode             ENUM('Online','Offline') NOT NULL DEFAULT 'Online',
    feedback         VARCHAR(255),
    result           ENUM('Pending','Passed','Failed') NOT NULL DEFAULT 'Pending',
    CONSTRAINT fk_int_app FOREIGN KEY (application_id)
        REFERENCES applications(application_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Audit trail. Filled by a trigger every time an application's status changes.
CREATE TABLE application_log (
    log_id          INT AUTO_INCREMENT PRIMARY KEY,
    application_id  INT NOT NULL,
    old_status      VARCHAR(20) NOT NULL,
    new_status      VARCHAR(20) NOT NULL,
    changed_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_log_app FOREIGN KEY (application_id)
        REFERENCES applications(application_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. INDEXES  (speed up the searches the app does most)
-- ------------------------------------------------------------
CREATE INDEX idx_jobs_location       ON jobs(location);
CREATE INDEX idx_jobs_status         ON jobs(status);
CREATE INDEX idx_candidates_location ON candidates(location);
CREATE INDEX idx_cs_skill            ON candidate_skills(skill_id);
CREATE INDEX idx_js_skill            ON job_skills(skill_id);
CREATE INDEX idx_app_candidate       ON applications(candidate_id);
CREATE INDEX idx_app_job_score       ON applications(job_id, match_score);

-- ------------------------------------------------------------
-- 3. FUNCTION + PROCEDURES + TRIGGERS  (the "smart" part)
-- ------------------------------------------------------------
DELIMITER $$

-- match_score = (skills the candidate has / skills the job needs) * 100
CREATE FUNCTION fn_match_score(p_candidate INT, p_job INT)
RETURNS DECIMAL(5,2)
READS SQL DATA
BEGIN
    DECLARE v_required INT DEFAULT 0;
    DECLARE v_matched  INT DEFAULT 0;

    SELECT COUNT(*) INTO v_required
    FROM job_skills WHERE job_id = p_job;

    IF v_required = 0 THEN
        RETURN 0;
    END IF;

    SELECT COUNT(*) INTO v_matched
    FROM job_skills js
    JOIN candidate_skills cs ON cs.skill_id = js.skill_id
    WHERE js.job_id = p_job AND cs.candidate_id = p_candidate;

    RETURN ROUND(v_matched / v_required * 100, 2);
END$$

-- Candidate applies to a job. Checks the rules, then inserts.
-- (The trigger below calculates the match score.)
CREATE PROCEDURE sp_apply_to_job(IN p_candidate INT, IN p_job INT)
BEGIN
    DECLARE v_status VARCHAR(10);

    SELECT status INTO v_status FROM jobs WHERE job_id = p_job;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This job does not exist.';
    END IF;
    IF v_status <> 'open' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This job is closed.';
    END IF;
    IF EXISTS (SELECT 1 FROM applications
               WHERE job_id = p_job AND candidate_id = p_candidate) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You have already applied to this job.';
    END IF;

    INSERT INTO applications (job_id, candidate_id) VALUES (p_job, p_candidate);
END$$

-- Recalculate scores (use after skills change).
-- NULL means "all":  CALL sp_refresh_scores(NULL, NULL);
CREATE PROCEDURE sp_refresh_scores(IN p_job INT, IN p_candidate INT)
BEGIN
    UPDATE applications
    SET match_score = fn_match_score(candidate_id, job_id)
    WHERE (p_job IS NULL OR job_id = p_job)
      AND (p_candidate IS NULL OR candidate_id = p_candidate);
END$$

-- Recruiter helper: top N candidates for one job.
CREATE PROCEDURE sp_top_candidates(IN p_job INT, IN p_limit INT)
BEGIN
    SELECT rank_no, candidate_name, experience_years, match_score, status
    FROM v_ranked_candidates
    WHERE job_id = p_job
    ORDER BY rank_no
    LIMIT p_limit;
END$$

-- TRIGGER 1: when an application is inserted, set its match score.
CREATE TRIGGER trg_application_before_insert
BEFORE INSERT ON applications
FOR EACH ROW
BEGIN
    SET NEW.match_score = fn_match_score(NEW.candidate_id, NEW.job_id);
END$$

-- TRIGGER 2: when the status changes, write a row in application_log.
CREATE TRIGGER trg_application_after_update
AFTER UPDATE ON applications
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO application_log (application_id, old_status, new_status)
        VALUES (NEW.application_id, OLD.status, NEW.status);
    END IF;
END$$

-- TRIGGER 3: business rule. A candidate cannot be "Selected" unless an
-- interview was scheduled first.
CREATE TRIGGER trg_application_before_select
BEFORE UPDATE ON applications
FOR EACH ROW
BEGIN
    IF NEW.status = 'Selected' AND OLD.status <> 'Selected'
       AND NOT EXISTS (SELECT 1 FROM interviews
                       WHERE application_id = NEW.application_id) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Schedule an interview before selecting this candidate.';
    END IF;
END$$

DELIMITER ;

-- ------------------------------------------------------------
-- 4. VIEWS
-- ------------------------------------------------------------

-- Open/closed jobs with company, required skills and applicant count.
CREATE VIEW v_job_listing AS
SELECT j.job_id, j.title, c.company_id, c.name AS company, c.industry,
       j.location, j.salary_lpa, j.experience_required, j.status, j.posted_date,
       j.description,
       (SELECT GROUP_CONCAT(s.skill_name ORDER BY s.skill_name SEPARATOR ', ')
          FROM job_skills js JOIN skills s ON s.skill_id = js.skill_id
         WHERE js.job_id = j.job_id) AS required_skills,
       (SELECT COUNT(*) FROM applications a WHERE a.job_id = j.job_id) AS applicants
FROM jobs j
JOIN companies c ON c.company_id = j.company_id;

-- The recruiter's "Top Matched Candidates" ranking, per job.
CREATE VIEW v_ranked_candidates AS
SELECT a.job_id, j.title AS job_title, c.company_id, c.name AS company,
       a.application_id, a.candidate_id, u.name AS candidate_name,
       cd.experience_years, cd.education, cd.location AS candidate_location,
       cd.resume_link, a.match_score, a.status, a.applied_date,
       RANK() OVER (PARTITION BY a.job_id
                    ORDER BY a.match_score DESC, cd.experience_years DESC) AS rank_no
FROM applications a
JOIN jobs j        ON j.job_id = a.job_id
JOIN companies c   ON c.company_id = j.company_id
JOIN candidates cd ON cd.candidate_id = a.candidate_id
JOIN users u       ON u.user_id = cd.user_id;

-- Every candidate vs every OPEN job with a score (for "Recommended jobs").
CREATE VIEW v_candidate_job_match AS
SELECT cd.candidate_id, j.job_id, j.title, c.name AS company, j.location,
       j.salary_lpa, j.experience_required,
       ROUND(100 * COUNT(cs.skill_id) /
             NULLIF((SELECT COUNT(*) FROM job_skills x WHERE x.job_id = j.job_id), 0), 2)
             AS match_score
FROM candidates cd
CROSS JOIN jobs j
JOIN companies c ON c.company_id = j.company_id
LEFT JOIN job_skills js       ON js.job_id = j.job_id
LEFT JOIN candidate_skills cs ON cs.candidate_id = cd.candidate_id
                             AND cs.skill_id = js.skill_id
WHERE j.status = 'open'
GROUP BY cd.candidate_id, j.job_id, j.title, c.name, j.location,
         j.salary_lpa, j.experience_required;

-- One line per company for the admin dashboard.
CREATE VIEW v_company_stats AS
SELECT c.company_id, c.name AS company, c.industry, c.location,
       (SELECT COUNT(*) FROM jobs j WHERE j.company_id = c.company_id AND j.status = 'open')
            AS open_jobs,
       (SELECT COUNT(*) FROM applications a JOIN jobs j ON j.job_id = a.job_id
         WHERE j.company_id = c.company_id) AS total_applications,
       (SELECT ROUND(AVG(a.match_score), 1) FROM applications a JOIN jobs j ON j.job_id = a.job_id
         WHERE j.company_id = c.company_id) AS avg_match_score,
       (SELECT COUNT(*) FROM applications a JOIN jobs j ON j.job_id = a.job_id
         WHERE j.company_id = c.company_id AND a.status = 'Selected') AS selected
FROM companies c;
