"""Generates the architecture and workflow diagrams (SVG) in docs/.

    python3 docs/make_diagrams.py

Hand-placed layout, no dependencies. Edit the coordinates below and re-run.
"""
import pathlib
from xml.sax.saxutils import escape

OUT = pathlib.Path(__file__).parent
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
MONO = "Consolas, DejaVu Sans Mono, monospace"
INK, SUB, LINE = "#1F2933", "#52606D", "#9AA5B1"
C = {  # fill, stroke
    "app": ("#E8F0FE", "#3B6FD8"), "model": ("#F3E8FD", "#8E44AD"),
    "tool": ("#E6F6EC", "#2F9E5B"), "db": ("#FFF4E0", "#D9822B"),
    "ora": ("#FDECEC", "#C0392B"), "you": ("#EEF2F6", "#52606D"),
    "vol": ("#F5F7FA", "#7B8794"), "note": ("#FFFBEA", "#C9A227"),
}


class SVG:
    def __init__(self, w, h, title, subtitle=""):
        self.w, self.h, self.p = w, h, []
        self.p.append(f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>')
        self.text(30, 42, title, 22, INK, bold=True)
        if subtitle:
            self.text(30, 66, subtitle, 14, SUB)

    def text(self, x, y, s, size=13, fill=INK, bold=False, anchor="start", mono=False, italic=False):
        w = ' font-weight="bold"' if bold else ""
        it = ' font-style="italic"' if italic else ""
        self.p.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"'
                      f'{w}{it} font-family="{MONO if mono else FONT}">{escape(s)}</text>')

    def rect(self, x, y, w, h, kind="vol", r=10, dash=False, fill=None, stroke=None, sw=1.6):
        f, s = C[kind]
        d = ' stroke-dasharray="6 4"' if dash else ""
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or f}" '
                      f'stroke="{stroke or s}" stroke-width="{sw}"{d}/>')

    def box(self, x, y, w, h, kind, title, lines=(), size=12.5, mono_lines=False, center=False):
        self.rect(x, y, w, h, kind)
        cx = x + w / 2
        if center:
            self.text(cx, y + 22, title, 14, C[kind][1], bold=True, anchor="middle")
        else:
            self.text(x + 12, y + 22, title, 14, C[kind][1], bold=True)
        for i, ln in enumerate(lines):
            if center:
                self.text(cx, y + 42 + i * 17, ln, size, INK, anchor="middle", mono=mono_lines)
            else:
                self.text(x + 12, y + 42 + i * 17, ln, size, INK, mono=mono_lines)

    def region(self, x, y, w, h, label, color=LINE, fill="#FAFBFC"):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
                      f'stroke="{color}" stroke-width="1.4" stroke-dasharray="8 5"/>')
        self.text(x + 14, y + 22, label, 13, SUB, bold=True)

    def arrow(self, x1, y1, x2, y2, label="", color="#7B8794", dash=False, both=False, lx=None, ly=None,
              lsize=11.5, lanchor="middle", sw=1.8):
        d = ' stroke-dasharray="6 4"' if dash else ""
        mid = f'marker-start="url(#a{color[1:]})" ' if both else ""
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d} '
                      f'{mid}marker-end="url(#a{color[1:]})"/>')
        self._colors.add(color)
        if label:
            self.text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 6,
                      label, lsize, SUB, anchor=lanchor)

    def path(self, d, color="#7B8794", dash=False, sw=1.8):
        ds = ' stroke-dasharray="6 4"' if dash else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{ds} marker-end="url(#a{color[1:]})"/>')
        self._colors.add(color)

    def badge(self, x, y, n, color="#3B6FD8"):
        self.p.append(f'<circle cx="{x}" cy="{y}" r="11" fill="{color}"/>')
        self.text(x, y + 4.5, str(n), 12, "#FFFFFF", bold=True, anchor="middle")

    _colors = set()

    def save(self, name):
        defs = "".join(
            f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for c in sorted(self._colors))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
               f'height="{self.h}"><defs>{defs}</defs>' + "\n".join(self.p) + "</svg>\n")
        (OUT / name).write_text(svg)
        SVG._colors = set()


