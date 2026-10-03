"""Database agent over MCP Toolbox.

Modes (env AGENT_MODE):
  single (default)  You choose ONE database; every question goes there until you
                    switch with 'use <db>'. Only that database is connected.
  auto              A router agent picks the database for each question.

Databases are listed in databases.toml (same folder).
Terminal chat:  uv run --env-file .env python app/agent.py
"""

import contextvars
import fnmatch
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from openai import OpenAI
from toolbox_langchain import ToolboxClient

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
AGENT_MODE = os.getenv("AGENT_MODE", "single").strip().lower()      # single | auto
DEFAULT_DATABASE = os.getenv("DEFAULT_DATABASE", "").strip().lower() or None
DATABASES_FILE = Path(os.getenv("DATABASES_FILE", Path(__file__).with_name("databases.toml")))

EXIT_WORDS = {"quit", "exit", "q", ":q", "bye"}
TOOLS_WORDS = {"tools", "/tools", "help", "/help"}
DBS_WORDS = {"dbs", "databases", "/dbs"}
MAX_SQL_PER_QUESTION = 4       # execute_sql calls per question
MAX_DB_CALLS_PER_QUESTION = 6  # auto mode: specialist calls by the router, per question

if AGENT_MODE not in ("single", "auto"):
    raise ValueError(f"AGENT_MODE must be 'single' or 'auto', not {AGENT_MODE!r}")


def load_databases() -> list[dict]:
    with open(DATABASES_FILE, "rb") as f:
        dbs = tomllib.load(f)["database"]
    # requires_env = "SOME_VAR": the database is only offered when that variable is set
    # (e.g. oracle_prod needs ORACLE_PROD_CONNECTION_STRING).
    dbs = [d for d in dbs if not d.get("requires_env") or os.getenv(d["requires_env"])]
    for db in dbs:
        db["toolbox_url"] = os.getenv(f"TOOLBOX_URL_{db['key'].upper()}", db["toolbox_url"])
    # AGENT_DATABASES=oracle,mysql -> only these databases are available.
    only = [k.strip().lower() for k in os.getenv("AGENT_DATABASES", "").split(",") if k.strip()]
    if only:
        unknown = set(only) - {d["key"] for d in dbs}
        if unknown:
            raise ValueError(f"AGENT_DATABASES has unknown keys: {sorted(unknown)}")
        dbs = [d for d in dbs if d["key"] in only]
    return dbs


DATABASES = load_databases()
DB_BY_KEY = {d["key"]: d for d in DATABASES}
if DEFAULT_DATABASE and DEFAULT_DATABASE not in DB_BY_KEY:
    raise ValueError(f"DEFAULT_DATABASE={DEFAULT_DATABASE!r} is not one of {list(DB_BY_KEY)}")
# Kept for app.py, which shows this in its caption.
TOOLBOX_URL = ", ".join(f"{d['key']}={d['toolbox_url']}" for d in DATABASES)


def make_model(model: str | None = None):
    # parallel_tool_calls=False: one tool call at a time. Also stops the model from
    # mentioning OpenAI's internal "multi_tool_use.parallel" helper as a tool.
    return ChatOpenAI(model=model or OPENAI_MODEL, model_kwargs={"parallel_tool_calls": False})


# --------------------------------------------------------------------------
# Models: list what the provider offers, and keep prod data on internal models
# --------------------------------------------------------------------------
# Model ids that are routed to OUTSIDE providers even when the gateway is in-house
# (e.g. Open WebUI connections named internet/... or zcloud/...). Shell-style patterns.
EXTERNAL_MODEL_PATTERNS = [p.strip().lower() for p in
                           os.getenv("EXTERNAL_MODEL_PATTERNS", "internet/*,zcloud/*").split(",")
                           if p.strip()]
# Databases allowed to use external models anyway (lab only), e.g. oracle_prod.
ALLOW_EXTERNAL_MODELS_FOR = {k.strip().lower() for k in
                             os.getenv("ALLOW_EXTERNAL_MODELS_FOR", "").split(",") if k.strip()}


