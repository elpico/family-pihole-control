Family Pi-hole Control

A lightweight family-friendly web UI for controlling an existing Pi-hole installation.

The application simplifies common Pi-hole operations needed for family network management while leaving Pi-hole as the DNS filtering and enforcement engine.

Current status

Early development — MVP1.

The first MVP reads the existing Pi-hole groups and displays them through a simple FastAPI/Jinja2 web application.

Architecture

Python

FastAPI

Jinja2

HTMX (planned for interactive controls)

SQLite (planned)

APScheduler (planned)

Docker / Docker Compose

Raspberry Pi 5 deployment target

Development

Development is performed on a Linux workstation. The development Docker container connects over the LAN to the real Pi-hole running on the Raspberry Pi.

Linux development PC
    │
    ├── Docker
    │    └── Family Control
    │
    │ HTTP
    ▼
Raspberry Pi 5
    └── Pi-hole

Prerequisites

Docker

Docker Compose

Network access to the Pi-hole installation

Check Docker:

docker --version
docker compose version

Configure Pi-hole connection

Create a local .env file:

cp .env.example .env

Set the Pi-hole URL:

PIHOLE_URL=http://192.168.1.115

Do not commit .env. It is intentionally excluded by .gitignore.

Before starting the application, verify that the development machine can reach the Pi-hole API:

curl -s http://192.168.1.115/api/groups | python3 -m json.tool

This should return the Pi-hole group information.

Build the Docker image

From the project root:

docker compose build

Start the application

For initial development, run in the foreground so that logs are visible:

docker compose up

The application listens on port 8080.

Open:

http://localhost:8080

The FastAPI documentation is also available at:

http://localhost:8080/docs

Stop the application

If running in the foreground:

Ctrl+C

If running detached:

docker compose down

Run in the background

Once the application is working:

docker compose up -d

Check the container:

docker ps

View logs:

docker logs family-control

Follow logs:

docker logs -f family-control

Rebuild after code changes

docker compose up -d --build

Deployment to Raspberry Pi 5

The production target is the Raspberry Pi 5 running Pi-hole.

The application will eventually be deployed from the GitHub repository:

GitHub
   │
   ▼
Raspberry Pi 5
   │
   └── Docker Compose
       └── Family Control

The Pi should have its own .env file containing the production Pi-hole URL. Do not copy the development .env into Git.

Initial deployment:

git clone https://github.com/elpico/family-pihole-control.git
cd family-pihole-control

Create/configure .env, then:

docker compose up -d --build

Git workflow

Development takes place on feature branches.

Example:

git switch -c feature/mvp1-groups-read

Make small logical commits:

git add .
git commit -m "Add Pi-hole API client"

Push the feature branch:

git push -u origin feature/mvp1-groups-read

Merge completed features into main.

Project documentation

See DESIGN.md for the architecture, API findings, UX model, deployment design, and open questions.