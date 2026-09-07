import streamlit as st
from langchain_core.messages import HumanMessage

from code.workflow import build_workflow


@st.cache_resource
def get_workflow():
    """Build the expensive embedding/vector workflow once per Streamlit process."""
    return build_workflow()


def main() -> None:
    st.set_page_config(page_title="VeriGraph-AI", page_icon="🛡️", layout="centered")
    st.title("VeriGraph-AI")
    st.caption("Ask a question and the supervisor will choose general knowledge, local documents, or web search.")

    with st.sidebar:
        st.subheader("Configuration")
        st.write("Set `GROQ_API_KEY` and `TAVILY_API_KEY` in the container environment.")
        st.write("The local RAG source is `data/usa.txt`.")

    question = st.text_area("Your question", placeholder="What is the industrial growth of the USA?", height=120)
    if st.button("Ask", type="primary", disabled=not question.strip()):
        with st.spinner("Working..."):
            try:
                result = get_workflow().invoke(
                    {"messages": [HumanMessage(content=question.strip())]},
                    config={"recursion_limit": 8},
                )
                messages = result.get("messages", [])
                answer = messages[-2].content if len(messages) >= 2 else messages[-1].content
                st.markdown(answer)
            except Exception as exc:
                st.error(f"The request could not be completed: {exc}")


if __name__ == "__main__":
    main()
