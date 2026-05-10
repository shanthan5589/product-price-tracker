from decimal import Decimal
from difflib import SequenceMatcher
import re

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Max, Min, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import EmailAuthenticationForm, RegisterForm
from .models import AlertRule, PriceRecord, Product
from .ml.predict import predict_next_price

# =========================
# AUTH HELPERS
# =========================
def _generate_unique_username(email):
    base = re.sub(r"[^a-z0-9]+", "", email.split("@")[0].lower())
    base = (base or "user")[:20]

    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        suffix = str(counter)
        username = f"{base[:30 - len(suffix)]}{suffix}"
        counter += 1
    return username


def email_login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = EmailAuthenticationForm(request, data=request.POST or None)

    if request.method == "POST":
        email = (request.POST.get("username") or "").strip().lower()
        password = request.POST.get("password") or ""
        next_url = request.POST.get("next") or request.GET.get("next") or "home"

        user_obj = User.objects.filter(email__iexact=email).first()
        if user_obj is None:
            messages.error(request, "No account found with this email.")
            return render(request, "tracker/login.html", {"form": form, "next": next_url})

        user = authenticate(request, username=user_obj.username, password=password)
        if user is not None:
            login(request, user)
            return redirect(next_url)

        messages.error(request, "Invalid email or password.")

    return render(request, "tracker/login.html", {"form": form, "next": request.GET.get("next", "")})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = RegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password1"]

        username = _generate_unique_username(email)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        login(request, user)
        messages.success(request, "Your account has been created successfully.")
        return redirect("home")

    return render(request, "tracker/register.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


# =========================
# API
# =========================
def healthcheck(request):
    return HttpResponse("ok", content_type="text/plain")


def predict_price_view(request, product_id):
    result = predict_next_price(product_id)
    return JsonResponse(result)


# =========================
# SEARCH HELPERS
# =========================
def _normalize(text):
    return " ".join((text or "").strip().lower().split())


def _candidate_text(product):
    parts = [
        product.name,
        product.brand,
        product.category,
        getattr(product.source, "name", ""),
        getattr(product.source, "slug", ""),
    ]
    return _normalize(" ".join(part for part in parts if part))


def _search_score(query, product):
    q = _normalize(query)
    if not q:
        return 0.0

    candidate = _candidate_text(product)
    if not candidate:
        return 0.0

    return SequenceMatcher(None, q, candidate).ratio()


# =========================
# HOME VIEW
# =========================
def home(request):
    query = (request.GET.get("q") or "").strip()
    selected_category = (request.GET.get("category") or "all").strip()

    products_qs = (
        Product.objects.select_related("source")
        .prefetch_related("price_records")
        .filter(is_active=True)
    )

    if selected_category.lower() != "all":
        products_qs = products_qs.filter(category__iexact=selected_category)

    all_products = list(products_qs.order_by("category", "name"))

    if query:
        filtered_products = [
            p for p in all_products
            if query.lower() in (p.name or "").lower()
            or query.lower() in (p.brand or "").lower()
            or query.lower() in (p.category or "").lower()
        ]
    else:
        filtered_products = all_products

    paginator = Paginator(filtered_products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    products = list(page_obj.object_list)

    best_deal_product = None
    best_drop = Decimal("0")

    for product in products:
        history = list(product.price_records.order_by("-recorded_at")[:2])

        product.latest_price = None
        product.price_drop_amount = None
        product.is_best_deal = False

        if history:
            product.latest_price = history[0].price

        if len(history) >= 2:
            drop = history[1].price - history[0].price
            if drop > 0:
                product.price_drop_amount = drop
                if drop > best_drop:
                    best_drop = drop
                    best_deal_product = product

    if best_deal_product:
        best_deal_product.is_best_deal = True

    return render(request, "tracker/home.html", {
        "products": products,
        "page_obj": page_obj,
        "best_deal_product": best_deal_product,
    })


# =========================
# PRODUCT DETAIL
# =========================
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("source").prefetch_related(
            Prefetch("price_records", queryset=PriceRecord.objects.order_by("recorded_at")),
            Prefetch("alerts", queryset=AlertRule.objects.order_by("-is_active")),
        ),
        pk=pk,
    )

    price_records = list(product.price_records.all())

    labels = [r.recorded_at.strftime("%d %b") for r in price_records]
    prices = [float(r.price) for r in price_records]

    stats = PriceRecord.objects.filter(product=product).aggregate(
        min_price=Min("price"),
        max_price=Max("price"),
        avg_price=Avg("price"),
    )

    current_price = price_records[-1].price if price_records else None

    price_change_percent = None
    price_direction = "stable"
    if len(price_records) >= 2:
        first = float(price_records[0].price)
        last = float(price_records[-1].price)
        if first > 0:
            price_change_percent = ((last - first) / first) * 100
            price_direction = "down" if last < first else "up" if last > first else "stable"

    cache_key = f"prediction_{product.id}"
    pred = cache.get(cache_key)
    if pred is None:
        try:
            pred = predict_next_price(product.id)
            cache.set(cache_key, pred, timeout=3600)
        except Exception:
            pred = {}
    predicted_price = pred.get("predicted_price")
    decision = pred.get("decision")

    return render(request, "tracker/product_detail.html", {
        "product": product,
        "labels": labels,
        "prices": prices,
        "min_price": stats["min_price"],
        "max_price": stats["max_price"],
        "avg_price": stats["avg_price"],
        "current_price": current_price,
        "predicted_price": predicted_price,
        "decision": decision,
        "price_change_percent": price_change_percent,
        "price_direction": price_direction,
    })


# =========================
# ALERTS
# =========================
@login_required(login_url="login")
def alerts_dashboard(request):
    alerts = (
        AlertRule.objects
        .filter(user=request.user)
        .select_related("product")
        .order_by("-is_active", "target_price")
    )

    for alert in alerts:
        latest_price = (
            PriceRecord.objects
            .filter(product=alert.product)
            .order_by("-recorded_at")
            .values_list("price", flat=True)
            .first()
        )
        alert.current_price = latest_price
        alert.triggered = bool(
            latest_price is not None and alert.target_price is not None and latest_price <= alert.target_price
        )

    products = Product.objects.all().order_by("name")

    return render(request, "tracker/alerts.html", {
        "alerts": alerts,
        "products": products
    })


@login_required(login_url="login")
def create_alert(request):
    if request.method != "POST":
        return redirect("home")

    product_id = request.POST.get("product")
    target_price = request.POST.get("target_price")

    product = get_object_or_404(Product, pk=product_id)

    if not target_price:
        messages.error(request, "Please enter a target price.")
        return redirect("product_detail", pk=product.pk)

    email = (request.user.email or "").strip()
    if not email:
        messages.error(request, "No email is saved in your account.")
        return redirect("product_detail", pk=product.pk)

    AlertRule.objects.create(
        user=request.user,
        product=product,
        email=email,
        target_price=target_price,
        is_active=True
    )

    messages.success(request, f"Alert created for {product.name}.")
    return redirect("product_detail", pk=product.pk)


@login_required(login_url="login")
def delete_alert(request, pk):
    alert = get_object_or_404(AlertRule, pk=pk, user=request.user)
    product_pk = alert.product_id

    if request.method == "POST":
        alert.delete()
        messages.success(request, "Alert deleted.")

    return redirect("product_detail", pk=product_pk)
