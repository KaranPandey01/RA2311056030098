import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

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

    def _write(self, level: str, message: str, context: Dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def info(self, message: str, context: Dict[str, Any] | None = None) -> None:
        self._write("INFO", message, context)

    def warning(self, message: str, context: Dict[str, Any] | None = None) -> None:
        self._write("WARNING", message, context)

    def error(self, message: str, context: Dict[str, Any] | None = None) -> None:
        self._write("ERROR", message, context)

    def success(self, message: str, context: Dict[str, Any] | None = None) -> None:
        self._write("SUCCESS", message, context)


@dataclass(frozen=True)
class VehicleTask:
    task_id: str
    duration: int
    impact: int


def write_report(lines: List[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_failure_report(reason: str) -> None:
    lines = [
        "Vehicle Maintenance Scheduling Output",
        "=" * 50,
        "Run Status: FAILED",
        f"Reason: {reason}",
        "",
        'PowerShell example: $env:API_TOKEN = "real-token-here"',
        "Then run: python .\\scheduler.py",
    ]
    write_report(lines)


def fetch_api_data(url: str, token: str, logger: LoggingMiddleware) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token.strip()}"}
    response = None

    logger.info("Sending API request", {"url": url})

    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(
            "Received API response",
            {"url": url, "status_code": response.status_code},
        )

        if response.status_code == 401:
            logger.error(
                "Unauthorized API request",
                {"url": url, "reason": "API token is invalid or expired"},
            )
            return {}

        response.raise_for_status()
        payload = response.json()
        logger.success("Parsed API response successfully", {"url": url})
        return payload

    except requests.exceptions.Timeout:
        logger.error("API request timed out", {"url": url})
    except requests.exceptions.RequestException as exc:
        logger.error("API request failed", {"url": url, "error": str(exc)})
    except ValueError:
        body = response.text if response is not None else "<no response>"
        logger.error(
            "API response was not valid JSON",
            {"url": url, "response_body": body[:500]},
        )

    return {}


def solve_knapsack(
    tasks: List[VehicleTask],
    capacity: int,
    logger: LoggingMiddleware,
) -> Tuple[int, int, List[VehicleTask]]:
    logger.info(
        "Starting knapsack calculation",
        {"task_count": len(tasks), "capacity": capacity},
    )

    if capacity <= 0 or not tasks:
        logger.warning(
            "Knapsack skipped due to empty tasks or non-positive capacity",
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
        "Knapsack calculation completed",
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
            logger.warning("Skipping vehicle with missing fields", {"vehicle": vehicle})
            continue

        try:
            task = VehicleTask(
                task_id=str(vehicle["TaskID"]),
                duration=int(vehicle["Duration"]),
                impact=int(vehicle["Impact"]),
            )
            tasks.append(task)
        except (TypeError, ValueError):
            logger.warning("Skipping vehicle with invalid field types", {"vehicle": vehicle})

    logger.info("Finished parsing vehicle tasks", {"valid_task_count": len(tasks)})
    return tasks


def build_depot_report(
    depot_id: Any,
    capacity: int,
    max_impact: int,
    total_duration: int,
    selected_tasks: List[VehicleTask],
) -> List[str]:
    lines = [
        f"Depot ID: {depot_id}",
        f"Available Mechanic Hours: {capacity}",
        f"Total Impact Score: {max_impact}",
        f"Total Hours Used: {total_duration}/{capacity}",
        f"Number of Tasks Selected: {len(selected_tasks)}",
        "Selected Task Details:",
    ]

    if selected_tasks:
        for task in selected_tasks:
            lines.append(
                f"  - TaskID: {task.task_id} "
                f"(Duration: {task.duration}, Impact: {task.impact})"
            )
    else:
        lines.append("  - No tasks scheduled.")

    lines.append("-" * 50)
    return lines


def main() -> int:
    logger = LoggingMiddleware(LOG_FILE)
    logger.info(
        "Vehicle scheduling run started",
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
        reason = "API_TOKEN is missing or still set to a placeholder value."
        logger.error(reason)
        write_failure_report(reason)
        return 1

    depot_data = fetch_api_data(DEPOT_API_URL, api_token, logger)
    if not depot_data or "depots" not in depot_data or not isinstance(depot_data["depots"], list):
        reason = "Could not fetch or parse depot data."
        logger.error(reason, {"payload": depot_data})
        write_failure_report(reason)
        return 1

    vehicle_data = fetch_api_data(VEHICLES_API_URL, api_token, logger)
    if not vehicle_data or "vehicles" not in vehicle_data or not isinstance(vehicle_data["vehicles"], list):
        reason = "Could not fetch or parse vehicle data."
        logger.error(reason, {"payload": vehicle_data})
        write_failure_report(reason)
        return 1

    tasks = parse_vehicle_tasks(vehicle_data, logger)
    if not tasks:
        reason = "No valid vehicle tasks were returned by the API."
        logger.error(reason)
        write_failure_report(reason)
        return 1

    depots = depot_data["depots"]
    report_lines = [
        "Vehicle Maintenance Scheduling Output",
        "=" * 50,
        f"Total Depots Received: {len(depots)}",
        f"Total Valid Vehicle Tasks Received: {len(tasks)}",
        "-" * 50,
    ]

    processed_depots = 0

    for depot in depots:
        depot_id = depot.get("ID")
        raw_capacity = depot.get("MechanicHours")

        if depot_id is None or raw_capacity is None:
            logger.warning("Skipping depot with missing fields", {"depot": depot})
            continue

        try:
            capacity = int(raw_capacity)
        except (TypeError, ValueError):
            logger.warning("Skipping depot with invalid MechanicHours", {"depot": depot})
            continue

        logger.info(
            "Calculating depot schedule",
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
            "Depot schedule completed",
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
        reason = "No valid depots were available to process."
        logger.error(reason)
        write_failure_report(reason)
        return 1

    write_report(report_lines)
    logger.success(
        "Vehicle scheduling run completed",
        {
            "processed_depots": processed_depots,
            "report_file": str(REPORT_FILE),
            "log_file": str(LOG_FILE),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