# ============================================================ 1. architecture
def architecture():
    s = SVG(1280, 900, "db-agent architecture",
            "Docker Compose on one Linux VM (VirtualBox home lab or cloud). Every port is bound to 127.0.0.1.")
    # outside the VM
    s.box(30, 130, 230, 110, "you", "Your laptop", [
        "browser  http://localhost:8501", "terminal (ssh)", "ssh -L 8501:localhost:8501"])
    s.box(30, 470, 230, 170, "model", "Model (HTTPS)", [
        "OpenAI  api.openai.com", "  — or —", "Open WebUI /api", "(in-house vLLM, gpt-oss …)",
        "", "OPENAI_BASE_URL in .env"])
    # VM
    s.region(290, 85, 960, 795, "Linux VM · Ubuntu 24.04 · 16 GB RAM · 4 vCPU · 100 GB", "#52606D", "#FCFCFD")
    s.box(320, 130, 270, 250, "app", "Python app  (uv · .venv)", [
        "app/agent.py   terminal chat", "app/app.py     web UI  :8501",
        "LangChain create_agent", "one specialist per database",
        "databases.toml: dialect + notes", "  (oracle_prod: DG runbook)",
        "model picker: /models", "guards: 4-SQL cap, write refusal,", "  external-model block",
        "", "→ MCP over HTTP to each Toolbox"], size=12)
    s.arrow(260, 190, 320, 190, "SSH tunnel", lx=290, ly=182, lsize=10.5)
    s.arrow(320, 340, 260, 540, color="#8E44AD")
    s.text(282, 425, "chat +", 10.5, SUB, anchor="end")
    s.text(282, 439, "tool calls", 10.5, SUB, anchor="end")

    s.box(320, 420, 270, 205, "note", "Read-only by design", [
        "Toolbox logs in as agent_reader /", "C##AGENT_READER: SELECT + monitoring",
        "The database refuses writes.", "Admin/SYS: setup scripts only.",
        "oracle_prod: in-house models only", "  (lab: ALLOW_EXTERNAL_MODELS_FOR)",
        "Secrets in .env (chmod 600)", "Web UI only via SSH tunnel"], size=12)
    s.box(320, 660, 270, 150, "vol", "Docker volumes", [
        "pgdata · mysqldata · mariadbdata", "oraprimary   primary datafiles,",
        "             spfile, archive logs", "orastandby   standby files + config",
        "orashared    orapw + primary_ready", "             (hand-over to standby)"],
        size=12, mono_lines=True)

    # compose region
    s.region(620, 120, 610, 745, "Docker Compose · network tool-network", "#7B8794", "#F7F9FB")
    s.text(760, 160, "MCP Toolbox (one per DB)", 12.5, SUB, bold=True, anchor="middle")
    s.text(1075, 160, "Databases", 12.5, SUB, bold=True, anchor="middle")
    rows = [(172, "toolbox  :5000", "Postgres · 32 tools", "db  PostgreSQL 16", "shop  ·  :5432"),
            (260, "toolbox-mysql  :5001", "MySQL · 9 tools", "mysql  MySQL 8.4", "inventory  ·  :3306"),
            (348, "toolbox-mariadb  :5002", "MariaDB · 9 tools", "mariadb  MariaDB 11.4", "support  ·  :3307")]
    for y, tt, tl, dt, dl in rows:
        s.box(650, y, 220, 66, "tool", tt, [tl])
        s.box(955, y, 245, 66, "db", dt, [dl])
        s.arrow(870, y + 33, 955, y + 33, "read-only", lsize=10.5)
        s.arrow(590, 255, 650, y + 33, color="#3B6FD8", sw=1.4)

    # oracle
    s.p.append('<rect x="640" y="440" width="575" height="405" rx="12" fill="#FFF9F9" stroke="#C0392B" '
               'stroke-width="1.2" stroke-dasharray="5 4"/>')
    s.text(655, 462, "Oracle 19c Data Guard lab   (profiles oracle-lab + oracle-prod)", 12.5, "#C0392B", bold=True)
    s.box(650, 490, 220, 100, "tool", "toolbox-oracle-prod :5004", [
        "30 tools: 8 Data Guard,", "13 performance, 6 space,", "3 general"], size=12)
    s.arrow(590, 255, 650, 540, color="#3B6FD8", sw=1.4)
    s.box(955, 480, 245, 120, "ora", "oracle-primary", [
        "CDB ORCLCDB · PDB ORCLPDB1", "PRIMARY · READ WRITE", "ARCHIVELOG · FORCE LOGGING",
        "localhost:1531"], size=12)
    s.arrow(870, 540, 955, 540, "read-only", lsize=10.5)
    s.box(955, 690, 245, 120, "ora", "oracle-standby", [
        "ORCLCDB_STBY", "PHYSICAL STANDBY · MOUNTED", "MRP real-time apply",
        "localhost:1532"], size=12)
    s.arrow(1000, 600, 1000, 690, "", color="#C0392B", sw=2.2)
    s.text(1008, 622, "redo ASYNC", 11, "#C0392B", bold=True)
    s.text(1008, 636, "dest 2 → DG_STANDBY", 10.5, SUB)
    s.arrow(1170, 690, 1170, 600, "", color="#C0392B", dash=True, sw=1.6)
    s.text(1162, 662, "FAL: fetch", 10.5, SUB, anchor="end")
    s.text(1162, 676, "missing logs", 10.5, SUB, anchor="end")
    s.box(650, 620, 220, 60, "vol", "oracle-init (one-off)", ["chown orashared → exit"], size=12)
    s.box(650, 705, 220, 110, "vol", "orashared volume", [
        "orapwORCLCDB", "primary_service", "primary_ready  (flag)"], size=12, mono_lines=True)
    s.arrow(870, 725, 955, 585, color="#7B8794", dash=True, sw=1.3)
    s.arrow(870, 775, 955, 760, color="#7B8794", dash=True, sw=1.3)
    s.text(930, 680, "writes", 10.5, SUB, anchor="middle")
    s.text(905, 785, "reads", 10.5, SUB, anchor="middle")
    s.save("architecture.svg")


