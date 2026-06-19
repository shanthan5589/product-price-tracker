from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AlertRule, MarketplaceSource, PriceRecord, Product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_source(**kwargs):
    defaults = {"name": "Test Market", "slug": "test-market", "base_url": "https://example.com"}
    defaults.update(kwargs)
    return MarketplaceSource.objects.create(**defaults)


def make_product(source, **kwargs):
    defaults = {
        "name": "Test Phone",
        "brand": "TestBrand",
        "category": "mobiles",
        "source_url": "https://example.com/product/1",
        "external_id": "test-ext-1",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Product.objects.create(source=source, **defaults)


def make_price(product, source, price="999.00", **kwargs):
    return PriceRecord.objects.create(
        product=product, source=source, price=Decimal(price), **kwargs
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class ModelStrTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.product = make_product(self.source)

    def test_marketplace_source_str(self):
        self.assertEqual(str(self.source), "Test Market")

    def test_product_str(self):
        self.assertEqual(str(self.product), "Test Phone")

    def test_price_record_str(self):
        pr = make_price(self.product, self.source)
        self.assertIn("Test Phone", str(pr))

    def test_alert_rule_str(self):
        user = User.objects.create_user("u1", "u1@test.com", "pw")
        alert = AlertRule.objects.create(
            user=user,
            product=self.product,
            target_price=Decimal("800.00"),
            email="u1@test.com",
        )
        text = str(alert)
        self.assertIn("Test Phone", text)
        self.assertIn("800", text)


# ---------------------------------------------------------------------------
# Healthcheck
# ---------------------------------------------------------------------------

class HealthCheckTest(TestCase):
    def test_returns_ok(self):
        resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")


# ---------------------------------------------------------------------------
# Home view
# ---------------------------------------------------------------------------

class HomeViewTests(TestCase):
    def setUp(self):
        self.source = make_source()

    def test_home_empty_db(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_home_shows_active_products(self):
        p = make_product(self.source)
        make_price(p, self.source, "500.00")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test Phone")

    def test_home_hides_inactive_products(self):
        make_product(self.source, name="Hidden Phone", external_id="ext-hidden", is_active=False)
        resp = self.client.get("/")
        self.assertNotContains(resp, "Hidden Phone")

    def test_search_filters_by_name(self):
        make_product(self.source, name="Galaxy S24", brand="Samsung", external_id="gal-1")
        make_product(self.source, name="iPhone 15",  brand="Apple",   external_id="iph-1")
        resp = self.client.get("/?q=galaxy")
        self.assertContains(resp, "Galaxy S24")
        self.assertNotContains(resp, "iPhone 15")

    def test_search_filters_by_brand(self):
        make_product(self.source, name="Laptop A", brand="Samsung", external_id="lap-s")
        make_product(self.source, name="Laptop B", brand="Apple",   external_id="lap-a")
        resp = self.client.get("/?q=apple")
        self.assertContains(resp, "Laptop B")
        self.assertNotContains(resp, "Laptop A")

    def test_category_filter(self):
        make_product(self.source, name="Laptop A",  category="laptops", external_id="lap-1")
        make_product(self.source, name="Phone B",   category="mobiles", external_id="mob-1")
        resp = self.client.get("/?category=laptops")
        self.assertContains(resp, "Laptop A")
        self.assertNotContains(resp, "Phone B")


# ---------------------------------------------------------------------------
# Product detail view
# ---------------------------------------------------------------------------

class ProductDetailViewTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.product = make_product(self.source)

    @patch("tracker.views.predict_next_price", return_value={"predicted_price": 450.0, "decision": "BUY"})
    def test_detail_with_price_history(self, _mock):
        make_price(self.product, self.source, "500.00")
        make_price(self.product, self.source, "480.00")
        url = reverse("product_detail", kwargs={"pk": self.product.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test Phone")

    @patch("tracker.views.predict_next_price", return_value={})
    def test_detail_no_prices(self, _mock):
        url = reverse("product_detail", kwargs={"pk": self.product.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_detail_404_on_missing_product(self):
        url = reverse("product_detail", kwargs={"pk": 99999})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class AuthViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    # --- login ---

    def test_login_page_loads(self):
        resp = self.client.get("/login/")
        self.assertEqual(resp.status_code, 200)

    def test_login_valid_credentials(self):
        resp = self.client.post("/login/", {"username": "test@example.com", "password": "testpass123"})
        self.assertRedirects(resp, "/", fetch_redirect_response=False)

    def test_login_wrong_password(self):
        resp = self.client.post("/login/", {"username": "test@example.com", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid email or password")

    def test_login_unknown_email(self):
        resp = self.client.post("/login/", {"username": "nobody@example.com", "password": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No account found")

    def test_authenticated_user_redirected_from_login(self):
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/login/")
        self.assertRedirects(resp, "/", fetch_redirect_response=False)

    # --- register ---

    def test_register_page_loads(self):
        resp = self.client.get("/register/")
        self.assertEqual(resp.status_code, 200)

    def test_register_valid(self):
        resp = self.client.post("/register/", {
            "email": "new@example.com",
            "password1": "securepass123",
            "password2": "securepass123",
        })
        self.assertRedirects(resp, "/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())

    def test_register_password_mismatch(self):
        resp = self.client.post("/register/", {
            "email": "new2@example.com",
            "password1": "pass1",
            "password2": "pass2",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Passwords do not match")

    def test_register_duplicate_email(self):
        resp = self.client.post("/register/", {
            "email": "test@example.com",
            "password1": "securepass123",
            "password2": "securepass123",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")

    def test_authenticated_user_redirected_from_register(self):
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/register/")
        self.assertRedirects(resp, "/", fetch_redirect_response=False)

    # --- logout ---

    def test_logout_redirects_to_login(self):
        self.client.login(username="testuser", password="testpass123")
        resp = self.client.get("/logout/")
        self.assertRedirects(resp, "/login/", fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Alert views
# ---------------------------------------------------------------------------

class AlertViewTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.product = make_product(self.source)
        self.user = User.objects.create_user(
            username="alertuser",
            email="alert@example.com",
            password="testpass123",
        )
        self.client.login(username="alertuser", password="testpass123")

    def test_alerts_dashboard_requires_login(self):
        self.client.logout()
        resp = self.client.get("/alerts/")
        self.assertRedirects(resp, "/login/?next=/alerts/", fetch_redirect_response=False)

    def test_alerts_dashboard_loads(self):
        resp = self.client.get("/alerts/")
        self.assertEqual(resp.status_code, 200)

    def test_create_alert(self):
        resp = self.client.post("/create-alert/", {
            "product": self.product.pk,
            "target_price": "450.00",
        })
        self.assertRedirects(resp, f"/product/{self.product.pk}/", fetch_redirect_response=False)
        self.assertTrue(
            AlertRule.objects.filter(user=self.user, product=self.product, target_price=Decimal("450.00")).exists()
        )

    def test_create_alert_missing_price(self):
        resp = self.client.post("/create-alert/", {"product": self.product.pk, "target_price": ""})
        self.assertRedirects(resp, f"/product/{self.product.pk}/", fetch_redirect_response=False)
        self.assertFalse(AlertRule.objects.filter(user=self.user).exists())

    def test_create_alert_requires_login(self):
        self.client.logout()
        resp = self.client.post("/create-alert/", {"product": self.product.pk, "target_price": "450.00"})
        self.assertRedirects(resp, "/login/?next=/create-alert/", fetch_redirect_response=False)

    def test_delete_alert(self):
        alert = AlertRule.objects.create(
            user=self.user,
            product=self.product,
            email="alert@example.com",
            target_price=Decimal("500.00"),
        )
        resp = self.client.post(f"/delete-alert/{alert.pk}/")
        self.assertRedirects(resp, f"/product/{self.product.pk}/", fetch_redirect_response=False)
        self.assertFalse(AlertRule.objects.filter(pk=alert.pk).exists())

    def test_delete_alert_another_users_alert_returns_404(self):
        other = User.objects.create_user("other", "other@test.com", "pw")
        alert = AlertRule.objects.create(
            user=other,
            product=self.product,
            email="other@test.com",
            target_price=Decimal("500.00"),
        )
        resp = self.client.post(f"/delete-alert/{alert.pk}/")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Predict view
# ---------------------------------------------------------------------------

class PredictViewTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.product = make_product(self.source)

    @patch("tracker.views.predict_next_price", return_value={"predicted_price": 450.0, "decision": "BUY"})
    def test_predict_returns_json(self, _mock):
        url = reverse("predict_price", kwargs={"product_id": self.product.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("predicted_price", data)
        self.assertIn("decision", data)
        self.assertEqual(data["predicted_price"], 450.0)


# ---------------------------------------------------------------------------
# RegisterForm unit tests
# ---------------------------------------------------------------------------

class RegisterFormTests(TestCase):
    def _form(self, email, p1, p2):
        from .forms import RegisterForm
        return RegisterForm({"email": email, "password1": p1, "password2": p2})

    def test_valid_form(self):
        self.assertTrue(self._form("a@b.com", "abc123", "abc123").is_valid())

    def test_password_mismatch(self):
        form = self._form("a@b.com", "abc123", "xyz789")
        self.assertFalse(form.is_valid())
        self.assertIn("Passwords do not match", str(form.errors))

    def test_duplicate_email(self):
        User.objects.create_user("u", "a@b.com", "pw")
        form = self._form("a@b.com", "abc123", "abc123")
        self.assertFalse(form.is_valid())
        self.assertIn("already exists", str(form.errors))

    def test_invalid_email_format(self):
        form = self._form("not-an-email", "abc123", "abc123")
        self.assertFalse(form.is_valid())
