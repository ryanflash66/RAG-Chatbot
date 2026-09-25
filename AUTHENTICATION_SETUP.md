# Authentication

The Chainlit chat UI requires a login. Chat history is stored per logged-in user, so logins also keep each user's history separate.

## Setup

In `.env`:

```bash
CHAINLIT_AUTH_SECRET=...           # generate with: chainlit create-secret
CHAINLIT_AUTH_USERNAME=analyst
CHAINLIT_AUTH_PASSWORD=choose-a-strong-password
```

- `auth_callback` in `app.py` compares the submitted credentials with these values using a constant-time comparison.
- If either variable is unset, **every login is refused** and the server logs a message saying so. There are no built-in default credentials.
- `CHAINLIT_AUTH_SECRET` signs the session tokens. Changing it logs everyone out.

## One account, one history

This is a single shared account. Everyone who logs in with it sees the same chat history (`chat_history/<username>/`). For separate users, replace `auth_callback` with a lookup against your user store, or use Chainlit's OAuth or header auth:

```python
@cl.oauth_callback
def oauth_callback(provider_id, token, raw_user_data, default_user):
    return default_user   # identifier becomes the history folder name
```

The user identifier becomes the history folder name. Characters other than letters, digits, `_` and `-` are replaced with `_`.

## Troubleshooting

- **The login is always rejected.** Check that both `CHAINLIT_AUTH_USERNAME` and `CHAINLIT_AUTH_PASSWORD` are set in `.env`, and read the server log.
- **Chainlit reports a missing auth secret.** Set `CHAINLIT_AUTH_SECRET`.
- **You're logged out after a restart.** The secret changed.
