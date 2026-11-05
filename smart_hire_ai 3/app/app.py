"""
Smart Hire AI - Flask web app (DBMS project)

All the "smart" work (match score, ranking, rules, audit log) happens INSIDE
the database: views, a function, stored procedures and triggers from
database/schema.sql. This file only calls them and shows the results.

Run:  python app.py      ->  open http://127.0.0.1:5000
"""
import os
from functools import wraps

import pymysql
from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-for-real-use")

# ----- database settings: change here or set environment variables -----
DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", ""),
    database=os.environ.get("DB_NAME", "smart_hire_ai"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)


# =====================================================================
#  Database helpers
# =====================================================================
def db():
    if "db" not in g:
        g.db = pymysql.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    """SELECT helper. Returns a list of dicts (or one dict / None)."""
    with db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    """INSERT / UPDATE / DELETE helper. Commits and returns last insert id."""
    with db().cursor() as cur:
        cur.execute(sql, args)
        last_id = cur.lastrowid
    db().commit()
    return last_id


def db_error_text(err):
    """Friendly text from a MySQL error (our SIGNAL messages come through here)."""
    return err.args[1] if len(err.args) > 1 else str(err)


# =====================================================================
#  Login helpers
# =====================================================================
def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "error")
                return redirect(url_for("login", next=request.path))
            if roles and session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def safe_next(url):
    """Only allow redirects to pages inside this site."""
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return None


def to_number(text, default=0.0):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def all_skills():
    return query("SELECT skill_id, skill_name, category FROM skills "
                 "ORDER BY category, skill_name")


@app.template_filter("score_class")
def score_class(value):
    value = float(value or 0)
    if value >= 75:
        return "high"
    if value >= 40:
        return "mid"
    return "low"


@app.errorhandler(403)
def forbidden(_e):
    return render_template("message.html", title="Not allowed",
                           text="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Page not found",
                           text="This page does not exist."), 404


# =====================================================================
#  Public pages: home, job details, login, signup
# =====================================================================
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "")
    skill = request.args.get("skill", "")
    company_id = request.args.get("company", "")
    sort = request.args.get("sort", "new")

    sql = "SELECT * FROM v_job_listing WHERE status = 'open'"
    args = []
    if q:
        sql += " AND (title LIKE %s OR company LIKE %s)"
        args += [f"%{q}%", f"%{q}%"]
    if location:
        sql += " AND location = %s"
        args.append(location)
    if company_id.isdigit():
        sql += " AND company_id = %s"
        args.append(int(company_id))
    if skill:
        sql += (" AND job_id IN (SELECT js.job_id FROM job_skills js "
                "JOIN skills s ON s.skill_id = js.skill_id WHERE s.skill_name = %s)")
        args.append(skill)
    order = {"salary": "salary_lpa DESC", "new": "posted_date DESC, job_id"}
    sql += " ORDER BY " + order.get(sort, order["new"])
    jobs = query(sql, args)

    scores, applied = {}, set()
    if session.get("role") == "candidate":
        cid = session["candidate_id"]
        scores = {r["job_id"]: r["match_score"] for r in
                  query("SELECT job_id, match_score FROM v_candidate_job_match "
                        "WHERE candidate_id = %s", (cid,))}
        applied = {r["job_id"] for r in
                   query("SELECT job_id FROM applications WHERE candidate_id = %s", (cid,))}
        if sort == "match":
            jobs.sort(key=lambda j: float(scores.get(j["job_id"], 0)), reverse=True)

    stats = query(
        "SELECT (SELECT COUNT(*) FROM companies) AS companies,"
        " (SELECT COUNT(*) FROM jobs WHERE status = 'open') AS open_jobs,"
        " (SELECT COUNT(*) FROM candidates) AS candidates,"
        " (SELECT COUNT(*) FROM applications) AS applications", one=True)
    return render_template(
        "index.html", jobs=jobs, scores=scores, applied=applied, stats=stats,
        locations=query("SELECT DISTINCT location FROM jobs WHERE status='open' ORDER BY location"),
        skills=query("SELECT skill_name FROM skills ORDER BY skill_name"),
        companies=query("SELECT company_id, name FROM companies ORDER BY name"),
        f=dict(q=q, location=location, skill=skill, company=company_id, sort=sort))


