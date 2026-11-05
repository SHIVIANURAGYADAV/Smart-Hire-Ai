-- ============================================================
--  SMART HIRE AI  -  File 3 of 3: queries.sql
--  Ready-made queries to show in the viva / demo.
--  Run one by one in MySQL Workbench, or all:
--      mysql -u root -p smart_hire_ai < database/queries.sql
--
--  NOTE: Q16, Q17 and Q20 CHANGE data. Running Q16 a second time gives
--  "You have already applied" - that is the rule working. To reset
--  everything, run schema.sql and then data.sql again.
-- ============================================================
USE smart_hire_ai;

-- ---------- A. BASIC / JOIN QUERIES ----------

-- Q1. All open jobs with company, salary and required skills (VIEW + JOIN)
SELECT job_id, company, title, location, salary_lpa, required_skills
FROM v_job_listing
WHERE status = 'open'
ORDER BY salary_lpa DESC;

-- Q2. Which skills does candidate #1 have? (many-to-many JOIN)
SELECT u.name AS candidate, s.skill_name
FROM candidates c
JOIN users u            ON u.user_id = c.user_id
JOIN candidate_skills cs ON cs.candidate_id = c.candidate_id
JOIN skills s           ON s.skill_id = cs.skill_id
WHERE c.candidate_id = 1;

-- Q3. Jobs in Bengaluru paying more than 20 LPA
SELECT company, title, salary_lpa
FROM v_job_listing
WHERE location = 'Bengaluru' AND salary_lpa > 20 AND status = 'open';

-- ---------- B. THE SMART MATCHING PART ----------

-- Q4. Top 5 candidates for job #1 (the recruiter's ranked list, VIEW)
SELECT rank_no, candidate_name, experience_years, match_score, status
FROM v_ranked_candidates
WHERE job_id = 1
ORDER BY rank_no
LIMIT 5;

-- Q5. Same thing through a STORED PROCEDURE
CALL sp_top_candidates(1, 5);

-- Q6. Use the FUNCTION directly: score of candidate #1 for job #1
SELECT fn_match_score(1, 1) AS match_score_percent;

-- Q7. Best 5 open jobs for candidate #1 (recommendation, VIEW)
SELECT company, title, location, match_score
FROM v_candidate_job_match
WHERE candidate_id = 1
ORDER BY match_score DESC, salary_lpa DESC
LIMIT 5;

-- Q8. Skill gap: skills job #1 needs that candidate #1 is missing
SELECT s.skill_name AS missing_skill
FROM job_skills js
JOIN skills s ON s.skill_id = js.skill_id
WHERE js.job_id = 1
  AND js.skill_id NOT IN (SELECT skill_id FROM candidate_skills WHERE candidate_id = 1);

-- ---------- C. AGGREGATE QUERIES (GROUP BY / HAVING) ----------

-- Q9. Applications and average match score per company
SELECT company, open_jobs, total_applications, avg_match_score, selected
FROM v_company_stats
ORDER BY total_applications DESC;

-- Q10. Most demanded skills (how many jobs need each skill)
SELECT s.skill_name, COUNT(*) AS jobs_needing_it
FROM job_skills js
JOIN skills s ON s.skill_id = js.skill_id
GROUP BY s.skill_id, s.skill_name
ORDER BY jobs_needing_it DESC, s.skill_name
LIMIT 8;

-- Q11. Jobs that got more than 5 applications (HAVING)
SELECT c.name AS company, j.title, COUNT(a.application_id) AS applications
FROM jobs j
JOIN companies c ON c.company_id = j.company_id
JOIN applications a ON a.job_id = j.job_id
GROUP BY j.job_id, c.name, j.title
HAVING COUNT(a.application_id) > 5
ORDER BY applications DESC;

-- Q12. Application status summary
SELECT status, COUNT(*) AS total FROM applications GROUP BY status;

-- ---------- D. SUBQUERIES / LEFT JOIN ----------

-- Q13. Applications whose score is above the overall average (SUBQUERY)
SELECT candidate_name, job_title, company, match_score
FROM v_ranked_candidates
WHERE match_score > (SELECT AVG(match_score) FROM applications)
ORDER BY match_score DESC
LIMIT 10;

-- Q14. Candidates who have NOT applied anywhere (LEFT JOIN ... IS NULL)
SELECT u.name, c.location
FROM candidates c
JOIN users u ON u.user_id = c.user_id
LEFT JOIN applications a ON a.candidate_id = c.candidate_id
WHERE a.application_id IS NULL;

-- Q15. Jobs nobody has applied to yet
SELECT company, title FROM v_job_listing WHERE applicants = 0 AND status = 'open';

-- ---------- E. TRIGGER + PROCEDURE DEMO ----------

-- Q16. Apply through the procedure (candidate #1 applies to job #20).
--      The BEFORE INSERT trigger fills in match_score automatically.
CALL sp_apply_to_job(1, 20);
SELECT application_id, job_id, candidate_id, status, match_score
FROM applications WHERE candidate_id = 1 AND job_id = 20;

-- Q17. Change the status. The AFTER UPDATE trigger writes to application_log.
UPDATE applications SET status = 'Shortlisted'
WHERE candidate_id = 1 AND job_id = 20;
SELECT * FROM application_log ORDER BY log_id DESC LIMIT 3;

-- Q18. Business-rule trigger: this FAILS on purpose (no interview scheduled).
--      Expected error: "Schedule an interview before selecting this candidate."
-- UPDATE applications SET status = 'Selected' WHERE candidate_id = 1 AND job_id = 20;

-- Q19. Duplicate application is blocked. This FAILS on purpose:
--      "You have already applied to this job."
-- CALL sp_apply_to_job(1, 20);

-- Q20. Recalculate every score after skills changed
CALL sp_refresh_scores(NULL, NULL);

-- ---------- F. INDEXES ----------

-- Q21. Index demo. NOTE: with only 20 sample jobs MySQL may still choose a
--      full scan (type = ALL) because the table is tiny. The index
--      idx_jobs_location is listed under possible_keys and starts to be used
--      as soon as the table grows. Say this in the viva.
EXPLAIN SELECT * FROM jobs WHERE location = 'Bengaluru';
SHOW INDEX FROM applications;
