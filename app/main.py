import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from typing import Literal

from .categories import (
    ALL_GROUPS,
    CATEGORIES,
    KIDS,
    build_view,
)
from .pihole import PiHoleClient, PiHoleError
from .schedule_store import ScheduleStore, ScheduleValidationError
from .scheduler import (
    DAY_NAMES,
    active_end,
    describe_days,
    describe_schedule,
    describe_when,
    end_crosses_midnight,
    format_duration,
    is_active,
    next_change,
    scheduled_states,
)

pihole = PiHoleClient(os.environ["PIHOLE_URL"])
store = ScheduleStore(os.environ.get("SCHEDULE_DIR", "data"))
tick_seconds = float(os.environ.get("SCHEDULER_TICK_SECONDS", "30"))
tick_error = None


class StateUpdate(BaseModel):
    state: Literal["BLOCKED", "ALLOWED"]


class ScheduleIn(BaseModel):
    name: str = ""
    days: list
    start: str
    end: str
    categories: list

    @field_validator("days", "categories", mode="before")
    @classmethod
    def _coerce_single_to_list(cls, value):
        if isinstance(value, (str, int)):
            return [value]
        return value


def groups_by_name(payload):
    return {group["name"]: group for group in payload["groups"]}


def missing_groups_message(names):
    return (
        "Pi-hole group(s) " + ", ".join(names) + " do not exist. "
        "Create them in Pi-hole first."
    )


def schedule_view(now=None):
    now = now or datetime.now()
    state = store.load_state()
    schedules = store.load_schedules()
    desired = scheduled_states(schedules, now)
    change = next_change(schedules, now)
    next_info = None
    if change is not None:
        when, changes = change
        next_info = {
            "when": describe_when(when, now),
            "time": when.strftime("%H:%M"),
            "delta": format_duration(when - now),
            "text": ", ".join(
                f"{CATEGORIES[category]}: {before.lower()} to {after.lower()}"
                for category, (before, after) in sorted(changes.items())
            ),
        }
    category_info = {}
    for key, label in CATEGORIES.items():
        end = active_end(schedules, now, key)
        category_info[key] = {
            "name": label,
            "state": desired[key],
            "until": end.strftime("%H:%M") if end is not None else None,
        }
    return {
        "paused": state.paused,
        "tick_error": None if state.paused else tick_error,
        "schedules": [
            {
                "id": schedule.id,
                "description": describe_schedule(schedule),
                "days": describe_days(schedule.days),
                "window": f"{schedule.start}\u2013{schedule.end}"
                + (" (until tomorrow)" if end_crosses_midnight(schedule) else ""),
                "categories": ", ".join(
                    CATEGORIES[c] for c in schedule.categories
                ),
                "category_keys": list(schedule.categories),
                "active_now": is_active(schedule, now),
                "edit_json": {
                    "id": schedule.id,
                    "name": schedule.name,
                    "days": list(schedule.days),
                    "start": schedule.start,
                    "end": schedule.end,
                    "categories": list(schedule.categories),
                },
            }
            for schedule in schedules
        ],
        "next": next_info,
        "categories": category_info,
        "day_labels": list(enumerate(DAY_NAMES)),
        "category_labels": list(CATEGORIES.items()),
        "now": now.strftime("%a %H:%M"),
    }


@asynccontextmanager
async def lifespan(_app):
    state = store.load_state()
    if not state.last_enforced:
        state.last_enforced = scheduled_states(
            store.load_schedules(), datetime.now()
        )
        store.save_state(state)
    task = asyncio.create_task(tick_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def tick_loop():
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            await scheduler_tick()
        except Exception:
            global tick_error
            tick_error = (
                "The scheduler hit an unexpected error and will retry."
            )


async def scheduler_tick(now=None):
    global tick_error
    now = now or datetime.now()
    state = store.load_state()
    if state.paused:
        return
    schedules = store.load_schedules()
    desired = scheduled_states(schedules, now)
    changes = [
        category
        for category in CATEGORIES
        if state.last_enforced.get(category, desired[category])
        != desired[category]
    ]
    if not changes:
        tick_error = None
        return
    try:
        payload = await pihole.get_groups()
    except PiHoleError as exc:
        tick_error = str(exc)
        return
    groups = groups_by_name(payload)
    for name in changes:
        if name not in groups:
            continue
        try:
            await pihole.replace_group(
                name, groups[name]["comment"], desired[name] == "BLOCKED"
            )
        except PiHoleError as exc:
            tick_error = str(exc)
            return
    state.last_enforced.update(
        {name: desired[name] for name in changes if name in groups}
    )
    store.save_state(state)
    missing = [name for name in changes if name not in groups]
    tick_error = missing_groups_message(missing) if missing else None


app = FastAPI(title="Family Pi-hole Control", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


async def fetch_view():
    payload = await pihole.get_groups()
    return build_view(payload["groups"])


async def render_dashboard(request, view, error, note=None):
    schedule = schedule_view()
    if view is not None and not schedule["paused"]:
        for row in view["categories"]:
            scheduled = schedule["categories"].get(row["key"], {}).get("state")
            row["override"] = (
                scheduled is not None
                and row["state"] in ("BLOCKED", "ALLOWED")
                and row["state"] != scheduled
            )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"view": view, "error": error, "note": note,
                 "schedule": schedule},
    )