@app.route("/job/<int:job_id>")
def job_detail(job_id):
    job = query("SELECT * FROM v_job_listing WHERE job_id = %s", (job_id,), one=True)
    if job is None:
        abort(404)
    cid = session.get("candidate_id") if session.get("role") == "candidate" else None
    skills = query(
        "SELECT s.skill_name, (cs.candidate_id IS NOT NULL) AS has_it "
        "FROM job_skills js JOIN skills s ON s.skill_id = js.skill_id "
        "LEFT JOIN candidate_skills cs ON cs.skill_id = js.skill_id AND cs.candidate_id = %s "
        "WHERE js.job_id = %s ORDER BY s.skill_name", (cid or 0, job_id))
    my_app, score = None, None
    if cid:
        my_app = query("SELECT * FROM applications WHERE job_id = %s AND candidate_id = %s",
                       (job_id, cid), one=True)
        score = query("SELECT fn_match_score(%s, %s) AS s", (cid, job_id), one=True)["s"]
    return render_template("job.html", job=job, skills=skills, my_app=my_app,
                           score=score, is_candidate=bool(cid))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = query("SELECT * FROM users WHERE email = %s", (email,), one=True)
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["user_id"], name=user["name"], role=user["role"])
            if user["role"] == "candidate":
                session["candidate_id"] = query(
                    "SELECT candidate_id FROM candidates WHERE user_id = %s",
                    (user["user_id"],), one=True)["candidate_id"]
            elif user["role"] == "recruiter":
                session["company_id"] = query(
                    "SELECT company_id FROM companies WHERE user_id = %s",
                    (user["user_id"],), one=True)["company_id"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(safe_next(request.args.get("next")) or url_for("home"))
        flash("Wrong email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You are logged out.", "success")
    return redirect(url_for("index"))


@app.route("/home")
@login_required()
def home():
    """Send each role to its own dashboard."""
    return redirect(url_for({"candidate": "candidate_dashboard",
                             "recruiter": "recruiter_dashboard",
                             "admin": "admin_dashboard"}[session["role"]]))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        f = request.form
        role = f.get("role")
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        password = f.get("password", "")
        if role not in ("candidate", "recruiter") or not name or "@" not in email:
            flash("Please fill in your name, a valid email and choose a role.", "error")
            return redirect(url_for("signup"))
        if len(password) < 6:
            flash("Password must have at least 6 characters.", "error")
            return redirect(url_for("signup"))
        user_id = None            # stays None until THIS request creates the user
        try:
            user_id = execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s,%s,%s,%s)",
                (name, email, generate_password_hash(password, method="pbkdf2:sha256"), role))
            if role == "candidate":
                cid = execute(
                    "INSERT INTO candidates (user_id, experience_years, education, location, resume_link) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (user_id, max(0, to_number(f.get("experience"))), f.get("education", "").strip() or "Not given",
                     f.get("location", "").strip() or "Not given", f.get("resume_link", "").strip() or None))
                for sid in f.getlist("skills"):
                    if sid.isdigit():
                        execute("INSERT IGNORE INTO candidate_skills VALUES (%s,%s)", (cid, int(sid)))
            else:
                execute("INSERT INTO companies (user_id, name, industry, location, website) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (user_id, f.get("company_name", "").strip() or name + " Company",
                         f.get("industry", "").strip() or "Technology",
                         f.get("company_location", "").strip() or "India",
                         f.get("website", "").strip() or None))
        except pymysql.err.IntegrityError as err:
            db().rollback()
            if err.args[0] == 1062:
                flash("This email or company name is already registered.", "error")
            else:
                flash(db_error_text(err), "error")
            if user_id is not None:   # profile insert failed -> undo the new user only
                execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            return redirect(url_for("signup"))
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html", skills=all_skills())


# =====================================================================
#  Candidate
# =====================================================================
@app.route("/job/<int:job_id>/apply", methods=["POST"])
@login_required("candidate")
def apply_job(job_id):
    cid = session["candidate_id"]
    try:
        with db().cursor() as cur:
            cur.callproc("sp_apply_to_job", (cid, job_id))   # trigger sets match_score
        db().commit()
        score = query("SELECT match_score FROM applications WHERE job_id=%s AND candidate_id=%s",
                      (job_id, cid), one=True)["match_score"]
        flash(f"Application sent! Your match score is {score:.0f}%.", "success")
    except pymysql.MySQLError as err:
        db().rollback()
        flash(db_error_text(err), "error")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/candidate")
