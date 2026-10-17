# Tools

Developer scripts.

| Tool | What it does |
| --- | --- |
| [`check.sh`](check.sh) | Checks the generated protocol files, builds the core and runs its tests, the simulator's tests and every game mode's tests: the same checks as CI |
| [`protogen.py`](protogen.py) | Generates the C and Python protocol tables, the C test vectors and the JSON Schema from `protocol/schema/`; `--check` fails if they are stale. See [protocol/README.md](../protocol/README.md#changing-the-schema) |
| [`dev/Dockerfile`](dev/Dockerfile) | A Linux build environment matching CI, for machines without a C toolchain |

Using the dev container (from the repository root):

```sh
docker build -t atalaia-dev tools/dev
docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
```

On Windows, use `${PWD}` in PowerShell or `$(pwd -W)` in Git Bash for the volume path.
