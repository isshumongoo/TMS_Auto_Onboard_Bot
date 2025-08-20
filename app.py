import os, re, sqlite3, stat
from datetime import datetime, UTC
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Load .env early (if present) so env vars are available before we read them
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Tokens
BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]     # xoxb-...
APP_TOKEN = os.environ["SLACK_APP_TOKEN"]     # xapp-...

# ---- SQLite path (persist to /data in Railway)
DB_PATH = os.getenv("ONBOARDING_DB_PATH", "onboarding.db")

# Ensure parent dir exists and is writable (important for mounted volumes like /data)
db_dir = os.path.dirname(DB_PATH) or "."
try:
    os.makedirs(db_dir, exist_ok=True)
    # Relax permissions in case the volume is mounted with strict defaults
    os.chmod(db_dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0o777
except Exception as e:
    print(f"[DB] mkdir/chmod error for {db_dir}: {e}")

# Diagnostics you'll see in Railway logs
print(f"[DB] DB_PATH={DB_PATH}")
print(f"[DB] dir exists? {os.path.isdir(db_dir)}  writable? {os.access(db_dir, os.W_OK)}")

# ---- Data store (SQLite)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS onboarding_progress (
  user_id    TEXT NOT NULL,
  task_id    TEXT NOT NULL,
  done       INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, task_id)
);
""")
conn.commit()

# ===== ONBOARDING RESOURCES (replace placeholders) =====
RESOURCES = {
    "handbook_url": "https://docs.google.com/document/d/1711C6vSp4r4EHZw5MbgYuy-LkxrPF-2o69fHCCgU0fQ/edit?usp=sharing",
    "brand_center_url": "https://drive.google.com/file/d/1hTp4w1ufmJVgNkzYxsOLjcdI9kBvro1X/view?usp=sharing",
    "pd_recordings_url": "https://drive.google.com/drive/folders/1VkBMVvdlG0IofZ7_RKB4dMT0aXEzsxew?usp=drive_link",
    "staff_directory_url": "https://docs.google.com/spreadsheets/d/1_7uLjg20Oy-ajgQCVdtozPTiWnO5pgdniR3lpKqRjw0/edit?usp=sharing",
    "all_team_channel": "<#allthemovementstreet>",  # or channel ID like <#C12345678>
    "announcements_channel": "<#announcements>",    # or channel ID
    "admin_email": "admin@themovementstreet.org",
}

# ===== ONBOARDING TASKS (grouped; each group renders its own checkbox element) =====
TASKS = [
  # Step 1: Paperwork & Documents
  {"id": "welcome_letter",      "label": "Sign Welcome Letter",                                     "group": "Paperwork"},
  {"id": "nda",                 "label": "Sign NDA",                                                "group": "Paperwork"},
  {"id": "offer_letter",        "label": "Sign Offer Letter",                                       "group": "Paperwork"},
  {"id": "volunteer_agreement", "label": "Sign Volunteer Agreement",                                "group": "Paperwork"},
  {"id": "contract",            "label": "Sign Contract (duties and responsibilities)",             "group": "Paperwork"},
  {"id": "upload_docs",         "label": f"Upload docs & share with {RESOURCES['admin_email']}",    "group": "Paperwork"},

  # Step 2: Onboarding & Integration
  {"id": "staff_directory",     "label": "Review Staff Directory",                                  "group": "Integration"},
  {"id": "chapter_handbook",    "label": "Read Chapter Handbook",                                   "group": "Integration"},
  {"id": "brand_center",        "label": "Explore Brand Center",                                    "group": "Integration"},
  {"id": "pd_recordings",       "label": "Watch Professional Development Recordings",               "group": "Integration"},

  # Step 3: Workflow & Role Setup
  {"id": "role_checklist",      "label": "Review your role-specific checklist",                     "group": "Workflow"},
  {"id": "setup_workflow",      "label": "Set up your role workflows and tools",                    "group": "Workflow"},

  # Step 4: Connection & Culture
  {"id": "coffee_chat_1",       "label": "Coffee Chat #1 with a TMS team member",                   "group": "Culture"},
  {"id": "coffee_chat_2",       "label": "Coffee Chat #2 with a TMS team member",                   "group": "Culture"},
  {"id": "coffee_chat_3",       "label": "Coffee Chat #3 with a TMS team member",                   "group": "Culture"},
]

def ensure_user_rows(user_id: str):
    now = datetime.now(UTC).isoformat()
    for t in TASKS:
        cur.execute(
            "INSERT OR IGNORE INTO onboarding_progress(user_id, task_id, done, updated_at) VALUES(?,?,0,?)",
            (user_id, t["id"], now)
        )
    conn.commit()

def get_done_set(user_id: str):
    cur.execute("SELECT task_id FROM onboarding_progress WHERE user_id=? AND done=1", (user_id,))
    return {row[0] for row in cur.fetchall()}

def set_done_bulk(user_id: str, new_done_ids: set):
    now = datetime.now(UTC).isoformat()
    for t in TASKS:
        is_done = 1 if t["id"] in new_done_ids else 0
        cur.execute(
            "UPDATE onboarding_progress SET done=?, updated_at=? WHERE user_id=? AND task_id=?",
            (is_done, now, user_id, t["id"])
        )
    conn.commit()

def group_names_in_order():
    seen = []
    for t in TASKS:
        g = t["group"]
        if g not in seen:
            seen.append(g)
    return seen

def tasks_by_group():
    groups = {}
    for t in TASKS:
        groups.setdefault(t["group"], []).append(t)
    return groups

def build_home_view(user_id: str):
    done = get_done_set(user_id)
    total = len(TASKS)
    progress_text = f"{len(done)}/{total} completed"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "TMS Onboarding Checklist"}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "Welcome to The Movement Street. Check items as you complete them. Your progress saves automatically."}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Progress:* {progress_text}"}},

    ]

    groups = tasks_by_group()
    for group_name in group_names_in_order():
        items = groups[group_name]
        # Group header with mini count
        group_done_count = sum(1 for t in items if t["id"] in done)
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*{group_name}* ({group_done_count}/{len(items)})"}})

        options = [{"text": {"type": "plain_text", "text": t["label"]}, "value": t["id"]} for t in items]
        initial = [{"text": {"type": "plain_text", "text": t["label"]}, "value": t["id"]}
                   for t in items if t["id"] in done]

        checkbox_el = {
            "type": "checkboxes",
            "action_id": f"task_toggle_{group_name.lower()}",
            "options": options,
        }
        # Only set initial_options if we actually have any (avoids Slack validation error)
        if initial:
            checkbox_el["initial_options"] = initial

        blocks.append({
            "type": "actions",
            "elements": [checkbox_el]
        })

    resources_md = (
        f"{RESOURCES['all_team_channel']} • {RESOURCES['announcements_channel']} • "
        f"<{RESOURCES['handbook_url']}|Handbook> • "
        f"<{RESOURCES['brand_center_url']}|Brand Center> • "
        f"<{RESOURCES['pd_recordings_url']}|PD Recordings> • "
        f"<{RESOURCES['staff_directory_url']}|Staff Directory>"
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Resources: {resources_md}"}]})

    return {"type": "home", "blocks": blocks}

app = App(token=BOT_TOKEN)  # Socket Mode -> no signing secret needed

# Publish checklist when a user opens the App Home
@app.event("app_home_opened")
def handle_home_opened(event, client, logger):
    user_id = event["user"]
    ensure_user_rows(user_id)
    client.views_publish(user_id=user_id, view=build_home_view(user_id))

# Auto-setup when someone joins the workspace
@app.event("team_join")
def handle_team_join(event, client, logger):
    user_id = event["user"]["id"]
    ensure_user_rows(user_id)
    client.chat_postMessage(
        channel=user_id,
        text=("Welcome to TMS. Open the app’s *Home* tab to see your onboarding checklist. "
              "If you have questions, reply here.")
    )
    client.views_publish(user_id=user_id, view=build_home_view(user_id))

# Save checkbox changes for any group (regex matches all action_ids like task_toggle_paperwork, etc.)
@app.action(re.compile(r"^task_toggle_"))
def handle_toggle_any_group(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    action_id = body["actions"][0]["action_id"]  # e.g., task_toggle_paperwork
    group_key = action_id.replace("task_toggle_", "", 1)  # 'paperwork', 'integration', 'workflow', 'culture'

    # Which tasks belong to this group?
    group_tasks = [t for t in TASKS if t["group"].lower() == group_key]
    group_task_ids = {t["id"] for t in group_tasks}

    # What did the user just select in this group?
    selected_ids = {opt["value"] for opt in body["actions"][0].get("selected_options", [])}

    # Merge: keep current done outside this group, replace state for this group
    current_done = get_done_set(user_id)
    new_done = (current_done - group_task_ids) | selected_ids

    ensure_user_rows(user_id)
    set_done_bulk(user_id, new_done)
    client.views_publish(user_id=user_id, view=build_home_view(user_id))

# Optional helper slash command to refresh your own view
@app.command("/onboard")
def cmd_onboard(ack, body, client):
    ack("Opening your checklist in the App Home.")
    user_id = body["user_id"]
    ensure_user_rows(user_id)
    client.views_publish(user_id=user_id, view=build_home_view(user_id))

if __name__ == "__main__":
    SocketModeHandler(app, APP_TOKEN).start()
