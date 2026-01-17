"""
LinkedIn Publisher Cloud Function

Publishes content to LinkedIn using the REST API.
Credentials are fetched from Secret Manager at runtime.
"""

import functions_framework
from google.cloud import secretmanager
import requests
import re

# Lazy-initialized clients
_secrets_client = None
PROJECT_ID = None


def get_secrets_client():
    """Lazy initialization of Secret Manager client."""
    global _secrets_client
    if _secrets_client is None:
        _secrets_client = secretmanager.SecretManagerServiceClient()
    return _secrets_client


def get_secret(name: str) -> str:
    """Fetch a secret from Secret Manager."""
    client = get_secrets_client()
    resource = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    response = client.access_secret_version(request={"name": resource})
    return response.payload.data.decode("UTF-8")


def escape_linkedin_chars(text: str) -> str:
    """Escape reserved characters for LinkedIn API."""
    reserved = r"[|{}@\[\]()<>#*_~\\]"
    return re.sub(reserved, r"\\\g<0>", text)


def format_content(content: str, audio_url: str = "") -> str:
    """Format content for LinkedIn with optional audio link."""
    formatted = escape_linkedin_chars(content)
    if audio_url:
        formatted += f"\n\n🎧 Listen: {audio_url}"
    return formatted


@functions_framework.http
def publish_linkedin(request):
    """
    HTTP Cloud Function to publish to LinkedIn.

    Expected JSON body:
    {
        "content": "The post content",
        "audio_url": "Optional URL to audio version"
    }
    """
    global PROJECT_ID

    # Get project ID from environment
    import os

    PROJECT_ID = os.environ.get("GCP_PROJECT")

    # Parse request
    request_json = request.get_json(silent=True)
    if not request_json or "content" not in request_json:
        return {"error": "Missing content field"}, 400

    content = request_json["content"]
    audio_url = request_json.get("audio_url", "")

    # Get credentials from Secret Manager
    try:
        access_token = get_secret("linkedin-access-token")
        author_urn = get_secret("linkedin-urn")
    except Exception as e:
        return {"error": f"Failed to retrieve secrets: {str(e)}"}, 500

    # Format content
    formatted_content = format_content(content, audio_url)

    # Build LinkedIn API request
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202601",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    payload = {
        "author": author_urn,
        "commentary": formatted_content,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    # Make API call
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return {
            "success": True,
            "platform": "linkedin",
            "status_code": response.status_code,
        }, 200
    except requests.exceptions.HTTPError as e:
        return {
            "error": str(e),
            "status_code": e.response.status_code if e.response else 500,
        }, e.response.status_code if e.response else 500
    except Exception as e:
        return {"error": str(e)}, 500
