"""Streamlit chat UI for the database agent.
Run: uv run --env-file .env streamlit run app/app.py --server.headless true"""

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent import (AGENT_MODE, DATABASES, DB_BY_KEY, DEFAULT_DATABASE, OPENAI_MODEL, ask,
                   build_agent, list_models, model_blocked, model_is_external)

st.set_page_config(page_title="Ask your database", page_icon="🗄️", layout="centered")
# Hide Streamlit's "Deploy" button (the theme switch stays in the ⋮ menu).
st.markdown("<style>[data-testid='stAppDeployButton']{display:none}</style>",
            unsafe_allow_html=True)


@st.cache_resource(show_spinner="Starting…")
def get_agent():
    return build_agent()


try:
    agent = get_agent()
except Exception as e:
    st.error(f"Couldn't start the agent.\n\n{e}")
    if st.button("Retry"):
        st.cache_resource.clear()
        st.rerun()
    st.stop()

@st.cache_data(ttl=300, show_spinner=False)
def get_models() -> list[str]:
    """The provider's /models list, refreshed every 5 minutes."""
    return list_models()


if "model" not in st.session_state:
    st.session_state.model = OPENAI_MODEL  # each browser session picks its own model
if "turns" not in st.session_state:
    st.session_state.turns = []  # dicts: {q, answer, calls, sql, db}

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Database")
    choices = list(DB_BY_KEY) + (["auto"] if AGENT_MODE == "auto" else [])
    default = DEFAULT_DATABASE or ("auto" if AGENT_MODE == "auto" else choices[0])
    target = st.radio(
        "Talk to", choices, index=choices.index(default),
        format_func=lambda k: "Auto: agent picks" if k == "auto" else DB_BY_KEY[k]["name"],
        key="target", label_visibility="collapsed",
    )
    if st.session_state.get("last_target") not in (None, target):
        st.session_state.turns = []  # new database, fresh conversation
    st.session_state.last_target = target

    if target != "auto":
        err = agent.connect(target)
        if err:
            st.error(err)
            if st.button("Retry connection", use_container_width=True):
                agent.offline.pop(target, None)
                st.rerun()
        else:
            sp = agent.specialists[target]
            st.success(f"Connected · {len(sp.tools)} tools")
            with st.expander("Tools"):
                st.write(", ".join(sorted(t.name for t in sp.tools)))
    st.caption("Tip: `@oracle …` asks another database once, without switching.")

    st.subheader("Model")
    try:
        models, models_err = get_models(), None
    except Exception as e:
        models, models_err = [], f"{type(e).__name__}: {str(e)[:150]}"
    if models:
        if st.session_state.model not in models:
            models = [st.session_state.model] + models
        st.selectbox("Model", models, key="model", label_visibility="collapsed",
                     format_func=lambda m: f"{m}  · external" if model_is_external(m) else m)
    else:
        st.caption(f"Can't list models ({models_err}). Type a model id:")
        st.text_input("Model id", key="model", label_visibility="collapsed")
    if model_is_external(st.session_state.model):
        st.caption("⚠️ External model: questions and results leave your network.")
    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state.turns = []
        st.rerun()

# ------------------------------------------------------------------ main
name = "your databases" if target == "auto" else DB_BY_KEY[target]["name"]
st.title(f"Ask {name}")
model = st.session_state.model
st.caption(f"Plain-English questions → read-only queries via MCP Toolbox · model: {model}")
blocked = model_blocked(None if target == "auto" else target, model)
if blocked:
    st.error(blocked)


def render_details(t):
    if t["calls"]:
        with st.expander(f"Tools used ({len(t['calls'])})"):
            for c in t["calls"]:
                st.code(c, language="text")
            for s in t["sql"]:
                st.code(s, language="sql")
            if t.get("model"):
                st.caption(f"model: {t['model']}")


for t in st.session_state.turns:
    with st.chat_message("user"):
        st.markdown(t["q"])
    with st.chat_message("assistant"):
        st.markdown(t["answer"])
        render_details(t)

question = st.chat_input(f"Ask {name}…", disabled=bool(blocked))
if question:
    history = []
    for t in st.session_state.turns[-6:]:
        if not t["q"].startswith("@"):
            history += [HumanMessage(content=t["q"]), AIMessage(content=t["answer"])]
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Querying…"):
            try:
                r = ask(agent, question, history, db=None if target == "auto" else target,
                        model=model)
                turn = {"q": question, "answer": r.answer, "calls": r.tool_calls, "sql": r.sql,
                        "model": r.model}
            except Exception as e:
                turn = {"q": question, "answer": f"⚠️ Error: {e}", "calls": [], "sql": []}
        st.markdown(turn["answer"])
        render_details(turn)
    st.session_state.turns.append(turn)
