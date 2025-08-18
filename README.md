# adobe-hackathon-finale

Full-stack project skeleton with a Python FastAPI backend and a frontend placeholder.

- backend: FastAPI application
- frontend: your web UI (React/Vite, Next.js, or any framework)

## Environment setup

Backend (.env in `backend/`):

```
GOOGLE_API_KEY=your_google_api_key
# UVICORN_HOST=127.0.0.1
# UVICORN_PORT=8001
```

Frontend (.env in `frontend/pdf-reader-ui/`):

```
VITE_ADOBE_CLIENT_ID=your_adobe_embed_client_id
VITE_API_BASE_URL=http://127.0.0.1:8001
```

Notes:

- Backend loads .env via python-dotenv.
- Frontend requires variables prefixed with `VITE_`.
