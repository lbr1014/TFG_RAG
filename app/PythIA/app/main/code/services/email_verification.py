"""
Author: Lydia Blanco Ruiz
Script para verificar correos electrónicos usando la API de Emailable.
"""

import requests
from flask import current_app


def verify_email(email: str) -> dict:
    """
    Verifica un correo mediante Emailable API.
    
    Args: 
        email (str): Correo electrónico a verificar.
    """

    api_key = current_app.config.get("EMAILABLE_API_KEY")
    if not api_key:
        return {"state": "skipped", "reason": "missing_api_key"}

    url = "https://api.emailable.com/v1/verify"

    params = {
        "email": email.strip().lower(),
        "api_key": api_key
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10,
            headers={"Accept": "application/json"},
        )

        response.raise_for_status()

        payload = response.json()
        return payload if isinstance(payload, dict) else {"state": "error"}

    except requests.RequestException:
        return {
            "state": "error"
        }
