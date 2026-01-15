"""
Threads Publisher Cloud Function

Publishes content to Threads using the Meta Graph API.
Uses a two-step process: create container, then publish.
Credentials are fetched from Secret Manager at runtime.
"""

import functions_framework
from google.cloud import secretmanager
import requests
import time

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


@functions_framework.http
def publish_threads(request):
    """
    HTTP Cloud Function to publish to Threads.

    Expected JSON body:
    {
        "content": "The post content"
    }

    Uses two-step publish process:
    1. Create media container
    2. Publish the container
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

    # Get credentials from Secret Manager
    try:
        access_token = get_secret("threads-access-token")
        user_id = get_secret("threads-user-id")
    except Exception as e:
        return {"error": f"Failed to retrieve secrets: {str(e)}"}, 500

    base_url = "https://graph.threads.net/v1.0"

    # Step 1: Create media container
    try:
        container_url = f"{base_url}/{user_id}/threads"
        container_params = {
            "media_type": "TEXT",
            "text": content,
            "access_token": access_token,
        }

        container_response = requests.post(
            container_url, params=container_params, timeout=30
        )
        container_response.raise_for_status()
        container_id = container_response.json().get("id")

        if not container_id:
            return {"error": "No container ID returned"}, 500

    except requests.exceptions.HTTPError as e:
        return {
            "error": f"Container creation failed: {str(e)}",
            "status_code": e.response.status_code if e.response else 500,
        }, e.response.status_code if e.response else 500

    # Brief pause for container processing
    time.sleep(1)

    # Step 2: Publish the container
    try:
        publish_url = f"{base_url}/{user_id}/threads_publish"
        publish_params = {"creation_id": container_id, "access_token": access_token}

        publish_response = requests.post(publish_url, params=publish_params, timeout=30)
        publish_response.raise_for_status()

        return {
            "success": True,
            "platform": "threads",
            "post_id": publish_response.json().get("id"),
            "status_code": publish_response.status_code,
        }, 200

    except requests.exceptions.HTTPError as e:
        return {
            "error": f"Publish failed: {str(e)}",
            "status_code": e.response.status_code if e.response else 500,
        }, e.response.status_code if e.response else 500
    except Exception as e:
        return {"error": str(e)}, 500
