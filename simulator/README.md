# Simulator

Runs the shared core on a desktop with any number of virtual nodes on a virtual clock. It is used to develop and test game modes before any hardware exists, and CI uses it to run every mode's `tests/`.

It is a small Python package that loads the core as a shared library, so modes behave exactly as they will on a prop.

## Run the mode tests

```sh
cmake -S core -B build -DATALAIA_SHARED=ON && cmake --build build
pip install -r simulator/requirements.txt
cd simulator
python -m atalaia_sim test                     # every mode in modes/
python -m atalaia_sim test ../modes/bomb       # one mode
```

The simulator looks for the library in `build/`. Point it elsewhere with `--lib PATH` or the `ATALAIA_CORE_LIB` environment variable. A failing test prints the merged event log and the scripts' log lines.

The test file format is described in [modes/README.md](../modes/README.md#tests).

## Status

| Feature | Status |
| --- | --- |
| Virtual nodes running `node.lua` | Done |
| Event-sequence tests | Done |
| Web view of screens, LEDs and events | Planned (phase 0) |
| `field.lua` and cross-node delivery | Phase 2, with the field controller |
