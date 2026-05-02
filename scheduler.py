import os
import requests
from typing import List, Dict, Any, Tuple

# API endpoints
DEPOT_API_URL = "http://20.207.122.201/evaluation-service/depots"
VEHICLES_API_URL = "http://20.207.122.201/evaluation-service/vehicles"


class VehicleTask:
    def __init__(self, task_id: str, duration: int, impact: int):
        self.task_id = task_id
        self.duration = duration
        self.impact = impact

    def __repr__(self) -> str:
        return f"Task(id={self.task_id}, duration={self.duration}, impact={self.impact})"


def fetch_api_data(url: str, token: str) -> Dict[str, Any]:#test function 1
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {url}: {e}")
    except requests.exceptions.JSONDecodeError:
        print(f"Error decoding JSON from {url}. Response: {response.text}")
    return {}


def solve_knapsack(tasks: List[VehicleTask], capacity: int) -> Tuple[int, int, List[VehicleTask]]:#test function 2
    
    n = len(tasks)
    dp = [[0 for _ in range(capacity + 1)] for _ in range(n + 1)]

    for i in range(1, n + 1):
        task_duration = tasks[i - 1].duration
        task_impact = tasks[i - 1].impact
        for w in range(capacity + 1):
            if task_duration > w:
                dp[i][w] = dp[i - 1][w]
            else:
                dp[i][w] = max(dp[i - 1][w], dp[i - 1][w - task_duration] + task_impact)

    max_impact = dp[n][capacity]
    selected_tasks = []
    total_duration = 0
    w = capacity
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            task = tasks[i - 1]
            selected_tasks.append(task)
            total_duration += task.duration
            w -= task.duration

    selected_tasks.reverse()
    return max_impact, total_duration, selected_tasks


def main(): #test function 3
    api_token = os.getenv("API_TOKEN")
    if not api_token:
        print("Error: The API_TOKEN environment variable is not set.")
        print("Please set it to your authentication token and run the script again.")
        print('Example: export API_TOKEN="your-token"')
        return

    print("Fetching depot data...")
    depot_data = fetch_api_data(DEPOT_API_URL, api_token)
    if not depot_data or "depots" not in depot_data:
        print("Could not fetch or parse depot data. Exiting.")
        return

    print("Fetching vehicle task data...")
    vehicle_data = fetch_api_data(VEHICLES_API_URL, api_token)
    if not vehicle_data or "vehicles" not in vehicle_data:
        print("Could not fetch or parse vehicle data. Exiting.")
        return

    tasks = [
        VehicleTask(v["TaskID"], v["Duration"], v["Impact"])
        for v in vehicle_data.get("vehicles", [])
        if "TaskID" in v and "Duration" in v and "Impact" in v
    ]

    print(f"\nFound {len(depot_data.get('depots', []))} depots and {len(tasks)} vehicle tasks.")
    print("-" * 50)

    for depot in depot_data.get("depots", []):
        depot_id = depot.get("ID")
        capacity = depot.get("MechanicHours")

        if depot_id is None or capacity is None:
            print(f"Skipping invalid depot data: {depot}")
            continue

        print(f"\nCalculating schedule for Depot ID: {depot_id}")
        print(f"Available Mechanic Hours (Capacity): {capacity}")

        max_impact, total_duration, selected_tasks = solve_knapsack(tasks, capacity)

        print("\n  --- Optimal Schedule ---")
        print(f"  Total Impact Score: {max_impact}")
        print(f"  Total Hours Used: {total_duration}/{capacity}")
        print(f"  Number of Tasks Selected: {len(selected_tasks)}")
        print("  ------------------------")
        print("  Selected Task Details:")
        if selected_tasks:
            for task in selected_tasks:
                print(f"    - TaskID: {task.task_id} (Duration: {task.duration}, Impact: {task.impact})")
        else:
            print("    - No tasks scheduled.")
        print("-" * 50)


if __name__ == "__main__":
    main()

    
