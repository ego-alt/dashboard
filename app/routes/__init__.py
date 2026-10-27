"""The dashboard's endpoints, one module per area; app/main.py includes them all.

  account      sign in and out, your account, /auth/verify for nginx
  totp         two-factor sign-in with an authenticator app
  passkeys     passkeys (WebAuthn)
  tokens       API tokens for native apps
  users        managing people (admins)
  services     the Services page: tiles, icons, uptime
  containers   the Monitor page: containers and the host
  backups      the last backup run
  deploy       the Deploy tab
  phone_apps   phone apps on Services, and their update check
"""
