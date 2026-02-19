from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/health")
async def health_check():
    """
    Health check endpoint to verify that the API is running.
    - when was it last restarted
    - current status of the application
    - any other relevant information (e.g., uptime, version)

    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "0.1.0",
        
    }