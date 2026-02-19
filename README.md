# DocChat

A FastAPI application for document-based chat. Upload documents and chat with their contents.

## Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # or ./venv/bin/activate on macOS with conda

# Install dependencies
pip install -r requirements.txt
```

## Running

```bash
./venv/bin/uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/documents` | Upload a document |
| `GET` | `/api/v1/documents/{id}` | Get document status and metadata |

### Upload a document

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@/path/to/document.pdf;type=application/pdf"
```

Supported formats: **PDF**, **DOCX**, **TXT** (max 10 MB)

### Response

```json
{
  "id": "96cf2491-d952-4666-a4cc-6c5fb08162e7",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "status": "ready",
  "chunk_count": 9,
  "error_message": null,
  "created_at": "2026-02-19T10:38:24"
}
```

## Configuration

Set via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./docchat.db` | Database connection string |
| `UPLOAD_DIR` | `./uploads` | Directory for uploaded files |
| `MAX_UPLOAD_BYTES` | `10485760` | Max file size (10 MB) |
| `DEBUG` | `true` | Enable SQLAlchemy query logging |
