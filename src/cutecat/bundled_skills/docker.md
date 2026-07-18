# Docker

Use when writing or fixing a Dockerfile, a compose file, or when an image is
huge, slow to build, or behaves differently from the host.

## A Dockerfile that doesn't hurt

```dockerfile
# 1. Pin the base. "latest" is not reproducible.
FROM python:3.12-slim AS build

WORKDIR /app

# 2. Dependencies BEFORE source: this layer is cached until the manifest
#    changes, so an edit to your code doesn't reinstall the world.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir .

# 3. Then the code.
COPY src/ src/

# 4. A separate runtime stage: the compiler and the build cache do not ship.
FROM python:3.12-slim
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /app /app
WORKDIR /app

# 5. Don't run as root.
RUN useradd --system app && chown -R app /app
USER app

CMD ["python", "-m", "myapp"]
```

## Rules

- **Layer order is cache order.** Anything that changes often goes last. Copying
  the whole source before installing deps means every keystroke rebuilds them.
- **Use a `.dockerignore`.** Without it, `.git`, `node_modules`, and your `.venv`
  are shipped into the build context — slow builds and leaked secrets.
- **Never bake a secret into an image.** Layers are forever, even if a later
  layer deletes the file. Use build secrets or runtime env vars.
- **Multi-stage** for anything compiled: the toolchain stays behind.
- **One process per container.** If you're reaching for supervisord, you want two
  containers.
- **Pin the base image**, and rebuild it regularly for the security patches —
  those two are in tension, and the answer is a pinned digest plus a scheduled
  bump, not `:latest`.

## When it "works locally but not in the container"

Check, in this order: the working directory, the user (root vs not), the env
vars, the network (`localhost` inside a container is the container), and file
permissions on a mounted volume. It is almost always one of those five.
