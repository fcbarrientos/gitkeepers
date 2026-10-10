"""Serving the built frontend on the API's port."""
from unittest import mock

from core import config
from tests.api_case import ApiTestCase

INDEX = "<!doctype html><title>GitKeepers app</title>"


class FrontendServingTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        site = self.data_dir / "site"
        self.dist = site / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text(INDEX, encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
        (site / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
        patcher = mock.patch.object(config, "FRONTEND_DIST", self.dist)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_index_and_client_routes_serve_the_app(self):
        for path in ("/", "/patients/5", "/follow-ups?state=due"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("GitKeepers app", response.text)
            self.assertIn("text/html", response.headers["content-type"])

    def test_assets_are_served_and_missing_assets_are_404(self):
        response = self.client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("console.log", response.text)
        self.assertEqual(self.client.get("/assets/missing.js").status_code, 404)

    def test_api_paths_keep_json_errors(self):
        response = self.client.get("/api/v1/unknown")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertEqual(self.client.get("/api/v1/patients").status_code, 401)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_files_outside_dist_are_not_served(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
            self.assertNotIn("TOP SECRET", self.client.get(path).text, path)

    def test_without_a_build_nothing_is_served(self):
        with mock.patch.object(config, "FRONTEND_DIST", self.data_dir / "missing"):
            self.assertEqual(self.client.get("/").status_code, 404)
            self.assertEqual(self.client.get("/patients/5").status_code, 404)
