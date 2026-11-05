# Smart Hire AI - DBMS Project

A recruitment database. Companies post jobs, candidates apply, and the **database itself** calculates a match score
(matching skills ÷ required skills × 100) and ranks candidates for the recruiter.

Sample data: **10 top companies** (TCS, Infosys, Wipro, HCLTech, Accenture, Google, Microsoft, Amazon, Tech Mahindra,
Cognizant), 20 jobs, 30 candidates, 26 skills, 93 applications.
All jobs, candidates and applications are **dummy data for the project, not real openings**.

## Folder

```
smart_hire_ai/
├── database/
│   ├── schema.sql    <- tables, indexes, function, procedures, triggers, views
│   ├── data.sql      <- sample data for the 10 companies
│   └── queries.sql   <- 21 ready queries for the viva
└── app/
    ├── app.py        <- Flask backend (calls the database)
    ├── templates/    <- HTML pages
    ├── static/style.css
    └── requirements.txt
```

## How to run (5 minutes)

**1. Install:** MySQL 8.0+ (with MySQL Workbench) and Python 3.9+.

**2. Create the database** (pick one way):
- Terminal: `mysql -u root -p < database/schema.sql` then `mysql -u root -p < database/data.sql`
- Or in MySQL Workbench: open `schema.sql` -> run (lightning icon), then open `data.sql` -> run.

**3. Start the app:**
```
cd app
pip install -r requirements.txt
python app.py
```
Open **http://127.0.0.1:5000**

If your MySQL root user has a password, set it first:
- Windows CMD: `set DB_PASSWORD=yourpassword`
- PowerShell: `$env:DB_PASSWORD="yourpassword"`
- Mac/Linux: `export DB_PASSWORD=yourpassword`

(Other settings if needed: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`.)

## Demo logins

| Role | Email | Password |
|---|---|---|
| Candidate | aarav.sharma@demo.com (any candidate: firstname.lastname@demo.com) | password123 |
| Recruiter (TCS) | hr.tcs@demo.com | password123 |
| Recruiter (Google) | hr.google@demo.com | password123 |
| Admin | admin@demo.com | admin123 |

Other recruiters: `hr.infosys`, `hr.wipro`, `hr.hcl`, `hr.accenture`, `hr.microsoft`, `hr.amazon`, `hr.techm`,
`hr.cognizant` (all `@demo.com`).

## What each role can do

- **Candidate:** browse and filter jobs, see own match score on every job, apply, get recommended jobs, edit skills
  (scores recalculate automatically), track applications and interviews.
- **Recruiter:** post jobs with required skills, open the **ranked candidate list** for each job, shortlist / reject /
  select, schedule interviews, close or reopen jobs.
- **Admin:** totals, per-company statistics, most demanded skills, recent status changes (audit log).
- **DBMS Demo page** (top menu): runs 9 real queries live and shows the SQL and the result. Use it in your viva.

## DBMS concepts and where to find them

| Concept | Where |
|---|---|
| ER design, 3NF, PK / FK / UNIQUE / CHECK | `schema.sql`, tables section |
| Many-to-many with junction tables | `candidate_skills`, `job_skills` |
| Function | `fn_match_score` |
| Stored procedures | `sp_apply_to_job`, `sp_refresh_scores`, `sp_top_candidates` |
| Triggers | `trg_application_before_insert` (sets score), `trg_application_after_update` (audit log), `trg_application_before_select` (business rule) |
| Views | `v_ranked_candidates` (uses `RANK()`), `v_job_listing`, `v_candidate_job_match`, `v_company_stats` |
| Indexes | end of the tables section in `schema.sql` |
| Joins, GROUP BY, HAVING, subqueries, LEFT JOIN | `queries.sql` |

## Explaining the "AI" in the viva

The matching is a transparent, rule-based score done in SQL: `matching skills ÷ required skills × 100`.
It is explainable (a recruiter can see exactly which skills matched or are missing) and runs inside the database.
It is not a machine-learning model. Say this clearly; it is a strength for a DBMS project.

## Good to know

- Needs **MySQL 8.0+** (the ranking view uses the `RANK()` window function).
- `queries.sql` Q16, Q17 and Q20 change data. To reset everything, run `schema.sql` and then `data.sql` again.
- This is a college project: no email verification, CSRF protection or production hardening. Change `SECRET_KEY`
  before putting it anywhere public.