# ============================================================ 2. question flow
def question_flow():
    W, H = 1280, 840
    s = SVG(W, H, "What happens when you ask a question",
            "Example: oracle_prod · “Is Data Guard healthy?”  —  every arrow is one step, top to bottom.")
    lanes = [("You", 120, "you"), ("Agent (app/agent.py)", 390, "app"), ("Model", 660, "model"),
             ("MCP Toolbox :5004", 920, "tool"), ("oracle-primary", 1160, "ora")]
    for name, x, k in lanes:
        s.rect(x - 95, 90, 190, 40, k)
        s.text(x, 115, name, 13.5, C[k][1], bold=True, anchor="middle")
        s.p.append(f'<line x1="{x}" y1="130" x2="{x}" y2="{H - 30}" stroke="#CBD2D9" stroke-width="1.5" '
                   'stroke-dasharray="4 4"/>')
    X = {n: x for n, x, _ in lanes}
    y = 170
    steps = [
        ("You", "Agent (app/agent.py)", "Is Data Guard healthy?", "#52606D", False),
        ("Agent (app/agent.py)", None, "model allowed for oracle_prod? (internal_models_only)", "#3B6FD8", False),
        ("Agent (app/agent.py)", "Model", "question + history + tools + runbook", "#3B6FD8", False),
        ("Model", "Agent (app/agent.py)", "tool call: dg_health_check()", "#8E44AD", True),
        ("Agent (app/agent.py)", "MCP Toolbox :5004", "MCP tools/call  dg_health_check", "#3B6FD8", False),
        ("MCP Toolbox :5004", "oracle-primary", "fixed SQL as C##AGENT_READER", "#2F9E5B", False),
        ("oracle-primary", "MCP Toolbox :5004", "rows: VALID, no gap, lag 0 s", "#C0392B", True),
        ("MCP Toolbox :5004", "Agent (app/agent.py)", "JSON result", "#2F9E5B", True),
        ("Agent (app/agent.py)", "Model", "tool result", "#3B6FD8", False),
        ("Model", "Agent (app/agent.py)", "more tools if needed (dg_apply_progress …)", "#8E44AD", True),
        ("Model", "Agent (app/agent.py)", "answer: verdict + evidence + fixes", "#8E44AD", True),
        ("Agent (app/agent.py)", "You", "[Oracle PROD] HEALTHY … + tools used", "#3B6FD8", True),
    ]
    loop_top, loop_bot = None, None
    for i, (a, b, label, col, back) in enumerate(steps, 1):
        if i == 4:
            y += 18
            loop_top = y - 44
        if b is None:
            s.rect(X[a] + 10, y - 16, 330, 28, "app", r=6)
            s.text(X[a] + 20, y + 3, label, 11.5, INK)
            s.badge(40, y - 2, i, col)
        else:
            x1, x2 = X[a], X[b]
            s.arrow(x1, y, x2, y, color=col, dash=back)
            s.text((x1 + x2) / 2, y - 8, label, 12, INK, anchor="middle")
            s.badge(40, y - 2, i, col)
        if i == 10:
            loop_bot = y + 18
        y += 52
    s.p.append(f'<rect x="300" y="{loop_top}" width="910" height="{loop_bot - loop_top}" rx="8" fill="none" '
               'stroke="#8E44AD" stroke-width="1.2" stroke-dasharray="3 3"/>')
    s.text(310, loop_top + 16, "loop  ·  one tool call at a time  ·  max 4 execute_sql per question", 11.5, "#8E44AD",
           bold=True)
    s.text(30, H - 12, "Solid = request, dashed = response. The model never sees database passwords; the "
           "database refuses any write.", 12, SUB)
    s.save("workflow-question.svg")