@login_required("candidate")
def candidate_dashboard():
    cid = session["candidate_id"]
    profile = query("SELECT c.*, u.name, u.email FROM candidates c "
                    "JOIN users u ON u.user_id = c.user_id WHERE c.candidate_id = %s",
                    (cid,), one=True)
    my_skills = query("SELECT s.skill_name FROM candidate_skills cs "
                      "JOIN skills s ON s.skill_id = cs.skill_id "
                      "WHERE cs.candidate_id = %s ORDER BY s.skill_name", (cid,))
    applications = query(
        "SELECT a.application_id, a.job_id, a.status, a.match_score, a.applied_date, "
        "j.title, c.name AS company, i.interview_date, i.mode, i.result "
        "FROM applications a JOIN jobs j ON j.job_id = a.job_id "
        "JOIN companies c ON c.company_id = j.company_id "
        "LEFT JOIN interviews i ON i.application_id = a.application_id "
        "WHERE a.candidate_id = %s ORDER BY a.applied_date DESC, a.application_id DESC", (cid,))
    recommended = query(
        "SELECT * FROM v_candidate_job_match WHERE candidate_id = %s "
        "AND job_id NOT IN (SELECT job_id FROM applications WHERE candidate_id = %s) "
        "ORDER BY match_score DESC, salary_lpa DESC LIMIT 5", (cid, cid))
    return render_template("candidate_dashboard.html", profile=profile,
                           my_skills=my_skills, applications=applications,
                           recommended=recommended)


@app.route("/candidate/profile", methods=["GET", "POST"])
@login_required("candidate")
def candidate_profile():
    cid = session["candidate_id"]
    if request.method == "POST":
        f = request.form
        execute("UPDATE candidates SET experience_years=%s, education=%s, location=%s, resume_link=%s "
                "WHERE candidate_id=%s",
                (max(0, to_number(f.get("experience"))), f.get("education", "").strip() or "Not given",
                 f.get("location", "").strip() or "Not given", f.get("resume_link", "").strip() or None, cid))
        execute("DELETE FROM candidate_skills WHERE candidate_id = %s", (cid,))
        for sid in f.getlist("skills"):
            if sid.isdigit():
                execute("INSERT IGNORE INTO candidate_skills VALUES (%s,%s)", (cid, int(sid)))
        with db().cursor() as cur:
            cur.callproc("sp_refresh_scores", (None, cid))   # re-score old applications
        db().commit()
        flash("Profile saved. Your match scores were recalculated.", "success")
        return redirect(url_for("candidate_dashboard"))
    profile = query("SELECT * FROM candidates WHERE candidate_id = %s", (cid,), one=True)
    mine = {r["skill_id"] for r in
            query("SELECT skill_id FROM candidate_skills WHERE candidate_id = %s", (cid,))}
    return render_template("candidate_profile.html", profile=profile,
                           skills=all_skills(), mine=mine)


# =====================================================================
#  Recruiter
# =====================================================================
def own_job_or_404(job_id):
    job = query("SELECT * FROM v_job_listing WHERE job_id = %s", (job_id,), one=True)
    if job is None:
        abort(404)
    if job["company_id"] != session["company_id"]:
        abort(403)
    return job


@app.route("/recruiter")
@login_required("recruiter")
def recruiter_dashboard():
    company = query("SELECT * FROM companies WHERE company_id = %s",
                    (session["company_id"],), one=True)
    jobs = query("SELECT * FROM v_job_listing WHERE company_id = %s "
                 "ORDER BY status, posted_date DESC", (session["company_id"],))
    return render_template("recruiter_dashboard.html", company=company, jobs=jobs)


@app.route("/recruiter/post", methods=["GET", "POST"])
@login_required("recruiter")
def post_job():
    if request.method == "POST":
        f = request.form
        title = f.get("title", "").strip()
        salary = to_number(f.get("salary"))
        skill_ids = [int(s) for s in f.getlist("skills") if s.isdigit()]
        if not title or salary <= 0 or not skill_ids:
            flash("Please give a title, a salary above 0 and at least one required skill.", "error")
            return redirect(url_for("post_job"))
        job_id = execute(
            "INSERT INTO jobs (company_id, title, description, experience_required, location, salary_lpa) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (session["company_id"], title, f.get("description", "").strip(),
             max(0, to_number(f.get("experience"))), f.get("location", "").strip() or "India", salary))
        for sid in skill_ids:
            execute("INSERT IGNORE INTO job_skills VALUES (%s,%s)", (job_id, sid))
        flash("Job posted.", "success")
        return redirect(url_for("recruiter_dashboard"))
    return render_template("post_job.html", skills=all_skills())


