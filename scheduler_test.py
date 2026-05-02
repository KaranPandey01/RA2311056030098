import io
import os
import unittest
from unittest.mock import Mock, patch
import requests

import scheduler
from scheduler import VehicleTask, solve_knapsack


class TestScheduler(unittest.TestCase):
    def test_solve_knapsack_picks_best_tasks(self):
        tasks = [
            VehicleTask("A", 2, 6),
            VehicleTask("B", 2, 10),
            VehicleTask("C", 3, 12),
        ]

        max_impact, total_duration, selected = solve_knapsack(tasks, 4)

        self.assertEqual(max_impact, 16)
        self.assertEqual(total_duration, 4)
        self.assertEqual([t.task_id for t in selected], ["A", "B"])

    def test_fetch_api_data_success(self):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"depots": []}

        with patch("scheduler.requests.get", return_value=mock_response) as mock_get:
            result = scheduler.fetch_api_data("http://example.com", "token123")

        self.assertEqual(result, {"depots": []})
        mock_get.assert_called_once_with(
            "http://example.com",
            headers={"Authorization": "Bearer token123"},
            timeout=10,
        )

    def test_fetch_api_data_request_error(self):
        with patch(
            "scheduler.requests.get",
            side_effect=requests.exceptions.RequestException("boom"),
        ), patch("sys.stdout", new_callable=io.StringIO) as fake_out:
            result = scheduler.fetch_api_data("http://example.com", "token123")

        self.assertEqual(result, {})
        self.assertIn("Error fetching data", fake_out.getvalue())

    def test_main_without_api_token(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as fake_out:
            scheduler.main()

        self.assertIn("API_TOKEN environment variable is not set", fake_out.getvalue())

    def test_main_happy_path(self):
        fake_depots = {"depots": [{"ID": "D1", "MechanicHours": 4}]}
        fake_vehicles = {
            "vehicles": [
                {"TaskID": "A", "Duration": 2, "Impact": 6},
                {"TaskID": "B", "Duration": 2, "Impact": 10},
                {"TaskID": "C", "Duration": 3, "Impact": 12},
            ]
        }

        with patch.dict(os.environ, {"API_TOKEN": "token123"}, clear=True), patch(
            "scheduler.fetch_api_data", side_effect=[fake_depots, fake_vehicles]
        ), patch("sys.stdout", new_callable=io.StringIO) as fake_out:
            scheduler.main()

        output = fake_out.getvalue()
        self.assertIn("Found 1 depots and 3 vehicle tasks", output)
        self.assertIn("Total Impact Score: 16", output)
        self.assertIn("TaskID: A", output)
        self.assertIn("TaskID: B", output)


if __name__ == "__main__":
    unittest.main()