# ============================================================ 3. data guard build
def dg_build():
    W, H = 1280, 1010
    s = SVG(W, H, "How the Data Guard lab builds itself (first docker compose up)",
            "Time runs downward. Later starts skip straight to “open / mount + apply” (about a minute).")
    lanes = [("oracle-init", 130, "vol"), ("oracle-primary", 420, "ora"), ("orashared volume", 690, "vol"),
             ("oracle-standby", 960, "ora"), ("toolbox-oracle-prod", 1180, "tool")]
    for name, x, k in lanes:
        s.rect(x - 100, 90, 200, 40, k)
        s.text(x, 115, name, 13.5, C[k][1], bold=True, anchor="middle")
        s.p.append(f'<line x1="{x}" y1="130" x2="{x}" y2="{H - 60}" stroke="#CBD2D9" stroke-width="1.5" '
                   'stroke-dasharray="4 4"/>')
    X = {n: x for n, x, _ in lanes}

    def step(lane, y, n, title, lines, w=250, kind=None, h=None):
        x = X[lane]
        k = kind or dict((a, c) for a, _, c in lanes)[lane]
        hh = h or (34 + 17 * len(lines))
        s.box(x - w / 2, y, w, hh, k, title, lines, size=12)
        s.badge(x - w / 2, y, n, C[k][1])
        return y + hh

    step("oracle-init", 150, 1, "chown orashared", ["to oracle:oinstall, exit 0"], w=210)
    s.text(130, 232, "~1 min", 11.5, SUB, anchor="middle", italic=True)

    step("oracle-primary", 160, 2, "createDB.sh (image)", ["dbca: CDB ORCLCDB + PDB ORCLPDB1",
         "ENABLE_ARCHIVELOG=true", "15-40 minutes"])
    s.arrow(130, 205, 295, 205, "", dash=True, sw=1.3)
    step("oracle-primary", 285, 3, "01-dataguard-primary.sh", [
        "force logging", "standby_file_management=AUTO", "log_archive_config DG_CONFIG",
        "log_archive_dest_2 → DG_STANDBY", "fal_server, standby redo logs", "tnsnames DG_PRIMARY/STANDBY",
        "create C##AGENT_READER"], w=260)
    step("orashared volume", 480, 4, "hand-over files", ["orapwORCLCDB", "primary_service", "primary_ready"],
         w=200)
    s.arrow(550, 500, 590, 500, "copy", lsize=11)
    step("oracle-primary", 560, 5, "DATABASE IS READY", ["open READ WRITE, listener up"], w=260)

    step("oracle-standby", 160, 6, "wait for primary_ready", ["polls the shared volume", "every 30 s"], w=240)
    s.arrow(790, 530, 835, 585, "", dash=True, sw=1.3)
    s.text(800, 470, "flag appears →", 11, SUB, anchor="start")
    s.p.append('<line x1="960" y1="245" x2="960" y2="560" stroke="#C0392B" stroke-width="3" stroke-dasharray="2 5"/>')
    s.text(968, 400, "waiting …", 11, "#C0392B", italic=True)
    step("oracle-standby", 560, 7, "prepare", ["copy orapw, write tnsnames,", "listener with static entry",
         "mkdir the primary's paths", "startup nomount (db_name only)"], w=250)
    y8 = step("oracle-standby", 680, 8, "RMAN duplicate", ["for standby from active database",
              "spfile set db_unique_name", "  = ORCLCDB_STBY … nofilenamecheck", "10-30 minutes"], w=270)
    s.arrow(550, 735, 825, 735, "datafiles + controlfile over the network", color="#C0392B", sw=2.2, ly=727)
    step("oracle-standby", 800, 9, "start apply", ["standby redo logs if missing", "recover managed standby",
         "  database disconnect  (MRP0)"], w=250)
    s.arrow(835, 880, 550, 880, "enable dest 2 + archive log current", color="#C0392B", dash=True, sw=1.5,
            ly=872)
    step("oracle-primary", 850, "P", "redo shipping starts", ["dest 2 VALID → standby applies"], w=260)
    step("oracle-standby", 900, 10, "STANDBY IS READY", ["healthcheck: PHYSICAL STANDBY + MRP"], w=270)

    step("toolbox-oracle-prod", 160, "T", "restarting …", ["ping fails until the", "primary is open"], w=180)
    step("toolbox-oracle-prod", 560, "T", "serving :5004", ["from step 5 on:", "30 tools as", "C##AGENT_READER"], w=180)
    s.text(30, H - 30, "Scripts: db/oracle-lab/primary/01-dataguard-primary.sh (sourced once by the image) · "
           "db/oracle-lab/standby/standby.sh (standby entrypoint) · healthcheck.sh", 12, SUB)
    s.text(30, H - 12, "If RMAN fails: the standby keeps running and writes "
           "/opt/oracle/oradata/dbconfig/ORCLCDB_STBY/duplicate.log; restart it to try again.", 12, SUB)
    s.save("workflow-dg-build.svg")