@app.route("/recruiter/job/<int:job_id>")
@login_required("recruiter")
def job_candidates(job_id):
    job = own_job_or_404(job_id)
    required = [r["skill_name"] for r in
                query("SELECT s.skill_name FROM job_skills js JOIN skills s ON s.skill_id = js.skill_id "
                      "WHERE js.job_id = %s ORDER BY s.skill_name", (job_id,))]
    ranked = query("SELECT r.*, i.interview_date, i.mode, i.result FROM v_ranked_candidates r "
                   "LEFT JOIN interviews i ON i.application_id = r.application_id "
                   "WHERE r.job_id = %s ORDER BY r.rank_no, r.candidate_name", (job_id,))
    matched = {}
    for row in query(
            "SELECT cs.candidate_id, s.skill_name FROM candidate_skills cs "
            "JOIN job_skills js ON js.skill_id = cs.skill_id AND js.job_id = %s "
            "JOIN skills s ON s.skill_id = cs.skill_id "
            "WHERE cs.candidate_id IN (SELECT candidate_id FROM applications WHERE job_id = %s)",
            (job_id, job_id)):
        matched.setdefault(row["candidate_id"], set()).add(row["skill_name"])
    for r in ranked:
        have = matched.get(r["candidate_id"], set())
        r["have"] = [s for s in required if s in have]
        r["missing"] = [s for s in required if s not in have]
    return render_template("job_candidates.html", job=job, ranked=ranked, required=required)


@app.route("/recruiter/application/<int:app_id>/status", methods=["POST"])
@login_required("recruiter")
def set_status(app_id):
    row = query("SELECT a.job_id FROM applications a JOIN jobs j ON j.job_id = a.job_id "
                "WHERE a.application_id = %s AND j.company_id = %s",
                (app_id, session["company_id"]), one=True)
    if row is None:
        abort(403)
    new_status = request.form.get("status")
    if new_status not in ("Applied", "Shortlisted", "Rejected", "Selected"):
        abort(400)
    try:
        execute("UPDATE applications SET status = %s WHERE application_id = %s", (new_status, app_id))
        flash(f"Status changed to {new_status}.", "success")
    except pymysql.MySQLError as err:      # business-rule trigger can stop this
        db().rollback()
        flash(db_error_text(err), "error")
    return redirect(url_for("job_candidates", job_id=row["job_id"]))


@app.route("/recruiter/application/<int:app_id>/interview", methods=["GET", "POST"])
@login_required("recruiter")
def schedule_interview(app_id):
    row = query("SELECT r.* FROM v_ranked_candidates r "
                "WHERE r.application_id = %s AND r.company_id = %s",
                (app_id, session["company_id"]), one=True)
    if row is None:
        abort(403)
    if request.method == "POST":
        f = request.form
        when = f.get("interview_date", "").replace("T", " ")
        if not when:
            flash("Please choose a date and time.", "error")
            return redirect(url_for("schedule_interview", app_id=app_id))
        execute("INSERT INTO interviews (application_id, interview_date, mode, feedback, result) "
                "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE interview_date = VALUES(interview_date), "
                "mode = VALUES(mode), feedback = VALUES(feedback), result = VALUES(result)",
                (app_id, when, f.get("mode", "Online"), f.get("feedback", "").strip() or None,
                 f.get("result", "Pending")))
        flash("Interview saved.", "success")
        return redirect(url_for("job_candidates", job_id=row["job_id"]))
    interview = query("SELECT * FROM interviews WHERE application_id = %s", (app_id,), one=True)
    return render_template("interview.html", row=row, interview=interview)


@app.route("/recruiter/job/<int:job_id>/toggle", methods=["POST"])
@login_required("recruiter")
def toggle_job(job_id):
    job = own_job_or_404(job_id)
    new = "closed" if job["status"] == "open" else "open"
    execute("UPDATE jobs SET status = %s WHERE job_id = %s", (new, job_id))
    flash(f"Job is now {new}.", "success")
    return redirect(url_for("recruiter_dashboard"))