async def apply_group_states(request, groups, names, enabled):
    try:
        for name in names:
            await pihole.replace_group(
                name, groups[name]["comment"], enabled
            )
        view = await fetch_view()
        error = None
    except PiHoleError as exc:
        view = None
        error = str(exc)
    return await render_dashboard(request, view, error)


async def set_single_group(request, name, update):
    try:
        payload = await pihole.get_groups()
    except PiHoleError as exc:
        return await render_dashboard(request, None, str(exc))

    groups = groups_by_name(payload)
    if name not in groups:
        return await render_dashboard(
            request,
            build_view(payload["groups"]),
            missing_groups_message([name]),
        )
    return await apply_group_states(
        request, groups, [name], update.state == "BLOCKED"
    )


async def render_after_change(request, note):
    try:
        view = await fetch_view()
        error = None
    except PiHoleError as exc:
        view = None
        error = str(exc)
    return await render_dashboard(request, view, error, note=note)


async def render_validation_error(request, message):
    response = await render_dashboard(request, None, message)
    response.status_code = 422
    return response


@app.exception_handler(RequestValidationError)
async def handle_request_validation(request, exc):
    parts = []
    for error in exc.errors():
        field = ".".join(
            str(part) for part in error.get("loc", ()) if part != "body"
        )
        message = error.get("msg", "invalid value")
        parts.append(f"{field}: {message}" if field else message)
    return await render_validation_error(
        request, "Check the schedule form: " + "; ".join(parts)
    )


@app.get("/")
async def home(request: Request):
    try:
        view = await fetch_view()
        error = None
    except PiHoleError as exc:
        view = None
        error = str(exc)
    return await render_dashboard(request, view, error)


@app.get("/api/groups")
async def api_groups():
    try:
        return await fetch_view()
    except PiHoleError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@app.post("/categories/{name}")
async def set_category(request: Request, name: str, update: StateUpdate):
    if name not in CATEGORIES:
        raise HTTPException(status_code=404, detail="Unknown category.")
    return await set_single_group(request, name, update)


@app.post("/people/{name}")
async def set_person(request: Request, name: str, update: StateUpdate):
    if name not in KIDS:
        raise HTTPException(status_code=404, detail="Unknown person.")
    return await set_single_group(request, name, update)


@app.post("/all")
async def set_all(request: Request, update: StateUpdate):
    try:
        payload = await pihole.get_groups()
    except PiHoleError as exc:
        return await render_dashboard(request, None, str(exc))

    groups = groups_by_name(payload)
    missing = [name for name in ALL_GROUPS if name not in groups]
    if missing:
        return await render_dashboard(
            request,
            build_view(payload["groups"]),
            missing_groups_message(missing),
        )
    return await apply_group_states(
        request, groups, list(ALL_GROUPS), update.state == "BLOCKED"
    )


@app.post("/schedules")
async def create_schedule(request: Request, body: ScheduleIn):
    try:
        store.add_schedule(
            body.name, body.days, body.start, body.end, body.categories
        )
    except ScheduleValidationError as exc:
        return await render_validation_error(request, str(exc))
    return await render_after_change(request, "Schedule added.")


@app.post("/schedules/{schedule_id}")
async def update_schedule(request: Request, schedule_id: str, body: ScheduleIn):
    try:
        updated = store.update_schedule(
            schedule_id, body.name, body.days, body.start, body.end,
            body.categories,
        )
    except ScheduleValidationError as exc:
        return await render_validation_error(request, str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="Unknown schedule.")
    return await render_after_change(request, "Schedule updated.")


@app.post("/schedules/{schedule_id}/delete")
async def delete_schedule(request: Request, schedule_id: str):
    if not store.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Unknown schedule.")
    return await render_after_change(request, "Schedule deleted.")


@app.post("/schedule/pause")
async def pause_scheduler(request: Request):
    state = store.load_state()
    state.paused = True
    store.save_state(state)
    return await render_after_change(
        request, "Scheduler paused. Manual controls are in charge."
    )


@app.post("/schedule/resume")
async def resume_scheduler(request: Request):
    state = store.load_state()
    state.paused = False
    store.save_state(state)
    await scheduler_tick()
    return await render_after_change(request, "Scheduler resumed.")
