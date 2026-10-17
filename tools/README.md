# Tools

Developer scripts.

| Tool | What it does |
| --- | --- |
| [`check.sh`](check.sh) | Builds the core and runs its tests and every game mode's tests: the same checks as CI |
| [`dev/Dockerfile`](dev/Dockerfile) | A Linux build environment matching CI, for machines without a C toolchain |

Using the dev container (from the repository root):

```sh
docker build -t atalaia-dev tools/dev
docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
```

On Windows, use `${PWD}` in PowerShell or `$(pwd -W)` in Git Bash for the volume path.

Planned: code generation from `protocol/schema`.
