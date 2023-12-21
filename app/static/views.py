from fastapi import APIRouter
from starlette.responses import FileResponse

static_router = APIRouter()

ics_directory = "./calendars"  # Replace with your directory path

@router.get("/calendars/{filename}")
async def serve_calendar(filename: str):
    return FileResponse(f"{ics_directory}/{filename}")