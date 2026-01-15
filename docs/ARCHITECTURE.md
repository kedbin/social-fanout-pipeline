# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LOCAL                                                                       │
│  ┌─────────────────┐                                                        │
│  │  Markdown File  │  Content with frontmatter (publish_social: true)       │
│  └────────┬────────┘                                                        │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │ git push
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GITHUB ACTIONS                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │  Detect Change  │ →  │  Extract Front  │ →  │  Authenticate   │         │
│  │  in content/*   │    │  matter + body  │    │  via WIF (OIDC) │         │
│  └─────────────────┘    └─────────────────┘    └────────┬────────┘         │
│                                                          │                   │
│                                              ┌───────────▼───────────┐      │
│                                              │  Publish to Pub/Sub   │      │
│                                              │  (JSON payload)       │      │
│                                              └───────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
            │
            ▼ Pub/Sub message
┌─────────────────────────────────────────────────────────────────────────────┐
│  GOOGLE CLOUD                                                                │
│                                                                              │
│  ┌─────────────────┐                                                        │
│  │    Eventarc     │  Listens for: google.cloud.pubsub.topic.v1.message    │
│  │    Trigger      │  Routes to: Cloud Workflow                             │
│  └────────┬────────┘                                                        │
│           │                                                                  │
│           ▼ triggers                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  CLOUD WORKFLOW                                                      │   │
│  │                                                                       │   │
│  │  ┌─────────────┐                                                     │   │
│  │  │  Log Start  │                                                     │   │
│  │  └──────┬──────┘                                                     │   │
│  │         │                                                             │   │
│  │         ▼                                                             │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │                    PARALLEL EXECUTION                        │    │   │
│  │  │                                                              │    │   │
│  │  │   ┌─────────────────┐         ┌─────────────────┐          │    │   │
│  │  │   │ LinkedIn Branch │         │ Threads Branch  │          │    │   │
│  │  │   │                 │         │                 │          │    │   │
│  │  │   │ Retry: 3x       │         │ Retry: 5x       │          │    │   │
│  │  │   │ Backoff: 2-60s  │         │ Backoff: 3-120s │          │    │   │
│  │  │   │                 │         │                 │          │    │   │
│  │  │   │      ▼          │         │      ▼          │          │    │   │
│  │  │   │ HTTP Call to    │         │ HTTP Call to    │          │    │   │
│  │  │   │ Cloud Function  │         │ Cloud Function  │          │    │   │
│  │  │   └─────────────────┘         └─────────────────┘          │    │   │
│  │  │                                                              │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  │         │                                                             │   │
│  │         ▼                                                             │   │
│  │  ┌──────────────┐                                                    │   │
│  │  │ Log Complete │                                                    │   │
│  │  └──────────────┘                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│           │ HTTP calls                                                       │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  CLOUD FUNCTIONS                                                     │   │
│  │                                                                       │   │
│  │  ┌─────────────────────┐         ┌─────────────────────┐            │   │
│  │  │  publish-linkedin   │         │  publish-threads    │            │   │
│  │  │                     │         │                     │            │   │
│  │  │  1. Get secret      │         │  1. Get secret      │            │   │
│  │  │  2. Format content  │         │  2. Format content  │            │   │
│  │  │  3. POST to API     │         │  3. Create container│            │   │
│  │  │  4. Return status   │         │  4. Publish container│           │   │
│  │  │                     │         │  5. Return status   │            │   │
│  │  └──────────┬──────────┘         └──────────┬──────────┘            │   │
│  │             │                               │                        │   │
│  │             ▼                               ▼                        │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │                    SECRET MANAGER                            │   │   │
│  │  │                                                              │   │   │
│  │  │  • linkedin-access-token    • threads-access-token          │   │   │
│  │  │  • linkedin-urn             • threads-user-id               │   │   │
│  │  │                                                              │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
            │
            ▼ API calls
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXTERNAL APIS                                                               │
│                                                                              │
│  ┌─────────────────┐         ┌─────────────────┐                           │
│  │   LinkedIn      │         │   Threads       │                           │
│  │   REST API      │         │   Graph API     │                           │
│  └─────────────────┘         └─────────────────┘                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Authentication Flow (Workload Identity Federation)

```
┌─────────────────┐
│  GitHub Action  │
│  requests OIDC  │
│  token          │
└────────┬────────┘
         │
         ▼ OIDC token (JWT)
┌─────────────────┐
│  Google Cloud   │
│  Security Token │
│  Service (STS)  │
└────────┬────────┘
         │
         ▼ Validates against Workload Identity Pool
┌─────────────────┐
│  Returns short- │
│  lived access   │
│  token (1 hour) │
└────────┬────────┘
         │
         ▼ Access token
┌─────────────────┐
│  GitHub Action  │
│  uses token for │
│  GCP API calls  │
└─────────────────┘
```

**Key Points:**
- No JSON keys stored anywhere
- Token lifetime: 1 hour (default)
- Permissions scoped to specific service account
- Audit trail in Cloud Logging

## Message Format

The Pub/Sub message payload (CloudEvents-style):

```json
{
  "content": "The main body of the post",
  "linkedin_content": "Platform-specific formatted version for LinkedIn",
  "threads_content": "Platform-specific formatted version for Threads",
  "audio_url": "https://audio.example.com/entry-xxx.mp3"
}
```

## Retry Logic

The retry predicate in the Workflow:

```yaml
retry_predicate:
  params: [e]
  steps:
    - check_error:
        switch:
          - condition: ${e.code == 429}   # Rate limit
            return: true
          - condition: ${e.code >= 500}   # Server error
            return: true
    - return_false:
        return: false
```

**Retries on:**
- HTTP 429 (Rate Limited)
- HTTP 5xx (Server errors)

**Does NOT retry on:**
- HTTP 4xx (Client errors like bad request, auth failures)

## APIs Enabled

The following Google Cloud APIs are required:

- `cloudfunctions.googleapis.com`
- `workflows.googleapis.com`
- `pubsub.googleapis.com`
- `cloudbuild.googleapis.com`
- `run.googleapis.com`
- `logging.googleapis.com`
- `secretmanager.googleapis.com`
- `eventarc.googleapis.com`
- `iam.googleapis.com`
- `iamcredentials.googleapis.com`

## Security Layers

1. **No long-lived credentials** — WIF eliminates service account keys
2. **Secrets isolated** — API tokens in Secret Manager, not in code or env vars
3. **OIDC-protected functions** — Cloud Functions require authenticated callers
4. **Minimal permissions** — Service account has only necessary IAM roles
5. **Audit logging** — All API calls and secret access logged