# ============================================================ 4. redo + what the agent sees
def redo_flow():
    W, H = 1280, 860
    s = SVG(W, H, "Data Guard redo flow, and what the agent can see",
            "All 30 tools run on the PRIMARY (a mounted standby only accepts SYSDBA/SYSDG logins).")
    s.region(30, 90, 520, 430, "oracle-primary  ·  ORCLCDB  ·  PRIMARY", "#C0392B", "#FFF9F9")
    s.region(730, 90, 520, 430, "oracle-standby  ·  ORCLCDB_STBY  ·  PHYSICAL STANDBY", "#C0392B", "#FFF9F9")
    s.box(60, 130, 200, 60, "app", "sessions / DML", ["commits"], center=True)
    s.box(60, 230, 200, 60, "ora", "LGWR", ["writes redo"], center=True)
    s.box(60, 330, 200, 70, "db", "online redo logs", ["redo01-03.log"], center=True)
    s.box(310, 330, 210, 70, "db", "ARCn → archive_logs", ["log_archive_dest_1"], center=True)
    s.box(310, 230, 210, 60, "ora", "TT (transport)", ["dest 2, ASYNC"], center=True)
    s.box(60, 430, 460, 60, "vol", "datafiles · controlfile", ["/opt/oracle/oradata/ORCLCDB"], center=True)
    s.arrow(160, 190, 160, 230)
    s.arrow(160, 290, 160, 330)
    s.arrow(260, 365, 310, 365)
    s.arrow(260, 260, 310, 260)

    s.box(760, 230, 210, 60, "ora", "RFS", ["receives redo"], center=True)
    s.box(760, 330, 210, 70, "db", "standby redo logs", ["groups = online + 1"], center=True)
    s.box(1010, 330, 210, 70, "ora", "MRP0", ["real-time apply"], center=True)
    s.box(1010, 230, 210, 60, "db", "archived on standby", ["after each log switch"], center=True)
    s.box(760, 430, 460, 60, "vol", "datafiles · controlfile (MOUNTED)", ["same paths as the primary"],
          center=True)
    s.arrow(520, 260, 760, 260, "redo stream", color="#C0392B", sw=2.4, ly=250)
    s.arrow(760, 300, 520, 300, "FAL: missing sequences", color="#C0392B", dash=True, ly=318)
    s.arrow(865, 290, 865, 330)
    s.arrow(970, 365, 1010, 365)
    s.arrow(970, 260, 1010, 260)
    s.arrow(1115, 400, 1115, 430)

    # failure points
    def x_mark(x, y, label, anchor="start"):
        s.p.append(f'<circle cx="{x}" cy="{y}" r="12" fill="#C0392B"/>')
        s.text(x, y + 5, "✕", 14, "#FFFFFF", bold=True, anchor="middle")
        s.text(x + (18 if anchor == "start" else -18), y + 5, label, 11.5, "#C0392B", bold=True, anchor=anchor)
    x_mark(640, 150, "")
    s.text(640, 182, "standby down", 11.5, "#C0392B", bold=True, anchor="middle")
    s.text(640, 197, "→ dest 2 ERROR", 11.5, "#C0392B", bold=True, anchor="middle")
    x_mark(1125, 312, "MRP stopped")

    s.text(30, 560, "What the agent reads on the primary — and which tool shows it", 16, INK, bold=True)
    rows = [
        ("dg_health_check", "one-shot verdict per standby: dest status, gap, recovery mode, apply lag (SCN → time)"),
        ("dg_destinations", "GV$ARCHIVE_DEST(_STATUS): VALID / ERROR, error text, target, transport mode"),
        ("dg_apply_progress", "last archived vs last applied sequence per thread; logs behind"),
        ("dg_missing_logs", "archive gap: which sequences the standby is missing (RESOLVABLE / UNRESOLVABLE)"),
        ("dg_messages", "V$DATAGUARD_STATUS: recent Data Guard errors and warnings"),
        ("dg_standby_redo_logs", "standby redo log groups and sizes (needed for real-time apply)"),
        ("dg_parameters · dg_redo_rate", "log_archive_* / fal_* settings; redo generated per hour (explains lag)"),
    ]
    y = 590
    for i, (t, d) in enumerate(rows):
        if i % 2 == 0:
            s.p.append(f'<rect x="30" y="{y - 4}" width="1220" height="30" fill="#F5F7FA"/>')
        s.text(42, y + 16, t, 13, "#2F9E5B", bold=True, mono=True)
        s.text(330, y + 16, d, 13, INK)
        y += 30
    s.text(30, y + 26, "Typical findings:  dest 2 ERROR ORA-12541 (standby down)  ·  RECOVERY_MODE = IDLE "
           "(MRP stopped)  ·  GAP_STATUS = RESOLVABLE GAP  ·  apply lag growing while redo rate is high", 12.5, SUB)
    s.text(30, y + 48, "The agent explains the cause and gives the DBA commands; it never runs them "
           "(approved actions are phase 2).", 12.5, SUB)
    s.save("workflow-redo.svg")