def provider_is_external() -> bool:
    """True when OPENAI_BASE_URL points outside the company (OpenAI itself by default).
    Override with LLM_PROVIDER_EXTERNAL=true/false."""
    forced = os.getenv("LLM_PROVIDER_EXTERNAL", "").strip().lower()
    if forced in ("1", "true", "yes"):
        return True
    if forced in ("0", "false", "no"):
        return False
    host = urlparse(os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").hostname or ""
    return host == "openai.com" or host.endswith(".openai.com")


def model_is_external(model: str) -> bool:
    return provider_is_external() or any(fnmatch.fnmatch(model.lower(), p)
                                         for p in EXTERNAL_MODEL_PATTERNS)


def model_blocked(db_key: str | None, model: str) -> str | None:
    """Error message if this database must not be used with this model, else None.
    Databases with internal_models_only = true (databases.toml) never get an external model."""
    if not db_key or db_key not in DB_BY_KEY:
        return None
    db = DB_BY_KEY[db_key]
    if db.get("internal_models_only") and db_key not in ALLOW_EXTERNAL_MODELS_FOR \
            and model_is_external(model):
        return (f"Blocked: {db['name']} may only be used with an in-house model, and "
                f"'{model}' is external (provider {os.getenv('OPENAI_BASE_URL') or 'api.openai.com'}). "
                "Pick an internal model ('models' / 'model <id>'), or switch OPENAI_BASE_URL "
                "to your in-house gateway.")
    return None


def list_models() -> list[str]:
    """Every model id the current provider's /models endpoint returns (same URL, key and
    CA settings as the agent). Raises if the provider can't be reached."""
    with OpenAI() as client:
        return sorted(m.id for m in client.models.list())


def describe_tools(tools) -> str:
    lines = []
    for t in sorted(tools, key=lambda t: t.name):
        desc = " ".join((t.description or "").split())
        lines.append(f"- {t.name}: {desc}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Specialist: one agent per database, with only that database's tools
# --------------------------------------------------------------------------
SPECIALIST_PROMPT = """You are the {name} assistant. You answer questions about ONE database:
{about}
SQL dialect: {dialect}. Write SQL for this dialect only.

Your tools (MCP Toolbox). These are the ONLY tools you have:
{tool_list}

Questions about you, your tools or what you can do: answer from the list above without
calling tools. If a question is clearly about data that is not in this database, say so
and suggest switching database (the user types 'use <db>').

Choosing a tool (in this order):
1. A tool whose description matches the question exactly (business or admin tool): use it.
2. Database administration (users/roles, sessions, locks, slow or top SQL, sizes,
   storage, settings, indexes, invalid objects, replication): use the matching
   dedicated tool once, then answer. No list_tables needed.
3. Anything else about the data: call list_tables first (unless you already know the
   schema), then write ONE read-only SELECT and run it with execute_sql.

Rules for execute_sql:
- Use only tables and columns that exist. The login is read-only: writes and DDL fail.
- Cap rows unless the query aggregates (100 rows maximum).
- If a query errors, fix it and retry (max 3 attempts). If it returns no rows, say so;
  do not keep re-running variations.
{notes}
Answer in plain English with the numbers you found; use a short markdown table for more
than 3 rows. Never invent data a tool did not return. If a tool errors or returns nothing,
say so plainly.

Requests to change data or structure (insert, update, delete, truncate, drop, create,
grant...): reply in ONE short sentence that this assistant is read-only and cannot make
changes. Do not provide SQL or step-by-step instructions for making the change, UNLESS
this database's notes above allow recommending administrative fixes: then you may
recommend commands for a DBA to run, but you never run them yourself."""

LABEL_RE = re.compile(r"^(\s*\*\*\[[^\]]*\]\*\*\s*)+")


def strip_label(text: str) -> str:
    """Remove leading '**[Database name]**' labels."""
    return LABEL_RE.sub("", text or "")


def clean_history(history: list | None) -> list:
    """History without the database labels, so the model doesn't copy them."""
    out = []
    for m in history or []:
        if isinstance(m, AIMessage) and isinstance(m.content, str):
            m = AIMessage(content=strip_label(m.content))
        out.append(m)
    return out


# Per-question record of the tools the specialists called, read by ask().
_trace: contextvars.ContextVar[list | None] = contextvars.ContextVar("trace", default=None)


@dataclass
class Specialist:
    db: dict
    tools: list
    prompt: str
    client: object = None  # ToolboxClient; closed by DBAgent.close()
    agents: dict = field(default_factory=dict)  # model id -> LangChain agent

    def agent_for(self, model: str):
        """The agent for this database on a given model (built once per model)."""
        if model not in self.agents:
            self.agents[model] = create_agent(
                model=make_model(model), tools=self.tools, system_prompt=self.prompt,
                middleware=[ToolCallLimitMiddleware(tool_name="execute_sql",
                                                    run_limit=MAX_SQL_PER_QUESTION)])
        return self.agents[model]

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def run(self, question: str, history: list | None = None, model: str | None = None) -> str:
        model = model or OPENAI_MODEL
        if err := model_blocked(self.db["key"], model):
            return err
        messages = clean_history(history) + [HumanMessage(content=question)]
        state = self.agent_for(model).invoke({"messages": messages},
                                             config={"recursion_limit": 25})
        turn = state["messages"][len(messages):]
        trace = _trace.get()
        for m in turn:
            if isinstance(m, AIMessage) and trace is not None:
                for call in m.tool_calls or []:
                    trace.append((self.db["key"], call["name"], call.get("args") or {}))
        final = next((m for m in reversed(turn) if isinstance(m, AIMessage) and m.content), None)
        text = final.content if final else "No answer."
        if isinstance(text, list):
            text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
        return strip_label(text)


def build_specialist(db: dict) -> Specialist:
    client = ToolboxClient(db["toolbox_url"])
    try:
        tools = client.load_toolset()
    except Exception:
        client.close()  # don't leave a dangling HTTP session behind
        raise
    prompt = SPECIALIST_PROMPT.format(
        name=db["name"], about=db["about"], dialect=db["dialect"],
        tool_list=describe_tools(tools), notes=db.get("notes", ""),
    )
    return Specialist(db=db, tools=tools, prompt=prompt, client=client)


# --------------------------------------------------------------------------
# Router (auto mode only): picks the database(s) and combines answers
# --------------------------------------------------------------------------
ROUTER_PROMPT = """You are a database assistant connected to several databases. You do not query
them directly: you hand questions to one specialist per database.

Specialists (these are your ONLY tools):
{db_list}

How to work:
- Pick the database whose description matches the question and call its ask_<db> tool
  with a complete, self-contained question (resolve "it", "those" from the conversation).
- If the question names several databases or "all databases", call each relevant
  specialist, one after another, then combine. Specialists cannot see each other's data.
- If it is unclear which database is meant, ask the user, naming the options.
- Questions about you or what you can do: answer from the list above without tools.
- Everything is read-only. Never invent data; pass on errors plainly. Always say which
  database each answer came from.
{offline}"""


@dataclass
class AgentResult:
    answer: str
    database: str | None = None                            # key of the database used
    sql: list[str] = field(default_factory=list)           # SQL run via execute_sql
    tool_calls: list[str] = field(default_factory=list)    # "[db] tool {args}"
    tool_outputs: list[str] = field(default_factory=list)
    model: str | None = None                                # model that answered


class DBAgent:
    """Connects to databases lazily: in single mode only the ones you use."""

    def __init__(self, mode: str = AGENT_MODE, model: str = OPENAI_MODEL):
        self.mode = mode
        self.model = model            # default model (the CLI's current one); see set_model
        self.specialists: dict[str, Specialist] = {}
        self.offline: dict[str, str] = {}
        self.routers: dict[str, object] = {}   # model id -> router agent (auto mode)
        if mode == "auto":
            for db in DATABASES:
                self.connect(db["key"])
            if not self.specialists:
                raise RuntimeError(f"No database Toolbox is reachable: {self.offline}")

    def set_model(self, model: str, current_db: str | None = None) -> str | None:
        """Switch the default model. Returns an error message (and keeps the old model)
        if the current database may not use it."""
        model = model.strip()
        if not model:
            return "Give a model id, e.g. 'model gpt-5-mini' (see 'models')."
        if err := model_blocked(current_db, model):
            return err
        self.model = model
        return None

    def connect(self, key: str) -> str | None:
        """Connect to a database's Toolbox. Returns an error message, or None if OK."""
        if key not in DB_BY_KEY:
            return f"Unknown database '{key}'. Choose one of: {', '.join(DB_BY_KEY)}"
        if key in self.specialists:
            return None
        try:
            self.specialists[key] = build_specialist(DB_BY_KEY[key])
            self.offline.pop(key, None)
            return None
        except Exception as e:  # Toolbox down or unreachable
            self.offline[key] = f"{type(e).__name__}: {e}"
            return f"Can't reach {DB_BY_KEY[key]['name']} ({DB_BY_KEY[key]['toolbox_url']}): " \
                   f"{self.offline[key][:150]}"

    def close(self) -> None:
        """Close every Toolbox connection (avoids 'Unclosed client session' on exit)."""
        for sp in self.specialists.values():
            sp.close()

    def router_for(self, model: str):
        """Auto-mode router for a model. Databases that may not use this model are left out."""
        if model in self.routers:
            return self.routers[model]
        allowed = {k: sp for k, sp in self.specialists.items() if not model_blocked(k, model)}
        blocked = [k for k in self.specialists if k not in allowed]
        if not allowed:
            raise RuntimeError(f"No database may be used with model '{model}'.")
        tools = []
        for key, sp in allowed.items():
            def _ask(question: str, _sp=sp, _model=model) -> str:
                return _sp.run(question, model=_model)
            tools.append(StructuredTool.from_function(
                _ask, name=f"ask_{key}",
                description=f"Ask the {sp.db['name']} specialist. Data: {sp.db['about']}"))
        db_list = "\n".join(f"- ask_{k}: {sp.db['name']}. {sp.db['about']}"
                            for k, sp in allowed.items())
        unavailable = list(self.offline) + blocked
        offline = ("\nCurrently NOT AVAILABLE (offline, or not allowed with this model; say so "
                   "if asked about them): " + ", ".join(unavailable)) if unavailable else ""
        self.routers[model] = create_agent(
            model=make_model(model), tools=tools,
            system_prompt=ROUTER_PROMPT.format(db_list=db_list, offline=offline),
            middleware=[ToolCallLimitMiddleware(run_limit=MAX_DB_CALLS_PER_QUESTION)])
        return self.routers[model]


def build_agent(mode: str = AGENT_MODE) -> DBAgent:
    return DBAgent(mode)


def ask(agent: DBAgent, question: str, history: list | None = None,
        db: str | None = None, model: str | None = None) -> AgentResult:
    """Answer one question.
    db='oracle'          -> that database only (required in single mode)
    '@oracle question'   -> that database only, for this question
    db=None, auto mode   -> the router picks.
    model                -> model id for this question (default: agent.model)"""
    model = model or agent.model
    if question.startswith("@"):
        key, _, question = question[1:].partition(" ")
        key, question = key.lower(), question.strip()
        if not question:
            return AgentResult(answer=f"Type a question after @{key}.")
        if key != db:
            history = None  # one-off question to another database: start clean
        db = key
    if db is None and agent.mode == "single":
        return AgentResult(answer="Choose a database first: type 'use <db>' "
                                  f"({', '.join(DB_BY_KEY)}).")
    if err := model_blocked(db, model):
        return AgentResult(answer=err, database=db, model=model)
    if db is not None and (err := agent.connect(db)):
        return AgentResult(answer=err, database=db, model=model)

    trace: list = []
    token = _trace.set(trace)
    try:
        if db:  # one database: no router involved
            sp = agent.specialists[db]
            answer = f"**[{sp.db['name']}]** {sp.run(question, history, model)}"
            outputs: list[str] = []
        else:
            messages = clean_history(history) + [HumanMessage(content=question)]
            state = agent.router_for(model).invoke({"messages": messages},
                                                   config={"recursion_limit": 25})
            turn = state["messages"][len(messages):]
            outputs = [str(m.content) for m in turn if isinstance(m, ToolMessage)]
            final = next((m for m in reversed(turn) if isinstance(m, AIMessage) and m.content), None)
            answer = final.content if final else "I couldn't produce an answer."
            if isinstance(answer, list):
                answer = "".join(b.get("text", "") for b in answer if isinstance(b, dict))
    finally:
        _trace.reset(token)

    sql, calls = [], []
    for key, name, args in trace:
        if name == "execute_sql":
            sql.append(f"-- {key}\n{args.get('sql', '')}")
            calls.append(f"[{key}] execute_sql")
        else:
            calls.append(f"[{key}] {name} {json.dumps(args)}" if args else f"[{key}] {name}")
    return AgentResult(answer=answer, database=db, sql=sql, tool_calls=calls,
                       tool_outputs=outputs, model=model)


# --------------------------------------------------------------------------
# Terminal chat
# --------------------------------------------------------------------------
def print_dbs(agent: DBAgent, current: str | None) -> None:
    for d in DATABASES:
        k = d["key"]
        status = ("connected" if k in agent.specialists else
                  "OFFLINE" if k in agent.offline else "not connected")
        mark = "  <- current" if k == current else ""
        print(f"- {k:9} {status:13} {d['name']}  ({d['toolbox_url']}){mark}")


def print_tools(agent: DBAgent, current: str | None) -> None:
    keys = [current] if current else list(agent.specialists)
    for k in keys:
        if k in agent.specialists:
            sp = agent.specialists[k]
            print(f"\n[{k}] {sp.db['name']} - {len(sp.tools)} tools ({sp.db['toolbox_url']})")
            print("  " + ", ".join(sorted(t.name for t in sp.tools)))


def choose_database(agent: DBAgent) -> str | None:
    """Startup menu for single mode. Returns the chosen key, or None to quit."""
    while True:
        print("\nWhich database do you want to talk to?")
        for i, d in enumerate(DATABASES, 1):
            print(f"  {i}. {d['key']:9} {d['name']}")
        try:
            pick = input("Number or name (or 'quit'): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return None
        if pick in EXIT_WORDS:
            return None
        if pick.isdigit() and 1 <= int(pick) <= len(DATABASES):
            pick = DATABASES[int(pick) - 1]["key"]
        if err := model_blocked(pick, agent.model):
            print(err)
            continue
        if err := agent.connect(pick):
            print(err)
            continue
        return pick


def print_models(agent: DBAgent, current_db: str | None) -> list[str]:
    """Print the provider's models, numbered. Returns the list (for 'model <number>')."""
    try:
        models = list_models()
    except Exception as e:
        print(f"Can't list models from {os.getenv('OPENAI_BASE_URL') or 'api.openai.com'}: "
              f"{type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"{len(models)} models at {os.getenv('OPENAI_BASE_URL') or 'https://api.openai.com/v1'} "
          "(external = data leaves your network):")
    for i, m in enumerate(models, 1):
        tags = []
        if m == agent.model:
            tags.append("<- current")
        if model_is_external(m):
            tags.append("external")
        if model_blocked(current_db, m):
            tags.append(f"blocked for {current_db}")
        print(f"  {i:3}. {m}" + (f"   [{', '.join(tags)}]" if tags else ""))
    print("Switch with 'model <number or id>'.")
    return models


def switch(agent: DBAgent, target: str) -> bool:
    if err := model_blocked(target, agent.model):
        print(err)
        return False
    if err := agent.connect(target):
        print(err)
        return False
    sp = agent.specialists[target]
    print(f"Now talking to {sp.db['name']} ({len(sp.tools)} tools). "
          "Every question goes here until you type 'use <db>'.")
    return True


def main():
    agent = build_agent()
    try:
        chat(agent)
    finally:
        agent.close()


def chat(agent: DBAgent) -> None:
    history: list = []
    current: str | None = None

    if agent.mode == "single":
        current = DEFAULT_DATABASE or (DATABASES[0]["key"] if len(DATABASES) == 1 else None)
        if current and not switch(agent, current):
            current = None
        if current is None:
            current = choose_database(agent)
            if current is None:
                print("Bye.")
                return
            switch(agent, current)
    else:
        print(f"Auto mode: connected to {', '.join(agent.specialists)}"
              + (f"; offline: {', '.join(agent.offline)}" if agent.offline else "") + ".")

    print(f"Model {agent.model}. Commands: 'use <db>' to switch, 'dbs', 'tools', "
          "'models', 'model <id>', 'quit' (or Ctrl+C).")
    last_models: list[str] = []
    while True:
        try:
            q = input(f"\nYou [{current or 'auto'} | {agent.model}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not q:
            continue
        low = q.lower()
        if low in EXIT_WORDS:
            print("Bye.")
            break
        if low in TOOLS_WORDS:
            print_tools(agent, current)
            continue
        if low in DBS_WORDS:
            print_dbs(agent, current)
            continue
        if low in ("models", "/models"):
            last_models = print_models(agent, current)
            continue
        if low.startswith("model ") or low == "model":
            pick = q[6:].strip()
            if pick.isdigit() and last_models and 1 <= int(pick) <= len(last_models):
                pick = last_models[int(pick) - 1]
            if err := agent.set_model(pick, current):
                print(err)
            else:
                print(f"Model is now {agent.model}"
                      + (" (external: data leaves your network)" if model_is_external(agent.model) else ""))
            continue
        if low == "use" or low.startswith("use "):
            target = low[4:].strip()
            if target in ("", "auto", "all", "any"):
                if agent.mode == "auto":
                    current = None
                    history = []
                    print("Routing: automatic (the agent picks the database).")
                else:
                    print(f"Single-database mode: pick one of {', '.join(DB_BY_KEY)} "
                          "(start with AGENT_MODE=auto for automatic routing).")
                continue
            if switch(agent, target):
                current = target
                history = []  # new database, fresh context
            continue
        try:
            r = ask(agent, q, history, db=current, model=agent.model)
        except Exception as e:  # keep the chat alive on API/tool errors
            print(f"\n[error] {e}")
            continue
        for c in r.tool_calls:
            print(f"\n[tool] {c}")
        for s in r.sql:
            print(f"\n[SQL] {s}")
        print(f"\nAgent: {r.answer}")
        if not q.startswith("@"):  # one-off @db questions don't join this chat's context
            history += [HumanMessage(content=q), AIMessage(content=r.answer)]
            history = history[-12:]  # keep the last 6 exchanges


if __name__ == "__main__":
    main()
