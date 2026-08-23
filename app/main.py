import os

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from .pihole import PiHoleClient, PiHoleError


app = FastAPI(title="Family Pi-hole Control")

templates = Jinja2Templates(
    directory="app/templates"
)

pihole = PiHoleClient(
    os.environ["PIHOLE_URL"]
)


@app.get("/")
async def home(request: Request):

    groups = None
    error = None

    try:
        result = await pihole.get_groups()
        groups = result["groups"]
    except PiHoleError as exc:
        error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "groups": groups,
            "error": error,
        },
    )