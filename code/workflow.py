"""LangGraph workflow for the Streamlit application."""

import operator
from pathlib import Path
from typing import Annotated, Literal, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_tavily import TavilySearch
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .prompts import GENERAL_PROMPT, RAG_PROMPT, ROUTER_PROMPT, VALIDATION_PROMPT


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


class RouteQuery(BaseModel):
    step: Literal["llm", "rag", "web_scraper"]
    reasoning: str = Field(description="Why this worker is appropriate")


class ValidationResult(BaseModel):
    is_valid: bool
    reason: str


def build_workflow(data_dir: Path | None = None):
    """Create the complete supervisor, worker, retrieval, and validation graph."""
    load_dotenv()
    data_path = data_dir or Path(__file__).resolve().parent.parent / "data"

    # Build the local retrieval index once when Streamlit initializes the graph.
    documents = DirectoryLoader(str(data_path), glob="**/*.txt", loader_cls=TextLoader).load()
    chunks = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=50).split_documents(documents)
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    retriever = Chroma.from_documents(chunks, embeddings).as_retriever(search_kwargs={"k": 2})
    llm = ChatGroq(model_name="llama-3.3-70b-versatile")
    route_parser = PydanticOutputParser(pydantic_object=RouteQuery)
    validation_parser = PydanticOutputParser(pydantic_object=ValidationResult)

    def question_from(state: AgentState) -> str:
        """Normalize LangChain messages and notebook string inputs to plain text."""
        message = state["messages"][0]
        return message.content if hasattr(message, "content") else str(message)

    def supervisor(state: AgentState):
        """Select the worker that best matches the user's question."""
        prompt = PromptTemplate(
            template=ROUTER_PROMPT,
            input_variables=["question"],
            partial_variables={"format_instructions": route_parser.get_format_instructions()},
        )
        try:
            route = (prompt | llm | route_parser).invoke({"question": question_from(state)})
            decision = route.step
        except Exception:
            decision = "llm"
        return {"messages": [AIMessage(content=decision)]}

    def route(state: AgentState):
        """Keep model output inside the graph's known route set."""
        decision = str(state["messages"][-1].content).strip().lower()
        return decision if decision in {"llm", "rag", "web_scraper"} else "llm"

    def llm_worker(state: AgentState):
        """Answer general questions without retrieval or web search."""
        prompt = PromptTemplate(template=GENERAL_PROMPT, input_variables=["question"])
        answer = (prompt | llm | StrOutputParser()).invoke({"question": question_from(state)})
        return {"messages": [AIMessage(content=answer)]}

    def rag_worker(state: AgentState):
        """Answer document questions from the local Chroma retriever."""
        prompt = PromptTemplate(template=RAG_PROMPT, input_variables=["context", "question"])

        def format_docs(docs):
            return "\n\n".join(document.page_content for document in docs)

        chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )
        answer = chain.invoke(question_from(state))
        return {"messages": [AIMessage(content=answer)]}

    def web_worker(state: AgentState):
        """Answer current-information questions with Tavily search."""
        try:
            answer = str(TavilySearch().invoke(question_from(state)))
        except Exception as exc:
            answer = f"Web search failed: {exc}"
        return {"messages": [AIMessage(content=answer)]}

    def validator(state: AgentState):
        """Check the selected worker's answer before returning it to the UI."""
        answer = state["messages"][-1].content
        prompt = PromptTemplate(
            template=VALIDATION_PROMPT,
            input_variables=["query", "answer"],
            partial_variables={"format_instructions": validation_parser.get_format_instructions()},
        )
        try:
            result = (prompt | llm | validation_parser).invoke(
                {"query": question_from(state), "answer": answer}
            )
            decision = "valid" if result.is_valid else "invalid"
        except Exception:
            decision = "valid"
        return {"messages": [AIMessage(content=decision)]}

    def validation_route(state: AgentState):
        return "valid" if state["messages"][-1].content == "valid" else "invalid"

    # The validator can retry through the supervisor when an answer is insufficient.
    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", supervisor)
    workflow.add_node("llm", llm_worker)
    workflow.add_node("rag", rag_worker)
    workflow.add_node("web_scraper", web_worker)
    workflow.add_node("validator", validator)
    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", route, {"llm": "llm", "rag": "rag", "web_scraper": "web_scraper"})
    workflow.add_edge("llm", "validator")
    workflow.add_edge("rag", "validator")
    workflow.add_edge("web_scraper", "validator")
    workflow.add_conditional_edges("validator", validation_route, {"valid": END, "invalid": "supervisor"})
    return workflow.compile()