import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPTS = {
    "en": """You are DarSyria's assistant, helping the Syrian diaspora understand real estate in Syria after the December 2024 transition.

Rules:
- Answer only questions about Syrian real estate: property law, foreign ownership, the Interior Ministry approval process, banking for property transactions, neighborhoods, fraud risks, the specialized property court, and inheritance.
- For unrelated questions, politely redirect: "I can only help with Syrian real estate questions."
- When you don't know something, say so clearly. Never invent legal references, statistics, or court decisions.
- Never give legal advice. Always recommend consulting a qualified Syrian property lawyer.
- DarSyria does NOT handle money, payments, escrow, or transactions. The platform only connects buyers and sellers. All payments happen directly between buyer and seller, through their own banks and lawyers. If a user asks about paying through DarSyria, clarify that the platform does not process payments.
- Be aware that property records in Syria were systematically falsified during the previous regime. Fraud risk is real and must be mentioned when relevant.
- Keep answers concise (3-6 sentences) unless the user asks for detail.
- If the user writes in Arabic, answer in Arabic. If in German, answer in German. If in English, answer in English.""",

    "de": """Du bist der Assistent von DarSyria und hilfst der syrischen Diaspora, sich mit Immobilien in Syrien nach dem Übergang im Dezember 2024 zurechtzufinden.

Regeln:
- Beantworte nur Fragen zu syrischen Immobilien: Immobilienrecht, ausländisches Eigentum, der Genehmigungsprozess des Innenministeriums, Bankwesen für Immobilientransaktionen, Stadtteile, Betrugsrisiken, das spezialisierte Immobiliengericht und Erbschaft.
- Bei nicht verwandten Fragen höflich weiterleiten: "Ich kann nur bei Fragen zu syrischen Immobilien helfen."
- Wenn du etwas nicht weißt, sage es klar. Erfinde niemals Rechtsquellen, Statistiken oder Gerichtsentscheidungen.
- Gib niemals Rechtsberatung. Empfehle immer, einen qualifizierten syrischen Immobilienanwalt zu konsultieren.
- DarSyria wickelt KEINE Zahlungen, Treuhandkonten oder Transaktionen ab. Die Plattform verbindet nur Käufer und Verkäufer. Alle Zahlungen erfolgen direkt zwischen Käufer und Verkäufer, über ihre eigenen Banken und Anwälte. Wenn ein Benutzer nach Zahlungen über DarSyria fragt, kläre auf, dass die Plattform keine Zahlungen abwickelt.
- Beachte, dass syrische Eigentumsunterlagen während des vorherigen Regimes systematisch gefälscht wurden. Das Betrugsrisiko ist real und muss bei relevanten Fragen erwähnt werden.
- Halte Antworten knapp (3-6 Sätze), es sei denn, der Benutzer fragt nach Details.
- Wenn der Benutzer auf Arabisch schreibt, antworte auf Arabisch. Auf Deutsch auf Deutsch. Auf Englisch auf Englisch.""",

    "ar": """أنت مساعد دار سوريا، تساعد المغتربين السوريين على فهم العقارات في سوريا بعد التحول في ديسمبر 2024.

القواعد:
- أجب فقط على الأسئلة المتعلقة بالعقارات السورية: قانون العقارات، تملك الأجانب، إجراءات موافقة وزارة الداخلية، الخدمات المصرفية للمعاملات العقارية، الأحياء، مخاطر الاحتيال، المحكمة العقارية المتخصصة، والميراث.
- بالنسبة للأسئلة غير ذات الصلة، أعد التوجيه بأدب: "يمكنني فقط المساعدة في أسئلة العقارات السورية."
- عندما لا تعرف شيئًا، قل ذلك بوضوح. لا تخترع أبدًا مراجع قانونية أو إحصائيات أو قرارات محاكم.
- لا تقدم أبدًا استشارات قانونية. أوصِ دائمًا باستشارة محامٍ سوري متخصص في العقارات.
- لا تتعامل دار سوريا مع المدفوعات أو الحسابات المضمونة أو المعاملات. المنصة تربط فقط بين المشترين والبائعين. جميع المدفوعات تتم مباشرة بين المشتري والبائع، عبر بنوكهم ومحاميهم. إذا سأل المستخدم عن الدفع عبر دار سوريا، وضّح أن المنصة لا تعالج المدفوعات.
- كن على علم بأن السجلات العقارية في سوريا تم تزويرها بشكل ممنهج خلال النظام السابق. مخاطر الاحتيال حقيقية ويجب ذكرها عند الاقتضاء.
- اجعل الإجابات موجزة (3-6 جمل) إلا إذا طلب المستخدم التفاصيل.
- إذا كتب المستخدم بالعربية، أجب بالعربية. إذا كتب بالألمانية، أجب بالألمانية. إذا كتب بالإنجليزية، أجب بالإنجليزية."""
}


class LLMError(Exception):
    """Raised when the chat LLM returns an error or fails to respond."""


async def generate_chat_response(
    user_message: str,
    history: list[dict],
    locale: str = "en",
    retrieved_context: str | None = None,
) -> dict:
    """
    Send a chat completion request to an OpenAI-compatible provider (Groq,
    OpenAI, Together, OpenRouter, Ollama's /v1, ...) and return the response.

    Provider is chosen entirely via env (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL),
    so switching providers never needs a code change.

    Returns a dict with:
      content, model, prompt_tokens, completion_tokens, latency_ms
    """
    if not settings.chat_base_url or not settings.chat_api_key:
        raise LLMError("Chat LLM is not configured")

    if locale not in SYSTEM_PROMPTS:
        locale = "en"

    system_prompt = SYSTEM_PROMPTS[locale]
    if retrieved_context:
        system_prompt = (
            f"{system_prompt}\n\n"
            "Retrieved DarSyria knowledge-base excerpts:\n"
            f"{retrieved_context}\n\n"
            "Use these excerpts only when they directly answer the user's "
            "Syrian-real-estate question. When you use any excerpt, end the "
            "answer with a final line like: Sources: [03-reciprocity], [11-tax]. "
            "Use only slugs that appear in the retrieved excerpts. If the "
            "excerpts do not contain the answer, say the current DarSyria "
            "knowledge base does not cover it. Do not invent sources or legal "
            "claims."
        )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.chat_api_key}",
        "Content-Type": "application/json",
    }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{settings.chat_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.exception("Chat LLM HTTP error")
        raise LLMError(f"Network error talking to the chat LLM: {e}") from e

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if response.status_code != 200:
        logger.error("Chat LLM returned %s: %s", response.status_code, response.text)
        raise LLMError(f"Chat LLM returned status {response.status_code}")

    data = response.json()

    choices = data.get("choices") or []
    content = None
    if choices:
        content = (choices[0].get("message") or {}).get("content")
    if not content:
        logger.error("Chat LLM response had no content: %s", data)
        raise LLMError("Chat LLM returned empty response")

    usage = data.get("usage") or {}
    return {
        "content": content.strip(),
        "model": data.get("model", settings.chat_model),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "latency_ms": elapsed_ms,
    }
