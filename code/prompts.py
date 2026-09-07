"""Centralized prompt templates for the supervisor and worker nodes."""

ROUTER_PROMPT = """
You are a supervisor routing a user question to exactly one specialized worker.
Choose exactly one route:
- llm: general knowledge, reasoning, or conversation
- rag: questions answerable from the local knowledge base
- web_scraper: current events or information that requires web search

User question: {question}

{format_instructions}
"""

GENERAL_PROMPT = """
Answer the following question clearly and accurately using your knowledge.
Do not claim to have searched the web.

Question: {question}
"""

RAG_PROMPT = """
You answer questions using the retrieved context below.
If the context does not contain the answer, say that you do not know.
Keep the answer concise and use no more than three sentences.

Context:
{context}

Question: {question}
"""

VALIDATION_PROMPT = """
You are a quality reviewer. Decide whether the answer directly and usefully answers the question.
Mark an answer invalid when it is irrelevant or says it does not know.

Question: {query}
Answer: {answer}

{format_instructions}
"""