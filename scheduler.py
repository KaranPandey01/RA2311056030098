import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

DEPOT_API_URL = "http://20.207.122.201/evaluation-service/depots"
VEHICLES_API_URL = "http://20.207.122.201/evaluation-service/vehicles"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "vehicle_scheduling"
REPORT_FILE = OUTPUT_DIR / "output.txt"
LOG_FILE = OUTPUT_DIR / "logs" / "scheduler.log"


class LoggingMiddleware:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._write("INFO", message, context)

    def warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._write("WARNING", message, context)

    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._write("ERROR", message, context)

    def success(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._write("SUCCESS", message, context)


@dataclass(frozen=True)
class VehicleTask:
    task_id: str
    duration: int
    impact: int


def write_report(lines: List[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_failure_report(reason: str, next_step: str) -> None:
    lines = [
        "Vehicle Maintenance Scheduling Output",
        "=" * 50,
        "Status: This run could not be completed.",
        "",
        f"What went wrong: {reason}",
        "",
        "What to do next:",
        next_step,
    ]
    write_report(lines)


def fetch_api_data(
    url: str,
    token: str,
    logger: LoggingMiddleware,
) -> Tuple[Dict[str, Any], Optional[str]]:
    headers = {"Authorization": f"Bearer {token.strip()}"}
    response = None

    logger.info("Trying to load data from the API.", {"url": url})

    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(
            "The API responded.",
            {"url": url, "status_code": response.status_code},
        )

        if response.status_code == 401:
            reason = (
                "The API returned 401 Unauthorized. "
                "The token is probably missing, incorrect, or expired."
            )
            logger.error("The API rejected the request.", {"url": url, "status_code": 401})
            return {}, reason

        response.raise_for_status()
        payload = response.json()
        logger.success("The response was loaded successfully.", {"url": url})
        return payload, None

    except requests.exceptions.Timeout:
        reason = "The request timed out before the API could respond."
        logger.error("The request timed out.", {"url": url})
        return {}, reason
    except requests.exceptions.RequestException as exc:
        reason = f"The request failed: {exc}"
        logger.error("The request failed.", {"url": url, "error": str(exc)})
        return {}, reason
    except ValueError:
        body = response.text if response is not None else "<no response>"
        reason = "The API responded, but the response was not valid JSON."
        logger.error(
            "The API response could not be parsed as JSON.",
            {"url": url, "response_body": body[:500]},
        )
        return {}, reason


def solve_knapsack(
    tasks: List[VehicleTask],
    capacity: int,
    logger: LoggingMiddleware,
) -> Tuple[int, int, List[VehicleTask]]:
    logger.info(
        "Starting the schedule calculation.",
        {"task_count": len(tasks), "capacity": capacity},
    )

    if capacity <= 0 or not tasks:
        logger.warning(
            "No schedule could be built because the capacity or task list was empty.",
            {"task_count": len(tasks), "capacity": capacity},
        )
        return 0, 0, []

    task_count = len(tasks)
    dp = [[0 for _ in range(capacity + 1)] for _ in range(task_count + 1)]

    for i in range(1, task_count + 1):
        task_duration = tasks[i - 1].duration
        task_impact = tasks[i - 1].impact

        for hours in range(capacity + 1):
            if task_duration > hours:
                dp[i][hours] = dp[i - 1][hours]
            else:
                dp[i][hours] = max(
                    dp[i - 1][hours],
                    dp[i - 1][hours - task_duration] + task_impact,
                )

    max_impact = dp[task_count][capacity]
    selected_tasks: List[VehicleTask] = []
    total_duration = 0
    remaining_capacity = capacity

    for i in range(task_count, 0, -1):
        if dp[i][remaining_capacity] != dp[i - 1][remaining_capacity]:
            task = tasks[i - 1]
            selected_tasks.append(task)
            total_duration += task.duration
            remaining_capacity -= task.duration

    selected_tasks.reverse()

    logger.success(
        "The best schedule for this depot has been calculated.",
        {
            "capacity": capacity,
            "selected_task_count": len(selected_tasks),
            "total_duration": total_duration,
            "max_impact": max_impact,
        },
    )
    return max_impact, total_duration, selected_tasks


def parse_vehicle_tasks(vehicle_data: Dict[str, Any], logger: LoggingMiddleware) -> List[VehicleTask]:
    tasks: List[VehicleTask] = []

    for vehicle in vehicle_data.get("vehicles", []):
        if not all(key in vehicle for key in ("TaskID", "Duration", "Impact")):
            logger.warning("A vehicle record was skipped because fields were missing.", {"vehicle": vehicle})
            continue

        try:
            task = VehicleTask(
                task_id=str(vehicle["TaskID"]),
                duration=int(vehicle["Duration"]),
                impact=int(vehicle["Impact"]),
            )
            tasks.append(task)
        except (TypeError, ValueError):
            logger.warning("A vehicle record was skipped because the values were invalid.", {"vehicle": vehicle})

    logger.info("Vehicle task parsing is complete.", {"valid_task_count": len(tasks)})
    return tasks


def build_depot_report(
    depot_id: Any,
    capacity: int,
    max_impact: int,
    total_duration: int,
    selected_tasks: List[VehicleTask],
) -> List[str]:
    lines = [
        f"Depot {depot_id}",
        f"Mechanic hours available: {capacity}",
        f"Best total impact score: {max_impact}",
        f"Hours used: {total_duration} out of {capacity}",
        f"Tasks selected: {len(selected_tasks)}",
        "Chosen tasks:",
    ]

    if selected_tasks:
        for task in selected_tasks:
            lines.append(
                f"  - TaskID: {task.task_id} "
                f"(Duration: {task.duration}, Impact: {task.impact})"
            )
    else:
        lines.append("  - No tasks were selected for this depot.")

    lines.append("-" * 50)
    return lines


def main() -> int:
    logger = LoggingMiddleware(LOG_FILE)
    logger.info(
        "The vehicle scheduling run has started.",
        {
            "depot_api_url": DEPOT_API_URL,
            "vehicles_api_url": VEHICLES_API_URL,
        },
    )

    api_token = (os.getenv("API_TOKEN") or "").strip()
    placeholder_tokens = {
        "",
        "your-token",
        "your-real-token",
        "actual-token-here",
        "paste-your-real-token-here",
    }

    if api_token in placeholder_tokens:
        reason = "No real API token was found in the API_TOKEN environment variable."
        next_step = 'Set the token first, for example: $env:API_TOKEN = "your-real-token"'
        logger.error(reason)
        write_failure_report(reason, next_step)
        return 1

    depot_data, depot_error = fetch_api_data(DEPOT_API_URL, api_token, logger)
    if depot_error:
        logger.error("The depot data could not be loaded.", {"reason": depot_error})
        write_failure_report(
            "We could not load the depot list from the API. " + depot_error,
            'Make sure API_TOKEN contains the real bearer token, then run: python .\\scheduler.py',
        )
        return 1

    if "depots" not in depot_data or not isinstance(depot_data["depots"], list):
        reason = "The depot API responded, but the data format was not what the script expected."
        logger.error(reason, {"payload": depot_data})
        write_failure_report(reason, "Check the API response format and run the script again.")
        return 1

    vehicle_data, vehicle_error = fetch_api_data(VEHICLES_API_URL, api_token, logger)
    if vehicle_error:
        logger.error("The vehicle data could not be loaded.", {"reason": vehicle_error})
        write_failure_report(
            "We could not load the vehicle task list from the API. " + vehicle_error,
            'Make sure API_TOKEN contains the real bearer token, then run: python .\\scheduler.py',
        )
        return 1

    if "vehicles" not in vehicle_data or not isinstance(vehicle_data["vehicles"], list):
        reason = "The vehicle API responded, but the data format was not what the script expected."
        logger.error(reason, {"payload": vehicle_data})
        write_failure_report(reason, "Check the API response format and run the script again.")
        return 1

    tasks = parse_vehicle_tasks(vehicle_data, logger)
    if not tasks:
        reason = "The vehicle API response did not contain any valid tasks to schedule."
        logger.error(reason)
        write_failure_report(reason, "Check the vehicle data coming from the API and try again.")
        return 1

    depots = depot_data["depots"]
    report_lines = [
        "Vehicle Maintenance Scheduling Output",
        "=" * 50,
        "Status: Completed successfully.",
        "",
        f"Depots processed: {len(depots)}",
        f"Valid vehicle tasks considered: {len(tasks)}",
        "-" * 50,
    ]

    processed_depots = 0

    for depot in depots:
        depot_id = depot.get("ID")
        raw_capacity = depot.get("MechanicHours")

        if depot_id is None or raw_capacity is None:
            logger.warning("A depot record was skipped because fields were missing.", {"depot": depot})
            continue

        try:
            capacity = int(raw_capacity)
        except (TypeError, ValueError):
            logger.warning("A depot record was skipped because MechanicHours was invalid.", {"depot": depot})
            continue

        logger.info(
            "Working on a depot schedule.",
            {"depot_id": depot_id, "capacity": capacity},
        )

        max_impact, total_duration, selected_tasks = solve_knapsack(tasks, capacity, logger)

        report_lines.extend(
            build_depot_report(
                depot_id=depot_id,
                capacity=capacity,
                max_impact=max_impact,
                total_duration=total_duration,
                selected_tasks=selected_tasks,
            )
        )

        logger.success(
            "A depot schedule has been completed.",
            {
                "depot_id": depot_id,
                "capacity": capacity,
                "total_impact": max_impact,
                "hours_used": total_duration,
                "selected_task_count": len(selected_tasks),
            },
        )
        processed_depots += 1

    if processed_depots == 0:
        reason = "No usable depot records were found in the API response."
        logger.error(reason)
        write_failure_report(reason, "Check the depot data and run the script again.")
        return 1

    write_report(report_lines)
    logger.success(
        "The scheduling run finished successfully.",
        {
            "processed_depots": processed_depots,
            "report_file": str(REPORT_FILE),
            "log_file": str(LOG_FILE),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
