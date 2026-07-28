# Gait KNR

Python exploration implementation of a causal gait event detector.

Run from the repository root:

```sh
python3 -m gait_knr.run_detection
```

By default, the script reads `backup/synchronized_walk.csv` and writes the
augmented result to `viewer/data/synchronized_walk.csv`. Backup files are never
modified.

## State Columns

- `0`: `STANCE`
- `1`: `EARLY_SWING`
- `2`: `MID_SWING`

## Event Columns

- `0`: `NONE`
- `1`: `EARLY_SWING_START`
- `2`: `MID_SWING_VALLEY`
- `3`: `STANCE_BY_TIMEOUT`
- `4`: `STANCE_BY_OPPOSITE_SWING`

Left `gyr_z` is treated as the conventional sign. Right `gyr_z` is multiplied by
`-1` before event detection so both sides share the same state-machine logic.