# ============================================================ ARCHITECTURE.html
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>db-agent Architecture</title>
<style>
:root{--ink:#1F2933;--sub:#52606D;--line:#D9E2EC;--bg:#F5F7FA;--card:#FFFFFF;--accent:#3B6FD8;--code:#EEF2F6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ink:#E4E7EB;--sub:#9AA5B1;--line:#3E4C59;--bg:#14191F;--card:#1F2933;--accent:#7BA4F0;--code:#2A3541}}
:root[data-theme="dark"]{--ink:#E4E7EB;--sub:#9AA5B1;--line:#3E4C59;--bg:#14191F;--card:#1F2933;--accent:#7BA4F0;--code:#2A3541}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 'Segoe UI',Helvetica,Arial,sans-serif}
main{max-width:1320px;margin:0 auto;padding:28px 16px 80px}
h1{font-size:30px;margin:0 0 4px}
.lead{color:var(--sub);margin:0 0 20px;max-width:90ch}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 28px}
nav a{padding:6px 12px;border:1px solid var(--line);border-radius:999px;color:var(--ink);text-decoration:none;background:var(--card);font-size:14px}
nav a:hover{border-color:var(--accent);color:var(--accent)}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 20px;margin:0 0 26px}
h2{font-size:22px;margin:0 0 6px}
section>p{max-width:95ch;color:var(--ink)}
.fig{overflow-x:auto;border-radius:10px;border:1px solid var(--line);background:#fff;margin:14px 0}
.fig svg{display:block;width:100%;height:auto;min-width:760px}
ol,ul{max-width:95ch}
li{margin:4px 0}
code{background:var(--code);padding:1px 6px;border-radius:5px;font:14px Consolas,'DejaVu Sans Mono',monospace}
table{border-collapse:collapse;width:100%;font-size:14.5px;margin:10px 0}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--code)}
.tbl{overflow-x:auto}
footer{color:var(--sub);font-size:13px}
</style></head><body><main>
<h1>db-agent: architecture and workflows</h1>
<p class="lead">Ask PostgreSQL, MySQL, MariaDB and an Oracle 19c Data Guard pair questions in plain English.
Everything runs with Docker Compose on one Linux VM. Four pictures, each with what to take away from it.
Setup steps are in <code>SETUP.md</code>; the Oracle lab in <code>ORACLE-LAB.md</code>.</p>
<nav><a href="#arch">1 · Architecture</a><a href="#ask">2 · Asking a question</a>
<a href="#build">3 · How the Oracle lab builds</a><a href="#redo">4 · Redo flow &amp; what the agent sees</a>
<a href="#ports">5 · Ports &amp; names</a></nav>

