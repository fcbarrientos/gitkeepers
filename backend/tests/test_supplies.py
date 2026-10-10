"""Supply items, stock movements, low-stock flags and the request list."""
from tests.api_case import VisitTestCase


class SupplyTests(VisitTestCase):
    def item(self, name="Paracetamol 500mg", unit="tablets", low=50, target=200):
        response = self.client.post("/api/v1/supplies", json={
            "name": name, "unit": unit, "low_stock_threshold": low, "target_level": target}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def move(self, item_id, kind, quantity, movement_date="2026-10-09", note=None):
        return self.client.post(f"/api/v1/supplies/{item_id}/movements", json={
            "kind": kind, "quantity": quantity, "movement_date": movement_date, "note": note}, headers=self.headers)

    def get(self, item_id):
        return self.client.get(f"/api/v1/supplies/{item_id}", headers=self.headers).json()

    def test_stock_is_the_sum_of_movements(self):
        item = self.item()
        self.assertEqual(self.move(item["id"], "received", 100).status_code, 201)
        self.assertEqual(self.move(item["id"], "distributed", 30).json()["quantity"], -30)
        self.assertEqual(self.move(item["id"], "adjusted", -5, note="count").status_code, 201)
        current = self.get(item["id"])
        self.assertEqual((current["on_hand"], current["low"]), (65, False))
        history = self.client.get(f"/api/v1/supplies/{item['id']}/movements", headers=self.headers).json()
        self.assertEqual(history["total"], 3)
        self.assertEqual(history["items"][0]["recorded_by_name"], "Test User")

    def test_cannot_take_more_than_is_in_stock(self):
        item = self.item()
        self.move(item["id"], "received", 10)
        for kind, quantity in (("distributed", 11), ("adjusted", -11)):
            response = self.move(item["id"], kind, quantity)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], ["quantity: only 10 tablets in stock"])
        self.assertEqual(self.get(item["id"])["on_hand"], 10)

    def test_rejects_bad_movements(self):
        item = self.item()
        self.assertEqual(self.move(item["id"], "received", 0).json()["detail"], ["quantity: must be more than 0"])
        self.assertEqual(self.move(item["id"], "adjusted", 0).json()["detail"], ["quantity: an adjustment cannot be 0"])
        self.assertEqual(self.move(item["id"], "received", 5, movement_date="2026-10-11").json()["detail"],
                         ["movement_date: cannot be in the future"])
        self.assertEqual(self.move("nope", "received", 5).status_code, 404)

    def test_low_stock_and_request_list(self):
        low = self.item(name="ORS sachets", unit="sachets", low=50, target=200)
        self.move(low["id"], "received", 40)
        ok = self.item(name="Iron tablets")
        self.move(ok["id"], "received", 500)
        self.assertTrue(self.get(low["id"])["low"])
        request = self.client.get("/api/v1/supplies/request-list", headers=self.headers).json()
        self.assertEqual([(r["name"], r["request_quantity"]) for r in request], [("ORS sachets", 160)])

    def test_item_rules(self):
        self.item()
        duplicate = self.client.post("/api/v1/supplies", json={
            "name": "paracetamol 500MG", "unit": "tablets", "low_stock_threshold": 1, "target_level": 2},
            headers=self.headers)
        self.assertEqual(duplicate.status_code, 409)
        bad = self.client.post("/api/v1/supplies", json={
            "name": "Gauze", "unit": "rolls", "low_stock_threshold": 20, "target_level": 10}, headers=self.headers)
        self.assertEqual(bad.json()["detail"], ["target_level: must be at least the low-stock level"])

    def test_update_and_deactivate(self):
        item = self.item()
        response = self.client.patch(f"/api/v1/supplies/{item['id']}", json={"low_stock_threshold": 5, "active": False},
                                     headers=self.headers)
        self.assertEqual((response.json()["low_stock_threshold"], response.json()["active"]), (5, False))
        self.assertEqual(self.client.get("/api/v1/supplies", headers=self.headers).json(), [])
        self.assertEqual(len(self.client.get("/api/v1/supplies?include_inactive=true", headers=self.headers).json()), 1)
