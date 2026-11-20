import csv
import json
import math
from pathlib import Path


def new_path(path, suffix):
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != suffix:
        raise ValueError("Expected " + suffix + " path")
    if target.exists():
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def export(connection, data_paths, output_path):
    if not data_paths or len(set(data_paths)) != len(data_paths):
        raise ValueError("Provide unique variable paths")
    target = new_path(output_path, ".csv")
    summary = target.with_suffix(".json")
    if summary.exists():
        raise FileExistsError(str(summary))
    series = [connection.api.AMEGetVariableValues(path) for path in data_paths]
    times = [pair[0] for pair in series[0]]
    if not times or any([p[0] for p in values] != times for values in series):
        raise ValueError("Missing data or inconsistent time grids")
    if not all(math.isfinite(v) for values in series for pair in values for v in pair):
        raise ValueError("Nonfinite simulation result")
    result = {"csv": str(target), "samples": len(times), "variables": data_paths,
              "start_time": times[0], "stop_time": times[-1]}
    with target.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s"] + data_paths)
        writer.writerows([t] + [values[i][1] for values in series] for i, t in enumerate(times))
    with summary.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return result