# =====================================================================
#  Admin
# =====================================================================
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    totals = query(
        "SELECT (SELECT COUNT(*) FROM users) AS users,"
        " (SELECT COUNT(*) FROM companies) AS companies,"
        " (SELECT COUNT(*) FROM candidates) AS candidates,"
        " (SELECT COUNT(*) FROM jobs) AS jobs,"
        " (SELECT COUNT(*) FROM applications) AS applications,"
        " (SELECT COUNT(*) FROM interviews) AS interviews", one=True)
    return render_template(
        "admin.html", totals=totals,
        companies=query("SELECT * FROM v_company_stats ORDER BY total_applications DESC"),
        statuses=query("SELECT status, COUNT(*) AS total FROM applications GROUP BY status"),
        top_skills=query("SELECT s.skill_name, COUNT(*) AS total FROM job_skills js "
                         "JOIN skills s ON s.skill_id = js.skill_id "
                         "GROUP BY s.skill_id, s.skill_name ORDER BY total DESC, s.skill_name LIMIT 8"),
        log=query("SELECT l.log_id, u.name AS candidate, j.title, c.name AS company, "
                  "l.old_status, l.new_status, l.changed_at FROM application_log l "
                  "JOIN applications a ON a.application_id = l.application_id "
                  "JOIN candidates cd ON cd.candidate_id = a.candidate_id "
                  "JOIN users u ON u.user_id = cd.user_id "
                  "JOIN jobs j ON j.job_id = a.job_id "
                  "JOIN companies c ON c.company_id = j.company_id "
                  "ORDER BY l.log_id DESC LIMIT 10"))


# =====================================================================
#  DBMS demo page (for viva / presentation). Fixed queries only.
# =====================================================================
DEMO_QUERIES = [
    ("VIEW + RANK()", "Top 5 candidates for job #1 from the view v_ranked_candidates",
     "SELECT rank_no, candidate_name, experience_years, match_score, status "
     "FROM v_ranked_candidates WHERE job_id = 1 ORDER BY rank_no LIMIT 5"),
    ("FUNCTION", "fn_match_score(candidate, job) calculates the match percentage",
     "SELECT fn_match_score(1, 1) AS score_candidate1_job1, fn_match_score(1, 9) AS score_candidate1_job9"),
    ("JOIN (many-to-many)", "Open jobs with their required skills (view with sub-queries)",
     "SELECT company, title, location, salary_lpa, required_skills FROM v_job_listing "
     "WHERE status = 'open' ORDER BY salary_lpa DESC LIMIT 5"),
    ("GROUP BY + HAVING", "Jobs that received more than 5 applications",
     "SELECT c.name AS company, j.title, COUNT(a.application_id) AS applications "
     "FROM jobs j JOIN companies c ON c.company_id = j.company_id "
     "JOIN applications a ON a.job_id = j.job_id GROUP BY j.job_id, c.name, j.title "
     "HAVING COUNT(a.application_id) > 5 ORDER BY applications DESC"),
    ("SUBQUERY", "Applications with a score above the overall average",
     "SELECT candidate_name, job_title, company, match_score FROM v_ranked_candidates "
     "WHERE match_score > (SELECT AVG(match_score) FROM applications) "
     "ORDER BY match_score DESC LIMIT 5"),
    ("LEFT JOIN", "Skills in the master list that no job needs",
     "SELECT s.skill_name FROM skills s LEFT JOIN job_skills js ON js.skill_id = s.skill_id "
     "WHERE js.job_id IS NULL ORDER BY s.skill_name"),
    ("TRIGGER (audit log)", "Every status change is logged automatically by an AFTER UPDATE trigger",
     "SELECT log_id, application_id, old_status, new_status, changed_at "
     "FROM application_log ORDER BY log_id DESC LIMIT 5"),
    ("TRIGGERS in the database", "All triggers created in schema.sql",
     "SELECT trigger_name AS name, action_timing AS timing, event_manipulation AS event, "
     "event_object_table AS on_table FROM information_schema.triggers "
     "WHERE trigger_schema = DATABASE() ORDER BY trigger_name"),
    ("INDEXES", "Indexes on the applications table",
     "SELECT DISTINCT index_name AS index_name, column_name AS column_name "
     "FROM information_schema.statistics WHERE table_schema = DATABASE() "
     "AND table_name = 'applications' ORDER BY index_name"),
]


@app.route("/demo")
def demo():
    results = []
    for concept, text, sql in DEMO_QUERIES:
        rows = query(sql)
        results.append(dict(concept=concept, text=text, sql=sql, rows=rows,
                            cols=list(rows[0].keys()) if rows else []))
    return render_template("demo.html", results=results)


if __name__ == "__main__":
    app.run(debug=True)