<section id="arch"><h2>1 · Architecture</h2>
<p>Three layers. The <b>Python app</b> (your terminal or the web UI) runs the LangChain agent and talks to the
<b>model</b> over HTTPS. For data it never touches a database directly: it calls the <b>MCP Toolbox</b> for that
database, and the Toolbox runs SQL with a <b>read-only login</b>. The Oracle lab adds a primary and a physical
standby; the agent's Toolbox connects to the primary only.</p>
<div class="fig">@@architecture@@</div>
<ul>
<li><b>One Toolbox per database</b> because the built-in tool sets reuse names (<code>execute_sql</code>, <code>list_tables</code>).</li>
<li><b>Read-only is enforced by the database</b>, not by the prompt: <code>agent_reader</code> / <code>C##AGENT_READER</code> cannot write.</li>
<li><b>The web UI has no login</b>: it listens on the VM only, and you reach it through an SSH tunnel.</li>
<li><b>Model choice</b> is per session; <code>oracle_prod</code> refuses external models unless you allow it for the lab.</li>
</ul></section>

<section id="ask"><h2>2 · What happens when you ask a question</h2>
<p>The agent is a loop: the model chooses a tool, the app runs it through the Toolbox, the result goes back to the
model, until the model can answer. For <code>oracle_prod</code> the prompt carries a Data Guard runbook from
<code>app/databases.toml</code>, so the model knows which tools to call first and what counts as a problem.</p>
<div class="fig">@@workflow-question@@</div>
<ol>
<li>The model only sees tool <i>descriptions</i> and results. Passwords stay in <code>.env</code> and the Toolbox.</li>
<li>Custom tools (all 30 Oracle ones) are <b>fixed SQL</b>: the model supplies values, never SQL.
Free-form SQL goes through <code>execute_sql</code>, capped at 4 per question.</li>
<li>The answer names the database and lists the tools used, so you can check the evidence.</li>
</ol></section>

