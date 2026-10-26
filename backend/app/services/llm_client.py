import httpx
from fastapi import HTTPException

from app.core.config import settings


def complete(system: str, user: str, max_tokens: int = 1000) -> str:
    """Appel LLM unique (API Ollama). Seul fichier à modifier pour changer de fournisseur."""
    options = {
        "temperature": 0,
        # les modèles qui raisonnent consomment une partie du budget en "réflexion"
        "num_predict": max(max_tokens, settings.llm_min_output_tokens),
    }
    if settings.llm_num_ctx > 0:
        options["num_ctx"] = settings.llm_num_ctx

    payload = {
        "model": settings.llm_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": options,
    }
    if settings.llm_think is not None:
        payload["think"] = settings.llm_think

    headers = {}
    if settings.ollama_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"

    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_s)
    except httpx.ConnectError:
        raise HTTPException(503, f"Impossible de joindre {settings.ollama_base_url} (réseau ?).")
    except httpx.TimeoutException:
        raise HTTPException(504, "Le modèle a mis trop de temps à répondre. Réessaie.")
    except httpx.HTTPError:
        raise HTTPException(502, "Erreur de communication avec l'API Ollama.")

    if r.status_code in (401, 403):
        raise HTTPException(503, "Clé API Ollama invalide ou sans permission (OLLAMA_API_KEY dans backend/.env).")
    if r.status_code == 404:
        raise HTTPException(
            503, f"Modèle « {settings.llm_model} » introuvable. Liste les modèles : https://ollama.com/api/tags"
        )
    if r.status_code == 429:
        raise HTTPException(429, "Limite d'utilisation de l'API Ollama atteinte. Réessaie plus tard.")
    if r.status_code >= 400:
        raise HTTPException(502, f"L'API Ollama a renvoyé une erreur ({r.status_code}).")

    try:
        content = r.json()["message"]["content"] or ""
    except (KeyError, ValueError):
        raise HTTPException(502, "Réponse de l'API Ollama illisible.")
    if not content.strip():
        raise HTTPException(502, "Le modèle a renvoyé une réponse vide (réflexion trop longue ?). Réessaie.")
    return content