"""Doc-type classification step -- the first stage of the single LangChain
retrieval chain. Uses .with_structured_output() (function-calling/JSON-mode
under the hood for OpenAI models) rather than a manual PydanticOutputParser
+ format-instructions prompt, since it's the more direct modern LangChain
API for this and was confirmed available on the installed langchain-openai
version during Phase 0.
"""
from langchain_openai import ChatOpenAI

from nrg_chains.prompts import CLASSIFY_PROMPT
from nrg_chains.schemas import ClassifiedQuery

CLASSIFIER_MODEL = "gpt-4o-mini"

_classifier_llm = ChatOpenAI(model=CLASSIFIER_MODEL, temperature=0)
_classify_chain = CLASSIFY_PROMPT | _classifier_llm.with_structured_output(ClassifiedQuery)


async def classify_question(question: str) -> ClassifiedQuery:
    return await _classify_chain.ainvoke({"question": question})