<section id="build"><h2>3 · How the Oracle Data Guard lab builds itself</h2>
<p>The first <code>docker compose up</code> takes 30-70 minutes; later starts take about a minute. The two Oracle
containers coordinate through a small shared volume: the primary drops its password file and a
<code>primary_ready</code> flag there, and the standby waits for that flag before cloning.</p>
<div class="fig">@@workflow-dg-build@@</div>
<div class="tbl"><table><tr><th>Step</th><th>Where it is coded</th><th>Watch it with</th></tr>
<tr><td>2 · create the CDB</td><td>the image (<code>createDB.sh</code>)</td><td><code>docker compose logs -f oracle-primary</code></td></tr>
<tr><td>3-4 · Data Guard on the primary, hand-over</td><td><code>db/oracle-lab/primary/01-dataguard-primary.sh</code></td><td><code>… | grep db-agent</code></td></tr>
<tr><td>6-10 · build and run the standby</td><td><code>db/oracle-lab/standby/standby.sh</code></td><td><code>docker compose logs -f oracle-standby</code></td></tr>
<tr><td>health</td><td><code>db/oracle-lab/standby/healthcheck.sh</code></td><td><code>docker compose ps</code> → <code>(healthy)</code></td></tr>
</table></div></section>

<section id="redo"><h2>4 · Redo flow, and what the agent can see</h2>
<p>Every change on the primary becomes redo. The transport process ships it ASYNC to the standby, which writes
it to standby redo logs and applies it in real time (MRP). A mounted standby only accepts SYSDBA/SYSDG logins, so
the agent reads everything <b>from the primary</b>, which tracks each standby's status, gaps and applied SCN.</p>
<div class="fig">@@workflow-redo@@</div>
<p>Try it: stop apply on the standby, or stop the standby container, then ask <i>"Is Data Guard healthy?"</i>.
<code>ORACLE-LAB.md</code> → <i>Break it on purpose</i> has the commands.</p></section>

<section id="ports"><h2>5 · Ports and names</h2>
<div class="tbl"><table>
<tr><th>Service (container)</th><th>Inside Docker</th><th>On the VM</th><th>Login used by the agent</th></tr>
<tr><td><code>db</code> PostgreSQL 16</td><td>db:5432</td><td>127.0.0.1:5432</td><td><code>agent_reader</code></td></tr>
<tr><td><code>mysql</code> MySQL 8.4</td><td>mysql:3306</td><td>127.0.0.1:3306</td><td><code>agent_reader</code></td></tr>
<tr><td><code>mariadb</code> MariaDB 11.4</td><td>mariadb:3306</td><td>127.0.0.1:3307</td><td><code>agent_reader</code></td></tr>
<tr><td><code>oracle-primary</code></td><td>oracle-primary:1521 · service <code>ORCLCDB.localdomain</code></td><td>127.0.0.1:1531</td><td><code>C##AGENT_READER</code></td></tr>
<tr><td><code>oracle-standby</code></td><td>oracle-standby:1521 · service <code>ORCLCDB_STBY</code></td><td>127.0.0.1:1532</td><td>none (SYSDBA only)</td></tr>
<tr><td><code>toolbox</code> / <code>-mysql</code> / <code>-mariadb</code> / <code>-oracle-prod</code></td><td>:5000</td><td>127.0.0.1:5000 / 5001 / 5002 / 5004</td><td>-</td></tr>
<tr><td>web UI (Streamlit)</td><td>-</td><td>127.0.0.1:8501 (SSH tunnel)</td><td>-</td></tr>
</table></div></section>
<footer>Diagrams are generated by <code>docs/make_diagrams.py</code> (SVGs in <code>docs/</code>). Edit and re-run to change them.</footer>
</main></body></html>
"""


def page():
    html = PAGE
    for name in ("architecture", "workflow-question", "workflow-dg-build", "workflow-redo"):
        svg = (OUT / f"{name}.svg").read_text()
        svg = svg.replace("<svg ", f'<svg role="img" aria-label="{name}" ', 1)
        html = html.replace(f"@@{name}@@", svg)
    (OUT.parent / "ARCHITECTURE.html").write_text(html)


if __name__ == "__main__":
    architecture()
    question_flow()
    dg_build()
    redo_flow()
    page()
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
