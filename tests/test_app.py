import os
import re
import tempfile
import unittest

from app import create_app


class TaskFlowTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.path})
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.path)

    # -- helpers --
    def token(self):
        html = self.client.get("/").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, url, **data):
        data["csrf_token"] = self.token()
        return self.client.post(url, data=data, follow_redirects=True)

    def add(self, title="Write report", priority="medium", **extra):
        return self.post("/tasks", title=title, priority=priority, **extra)

    # -- tests --
    def test_empty_state(self):
        self.assertIn("No tasks yet", self.client.get("/").get_data(as_text=True))

    def test_create_task(self):
        page = self.add("Buy milk", "high", due_date="2030-01-01").get_data(as_text=True)
        self.assertIn("Buy milk", page)
        self.assertIn("Task added.", page)
        self.assertIn("2030-01-01", page)

    def test_title_required(self):
        page = self.add("   ").get_data(as_text=True)
        self.assertIn("Give the task a title.", page)

    def test_invalid_priority_and_date_rejected(self):
        page = self.add("X", "urgent", due_date="31/12/2030").get_data(as_text=True)
        self.assertIn("Choose low, medium or high priority.", page)
        self.assertIn("YYYY-MM-DD", page)
        self.assertNotIn("Task added.", page)

    def test_edit_task(self):
        self.add("Old title")
        self.post("/tasks/1/edit", title="New title", priority="low", description="notes", due_date="")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("New title", page)
        self.assertNotIn("Old title", page)

    def test_complete_and_reopen(self):
        self.add("Task A")
        self.post("/tasks/1/toggle")
        self.assertIn("Task A", self.client.get("/?status=completed").get_data(as_text=True))
        self.assertNotIn("Task A", self.client.get("/?status=active").get_data(as_text=True))
        self.post("/tasks/1/toggle")
        self.assertIn("Task A", self.client.get("/?status=active").get_data(as_text=True))

    def test_delete_task(self):
        self.add("Temp")
        page = self.post("/tasks/1/delete").get_data(as_text=True)
        self.assertIn("Task deleted.", page)
        self.assertEqual(self.client.get("/tasks/1/edit").status_code, 404)

    def test_filter_by_priority(self):
        self.add("High one", "high")
        self.add("Low one", "low")
        page = self.client.get("/?priority=high").get_data(as_text=True)
        self.assertIn("High one", page)
        self.assertNotIn("Low one", page)

    def test_default_sort_puts_high_first(self):
        self.add("Low one", "low")
        self.add("High one", "high")
        page = self.client.get("/").get_data(as_text=True)
        self.assertLess(page.index("High one"), page.index("Low one"))

    def test_unknown_filters_fall_back_safely(self):
        self.add("Still here")
        r = self.client.get("/?status=bogus&priority=bogus&sort=bogus; DROP TABLE tasks")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Still here", r.get_data(as_text=True))

    def test_csrf_required(self):
        r = self.client.post("/tasks", data={"title": "No token"})
        self.assertEqual(r.status_code, 400)

    def test_html_is_escaped(self):
        page = self.add("<script>alert(1)</script>").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
