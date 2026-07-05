"""Local operator tooling (FTY-250).

Host-run, read-only commands that help a self-hoster confirm the local stack is
coherent before using Fatty for real. These are *not* part of the request-serving
application; they shell out to Docker Compose and probe the running services.
"""
